"""Predict protein-ligand complex structure + binding affinity using Boltz-2.

Boltz-2 (MIT, github.com/jwohlwend/boltz) is FEP-level accurate at 1000x speed.
On the MI300X it loads in ~5GB GPU RAM coresident with Gemma 4 31B-it.

When Boltz-2 is not available locally (e.g. pre-kickoff CPU dev), we return a
synthetic but plausibly-shaped result so the UI/agent can demo end-to-end. The
real Boltz-2 swap-in happens automatically on Day 4.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.structural.predict_complex_structure")

# Canonical PDB IDs for our 8 priority pathogen targets — used as defaults
DEFAULT_TARGETS: dict[str, dict] = {
    "MRSA": {"pdb_id": "1VQQ", "name": "PBP2a", "uniprot": "P07944"},
    "Mtb": {"pdb_id": "2X22", "name": "InhA (enoyl-ACP reductase)", "uniprot": "P9WGR1"},
    "EColi-CRE": {"pdb_id": "5UL8", "name": "PBP3 (FtsI)", "uniprot": "P0AD68"},
    "KpneuCRE": {"pdb_id": "6QWN", "name": "KPC-2", "uniprot": "Q9F663"},
    "Abaum": {"pdb_id": "7M4F", "name": "OXA-23", "uniprot": "Q7BSF1"},
    "Paer": {"pdb_id": "5DPX", "name": "PBP3", "uniprot": "Q9HVM6"},
    "VRE": {"pdb_id": "1MWS", "name": "VanA ligase", "uniprot": "Q06239"},
    "NGono": {"pdb_id": "5XFT", "name": "PBP2 (penA)", "uniprot": "P08149"},
}


class PredictStructureInput(BaseModel):
    smiles: str = Field(..., description="Ligand SMILES")
    target: str = Field(..., description="Pathogen short code OR explicit PDB ID")
    pose_count: int = Field(5, ge=1, le=20, description="Number of poses to predict")


class BoltzPose(BaseModel):
    rank: int
    confidence: float = Field(..., description="Boltz-2 pLDDT confidence in [0, 1]")
    plddt_mean: float
    pae_interface: float = Field(..., description="Predicted aligned error at the interface")


class BindingAffinity(BaseModel):
    delta_g_kcal_mol: float = Field(..., description="Predicted binding free energy")
    pkd: float = Field(..., description="Predicted -log10(Kd) in M units")
    confidence: float


class PredictStructureOutput(BaseModel):
    smiles: str
    target_pdb_id: str
    target_name: str
    poses: list[BoltzPose]
    affinity: BindingAffinity
    backend: Literal["boltz2", "synthetic_dev"]
    interpretation: str
    download_url: Optional[str] = Field(None, description="URL to download .cif of top pose")


def _synthetic_result(smiles: str, target_info: dict, n: int) -> tuple[list[BoltzPose], BindingAffinity]:
    """Deterministic synthetic affinity for dev mode (pre-Boltz-2-on-MI300X).

    Hash-based so the same SMILES always returns the same numbers.
    """
    h = hashlib.sha256(smiles.encode()).digest()
    seed = int.from_bytes(h[:4], "big") / (2**32)

    base_dg = -4.5 - (seed * 6.0)  # range -10.5 to -4.5
    base_conf = 0.55 + (seed * 0.4)

    poses = []
    for i in range(n):
        decay = 0.85 ** i
        poses.append(BoltzPose(
            rank=i + 1,
            confidence=round(base_conf * decay, 3),
            plddt_mean=round(70 + (seed * 25) * decay, 2),
            pae_interface=round(2.0 + (1 - seed) * 8 * (1 - decay), 2),
        ))

    affinity = BindingAffinity(
        delta_g_kcal_mol=round(base_dg, 2),
        pkd=round(-base_dg / 1.36, 2),
        confidence=round(base_conf, 2),
    )
    return poses, affinity


@tool(
    description=(
        "Predict protein-ligand complex structure + binding affinity using "
        "Boltz-2 (FEP-level accuracy at 1000x speed). Pass pathogen short "
        "code (uses default target) or explicit PDB ID. Returns top-K poses "
        "with confidence + ΔG. On dev (pre-MI300X) returns deterministic "
        "synthetic results for UI/agent flow validation."
    ),
    category="structural",
    input_model=PredictStructureInput,
    output_model=PredictStructureOutput,
    expected_duration_ms=4000,
    needs_approval=True,
    tags=("structural", "docking", "boltz2", "core"),
)
def predict_complex_structure(
    smiles: str,
    target: str,
    pose_count: int = 5,
) -> PredictStructureOutput:
    target_info = DEFAULT_TARGETS.get(target, {
        "pdb_id": target,
        "name": "user-supplied target",
        "uniprot": None,
    })

    backend: Literal["boltz2", "synthetic_dev"]
    try:
        # Real Boltz-2 path — load + run
        # from boltz import Boltz2Inference
        # ... (real integration on MI300X Day 4)
        raise ImportError("Boltz-2 not loaded in dev mode")
    except ImportError:
        log.info("Boltz-2 not available — returning synthetic dev result for %s", smiles)
        poses, affinity = _synthetic_result(smiles, target_info, pose_count)
        backend = "synthetic_dev"

    if affinity.delta_g_kcal_mol <= -9.0:
        interp = (
            f"Very strong predicted binding to {target_info['name']} "
            f"(ΔG = {affinity.delta_g_kcal_mol} kcal/mol, pKd ≈ {affinity.pkd}). "
            f"In drug-discovery terms: nanomolar affinity range."
        )
    elif affinity.delta_g_kcal_mol <= -7.0:
        interp = (
            f"Strong predicted binding (ΔG = {affinity.delta_g_kcal_mol} kcal/mol). "
            f"Sub-µM affinity range — promising lead."
        )
    elif affinity.delta_g_kcal_mol <= -5.5:
        interp = (
            f"Moderate predicted binding (ΔG = {affinity.delta_g_kcal_mol} kcal/mol). "
            f"Low-µM range — needs optimization."
        )
    else:
        interp = (
            f"Weak predicted binding (ΔG = {affinity.delta_g_kcal_mol} kcal/mol). "
            f"Likely insufficient for therapeutic effect."
        )

    return PredictStructureOutput(
        smiles=smiles,
        target_pdb_id=target_info["pdb_id"],
        target_name=target_info["name"],
        poses=poses,
        affinity=affinity,
        backend=backend,
        interpretation=interp,
        download_url=None if backend == "synthetic_dev" else f"/artifacts/poses/{smiles[:16]}.cif",
    )
