"""Boltz-2 binding affinity predictor (FEP-level accuracy at 1000x speed).

For dev mode (pre-MI300X) we return a deterministic synthetic value derived
from the SMILES hash — same backbone as predict_complex_structure but
without the pose data. On Day 4 we swap in real Boltz-2 inference.
"""
from __future__ import annotations

import hashlib
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..base import tool


class AffinityInput(BaseModel):
    smiles: str = Field(..., description="Candidate ligand SMILES")
    target: str = Field(..., description="Pathogen short code OR PDB ID")


class AffinityOutput(BaseModel):
    smiles: str
    target: str
    delta_g_kcal_mol: float
    pkd_predicted: float
    affinity_class: Literal["nanomolar", "sub_micromolar", "low_micromolar", "weak"]
    confidence: float
    interpretation: str
    backend: Literal["boltz2", "synthetic_dev"]


@tool(
    description=(
        "Predict ligand binding free energy (ΔG, kcal/mol) and pKd against a "
        "named pathogen target via Boltz-2. Returns affinity_class + interpretation."
    ),
    category="structural",
    input_model=AffinityInput,
    output_model=AffinityOutput,
    expected_duration_ms=2500,
    needs_approval=True,
    tags=("structural", "affinity", "boltz2"),
)
def predict_binding_affinity(smiles: str, target: str) -> AffinityOutput:
    h = hashlib.sha256((smiles + target).encode()).digest()
    seed = int.from_bytes(h[:4], "big") / (2 ** 32)
    dg = -4.5 - seed * 6.0  # range -10.5 to -4.5
    pkd = -dg / 1.36

    if dg <= -9.0:
        cls = "nanomolar"
        interp = f"Nanomolar predicted affinity (ΔG={dg:.1f} kcal/mol, pKd={pkd:.1f})."
    elif dg <= -7.0:
        cls = "sub_micromolar"
        interp = f"Sub-µM affinity (ΔG={dg:.1f}, pKd={pkd:.1f}) — promising."
    elif dg <= -5.5:
        cls = "low_micromolar"
        interp = f"Low-µM affinity (ΔG={dg:.1f}, pKd={pkd:.1f}) — needs optimization."
    else:
        cls = "weak"
        interp = f"Weak binding (ΔG={dg:.1f}, pKd={pkd:.1f}) — unlikely therapeutic."

    return AffinityOutput(
        smiles=smiles,
        target=target,
        delta_g_kcal_mol=round(dg, 2),
        pkd_predicted=round(pkd, 2),
        affinity_class=cls,
        confidence=round(0.55 + seed * 0.4, 2),
        interpretation=interp,
        backend="synthetic_dev",
    )
