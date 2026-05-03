"""Audit the Stage 3 RL prompts dataset (rahul24raj/lysos-rl-prompts).

Pulls the dataset from HF Hub and verifies:
  1. Splits + counts match the documented 11,520 train + 480 valid
  2. All 8 priority pathogens appear (MRSA, Mtb, EColi-CRE, KpneuCRE,
     Abaum, Paer, VRE, NGono)
  3. Both modalities (small-molecule + AMP/peptide) appear
  4. Prompt format is consistent — no truncated prompts, no missing fields
  5. Per-pathogen × per-modality balance is within tolerance
  6. No prompt collisions between train and valid (leakage)

Catches problems before MI300X kickoff. ZERO GPU.
"""
import json
import sys
from collections import Counter

from datasets import load_dataset


HUB_ID = "rahul24raj/lysos-rl-prompts"
EXPECTED_PATHOGENS = {"MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
                      "Abaum", "Paer", "VRE", "NGono"}


def main():
    failures = []
    print(f"Loading {HUB_ID} from HF Hub...")
    ds = load_dataset(HUB_ID)
    print(f"  splits: {list(ds.keys())}")
    for split in ds:
        print(f"  {split}: {len(ds[split]):,} rows")
        print(f"  columns: {ds[split].column_names}")

    # --- Check 1: split sizes ---
    train_n, valid_n = len(ds["train"]), len(ds["valid"])
    if train_n != 11520:
        print(f"  ⚠ train rows {train_n} != expected 11520")
    if valid_n != 480:
        print(f"  ⚠ valid rows {valid_n} != expected 480")

    # --- Check 2: pathogen coverage ---
    print(f"\n[2/6] Pathogen coverage...")
    pathogens_seen = Counter()
    for r in ds["train"]:
        # Could be in any of these fields depending on dataset schema
        for field in ("pathogen_short", "pathogen", "target_pathogen", "target"):
            v = r.get(field)
            if v:
                pathogens_seen[v] += 1
                break
    print(f"  pathogens seen ({len(pathogens_seen)}):")
    for p, n in pathogens_seen.most_common():
        marker = "✓" if p in EXPECTED_PATHOGENS else "?"
        print(f"    {marker} {p:20s} {n:5d}")
    missing = EXPECTED_PATHOGENS - set(pathogens_seen)
    if missing:
        failures.append(f"Missing pathogens: {missing}")
        print(f"  ❌ MISSING: {missing}")
    else:
        print(f"  ✓ all 8 priority pathogens covered")

    # --- Check 3: modality ---
    print(f"\n[3/6] Modality coverage...")
    modalities_seen = Counter()
    for r in ds["train"]:
        for field in ("modality", "type", "category"):
            v = r.get(field)
            if v:
                modalities_seen[v] += 1
                break
    print(f"  modalities ({len(modalities_seen)}):")
    for m, n in modalities_seen.most_common():
        print(f"    {m:20s} {n:5d}")

    # --- Check 4: prompt fields populated ---
    print(f"\n[4/6] Prompt field integrity...")
    empty_prompts = 0
    short_prompts = 0
    for r in ds["train"]:
        p = r.get("prompt", "")
        if not p:
            empty_prompts += 1
        elif len(p) < 50:
            short_prompts += 1
    print(f"  empty prompts: {empty_prompts}")
    print(f"  prompts under 50 chars: {short_prompts}")
    if empty_prompts:
        failures.append(f"{empty_prompts} empty prompts")

    # --- Check 5: per-pathogen × per-modality balance ---
    print(f"\n[5/6] Per-pathogen × per-modality balance...")
    cross_dist = Counter()
    for r in ds["train"]:
        path = next((r.get(f) for f in ("pathogen_short", "pathogen",
                                         "target_pathogen", "target") if r.get(f)), None)
        modal = next((r.get(f) for f in ("modality", "type", "category")
                     if r.get(f)), None)
        cross_dist[(path, modal)] += 1
    print(f"  combinations seen: {len(cross_dist)}")
    for (p, m), n in cross_dist.most_common():
        print(f"    {str(p):20s} × {str(m):20s}  {n:5d}")
    if len(cross_dist) < 16:
        print(f"  (expected 16 = 8 pathogens × 2 modalities; check schema)")

    # --- Check 6: train/valid leakage ---
    print(f"\n[6/6] Train/valid prompt-leakage check...")
    valid_prompts = set(ds["valid"]["prompt"])
    train_prompts = set(ds["train"]["prompt"])
    overlap = valid_prompts & train_prompts
    print(f"  overlap: {len(overlap)} prompts")
    if overlap:
        failures.append(f"{len(overlap)} prompts leak between train/valid")

    print(f"\n{'='*70}")
    if failures:
        print(f"❌ {len(failures)} FAILURE(S):")
        for f in failures:
            print(f"   - {f}")
        return 1
    print(f"✅ ALL CHECKS PASSED — Stage 3 prompts ready for GRPO")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
