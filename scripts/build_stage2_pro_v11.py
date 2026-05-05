"""Build pro-v11 — pro-v10 with quality-weighted sampling.

Strategy:
  - Read pro-v10 + per-row quality scores from
    data/processed/pro-v10-quality-scores.parquet
  - Oversample top-quartile rows 2x (high-leverage teacher distill)
  - Keep middle-quartile rows 1x
  - Downsample bottom-quartile rows 0.5x

This biases SFT toward Designer<->Critic loops + arch contracts + niche
deep-dives + eval-aligned skills, away from boilerplate name-lookup tasks.

Output: data/processed/amr-stage2-pro-v11
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pandas as pd
from datasets import Dataset, DatasetDict, load_from_disk

ROOT = Path(__file__).resolve().parents[1]
PRO_V10 = ROOT / "data" / "processed" / "amr-stage2-pro-v10"
SCORES = ROOT / "data" / "processed" / "pro-v10-quality-scores.parquet"
OUT_DIR = ROOT / "data" / "processed" / "amr-stage2-pro-v11"


def main():
    print(f"Loading pro-v10 from {PRO_V10}")
    base = load_from_disk(str(PRO_V10))
    print(f"  splits: {dict((k, len(base[k])) for k in base.keys())}")

    print(f"Loading quality scores from {SCORES}")
    scores_df = pd.read_parquet(SCORES)
    print(f"  scored rows: {len(scores_df):,}")

    # Quartile thresholds
    top_t = scores_df["total_score"].quantile(0.75)
    bot_t = scores_df["total_score"].quantile(0.25)
    print(f"  top quartile threshold: {top_t:.2f}")
    print(f"  bot quartile threshold: {bot_t:.2f}")

    rng = random.Random(0xC0DE_5151)
    score_lookup = dict(zip(scores_df["row_idx"], scores_df["total_score"]))

    new_train = []
    n_oversampled = 0
    n_downsampled_kept = 0
    n_downsampled_skipped = 0
    n_kept_normal = 0

    for i, r in enumerate(base["train"]):
        score = score_lookup.get(i, 5.0)
        normalized = {
            "task": r["task"],
            "pathogen": r["pathogen"],
            "messages": r["messages"],
            "split": r["split"],
        }
        if score >= top_t:
            # Oversample 2x
            new_train.append(normalized)
            new_train.append(normalized)
            n_oversampled += 1
        elif score <= bot_t:
            # Downsample 0.5x
            if rng.random() < 0.5:
                new_train.append(normalized)
                n_downsampled_kept += 1
            else:
                n_downsampled_skipped += 1
        else:
            # Keep middle quartile 1x
            new_train.append(normalized)
            n_kept_normal += 1

    rng.shuffle(new_train)
    print(f"\nQuality-weighted sampling:")
    print(f"  oversampled (top quartile): {n_oversampled:,} (each appears 2x)")
    print(f"  kept normal (middle):       {n_kept_normal:,}")
    print(f"  downsampled (bot quartile): {n_downsampled_kept:,} kept, {n_downsampled_skipped:,} dropped")
    print(f"  total train rows: {len(new_train):,}")

    valid_rows = list(base["valid"])
    test_rows = list(base["test"]) if "test" in base.keys() else []

    train_ds = Dataset.from_list(new_train)
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
    print(f"\n✅ stage2-pro-v11: train={len(train_ds):,} valid={len(valid_ds):,} test={test_n}")


if __name__ == "__main__":
    sys.exit(main())
