"""Workbench API routes — sessions, SSE event bus, tool dispatch.

The Workbench is the new agentic playground (multi-agent state machine + 25
tools + 3D + chat). Lives alongside the legacy Designer routes in server.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

# Workspace-level imports
_WORKSPACE = Path(__file__).resolve().parent.parent
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))

from agents import WorkbenchState, get_llm  # noqa: E402
from agents.graph import run_workbench_loop  # noqa: E402
from agents.state import Constraint  # noqa: E402
from api.notebook import export_session_notebook  # noqa: E402
from tools import registry  # noqa: E402

# Postgres persistence (no-op if LYSOS_DB_URL unset)
try:
    from .db.repository import SessionRepo, CandidateRepo, ToolCallRepo, EventRepo
except Exception:  # noqa: BLE001
    SessionRepo = CandidateRepo = ToolCallRepo = EventRepo = None  # type: ignore[assignment]

log = logging.getLogger("workbench.api")

router = APIRouter(prefix="/workbench", tags=["workbench"])


# ---------------------------------------------------------------------------
# In-memory session store (replace with Postgres in v2)
# ---------------------------------------------------------------------------

_sessions: dict[str, WorkbenchState] = {}
_event_queues: dict[str, asyncio.Queue] = {}


def _get_or_create_queue(session_id: str) -> asyncio.Queue:
    if session_id not in _event_queues:
        _event_queues[session_id] = asyncio.Queue()
    return _event_queues[session_id]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    target_pathogen: str
    mode: str = "design"
    autonomy: str = "copilot"
    constraints: list[dict] = []
    max_iterations: int = 8


class CreateSessionResponse(BaseModel):
    session_id: str


class StartSessionResponse(BaseModel):
    session_id: str
    status: str


class InterventionRequest(BaseModel):
    """Mid-loop user injection.

    kind="constraint" → payload must be {type, field, value} (matches Constraint).
    kind="directive"  → payload is a free-text instruction the Designer reads.
    """
    kind: str  # "constraint" | "directive"
    payload: Any


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    sid = str(uuid.uuid4())
    constraints = []
    for c in req.constraints:
        try:
            constraints.append(Constraint(**c))
        except Exception:
            log.warning("Invalid constraint dropped: %s", c)
    state = WorkbenchState(
        session_id=sid,
        target_pathogen=req.target_pathogen,
        mode=req.mode,
        autonomy=req.autonomy,
        constraints=constraints,
        max_iterations=req.max_iterations,
    )
    _sessions[sid] = state
    _get_or_create_queue(sid)

    # Persist (no-op if Postgres unavailable)
    if SessionRepo is not None:
        try:
            SessionRepo.insert(
                session_id=sid,
                target_pathogen=req.target_pathogen,
                mode=req.mode,
                autonomy=req.autonomy,
                constraints=req.constraints,
                max_iterations=req.max_iterations,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("SessionRepo.insert failed: %s", exc)

    return CreateSessionResponse(session_id=sid)


@router.get("/sessions")
async def list_sessions() -> dict:
    """List in-memory sessions (newest first) for the replay/resume picker."""
    out = []
    for sid, state in _sessions.items():
        last_score = (
            state.candidates[-1].scores.composite if state.candidates else 0.0
        )
        out.append({
            "session_id": sid,
            "target_pathogen": state.target_pathogen,
            "mode": state.mode,
            "autonomy": state.autonomy,
            "iteration": state.iteration,
            "max_iterations": state.max_iterations,
            "n_candidates": len(state.candidates),
            "n_pareto": len(state.pareto_frontier),
            "last_composite": last_score,
            "terminated": state.terminated,
            "termination_reason": state.termination_reason,
        })
    out.sort(key=lambda r: (not r["terminated"], r["iteration"]), reverse=True)
    return {"total": len(out), "sessions": out}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(404, "session not found")
    return state.model_dump(mode="json")


@router.post("/sessions/{session_id}/intervene")
async def intervene(session_id: str, req: InterventionRequest) -> dict:
    """Inject a constraint or directive mid-loop. Consumed by Designer
    on its next iteration via state.consume_interventions().
    """
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(404, "session not found")
    if state.terminated:
        raise HTTPException(409, "session already terminated")
    if req.kind not in ("constraint", "directive"):
        raise HTTPException(422, f"unknown kind: {req.kind!r}")

    # Validate constraint payload shape early so we surface errors to UI
    if req.kind == "constraint":
        try:
            Constraint(**req.payload)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"invalid constraint payload: {exc}")

    state.push_intervention(req.kind, req.payload)

    # Mirror to SSE so the UI sees it appear in the chat panel immediately
    queue = _get_or_create_queue(session_id)
    await queue.put({
        "type": "intervention",
        "agent": "user",
        "data": {"kind": req.kind, "payload": req.payload,
                 "queue_depth": len(state.intervention_queue)},
    })

    return {
        "session_id": session_id,
        "queued": True,
        "queue_depth": len(state.intervention_queue),
    }


@router.get("/sessions/{session_id}/notebook")
async def export_notebook(session_id: str) -> dict:
    """Return the session as a Jupyter notebook (nbformat v4)."""
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(404, "session not found")
    nb = export_session_notebook(state.model_dump(mode="json"))
    return nb


@router.post("/sessions/{session_id}/start", response_model=StartSessionResponse)
async def start_session(session_id: str) -> StartSessionResponse:
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(404, "session not found")
    if state.terminated:
        return StartSessionResponse(session_id=session_id, status="already_terminated")

    queue = _get_or_create_queue(session_id)

    # Persistent trace — JSONL of every event for replay + debugging.
    from .tracing import Tracer
    _tracer = Tracer(session_id=session_id, emit_fn=lambda ev: queue.put(ev))

    async def emit(ev: dict) -> None:
        # Always go through the tracer so every event lands in
        # reports/traces/<session_id>.jsonl + has correlation IDs.
        await _tracer.emit(ev)
        # Persist relevant events
        if EventRepo is not None:
            try:
                EventRepo.append(
                    session_id=session_id,
                    iteration=state.iteration,
                    event_type=ev.get("type", "unknown"),
                    agent=ev.get("agent"),
                    payload=ev.get("data") or {},
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("EventRepo.append failed: %s", exc)

        # Mirror tool calls + candidates into their dedicated tables
        if ev.get("type") == "tool_call_result" and ToolCallRepo is not None:
            d = ev.get("data") or {}
            try:
                ToolCallRepo.insert(
                    call_id=d.get("id"),
                    session_id=session_id,
                    agent=d.get("agent", "system"),
                    tool_name=d.get("tool", "?"),
                    args=d.get("args", {}),
                    result=d.get("result"),
                    error=d.get("error"),
                    duration_ms=d.get("duration_ms", 0),
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("ToolCallRepo.insert failed: %s", exc)
        if ev.get("type") == "candidate_added" and CandidateRepo is not None:
            d = ev.get("data") or {}
            try:
                CandidateRepo.insert(
                    candidate_id=d.get("id"),
                    session_id=session_id,
                    parent_id=d.get("parent_id"),
                    smiles=d.get("smiles", ""),
                    pathogen=d.get("pathogen", state.target_pathogen),
                    scores=d.get("scores", {}),
                    similar_to=d.get("similar_to", []),
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("CandidateRepo.insert failed: %s", exc)

    async def runner() -> None:
        try:
            await run_workbench_loop(state, emit)
            if SessionRepo is not None:
                try:
                    SessionRepo.update_termination(
                        session_id, state.terminated, state.termination_reason,
                    )
                except Exception:
                    pass
            await queue.put({"type": "session_complete", "data": {"session_id": session_id}})
        except Exception as exc:  # noqa: BLE001
            log.exception("Session %s crashed", session_id)
            await queue.put({"type": "error", "data": str(exc)})
        finally:
            await queue.put(None)  # signal SSE consumer to close

    asyncio.create_task(runner())
    return StartSessionResponse(session_id=session_id, status="running")


@router.get("/sessions/{session_id}/events")
async def stream_events(session_id: str, request: Request):
    if session_id not in _sessions:
        raise HTTPException(404, "session not found")
    queue = _get_or_create_queue(session_id)

    async def event_gen() -> AsyncIterator[dict]:
        while True:
            if await request.is_disconnected():
                break
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "{}"}
                continue
            if ev is None:
                break
            yield {"event": ev.get("type", "message"), "data": json.dumps(ev)}

    return EventSourceResponse(event_gen())


@router.get("/skills")
async def list_skills() -> dict:
    """Expose the full tool registry to UI / external integrators."""
    schemas = registry.schemas()
    by_category: dict[str, list[dict]] = {}
    for s in schemas:
        by_category.setdefault(s["category"], []).append(s)
    return {"total": len(schemas), "by_category": by_category}


@router.post("/tools/{tool_name}")
async def invoke_tool(tool_name: str, args: dict[str, Any]) -> dict:
    """Direct tool invocation (MCP-compatible)."""
    t = registry.get(tool_name)
    if t is None:
        raise HTTPException(404, f"unknown tool {tool_name}")
    return t.call(args)


# ---------------------------------------------------------------------------
# 3D molecule endpoint — RDKit-generated proper SDF for the ligand viewer.
# Without this the frontend falls back to cactus.nci.nih.gov / in-browser
# parsing which produces flat / broken renderings for novel SMILES.
# ---------------------------------------------------------------------------

class Mol3DRequest(BaseModel):
    smiles: str
    optimize: bool = True
    add_hydrogens: bool = True
    seed: int = 0xC0FFEE


# ---------------------------------------------------------------------------
# W1 — Design (one-shot create+start; pathogen + objective → multi-agent loop)
# ---------------------------------------------------------------------------


class DesignRequest(BaseModel):
    pathogen: str = Field(..., description="WHO-priority pathogen code (MRSA, Mtb, …)")
    objective: Optional[str] = Field(
        None,
        description="Free-text design objective (e.g. 'non-toxic macrolide that escapes mecA')",
    )
    constraints: list[dict] = Field(default_factory=list)
    max_iterations: int = 8
    autonomy: Literal["auto", "copilot", "manual"] = "copilot"


class DesignResponse(BaseModel):
    session_id: str
    pathogen: str
    objective: Optional[str]
    sse_url: str
    status: str


@router.post("/design", response_model=DesignResponse)
async def workbench_design(req: DesignRequest) -> DesignResponse:
    """W1 entry point — kicks off a full multi-agent design session.

    Creates a WorkbenchState, queues the user objective as a directive
    intervention so the Designer reads it on iteration 1, spawns the
    multi-agent loop in the background, and returns the session_id.

    Frontend subscribes to /workbench/sessions/{id}/events (SSE) for
    live event streaming (agent_message, candidate_added, iteration_*,
    score, session_complete).
    """
    sid = str(uuid.uuid4())

    # Materialize constraints (drop unparseable, log)
    constraints: list[Constraint] = []
    for c in req.constraints:
        try:
            constraints.append(Constraint(**c))
        except Exception:
            log.warning("Invalid constraint dropped: %s", c)

    state = WorkbenchState(
        session_id=sid,
        target_pathogen=req.pathogen,  # type: ignore[arg-type]
        mode="design",
        autonomy=req.autonomy,
        constraints=constraints,
        max_iterations=req.max_iterations,
    )

    # Queue the free-text objective as a directive so Designer picks it up
    if req.objective:
        state.push_intervention("directive", {"text": req.objective})

    _sessions[sid] = state
    queue = _get_or_create_queue(sid)

    # Persist (no-op if Postgres unavailable)
    if SessionRepo is not None:
        try:
            SessionRepo.insert(
                session_id=sid,
                target_pathogen=req.pathogen,
                mode="design",
                autonomy=req.autonomy,
                constraints=req.constraints,
                max_iterations=req.max_iterations,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("SessionRepo.insert failed: %s", exc)

    # Spawn the loop. Mirror the start_session pattern: tracer wraps emit,
    # Postgres mirrors get/cand/tool tables, queue feeds SSE consumer.
    # ALSO: HarnessAdapter mirrors events into the playground bus + SQLite
    # so the canvas (3D / 2D / radar / agent-trace windows) updates live.
    from .tracing import Tracer
    _tracer = Tracer(session_id=sid, emit_fn=lambda ev: queue.put(ev))
    try:
        from workspace.playground import HarnessAdapter
        _adapter = HarnessAdapter(session_id=sid, target_pathogen=req.pathogen)
    except Exception as exc:  # noqa: BLE001
        log.warning("HarnessAdapter not available: %s", exc)
        _adapter = None

    async def emit(ev: dict) -> None:
        # Always go through the tracer so SSE clients keep working
        await _tracer.emit(ev)
        # Also mirror to the playground bus + SQLite for live canvas
        if _adapter is not None:
            await _adapter.emit(ev)

    async def runner() -> None:
        try:
            await run_workbench_loop(state, emit)
            if SessionRepo is not None:
                try:
                    SessionRepo.update_termination(
                        sid, state.terminated, state.termination_reason,
                    )
                except Exception:
                    pass
            await queue.put({"type": "session_complete", "data": {"session_id": sid}})
        except Exception as exc:  # noqa: BLE001
            log.exception("Design session %s crashed", sid)
            await queue.put({"type": "error", "data": str(exc)})
        finally:
            await queue.put(None)

    asyncio.create_task(runner())

    return DesignResponse(
        session_id=sid,
        pathogen=req.pathogen,
        objective=req.objective,
        sse_url=f"/workbench/sessions/{sid}/events",
        status="running",
    )


# ---------------------------------------------------------------------------
# Scaffold templates — curated starting molecules for "build from"
# ---------------------------------------------------------------------------


SCAFFOLD_TEMPLATES = [
    {"id": "benzene", "name": "Benzene", "category": "ring",
     "smiles": "c1ccccc1", "tag": "aromatic 6-ring"},
    {"id": "pyridine", "name": "Pyridine", "category": "ring",
     "smiles": "c1ccncc1", "tag": "aromatic 6-ring with N"},
    {"id": "pyrimidine", "name": "Pyrimidine", "category": "ring",
     "smiles": "c1ncncc1", "tag": "aromatic, 2 N"},
    {"id": "cyclohexane", "name": "Cyclohexane", "category": "ring",
     "smiles": "C1CCCCC1", "tag": "saturated 6-ring"},
    {"id": "imidazole", "name": "Imidazole", "category": "ring",
     "smiles": "c1[nH]cnc1", "tag": "aromatic 5-ring (2 N)"},
    {"id": "thiophene", "name": "Thiophene", "category": "ring",
     "smiles": "c1ccsc1", "tag": "aromatic 5-ring with S"},

    {"id": "beta_lactam", "name": "β-Lactam (penam core)", "category": "antibiotic",
     "smiles": "O=C1CCN1", "tag": "4-ring · MRSA target (penicillins)"},
    {"id": "cephem", "name": "Cephem core", "category": "antibiotic",
     "smiles": "O=C1N2CCSC2C1", "tag": "fused β-lactam (cephalosporins)"},
    {"id": "carbapenem", "name": "Carbapenem core", "category": "antibiotic",
     "smiles": "O=C1N2CCC2C1", "tag": "MRSA-active β-lactam"},
    {"id": "monobactam", "name": "Monobactam (aztreonam-like)", "category": "antibiotic",
     "smiles": "O=C1CCN1S(=O)(=O)O", "tag": "Gram-neg β-lactam"},
    {"id": "fluoroquinolone", "name": "Fluoroquinolone (cipro core)", "category": "antibiotic",
     "smiles": "O=C(O)c1cnc2ccc(F)cc2c1=O", "tag": "DNA gyrase inhibitor"},
    {"id": "oxazolidinone", "name": "Oxazolidinone (linezolid core)", "category": "antibiotic",
     "smiles": "O=C1OCCN1", "tag": "ribosome 50S inhibitor (active vs MRSA/VRE)"},
    {"id": "macrolide_aglycone", "name": "Macrolide aglycone (erythronolide)", "category": "antibiotic",
     "smiles": "CCC1OC(=O)C(C)C(O)C(C)C(=O)C(C)CC(C)C(O)C(C)C(=O)O1", "tag": "14-member ring · 50S binder"},
    {"id": "tetracycline_core", "name": "Tetracycline 4-ring core", "category": "antibiotic",
     "smiles": "Oc1ccc2c(c1)CC1CC3CC(=O)C(=C(O)c3c1C2)C(N)=O", "tag": "broad-spectrum scaffold"},
    {"id": "vancomycin_micro", "name": "Vancomycin glycopeptide micro-fragment", "category": "antibiotic",
     "smiles": "NC(CC(=O)N)C(=O)O", "tag": "D-Ala-D-Ala mimic"},

    {"id": "aspirin", "name": "Aspirin", "category": "drug",
     "smiles": "CC(=O)Oc1ccccc1C(=O)O", "tag": "common test molecule"},
    {"id": "caffeine", "name": "Caffeine", "category": "drug",
     "smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "tag": "purine, multi-N reference"},
    {"id": "amoxicillin", "name": "Amoxicillin", "category": "drug",
     "smiles": "CC1(C)SC2C(NC(=O)C(N)c3ccc(O)cc3)C(=O)N2C1C(=O)O", "tag": "MRSA reference (FDA)"},
    {"id": "ciprofloxacin", "name": "Ciprofloxacin", "category": "drug",
     "smiles": "O=C(O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O", "tag": "fluoroquinolone (FDA)"},
    {"id": "linezolid", "name": "Linezolid", "category": "drug",
     "smiles": "CC(=O)NC[C@H]1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1", "tag": "VRE/MRSA (FDA)"},

    {"id": "empty", "name": "Empty (start from atom)", "category": "scratch",
     "smiles": "C", "tag": "single carbon — build from scratch"},
]


@router.get("/playground/scaffolds")
async def list_scaffolds() -> dict:
    """Curated scaffold templates for 'start from'. Each has SMILES + a
    short pharmacology tag for the picker UI."""
    return {"total": len(SCAFFOLD_TEMPLATES), "scaffolds": SCAFFOLD_TEMPLATES}


# ---------------------------------------------------------------------------
# CHEM RULES ENGINE — atom-level chemistry knowledge for the playground.
#
# The 2D builder window calls this whenever the user clicks an atom on a
# molecule. The agents call it as a tool to query "what can I attach
# here?" instead of hallucinating chemistry.
#
# Returns: valence + neighbours + allowed_attachments[] + sar_notes[]
# grounded in:
#   - RDKit GetAtomWithIdx().GetTotalNumHs() / GetExplicitValence() rules
#   - Static functional-group library (carboxyl, amine, hydroxyl, etc.)
#   - Curated 387-drug corpus search for SAR mentions of analogous positions
# ---------------------------------------------------------------------------


class AllowedAttachment(BaseModel):
    label: str                  # human-readable button text e.g. "+F"
    op: str                     # "swap_element" | "add_methyl" | "add_functional_group"
    new_element: Optional[str] = None
    functional_group: Optional[str] = None
    note: str = ""              # one-liner reason ("common SAR position")


class AtomNeighbor(BaseModel):
    idx: int
    element: str
    bond: str                   # "single" | "double" | "triple" | "aromatic"


class SARNote(BaseModel):
    drug: str
    position: str
    effect: str


class AtomContextResponse(BaseModel):
    smiles: str
    atom_idx: int
    element: str
    formal_charge: int
    is_aromatic: bool
    in_ring: bool
    ring_size: int = 0
    explicit_valence: int
    implicit_valence: int
    n_hydrogens: int
    # Richer chemistry context — added for the workbench atoms-rail redesign.
    atomic_number: int = 0
    atomic_mass: float = 0.0
    hybridization: str = "unspecified"   # sp / sp2 / sp3 / sp3d / sp3d2
    degree: int = 0                      # explicit (heavy-atom) neighbor count
    total_degree: int = 0                # explicit + implicit-H neighbors
    free_valence: int = 0                # remaining single-bond slots = n_H
    is_chiral: bool = False              # chirality tag set
    is_isotope: bool = False             # isotope mass set
    cip_code: str = ""                   # R / S / "" if not assigned
    neighbors: list[AtomNeighbor]
    allowed_attachments: list[AllowedAttachment]
    sar_notes: list[SARNote]


# Functional-group quick-add palette (only attaches to atoms with free H)
_FUNCTIONAL_GROUPS: list[dict] = [
    {"name": "hydroxyl",   "label": "+OH",   "smiles_part": "O",     "valence_used": 1},
    {"name": "methyl",     "label": "+CH₃",  "smiles_part": "C",     "valence_used": 1},
    {"name": "fluorine",   "label": "+F",    "smiles_part": "F",     "valence_used": 1},
    {"name": "chlorine",   "label": "+Cl",   "smiles_part": "Cl",    "valence_used": 1},
    {"name": "amine",      "label": "+NH₂",  "smiles_part": "N",     "valence_used": 1},
    {"name": "cyano",      "label": "+CN",   "smiles_part": "C#N",   "valence_used": 1},
    {"name": "carboxyl",   "label": "+COOH", "smiles_part": "C(=O)O","valence_used": 1},
    {"name": "methoxy",    "label": "+OCH₃", "smiles_part": "OC",    "valence_used": 1},
    {"name": "trifluoromethyl", "label": "+CF₃", "smiles_part": "C(F)(F)F", "valence_used": 1},
]


def _sar_lookup(element: str, neighborhood_smiles: str, target: Optional[str]) -> list[SARNote]:
    """Cheap text search over the 387-drug corpus for SAR mentions that
    might apply to this atom. Returns up to 3 most-relevant notes."""
    try:
        idx = _load_pharma_ground()
    except Exception:
        return []
    out: list[SARNote] = []
    needle = element.lower()
    for entry in idx:
        resp = (entry.get("response") or "").lower()
        if needle not in resp:
            continue
        # Look for nearby phrases like "C6", "+F at C6", "ortho", "para", etc.
        import re
        m = re.search(rf"[+\-]?{element}\s*(?:at|on)?\s*([A-Z]\d+|ortho|para|meta|C-?\d+)", resp)
        if not m:
            continue
        out.append(SARNote(
            drug=entry.get("drug", "?"),
            position=m.group(1),
            effect=resp[max(0, m.start()-30):m.end()+80].replace("\n", " ")[:140],
        ))
        if len(out) >= 3:
            break
    return out


def _decode_smiles_b64(smiles_b64: str) -> str:
    """Decode URL-safe base64 SMILES, restoring missing padding.
    Frontend strips `=` for cleaner URLs (per RFC 4648 §5); we have to
    add it back before calling urlsafe_b64decode (which is strict)."""
    import base64
    raw = smiles_b64.encode("ascii")
    pad = (-len(raw)) % 4
    if pad:
        raw = raw + (b"=" * pad)
    return base64.urlsafe_b64decode(raw).decode()


@router.get("/chem/elements")
async def chem_elements_palette() -> Dict[str, Any]:
    """Element palette supported by /molecule/edit. Returns symbol → metadata
    (atomic number, common valences, name, group). The frontend uses this
    to render the periodic-table dropdown for swap_element / add_atom_at,
    so the palette stays in sync with the backend automatically."""
    # symbol → (atomic_number, common_valences, full_name, group)
    PALETTE: List[Dict[str, Any]] = [
        # H + group 1/2 + p-block essentials
        {"sym": "H",  "Z": 1,  "valences": [1],     "name": "Hydrogen",  "group": "nonmetal"},
        {"sym": "Li", "Z": 3,  "valences": [1],     "name": "Lithium",   "group": "alkali"},
        {"sym": "Be", "Z": 4,  "valences": [2],     "name": "Beryllium", "group": "alkaline-earth"},
        {"sym": "B",  "Z": 5,  "valences": [3],     "name": "Boron",     "group": "metalloid"},
        {"sym": "C",  "Z": 6,  "valences": [4],     "name": "Carbon",    "group": "nonmetal"},
        {"sym": "N",  "Z": 7,  "valences": [3, 5],  "name": "Nitrogen",  "group": "nonmetal"},
        {"sym": "O",  "Z": 8,  "valences": [2],     "name": "Oxygen",    "group": "nonmetal"},
        {"sym": "F",  "Z": 9,  "valences": [1],     "name": "Fluorine",  "group": "halogen"},
        {"sym": "Na", "Z": 11, "valences": [1],     "name": "Sodium",    "group": "alkali"},
        {"sym": "Mg", "Z": 12, "valences": [2],     "name": "Magnesium", "group": "alkaline-earth"},
        {"sym": "Al", "Z": 13, "valences": [3],     "name": "Aluminum",  "group": "post-transition"},
        {"sym": "Si", "Z": 14, "valences": [4],     "name": "Silicon",   "group": "metalloid"},
        {"sym": "P",  "Z": 15, "valences": [3, 5],  "name": "Phosphorus","group": "nonmetal"},
        {"sym": "S",  "Z": 16, "valences": [2, 4, 6], "name": "Sulfur",  "group": "nonmetal"},
        {"sym": "Cl", "Z": 17, "valences": [1, 3, 5, 7], "name": "Chlorine", "group": "halogen"},
        {"sym": "K",  "Z": 19, "valences": [1],     "name": "Potassium", "group": "alkali"},
        {"sym": "Ca", "Z": 20, "valences": [2],     "name": "Calcium",   "group": "alkaline-earth"},
        # Drug-relevant transition metals
        {"sym": "Ti", "Z": 22, "valences": [4],     "name": "Titanium",  "group": "transition"},
        {"sym": "V",  "Z": 23, "valences": [3, 5],  "name": "Vanadium",  "group": "transition"},
        {"sym": "Cr", "Z": 24, "valences": [3, 6],  "name": "Chromium",  "group": "transition"},
        {"sym": "Mn", "Z": 25, "valences": [2, 4, 7], "name": "Manganese","group": "transition"},
        {"sym": "Fe", "Z": 26, "valences": [2, 3],  "name": "Iron",      "group": "transition"},
        {"sym": "Co", "Z": 27, "valences": [2, 3],  "name": "Cobalt",    "group": "transition"},
        {"sym": "Ni", "Z": 28, "valences": [2],     "name": "Nickel",    "group": "transition"},
        {"sym": "Cu", "Z": 29, "valences": [1, 2],  "name": "Copper",    "group": "transition"},
        {"sym": "Zn", "Z": 30, "valences": [2],     "name": "Zinc",      "group": "transition"},
        {"sym": "As", "Z": 33, "valences": [3, 5],  "name": "Arsenic",   "group": "metalloid"},
        {"sym": "Se", "Z": 34, "valences": [2, 4, 6], "name": "Selenium","group": "nonmetal"},
        {"sym": "Br", "Z": 35, "valences": [1, 3, 5], "name": "Bromine", "group": "halogen"},
        {"sym": "Mo", "Z": 42, "valences": [4, 6],  "name": "Molybdenum","group": "transition"},
        {"sym": "Ru", "Z": 44, "valences": [2, 3],  "name": "Ruthenium", "group": "transition"},
        {"sym": "Pd", "Z": 46, "valences": [2],     "name": "Palladium", "group": "transition"},
        {"sym": "Ag", "Z": 47, "valences": [1],     "name": "Silver",    "group": "transition"},
        {"sym": "I",  "Z": 53, "valences": [1, 3, 5, 7], "name": "Iodine","group": "halogen"},
        {"sym": "Pt", "Z": 78, "valences": [2, 4],  "name": "Platinum",  "group": "transition"},
        {"sym": "Au", "Z": 79, "valences": [1, 3],  "name": "Gold",      "group": "transition"},
        {"sym": "Hg", "Z": 80, "valences": [1, 2],  "name": "Mercury",   "group": "transition"},
    ]
    return {"elements": PALETTE, "count": len(PALETTE)}


# ---------------------------------------------------------------------------
# Chemistry-law gating + diagnostics + structured violations.
# Rule of the workbench: never offer an action the user (or agent) cannot
# legally perform. The frontend pre-filters its palettes from these
# endpoints, and the /molecule/edit failure path returns the same
# structured `ChemViolation` shape so toasts, inline errors, and agent
# replies all share one vocabulary.
# ---------------------------------------------------------------------------

# Common bond-cost (single bonds the FG/ring will consume off the anchor)
_FG_BOND_COST: Dict[str, int] = {
    "hydroxyl": 1, "methyl": 1, "amine": 1, "fluorine": 1, "chlorine": 1,
    "bromine": 1, "iodine": 1, "thiol": 1, "carbonyl": 1, "aldehyde": 1,
    "carboxyl": 1, "ester": 1, "amide": 1, "nitro": 1, "sulfonyl": 1,
    "sulfonamide": 1, "sulfide": 1, "phosphate": 1, "phosphonate": 1,
    "cyano": 1, "isocyano": 1, "azido": 1, "trifluoromethyl": 1,
    "trichloromethyl": 1, "ethyl": 1, "vinyl": 1, "ethynyl": 1,
    "methoxy": 1, "ethoxy": 1, "isopropyl": 1, "tert-butyl": 1, "phenyl": 1,
}

# Default valences (max bonds an atom can have, ignoring formal charge)
_DEFAULT_VALENCE: Dict[str, int] = {
    "H": 1, "B": 3, "C": 4, "N": 3, "O": 2, "F": 1,
    "Si": 4, "P": 3, "S": 2, "Cl": 1, "Br": 1, "I": 1,
    "Se": 2, "As": 3,
    # Metals/heavies — varies; use conservative max
    "Li": 1, "Na": 1, "K": 1, "Mg": 2, "Ca": 2, "Al": 3,
    "Ti": 4, "V": 5, "Cr": 6, "Mn": 7, "Fe": 6, "Co": 6, "Ni": 6,
    "Cu": 4, "Zn": 4, "Mo": 6, "Ru": 6, "Pd": 4, "Ag": 4,
    "Pt": 6, "Au": 5, "Hg": 2,
}


def _violation(code: str, message: str, hint: str = "",
               atom_idx: Optional[int] = None,
               bond_idx: Optional[int] = None,
               suggested_fix: str = "") -> Dict[str, Any]:
    """Structured violation payload — used both in 422 detail bodies and
    in /chem/diagnostics + /chem/valid-actions blocked_reasons. Agents
    parse `code`; humans read `message` + `hint`."""
    return {
        "code": code,
        "message": message,
        "hint": hint,
        "atom_idx": atom_idx,
        "bond_idx": bond_idx,
        "suggested_fix": suggested_fix,
    }


@router.get("/chem/valid-actions/{smiles_b64}/{atom_idx}")
async def chem_valid_actions(smiles_b64: str, atom_idx: int) -> Dict[str, Any]:
    """Pre-filter palette for an anchor atom. Returns ONLY the actions
    that won't violate chemistry laws — the frontend uses this to render
    valid options upfront instead of grey-out + 422-on-attempt.

    Returns:
      {
        atom_idx, element, free_valence,
        valid_elements_for_swap: [str, ...],      # element symbols that
                                                  # respect existing bonds
        valid_functional_groups: [str, ...],      # FGs whose cost ≤ free_v
        valid_rings: bool,                        # any ring attaches?
        valid_bond_orders_to_neighbors: {nb_idx: ["single","double",...]},
        blocked_reasons: [ChemViolation, ...],    # why other actions blocked
      }
    """
    try:
        from rdkit import Chem
    except ImportError:
        raise HTTPException(503, "RDKit not available")
    try:
        smiles = _decode_smiles_b64(smiles_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, detail=_violation(
            "decode_failed", f"smiles decode failed: {exc}",
            hint="Frontend should pass URL-safe base64 of canonical SMILES.",
        ))
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(422, detail=_violation(
            "unparseable_smiles", f"unparseable SMILES: {smiles}",
            hint="RDKit could not parse this structure. Check ring closures + valence.",
        ))
    if atom_idx < 0 or atom_idx >= mol.GetNumAtoms():
        raise HTTPException(422, detail=_violation(
            "atom_index_out_of_range",
            f"atom_idx {atom_idx} out of range (0..{mol.GetNumAtoms()-1})",
            atom_idx=atom_idx,
        ))
    atom = mol.GetAtomWithIdx(atom_idx)
    elt = atom.GetSymbol()
    n_h = atom.GetTotalNumHs()
    free_valence = n_h
    explicit_v = atom.GetExplicitValence()

    blocked: list[Dict[str, Any]] = []

    # 1) Valid functional groups — cost ≤ free_valence
    valid_fgs: list[str] = []
    for fg, cost in _FG_BOND_COST.items():
        if cost <= free_valence:
            valid_fgs.append(fg)
        else:
            blocked.append(_violation(
                "fg_no_free_valence",
                f"functional group '{fg}' needs {cost} free bond slot(s); atom {atom_idx} has {free_valence}",
                hint=f"Free up a slot on atom {atom_idx} by deleting a neighbor or breaking a bond.",
                atom_idx=atom_idx,
                suggested_fix=f"break a bond on atom {atom_idx} first",
            ))

    # 2) Valid rings — any ring attach needs ≥1 free bond
    valid_rings = free_valence >= 1
    if not valid_rings:
        blocked.append(_violation(
            "ring_no_free_valence",
            f"atom {atom_idx} has no free bond slots; cannot attach a ring",
            hint="Rings attach via a single bond from anchor to first ring atom.",
            atom_idx=atom_idx,
            suggested_fix=f"break a bond on atom {atom_idx} first",
        ))

    # 3) Valid swap elements — preserve existing explicit valence.
    # An element is a candidate iff its default max valence ≥ explicit_v.
    valid_swap_elements: list[str] = []
    for sym, max_v in _DEFAULT_VALENCE.items():
        if sym == elt:
            continue
        if max_v >= explicit_v:
            valid_swap_elements.append(sym)
        else:
            blocked.append(_violation(
                "swap_element_undervalent",
                f"swapping atom {atom_idx} ({elt}) → {sym} would over-valence "
                f"(needs ≥{explicit_v} bonds, {sym} max is {max_v})",
                hint=f"{sym} can hold at most {max_v} bonds.",
                atom_idx=atom_idx,
                suggested_fix=f"break {explicit_v - max_v} bond(s) first",
            ))

    # 4) Valid bond orders to existing neighbors (for upgrade attempts)
    valid_bond_orders: Dict[int, list[str]] = {}
    for nb in atom.GetNeighbors():
        b = mol.GetBondBetweenAtoms(atom_idx, nb.GetIdx())
        cur = "single"
        if b:
            bt = b.GetBondType()
            if bt == Chem.BondType.DOUBLE: cur = "double"
            elif bt == Chem.BondType.TRIPLE: cur = "triple"
            elif bt == Chem.BondType.AROMATIC: cur = "aromatic"
        # An upgrade from single→double consumes 1 more H from each end;
        # only valid if both atoms have ≥1 free valence.
        nb_free = nb.GetTotalNumHs()
        upgrades = []
        if cur == "single":
            if free_valence >= 1 and nb_free >= 1:
                upgrades.append("double")
            if free_valence >= 2 and nb_free >= 2:
                upgrades.append("triple")
        elif cur == "double":
            if free_valence >= 1 and nb_free >= 1:
                upgrades.append("triple")
        valid_bond_orders[nb.GetIdx()] = [cur] + upgrades

    return {
        "atom_idx": atom_idx,
        "element": elt,
        "free_valence": free_valence,
        "explicit_valence": explicit_v,
        "valid_elements_for_swap": valid_swap_elements,
        "valid_functional_groups": valid_fgs,
        "valid_rings": valid_rings,
        "valid_bond_orders_to_neighbors": valid_bond_orders,
        "blocked_reasons": blocked,
    }


@router.get("/chem/diagnostics/{smiles_b64}")
async def chem_diagnostics(smiles_b64: str) -> Dict[str, Any]:
    """Whole-molecule chemistry health check. Returns structured
    violations for every atom whose explicit valence < expected (broken
    bond after a delete/break), invalid charge balances, and any
    Sanitize warnings RDKit can give us.

    The 2D viewer uses this to highlight incomplete atoms (red pulse)
    after a bond-break, and to gate scoring."""
    try:
        from rdkit import Chem
    except ImportError:
        raise HTTPException(503, "RDKit not available")
    try:
        smiles = _decode_smiles_b64(smiles_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, detail=_violation(
            "decode_failed", f"smiles decode failed: {exc}"))
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(422, detail=_violation(
            "unparseable_smiles", f"unparseable SMILES: {smiles}",
            hint="See atom-by-atom diagnostics by editing one step back.",
            suggested_fix="undo last edit",
        ))

    incomplete: list[Dict[str, Any]] = []
    for atom in mol.GetAtoms():
        sym = atom.GetSymbol()
        max_v = _DEFAULT_VALENCE.get(sym, 0)
        if max_v == 0:
            continue
        # Account for formal charge: +1 raises valence by 1, −1 lowers it.
        adjusted_max = max_v + atom.GetFormalCharge()
        explicit = atom.GetExplicitValence()
        n_h = atom.GetTotalNumHs()
        total = explicit + n_h
        if total < adjusted_max - 1:  # under-valent by ≥2 → likely broken
            incomplete.append(_violation(
                "atom_under_valent",
                f"atom {atom.GetIdx()} ({sym}) has only {total} bonds; expected {adjusted_max}",
                hint=f"{sym} normally forms {adjusted_max} bonds. After a bond-break this atom needs reconnection.",
                atom_idx=atom.GetIdx(),
                suggested_fix=f"add a bond or H on atom {atom.GetIdx()}",
            ))

    # Charge balance — track total formal charge
    total_charge = sum(a.GetFormalCharge() for a in mol.GetAtoms())
    charge_warnings: list[Dict[str, Any]] = []
    if abs(total_charge) > 0:
        charge_warnings.append(_violation(
            "non_zero_total_charge",
            f"total formal charge = {total_charge:+d}",
            hint="Most drugs are net-neutral. Consider counterions or an opposite charge elsewhere.",
            suggested_fix="add a counterion or balance the charge",
        ))

    # Disconnected fragments — return per-atom fragment ids so the
    # frontend can highlight all atoms in NON-main fragments (the
    # "broken-off" pieces that need reconnection).
    frags = Chem.GetMolFrags(mol)
    n_frags = len(frags)
    fragment_warnings: list[Dict[str, Any]] = []
    fragment_atom_ids: list[list[int]] = [list(f) for f in frags]
    # Largest fragment is the "main" one; others are broken-off.
    main_frag_idx = max(range(n_frags), key=lambda i: len(frags[i])) if n_frags else 0
    broken_off_atom_ids: list[int] = []
    if n_frags > 1:
        for i, f in enumerate(frags):
            if i != main_frag_idx:
                broken_off_atom_ids.extend(list(f))
        fragment_warnings.append(_violation(
            "disconnected_fragments",
            f"molecule has {n_frags} disconnected fragments",
            hint="A bond was broken without reconnection; molecule is no longer one piece.",
            suggested_fix="reconnect the fragments with add_bond",
        ))

    # Single unified status — frontend renders this as one badge at the
    # top of the 2D viewer. tier: "ok" (green) | "warn" (amber) | "block" (red)
    if n_frags > 1 or incomplete:
        status_tier = "block"
        status_label = (
            f"{n_frags} fragments"      if n_frags > 1
            else f"{len(incomplete)} under-valent"
        )
    elif charge_warnings:
        status_tier = "warn"
        status_label = f"charge {total_charge:+d}"
    else:
        status_tier = "ok"
        status_label = "valid"

    return {
        "is_valid": (not incomplete) and (n_frags == 1),
        "n_atoms": mol.GetNumAtoms(),
        "n_bonds": mol.GetNumBonds(),
        "n_fragments": n_frags,
        "total_formal_charge": total_charge,
        "incomplete_atoms": incomplete,
        "charge_warnings": charge_warnings,
        "fragment_warnings": fragment_warnings,
        "all_violations": incomplete + charge_warnings + fragment_warnings,
        # New fields — per-atom fragment membership + broken-off ids +
        # single unified status tag for the top-of-viewer badge.
        "fragment_atom_ids": fragment_atom_ids,
        "main_fragment_idx": main_frag_idx,
        "broken_off_atom_ids": broken_off_atom_ids,
        "status_tier": status_tier,
        "status_label": status_label,
    }


@router.get("/chem/bonds/{smiles_b64}")
async def chem_bonds(smiles_b64: str) -> Dict[str, Any]:
    """List every bond in the molecule with structured metadata. The 2D
    viewer uses this to translate a click on a bond glyph back to the
    correct bond_index for /molecule/edit op:break_bond."""
    try:
        from rdkit import Chem
    except ImportError:
        raise HTTPException(503, "RDKit not available")
    try:
        smiles = _decode_smiles_b64(smiles_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, detail=_violation(
            "decode_failed", f"smiles decode failed: {exc}"))
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(422, detail=_violation(
            "unparseable_smiles", f"unparseable SMILES: {smiles}"))
    bonds = []
    for b in mol.GetBonds():
        bt = b.GetBondType()
        order = "single"
        if bt == Chem.BondType.DOUBLE:    order = "double"
        elif bt == Chem.BondType.TRIPLE:  order = "triple"
        elif bt == Chem.BondType.AROMATIC: order = "aromatic"
        bonds.append({
            "bond_idx": b.GetIdx(),
            "atom_a": b.GetBeginAtomIdx(),
            "atom_b": b.GetEndAtomIdx(),
            "order": order,
            "in_ring": b.IsInRing(),
            "is_aromatic": b.GetIsAromatic(),
        })
    return {"bonds": bonds, "n_bonds": len(bonds)}


@router.get("/chem/atom/{smiles_b64}/{atom_idx}", response_model=AtomContextResponse)
async def chem_atom_context(smiles_b64: str, atom_idx: int,
                             target: Optional[str] = None) -> AtomContextResponse:
    """SMILES is base64-urlsafe encoded to dodge URL-special-chars
    (ring bonds, slashes, etc.) — frontend wraps with btoa(smi).
    Padding `=` is stripped client-side; _decode_smiles_b64 restores it."""
    try:
        smiles = _decode_smiles_b64(smiles_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"smiles base64 decode failed: {exc}")

    try:
        from rdkit import Chem
    except ImportError:
        raise HTTPException(503, "RDKit not available")

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")
    if atom_idx < 0 or atom_idx >= mol.GetNumAtoms():
        raise HTTPException(422, f"atom_idx {atom_idx} out of range (0..{mol.GetNumAtoms()-1})")

    atom = mol.GetAtomWithIdx(atom_idx)
    elt = atom.GetSymbol()

    # Neighbours
    neighbors: list[AtomNeighbor] = []
    for nb in atom.GetNeighbors():
        bond = mol.GetBondBetweenAtoms(atom_idx, nb.GetIdx())
        bond_type = "single"
        if bond:
            bt = bond.GetBondType()
            if bt == Chem.BondType.DOUBLE:    bond_type = "double"
            elif bt == Chem.BondType.TRIPLE:  bond_type = "triple"
            elif bt == Chem.BondType.AROMATIC: bond_type = "aromatic"
        neighbors.append(AtomNeighbor(
            idx=nb.GetIdx(),
            element=nb.GetSymbol(),
            bond=bond_type,
        ))

    # Ring info
    ring_info = mol.GetRingInfo()
    in_ring = atom.IsInRing()
    ring_size = 0
    for ring in ring_info.AtomRings():
        if atom_idx in ring:
            ring_size = len(ring)
            break

    n_h = atom.GetTotalNumHs()
    free_valence = n_h  # number of single-bond slots open

    # Allowed attachments
    allowed: list[AllowedAttachment] = []
    if free_valence >= 1:
        # Single-element swaps (only for atoms that aren't already that element)
        # and only if the atom HAS free H to give up its one of its bonds (we
        # keep this simple: same-valence single swaps).
        for swap_elt in ("N", "O", "F", "Cl", "S"):
            if swap_elt == elt:
                continue
            if elt in ("F", "Cl", "Br") and swap_elt in ("F", "Cl", "Br"):
                allowed.append(AllowedAttachment(
                    label=f"{elt}→{swap_elt}",
                    op="swap_element",
                    new_element=swap_elt,
                    note="halogen swap",
                ))
            elif n_h > 0 and atom.GetTotalDegree() <= 4:
                allowed.append(AllowedAttachment(
                    label=f"{elt}→{swap_elt}",
                    op="swap_element",
                    new_element=swap_elt,
                    note="atom-class change",
                ))
        # Functional-group attach (uses up 1 free H slot)
        for fg in _FUNCTIONAL_GROUPS:
            if fg["valence_used"] <= free_valence:
                allowed.append(AllowedAttachment(
                    label=fg["label"],
                    op="add_functional_group",
                    functional_group=fg["name"],
                    note=("aromatic-H position" if atom.GetIsAromatic() else "free-H position"),
                ))
    else:
        # Saturated atom — only break-bond is available; we mark as fully-bound.
        pass

    # SAR notes from the curated corpus
    sar = _sar_lookup(elt, smiles, target)

    # Hybridization → human-friendly string
    hyb_map = {
        Chem.HybridizationType.S:    "s",
        Chem.HybridizationType.SP:   "sp",
        Chem.HybridizationType.SP2:  "sp²",
        Chem.HybridizationType.SP3:  "sp³",
        Chem.HybridizationType.SP3D: "sp³d",
        Chem.HybridizationType.SP3D2:"sp³d²",
    }
    hyb_str = hyb_map.get(atom.GetHybridization(), "unspecified")

    # CIP code (R/S) if assigned. Compute on a copy so we don't mutate caller mol.
    cip = ""
    try:
        Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
        if atom.HasProp("_CIPCode"):
            cip = atom.GetProp("_CIPCode")
    except Exception:  # noqa: BLE001
        pass

    return AtomContextResponse(
        smiles=smiles,
        atom_idx=atom_idx,
        element=elt,
        formal_charge=atom.GetFormalCharge(),
        is_aromatic=atom.GetIsAromatic(),
        in_ring=in_ring,
        ring_size=ring_size,
        explicit_valence=atom.GetExplicitValence(),
        implicit_valence=atom.GetImplicitValence(),
        n_hydrogens=n_h,
        atomic_number=atom.GetAtomicNum(),
        atomic_mass=round(atom.GetMass(), 3),
        hybridization=hyb_str,
        degree=atom.GetDegree(),
        total_degree=atom.GetTotalDegree(),
        free_valence=n_h,
        is_chiral=atom.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED,
        is_isotope=atom.GetIsotope() != 0,
        cip_code=cip,
        neighbors=neighbors,
        allowed_attachments=allowed,
        sar_notes=sar,
    )


@router.get("/molecule/2d/{smiles_b64}")
async def molecule_2d_svg(smiles_b64: str, w: int = 480, h: int = 340,
                          indices: int = 1) -> dict:
    """Render a 2D structure as SVG. With `indices=1` (default) the SVG
    carries atom-N classes the 2D builder uses for hit-testing.
    Thumbnails should pass `indices=0` to get a clean structure
    without number labels."""
    try:
        smiles = _decode_smiles_b64(smiles_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"smiles decode failed: {exc}")
    try:
        from rdkit import Chem
        from rdkit.Chem.Draw import rdMolDraw2D
    except ImportError:
        raise HTTPException(503, "RDKit not available")

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")

    drawer = rdMolDraw2D.MolDraw2DSVG(w, h)
    opts = drawer.drawOptions()
    opts.addAtomIndices = bool(indices)
    opts.bondLineWidth = 2
    opts.baseFontSize = 0.6
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    svg = drawer.GetDrawingText()

    # Authoritative atom (x, y) coords in SVG pixel space. The frontend
    # uses these directly for halo / hit-circle placement instead of
    # parsing bond endpoints (which is unreliable for aromatic stripes
    # and yields halos drifting onto bond midpoints).
    atom_coords: list[dict] = []
    try:
        n = mol.GetNumAtoms()
        for i in range(n):
            try:
                pt = drawer.GetDrawCoords(i)
                atom_coords.append({"idx": i, "x": float(pt.x), "y": float(pt.y)})
            except Exception:
                # Some RDKit versions return a Point2D with .x .y; some return a
                # tuple. Fall back to the second form.
                try:
                    pt = drawer.GetDrawCoords(i)  # type: ignore[assignment]
                    atom_coords.append({"idx": i, "x": float(pt[0]), "y": float(pt[1])})
                except Exception:
                    pass
    except Exception:
        atom_coords = []

    return {
        "smiles": smiles,
        "svg": svg,
        "n_atoms": mol.GetNumAtoms(),
        "n_bonds": mol.GetNumBonds(),
        "w": w,
        "h": h,
        "atom_coords": atom_coords,
    }


# ---------------------------------------------------------------------------
# W6 — Compare N candidates side-by-side.
#
# Scores each candidate on the same 12-axis stack and returns the
# breakdowns + a winner-by-component matrix. Frontend renders as a
# comparison table with per-component bars.
# ---------------------------------------------------------------------------


class CompareRequest(BaseModel):
    smiles: list[str] = Field(..., min_length=2, max_length=8)
    target_pathogen: str = "MRSA"


class CompareEntry(BaseModel):
    smiles: str
    composite: float = 0.0
    weakest: str = ""
    strongest: str = ""
    components: list[dict] = []
    rank: int = 0
    error: str = ""


class CompareResponse(BaseModel):
    target_pathogen: str
    entries: list[CompareEntry]
    component_winners: dict[str, str]   # component_name -> smiles of best entry
    elapsed_ms: int


@router.post("/compare", response_model=CompareResponse)
async def workbench_compare(req: CompareRequest) -> CompareResponse:
    import time as _t
    t0 = _t.perf_counter()

    try:
        from tools.scoring.score_molecule import score_molecule
    except ImportError as exc:
        raise HTTPException(503, f"scoring not available: {exc}")

    entries: list[CompareEntry] = []
    for smi in req.smiles:
        try:
            br = score_molecule(smiles=smi, target_pathogen=req.target_pathogen)
            d = br.model_dump()
            entries.append(CompareEntry(
                smiles=smi,
                composite=d["composite"],
                weakest=d.get("weakest", ""),
                strongest=d.get("strongest", ""),
                components=d.get("components", []),
            ))
        except Exception as exc:  # noqa: BLE001
            entries.append(CompareEntry(smiles=smi, error=str(exc)[:200]))

    # Rank by composite (errored entries get rank -1)
    valid = [e for e in entries if not e.error]
    valid.sort(key=lambda e: -e.composite)
    for i, e in enumerate(valid, 1):
        e.rank = i

    # Component-wise winners
    winners: dict[str, str] = {}
    if valid:
        all_components = {c["name"] for e in valid for c in e.components}
        for comp_name in all_components:
            best_e = None
            best_v = -1.0
            for e in valid:
                v = next((c["value"] for c in e.components if c["name"] == comp_name), -1.0)
                if v > best_v:
                    best_v = v
                    best_e = e
            if best_e:
                winners[comp_name] = best_e.smiles

    return CompareResponse(
        target_pathogen=req.target_pathogen,
        entries=entries,
        component_winners=winners,
        elapsed_ms=int((_t.perf_counter() - t0) * 1000),
    )


# ---------------------------------------------------------------------------
# W5 — Stress-test (adversarial Critic + structured failure modes).
#
# Sends the candidate to a Gemini-Pro Critic agent with an adversarial
# prompt that returns a JSON list of attack vectors:
#   [{ mode, severity, why_fails, mitigation }]
# Each attack documents a way the molecule could fail clinically/ATC: PK
# liabilities, β-lactamase hydrolysis, structural alerts, resistance
# escape, etc. Frontend renders as a list of severity-coded chips.
# ---------------------------------------------------------------------------


class StressTestRequest(BaseModel):
    smiles: str = Field(..., description="Candidate SMILES to red-team")
    target_pathogen: str = "MRSA"
    max_attacks: int = Field(6, ge=1, le=12)


class StressAttack(BaseModel):
    mode: str
    severity: Literal["high", "medium", "low"]
    why_fails: str
    mitigation: str = ""
    smiles_variant: str = ""        # optional adversarial variant


class StressTestResponse(BaseModel):
    smiles: str
    target_pathogen: str
    summary: str
    attacks: list[StressAttack]
    model: str
    elapsed_ms: int


_STRESS_PROMPT = """You are the Lysos Critic agent. Red-team the candidate molecule below — find every way it could FAIL as an antibiotic clinically. Return STRUCTURED JSON only, no prose.

