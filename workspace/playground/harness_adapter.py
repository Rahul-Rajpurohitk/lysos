"""HarnessAdapter — bridges the agent loop (graph.py) to the playground.

The existing agent loop emits trace events (`agent_message`,
`candidate_added`, `score`, `iteration_*`, `tool_call_*`) via a callback
provided by the API route. This adapter wraps that callback so each
event ALSO:

  1. Persists to the PlaygroundStore (Molecule + Atoms + Bonds for new
     candidates, ScoreSnapshot for scores, AgentAction for messages)
  2. Publishes a typed event on the EventBus → WS clients update live
  3. Honors actor identity (designer/critic/editor/strategist mapped
     from the event's role) so cursor presence & reasoning trace work

The original tracer/SSE pipeline is unaffected — the adapter is purely
additive. /workbench/design installs an emit chain:
    raw_emit → tracer.emit → adapter.emit
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from .bus import get_bus
from .store import (
    AgentAction, MoleculeEdit, ScoreSnapshot, get_store,
    materialize_from_smiles,
)

log = logging.getLogger("workbench.playground.harness_adapter")


EmitFn = Callable[[dict], Awaitable[None]]


class HarnessAdapter:
    """Stateful per-session adapter. Tracks last molecule_id so subsequent
    edits can chain (parent → child)."""

    def __init__(self, session_id: str, target_pathogen: str = "MRSA",
                 user_id: str = "anonymous") -> None:
        self.session_id = session_id
        self.target_pathogen = target_pathogen
        self.user_id = user_id
        self._last_molecule_id: Optional[str] = None
        self._store = get_store()
        self._bus = get_bus()
        self._store.create_session(session_id, user_id, target_pathogen)

    @staticmethod
    def normalize_actor(role: Optional[str]) -> tuple[str, str]:
        """Return (actor_name, actor_kind) for an event's role/agent field."""
        if not role:
            return "system", "system"
        r = role.lower()
        if r in ("designer", "critic", "editor", "strategist", "orchestrator"):
            return r, "agent"
        return r, "user"

    async def emit(self, ev: dict) -> None:
        """Called for every event the agent loop produces. Side-effects only —
        does not mutate the event in place."""
        try:
            await self._dispatch(ev)
        except Exception as exc:  # noqa: BLE001
            log.warning("HarnessAdapter dispatch failed: %s", exc, exc_info=False)

    async def _dispatch(self, ev: dict) -> None:
        et = ev.get("type", "")
        data = ev.get("data") or {}
        role = data.get("role") or ev.get("agent") or data.get("agent")
        actor, actor_kind = self.normalize_actor(role)

        if et == "agent_message":
            content = data.get("content") or ev.get("content") or ""
            iteration = data.get("iteration") or ev.get("iteration")
            self._store.append_action(AgentAction(
                id="act_" + uuid.uuid4().hex[:12],
                session_id=self.session_id, ts=time.time(),
                agent_name=actor,
                action_type="message",
                target_molecule_id=self._last_molecule_id,
                target_atom_idx=None,
                message_text=content[:2000],
                confidence=0.0,
                references={"iteration": iteration} if iteration is not None else {},
            ))
            self._bus.publish(self.session_id, {
                "event": "agent.message",
                "agent": actor,
                "actor_kind": actor_kind,
                "content": content[:2000],
                "iteration": iteration,
                "molecule_id": self._last_molecule_id,
            })

        elif et == "candidate_added":
            smi = data.get("smiles") or ev.get("smiles")
            cand_id = data.get("id") or "cand_" + uuid.uuid4().hex[:8]
            iteration = data.get("iteration") or ev.get("iteration")
            if not smi:
                return
            try:
                mol, atoms, bonds = materialize_from_smiles(
                    smi, self.session_id, self._last_molecule_id,
                    created_by=actor, role="active",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("materialize failed for %s: %s", smi, exc)
                return
            self._store.upsert_molecule(mol, atoms, bonds)
            self._store.append_edit(MoleculeEdit(
                id="ed_" + uuid.uuid4().hex[:12],
                ts=time.time(),
                session_id=self.session_id,
                parent_molecule_id=self._last_molecule_id,
                child_molecule_id=mol.id,
                actor=actor,
                actor_kind=actor_kind,
                op="propose",
                atom_idx=None,
                bond_idx=None,
                params={"candidate_id": cand_id, "iteration": iteration},
                result_smiles=mol.canonical_smiles,
                composite_before=None,
                composite_after=None,
                delta=None,
                client_op_id=None,
            ))
            self._last_molecule_id = mol.id
            self._bus.publish(self.session_id, {
                "event": "molecule.created",
                "actor": actor,
                "actor_kind": actor_kind,
                "molecule_id": mol.id,
                "smiles": mol.canonical_smiles,
                "n_atoms": len(atoms),
                "n_bonds": len(bonds),
                "iteration": iteration,
                "candidate_id": cand_id,
            })

        elif et == "score":
            smi = data.get("smiles") or ev.get("smiles")
            composite = data.get("composite") or ev.get("composite") or 0.0
            scores = data.get("scores") or {}
            if not smi:
                return
            mid = self._last_molecule_id
            # If we don't already have this molecule materialized, materialize it
            if not mid:
                try:
                    mol, atoms, bonds = materialize_from_smiles(
                        smi, self.session_id, None, created_by=actor, role="active",
                    )
                    self._store.upsert_molecule(mol, atoms, bonds)
                    mid = mol.id
                    self._last_molecule_id = mid
                except Exception:
                    return
            weakest = min(scores.items(), key=lambda kv: kv[1])[0] if scores else ""
            strongest = max(scores.items(), key=lambda kv: kv[1])[0] if scores else ""
            self._store.append_score(ScoreSnapshot(
                id="score_" + uuid.uuid4().hex[:12],
                molecule_id=mid,
                ts=time.time(),
                composite=float(composite),
                components=scores,
                weakest=weakest,
                strongest=strongest,
                model_used="lysos.score_molecule",
            ))
            self._bus.publish(self.session_id, {
                "event": "molecule.scored",
                "molecule_id": mid,
                "composite": float(composite),
                "components": scores,
                "weakest": weakest,
                "strongest": strongest,
            })

        elif et == "iteration_start":
            self._bus.publish(self.session_id, {
                "event": "iteration.started",
                "iteration": data.get("iteration") or ev.get("iteration"),
            })

        elif et == "iteration_end":
            self._bus.publish(self.session_id, {
                "event": "iteration.ended",
                "iteration": data.get("iteration") or ev.get("iteration"),
                "composite": data.get("composite") or ev.get("composite"),
            })

        elif et == "tool_call_result":
            # Surface tool calls as agent thinking events (cursor halo when
            # the tool relates to a target_atom_idx).
            self._bus.publish(self.session_id, {
                "event": "agent.tool_call",
                "agent": actor,
                "tool": data.get("tool") or ev.get("tool"),
                "ok": True,
            })

        elif et == "tool_call_error":
            self._bus.publish(self.session_id, {
                "event": "agent.tool_call",
                "agent": actor,
                "tool": data.get("tool") or ev.get("tool"),
                "ok": False,
                "error": (data.get("error") or "")[:200],
            })

        elif et == "session_complete":
            self._bus.publish(self.session_id, {
                "event": "session.complete",
                "molecule_id": self._last_molecule_id,
            })


def chain_emits(*emit_fns: EmitFn) -> EmitFn:
    """Compose multiple emit callbacks into one. Each gets every event
    independently — no return-value chaining, no exception propagation
    between adapters (one failure doesn't kill the others)."""

    async def emit(ev: dict) -> None:
        for fn in emit_fns:
            try:
                await fn(ev)
            except Exception as exc:  # noqa: BLE001
                log.warning("chained emit fn failed: %s", exc, exc_info=False)

    return emit
