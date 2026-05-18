"""service_store.py — shared artifact persistence for the Lysos
productized service layer.

Every productized service (Synthesis Make-Route, IP/FTO Sentinel,
ADMET Observatory, Regimen Lab, Campaign Autopilot) writes its outputs
here as JSON artifacts through ONE CRUD surface — one schema, one set
of guarantees, no per-service persistence reinvention.

Storage: SQLite at $LYSOS_SERVICES_DB (default ~/.lysos/services.sqlite),
kept SEPARATE from the playground DB so a service-layer change can
never risk the molecule / edit / score history.

Schema — service_artifacts:
  id            TEXT  PK    16-hex uuid
  kind          TEXT        'synthesis_route' | 'fto_report' | 'admet_profile'
                            | 'regimen' | 'campaign' | 'dossier' | ...
  session_id    TEXT        owning chat session (nullable)
  smiles        TEXT        subject molecule (nullable)
  title         TEXT        human label
  created_at    REAL
  updated_at    REAL
  payload_json  TEXT        the service-specific result blob
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("api.service_store")

_DEFAULT_DB = Path.home() / ".lysos" / "services.sqlite"
_LOCK = threading.Lock()
_CONN: Optional[sqlite3.Connection] = None


def _conn() -> sqlite3.Connection:
    """Lazily open the SQLite connection + ensure the schema exists.
    One shared connection (check_same_thread=False) guarded by _LOCK."""
    global _CONN
    if _CONN is not None:
        return _CONN
    db_path = Path(os.environ.get("LYSOS_SERVICES_DB", str(_DEFAULT_DB)))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS service_artifacts (
            id            TEXT PRIMARY KEY,
            kind          TEXT NOT NULL,
            session_id    TEXT,
            smiles        TEXT,
            title         TEXT,
            created_at    REAL NOT NULL,
            updated_at    REAL NOT NULL,
            payload_json  TEXT NOT NULL
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_kind ON service_artifacts(kind)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_session ON service_artifacts(session_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_smiles ON service_artifacts(smiles)")
    c.commit()
    _CONN = c
    log.info("service_store ready at %s", db_path)
    return c


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw = d.pop("payload_json", None)
    try:
        d["payload"] = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        d["payload"] = {}
    return d


def save_artifact(
    kind: str,
    payload: dict[str, Any],
    *,
    session_id: Optional[str] = None,
    smiles: Optional[str] = None,
    title: Optional[str] = None,
    artifact_id: Optional[str] = None,
) -> dict[str, Any]:
    """Insert a new artifact, or overwrite an existing one when
    `artifact_id` is supplied and already present. created_at is
    preserved across overwrites; updated_at always advances."""
    aid = artifact_id or uuid.uuid4().hex[:16]
    now = time.time()
    with _LOCK:
        c = _conn()
        existing = c.execute(
            "SELECT created_at FROM service_artifacts WHERE id=?", (aid,)
        ).fetchone()
        created = existing["created_at"] if existing else now
        c.execute(
            "INSERT OR REPLACE INTO service_artifacts "
            "(id, kind, session_id, smiles, title, created_at, updated_at, payload_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (aid, kind, session_id, smiles, title, created, now,
             json.dumps(payload, default=str)),
        )
        c.commit()
    rec = get_artifact(aid)
    assert rec is not None  # just written
    return rec


def get_artifact(artifact_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        row = _conn().execute(
            "SELECT * FROM service_artifacts WHERE id=?", (artifact_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_artifacts(
    *,
    kind: Optional[str] = None,
    session_id: Optional[str] = None,
    smiles: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List artifacts newest-first, optionally filtered. All filters
    are AND-combined."""
    clauses: list[str] = []
    params: list[Any] = []
    if kind:
        clauses.append("kind=?"); params.append(kind)
    if session_id:
        clauses.append("session_id=?"); params.append(session_id)
    if smiles:
        clauses.append("smiles=?"); params.append(smiles)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, min(int(limit), 500)))
    with _LOCK:
        rows = _conn().execute(
            f"SELECT * FROM service_artifacts{where} ORDER BY updated_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_artifact(
    artifact_id: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    title: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Patch an artifact's payload and/or title. Returns None if the
    artifact doesn't exist."""
    cur = get_artifact(artifact_id)
    if cur is None:
        return None
    return save_artifact(
        cur["kind"],
        payload if payload is not None else cur["payload"],
        session_id=cur.get("session_id"),
        smiles=cur.get("smiles"),
        title=title if title is not None else cur.get("title"),
        artifact_id=artifact_id,
    )


def delete_artifact(artifact_id: str) -> bool:
    """Delete an artifact. Returns True if a row was removed."""
    with _LOCK:
        c = _conn()
        cur = c.execute("DELETE FROM service_artifacts WHERE id=?", (artifact_id,))
        c.commit()
        return cur.rowcount > 0


def count_artifacts(*, kind: Optional[str] = None, session_id: Optional[str] = None) -> int:
    clauses: list[str] = []
    params: list[Any] = []
    if kind:
        clauses.append("kind=?"); params.append(kind)
    if session_id:
        clauses.append("session_id=?"); params.append(session_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _LOCK:
        row = _conn().execute(
            f"SELECT COUNT(*) AS n FROM service_artifacts{where}", tuple(params)
        ).fetchone()
    return int(row["n"]) if row else 0
