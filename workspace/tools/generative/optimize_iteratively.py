"""Mini RL-style iterative optimizer — apply transformations greedily to improve composite."""
from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.generative.optimize_iteratively")


TRANSFORM_OPS = [
    "add_hydroxyl", "add_fluorine", "add_methyl", "add_amine",
    "swap_chloro_to_fluoro", "remove_methyl",
]


class OptimizeInput(BaseModel):
    smiles: str = Field(..., description="Starting SMILES")
    target_pathogen: str = Field(..., description="For composite scoring")
    max_steps: int = Field(5, ge=1, le=15)
    objective: str = Field("composite", description="Field to maximize: composite | predicted_mic | qed | sa")


class OptimizationStep(BaseModel):
    step: int
    smiles: str
    op_applied: Optional[str]
    composite: float
    delta: float


class OptimizationOutput(BaseModel):
    starting_smiles: str
    target_pathogen: str
    objective: str
    trajectory: list[OptimizationStep]
    best_smiles: str
    best_composite: float
    interpretation: str


@tool(
    description=(
        "Mini RL-style iterative optimizer: starting from a SMILES, greedily "
        "applies transformations to maximize the chosen objective (composite by "
        "default). Returns the trajectory + best candidate. Useful for the "
        "Designer agent to do quick local search before yielding to the Critic."
    ),
    category="generative",
    input_model=OptimizeInput,
    output_model=OptimizationOutput,
    expected_duration_ms=2000,
    needs_approval=True,
    tags=("generative", "optimization", "core"),
)
def optimize_iteratively(
    smiles: str, target_pathogen: str, max_steps: int = 5, objective: str = "composite",
) -> OptimizationOutput:
    from .transform_structure import transform_structure
    from ..scoring.score_molecule import score_molecule

    current = smiles
    trajectory: list[OptimizationStep] = []
    initial = score_molecule(current, target_pathogen)
    best_composite = initial.composite
    trajectory.append(OptimizationStep(
        step=0, smiles=current, op_applied=None,
        composite=initial.composite, delta=0.0,
    ))

    for step in range(1, max_steps + 1):
        best_op = None
        best_smi = current
        best_score = best_composite
        for op in TRANSFORM_OPS:
            r = transform_structure(current, op)
            if not r.products:
                continue
            for cand in r.products[:2]:
                s = score_molecule(cand, target_pathogen)
                if s.composite > best_score:
                    best_score = s.composite
                    best_smi = cand
                    best_op = op
        if best_op is None or best_smi == current:
            log.info("Optimization plateaued at step %d", step)
            break
        delta = best_score - best_composite
        trajectory.append(OptimizationStep(
            step=step, smiles=best_smi, op_applied=best_op,
            composite=best_score, delta=delta,
        ))
        current = best_smi
        best_composite = best_score

    return OptimizationOutput(
        starting_smiles=smiles,
        target_pathogen=target_pathogen,
        objective=objective,
        trajectory=trajectory,
        best_smiles=current,
        best_composite=best_composite,
        interpretation=(
            f"Optimized over {len(trajectory) - 1} steps. "
            f"Composite improved from {trajectory[0].composite:.3f} to "
            f"{best_composite:.3f} (Δ={best_composite - trajectory[0].composite:+.3f})."
        ),
    )