Candidate SMILES: {smiles}
Target pathogen: {target_pathogen}

Return JSON with this exact shape:
{{
  "summary": "<2-sentence verdict on overall fitness>",
  "attacks": [
    {{
      "mode": "<short label, e.g. 'KPC β-lactamase hydrolysis'>",
      "severity": "high" | "medium" | "low",
      "why_fails": "<1-3 sentences explaining the failure mode>",
      "mitigation": "<1-2 sentences on how a designer could fix it>",
      "smiles_variant": "<optional: a known scaffold the designer could pivot to; can be empty>"
    }},
    ...
  ]
}}

Constraints:
- Return at most {max_attacks} distinct attacks.
- Severity reflects clinical likelihood × impact, not just "is this possible".
- Cover diverse modes: PK/ADMET, resistance enzymes (KPC/NDM/OXA, mecA, vanA),
  efflux, structural alerts (PAINS), bioavailability, hERG, hepatotoxicity,
  spectrum gaps. Don't repeat the same axis twice.
- ONLY emit the JSON object. No markdown fences, no ```json, no prefix.
"""


@router.post("/stress", response_model=StressTestResponse)
async def workbench_stress(req: StressTestRequest) -> StressTestResponse:
    """Adversarial Critic — returns a structured list of failure modes."""
    import time as _t
    t0 = _t.perf_counter()

    prompt = _STRESS_PROMPT.format(
        smiles=req.smiles,
        target_pathogen=req.target_pathogen,
        max_attacks=req.max_attacks,
    )

    summary = ""
    attacks: list[StressAttack] = []
    model_used = "fallback"

    # Gemini 2.5 Pro REST (same tier as auto-title / explain)
    import os as _os
    gemini_key = _os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            import httpx
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{_os.getenv('LYSOS_STRESS_GEMINI_MODEL', 'gemini-2.5-pro')}:generateContent"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": 3072,
                    "temperature": 0.4,
                    "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingBudget": 1024, "includeThoughts": False},
                },
            }
            async with httpx.AsyncClient(timeout=45.0) as cx:
                r = await cx.post(
                    url,
                    headers={"x-goog-api-key": gemini_key,
                             "Content-Type": "application/json"},
                    json=payload,
                )
            if r.status_code != 200:
                raise RuntimeError(f"http {r.status_code}: {r.text[:200]}")
            d = r.json()
            cands = d.get("candidates") or []
            raw = ""
            if cands:
                parts = (cands[0].get("content") or {}).get("parts") or []
                if parts:
                    raw = (parts[0].get("text") or "").strip()
            if not raw:
                raise RuntimeError("empty LLM response")
            # Strip any accidental fencing
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.lower().startswith("json"):
                    raw = raw[4:].lstrip()
            parsed = json.loads(raw)
            summary = (parsed.get("summary") or "").strip()
            for a in (parsed.get("attacks") or [])[: req.max_attacks]:
                sev = (a.get("severity") or "medium").lower()
                if sev not in ("high", "medium", "low"):
                    sev = "medium"
                attacks.append(StressAttack(
                    mode=(a.get("mode") or "?").strip()[:80],
                    severity=sev,  # type: ignore[arg-type]
                    why_fails=(a.get("why_fails") or "").strip()[:600],
                    mitigation=(a.get("mitigation") or "").strip()[:400],
                    smiles_variant=(a.get("smiles_variant") or "").strip(),
                ))
            model_used = "gemini"
        except Exception as exc:  # noqa: BLE001
            log.warning("stress-test Gemini failed: %s", exc)

    # Fallback heuristic — at least give the user something
    if not attacks:
        summary = (
            "LLM Critic unavailable. Using heuristic fallback — review composite "
            "axes manually for low-scoring components and consult /score breakdown."
        )
        attacks = [StressAttack(
            mode="Heuristic-only mode",
            severity="medium",
            why_fails="No LLM grounding available. Run /score to see component-level liabilities.",
            mitigation="Configure GEMINI_API_KEY (or LysosEndpoint) and retry.",
        )]

    return StressTestResponse(
        smiles=req.smiles,
        target_pathogen=req.target_pathogen,
        summary=summary,
        attacks=attacks,
        model=model_used,
        elapsed_ms=int((_t.perf_counter() - t0) * 1000),
    )


# ---------------------------------------------------------------------------
# W3 — SAR exploration (parent SMILES → k mutants + score deltas).
#
# Generates structurally-related variants via RDKit transforms, scores each
# with the same 12-axis reward stack as W2, computes delta vs parent.
# Frontend renders as a tree card with click-to-load semantics.
#
# Per SAAS_HARNESS §6 W3: "Designer mutates, Editor validates, Critic
# challenges drift." Phase-1 ships the deterministic substrate (transforms +
# scoring); the agent debate layer can wrap this later by routing each
# accepted child back through /design.
# ---------------------------------------------------------------------------


class SARExpandRequest(BaseModel):
    parent_smiles: str = Field(..., description="Starting candidate SMILES")
    k: int = Field(5, ge=1, le=20, description="Number of mutant children to generate")
    target_pathogen: str = "MRSA"
    ops: list[str] = Field(
        default_factory=lambda: [
            "swap_N", "swap_O", "swap_F", "add_methyl",
            "add_hydroxyl", "add_fluorine_aromatic", "add_chlorine_aromatic",
        ],
        description="Allowed transform ops (cycled for k mutants)",
    )


class SARChild(BaseModel):
    smiles: str
    op: str
    op_label: str               # human-readable e.g. "C→N at idx 4"
    composite: float
    delta_vs_parent: float      # composite - parent_composite
    weakest: str = ""
    strongest: str = ""
    components: list[dict] = []
    error: str = ""


class SARExpandResponse(BaseModel):
    parent: dict                # full RewardBreakdown
    children: list[SARChild]
    n_proposed: int             # how many ops we tried (some may have failed)
    n_accepted: int             # how many produced a valid scored mutant
    elapsed_ms: int


def _apply_transform(smiles: str, op: str, atom_idx: int) -> tuple[str, str]:
    """Try one structural mutation. Returns (new_smiles, label) or raises."""
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError("unparseable SMILES")
    rw = Chem.RWMol(mol)
    n = rw.GetNumAtoms()
    if atom_idx < 0 or atom_idx >= n:
        raise ValueError("atom_idx out of range")
    atom = rw.GetAtomWithIdx(atom_idx)
    elt = atom.GetSymbol()

    label = ""
    if op == "swap_N":
        if elt == "N":
            raise ValueError("already N")
        atom.SetAtomicNum(7)
        label = f"{elt}→N at idx {atom_idx}"
    elif op == "swap_O":
        if elt == "O" or atom.GetIsAromatic():
            raise ValueError("not a useful swap target")
        atom.SetAtomicNum(8)
        label = f"{elt}→O at idx {atom_idx}"
    elif op == "swap_F":
        if elt == "F" or atom.GetTotalNumHs() == 0:
            raise ValueError("not a useful swap target")
        atom.SetAtomicNum(9)
        label = f"{elt}→F at idx {atom_idx}"
    elif op == "add_methyl":
        if atom.GetTotalNumHs() == 0:
            raise ValueError("no H to replace")
        c = rw.AddAtom(Chem.Atom(6))
        rw.AddBond(atom_idx, c, Chem.BondType.SINGLE)
        label = f"+CH₃ at idx {atom_idx}"
    elif op == "add_hydroxyl":
        if atom.GetTotalNumHs() == 0:
            raise ValueError("no H to replace")
        o = rw.AddAtom(Chem.Atom(8))
        rw.AddBond(atom_idx, o, Chem.BondType.SINGLE)
        label = f"+OH at idx {atom_idx}"
    elif op == "add_fluorine_aromatic":
        if not atom.GetIsAromatic() or atom.GetTotalNumHs() == 0:
            raise ValueError("not aromatic-H position")
        f = rw.AddAtom(Chem.Atom(9))
        rw.AddBond(atom_idx, f, Chem.BondType.SINGLE)
        label = f"+F (aromatic) at idx {atom_idx}"
    elif op == "add_chlorine_aromatic":
        if not atom.GetIsAromatic() or atom.GetTotalNumHs() == 0:
            raise ValueError("not aromatic-H position")
        cl = rw.AddAtom(Chem.Atom(17))
        rw.AddBond(atom_idx, cl, Chem.BondType.SINGLE)
        label = f"+Cl (aromatic) at idx {atom_idx}"
    else:
        raise ValueError(f"unknown op: {op}")

    Chem.SanitizeMol(rw)
    out = Chem.MolToSmiles(rw, canonical=True)
    return out, label


def _score(smiles: str, target: str) -> "RewardBreakdown":  # type: ignore[name-defined]
    from tools.scoring.score_molecule import score_molecule
    return score_molecule(smiles=smiles, target_pathogen=target)


@router.post("/sar/expand", response_model=SARExpandResponse)
async def workbench_sar_expand(req: SARExpandRequest) -> SARExpandResponse:
    """Expand a parent SMILES into k structurally-related mutants + score
    each. Returns a tree-shaped response the frontend renders as a SAR
    tree card with click-to-load semantics on every child.
    """
    import time as _t
    t0 = _t.perf_counter()

    try:
        from rdkit import Chem
        parent_mol = Chem.MolFromSmiles(req.parent_smiles)
        if parent_mol is None:
            raise HTTPException(422, f"parent SMILES unparseable: {req.parent_smiles}")
    except ImportError:
        raise HTTPException(503, "RDKit not available")

    # Score parent first — anchor for delta computation
    try:
        parent_breakdown = _score(req.parent_smiles, req.target_pathogen)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"parent score failed: {exc}")
    parent_dict = parent_breakdown.model_dump()
    parent_composite = parent_dict["composite"]

    # Generate k mutants — cycle through ops, try each at a random atom
    import random
    rng = random.Random(0xC0FFEE)
    n_atoms = parent_mol.GetNumAtoms()
    candidates_seen: set[str] = {req.parent_smiles}
    children: list[SARChild] = []
    n_proposed = 0
    op_cycle = req.ops or ["swap_N", "add_methyl", "add_hydroxyl"]

    # Try up to k * 3 attempts to land k accepted mutants
    max_attempts = req.k * 4
    attempts = 0
    while len(children) < req.k and attempts < max_attempts:
        attempts += 1
        op = op_cycle[attempts % len(op_cycle)]
        atom_idx = rng.randrange(n_atoms)
        n_proposed += 1
        try:
            new_smi, label = _apply_transform(req.parent_smiles, op, atom_idx)
        except Exception:
            continue
        if new_smi in candidates_seen:
            continue
        candidates_seen.add(new_smi)
        try:
            br = _score(new_smi, req.target_pathogen)
            d = br.model_dump()
            children.append(SARChild(
                smiles=new_smi,
                op=op,
                op_label=label,
                composite=d["composite"],
                delta_vs_parent=d["composite"] - parent_composite,
                weakest=d.get("weakest", ""),
                strongest=d.get("strongest", ""),
                components=d.get("components", []),
            ))
        except Exception as exc:  # noqa: BLE001
            children.append(SARChild(
                smiles=new_smi,
                op=op,
                op_label=label,
                composite=0.0,
                delta_vs_parent=-parent_composite,
                error=str(exc)[:120],
            ))

    # Sort children by delta (best improvements first)
    children.sort(key=lambda c: -c.delta_vs_parent)

    return SARExpandResponse(
        parent=parent_dict,
        children=children,
        n_proposed=n_proposed,
        n_accepted=len([c for c in children if not c.error]),
        elapsed_ms=int((_t.perf_counter() - t0) * 1000),
    )


# ---------------------------------------------------------------------------
# HuggingScience dataset registry — exposes which external science datasets
# are available (and which have been fetched to local parquet) so the agent
# + frontend can discover them. Updated by scripts/fetch_huggingscience.py.
# ---------------------------------------------------------------------------


@router.get("/datasets")
async def list_datasets() -> dict:
    """Catalog of HuggingScience datasets registered for this workbench.

    The registry file is written by scripts/fetch_huggingscience.py.
    Each entry shows whether the local subset has been fetched
    (parquet present at data/external/<name>.parquet).
    """
    repo_root = _WORKSPACE.parent
    reg_path = repo_root / "data" / "external" / "registry.json"
    if not reg_path.exists():
        return {"datasets": [], "registry_path": str(reg_path),
                "note": "run `python scripts/fetch_huggingscience.py --dataset tier1` to seed"}

    try:
        entries = json.loads(reg_path.read_text())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"registry parse failed: {exc}")

    out = []
    for e in entries:
        local_path = repo_root / "data" / "external" / f"{e['name']}.parquet"
        out.append({
            **e,
            "fetched": local_path.exists(),
            "local_size_kb": (local_path.stat().st_size // 1024) if local_path.exists() else 0,
        })
    return {"datasets": out, "registry_path": str(reg_path)}


# ---------------------------------------------------------------------------
# W4 — Explain (target/drug → markdown brief streamed to right pane).
#
# Grounded against the local pharma corpus:
#   - data/synthetic/named_drug_examples.jsonl  (387 deep drug profiles)
#   - data/synthetic/pharma_qa_layer.jsonl      (872 Q/A pairs)
# Top-K matched entries are concatenated into the LLM prompt so the
# generated brief is grounded in real curated knowledge instead of
# the model's prior. LLM is Gemini 2.5 Pro until Lysos-Gemma is
# deployed (then swap via LYSOS_AUTOTITLE_BACKEND-style env, see
# docs/SAAS_HARNESS.md §8.5).
# ---------------------------------------------------------------------------


class ExplainRequest(BaseModel):
    target: str = Field(..., description="Drug name, target protein, or mechanism (e.g. 'cefiderocol', 'mecA', 'ribosome 50S')")
    style: Literal["full", "brief"] = "full"


class ExplainResponse(BaseModel):
    session_id: str
    target: str
    sse_url: str
    status: str
    grounding_count: int


_PHARMA_GROUND_INDEX: list[dict] = []


def _load_pharma_ground() -> list[dict]:
    """One-shot indexer — reads named_drug_examples.jsonl into memory.

    Each entry: {"drug": str, "prompt": str, "response": str, "task": str}.
    Cheap (387 rows × ~5KB ≈ 2MB), so we keep it resident.
    """
    global _PHARMA_GROUND_INDEX
    if _PHARMA_GROUND_INDEX:
        return _PHARMA_GROUND_INDEX
    out: list[dict] = []
    p = _WORKSPACE.parent / "data" / "synthetic" / "named_drug_examples.jsonl"
    if p.exists():
        with p.open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                # Pull the drug name out of the prompt's "Drug: …" line
                prompt = (e.get("prompt") or "")
                drug = ""
                for ln in prompt.splitlines():
                    if ln.strip().lower().startswith("drug:"):
                        drug = ln.split(":", 1)[1].strip().split("—")[0].split("(")[0].strip()
                        break
                out.append({
                    "drug": drug,
                    "prompt": prompt[:600],
                    "response": (e.get("response") or "")[:3500],
                    "task": e.get("task", ""),
                })
    # Also include pharma_qa pairs as compact grounding
    p2 = _WORKSPACE.parent / "data" / "synthetic" / "pharma_qa_layer.jsonl"
    if p2.exists():
        with p2.open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                msgs = e.get("messages") or []
                if len(msgs) < 2:
                    continue
                out.append({
                    "drug": e.get("drug", ""),
                    "prompt": msgs[0].get("content", "")[:300],
                    "response": msgs[1].get("content", "")[:1200],
                    "task": e.get("question_type", "qa"),
                })
    _PHARMA_GROUND_INDEX = out
    log.info("pharma grounding loaded: %d entries", len(out))
    return out


def _ground_for(target: str, k: int = 3) -> list[dict]:
    """Tiny BM25-style scorer — case-insensitive substring + drug-name boost."""
    idx = _load_pharma_ground()
    q = target.lower().strip()
    if not q:
        return []
    scored: list[tuple[float, dict]] = []
    for e in idx:
        drug = (e.get("drug") or "").lower()
        prompt = (e.get("prompt") or "").lower()
        resp = (e.get("response") or "").lower()
        s = 0.0
        if q in drug:
            s += 5.0
        if q == drug:
            s += 5.0
        s += 1.5 * prompt.count(q)
        s += 0.5 * resp.count(q)
        if s > 0:
            scored.append((s, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:k]]


_EXPLAIN_PROMPT = """You are the Lysos Strategist agent. Produce a structured Markdown brief on the requested target/drug for an antibiotic-design workbench. Use ONLY the grounding context below for facts; if the grounding is empty for some sections, mark them "(no curated source — model best-effort)".

Requested target: {target}

Grounding context (top-{k} matched entries from the curated pharma corpus):
---
{grounding}
---

Output sections (in this order, with these exact `##` headers):

