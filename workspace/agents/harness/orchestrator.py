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


# ----- Per-agent thread-reply prompts ------------------------------------
# The original DESIGNER_SYSTEM/CRITIC_SYSTEM/EDITOR_SYSTEM in prompts.py
# are debate-loop prompts (telling the agent "your turn, propose / argue /
# transform"). For one-off thread replies ("where?", "why atom 2?", "what
# was the escape score?") we need a different prompt: the agent needs to
# answer THE USER'S QUESTION grounded in the recent conversation, not
# initiate a new debate turn.
_ROLE_BLURB = {
    "designer":   "You propose new candidate antibiotics and explain scaffold choices.",
    "critic":     "You identify weaknesses in candidates — resistance escape, ADMET liabilities, off-targets — and propose transformations.",
    "editor":     "You apply structural transformations (atom swaps, functional-group adds, SMARTS edits) and report the resulting SMILES.",
    "strategist": "You make routing decisions — continue, branch, terminate, or red-team — based on the Pareto frontier and lineage tree.",
}

_PER_AGENT_REPLY_SYSTEM = """\
You are the **{title}** agent in the Lysos antibiotic-design workspace.
The user just asked you a FOLLOW-UP question about your earlier work in
this session. Answer DIRECTLY and CONCRETELY using the context below.

# Your role
{role}

# Recent session activity (oldest → newest)
{history}

# Ambient context
- Current SMILES: `{smiles}`
- Target pathogen: {pathogen}
- PDB target: {pdb}

# Rules
1. Answer the user's question using the activity above. If a workflow
   already produced concrete numbers (atom indices, escape scores,
   robustness, residue positions, transformations), QUOTE THEM.
2. If they ask "where?" — name specific atom indices, residue positions
   (e.g. K247T, S365A), or transformation locations from the activity.
3. If they ask "why?" — give the chemical / biological reason
   (active-site catalytic residue, H-bond donor, electrostatic
   complementarity), not generic disclaimers.
4. NEVER deflect with "please specify" or "I'm focused on antibiotics" —
   you ALREADY have the context, USE IT.
5. Stay in character. Editor talks structure edits. Critic talks
   weaknesses. Designer talks scaffolds. Strategist talks decisions.
6. Be concise — 2-4 sentences unless the user asks for detail.
"""


