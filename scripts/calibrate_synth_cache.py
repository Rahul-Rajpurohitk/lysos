"""Synthesis-cost reward calibration cache (replaces AizynthFinder for now).

Uses RDKit's SAscore (Ertl + Schuffenhauer 2009) — the same heuristic
AizynthFinder uses as a baseline. Cheap, deterministic, runs in seconds
on all 39K cleaned actives.

Output cache feeds the `synthesizability` reward component
(src/eval/rewards/synth.py) so RL gets real synth-cost signal instead
of the fallback constant.

When AizynthFinder + ROCm + the full retrosynthesis stack is available
(post-hackathon), this gets replaced with full route-finding.

Run:
  /tmp/lysos_venv/bin/python scripts/calibrate_synth_cache.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from rdkit import Chem, RDLogger
from rdkit.Chem import RDConfig

# RDKit ships SAscorer in Contrib
sys.path.append(str(Path(RDConfig.RDContribDir) / "SA_Score"))
import sascorer  # noqa: E402

RDLogger.DisableLog("rdApp.*")

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "processed" / "known-antibiotics-canonical.parquet"
OUT = ROOT / "data" / "processed" / "synth_calibration_cache.parquet"


def main():
    print(f"Loading actives from {INPUT}")
    df = pd.read_parquet(INPUT)
    print(f"  rows: {len(df):,}")

    rows = []
    n = 0
    for r in df.to_dict(orient="records"):
        n += 1
        smi = r.get("smiles")
        if not isinstance(smi, str): continue
        mol = Chem.MolFromSmiles(smi)
        if mol is None: continue
        try:
            sa = float(sascorer.calculateScore(mol))
        except Exception:
            continue
        # Heuristic step count + cost mapping from SA score
        # SA 1-2: trivial, ~3 steps, ~$50/g
        # SA 2-3: easy, ~4 steps, ~$120/g
        # SA 3-4: moderate, ~5 steps, ~$300/g
        # SA 4-5: hard, ~7 steps, ~$700/g
        # SA 5-6: very hard, ~9 steps, ~$1500/g
        # SA 6+: extreme, ~12+ steps, ~$3000+/g
        if sa < 2:
            est_steps, est_cost = 3, 50
        elif sa < 3:
            est_steps, est_cost = 4, 120
        elif sa < 4:
            est_steps, est_cost = 5, 300
        elif sa < 5:
            est_steps, est_cost = 7, 700
        elif sa < 6:
            est_steps, est_cost = 9, 1500
        else:
            est_steps, est_cost = 12, 3000

        # Reward score: 1.0 - SA/10 (higher is better for reward)
        synth_reward = max(0.0, min(1.0, 1.0 - sa / 10.0))

        rows.append({
            "smiles": smi,
            "name": r.get("name"),
            "source": r.get("source"),
            "sa_score": round(sa, 3),
            "estimated_steps": est_steps,
            "estimated_cost_usd_per_g": est_cost,
            "synth_reward": round(synth_reward, 3),
        })

        if n % 5000 == 0:
            print(f"  progress {n:,}/{len(df):,}  cached={len(rows):,}")

    out_df = pd.DataFrame(rows)
    out_df.to_parquet(OUT, index=False)

    # Distribution summary
    print(f"\nDone. cached={len(out_df):,}")
    print(f"\nSA score distribution:")
    print(f"  min:    {out_df['sa_score'].min():.2f}")
    print(f"  p10:    {out_df['sa_score'].quantile(0.10):.2f}")
    print(f"  p50:    {out_df['sa_score'].median():.2f}")
    print(f"  p90:    {out_df['sa_score'].quantile(0.90):.2f}")
    print(f"  max:    {out_df['sa_score'].max():.2f}")
    print(f"\nCost class distribution:")
    print(out_df["estimated_cost_usd_per_g"].value_counts().sort_index())
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
