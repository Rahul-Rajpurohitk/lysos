"""Playground HTTP + WebSocket endpoints — atom-level data + live editing.

  GET  /workbench/playground/molecule/{mid}/atoms
       → full Atom records (element, valence, free_valence, ring info, x/y/z)
  GET  /workbench/playground/molecule/{mid}/bonds
       → full Bond records
  GET  /workbench/playground/molecule/{mid}/state
       → molecule + atoms + bonds + latest_score in one round-trip
  POST /workbench/playground/sessions/{sid}/molecule
       → upsert a molecule from SMILES (materializes via RDKit)
  GET  /workbench/playground/sessions/{sid}/edits?since=<ts>
       → tail the edit log
  WS   /ws/playground/{sid}
       → bidirectional live editing protocol
       client → server: cursor.move | atom.hover | edit.propose | edit.apply | select | branch
       server → client: cursor.moved | atom.hovered | edit.applied | edit.rejected | agent.thinking | agent.message

The protocol auto-routes through the EventBus + persists every edit to
SQLite so multi-actor (user + agents) co-editing is durable + replayable.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from workspace.playground import get_bus, get_rules, get_store
from workspace.playground.store import (
    AgentAction, MoleculeEdit, ScoreSnapshot, materialize_from_smiles,
)

log = logging.getLogger("workbench.playground.api")
router = APIRouter(prefix="/workbench/playground", tags=["playground"])


# ---------------------------------------------------------------------------
# Read APIs
# ---------------------------------------------------------------------------

@router.get("/molecule/{mid}/atoms")
async def get_molecule_atoms(mid: str) -> dict[str, Any]:
    store = get_store()
    mol = store.get_molecule(mid)
    if not mol:
        raise HTTPException(404, f"molecule {mid} not found")
    return {"molecule_id": mid, "atoms": store.get_atoms(mid)}


@router.get("/molecule/{mid}/bonds")
async def get_molecule_bonds(mid: str) -> dict[str, Any]:
    store = get_store()
    mol = store.get_molecule(mid)
    if not mol:
        raise HTTPException(404, f"molecule {mid} not found")
    return {"molecule_id": mid, "bonds": store.get_bonds(mid)}


@router.get("/molecule/{mid}/state")
async def get_molecule_state(mid: str) -> dict[str, Any]:
    store = get_store()
    mol = store.get_molecule(mid)
    if not mol:
        raise HTTPException(404, f"molecule {mid} not found")
    return {
        "molecule": mol,
        "atoms": store.get_atoms(mid),
        "bonds": store.get_bonds(mid),
        "score": store.latest_score(mid),
    }


@router.get("/sessions/{sid}/molecules")
async def list_session_mols(sid: str) -> dict[str, Any]:
    store = get_store()
    return {"session_id": sid, "molecules": store.list_session_molecules(sid)}


@router.get("/sessions/{sid}/edits")
async def list_session_edits(sid: str, since: float = 0.0, limit: int = 500) -> dict[str, Any]:
    store = get_store()
    return {"session_id": sid, "edits": store.list_edits(sid, since_ts=since, limit=limit)}


# ---------------------------------------------------------------------------
# Materialize molecule
# ---------------------------------------------------------------------------

class CreateMolRequest(BaseModel):
    smiles: str
    parent_id: Optional[str] = None
    created_by: str = "user"
    role: str = "active"


@router.post("/sessions/{sid}/molecule")
async def upsert_session_molecule(sid: str, req: CreateMolRequest) -> dict[str, Any]:
    """Materialize a SMILES → Molecule + Atoms + Bonds, persist, broadcast
    a `molecule.created` event so all subscribers update their views."""
    store = get_store()
    try:
        mol, atoms, bonds = materialize_from_smiles(
            req.smiles, sid, req.parent_id, req.created_by, req.role,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"materialize failed: {exc}")
    store.create_session(sid, "anonymous", "MRSA")
    store.upsert_molecule(mol, atoms, bonds)
    bus = get_bus()
    bus.publish(sid, {
        "event": "molecule.created",
        "actor": req.created_by,
        "molecule_id": mol.id,
        "smiles": mol.smiles,
        "n_atoms": len(atoms),
        "n_bonds": len(bonds),
    })
    return {
        "molecule_id": mol.id,
        "smiles": mol.canonical_smiles,
        "n_atoms": len(atoms),
        "n_bonds": len(bonds),
    }


# ---------------------------------------------------------------------------
# Edit predict (cheap RDKit pre-validation, no scoring call)
# ---------------------------------------------------------------------------

class PredictEditRequest(BaseModel):
    smiles: str
    edit: dict[str, Any]


@router.post("/predict-edit")
async def predict_edit(req: PredictEditRequest) -> dict[str, Any]:
    return get_rules().predict_edit(req.smiles, req.edit)


# ---------------------------------------------------------------------------
# Job queue — async pool for /dock /admet /conformer /retrosynth
# ---------------------------------------------------------------------------

class EnqueueJobRequest(BaseModel):
    kind: str  # "dock" | "admet" | "conformer" | "retrosynth"
    payload: dict[str, Any] = {}


@router.post("/sessions/{sid}/jobs")
async def enqueue_job(sid: str, req: EnqueueJobRequest) -> dict[str, Any]:
    from workspace.playground.queue import get_queue
    job_id = await get_queue().enqueue(sid, req.kind, req.payload)
    return {"job_id": job_id, "kind": req.kind, "status": "queued"}


@router.get("/sessions/{sid}/jobs")
async def list_jobs(sid: str, status: Optional[str] = None) -> dict[str, Any]:
    return {"session_id": sid, "jobs": get_store().list_jobs(sid, status=status)}


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str) -> dict[str, Any]:
    from workspace.playground.queue import get_queue
    get_queue().cancel(job_id)
    return {"job_id": job_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# WebSocket — the live editing protocol
# ---------------------------------------------------------------------------

@router.websocket("/ws/playground/{sid}")
async def playground_ws(ws: WebSocket, sid: str) -> None:
    await ws.accept()
    bus = get_bus()
    store = get_store()

    # Fan-out: server-side bus → this client
    import asyncio

    async def fan_out() -> None:
        async for ev in bus.stream(sid):
            try:
                await ws.send_json(ev)
            except Exception:
                return

    fan_task = asyncio.create_task(fan_out())

    # Welcome packet — recent state for the client to bootstrap
    try:
        recent_edits = store.list_edits(sid, since_ts=0.0, limit=200)
        await ws.send_json({
            "event": "session.snapshot",
            "session_id": sid,
            "recent_edits": recent_edits,
        })
    except Exception:
        pass

    try:
        while True:
            msg = await ws.receive_json()
            op = msg.get("op", "")
            actor = msg.get("actor", "user")
            actor_kind = "agent" if actor in ("designer", "critic", "editor", "strategist") else "user"

            if op == "cursor.move":
                bus.publish(sid, {
                    "event": "cursor.moved",
                    "actor": actor,
                    "molecule_id": msg.get("molecule_id"),
                    "atom_idx": msg.get("atom_idx"),
                })

            elif op == "atom.hover":
                # Predictive hint: what would happen if we attached at this atom?
                # We don't run real scoring here — return a fast prevalidation.
                ev = {
                    "event": "atom.hovered",
                    "actor": actor,
                    "molecule_id": msg.get("molecule_id"),
                    "atom_idx": msg.get("atom_idx"),
                }
                if msg.get("predict_edit"):
                    smi = msg.get("smiles", "")
                    if smi:
                        ev["predicted"] = get_rules().predict_edit(smi, msg["predict_edit"])
                bus.publish(sid, ev)

            elif op == "select":
                bus.publish(sid, {
                    "event": "selection.changed",
                    "actor": actor,
                    "molecule_id": msg.get("molecule_id"),
                    "atom_idxs": msg.get("atom_idxs", []),
                })

            elif op in ("edit.propose", "edit.apply"):
                edit = msg.get("edit") or {}
                smi = msg.get("smiles", "")
                client_op_id = msg.get("client_op_id")
                # 1. validate via RulesEngine
                pred = get_rules().predict_edit(smi, edit)
                if not pred.get("ok"):
                    bus.publish(sid, {
                        "event": "edit.rejected",
                        "actor": actor,
                        "reason": pred.get("reason", "unknown"),
                        "client_op_id": client_op_id,
                    })
                    continue
                new_smi = pred["new_smiles"]
                # 2. materialize new molecule
                try:
                    mol, atoms, bonds = materialize_from_smiles(
                        new_smi, sid, msg.get("molecule_id"), actor, "active",
                    )
                except Exception as exc:  # noqa: BLE001
                    bus.publish(sid, {
                        "event": "edit.rejected",
                        "actor": actor,
                        "reason": f"materialize failed: {exc}",
                        "client_op_id": client_op_id,
                    })
                    continue
                # 3. persist molecule + edit
                store.upsert_molecule(mol, atoms, bonds)
                store.append_edit(MoleculeEdit(
                    id="ed_" + uuid.uuid4().hex[:12],
                    ts=time.time(),
                    session_id=sid,
                    parent_molecule_id=msg.get("molecule_id"),
                    child_molecule_id=mol.id,
                    actor=actor,
                    actor_kind=actor_kind,
                    op=edit.get("kind") or edit.get("op", "?"),
                    atom_idx=edit.get("atom_idx"),
                    bond_idx=edit.get("bond_idx"),
                    params=edit,
                    result_smiles=new_smi,
                    composite_before=None,
                    composite_after=None,
                    delta=None,
                    client_op_id=client_op_id,
                ))
                # 4. broadcast
                bus.publish(sid, {
                    "event": "edit.applied",
                    "actor": actor,
                    "client_op_id": client_op_id,
                    "from_molecule_id": msg.get("molecule_id"),
                    "to_molecule_id": mol.id,
                    "from_smiles": smi,
                    "to_smiles": new_smi,
                    "edit": edit,
                    "hints": pred.get("hints", {}),
                })

            elif op == "agent.thinking":
                # Agent loop sends this when it's reasoning about a target atom.
                # Persisted as an AgentAction row + broadcast for cursor display.
                store.append_action(AgentAction(
                    id="act_" + uuid.uuid4().hex[:12],
                    session_id=sid,
                    ts=time.time(),
                    agent_name=actor,
                    action_type=msg.get("action_type", "hover"),
                    target_molecule_id=msg.get("molecule_id"),
                    target_atom_idx=msg.get("atom_idx"),
                    message_text=msg.get("rationale", ""),
                    confidence=float(msg.get("confidence", 0.5)),
                    references=msg.get("references", {}) or {},
                ))
                bus.publish(sid, {
                    "event": "agent.thinking",
                    "agent": actor,
                    "molecule_id": msg.get("molecule_id"),
                    "atom_idx": msg.get("atom_idx"),
                    "rationale": msg.get("rationale", ""),
                })

            elif op == "ping":
                await ws.send_json({"event": "pong", "ts": time.time()})

            else:
                await ws.send_json({"event": "error", "msg": f"unknown op: {op}"})

    except WebSocketDisconnect:
        log.info("playground ws %s disconnected", sid)
    except Exception as exc:  # noqa: BLE001
        log.warning("playground ws %s error: %s", sid, exc)
        try:
            await ws.send_json({"event": "error", "msg": str(exc)})
        except Exception:
            pass
    finally:
        fan_task.cancel()
