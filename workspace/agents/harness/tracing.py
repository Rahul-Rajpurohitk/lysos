"""Tracing — structured event log for every harness operation.

Pattern: lifted from atikan-agentic-module/src/agent/tracing.py + audit.py.
Adapted for Lysos's chemistry domain: every command, tool call, cell run,
edit, and reward score becomes a typed trace event.

Three sinks:
1. In-memory ring buffer per session (fast read for the right-panel "trace"
   tab without a DB hit)
2. JSONL append to `~/.lysos/sessions/<id>/trace.jsonl` (durable, replayable)
3. Optional structured emit to stderr / wandb (observability)

Why this matters:
- Trace = the source of truth for "what did the agent do, in what order,
  with what arguments, with what result". The methods paper wants this.
- Re-running a session means replaying the trace, NOT re-asking the LLM.
- Debugging a stuck design loop = scrolling the trace and finding the
  reward fallback that broke composition.

API:
    tracer = Tracer(session_id="abc")
    tracer.emit("command.start", cmd="design", args="MRSA")
    with tracer.span("tool.score"):
        ... call score_molecule
    tracer.emit("command.done", cmd="design", elapsed_ms=82)
    tracer.dump_recent(50)   # last 50 events
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

log = logging.getLogger("workbench.agents.harness.tracing")


@dataclass
class TraceEvent:
    event_id: str
    session_id: str
    type: str                                # e.g. "command.start", "tool.score.done"
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: Optional[int] = None         # set on .done events
    parent_id: Optional[str] = None          # for nested spans

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class Tracer:
    """Per-session tracer. Thread-safe."""

    def __init__(
        self,
        session_id: str,
        ring_size: int = 1024,
        persist_dir: Optional[Path] = None,
        also_log: bool = True,
    ):
        self.session_id = session_id
        self.ring_size = ring_size
        self.persist_dir = persist_dir or (
            Path.home() / ".lysos" / "sessions" / session_id
        )
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._ring: deque[TraceEvent] = deque(maxlen=ring_size)
        self._lock = threading.Lock()
        self._span_stack: list[str] = []
        self.also_log = also_log

    # ---- core emit ----

    def emit(self, event_type: str, **payload: Any) -> TraceEvent:
        ev = TraceEvent(
            event_id=uuid.uuid4().hex[:12],
            session_id=self.session_id,
            type=event_type,
            timestamp=time.time(),
            payload=payload,
            parent_id=self._span_stack[-1] if self._span_stack else None,
        )
        with self._lock:
            self._ring.append(ev)
            self._persist(ev)
        if self.also_log:
            log.info("trace[%s]: %s %s", self.session_id, event_type,
                     json.dumps(payload, default=str)[:200])
        return ev

    @contextmanager
    def span(self, event_type: str, **payload: Any) -> Iterator[TraceEvent]:
        """Context manager that emits .start at __enter__ and .done at __exit__,
        with elapsed_ms automatically computed. Sets parent_id on nested events.
        """
        start_ev = self.emit(f"{event_type}.start", **payload)
        self._span_stack.append(start_ev.event_id)
        t0 = time.perf_counter()
        try:
            yield start_ev
            self._span_stack.pop()
            done = self.emit(
                f"{event_type}.done",
                **payload,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
                parent_id=start_ev.event_id,
            )
            done.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        except Exception as exc:  # noqa: BLE001
            self._span_stack.pop()
            self.emit(
                f"{event_type}.error",
                **payload,
                error_type=type(exc).__name__,
                error_msg=str(exc)[:300],
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
                parent_id=start_ev.event_id,
            )
            raise

    # ---- persistence ----

    def _persist(self, ev: TraceEvent) -> None:
        try:
            with (self.persist_dir / "trace.jsonl").open("a") as f:
                f.write(json.dumps(ev.to_dict(), default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            # Tracing failures must never crash the harness — degrade gracefully.
            log.warning("trace persist failed: %s", exc)

    # ---- read ----

    def dump_recent(self, n: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in list(self._ring)[-n:]]

    def all_persisted(self) -> list[dict[str, Any]]:
        """Read the full trace.jsonl off disk (for replay / methods-paper)."""
        path = self.persist_dir / "trace.jsonl"
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out


# ---------------------------------------------------------------------------
# Global registry (one tracer per live session)
# ---------------------------------------------------------------------------

_TRACERS: dict[str, Tracer] = {}
_TRACERS_LOCK = threading.Lock()


def get_tracer(session_id: str) -> Tracer:
    with _TRACERS_LOCK:
        t = _TRACERS.get(session_id)
        if t is None:
            t = Tracer(session_id=session_id)
            _TRACERS[session_id] = t
        return t


def drop_tracer(session_id: str) -> None:
    with _TRACERS_LOCK:
        _TRACERS.pop(session_id, None)