## Mechanism
2-4 sentence explanation of how the drug acts OR what the target does in pathogen biology.

## Spectrum
Bulleted: which pathogens this affects (or for a target, which pathogens express it).

## Resistance landscape
Bulleted: known escape mechanisms, mutations, clinical prevalence if known.

## First-line drugs / standard of care
Bulleted: current drugs in this class / for this indication, with one-sentence status (FDA-approved year, key liability).

## Design implications for Lysos
3-5 sentence guidance: what should a new molecule for this target accomplish? What pharmacophores / scaffolds matter? Which liabilities to avoid?

Constraints:
- Stay under 800 words total.
- No introductory preamble; jump straight into ## Mechanism.
- Inline citations as [grounding-N] when a fact comes from a specific entry, where N is the 1-based index in the grounding list.
- Plain Markdown — no HTML.
"""


@router.post("/explain", response_model=ExplainResponse)
async def workbench_explain(req: ExplainRequest) -> ExplainResponse:
    """Kicks off a streaming Markdown brief on a target/drug.

    Frontend subscribes to /workbench/sessions/{id}/events (the existing
    SSE bus) and renders chunks into the right-pane ArtifactPanel.
    """
    sid = "explain-" + uuid.uuid4().hex[:10]

    # Materialize a minimal WorkbenchState so the SSE stream_events route
    # works (it gates on `session_id in _sessions`). We use mode="design"
    # because state.py's WorkbenchState only knows the three modes.
    state = WorkbenchState(
        session_id=sid,
        target_pathogen="MRSA",
        mode="design",
        autonomy="copilot",
    )
    _sessions[sid] = state
    queue = _get_or_create_queue(sid)

    # Pull grounding now (fast, in-memory)
    ground = _ground_for(req.target, k=3)

    async def runner() -> None:
        # Header event so the frontend mounts the artifact pane
        await queue.put({
            "type": "explain_start",
            "data": {"target": req.target, "session_id": sid,
                     "grounding_count": len(ground)},
        })

        # Build the grounded prompt
        if ground:
            pieces = []
            for i, g in enumerate(ground, 1):
                pieces.append(
                    f"[grounding-{i}] drug={g.get('drug','?')} "
                    f"task={g.get('task','?')}\nprompt: {g.get('prompt','')[:500]}\n"
                    f"response: {g.get('response','')[:2000]}"
                )
            grounding_text = "\n\n".join(pieces)
        else:
            grounding_text = "(no curated grounding matched; rely on model knowledge with explicit uncertainty markers)"

        prompt = _EXPLAIN_PROMPT.format(
            target=req.target,
            k=len(ground),
            grounding=grounding_text,
        )

        # Call Gemini 2.5 Pro via direct REST. We don't use streaming
        # endpoint — instead we get the full response then chunk-publish
        # to the SSE bus so the frontend animates the markdown filling
        # in section-by-section.
        try:
            import os as _os
            import httpx
            gemini_key = _os.getenv("GEMINI_API_KEY")
            if not gemini_key:
                raise RuntimeError("GEMINI_API_KEY not set")
            # Primary + fallback — gemini-2.5-pro hits 503 under demand,
            # so the /explain brief was silently completing with 0 chunks
            # (runner caught the exception). Auto-retry on Flash.
            primary = _os.getenv("LYSOS_EXPLAIN_GEMINI_MODEL", "gemini-2.5-pro")
            fallback = _os.getenv("LYSOS_EXPLAIN_GEMINI_FALLBACK", "gemini-2.5-flash")
            def _model_url(m: str) -> str:
                return (
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{m}:generateContent"
                )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": 4096,
                    "temperature": 0.3,
                    "responseMimeType": "text/plain",
                    "thinkingConfig": {
                        "thinkingBudget": int(_os.getenv("LYSOS_EXPLAIN_THINKING", "1024")),
                        "includeThoughts": False,
                    },
                },
            }
            r = None
            for attempt_model in (primary, fallback):
                async with httpx.AsyncClient(timeout=60.0) as cx:
                    r = await cx.post(
                        _model_url(attempt_model),
                        headers={"x-goog-api-key": gemini_key,
                                 "Content-Type": "application/json"},
                        json=payload,
                    )
                if r.status_code == 200:
                    break
                if r.status_code not in (429, 503):
                    break
                log.warning("explain %s returned %d; falling back to %s",
                            attempt_model, r.status_code, fallback)
            if r is None or r.status_code != 200:
                code = r.status_code if r is not None else 0
                body = (r.text[:200] if r is not None else "no response")
                raise RuntimeError(f"gemini http {code}: {body}")
            d = r.json()
            cands = d.get("candidates") or []
            md = ""
            if cands:
                parts = (cands[0].get("content") or {}).get("parts") or []
                if parts:
                    md = (parts[0].get("text") or "").strip()
            if not md:
                raise RuntimeError("empty LLM response")

            # Chunk-publish: split on ## headers so each section streams in
            # as a discrete event. Frontend assembles them into one md doc.
            chunks: list[str] = []
            cur = ""
            for line in md.splitlines(keepends=True):
                if line.lstrip().startswith("## ") and cur:
                    chunks.append(cur)
                    cur = ""
                cur += line
            if cur:
                chunks.append(cur)

            for i, chunk in enumerate(chunks):
                await queue.put({
                    "type": "explain_chunk",
                    "data": {"session_id": sid, "chunk": chunk,
                             "index": i, "total": len(chunks)},
                })
                # Tiny inter-chunk pause so the frontend animates
                await asyncio.sleep(0.06)

            await queue.put({
                "type": "explain_complete",
                "data": {"session_id": sid, "target": req.target,
                         "n_chunks": len(chunks),
                         "grounding_count": len(ground)},
            })
        except Exception as exc:  # noqa: BLE001
            log.exception("explain session %s failed", sid)
            await queue.put({"type": "explain_error",
                             "data": {"session_id": sid, "error": str(exc)[:300]}})
        finally:
            await queue.put(None)

    asyncio.create_task(runner())

    return ExplainResponse(
        session_id=sid,
        target=req.target,
        sse_url=f"/workbench/sessions/{sid}/events",
        status="running",
        grounding_count=len(ground),
    )


# ---------------------------------------------------------------------------
# W2 — Score a molecule (deterministic, no agent debate).
# ---------------------------------------------------------------------------


class ScoreMoleculeRequest(BaseModel):
    smiles: str
    target_pathogen: str = "MRSA"
    session_id: Optional[str] = None  # for session memory recording


@router.post("/score")
async def workbench_score(req: ScoreMoleculeRequest) -> dict:
    """Run the 12-component reward stack on a SMILES.

    Reuses workspace.tools.scoring.score_molecule which calls into
    src.eval.rewards.* — the same composite Stage 3 GRPO training uses.

    Returns: composite ∈ [0, 1] + per-component value/weight/contribution.
    """
    try:
        from tools.scoring.score_molecule import score_molecule
    except ImportError as exc:
        raise HTTPException(503, f"scoring module not available: {exc}")

    try:
        breakdown = score_molecule(smiles=req.smiles, target_pathogen=req.target_pathogen)
    except Exception as exc:  # noqa: BLE001
        # Most likely: invalid SMILES, RDKit can't sanitize, or a missing
        # reward dep. Surface the error verbatim — the chat card renders it.
        raise HTTPException(422, f"score failed: {exc}")

    result = breakdown.model_dump()
    # Record into session memory so future Gemini calls in this session
    # have a sense of what was last scored. Best-effort; never blocks.
    if req.session_id:
        try:
            from . import session_memory
            session_memory.record(req.session_id, "score", {
                "smiles": req.smiles,
                "composite": result.get("composite"),
                "weakest": result.get("weakest"),
            })
        except Exception:
            pass
    return result


@router.post("/score-explain")
async def workbench_score_explain(req: ScoreMoleculeRequest) -> dict:
    """Deep score breakdown — every axis gets:
      - the raw value + weight + contribution (same as /score)
      - the actual RDKit-derived properties driving it (MW, LogP, HBA,
        HBD, TPSA, rotatable bonds, ring count, aromatic rings, fsp3,
        Lipinski/Veber/Egan compliance flags)
      - per-axis Gemini-generated reasoning explaining WHY this value
        and a concrete suggestion to improve it

    Used by the Scoring container's "deep dive" panel — each axis
    expands to show the underlying chemistry + improvement direction.
    """
    try:
        from tools.scoring.score_molecule import score_molecule
    except ImportError as exc:
        raise HTTPException(503, f"scoring module not available: {exc}")

    try:
        breakdown = score_molecule(smiles=req.smiles, target_pathogen=req.target_pathogen)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"score failed: {exc}")

    base = breakdown.model_dump()

    # ── Real RDKit-derived molecular properties ──
    props = _deep_properties(req.smiles)
    base["rdkit_properties"] = props

    # ── Rule compliance flags (Lipinski / Veber / Egan / PAINS-aware) ──
    rules = _compute_rule_compliance(props)
    base["rules"] = rules

    # ── Per-axis Gemini reasoning + improvement suggestions ──
    axis_reasoning = await _llm_score_axis_reasoning(
        req.smiles, req.target_pathogen, base.get("components") or [], props,
    )
    base["axis_reasoning"] = axis_reasoning

    return base


def _deep_properties(smiles: str) -> dict:
    """Full RDKit property panel — everything the Scoring container
    needs to surface real chemistry behind each axis."""
    try:
        from rdkit import Chem
        from rdkit.Chem import (
            Crippen, Descriptors, Lipinski, rdMolDescriptors,
        )
    except ImportError:
        return {"valid": False, "error": "rdkit unavailable"}
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return {"valid": False, "error": "unparseable"}
    return {
        "valid": True,
        "smiles_canonical": Chem.MolToSmiles(mol),
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "mw": round(Descriptors.MolWt(mol), 2),
        "exact_mass": round(Descriptors.ExactMolWt(mol), 4),
        "logp": round(Crippen.MolLogP(mol), 2),
        "logd_proxy": round(Crippen.MolLogP(mol), 2),  # at neutral pH ~ logP
        "hba": int(Lipinski.NumHAcceptors(mol)),
        "hbd": int(Lipinski.NumHDonors(mol)),
        "tpsa": round(Descriptors.TPSA(mol), 2),
        "rotatable_bonds": int(Lipinski.NumRotatableBonds(mol)),
        "rings": int(Descriptors.RingCount(mol)),
        "aromatic_rings": int(rdMolDescriptors.CalcNumAromaticRings(mol)),
        "fsp3": round(rdMolDescriptors.CalcFractionCSP3(mol), 3),
        "n_heavy_atoms": int(mol.GetNumHeavyAtoms()),
        "n_stereo_centers": int(rdMolDescriptors.CalcNumAtomStereoCenters(mol)),
        "qed": round(Descriptors.qed(mol), 4),
        "bertz_complexity": round(Descriptors.BertzCT(mol), 1),
    }


def _compute_rule_compliance(props: dict) -> dict:
    """Industry rule sets for drug-likeness compliance.
      Lipinski (CRO oral absorption):  MW≤500, LogP≤5, HBA≤10, HBD≤5
      Veber (oral bioavailability):    rot≤10, TPSA≤140
      Egan (oral absorption):          LogP −1..6, TPSA≤132
      Ghose (CNS-active):              MW 160-480, LogP −0.4..5.6, HA 20-70
    Each rule returns {pass, n_violations, violations[]}."""
    if not props.get("valid"):
        return {}
    mw = props["mw"]; logp = props["logp"]
    hba = props["hba"]; hbd = props["hbd"]
    rot = props["rotatable_bonds"]; tpsa = props["tpsa"]; ha = props["n_heavy_atoms"]
    out: dict[str, dict] = {}

    lip_v = []
    if mw > 500: lip_v.append(f"MW {mw}>500")
    if logp > 5: lip_v.append(f"LogP {logp}>5")
    if hba > 10: lip_v.append(f"HBA {hba}>10")
    if hbd > 5:  lip_v.append(f"HBD {hbd}>5")
    out["lipinski"] = {"pass": len(lip_v) <= 1, "n_violations": len(lip_v), "violations": lip_v}

    veb_v = []
    if rot > 10: veb_v.append(f"rot {rot}>10")
    if tpsa > 140: veb_v.append(f"TPSA {tpsa}>140")
    out["veber"] = {"pass": len(veb_v) == 0, "n_violations": len(veb_v), "violations": veb_v}

    egan_v = []
    if logp < -1 or logp > 6: egan_v.append(f"LogP {logp} outside [-1, 6]")
    if tpsa > 132: egan_v.append(f"TPSA {tpsa}>132")
    out["egan"] = {"pass": len(egan_v) == 0, "n_violations": len(egan_v), "violations": egan_v}

    ghose_v = []
    if mw < 160 or mw > 480: ghose_v.append(f"MW {mw} outside [160, 480]")
    if logp < -0.4 or logp > 5.6: ghose_v.append(f"LogP {logp} outside [-0.4, 5.6]")
    if ha < 20 or ha > 70: ghose_v.append(f"HA {ha} outside [20, 70]")
    out["ghose"] = {"pass": len(ghose_v) == 0, "n_violations": len(ghose_v), "violations": ghose_v}

    out["overall_pass_count"] = sum(1 for r in out.values() if isinstance(r, dict) and r.get("pass"))
    return out


async def _llm_score_axis_reasoning(
    smiles: str, pathogen: str, components: list, props: dict,
) -> dict:
    """Gemini-generated per-axis reasoning. For each scored axis returns:
      {axis: {explanation, improvement, predicted_delta_if_applied}}.
    Best-effort — empty dict on any failure path."""
    import os as _os
    key = _os.getenv("GEMINI_API_KEY")
    if not key or not components or not props.get("valid"):
        return {}
    model_id = _os.getenv("LYSOS_SCORE_GEMINI_MODEL", "gemini-2.5-flash")
    axis_lines = "\n".join(
        f"  - {c.get('name')}: value={c.get('value'):.3f} weight={c.get('weight')} contribution={c.get('contribution', 0):.3f}"
        for c in components if isinstance(c, dict) and "name" in c
    )
    prompt = (
        "You are a senior medicinal chemist reviewing a candidate's score. "
        "For EACH axis below, return JSON explaining (a) WHY the value is "
        "what it is given the molecule's properties, and (b) a concrete "
        "improvement direction with predicted delta if applied.\n\n"
        f"SMILES: {smiles}\n"
        f"Target pathogen: {pathogen}\n"
        f"Properties: MW={props['mw']}, LogP={props['logp']}, HBA={props['hba']}, "
        f"HBD={props['hbd']}, TPSA={props['tpsa']}, rotatables={props['rotatable_bonds']}, "
        f"rings={props['rings']}, aromatic_rings={props['aromatic_rings']}, "
        f"fsp3={props['fsp3']}, QED={props['qed']}, formula={props.get('formula')}\n"
        f"Per-axis breakdown:\n{axis_lines}\n\n"
        "Return STRICT JSON: "
        '{"axes": [{"name":"<axis>","explanation":"<≤220 chars>",'
        '"improvement":"<≤180 chars>","predicted_delta":<0..0.4>}]}\n'
        "No markdown."
    )
    try:
        import httpx
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 3072,
                "temperature": 0.4,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingBudget": 512, "includeThoughts": False},
            },
        }
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.post(url,
                              headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json=payload)
        if r.status_code != 200:
            return {}
        d = r.json()
        cands = d.get("candidates") or []
        if not cands:
            return {}
        parts = (cands[0].get("content") or {}).get("parts") or []
        if not parts:
            return {}
        raw = (parts[0].get("text") or "").strip()
        try:
            obj = json.loads(raw)
        except Exception:
            # Brace-balanced fallback
            start = raw.find("{")
            if start < 0: return {}
            depth = 0; end = len(raw)
            for i in range(start, len(raw)):
                if raw[i] == "{": depth += 1
                elif raw[i] == "}":
                    depth -= 1
                    if depth == 0: end = i + 1; break
            try: obj = json.loads(raw[start:end])
            except Exception: return {}
        items = obj.get("axes") if isinstance(obj, dict) else None
        if not isinstance(items, list):
            return {}
        out: dict[str, dict] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()
            if not name:
                continue
            try: pdelta = float(it.get("predicted_delta", 0.0))
            except Exception: pdelta = 0.0
            out[name] = {
                "explanation": str(it.get("explanation") or "")[:300],
                "improvement": str(it.get("improvement") or "")[:240],
                "predicted_delta": round(max(0.0, min(0.4, pdelta)), 3),
            }
        return out
    except Exception as exc:  # noqa: BLE001
        log.debug("score-explain gemini failed: %s", exc)
        return {}


@router.post("/molecule/3d")
async def molecule_3d(req: Mol3DRequest) -> dict:
    """Generate a proper 3D conformer from SMILES via RDKit.

    Returns:
      sdf            : MolBlock string with explicit atom coordinates
      n_atoms        : total atoms (incl. H if added)
      n_bonds        : bond count
      energy_kcal_mol: MMFF94s energy if optimization succeeded, else None
      formula        : molecular formula (e.g. C14H22FN3O3)
      mw             : molecular weight (Da)
      logp           : crippen logP estimate
      element_counts : {element: n}
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, Descriptors, Crippen, rdMolDescriptors
    except ImportError:
        raise HTTPException(503, "RDKit not available in this server")

    mol = Chem.MolFromSmiles(req.smiles)
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {req.smiles}")

    if req.add_hydrogens:
        mol = Chem.AddHs(mol)

    # Embed: random-coords helps fragile rings (e.g. carbapenems)
    params = AllChem.ETKDGv3()
    params.randomSeed = int(req.seed) & 0x7FFFFFFF
    params.useRandomCoords = True
    embed_status = AllChem.EmbedMolecule(mol, params)
    if embed_status != 0:
        # Retry with looser settings
        params.maxAttempts = 100
        embed_status = AllChem.EmbedMolecule(mol, params)
    if embed_status != 0:
        raise HTTPException(422, "RDKit could not embed a 3D conformer")

    energy: Optional[float] = None
    if req.optimize:
        try:
            mmff_props = AllChem.MMFFGetMoleculeProperties(mol, mmffVariant="MMFF94s")
            if mmff_props is not None:
                ff = AllChem.MMFFGetMoleculeForceField(mol, mmff_props)
                if ff is not None:
                    ff.Minimize(maxIts=200)
                    energy = float(ff.CalcEnergy())
            else:
                # Fall back to UFF
                AllChem.UFFOptimizeMolecule(mol, maxIters=200)
        except Exception as exc:  # noqa: BLE001
            log.debug("MMFF/UFF optimize failed: %s", exc)

    sdf = Chem.MolToMolBlock(mol)
    formula = rdMolDescriptors.CalcMolFormula(mol)
    mw = float(Descriptors.MolWt(mol))
    logp = float(Crippen.MolLogP(mol))

    el_counts: dict[str, int] = {}
    for atom in mol.GetAtoms():
        sym = atom.GetSymbol()
        el_counts[sym] = el_counts.get(sym, 0) + 1

    return {
        "sdf": sdf,
        "n_atoms": mol.GetNumAtoms(),
        "n_bonds": mol.GetNumBonds(),
        "energy_kcal_mol": energy,
        "formula": formula,
        "mw": round(mw, 2),
        "logp": round(logp, 2),
        "element_counts": el_counts,
    }


