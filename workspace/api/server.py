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

# Load .env from repo root if present so env vars (LYSOS_INFERENCE_URL,
# LYSOS_MODEL_ID, GEMINI_API_KEY, etc.) reach os.environ before any
# downstream module reads them. Without this, running the backend with
# `uvicorn workspace.api.server:app` from the repo root won't pick up
# .env automatically — the workbench would fall back to "LLM endpoint
# not configured" even when the SSH tunnel + serve.py on the VM are up.
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parents[2] / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass

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


# Tiny LRU for /api/score so the same (smiles, target) doesn't recompute
# the full reward stack on every refresh. Capped at 256 entries (~1MB).
from collections import OrderedDict as _OD
_SCORE_CACHE: "_OD[tuple[str, str], dict]" = _OD()
_SCORE_CACHE_MAX = 256


def _score_cache_get(smiles: str, target: str) -> Optional[dict]:
    key = (smiles, target)
    if key in _SCORE_CACHE:
        _SCORE_CACHE.move_to_end(key)
        return _SCORE_CACHE[key]
    return None


def _score_cache_put(smiles: str, target: str, payload: dict) -> None:
    key = (smiles, target)
    _SCORE_CACHE[key] = payload
    _SCORE_CACHE.move_to_end(key)
    while len(_SCORE_CACHE) > _SCORE_CACHE_MAX:
        _SCORE_CACHE.popitem(last=False)


def _get_generator():
    """Lazy-import + cache the generator. Heavy init happens once."""
    global _GENERATOR
    if _GENERATOR is None:
        log.info("Cold-start: loading Lysos model (this may take 30-60s)")
        from src.inference.generate import LysosGenerator

        model_id = os.environ.get("LYSOS_MODEL_ID", "rahul24raj/lysos-base-dpo")
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

# Production hardening (rate limits, request-id logs, sanitizer, /api/ready).
# Idempotent — safe to call before or after route inclusion.
from . import hardening as _hardening
_hardening.apply_hardening(app)

# Workbench v2 — agentic playground (multi-agent state machine + 25 tools)
try:
    from .workbench import router as workbench_router
    app.include_router(workbench_router)
except Exception as exc:  # noqa: BLE001
    log.warning("Workbench router not loaded: %s", exc)

# Chemistry 3D — Service 1: Target-Ligand Theater
# Mounts under /workbench/chem/* alongside the existing chem endpoints.
try:
    from .chem_3d import router as chem_3d_router
    app.include_router(chem_3d_router, prefix="/workbench")
    log.info("Chem 3D routes loaded (/workbench/chem/targets, /target/{pdb}, /place-in-pocket)")
except Exception as exc:  # noqa: BLE001
    log.warning("Chem 3D router not loaded: %s", exc)

# Chemistry resistance — Service 2: Resistance-Escape Vulnerability Map
# Mounts under /workbench/chem/* alongside Service 1.
try:
    from .chem_resistance import router as chem_resistance_router
    app.include_router(chem_resistance_router, prefix="/workbench")
    log.info("Chem resistance routes loaded (/workbench/chem/resistance/known, /predict)")
except Exception as exc:  # noqa: BLE001
    log.warning("Chem resistance router not loaded: %s", exc)

# Chemistry pareto — Service 3: Multi-Candidate Pareto Lab
try:
    from .chem_pareto import router as chem_pareto_router
    app.include_router(chem_pareto_router, prefix="/workbench")
    log.info("Chem pareto routes loaded (/workbench/chem/session/{sid}/candidates, /pareto, /axes)")
except Exception as exc:  # noqa: BLE001
    log.warning("Chem pareto router not loaded: %s", exc)

# Synthesis Make-Route — Service 1: retrosynthesis + cost
try:
    from .chem_synthesis import router as chem_synthesis_router
    app.include_router(chem_synthesis_router, prefix="/workbench")
    log.info("Chem synthesis routes loaded (/workbench/chem/synthesis/plan, /routes)")
except Exception as exc:  # noqa: BLE001
    log.warning("Chem synthesis router not loaded: %s", exc)

# Candidate Dossier — integration backbone linking every service
try:
    from .candidate_dossier import router as candidate_dossier_router
    app.include_router(candidate_dossier_router, prefix="/workbench")
    log.info("Candidate dossier routes loaded (/workbench/chem/dossier/{sid})")
except Exception as exc:  # noqa: BLE001
    log.warning("Candidate dossier router not loaded: %s", exc)

# IP / FTO Sentinel — Service 2: freedom-to-operate
try:
    from .chem_ip import router as chem_ip_router
    app.include_router(chem_ip_router, prefix="/workbench")
    log.info("Chem IP/FTO routes loaded (/workbench/chem/ip/fto-scan, /reports)")
except Exception as exc:  # noqa: BLE001
    log.warning("Chem IP/FTO router not loaded: %s", exc)

