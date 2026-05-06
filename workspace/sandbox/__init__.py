"""Lysos molecular sandbox.

A first-class Python execution + 3D scene environment that BOTH the agent
and the user can read, write, and replay. The right panel of the SaaS
renders this as an .md-styled artifact view.

Three primitives:

  Cell      — Python code + stdout/stderr + structured output. Cells
              share a session-scoped namespace ("`mol_a` from cell 1 is
              visible in cell 2").
  Scene     — 3D molecular scene state: protein PDB + ligand pose(s) +
              camera + residue highlights + measurement annotations.
              Mutations stream as ordered events for live preview.
  Session   — top-level container: a list of cells, the current scene
              state, the active SMILES candidate, the active target.

Architecture:

  - Backend runtime: in-process subprocess pool. Each session pins one
    Python subprocess with rdkit/py3Dmol/pandas/numpy/matplotlib pre-
    imported. Runs cells via subprocess stdin/stdout protocol.
  - Resource caps per cell: 30 s CPU wall, 4 GB RAM, no network.
  - Communication with frontend: JSON-RPC over WebSocket. Events:
    `cell.requested`, `cell.stdout`, `cell.stderr`, `cell.done`,
    `scene.update`, `scene.event`.
  - Persistence: append-only `~/.lysos/sessions/<id>.jsonl` per session
    (cells + scene snapshots). Replayable.
"""

from .runtime import SandboxRuntime, Cell, CellStatus  # noqa: F401
from .scene import Scene, SceneEvent  # noqa: F401
from .session import SandboxSession  # noqa: F401

__all__ = [
    "SandboxRuntime",
    "Cell",
    "CellStatus",
    "Scene",
    "SceneEvent",
    "SandboxSession",
]
