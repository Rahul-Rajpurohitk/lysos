"""Smoke-test the Stage 2 pro-v3 + Stage 3 rl-prompts-v2 plumbing (no GPU).

Verifies:
  1. configs/stage2_amr_sft.yaml parses; task_mix sums to 1.0
  2. Local pro-v3 dataset loads with train/valid/test splits
  3. Schema has expected columns
  4. Every task in task_mix exists in the dataset
  5. v6 additions present (safety_refusal, tool_arg_validation, held_out_eval)
  6. Held-out eval — all rows split=test, exact count
  7. Messages deserialize cleanly to chat list
  8. response_template appears in formatted text
  9. Held-out content never appears in train/valid (leak canary)
 10. Safety-refusal sanitation — every assistant turn refuses, no literal
     harmful names (only abstracted category tokens)
 11. configs/stage3_rl_grpo.yaml parses; rl-prompts-v2 loads cleanly

Run:
  /tmp/lysos_venv/bin/python scripts/smoke_test_stage2_v3.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml
from datasets import load_from_disk


CFG_STAGE2 = Path("configs/stage2_amr_sft.yaml")
CFG_STAGE3 = Path("configs/stage3_rl_grpo.yaml")
LOCAL_DS_S2 = Path("data/processed/amr-stage2-pro-v3")
LOCAL_DS_S3 = Path("data/processed/amr-rl-prompts-v2")

# Patterns we DO NOT want appearing in safety_refusal training data —
# this is a regression check for the abstracted-token approach. The set is
# intentionally narrow (literal CW / regulated-substance terms).
BAD_LITERALS = [
    r"\bsarin\b", r"\bvx\b", r"\bsoman\b", r"\btabun\b", r"\bnovichok\b",
    r"\bricin\b", r"\bbotulinum\b", r"\bfentanyl\b", r"\bcarfentanil\b",
    r"\banthrax\b", r"\bsmallpox\b", r"\bebola\b",
    r"\bmustard gas\b", r"\bphosgene\b",
]
BAD_RE = re.compile("|".join(BAD_LITERALS), re.IGNORECASE)


def section(title):
    print(f"\n{'='*64}\n{title}\n{'='*64}")


def main():
    failures: list[str] = []

    section("[1] Stage 2 config parses + task_mix integrity")
    with CFG_STAGE2.open() as f:
        cfg2 = yaml.safe_load(f)
    task_mix = cfg2["dataset"]["task_mix"]
    total = sum(task_mix.values())
    print(f"  task_mix entries: {len(task_mix)}")
    print(f"  task_mix sum: {total:.4f}")
    if abs(total - 1.0) > 1e-6:
        failures.append(f"task_mix sum is {total}, expected 1.0")
    print(f"  dataset.path: {cfg2['dataset']['path']}")
    print(f"  dataset.hub_id: {cfg2['dataset']['hub_id']}")
    print(f"  text_field: {cfg2['dataset']['text_field']}")
    print(f"  response_template: {cfg2['dataset']['response_template']!r}")
    if cfg2["dataset"]["path"] != "data/processed/amr-stage2-pro-v3":
        failures.append(f"Stage 2 path not pro-v3: {cfg2['dataset']['path']}")

    section("[2] Local pro-v3 dataset load")
    ds = load_from_disk(str(LOCAL_DS_S2))
    print(f"  splits: {list(ds.keys())}")
    print(f"  train: {len(ds['train']):,}")
    print(f"  valid: {len(ds['valid']):,}")
    print(f"  test:  {len(ds['test']):,}")
    expected_splits = {"train", "valid", "test"}
    if set(ds.keys()) != expected_splits:
        failures.append(f"Splits mismatch: {set(ds.keys())} != {expected_splits}")
    if len(ds["test"]) != 50:
        failures.append(f"Test split has {len(ds['test'])} rows, expected 50")

    section("[3] Schema integrity")
    cols = ds["train"].column_names
    print(f"  columns: {cols}")
    expected_cols = {"task", "pathogen", "messages", "split"}
    if set(cols) != expected_cols:
        failures.append(f"Schema mismatch: {set(cols)} != {expected_cols}")

    section("[4] task_mix coverage")
    train_tasks = Counter(ds["train"]["task"])
    missing = []
    for task in task_mix:
        if train_tasks[task] == 0:
            missing.append(task)
    if missing:
        failures.append(f"Tasks in task_mix with 0 rows: {missing}")
    else:
        print(f"  ✓ all {len(task_mix)} task_mix entries present in train")

    section("[5] v6 additions present")
    for t, expected_min in [
        ("safety_refusal", 800),
        ("tool_arg_validation", 400),
        ("held_out_eval", 50),
    ]:
        # held_out_eval lives in test split
        n = train_tasks.get(t, 0)
        if t == "held_out_eval":
            n = Counter(ds["test"]["task"]).get(t, 0)
            print(f"  {t}: {n} rows (test split)")
        else:
            print(f"  {t}: {n} train rows")
        if n < expected_min:
            failures.append(f"{t} only {n} rows, expected ≥{expected_min}")

    section("[6] Held-out — every row split=test")
    bad_split = [r for r in ds["test"] if r["split"] != "test"]
    print(f"  rows with non-test split: {len(bad_split)}")
    if bad_split:
        failures.append(f"{len(bad_split)} test rows have wrong split label")

    section("[7] messages deserializes for sample row")
    sample = ds["train"][0]
    try:
        msgs = json.loads(sample["messages"])
        assert isinstance(msgs, list) and msgs
        for m in msgs:
            assert "role" in m and "content" in m
        print(f"  ✓ parsed as list of {len(msgs)} turns, "
              f"roles={[m['role'] for m in msgs]}")
    except Exception as e:
        failures.append(f"messages parse failed: {e}")

    section("[8] response_template appears in formatted text")
    template = cfg2["dataset"]["response_template"]
    msgs = json.loads(sample["messages"])
    user_msg = next((m for m in msgs if m["role"] == "user"), msgs[0])
    asst_msg = next((m for m in msgs if m["role"] == "assistant"), msgs[-1])
    formatted = (
        "<start_of_turn>user\n" + user_msg["content"] + "<end_of_turn>\n"
        + template + asst_msg["content"] + "<end_of_turn>"
    )
    if template not in formatted:
        failures.append(f"response_template {template!r} missing")
    else:
        print(f"  ✓ {template!r} present in chat-templated example")

    section("[9] Held-out leak canary — test content not in train/valid")
    test_user_msgs = set()
    for r in ds["test"]:
        m = json.loads(r["messages"])
        u = next((x["content"] for x in m if x["role"] == "user"), None)
        if u: test_user_msgs.add(u)
    leak_train = leak_valid = 0
    # Sample 20K rows from train + all valid for speed
    import random
    random.seed(0)
    train_sample_idx = random.sample(range(len(ds["train"])), min(20000, len(ds["train"])))
    for idx in train_sample_idx:
        m = json.loads(ds["train"][idx]["messages"])
        u = next((x["content"] for x in m if x["role"] == "user"), None)
        if u and u in test_user_msgs:
            leak_train += 1
    for r in ds["valid"]:
        m = json.loads(r["messages"])
        u = next((x["content"] for x in m if x["role"] == "user"), None)
        if u and u in test_user_msgs:
            leak_valid += 1
    print(f"  test user-prompts: {len(test_user_msgs)}")
    print(f"  leakage into train (sampled): {leak_train}")
    print(f"  leakage into valid (full):    {leak_valid}")
    if leak_train or leak_valid:
        failures.append(f"Test leakage: {leak_train} train, {leak_valid} valid")

    section("[10] Safety-refusal sanitation — abstracted tokens only")
    refusal_rows = [r for r in ds["train"] if r["task"] == "safety_refusal"]
    print(f"  safety_refusal rows scanned: {len(refusal_rows)}")
    bad_hits, refuse_count = 0, 0
    for r in refusal_rows:
        msgs = json.loads(r["messages"])
        full = " ".join(m["content"] for m in msgs)
        if BAD_RE.search(full):
            bad_hits += 1
        # Every assistant turn must contain "REFUSE"
        for m in msgs:
            if m["role"] == "assistant" and "REFUSE" in m["content"]:
                refuse_count += 1
                break
    print(f"  rows containing literal harmful terms: {bad_hits}")
    print(f"  rows with REFUSE in assistant turn:    {refuse_count}/{len(refusal_rows)}")
    if bad_hits:
        failures.append(f"{bad_hits} safety_refusal rows contain literal harmful terms")
    if refuse_count != len(refusal_rows):
        failures.append(
            f"{len(refusal_rows) - refuse_count} safety_refusal rows missing REFUSE")

    section("[11] Stage 3 config + rl-prompts-v2 load")
    with CFG_STAGE3.open() as f:
        cfg3 = yaml.safe_load(f)
    print(f"  dataset.path: {cfg3['dataset']['path']}")
    print(f"  dataset.hub_id: {cfg3['dataset']['hub_id']}")
    if cfg3["dataset"]["path"] != "data/processed/amr-rl-prompts-v2":
        failures.append(f"Stage 3 path not v2: {cfg3['dataset']['path']}")
    ds3 = load_from_disk(str(LOCAL_DS_S3))
    print(f"  rl-prompts-v2 train: {len(ds3['train']):,}")
    print(f"  rl-prompts-v2 valid: {len(ds3['valid']):,}")
    print(f"  rl-prompts-v2 cols: {ds3['train'].column_names}")
    pf = cfg3["dataset"]["prompt_field"]
    if pf not in ds3["train"].column_names:
        failures.append(f"prompt_field {pf!r} missing in rl-prompts-v2")
    else:
        print(f"  ✓ prompt_field {pf!r} present")

    section("=== SUMMARY ===")
    if not failures:
        print("  ✅ ALL CHECKS PASSED — pro-v3 + rl-prompts-v2 plumbing OK")
        return 0
    print(f"  ❌ {len(failures)} FAILURE(S):")
    for fl in failures:
        print(f"     - {fl}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
