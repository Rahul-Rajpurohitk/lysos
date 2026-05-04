"""Generate a 3D-scene description (Mol* spec) for the frontend viewer.

The frontend has 3Dmol.js + Mol* embedded; this tool returns a structured
scene spec the agent can use to direct visualization (e.g. "show me the
binding pocket with this ligand pose"). Output is consumed by the UI to
configure the 3D viewer.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..base import tool


class SceneInput(BaseModel):
    structure: str = Field(..., description="PDB ID or 'ligand_only' for SMILES-only view")
    ligand_smiles: Optional[str] = Field(None, description="Ligand SMILES to overlay")
    style: Literal["cartoon", "surface", "stick", "ball_stick"] = "cartoon"
    color_scheme: Literal["spectrum", "chainid", "secondary", "uniform"] = "spectrum"
    highlight_residues: list[str] = Field([], description="Residue IDs to highlight (e.g. ['A:Glu447'])")


class MolStarScene(BaseModel):
    structure: str
    ligand_smiles: Optional[str] = None
    style: str
    color_scheme: str
    highlight_residues: list[str]
    camera_preset: str
    annotations: list[str]


@tool(
    description=(
        "Generate a 3D-scene specification for the frontend viewer. Pass a PDB "
        "ID, optional ligand SMILES to overlay, style (cartoon/surface/stick), "
        "color scheme, and residue highlights. The frontend consumes this to "
        "configure the Mol*/3Dmol viewer."
    ),
    category="sandbox",
    input_model=SceneInput,
    output_model=MolStarScene,
    expected_duration_ms=20,
    tags=("sandbox", "viz", "molstar"),
)
def render_3d_scene(
    structure: str,
    ligand_smiles: Optional[str] = None,
    style: str = "cartoon",
    color_scheme: str = "spectrum",
    highlight_residues: Optional[list[str]] = None,
) -> MolStarScene:
    if highlight_residues is None:
        highlight_residues = []

    annotations = []
    if ligand_smiles:
        annotations.append(f"Ligand overlaid: {ligand_smiles[:30]}…")
    if highlight_residues:
        annotations.append(f"Highlighting {len(highlight_residues)} residue(s): {', '.join(highlight_residues[:3])}")
    if not annotations:
        annotations.append("Default scene: full protein + spectrum coloring")

    return MolStarScene(
        structure=structure,
        ligand_smiles=ligand_smiles,
        style=style,
        color_scheme=color_scheme,
        highlight_residues=highlight_residues,
        camera_preset="centered_on_ligand" if ligand_smiles else "default",
        annotations=annotations,
    )
