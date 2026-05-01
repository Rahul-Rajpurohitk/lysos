"""Reward: Quantitative Estimate of Drug-likeness (QED).

QED scores each molecule on [0, 1] based on 8 desirability functions
covering molecular weight, logP, hydrogen bond donors/acceptors, polar
surface area, rotatable bonds, aromatic rings, and structural alerts.
Bickerton et al., Nature Chemistry 2012.
"""

from __future__ import annotations

from . import extract_smiles


def qed_score(samples: list[str], **_) -> list[float]:
    """Returns QED score in [0, 1] for each sample. Invalid -> 0.0."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import QED

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
            out.append(float(QED.qed(mol)))
        except Exception:  # noqa: BLE001
            out.append(0.0)
    return out


def lipinski_pass(samples: list[str], **_) -> list[float]:
    """1.0 if Lipinski's Rule of 5 passes (≤1 violation allowed), else 0.0."""
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
            mw = Descriptors.MolWt(mol)
            logp = Crippen.MolLogP(mol)
            hbd = Lipinski.NumHDonors(mol)
            hba = Lipinski.NumHAcceptors(mol)
            violations = 0
            if mw > 500:
                violations += 1
            if logp > 5:
                violations += 1
            if hbd > 5:
                violations += 1
            if hba > 10:
                violations += 1
            out.append(1.0 if violations <= 1 else 0.0)
        except Exception:  # noqa: BLE001
            out.append(0.0)
    return out
