"""Reward: predicted antibacterial activity (MIC).

MIC = Minimum Inhibitory Concentration. Lower is better (less drug
needed to inhibit growth). We map predicted log(MIC) into a reward in [0, 1]:

    log_mic <= log_mic_strong (e.g. log10(2 µg/mL)) -> 1.0
    log_mic >= log_mic_weak   (e.g. log10(64 µg/mL))-> 0.0
    in between: linear interpolation

Two implementations:
  1. heuristic_predict_mic — Lipophilicity-based proxy (cheap, weak signal)
  2. ml_predict_mic        — pluggable HF model (TODO: train + ship)

The Stage 3 config currently uses predict_mic, which dispatches to ml when
available, heuristic otherwise.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from . import extract_smiles

log = logging.getLogger(__name__)

# Default targets for AMR — strong = clinical breakpoint MIC, weak = "barely active"
LOG_MIC_STRONG = 0.30  # log10(2)
LOG_MIC_WEAK = 1.81    # log10(64)


def predict_mic(samples: list[str], target_pathogen: str = "MRSA", **_) -> list[float]:
    """Top-level dispatch: ML predictor if available, else heuristic."""
    model = _load_ml_model_if_available()
    if model is not None:
        return _ml_predict_mic(samples, model=model, target_pathogen=target_pathogen)
    return heuristic_predict_mic(samples, target_pathogen=target_pathogen)


# ---------------------------------------------------------------------------
# Heuristic predictor
# ---------------------------------------------------------------------------


def heuristic_predict_mic(samples: list[str], target_pathogen: str = "MRSA", **_) -> list[float]:
    """Cheap proxy: scores molecules by combination of:
      - molecular weight (200-700 Da is sweet spot)
      - logP (1-4 is sweet spot for membrane-active drugs)
      - presence of antibacterial scaffolds (heuristic SMARTS)

    Returns reward in [0, 1]. Real ML predictor will replace this.
    """
    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem, Crippen, Descriptors

    RDLogger.DisableLog("rdApp.*")

    # Simple SMARTS for known antibiotic-relevant scaffolds (β-lactam, fluoroquinolone, etc.)
    scaffolds = [
        Chem.MolFromSmarts("[N&R]1[C&R](=O)[C&R][C&R]1"),  # β-lactam ring
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

            # MW desirability — peaks around 350-450 Da
            mw_score = 1.0 - min(abs(mw - 400) / 300, 1.0)
            # logP desirability — peaks around 2-3
            logp_score = 1.0 - min(abs(logp - 2.5) / 4, 1.0)
            # Scaffold bonus
            scaffold_bonus = 0.1 * sum(1 for s in scaffolds if s and mol.HasSubstructMatch(s))

            score = 0.5 * mw_score + 0.4 * logp_score + scaffold_bonus
            out.append(max(0.0, min(1.0, score)))
        except Exception:  # noqa: BLE001
            out.append(0.0)
    return out


# ---------------------------------------------------------------------------
# ML predictor (placeholder — will plug in trained MIC predictor)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_ml_model_if_available():
    """Return ML model object if trained predictor exists, else None.

    TODO once Stage 2 specialization is done: load the pathogen-specific
    MIC predictor head from rahul24raj/lysos-mic-predictor.
    """
    model_path = os.environ.get("LYSOS_MIC_PREDICTOR")
    if not model_path:
        return None
    try:
        # Future: load HF model
        log.info("ML MIC predictor would load from %s (not implemented yet)", model_path)
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to load ML MIC predictor: %s — falling back to heuristic", exc)
        return None


def _ml_predict_mic(samples: list[str], *, model, target_pathogen: str) -> list[float]:
    """Real ML predictor. Stub for now."""
    log.info("ml_predict_mic stub for pathogen=%s", target_pathogen)
    return heuristic_predict_mic(samples, target_pathogen=target_pathogen)
