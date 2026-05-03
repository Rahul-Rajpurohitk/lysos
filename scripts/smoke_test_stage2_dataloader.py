"""Smoke-test the actual Stage 2 SFT data loader (no GPU, no training).

Builds the same multi-task weighted sampler the trainer will use, draws
a small batch, and verifies:
  1. Every weighted task in task_mix is reachable (no zero-prob bug)
  2. Task-mix sampling proportions match config weights at scale
  3. The 'messages' field deserializes cleanly to OpenAI-style chat
  4. SFTTrainer's chat-template + response-template chunking works on
     a sample row (catches mask-of-prompt-vs-response bugs)
  5. Bucketed token-length distribution per task type

Catches problems before MI300X kickoff so you don't burn $1.99/hr discovering
the data loader is misconfigured. ZERO GPU. ZERO model. Pure data plumbing.

Run:
  python scripts/smoke_test_stage2_dataloader.py
  python scripts/smoke_test_stage2_dataloader.py --n-samples 5000
"""
import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/stage2_amr_sft.yaml")
    ap.add_argument("--n-samples", type=int, default=2000,
                    help="Number of samples to draw from the weighted sampler")
    ap.add_argument("--tokenizer", default="gpt2",
                    help="Ungated tokenizer for sizing (gpt2 ~5pct denser than Gemma BPE)")
    args = ap.parse_args()

    failures = []
    print(f"Loading {args.config}...")
    cfg = yaml.safe_load(Path(args.config).read_text())
    task_mix = cfg["dataset"]["task_mix"]
    response_template = cfg["dataset"]["response_template"]
    max_seq_length = cfg["dataset"]["max_seq_length"]
    print(f"  {len(task_mix)} weighted task types")
    print(f"  response_template: {response_template!r}")
    print(f"  max_seq_length: {max_seq_length}")

    # Load dataset
    print(f"\nLoading dataset {cfg['dataset']['path']}...")
    from datasets import load_from_disk
    ds = load_from_disk(cfg["dataset"]["path"])
    train = ds["train"]
    print(f"  train rows: {len(train):,}")

    # ------------------------------------------------------------------
    # Check 1: every task in task_mix has rows in train
    # ------------------------------------------------------------------
    print(f"\n[1/5] Verifying every weighted task has data in train...")
    train_tasks = Counter(train["task"])
    missing = [t for t in task_mix if train_tasks[t] == 0]
    if missing:
        failures.append(f"Tasks with 0 rows: {missing}")
        print(f"  ❌ MISSING: {missing}")
    else:
        print(f"  ✓ all {len(task_mix)} tasks present")

    # ------------------------------------------------------------------
    # Check 2: build a weighted sampler matching the task_mix
    # ------------------------------------------------------------------
    print(f"\n[2/5] Building weighted sampler + drawing {args.n_samples} samples...")
    # Build per-task index lists
    task_idx = defaultdict(list)
    for i, t in enumerate(train["task"]):
        task_idx[t].append(i)

    # Weighted sampler: pick task by weight, then uniform within task
    task_names = list(task_mix.keys())
    task_weights = [task_mix[t] for t in task_names]

    rng = random.Random(0)
    sampled_task_counts = Counter()
    sampled_indices = []
    for _ in range(args.n_samples):
        task = rng.choices(task_names, weights=task_weights, k=1)[0]
        if not task_idx[task]:
            continue
        idx = rng.choice(task_idx[task])
        sampled_indices.append(idx)
        sampled_task_counts[task] += 1

    # Compare empirical vs config weights
    print(f"  empirical vs target weight (sum={sum(task_weights):.4f}):")
    print(f"  {'task':40s} {'config':>8s} {'empirical':>10s} {'delta':>8s}")
    max_drift = 0.0
    for t in task_names:
        config_w = task_mix[t]
        empirical = sampled_task_counts[t] / args.n_samples
        delta = empirical - config_w
        max_drift = max(max_drift, abs(delta))
        marker = "⚠" if abs(delta) > 0.005 else " "
        print(f"  {marker} {t:38s} {config_w:>8.4f} {empirical:>10.4f} {delta:>+8.4f}")
    print(f"\n  max drift: {max_drift:.4f}")
    if max_drift > 0.01:
        failures.append(f"Sampler drift {max_drift:.4f} exceeds 0.01")

    # ------------------------------------------------------------------
    # Check 3: messages field deserializes
    # ------------------------------------------------------------------
    print(f"\n[3/5] Verifying messages field on sampled rows...")
    bad_examples = []
    for idx in sampled_indices[:200]:
        row = train[idx]
        try:
            msgs = json.loads(row["messages"])
            assert isinstance(msgs, list) and len(msgs) >= 2
            assert all("role" in m and "content" in m for m in msgs)
        except Exception as exc:
            bad_examples.append((idx, row["task"], str(exc), str(row["messages"])[:200]))
    if bad_examples:
        failures.append(f"{len(bad_examples)}/200 rows had bad messages field")
        print(f"  ❌ {len(bad_examples)}/200 rows have bad messages")
        for idx, task, err, preview in bad_examples[:3]:
            print(f"    row {idx} ({task}): {err}")
            print(f"      messages: {preview}")
    else:
        print(f"  ✓ 200/200 sampled rows have valid messages")

    # ------------------------------------------------------------------
    # Check 4: SFTTrainer-style chat-template + response_template chunking
    # ------------------------------------------------------------------
    print(f"\n[4/5] Verifying response_template chunking on a sample...")
    sample = train[sampled_indices[0]]
    msgs = json.loads(sample["messages"])

    # Gemma chat template maps OpenAI roles to:
    #   user      -> <start_of_turn>user\n
    #   assistant -> <start_of_turn>model\n   (Gemma uses "model" not "assistant")
    role_map = {"user": "user", "assistant": "model", "system": "user"}
    formatted = ""
    for m in msgs:
        gemma_role = role_map.get(m["role"], m["role"])
        formatted += f"<start_of_turn>{gemma_role}\n{m['content']}<end_of_turn>\n"

    if response_template not in formatted:
        failures.append(f"response_template {response_template!r} not in formatted text")
        print(f"  ❌ template {response_template!r} not in formatted output")
    else:
        idx_user = formatted.find(msgs[0]["content"])
        idx_template = formatted.find(response_template)
        if idx_template > idx_user:
            print(f"  ✓ response_template appears AFTER user content (correct masking direction)")
        else:
            failures.append("response_template position wrong relative to user content")

    # Test chunked split — TRL's SFTTrainer collator splits on response_template
    parts = formatted.split(response_template, 1)
    if len(parts) == 2:
        prompt_part, response_part = parts
        print(f"  ✓ split into prompt({len(prompt_part)} chars) + response({len(response_part)} chars)")
    else:
        failures.append("response_template chunking produced wrong number of parts")

    # ------------------------------------------------------------------
    # Check 5: token length per task on the WEIGHTED sample
    # ------------------------------------------------------------------
    print(f"\n[5/5] Token-length on weighted batch (using {args.tokenizer})...")
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.tokenizer)

    by_task_lens = defaultdict(list)
    for idx in sampled_indices:
        row = train[idx]
        text = (row["prompt"] or "") + " " + (row["response"] or "")
        n = len(tok(text, add_special_tokens=False)["input_ids"])
        by_task_lens[row["task"]].append(n)

    print(f"  {'task':40s} {'n':>5s} {'p50':>5s} {'max':>5s}")
    over_max = 0
    for t in sorted(by_task_lens):
        vals = sorted(by_task_lens[t])
        n = len(vals)
        p50 = vals[n // 2]
        mx = vals[-1]
        if mx > max_seq_length:
            over_max += 1
        marker = "⚠" if mx > max_seq_length * 0.9 else " "
        print(f"  {marker} {t:38s} {n:>5d} {p50:>5d} {mx:>5d}")
    if over_max:
        failures.append(f"{over_max} task types had max-token rows over max_seq_length")

    # ------------------------------------------------------------------
    print(f"\n{'='*70}")
    if failures:
        print(f"❌ {len(failures)} FAILURES:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print(f"✅ ALL CHECKS PASSED — Stage 2 dataloader ready for trainer")
    print(f"   Sample weighted-batch reproduces task_mix proportions to within {max_drift:.4f}")
    print(f"   (config sum = {sum(task_weights):.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
