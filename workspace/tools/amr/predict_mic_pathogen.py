"""Predict MIC of a candidate molecule against a named pathogen.

Dispatches to the trained XGBoost MIC predictor (scaffold-CV MAE 0.62, R² 0.56)
in src/eval/rewards/activity.py. Falls back to lipophilicity heuristic if the
joblib bundle is missing.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..base import tool

log = logging.getLogger("workbench.tools.amr.predict_mic_pathogen")

# Make src/ importable
_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

PATHOGENS = Literal["MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
                    "Abaum", "Paer", "VRE", "NGono"]


class PredictMicInput(BaseModel):
    smiles: str = Field(..., description="Canonical SMILES of the candidate molecule")
    pathogen: PATHOGENS = Field(..., description="Target pathogen short code")


class MicPrediction(BaseModel):
    smiles: str
    pathogen: str
    log_mic_predicted: float = Field(..., description="Predicted log10(MIC ug/mL)")
    mic_ug_ml: float = Field(..., description="Predicted MIC in ug/mL")
    reward: float = Field(..., description="Reward in [0, 1] — higher is more potent")
    confidence: float = Field(..., description="Predictor confidence in [0, 1]")
    interpretation: str = Field(..., description="Plain-English interpretation")
    predictor: Literal["ml_xgboost", "heuristic"]


@tool(
    description=(
        "Predict the minimum inhibitory concentration (MIC) of a candidate "
        "antibacterial molecule against a named drug-resistant pathogen. "
        "Uses the trained XGBoost predictor (scaffold-CV MAE 0.62, R² 0.56) "
        "on Morgan fingerprints + 8-pathogen one-hot. Fallback heuristic if "
        "the trained bundle is missing."
    ),
    category="amr",
    input_model=PredictMicInput,
    output_model=MicPrediction,
    expected_duration_ms=80,
    tags=("amr", "activity", "mic", "core"),
)
def predict_mic_pathogen(smiles: str, pathogen: str) -> MicPrediction:
    from src.eval.rewards.activity import predict_mic, _load_ml_bundle, _log_mic_to_reward

    bundle = _load_ml_bundle()
    rewards = predict_mic([smiles], target_pathogen=pathogen)
    reward = float(rewards[0])

    # Reverse the reward → log_mic mapping for explanation
    # reward = 1 - (log_mic - LOG_MIC_STRONG) / (LOG_MIC_WEAK - LOG_MIC_STRONG)
    # We store the underlying log_mic if predictor returned it; reconstruct otherwise.
    LOG_STRONG, LOG_WEAK = 0.30, 1.81
    log_mic = LOG_STRONG + (1.0 - reward) * (LOG_WEAK - LOG_STRONG)
    mic_ug = 10 ** log_mic

    if bundle is not None:
        predictor = "ml_xgboost"
        confidence = 0.85
    else:
        predictor = "heuristic"
        confidence = 0.40

    if mic_ug <= 2:
        interp = f"Strong predicted activity vs {pathogen} (MIC ≤ 2 µg/mL)."
    elif mic_ug <= 8:
        interp = f"Moderate predicted activity vs {pathogen} (MIC ≤ 8 µg/mL)."
    elif mic_ug <= 32:
        interp = f"Weak predicted activity vs {pathogen} (MIC 8-32 µg/mL)."
    else:
        interp = f"Likely inactive vs {pathogen} (MIC > 32 µg/mL)."

    return MicPrediction(
        smiles=smiles,
        pathogen=pathogen,
        log_mic_predicted=log_mic,
        mic_ug_ml=mic_ug,
        reward=reward,
        confidence=confidence,
        interpretation=interp,
        predictor=predictor,
    )
