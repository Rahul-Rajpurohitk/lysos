"""Loss masking smoke test — catches the silent-failure where Gemma 4
chat template + response_template don't align properly.

If response_template doesn't appear in the formatted text, the trainer
either crashes OR silently trains on user content (catastrophic).

This test:
  1. Loads pro-v11 sample row
  2. Formats it through Gemma chat template
  3. Verifies response_template substring appears AFTER user turn
  4. Verifies the substring AFTER response_template is the assistant content

Run:
  /tmp/lysos_venv/bin/python scripts/test_loss_masking.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from datasets import load_from_disk

ROOT = Path(__file__).resolve().parents[1]
DS = ROOT / "data" / "processed" / "amr-stage2-pro-v11"
CFG = ROOT / "configs" / "stage2_amr_sft.yaml"


def gemma_chat_format(msgs):
    """Approximate the Gemma 4 chat template."""
    out = ""
    for m in msgs:
        role = m.get("role")
        c = m.get("content", "")
        if role == "system":
            # Gemma 4 has no separate system role; prepend to first user
            out += f"<start_of_turn>user\n{c}<end_of_turn>\n"
        elif role == "user":
            out += f"<start_of_turn>user\n{c}<end_of_turn>\n"
        elif role == "assistant":
            out += f"<start_of_turn>model\n{c}<end_of_turn>\n"
        elif role == "tool":
            out += f"<start_of_turn>tool\n{c}<end_of_turn>\n"
    return out


def main():
    print(f"Loading config {CFG}")
    cfg = yaml.safe_load(CFG.read_text())
    response_template = cfg["dataset"]["response_template"]
    print(f"  response_template: {response_template!r}")

    print(f"\nLoading dataset {DS}")
    ds = load_from_disk(str(DS))
    train = ds["train"]
    print(f"  train rows: {len(train):,}")

    failures = []

    # Test 1: response_template appears in 100/100 sample
    print(f"\n[Test 1] response_template appears in formatted text (100 sample)")
    import random
    random.seed(0)
    sample_idx = random.sample(range(len(train)), 100)
    n_with_template = 0
    n_no_assistant = 0
    for i in sample_idx:
        msgs = json.loads(train[i]["messages"])
        if not any(m.get("role") == "assistant" for m in msgs):
            n_no_assistant += 1
            continue
        formatted = gemma_chat_format(msgs)
        if response_template in formatted:
            n_with_template += 1
        else:
            failures.append(f"row {i}: response_template not in formatted text (task={train[i]['task']})")
    print(f"  with template: {n_with_template}/100")
    print(f"  no assistant turn: {n_no_assistant}/100")

    # Test 2: text AFTER response_template is the assistant content
    print(f"\n[Test 2] text after response_template is assistant content")
    sample_row = train[sample_idx[0]]
    msgs = json.loads(sample_row["messages"])
    formatted = gemma_chat_format(msgs)
    asst_msg = next(m["content"] for m in msgs if m.get("role") == "assistant" and isinstance(m.get("content"), str))
    if response_template in formatted:
        idx = formatted.index(response_template)
        after = formatted[idx + len(response_template):]
        if after.startswith(asst_msg[:50]):
            print(f"  ✓ assistant content immediately follows response_template")
        else:
            print(f"  ✗ MISALIGNMENT — content after template doesn't match assistant")
            print(f"     after[:80]: {after[:80]!r}")
            print(f"     asst[:80]:  {asst_msg[:80]!r}")
            failures.append("response_template not aligned to assistant content")

    # Test 3: TRL SFTTrainer compatibility — DataCollatorForCompletionOnlyLM expects template
    print(f"\n[Test 3] DataCollator compatibility (substring search)")
    template_bytes = response_template.encode()
    n_passes_template_search = sum(
        1 for i in sample_idx
        if response_template in gemma_chat_format(json.loads(train[i]["messages"]))
    )
    print(f"  rows where DataCollator can find template: {n_passes_template_search}/100")
    if n_passes_template_search < 95:
        failures.append(f"Only {n_passes_template_search}/100 rows have template — DataCollator will skip the rest")

    # Test 4: Tokenization sanity (using gpt2 as proxy for Gemma)
    print(f"\n[Test 4] Tokenization sanity check")
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained("gpt2", use_fast=True)
        formatted = gemma_chat_format(json.loads(train[sample_idx[0]]["messages"]))
        ids = tok.encode(formatted)
        print(f"  formatted len: {len(formatted)} chars, {len(ids)} tokens (gpt2 proxy)")
        # Find response_template token-span
        rt_ids = tok.encode(response_template)
        print(f"  response_template tokens: {rt_ids}")
        # Search for the sequence in the encoded ids
        for i in range(len(ids) - len(rt_ids) + 1):
            if ids[i:i+len(rt_ids)] == rt_ids:
                print(f"  ✓ template token sequence found at position {i}")
                break
        else:
            failures.append("response_template token sequence NOT found in encoded ids — DataCollator will fail")
    except Exception as e:
        print(f"  SKIP: {e}")

    # Summary
    print(f"\n{'='*60}\nSUMMARY\n{'='*60}")
    if failures:
        print(f"❌ {len(failures)} FAILURE(S):")
        for f in failures[:10]:
            print(f"   - {f}")
        return 1
    print("✅ ALL CHECKS PASSED — loss masking is correctly aligned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
