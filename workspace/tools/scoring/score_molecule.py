"""Score a candidate molecule on the 8-component reward stack.

Reuses src/eval/rewards/* — the same reward composite the Stage 3 GRPO
trainer optimizes against. Output is a structured RewardBreakdown that the
agent can reason over and the UI can render in the radar.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.scoring.score_molecule")

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Mirror the Stage 3 reward weights from configs/stage3_rl_grpo.yaml
WEIGHTS = {
    "validity": 0.05,
    "structural_alerts": 0.05,
    "predicted_mic": 0.30,
    "drug_likeness_qed": 0.15,
    "synthesizability": 0.10,
    "hemolysis_safety": 0.15,
    "novelty": 0.10,
    "embedding_novelty": 0.10,
}


class ScoreMoleculeInput(BaseModel):
    smiles: str = Field(..., description="Candidate SMILES")
    target_pathogen: str = Field("MRSA", description="For predicted_mic component")


class ComponentScore(BaseModel):
    name: str
    value: float
    weight: float
    contribution: float


class RewardBreakdown(BaseModel):
    smiles: str
    target_pathogen: str
    components: list[ComponentScore]
    composite: float = Field(..., description="Weighted-sum composite reward in [0, 1]")
    weakest: str = Field(..., description="Component with lowest value (improvement target)")
    strongest: str = Field(..., description="Component with highest value")


@tool(
    description=(
        "Score a candidate molecule on the 8-component reward stack used by "
        "Stage 3 GRPO training: validity, structural_alerts, predicted_mic, "
        "drug_likeness_qed, synthesizability, hemolysis_safety, novelty, "
        "embedding_novelty. Returns per-component values + weighted composite."
    ),
    category="scoring",
    input_model=ScoreMoleculeInput,
    output_model=RewardBreakdown,
    expected_duration_ms=300,
    tags=("scoring", "reward", "core"),
)
def score_molecule(smiles: str, target_pathogen: str = "MRSA") -> RewardBreakdown:
    from src.eval.rewards.activity import predict_mic
    from src.eval.rewards.drug_likeness import qed_score
    from src.eval.rewards.synth import sa_score
    from src.eval.rewards.safety import hemolysis_inverse
    from src.eval.rewards.novelty import tanimoto_distance_to_known
    from src.eval.rewards.validity import smiles_valid
    from src.eval.rewards.structural_alerts import structural_alerts_score
    from src.eval.rewards.embedding_novelty import embedding_novelty

    samples = [smiles]

    def _safe(fn, *args, **kwargs):
        try:
            r = fn(*args, **kwargs)
            return float(r[0]) if isinstance(r, list) else float(r)
        except Exception as exc:  # noqa: BLE001
            log.warning("Reward component %s failed: %s", fn.__name__, exc)
            return 0.0

    components_raw = {
        "validity": _safe(smiles_valid, samples),
        "structural_alerts": _safe(structural_alerts_score, samples),
        "predicted_mic": _safe(predict_mic, samples, target_pathogen=target_pathogen),
        "drug_likeness_qed": _safe(qed_score, samples),
        "synthesizability": _safe(sa_score, samples),
        "hemolysis_safety": _safe(hemolysis_inverse, samples),
        "novelty": _safe(
            tanimoto_distance_to_known, samples,
            reference_set="data/processed/known-antibiotics.smiles",
            threshold=0.6,
        ),
        "embedding_novelty": _safe(
            embedding_novelty, samples,
            reference_set="data/processed/known-antibiotics.smiles",
            threshold=0.6,
        ),
    }

    components = []
    composite = 0.0
    for name, value in components_raw.items():
        weight = WEIGHTS[name]
        contribution = value * weight
        composite += contribution
        components.append(ComponentScore(
            name=name, value=value, weight=weight, contribution=contribution,
        ))

    components.sort(key=lambda c: c.value)
    weakest = components[0].name
    strongest = components[-1].name
    components.sort(key=lambda c: -c.weight)

    return RewardBreakdown(
        smiles=smiles,
        target_pathogen=target_pathogen,
        components=components,
        composite=composite,
        weakest=weakest,
        strongest=strongest,
    )
