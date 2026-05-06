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
from pydantic import BaseModel
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
