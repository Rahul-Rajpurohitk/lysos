"""Run AizynthFinder on the top-priority subset of candidates.

Selects the 1000 candidates with lowest SA score (most likely to yield a
viable route) from the synth_calibration_cache. Runs full retrosynthesis
on each. Caches per-(smiles) route for the synthesizability reward.

Run with the python 3.12 venv that has aizynthfinder installed:
  /tmp/aizynth_venv/bin/python scripts/run_aizynth_priority_sweep.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SAS_CACHE = ROOT / "data" / "processed" / "synth_calibration_cache.parquet"
OUT = ROOT / "data" / "processed" / "aizynth_calibration_cache.parquet"
CONFIG = Path("/tmp/aizynth_data/config.yml")

N_CANDIDATES = 1000


def main():
    print(f"Loading SA cache from {SAS_CACHE}")
    df = pd.read_parquet(SAS_CACHE)
    df = df.sort_values("sa_score").head(N_CANDIDATES).reset_index(drop=True)
    print(f"  selected top {len(df)} candidates by SA score")

    print(f"Loading AizynthFinder with config {CONFIG}")
    from aizynthfinder.aizynthfinder import AiZynthFinder
    finder = AiZynthFinder(configfile=str(CONFIG))
    finder.stock.select("zinc")
    finder.expansion_policy.select("uspto")
    finder.filter_policy.select("uspto")

    rows = []
    n_done = 0
    t0 = time.time()
    for r in df.to_dict(orient="records"):
        smi = r.get("smiles")
        if not isinstance(smi, str): continue
        finder.target_smiles = smi
        try:
            finder.tree_search()
            finder.build_routes()
            stats = finder.extract_statistics()
            n_routes = stats.get("number_of_routes", 0)
            top_score = stats.get("top_score", 0.0)
            best_route = finder.routes[0] if finder.routes else None
            n_steps = best_route.depth if best_route else 0
            n_buildup = stats.get("number_of_solved_routes", 0)
            rows.append({
                "smiles": smi,
                "name": r.get("name"),
                "sa_score": r.get("sa_score"),
                "n_routes_found": n_routes,
                "n_solved_routes": n_buildup,
                "best_route_score": float(top_score),
                "best_route_depth": int(n_steps),
                "synth_reward_aizynth": float(top_score),
            })
        except Exception as e:
            rows.append({
                "smiles": smi,
                "name": r.get("name"),
                "sa_score": r.get("sa_score"),
                "n_routes_found": 0,
                "n_solved_routes": 0,
                "best_route_score": 0.0,
                "best_route_depth": 0,
                "synth_reward_aizynth": 0.0,
                "error": str(e)[:100],
            })
        n_done += 1
        if n_done % 25 == 0:
            elapsed = time.time() - t0
            rate = n_done / elapsed
            remaining = (len(df) - n_done) / rate if rate > 0 else 0
            print(f"  done {n_done}/{len(df)}  rate={rate:.1f}/s  ETA={remaining/60:.0f}min")
            # incremental save
            pd.DataFrame(rows).to_parquet(OUT, index=False)

    pd.DataFrame(rows).to_parquet(OUT, index=False)
    print(f"\nDone. {len(rows)} candidates processed.")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