# ---------------------------------------------------------------------------
# Atom-level molecule editing — click-to-swap an atom's element / break a
# bond / add a substituent. Returns the new canonical SMILES + a fresh 3D.
# This is what makes the 3D viewer a real "playground" not a static render.
# ---------------------------------------------------------------------------

class AtomEditRequest(BaseModel):
    smiles: str
    op: Literal[
        "swap_element", "break_bond", "add_methyl_at",
        "add_atom_at", "delete_atom", "add_bond", "delete_bond",
        "add_functional_group_at", "attach_fragment",
    ]
    atom_index: Optional[int] = None       # for swap_element / add_*_at / delete_atom
    atom_index_a: Optional[int] = None     # for add_bond (first atom)
    atom_index_b: Optional[int] = None     # for add_bond (second atom)
    bond_index: Optional[int] = None       # for break_bond / delete_bond
    new_element: Optional[str] = None      # element symbol for swap/add_atom_at
    bond_order: Optional[Literal["single", "double", "triple", "aromatic"]] = "single"
    functional_group: Optional[str] = None # name for add_functional_group_at
    fragment_smiles: Optional[str] = None  # SMILES of the fragment to attach (rings, custom)
    fragment_anchor_idx: int = 0           # index within the fragment of the bonding atom
    # Actor attribution — every edit carries its actor (user/designer/critic
    # /editor/strategist). The frontend reads this from the broadcast event
    # to render a step trail. Defaults to "user" when not specified.
    actor: str = "user"
    # Optional session id to broadcast on. When present, every successful
    # edit is published on the playground bus so subscribers (other UI
    # tabs, agent dashboards, replay loggers) re-render in lockstep.
    session_id: Optional[str] = None


