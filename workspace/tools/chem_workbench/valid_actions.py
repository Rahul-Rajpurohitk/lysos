"""valid_actions — pre-filter palette for an anchor atom.

Returns ONLY the actions that won't violate chemistry laws. The agent
calls this BEFORE proposing an edit so it doesn't waste tool-calls on
operations that will 422.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..base import tool
from ._chem_lib import DEFAULT_VALENCE


class ValidActionsInput(BaseModel):
    smiles: str = Field(..., description="Current SMILES")
    atom_idx: int = Field(..., description="Anchor atom index")


_FG_BOND_COST: Dict[str, int] = {
    "hydroxyl": 1, "methyl": 1, "amine": 1, "fluorine": 1, "chlorine": 1,
    "bromine": 1, "iodine": 1, "thiol": 1, "carbonyl": 1, "aldehyde": 1,
    "carboxyl": 1, "ester": 1, "amide": 1, "nitro": 1, "sulfonyl": 1,
    "sulfonamide": 1, "sulfide": 1, "phosphate": 1, "phosphonate": 1,
    "cyano": 1, "isocyano": 1, "azido": 1, "trifluoromethyl": 1,
    "trichloromethyl": 1, "ethyl": 1, "vinyl": 1, "ethynyl": 1,
    "methoxy": 1, "ethoxy": 1, "isopropyl": 1, "tert-butyl": 1, "phenyl": 1,
}


@tool(
    name="valid_actions",
    description=(
        "Pre-filter palette: returns the lists of (a) elements you can "
        "swap this atom to without over-valencing, (b) functional groups "
        "you can attach (cost ≤ free_valence), (c) whether a ring can "
        "attach, (d) bond-order upgrades available to each existing "
        "neighbor. Always call this before edit_molecule to avoid "
        "valence_violation 422s."
    ),
    category="chem_workbench",
    input_model=ValidActionsInput,
    expected_duration_ms=15,
    tags=("chemistry", "rdkit", "gating"),
)
def valid_actions(smiles: str, atom_idx: int) -> Dict[str, Any]:
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError({"code": "unparseable_smiles", "message": f"unparseable SMILES: {smiles}"})
    if atom_idx < 0 or atom_idx >= mol.GetNumAtoms():
        raise ValueError({"code": "atom_index_out_of_range",
                          "message": f"atom_idx {atom_idx} out of range"})
    atom = mol.GetAtomWithIdx(atom_idx)
    elt = atom.GetSymbol()
    n_h = atom.GetTotalNumHs()
    free_v = n_h
    explicit_v = atom.GetExplicitValence()

    valid_fgs = [fg for fg, cost in _FG_BOND_COST.items() if cost <= free_v]
    valid_swap = [
        sym for sym, max_v in DEFAULT_VALENCE.items()
        if sym != elt and max_v >= explicit_v
    ]
    valid_bond_orders: Dict[int, List[str]] = {}
    for nb in atom.GetNeighbors():
        b = mol.GetBondBetweenAtoms(atom_idx, nb.GetIdx())
        cur = "single"
        if b:
            t = b.GetBondType()
            cur = "double" if t == Chem.BondType.DOUBLE else \
                  "triple" if t == Chem.BondType.TRIPLE else \
                  "aromatic" if t == Chem.BondType.AROMATIC else "single"
        nb_free = nb.GetTotalNumHs()
        upgrades = []
        if cur == "single":
            if free_v >= 1 and nb_free >= 1:
                upgrades.append("double")
            if free_v >= 2 and nb_free >= 2:
                upgrades.append("triple")
        elif cur == "double" and free_v >= 1 and nb_free >= 1:
            upgrades.append("triple")
        valid_bond_orders[nb.GetIdx()] = [cur] + upgrades

    return {
        "atom_idx": atom_idx,
        "element": elt,
        "free_valence": free_v,
        "explicit_valence": explicit_v,
        "valid_elements_for_swap": valid_swap,
        "valid_functional_groups": valid_fgs,
        "valid_rings": free_v >= 1,
        "valid_bond_orders_to_neighbors": valid_bond_orders,
    }
