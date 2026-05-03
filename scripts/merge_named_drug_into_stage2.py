"""Merge data/synthetic/named_drug_examples.jsonl into the Stage 2 pro dataset.

Carves a stratified 50-entry held-out test split (proportional across task types)
and appends the remaining ~310 entries into the train split of a new
`amr-stage2-pro-v2` dataset directory.

Schema match:
  Stage 2 pro train cols = ['task', 'split', 'prompt', 'response', 'messages']
  named_drug_examples.jsonl cols = same, except `messages` is a list-of-dicts
  (we serialize to JSON string to match Stage 2 pro's stringified schema).

Outputs:
  data/processed/amr-stage2-pro-v2/        (HF DatasetDict on disk)
  data/processed/amr-stage2-pro-v2/test_named_drug.jsonl   (held-out test)
  data/synthetic/named_drug_train_split.jsonl              (training partition)

Run:
  python scripts/merge_named_drug_into_stage2.py
"""
import json
import hashlib
from collections import defaultdict
from pathlib import Path

from datasets import load_from_disk, Dataset, DatasetDict


SOURCE_JSONL = Path("data/synthetic/named_drug_examples.jsonl")
STAGE2_PRO_DIR = Path("data/processed/amr-stage2-pro")
OUT_DIR = Path("data/processed/amr-stage2-pro-v2")
# Test + train splits go into data/synthetic/ (git-tracked) for reproducibility,
# in addition to a copy of the test split inside OUT_DIR for trainer convenience.
TEST_OUT_DIR = OUT_DIR / "test_named_drug.jsonl"
TEST_OUT_TRACKED = Path("data/synthetic/named_drug_test_split.jsonl")
TRAIN_PARTITION = Path("data/synthetic/named_drug_train_split.jsonl")
TEST_FRACTION = 50 / 360  # ~14% test


def stable_hash(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def carve_test_split(rows):
    """Stratified by task: deterministically pick TEST_FRACTION from each task bucket."""
    by_task = defaultdict(list)
    for r in rows:
        by_task[r["task"]].append(r)

    train, test = [], []
    for task, task_rows in sorted(by_task.items()):
        # sort by deterministic hash so split is reproducible
        sorted_rows = sorted(task_rows, key=lambda r: stable_hash(r["prompt"]))
        n_test = max(1, round(len(sorted_rows) * TEST_FRACTION))
        test.extend(sorted_rows[:n_test])
        train.extend(sorted_rows[n_test:])

    return train, test


def to_stage2_schema(row):
    """Convert from our JSONL schema (messages as list) to Stage 2 pro (messages as JSON str)."""
    messages = row["messages"]
    if isinstance(messages, list):
        messages = json.dumps(messages, ensure_ascii=False)
    return {
        "task": row["task"],
        "split": row["split"],
        "prompt": row["prompt"],
        "response": row["response"],
        "messages": messages,
    }


def main():
    print(f"Reading {SOURCE_JSONL}...")
    rows = []
    with SOURCE_JSONL.open() as f:
        for line in f:
            rows.append(json.loads(line))
    print(f"  {len(rows)} entries loaded")

    train_rows, test_rows = carve_test_split(rows)
    print(f"  carved {len(train_rows)} train, {len(test_rows)} test")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Persist test split as JSONL for the held-out eval — both the OUT_DIR copy
    # (trainer convenience) and the data/synthetic/ tracked copy (reproducibility).
    for path in (TEST_OUT_DIR, TEST_OUT_TRACKED):
        with path.open("w") as f:
            for r in test_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  wrote {path}")

    with TRAIN_PARTITION.open("w") as f:
        for r in train_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  wrote {TRAIN_PARTITION}")

    # Convert train to Stage 2 schema
    train_stage2 = [to_stage2_schema(r) for r in train_rows]

    print(f"\nLoading existing Stage 2 pro from {STAGE2_PRO_DIR}...")
    existing = load_from_disk(str(STAGE2_PRO_DIR))
    print(f"  existing train rows: {len(existing['train'])}")
    print(f"  existing valid rows: {len(existing['valid'])}")

    # Dedupe: any pre-existing train rows whose prompt matches our held-out
    # test must be removed (otherwise the test isn't held-out). This catches
    # named_drug_examples that were integrated into stage2-pro by earlier sprints.
    test_prompt_set = {r["prompt"] for r in test_rows}
    pre_dedupe_train = existing["train"]
    deduped_train = pre_dedupe_train.filter(
        lambda r: r["prompt"] not in test_prompt_set,
        desc="Filtering pre-existing test-leaking rows",
    )
    leaks = len(pre_dedupe_train) - len(deduped_train)
    print(f"  removed {leaks} pre-existing duplicates of test prompts")

    # Build a Dataset from train_stage2 with same schema as existing
    new_train_ds = Dataset.from_list(train_stage2)
    print(f"  new entries to append: {len(new_train_ds)}")

    # Verify schema match
    if set(new_train_ds.column_names) != set(deduped_train.column_names):
        raise SystemExit(
            f"Schema mismatch: new={new_train_ds.column_names} "
            f"vs existing={deduped_train.column_names}"
        )

    # Concatenate
    from datasets import concatenate_datasets
    merged_train = concatenate_datasets([deduped_train, new_train_ds])
    print(f"  merged train rows: {len(merged_train)}")

    out_dict = DatasetDict({
        "train": merged_train,
        "valid": existing["valid"],
    })
    out_dict.save_to_disk(str(OUT_DIR))
    print(f"  saved DatasetDict to {OUT_DIR}")

    # Distribution report
    from collections import Counter
    print("\nNew task distribution in train:")
    tasks = Counter(merged_train["task"])
    new_tasks = set(r["task"] for r in train_stage2)
    for t in sorted(new_tasks):
        print(f"  {tasks[t]:6d}  {t}  (was {tasks[t] - sum(1 for r in train_stage2 if r['task']==t)})")


if __name__ == "__main__":
    main()
