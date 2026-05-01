"""Reward: Synthetic Accessibility (SA) score.

SA score (Ertl & Schuffenhauer, J. Cheminform. 2009) estimates how easy a
molecule is to synthesize, on a 1 (very easy) to 10 (very hard) scale.

We invert and rescale to [0, 1] so higher reward = easier to synthesize.
"""

from __future__ import annotations

import logging

from . import extract_smiles

log = logging.getLogger(__name__)


def _try_load_sa_scorer():
    """SA scorer ships with rdkit-contrib but isn't always on path. Lazy load."""
    try:
        # rdkit-contrib path
        import sys
        from rdkit.Chem import RDConfig
        sa_dir = f"{RDConfig.RDContribDir}/SA_Score"
        if sa_dir not in sys.path:
            sys.path.append(sa_dir)
        import sascorer  # noqa: F401
        return sascorer
    except Exception as exc:  # noqa: BLE001
        log.warning("sascorer not available: %s", exc)
        return None


_SA = _try_load_sa_scorer()


def sa_score(samples: list[str], **_) -> list[float]:
    """Reward in [0, 1]. SA=1 (easy) -> 1.0, SA=10 (hard) -> 0.0."""
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")

    if _SA is None:
        # Fallback: heuristic — penalize molecules with too many rings or fused systems
        return [_heuristic_synth(s) for s in samples]

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
            sa = _SA.calculateScore(mol)
            # SA is in [1, 10]. Map to reward in [0, 1] with 1 being easy.
            reward = max(0.0, min(1.0, (10.0 - sa) / 9.0))
            out.append(reward)
        except Exception:  # noqa: BLE001
            out.append(0.0)
    return out


def _heuristic_synth(sample: str) -> float:
    """Cheap fallback if sascorer is missing — based on ring count + size."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Descriptors

    RDLogger.DisableLog("rdApp.*")

    smi = extract_smiles(sample)
    if smi is None:
        return 0.0
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return 0.0
    # Penalize: many rings, very high MW, many stereocenters
    n_rings = Descriptors.RingCount(mol) or 0
    mw = Descriptors.MolWt(mol)
    n_stereo = sum(1 for atom in mol.GetAtoms() if atom.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED)
    score = 1.0
    if n_rings > 6:
        score -= 0.2 * (n_rings - 6)
    if mw > 700:
        score -= 0.3
    if n_stereo > 5:
        score -= 0.1 * (n_stereo - 5)
    return max(0.0, min(1.0, score))
