"""FastAPI router for chat + sandbox WebSocket.

Endpoints:
  POST /api/commands/list       — list registered slash commands (registry-driven)
  POST /api/chat                — handle a single user message via Harness
                                   (slash or free prompt)
  WS   /ws/session/{session_id} — bidirectional stream:
                                   client → {action: "run_cell", code: ...}
                                            {action: "scene_event", ...}
                                            {action: "chat", text: ...}
                                   server → {event: "cell.done", ...}
                                            {event: "scene.event", ...}
                                            {event: "chat.delta", ...}

This is the surface the React frontend consumes. The harness +
sandbox + skills_loader are all mounted here.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

log = logging.getLogger("workbench.api.chat")

router = APIRouter(tags=["chat"])


# ---------------------------------------------------------------------------
# In-memory session store (TODO: replace with DB-backed for multi-replica)
# ---------------------------------------------------------------------------

class _SessionRegistry:
    """Holds live SandboxSessions per session_id. Single-process for now."""

    def __init__(self):
        self._sessions: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, session_id: str, user_id: str = "anonymous"):
        async with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            from workspace.sandbox import SandboxSession
            sess = SandboxSession(session_id=session_id, user_id=user_id)
            self._sessions[session_id] = sess
            log.info("session %s: created (user=%s)", session_id, user_id)
            return sess

    async def stop(self, session_id: str) -> None:
        async with self._lock:
            sess = self._sessions.pop(session_id, None)
            if sess is None:
                return
            try:
                await sess.stop()
            except Exception as exc:  # noqa: BLE001
                log.warning("session %s stop failed: %s", session_id, exc)


registry = _SessionRegistry()


def _harness_singleton():
    global _HARNESS
    try:
        return _HARNESS  # type: ignore[name-defined]
    except NameError:
        from workspace.agents.harness import Harness
        _HARNESS = Harness()
        return _HARNESS


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Stable session identifier")
    user_id: str = Field("anonymous", description="User identifier")
    text: str = Field(..., description="User message (slash or free)")


class ChatResponse(BaseModel):
    session_id: str
    message_id: str
    text: str = ""
    error: str = ""
    artifact: Optional[dict] = None
    follow_ups: list[str] = []
    elapsed_ms: int = 0
    events: list[dict] = []


class CommandSpec(BaseModel):
    name: str
    description: str
    type: str
    argument_hint: str = ""
    aliases: list[str] = []
    requires_smiles: bool = False
    requires_target: bool = False
    category: str = "general"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/api/commands/list", response_model=list[CommandSpec])
async def list_commands() -> list[CommandSpec]:
    """List all registered slash commands. Frontend calls this on boot
    so the SlashPalette stays in sync with the Python CommandRegistry.
    """
    from workspace.agents.commands import get_registry

    reg = get_registry()
    out: list[CommandSpec] = []
    for cmd in reg.all():
        out.append(CommandSpec(
            name=cmd.name,
            description=cmd.description,
            type=cmd.type.value,
            argument_hint=cmd.argument_hint,
            aliases=cmd.aliases,
            requires_smiles=cmd.requires_smiles,
            requires_target=cmd.requires_target,
            category=_infer_category(cmd.name),
        ))
    return out


def _infer_category(name: str) -> str:
    name = name.lower()
    if name in ("help", "clear", "set-target", "branch"):
        return "system"
    if name in ("design",):
        return "design"
    if name in ("edit", "scaffold-hop", "hop"):
        return "edit"
    if name in ("score", "similar", "sim"):
        return "scoring"
    if name in ("explain",):
        return "knowledge"
    if name in ("resistance", "res"):
        return "amr"
    if name in ("run",):
        return "sandbox"
    return "general"


@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Handle one user message. Slash commands route through the
    CommandRegistry; free prompts route through the LLM (with skills
    context). Either way the response is a chat message + optional
    right-panel artifact.
    """
    sess = await registry.get_or_create(req.session_id, req.user_id)
    try:
        await sess.start()
    except Exception as exc:  # noqa: BLE001
        log.warning("session start (sandbox) failed: %s", exc)

    from workspace.agents.harness.orchestrator import SessionState

    state = SessionState(
        session_id=req.session_id,
        user_id=req.user_id,
        active_smiles=sess.meta.active_smiles,
        active_target=sess.meta.active_target,
        sandbox=sess,
        settings=sess.meta.settings,
    )

    harness = _harness_singleton()
    resp = await harness.handle_message(state, req.text)

    # Persist any side effects back to the session meta
    if resp.artifact and isinstance(resp.artifact, dict):
        action = resp.artifact.get("action") or resp.artifact.get("kind")
        if action == "set_target":
            sess.set_active_target(resp.artifact.get("target"))
        if action == "set_active_smiles":
            sess.set_active_smiles(resp.artifact.get("smiles"))

    return ChatResponse(
        session_id=resp.session_id,
        message_id=resp.message_id,
        text=resp.text,
        error=resp.error,
        artifact=resp.artifact,
        follow_ups=resp.follow_ups,
        elapsed_ms=resp.elapsed_ms,
        events=resp.events,
    )