def _format_ledger_for_agent(orch_state, target_agent: str, k: int = 12) -> str:
    """Build a compact "you said X, then user said Y" history that
    grounds the per-agent reply. Pulls the last k ledger entries that are
    either from THIS agent or are user messages, so the LLM sees its own
    output + the user's prompts in order.

    Workflow step results (predict, harden, score) are reformatted as
    "[tool]" lines so the agent can quote concrete numbers.
    """
    try:
        ledger = orch_state.ledger
    except AttributeError:
        return "(no recent activity)"
    if not ledger:
        return "(no recent activity)"

    relevant = []
    for entry in ledger[-60:]:  # cap at 60 so we don't blow context
        agent = (entry.agent or "").lower()
        if entry.kind == "message" and (agent == "user" or agent == target_agent):
            relevant.append(entry)
        elif entry.kind in ("tool_call", "candidate", "score"):
            # All agents benefit from seeing tool results / new candidates
            relevant.append(entry)

    if not relevant:
        return "(no recent activity)"

    lines = []
    for entry in relevant[-k:]:
        agent = (entry.agent or "system").lower()
        summary = entry.summary or "(empty)"
        if len(summary) > 280:
            summary = summary[:277] + "…"
        if entry.kind == "message":
            lines.append(f"- **{agent}**: {summary}")
        elif entry.kind == "tool_call":
            tool = (entry.payload or {}).get("tool", "tool")
            lines.append(f"- _{tool}_: {summary}")
        elif entry.kind == "candidate":
            lines.append(f"- _new candidate_: {summary}")
        elif entry.kind == "score":
            lines.append(f"- _score_: {summary}")
    return "\n".join(lines) if lines else "(no recent activity)"


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
        target_agent: Optional[str] = None
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

            # Per-agent thread reply: the user replied to a specific agent
            # bubble. Build a context-aware system prompt with the recent
            # ledger so the agent answers IN CHARACTER and grounded in
            # what's already on screen — fixes "where?" → editor giving a
            # generic "please specify" deflection.
            if mode == "single" and target_agent and target_agent in _ROLE_BLURB:
                if not user_text.strip().startswith("/"):
                    ans = await self._reply_as_agent(
                        agent=target_agent,
                        user_text=user_text,
                        session=session,
                        orch=orch,
                        trace=trace,
                    )
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
            # parse "/cmd args" — case-insensitive lookup so /HELP and
            # /Help both find /help
            head_raw, _, args = text[1:].partition(" ")
            head = head_raw.lower()
            cmd = self.registry.get(head)
            trace("resolve.slash", cmd=head, args=args, found=bool(cmd))
            if cmd is None:
                # Don't error out — the orchestrator IS the main agent
                # and should reinterpret unknown slashes as natural-
                # language intent. `/debate lets build to fight mrsa`
                # → orchestrator picks design_with_debate workflow.
                # Strip the leading slash and treat the whole line as
                # free text. Phase 2-4 below picks up via the
                # is_slash=False path.
                stripped = text[1:].strip()
                if not stripped:
                    return HarnessResponse(
                        session_id=session.session_id,
                        message_id=msg_id,
                        error=(
                            f"Empty slash — type `/help` for the command list "
                            f"or describe what you want to do in plain English."
                        ),
                        elapsed_ms=int((time.perf_counter() - t0) * 1000),
                        events=events,
                    )
                user_text = stripped
                text = stripped
                is_slash = False
                # Fall through to phase 2 (skills) / phase 4 (LLM agent
                # loop). All `cmd.*` calls below are inside this same
                # `if is_slash:` block so they're skipped entirely.

        if is_slash:
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
            elif head == "champion" and result.data:
                card_kind = "champion"
                # Reshape the output payload into the shape the frontend
                # ChampionCard expects (mode-discriminated).
                d = result.data
                if "ab_compare" in d:
                    result.data = {"mode": "compare", "ab": d["ab_compare"], "pathogen": d.get("pathogen")}
                elif "champion_promotion" in d:
                    result.data = {"mode": "promote", "promotion": d["champion_promotion"], "pathogen": d.get("pathogen")}
                else:
                    result.data = {"mode": "show", "champion": d.get("champion"), "pathogen": d.get("pathogen")}

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

    async def _reply_as_agent(
        self,
        agent: str,
        user_text: str,
        session: SessionState,
        orch,
        trace,
    ) -> str:
        """Generate a context-aware reply when the user clicks "reply to
        editor / critic / designer / strategist". Uses orchestrator state
        to ground the response in recent activity instead of inviting
        generic boilerplate.
        """
        if self.llm is None:
            return f"({agent.title()} can't reply — no LLM configured.)"

        # Prefer the frontend-shipped on-screen context: the workflow
        # narration ("Generate hardening suggestions complete") and the
        # blob explaining "atom 2 → 2-fluoro substitution" only land in
        # the chat via SSE-driven client-side events; they may not be
        # in the orchestrator ledger. Frontend-context is more accurate.
        history = "(no recent activity)"
        recent = session.settings.get("recent_messages") or []
        if recent:
            try:
                lines = []
                for m in recent[-14:]:
                    if not isinstance(m, dict):
                        continue
                    a = (m.get("agent") or "system").lower()
                    c = (m.get("content") or "").strip().replace("\n", " ")
                    if not c:
                        continue
                    if len(c) > 320:
                        c = c[:317] + "…"
                    lines.append(f"- **{a}**: {c}")
                if lines:
                    history = "\n".join(lines)
            except Exception as exc:  # noqa: BLE001
                trace("agent.reply.frontend_history_error", err=str(exc))
        # Fallback to ledger if frontend didn't ship anything.
        if history == "(no recent activity)":
            try:
                orch_state = orch.get(session.session_id)
                history = _format_ledger_for_agent(orch_state, agent, k=12)
            except Exception as exc:  # noqa: BLE001
                trace("agent.reply.history_error", err=str(exc))
                history = "(history unavailable)"

        sys_prompt = _PER_AGENT_REPLY_SYSTEM.format(
            title=agent.title(),
            role=_ROLE_BLURB.get(agent, ""),
            history=history,
            smiles=session.active_smiles or "(none loaded)",
            pathogen=session.active_target or "(unset)",
            pdb=session.settings.get("pdb_id") or "(unset)",
        )
        trace("agent.reply.start", agent=agent, history_len=len(history))
        try:
            llm_out = await self.llm.acomplete(
                messages=[{"role": "user", "content": user_text}],
                tools=[],
                system=sys_prompt,
            )
            text = (llm_out.get("content") or "").strip()
        except Exception as exc:  # noqa: BLE001
            trace("agent.reply.error", agent=agent, err=str(exc))
            return f"({agent.title()} hit an LLM error: {exc})"

        trace("agent.reply.done", agent=agent, chars=len(text))
        if not text:
            return (
                f"({agent.title()} returned an empty response — try "
                f"rephrasing or asking the orchestrator instead.)"
            )

        # Persist the agent's reply into the ledger so subsequent thread
        # replies see it as part of "your prior output".
        try:
            orch.ingest(session.session_id, {
                "type": "agent_message",
                "agent": agent,
                "data": {"content": text},
                "thread_id": session.settings.get("thread_id"),
            })
        except Exception:  # noqa: BLE001
            pass

        return text

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
