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
        from workspace.agents.llm import get_llm
        # Wire the LLM so free-form chat reaches the model. get_llm()
        # picks the backend per LYSOS_LLM_BACKEND (default "lysos" →
        # OpenAI-compatible endpoint at LYSOS_INFERENCE_URL, currently
        # the SSH-tunneled MI300X serve.py at localhost:7861/v1).
        # Falls back to MockEndpoint if the backend can't initialize so
        # the demo flow never breaks end-to-end.
        try:
            llm = get_llm()
        except Exception:  # noqa: BLE001
            llm = None
        _HARNESS = Harness(llm=llm)
        return _HARNESS


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Stable session identifier")
    user_id: str = Field("anonymous", description="User identifier")
    text: str = Field(..., description="User message (slash or free)")
    # ---- Agent message tagging / per-agent reply (W1++) ----
    reply_to_agent: Optional[str] = Field(
        None,
        description=(
            "If set, route this message to ONLY this specialist agent's "
            "prompt budget instead of the full Designer→Critic→Editor "
            "→Strategist debate. Values: designer / critic / editor / "
            "strategist / orchestrator."
        ),
    )
    parent_message_id: Optional[str] = Field(
        None,
        description="The agent message this reply is anchored to (for threading).",
    )
    thread_id: Optional[str] = Field(
        None,
        description=(
            "Logical thread id. New replies inherit the parent's thread_id; "
            "the main timeline uses thread_id=null."
        ),
    )
    # ---- Per-request context overrides ----
    # The chat is an AI surface — the user shouldn't have to repeat
    # "for MRSA" / "on c1ccccc1" in every slash command. The frontend
    # passes the currently-selected pathogen + loaded SMILES + PDB so
    # commands like `/explain` (no args) and `/score` (no args) can
    # resolve from this request's context.
    pathogen: Optional[str] = Field(
        None, description="Currently-selected pathogen — used as fallback for /explain, /design, etc."
    )
    smiles: Optional[str] = Field(
        None, description="Currently-loaded SMILES — used as fallback for /score, /harden, etc."
    )
    pdb_id: Optional[str] = Field(
        None, description="Currently-selected PDB target."
    )
    # ---- On-screen conversation context (for per-agent thread replies) ----
    # When the user clicks "reply to editor" on a chat bubble, they
    # expect the editor to remember what was on screen. The orchestrator
    # ledger may not have all the workflow narration events (those are
    # rendered client-side from SSE streams), so the frontend optionally
    # ships the last few visible chat messages to ground the reply.
    recent_messages: Optional[list[dict]] = Field(
        None,
        description=(
            "Optional last-N visible chat messages, oldest→newest. Each "
            "entry: {agent: str, content: str, ts?: float}. Used by the "
            "per-agent reply path to ground responses in on-screen context."
        ),
    )


class ChatResponse(BaseModel):
    session_id: str
    message_id: str
    text: str = ""
    error: str = ""
    artifact: Optional[dict] = None
    data: dict = {}                           # structured chat-card payload
    card_kind: str = ""                       # discriminator: score | candidate | sar_tree | …
    follow_ups: list[str] = []
    elapsed_ms: int = 0
    events: list[dict] = []
    # Threading echoes back so the frontend can attach the reply to the
    # right parent and visualize the side-thread.
    parent_message_id: Optional[str] = None
    thread_id: Optional[str] = None
    reply_agent: Optional[str] = None


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


# ---------------------------------------------------------------------------
# Auto-title — LLM summarization of a chat tab into a 3-5 word title.
# Frontend calls this debounced after activity. Reads the Orchestrator
# ledger (no separate transcript), so the same source of truth that
# powers /summary also names the tab.
# ---------------------------------------------------------------------------


class ChatTitleRequest(BaseModel):
    session_id: str
    user_id: str = "anonymous"
    # Optional: client-side recent message snapshot to use instead of the
    # server-side ledger (useful before any orch.ingest has happened).
    transcript: list[dict] = []


class ChatTitleResponse(BaseModel):
    session_id: str
    title: str = ""
    source: str = ""           # "llm" | "fallback" | "ledger"
    elapsed_ms: int = 0


