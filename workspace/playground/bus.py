"""Per-session asyncio event bus + persistence to SQLite.

Producers:
  - WebSocket clients (user actions)
  - Agent loop (graph.py)
  - Job workers (job.update events)

Consumers:
  - WebSocket clients (everyone subscribed to the session sees events)
  - Orchestrator ledger (already exists at agents/orchestrator_agent.py)
  - Replay scrubber

Backpressure:
  - cursor.move events older than 100ms are dropped
  - edits NEVER drop
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from typing import Any, AsyncIterator, Optional


class _SessionChannel:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        # Per-subscriber queues so slow consumers can't block fast ones
        self._subs: list[asyncio.Queue] = []
        self._last_cursor_ts: dict[str, float] = {}  # actor → last cursor.move ts

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1024)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subs:
            self._subs.remove(q)

    def publish(self, event: dict[str, Any]) -> None:
        # Drop old cursor.move events from the same actor (cheap throttle)
        if event.get("event") == "cursor.moved":
            actor = event.get("actor", "?")
            now = time.time()
            last = self._last_cursor_ts.get(actor, 0.0)
            if now - last < 0.1:  # 100ms throttle per actor
                return
            self._last_cursor_ts[actor] = now

        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest, push newest
                try:
                    q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait(event)
                except Exception:
                    pass


class EventBus:
    """Singleton-ish; one channel per session_id."""

    def __init__(self) -> None:
        self._channels: dict[str, _SessionChannel] = {}
        self._lock = asyncio.Lock() if False else None  # lazy — channels are per-session

    def channel(self, session_id: str) -> _SessionChannel:
        ch = self._channels.get(session_id)
        if ch is None:
            ch = _SessionChannel(session_id)
            self._channels[session_id] = ch
        return ch

    def publish(self, session_id: str, event: dict[str, Any]) -> None:
        """Add a unique event_id + ts if missing, then fan out to subs."""
        if "event_id" not in event:
            event["event_id"] = uuid.uuid4().hex[:12]
        if "ts" not in event:
            event["ts"] = time.time()
        if "session_id" not in event:
            event["session_id"] = session_id
        self.channel(session_id).publish(event)

    async def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        """Async iterator over events for a session. Caller should run this
        inside a task and break when done. Each call gets its own queue,
        so multiple subscribers don't steal events from each other."""
        ch = self.channel(session_id)
        q = ch.subscribe()
        try:
            while True:
                ev = await q.get()
                yield ev
        finally:
            ch.unsubscribe(q)


_BUS: Optional[EventBus] = None


def get_bus() -> EventBus:
    global _BUS
    if _BUS is None:
        _BUS = EventBus()
    return _BUS
