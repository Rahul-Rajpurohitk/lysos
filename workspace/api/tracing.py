"""Agentic tracing layer — structured event types + persistence.

The Workbench's SSE event bus already emits `agent_message`, `tool_call_*`,
`candidate_added`, `score`. This module formalizes the schema, adds:

  * `reasoning_chunk`  — streaming-token-level reasoning from a model
                         (one event per chunk, replayable)
  * `iteration_start`  / `iteration_end`
  * `state_change`     — Strategist's TERMINATE / CONTINUE / BRANCH
  * `intervention`     — user mid-loop directive
  * `mol_edit`         — sandbox transform / atom-edit applied
  * `score_delta`      — per-component reward delta on a transform
  * `error`            — explicit error with reason + recovery hint

It also provides a `Tracer` class that:
  * Auto-attaches iteration + agent + correlation_id
  * Buffers events to a JSONL file under reports/traces/<session>.jsonl
  * Computes lightweight stats (event counts, agent activity)
  * Supports replay (read JSONL, re-emit events to a different sink)

Replay is what powers the brief's "playback controls inside the iteration
strip" feature on the frontend.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator, Literal

log = logging.getLogger("workbench.tracing")

EventType = Literal[
    "agent_message",
    "reasoning_chunk",
    "tool_call_start",
    "tool_call_result",
    "tool_call_error",
    "candidate_added",
    "candidate_rejected",
    "iteration_start",
    "iteration_end",
    "state_change",
    "intervention",
    "mol_edit",
    "score",
    "score_delta",
    "session_start",
    "session_end",
    "ping",
    "error",
]

EmitFn = Callable[[dict], Awaitable[None]]


@dataclass
class Tracer:
    """Wraps an SSE emit function to add structured fields + persist to disk."""

    session_id: str
    emit_fn: EmitFn
    out_path: Path | None = None
    iteration: int = 0
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    _stats: dict[str, int] = field(default_factory=dict)
    _agent_last_seen: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if self.out_path is None:
            self.out_path = Path("reports/traces") / f"{self.session_id}.jsonl"
        self.out_path.parent.mkdir(parents=True, exist_ok=True)

    def _enrich(self, ev: dict) -> dict:
        """Add ts, iteration, session, correlation_id to every event."""
        ev = dict(ev)  # shallow copy
        ev.setdefault("ts", time.time())
        ev.setdefault("iteration", self.iteration)
        ev.setdefault("session_id", self.session_id)
        ev.setdefault("correlation_id", self.correlation_id)
        return ev

    def _record(self, ev: dict) -> None:
        """Update stats + write to JSONL."""
        t = ev.get("type", "unknown")
        self._stats[t] = self._stats.get(t, 0) + 1
        agent = ev.get("agent")
        if agent:
            self._agent_last_seen[agent] = ev.get("ts", time.time())
        try:
            with open(self.out_path, "a") as f:
                f.write(json.dumps(ev, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            log.warning("trace write failed: %s", exc)

    async def emit(self, ev: dict) -> None:
        ev = self._enrich(ev)
        self._record(ev)
        await self.emit_fn(ev)

    # Convenience methods — semantic shortcuts for common events --------

    async def session_start(self, target_pathogen: str, mode: str) -> None:
        await self.emit({"type": "session_start",
                         "target_pathogen": target_pathogen, "mode": mode})

    async def session_end(self, reason: str, composite: float | None = None) -> None:
        await self.emit({"type": "session_end", "reason": reason,
                         "composite": composite, "stats": self._stats})

    async def iteration_start(self, n: int) -> None:
        self.iteration = n
        await self.emit({"type": "iteration_start", "iteration": n})

    async def iteration_end(self, n: int, composite: float, n_candidates: int) -> None:
        await self.emit({"type": "iteration_end", "iteration": n,
                         "composite": composite, "n_candidates": n_candidates})

    async def agent_message(self, agent: str, content: str,
                            tokens: int | None = None,
                            latency_ms: int | None = None,
                            model: str | None = None) -> None:
        await self.emit({"type": "agent_message", "agent": agent,
                         "content": content, "tokens": tokens,
                         "latency_ms": latency_ms, "model": model})

    async def reasoning_chunk(self, agent: str, chunk: str) -> None:
        """Streaming-token reasoning. Frontend appends to the latest agent
        message bubble's thinking block."""
        await self.emit({"type": "reasoning_chunk", "agent": agent,
                         "chunk": chunk})

    async def tool_call(self, tool: str, args: dict, agent: str,
                        result: dict | None = None,
                        error: str | None = None,
                        elapsed_ms: int | None = None) -> None:
        if error:
            await self.emit({"type": "tool_call_error", "tool": tool,
                             "args": args, "agent": agent, "error": error,
                             "elapsed_ms": elapsed_ms})
        else:
            await self.emit({"type": "tool_call_result", "tool": tool,
                             "args": args, "agent": agent, "result": result,
                             "elapsed_ms": elapsed_ms})

    async def candidate_added(self, smiles: str, scores: dict,
                              composite: float, source: str = "designer") -> None:
        await self.emit({"type": "candidate_added", "smiles": smiles,
                         "scores": scores, "composite": composite,
                         "source": source})

    async def mol_edit(self, parent: str, candidate: str, op: str,
                       delta: dict | None = None,
                       agent: str = "editor") -> None:
        """Emitted by the chemistry sandbox transform/atom-edit flow."""
        await self.emit({"type": "mol_edit", "parent": parent,
                         "candidate": candidate, "op": op,
                         "delta": delta or {}, "agent": agent})

    async def score(self, smiles: str, scores: dict, composite: float) -> None:
        await self.emit({"type": "score", "smiles": smiles,
                         "scores": scores, "composite": composite})

    async def score_delta(self, parent: str, candidate: str,
                          delta: dict, composite_delta: float) -> None:
        await self.emit({"type": "score_delta", "parent": parent,
                         "candidate": candidate, "delta": delta,
                         "composite_delta": composite_delta})

    async def state_change(self, decision: Literal["TERMINATE", "CONTINUE", "BRANCH"],
                           reason: str) -> None:
        await self.emit({"type": "state_change", "decision": decision,
                         "reason": reason})

    async def intervention(self, kind: str, payload: Any) -> None:
        await self.emit({"type": "intervention", "kind": kind,
                         "payload": payload})

    async def error(self, where: str, message: str, recovery: str | None = None) -> None:
        await self.emit({"type": "error", "where": where, "message": message,
                         "recovery": recovery})

    # Stats / replay ----------------------------------------------------

    def stats(self) -> dict:
        return {
            "event_counts": dict(self._stats),
            "agents_active": list(self._agent_last_seen.keys()),
            "iteration": self.iteration,
            "correlation_id": self.correlation_id,
        }


def replay(trace_path: Path | str) -> Iterator[dict]:
    """Read a JSONL trace and yield events in order. Used by the
    'playback' UI to re-render a finished session."""
    p = Path(trace_path)
    if not p.exists():
        raise FileNotFoundError(p)
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
