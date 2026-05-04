"""Compare two molecules — Tanimoto similarity, atom-level diff, score deltas."""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.knowledge.compare_molecules")


class CompareInput(BaseModel):
    smiles_a: str = Field(..., description="First SMILES")
    smiles_b: str = Field(..., description="Second SMILES")
    pathogen: Optional[str] = Field("MRSA", description="For score comparison")


class MoleculeDiff(BaseModel):
    smiles_a: str
    smiles_b: str
    tanimoto_similarity: float
    same_scaffold: bool
    mw_delta: float
    logp_delta: float
    hbd_delta: int
    hba_delta: int
    qed_delta: float
    composite_delta: float
    interpretation: str


@tool(
    description=(
        "Compare two molecules — Tanimoto fingerprint similarity, atom-level "
        "scaffold sameness, descriptor deltas (MW/logP/HBD/HBA/QED), and "
        "composite reward delta."
    ),
    category="knowledge",
    input_model=CompareInput,
    output_model=MoleculeDiff,
    expected_duration_ms=400,
    tags=("knowledge", "compare", "diff"),
)
def compare_molecules(smiles_a: str, smiles_b: str, pathogen: str = "MRSA") -> MoleculeDiff:
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, Descriptors, Lipinski, QED
        from rdkit.Chem.Scaffolds import MurckoScaffold
        from rdkit.DataStructs import TanimotoSimilarity
    except ImportError:
        return MoleculeDiff(
            smiles_a=smiles_a, smiles_b=smiles_b,
            tanimoto_similarity=0.0, same_scaffold=False,
            mw_delta=0.0, logp_delta=0.0, hbd_delta=0, hba_delta=0,
            qed_delta=0.0, composite_delta=0.0,
            interpretation="RDKit not installed.",
        )

    a = Chem.MolFromSmiles(smiles_a)
    b = Chem.MolFromSmiles(smiles_b)
    if a is None or b is None:
        return MoleculeDiff(
            smiles_a=smiles_a, smiles_b=smiles_b,
            tanimoto_similarity=0.0, same_scaffold=False,
            mw_delta=0.0, logp_delta=0.0, hbd_delta=0, hba_delta=0,
            qed_delta=0.0, composite_delta=0.0,
            interpretation="Parse failure on one or both SMILES.",
        )

    fp_a = AllChem.GetMorganFingerprintAsBitVect(a, 2, nBits=2048)
    fp_b = AllChem.GetMorganFingerprintAsBitVect(b, 2, nBits=2048)
    tan = TanimotoSimilarity(fp_a, fp_b)

    sa = MurckoScaffold.GetScaffoldForMol(a)
    sb = MurckoScaffold.GetScaffoldForMol(b)
    same_scaffold = Chem.MolToSmiles(sa) == Chem.MolToSmiles(sb)

    mw_d = Descriptors.MolWt(b) - Descriptors.MolWt(a)
    logp_d = Descriptors.MolLogP(b) - Descriptors.MolLogP(a)
    hbd_d = Lipinski.NumHDonors(b) - Lipinski.NumHDonors(a)
    hba_d = Lipinski.NumHAcceptors(b) - Lipinski.NumHAcceptors(a)
    qed_d = QED.qed(b) - QED.qed(a)

    # Score composite delta if possible
    composite_d = 0.0
    try:
        from ..scoring.score_molecule import score_molecule
        sa_score = score_molecule(smiles_a, pathogen)
        sb_score = score_molecule(smiles_b, pathogen)
        composite_d = sb_score.composite - sa_score.composite
    except Exception as exc:  # noqa: BLE001
        log.warning("composite delta failed: %s", exc)

    if tan >= 0.85:
        interp = f"Very similar molecules (Tanimoto {tan:.2f}); same chemical lineage."
    elif tan >= 0.5:
        interp = f"Related molecules (Tanimoto {tan:.2f}); shared scaffold with substitutional changes."
    else:
        interp = f"Distinct molecules (Tanimoto {tan:.2f}); novel chemical space."

    if abs(composite_d) > 0.05:
        direction = "improved" if composite_d > 0 else "regressed"
        interp += f" Composite reward {direction} by {abs(composite_d):.3f}."

    return MoleculeDiff(
        smiles_a=smiles_a, smiles_b=smiles_b,
        tanimoto_similarity=round(tan, 3),
        same_scaffold=same_scaffold,
        mw_delta=round(mw_d, 1),
        logp_delta=round(logp_d, 2),
        hbd_delta=hbd_d, hba_delta=hba_d,
        qed_delta=round(qed_d, 3),
        composite_delta=round(composite_d, 3),
        interpretation=interp,
    )
