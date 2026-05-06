"""3D molecular scene state.

Scene = the object the right panel renders as a py3Dmol viewer. It's a
list of objects (proteins, ligand poses) + camera + highlights +
measurements. Cells emit events that mutate the scene; the frontend
applies them in order.

Three layers:
  1. SceneObject — one item in the scene (protein PDB, ligand PDB, etc.)
  2. SceneEvent  — one mutation (add_object, remove_object, highlight,
                   set_camera, …)
  3. Scene       — current state + ordered event log (replay-friendly)

Why this design:
- Idempotent: any client that consumes the event log gets the same
  final scene state. Recovers cleanly from disconnect.
- Granular: agent + user can both edit the scene without merge conflicts
  (events are appended, not in-place mutated).
- Observable: every event is a structured action ("highlight residue
  PBP2a:Asn146"), perfect for trace replay in the methods paper.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class SceneObjectKind(str, Enum):
    PROTEIN = "protein"
    LIGAND = "ligand"
    POSE = "pose"
    SURFACE = "surface"
    LABEL = "label"


@dataclass
class SceneObject:
    obj_id: str
    kind: SceneObjectKind
    label: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    # payload examples by kind:
    #   protein: {"pdb_id": "4DKI", "chain": "A"}
    #   ligand:  {"smiles": "CC(=O)..."}
    #   pose:    {"pdb_text": "...", "ipTM": 0.71}
    #   surface: {"target_obj_id": "...", "color": "spectrum", "opacity": 0.3}
    #   label:   {"text": "Asn146", "anchor_obj_id": "...", "residue": "146"}
    style: dict[str, Any] = field(default_factory=dict)
    # style examples:
    #   {"colorscheme": "default", "stick": {"radius": 0.15}}
    #   {"cartoon": {"colorscheme": "spectrum"}}
    visible: bool = True


class SceneEventKind(str, Enum):
    ADD_OBJECT = "add_object"
    REMOVE_OBJECT = "remove_object"
    UPDATE_OBJECT = "update_object"
    SET_CAMERA = "set_camera"
    HIGHLIGHT_RESIDUE = "highlight_residue"
    ADD_MEASUREMENT = "add_measurement"
    CLEAR = "clear"


@dataclass
class SceneEvent:
    event_id: str
    kind: SceneEventKind
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    actor: str = "agent"   # "agent" | "user" | "tool:<name>"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "kind": self.kind.value}


# ---------------------------------------------------------------------------
# Scene container
# ---------------------------------------------------------------------------

@dataclass
class _CameraState:
    target_obj: Optional[str] = None  # camera looks at this obj_id
    zoom: float = 1.0
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)


class Scene:
    """Append-only event log + materialized current state.

    Apply mutations via `apply_event`. Frontend consumes events in order;
    `current_state()` returns the materialized projection for snapshot
    saves / right-panel initial render.
    """

    def __init__(self, scene_id: Optional[str] = None):
        self.scene_id = scene_id or uuid.uuid4().hex[:12]
        self._objects: dict[str, SceneObject] = {}
        self._events: list[SceneEvent] = []
        self._camera = _CameraState()

    # ---- public mutations ----

    def add_object(self, obj: SceneObject, actor: str = "agent") -> SceneEvent:
        ev = SceneEvent(
            event_id=uuid.uuid4().hex[:12],
            kind=SceneEventKind.ADD_OBJECT,
            payload={"object": asdict(obj)},
            actor=actor,
        )
        self.apply_event(ev)
        return ev

    def remove_object(self, obj_id: str, actor: str = "agent") -> SceneEvent:
        ev = SceneEvent(
            event_id=uuid.uuid4().hex[:12],
            kind=SceneEventKind.REMOVE_OBJECT,
            payload={"obj_id": obj_id},
            actor=actor,
        )
        self.apply_event(ev)
        return ev

    def highlight_residue(
        self,
        obj_id: str,
        residue: str,
        chain: str = "A",
        color: str = "#ff8800",
        actor: str = "agent",
    ) -> SceneEvent:
        ev = SceneEvent(
            event_id=uuid.uuid4().hex[:12],
            kind=SceneEventKind.HIGHLIGHT_RESIDUE,
            payload={
                "obj_id": obj_id,
                "chain": chain,
                "residue": residue,
                "color": color,
            },
            actor=actor,
        )
        self.apply_event(ev)
        return ev

    def set_camera(self, target_obj: Optional[str] = None,
                   zoom: float = 1.0, actor: str = "agent") -> SceneEvent:
        ev = SceneEvent(
            event_id=uuid.uuid4().hex[:12],
            kind=SceneEventKind.SET_CAMERA,
            payload={"target_obj": target_obj, "zoom": zoom},
            actor=actor,
        )
        self.apply_event(ev)
        return ev

    def clear(self, actor: str = "user") -> SceneEvent:
        ev = SceneEvent(
            event_id=uuid.uuid4().hex[:12],
            kind=SceneEventKind.CLEAR,
            payload={},
            actor=actor,
        )
        self.apply_event(ev)
        return ev

    # ---- event application (also used during replay) ----

    def apply_event(self, ev: SceneEvent) -> None:
        if ev.kind == SceneEventKind.ADD_OBJECT:
            obj_dict = ev.payload.get("object") or {}
            obj = SceneObject(
                obj_id=obj_dict["obj_id"],
                kind=SceneObjectKind(obj_dict["kind"]),
                label=obj_dict.get("label", ""),
                payload=obj_dict.get("payload", {}),
                style=obj_dict.get("style", {}),
                visible=obj_dict.get("visible", True),
            )
            self._objects[obj.obj_id] = obj
        elif ev.kind == SceneEventKind.REMOVE_OBJECT:
            self._objects.pop(ev.payload.get("obj_id", ""), None)
        elif ev.kind == SceneEventKind.UPDATE_OBJECT:
            oid = ev.payload.get("obj_id")
            if oid in self._objects:
                upd = ev.payload.get("updates", {})
                obj = self._objects[oid]
                for k, v in upd.items():
                    setattr(obj, k, v)
        elif ev.kind == SceneEventKind.SET_CAMERA:
            self._camera.target_obj = ev.payload.get("target_obj")
            self._camera.zoom = float(ev.payload.get("zoom", 1.0))
        elif ev.kind == SceneEventKind.CLEAR:
            self._objects.clear()
            self._camera = _CameraState()
        # HIGHLIGHT_RESIDUE / ADD_MEASUREMENT are visual-only — no
        # change to materialized state, just appended to event log.
        self._events.append(ev)

    # ---- introspection ----

    def current_state(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "objects": [asdict(o) for o in self._objects.values()],
            "camera": asdict(self._camera),
            "n_events": len(self._events),
        }

    def event_log(self, since: int = 0) -> list[dict]:
        return [e.to_dict() for e in self._events[since:]]
