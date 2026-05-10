"""Champion table — per-pathogen reigning best candidate.

After every workflow run that produces a winner, we promote it (if it
beats the current champion on a configurable score). Used by:

  - Knowledge container's Champion panel (current best per pathogen)
  - A/B comparison cards in chat (new candidate vs reigning champion
    with Δ on every reward axis)
  - /champion slash command

Storage is sqlite (workspace.playground.store) so champions persist
across backend restarts. In-memory cache for hot reads.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from threading import RLock
from typing import Any, Optional

log = logging.getLogger("api.champions")

_lock = RLock()
_cache: dict[str, dict[str, Any]] = {}  # pathogen → champion record
_DB_TABLE = "lysos_champions"


def _ensure_table() -> None:
    """Create the champions table if it doesn't exist. Idempotent."""
    try:
        from workspace.playground.store import get_store
        conn = get_store()._conn  # noqa: SLF001 — keeping store's conn private  # noqa: SLF001 — store keeps the conn private
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_DB_TABLE} (
                pathogen TEXT PRIMARY KEY,
                smiles TEXT NOT NULL,
                composite REAL,
                robustness REAL,
                fitness REAL,
                scores_json TEXT,
                created_ts REAL,
                session_id TEXT,
                rationale TEXT
            )
        """)
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        log.debug("champions table init failed (non-fatal): %s", exc)


def _row_to_dict(row) -> dict[str, Any]:
    import json as _json
    return {
        "pathogen": row[0], "smiles": row[1],
        "composite": row[2], "robustness": row[3], "fitness": row[4],
        "scores": _json.loads(row[5] or "{}"),
        "created_ts": row[6],
        "session_id": row[7], "rationale": row[8] or "",
    }


def get(pathogen: str) -> Optional[dict[str, Any]]:
    """Read the reigning champion for a pathogen."""
    _ensure_table()
    pathogen = (pathogen or "MRSA").upper()
    with _lock:
        if pathogen in _cache:
            return _cache[pathogen]
    try:
        from workspace.playground.store import get_store
        conn = get_store()._conn  # noqa: SLF001 — keeping store's conn private
        row = conn.execute(
            f"SELECT pathogen, smiles, composite, robustness, fitness, "
            f"scores_json, created_ts, session_id, rationale "
            f"FROM {_DB_TABLE} WHERE pathogen = ?",
            (pathogen,),
        ).fetchone()
        if not row:
            return None
        rec = _row_to_dict(row)
        with _lock:
            _cache[pathogen] = rec
        return rec
    except Exception as exc:  # noqa: BLE001
        log.debug("champion get failed: %s", exc)
        return None


def all_champions() -> list[dict[str, Any]]:
    _ensure_table()
    try:
        from workspace.playground.store import get_store
        conn = get_store()._conn  # noqa: SLF001 — keeping store's conn private
        rows = conn.execute(
            f"SELECT pathogen, smiles, composite, robustness, fitness, "
            f"scores_json, created_ts, session_id, rationale "
            f"FROM {_DB_TABLE} ORDER BY pathogen"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


def propose(
    pathogen: str,
    smiles: str,
    composite: Optional[float] = None,
    robustness: Optional[float] = None,
    fitness: Optional[float] = None,
    scores: Optional[dict[str, float]] = None,
    session_id: str = "",
    rationale: str = "",
    *,
    score_axis: str = "fitness",  # "fitness" | "composite" | "robustness"
) -> dict[str, Any]:
    """Propose a new champion. If it beats the current one on
    `score_axis`, replace and return {"promoted": True, ...}. Otherwise
    return {"promoted": False, "current": <reigning>, "new": <proposed>}.
    """
    _ensure_table()
    pathogen = (pathogen or "MRSA").upper()
    fit = fitness if fitness is not None else (
        (composite or 0.0) * (robustness or 0.0)
    )
    proposed = {
        "pathogen": pathogen, "smiles": smiles,
        "composite": composite, "robustness": robustness, "fitness": fit,
        "scores": scores or {},
        "created_ts": time.time(),
        "session_id": session_id, "rationale": rationale,
    }
    current = get(pathogen)
    cur_val = (current or {}).get(score_axis) if current else None
    new_val = proposed.get(score_axis)
    if cur_val is not None and new_val is not None and new_val <= cur_val:
        return {"promoted": False, "current": current, "new": proposed,
                "score_axis": score_axis,
                "reason": f"{score_axis} {new_val:.3f} did not beat reigning {cur_val:.3f}"}
    # Promote
    try:
        import json as _json
        from workspace.playground.store import get_store
        conn = get_store()._conn  # noqa: SLF001 — keeping store's conn private
        conn.execute(
            f"INSERT OR REPLACE INTO {_DB_TABLE} "
            f"(pathogen, smiles, composite, robustness, fitness, "
            f" scores_json, created_ts, session_id, rationale) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (proposed["pathogen"], proposed["smiles"],
             proposed["composite"], proposed["robustness"], proposed["fitness"],
             _json.dumps(proposed["scores"]),
             proposed["created_ts"],
             proposed["session_id"], proposed["rationale"]),
        )
        conn.commit()
        with _lock:
            _cache[pathogen] = proposed
        return {"promoted": True, "current": current, "new": proposed,
                "score_axis": score_axis,
                "delta_fitness": (proposed["fitness"] or 0) - ((current or {}).get("fitness") or 0)}
    except Exception as exc:  # noqa: BLE001
        log.warning("champion propose failed: %s", exc)
        return {"promoted": False, "error": str(exc)}


def compare(
    pathogen: str,
    smiles: str,
    composite: Optional[float] = None,
    robustness: Optional[float] = None,
    scores: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """A/B head-to-head: returns the reigning champion + the new
    candidate + per-axis Δ. Used by the chat A/B card."""
    pathogen = (pathogen or "MRSA").upper()
    champ = get(pathogen)
    new = {
        "smiles": smiles,
        "composite": composite or 0.0,
        "robustness": robustness or 0.0,
        "fitness": (composite or 0.0) * (robustness or 0.0),
        "scores": scores or {},
    }
    if not champ:
        return {"pathogen": pathogen, "champion": None, "candidate": new,
                "verdict": "no reigning champion — promote this if you like."}
    deltas = {
        "composite": (new["composite"] or 0) - (champ["composite"] or 0),
        "robustness": (new["robustness"] or 0) - (champ["robustness"] or 0),
        "fitness": (new["fitness"] or 0) - (champ["fitness"] or 0),
    }
    # Per-axis delta (intersect axes that exist in both)
    axis_deltas: dict[str, float] = {}
    for k, v in (new["scores"] or {}).items():
        cv = (champ["scores"] or {}).get(k)
        if cv is not None and isinstance(v, (int, float)):
            axis_deltas[k] = v - cv
    verdict = (
        "candidate beats champion" if deltas["fitness"] > 0
        else "candidate is worse than champion" if deltas["fitness"] < 0
        else "tie on fitness — drill into per-axis deltas"
    )
    return {
        "pathogen": pathogen,
        "champion": champ,
        "candidate": new,
        "deltas": deltas,
        "axis_deltas": axis_deltas,
        "verdict": verdict,
    }
