"""Per-session memory layer for the Lysos agentic stack.

Keeps a rolling, bounded record of what each session has done so the
LLM (Gemini Pro / Flash) gets real conversational + chemistry context
on every call instead of starting from zero. Entries are compact and
typed; the layer renders them into a markdown brief that's prepended
to system prompts.

Storage is in-memory (dict-of-deques) — same lifecycle as the rest of
the FastAPI process. Crashes lose memory, which is fine for the demo;
upgrading to Redis or sqlite is a one-file swap.

Public API:
    record(session_id, kind, payload)   – push an event
    snapshot(session_id, kinds=None)    – list of recent events
    brief(session_id)                   – markdown context block for LLM
    clear(session_id)                   – reset
"""
from __future__ import annotations

from collections import deque
from threading import RLock
from time import time
from typing import Any, Iterable, Optional

# ── tunable bounds ──────────────────────────────────────────────────
_MAX_PER_SESSION = 64       # events per session before LRU eviction
_MAX_BRIEF_CHARS = 4000     # safety cap on rendered context size

_lock = RLock()
_store: dict[str, deque[dict[str, Any]]] = {}


# ────────────────────────────────────────────────────────────────────
# Write path

def record(session_id: str, kind: str, payload: dict[str, Any]) -> None:
    """Append an event. `kind` is a short tag (e.g. 'score', 'harden',
    'load', 'design', 'user', 'workflow'); `payload` is a small dict
    of the salient fields (smiles, composite, vulnerable_atoms, etc.)."""
    if not session_id:
        return
    item = {"kind": kind, "ts": time(), **payload}
    with _lock:
        q = _store.get(session_id)
        if q is None:
            q = deque(maxlen=_MAX_PER_SESSION)
            _store[session_id] = q
        q.append(item)


# ────────────────────────────────────────────────────────────────────
# Read path

def snapshot(session_id: str, kinds: Optional[Iterable[str]] = None) -> list[dict[str, Any]]:
    """Return recent events (oldest first), optionally filtered by kind."""
    with _lock:
        q = _store.get(session_id)
        if q is None:
            return []
        items = list(q)
    if kinds:
        s = set(kinds)
        items = [e for e in items if e.get("kind") in s]
    return items


def clear(session_id: str) -> None:
    with _lock:
        _store.pop(session_id, None)


# ────────────────────────────────────────────────────────────────────
# Brief renderer — compact markdown for LLM system prompts

def brief(session_id: str) -> str:
    """Render the recent session activity as a tight markdown block.
    Returns "" if the session has no recorded activity. The brief is
    deduped (collapses repeat smiles loads) and clamped to
    _MAX_BRIEF_CHARS so it never blows the context budget."""
    items = snapshot(session_id)
    if not items:
        return ""

    # Latest values per kind
    last_user: Optional[str] = None
    last_load: Optional[str] = None
    last_score: Optional[dict] = None
    last_harden: Optional[dict] = None
    candidates: list[dict] = []
    workflows: list[dict] = []

    for e in items:
        k = e.get("kind")
        if k == "user":
            last_user = e.get("text")
        elif k == "load":
            last_load = e.get("smiles")
        elif k == "score":
            last_score = e
        elif k == "harden":
            last_harden = e
        elif k == "candidate":
            candidates.append(e)
        elif k == "workflow":
            workflows.append(e)

    lines = ["## Session memory"]
    if last_user:
        lines.append(f"- last user prompt: {last_user[:160]}")
    if last_load:
        lines.append(f"- current SMILES: `{last_load}`")
    if last_score:
        comp = last_score.get("composite")
        weakest = last_score.get("weakest")
        if comp is not None:
            lines.append(f"- last score: composite={comp:.3f}"
                         + (f", weakest={weakest}" if weakest else ""))
    if last_harden:
        rb = last_harden.get("robustness")
        atoms = last_harden.get("vulnerable_atoms") or []
        if rb is not None:
            lines.append(f"- last harden: robustness={rb:.3f}, "
                         f"vulnerable_atoms={atoms[:5]}")
    if candidates:
        # Show the last 3 unique candidate smiles seen
        seen = []
        for c in reversed(candidates):
            smi = c.get("smiles")
            if smi and smi not in seen:
                seen.append(smi)
            if len(seen) >= 3:
                break
        if seen:
            lines.append("- recent candidates: " + " · ".join(f"`{s}`" for s in seen))
    if workflows:
        recent = workflows[-3:]
        lines.append("- recent workflows: " + " · ".join(
            f"{w.get('name')}({w.get('status', '?')})" for w in recent))

    out = "\n".join(lines)
    if len(out) > _MAX_BRIEF_CHARS:
        out = out[:_MAX_BRIEF_CHARS] + "\n…(truncated)"
    return out
