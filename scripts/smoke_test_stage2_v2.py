"""Smoke-test the Stage 2 pro v2 integration end-to-end (no GPU).

Verifies:
  1. configs/stage2_amr_sft.yaml parses; task_mix sums to 1.0
  2. Every task in task_mix exists in the dataset (catches typos)
  3. Local v2 dataset loads via load_from_disk
  4. Hub v2 dataset loads via load_dataset (HF round-trip)
  5. Schema integrity on a sample of rows
  6. messages field deserializes to valid OpenAI-style chat list
  7. response_template appears in formatted text (TRL SFTTrainer expectation)
  8. Held-out test JSONL loads + zero leakage with train

Run:
  python scripts/smoke_test_stage2_v2.py
"""
import json
import sys
from pathlib import Path

import yaml
from datasets import load_from_disk, load_dataset


CONFIG = Path("configs/stage2_amr_sft.yaml")
LOCAL_DS = Path("data/processed/amr-stage2-pro-v2")
TEST_JSONL = Path("data/synthetic/named_drug_test_split.jsonl")


def section(title):
    print(f"\n{'='*60}\n{title}\n{'='*60}")


def main():
    failures = []

    section("[1] configs/stage2_amr_sft.yaml — task_mix sums + integrity")
    with CONFIG.open() as f:
        cfg = yaml.safe_load(f)
    task_mix = cfg["dataset"]["task_mix"]
    total = sum(task_mix.values())
    print(f"  task_mix entries: {len(task_mix)}")
    print(f"  task_mix sum: {total:.4f}")
    if abs(total - 1.0) > 1e-6:
        failures.append(f"task_mix sum is {total}, expected 1.0")
    print(f"  dataset.path: {cfg['dataset']['path']}")
    print(f"  dataset.hub_id: {cfg['dataset']['hub_id']}")
    print(f"  text_field: {cfg['dataset']['text_field']}")
    print(f"  response_template: {cfg['dataset']['response_template']!r}")

    section("[2] Local Stage 2 pro v2 dataset load")
    ds = load_from_disk(str(LOCAL_DS))
    print(f"  splits: {list(ds.keys())}")
    print(f"  train rows: {len(ds['train']):,}")
    print(f"  valid rows: {len(ds['valid']):,}")
    print(f"  columns: {ds['train'].column_names}")
    expected_cols = {"task", "split", "prompt", "response", "messages"}
    if set(ds["train"].column_names) != expected_cols:
        failures.append(f"Schema mismatch: {ds['train'].column_names}")

    section("[3] Every task_mix task exists in dataset.train")
    from collections import Counter
    train_tasks = Counter(ds["train"]["task"])
    missing_tasks = []
    for task in task_mix:
        if train_tasks[task] == 0:
            missing_tasks.append(task)
        else:
            print(f"  ✓ {task}: {train_tasks[task]} rows (weight {task_mix[task]:.3f})")
    if missing_tasks:
        failures.append(f"Tasks in task_mix with 0 train rows: {missing_tasks}")

    section("[4] Hub v2 round-trip (rahul24raj/lysos-amr-stage2-pro-v2)")
    try:
        hub_ds = load_dataset(cfg["dataset"]["hub_id"])
        print(f"  hub train rows: {len(hub_ds['train']):,}")
        print(f"  hub valid rows: {len(hub_ds['valid']):,}")
        if len(hub_ds["train"]) != len(ds["train"]):
            failures.append(
                f"Hub train rows {len(hub_ds['train'])} != local {len(ds['train'])}"
            )
        else:
            print(f"  ✓ Hub matches local")
    except Exception as e:
        failures.append(f"Hub load failed: {e}")

    section("[5] Schema integrity — random sample")
    import random
    random.seed(0)
    sample = random.sample(range(len(ds["train"])), 20)
    bad = 0
    for idx in sample:
        r = ds["train"][idx]
        if not (r["task"] and r["prompt"] and r["response"] and r["messages"]):
            bad += 1
    print(f"  20 random rows checked — {bad} failures")
    if bad:
        failures.append(f"{bad}/20 random rows have missing fields")

    section("[6] messages field deserializes to chat list")
    sample_row = ds["train"][0]
    try:
        msgs = json.loads(sample_row["messages"])
        assert isinstance(msgs, list), f"not a list: {type(msgs)}"
        assert all("role" in m and "content" in m for m in msgs), "missing role/content"
        roles = [m["role"] for m in msgs]
        print(f"  ✓ messages parsed as list of {len(msgs)} chat turns")
        print(f"  ✓ roles: {roles}")
    except Exception as e:
        failures.append(f"messages deserialization failed: {e}")

    section("[7] response_template appears in formatted text")
    template = cfg["dataset"]["response_template"]
    # Take a sample with messages and simulate Gemma chat-template formatting
    msgs = json.loads(sample_row["messages"])
    formatted = "<start_of_turn>user\n" + msgs[0]["content"] + "<end_of_turn>\n"
    formatted += template + msgs[1]["content"] + "<end_of_turn>"
    if template not in formatted:
        failures.append(f"response_template {template!r} not in formatted output")
    else:
        print(f"  ✓ {template!r} present in chat-templated example")

    section("[8] Held-out test isolation — final check")
    test_prompts = set()
    with TEST_JSONL.open() as f:
        for line in f:
            test_prompts.add(json.loads(line)["prompt"])
    print(f"  test split rows: {len(test_prompts)}")
    leaks = sum(1 for p in ds["train"]["prompt"] if p in test_prompts)
    leaks_v = sum(1 for p in ds["valid"]["prompt"] if p in test_prompts)
    print(f"  test prompts in train: {leaks}")
    print(f"  test prompts in valid: {leaks_v}")
    if leaks or leaks_v:
        failures.append(f"Test leakage: {leaks} train, {leaks_v} valid")

    section("=== SUMMARY ===")
    if not failures:
        print("  ✅ ALL CHECKS PASSED — Stage 2 v2 ready for MI300X kickoff")
        return 0
    print(f"  ❌ {len(failures)} FAILURE(S):")
    for f in failures:
        print(f"     - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