# ADMET Observatory — Service 3: 5-axis PK panel + agentic fix-design
try:
    from .chem_admet import router as chem_admet_router
    app.include_router(chem_admet_router, prefix="/workbench")
    log.info("Chem ADMET routes loaded (/workbench/chem/admet/panel, /panels)")
except Exception as exc:  # noqa: BLE001
    log.warning("Chem ADMET router not loaded: %s", exc)

# Campaign — the productization backbone (Act II)
try:
    from .campaign import router as campaign_router
    app.include_router(campaign_router, prefix="/workbench")
    log.info("Campaign routes loaded (/workbench/chem/campaign/*)")
except Exception as exc:  # noqa: BLE001
    log.warning("Campaign router not loaded: %s", exc)

# Generation — Service 4: de-novo + lead-opt (BRICS now, GenMol on MI300X)
try:
    from .chem_generate import router as chem_generate_router
    app.include_router(chem_generate_router, prefix="/workbench")
    log.info("Chem generate routes loaded (/workbench/chem/generate)")
except Exception as exc:  # noqa: BLE001
    log.warning("Chem generate router not loaded: %s", exc)

# Peptide (AMP) modality — the second pipeline (Act II dual modality)
try:
    from .chem_peptide import router as chem_peptide_router
    app.include_router(chem_peptide_router, prefix="/workbench")
    log.info("Chem peptide routes loaded (/workbench/chem/peptide/*)")
except Exception as exc:  # noqa: BLE001
    log.warning("Chem peptide router not loaded: %s", exc)

# Retrospective validation — the trust centerpiece (Act II)
try:
    from .validation import router as validation_router
    app.include_router(validation_router, prefix="/workbench")
    log.info("Validation routes loaded (/workbench/chem/validation/*)")
except Exception as exc:  # noqa: BLE001
    log.warning("Validation router not loaded: %s", exc)

# Docking — real binding-affinity prediction (AutoDock Vina scoring fn)
try:
    from .chem_dock import router as chem_dock_router
    app.include_router(chem_dock_router, prefix="/workbench")
    log.info("Chem dock routes loaded (/workbench/chem/dock)")
except Exception as exc:  # noqa: BLE001
    log.warning("Chem dock router not loaded: %s", exc)

# Synthesizability — real SAScore + AiZynth route stats
try:
    from .chem_synth_access import router as chem_synth_access_router
    app.include_router(chem_synth_access_router, prefix="/workbench")
    log.info("Chem synthesizability routes loaded (/workbench/chem/synthesizability)")
except Exception as exc:  # noqa: BLE001
    log.warning("Chem synthesizability router not loaded: %s", exc)

# Report container — snapshot + preview + export
try:
    from .report import router as report_router
    app.include_router(report_router, prefix="/workbench")
    log.info("Report routes loaded (/workbench/report/snapshot, /preview, /export)")
except Exception as exc:  # noqa: BLE001
    log.warning("Report router not loaded: %s", exc)

# Chemistry sandbox — agent-driven molecular edits with reward delta
try:
    from .sandbox import router as sandbox_router
    app.include_router(sandbox_router)
    log.info("Chemistry sandbox routes loaded")
except Exception as exc:  # noqa: BLE001
    log.warning("Sandbox router not loaded: %s", exc)

# Chat + agent harness — slash commands, skills-driven LLM, sandbox WS
try:
    from .chat import router as chat_router
    app.include_router(chat_router)
    log.info("Chat / harness routes loaded (POST /api/chat, WS /ws/session/<id>, GET /api/commands/list)")
except Exception as exc:  # noqa: BLE001
    log.warning("Chat router not loaded: %s", exc)

# Playground — atom-level data API + live-editing WebSocket + chem rules
try:
    from .playground import router as playground_router
    app.include_router(playground_router)
    log.info("Playground routes loaded (atom-level read API + WS /workbench/playground/ws/playground/<id>)")
except Exception as exc:  # noqa: BLE001
    log.warning("Playground router not loaded: %s", exc)

# Agent — Gemini Pro tool-calling agent with SSE streaming
try:
    from .agent import router as agent_router
    app.include_router(agent_router)
    log.info("Agent routes loaded (POST /api/agent/run [SSE], GET /api/agent/tools)")
except Exception as exc:  # noqa: BLE001
    log.warning("Agent router not loaded: %s", exc)

# Workflows — declarative multi-step pipelines + guidance engine
try:
    from .workflows import router as workflows_router
    app.include_router(workflows_router)
    log.info("Workflow routes loaded (GET /api/workflows/list, POST /api/workflows/run [SSE], GET /api/agent/suggest-next)")
except Exception as exc:  # noqa: BLE001
    log.warning("Workflows router not loaded: %s", exc)

