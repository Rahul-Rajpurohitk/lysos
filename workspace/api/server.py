"""Lysos workspace API — FastAPI backend for the demo.

Endpoints:
  GET  /api/health             — liveness check
  GET  /api/pathogens          — list AMR target pathogens
  POST /api/design              — generate antibiotic candidates (sync)
  POST /api/design/stream       — generate w/ SSE streaming
  GET  /api/score?smiles=...   — score an arbitrary SMILES against the rubric
  GET  /                        — serve the React SPA (Vite build output)

This server is what the HF Space runs. The Dockerfile in workspace/ builds
the React frontend and copies the dist into static/ which FastAPI serves.

Locally:
    cd workspace && uvicorn api.server:app --reload --port 7860

In production (HF Space):
    docker run -p 7860:7860 lysos-workspace
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] api | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("lysos-api")

# ----------------------------------------------------------------------------
# Pathogen catalog (mirrors src/inference/generate.py)
# ----------------------------------------------------------------------------

PATHOGENS = [
    {
        "short": "MRSA",
        "name": "Staphylococcus aureus (MRSA)",
        "category": "gram_positive",
        "priority": "critical",
        "description": "Methicillin-resistant Staphylococcus aureus is a major hospital-acquired pathogen causing skin, blood, and bone infections.",
    },
    {
        "short": "Mtb",
        "name": "Mycobacterium tuberculosis",
        "category": "mycobacterium",
        "priority": "critical",
        "description": "M. tuberculosis kills 1.5 million people per year. MDR and XDR strains require new drug classes.",
    },
    {
        "short": "EColi-CRE",
        "name": "Escherichia coli (ESBL+ / CRE)",
        "category": "gram_negative",
        "priority": "critical",
        "description": "ESBL-producing or carbapenem-resistant E. coli causes severe urinary tract and bloodstream infections.",
    },
    {
        "short": "KpneuCRE",
        "name": "Klebsiella pneumoniae (CRE)",
        "category": "gram_negative",
        "priority": "critical",
        "description": "Carbapenem-resistant K. pneumoniae is among the WHO's highest priority pathogens; mortality up to 50%.",
    },
    {
        "short": "Abaum",
        "name": "Acinetobacter baumannii",
        "category": "gram_negative",
        "priority": "critical",
        "description": "Multidrug-resistant A. baumannii causes ICU pneumonia, often pan-resistant.",
    },
    {
        "short": "Paer",
        "name": "Pseudomonas aeruginosa",
        "category": "gram_negative",
        "priority": "critical",
        "description": "P. aeruginosa is intrinsically resistant to many antibiotics.",
    },
    {
        "short": "VRE",
        "name": "Enterococcus faecium (VRE)",
        "category": "gram_positive",
        "priority": "high",
        "description": "Vancomycin-resistant Enterococcus faecium causes bloodstream and endocarditis infections.",
    },
    {
        "short": "NGono",
        "name": "Neisseria gonorrhoeae",
        "category": "gram_negative",
        "priority": "high",
        "description": "Drug-resistant gonorrhea is on the verge of becoming untreatable.",
    },
]
PATHOGEN_BY_SHORT = {p["short"]: p for p in PATHOGENS}


# ----------------------------------------------------------------------------
# Lifecycle: warm the model on startup so first request is fast
# ----------------------------------------------------------------------------

_GENERATOR = None  # type: Optional[Any]


def _get_generator():
    """Lazy-import + cache the generator. Heavy init happens once."""
    global _GENERATOR
    if _GENERATOR is None:
        log.info("Cold-start: loading Lysos model (this may take 30-60s)")
        from src.inference.generate import LysosGenerator

        model_id = os.environ.get("LYSOS_MODEL_ID", "rahul24raj/lysos-rl")
        adapter_id = os.environ.get("LYSOS_ADAPTER_ID")
        _GENERATOR = LysosGenerator(model_id=model_id, adapter_id=adapter_id)
        # Trigger model load now so first design() call is hot
        _GENERATOR._load()
        log.info("Generator ready: %s", model_id)
    return _GENERATOR


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eager-load on startup if env says so (production)
    if os.environ.get("LYSOS_EAGER_LOAD", "false").lower() == "true":
        log.info("LYSOS_EAGER_LOAD=true — pre-warming model")
        _get_generator()
    yield


# ----------------------------------------------------------------------------
# App + middleware
# ----------------------------------------------------------------------------

app = FastAPI(
    title="Lysos API",
    description="Generative drug designer for antimicrobial resistance — built on Gemma 4, RL-tuned on AMD MI300X.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo space; tighten in prod
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------------


class DesignRequest(BaseModel):
    target: str = Field(..., description="Pathogen short code, e.g. MRSA")
    n: int = Field(20, ge=1, le=200, description="Number of candidates to generate")
    modality: str = Field("smiles", pattern="^(smiles|peptide)$")
    temperature: float = Field(1.0, ge=0.1, le=2.0)
    top_p: float = Field(0.95, ge=0.1, le=1.0)
    max_new_tokens: int = Field(256, ge=32, le=1024)
    return_top: int = Field(20, ge=1, le=200)
    enable_rag: bool = Field(True, description="Use EmbeddingGemma to inject known antibiotics as in-context examples")
    rag_k: int = Field(3, ge=0, le=10, description="How many reference antibiotics to inject")


class SimilarRequest(BaseModel):
    smiles: str = Field(..., min_length=1, max_length=500)
    k: int = Field(5, ge=1, le=20)


class CandidateOut(BaseModel):
    smiles: Optional[str]
    sequence: Optional[str]
    raw: str
    scores: dict[str, float]
    combined: float


class DesignResponse(BaseModel):
    target: str
    pathogen: dict
    n_total: int
    n_returned: int
    elapsed_s: float
    model: str
    candidates: list[CandidateOut]
    aggregate: dict[str, float]


class HealthResponse(BaseModel):
    status: str
    model: Optional[str]
    loaded: bool
    uptime_s: float


# ----------------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------------


_STARTED = time.time()


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        model=os.environ.get("LYSOS_MODEL_ID", "rahul24raj/lysos-rl"),
        loaded=_GENERATOR is not None,
        uptime_s=time.time() - _STARTED,
    )


@app.get("/api/pathogens")
async def list_pathogens() -> list[dict]:
    return PATHOGENS


@app.post("/api/design", response_model=DesignResponse)
async def design(req: DesignRequest) -> DesignResponse:
    pathogen = PATHOGEN_BY_SHORT.get(req.target)
    if pathogen is None:
        raise HTTPException(404, f"unknown pathogen: {req.target}")

    gen = _get_generator()
    t0 = time.perf_counter()
    candidates = await asyncio.to_thread(
        gen.design,
        target=req.target,
        n=req.n,
        modality=req.modality,
        temperature=req.temperature,
        top_p=req.top_p,
        max_new_tokens=req.max_new_tokens,
        score=True,
        enable_rag=req.enable_rag,
        rag_k=req.rag_k,
    )
    elapsed = time.perf_counter() - t0

    candidates.sort(key=lambda c: (c.combined or -1.0), reverse=True)
    top = candidates[: req.return_top]

    # Aggregate
    valid = [c for c in candidates if c.combined is not None]
    if valid:
        composites = [c.combined for c in valid]
        aggregate = {
            "validity_rate": sum(1 for c in candidates if c.smiles or c.sequence) / len(candidates),
            "mean_composite": sum(composites) / len(composites),
            "max_composite": max(composites),
        }
        # Per-component means
        for key in valid[0].scores:
            aggregate[f"mean_{key}"] = sum(c.scores[key] for c in valid) / len(valid)
    else:
        aggregate = {"validity_rate": 0.0}

    return DesignResponse(
        target=req.target,
        pathogen=pathogen,
        n_total=len(candidates),
        n_returned=len(top),
        elapsed_s=elapsed,
        model=os.environ.get("LYSOS_MODEL_ID", "rahul24raj/lysos-rl"),
        candidates=[
            CandidateOut(
                smiles=c.smiles,
                sequence=c.sequence,
                raw=c.raw,
                scores=c.scores,
                combined=c.combined or 0.0,
            )
            for c in top
        ],
        aggregate=aggregate,
    )


@app.post("/api/design/stream")
async def design_stream(req: DesignRequest):
    """SSE-stream candidates as they're generated. Better UX than waiting for full batch."""
    pathogen = PATHOGEN_BY_SHORT.get(req.target)
    if pathogen is None:
        raise HTTPException(404, f"unknown pathogen: {req.target}")

    async def event_gen():
        gen = _get_generator()
        yield {"event": "start", "data": json.dumps({"target": req.target, "n": req.n})}

        # Generate one batch — note: real streaming would generate one-at-a-time.
        # For now we generate all and emit in chunks.
        candidates = await asyncio.to_thread(
            gen.design,
            target=req.target,
            n=req.n,
            modality=req.modality,
            temperature=req.temperature,
            top_p=req.top_p,
            score=True,
        )
        candidates.sort(key=lambda c: (c.combined or -1.0), reverse=True)

        for i, c in enumerate(candidates):
            yield {
                "event": "candidate",
                "data": json.dumps({
                    "index": i,
                    "smiles": c.smiles,
                    "sequence": c.sequence,
                    "scores": c.scores,
                    "combined": c.combined,
                    "raw": c.raw[:200],
                }),
            }
            await asyncio.sleep(0)  # let other tasks run

        yield {"event": "done", "data": json.dumps({"total": len(candidates)})}

    return EventSourceResponse(event_gen())