@router.post("/molecule/edit")
async def molecule_edit(req: AtomEditRequest) -> dict:
    """Edit a molecule at the atom/bond level. Used by the 3D viewer to
    let the user actually mutate the candidate via clicks. Broadcasts
    `molecule.edit` on the playground bus when session_id is supplied
    so all WS subscribers (frontend tabs, agent UIs) update in real time."""
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError:
        raise HTTPException(503, "RDKit not available")

    mol = Chem.MolFromSmiles(req.smiles)
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {req.smiles}")
    # Kekulize first so we can edit aromatic structures cleanly. Aromatic
    # bonds + atoms have implicit valence rules that break when atoms are
    # removed/disconnected; kekulizing converts to explicit single/double
    # bonds which RWMol can edit safely.
    try:
        Chem.Kekulize(mol, clearAromaticFlags=True)
    except Exception:  # noqa: BLE001
        pass
    rw = Chem.RWMol(mol)

    # Expanded periodic-table coverage. Drug-relevant subset (CHNOPS + halogens
    # + boron/silicon for protected synthons + selenium for SeMet + transition
    # metals seen in metallodrugs + alkali/alkaline earth counter-ions).
    ELEMENTS = {
        "H": 1,  "He": 2,
        "Li": 3, "Be": 4, "B": 5,  "C": 6,  "N": 7,  "O": 8,  "F": 9,  "Ne": 10,
        "Na": 11, "Mg": 12, "Al": 13, "Si": 14, "P": 15, "S": 16, "Cl": 17, "Ar": 18,
        "K": 19, "Ca": 20,
        # First-row transition metals (metallodrugs, cofactors)
        "Ti": 22, "V": 23, "Cr": 24, "Mn": 25, "Fe": 26, "Co": 27,
        "Ni": 28, "Cu": 29, "Zn": 30,
        # Heavier halogens / metalloids / pharma metals
        "As": 33, "Se": 34, "Br": 35,
        "Mo": 42, "Ru": 44, "Rh": 45, "Pd": 46, "Ag": 47, "Cd": 48,
        "I": 53,
        "Pt": 78, "Au": 79, "Hg": 80,
    }
    BOND_ORDERS = {
        "single": Chem.BondType.SINGLE,
        "double": Chem.BondType.DOUBLE,
        "triple": Chem.BondType.TRIPLE,
        "aromatic": Chem.BondType.AROMATIC,
    }

    # Functional group library (SMARTS templates for "attach this fragment")
    # Each has (atoms_to_add, bonds_to_add) starting from anchor=req.atom_index
    # Functional group templates — each is (atoms_to_add, bond_order_to_prev).
    # First atom attaches to anchor with first bond_order, others chain linearly
    # unless this is a "branched" FG where atoms 2..n branch off atom 1.
    FG_TEMPLATES = {
        # Single-atom halogens / heteroatoms
        "hydroxyl":   [("O", "single")],
        "methyl":     [("C", "single")],
        "amine":      [("N", "single")],
        "fluorine":   [("F", "single")],
        "chlorine":   [("Cl", "single")],
        "bromine":    [("Br", "single")],
        "iodine":     [("I", "single")],
        "thiol":      [("S", "single")],
        # Carbonyl / oxo-containing
        "carbonyl":   [("C", "single"), ("O", "double")],                     # >C=O
        "aldehyde":   [("C", "single"), ("O", "double")],                     # –CHO (single H stays implicit)
        "carboxyl":   [("C", "single"), ("O", "double"), ("O", "single")],    # –COOH
        "ester":      [("O", "single"), ("C", "single"), ("O", "double"), ("C", "single")],  # –O–C(=O)–CH3 methyl ester
        "amide":      [("C", "single"), ("O", "double"), ("N", "single")],    # –C(=O)NH2 (branched on C)
        "nitro":      [("N", "single"), ("O", "double"), ("O", "single")],    # –NO2 (branched on N)
        # Sulfur / phosphorus
        "sulfonyl":   [("S", "single"), ("O", "double"), ("O", "double")],    # –S(=O)(=O)–
        "sulfonamide":[("S", "single"), ("O", "double"), ("O", "double"), ("N", "single")],
        "sulfide":    [("S", "single"), ("C", "single")],                     # –S–CH3 thioether
        "phosphate":  [("O", "single"), ("P", "single"), ("O", "double"), ("O", "single"), ("O", "single")],
        "phosphonate":[("P", "single"), ("O", "double"), ("O", "single"), ("O", "single")],
        # Heteroaryl / unsaturated
        "cyano":      [("C", "single"), ("N", "triple")],
        "isocyano":   [("N", "single"), ("C", "triple")],                     # –NC
        "azido":      [("N", "single"), ("N", "double"), ("N", "double")],    # –N=N=N (linear approximation)
        "trifluoromethyl": [("C", "single"), ("F", "single"), ("F", "single"), ("F", "single")],
        "trichloromethyl": [("C", "single"), ("Cl", "single"), ("Cl", "single"), ("Cl", "single")],
        # Two-carbon groups
        "ethyl":      [("C", "single"), ("C", "single")],
        "vinyl":      [("C", "single"), ("C", "double")],                     # –CH=CH2
        "ethynyl":    [("C", "single"), ("C", "triple")],                     # –C≡CH
        "methoxy":    [("O", "single"), ("C", "single")],                     # –O–CH3
        "ethoxy":     [("O", "single"), ("C", "single"), ("C", "single")],
        # Larger
        "isopropyl":  [("C", "single"), ("C", "single"), ("C", "single")],    # branched at first C
        "tert-butyl": [("C", "single"), ("C", "single"), ("C", "single"), ("C", "single")],
        "phenyl":     [("C", "single"), ("C", "aromatic"), ("C", "aromatic"),
                       ("C", "aromatic"), ("C", "aromatic"), ("C", "aromatic")],  # benzene-like
    }
    # FGs whose atoms 2..n BRANCH from atom 1 (the anchor of the FG itself),
    # not chain linearly. Carbonyl/carboxyl/nitro/sulfonyl/sulfonamide/amide
    # all attach multiple substituents to the central heavy atom.
    BRANCHED_FGS = {"carbonyl", "carboxyl", "amide", "nitro", "sulfonyl",
                    "sulfonamide", "phosphonate", "trifluoromethyl",
                    "trichloromethyl", "isopropyl", "tert-butyl", "aldehyde"}

    if req.op == "swap_element":
        if req.atom_index is None or req.new_element is None:
            raise HTTPException(422, detail=_violation(
                "missing_args", "swap_element needs atom_index + new_element",
                hint="Pass both atom_index (target atom) and new_element (e.g. 'N')."))
        if req.atom_index < 0 or req.atom_index >= rw.GetNumAtoms():
            raise HTTPException(422, detail=_violation(
                "atom_index_out_of_range",
                f"atom_index {req.atom_index} out of range (0..{rw.GetNumAtoms()-1})",
                atom_idx=req.atom_index))
        if req.new_element not in ELEMENTS:
            raise HTTPException(422, detail=_violation(
                "unsupported_element", f"unsupported element: {req.new_element}",
                hint="See GET /workbench/chem/elements for the supported palette."))
        rw.GetAtomWithIdx(req.atom_index).SetAtomicNum(ELEMENTS[req.new_element])

    elif req.op == "break_bond" or req.op == "delete_bond":
        if req.bond_index is None:
            raise HTTPException(422, detail=_violation(
                "missing_args", f"{req.op} needs bond_index",
                hint="See GET /workbench/chem/bonds/{smiles_b64} for bond indices."))
        if req.bond_index < 0 or req.bond_index >= rw.GetNumBonds():
            raise HTTPException(422, detail=_violation(
                "bond_index_out_of_range",
                f"bond_index {req.bond_index} out of range (0..{rw.GetNumBonds()-1})",
                bond_idx=req.bond_index))
        b = rw.GetBondWithIdx(req.bond_index)
        rw.RemoveBond(b.GetBeginAtomIdx(), b.GetEndAtomIdx())

    elif req.op == "add_methyl_at":
        if req.atom_index is None:
            raise HTTPException(422, detail=_violation(
                "missing_args", "add_methyl_at needs atom_index",
                hint="Pass atom_index of the anchor atom."))
        c = rw.AddAtom(Chem.Atom(6))
        rw.AddBond(req.atom_index, c, Chem.BondType.SINGLE)

    elif req.op == "add_atom_at":
        if req.atom_index is None or req.new_element is None:
            raise HTTPException(422, detail=_violation(
                "missing_args", "add_atom_at needs atom_index + new_element",
                hint="Pass both anchor atom_index and the element symbol."))
        if req.new_element not in ELEMENTS:
            raise HTTPException(422, detail=_violation(
                "unsupported_element", f"unsupported element: {req.new_element}",
                hint="See GET /workbench/chem/elements for the supported palette."))
        new_idx = rw.AddAtom(Chem.Atom(ELEMENTS[req.new_element]))
        bond_type = BOND_ORDERS.get(req.bond_order or "single", Chem.BondType.SINGLE)
        rw.AddBond(req.atom_index, new_idx, bond_type)

    elif req.op == "delete_atom":
        if req.atom_index is None:
            raise HTTPException(422, detail=_violation(
                "missing_args", "delete_atom needs atom_index"))
        if req.atom_index < 0 or req.atom_index >= rw.GetNumAtoms():
            raise HTTPException(422, detail=_violation(
                "atom_index_out_of_range",
                f"atom_index {req.atom_index} out of range",
                atom_idx=req.atom_index))
        rw.RemoveAtom(req.atom_index)

    elif req.op == "add_bond":
        if req.atom_index_a is None or req.atom_index_b is None:
            raise HTTPException(422, detail=_violation(
                "missing_args", "add_bond needs atom_index_a + atom_index_b"))
        if req.atom_index_a == req.atom_index_b:
            raise HTTPException(422, detail=_violation(
                "self_bond", "cannot bond an atom to itself",
                atom_idx=req.atom_index_a))
        n = rw.GetNumAtoms()
        if not (0 <= req.atom_index_a < n and 0 <= req.atom_index_b < n):
            raise HTTPException(422, detail=_violation(
                "atom_index_out_of_range", "atom_index_a or _b out of range"))
        if rw.GetBondBetweenAtoms(req.atom_index_a, req.atom_index_b) is not None:
            raise HTTPException(422, detail=_violation(
                "bond_already_exists",
                f"bond already exists between {req.atom_index_a} and {req.atom_index_b}",
                hint="Use op:break_bond to remove first, or upgrade order via add_bond on a different pair.",
                suggested_fix="break the existing bond first"))
        bond_type = BOND_ORDERS.get(req.bond_order or "single", Chem.BondType.SINGLE)
        rw.AddBond(req.atom_index_a, req.atom_index_b, bond_type)

    elif req.op == "add_functional_group_at":
        if req.atom_index is None or req.functional_group is None:
            raise HTTPException(422, detail=_violation(
                "missing_args", "add_functional_group_at needs atom_index + functional_group"))
        tpl = FG_TEMPLATES.get(req.functional_group)
        if tpl is None:
            raise HTTPException(422, detail=_violation(
                "unknown_functional_group",
                f"unknown functional group: {req.functional_group}",
                hint="See SKILLS.md §10.3 for the supported FG list."))
        # Build the fragment: anchor connects to new atom 1, which connects to others linearly
        # (simple chain layout; ring FGs would need a separate template).
        prev_idx = req.atom_index
        first_new_idx = None
        for i, (elt, bo) in enumerate(tpl):
            if elt not in ELEMENTS:
                raise HTTPException(422, f"unsupported element in template: {elt}")
            new_idx = rw.AddAtom(Chem.Atom(ELEMENTS[elt]))
            if first_new_idx is None:
                first_new_idx = new_idx
            bond_type = BOND_ORDERS.get(bo, Chem.BondType.SINGLE)
            # Carbonyl/carboxyl/nitro have branching: atom 1 of template gets =O / extra bonds.
            # Simple heuristic: subsequent atoms connect back to first_new_idx for branched FGs.
            if i == 0 or req.functional_group not in BRANCHED_FGS:
                rw.AddBond(prev_idx, new_idx, bond_type)
                prev_idx = new_idx
            else:
                # Branch off the first added atom (anchor of the FG)
                rw.AddBond(first_new_idx, new_idx, bond_type)

    elif req.op == "attach_fragment":
        # Generic fragment attachment via SMILES — enables rings (benzene,
        # pyridine, cyclopropane), heterocycles (imidazole, thiazole),
        # bicyclics, and arbitrary user-supplied fragments. The agent uses
        # this to compose larger structures incrementally.
        if req.atom_index is None or req.fragment_smiles is None:
            raise HTTPException(422, "attach_fragment needs atom_index + fragment_smiles")
        if req.atom_index < 0 or req.atom_index >= rw.GetNumAtoms():
            raise HTTPException(422, "atom_index out of range")
        try:
            frag = Chem.MolFromSmiles(req.fragment_smiles)
            if frag is None:
                raise HTTPException(422, f"unparseable fragment_smiles: {req.fragment_smiles}")
            try:
                Chem.Kekulize(frag, clearAromaticFlags=True)
            except Exception:  # noqa: BLE001
                pass
            anchor_in_frag = req.fragment_anchor_idx
            if anchor_in_frag < 0 or anchor_in_frag >= frag.GetNumAtoms():
                raise HTTPException(422, "fragment_anchor_idx out of range")
            n_main = rw.GetNumAtoms()
            combined = Chem.CombineMols(rw.GetMol(), frag)
            rw2 = Chem.RWMol(combined)
            bond_type = BOND_ORDERS.get(req.bond_order or "single", Chem.BondType.SINGLE)
            rw2.AddBond(req.atom_index, n_main + anchor_in_frag, bond_type)
            rw = rw2
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"attach_fragment failed: {exc}")

    else:
        raise HTTPException(422, f"unknown op: {req.op}")

    # Sanitize — return error if violates valence.
    # If first sanitize fails because of stale aromatic flags on now-
    # broken rings, clear all aromatic flags and retry. RDKit will
    # re-aromatize during sanitize where chemically appropriate.
    try:
        Chem.SanitizeMol(rw)
    except Exception as exc:  # noqa: BLE001
        first_err = str(exc)
        try:
            for atom in rw.GetAtoms():
                atom.SetIsAromatic(False)
            for bond in rw.GetBonds():
                bond.SetIsAromatic(False)
                if bond.GetBondType() == Chem.BondType.AROMATIC:
                    bond.SetBondType(Chem.BondType.SINGLE)
            Chem.SanitizeMol(rw)
        except Exception as exc2:  # noqa: BLE001
            # Translate the RDKit SanitizeException to a structured violation.
            # Common patterns we can match → human-friendly hint:
            err_text = first_err.lower()
            if "valence" in err_text or "explicit valence" in err_text:
                code = "valence_violation"
                msg = first_err
                hint = "Atom would exceed its allowed valence. Pick a different element, lower the bond order, or break a neighbor bond first."
                fix = "lower bond order or remove a neighbor"
            elif "aromatic" in err_text:
                code = "aromaticity_violation"
                msg = first_err
                hint = "Aromatic ring constraint violated (Hückel rule). The structure no longer satisfies 4n+2 π electrons."
                fix = "restore the ring or convert to non-aromatic"
            elif "non-ring" in err_text:
                code = "non_ring_aromatic_atom"
                msg = first_err
                hint = "An atom flagged aromatic is no longer in a ring."
                fix = "convert to non-aromatic bonds"
            else:
                code = "chemistry_violation"
                msg = f"chemistry violation: {first_err}"
                hint = "RDKit could not sanitize the resulting structure."
                fix = "undo this edit"
            raise HTTPException(422, detail=_violation(code, msg, hint=hint, suggested_fix=fix))

    new_smiles = Chem.MolToSmiles(rw, canonical=True)

    # Broadcast `molecule.edit` on the playground bus so every subscriber
    # (other frontend tabs, agent dashboards, replay loggers) re-renders
    # in lockstep. The edit carries its actor so the step trail can label
    # who did what without rendering halos on the molecule visual.
    if req.session_id:
        try:
            from workspace.playground import get_bus
            import time as _time
            get_bus().publish(req.session_id, {
                "type": "molecule.edit",
                "ts": _time.time(),
                "actor": req.actor,
                "op": req.op,
                "atom_index": req.atom_index,
                "bond_index": req.bond_index,
                "new_element": req.new_element,
                "functional_group": req.functional_group,
                "smiles": new_smiles,
                "n_atoms": rw.GetNumAtoms(),
                "n_bonds": rw.GetNumBonds(),
            })
        except Exception:  # noqa: BLE001
            pass  # WS broadcast is best-effort; never fail the edit

    return {
        "smiles": new_smiles,
        "n_atoms": rw.GetNumAtoms(),
        "n_bonds": rw.GetNumBonds(),
        "actor": req.actor,
    }


# ---------------------------------------------------------------------------
# Curated antibiotic reference set — used for similarity matching ("which
# known drug does this candidate resemble?") and as the seed for the
# library on first launch. Single source of truth for the agent + UI.
# ---------------------------------------------------------------------------

ANTIBIOTIC_REFERENCE: list[dict] = [
    # β-lactams
    {"name": "Penicillin G",      "smiles": "CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O",
     "drug_class": "beta-lactam · penicillin", "mechanism": "PBP inhibition",
     "targets": ["MRSA", "VRE", "NGono"], "year": 1928},
    {"name": "Amoxicillin",       "smiles": "CC1(C)S[C@@H]2[C@H](NC(=O)[C@@H](N)c3ccc(O)cc3)C(=O)N2[C@H]1C(=O)O",
     "drug_class": "beta-lactam · aminopenicillin", "mechanism": "PBP inhibition",
     "targets": ["MRSA", "EColi-CRE"], "year": 1972},
    {"name": "Methicillin",       "smiles": "COc1ccccc1C(=O)N[C@@H]1C(=O)N2[C@@H](C(=O)O)C(C)(C)S[C@@H]12",
     "drug_class": "beta-lactam · semisynthetic penicillin", "mechanism": "PBP inhibition",
     "targets": ["MRSA"], "year": 1959},
    {"name": "Cefuroxime",        "smiles": "CO/N=C(\\C(=O)N[C@@H]1C(=O)N2[C@H]1SCC(=C2C(=O)O)COC(=O)N)/c1ccoc1",
     "drug_class": "beta-lactam · cephalosporin (2nd gen)", "mechanism": "PBP inhibition",
     "targets": ["EColi-CRE", "KpneuCRE"], "year": 1977},
    {"name": "Ceftriaxone",       "smiles": "CO/N=C(\\C(=O)N[C@@H]1C(=O)N2[C@H]1SCC(=C2C(=O)O)CSc1nc(=O)c(=O)[nH]n1C)/c1csc(N)n1",
     "drug_class": "beta-lactam · cephalosporin (3rd gen)", "mechanism": "PBP inhibition",
     "targets": ["EColi-CRE", "NGono"], "year": 1982},
    {"name": "Meropenem",         "smiles": "CC1=C(C(=O)O)N2C(=O)[C@H]([C@H]1C)[C@H]2[C@H](C)O.OS(=O)(=O)C1CSC2N1C(=O)C2=C(C)C(=O)O",
     "drug_class": "beta-lactam · carbapenem", "mechanism": "PBP inhibition",
     "targets": ["EColi-CRE", "KpneuCRE", "Paer"], "year": 1996},
    {"name": "Aztreonam",         "smiles": "CC(C)(C(=O)O)O/N=C(\\C(=O)NC1C(=O)N(C1)S(=O)(=O)O)/c1csc(N)n1",
     "drug_class": "monobactam", "mechanism": "PBP3 inhibition",
     "targets": ["EColi-CRE", "KpneuCRE", "Paer"], "year": 1987},
    {"name": "Clavulanic acid",   "smiles": "OC(=O)C1=CCO[C@@H]2CC(=O)N12",
     "drug_class": "beta-lactamase inhibitor", "mechanism": "irreversible serine-β-lactamase inhibition",
     "targets": ["EColi-CRE"], "year": 1976},
    # Fluoroquinolones
    {"name": "Ciprofloxacin",     "smiles": "OC(=O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O",
     "drug_class": "fluoroquinolone", "mechanism": "DNA gyrase inhibition",
     "targets": ["EColi-CRE", "Paer", "NGono"], "year": 1987},
    {"name": "Levofloxacin",      "smiles": "C[C@H]1COc2c(N3CCN(C)CC3)c(F)cc3C(=O)C(=CN1c23)C(=O)O",
     "drug_class": "fluoroquinolone", "mechanism": "DNA gyrase / topoisomerase IV",
     "targets": ["EColi-CRE", "Paer"], "year": 1996},
    {"name": "Moxifloxacin",      "smiles": "COc1c(N2CC3CCCNC3C2)c(F)cc2c1N(C1CC1)C=C(C(=O)O)C2=O",
     "drug_class": "fluoroquinolone", "mechanism": "DNA gyrase / topoisomerase IV",
     "targets": ["MRSA", "Mtb"], "year": 1999},
    # Aminoglycosides
    {"name": "Gentamicin",        "smiles": "CC(N)C1OC(OC2C(N)CC(N)C(OC3OCC(C)(O)C(NC)C3O)C2O)C(N)C(O)C1O",
     "drug_class": "aminoglycoside", "mechanism": "30S ribosomal misreading",
     "targets": ["EColi-CRE", "Paer"], "year": 1963},
    {"name": "Tobramycin",        "smiles": "NCC1OC(OC2C(N)CC(N)C(OC3OC(CN)C(O)C(O)C3N)C2O)C(N)CC1O",
     "drug_class": "aminoglycoside", "mechanism": "30S ribosomal misreading",
     "targets": ["Paer", "EColi-CRE"], "year": 1967},
    {"name": "Amikacin",          "smiles": "NCC1OC(OC2C(O)C(NC(=O)C(O)CCN)CC(N)C2OC2OC(CO)C(O)C(O)C2N)C(N)CC1O",
     "drug_class": "aminoglycoside", "mechanism": "30S ribosomal misreading",
     "targets": ["Mtb", "Paer"], "year": 1972},
    # Tetracyclines
    {"name": "Doxycycline",       "smiles": "CC1c2cccc(O)c2C(=O)C2=C1C(=O)C1(O)C(C(=O)C(C(=O)N)=C1O)C2N(C)C",
     "drug_class": "tetracycline", "mechanism": "30S ribosomal binding",
     "targets": ["MRSA", "VRE"], "year": 1967},
    {"name": "Tigecycline",       "smiles": "CN(C)C1C(O)=C(C(=O)N)C(=O)C2(O)C1Cc1cc(NC(=O)CNC(C)(C)C)c(N(C)C)c(O)c1C2=O",
     "drug_class": "glycylcycline", "mechanism": "30S ribosomal binding",
     "targets": ["MRSA", "VRE", "Abaum"], "year": 2005},
    # Macrolides
    {"name": "Erythromycin",      "smiles": "CCC1OC(=O)C(C)C(OC2CC(C)(OC)C(O)C(C)O2)C(C)C(OC2OC(C)CC(N(C)C)C2O)C(C)(O)CC(C)C(=O)C(C)C(O)C1(C)O",
     "drug_class": "macrolide", "mechanism": "50S ribosomal binding",
     "targets": ["MRSA"], "year": 1952},
    {"name": "Azithromycin",      "smiles": "CCC1OC(=O)C(C)C(OC2CC(C)(OC)C(O)C(C)O2)C(C)C(OC2OC(C)CC(N(C)C)C2O)C(C)(O)CC(C)CN(C)C(C)C(O)C1(C)O",
     "drug_class": "azalide (macrolide)", "mechanism": "50S ribosomal binding",
     "targets": ["MRSA", "NGono"], "year": 1980},
    # Glycopeptides
    {"name": "Vancomycin",        "smiles": "CC1C(C(CC(=O)NC(C)C(O)C2=CC(=C(C(=C2)O)Cl)Oc2cc3cc(c2O)Oc2ccc(cc2Cl)C(C(NC(=O)C(c2ccc(O)c(O)c2)NC(=O)c2ccc(O)c(O)c2)C(=O)NC2C(=O)NC(c4cc(O)cc(O)c4-c4cc3ccc4O)C(=O)O)O)C(=O)NC(C(=O)NC(C)C2OC(CO)C(O)C(N)C2O)C(=O)NC(c2cc(O)cc(O)c2-c2c(O)cc(O)cc2C(C)C)C(=O)O)NC(=O)C(N(C)C)C)O",
     "drug_class": "glycopeptide", "mechanism": "D-Ala-D-Ala binding · cell-wall synthesis",
     "targets": ["MRSA", "VRE"], "year": 1958},
    {"name": "Daptomycin",        "smiles": "CCCCCCCCCC(=O)NC(Cc1c[nH]c2ccccc12)C(=O)NC(CC(=O)N)C(=O)NC(CC(=O)O)C(=O)NC1C(C)OC(=O)C(Cc2ccc(O)cc2)NC(=O)C(CCCN)NC(=O)C(CC(=O)O)NC(=O)C(C)NC(=O)C(CC(=O)O)NC(=O)CNC(=O)C(NC(=O)C1)C(C)CC(=O)O",
     "drug_class": "lipopeptide", "mechanism": "membrane depolarization",
     "targets": ["MRSA", "VRE"], "year": 2003},
    # Oxazolidinones
    {"name": "Linezolid",         "smiles": "CC(=O)NCC1CN(c2ccc(N3CCOCC3)cc2F)C(=O)O1",
     "drug_class": "oxazolidinone", "mechanism": "50S initiation complex",
     "targets": ["MRSA", "VRE"], "year": 2000},
    # Polymyxins
    {"name": "Colistin",          "smiles": "CCC(C)CCCCC(=O)NC(CCN)C(=O)NC(C(C)O)C(=O)NC(CCN)C(=O)NC1CCNC(=O)C(NC(=O)C(NC(=O)C(NC(=O)C(NC(=O)C1)CCN)CC(C)C)CC(C)C)CCN",
     "drug_class": "polymyxin", "mechanism": "outer-membrane disruption (binds LPS)",
     "targets": ["EColi-CRE", "KpneuCRE", "Abaum", "Paer"], "year": 1959},
    # Nitroimidazoles / antimycobacterials
    {"name": "Metronidazole",     "smiles": "Cc1ncc([N+](=O)[O-])n1CCO",
     "drug_class": "nitroimidazole", "mechanism": "DNA strand breakage (anaerobes)",
     "targets": ["EColi-CRE"], "year": 1959},
    {"name": "Isoniazid",         "smiles": "NNC(=O)c1ccncc1",
     "drug_class": "antimycobacterial", "mechanism": "InhA inhibition (mycolic acid)",
     "targets": ["Mtb"], "year": 1952},
    {"name": "Rifampicin",        "smiles": "CO[C@H]1\\C=C\\O[C@@]2(C)Oc3c(C)c(O)c4c(O)c(NC(=O)\\C(C)=C/C=C/[C@H](C)[C@H](O)[C@@H](C)[C@@H](O)[C@@H](C)[C@H](OC(C)=O)[C@H]1C)c(/C=N/N1CCN(C)CC1)c(O)c4c3C2=O",
     "drug_class": "rifamycin", "mechanism": "RNA polymerase inhibition",
     "targets": ["Mtb", "MRSA"], "year": 1965},
    {"name": "Pyrazinamide",      "smiles": "NC(=O)c1cnccn1",
     "drug_class": "antimycobacterial", "mechanism": "POA (acid pH) · membrane",
     "targets": ["Mtb"], "year": 1952},
    {"name": "Ethambutol",        "smiles": "CCC(CO)NCCNC(CC)CO",
     "drug_class": "antimycobacterial", "mechanism": "arabinosyl transferase",
     "targets": ["Mtb"], "year": 1961},
    # Sulfonamides + diaminopyrimidine combos
    {"name": "Trimethoprim",      "smiles": "COc1cc(Cc2cnc(N)nc2N)cc(OC)c1OC",
     "drug_class": "diaminopyrimidine", "mechanism": "DHFR inhibition",
     "targets": ["EColi-CRE"], "year": 1962},
    {"name": "Sulfamethoxazole",  "smiles": "Cc1cc(NS(=O)(=O)c2ccc(N)cc2)no1",
     "drug_class": "sulfonamide", "mechanism": "DHPS inhibition",
     "targets": ["EColi-CRE"], "year": 1961},
    # Lincosamides / streptogramins
    {"name": "Clindamycin",       "smiles": "CCCC1CC(C(=O)NC(C(C)Cl)C2OC(SC)C(O)C(O)C2O)N(C)C1",
     "drug_class": "lincosamide", "mechanism": "50S ribosomal binding",
     "targets": ["MRSA"], "year": 1968},
    # Newer / pipeline
    {"name": "Cefiderocol",       "smiles": "CO/N=C(\\C(=O)N[C@@H]1C(=O)N2[C@H]1SCC(=C2C(=O)O)C[N+]1(CCNC(=O)c2ccccc2OC2=CC(=O)C(O)=C(O)C=2)CCCC1)/c1csc(N)n1",
     "drug_class": "siderophore cephalosporin", "mechanism": "PBP3 + iron-uptake exploit",
     "targets": ["EColi-CRE", "KpneuCRE", "Abaum"], "year": 2019},
    {"name": "Eravacycline",      "smiles": "CN(C)C1C(=O)C(C(=O)N)=C(O)C2(O)C1Cc1cc(F)c(NCC(=O)NC(C)(C)C)c(N(C)C)c1C2=O",
     "drug_class": "fluorocycline", "mechanism": "30S ribosomal binding",
     "targets": ["MRSA", "VRE"], "year": 2018},
]


