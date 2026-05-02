"""ML hemolysis predictor — replaces the heuristic in `safety.py`.

Trains a binary classifier on DBAASP `hemolytic_int` labels using simple
peptide-sequence features. AMR design needs a clean hemolysis signal
because Stage 3 RL otherwise rewards lipophilic cations (which are also
hemolytic), driving the policy toward a 'lipoamphiphilic-toxic' optimum.

Features (per peptide):
  - amino-acid composition (20 frequencies)
  - net charge at pH 7.4
  - hydrophobic fraction (Eisenberg consensus)
  - sequence length
  - hydrophobic-moment (helical amphipathicity proxy)
  - termini-amidation flag (heuristic — ends in K/R/-NH2)

Output: data/processed/hemolysis_predictor.joblib
  {
    "model": XGBClassifier,
    "feature_names": [...],
    "metrics": {"auroc": ..., "accuracy": ..., "n": ...},
    "trained_at": iso8601,
  }

Usage:

    python scripts/train_hemolysis_predictor.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] hemo | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hemo")


# Eisenberg consensus hydrophobicity scale (kcal/mol)
HYDRO = {
    "A":  0.62, "R": -2.53, "N": -0.78, "D": -0.90, "C":  0.29,
    "Q": -0.85, "E": -0.74, "G":  0.48, "H": -0.40, "I":  1.38,
    "L":  1.06, "K": -1.50, "M":  0.64, "F":  1.19, "P":  0.12,
    "S": -0.18, "T": -0.05, "W":  0.81, "Y":  0.26, "V":  1.08,
}
AA = sorted(HYDRO.keys())


def featurize_one(seq: str) -> "np.ndarray":
    import numpy as np
    seq = seq.upper().strip()
    if not seq or any(a not in HYDRO for a in seq):
        return np.zeros(28, dtype=np.float32)
    L = len(seq)
    # 20 AA composition frequencies
    comp = [seq.count(a) / L for a in AA]
    # net charge at pH 7.4 (K, R = +1; D, E = -1; H ~= 0.1; rest = 0)
    charge = (
        seq.count("K") + seq.count("R")
        + 0.1 * seq.count("H")
        - seq.count("D") - seq.count("E")
    )
    # hydrophobic fraction (positive HYDRO scale)
    hydro_frac = sum(1 for a in seq if HYDRO[a] > 0) / L
    # hydrophobic moment (Eisenberg, alpha-helical assumption: 100° per residue)
    angle = 1.7453  # 100° in radians
    sum_cos = sum(HYDRO[a] * float(np.cos(angle * i)) for i, a in enumerate(seq))
    sum_sin = sum(HYDRO[a] * float(np.sin(angle * i)) for i, a in enumerate(seq))
    hydro_mom = float(np.sqrt(sum_cos ** 2 + sum_sin ** 2)) / L
    # average hydrophobicity (Eisenberg)
    avg_hydro = sum(HYDRO[a] for a in seq) / L
    # termini-amidation heuristic
    amid = 1.0 if seq.endswith(("K", "R")) else 0.0
    feats = comp + [
        charge / max(L, 1),  # charge density
        charge,
        hydro_frac,
        hydro_mom,
        avg_hydro,
        L,
        amid,
        seq.count("C") / L,  # cysteine fraction (S-S bonds)
    ]
    return np.asarray(feats, dtype=np.float32)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=Path("data/raw/dbaasp_amps.csv"))
    p.add_argument("--output", type=Path,
                   default=Path("data/processed/hemolysis_predictor.joblib"))
    p.add_argument("--cv-folds", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    try:
        import numpy as np
        import pandas as pd
        from sklearn.metrics import roc_auc_score, accuracy_score, average_precision_score
        from sklearn.model_selection import StratifiedKFold
        import xgboost as xgb
        import joblib
    except ImportError as exc:
        log.error("Missing deps: %s", exc)
        return 2

    if not args.input.exists():
        log.error("Input %s missing", args.input)
        return 1

    log.info("Loading %s ...", args.input)
    df = pd.read_csv(args.input, low_memory=False)
    df = df.dropna(subset=["sequence", "hemolytic_int"])
    df["hemolytic_int"] = df["hemolytic_int"].astype(int).clip(0, 1)
    df = df.drop_duplicates(subset=["sequence"], keep="first")
    log.info("After dedup: %d unique peptides", len(df))
    log.info("  hemolytic = %d (%.1f%%), non-hemolytic = %d (%.1f%%)",
             int(df["hemolytic_int"].sum()),
             100 * df["hemolytic_int"].mean(),
             int((df["hemolytic_int"] == 0).sum()),
             100 * (df["hemolytic_int"] == 0).mean())

    log.info("Featurizing %d peptides ...", len(df))
    X = np.vstack([featurize_one(s) for s in df["sequence"]])
    y = df["hemolytic_int"].to_numpy()

    log.info("Stratified %d-fold CV ...", args.cv_folds)
    skf = StratifiedKFold(n_splits=args.cv_folds, shuffle=True, random_state=args.seed)
    cv_results = []
    for fold, (tr, te) in enumerate(skf.split(X, y)):
        model = xgb.XGBClassifier(
            n_estimators=400, max_depth=5, learning_rate=0.05,
            tree_method="hist", random_state=args.seed,
            eval_metric="logloss", n_jobs=-1,
        )
        model.fit(X[tr], y[tr])
        p_pred = model.predict_proba(X[te])[:, 1]
        y_pred = (p_pred >= 0.5).astype(int)
        auroc = float(roc_auc_score(y[te], p_pred))
        ap = float(average_precision_score(y[te], p_pred))
        acc = float(accuracy_score(y[te], y_pred))
        cv_results.append({"fold": fold + 1, "auroc": auroc, "accuracy": acc,
                           "ap": ap, "n_train": int(len(tr)), "n_test": int(len(te))})
        log.info("  fold %d: AUROC=%.3f  AP=%.3f  Acc=%.3f  (n_train=%d, n_test=%d)",
                 fold + 1, auroc, ap, acc, len(tr), len(te))

    mean_auroc = float(np.mean([r["auroc"] for r in cv_results]))
    mean_acc = float(np.mean([r["accuracy"] for r in cv_results]))
    mean_ap = float(np.mean([r["ap"] for r in cv_results]))
    log.info("=" * 60)
    log.info("CV mean AUROC=%.3f  AP=%.3f  Acc=%.3f", mean_auroc, mean_ap, mean_acc)

    # Train final on all data
    log.info("Training final on full data ...")
    final = xgb.XGBClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.05,
        tree_method="hist", random_state=args.seed, eval_metric="logloss", n_jobs=-1,
    )
    final.fit(X, y)

    bundle = {
        "model": final,
        "feature_names": [f"aa_{a}" for a in AA] + [
            "charge_density", "charge", "hydro_frac", "hydro_mom",
            "avg_hydro", "length", "amidated", "cys_frac",
        ],
        "metrics": {
            "n_train": int(len(y)),
            "n_pos": int(y.sum()),
            "n_neg": int((y == 0).sum()),
            "cv_auroc": mean_auroc,
            "cv_ap": mean_ap,
            "cv_accuracy": mean_acc,
            "scaffold_cv": cv_results,
        },
        "trained_at": dt.datetime.utcnow().isoformat() + "Z",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, args.output, compress=3)
    log.info("Wrote %s (%.1f KB)", args.output, args.output.stat().st_size / 1024)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
