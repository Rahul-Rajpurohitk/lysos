"""DiffDock-L generative docking — predict ligand poses against target PDB.

Pre-MI300X: deterministic synthetic pose with RMSD + score. Day 4: real
DiffDock-L inference (43% success rate on PDBBind).
"""
from __future__ import annotations

import hashlib
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..base import tool


class DockInput(BaseModel):
    smiles: str = Field(..., description="Ligand SMILES")
    pdb_id: str = Field(..., description="Target PDB ID (e.g. 1VQQ)")
    num_poses: int = Field(5, ge=1, le=20)


class DockingPose(BaseModel):
    rank: int
    rmsd_to_native: float
    docking_score: float
    confidence: float


class DockingResult(BaseModel):
    smiles: str
    pdb_id: str
    poses: list[DockingPose]
    best_score: float
    best_rmsd: float
    backend: Literal["diffdock_l", "synthetic_dev"]
    interpretation: str
    pose_download_url: Optional[str] = None


@tool(
    description=(
        "Predict ligand binding poses against a target PDB structure via "
        "DiffDock-L (generative diffusion docking). Returns top-K poses with "
        "RMSD to native + docking scores."
    ),
    category="structural",
    input_model=DockInput,
    output_model=DockingResult,
    expected_duration_ms=8000,
    needs_approval=True,
    tags=("structural", "docking", "diffdock"),
)
def dock_against_target(smiles: str, pdb_id: str, num_poses: int = 5) -> DockingResult:
    h = hashlib.sha256((smiles + pdb_id).encode()).digest()
    seed = int.from_bytes(h[:4], "big") / (2 ** 32)

    base_score = -10.5 - seed * 4.5  # -15 to -10.5
    base_rmsd = 1.5 + seed * 3.0      # 1.5 to 4.5 Å

    poses = []
    for i in range(num_poses):
        decay = 0.85 ** i
        poses.append(DockingPose(
            rank=i + 1,
            rmsd_to_native=round(base_rmsd / decay, 2),
            docking_score=round(base_score * decay, 2),
            confidence=round(0.55 + seed * 0.4 * decay, 3),
        ))

    if base_rmsd <= 2.0:
        interp = (
            f"Top pose RMSD {base_rmsd:.1f} Å — confident binding mode "
            f"with score {base_score:.1f}. Strong binder."
        )
    elif base_rmsd <= 3.5:
        interp = (
            f"Top pose RMSD {base_rmsd:.1f} Å — plausible binding mode, "
            f"score {base_score:.1f}. Worth refining."
        )
    else:
        interp = (
            f"Top pose RMSD {base_rmsd:.1f} Å — uncertain binding pose, "
            f"may not occupy intended pocket."
        )

    return DockingResult(
        smiles=smiles,
        pdb_id=pdb_id,
        poses=poses,
        best_score=poses[0].docking_score,
        best_rmsd=poses[0].rmsd_to_native,
        backend="synthetic_dev",
        interpretation=interp,
        pose_download_url=None,
    )