@app.post("/api/similar")
async def find_similar(req: SimilarRequest) -> list[dict]:
    """Return top-k known antibiotics most similar to the given SMILES,
    using EmbeddingGemma 300m cosine similarity over our indexed corpus."""
    try:
        from src.inference.retrieval import get_retriever
        index_path = os.environ.get(
            "LYSOS_RAG_INDEX",
            "data/processed/known-antibiotics.smiles",
        )
        retr = get_retriever(index_path)
        hits = await asyncio.to_thread(retr.retrieve, req.smiles, k=req.k)
        return hits
    except FileNotFoundError as exc:
        raise HTTPException(503, f"retrieval index not built: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"retrieval failed: {exc}") from exc


@app.get("/api/score")
async def score_smiles(smiles: str = Query(..., min_length=1, max_length=500),
                       target: str = Query("MRSA")) -> dict:
    """Score an arbitrary SMILES the user provides (manual entry)."""
    pathogen = PATHOGEN_BY_SHORT.get(target)
    if pathogen is None:
        raise HTTPException(404, f"unknown pathogen: {target}")

    from src.eval.rewards.activity import predict_mic
    from src.eval.rewards.drug_likeness import qed_score
    from src.eval.rewards.novelty import tanimoto_distance_to_known
    from src.eval.rewards.safety import hemolysis_inverse
    from src.eval.rewards.synth import sa_score
    from src.eval.rewards.validity import smiles_valid

    raws = [f"SMILES: {smiles}"]
    weights = {
        "validity": 0.10,
        "predicted_mic": 0.35,
        "drug_likeness_qed": 0.15,
        "synthesizability": 0.10,
        "hemolysis_safety": 0.15,
        "novelty": 0.15,
    }
    scores = {
        "validity": smiles_valid(raws)[0],
        "predicted_mic": predict_mic(raws, target_pathogen=target)[0],
        "drug_likeness_qed": qed_score(raws)[0],
        "synthesizability": sa_score(raws)[0],
        "hemolysis_safety": hemolysis_inverse(raws)[0],
        "novelty": tanimoto_distance_to_known(raws)[0],
    }
    combined = sum(weights[k] * v for k, v in scores.items())

    return {
        "smiles": smiles,
        "target": target,
        "pathogen": pathogen,
        "scores": scores,
        "combined": combined,
    }


# ----------------------------------------------------------------------------
# Static frontend
# ----------------------------------------------------------------------------


_STATIC_DIR = Path(__file__).parent.parent / "web" / "dist"

if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    async def fallback_index() -> str:
        return """
        <html><head><title>Lysos</title></head>
        <body style="font-family:system-ui;padding:40px;max-width:640px;margin:auto">
            <h1>Lysos API is running</h1>
            <p>Frontend not yet built. Try:</p>
            <ul>
                <li><a href="/api/health">/api/health</a></li>
                <li><a href="/api/pathogens">/api/pathogens</a></li>
                <li><a href="/docs">/docs</a> — interactive API docs</li>
            </ul>
            <p>To build the frontend: <code>cd workspace/web && npm install && npm run build</code></p>
        </body></html>
        """