_TITLE_PROMPT = (
    "You name chat tabs in a drug-design workbench. Read the conversation below "
    "and produce a SHORT label (3 to 6 words, max 50 chars) that captures the "
    "user's intent. No quotes, no trailing punctuation, no markdown — just the "
    "title text. Prefer the pathogen + scaffold/objective when present "
    "(e.g. 'Macrolide for MRSA', 'Score CCO', 'mecA mechanism brief').\n\n"
    "Conversation:\n{transcript}\n\nTitle:"
)


# ---------------------------------------------------------------------------
# Auto-title budget + backend selection. Keep external API usage bounded
# until the trained Lysos-Gemma is deployed and we can swap LYSOS_AUTOTITLE_
# BACKEND="lysos".
# ---------------------------------------------------------------------------

import os as _os
import time as _t

# env-tunable knobs (set in .env or shell):
#   LYSOS_AUTOTITLE_BACKEND        = "gemini" | "lysos" | "fallback"  (default gemini)
#   LYSOS_AUTOTITLE_GEMINI_MODEL   = Gemini model id                   (default 2.5-pro)
#   LYSOS_AUTOTITLE_THINKING_BUDGET= thinkingConfig.thinkingBudget     (default 512)
#   LYSOS_AUTOTITLE_MAX_PER_DAY    = int                               (default 200)
#   LYSOS_AUTOTITLE_MAX_PER_SESS   = int                               (default 8)
#   LYSOS_AUTOTITLE_MIN_GAP_SEC    = int                               (default 4)
#
# Why 2.5-pro by default and not flash:
#   We want dev-test parity with the deployed Lysos-Gemma (a Gemma 4
#   31B fine-tune). 2.5-pro is the closest off-the-shelf analog in
#   capability tier — behavior we observe during build is closer to
#   what the trained model will produce. Flash drops to a much smaller
#   class and would mask quality regressions during the swap.
_AUTOTITLE_BACKEND = _os.getenv("LYSOS_AUTOTITLE_BACKEND", "gemini").lower()
_AUTOTITLE_GEMINI_MODEL = _os.getenv("LYSOS_AUTOTITLE_GEMINI_MODEL", "gemini-2.5-pro")
_AUTOTITLE_THINKING_BUDGET = int(_os.getenv("LYSOS_AUTOTITLE_THINKING_BUDGET", "512"))
_AUTOTITLE_MAX_PER_DAY = int(_os.getenv("LYSOS_AUTOTITLE_MAX_PER_DAY", "200"))
_AUTOTITLE_MAX_PER_SESS = int(_os.getenv("LYSOS_AUTOTITLE_MAX_PER_SESS", "8"))
_AUTOTITLE_MIN_GAP_SEC = int(_os.getenv("LYSOS_AUTOTITLE_MIN_GAP_SEC", "4"))

# Process-local counters. Reset at midnight UTC (cheap heuristic — sufficient
# for a single-process FastAPI; replace with Redis when we go multi-replica).
_autotitle_usage: dict[str, Any] = {
    "day_key": "",
    "day_calls": 0,
    "by_session": {},   # session_id -> {"calls": int, "last_ts": float}
}


def _autotitle_check_budget(session_id: str) -> tuple[bool, str]:
    """Return (allowed, reason). Caller bails to fallback on (False, _)."""
    today = _t.strftime("%Y-%m-%d", _t.gmtime())
    if _autotitle_usage["day_key"] != today:
        _autotitle_usage["day_key"] = today
        _autotitle_usage["day_calls"] = 0
        _autotitle_usage["by_session"] = {}

    if _autotitle_usage["day_calls"] >= _AUTOTITLE_MAX_PER_DAY:
        return False, f"day_cap reached ({_AUTOTITLE_MAX_PER_DAY})"

    sess = _autotitle_usage["by_session"].setdefault(
        session_id, {"calls": 0, "last_ts": 0.0}
    )
    if sess["calls"] >= _AUTOTITLE_MAX_PER_SESS:
        return False, f"session_cap reached ({_AUTOTITLE_MAX_PER_SESS})"

    now = _t.time()
    if (now - sess["last_ts"]) < _AUTOTITLE_MIN_GAP_SEC:
        return False, f"min_gap_sec ({_AUTOTITLE_MIN_GAP_SEC}s)"
    return True, ""


