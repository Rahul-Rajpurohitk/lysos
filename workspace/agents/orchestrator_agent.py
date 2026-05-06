"""Orchestrator agent — the always-aware meta-agent.

Per SAAS_HARNESS.md §3:
  > A new agent: the Orchestrator. Always aware of every sub-agent's
  > state. Routes user messages, decides debate vs. single-agent dispatch,
  > reconciles parallel threads.

Phase 1 (this file) is a skeleton:
  • Maintains a per-session message ledger (every agent_message + tool
    call + candidate emission gets logged here)
  • Provides summary() returning a structured snapshot of what each
    specialist has been up to, plus the running candidate list
  • Provides route_dispatch_intent() — given a user prompt + optional
    reply_to_agent, returns one of:
        ("debate",      None)         # default — full Designer→Critic→Editor→Strategist
        ("single",      "<agent>")    # reply-to-agent or per-agent slash command
        ("orchestrator", None)        # /orchestrate or @orchestrator — the meta-agent answers
  • Provides answer_meta() — when the user asks the Orchestrator a meta
    question ("what has Critic been arguing?"), produce a grounded answer
    from the ledger without re-invoking the specialists

Phase 2 (later) wires the Orchestrator into the full multi-agent loop —
right now graph.py runs the debate without consulting it.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal, Optional


AgentName = Literal["designer", "critic", "editor", "strategist", "orchestrator", "user"]


@dataclass
class LedgerEntry:
    ts: float
    kind: str            # "message" | "tool_call" | "candidate" | "score" | "intervention" | "side_thread"
    agent: Optional[str] # which specialist (None for system events)
    summary: str         # short human-readable line
    payload: dict[str, Any] = field(default_factory=dict)
    thread_id: Optional[str] = None


@dataclass
class OrchestratorState:
    """Per-session memory the Orchestrator maintains."""
    session_id: str
    ledger: list[LedgerEntry] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)  # {id, smiles, composite, agent}
    by_agent: dict[str, list[LedgerEntry]] = field(default_factory=lambda: defaultdict(list))
    threads: dict[str, list[LedgerEntry]] = field(default_factory=lambda: defaultdict(list))
    last_seen: float = field(default_factory=time.time)


class Orchestrator:
    """Singleton-ish — owns one OrchestratorState per session id."""

    def __init__(self) -> None:
        self._states: dict[str, OrchestratorState] = {}

    def get(self, session_id: str) -> OrchestratorState:
        st = self._states.get(session_id)
        if st is None:
            st = OrchestratorState(session_id=session_id)
            self._states[session_id] = st
        return st

    # ---- ingest events from the bus -------------------------------------

    def ingest(self, session_id: str, event: dict) -> None:
        """Called for every event that flows through the trace bus.

        Builds the ledger so the Orchestrator can answer meta questions
        without re-running the specialists.
        """
        st = self.get(session_id)
        st.last_seen = time.time()
        kind = event.get("type", "")
        agent = (event.get("agent") or event.get("data", {}).get("role")
                 or event.get("data", {}).get("agent"))
        thread_id = event.get("thread_id") or event.get("data", {}).get("thread_id")
        summary = self._summarize(event)

        entry = LedgerEntry(
            ts=time.time(),
            kind=self._classify(kind),
            agent=agent,
            summary=summary,
            payload=event.get("data") or {},
            thread_id=thread_id,
        )
        st.ledger.append(entry)
        if agent:
            st.by_agent[agent].append(entry)
        if thread_id:
            st.threads[thread_id].append(entry)

        if kind == "candidate_added":
            data = event.get("data") or {}
            st.candidates.append({
                "id": data.get("id"),
                "smiles": data.get("smiles"),
                "composite": data.get("composite", 0.0),
                "agent": agent or "designer",
                "iteration": data.get("iteration"),
            })

    @staticmethod
    def _classify(event_type: str) -> str:
        if event_type == "agent_message":          return "message"
        if event_type == "candidate_added":        return "candidate"
        if event_type in ("tool_call_result", "tool_call_error"): return "tool_call"
        if event_type == "score":                  return "score"
        if event_type == "intervention_queued":    return "intervention"
        if event_type == "side_thread":            return "side_thread"
        return "other"

    @staticmethod
    def _summarize(event: dict) -> str:
        t = event.get("type", "?")
        d = event.get("data") or {}
        if t == "agent_message":
            return (d.get("content") or "")[:120]
        if t == "candidate_added":
            return f"smiles={d.get('smiles', '?')} composite={d.get('composite', 0):.3f}"
        if t == "tool_call_result":
            return f"tool={d.get('tool', '?')} ok"
        if t == "tool_call_error":
            return f"tool={d.get('tool', '?')} ERROR: {(d.get('error') or '')[:60]}"
        if t == "score":
            return f"composite={d.get('composite', 0):.3f}"
        return t

    # ---- routing -------------------------------------------------------

    def route_dispatch_intent(
        self,
        text: str,
        reply_to_agent: Optional[str] = None,
    ) -> tuple[Literal["debate", "single", "orchestrator"], Optional[str]]:
        """Decide which dispatch mode + (if single) which agent."""
        if reply_to_agent:
            tgt = reply_to_agent.lower().strip()
            if tgt == "orchestrator":
                return ("orchestrator", None)
            if tgt in {"designer", "critic", "editor", "strategist"}:
                return ("single", tgt)

        head = text.strip().split(" ", 1)[0].lower().lstrip("/")
        # Per-agent slash routes (planned per SAAS_HARNESS §4)
        slash_to_agent = {
            "design": "designer", "d": "designer",
            "critique": "critic", "argue": "critic",
            "edit": "editor",
            "plan": "strategist", "strategy": "strategist",
            "orchestrate": "orchestrator", "summary": "orchestrator",
        }
        if head in slash_to_agent:
            agent = slash_to_agent[head]
            if agent == "orchestrator":
                return ("orchestrator", None)
            return ("single", agent)

        return ("debate", None)

    # ---- meta answers --------------------------------------------------

    def summary(self, session_id: str) -> dict[str, Any]:
        """Snapshot of what each specialist has been doing in this session."""
        st = self.get(session_id)
        per_agent_counts = {a: len(v) for a, v in st.by_agent.items()}
        last_per_agent = {a: v[-1].summary for a, v in st.by_agent.items() if v}
        return {
            "session_id": session_id,
            "total_events": len(st.ledger),
            "total_candidates": len(st.candidates),
            "best_composite": (
                max((c["composite"] for c in st.candidates), default=0.0)
            ),
            "messages_per_agent": per_agent_counts,
            "last_action_per_agent": last_per_agent,
            "active_threads": len([t for t in st.threads.values() if t]),
            "last_seen": st.last_seen,
        }

    def answer_meta(self, session_id: str, question: str) -> str:
        """Cheap, grounded meta-answer for the user. No LLM needed for the
        common 'who said what' questions; the ledger is the source of truth."""
        st = self.get(session_id)
        q = question.lower()
        if any(k in q for k in ("status", "summary", "what's happening", "progress")):
            s = self.summary(session_id)
            agents = ", ".join(f"{a}({n})" for a, n in s["messages_per_agent"].items()) or "no activity yet"
            return (
                f"**Orchestrator summary** — {s['total_candidates']} candidate(s), "
                f"best composite {s['best_composite']:.3f}, agents: {agents}."
            )
        for agent in ("designer", "critic", "editor", "strategist"):
            if agent in q:
                last = st.by_agent.get(agent, [])
                if not last:
                    return f"{agent.title()} hasn't said anything yet in this session."
                return f"**{agent.title()}** (last {min(3, len(last))}):\n" + "\n".join(
                    f"- {e.summary}" for e in last[-3:]
                )
        return "Ask about a specific specialist (designer / critic / editor / strategist) or say 'summary'."


# Module-level singleton — same lifetime as the FastAPI app
_ORCHESTRATOR: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = Orchestrator()
    return _ORCHESTRATOR
