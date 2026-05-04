"""Predict a retrosynthesis route + heuristic synthesis cost.

Real implementation would call AiZynthFinder (open-source, AstraZeneca). For
v0 we return a deterministic synthetic-accessibility-based route stub so the
agent can reason about cost trade-offs. AiZynthFinder hookup arrives Day 1.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.scoring.predict_synthesis_route")

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


class RetroInput(BaseModel):
    smiles: str = Field(..., description="Target SMILES")
    max_steps: int = Field(8, ge=1, le=20)


class RetroStep(BaseModel):
    step: int
    reaction: str
    reactants: list[str]
    products: list[str]
    confidence: float


class RetrosynthesisTree(BaseModel):
    target_smiles: str
    sa_score: float = Field(..., description="Synthetic accessibility (1=easy, 10=hard)")
    estimated_steps: int
    estimated_cost_usd_per_g: float
    confidence_route_found: float
    backend: str
    interpretation: str
    steps: list[RetroStep] = []


@tool(
    description=(
        "Predict a retrosynthesis route + estimate cost. Stub uses RDKit SA "
        "score + heuristic step/cost mapping; v1 swaps in AiZynthFinder."
    ),
    category="scoring",
    input_model=RetroInput,
    output_model=RetrosynthesisTree,
    expected_duration_ms=400,
    tags=("scoring", "retro", "cost"),
)
def predict_synthesis_route(smiles: str, max_steps: int = 8) -> RetrosynthesisTree:
    try:
        from src.eval.rewards.synth import sa_score
        sa_raw = sa_score([smiles])
        # Reward map sa_score → SA score is inversely related; reverse engineer
        # The reward is 1.0 - normalized_sa, so sa_real = (1 - reward) * 9 + 1
        sa_real = (1.0 - float(sa_raw[0])) * 9.0 + 1.0
    except Exception as exc:  # noqa: BLE001
        log.warning("sa_score failed: %s", exc)
        sa_real = 5.0

    # Heuristic mapping: SA score to estimated steps + cost
    if sa_real <= 3:
        steps = 3
        cost_per_g = 50.0
        conf = 0.85
        interp = "Easy synthesis — 3-step route, ~$50/g lab-scale."
    elif sa_real <= 5:
        steps = 6
        cost_per_g = 250.0
        conf = 0.65
        interp = "Moderate synthesis — 6-step route, ~$250/g."
    elif sa_real <= 7:
        steps = 12
        cost_per_g = 1500.0
        conf = 0.45
        interp = "Hard synthesis — 12-step route, ~$1500/g — viable but expensive."
    else:
        steps = 20
        cost_per_g = 10000.0
        conf = 0.25
        interp = "Very hard synthesis — likely needs custom chemistry, ~$10K/g."

    return RetrosynthesisTree(
        target_smiles=smiles,
        sa_score=round(sa_real, 2),
        estimated_steps=min(steps, max_steps),
        estimated_cost_usd_per_g=cost_per_g,
        confidence_route_found=conf,
        backend="sa_heuristic_v0",
        interpretation=interp,
        steps=[],  # filled by AiZynthFinder Day 1
    )
