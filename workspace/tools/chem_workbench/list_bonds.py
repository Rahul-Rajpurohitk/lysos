"""list_bonds — enumerate every bond in the candidate.

Used by the agent to know bond_index values for break_bond + to inspect
bond orders before suggesting an upgrade.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..base import tool


class ListBondsInput(BaseModel):
    smiles: str = Field(..., description="Current SMILES")


@tool(
    name="list_bonds",
    description=(
        "List every bond in the molecule with bond_idx, atom_a, atom_b, "
        "order (single/double/triple/aromatic), in_ring, is_aromatic. "
        "Use this to find the bond_index for a break_bond call."
    ),
    category="chem_workbench",
    input_model=ListBondsInput,
    expected_duration_ms=10,
    tags=("chemistry", "rdkit", "inspect"),
)
def list_bonds(smiles: str) -> Dict[str, Any]:
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError({"code": "unparseable_smiles", "message": f"unparseable SMILES: {smiles}"})
    bonds: List[Dict[str, Any]] = []
    for b in mol.GetBonds():
        t = b.GetBondType()
        order = "double" if t == Chem.BondType.DOUBLE else \
                "triple" if t == Chem.BondType.TRIPLE else \
                "aromatic" if t == Chem.BondType.AROMATIC else "single"
        bonds.append({
            "bond_idx": b.GetIdx(),
            "atom_a": b.GetBeginAtomIdx(),
            "atom_b": b.GetEndAtomIdx(),
            "order": order,
            "in_ring": b.IsInRing(),
            "is_aromatic": b.GetIsAromatic(),
        })
    return {"bonds": bonds, "n_bonds": len(bonds)}