# Orchestrator — plain-English prompt → routed execution (workflow / slash / agent / answer)
try:
    from .orchestrator import router as orchestrator_router
    app.include_router(orchestrator_router)
    log.info("Orchestrator routes loaded (POST /api/orchestrator/run [SSE], POST /api/orchestrator/route, GET /api/orchestrator/health)")
except Exception as exc:  # noqa: BLE001
    log.warning("Orchestrator router not loaded: %s", exc)

try:
    from .knowledge import router as knowledge_router  # noqa: E402
    app.include_router(knowledge_router)
    log.info("Knowledge routes loaded (GET /workbench/knowledge/{pathogen})")
except Exception as exc:  # noqa: BLE001
    log.warning("Knowledge router not loaded: %s", exc)

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
    enable_rag: bool = Field(True, description="Use Gemini Embedding 2 to inject known antibiotics as in-context examples")
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
        model=os.environ.get("LYSOS_MODEL_ID", "rahul24raj/lysos-base-dpo"),
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

    # Cold-start lock: serialize the first request so the 60GB model load
    # doesn't get triggered twice in parallel by concurrent first hits.
    gen = await _hardening.with_model_lock(_get_generator)

    # Bound the wall time so a stuck generation can't pin a worker forever.
    t0 = time.perf_counter()
    timeout_s = float(os.environ.get("LYSOS_DESIGN_TIMEOUT_S", "300"))
    try:
        candidates = await asyncio.wait_for(
            asyncio.to_thread(
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
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        raise HTTPException(504, f"design timed out after {timeout_s:.0f}s")
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
        model=os.environ.get("LYSOS_MODEL_ID", "rahul24raj/lysos-base-dpo"),
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
    using Gemini Embedding 2 (gemini-embedding-2) cosine similarity over our indexed corpus."""
    try:
        smi = _hardening.sanitize_smiles(req.smiles)
    except ValueError as exc:
        raise HTTPException(400, f"invalid smiles: {exc}") from exc
    try:
        from src.inference.retrieval import get_retriever
        index_path = os.environ.get(
            "LYSOS_RAG_INDEX",
            "data/processed/known-antibiotics.smiles",
        )
        retr = get_retriever(index_path)
        hits = await asyncio.to_thread(retr.retrieve, smi, k=req.k)
        return hits
    except FileNotFoundError as exc:
        raise HTTPException(503, "retrieval index not built") from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("retrieval failed")
        raise HTTPException(500, "retrieval failed") from exc


@app.get("/api/score")
async def score_smiles(smiles: str = Query(..., min_length=1, max_length=500),
                       target: str = Query("MRSA")) -> dict:
    """Score an arbitrary SMILES the user provides (manual entry)."""
    pathogen = PATHOGEN_BY_SHORT.get(target)
    if pathogen is None:
        raise HTTPException(404, f"unknown pathogen: {target}")
    try:
        smiles = _hardening.sanitize_smiles(smiles)
    except ValueError as exc:
        raise HTTPException(400, f"invalid smiles: {exc}") from exc

    from src.eval.rewards.activity import predict_mic
    from src.eval.rewards.drug_likeness import qed_score
    from src.eval.rewards.novelty import tanimoto_distance_to_known
    from src.eval.rewards.safety import hemolysis_inverse
    from src.eval.rewards.synth import sa_score
    from src.eval.rewards.validity import smiles_valid

    cached = _score_cache_get(smiles, target)
    if cached is not None:
        return cached

    raws = [f"SMILES: {smiles}"]
    weights = {
        "validity": 0.10,
        "predicted_mic": 0.35,
        "drug_likeness_qed": 0.15,
        "synthesizability": 0.10,
        "hemolysis_safety": 0.15,
        "novelty": 0.15,
    }

    def _safe(fn, key: str) -> float:
        try:
            return float(fn())
        except (ImportError, ModuleNotFoundError):
            log.warning("%s scorer skipped — backing module unavailable", key)
            return 0.0
        except Exception as exc:  # noqa: BLE001
            log.warning("%s scorer failed: %s", key, exc)
            return 0.0

    scores = {
        "validity": _safe(lambda: smiles_valid(raws)[0], "validity"),
        "predicted_mic": _safe(lambda: predict_mic(raws, target_pathogen=target)[0], "predicted_mic"),
        "drug_likeness_qed": _safe(lambda: qed_score(raws)[0], "drug_likeness_qed"),
        "synthesizability": _safe(lambda: sa_score(raws)[0], "synthesizability"),
        "hemolysis_safety": _safe(lambda: hemolysis_inverse(raws)[0], "hemolysis_safety"),
        "novelty": _safe(lambda: tanimoto_distance_to_known(raws)[0], "novelty"),
    }
    combined = sum(weights[k] * v for k, v in scores.items())

    payload = {
        "smiles": smiles,
        "target": target,
        "pathogen": pathogen,
        "scores": scores,
        "combined": combined,
    }
    _score_cache_put(smiles, target, payload)
    return payload


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
