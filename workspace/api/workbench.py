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
from typing import Any, AsyncIterator, Optional

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


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(404, "session not found")
    return state.model_dump(mode="json")


@router.post("/sessions/{session_id}/start", response_model=StartSessionResponse)
async def start_session(session_id: str) -> StartSessionResponse:
    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(404, "session not found")
    if state.terminated:
        return StartSessionResponse(session_id=session_id, status="already_terminated")

    queue = _get_or_create_queue(session_id)

    async def emit(ev: dict) -> None:
        await queue.put(ev)
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
