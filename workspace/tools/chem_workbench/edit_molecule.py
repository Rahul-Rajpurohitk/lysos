"""edit_molecule — atom & bond level edits.

Single tool that dispatches to all the edit operations. Mirrors the
/workbench/molecule/edit endpoint exactly. Agent function-call.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..base import tool
from ._chem_lib import (
    ELEMENTS, FG_TEMPLATES, BRANCHED_FGS,
    parse_and_kekulize, sanitize_with_retry, get_bond_orders,
)


class EditMoleculeInput(BaseModel):
    smiles: str = Field(..., description="Current candidate SMILES")
    op: str = Field(..., description=(
        "Operation: swap_element | break_bond | add_methyl_at | add_atom_at | "
        "delete_atom | add_bond | delete_bond | add_functional_group_at | attach_fragment"
    ))
    atom_index: Optional[int] = Field(None, description="Anchor atom index (most ops)")
    atom_index_a: Optional[int] = Field(None, description="First atom for add_bond")
    atom_index_b: Optional[int] = Field(None, description="Second atom for add_bond")
    bond_index: Optional[int] = Field(None, description="Bond index for break_bond / delete_bond")
    new_element: Optional[str] = Field(None, description="Element symbol for swap/add_atom_at")
    bond_order: str = Field("single", description="single | double | triple | aromatic")
    functional_group: Optional[str] = Field(None, description="FG name for add_functional_group_at")
    fragment_smiles: Optional[str] = Field(None, description="SMILES of fragment for attach_fragment")
    fragment_anchor_idx: int = Field(0, description="Index within fragment of bonding atom")
    actor: str = Field("agent", description="Source of the edit (user/designer/critic/etc)")


class EditMoleculeOutput(BaseModel):
    smiles: str
    n_atoms: int
    n_bonds: int
    actor: str


@tool(
    name="edit_molecule",
    description=(
        "Atom-and-bond-level edit on the current candidate SMILES. "
        "Supports element swap, atom add/delete, bond add/delete, functional "
        "group attach, and arbitrary fragment attach. Returns the canonical "
        "SMILES of the result. Pre-flight with valid_actions to avoid valence "
        "violations."
    ),
    category="chem_workbench",
    input_model=EditMoleculeInput,
    output_model=EditMoleculeOutput,
    expected_duration_ms=80,
    tags=("chemistry", "rdkit", "edit"),
)
def edit_molecule(
    smiles: str,
    op: str,
    atom_index: Optional[int] = None,
    atom_index_a: Optional[int] = None,
    atom_index_b: Optional[int] = None,
    bond_index: Optional[int] = None,
    new_element: Optional[str] = None,
    bond_order: str = "single",
    functional_group: Optional[str] = None,
    fragment_smiles: Optional[str] = None,
    fragment_anchor_idx: int = 0,
    actor: str = "agent",
) -> EditMoleculeOutput:
    from rdkit import Chem
    rw = parse_and_kekulize(smiles)
    BO = get_bond_orders()

    if op == "swap_element":
        if atom_index is None or new_element is None:
            raise ValueError({"code": "missing_args", "message": "swap_element needs atom_index + new_element"})
        if new_element not in ELEMENTS:
            raise ValueError({"code": "unsupported_element", "message": f"unsupported element: {new_element}"})
        rw.GetAtomWithIdx(atom_index).SetAtomicNum(ELEMENTS[new_element])

    elif op in ("break_bond", "delete_bond"):
        if bond_index is None:
            raise ValueError({"code": "missing_args", "message": f"{op} needs bond_index"})
        b = rw.GetBondWithIdx(bond_index)
        rw.RemoveBond(b.GetBeginAtomIdx(), b.GetEndAtomIdx())

    elif op == "add_methyl_at":
        if atom_index is None:
            raise ValueError({"code": "missing_args", "message": "add_methyl_at needs atom_index"})
        c = rw.AddAtom(Chem.Atom(6))
        rw.AddBond(atom_index, c, Chem.BondType.SINGLE)

    elif op == "add_atom_at":
        if atom_index is None or new_element is None:
            raise ValueError({"code": "missing_args", "message": "add_atom_at needs atom_index + new_element"})
        if new_element not in ELEMENTS:
            raise ValueError({"code": "unsupported_element", "message": f"unsupported element: {new_element}"})
        new_idx = rw.AddAtom(Chem.Atom(ELEMENTS[new_element]))
        rw.AddBond(atom_index, new_idx, BO.get(bond_order, Chem.BondType.SINGLE))

    elif op == "delete_atom":
        if atom_index is None:
            raise ValueError({"code": "missing_args", "message": "delete_atom needs atom_index"})
        rw.RemoveAtom(atom_index)

    elif op == "add_bond":
        if atom_index_a is None or atom_index_b is None:
            raise ValueError({"code": "missing_args", "message": "add_bond needs atom_index_a + atom_index_b"})
        if atom_index_a == atom_index_b:
            raise ValueError({"code": "self_bond", "message": "cannot bond an atom to itself"})
        if rw.GetBondBetweenAtoms(atom_index_a, atom_index_b) is not None:
            raise ValueError({"code": "bond_already_exists", "message": f"bond already exists between {atom_index_a} and {atom_index_b}"})
        rw.AddBond(atom_index_a, atom_index_b, BO.get(bond_order, Chem.BondType.SINGLE))

    elif op == "add_functional_group_at":
        if atom_index is None or functional_group is None:
            raise ValueError({"code": "missing_args", "message": "add_functional_group_at needs atom_index + functional_group"})
        tpl = FG_TEMPLATES.get(functional_group)
        if tpl is None:
            raise ValueError({"code": "unknown_functional_group", "message": f"unknown FG: {functional_group}"})
        prev_idx = atom_index
        first_new = None
        for i, (elt, bo) in enumerate(tpl):
            new_idx = rw.AddAtom(Chem.Atom(ELEMENTS[elt]))
            if first_new is None:
                first_new = new_idx
            bt = BO.get(bo, Chem.BondType.SINGLE)
            if i == 0 or functional_group not in BRANCHED_FGS:
                rw.AddBond(prev_idx, new_idx, bt)
                prev_idx = new_idx
            else:
                rw.AddBond(first_new, new_idx, bt)

    elif op == "attach_fragment":
        if atom_index is None or fragment_smiles is None:
            raise ValueError({"code": "missing_args", "message": "attach_fragment needs atom_index + fragment_smiles"})
        frag = Chem.MolFromSmiles(fragment_smiles)
        if frag is None:
            raise ValueError({"code": "unparseable_smiles", "message": f"unparseable fragment: {fragment_smiles}"})
        try:
            Chem.Kekulize(frag, clearAromaticFlags=True)
        except Exception:  # noqa: BLE001
            pass
        n_main = rw.GetNumAtoms()
        combined = Chem.CombineMols(rw.GetMol(), frag)
        rw2 = Chem.RWMol(combined)
        rw2.AddBond(atom_index, n_main + fragment_anchor_idx, BO.get(bond_order, Chem.BondType.SINGLE))
        rw = rw2

    else:
        raise ValueError({"code": "unknown_op", "message": f"unknown op: {op}"})

    new_smiles = sanitize_with_retry(rw)
    return EditMoleculeOutput(
        smiles=new_smiles,
        n_atoms=rw.GetNumAtoms(),
        n_bonds=rw.GetNumBonds(),
        actor=actor,
    )
