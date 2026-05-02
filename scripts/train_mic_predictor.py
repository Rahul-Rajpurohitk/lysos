"""Train an ML-based MIC predictor for the Stage 3 RL reward.

Replaces the heuristic in `src/eval/rewards/activity.py` with a real model
that takes a SMILES + pathogen short-code and outputs predicted log10(MIC).

Architecture (kept simple + reproducible):
  - Featurize SMILES → Morgan fingerprint (radius 2, 2048 bits) — RDKit
  - Plus 8 pathogen-onehot dimensions
  - XGBoost regressor on `mic_log_ug_per_ml`
  - 5-fold scaffold-split cross-validation for honest eval

Why this matters:
  - Stage 3 GRPO uses predicted MIC as 35-40% of the reward.
  - A heuristic that just rewards heavy molecules teaches the policy to
    generate fat, undruglike compounds. We saw this in early dry-runs.
  - A real model trained on 14,971 unique antibacterial measurements
    gives proper signal so RL converges to potent + drug-like (not just fat).

Output:
  data/processed/mic_predictor.joblib   — sklearn-style joblib bundle:
      {
        "model": XGBRegressor,
        "pathogen_index": {"MRSA": 0, ...},
        "fp_radius": 2,
        "fp_bits": 2048,
        "metrics": {"mae": ..., "r2": ..., "rmse": ..., "n_train": ...,
                    "scaffold_cv": [...]},
        "trained_at": iso8601,
        "git_sha": str,
      }

Usage:

    pip install xgboost scikit-learn rdkit
    python scripts/train_mic_predictor.py
    python scripts/train_mic_predictor.py --quick   # fast 1-fold, no CV
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] mic | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mic")

PATHOGEN_LIST = [
    "MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
    "Abaum", "Paer", "VRE", "NGono",
]
PATHOGEN_INDEX = {p: i for i, p in enumerate(PATHOGEN_LIST)}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path,
                   default=Path("data/raw/chembl_antibiotics.canonical.csv"),
                   help="Canonicalized ChEMBL CSV (run audit_and_canonicalize first)")
    p.add_argument("--output", type=Path,
                   default=Path("data/processed/mic_predictor.joblib"))
    p.add_argument("--fp-bits", type=int, default=2048)
    p.add_argument("--fp-radius", type=int, default=2)
    p.add_argument("--n-estimators", type=int, default=500)
    p.add_argument("--max-depth", type=int, default=6)
    p.add_argument("--lr", type=float, default=0.05)
    p.add_argument("--cv-folds", type=int, default=5)
    p.add_argument("--quick", action="store_true",
                   help="Skip CV, train on full data only (faster)")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _featurize(smiles_list, pathogens, fp_bits, fp_radius):
    """SMILES + pathogen → (fp_bits + 8) feature matrix."""
    import numpy as np
    from rdkit import Chem
    from rdkit.Chem import AllChem

    n_total = fp_bits + len(PATHOGEN_LIST)
    out = np.zeros((len(smiles_list), n_total), dtype=np.float32)
    drop_idx = []
    for i, (smi, path) in enumerate(zip(smiles_list, pathogens)):
        mol = Chem.MolFromSmiles(str(smi))
        if mol is None:
            drop_idx.append(i)
            continue
        fp = AllChem.GetMorganFingerprintAsBitVect(mol, fp_radius, nBits=fp_bits)
        # to numpy
        arr = np.zeros((fp_bits,), dtype=np.uint8)
        from rdkit.DataStructs import ConvertToNumpyArray
        ConvertToNumpyArray(fp, arr)
        out[i, :fp_bits] = arr.astype(np.float32)
        # one-hot pathogen
        if path in PATHOGEN_INDEX:
            out[i, fp_bits + PATHOGEN_INDEX[path]] = 1.0
    return out, drop_idx


def _scaffold(smi: str) -> str:
    """Bemis-Murcko scaffold for safe scaffold-split CV."""
    try:
        from rdkit import Chem
        from rdkit.Chem.Scaffolds import MurckoScaffold
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            return ""
        return Chem.MolToSmiles(MurckoScaffold.GetScaffoldForMol(mol))
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    args = parse_args()

    try:
        import numpy as np
        import pandas as pd
        from sklearn.metrics import mean_absolute_error, r2_score, mean_squared_error
        from sklearn.model_selection import GroupKFold
        import xgboost as xgb
        import joblib
    except ImportError as exc:
        log.error("Missing deps: %s. pip install xgboost scikit-learn joblib rdkit", exc)
        return 2

    if not args.input.exists():
        log.error("Input %s not found. Run scripts/audit_and_canonicalize.py "
                  "and ensure data/raw/chembl_antibiotics.canonical.csv exists.",
                  args.input)
        return 1

    log.info("Loading %s ...", args.input)
    df = pd.read_csv(args.input, low_memory=False)
    df = df.dropna(subset=["smiles", "mic_log_ug_per_ml", "pathogen_short"])
    df["mic_log_ug_per_ml"] = pd.to_numeric(df["mic_log_ug_per_ml"], errors="coerce")
    df = df.dropna(subset=["mic_log_ug_per_ml"])
    # Keep only the 8 priority pathogens
    df = df[df["pathogen_short"].isin(PATHOGEN_INDEX)]
    # Clip extreme MIC values (likely measurement error)
    df = df[(df["mic_log_ug_per_ml"] >= -3) & (df["mic_log_ug_per_ml"] <= 4)]
    log.info("After cleaning: %d (smiles, pathogen, mic) tuples",  len(df))
    log.info("Pathogen distribution:")
    for p, n in df["pathogen_short"].value_counts().items():
        log.info("  %-12s %5d", p, n)

    df = df.reset_index(drop=True)
    log.info("Featurizing %d rows (Morgan radius=%d, bits=%d)...",
             len(df), args.fp_radius, args.fp_bits)
    t0 = time.time()
    X, drop = _featurize(
        df["smiles"].tolist(),
        df["pathogen_short"].tolist(),
        args.fp_bits, args.fp_radius,
    )
    log.info("  featurized in %.1fs (%d unparseable dropped)", time.time() - t0, len(drop))
    if drop:
        keep = [i for i in range(len(df)) if i not in set(drop)]
        df = df.iloc[keep].reset_index(drop=True)
        X = X[keep]
    y = df["mic_log_ug_per_ml"].to_numpy(dtype=np.float32)
    assert len(df) == X.shape[0] == len(y), (
        f"len mismatch after featurize: df={len(df)} X={X.shape[0]} y={len(y)}"
    )

    metrics: dict = {
        "n_train": int(len(y)),
        "fp_bits": args.fp_bits,
        "fp_radius": args.fp_radius,
        "label_range": [float(y.min()), float(y.max())],
        "label_mean": float(y.mean()),
        "label_std": float(y.std()),
    }

    cv_results = []
    if not args.quick and args.cv_folds > 1:
        log.info("Scaffold-split %d-fold CV ...", args.cv_folds)
        df["scaffold"] = df["smiles"].map(_scaffold)
        # Replace any empty scaffold with a unique key so they form their own
        # tiny groups (won't dominate)
        for i, s in enumerate(df["scaffold"]):
            if not s:
                df.at[i, "scaffold"] = f"_no_scaffold_{i}"
        gkf = GroupKFold(n_splits=args.cv_folds)
        for fold, (tr, te) in enumerate(gkf.split(X, y, df["scaffold"])):
            t1 = time.time()
            model = xgb.XGBRegressor(
                n_estimators=args.n_estimators,
                max_depth=args.max_depth,
                learning_rate=args.lr,
                tree_method="hist",
                random_state=args.seed,
                n_jobs=-1,
            )
            model.fit(X[tr], y[tr])
            yhat = model.predict(X[te])
            mae = float(mean_absolute_error(y[te], yhat))
            r2 = float(r2_score(y[te], yhat))
            rmse = float(np.sqrt(mean_squared_error(y[te], yhat)))
            log.info("  fold %d: n_train=%d n_test=%d MAE=%.3f R²=%.3f RMSE=%.3f (%.0fs)",
                     fold + 1, len(tr), len(te), mae, r2, rmse, time.time() - t1)
            cv_results.append({"fold": fold + 1, "mae": mae, "r2": r2, "rmse": rmse,
                               "n_train": int(len(tr)), "n_test": int(len(te))})

        if cv_results:
            mean_mae = float(np.mean([r["mae"] for r in cv_results]))
            mean_r2 = float(np.mean([r["r2"] for r in cv_results]))
            log.info("=" * 60)
            log.info("CV mean MAE = %.3f log10(µg/mL)   R² = %.3f", mean_mae, mean_r2)
            metrics["cv_mean_mae"] = mean_mae
            metrics["cv_mean_r2"] = mean_r2
            metrics["scaffold_cv"] = cv_results

    log.info("Training final model on full data ...")
    t1 = time.time()
    final = xgb.XGBRegressor(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        learning_rate=args.lr,
        tree_method="hist",
        random_state=args.seed,
        n_jobs=-1,
    )
    final.fit(X, y)
    yhat = final.predict(X)
    metrics["train_mae"] = float(mean_absolute_error(y, yhat))
    metrics["train_r2"] = float(r2_score(y, yhat))
    metrics["train_rmse"] = float(np.sqrt(mean_squared_error(y, yhat)))
    log.info("  train MAE=%.3f R²=%.3f (%.0fs)",
             metrics["train_mae"], metrics["train_r2"], time.time() - t1)

    bundle = {
        "model": final,
        "pathogen_index": PATHOGEN_INDEX,
        "fp_radius": args.fp_radius,
        "fp_bits": args.fp_bits,
        "metrics": metrics,
        "trained_at": dt.datetime.utcnow().isoformat() + "Z",
        "git_sha": _git_sha(),
        "inputs_path": str(args.input),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, args.output, compress=3)
    log.info("Wrote %s (%.1f KB)", args.output,
             args.output.stat().st_size / 1024)
    log.info("Reward backbone:")
    log.info("  CV MAE  = %.3f log10(µg/mL)" % metrics.get("cv_mean_mae", 0))
    log.info("  CV R²   = %.3f" % metrics.get("cv_mean_r2", 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
