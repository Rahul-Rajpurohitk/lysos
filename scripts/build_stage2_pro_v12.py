"""Build stage2-pro-v12 — pro-v11 + counterfactual pairs + time-aware eval.

Adds two new training-data layers on top of the quality-weighted pro-v11:
  - 1,437 counterfactual pairs (MMP-mined activity-cliff training)
  - 8 time-aware eval prompts (held-out test split for temporal generalization)

Output: data/processed/amr-stage2-pro-v12
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from datasets import Dataset, DatasetDict, load_from_disk

ROOT = Path(__file__).resolve().parents[1]
PRO_V11 = ROOT / "data" / "processed" / "amr-stage2-pro-v11"
NEW_LAYERS = [
    ("counterfactual_pair", ROOT / "data" / "synthetic" / "agentic_counterfactual_pairs.jsonl"),
    ("time_aware_eval",     ROOT / "data" / "synthetic" / "agentic_time_aware_eval.jsonl"),
]
OUT_DIR = ROOT / "data" / "processed" / "amr-stage2-pro-v12"


def main():
    print(f"Loading pro-v11 from {PRO_V11}")
    base = load_from_disk(str(PRO_V11))
    print(f"  splits: {dict((k, len(base[k])) for k in base.keys())}")

    train_rows = list(base["train"])
    valid_rows = list(base["valid"])
    test_rows = list(base["test"]) if "test" in base.keys() else []

    rng = random.Random(0xC0DE_5252)

    for label, path in NEW_LAYERS:
        if not path.exists():
            print(f"  SKIP {label} — file missing")
            continue
        n_train = n_valid = n_test = 0
        with open(path) as f:
            for line in f:
                if not line.strip(): continue
                row = json.loads(line)
                msgs_str = json.dumps(row["messages"])
                # time_aware_eval rows go to test split (held-out)
                if label == "time_aware_eval":
                    split = "test"
                else:
                    split = "valid" if rng.random() < 0.05 else "train"
                normalized = {
                    "task": row.get("task", label),
                    "pathogen": row.get("pathogen") if isinstance(row.get("pathogen"), str) else None,
                    "messages": msgs_str,
                    "split": split,
                }
                if split == "train":
                    train_rows.append(normalized); n_train += 1
                elif split == "valid":
                    valid_rows.append(normalized); n_valid += 1
                elif split == "test":
                    test_rows.append(normalized); n_test += 1
        print(f"  {label:25s} +train {n_train:>5,}  +valid {n_valid:>4,}  +test {n_test:>3,}")

    rng.shuffle(train_rows); rng.shuffle(valid_rows); rng.shuffle(test_rows)

    train_ds = Dataset.from_list(train_rows)
    valid_ds = Dataset.from_list(valid_rows)
    splits = {"train": train_ds, "valid": valid_ds}
    if test_rows:
        splits["test"] = Dataset.from_list(test_rows)
    out = DatasetDict(splits)

    OUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    if OUT_DIR.exists():
        import shutil; shutil.rmtree(OUT_DIR)
    print(f"Saving to {OUT_DIR} …")
    out.save_to_disk(str(OUT_DIR))

    test_n = len(splits["test"]) if "test" in splits else 0
    print(f"\n✅ stage2-pro-v12: train={len(train_ds):,} valid={len(valid_ds):,} test={test_n}")


if __name__ == "__main__":
    sys.exit(main())