def _morgan_fp(mol, radius: int = 2, n_bits: int = 2048):
    """Morgan/ECFP4 fingerprint — used for similarity matching."""
    from rdkit.Chem import AllChem
    return AllChem.GetMorganFingerprintAsBitVect(mol, radius, nBits=n_bits)


@router.get("/molecule/match-known")
async def molecule_match_known(smiles: str, top_k: int = 5) -> Dict[str, Any]:
    """Find the closest known antibiotic(s) to the candidate via Tanimoto
    on Morgan-2 fingerprints. Returns top_k matches with similarity in
    [0, 1]. Used by the 3D viewer's "tag-detection" overlay so the user
    sees `≈ Penicillin G (0.94)` as they build atom-by-atom."""
    try:
        from rdkit import Chem
        from rdkit import DataStructs
    except ImportError:
        raise HTTPException(503, "RDKit not available")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")
    cand_fp = _morgan_fp(mol)
    scored: list[tuple[float, dict]] = []
    for ref in ANTIBIOTIC_REFERENCE:
        rmol = Chem.MolFromSmiles(ref["smiles"])
        if rmol is None:
            continue
        rfp = _morgan_fp(rmol)
        sim = DataStructs.TanimotoSimilarity(cand_fp, rfp)
        scored.append((sim, ref))
    scored.sort(key=lambda x: x[0], reverse=True)
    matches = [
        {
            "name": ref["name"],
            "drug_class": ref["drug_class"],
            "mechanism": ref["mechanism"],
            "targets": ref["targets"],
            "year": ref["year"],
            "smiles": ref["smiles"],
            "similarity": round(sim, 4),
            "is_exact": sim >= 0.999,
        }
        for sim, ref in scored[:top_k]
    ]
    return {
        "matches": matches,
        "best": matches[0] if matches else None,
        "is_known": bool(matches and matches[0]["similarity"] >= 0.95),
        "candidate_smiles": smiles,
    }


@router.get("/molecule/reference-set")
async def molecule_reference_set() -> Dict[str, Any]:
    """Curated known-antibiotic library used for matching, library seed,
    and the 'load reference' picker in the 2D builder. Same set the agent
    sees when it asks 'show me known antibiotics in class X'."""
    return {
        "antibiotics": ANTIBIOTIC_REFERENCE,
        "count": len(ANTIBIOTIC_REFERENCE),
        "classes": sorted(set(a["drug_class"].split(" · ")[0] for a in ANTIBIOTIC_REFERENCE)),
    }


class ReplaceRequest(BaseModel):
    smiles: str


# ---------------------------------------------------------------------------
# Curated SMARTS preset catalog with categories + per-category colors.
# Single source of truth — frontend fetches this so the SMARTS panel
# stays consistent with the agent's smarts_match tool semantics.
# ---------------------------------------------------------------------------

SMARTS_PRESETS: list[dict] = [
    # Antibiotic-class warheads
    {"label": "β-lactam",          "pattern": "[#7]1[#6](=O)[#6]([#6]1)",          "category": "antibiotic-warhead"},
    {"label": "thiazolidine",      "pattern": "C1SCNC1",                           "category": "antibiotic-warhead"},
    {"label": "fluoroquinolone",   "pattern": "c1cc2N(C)cc(C(=O)O)c(=O)c2cc1F",    "category": "antibiotic-warhead"},
    {"label": "aminoglycoside-NH₂","pattern": "[CH]([NH2])[CH]([OH])[CH][CH]([OH])","category": "antibiotic-warhead"},
    {"label": "tetracycline core", "pattern": "C1=CC=C2C(=O)C3=C(C(=C(C=C3)O)O)C(=O)C2=C1","category": "antibiotic-warhead"},
    {"label": "oxazolidinone",     "pattern": "O=C1OCCN1",                         "category": "antibiotic-warhead"},
    # Acid / base / oxo functional groups
    {"label": "carboxylic acid",   "pattern": "C(=O)[OH]",                          "category": "acid-base"},
    {"label": "ester",             "pattern": "[#6][CX3](=O)O[#6]",                 "category": "acid-base"},
    {"label": "amide",             "pattern": "[NX3][CX3](=[OX1])",                 "category": "acid-base"},
    {"label": "peptide bond",      "pattern": "[NX3][CX3](=O)[CX3]",                "category": "acid-base"},
    {"label": "carbonyl",          "pattern": "[CX3]=[OX1]",                        "category": "acid-base"},
    {"label": "aldehyde",          "pattern": "[CX3H1](=O)[#6]",                    "category": "acid-base"},
    {"label": "ketone",            "pattern": "[#6][CX3](=O)[#6]",                  "category": "acid-base"},
    {"label": "ether",             "pattern": "[OD2]([#6])[#6]",                    "category": "acid-base"},
    {"label": "alcohol -OH",       "pattern": "[OX2H][CX4]",                        "category": "acid-base"},
    {"label": "phenol",            "pattern": "c[OH]",                              "category": "acid-base"},
    {"label": "primary amine",     "pattern": "[NX3;H2;!$(NC=O)]",                  "category": "acid-base"},
    {"label": "secondary amine",   "pattern": "[NX3;H1;!$(NC=O)]",                  "category": "acid-base"},
    {"label": "tertiary amine",    "pattern": "[NX3;H0;!$(NC=O);!$(N=*)]",          "category": "acid-base"},
    {"label": "thiol -SH",         "pattern": "[#16X2H]",                           "category": "acid-base"},
    # Sulfur / phosphorus / nitrogen oxos
    {"label": "sulfonamide",       "pattern": "[#16](=O)(=O)[#7]",                  "category": "heteroatom-oxo"},
    {"label": "sulfonyl",          "pattern": "[#16X4](=[OX1])(=[OX1])",            "category": "heteroatom-oxo"},
    {"label": "phosphate",         "pattern": "P(=O)(O)(O)O",                       "category": "heteroatom-oxo"},
    {"label": "nitro",             "pattern": "[N+](=O)[O-]",                       "category": "heteroatom-oxo"},
    {"label": "nitrile -CN",       "pattern": "C#N",                                "category": "heteroatom-oxo"},
    {"label": "azide",             "pattern": "N=[N+]=[N-]",                        "category": "heteroatom-oxo"},
    # Halogens
    {"label": "halogen",           "pattern": "[F,Cl,Br,I]",                        "category": "halogen"},
    {"label": "trifluoromethyl",   "pattern": "C(F)(F)F",                           "category": "halogen"},
    {"label": "aryl halide",       "pattern": "[c][F,Cl,Br,I]",                     "category": "halogen"},
    # Aromatic / heteroaryl
    {"label": "aromatic-N",        "pattern": "[n]",                                "category": "aromatic"},
    {"label": "benzene",           "pattern": "c1ccccc1",                           "category": "aromatic"},
    {"label": "pyridine",          "pattern": "c1ccncc1",                           "category": "aromatic"},
    {"label": "imidazole",         "pattern": "c1cnc[nH]1",                         "category": "aromatic"},
    {"label": "thiazole",          "pattern": "c1cscn1",                            "category": "aromatic"},
    {"label": "indole",            "pattern": "c1ccc2[nH]ccc2c1",                   "category": "aromatic"},
    {"label": "quinoline",         "pattern": "c1ccc2ncccc2c1",                     "category": "aromatic"},
    # Drug-likeness motifs
    {"label": "Michael acceptor",  "pattern": "[#6]=[#6][CX3](=O)",                 "category": "reactivity"},
    {"label": "epoxide",           "pattern": "C1OC1",                              "category": "reactivity"},
    {"label": "Mannich base",      "pattern": "[NX3]C[CX4]C(=O)",                   "category": "reactivity"},
    {"label": "guanidine",         "pattern": "NC(=N)N",                            "category": "reactivity"},
    {"label": "urea",              "pattern": "[NX3][CX3](=[OX1])[NX3]",            "category": "reactivity"},
]

SMARTS_CATEGORY_COLOR: dict[str, str] = {
    "antibiotic-warhead": "#10b981",   # green — flagship
    "acid-base":          "#dc2626",   # red — ionizable / H-bond
    "heteroatom-oxo":     "#ca8a04",   # amber — S/P/N=O
    "halogen":            "#16a34a",   # leaf green — halogens
    "aromatic":           "#a855f7",   # purple — aromatic systems
    "reactivity":         "#ea580c",   # orange — reactive motifs
}


@router.get("/molecule/state")
async def molecule_state(
    smiles: str,
    include: str = "diagnostics,bonds,auto_patterns,match_known,properties",
    top_k: int = 3,
) -> Dict[str, Any]:
    """Combined endpoint that returns ALL the per-molecule state the
    frontend needs in ONE round-trip. The chem container previously
    polled /chem/diagnostics, /chem/bonds, /chem/auto-patterns,
    /molecule/match-known, /molecule/properties on every SMILES change
    — five separate requests racing each other. This consolidates them
    so the entire panel updates in one network hop.

    `include` is a comma-separated list of slices to compute. Omit
    sections to save backend work (e.g. include=diagnostics,bonds).

    Output keys (only present if requested + computed):
      - diagnostics: same as /chem/diagnostics
      - bonds:        same as /chem/bonds
      - auto_patterns: same as /chem/auto-patterns
      - match_known:  same as /molecule/match-known
      - properties:   same as /molecule/properties (medchem stack)
    """
    try:
        from rdkit import Chem
    except ImportError:
        raise HTTPException(503, "RDKit not available")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(422, detail=_violation(
            "unparseable_smiles", f"unparseable SMILES: {smiles}"))

    wanted = {s.strip() for s in include.split(",") if s.strip()}
    out: Dict[str, Any] = {"smiles": smiles, "n_atoms": mol.GetNumAtoms(),
                            "n_bonds": mol.GetNumBonds()}

    # ---- diagnostics ----
    if "diagnostics" in wanted:
        incomplete: list[Dict[str, Any]] = []
        for atom in mol.GetAtoms():
            sym = atom.GetSymbol()
            max_v = _DEFAULT_VALENCE.get(sym, 0)
            if max_v == 0:
                continue
            adjusted_max = max_v + atom.GetFormalCharge()
            explicit = atom.GetExplicitValence()
            n_h = atom.GetTotalNumHs()
            total = explicit + n_h
            if total < adjusted_max - 1:
                incomplete.append(_violation(
                    "atom_under_valent",
                    f"atom {atom.GetIdx()} ({sym}) has only {total} bonds; expected {adjusted_max}",
                    hint=f"{sym} normally forms {adjusted_max} bonds.",
                    atom_idx=atom.GetIdx(),
                    suggested_fix=f"add a bond on atom {atom.GetIdx()}",
                ))
        total_charge = sum(a.GetFormalCharge() for a in mol.GetAtoms())
        charge_warnings: list[Dict[str, Any]] = []
        if abs(total_charge) > 0:
            charge_warnings.append(_violation(
                "non_zero_total_charge", f"total formal charge = {total_charge:+d}",
                hint="Most drugs are net-neutral.",
                suggested_fix="add a counterion or balance the charge"))
        frags = Chem.GetMolFrags(mol)
        n_frags = len(frags)
        fragment_warnings: list[Dict[str, Any]] = []
        fragment_atom_ids: list[list[int]] = [list(f) for f in frags]
        main_frag_idx = max(range(n_frags), key=lambda i: len(frags[i])) if n_frags else 0
        broken_off_atom_ids: list[int] = []
        if n_frags > 1:
            for i, f in enumerate(frags):
                if i != main_frag_idx:
                    broken_off_atom_ids.extend(list(f))
            fragment_warnings.append(_violation(
                "disconnected_fragments",
                f"molecule has {n_frags} disconnected fragments",
                hint="A bond was broken without reconnection.",
                suggested_fix="reconnect with add_bond"))
        if n_frags > 1 or incomplete:
            status_tier = "block"
            status_label = (f"{n_frags} fragments" if n_frags > 1
                            else f"{len(incomplete)} under-valent")
        elif charge_warnings:
            status_tier, status_label = "warn", f"charge {total_charge:+d}"
        else:
            status_tier, status_label = "ok", "valid"
        out["diagnostics"] = {
            "is_valid": (not incomplete) and (n_frags == 1),
            "n_atoms": mol.GetNumAtoms(),
            "n_bonds": mol.GetNumBonds(),
            "n_fragments": n_frags,
            "total_formal_charge": total_charge,
            "incomplete_atoms": incomplete,
            "charge_warnings": charge_warnings,
            "fragment_warnings": fragment_warnings,
            "all_violations": incomplete + charge_warnings + fragment_warnings,
            "fragment_atom_ids": fragment_atom_ids,
            "main_fragment_idx": main_frag_idx,
            "broken_off_atom_ids": broken_off_atom_ids,
            "status_tier": status_tier,
            "status_label": status_label,
        }

    # ---- bonds ----
    if "bonds" in wanted:
        bonds: list[dict] = []
        for b in mol.GetBonds():
            bt = b.GetBondType()
            order = "double" if bt == Chem.BondType.DOUBLE else \
                    "triple" if bt == Chem.BondType.TRIPLE else \
                    "aromatic" if bt == Chem.BondType.AROMATIC else "single"
            bonds.append({
                "bond_idx": b.GetIdx(), "atom_a": b.GetBeginAtomIdx(),
                "atom_b": b.GetEndAtomIdx(), "order": order,
                "in_ring": b.IsInRing(), "is_aromatic": b.GetIsAromatic(),
            })
        out["bonds"] = {"bonds": bonds, "n_bonds": len(bonds)}

    # ---- auto_patterns ----
    if "auto_patterns" in wanted:
        hits: list[dict] = []
        for preset in SMARTS_PRESETS:
            try:
                patt = Chem.MolFromSmarts(preset["pattern"])
                if patt is None:
                    continue
                matches = mol.GetSubstructMatches(patt)
                if not matches:
                    continue
                atom_idxs = sorted({i for m in matches for i in m})
                hits.append({
                    "label": preset["label"], "pattern": preset["pattern"],
                    "category": preset["category"],
                    "color": SMARTS_CATEGORY_COLOR.get(preset["category"], "#6b7280"),
                    "hit_count": len(matches), "atom_idxs": atom_idxs,
                })
            except Exception:  # noqa: BLE001
                continue
        cat_order = list(SMARTS_CATEGORY_COLOR.keys())
        hits.sort(key=lambda h: (cat_order.index(h["category"])
                                 if h["category"] in cat_order else 99, h["label"]))
        out["auto_patterns"] = {
            "matches": hits, "count": len(hits),
            "total_presets_checked": len(SMARTS_PRESETS),
        }

    # ---- match_known ----
    if "match_known" in wanted:
        try:
            from rdkit import DataStructs
            from rdkit.Chem import AllChem
            cand_fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
            scored: list[tuple] = []
            for ref in ANTIBIOTIC_REFERENCE:
                rmol = Chem.MolFromSmiles(ref["smiles"])
                if rmol is None:
                    continue
                rfp = AllChem.GetMorganFingerprintAsBitVect(rmol, 2, nBits=2048)
                sim = DataStructs.TanimotoSimilarity(cand_fp, rfp)
                scored.append((sim, ref))
            scored.sort(key=lambda x: x[0], reverse=True)
            matches = [{
                "name": ref["name"], "drug_class": ref["drug_class"],
                "mechanism": ref["mechanism"], "targets": ref["targets"],
                "year": ref["year"], "smiles": ref["smiles"],
                "similarity": round(sim, 4), "is_exact": sim >= 0.999,
            } for sim, ref in scored[:top_k]]
            out["match_known"] = {
                "matches": matches, "best": matches[0] if matches else None,
                "is_known": bool(matches and matches[0]["similarity"] >= 0.95),
            }
        except Exception:  # noqa: BLE001
            out["match_known"] = {"matches": [], "best": None, "is_known": False}

    # ---- properties (lightweight: only element_counts + key fields) ----
    if "properties" in wanted:
        try:
            from rdkit.Chem import Descriptors
            element_counts: Dict[str, int] = {}
            for a in mol.GetAtoms():
                sym = a.GetSymbol()
                element_counts[sym] = element_counts.get(sym, 0) + 1
            out["properties"] = {
                "element_counts": element_counts,
                "molecular_weight": round(Descriptors.MolWt(mol), 2),
                "n_heavy_atoms": mol.GetNumHeavyAtoms(),
                "n_rings": mol.GetRingInfo().NumRings(),
            }
        except Exception:  # noqa: BLE001
            out["properties"] = {"element_counts": {}}

    return out


@router.get("/chem/auto-patterns")
async def chem_auto_patterns(smiles: str) -> Dict[str, Any]:
    """Run EVERY curated SMARTS preset against the candidate and return
    ONLY the ones that match. Used by the Properties panel to auto-
    surface "patterns found so far" without the user having to click
    each preset. The agent uses this to know which structural classes
    the candidate already contains.

    Output: list of {label, pattern, category, color, hit_count, atom_idxs}.
    Sorted by category then label for stable rendering.
    """
    try:
        from rdkit import Chem
    except ImportError:
        raise HTTPException(503, "RDKit not available")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(422, detail=_violation(
            "unparseable_smiles", f"unparseable SMILES: {smiles}"))
    hits: List[Dict[str, Any]] = []
    for preset in SMARTS_PRESETS:
        try:
            patt = Chem.MolFromSmarts(preset["pattern"])
            if patt is None:
                continue
            matches = mol.GetSubstructMatches(patt)
            if not matches:
                continue
            # Flatten atom indices across all unique matches
            atom_idxs = sorted({i for m in matches for i in m})
            hits.append({
                "label": preset["label"],
                "pattern": preset["pattern"],
                "category": preset["category"],
                "color": SMARTS_CATEGORY_COLOR.get(preset["category"], "#6b7280"),
                "hit_count": len(matches),
                "atom_idxs": atom_idxs,
            })
        except Exception:  # noqa: BLE001
            continue
    # Stable order: category then label
    cat_order = list(SMARTS_CATEGORY_COLOR.keys())
    hits.sort(key=lambda h: (cat_order.index(h["category"]) if h["category"] in cat_order else 99, h["label"]))
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for h in hits:
        by_category.setdefault(h["category"], []).append(h)
    return {
        "matches": hits,
        "by_category": by_category,
        "count": len(hits),
        "total_presets_checked": len(SMARTS_PRESETS),
    }


@router.get("/chem/smarts-presets")
async def chem_smarts_presets() -> Dict[str, Any]:
    """Curated SMARTS catalog with category + color. The frontend SMARTS
    panel renders one section per category, color-keyed. Single source
    of truth for both UI and agent skill 'smarts_match'."""
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for p in SMARTS_PRESETS:
        by_category.setdefault(p["category"], []).append(p)
    return {
        "presets": SMARTS_PRESETS,
        "by_category": by_category,
        "categories": [
            {"name": k, "color": v, "count": len(by_category.get(k, []))}
            for k, v in SMARTS_CATEGORY_COLOR.items()
            if k in by_category
        ],
        "count": len(SMARTS_PRESETS),
    }


# Drug-class → color map for the Library + Match panels. Same color is
# used by every UI element keyed to a drug class so the user sees one
# consistent visual identity for "β-lactam", "fluoroquinolone", etc.
DRUG_CLASS_COLOR: dict[str, str] = {
    "beta-lactam":         "#10b981",  # green
    "fluoroquinolone":     "#2563eb",  # blue
    "aminoglycoside":      "#ea580c",  # orange
    "tetracycline":        "#9a3412",  # brown
    "glycylcycline":       "#9a3412",  # same family
    "macrolide":           "#a855f7",  # purple
    "azalide (macrolide)": "#a855f7",
    "glycopeptide":        "#ec4899",  # pink
    "lipopeptide":         "#ec4899",
    "oxazolidinone":       "#0891b2",  # teal
    "polymyxin":           "#84cc16",  # lime
    "nitroimidazole":      "#f59e0b",  # amber
    "antimycobacterial":   "#7c3aed",  # violet
    "diaminopyrimidine":   "#06b6d4",  # cyan
    "sulfonamide":         "#06b6d4",
    "lincosamide":         "#a855f7",
    "rifamycin":           "#7c3aed",
    "monobactam":          "#10b981",
    "beta-lactamase inhibitor": "#10b981",
    "siderophore cephalosporin": "#10b981",
    "fluorocycline":       "#9a3412",
}


@router.get("/molecule/drug-class-colors")
async def molecule_drug_class_colors() -> Dict[str, Any]:
    """Drug-class → color map. Used by the Library panel + Match overlay
    + any UI surface that shows a drug class. Single source of truth."""
    return {"colors": DRUG_CLASS_COLOR}


@router.post("/molecule/replace")
async def molecule_replace(req: ReplaceRequest) -> Dict[str, Any]:
    """Validate a full SMILES string and return canonical form. Used by
    the SMILES quick-input field in the 2D builder so a user (or agent)
    can paste a complete structure instead of building atom-by-atom."""
    try:
        from rdkit import Chem
    except ImportError:
        raise HTTPException(503, "RDKit not available")
    mol = Chem.MolFromSmiles(req.smiles)
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {req.smiles}")
    canonical = Chem.MolToSmiles(mol, canonical=True)
    return {
        "smiles": canonical,
        "n_atoms": mol.GetNumAtoms(),
        "n_bonds": mol.GetNumBonds(),
        "n_rings": mol.GetRingInfo().NumRings(),
    }


# ---------------------------------------------------------------------------
# Pocket coords — per-pathogen binding-site centers (curated from PDB sites
# documented in the literature). Used to translate the ligand into the
# actual pocket instead of rendering it floating at the origin.
# ---------------------------------------------------------------------------

# Pathogen → primary PDB target. Every PDB here MUST exist in the
# curated CARD resistance subset (data/curated/card_resistance_subset.json)
# so that selecting a pathogen drives a target the resistance / harden /
# predict endpoints can actually score. KpneuCRE + Paer previously
# pointed at 6QWN / 5DPX (porin / efflux structures with NO curated
# mutations) — picking those pathogens silently 404'd the whole
# resistance chain. They now point at the NDM-1 / DNA-gyrase-B targets
# that the CARD subset covers.
PATHOGEN_TARGET_PDB: dict[str, str] = {
    "MRSA":      "1VQQ",  # PBP2a
    "Mtb":       "2X22",  # InhA
    "EColi-CRE": "5UL8",  # KPC-2
    "KpneuCRE":  "3SPU",  # NDM-1
    "Abaum":     "7M4F",  # OXA-23
    "Paer":      "5TJX",  # DNA gyrase B
    "VRE":       "1MWS",  # PBP5
    "NGono":     "5XFT",  # PBP2 / penA
}


def _card_primary_targets() -> dict[str, dict[str, str]]:
    """Build pathogen → {pdb, target_name} from the curated CARD subset.

    The CARD subset is the authoritative list of targets that have
    curated clinical resistance mutations — so the PDB we hand the
    frontend is guaranteed to be one the resistance/harden endpoints
    can score. First PDB encountered per pathogen wins (insertion
    order = primary target first). Imported lazily to avoid a circular
    import (chem_resistance imports place_endpoint from this module)."""
    out: dict[str, dict[str, str]] = {}
    try:
        from . import chem_resistance as _cr
        by_pdb = (getattr(_cr, "_CARD", {}) or {}).get("by_pdb", {})
        for pdb, entry in by_pdb.items():
            pth = entry.get("_pathogen")
            if pth and pth not in out:
                out[pth] = {"pdb": pdb, "target_name": entry.get("_target", "")}
    except Exception as exc:  # noqa: BLE001
        log.warning("could not load CARD primary targets: %s", exc)
    return out

