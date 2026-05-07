"""Place-in-pocket — geometric ligand placement + contact analysis.

Service 1 (3D Target-Ligand Theater) tool. Drops a candidate molecule into
the active site of a curated pathogen target and reads back contacts +
clashes the agent can reason about.

Unlike `dock_against_target` (DiffDock-L, generative, slow, needs approval),
this tool is FAST (<1s), DETERMINISTIC, and CHEAP. It exists for the
inner-loop reasoning where the Designer / Critic / Editor ask "after this
edit, did the binding contacts change?". No GPU required.

Contract:
  Input:  smiles + pdb_id (must be in the curated PATHOGEN_TARGETS map)
  Output: pose_score (0-1), contacts list, clashes list, binding_atoms /
          clashing_atoms (the ligand atom indices for the 2D builder halos)

The actual geometric work is done by the FastAPI endpoint at
/workbench/chem/place-in-pocket — this @tool wrapper makes it available
to the agent harness's tool registry alongside the other structural tools.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("tools.structural.place_in_pocket")


class PlaceInput(BaseModel):
    smiles: str = Field(..., description="Candidate ligand SMILES")
    pdb_id: str = Field(..., description="Target PDB ID (e.g. 1VQQ for PBP2a, 5UL8 for KPC-2)")


class KeyContact(BaseModel):
    residue: str
    chain: str
    ligand_atom_idx: int
    ligand_element: str
    distance_a: float


class PlaceResult(BaseModel):
    pdb_id: str
    smiles: str
    pose_score: float = Field(..., description="Geometric pose quality, 0-1 (higher = more contacts, fewer clashes)")
    n_contacts: int
    n_clashes: int
    binding_atoms: list[int] = Field(..., description="Ligand atom indices within 4Å of any non-water protein atom")
    clashing_atoms: list[int] = Field(..., description="Ligand atom indices within 1.5Å of any non-water protein atom (steric clash)")
    key_contacts: list[KeyContact] = Field(..., description="Top-8 closest residue contacts (one per residue, min distance)")


@tool(
    description=(
        "Place a candidate molecule in the active site of a target protein and "
        "read back which atoms make binding contacts vs which clash. Fast "
        "geometric placement (~1s, no GPU) — meant for the inner agent loop "
        "where each edit needs a fresh contact map. For real generative "
        "docking, use dock_against_target instead."
    ),
    category="structural",
    input_model=PlaceInput,
    output_model=PlaceResult,
    expected_duration_ms=1500,
    needs_approval=False,
)
async def place_in_pocket(args: PlaceInput) -> PlaceResult:
    """Calls the /workbench/chem/place-in-pocket FastAPI endpoint via in-process
    function call (avoids HTTP roundtrip when invoked from the agent harness)."""
    from workspace.api.chem_3d import place_in_pocket as _endpoint
    from workspace.api.chem_3d import PlaceInPocketRequest

    result = await _endpoint(PlaceInPocketRequest(smiles=args.smiles, pdb_id=args.pdb_id))
    return PlaceResult(
        pdb_id=result["pdb_id"],
        smiles=result["smiles"],
        pose_score=result["pose_score"],
        n_contacts=result["n_contacts"],
        n_clashes=result["n_clashes"],
        binding_atoms=result["binding_atoms"],
        clashing_atoms=result["clashing_atoms"],
        key_contacts=[KeyContact(**kc) for kc in result["key_contacts"]],
    )
