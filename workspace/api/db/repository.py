"""Postgres repositories — sessions, candidates, tool_calls, agent_events.

Lazy connection: if LYSOS_DB_URL isn't set or Postgres isn't reachable, all
repo methods become no-ops. The in-memory store in workbench.py remains the
authoritative source for the current session lifetime; the DB is for
durable replay + branching across restarts.

On Day 4 (production) we make the DB authoritative.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

log = logging.getLogger("workbench.api.db")

DB_URL = os.environ.get("LYSOS_DB_URL")  # postgresql://...

_conn = None


def _get_conn():
    global _conn
    if _conn is not None:
        return _conn
    if not DB_URL:
        return None
    try:
        import psycopg
        _conn = psycopg.connect(DB_URL, autocommit=True)
        log.info("Postgres connected at %s", DB_URL.split("@")[-1])
        return _conn
    except Exception as exc:  # noqa: BLE001
        log.warning("Postgres unavailable: %s", exc)
        return None


def _execute(sql: str, params: tuple = ()) -> list[tuple]:
    conn = _get_conn()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            try:
                return cur.fetchall()
            except Exception:
                return []
    except Exception as exc:  # noqa: BLE001
        log.warning("DB query failed: %s", exc)
        return []


class SessionRepo:
    @staticmethod
    def insert(session_id: str, target_pathogen: str, mode: str, autonomy: str,
               constraints: list[dict], max_iterations: int) -> None:
        _execute(
            """INSERT INTO sessions
               (id, target_pathogen, mode, autonomy, constraints, max_iterations)
               VALUES (%s, %s, %s, %s, %s::jsonb, %s)
               ON CONFLICT (id) DO NOTHING""",
            (session_id, target_pathogen, mode, autonomy,
             json.dumps(constraints), max_iterations),
        )

    @staticmethod
    def update_termination(session_id: str, terminated: bool, reason: Optional[str]) -> None:
        _execute(
            """UPDATE sessions SET terminated=%s, termination_reason=%s,
               updated_at=NOW() WHERE id=%s""",
            (terminated, reason, session_id),
        )

    @staticmethod
    def get(session_id: str) -> Optional[dict]:
        rows = _execute(
            """SELECT id, target_pathogen, mode, autonomy, constraints,
                      max_iterations, iteration, terminated, termination_reason,
                      resistome_summary, created_at
               FROM sessions WHERE id=%s""",
            (session_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "session_id": str(r[0]),
            "target_pathogen": r[1],
            "mode": r[2],
            "autonomy": r[3],
            "constraints": r[4],
            "max_iterations": r[5],
            "iteration": r[6],
            "terminated": r[7],
            "termination_reason": r[8],
            "resistome_summary": r[9],
            "created_at": r[10].isoformat() if r[10] else None,
        }


class CandidateRepo:
    @staticmethod
    def insert(candidate_id: str, session_id: str, parent_id: Optional[str],
               smiles: str, pathogen: str, scores: dict,
               similar_to: list[str]) -> None:
        _execute(
            """INSERT INTO candidates
               (id, session_id, parent_id, smiles, pathogen, scores, similar_to)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
               ON CONFLICT (id) DO NOTHING""",
            (candidate_id, session_id, parent_id, smiles, pathogen,
             json.dumps(scores), similar_to),
        )

    @staticmethod
    def list_for_session(session_id: str) -> list[dict]:
        rows = _execute(
            """SELECT id, parent_id, smiles, pathogen, scores, similar_to, created_at
               FROM candidates WHERE session_id=%s ORDER BY created_at""",
            (session_id,),
        )
        return [
            {
                "id": str(r[0]),
                "parent_id": str(r[1]) if r[1] else None,
                "smiles": r[2],
                "pathogen": r[3],
                "scores": r[4],
                "similar_to": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ]


class ToolCallRepo:
    @staticmethod
    def insert(call_id: str, session_id: str, agent: str, tool_name: str,
               args: dict, result: Optional[dict], error: Optional[str],
               duration_ms: int) -> None:
        _execute(
            """INSERT INTO tool_calls
               (id, session_id, agent, tool_name, args, result, error, duration_ms)
               VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
               ON CONFLICT (id) DO NOTHING""",
            (call_id, session_id, agent, tool_name,
             json.dumps(args), json.dumps(result) if result else None,
             error, duration_ms),
        )


class EventRepo:
    @staticmethod
    def append(session_id: str, iteration: int, event_type: str,
               agent: Optional[str], payload: dict) -> None:
        _execute(
            """INSERT INTO agent_events (session_id, iteration, event_type, agent, payload)
               VALUES (%s, %s, %s, %s, %s::jsonb)""",
            (session_id, iteration, event_type, agent, json.dumps(payload)),
        )
