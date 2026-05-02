"""Reward: hemolysis safety (inverse of predicted hemolytic activity).

Hemolysis = the molecule lyses red blood cells, typically a deal-breaker
for antimicrobial peptides. We want LOW hemolysis, so reward = 1 - p(hemolysis).

Two implementations:
  1. ml_hemolysis_inverse — XGBoost trained on DBAASP `hemolytic_int` labels
                             (CV AUROC ≈ 0.81). Used by default when the
                             trained joblib bundle exists.
  2. heuristic_hemolysis_inverse — descriptor-based proxy (cheap, fallback).

The composite reward dispatches via `hemolysis_inverse` which picks ML when
available, heuristic otherwise.

The ML predictor lives at `data/processed/hemolysis_predictor.joblib`.
Train/refresh it with `scripts/train_hemolysis_predictor.py`.

Note on input handling: `samples` may contain SMILES (small molecules)
OR peptide sequences. The ML predictor was trained on peptides; for
SMILES inputs we delegate to the heuristic.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path

from . import extract_smiles

log = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = "data/processed/hemolysis_predictor.joblib"
SEQUENCE_RE = re.compile(r"Sequence:\s*([A-Z]{5,})")
VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")


def hemolysis_inverse(samples: list[str], **_) -> list[float]:
    """Default entry — dispatches to ML when available, heuristic otherwise."""
    bundle = _load_ml_bundle()
    out: list[float] = []
    for sample in samples:
        seq = _extract_peptide(sample)
        if seq and bundle is not None:
            out.append(_ml_score_one(seq, bundle))
        else:
            out.append(_heuristic_score_one(sample))
    return out


def _extract_peptide(text: str) -> str | None:
    """Pull a peptide sequence out of `Sequence: AAAA...` or raw."""
    if not text:
        return None
    m = SEQUENCE_RE.search(text)
    if m:
        seq = m.group(1).strip().upper()
    else:
        # Maybe it's a bare amino-acid string
        candidate = text.strip().upper()
        if 5 <= len(candidate) <= 100 and set(candidate).issubset(VALID_AA):
            seq = candidate
        else:
            return None
    if 5 <= len(seq) <= 200 and set(seq).issubset(VALID_AA):
        return seq
    return None


@lru_cache(maxsize=1)
def _load_ml_bundle():
    path = Path(os.environ.get("LYSOS_HEMOLYSIS_PREDICTOR", DEFAULT_MODEL_PATH))
    if not path.exists():
        return None
    try:
        import joblib
        bundle = joblib.load(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not load hemolysis predictor at %s: %s", path, exc)
        return None
    metrics = bundle.get("metrics", {})
    log.info(
        "Loaded hemolysis predictor (n=%d, CV AUROC=%.3f, Acc=%.3f)",
        metrics.get("n_train", 0),
        metrics.get("cv_auroc", float("nan")),
        metrics.get("cv_accuracy", float("nan")),
    )
    return bundle


def _featurize_peptide(seq: str):
    """Match the feature schema in scripts/train_hemolysis_predictor.py."""
    import numpy as np
    HYDRO = {
        "A":  0.62, "R": -2.53, "N": -0.78, "D": -0.90, "C":  0.29,
        "Q": -0.85, "E": -0.74, "G":  0.48, "H": -0.40, "I":  1.38,
        "L":  1.06, "K": -1.50, "M":  0.64, "F":  1.19, "P":  0.12,
        "S": -0.18, "T": -0.05, "W":  0.81, "Y":  0.26, "V":  1.08,
    }
    AA = sorted(HYDRO.keys())
    seq = seq.upper()
    L = len(seq)
    comp = [seq.count(a) / L for a in AA]
    charge = (
        seq.count("K") + seq.count("R")
        + 0.1 * seq.count("H")
        - seq.count("D") - seq.count("E")
    )
    hydro_frac = sum(1 for a in seq if HYDRO[a] > 0) / L
    angle = 1.7453
    sum_cos = sum(HYDRO[a] * float(np.cos(angle * i)) for i, a in enumerate(seq))
    sum_sin = sum(HYDRO[a] * float(np.sin(angle * i)) for i, a in enumerate(seq))
    hydro_mom = float(np.sqrt(sum_cos ** 2 + sum_sin ** 2)) / L
    avg_hydro = sum(HYDRO[a] for a in seq) / L
    amid = 1.0 if seq.endswith(("K", "R")) else 0.0
    feats = comp + [
        charge / max(L, 1), charge, hydro_frac, hydro_mom,
        avg_hydro, L, amid, seq.count("C") / L,
    ]
    return np.asarray(feats, dtype=np.float32).reshape(1, -1)


def _ml_score_one(seq: str, bundle) -> float:
    """ML prediction → reward = 1 - p(hemolytic)."""
    X = _featurize_peptide(seq)
    p_hemo = float(bundle["model"].predict_proba(X)[0, 1])
    return 1.0 - p_hemo


def _heuristic_score_one(sample: str) -> float:
    """Fallback: descriptor heuristic for SMILES-bearing or unparsed inputs."""
    try:
        from rdkit import Chem, RDLogger
        from rdkit.Chem import Crippen, Descriptors, Lipinski
    except ImportError:
        return 0.5  # neutral when rdkit missing

    RDLogger.DisableLog("rdApp.*")
    smi = extract_smiles(sample)
    if smi is None:
        return 0.0
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return 0.0
    try:
        mw = Descriptors.MolWt(mol)
        logp = Crippen.MolLogP(mol)
        hbd = Lipinski.NumHDonors(mol)
        tpsa = Descriptors.TPSA(mol)
        risk = 0.0
        if logp > 4:
            risk += 0.2 * min((logp - 4), 3) / 3
        if mw > 700:
            risk += 0.2 * min((mw - 700) / 500, 1.0)
        if hbd > 6:
            risk += 0.2 * min((hbd - 6) / 4, 1.0)
        if tpsa < 60:
            risk += 0.2 * min((60 - tpsa) / 60, 1.0)
        return 1.0 - max(0.0, min(1.0, risk))
    except Exception:  # noqa: BLE001
        return 0.0


# Back-compat alias (configs reference this name)
def ml_hemolysis(samples: list[str], **_) -> list[float]:
    return hemolysis_inverse(samples)
