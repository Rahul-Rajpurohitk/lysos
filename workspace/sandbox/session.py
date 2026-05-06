"""SandboxSession — top-level container.

A SandboxSession bundles:
  - a SandboxRuntime (one Python subprocess for cells)
  - a Scene (3D scene state with event log)
  - the active SMILES candidate
  - the active target pathogen

This is the per-user-session object the FastAPI server holds in memory
during a connection. On disconnect we serialize and persist; on reconnect
we replay the event log and restart the runtime.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .runtime import Cell, SandboxRuntime
from .scene import Scene, SceneEvent

log = logging.getLogger("workbench.sandbox.session")


@dataclass
class SessionMeta:
    session_id: str
    user_id: str
    created_at: float = field(default_factory=time.time)
    active_smiles: Optional[str] = None
    active_target: Optional[str] = None
    settings: dict[str, Any] = field(default_factory=dict)


class SandboxSession:
    """Owns one runtime + one scene per user session.

    Usage:
        sess = SandboxSession(session_id="x", user_id="u")
        await sess.start()
        cell = await sess.run_cell("print('hi')")
        sess.scene.add_object(...)
        await sess.stop()
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        user_id: str = "anonymous",
        persist_root: Optional[Path] = None,
    ):
        self.meta = SessionMeta(
            session_id=session_id or uuid.uuid4().hex[:16],
            user_id=user_id,
        )
        self.persist_root = persist_root or (Path.home() / ".lysos" / "sessions")
        self.persist_dir = self.persist_root / self.meta.session_id
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.runtime = SandboxRuntime(
            session_id=self.meta.session_id,
            persist_dir=self.persist_dir,
        )
        self.scene = Scene(scene_id=self.meta.session_id + "-scene")
        self._scene_events_persisted = 0

    # ---- lifecycle ----

    async def start(self) -> None:
        await self.runtime.start()
        self._write_meta()

    async def stop(self) -> None:
        await self.runtime.stop()
        self._snapshot()

    # ---- cell ops ----

    async def run_cell(self, code: str) -> Cell:
        cell = await self.runtime.run_cell(code)
        # Apply any scene_events the cell emitted to the canonical Scene
        for ev_dict in cell.scene_events:
            try:
                from .scene import SceneEvent, SceneEventKind
                ev = SceneEvent(
                    event_id=ev_dict.get("event_id") or uuid.uuid4().hex[:12],
                    kind=SceneEventKind(ev_dict.get("kind", "update_object")),
                    payload=ev_dict.get("payload", {}),
                    actor="cell",
                )
                self.scene.apply_event(ev)
            except Exception as exc:  # noqa: BLE001
                log.warning("session %s: bad cell scene_event: %s", self.meta.session_id, exc)
        self._snapshot_scene_delta()
        return cell

    # ---- scene ops ----

    def emit_scene(self, kind: str, **payload: Any) -> SceneEvent:
        from .scene import SceneEvent, SceneEventKind
        ev = SceneEvent(
            event_id=uuid.uuid4().hex[:12],
            kind=SceneEventKind(kind),
            payload=payload,
            actor="agent",
        )
        self.scene.apply_event(ev)
        self._snapshot_scene_delta()
        return ev

    # ---- selection ----

    def set_active_smiles(self, smiles: Optional[str]) -> None:
        self.meta.active_smiles = smiles
        self._write_meta()

    def set_active_target(self, target: Optional[str]) -> None:
        self.meta.active_target = target
        self._write_meta()

    # ---- persistence ----

    def _write_meta(self) -> None:
        try:
            (self.persist_dir / "meta.json").write_text(
                json.dumps(self.meta.__dict__, indent=2, default=str)
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("session %s: meta persist failed: %s", self.meta.session_id, exc)

    def _snapshot_scene_delta(self) -> None:
        """Append only NEW scene events to scene.jsonl on every change."""
        try:
            new_events = self.scene.event_log(since=self._scene_events_persisted)
            if not new_events:
                return
            with (self.persist_dir / "scene.jsonl").open("a") as f:
                for ev in new_events:
                    f.write(json.dumps(ev, default=str) + "\n")
            self._scene_events_persisted += len(new_events)
        except Exception as exc:  # noqa: BLE001
            log.warning("session %s: scene persist failed: %s",
                        self.meta.session_id, exc)

    def _snapshot(self) -> None:
        """Full snapshot on shutdown."""
        try:
            (self.persist_dir / "scene_state.json").write_text(
                json.dumps(self.scene.current_state(), indent=2, default=str)
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("session %s: scene snapshot failed: %s",
                        self.meta.session_id, exc)

    # ---- API surface for harness ----

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta.__dict__,
            "scene": self.scene.current_state(),
            "n_cells": len(self.runtime.cells()),
        }
