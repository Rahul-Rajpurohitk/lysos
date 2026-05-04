"""Predict hemolytic safety risk via the trained DBAASP-derived ML predictor."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.scoring.predict_hemolysis")

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


class HemolysisInput(BaseModel):
    smiles: str = Field(..., description="Candidate SMILES")


class HemolysisRisk(BaseModel):
    smiles: str
    safety_score: float = Field(..., description="1.0 = predicted safe, 0.0 = predicted hemolytic")
    risk_class: str
    confidence: float
    interpretation: str
    predictor: str


@tool(
    description=(
        "Predict the hemolytic-safety risk of a candidate using the DBAASP-trained "
        "ML predictor (n=782, CV AUROC 0.813). Returns safety_score in [0,1] where "
        "1.0 = predicted-safe and 0.0 = predicted-hemolytic."
    ),
    category="scoring",
    input_model=HemolysisInput,
    output_model=HemolysisRisk,
    expected_duration_ms=80,
    tags=("scoring", "safety", "hemolysis", "core"),
)
def predict_hemolysis(smiles: str) -> HemolysisRisk:
    from src.eval.rewards.safety import hemolysis_inverse

    raw = hemolysis_inverse([smiles])
    score = float(raw[0]) if raw else 0.5

    if score >= 0.85:
        cls = "safe"
        interp = "Predicted SAFE — minimal hemolytic risk."
    elif score >= 0.65:
        cls = "low_risk"
        interp = "Low predicted hemolytic risk."
    elif score >= 0.40:
        cls = "moderate_risk"
        interp = "Moderate predicted hemolytic risk — monitor."
    else:
        cls = "high_risk"
        interp = "HIGH predicted hemolytic risk — likely fails preclinical safety."

    return HemolysisRisk(
        smiles=smiles,
        safety_score=round(score, 3),
        risk_class=cls,
        confidence=0.81,
        interpretation=interp,
        predictor="dbaasp_logreg",
    )