# Approximate pocket centers (Angstrom). When we can't compute these from
# the PDB at runtime, these literature-derived coords keep the ligand inside
# the binding cleft so the 3D viewer is visually meaningful.
PATHOGEN_POCKET_CENTER: dict[str, tuple[float, float, float]] = {
    "MRSA":      (33.0, 36.0, 60.0),
    "Mtb":       (10.0, -5.0, 12.0),
    "EColi-CRE": (-2.0, 13.0,  3.0),
    "KpneuCRE":  ( 8.0,  4.0,  0.0),
    "Abaum":     (15.0, 15.0, 15.0),
    "Paer":      ( 0.0,  0.0,  0.0),
    "VRE":       (20.0,  0.0, 30.0),
    "NGono":     (12.0, 15.0,  8.0),
}


@router.get("/pathogen/{code}/pocket")
async def pathogen_pocket(code: str) -> dict:
    pdb = PATHOGEN_TARGET_PDB.get(code)
    if pdb is None:
        raise HTTPException(404, f"unknown pathogen: {code}")
    cx, cy, cz = PATHOGEN_POCKET_CENTER.get(code, (0.0, 0.0, 0.0))
    return {
        "pathogen": code,
        "pdb_id": pdb,
        "pocket_center": {"x": cx, "y": cy, "z": cz},
        "pocket_radius_a": 8.0,
    }


@router.get("/pathogens")
async def list_pathogens() -> dict:
    """Return the 8 priority pathogens with full metadata.

    Each pathogen now carries `primary_pdb` + `target_name` — the
    CARD-backed structure the frontend should auto-load when this
    pathogen is selected, so picking a disease actually drives the
    3D viewer + resistance + harden against the right target (not
    a hard-coded MRSA PBP2a)."""
    pathogens = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
                 "Abaum", "Paer", "VRE", "NGono"]
    rt = registry.get("get_pathogen_resistome")
    card_targets = _card_primary_targets()
    out = []
    for p in pathogens:
        # CARD-backed target first, fall back to the static map.
        tgt = card_targets.get(p) or {}
        primary_pdb = tgt.get("pdb") or PATHOGEN_TARGET_PDB.get(p)
        target_name = tgt.get("target_name") or ""
        if rt is None:
            out.append({
                "code": p, "name": p, "resistome_count": 0,
                "primary_pdb": primary_pdb, "target_name": target_name,
            })
            continue
        rec = rt.call({"pathogen": p})
        result = rec.get("result") or {}
        out.append({
            "code": p,
            "name": result.get("full_name", p),
            "intrinsic_features": result.get("intrinsic_features", []),
            "resistome_count": len(result.get("resistome", [])),
            "first_line_count": len(result.get("first_line_therapy", [])),
            "common_syndromes": result.get("common_syndromes", []),
            "primary_pdb": primary_pdb,
            "target_name": target_name,
        })
    return {"pathogens": out}


# ===========================================================================
# CHEMISTRY DASHBOARD — properties, SMARTS search, library CRUD
# ===========================================================================
# These power the Chemistry container's full-stack mini-app:
#   GET  /molecule/properties?smiles=...      — Lipinski Ro5 + QED + descriptors
#   POST /molecule/smarts-match {smiles, smarts} — SMARTS pattern → matched atoms
#   GET  /library/molecules                    — list saved molecules (persistent)
#   POST /library/molecules                    — save current candidate to library
#   DELETE /library/molecules/{id}             — remove from library
#   GET  /library/tags                         — distinct tags for filter chips


class MoleculeProperties(BaseModel):
    smiles: str
    canonical_smiles: str
    inchi_key: str
    n_atoms: int
    n_heavy_atoms: int
    n_bonds: int
    n_rings: int
    n_aromatic_rings: int
    n_rotatable_bonds: int
    # Lipinski's Rule of 5
    molecular_weight: float
    logp: float
    h_bond_donors: int
    h_bond_acceptors: int
    lipinski_violations: int
    lipinski_pass: bool
    # Drug-likeness
    qed: float                          # 0-1, 0.67+ is "drug-like"
    sa_score: float                     # 1-10, lower = easier to synthesize
    tpsa: float                         # topological polar surface area, Å²
    fsp3: float                         # fraction sp3 (saturation, 0-1)
    formal_charge: int
    # Atom-level breakdown
    element_counts: dict[str, int]
    # Veber rules (orally bioavailable)
    veber_pass: bool
    # Drug class hint (if matches a SMARTS template)
    detected_classes: list[str]


@router.get("/molecule/properties", response_model=MoleculeProperties)
async def molecule_properties(smiles: str) -> MoleculeProperties:
    """Compute the full medchem property stack for a SMILES via RDKit.
    Returns Lipinski/Veber rules, QED, SA score, TPSA, fsp3, descriptors."""
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, Descriptors, Crippen, QED, rdMolDescriptors, Lipinski
    except ImportError:
        raise HTTPException(503, "RDKit not available")

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")

    canonical = Chem.MolToSmiles(mol, canonical=True)
    inchi_key = Chem.MolToInchiKey(mol) if Chem.MolToInchi(mol) else ""

    mw = float(Descriptors.MolWt(mol))
    logp = float(Crippen.MolLogP(mol))
    hbd = int(Lipinski.NumHDonors(mol))
    hba = int(Lipinski.NumHAcceptors(mol))
    rot_bonds = int(Lipinski.NumRotatableBonds(mol))
    tpsa = float(rdMolDescriptors.CalcTPSA(mol))
    fsp3 = float(rdMolDescriptors.CalcFractionCSP3(mol))
    qed_val = float(QED.qed(mol))

    # SA Score requires the contributed module — graceful fallback if missing
    sa_score = 0.0
    try:
        from rdkit.Chem import RDConfig
        import os as _os
        import sys as _sys
        sa_path = _os.path.join(RDConfig.RDContribDir, "SA_Score")
        if sa_path not in _sys.path:
            _sys.path.append(sa_path)
        import sascorer  # type: ignore[import]
        sa_score = float(sascorer.calculateScore(mol))
    except Exception:
        pass

    # Lipinski Ro5 — count violations
    violations = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    lipinski_pass = violations <= 1

    # Veber: rotatable bonds <= 10 AND TPSA <= 140
    veber_pass = rot_bonds <= 10 and tpsa <= 140

    # Element counts
    elements: dict[str, int] = {}
    for atom in mol.GetAtoms():
        sym = atom.GetSymbol()
        elements[sym] = elements.get(sym, 0) + 1

    # Drug-class hints via SMARTS
    DRUG_CLASS_SMARTS = {
        "β-lactam": "[#7]1[#6](=O)[#6]([#6]1)",
        "quinolone-core": "c1ccc2c(c1)c(=O)c(C(=O)O)cn2",
        "macrolide-large-ring": "[#6]1[#6][#6][#6][#6][#6][#6][#6][#6][#6][#6][#6][#6][#6]1",
        "aminoglycoside": "C1OCC(N)C(O)C1O",
        "peptide-bond": "[NX3][CX3](=O)[CX3]",
        "tetracycline-core": "c1ccc2c(c1)C(=O)c1c(O)cccc1C2=O",
        "sulfonamide": "[#16](=O)(=O)[#7]",
        "penicillin-thiazolidine": "[#6]1[#16][#6]([#6])[#7]2[#6](=O)[#6]12",
        "imidazole": "c1ncnc1",
        "fluoroquinolone-substruct": "c1cc2c(cc1F)c(=O)c(C(=O)O)cn2",
    }
    detected: list[str] = []
    for cls, smt in DRUG_CLASS_SMARTS.items():
        try:
            patt = Chem.MolFromSmarts(smt)
            if patt and mol.HasSubstructMatch(patt):
                detected.append(cls)
        except Exception:
            pass

    return MoleculeProperties(
        smiles=smiles,
        canonical_smiles=canonical,
        inchi_key=inchi_key,
        n_atoms=mol.GetNumAtoms(),
        n_heavy_atoms=mol.GetNumHeavyAtoms(),
        n_bonds=mol.GetNumBonds(),
        n_rings=int(rdMolDescriptors.CalcNumRings(mol)),
        n_aromatic_rings=int(rdMolDescriptors.CalcNumAromaticRings(mol)),
        n_rotatable_bonds=rot_bonds,
        molecular_weight=mw,
        logp=logp,
        h_bond_donors=hbd,
        h_bond_acceptors=hba,
        lipinski_violations=violations,
        lipinski_pass=lipinski_pass,
        qed=qed_val,
        sa_score=sa_score,
        tpsa=tpsa,
        fsp3=fsp3,
        formal_charge=Chem.GetFormalCharge(mol),
        element_counts=elements,
        veber_pass=veber_pass,
        detected_classes=detected,
    )


class SMARTSMatchRequest(BaseModel):
    smiles: str
    smarts: str


class SMARTSMatch(BaseModel):
    atom_indices: list[int]
    bond_indices: list[int]


class SMARTSMatchResponse(BaseModel):
    smiles: str
    smarts: str
    n_matches: int
    matches: list[SMARTSMatch]
    valid_smarts: bool
    error: str = ""


@router.post("/molecule/smarts-match", response_model=SMARTSMatchResponse)
async def molecule_smarts_match(req: SMARTSMatchRequest) -> SMARTSMatchResponse:
    """Find all SMARTS pattern matches in a SMILES. Returns matched atom +
    bond indices for highlighting in the 2D viewer."""
    try:
        from rdkit import Chem
    except ImportError:
        raise HTTPException(503, "RDKit not available")

    mol = Chem.MolFromSmiles(req.smiles)
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {req.smiles}")

    pat = Chem.MolFromSmarts(req.smarts)
    if pat is None:
        return SMARTSMatchResponse(
            smiles=req.smiles, smarts=req.smarts,
            n_matches=0, matches=[], valid_smarts=False,
            error=f"invalid SMARTS: {req.smarts}",
        )

    raw_matches = mol.GetSubstructMatches(pat, useChirality=False)
    out: list[SMARTSMatch] = []
    for m in raw_matches:
        # Get bond indices touching ONLY pairs within the match
        bonds: list[int] = []
        atom_set = set(m)
        for b in mol.GetBonds():
            if b.GetBeginAtomIdx() in atom_set and b.GetEndAtomIdx() in atom_set:
                bonds.append(b.GetIdx())
        out.append(SMARTSMatch(atom_indices=list(m), bond_indices=bonds))

    return SMARTSMatchResponse(
        smiles=req.smiles, smarts=req.smarts,
        n_matches=len(out), matches=out, valid_smarts=True,
    )


# --- Library CRUD ----------------------------------------------------------
# Persists user-saved molecules in a SQLite table. Survives restarts.
# Stored in the same DB the playground store uses for sessions.
import sqlite3 as _sql_lib  # noqa: E402
import json as _json_lib  # noqa: E402
import time as _time_lib  # noqa: E402
from pathlib import Path as _PathLib  # noqa: E402

_LIB_DB = _PathLib("workspace/data/molecule_library.db")


