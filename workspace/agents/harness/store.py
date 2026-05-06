"""SessionStore — DB-backed session persistence (SQLite for dev,
Postgres-compatible schema).

Why a real DB instead of just JSONL on disk:
- Multi-replica scaling: when we go from one box to many (post-hackathon),
  sessions need to be reachable from any replica. JSONL on local disk
  doesn't survive that.
- Index queries: "list all sessions for user X", "find candidates with
  composite > 1.0" — those are O(rows) scans on JSONL but O(log n) with
  indexes.
- Atomic writes: SQLite single-writer guarantees. JSONL append + rename
  needs careful ordering.

Schema (deliberately minimal; can grow):

    sessions(id PK, user_id, created_at, updated_at, active_smiles,
             active_target, settings_json)
    candidates(id PK, session_id FK, smiles, parent_id, op_chain_json,
               composite, score_json, created_at)
    cells(id PK, session_id FK, code, status, stdout, stderr,
          structured_json, scene_events_json, started_at, finished_at,
          elapsed_ms)
    trace(id PK AUTOINCREMENT, session_id FK, type, payload_json,
          parent_id, ts, elapsed_ms)

The path is configurable: defaults to ~/.lysos/lysos.db. Override via
env LYSOS_DB_PATH. For Postgres later, swap the connector — schema is
SQL-portable.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterator, Optional

log = logging.getLogger("workbench.agents.harness.store")

DEFAULT_DB_PATH = Path(os.environ.get(
    "LYSOS_DB_PATH",
    str(Path.home() / ".lysos" / "lysos.db"),
))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id              TEXT PRIMARY KEY,
  user_id         TEXT NOT NULL,
  created_at      REAL NOT NULL,
  updated_at      REAL NOT NULL,
  active_smiles   TEXT,
  active_target   TEXT,
  settings_json   TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);

CREATE TABLE IF NOT EXISTS candidates (
  id              TEXT PRIMARY KEY,
  session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  smiles          TEXT NOT NULL,
  parent_id       TEXT,
  op_chain_json   TEXT,
  composite       REAL,
  score_json      TEXT,
  created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS candidates_session_idx ON candidates(session_id);
CREATE INDEX IF NOT EXISTS candidates_composite_idx ON candidates(composite);

CREATE TABLE IF NOT EXISTS cells (
  id                TEXT PRIMARY KEY,
  session_id        TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  code              TEXT NOT NULL,
  status            TEXT NOT NULL,
  stdout            TEXT,
  stderr            TEXT,
  structured_json   TEXT,
  scene_events_json TEXT,
  started_at        REAL,
  finished_at       REAL,
  elapsed_ms        INTEGER
);
CREATE INDEX IF NOT EXISTS cells_session_idx ON cells(session_id);

CREATE TABLE IF NOT EXISTS trace (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  type            TEXT NOT NULL,
  payload_json    TEXT,
  parent_id       TEXT,
  ts              REAL NOT NULL,
  elapsed_ms      INTEGER
);
CREATE INDEX IF NOT EXISTS trace_session_ts_idx ON trace(session_id, ts);
"""


class SessionStore:
    """Thread-safe SQLite session store."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    @contextlib.contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        # one connection per call — sqlite3 + threads behaves better.
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    # ---- sessions ----

    def upsert_session(
        self,
        session_id: str,
        user_id: str,
        active_smiles: Optional[str] = None,
        active_target: Optional[str] = None,
        settings: Optional[dict[str, Any]] = None,
    ) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, created_at, updated_at,
                                      active_smiles, active_target, settings_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  updated_at = excluded.updated_at,
                  active_smiles = excluded.active_smiles,
                  active_target = excluded.active_target,
                  settings_json = excluded.settings_json
                """,
                (session_id, user_id, now, now, active_smiles, active_target,
                 json.dumps(settings or {})),
            )

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["settings"] = json.loads(out.pop("settings_json") or "{}")
        return out

    def list_sessions_for_user(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE user_id = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    # ---- candidates ----

    def add_candidate(
        self,
        candidate_id: str,
        session_id: str,
        smiles: str,
        parent_id: Optional[str] = None,
        op_chain: Optional[list[str]] = None,
        composite: Optional[float] = None,
        score: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO candidates
                  (id, session_id, smiles, parent_id, op_chain_json,
                   composite, score_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (candidate_id, session_id, smiles, parent_id,
                 json.dumps(op_chain or []), composite,
                 json.dumps(score or {}), time.time()),
            )

    def list_candidates(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM candidates WHERE session_id = ? "
                "ORDER BY created_at ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["op_chain"] = json.loads(d.pop("op_chain_json") or "[]")
            d["score"] = json.loads(d.pop("score_json") or "{}")
            out.append(d)
        return out

    # ---- cells ----

    def save_cell(self, session_id: str, cell: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cells
                  (id, session_id, code, status, stdout, stderr,
                   structured_json, scene_events_json,
                   started_at, finished_at, elapsed_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cell["cell_id"], session_id, cell["code"], cell["status"],
                 cell.get("stdout"), cell.get("stderr"),
                 json.dumps(cell.get("structured") or {}),
                 json.dumps(cell.get("scene_events") or []),
                 cell.get("started_at"), cell.get("finished_at"),
                 cell.get("elapsed_ms")),
            )

    def list_cells(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM cells WHERE session_id = ? "
                "ORDER BY started_at ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["structured"] = json.loads(d.pop("structured_json") or "{}")
            d["scene_events"] = json.loads(d.pop("scene_events_json") or "[]")
            out.append(d)
        return out

    # ---- trace ----

    def append_trace(self, session_id: str, event: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO trace (session_id, type, payload_json,
                                   parent_id, ts, elapsed_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, event.get("type"),
                 json.dumps(event.get("payload") or {}),
                 event.get("parent_id"),
                 event.get("timestamp", time.time()),
                 event.get("elapsed_ms")),
            )

    def list_trace(self, session_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trace WHERE session_id = ? "
                "ORDER BY id ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
            out.append(d)
        return out


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_STORE: Optional[SessionStore] = None
_STORE_LOCK = threading.Lock()


def get_store() -> SessionStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = SessionStore()
        return _STORE
