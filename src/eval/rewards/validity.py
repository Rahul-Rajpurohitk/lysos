"""Reward: SMILES validity.

A generated string scores 1.0 if rdkit can parse it as a valid molecule, else 0.0.
This is the cheapest, most fundamental reward — anchors training away from
syntactic gibberish.
"""

from __future__ import annotations

from . import extract_smiles


def smiles_valid(samples: list[str], **_) -> list[float]:
    """1.0 if extractable + parseable SMILES, else 0.0."""
    from rdkit import Chem
    from rdkit import RDLogger

    RDLogger.DisableLog("rdApp.*")  # suppress noisy parse warnings

    out = []
    for sample in samples:
        smi = extract_smiles(sample)
        if smi is None:
            out.append(0.0)
            continue
        mol = Chem.MolFromSmiles(smi)
        out.append(1.0 if mol is not None else 0.0)
    return out
