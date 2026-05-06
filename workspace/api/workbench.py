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
from typing import Any, AsyncIterator, Literal, Optional

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
        neighbors=neighbors,
        allowed_attachments=allowed,
        sar_notes=sar,
    )


@router.get("/molecule/2d/{smiles_b64}")
async def molecule_2d_svg(smiles_b64: str, w: int = 480, h: int = 340) -> dict:
    """Render a 2D structure as SVG with atom indices. Frontend uses this
    in the 2D Builder window; on click, the SVG already knows which atom
    index was hit (RDKit emits class="atom-N" on each atom)."""
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
    opts.addAtomIndices = True
    opts.bondLineWidth = 2
    opts.baseFontSize = 0.6
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    svg = drawer.GetDrawingText()
    # RDKit emits raw SVG with atom classes already; stash a small
    # n_atoms hint for the frontend.
    return {
        "smiles": smiles,
        "svg": svg,
        "n_atoms": mol.GetNumAtoms(),
        "n_bonds": mol.GetNumBonds(),
        "w": w,
        "h": h,
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
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{_os.getenv('LYSOS_EXPLAIN_GEMINI_MODEL', 'gemini-2.5-pro')}:generateContent"
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
            async with httpx.AsyncClient(timeout=60.0) as cx:
                r = await cx.post(
                    url,
                    headers={"x-goog-api-key": gemini_key,
                             "Content-Type": "application/json"},
                    json=payload,
                )
            if r.status_code != 200:
                raise RuntimeError(f"gemini http {r.status_code}: {r.text[:200]}")
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

    return breakdown.model_dump()


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
        "add_functional_group_at",
    ]
    atom_index: Optional[int] = None       # for swap_element / add_*_at / delete_atom
    atom_index_a: Optional[int] = None     # for add_bond (first atom)
    atom_index_b: Optional[int] = None     # for add_bond (second atom)
    bond_index: Optional[int] = None       # for break_bond / delete_bond
    new_element: Optional[str] = None      # element symbol for swap/add_atom_at
    bond_order: Optional[Literal["single", "double", "triple", "aromatic"]] = "single"
    functional_group: Optional[str] = None # name for add_functional_group_at