@router.websocket("/ws/session/{session_id}")
async def session_ws(ws: WebSocket, session_id: str):
    """Bidirectional stream for a single session.

    Client → server JSON actions:
      {"action": "chat", "text": "..."}                — handle as POST /api/chat
      {"action": "run_cell", "code": "..."}            — sandbox cell
      {"action": "scene", "kind": "...", "payload": ...} — emit a SceneEvent
      {"action": "set_active_smiles", "smiles": "..."}
      {"action": "set_active_target", "target": "..."}

    Server → client JSON events:
      {"event": "chat.message", ...}
      {"event": "cell.done", ...}
      {"event": "scene.event", ...}
      {"event": "session.snapshot", ...}    — full state on connect
    """
    await ws.accept()
    user_id = ws.query_params.get("user", "anonymous")
    sess = await registry.get_or_create(session_id, user_id)
    try:
        await sess.start()
    except Exception as exc:  # noqa: BLE001
        log.warning("ws %s: sandbox start failed: %s", session_id, exc)

    # Send initial snapshot
    try:
        await ws.send_json({"event": "session.snapshot", "session": sess.to_dict()})
    except Exception:
        pass

    harness = _harness_singleton()

    try:
        while True:
            msg = await ws.receive_json()
            action = msg.get("action")
            if action == "chat":
                from workspace.agents.harness.orchestrator import SessionState
                state = SessionState(
                    session_id=session_id, user_id=user_id,
                    active_smiles=sess.meta.active_smiles,
                    active_target=sess.meta.active_target,
                    sandbox=sess,
                )
                resp = await harness.handle_message(state, msg.get("text", ""))
                await ws.send_json({
                    "event": "chat.message",
                    "text": resp.text,
                    "error": resp.error,
                    "artifact": resp.artifact,
                    "follow_ups": resp.follow_ups,
                    "elapsed_ms": resp.elapsed_ms,
                    "trace": resp.events,
                })
            elif action == "run_cell":
                cell = await sess.run_cell(msg.get("code", ""))
                await ws.send_json({"event": "cell.done", "cell": cell.to_dict()})
                # Replay scene events that the cell emitted
                for ev in cell.scene_events:
                    await ws.send_json({"event": "scene.event", "scene_event": ev})
            elif action == "scene":
                ev = sess.emit_scene(msg.get("kind", "update_object"),
                                     **msg.get("payload", {}))
                await ws.send_json({"event": "scene.event", "scene_event": ev.to_dict()})
            elif action == "set_active_smiles":
                sess.set_active_smiles(msg.get("smiles"))
                await ws.send_json({"event": "session.smiles", "smiles": msg.get("smiles")})
            elif action == "set_active_target":
                sess.set_active_target(msg.get("target"))
                await ws.send_json({"event": "session.target", "target": msg.get("target")})
            elif action == "ping":
                await ws.send_json({"event": "pong"})
            else:
                await ws.send_json({"event": "error", "msg": f"unknown action: {action}"})
    except WebSocketDisconnect:
        log.info("ws %s: disconnected", session_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("ws %s: error: %s", session_id, exc)
        try:
            await ws.send_json({"event": "error", "msg": str(exc)})
        except Exception:
            pass


@router.delete("/api/session/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    """Tear down a session (kill subprocess, snapshot scene)."""
    await registry.stop(session_id)
    return {"ok": True, "session_id": session_id}


@router.get("/api/session/{session_id}/state")
async def session_state(session_id: str) -> dict[str, Any]:
    """Read-only session snapshot for /reconnect / refresh."""
    if session_id not in registry._sessions:
        raise HTTPException(status_code=404, detail="session not found")
    sess = registry._sessions[session_id]
    return sess.to_dict()
