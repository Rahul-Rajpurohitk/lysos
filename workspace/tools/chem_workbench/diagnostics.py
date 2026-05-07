"""diagnostics — whole-molecule chemistry health check.

Returns incomplete atoms (under-valent), charge imbalance, fragment
count after a bond-break. Agent calls this after every edit to detect
side-effects.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..base import tool
from ._chem_lib import DEFAULT_VALENCE


class DiagnosticsInput(BaseModel):
    smiles: str = Field(..., description="Current SMILES")


@tool(
    name="diagnostics",
    description=(
        "Whole-molecule chemistry health check. Reports incomplete "
        "(under-valent) atoms, total formal charge, disconnected "
        "fragment count. Returns is_valid=true when no violations. "
        "Recommended after every edit_molecule call."
    ),
    category="chem_workbench",
    input_model=DiagnosticsInput,
    expected_duration_ms=15,
    tags=("chemistry", "rdkit", "validate"),
)
def diagnostics(smiles: str) -> Dict[str, Any]:
    from rdkit import Chem
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError({"code": "unparseable_smiles", "message": f"unparseable SMILES: {smiles}"})

    incomplete: List[Dict[str, Any]] = []
    for atom in mol.GetAtoms():
        sym = atom.GetSymbol()
        max_v = DEFAULT_VALENCE.get(sym, 0)
        if max_v == 0:
            continue
        adjusted_max = max_v + atom.GetFormalCharge()
        explicit = atom.GetExplicitValence()
        n_h = atom.GetTotalNumHs()
        total = explicit + n_h
        if total < adjusted_max - 1:
            incomplete.append({
                "code": "atom_under_valent",
                "message": f"atom {atom.GetIdx()} ({sym}) has only {total} bonds; expected {adjusted_max}",
                "atom_idx": atom.GetIdx(),
                "hint": f"{sym} normally forms {adjusted_max} bonds.",
                "suggested_fix": f"add a bond on atom {atom.GetIdx()}",
            })

    total_charge = sum(a.GetFormalCharge() for a in mol.GetAtoms())
    charge_warnings = []
    if abs(total_charge) > 0:
        charge_warnings.append({
            "code": "non_zero_total_charge",
            "message": f"total formal charge = {total_charge:+d}",
        })

    n_frags = len(Chem.GetMolFrags(mol))
    fragment_warnings = []
    if n_frags > 1:
        fragment_warnings.append({
            "code": "disconnected_fragments",
            "message": f"molecule has {n_frags} disconnected fragments",
            "suggested_fix": "reconnect with add_bond",
        })

    return {
        "is_valid": (not incomplete) and (n_frags == 1),
        "n_atoms": mol.GetNumAtoms(),
        "n_bonds": mol.GetNumBonds(),
        "n_fragments": n_frags,
        "total_formal_charge": total_charge,
        "incomplete_atoms": incomplete,
        "charge_warnings": charge_warnings,
        "fragment_warnings": fragment_warnings,
        "all_violations": incomplete + charge_warnings + fragment_warnings,
    }
