"""Agent activity recorder + live event bus.

Single tap point for "an agent (designer/critic/editor/strategist/orchestrator)
just did something". Used by:

  - orchestrator.py     → records "orchestrator" routing decisions
  - workflows.py        → records each step.start/step.done with the
                          agent that owns the step (designer for seed,
                          critic for stress, etc.)
  - agent.py            → records each tool.call/tool.result that the
                          Gemini tool-calling loop fires
  - chem_resistance.py  → records harden Gemini suggestions as critic
                          actions
  - workbench.py        → records /design slash command invocations
                          as designer actions

The recorder writes to:

  1. workspace.playground.store.PlaygroundStore.append_action — DB
     persistence so the Action Log card shows full history across
     refreshes.
  2. an in-memory deque per session — fast SSE / poll for the live
     Agents container UI without round-tripping through SQLite.

Both are best-effort; failures are swallowed so a logging hiccup never
breaks the main path.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, asdict, field
from threading import RLock
from typing import Any, Optional

log = logging.getLogger("api.agent_activity")

_MAX_PER_SESSION = 400  # in-memory ring per session
_lock = RLock()
_recent: dict[str, deque[dict[str, Any]]] = defaultdict(
    lambda: deque(maxlen=_MAX_PER_SESSION)
)
# SSE event bus: per-session asyncio.Queue chain. Subscribers (UI clients
# via /agent-live/stream) get every record() the moment it lands. We
# fan-out to ALL subscribers so multiple tabs of the Agents container
# stay in lockstep.
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


# Approximate Gemini Pro 2.5 pricing (USD per million tokens). Used to
# render a running cost meter in the Agents Hub. Easy to update if pricing
# changes; not load-bearing for any business logic.
_PRICE_PER_M_INPUT  = 1.25   # USD / 1M input tokens
_PRICE_PER_M_OUTPUT = 10.0   # USD / 1M output tokens


@dataclass
class ActionRecord:
    id: str
    session_id: str
    ts: float
    agent_name: str        # designer | critic | editor | strategist | orchestrator
    action_type: str       # propose | critique | edit | decide | route | tool_call | …
    message_text: str = ""
    target_molecule_id: Optional[str] = None
    target_atom_idx: Optional[int] = None
    confidence: float = 0.0
    elapsed_ms: int = 0
    status: str = "ok"     # ok | error | running
    references: dict[str, Any] | None = None
    # ── v2 fields ────────────────────────────────────────────────
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    # which agent triggered this one — drives the handoff edge map
    triggered_by: Optional[str] = None
    # parent run id (workflow run, orchestrator run) — drives the
    # decision-tree drilldown
    parent_run_id: Optional[str] = None
    # Optional category tags for filtering (gemini, tool, edit, …)
    tags: list[str] = field(default_factory=list)


# ────────────────────────────────────────────────────────────────────
# Public write API

def record(
    session_id: str,
    agent: str,
    action_type: str,
    message: str = "",
    *,
    molecule_id: Optional[str] = None,
    atom_idx: Optional[int] = None,
    confidence: float = 0.0,
    elapsed_ms: int = 0,
    status: str = "ok",
    references: Optional[dict[str, Any]] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    triggered_by: Optional[str] = None,
    parent_run_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> ActionRecord:
    """Append a single agent action. Best-effort — swallows DB errors.
    Also pushes to all live SSE subscribers so the Agents Hub repaints
    without polling."""
    if not session_id or not agent or not action_type:
        return ActionRecord(
            id="", session_id=session_id or "",
            ts=time.time(), agent_name=agent or "?",
            action_type=action_type or "?",
        )

    cost = (tokens_in / 1e6) * _PRICE_PER_M_INPUT \
         + (tokens_out / 1e6) * _PRICE_PER_M_OUTPUT

    # Auto-detect last actor → handoff edge if not explicit
    if triggered_by is None:
        with _lock:
            ring = _recent.get(session_id)
            if ring:
                for prev in reversed(ring):
                    if prev.get("agent_name") != agent.lower():
                        triggered_by = prev.get("agent_name")
                        break

    rec = ActionRecord(
        id=uuid.uuid4().hex[:12],
        session_id=session_id,
        ts=time.time(),
        agent_name=agent.lower(),
        action_type=action_type,
        message_text=(message or "")[:1500],
        target_molecule_id=molecule_id,
        target_atom_idx=atom_idx,
        confidence=float(confidence or 0.0),
        elapsed_ms=int(elapsed_ms or 0),
        status=status,
        references=references or {},
        tokens_in=int(tokens_in or 0),
        tokens_out=int(tokens_out or 0),
        cost_usd=round(cost, 6),
        triggered_by=triggered_by,
        parent_run_id=parent_run_id,
        tags=list(tags or []),
    )

    # In-memory ring (always)
    with _lock:
        _recent[session_id].append(asdict(rec))
        subs = list(_subscribers.get(session_id, ()))

    # SSE fan-out (best effort, drop-on-full)
    payload = asdict(rec)
    for q in subs:
        try:
            q.put_nowait(payload)
        except Exception:
            pass

    # DB persistence (best effort)
    try:
        from workspace.playground.store import get_store, AgentAction as DBAction
        get_store().append_action(DBAction(
            id=rec.id,
            session_id=rec.session_id,
            ts=rec.ts,
            agent_name=rec.agent_name,
            action_type=rec.action_type,
            target_molecule_id=rec.target_molecule_id,
            target_atom_idx=rec.target_atom_idx,
            message_text=rec.message_text,
            confidence=rec.confidence,
            references={**(rec.references or {}),
                        "tokens_in": rec.tokens_in,
                        "tokens_out": rec.tokens_out,
                        "cost_usd": rec.cost_usd,
                        "triggered_by": rec.triggered_by,
                        "parent_run_id": rec.parent_run_id,
                        "tags": rec.tags},
        ))
    except Exception as exc:  # noqa: BLE001
        log.debug("append_action failed (non-fatal): %s", exc)

    return rec


# ────────────────────────────────────────────────────────────────────
# SSE pub/sub

def subscribe(session_id: str) -> asyncio.Queue:
    """Register a live subscriber. Caller is responsible for unsubscribe."""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    with _lock:
        _subscribers[session_id].append(q)
    return q


def unsubscribe(session_id: str, q: asyncio.Queue) -> None:
    with _lock:
        bucket = _subscribers.get(session_id)
        if bucket and q in bucket:
            bucket.remove(q)
        if bucket is not None and not bucket:
            _subscribers.pop(session_id, None)


# ────────────────────────────────────────────────────────────────────
# Public read API — fast in-memory snapshot

def recent(session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """In-memory snapshot of recent actions for live UI polls. Falls
    back to DB if the in-memory ring is empty (e.g. after restart)."""
    with _lock:
        items = list(_recent.get(session_id) or [])
    if items:
        return items[-limit:]
    # Cold start fallback — pull from DB so the panel still populates
    try:
        from workspace.playground.store import get_store
        rows = get_store().list_actions(session_id, limit=limit)
        return rows or []
    except Exception:
        return []


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(pct / 100.0 * (len(s) - 1)))))
    return float(s[k])


def metrics(session_id: str) -> dict[str, Any]:
    """Aggregate per-agent KPIs from the in-memory ring (or DB
    fallback). Cheap enough to call on every UI refresh."""
    rows = recent(session_id, limit=500)
    AGENTS = ["designer", "critic", "editor", "strategist", "orchestrator"]
    empty_agent = lambda a: {
        "agent": a, "n_actions": 0, "avg_latency_ms": 0,
        "sum_latency_ms": 0,
        "p50_ms": 0, "p95_ms": 0, "p99_ms": 0,
        "avg_confidence": 0.0, "ok_rate": 1.0, "error_count": 0,
        "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
        "last_ts": None, "last_action": None,
        "action_types": {},
    }
    if not rows:
        return {
            "session": session_id,
            "agents": [empty_agent(a) for a in AGENTS],
            "total_actions": 0, "duration_s": 0.0,
            "total_tokens_in": 0, "total_tokens_out": 0,
            "total_cost_usd": 0.0, "total_errors": 0,
        }
    ts_min = min(r.get("ts", 0) for r in rows)
    ts_max = max(r.get("ts", 0) for r in rows)
    out = []
    total_in = total_out = 0
    total_cost = 0.0
    total_err = 0
    for ag in AGENTS:
        ag_rows = [r for r in rows if (r.get("agent_name") or "").lower() == ag]
        if not ag_rows:
            out.append(empty_agent(ag))
            continue
        latencies = [r.get("elapsed_ms", 0) for r in ag_rows if r.get("elapsed_ms")]
        confs = [r.get("confidence", 0) for r in ag_rows if r.get("confidence")]
        ok_count = sum(1 for r in ag_rows if (r.get("status") or "ok") == "ok")
        err_count = sum(1 for r in ag_rows if (r.get("status") or "ok") == "error")
        ag_in = sum(int(r.get("tokens_in") or 0) for r in ag_rows)
        ag_out = sum(int(r.get("tokens_out") or 0) for r in ag_rows)
        ag_cost = sum(float(r.get("cost_usd") or 0.0) for r in ag_rows)
        total_in += ag_in
        total_out += ag_out
        total_cost += ag_cost
        total_err += err_count
        types: dict[str, int] = {}
        for r in ag_rows:
            t = r.get("action_type") or "unknown"
            types[t] = types.get(t, 0) + 1
        last = ag_rows[-1]
        out.append({
            "agent": ag,
            "n_actions": len(ag_rows),
            "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
            "sum_latency_ms": int(sum(latencies)) if latencies else 0,
            "p50_ms": int(_percentile(latencies, 50)),
            "p95_ms": int(_percentile(latencies, 95)),
            "p99_ms": int(_percentile(latencies, 99)),
            "avg_confidence": round(sum(confs) / len(confs), 3) if confs else 0.0,
            "ok_rate": round(ok_count / len(ag_rows), 3),
            "error_count": err_count,
            "tokens_in": ag_in,
            "tokens_out": ag_out,
            "cost_usd": round(ag_cost, 6),
            "last_ts": last.get("ts"),
            "last_action": (last.get("action_type") or "") + " · " + (last.get("message_text") or "")[:60],
            "action_types": types,
        })
    return {
        "session": session_id,
        "agents": out,
        "total_actions": len(rows),
        "duration_s": round(ts_max - ts_min, 2),
        "total_tokens_in": total_in,
        "total_tokens_out": total_out,
        "total_cost_usd": round(total_cost, 6),
        "total_errors": total_err,
    }


def handoffs(session_id: str) -> dict[str, Any]:
    """Build a directed edge map of agent handoffs — each time an action
    has triggered_by != self, count the edge. Drives a tiny graph viz
    showing how the agents collaborate (orchestrator → strategist →
    critic → editor)."""
    rows = recent(session_id, limit=2000)
    edges: dict[tuple[str, str], int] = {}
    for r in rows:
        src = (r.get("triggered_by") or "").lower()
        dst = (r.get("agent_name") or "").lower()
        if src and dst and src != dst:
            edges[(src, dst)] = edges.get((src, dst), 0) + 1
    return {
        "session": session_id,
        "edges": [{"from": a, "to": b, "count": n}
                  for (a, b), n in sorted(edges.items(), key=lambda x: -x[1])],
    }


def errors(session_id: str, limit: int = 30) -> dict[str, Any]:
    """Return only error-status actions — drives an alerts panel."""
    rows = [r for r in recent(session_id, limit=2000) if (r.get("status") or "ok") == "error"]
    return {"session": session_id, "errors": rows[-limit:]}


def timeline(session_id: str, bucket_s: float = 5.0, limit_buckets: int = 60) -> dict[str, Any]:
    """Per-agent action counts bucketed by time — drives the
    sparklines in the Agents container's metrics card."""
    rows = recent(session_id, limit=2000)
    AGENTS = ["designer", "critic", "editor", "strategist", "orchestrator"]
    if not rows:
        return {"session": session_id, "buckets": [], "by_agent": {a: [] for a in AGENTS}}
    ts_min = min(r.get("ts", 0) for r in rows)
    ts_max = max(r.get("ts", 0) for r in rows)
    n = max(1, min(limit_buckets, int((ts_max - ts_min) / bucket_s) + 1))
    by_agent: dict[str, list[int]] = {a: [0] * n for a in AGENTS}
    bucket_starts: list[float] = []
    for i in range(n):
        bucket_starts.append(ts_min + i * bucket_s)
    for r in rows:
        ag = (r.get("agent_name") or "").lower()
        if ag not in by_agent:
            continue
        idx = min(n - 1, int((r.get("ts", ts_min) - ts_min) / bucket_s))
        by_agent[ag][idx] += 1
    return {
        "session": session_id,
        "bucket_s": bucket_s,
        "buckets": bucket_starts,
        "by_agent": by_agent,
    }


def clear(session_id: str) -> None:
    with _lock:
        _recent.pop(session_id, None)
