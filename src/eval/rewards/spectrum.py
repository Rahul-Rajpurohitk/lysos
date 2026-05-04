"""Reward: spectrum_breadth — predicted active across multiple pathogens.

Calls the MIC predictor against ALL 8 priority pathogens and returns 1.0 if
the candidate is predicted active (log10(MIC) < threshold) against ≥
`min_pathogens_active` of them. Encourages broad-spectrum design.
"""
from __future__ import annotations

import logging
from pathlib import Path
from . import extract_smiles

log = logging.getLogger(__name__)
_PREDICTOR = None
_DEFAULT_PATHOGENS = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
                      "Abaum", "Paer", "VRE", "NGono"]


def _load_predictor():
    global _PREDICTOR
    if _PREDICTOR is not None:
        return _PREDICTOR
    p = Path("data/processed/mic_predictor.joblib")
    if not p.exists():
        log.warning("MIC predictor not found at %s; spectrum reward will return 0.0", p)
        _PREDICTOR = "MISSING"
        return _PREDICTOR
    try:
        import joblib
        bundle = joblib.load(p)
        _PREDICTOR = bundle
        return _PREDICTOR
    except Exception as e:
        log.warning("Failed to load MIC predictor: %s", e)
        _PREDICTOR = "MISSING"
        return _PREDICTOR


def _predict_log_mic(smiles: str, pathogen: str) -> float | None:
    predictor = _load_predictor()
    if predictor == "MISSING": return None
    from rdkit import Chem
    from rdkit.Chem import AllChem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None: return None
    fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, 2048)
    import numpy as np
    fp_arr = np.zeros((2048,), dtype=int)
    from rdkit.DataStructs import ConvertToNumpyArray
    ConvertToNumpyArray(fp, fp_arr)
    pathogens = predictor.get("pathogens") or _DEFAULT_PATHOGENS
    if pathogen not in pathogens: return None
    one_hot = np.zeros((len(pathogens),), dtype=int)
    one_hot[pathogens.index(pathogen)] = 1
    X = np.concatenate([fp_arr, one_hot]).reshape(1, -1)
    model = predictor.get("model")
    if model is None: return None
    try:
        return float(model.predict(X)[0])
    except Exception:
        return None


def multi_pathogen_breadth(samples: list[str],
                             pathogens: list[str] | None = None,
                             active_threshold_log_mic: float = 0.7,
                             min_pathogens_active: int = 3, **_) -> list[float]:
    pathogens = pathogens or _DEFAULT_PATHOGENS
    out = []
    for s in samples:
        smi = extract_smiles(s)
        if smi is None:
            out.append(0.0); continue
        n_active = 0
        n_predicted = 0
        for pat in pathogens:
            log_mic = _predict_log_mic(smi, pat)
            if log_mic is None: continue
            n_predicted += 1
            if log_mic < active_threshold_log_mic:
                n_active += 1
        if n_predicted == 0:
            out.append(0.0); continue
        # Score: linear ramp from 0 (zero pathogens active) to 1 (all active),
        # with a step bonus at min_pathogens_active.
        coverage = n_active / max(n_predicted, 1)
        bonus = 0.2 if n_active >= min_pathogens_active else 0.0
        out.append(min(1.0, coverage + bonus))
    return out
