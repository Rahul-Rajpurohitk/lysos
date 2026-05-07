"""attach_fragment — convenience wrapper that always uses op:attach_fragment.

Lets the agent say "attach pyridine to atom 3" without re-stating the
op every time.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..base import tool
from .edit_molecule import edit_molecule, EditMoleculeOutput


class AttachFragmentInput(BaseModel):
    smiles: str = Field(..., description="Current SMILES")
    anchor_atom_idx: int = Field(..., description="Atom on the parent the fragment attaches to")
    fragment_smiles: str = Field(..., description="SMILES of the fragment (e.g. 'c1ccccc1' for benzene)")
    fragment_anchor_idx: int = Field(0, description="Which atom of the fragment connects to anchor")
    bond_order: str = Field("single", description="single | double | aromatic")
    actor: str = Field("agent", description="Source of the action")


@tool(
    name="attach_fragment",
    description=(
        "Attach an arbitrary SMILES fragment to the parent at a specific "
        "atom. Use for rings (c1ccccc1, c1ccncc1), bicyclics, or any "
        "user-supplied fragment. Bond order is on the new bond between "
        "anchor and fragment_anchor."
    ),
    category="chem_workbench",
    input_model=AttachFragmentInput,
    output_model=EditMoleculeOutput,
    expected_duration_ms=80,
    tags=("chemistry", "rdkit", "build", "rings"),
)
def attach_fragment(
    smiles: str,
    anchor_atom_idx: int,
    fragment_smiles: str,
    fragment_anchor_idx: int = 0,
    bond_order: str = "single",
    actor: str = "agent",
) -> EditMoleculeOutput:
    return edit_molecule(
        smiles=smiles,
        op="attach_fragment",
        atom_index=anchor_atom_idx,
        fragment_smiles=fragment_smiles,
        fragment_anchor_idx=fragment_anchor_idx,
        bond_order=bond_order,
        actor=actor,
    )
