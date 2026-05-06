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


@router.get("/chem/atom/{smiles_b64}/{atom_idx}", response_model=AtomContextResponse)
async def chem_atom_context(smiles_b64: str, atom_idx: int,
                             target: Optional[str] = None) -> AtomContextResponse:
    """SMILES is base64-urlsafe encoded to dodge URL-special-chars
    (ring bonds, slashes, etc.) — frontend wraps with btoa(smi)."""
    import base64
    try:
        smiles = base64.urlsafe_b64decode(smiles_b64.encode()).decode()
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
    import base64
    try:
        smiles = base64.urlsafe_b64decode(smiles_b64.encode()).decode()
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
    op: Literal["swap_element", "break_bond", "add_methyl_at"]
    atom_index: Optional[int] = None    # for swap_element / add_methyl_at
    bond_index: Optional[int] = None    # for break_bond
    new_element: Optional[str] = None   # for swap_element: C, N, O, F, S, Cl, Br


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
    rw = Chem.RWMol(mol)

    if req.op == "swap_element":
        if req.atom_index is None or req.new_element is None:
            raise HTTPException(422, "swap_element needs atom_index + new_element")
        if req.atom_index < 0 or req.atom_index >= rw.GetNumAtoms():
            raise HTTPException(422, f"atom_index out of range")
        ELEMENTS = {"C": 6, "N": 7, "O": 8, "F": 9, "S": 16, "Cl": 17, "Br": 35, "P": 15}
        if req.new_element not in ELEMENTS:
            raise HTTPException(422, f"unsupported element: {req.new_element}")
        rw.GetAtomWithIdx(req.atom_index).SetAtomicNum(ELEMENTS[req.new_element])
    elif req.op == "break_bond":
        if req.bond_index is None:
            raise HTTPException(422, "break_bond needs bond_index")
        if req.bond_index < 0 or req.bond_index >= rw.GetNumBonds():
            raise HTTPException(422, f"bond_index out of range")
        b = rw.GetBondWithIdx(req.bond_index)
        rw.RemoveBond(b.GetBeginAtomIdx(), b.GetEndAtomIdx())
    elif req.op == "add_methyl_at":
        if req.atom_index is None:
            raise HTTPException(422, "add_methyl_at needs atom_index")
        c = rw.AddAtom(Chem.Atom(6))
        rw.AddBond(req.atom_index, c, Chem.BondType.SINGLE)
    else:
        raise HTTPException(422, f"unknown op: {req.op}")

    # Sanitize — return error if violates valence
    try:
        Chem.SanitizeMol(rw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"chemistry violation: {exc}")

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