def _autotitle_record(session_id: str, source: str, elapsed_ms: int) -> None:
    sess = _autotitle_usage["by_session"].setdefault(
        session_id, {"calls": 0, "last_ts": 0.0}
    )
    sess["calls"] += 1
    sess["last_ts"] = _t.time()
    _autotitle_usage["day_calls"] += 1
    log.info(
        "auto-title src=%s sid=%s ms=%d day=%d/%d sess=%d/%d",
        source, session_id, elapsed_ms,
        _autotitle_usage["day_calls"], _AUTOTITLE_MAX_PER_DAY,
        sess["calls"], _AUTOTITLE_MAX_PER_SESS,
    )


@router.post("/api/chat/title", response_model=ChatTitleResponse)
async def chat_title(req: ChatTitleRequest) -> ChatTitleResponse:
    import time as _t
    t0 = _t.perf_counter()

    # 1) Build a transcript — prefer the Orchestrator ledger, fall back
    #    to the client-supplied snapshot.
    try:
        from workspace.agents.orchestrator_agent import get_orchestrator
        orch = get_orchestrator()
        st = orch.get(req.session_id)
        lines: list[str] = []
        for entry in st.ledger[-10:]:
            agent = entry.agent or "system"
            text = (entry.summary or "").strip()
            if not text:
                continue
            lines.append(f"{agent}: {text[:140]}")
        transcript = "\n".join(lines)
    except Exception:
        transcript = ""
    if not transcript and req.transcript:
        lines = []
        for m in req.transcript[-10:]:
            agent = (m.get("agent") or "system").strip()
            text = (m.get("content") or "").strip()
            if not text:
                continue
            lines.append(f"{agent}: {text[:140]}")
        transcript = "\n".join(lines)

    if not transcript:
        return ChatTitleResponse(
            session_id=req.session_id,
            title="",
            source="empty",
            elapsed_ms=int((_t.perf_counter() - t0) * 1000),
        )

    # 2) Cheap heuristic fallback if LLM is unavailable. Try to extract
    #    the first user message and squash it.
    fallback = ""
    for line in transcript.split("\n"):
        if line.lower().startswith("user:"):
            payload = line.split(":", 1)[1].strip()
            payload = payload.lstrip("/")
            fallback = " ".join(payload.split()[:6])[:50]
            break

    # 3) LLM call — bounded. If budget is exhausted (per-day, per-session,
    #    or min-gap) we go straight to the heuristic fallback. Backend is
    #    env-selectable so flipping to the deployed Lysos-Gemma later is
    #    one config change.
    title = ""
    source = "fallback"
    prompt = _TITLE_PROMPT.format(transcript=transcript)

    allowed, reason = _autotitle_check_budget(req.session_id)
    if not allowed:
        log.info("auto-title budget skip: %s (sid=%s)", reason, req.session_id)
        # fall through to fallback heuristic only

    # Tier 1: Gemini Flash via direct REST (no extra dep). Cheapest +
    # reliably online if GEMINI_API_KEY is set. Only attempted when
    # backend == "gemini" AND budget allows.
    try:
        if not allowed or _AUTOTITLE_BACKEND != "gemini":
            raise RuntimeError("skip-gemini")
        # Inline the model name so it's clear at the call site
        _model_id = _AUTOTITLE_GEMINI_MODEL
        import os as _os
        gemini_key = _os.getenv("GEMINI_API_KEY")
        if gemini_key:
            import httpx  # FastAPI dep; always present
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{_model_id}:generateContent"
            )
            # Reasoning model gotcha (per project memory): both 2.5-Pro
            # and 2.5-Flash spend output tokens on thinking by default.
            # We bump maxOutputTokens HIGH (1024) so the title isn't
            # truncated, then bound the thinking budget so cost is
            # predictable. For 2.5-Pro a small thinking budget (~512)
            # produces noticeably better titles than thinking=0; for
            # Flash, 0 is fine.
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": 1024,
                    "temperature": 0.4,
                    "responseMimeType": "text/plain",
                    "thinkingConfig": {
                        "thinkingBudget": _AUTOTITLE_THINKING_BUDGET,
                        "includeThoughts": False,
                    },
                },
            }
            async with httpx.AsyncClient(timeout=8.0) as cx:
                r = await cx.post(
                    url,
                    headers={"x-goog-api-key": gemini_key,
                             "Content-Type": "application/json"},
                    json=payload,
                )
            if r.status_code == 200:
                d = r.json()
                cands = d.get("candidates") or []
                raw = ""
                if cands:
                    parts = (cands[0].get("content") or {}).get("parts") or []
                    if parts:
                        raw = (parts[0].get("text") or "").strip()
                first = (raw.splitlines()[0] if raw else "").strip().strip('"\'').rstrip(".,;:!? ")
                if first.lower().startswith("title:"):
                    first = first.split(":", 1)[1].strip()
                if first:
                    title = first[:50]
                    source = "gemini"
            else:
                log.debug("auto-title gemini http %s: %s", r.status_code, r.text[:120])
    except Exception as exc:  # noqa: BLE001
        log.debug("auto-title gemini failed: %s", exc)

    # Tier 2: configured LLMEndpoint (vLLM / Claude / LysosEndpoint).
    # Only attempted when backend == "lysos" AND budget allows. This is
    # the path we'll take when the trained Lysos-Gemma is deployed: set
    # LYSOS_AUTOTITLE_BACKEND=lysos and the Gemini call is bypassed.
    if not title and allowed and _AUTOTITLE_BACKEND == "lysos":
        try:
            from workspace.agents.llm import get_llm
            llm = get_llm()
            result = await llm.acomplete(
                messages=[{"role": "user", "content": prompt}],
                system=None,
                tools=None,
            )
            raw = (result.get("content") or "").strip()
            first = (raw.splitlines()[0] if raw else "").strip().strip('"\'').rstrip(".,;:!? ")
            if first.lower().startswith("title:"):
                first = first.split(":", 1)[1].strip()
            if first:
                title = first[:50]
                source = "lysos"
        except Exception as exc:  # noqa: BLE001
            log.debug("auto-title lysos endpoint failed: %s", exc)

    if not title:
        title = fallback or "New chat"

    elapsed_ms = int((_t.perf_counter() - t0) * 1000)
    if source in ("gemini", "lysos"):
        _autotitle_record(req.session_id, source, elapsed_ms)

    return ChatTitleResponse(
        session_id=req.session_id,
        title=title,
        source=source,
        elapsed_ms=elapsed_ms,
    )


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

    # Per-request context overrides — frontend passes the currently
    # selected pathogen / loaded SMILES so bare slash commands like
    # `/explain` and `/score` resolve from natural conversation context
    # instead of demanding explicit args every time.
    if req.pathogen:
        sess.set_active_target(req.pathogen)
    if req.smiles:
        sess.set_active_smiles(req.smiles)

    from workspace.agents.harness.orchestrator import SessionState

    state = SessionState(
        session_id=req.session_id,
        user_id=req.user_id,
        active_smiles=req.smiles or sess.meta.active_smiles,
        active_target=req.pathogen or sess.meta.active_target,
        sandbox=sess,
        settings=sess.meta.settings,
    )
    # Threading metadata flows into the harness via the SessionState
    # settings dict (not a structural state field — keeps the harness
    # contract small).
    if req.reply_to_agent:
        state.settings["reply_to_agent"] = req.reply_to_agent
    if req.parent_message_id:
        state.settings["parent_message_id"] = req.parent_message_id
    if req.thread_id:
        state.settings["thread_id"] = req.thread_id
    if req.pdb_id:
        state.settings["pdb_id"] = req.pdb_id
    if req.recent_messages:
        state.settings["recent_messages"] = req.recent_messages

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
        data=resp.data,
        card_kind=resp.card_kind,
        follow_ups=resp.follow_ups,
        elapsed_ms=resp.elapsed_ms,
        events=resp.events,
        parent_message_id=req.parent_message_id,
        thread_id=req.thread_id,
        reply_agent=req.reply_to_agent,
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
