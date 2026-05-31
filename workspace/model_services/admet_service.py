"""Lysos ADMET model service — real ADMET-AI / Chemprop predictions.

This is the local stand-in for the AMD MI300X "Lysos Inference Service".
It wraps the open-source ADMET-AI package (Swanson et al., Bioinformatics
2024 — Chemprop-RDKit GNNs trained on 41 Therapeutics Data Commons ADMET
datasets) behind a tiny FastAPI surface so the main backend can call REAL
model predictions instead of physchem heuristics.

Run locally (dev):
    .venv-models/bin/uvicorn workspace.model_services.admet_service:app \
        --host 127.0.0.1 --port 7920

On MI300X (Act II): same file, ROCm PyTorch wheel in the venv, batched
inference on GPU. The contract does not change.

Contract:
    GET  /health         -> {"ok": bool, "model_loaded": bool, "n_endpoints": int}
    POST /predict        {"smiles": ["...", ...]} -> {"predictions": {smiles: {endpoint: value}}, ...}

License note: ADMET-AI is MIT. Cite Swanson et al. in the model card.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

log = logging.getLogger("lysos.admet_service")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Lysos ADMET service", version="1.0")

# Lazy singleton — loading the Chemprop ensemble is heavy (~seconds), so we
# do it on first request, not at import, to keep startup fast + testable.
_MODEL: Optional[Any] = None
_LOAD_ERROR: Optional[str] = None
_N_ENDPOINTS: int = 0


def _get_model():
    global _MODEL, _LOAD_ERROR, _N_ENDPOINTS
    if _MODEL is not None or _LOAD_ERROR is not None:
        return _MODEL
    try:
        from admet_ai import ADMETModel
        t0 = time.time()
        _MODEL = ADMETModel()
        log.info("ADMET-AI model loaded in %.1fs", time.time() - t0)
    except Exception as exc:  # noqa: BLE001
        _LOAD_ERROR = str(exc)
        log.error("ADMET-AI load failed: %s", exc)
    return _MODEL


class PredictRequest(BaseModel):
    smiles: list[str]


def _predict_one(model: Any, smi: str) -> dict[str, float]:
    """Return {endpoint: value} for one SMILES, version-robust."""
    out = model.predict(smiles=smi)
    # ADMETModel.predict(single) returns a dict; (list) returns a DataFrame.
    if isinstance(out, dict):
        return {str(k): _num(v) for k, v in out.items()}
    # DataFrame fallback (one row)
    try:
        row = out.iloc[0].to_dict()
        return {str(k): _num(v) for k, v in row.items()}
    except Exception:  # noqa: BLE001
        return {}


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


@app.get("/health")
async def health() -> dict[str, Any]:
    m = _get_model()
    return {
        "ok": m is not None,
        "model_loaded": m is not None,
        "load_error": _LOAD_ERROR,
        "n_endpoints": _N_ENDPOINTS,
        "service": "admet-ai",
    }


@app.post("/predict")
async def predict(req: PredictRequest) -> dict[str, Any]:
    global _N_ENDPOINTS
    m = _get_model()
    if m is None:
        return {"ok": False, "error": _LOAD_ERROR or "model unavailable",
                "predictions": {}}
    t0 = time.time()
    preds: dict[str, dict[str, float]] = {}
    for smi in req.smiles[:64]:  # cap batch
        try:
            p = _predict_one(m, smi)
            preds[smi] = p
            _N_ENDPOINTS = max(_N_ENDPOINTS, len(p))
        except Exception as exc:  # noqa: BLE001
            preds[smi] = {"_error": 1.0}
            log.warning("predict failed for %s: %s", smi[:40], exc)
    return {
        "ok": True,
        "predictions": preds,
        "n_smiles": len(preds),
        "elapsed_s": round(time.time() - t0, 3),
        "model": "admet-ai/chemprop-rdkit",
    }