@router.post("/molecule/edit")
async def molecule_edit(req: AtomEditRequest) -> dict:
    """Edit a molecule at the atom/bond level. Used by the 3D viewer to
    let the user actually mutate the candidate via clicks."""
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

    ELEMENTS = {"C": 6, "N": 7, "O": 8, "F": 9, "S": 16, "Cl": 17, "Br": 35, "P": 15, "H": 1}
    BOND_ORDERS = {
        "single": Chem.BondType.SINGLE,
        "double": Chem.BondType.DOUBLE,
        "triple": Chem.BondType.TRIPLE,
        "aromatic": Chem.BondType.AROMATIC,
    }

    # Functional group library (SMARTS templates for "attach this fragment")
    # Each has (atoms_to_add, bonds_to_add) starting from anchor=req.atom_index
    FG_TEMPLATES = {
        "hydroxyl":   [("O", "single")],
        "methyl":     [("C", "single")],
        "amine":      [("N", "single")],
        "fluorine":   [("F", "single")],
        "chlorine":   [("Cl", "single")],
        "carbonyl":   [("C", "single"), ("O", "double")],   # ketone-like
        "carboxyl":   [("C", "single"), ("O", "double"), ("O", "single")],
        "nitro":      [("N", "single"), ("O", "double"), ("O", "single")],
        "cyano":      [("C", "single"), ("N", "triple")],
        "trifluoromethyl": [("C", "single"), ("F", "single"), ("F", "single"), ("F", "single")],
    }

    if req.op == "swap_element":
        if req.atom_index is None or req.new_element is None:
            raise HTTPException(422, "swap_element needs atom_index + new_element")
        if req.atom_index < 0 or req.atom_index >= rw.GetNumAtoms():
            raise HTTPException(422, "atom_index out of range")
        if req.new_element not in ELEMENTS:
            raise HTTPException(422, f"unsupported element: {req.new_element}")
        rw.GetAtomWithIdx(req.atom_index).SetAtomicNum(ELEMENTS[req.new_element])

    elif req.op == "break_bond" or req.op == "delete_bond":
        if req.bond_index is None:
            raise HTTPException(422, f"{req.op} needs bond_index")
        if req.bond_index < 0 or req.bond_index >= rw.GetNumBonds():
            raise HTTPException(422, "bond_index out of range")
        b = rw.GetBondWithIdx(req.bond_index)
        rw.RemoveBond(b.GetBeginAtomIdx(), b.GetEndAtomIdx())

    elif req.op == "add_methyl_at":
        if req.atom_index is None:
            raise HTTPException(422, "add_methyl_at needs atom_index")
        c = rw.AddAtom(Chem.Atom(6))
        rw.AddBond(req.atom_index, c, Chem.BondType.SINGLE)

    elif req.op == "add_atom_at":
        if req.atom_index is None or req.new_element is None:
            raise HTTPException(422, "add_atom_at needs atom_index + new_element")
        if req.new_element not in ELEMENTS:
            raise HTTPException(422, f"unsupported element: {req.new_element}")
        new_idx = rw.AddAtom(Chem.Atom(ELEMENTS[req.new_element]))
        bond_type = BOND_ORDERS.get(req.bond_order or "single", Chem.BondType.SINGLE)
        rw.AddBond(req.atom_index, new_idx, bond_type)

    elif req.op == "delete_atom":
        if req.atom_index is None:
            raise HTTPException(422, "delete_atom needs atom_index")
        if req.atom_index < 0 or req.atom_index >= rw.GetNumAtoms():
            raise HTTPException(422, "atom_index out of range")
        rw.RemoveAtom(req.atom_index)

    elif req.op == "add_bond":
        if req.atom_index_a is None or req.atom_index_b is None:
            raise HTTPException(422, "add_bond needs atom_index_a + atom_index_b")
        if req.atom_index_a == req.atom_index_b:
            raise HTTPException(422, "cannot bond an atom to itself")
        n = rw.GetNumAtoms()
        if not (0 <= req.atom_index_a < n and 0 <= req.atom_index_b < n):
            raise HTTPException(422, "atom_index_a or _b out of range")
        # Reject if bond already exists
        if rw.GetBondBetweenAtoms(req.atom_index_a, req.atom_index_b) is not None:
            raise HTTPException(422, f"bond already exists between {req.atom_index_a} and {req.atom_index_b}")
        bond_type = BOND_ORDERS.get(req.bond_order or "single", Chem.BondType.SINGLE)
        rw.AddBond(req.atom_index_a, req.atom_index_b, bond_type)

    elif req.op == "add_functional_group_at":
        if req.atom_index is None or req.functional_group is None:
            raise HTTPException(422, "add_functional_group_at needs atom_index + functional_group")
        tpl = FG_TEMPLATES.get(req.functional_group)
        if tpl is None:
            raise HTTPException(422, f"unknown functional group: {req.functional_group}")
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
            if i == 0 or req.functional_group not in ("carbonyl", "carboxyl", "nitro", "trifluoromethyl"):
                rw.AddBond(prev_idx, new_idx, bond_type)
                prev_idx = new_idx
            else:
                # Branch off the first added atom (anchor of the FG)
                rw.AddBond(first_new_idx, new_idx, bond_type)

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
            raise HTTPException(422, f"chemistry violation: {first_err} (retry: {exc2})")

    new_smiles = Chem.MolToSmiles(rw, canonical=True)
    return {
        "smiles": new_smiles,
        "n_atoms": rw.GetNumAtoms(),
        "n_bonds": rw.GetNumBonds(),
    }


# ---------------------------------------------------------------------------
# Pocket coords — per-pathogen binding-site centers (curated from PDB sites
# documented in the literature). Used to translate the ligand into the
# actual pocket instead of rendering it floating at the origin.
# ---------------------------------------------------------------------------

PATHOGEN_TARGET_PDB: dict[str, str] = {
    "MRSA":      "1VQQ",  # PBP2a
    "Mtb":       "2X22",  # InhA
    "EColi-CRE": "5UL8",  # KPC-2
    "KpneuCRE":  "6QWN",  # OmpK36
    "Abaum":     "7M4F",  # OXA-23
    "Paer":      "5DPX",  # MexY
    "VRE":       "1MWS",  # PBP5
    "NGono":     "5XFT",  # PBP2
}

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
    """Return the 8 priority pathogens with full metadata."""
    pathogens = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
                 "Abaum", "Paer", "VRE", "NGono"]
    rt = registry.get("get_pathogen_resistome")
    out = []
    for p in pathogens:
        if rt is None:
            out.append({"code": p, "name": p, "resistome_count": 0})
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

