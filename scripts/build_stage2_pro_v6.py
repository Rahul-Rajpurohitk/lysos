"""Build stage2-pro-v6 — pro-v5 + teacher-distillation traces.

Adds 1,000 manually-authored Designer<->Critic teacher traces
(data/synthetic/agentic_teacher_distill.jsonl) on top of pro-v5.

Output:
  data/processed/amr-stage2-pro-v6
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from datasets import Dataset, DatasetDict, load_from_disk

ROOT = Path(__file__).resolve().parents[1]
PRO_V5 = ROOT / "data" / "processed" / "amr-stage2-pro-v5"
TEACHER = ROOT / "data" / "synthetic" / "agentic_teacher_distill.jsonl"
OUT_DIR = ROOT / "data" / "processed" / "amr-stage2-pro-v6"


def main():
    print(f"Loading pro-v5 from {PRO_V5}")
    base = load_from_disk(str(PRO_V5))
    print(f"  splits: {dict((k, len(base[k])) for k in base.keys())}")

    train_rows = list(base["train"])
    valid_rows = list(base["valid"])
    test_rows = list(base["test"]) if "test" in base.keys() else []

    rng = random.Random(0xCAFE_4242)

    # Add teacher distill (95/5 train/valid split)
    if not TEACHER.exists():
        print(f"WARN: teacher distill file missing at {TEACHER}")
    else:
        n_added_train = n_added_valid = 0
        with open(TEACHER) as f:
            for line in f:
                if not line.strip(): continue
                row = json.loads(line)
                msgs_str = json.dumps(row["messages"])
                split = "valid" if rng.random() < 0.05 else "train"
                normalized = {
                    "task": "teacher_distill",
                    "pathogen": row.get("pathogen"),
                    "messages": msgs_str,
                    "split": split,
                }
                if split == "train":
                    train_rows.append(normalized); n_added_train += 1
                else:
                    valid_rows.append(normalized); n_added_valid += 1
        print(f"  teacher_distill: +train {n_added_train}, +valid {n_added_valid}")

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
    print(f"\n✅ stage2-pro-v6: train={len(train_ds):,} valid={len(valid_ds):,} test={test_n}")


if __name__ == "__main__":
    sys.exit(main())
