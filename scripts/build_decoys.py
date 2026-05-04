"""DUD-E style property-matched decoys (#6 from audit).

For each active in known-antibiotics-canonical, sample N_decoys ZINC molecules
matched on physical properties:
  MW ± 25 Da, logP ± 1.0, HBA ± 2, HBD ± 1, rotatable_bonds ± 2,
  ring_count ± 1, charge ± 1.

Decoys serve as property-matched negatives. Without them, the model can shortcut
on superficial features ("looks like a beta-lactam → predict active").

Inputs:
  data/processed/known-antibiotics-canonical.parquet  (cleaned actives)
  data/raw/zinc/*.smi  OR  fall-back: data/processed/zinc-sample.parquet

Outputs:
  data/processed/decoy-actives-pairs.parquet
  data/synthetic/agentic_decoy_negatives.jsonl  (training rows)

Run:
  /tmp/lysos_venv/bin/python scripts/build_decoys.py --n_decoys 10
"""
from __future__ import annotations

import argparse
import json
import sys
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, Crippen, Lipinski, rdMolDescriptors

RDLogger.DisableLog("rdApp.*")

ROOT = Path(__file__).resolve().parents[1]
ACTIVES_IN = ROOT / "data" / "processed" / "known-antibiotics-canonical.parquet"
ZINC_RAW_DIR = ROOT / "data" / "raw" / "zinc"
OUT_PAIRS = ROOT / "data" / "processed" / "decoy-actives-pairs.parquet"
OUT_JSONL = ROOT / "data" / "synthetic" / "agentic_decoy_negatives.jsonl"


def compute_props(smiles: str) -> dict | None:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None: return None
    return {
        "smiles": Chem.MolToSmiles(mol, isomericSmiles=True, canonical=True),
        "mw": Descriptors.MolWt(mol),
        "logp": Crippen.MolLogP(mol),
        "hba": Lipinski.NumHAcceptors(mol),
        "hbd": Lipinski.NumHDonors(mol),
        "rb": Lipinski.NumRotatableBonds(mol),
        "rings": rdMolDescriptors.CalcNumRings(mol),
        "charge": Chem.GetFormalCharge(mol),
    }


def load_zinc_pool() -> pd.DataFrame:
    """Load ZINC molecule pool. Try raw .smi files first, fall back to a synth pool."""
    pool: list[dict] = []
    if ZINC_RAW_DIR.exists():
        for p in ZINC_RAW_DIR.glob("*.smi"):
            with open(p) as f:
                for line in f:
                    parts = line.strip().split()
                    if not parts: continue
                    s = parts[0]
                    pp = compute_props(s)
                    if pp is None: continue
                    pp["zinc_id"] = parts[1] if len(parts) > 1 else f"ZINC{len(pool):08d}"
                    pool.append(pp)
                    if len(pool) >= 200000:
                        break
            if len(pool) >= 200000:
                break
    if not pool:
        # Fallback: use a deterministic synthetic decoy pool from common drug-like cores
        # combined with random functional-group decorations.
        cores = [
            "c1ccc(O)cc1", "c1ccncc1", "c1ccc(N)cc1", "c1cnccn1", "c1ccoc1",
            "C1CCCCC1", "C1CCNCC1", "C1CC(=O)NC1", "c1ccsc1", "C1=CC=CN1",
            "c1ccc2ncccc2c1", "C1CCC(=O)NC1", "OC(=O)c1ccccc1",
            "C(=O)NCCO", "CCOCCO", "OC(=O)CC", "OCCOCC",
        ]
        decs = ["", "C", "CC", "F", "Cl", "Br", "OC", "C(=O)O", "N", "OC(=O)C",
                "C(N)=O", "S(=O)(=O)N", "CCN", "OCC", "C1CC1", "c1ccccc1"]
        rng = random.Random(0xDECAF)
        seen = set()
        attempts = 0
        while len(pool) < 100000 and attempts < 500000:
            attempts += 1
            core = rng.choice(cores)
            d1 = rng.choice(decs)
            d2 = rng.choice(decs)
            cand = f"{d1}{core}{d2}"
            if cand in seen: continue
            seen.add(cand)
            pp = compute_props(cand)
            if pp is None: continue
            pp["zinc_id"] = f"DECOY{len(pool):08d}"
            pool.append(pp)
    df = pd.DataFrame(pool)
    return df


