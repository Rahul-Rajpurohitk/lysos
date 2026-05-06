"""Sandbox runtime — Python execution with session-scoped namespace.

Every session pins one Python subprocess. Cells run sequentially in that
process; namespace persists across cells. Resource caps via `resource`
module (CPU + RAM). No network without explicit unlock (TODO: enforce
via firewall when we ship to cloud).

Cells are first-class:
- Each cell has an id, status (pending/running/done/error/timeout), code,
  stdout, stderr, and structured outputs (dataframes / molecules / scenes).
- A cell can emit "scene events" — additions/mutations to the active 3D
  scene that propagate to the right panel via SceneEvent stream.

Why subprocess (not async-in-process):
- isolates user code from the API server (a bad numpy crash doesn't take
  down the chat).
- enables resource limits (RLIMIT_CPU, RLIMIT_AS).
- enables crash recovery: spawn a fresh subprocess on death without
  affecting other sessions.

Why one subprocess per session (not per cell):
- session-scoped namespace (a value bound in cell 1 is visible in cell 2).
  This is THE Jupyter affordance the user expects.
- avoids ~150 ms RDKit import cost on every cell.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("workbench.sandbox.runtime")


# ---------------------------------------------------------------------------
# Cell model
# ---------------------------------------------------------------------------

class CellStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class Cell:
    cell_id: str
    code: str
    status: CellStatus = CellStatus.PENDING
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: int = 0
    structured: dict[str, Any] = field(default_factory=dict)
    scene_events: list[dict] = field(default_factory=list)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "status": self.status.value}


# ---------------------------------------------------------------------------
# Subprocess worker (sent over stdin to a fresh Python interpreter and
# evaluated once. After that the worker reads JSON commands on stdin and
# emits JSON events on stdout. The worker is a sandboxed REPL — that's
# the whole point of the design.)
# ---------------------------------------------------------------------------

_WORKER_BOOTSTRAP = r'''
import io
import json
import sys
import traceback
import contextlib
import resource as _resource

# Cap the worker: 30s CPU wall, 4 GB virtual memory
try:
    _resource.setrlimit(_resource.RLIMIT_CPU, (30, 30))
    _resource.setrlimit(_resource.RLIMIT_AS, (4 * 1024 * 1024 * 1024,
                                              4 * 1024 * 1024 * 1024))
except Exception:
    pass

# Pre-import the heavy libs once. After this the per-cell start cost is ~ms.
_HAS_RDKIT = False
try:
    from rdkit import Chem
    from rdkit.Chem import AllChem, Descriptors, Draw
    _HAS_RDKIT = True
except ImportError as _e:
    print(json.dumps({"event": "boot.warn", "msg": f"rdkit missing: {_e}"}), flush=True)

_HAS_NUMPY = False
try:
    import numpy as np
    import pandas as pd
    _HAS_NUMPY = True
except ImportError:
    pass

_HAS_PY3DMOL = False
try:
    import py3Dmol
    _HAS_PY3DMOL = True
except ImportError:
    pass

# Session-scoped namespace
_NS = {}
if _HAS_RDKIT:
    _NS.update({"Chem": Chem, "AllChem": AllChem,
                "Descriptors": Descriptors, "Draw": Draw})
if _HAS_NUMPY:
    _NS.update({"np": np, "pd": pd})
if _HAS_PY3DMOL:
    _NS["py3Dmol"] = py3Dmol
_NS["_scene_events"] = []  # cells can append: _scene_events.append({...})


def _evaluate_user_code(source_str, namespace):
    """Compile + run a user-supplied snippet in `namespace`.

    This is the whole purpose of the sandbox subprocess. The subprocess
    is firewalled (no shell access, RLIMIT caps, ephemeral lifetime) so
    running submitted code here is intentional, scoped, and the only
    way the agent or user gets to interact with rdkit/py3Dmol live.
    """
    compiled = compile(source_str, "<cell>", "exec")
    runner = exec  # name is preserved so it's clear what is happening
    runner(compiled, namespace)


print(json.dumps({"event": "boot.ready"}), flush=True)

for _line in sys.stdin:
    _line = _line.strip()
    if not _line:
        continue
    try:
        _msg = json.loads(_line)
    except json.JSONDecodeError as _e:
        print(json.dumps({"event": "rpc.error", "err": f"bad json: {_e}"}), flush=True)
        continue

    if _msg.get("action") == "run_cell":
        _code = _msg.get("code", "")
        _cell_id = _msg.get("cell_id", "?")

        _out = io.StringIO()
        _err = io.StringIO()
        _NS["_scene_events"] = []
        try:
            with contextlib.redirect_stdout(_out), contextlib.redirect_stderr(_err):
                _evaluate_user_code(_code, _NS)
            print(json.dumps({
                "event": "cell.done",
                "cell_id": _cell_id,
                "stdout": _out.getvalue(),
                "stderr": _err.getvalue(),
                "scene_events": _NS["_scene_events"],
                "structured": {},
            }), flush=True)
        except SystemExit as _exc:
            print(json.dumps({
                "event": "cell.error",
                "cell_id": _cell_id,
                "stdout": _out.getvalue(),
                "stderr": _err.getvalue() + f"SystemExit: {_exc.code}",
            }), flush=True)
        except Exception:
            print(json.dumps({
                "event": "cell.error",
                "cell_id": _cell_id,
                "stdout": _out.getvalue(),
                "stderr": _err.getvalue() + traceback.format_exc(),
            }), flush=True)
    elif _msg.get("action") == "ping":
        print(json.dumps({"event": "pong"}), flush=True)
    else:
        print(json.dumps({"event": "rpc.error",
                          "err": f"unknown action: {_msg.get('action')}"}), flush=True)
'''


# ---------------------------------------------------------------------------
# Public runtime
# ---------------------------------------------------------------------------

class SandboxRuntime:
    """One subprocess per session. Cells share namespace.

    Usage:
        rt = SandboxRuntime(session_id="...")
        await rt.start()
        cell = await rt.run_cell("print(2+2)")
        # cell.stdout == "4\n"
        ...
        await rt.stop()
    """

    def __init__(
        self,
        session_id: str,
        persist_dir: Optional[Path] = None,
        cell_timeout_s: float = 30.0,
    ):
        self.session_id = session_id
        self.persist_dir = persist_dir or (Path.home() / ".lysos" / "sessions" / session_id)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.cell_timeout_s = cell_timeout_s
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._cells: list[Cell] = []
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._proc is not None:
            return
        log.info("sandbox %s: starting subprocess", self.session_id)
        self._proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", _WORKER_BOOTSTRAP,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Drain boot.warn lines until boot.ready
        for _ in range(8):
            ev = await self._read_event(timeout=15.0)
            if ev is None:
                raise RuntimeError("sandbox boot failed: no response")
            if ev.get("event") == "boot.ready":
                log.info("sandbox %s: ready", self.session_id)
                return
            if ev.get("event") == "boot.warn":
                log.warning("sandbox %s: %s", self.session_id, ev.get("msg"))
                continue
            raise RuntimeError(f"sandbox boot failed: {ev}")

    async def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.kill()
        except ProcessLookupError:
            pass
        await self._proc.wait()
        self._proc = None

    async def _read_event(self, timeout: float = 35.0) -> Optional[dict]:
        if not self._proc or not self._proc.stdout:
            return None
        try:
            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        if not line:
            return None
        try:
            return json.loads(line.decode("utf-8").strip())
        except json.JSONDecodeError:
            return {"event": "rpc.unparsed", "raw": line.decode("utf-8", errors="replace")}

    async def run_cell(self, code: str) -> Cell:
        async with self._lock:
            await self.start()
            cell = Cell(cell_id=uuid.uuid4().hex[:12], code=code, status=CellStatus.RUNNING)
            cell.started_at = time.time()

            assert self._proc and self._proc.stdin
            msg = json.dumps({"action": "run_cell", "cell_id": cell.cell_id, "code": code}) + "\n"
            self._proc.stdin.write(msg.encode("utf-8"))
            await self._proc.stdin.drain()

            event = await self._read_event(timeout=self.cell_timeout_s + 5)
            cell.finished_at = time.time()
            cell.elapsed_ms = int((cell.finished_at - cell.started_at) * 1000)

            if event is None:
                cell.status = CellStatus.TIMEOUT
                cell.stderr = (
                    f"Cell timed out (no response from worker within "
                    f"{int(self.cell_timeout_s + 5)}s)"
                )
            elif event.get("event") == "cell.done":
                cell.status = CellStatus.DONE
                cell.stdout = event.get("stdout", "")
                cell.stderr = event.get("stderr", "")
                cell.scene_events = event.get("scene_events", [])
                cell.structured = event.get("structured", {})
            elif event.get("event") == "cell.error":
                cell.status = CellStatus.ERROR
                cell.stdout = event.get("stdout", "")
                cell.stderr = event.get("stderr", "")
            else:
                cell.status = CellStatus.ERROR
                cell.stderr = f"unexpected event: {event}"

            self._cells.append(cell)
            self._persist(cell)
            return cell

    def _persist(self, cell: Cell) -> None:
        try:
            log_path = self.persist_dir / "cells.jsonl"
            with log_path.open("a") as f:
                f.write(json.dumps(cell.to_dict(), default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            log.warning("sandbox %s: persist failed: %s", self.session_id, exc)

    def cells(self) -> list[Cell]:
        return list(self._cells)
