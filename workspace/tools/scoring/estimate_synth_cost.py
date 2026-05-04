"""Estimate USD-per-gram cost of synthesizing a candidate at lab scale.

Thin wrapper over predict_synthesis_route — provides a ready-to-use cost
number for the Critic agent to reason over (e.g. "this candidate scores
high but costs $5000/g — too expensive for further optimization").
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..base import tool


class CostInput(BaseModel):
    smiles: str = Field(..., description="Candidate SMILES")


class CostEstimate(BaseModel):
    smiles: str
    cost_usd_per_g_lab_scale: float
    cost_class: Literal["cheap", "moderate", "expensive", "very_expensive"]
    confidence: float
    interpretation: str


@tool(
    description=(
        "Estimate USD-per-gram lab-scale synthesis cost for a candidate. "
        "Thin wrapper over predict_synthesis_route — ready-to-use number for "
        "the Critic agent to reason over."
    ),
    category="scoring",
    input_model=CostInput,
    output_model=CostEstimate,
    expected_duration_ms=400,
    tags=("scoring", "cost"),
)
def estimate_synth_cost(smiles: str) -> CostEstimate:
    from .predict_synthesis_route import predict_synthesis_route
    route = predict_synthesis_route(smiles, max_steps=20)
    cost = route.estimated_cost_usd_per_g

    if cost <= 100:
        cls = "cheap"
        interp = f"~${cost:.0f}/g — cheap; can iterate freely."
    elif cost <= 500:
        cls = "moderate"
        interp = f"~${cost:.0f}/g — moderate; reasonable for early development."
    elif cost <= 5000:
        cls = "expensive"
        interp = f"~${cost:.0f}/g — expensive; reserve for promising leads only."
    else:
        cls = "very_expensive"
        interp = f"~${cost:.0f}/g — prohibitive at lab scale; needs major route optimization."

    return CostEstimate(
        smiles=smiles,
        cost_usd_per_g_lab_scale=cost,
        cost_class=cls,
        confidence=route.confidence_route_found,
        interpretation=interp,
    )