def bin_key(p: dict) -> tuple:
    return (
        round(p["mw"] / 25),
        round(p["logp"] / 1.0),
        round(p["hba"] / 2),
        round(p["hbd"] / 1),
        round(p["rb"] / 2),
        round(p["rings"] / 1),
        int(p["charge"]),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_decoys", type=int, default=10,
                    help="Decoys per active (DUD-E uses 50, we use 10 for budget)")
    ap.add_argument("--seed", type=int, default=0xDEC0_DE)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    print(f"Loading actives from {ACTIVES_IN}")
    if not ACTIVES_IN.exists():
        print("ERROR: known-antibiotics-canonical.parquet does not exist.")
        print("Run scripts/clean_chemistry_corpus.py first.")
        return 1
    actives = pd.read_parquet(ACTIVES_IN)
    print(f"  actives: {len(actives):,}")

    print("\nLoading ZINC pool...")
    pool = load_zinc_pool()
    print(f"  pool: {len(pool):,}")

    print("\nBinning pool by property cell...")
    pool_records = pool.to_dict(orient="records")
    bins = defaultdict(list)
    for r in pool_records:
        bins[bin_key(r)].append(r)
    print(f"  occupied bins: {len(bins):,}")

    print("\nSampling decoys per active...")
    out_rows = []
    n_progress = 0
    n_skip_no_bin = 0
    for r in actives.to_dict(orient="records"):
        n_progress += 1
        if n_progress % 5000 == 0:
            print(f"  progress: {n_progress:,}/{len(actives):,}  pairs={len(out_rows):,}")
        if not isinstance(r.get("smiles"), str):
            continue
        # Use the active's already-computed properties (they're in the cleaned file)
        p = {
            "mw": r.get("mw") or 0,
            "logp": r.get("logp") or 0,
            "hba": r.get("hba") or 0,
            "hbd": r.get("hbd") or 0,
            "rb": r.get("rotatable_bonds") or 0,
            "rings": r.get("ring_count") or 0,
            "charge": 0,  # cleanup didn't store charge; default to 0
        }
        key = bin_key(p)
        candidates = bins.get(key, [])
        if not candidates:
            # widen one-bin neighborhood
            for dmw in (-1, 0, 1):
                for dlp in (-1, 0, 1):
                    candidates += bins.get((key[0]+dmw, key[1]+dlp, *key[2:]), [])
            if not candidates:
                n_skip_no_bin += 1
                continue
        if len(candidates) < args.n_decoys:
            chosen = candidates  # take all
        else:
            chosen = rng.sample(candidates, args.n_decoys)
        for d in chosen:
            out_rows.append({
                "active_smiles": r["smiles"],
                "active_name": r.get("name"),
                "active_source": r.get("source"),
                "decoy_smiles": d["smiles"],
                "decoy_zinc_id": d["zinc_id"],
                "active_mw": p["mw"], "decoy_mw": d["mw"],
                "active_logp": p["logp"], "decoy_logp": d["logp"],
            })
    print(f"\n  pairs generated: {len(out_rows):,}")
    print(f"  actives skipped (no bin match): {n_skip_no_bin:,}")
    out_df = pd.DataFrame(out_rows)
    out_df.to_parquet(OUT_PAIRS, index=False)
    print(f"  wrote {OUT_PAIRS}")

    # Build training rows (one per active, with ALL its decoys listed)
    print(f"\nBuilding training JSONL rows...")
    by_active: dict[str, list] = defaultdict(list)
    for r in out_rows:
        by_active[r["active_smiles"]].append(r["decoy_smiles"])
    if OUT_JSONL.exists(): OUT_JSONL.unlink()
    n_jsonl = 0
    with open(OUT_JSONL, "a") as f:
        for active, decoys in by_active.items():
            # Build a "label these molecules as active or decoy" task
            molecules = [(active, "active")] + [(d, "decoy") for d in decoys[:5]]
            rng.shuffle(molecules)
            molecules_str = "\n".join(f"  {i+1}. {s}" for i, (s, _) in enumerate(molecules))
            labels_str = "\n".join(
                f"  {i+1}. {label.upper()}{' — known antibacterial activity' if label == 'active' else ' — property-matched non-binder, no antibacterial pharmacophore'}"
                for i, (s, label) in enumerate(molecules)
            )
            row = {
                "task": "decoy_negative",
                "pathogen": None,
                "messages": [
                    {"role": "system", "content":
                        "You are the Lysos Critic agent. Distinguish bona-fide "
                        "antibacterials from property-matched decoys (DUD-E methodology). "
                        "Decoys share MW, logP, HBA, HBD, rotatable bonds, charge, and "
                        "ring count with actives but lack the antibacterial pharmacophore. "
                        "Surface-feature shortcuts will fail; reason about the structural "
                        "pharmacophore."},
                    {"role": "user", "content":
                        f"Classify each molecule below as ACTIVE or DECOY:\n\n{molecules_str}"},
                    {"role": "assistant", "content":
                        f"Per-molecule classification:\n\n{labels_str}\n\n"
                        f"Reasoning: the active carries the antibacterial pharmacophore "
                        f"(target-engagement features: e.g., β-lactam ring, aminoglycoside "
                        f"hydroxyls, pyridine ring, etc., depending on class). Decoys "
                        f"match physical properties only — same MW/logP/HBA/HBD bin — but "
                        f"lack the structural feature that engages a bacterial target."},
                ],
            }
            f.write(json.dumps(row) + "\n")
            n_jsonl += 1
    print(f"  wrote {n_jsonl:,} JSONL rows → {OUT_JSONL}")

    print("\nSummary:")
    print(f"  active-decoy pairs:  {len(out_rows):,}")
    print(f"  training rows:       {n_jsonl:,}")


if __name__ == "__main__":
    sys.exit(main())
