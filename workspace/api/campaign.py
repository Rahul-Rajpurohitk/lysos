"""Campaign — the productization backbone of Lysos (Act II).

A Campaign is the first-class object a drug-discovery team actually works in.
Everything else (candidates, workflow runs, service artifacts, the dossier,
the agent's decisions) hangs off ONE campaign so the product stops being a
loose pile of cards and becomes a coherent program.

    Campaign  = a goal: { pathogen, objective, modality }
       ├─ candidates[]   — SMILES under evaluation + their rollup state
       ├─ runs[]         — workflow executions performed under the campaign
       ├─ decisions[]    — the agent's advance / drop / A-B / hold calls
       └─ status         — scoping → exploring → optimizing → decided

Storage: rides on the shared service_store SQLite substrate as an artifact
of kind="campaign" (payload holds the whole campaign doc). No migration —
same single-source-of-truth store every service already uses.

Six-layer contract (same as every service):
  1. service_store substrate           (shared SQLite)
  2. backend compute + CRUD            (this module)
  3. agent tool                        (agent.py · campaign_* tools)
  4. workflow hook                     (runs auto-recorded by the executor)
  5. orchestrator awareness            (campaign in the brief)
  6. frontend Campaign board           (CampaignBoardCard.tsx) + dossier link
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.campaign")
router = APIRouter(prefix="/chem", tags=["campaign"])

_KIND = "campaign"

# Campaign lifecycle. The agent advances these as the program matures.
_STATUSES = ("scoping", "exploring", "optimizing", "decided", "archived")

# 8 WHO/CDC priority pathogens Lysos targets (kept in sync with the
# pathogen picker). The campaign goal references one.
_PRIORITY_PATHOGENS = {
    "MRSA", "VRE", "CRE", "A. baumannii", "P. aeruginosa",
    "N. gonorrhoeae", "C. difficile", "M. tuberculosis",
}


# ─────────────────────────────────────────────────────────────────────
# Core doc shape
# ─────────────────────────────────────────────────────────────────────

def _empty_doc(name: str, pathogen: str, objective: str,
               modality: str) -> dict[str, Any]:
    return {
        "name": name,
        "goal": {
            "pathogen": pathogen,
            "objective": objective,
            "modality": modality,      # "small_molecule" | "peptide"
        },
        "status": "scoping",
        "candidates": [],              # [{smiles, label, added_at, source, rollup}]
        "runs": [],                    # [{workflow, smiles, run_id, at, summary}]
        "decisions": [],               # [{kind, smiles, rationale, at, by}]
        "champion_smiles": None,       # current best candidate
        "created_at": time.time(),
        "updated_at": time.time(),
    }


def _persist(rec_id: str, doc: dict[str, Any]) -> None:
    doc["updated_at"] = time.time()
    service_store.update_artifact(rec_id, payload=doc,
                                  title=f"{doc['name']} · {doc['goal']['pathogen']}")


def _load(rec_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rec = service_store.get_artifact(rec_id)
    if rec is None or rec.get("kind") != _KIND:
        raise HTTPException(404, f"campaign {rec_id} not found")
    return rec, rec["payload"]


# ─────────────────────────────────────────────────────────────────────
# API models
# ─────────────────────────────────────────────────────────────────────

class CreateCampaign(BaseModel):
    name: str
    pathogen: str
    objective: str = "novel, synthesizable, safe lead"
    modality: str = "small_molecule"
    session_id: Optional[str] = None


class AddCandidate(BaseModel):
    smiles: str
    label: Optional[str] = None
    source: Optional[str] = None       # design | generate | apply | manual
    rollup: Optional[dict[str, Any]] = None


class RecordRun(BaseModel):
    workflow: str
    smiles: Optional[str] = None
    run_id: Optional[str] = None
    summary: Optional[str] = None


class RecordDecision(BaseModel):
    kind: str                          # advance | drop | hold | a_b | champion
    smiles: Optional[str] = None
    rationale: str = ""
    by: str = "strategist"


class SetStatus(BaseModel):
    status: str


# ─────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────

@router.post("/campaign/create")
async def create_campaign(req: CreateCampaign) -> dict[str, Any]:
    if req.pathogen not in _PRIORITY_PATHOGENS:
        log.info("campaign for non-priority pathogen %s (allowed)", req.pathogen)
    doc = _empty_doc(req.name.strip() or "Untitled campaign",
                     req.pathogen, req.objective, req.modality)
    rec = service_store.save_artifact(
        _KIND, doc, session_id=req.session_id, smiles=None,
        title=f"{doc['name']} · {req.pathogen}")
    return {"id": rec["id"], **doc}


@router.get("/campaign/list")
async def list_campaigns(session_id: Optional[str] = None) -> dict[str, Any]:
    items = service_store.list_artifacts(kind=_KIND, session_id=session_id)
    out = []
    for it in items:
        d = it["payload"]
        out.append({
            "id": it["id"],
            "name": d.get("name"),
            "goal": d.get("goal"),
            "status": d.get("status"),
            "n_candidates": len(d.get("candidates") or []),
            "n_runs": len(d.get("runs") or []),
            "n_decisions": len(d.get("decisions") or []),
            "champion_smiles": d.get("champion_smiles"),
            "updated_at": d.get("updated_at"),
        })
    out.sort(key=lambda x: x.get("updated_at") or 0, reverse=True)
    return {"campaigns": out, "n": len(out)}


@router.get("/campaign/{rec_id}")
async def get_campaign(rec_id: str) -> dict[str, Any]:
    rec, doc = _load(rec_id)
    return {"id": rec_id, **doc}


@router.post("/campaign/{rec_id}/candidate")
async def add_candidate(rec_id: str, req: AddCandidate) -> dict[str, Any]:
    rec, doc = _load(rec_id)
    cands = doc.setdefault("candidates", [])
    # Dedup by SMILES — update rollup if it already exists.
    existing = next((c for c in cands if c["smiles"] == req.smiles), None)
    if existing:
        if req.rollup:
            existing["rollup"] = {**(existing.get("rollup") or {}), **req.rollup}
        if req.label:
            existing["label"] = req.label
    else:
        cands.append({
            "smiles": req.smiles,
            "label": req.label or f"candidate {len(cands) + 1}",
            "source": req.source or "manual",
            "added_at": time.time(),
            "rollup": req.rollup or {},
        })
    if doc.get("status") == "scoping":
        doc["status"] = "exploring"
    _persist(rec_id, doc)
    return {"id": rec_id, "n_candidates": len(cands), **doc}


@router.post("/campaign/{rec_id}/run")
async def record_run(rec_id: str, req: RecordRun) -> dict[str, Any]:
    rec, doc = _load(rec_id)
    doc.setdefault("runs", []).append({
        "workflow": req.workflow,
        "smiles": req.smiles,
        "run_id": req.run_id,
        "summary": req.summary,
        "at": time.time(),
    })
    _persist(rec_id, doc)
    return {"id": rec_id, "n_runs": len(doc["runs"])}


@router.post("/campaign/{rec_id}/decision")
async def record_decision(rec_id: str, req: RecordDecision) -> dict[str, Any]:
    rec, doc = _load(rec_id)
    if req.kind not in ("advance", "drop", "hold", "a_b", "champion"):
        raise HTTPException(422, f"unknown decision kind: {req.kind}")
    doc.setdefault("decisions", []).append({
        "kind": req.kind,
        "smiles": req.smiles,
        "rationale": req.rationale,
        "by": req.by,
        "at": time.time(),
    })
    if req.kind == "champion" and req.smiles:
        doc["champion_smiles"] = req.smiles
        doc["status"] = "optimizing"
    if req.kind == "drop" and req.smiles:
        doc["candidates"] = [c for c in doc.get("candidates", [])
                             if c["smiles"] != req.smiles]
    _persist(rec_id, doc)
    return {"id": rec_id, "n_decisions": len(doc["decisions"]),
            "champion_smiles": doc.get("champion_smiles")}


@router.post("/campaign/{rec_id}/status")
async def set_status(rec_id: str, req: SetStatus) -> dict[str, Any]:
    rec, doc = _load(rec_id)
    if req.status not in _STATUSES:
        raise HTTPException(422, f"status must be one of {_STATUSES}")
    doc["status"] = req.status
    _persist(rec_id, doc)
    return {"id": rec_id, "status": doc["status"]}


@router.delete("/campaign/{rec_id}")
async def delete_campaign(rec_id: str) -> dict[str, Any]:
    ok = service_store.delete_artifact(rec_id)
    return {"deleted": bool(ok)}


# ─────────────────────────────────────────────────────────────────────
# Harness hooks — called by the workflow executor + agent
# ─────────────────────────────────────────────────────────────────────

def attach_run(campaign_id: Optional[str], workflow: str,
               smiles: Optional[str], run_id: Optional[str],
               summary: Optional[str]) -> None:
    """Best-effort: record a workflow run under a campaign. Called by the
    executor so any workflow run inside a campaign is auto-logged."""
    if not campaign_id:
        return
    try:
        rec = service_store.get_artifact(campaign_id)
        if rec is None or rec.get("kind") != _KIND:
            return
        doc = rec["payload"]
        doc.setdefault("runs", []).append({
            "workflow": workflow, "smiles": smiles, "run_id": run_id,
            "summary": summary, "at": time.time(),
        })
        _persist(campaign_id, doc)
    except Exception:  # noqa: BLE001
        pass


def campaign_brief(campaign_id: Optional[str]) -> Optional[str]:
    """One-line campaign context for the agent's session brief."""
    if not campaign_id:
        return None
    try:
        rec = service_store.get_artifact(campaign_id)
        if rec is None or rec.get("kind") != _KIND:
            return None
        d = rec["payload"]
        g = d.get("goal", {})
        champ = d.get("champion_smiles")
        return (f"Active campaign '{d.get('name')}' — target {g.get('pathogen')}, "
                f"goal: {g.get('objective')} ({g.get('modality')}). "
                f"{len(d.get('candidates') or [])} candidates, status "
                f"{d.get('status')}." + (f" Champion: {champ}." if champ else ""))
    except Exception:  # noqa: BLE001
        return None
