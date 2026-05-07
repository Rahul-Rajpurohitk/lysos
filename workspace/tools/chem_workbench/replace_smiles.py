"""replace_smiles — agent fast-path for writing a whole structure in one shot.

Mirrors POST /workbench/molecule/replace.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..base import tool


class ReplaceSmilesInput(BaseModel):
    smiles: str = Field(..., description="Complete SMILES to replace the candidate")
    actor: str = Field("agent", description="Source of the replace (user/agent)")


class ReplaceSmilesOutput(BaseModel):
    smiles: str
    n_atoms: int
    n_bonds: int
    n_rings: int
    actor: str


@tool(
    name="replace_smiles",
    description=(
        "Replace the entire candidate with a complete SMILES string. The "
        "agent uses this fast-path to write structures atom-graph-style "
        "instead of editing atom-by-atom. Validates with RDKit and returns "
        "the canonical form."
    ),
    category="chem_workbench",
    input_model=ReplaceSmilesInput,
    output_model=ReplaceSmilesOutput,
    expected_duration_ms=40,
    tags=("chemistry", "rdkit", "build"),
)
def replace_smiles(smiles: str, actor: str = "agent") -> ReplaceSmilesOutput:
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError({"code": "unparseable_smiles", "message": f"unparseable SMILES: {smiles}"})
    canonical = Chem.MolToSmiles(mol, canonical=True)
    return ReplaceSmilesOutput(
        smiles=canonical,
        n_atoms=mol.GetNumAtoms(),
        n_bonds=mol.GetNumBonds(),
        n_rings=mol.GetRingInfo().NumRings(),
        actor=actor,
    )
