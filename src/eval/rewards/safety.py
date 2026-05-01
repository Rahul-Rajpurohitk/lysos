"""Reward: hemolysis safety (inverse of predicted hemolytic activity).

Hemolysis = the molecule lyses red blood cells, typically a deal-breaker
for antimicrobial peptides. We want LOW hemolysis, so reward = 1 - p(hemolysis).

Two implementations:
  1. heuristic_hemolysis — descriptor-based proxy (cheap, decent for screen)
  2. ml_hemolysis — pluggable HF model (TODO: train + ship a real predictor)

The composite reward uses heuristic by default; swap in ml_hemolysis once
we have a trained predictor on HemoPI / DBAASP-Hemo data.
"""

from __future__ import annotations

import logging

from . import extract_smiles

log = logging.getLogger(__name__)


def hemolysis_inverse(samples: list[str], **_) -> list[float]:
    """Reward = 1 - heuristic_hemolysis_probability ∈ [0, 1]."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Crippen, Descriptors, Lipinski

    RDLogger.DisableLog("rdApp.*")

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
            # Heuristic: hemolytic compounds tend to be:
            #   - highly amphipathic (logP > 4 + many H-bond donors)
            #   - very large (MW > 700)
            #   - many positive charges (proxied via NHs)
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
            risk = max(0.0, min(1.0, risk))
            out.append(1.0 - risk)
        except Exception:  # noqa: BLE001
            out.append(0.0)
    return out


# ---------------------------------------------------------------------------
# ML-based hemolysis predictor — TODO: train + plug in
# ---------------------------------------------------------------------------

_ml_hemolysis_model = None


def ml_hemolysis(samples: list[str], **_) -> list[float]:
    """Wrapper around a (TODO) trained hemolysis predictor.

    Once we ship a fine-tuned hemolysis predictor on HemoPI/DBAASP-Hemo
    data, swap this in via the Stage 3 config.
    """
    global _ml_hemolysis_model
    if _ml_hemolysis_model is None:
        log.warning("ml_hemolysis predictor not yet trained — falling back to heuristic")
    return hemolysis_inverse(samples)
