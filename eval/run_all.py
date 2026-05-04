"""Lysos eval harness — runs all 7 leaderboard metrics.

Currently runs against pre-computed prediction files (CSV/JSONL). Inference
integration with vLLM/HF is wired but disabled by default until model
artifacts land. Use:

  /tmp/lysos_venv/bin/python eval/run_all.py --predictions reports/predictions.json
  /tmp/lysos_venv/bin/python eval/run_all.py --baseline_only

The eval config is locked in eval/config.json so results are reproducible
across runs and model versions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval import metrics

EVAL_CONFIG = {
    "version": "v3",
    "temperature": 0.0,
    "temperature_secondary": 0.7,
    "max_new_tokens": 512,
    "n_samples": 200,
    "novelty_threshold": 0.4,
    "mic_holdout_n": 500,
    "tool_call_replay_n": 100,
    "jailbreak_n": 50,
    "reasoning_n": 100,
    "seed": 0xEDA12_517,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", type=Path,
                    help="JSON file with: generations, mic_predictions, "
                         "tool_replay, jailbreak_responses, reasoning_records")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "eval_v3.json")
    ap.add_argument("--baseline_only", action="store_true",
                    help="Run on a baseline corpus (no model needed) — known-antibiotic SMILES")
    args = ap.parse_args()

    print(f"Lysos eval harness v3 — config locked")
    for k, v in EVAL_CONFIG.items():
        print(f"  {k}: {v}")

    results = {"config": EVAL_CONFIG, "metrics": {}}

    if args.baseline_only:
        # Run baseline: a sample of known antibiotics (should score 100% on
        # validity, varying on novelty against itself)
        import pandas as pd
        p = ROOT / "data" / "processed" / "known-antibiotics-canonical.parquet"
        if not p.exists():
            p = ROOT / "data" / "processed" / "known-antibiotics.parquet"
        df = pd.read_parquet(p)
        sample = df["smiles"].dropna().tolist()[:200]
        print(f"\nBaseline corpus: {len(sample)} known SMILES from {p.name}")
        results["metrics"]["chem_validity"] = metrics.chem_validity(sample)
        results["metrics"]["novelty_tanimoto"] = metrics.novelty_tanimoto(sample)
        results["metrics"]["admet_pass_rate"] = metrics.admet_pass_rate(sample)
        # Other metrics need model output, skip
        print("\nResults:")
        for k, v in results["metrics"].items():
            print(f"  {k}: pct={v.get('pct_parse') or v.get('pct_novel') or v.get('pct_pass') or v.get('pct_refused')}, target={v.get('target')}")
    elif args.predictions:
        with args.predictions.open() as f:
            preds = json.load(f)
        # generations: list of SMILES strings
        if "generations" in preds:
            results["metrics"]["chem_validity"] = metrics.chem_validity(preds["generations"])
            results["metrics"]["novelty_tanimoto"] = metrics.novelty_tanimoto(preds["generations"])
            results["metrics"]["admet_pass_rate"] = metrics.admet_pass_rate(preds["generations"])
        if "mic_predictions" in preds:
            results["metrics"]["mic_rmse_holdout"] = metrics.mic_rmse(preds["mic_predictions"])
        if "tool_replay" in preds:
            results["metrics"]["tool_call_accuracy"] = metrics.tool_call_accuracy(preds["tool_replay"])
        if "jailbreak_responses" in preds:
            results["metrics"]["refusal_robustness"] = metrics.refusal_robustness(preds["jailbreak_responses"])
        if "reasoning_records" in preds:
            results["metrics"]["reasoning_faithfulness"] = metrics.reasoning_faithfulness(preds["reasoning_records"])
        print(f"\nResults summary:")
        for k, v in results["metrics"].items():
            print(f"  {k}: {v}")
    else:
        print("\nUsage: --baseline_only OR --predictions FILE")
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
