"""Build stage2-pro-v10 — pro-v5 + ALL teacher distillation across 7 layers.

Layers (no API spend; all manual inline):
  1. Chem teacher (5,000)              Designer<->Critic chem-design loops
  2. Systems teacher (6,500)           13 categories of campaign / orchestration
  3. Architecture teacher (10,000)     20 categories of system contracts
  4. Raw-data + core teacher (12,000)  20 categories of source schemas + chem/biology
  5. Edge + clinical teacher (10,000)  20 categories of edges + clinical narratives
  6. Targeted teacher (17,150)         per-PDB + per-mutation + 3-way + self-correct + indications + chains
  7. Eval-aligned teacher (17,500)     10 categories explicitly improving the 7 leaderboard metrics

Total teacher distillation: 78,150 traces

Output: data/processed/amr-stage2-pro-v10
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from datasets import Dataset, DatasetDict, load_from_disk

ROOT = Path(__file__).resolve().parents[1]
PRO_V5 = ROOT / "data" / "processed" / "amr-stage2-pro-v5"
TEACHER_FILES = [
    ("teacher_distill_chem",          ROOT / "data" / "synthetic" / "agentic_teacher_distill.jsonl"),
    ("teacher_distill_systems",       ROOT / "data" / "synthetic" / "agentic_teacher_distill_systems.jsonl"),
    ("teacher_distill_arch",          ROOT / "data" / "synthetic" / "agentic_teacher_distill_architecture.jsonl"),
    ("teacher_distill_rawdata",       ROOT / "data" / "synthetic" / "agentic_teacher_distill_raw_data.jsonl"),
    ("teacher_distill_edge",          ROOT / "data" / "synthetic" / "agentic_teacher_distill_edge_clinical.jsonl"),
    ("teacher_distill_targeted",      ROOT / "data" / "synthetic" / "agentic_teacher_distill_targeted.jsonl"),
    ("teacher_distill_eval_aligned",  ROOT / "data" / "synthetic" / "agentic_teacher_distill_eval_aligned.jsonl"),
]
OUT_DIR = ROOT / "data" / "processed" / "amr-stage2-pro-v10"


def main():
    print(f"Loading pro-v5 from {PRO_V5}")
    base = load_from_disk(str(PRO_V5))
    print(f"  splits: {dict((k, len(base[k])) for k in base.keys())}")

    train_rows = list(base["train"])
    valid_rows = list(base["valid"])
    test_rows = list(base["test"]) if "test" in base.keys() else []

    rng = random.Random(0xC0DE_5050)

    for label, path in TEACHER_FILES:
        if not path.exists():
            print(f"  SKIP {label} — file missing")
            continue
        n_added_train = n_added_valid = 0
        with open(path) as f:
            for line in f:
                if not line.strip(): continue
                row = json.loads(line)
                msgs_str = json.dumps(row["messages"])
                split = "valid" if rng.random() < 0.05 else "train"
                normalized = {
                    "task": row.get("task", label),
                    "pathogen": row.get("pathogen") if isinstance(row.get("pathogen"), str) else None,
                    "messages": msgs_str,
                    "split": split,
                }
                if split == "train":
                    train_rows.append(normalized); n_added_train += 1
                else:
                    valid_rows.append(normalized); n_added_valid += 1
        print(f"  {label:35s} +train {n_added_train:>6,}  +valid {n_added_valid:>5,}")

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
    print(f"\n✅ stage2-pro-v10: train={len(train_ds):,} valid={len(valid_ds):,} test={test_n}")


if __name__ == "__main__":
    sys.exit(main())