def _lib_conn() -> _sql_lib.Connection:
    _LIB_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = _sql_lib.connect(str(_LIB_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS library_molecules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            smiles TEXT NOT NULL,
            canonical_smiles TEXT NOT NULL,
            inchi_key TEXT,
            name TEXT,
            tags TEXT,
            note TEXT,
            qed REAL,
            mw REAL,
            logp REAL,
            tpsa REAL,
            n_heavy_atoms INTEGER,
            lipinski_pass INTEGER,
            created_at REAL,
            updated_at REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lib_inchi ON library_molecules(inchi_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lib_canon ON library_molecules(canonical_smiles)")
    return conn


class LibraryEntry(BaseModel):
    id: int
    smiles: str
    canonical_smiles: str
    inchi_key: str = ""
    name: str = ""
    tags: list[str] = []
    note: str = ""
    qed: float = 0.0
    mw: float = 0.0
    logp: float = 0.0
    tpsa: float = 0.0
    n_heavy_atoms: int = 0
    lipinski_pass: bool = False
    created_at: float = 0.0
    updated_at: float = 0.0


class LibrarySaveRequest(BaseModel):
    smiles: str
    name: str = ""
    tags: list[str] = []
    note: str = ""


@router.get("/library/molecules")
async def library_list(
    tag: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """List saved molecules. Filter by tag or substring search across name/note/SMILES."""
    conn = _lib_conn()
    sql = "SELECT id, smiles, canonical_smiles, inchi_key, name, tags, note, qed, mw, logp, tpsa, n_heavy_atoms, lipinski_pass, created_at, updated_at FROM library_molecules"
    params: list = []
    where: list[str] = []
    if tag:
        where.append("tags LIKE ?")
        params.append(f"%\"{tag}\"%")
    if q:
        where.append("(name LIKE ? OR note LIKE ? OR smiles LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    out: list[LibraryEntry] = []
    for r in rows:
        try:
            tags_list = _json_lib.loads(r[5] or "[]")
        except Exception:
            tags_list = []
        out.append(LibraryEntry(
            id=r[0], smiles=r[1], canonical_smiles=r[2], inchi_key=r[3] or "",
            name=r[4] or "", tags=tags_list, note=r[6] or "",
            qed=r[7] or 0.0, mw=r[8] or 0.0, logp=r[9] or 0.0, tpsa=r[10] or 0.0,
            n_heavy_atoms=r[11] or 0, lipinski_pass=bool(r[12]),
            created_at=r[13] or 0.0, updated_at=r[14] or 0.0,
        ))
    conn.close()
    return {"entries": [e.model_dump() for e in out], "total": len(out)}


@router.post("/library/molecules")
async def library_save(req: LibrarySaveRequest) -> dict:
    """Save a molecule to the persistent library. Auto-computes properties.
    Idempotent on canonical SMILES — duplicates update name/tags/note."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Crippen, QED, rdMolDescriptors, Lipinski
    except ImportError:
        raise HTTPException(503, "RDKit not available")
    mol = Chem.MolFromSmiles(req.smiles)
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {req.smiles}")
    canonical = Chem.MolToSmiles(mol, canonical=True)
    inchi = Chem.MolToInchiKey(mol) if Chem.MolToInchi(mol) else ""
    mw = float(Descriptors.MolWt(mol))
    logp = float(Crippen.MolLogP(mol))
    tpsa = float(rdMolDescriptors.CalcTPSA(mol))
    qed_val = float(QED.qed(mol))
    hbd = int(Lipinski.NumHDonors(mol))
    hba = int(Lipinski.NumHAcceptors(mol))
    violations = sum([mw > 500, logp > 5, hbd > 5, hba > 10])

    now = _time_lib.time()
    tags_json = _json_lib.dumps(req.tags)
    conn = _lib_conn()
    # Upsert by canonical
    existing = conn.execute(
        "SELECT id FROM library_molecules WHERE canonical_smiles=? LIMIT 1",
        (canonical,),
    ).fetchone()
    if existing:
        conn.execute("""
            UPDATE library_molecules
            SET name=?, tags=?, note=?, updated_at=?,
                qed=?, mw=?, logp=?, tpsa=?, n_heavy_atoms=?, lipinski_pass=?
            WHERE id=?
        """, (
            req.name, tags_json, req.note, now,
            qed_val, mw, logp, tpsa, mol.GetNumHeavyAtoms(),
            1 if violations <= 1 else 0,
            existing[0],
        ))
        new_id = existing[0]
        action = "updated"
    else:
        cur = conn.execute("""
            INSERT INTO library_molecules
            (smiles, canonical_smiles, inchi_key, name, tags, note, qed, mw, logp, tpsa,
             n_heavy_atoms, lipinski_pass, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            req.smiles, canonical, inchi, req.name, tags_json, req.note,
            qed_val, mw, logp, tpsa, mol.GetNumHeavyAtoms(),
            1 if violations <= 1 else 0,
            now, now,
        ))
        new_id = cur.lastrowid
        action = "created"
    conn.commit()
    conn.close()
    return {"id": new_id, "action": action, "canonical_smiles": canonical}


@router.delete("/library/molecules/{mol_id}")
async def library_delete(mol_id: int) -> dict:
    conn = _lib_conn()
    conn.execute("DELETE FROM library_molecules WHERE id=?", (mol_id,))
    conn.commit()
    conn.close()
    return {"deleted": mol_id}


@router.get("/library/tags")
async def library_tags() -> dict:
    """Distinct tags across the library, with counts."""
    conn = _lib_conn()
    rows = conn.execute("SELECT tags FROM library_molecules").fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        try:
            for t in _json_lib.loads(r[0] or "[]"):
                counts[t] = counts.get(t, 0) + 1
        except Exception:
            pass
    sorted_tags = sorted(counts.items(), key=lambda x: -x[1])
    conn.close()
    return {"tags": [{"tag": t, "count": c} for t, c in sorted_tags]}


# ===========================================================================
# DRUG CORPUS — 387 enriched named-drug examples + canonical antibiotics
# ===========================================================================

@router.get("/drugs")
async def list_drugs(
    q: Optional[str] = None,
    task: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Search/list the 387-drug enriched corpus.

    Each row carries:
       drug, prompt (truncated), response (full mechanism/spectrum/etc.),
       task (one of drug_pathogen_reasoning, drug_mechanism_deep_dive,
       counterfactual_design, resistance_mechanism_explanation, ...).

    Query params:
       q     — substring match in drug name OR prompt OR response
       task  — exact task slug filter
       limit — return at most N rows (default 50)
    """
    rows = _load_pharma_ground()
    needle = (q or "").lower().strip()
    out: list[dict] = []
    seen_drugs: set[str] = set()
    for r in rows:
        if task and r.get("task", "") != task:
            continue
        if needle:
            hay = (r.get("drug","") + r.get("prompt","") + r.get("response","")).lower()
            if needle not in hay:
                continue
        # Dedup by drug name — return ONE row per drug (the first hit)
        d = (r.get("drug") or "").strip()
        if not d:
            continue
        if d.lower() in seen_drugs:
            continue
        seen_drugs.add(d.lower())
        out.append({
            "drug": d,
            "task": r.get("task", ""),
            "preview": (r.get("response") or "")[:280].replace("\n", " "),
        })
        if len(out) >= limit:
            break
    return {"total": len(out), "drugs": out}


@router.get("/drugs/{name}")
async def drug_profile(name: str) -> dict:
    """Full multi-task profile for a single drug.
    Returns ALL task-specific responses (mechanism / spectrum / SAR /
    resistance / etc.) for that drug from the enriched corpus."""
    rows = _load_pharma_ground()
    needle = name.lower().strip()
    profile: dict[str, list[dict]] = {}
    for r in rows:
        d = (r.get("drug") or "").lower().strip()
        if d != needle:
            continue
        t = r.get("task", "unknown")
        profile.setdefault(t, []).append({
            "prompt": r.get("prompt", ""),
            "response": r.get("response", ""),
        })
    if not profile:
        raise HTTPException(404, f"drug not found: {name}")
    return {
        "drug": name,
        "tasks_available": sorted(profile.keys()),
        "n_entries": sum(len(v) for v in profile.values()),
        "entries": profile,
    }


@router.get("/antibiotics")
async def list_antibiotics(
    q: Optional[str] = None,
    pathogen: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """List known antibiotics from the canonical parquet
    (data/processed/known-antibiotics-canonical.parquet).
    Each row: name, smiles, drug_class, target_pathogens (list-of-str)."""
    p = _WORKSPACE.parent / "data" / "processed" / "known-antibiotics-canonical.parquet"
    if not p.exists():
        return {"total": 0, "antibiotics": [], "error": "corpus not found"}
    try:
        import pandas as pd  # type: ignore[import]
    except ImportError:
        raise HTTPException(503, "pandas not available")
    try:
        df = pd.read_parquet(p)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"parquet read failed: {exc}")
    needle = (q or "").lower().strip()
    out: list[dict] = []
    for _, row in df.iterrows():
        d = row.to_dict()
        name = str(d.get("name") or d.get("drug") or "").strip()
        if not name:
            continue
        smi = str(d.get("smiles") or "").strip()
        cls = str(d.get("drug_class") or d.get("class") or "").strip()
        targets_field = d.get("target_pathogens", d.get("pathogens", ""))
        if isinstance(targets_field, list):
            targets = [str(x) for x in targets_field]
        elif isinstance(targets_field, str):
            targets = [t.strip() for t in targets_field.split(",") if t.strip()]
        else:
            targets = []
        if needle:
            hay = (name + " " + cls + " " + " ".join(targets)).lower()
            if needle not in hay:
                continue
        if pathogen and pathogen.lower() not in [t.lower() for t in targets]:
            continue
        out.append({
            "name": name,
            "smiles": smi,
            "drug_class": cls,
            "target_pathogens": targets,
        })
        if len(out) >= limit:
            break
    return {"total": len(out), "antibiotics": out}


# ===========================================================================
# TOXICITY — QSAR-rule predictions (no model, pure RDKit + literature thresholds)
# ===========================================================================

class ToxicityProfile(BaseModel):
    smiles: str
    canonical_smiles: str
    # hERG potassium-channel blockade prediction (cardiotoxicity proxy)
    herg_risk: str           # "low" | "medium" | "high"
    herg_score: float        # 0-1 risk
    herg_rationale: str
    # Hepatotoxicity proxy
    hepatotox_risk: str
    hepatotox_score: float
    hepatotox_rationale: str
    # Mutagenicity (Ames test) proxy via toxicophore SMARTS
    ames_risk: str
    ames_score: float
    ames_rationale: str
    # Skin sensitization
    skin_sens_risk: str
    skin_sens_rationale: str
    # Overall ADMET-Tox composite (for ranking)
    overall_safety_score: float   # 1.0 = clean, 0.0 = unsafe


@router.get("/molecule/toxicity", response_model=ToxicityProfile)
async def molecule_toxicity(smiles: str) -> ToxicityProfile:
    """QSAR-rule based toxicity prediction. Uses literature toxicophores
    and RDKit physicochemical thresholds. Not a substitute for actual
    DeepTox/eToxPred models, but reliable for early-stage triage."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Crippen, rdMolDescriptors
    except ImportError:
        raise HTTPException(503, "RDKit not available")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")

    canonical = Chem.MolToSmiles(mol, canonical=True)
    mw = float(Descriptors.MolWt(mol))
    logp = float(Crippen.MolLogP(mol))
    tpsa = float(rdMolDescriptors.CalcTPSA(mol))
    n_aromatic_rings = int(rdMolDescriptors.CalcNumAromaticRings(mol))
    n_basic_n = sum(
        1 for atom in mol.GetAtoms()
        if atom.GetSymbol() == "N" and atom.GetTotalNumHs() > 0
        and not atom.GetIsAromatic() and atom.GetFormalCharge() <= 0
    )

    # ─── hERG risk: high logP + basic N + aromatic rings → blocker
    # Aronov 2005, Cavalli 2002 thresholds
    herg_score = 0.0
    herg_reasons: list[str] = []
    if logp > 3.5:
        herg_score += 0.35
        herg_reasons.append(f"high logP ({logp:.2f})")
    if n_basic_n >= 1:
        herg_score += 0.30
        herg_reasons.append(f"basic N count {n_basic_n}")
    if n_aromatic_rings >= 2:
        herg_score += 0.20
        herg_reasons.append(f"{n_aromatic_rings} aromatic rings")
    if mw > 350 and logp > 3:
        herg_score += 0.15
        herg_reasons.append("MW>350 + logP>3")
    herg_score = min(1.0, herg_score)
    herg_risk = "high" if herg_score >= 0.6 else "medium" if herg_score >= 0.3 else "low"

    # ─── Hepatotoxicity: high logP + reactive groups
    hepa_score = 0.0
    hepa_reasons: list[str] = []
    HEPA_TOXICOPHORES = {
        "thiophene":     "c1ccsc1",
        "furan":         "c1ccoc1",
        "p-aminophenol": "Nc1ccc(O)cc1",
        "anilide":       "Nc1ccccc1",
    }
    for n, smt in HEPA_TOXICOPHORES.items():
        try:
            patt = Chem.MolFromSmarts(smt)
            if patt and mol.HasSubstructMatch(patt):
                hepa_score += 0.25
                hepa_reasons.append(n)
        except Exception:
            pass
    if logp > 5:
        hepa_score += 0.30
        hepa_reasons.append(f"very high logP ({logp:.2f})")
    elif logp > 3:
        hepa_score += 0.10
    hepa_score = min(1.0, hepa_score)
    hepa_risk = "high" if hepa_score >= 0.6 else "medium" if hepa_score >= 0.3 else "low"

    # ─── Mutagenicity (Ames): toxicophore-based (Kazius, McCarren)
    ames_score = 0.0
    ames_reasons: list[str] = []
    AMES_TOXICOPHORES = {
        "aromatic-nitro":       "c[N+](=O)[O-]",
        "aromatic-amine":       "c[NX3;H2]",
        "aliphatic-halide":     "[CX4][Cl,Br,I]",
        "epoxide":              "C1OC1",
        "aziridine":            "C1CN1",
        "michael-acceptor":     "[CX3]=[CX3][CX3]=[OX1]",
        "nitroso":              "[NX2]=[OX1]",
        "azide":                "[N-]=[N+]=N",
        "hydrazine":            "[NX3][NX3]",
        "peroxide":             "[OX2][OX2]",
    }
    for n, smt in AMES_TOXICOPHORES.items():
        try:
            patt = Chem.MolFromSmarts(smt)
            if patt and mol.HasSubstructMatch(patt):
                ames_score += 0.18
                ames_reasons.append(n)
        except Exception:
            pass
    ames_score = min(1.0, ames_score)
    ames_risk = "high" if ames_score >= 0.5 else "medium" if ames_score >= 0.2 else "low"

    # ─── Skin sensitization: reactive electrophiles
    skin_reasons: list[str] = []
    SKIN_TOXICOPHORES = ["[CX3](=O)[Cl,F]", "[#16](=O)(=O)[Cl]", "C=C[CX3](=O)"]
    for smt in SKIN_TOXICOPHORES:
        try:
            patt = Chem.MolFromSmarts(smt)
            if patt and mol.HasSubstructMatch(patt):
                skin_reasons.append(smt)
        except Exception:
            pass
    skin_risk = "high" if len(skin_reasons) >= 1 else "low"

    # ─── Composite safety
    overall = 1.0 - 0.4*herg_score - 0.3*hepa_score - 0.3*ames_score
    overall = max(0.0, min(1.0, overall))

    return ToxicityProfile(
        smiles=smiles, canonical_smiles=canonical,
        herg_risk=herg_risk, herg_score=round(herg_score, 3),
        herg_rationale=", ".join(herg_reasons) if herg_reasons else "no hERG-flagged features",
        hepatotox_risk=hepa_risk, hepatotox_score=round(hepa_score, 3),
        hepatotox_rationale=", ".join(hepa_reasons) if hepa_reasons else "no hepatotoxicity flags",
        ames_risk=ames_risk, ames_score=round(ames_score, 3),
        ames_rationale=", ".join(ames_reasons) if ames_reasons else "no Ames toxicophores",
        skin_sens_risk=skin_risk,
        skin_sens_rationale=", ".join(skin_reasons) if skin_reasons else "no electrophile flags",
        overall_safety_score=round(overall, 3),
    )


# ===========================================================================
# SIMILARITY — Tanimoto vs. canonical antibiotic corpus (real-time)
# ===========================================================================

class SimilarityRequest(BaseModel):
    smiles: str
    top_k: int = 8
    pathogen: Optional[str] = None     # filter corpus to drugs targeting this pathogen


class SimilarityHit(BaseModel):
    drug_name: str
    smiles: str
    drug_class: str
    target_pathogens: list[str]
    tanimoto: float
    common_atoms: int


class SimilarityResponse(BaseModel):
    smiles: str
    n_corpus: int
    top: list[SimilarityHit]


@router.post("/molecule/similarity", response_model=SimilarityResponse)
async def molecule_similarity(req: SimilarityRequest) -> SimilarityResponse:
    """Tanimoto similarity vs. known-antibiotics corpus.
    Returns top-K closest known drugs with their drug class + pathogen targets.
    Uses Morgan fingerprints (radius=2, 2048 bits) — the medchem standard."""
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, DataStructs
    except ImportError:
        raise HTTPException(503, "RDKit not available")
    try:
        import pandas as pd  # type: ignore[import]
    except ImportError:
        raise HTTPException(503, "pandas not available")
    p = _WORKSPACE.parent / "data" / "processed" / "known-antibiotics-canonical.parquet"
    if not p.exists():
        return SimilarityResponse(smiles=req.smiles, n_corpus=0, top=[])

    query_mol = Chem.MolFromSmiles(req.smiles)
    if query_mol is None:
        raise HTTPException(422, f"unparseable SMILES: {req.smiles}")
    qfp = AllChem.GetMorganFingerprintAsBitVect(query_mol, 2, nBits=2048)

    df = pd.read_parquet(p)
    hits: list[tuple[float, dict]] = []
    for _, row in df.iterrows():
        d = row.to_dict()
        smi = str(d.get("smiles") or "").strip()
        if not smi:
            continue
        try:
            cmol = Chem.MolFromSmiles(smi)
            if cmol is None:
                continue
            cfp = AllChem.GetMorganFingerprintAsBitVect(cmol, 2, nBits=2048)
            sim = float(DataStructs.TanimotoSimilarity(qfp, cfp))
        except Exception:
            continue
        targets_field = d.get("target_pathogens", d.get("pathogens", ""))
        if isinstance(targets_field, list):
            targets = [str(x) for x in targets_field]
        elif isinstance(targets_field, str):
            targets = [t.strip() for t in targets_field.split(",") if t.strip()]
        else:
            targets = []
        if req.pathogen and req.pathogen.lower() not in [t.lower() for t in targets]:
            continue
        # Approximate common atoms (heavy atoms in MCS would be better; this
        # is a quick proxy from match count)
        common = int(query_mol.GetNumHeavyAtoms() * sim)
        hits.append((sim, {
            "drug_name": str(d.get("name") or d.get("drug") or "?"),
            "smiles": smi,
            "drug_class": str(d.get("drug_class") or d.get("class") or ""),
            "target_pathogens": targets,
            "tanimoto": round(sim, 4),
            "common_atoms": common,
        }))
    hits.sort(key=lambda x: -x[0])
    top = [SimilarityHit(**h[1]) for h in hits[:req.top_k]]
    return SimilarityResponse(smiles=req.smiles, n_corpus=len(df), top=top)


# ===========================================================================
# SESSION TIMELINE — unified event log for the Live container
# ===========================================================================

@router.get("/sessions/{sid}/workflow")
async def session_workflow(sid: str) -> dict:
    """Return the derived workflow phase + per-phase evidence for a session.
    Used by the Agents container's WorkflowPhaseTracker.

    Phases:
      SCOPE       — user defines pathogen + constraints + criteria
      ANCHOR      — Designer queries resistome, picks scaffold class
      DESIGN      — Designer/Critic/Editor loop with reward feedback
      VALIDATE    — Top candidates run through 3D pose + resistance map
      STRESS_TEST — Adversarial Critic + red-team escape
      REPORT      — Final snapshot ready for export

    Phase derivation is heuristic from agent activity: looks at action_types
    and tool calls in the action log. The graph runner can also explicitly
    emit phase_transition events that override the heuristic.
    """
    from workspace.playground.store import get_store as _get_store
    store = _get_store()
    actions = store.list_actions(sid, limit=2000)
    mols = store.list_session_molecules(sid)

    # Collect per-phase evidence
    n_candidates = len(mols)
    n_score_actions = sum(1 for a in actions if (a.get("action_type") or "").lower() in ("score", "score_molecule"))
    n_resistome = sum(1 for a in actions if "resistome" in (a.get("action_type") or "").lower())
    n_pocket = sum(1 for a in actions if "pocket" in (a.get("action_type") or "").lower() or "place_in_pocket" in (a.get("message_text") or ""))
    n_resistance = sum(1 for a in actions if "resistance" in (a.get("action_type") or "").lower() or "vulnerability" in (a.get("message_text") or "").lower())
    n_red_team = sum(1 for a in actions if "red_team" in (a.get("action_type") or "").lower() or "escape" in (a.get("action_type") or "").lower())

    # Look for explicit phase_transition actions first
    explicit_transitions = [a for a in actions if (a.get("action_type") or "") == "phase_transition"]
    if explicit_transitions:
        latest = max(explicit_transitions, key=lambda a: a.get("ts", 0))
        # Convention: message_text = "from→to" or just the new phase
        msg = (latest.get("message_text") or "").strip()
        if "→" in msg:
            current_phase = msg.split("→", 1)[1].strip().split()[0]
        else:
            current_phase = msg.split()[0] if msg else "design"
    else:
        # Heuristic derivation
        if n_red_team > 0:
            current_phase = "stress_test"
        elif n_pocket > 0 or n_resistance > 0:
            current_phase = "validate"
        elif n_score_actions > 0:
            current_phase = "design"
        elif n_candidates > 0 or n_resistome > 0:
            current_phase = "anchor"
        else:
            current_phase = "scope"

    # Phase order
    PHASES = ["scope", "anchor", "design", "validate", "stress_test", "report"]
    cur_idx = PHASES.index(current_phase) if current_phase in PHASES else 0

    return {
        "session_id": sid,
        "current_phase": current_phase,
        "phases": [
            {
                "id": p,
                "label": p.replace("_", " ").upper(),
                "status": ("completed" if i < cur_idx else ("active" if i == cur_idx else "pending")),
                "tools_called": _phase_tool_count(p, actions),
                "evidence_count": _phase_evidence_count(p, actions, n_candidates, n_score_actions,
                                                        n_resistome, n_pocket, n_resistance, n_red_team),
            }
            for i, p in enumerate(PHASES)
        ],
        "counts": {
            "candidates": n_candidates,
            "score_actions": n_score_actions,
            "resistome_calls": n_resistome,
            "pocket_calls": n_pocket,
            "resistance_calls": n_resistance,
            "red_team_calls": n_red_team,
        },
        "transitions": [
            {
                "ts": a.get("ts"),
                "from_phase": (a.get("message_text") or "").split("→", 1)[0].strip() if "→" in (a.get("message_text") or "") else "",
                "to_phase": (a.get("message_text") or "").split("→", 1)[1].strip().split()[0] if "→" in (a.get("message_text") or "") else (a.get("message_text") or "").split()[0] if a.get("message_text") else "",
                "agent": a.get("agent_name", "system"),
            }
            for a in explicit_transitions
        ],
    }


def _phase_tool_count(phase: str, actions: list) -> int:
    PHASE_TOOLS = {
        "scope": [],
        "anchor": ["get_pathogen_resistome", "find_active_against_mdr", "find_similar_drugs"],
        "design": ["score_molecule", "edit_molecule", "transform_structure", "replace_smiles"],
        "validate": ["place_in_pocket", "predict_admet", "compare_molecules", "map_resistance_vulnerability"],
        "stress_test": ["predict_resistance_escape", "predict_resistance_escape_geometric"],
        "report": [],
    }
    tools = PHASE_TOOLS.get(phase, [])
    return sum(1 for a in actions if any(t in (a.get("action_type") or "") for t in tools))


def _phase_evidence_count(phase: str, actions: list, n_candidates: int, n_score: int,
                          n_resistome: int, n_pocket: int, n_resistance: int, n_red_team: int) -> int:
    return {
        "scope": 1 if n_candidates > 0 else 0,
        "anchor": n_resistome,
        "design": n_score,
        "validate": n_pocket + n_resistance,
        "stress_test": n_red_team,
        "report": 0,
    }.get(phase, 0)


@router.get("/sessions/{sid}/timeline")
async def session_timeline(sid: str, limit: int = 200) -> dict:
    """Unified timeline: molecule edits + score snapshots + agent actions
    for a session, sorted chronologically. Powers the Live container's
    SessionTraceCard."""
    from workspace.playground.store import get_store as _get_store
    store = _get_store()
    edits = store.list_edits(sid, limit=limit)
    actions = store.list_actions(sid, limit=limit)
    # Score snapshots — query directly since no list helper exists
    snaps: list[dict] = []
    try:
        rows = store._q(
            "SELECT s.* FROM score_snapshots s "
            "JOIN molecules m ON s.molecule_id = m.id "
            "WHERE m.session_id = ? ORDER BY s.ts DESC LIMIT ?",
            (sid, limit),
        ).fetchall()
        for r in rows:
            d = dict(r)
            try:
                d["components"] = _json_lib.loads(d.get("components") or "{}")
            except Exception:
                d["components"] = {}
            snaps.append(d)
    except Exception:
        snaps = []

    timeline = []
    for e in edits:
        actor = e.get("created_by") or e.get("actor") or "user"
        op = e.get("op") or e.get("op_kind") or ""
        atom_idx = e.get("target_atom_idx", e.get("atom_idx"))
        timeline.append({
            "ts": e.get("ts"), "kind": "edit", "actor": str(actor),
            "summary": f"{op}{' @ atom ' + str(atom_idx) if atom_idx is not None else ''}".strip(),
            "result_smiles": e.get("result_smiles", ""), "raw": e,
        })
    for s in snaps:
        composite = s.get("composite") or 0.0
        timeline.append({
            "ts": s.get("ts"), "kind": "score", "actor": s.get("model_used") or "scorer",
            "summary": f"composite = {composite:.3f}", "raw": s,
        })
    for a in actions:
        ag_name = a.get("agent_name") or a.get("actor") or "agent"
        a_type = a.get("action_type") or a.get("op") or ""
        msg = a.get("message_text") or ""
        timeline.append({
            "ts": a.get("ts"), "kind": "agent", "actor": str(ag_name),
            "summary": (msg[:120] if msg else a_type) or a_type,
            "raw": a,
        })
    timeline.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return {"session": sid, "n_events": len(timeline), "timeline": timeline[:limit]}


# ===========================================================================
# AGENT ROSTER — per-agent state + recent actions for the Agents container
# ===========================================================================

@router.get("/sessions/{sid}/agent-actions")
async def session_agent_actions(
    sid: str,
    agent: Optional[str] = None,
    action_type: Optional[str] = None,
    q: Optional[str] = None,
    since_ts: float = 0.0,
    limit: int = 200,
) -> dict:
    """Filterable agent action log for the session.

    Query params:
      agent       — filter by agent_name (designer/critic/editor/strategist/orchestrator)
      action_type — filter by action_type (propose/critique/edit/decide/...)
      q           — substring search across message_text
      since_ts    — only actions after this unix timestamp
      limit       — max rows (default 200)

    Each row: id, ts, agent_name, action_type, target_molecule_id,
    target_atom_idx, message_text, confidence, references (parsed json)."""
    from workspace.playground.store import get_store as _get_store
    store = _get_store()
    actions = store.list_actions(sid, since_ts=since_ts, limit=limit * 2)  # over-fetch then filter
    needle = (q or "").lower().strip()
    filtered: list[dict] = []
    for a in actions:
        if agent and (a.get("agent_name") or "").lower() != agent.lower():
            continue
        if action_type and (a.get("action_type") or "").lower() != action_type.lower():
            continue
        if needle:
            hay = (a.get("message_text") or "").lower()
            if needle not in hay:
                continue
        # Parse references_json once
        try:
            refs = _json_lib.loads(a.get("references_json") or a.get("references") or "{}")
        except Exception:
            refs = {}
        filtered.append({
            "id": a.get("id"),
            "ts": a.get("ts"),
            "agent_name": a.get("agent_name") or "",
            "action_type": a.get("action_type") or "",
            "target_molecule_id": a.get("target_molecule_id"),
            "target_atom_idx": a.get("target_atom_idx"),
            "message_text": a.get("message_text") or "",
            "confidence": a.get("confidence") or 0.0,
            "references": refs,
        })
        if len(filtered) >= limit:
            break
    # Distinct values for chip filters
    distinct_agents = sorted({(a.get("agent_name") or "").lower() for a in actions if a.get("agent_name")})
    distinct_types = sorted({(a.get("action_type") or "").lower() for a in actions if a.get("action_type")})
    return {
        "session": sid,
        "n": len(filtered),
        "actions": filtered,
        "distinct_agents": [a for a in distinct_agents if a],
        "distinct_action_types": [t for t in distinct_types if t],
    }


@router.get("/sessions/{sid}/agent-metrics")
async def session_agent_metrics(sid: str) -> dict:
    """Per-agent performance KPIs:
       - n_actions
       - actions_per_hour (over span of session)
       - avg_confidence
       - last_ts
       - action_type breakdown
       - distinct_target_molecules touched
    """
    from workspace.playground.store import get_store as _get_store
    store = _get_store()
    actions = store.list_actions(sid, limit=5000)
    if not actions:
        return {"session": sid, "agents": [], "total_actions": 0, "duration_h": 0.0}
    ts_min = min((a.get("ts") or 0) for a in actions)
    ts_max = max((a.get("ts") or 0) for a in actions)
    span_hours = max(1e-6, (ts_max - ts_min) / 3600.0)
    AGENTS = ["designer", "critic", "editor", "strategist", "orchestrator"]
    metrics = []
    for ag in AGENTS:
        ag_acts = [a for a in actions if (a.get("agent_name") or "").lower() == ag]
        if not ag_acts:
            metrics.append({
                "agent": ag, "n_actions": 0, "actions_per_hour": 0.0,
                "avg_confidence": 0.0, "last_ts": None,
                "action_type_breakdown": {}, "n_distinct_molecules": 0,
            })
            continue
        confs = [a.get("confidence") or 0.0 for a in ag_acts if a.get("confidence")]
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        type_breakdown: dict[str, int] = {}
        for a in ag_acts:
            t = a.get("action_type") or "unknown"
            type_breakdown[t] = type_breakdown.get(t, 0) + 1
        mols = {a.get("target_molecule_id") for a in ag_acts if a.get("target_molecule_id")}
        metrics.append({
            "agent": ag,
            "n_actions": len(ag_acts),
            "actions_per_hour": round(len(ag_acts) / span_hours, 2),
            "avg_confidence": round(avg_conf, 3),
            "last_ts": ag_acts[-1].get("ts"),
            "action_type_breakdown": type_breakdown,
            "n_distinct_molecules": len(mols),
        })
    return {
        "session": sid,
        "agents": metrics,
        "total_actions": len(actions),
        "duration_h": round(span_hours, 3),
    }


@router.get("/sessions/{sid}/agent-roster")
async def session_agent_roster(sid: str) -> dict:
    """Per-agent breakdown for the session.
    Returns each canonical agent (Designer/Critic/Editor/Strategist/Orchestrator)
    with action count, last-action timestamp, last summary, current state."""
    from workspace.playground.store import get_store as _get_store
    store = _get_store()
    actions = store.list_actions(sid, limit=500)
    AGENTS = ["designer", "critic", "editor", "strategist", "orchestrator"]
    roster = []
    for agent in AGENTS:
        ag_actions = [a for a in actions if (a.get("agent_name") or "").lower() == agent]
        # actions list is in chronological order (oldest first), so last entry is most recent
        last = ag_actions[-1] if ag_actions else None
        roster.append({
            "actor": agent,
            "n_actions": len(ag_actions),
            "last_ts": last.get("ts") if last else None,
            "last_op": (last.get("action_type") if last else "") or "",
            "last_summary": (last.get("message_text") if last else "")[:140] if last else "",
            "state": "active" if last else "idle",
        })
    return {"session": sid, "roster": roster, "total_actions": len(actions)}


# ---------------------------------------------------------------------------
# Live agent activity (in-memory, fast) — drives the redesigned Agents
# container's per-agent KPIs + timeline sparklines + flow graph.
# Powered by workspace.api.agent_activity which is the single tap point
# for "an agent did something in this session" across the orchestrator,
# workflows, harden, and design paths.
# ---------------------------------------------------------------------------

@router.get("/sessions/{sid}/agent-live/recent")
async def session_agent_live_recent(sid: str, limit: int = 200) -> dict:
    """Fast recent actions feed — no DB roundtrip, in-memory ring."""
    from . import agent_activity
    return {"session": sid, "actions": agent_activity.recent(sid, limit=limit)}


@router.get("/sessions/{sid}/agent-live/metrics")
async def session_agent_live_metrics(sid: str) -> dict:
    """Aggregate per-agent KPIs — n_actions, avg latency, ok_rate,
    avg_confidence, action_type breakdown, last action."""
    from . import agent_activity
    return agent_activity.metrics(sid)


@router.get("/sessions/{sid}/agent-live/timeline")
async def session_agent_live_timeline(sid: str, bucket_s: float = 5.0) -> dict:
    """Per-agent time-bucketed action counts — drives the sparklines."""
    from . import agent_activity
    return agent_activity.timeline(sid, bucket_s=bucket_s)


# ── Champions ───────────────────────────────────────────────────────

@router.get("/champion/{pathogen}")
async def champion_get(pathogen: str) -> dict:
    from . import champions
    rec = champions.get(pathogen)
    return {"pathogen": pathogen.upper(), "champion": rec}


@router.get("/champions")
async def champions_all() -> dict:
    from . import champions
    return {"champions": champions.all_champions()}


class ChampionProposeRequest(BaseModel):
    pathogen: str
    smiles: str
    composite: Optional[float] = None
    robustness: Optional[float] = None
    fitness: Optional[float] = None
    scores: Optional[dict[str, float]] = None
    session_id: str = ""
    rationale: str = ""
    score_axis: str = "fitness"


@router.post("/champion/propose")
async def champion_propose(req: ChampionProposeRequest) -> dict:
    from . import champions
    return champions.propose(
        req.pathogen, req.smiles,
        composite=req.composite, robustness=req.robustness,
        fitness=req.fitness, scores=req.scores,
        session_id=req.session_id, rationale=req.rationale,
        score_axis=req.score_axis,
    )


class ChampionCompareRequest(BaseModel):
    pathogen: str
    smiles: str
    composite: Optional[float] = None
    robustness: Optional[float] = None
    scores: Optional[dict[str, float]] = None


@router.post("/champion/compare")
async def champion_compare(req: ChampionCompareRequest) -> dict:
    from . import champions
    return champions.compare(
        req.pathogen, req.smiles,
        composite=req.composite, robustness=req.robustness, scores=req.scores,
    )


@router.get("/sessions/{sid}/agent-live/handoffs")
async def session_agent_live_handoffs(sid: str) -> dict:
    """Directed edges between agents — drives the handoff graph viz."""
    from . import agent_activity
    return agent_activity.handoffs(sid)


@router.get("/sessions/{sid}/agent-live/errors")
async def session_agent_live_errors(sid: str, limit: int = 30) -> dict:
    """Error-status actions only — drives the alerts panel."""
    from . import agent_activity
    return agent_activity.errors(sid, limit=limit)


@router.get("/sessions/{sid}/agent-live/stream")
async def session_agent_live_stream(sid: str, request: Request):
    """SSE push stream — every record() lands on subscribers immediately.
    Replaces 1.5s polling with sub-100ms push, lower DB load."""
    import asyncio as _asyncio
    import json as _json
    from . import agent_activity
    from sse_starlette.sse import EventSourceResponse

    async def event_gen():
        q = agent_activity.subscribe(sid)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await _asyncio.wait_for(q.get(), timeout=25.0)
                    yield {"event": "action", "data": _json.dumps(payload)}
                except _asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            agent_activity.unsubscribe(sid, q)

    return EventSourceResponse(event_gen())

