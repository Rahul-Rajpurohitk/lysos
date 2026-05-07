"""attach_functional_group — convenience wrapper for add_functional_group_at.

Lets the agent say "attach hydroxyl to atom 2" without re-stating the op.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..base import tool
from .edit_molecule import edit_molecule, EditMoleculeOutput


class AttachFunctionalInput(BaseModel):
    smiles: str = Field(..., description="Current SMILES")
    anchor_atom_idx: int = Field(..., description="Atom on parent the FG attaches to")
    functional_group: str = Field(..., description=(
        "FG name from the supported set: hydroxyl, methyl, amine, fluorine, "
        "chlorine, bromine, iodine, thiol, carbonyl, aldehyde, carboxyl, "
        "ester, amide, nitro, sulfonyl, sulfonamide, sulfide, phosphate, "
        "phosphonate, cyano, isocyano, azido, trifluoromethyl, "
        "trichloromethyl, ethyl, vinyl, ethynyl, methoxy, ethoxy, "
        "isopropyl, tert-butyl, phenyl"
    ))
    actor: str = Field("agent", description="Source of the action")


@tool(
    name="attach_functional_group",
    description=(
        "Attach a named functional group (hydroxyl, amine, carboxyl, "
        "sulfonamide, trifluoromethyl, etc.) to a specific atom. "
        "Convenience wrapper around edit_molecule op:add_functional_group_at."
    ),
    category="chem_workbench",
    input_model=AttachFunctionalInput,
    output_model=EditMoleculeOutput,
    expected_duration_ms=60,
    tags=("chemistry", "rdkit", "build", "fg"),
)
def attach_functional_group(
    smiles: str,
    anchor_atom_idx: int,
    functional_group: str,
    actor: str = "agent",
) -> EditMoleculeOutput:
    return edit_molecule(
        smiles=smiles,
        op="add_functional_group_at",
        atom_index=anchor_atom_idx,
        functional_group=functional_group,
        actor=actor,
    )
