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
import os
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


# ─────────────────────────────────────────────────────────────────────
# Antibacterial-activity head — our own trained classifier (HistGBT +
# Morgan), learned from antibiotic actives vs property-matched decoys.
# Separate model from ADMET-AI; same service so the backend has one URL.
# ─────────────────────────────────────────────────────────────────────

from pathlib import Path  # noqa: E402

_ACT_MODEL: Optional[Any] = None
_ACT_ERROR: Optional[str] = None
_ACT_META: dict[str, Any] = {}
_ACT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "activity_clf.joblib"
_ACT_META_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "activity_clf_metrics.json"


def _get_activity_model():
    global _ACT_MODEL, _ACT_ERROR, _ACT_META
    if _ACT_MODEL is not None or _ACT_ERROR is not None:
        return _ACT_MODEL
    try:
        import joblib
        _ACT_MODEL = joblib.load(_ACT_PATH)
        if _ACT_META_PATH.exists():
            import json as _json
            _ACT_META = _json.loads(_ACT_META_PATH.read_text())
        log.info("activity classifier loaded (AUC %s)", _ACT_META.get("roc_auc"))
    except Exception as exc:  # noqa: BLE001
        _ACT_ERROR = str(exc)
        log.warning("activity classifier load failed: %s", exc)
    return _ACT_MODEL


def _activity_fp(smiles: str):
    import numpy as np
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from rdkit.DataStructs import ConvertToNumpyArray
    mol = Chem.MolFromSmiles((smiles or "").strip())
    if mol is None:
        return None
    bv = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
    arr = np.zeros((2048,), dtype=np.float32)
    ConvertToNumpyArray(bv, arr)
    return arr.reshape(1, -1)


@app.post("/predict_activity")
async def predict_activity(req: PredictRequest) -> dict[str, Any]:
    """Predicted antibacterial-activity probability per SMILES from the
    trained classifier."""
    m = _get_activity_model()
    if m is None:
        return {"ok": False, "error": _ACT_ERROR or "activity model not trained",
                "predictions": {}}
    import numpy as np
    t0 = time.time()
    preds: dict[str, dict[str, float]] = {}
    for smi in req.smiles[:64]:
        fp = _activity_fp(smi)
        if fp is None:
            preds[smi] = {"_error": 1.0}
            continue
        try:
            prob = float(m.predict_proba(fp)[0, 1])
            preds[smi] = {"activity_probability": round(prob, 4)}
        except Exception as exc:  # noqa: BLE001
            preds[smi] = {"_error": 1.0}
            log.warning("activity predict failed for %s: %s", smi[:40], exc)
    return {
        "ok": True, "predictions": preds, "n_smiles": len(preds),
        "elapsed_s": round(time.time() - t0, 3),
        "model": _ACT_META.get("model", "activity-clf"),
        "model_auc": _ACT_META.get("roc_auc"),
    }


@app.get("/activity_health")
async def activity_health() -> dict[str, Any]:
    m = _get_activity_model()
    return {"ok": m is not None, "load_error": _ACT_ERROR,
            "metrics": _ACT_META}


# ─────────────────────────────────────────────────────────────────────
# ChemBERTa embeddings — real molecular-transformer representations.
# DeepChem/ChemBERTa-77M-MLM (RoBERTa pretrained on 77M PubChem SMILES).
# Mean-pooled 384-dim vectors → cosine similarity that captures chemistry
# beyond Morgan-FP bit overlap. Lazy-loaded; CPU here, MI300X in Act II.
# ─────────────────────────────────────────────────────────────────────

_EMB_MODEL: Optional[Any] = None
_EMB_TOK: Optional[Any] = None
_EMB_ERROR: Optional[str] = None
_EMB_ID = os.environ.get("LYSOS_CHEMBERTA_ID", "DeepChem/ChemBERTa-77M-MLM")


def _get_embedder():
    global _EMB_MODEL, _EMB_TOK, _EMB_ERROR
    if _EMB_MODEL is not None or _EMB_ERROR is not None:
        return _EMB_MODEL
    try:
        from transformers import AutoTokenizer, AutoModel
        t0 = time.time()
        _EMB_TOK = AutoTokenizer.from_pretrained(_EMB_ID)
        m = AutoModel.from_pretrained(_EMB_ID)
        m.eval()  # PyTorch inference mode (NOT python eval)
        _EMB_MODEL = m
        log.info("ChemBERTa %s loaded in %.1fs", _EMB_ID, time.time() - t0)
    except Exception as exc:  # noqa: BLE001
        _EMB_ERROR = str(exc)
        log.warning("ChemBERTa load failed: %s", exc)
    return _EMB_MODEL


def _embed(smiles_list):
    import torch
    mdl = _get_embedder()
    if mdl is None:
        return None
    out = []
    with torch.no_grad():
        for smi in smiles_list[:64]:
            x = _EMB_TOK(smi, return_tensors="pt", truncation=True, max_length=128)
            vec = mdl(**x).last_hidden_state.mean(dim=1)[0]
            out.append(vec.tolist())
    return out


class EmbedRequest(BaseModel):
    smiles: list


class SimRequest(BaseModel):
    smiles_a: str
    smiles_b: str


@app.post("/embed")
async def embed(req: EmbedRequest) -> dict:
    vecs = _embed(req.smiles)
    if vecs is None:
        return {"ok": False, "error": _EMB_ERROR or "embedder unavailable",
                "embeddings": []}
    return {"ok": True, "model": _EMB_ID, "dim": len(vecs[0]) if vecs else 0,
            "embeddings": vecs, "n": len(vecs)}


@app.post("/similarity")
async def similarity(req: SimRequest) -> dict:
    import torch
    vecs = _embed([req.smiles_a, req.smiles_b])
    if vecs is None or len(vecs) < 2:
        return {"ok": False, "error": _EMB_ERROR or "embedder unavailable"}
    a = torch.tensor(vecs[0]); b = torch.tensor(vecs[1])
    cos = float(torch.nn.functional.cosine_similarity(a, b, dim=0))
    return {"ok": True, "model": _EMB_ID, "cosine_similarity": round(cos, 4)}


@app.get("/embed_health")
async def embed_health() -> dict:
    m = _get_embedder()
    return {"ok": m is not None, "model": _EMB_ID, "load_error": _EMB_ERROR}
