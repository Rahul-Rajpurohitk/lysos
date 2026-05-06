"""Harness — the agent's pipeline.

Pattern: lifted from atikan-agentic-module/src/orchestrator/orchestrator.py
+ atlas-terminal/atlas/harness, adapted for chemistry/AMR.

Pipeline phases per request:
    1. RESOLVE — parse the user message: is it a slash command? a free
       prompt? what's the active candidate / target?
    2. CONTEXT — load relevant skills (SkillsLoader).
    3. SUPERVISE — apply guardrails (rules.md, structural-alert checks
       on any SMILES the user provided).
    4. ACT — execute:
       - slash command → CommandRegistry.exec
       - free prompt → LLM round-trip with tools
       - tool result → loop back into LLM if more tool calls needed
    5. PERSIST — write the trace to the session DB; emit events.

This is the single entry point the FastAPI server calls per WebSocket /
HTTP message. Other components (CommandRegistry, SkillsLoader, sandbox,
LLMEndpoint) are injected.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..commands import (
    CommandContext,
    CommandRegistry,
    CommandResult,
    get_registry,
)
from .skills_loader import SkillsLoader
from .store import SessionStore, get_store
from .tracing import Tracer, get_tracer

log = logging.getLogger("workbench.agents.harness.orchestrator")


@dataclass
class HarnessResponse:
    """What the harness returns per user message."""
    session_id: str
    message_id: str
    text: str = ""                              # markdown for chat
    artifact: Optional[dict] = None             # for right panel
    data: dict[str, Any] = field(default_factory=dict)  # structured chat-card payload
    card_kind: str = ""                         # discriminator: score | candidate | sar_tree | ...
    follow_ups: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)  # trace events
    error: str = ""
    elapsed_ms: int = 0


@dataclass
class SessionState:
    """In-memory mirror of session DB row. The orchestrator keeps it for
    the lifetime of a request; persistence is via session_store.
    """
    session_id: str
    user_id: str
    active_smiles: Optional[str] = None
    active_target: Optional[str] = None
    candidates: list[dict] = field(default_factory=list)   # lineage history
    sandbox: Any = None                                     # SandboxRuntime ref
    settings: dict[str, Any] = field(default_factory=dict)


class Harness:
    """Top-level coordinator. Owned by the FastAPI server (singleton)."""

    def __init__(
        self,
        registry: Optional[CommandRegistry] = None,
        skills: Optional[SkillsLoader] = None,
        llm: Any = None,
        store: Optional[SessionStore] = None,
    ):
        self.registry = registry or get_registry()
        self.skills = skills or SkillsLoader()
        self.llm = llm
        self.store = store or get_store()

    # ---- public entry point ----

    async def handle_message(
        self,
        session: SessionState,
        user_text: str,
    ) -> HarnessResponse:
        t0 = time.perf_counter()
        msg_id = uuid.uuid4().hex[:12]
        events: list[dict] = []

        def trace(event_type: str, **payload: Any) -> None:
            events.append({"type": event_type, "ts": time.time(), **payload})

        trace("message.received", session_id=session.session_id,
              user_id=session.user_id, text=user_text)

        # ---- Orchestrator awareness ---------------------------------
        # The Orchestrator is always-aware: every user message hits the
        # ledger first, and the routing decision (debate vs single-agent
        # vs meta) is taken with the full session history available.
        try:
            from ..orchestrator_agent import get_orchestrator
            orch = get_orchestrator()
        except Exception:  # noqa: BLE001
            orch = None
        if orch is not None:
            orch.ingest(session.session_id, {
                "type": "agent_message", "agent": "user",
                "data": {"content": user_text},
                "thread_id": session.settings.get("thread_id"),
            })
            reply_to = session.settings.get("reply_to_agent")
            mode, target_agent = orch.route_dispatch_intent(user_text, reply_to)
            trace("orchestrator.route", mode=mode, target=target_agent)
            # Meta question shortcut — no slash needed when reply_to is "orchestrator"
            if mode == "orchestrator":
                ans = orch.answer_meta(session.session_id, user_text)
                return HarnessResponse(
                    session_id=session.session_id,
                    message_id=msg_id,
                    text=ans,
                    events=events,
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                )

        # ---- phase 1: resolve ----
        text = user_text.strip()
        is_slash = text.startswith("/")

        if is_slash:
            # parse "/cmd args"
            head, _, args = text[1:].partition(" ")
            cmd = self.registry.get(head)
            trace("resolve.slash", cmd=head, args=args, found=bool(cmd))
            if cmd is None:
                return HarnessResponse(
                    session_id=session.session_id,
                    message_id=msg_id,
                    error=f"Unknown command: /{head}. Type / to see options or /help.",
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                    events=events,
                )

            ok, err = cmd.is_enabled(self._mk_cmd_ctx(session))
            if not ok:
                return HarnessResponse(
                    session_id=session.session_id,
                    message_id=msg_id,
                    error=err,
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                    events=events,
                )

            trace("act.slash.start", cmd=head)
            result: CommandResult = await cmd.execute(args, self._mk_cmd_ctx(session))
            trace("act.slash.done", cmd=head, error=bool(result.error))

            # Map slash → frontend chat-card kind so the UI knows what
            # component to render (RewardCard for /score, etc.). Most
            # commands just produce text; this is the structured channel.
            card_kind = ""
            if head == "score" and result.data:
                card_kind = "score"
            elif head in ("design", "d") and result.data and result.data.get("session_id"):
                card_kind = "design_session"
            elif head == "explain" and result.data and result.data.get("session_id"):
                card_kind = "explain_session"
            elif head in ("sar", "expand") and result.data and result.data.get("children"):
                card_kind = "sar"
            elif head in ("stress", "redteam", "rt") and result.data and result.data.get("attacks"):
                card_kind = "stress"
            elif head in ("compare", "cmp") and result.data and result.data.get("entries"):
                card_kind = "compare"
            elif head in ("library", "lib", "sessions") and result.data and "sessions" in result.data:
                card_kind = "library"

            return HarnessResponse(
                session_id=session.session_id,
                message_id=msg_id,
                text=result.output if not result.error else "",
                error=result.error,
                artifact=result.artifact,
                data=result.data or {},
                card_kind=card_kind,
                follow_ups=result.follow_ups,
                events=events,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            )

        # ---- phase 2: free prompt → LLM ----
        # Load skills context
        ctx_md = self.skills.build_context(
            user_text=user_text,
            entity_hints=self._guess_entities(user_text),
        )
        trace("context.loaded", chars=len(ctx_md))

        if self.llm is None:
            return HarnessResponse(
                session_id=session.session_id,
                message_id=msg_id,
                text="(LLM endpoint not configured; only slash commands available.)",
                events=events,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            )

        # ---- phase 3: supervise (guardrails) ----
        if self._is_unsafe(user_text):
            trace("guardrail.block", reason="unsafe_target")
            return HarnessResponse(
                session_id=session.session_id,
                message_id=msg_id,
                error="Out of scope. Lysos only designs antibacterial small-molecules and peptides.",
                events=events,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            )

        # ---- phase 4: act ----
        trace("act.llm.start")
        try:
            from ..llm import build_tool_specs
            tools = build_tool_specs()  # all 27 from registry
        except Exception:
            tools = []

        try:
            llm_out = await self.llm.acomplete(
                messages=[{"role": "user", "content": user_text}],
                tools=tools,
                system=ctx_md,
            )
            trace("act.llm.done")
        except Exception as exc:  # noqa: BLE001
            trace("act.llm.error", err=str(exc))
            return HarnessResponse(
                session_id=session.session_id,
                message_id=msg_id,
                error=f"LLM error: {exc}",
                events=events,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            )

        return HarnessResponse(
            session_id=session.session_id,
            message_id=msg_id,
            text=llm_out.get("content", ""),
            events=events,
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
        )

    # ---- helpers ----

    def _mk_cmd_ctx(self, session: SessionState) -> CommandContext:
        return CommandContext(
            session_id=session.session_id,
            user_id=session.user_id,
            active_smiles=session.active_smiles,
            active_target=session.active_target,
            sandbox=session.sandbox,
            llm=self.llm,
            settings=session.settings,
        )

    @staticmethod
    def _guess_entities(text: str) -> list[str]:
        """Crude entity extraction — drug names, pathogen codes, PDB IDs."""
        out: list[str] = []
        # Pathogen codes
        for code in ("MRSA", "Mtb", "EColi", "KpneuCRE", "Abaum", "Paer",
                     "VRE", "NGono", "CRE"):
            if code in text:
                out.append(code)
        # PDB IDs (4-letter alphanumeric, all caps usually)
        import re
        pdbs = re.findall(r"\b([0-9][A-Z0-9]{3})\b", text)
        out.extend(pdbs)
        # Drug names (lowercase keyword match against pharma_lookup catalog)
        try:
            from src.embeddings.pharma_lookup import all_drugs
            lower_text = text.lower()
            for drug in all_drugs():
                if drug in lower_text:
                    out.append(drug)
        except Exception:
            pass
        return out

    @staticmethod
    def _is_unsafe(text: str) -> bool:
        """Cheap keyword guardrail. The llm guardrails layer does the rest."""
        unsafe_terms = (
            "VX agent", "sarin", "soman", "tabun", "mustard gas",
            "novichok", "BZ agent", "ricin", "anthrax weaponization",
        )
        lower = text.lower()
        return any(u.lower() in lower for u in unsafe_terms)
