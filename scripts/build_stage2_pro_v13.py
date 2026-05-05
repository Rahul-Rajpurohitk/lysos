"""Build stage2-pro-v13 — pro-v12 + pharma_qa Gemini-Pro-grounded layer.

What's new vs v12:
  + 872 pharma Q&A pairs (concise) from data/synthetic/pharma_qa_layer.jsonl
  + 872 pharma Q&A pairs (with chain-of-thought) from
    data/synthetic/pharma_qa_layer_cot.jsonl

Why two variants:
  Concise pairs train direct-answer pharmacology recall (clinician-style
  one-liners). CoT pairs train explicit reasoning before answering
  (pharmacist-rounding style: "let me think through this...").
  Both improve Stage-2's grounding on the 218 most clinically-relevant
  named antibiotics — coverage that the bulk ChEMBL/NPAtlas SMILES
  catalog cannot provide.

Source-of-truth: artifacts/embeddings/named-drugs-gemini-enrichment.parquet
                 ($2.59 of Gemini 2.5 Pro, 218 drugs × 4 axes).
                 Locally owned. Reproducible via:
                 python3 scripts/build_pharma_qa_layer.py [--include-thinking]

Output: data/processed/amr-stage2-pro-v13
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from datasets import Dataset, DatasetDict, load_from_disk

ROOT = Path(__file__).resolve().parents[1]
PRO_V12 = ROOT / "data" / "processed" / "amr-stage2-pro-v12"
NEW_LAYERS = [
    ("pharma_qa_concise", ROOT / "data" / "synthetic" / "pharma_qa_layer.jsonl"),
    ("pharma_qa_cot",     ROOT / "data" / "synthetic" / "pharma_qa_layer_cot.jsonl"),
]
OUT_DIR = ROOT / "data" / "processed" / "amr-stage2-pro-v13"


def main():
    print(f"Loading pro-v12 from {PRO_V12}")
    base = load_from_disk(str(PRO_V12))
    print(f"  splits: {dict((k, len(base[k])) for k in base.keys())}")

    train_rows = list(base["train"])
    valid_rows = list(base["valid"])
    test_rows = list(base["test"]) if "test" in base.keys() else []

    rng = random.Random(0xC0DE_5253)

    for label, path in NEW_LAYERS:
        if not path.exists():
            print(f"  SKIP {label} — file missing")
            continue
        n_train = n_valid = n_test = 0
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                msgs_str = json.dumps(row["messages"])
                # 5% to valid, hold none in test (we want pharma_qa to train)
                split = "valid" if rng.random() < 0.05 else "train"
                normalized = {
                    "task": row.get("task", label),
                    "pathogen": row.get("pathogen")
                                if isinstance(row.get("pathogen"), str) else None,
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
        import shutil
        shutil.rmtree(OUT_DIR)
    print(f"Saving to {OUT_DIR} …")
    out.save_to_disk(str(OUT_DIR))

    test_n = len(splits["test"]) if "test" in splits else 0
    print(f"\nstage2-pro-v13: train={len(train_ds):,} valid={len(valid_ds):,} test={test_n}")


if __name__ == "__main__":
    sys.exit(main())
