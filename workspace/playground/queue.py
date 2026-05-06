"""Async job queue — long-running tasks (dock, admet, conformer, retrosynth).

Per-kind worker pool with concurrency caps. Status events flow through
the EventBus → WS clients → playground status pills. Cancellable.
Persisted across restarts via the `jobs` SQLite table.

Public API:
    enqueue(session_id, kind, payload) → job_id
    cancel(job_id)
    list(session_id, status?)

Workers are lazy-spawned on the first enqueue per kind. The pool runs
forever — there's no shutdown handshake (FastAPI lifespan kills tasks
on app shutdown).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from .bus import get_bus
from .store import Job, get_store

log = logging.getLogger("workbench.playground.queue")


# Per-kind concurrency caps. Tune per workload weight (dock is heavy,
# admet is light, retrosynth depends on AiZynth latency).
CONCURRENCY: dict[str, int] = {
    "dock": 1,
    "conformer": 2,
    "admet": 4,
    "retrosynth": 1,
    "default": 2,
}


# Registered handlers: kind → async function(payload, on_progress) → result
JobHandler = Callable[[dict, Callable[[str], Awaitable[None]]], Awaitable[dict]]
_handlers: dict[str, JobHandler] = {}


def register_handler(kind: str, fn: JobHandler) -> None:
    _handlers[kind] = fn
    log.info("job handler registered: %s", kind)


class JobQueue:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Optional[str]]] = {}
        self._workers: dict[str, list[asyncio.Task]] = {}
        self._cancelled: set[str] = set()
        self._store = get_store()
        self._bus = get_bus()

    def _ensure_workers(self, kind: str) -> None:
        if kind in self._workers:
            return
        self._queues[kind] = asyncio.Queue()
        n = CONCURRENCY.get(kind, CONCURRENCY["default"])
        self._workers[kind] = [
            asyncio.create_task(self._worker_loop(kind, i)) for i in range(n)
        ]
        log.info("spawned %d workers for kind=%s", n, kind)

    async def enqueue(self, session_id: str, kind: str, payload: dict) -> str:
        self._ensure_workers(kind)
        job_id = "job_" + uuid.uuid4().hex[:12]
        self._store.enqueue_job(Job(
            id=job_id, session_id=session_id, kind=kind, status="queued",
            payload=payload, result={}, error_text="",
            created_at=time.time(), started_at=None, finished_at=None,
            worker_id="",
        ))
        await self._queues[kind].put(job_id)
        self._bus.publish(session_id, {
            "event": "job.queued", "job_id": job_id, "kind": kind,
        })
        return job_id

    def cancel(self, job_id: str) -> None:
        self._cancelled.add(job_id)
        self._store.update_job(job_id, status="cancelled", finished_at=time.time())

    async def _worker_loop(self, kind: str, worker_idx: int) -> None:
        while True:
            try:
                job_id = await self._queues[kind].get()
                if job_id is None:
                    return
                await self._run_job(kind, job_id, worker_idx)
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("worker %s/%d crashed: %s", kind, worker_idx, exc)

    async def _run_job(self, kind: str, job_id: str, worker_idx: int) -> None:
        if job_id in self._cancelled:
            self._cancelled.discard(job_id)
            return
        # Direct row fetch — store has no get_job; reach into the connection
        # under its lock.
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if not row:
            return
        sid = row["session_id"]
        payload = {}
        try:
            import json
            payload = json.loads(row["payload"] or "{}")
        except Exception:
            pass

        worker_label = f"{kind}/{worker_idx}"
        self._store.update_job(
            job_id, status="running", started_at=time.time(), worker_id=worker_label,
        )
        self._bus.publish(sid, {
            "event": "job.started", "job_id": job_id, "kind": kind,
            "worker_id": worker_label,
        })

        handler = _handlers.get(kind)
        if handler is None:
            self._store.update_job(
                job_id, status="error",
                error_text=f"no handler for kind '{kind}'",
                finished_at=time.time(),
            )
            self._bus.publish(sid, {
                "event": "job.error", "job_id": job_id, "error": "no handler",
            })
            return

        async def on_progress(msg: str) -> None:
            self._bus.publish(sid, {
                "event": "job.progress", "job_id": job_id, "msg": msg,
            })

        try:
            result = await handler(payload, on_progress)
            self._store.update_job(
                job_id, status="done", result=result, finished_at=time.time(),
            )
            self._bus.publish(sid, {
                "event": "job.done", "job_id": job_id, "kind": kind, "result": result,
            })
        except asyncio.CancelledError:
            self._store.update_job(job_id, status="cancelled", finished_at=time.time())
            self._bus.publish(sid, {"event": "job.cancelled", "job_id": job_id})
        except Exception as exc:  # noqa: BLE001
            self._store.update_job(
                job_id, status="error",
                error_text=str(exc)[:300], finished_at=time.time(),
            )
            self._bus.publish(sid, {
                "event": "job.error", "job_id": job_id, "error": str(exc)[:300],
            })


_QUEUE: Optional[JobQueue] = None


def get_queue() -> JobQueue:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = JobQueue()
        _register_default_handlers()
    return _QUEUE


# ---------------------------------------------------------------------------
# Default handlers — wrap the existing scoring/admet/dock tools as jobs
# ---------------------------------------------------------------------------

async def _admet_handler(payload: dict, on_progress: Callable[[str], Awaitable[None]]) -> dict:
    smi = payload.get("smiles", "")
    target = payload.get("target_pathogen", "MRSA")
    await on_progress("loading TDC predictors…")
    try:
        from workspace.tools.scoring.predict_admet import predict_admet
        await on_progress("running ADMET panel…")
        r = predict_admet(smiles=smi)
        return {"ok": True, "admet": r.model_dump() if hasattr(r, "model_dump") else dict(r), "target": target}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


async def _conformer_handler(payload: dict, on_progress: Callable[[str], Awaitable[None]]) -> dict:
    smi = payload.get("smiles", "")
    n_conf = int(payload.get("n_confs", 5))
    await on_progress(f"generating {n_conf} conformers…")
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            return {"ok": False, "error": "unparseable SMILES"}
        mol = Chem.AddHs(mol)
        ids = AllChem.EmbedMultipleConfs(mol, numConfs=n_conf, randomSeed=0xC0FFEE)
        await on_progress(f"optimizing {len(ids)} conformers…")
        energies: list[float] = []
        for cid in ids:
            try:
                AllChem.MMFFOptimizeMolecule(mol, confId=int(cid))
                ff = AllChem.MMFFGetMoleculeForceField(
                    mol, AllChem.MMFFGetMoleculeProperties(mol), confId=int(cid),
                )
                energies.append(ff.CalcEnergy() if ff else 0.0)
            except Exception:
                energies.append(0.0)
        return {"ok": True, "n_conformers": len(ids), "energies_kcal_mol": energies}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


async def _retrosynth_handler(payload: dict, on_progress: Callable[[str], Awaitable[None]]) -> dict:
    smi = payload.get("smiles", "")
    await on_progress("estimating retrosynthesis route…")
    try:
        from workspace.tools.scoring.estimate_synth_cost import estimate_synth_cost
        r = estimate_synth_cost(smiles=smi)
        return {"ok": True, "route": r.model_dump() if hasattr(r, "model_dump") else dict(r)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


async def _dock_handler(payload: dict, on_progress: Callable[[str], Awaitable[None]]) -> dict:
    smi = payload.get("smiles", "")
    pathogen = payload.get("pathogen", "MRSA")
    await on_progress(f"docking against {pathogen} target…")
    try:
        # Light-weight dock: use the existing molecule/3d endpoint to get a
        # conformer, then return a "binding affinity" placeholder. Real
        # Boltz-2 docking goes here in a future iteration.
        from workspace.tools.scoring.score_molecule import score_molecule
        r = score_molecule(smiles=smi, target_pathogen=pathogen)
        d = r.model_dump()
        # Extract pose-related component if present
        pose_score = next((c["value"] for c in d.get("components", []) if "pose" in c["name"]), 0.0)
        return {"ok": True, "pose_score": pose_score, "composite": d.get("composite", 0.0)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def _register_default_handlers() -> None:
    register_handler("admet", _admet_handler)
    register_handler("conformer", _conformer_handler)
    register_handler("retrosynth", _retrosynth_handler)
    register_handler("dock", _dock_handler)
