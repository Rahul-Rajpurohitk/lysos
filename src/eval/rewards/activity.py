"""Reward: predicted antibacterial activity (MIC).

MIC = Minimum Inhibitory Concentration. Lower is better (less drug needed
to inhibit growth). We map predicted log(MIC) into a reward in [0, 1]:

    log_mic <= log_mic_strong (e.g. log10(2 µg/mL))  → 1.0
    log_mic >= log_mic_weak   (e.g. log10(64 µg/mL)) → 0.0
    in between: linear interpolation

Two implementations:
  1. ml_predict_mic        — XGBoost on Morgan fingerprints, trained on
                             ChEMBL bacterial activity (scaffold-CV MAE 0.62
                             log10(µg/mL), R² 0.56). Default.
  2. heuristic_predict_mic — Lipophilicity + scaffold heuristic. Used only
                             as a fallback if the trained model is missing.

The Stage 3 config calls `predict_mic`, which dispatches to ML when the
trained joblib bundle exists at `data/processed/mic_predictor.joblib`
(or LYSOS_MIC_PREDICTOR env var), heuristic otherwise.

To re-train the ML predictor:

    python scripts/train_mic_predictor.py
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from . import extract_smiles

log = logging.getLogger(__name__)

# Clinical breakpoint thresholds — MIC ≤ 2 µg/mL is generally "potent"
LOG_MIC_STRONG = 0.30  # log10(2)
LOG_MIC_WEAK = 1.81    # log10(64)

DEFAULT_MODEL_PATH = "data/processed/mic_predictor.joblib"


def predict_mic(samples: list[str], target_pathogen: str = "MRSA", **_) -> list[float]:
    """Top-level dispatch: ML predictor if available, else heuristic."""
    bundle = _load_ml_bundle()
    if bundle is not None:
        return _ml_predict_mic(
            samples, bundle=bundle, target_pathogen=target_pathogen,
        )
    log.warning(
        "ML MIC predictor not loaded — falling back to heuristic. "
        "Train it with `python scripts/train_mic_predictor.py`."
    )
    return heuristic_predict_mic(samples, target_pathogen=target_pathogen)


def _log_mic_to_reward(log_mic: float) -> float:
    """Map log10(MIC µg/mL) → reward in [0, 1]. Lower MIC = higher reward."""
    if log_mic <= LOG_MIC_STRONG:
        return 1.0
    if log_mic >= LOG_MIC_WEAK:
        return 0.0
    # Linear interpolation
    return float(1.0 - (log_mic - LOG_MIC_STRONG) / (LOG_MIC_WEAK - LOG_MIC_STRONG))


# ---------------------------------------------------------------------------
# ML predictor (XGBoost on Morgan fingerprints + pathogen one-hot)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_ml_bundle():
    """Load the MIC predictor joblib bundle. Returns None if missing."""
    path = Path(os.environ.get("LYSOS_MIC_PREDICTOR", DEFAULT_MODEL_PATH))
    if not path.exists():
        return None
    try:
        import joblib
        bundle = joblib.load(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not load MIC predictor at %s: %s", path, exc)
        return None
    metrics = bundle.get("metrics", {})
    log.info(
        "Loaded MIC predictor (n_train=%d, CV MAE=%.3f, R²=%.3f, sha=%s)",
        metrics.get("n_train", 0),
        metrics.get("cv_mean_mae", float("nan")),
        metrics.get("cv_mean_r2", float("nan")),
        bundle.get("git_sha", "?"),
    )
    return bundle


def _featurize_one(smi: str, pathogen_short: str, bundle) -> "Optional[np.ndarray]":
    """SMILES + pathogen → feature vector. None if SMILES unparseable."""
    import numpy as np
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from rdkit.DataStructs import ConvertToNumpyArray

    fp_bits = bundle["fp_bits"]
    fp_radius = bundle["fp_radius"]
    pathogen_index = bundle["pathogen_index"]

    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return None
    fp = AllChem.GetMorganFingerprintAsBitVect(mol, fp_radius, nBits=fp_bits)
    arr = np.zeros((fp_bits,), dtype=np.uint8)
    ConvertToNumpyArray(fp, arr)
    n_path = len(pathogen_index)
    feat = np.zeros((fp_bits + n_path,), dtype=np.float32)
    feat[:fp_bits] = arr.astype(np.float32)
    if pathogen_short in pathogen_index:
        feat[fp_bits + pathogen_index[pathogen_short]] = 1.0
    return feat


def _ml_predict_mic(samples: list[str], *, bundle, target_pathogen: str) -> list[float]:
    """Real ML predictor. Returns reward ∈ [0, 1] per sample."""
    import numpy as np
    from rdkit import RDLogger
    RDLogger.DisableLog("rdApp.*")

    feats: list = []
    valid_idx: list[int] = []
    out = [0.0] * len(samples)

    for i, sample in enumerate(samples):
        smi = extract_smiles(sample)
        if smi is None:
            continue
        f = _featurize_one(smi, target_pathogen, bundle)
        if f is None:
            continue
        feats.append(f)
        valid_idx.append(i)

    if not feats:
        return out

    X = np.vstack(feats)
    log_mic_pred = bundle["model"].predict(X)
    for k, i in enumerate(valid_idx):
        out[i] = _log_mic_to_reward(float(log_mic_pred[k]))
    return out


# ---------------------------------------------------------------------------
# Heuristic predictor (fallback only)
# ---------------------------------------------------------------------------


def heuristic_predict_mic(samples: list[str], target_pathogen: str = "MRSA", **_) -> list[float]:
    """Lipophilicity-based proxy. Used only as fallback if the trained
    ML predictor is missing."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Crippen, Descriptors

    RDLogger.DisableLog("rdApp.*")

    scaffolds = [
        Chem.MolFromSmarts("[N&R]1[C&R](=O)[C&R][C&R]1"),  # β-lactam
        Chem.MolFromSmarts("c1cc2ncc(C(=O)O)cc2cc1"),       # quinolone-ish
        Chem.MolFromSmarts("c1cnc2[nH]cnc2c1"),             # purine-like
        Chem.MolFromSmarts("c1ncccn1"),                      # pyrimidine
    ]

    out = []
    for sample in samples:
        smi = extract_smiles(sample)
        if smi is None:
            out.append(0.0)
            continue
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            out.append(0.0)
            continue
        try:
            mw = Descriptors.MolWt(mol)
            logp = Crippen.MolLogP(mol)
            mw_score = 1.0 - min(abs(mw - 400) / 300, 1.0)
            logp_score = 1.0 - min(abs(logp - 2.5) / 4, 1.0)
            scaffold_bonus = 0.1 * sum(
                1 for s in scaffolds if s and mol.HasSubstructMatch(s)
            )
            score = 0.5 * mw_score + 0.4 * logp_score + scaffold_bonus
            out.append(max(0.0, min(1.0, score)))
        except Exception:  # noqa: BLE001
            out.append(0.0)
    return out
