"""Synthesis Make-Route — Service 1 of the productized service layer.

Turns the abstract `synthesizability` score into an actual plan: a
retrosynthetic route with named steps, reagents, building-block
availability, a cost estimate and a lead-time estimate.

Endpoints (router prefix /chem, mounted under /workbench):
  POST   /chem/synthesis/plan              SMILES → retrosynthetic route
  GET    /chem/synthesis/routes            list saved routes (CRUD read)
  GET    /chem/synthesis/routes/{rid}      get one saved route
  PATCH  /chem/synthesis/routes/{rid}      update title / notes / starred
  DELETE /chem/synthesis/routes/{rid}      delete a saved route

Design pattern (shared across the service layer):
  - Gemini PROPOSES the chemistry; RDKit VALIDATES every intermediate
    SMILES — same proposer/validator split the harden service uses.
  - Cost / feasibility / lead-time are computed SERVER-SIDE from real
    signals (step count, intermediate validity, building-block
    availability) — never taken from the model.
  - Every computed route is persisted via service_store as a
    `synthesis_route` artifact so users + agents share one CRUD view.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("api.chem_synthesis")
router = APIRouter(prefix="/chem", tags=["chem_synthesis"])

_ARTIFACT_KIND = "synthesis_route"

# ── Cost model — literature-anchored heuristics, NOT model output ──────
_COST_PER_STEP_USD = 80.0          # labor + reagents per synthetic step
_SM_COST_USD = {                   # per starting material, by availability
    "in_stock": 30.0,
    "catalog": 90.0,
    "custom": 250.0,
}
_AVAILABILITY = {"in_stock", "catalog", "custom"}


# ─────────────────────────────────────────────────────────────────────
# RDKit helpers
# ─────────────────────────────────────────────────────────────────────

def _canonical(smiles: str) -> Optional[str]:
    """Canonical SMILES, or None when RDKit can't parse it. An empty
    string parses as a zero-atom Mol in RDKit — treat that, and any
    atomless parse, as invalid."""
    s = (smiles or "").strip()
    if not s:
        return None
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles(s)
        if m is None or m.GetNumAtoms() == 0:
            return None
        return Chem.MolToSmiles(m)
    except Exception:  # noqa: BLE001
        return None


def _heavy_atoms(smiles: str) -> int:
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles(smiles)
        return int(m.GetNumHeavyAtoms()) if m else 0
    except Exception:  # noqa: BLE001
        return 0


def _complexity(smiles: str) -> dict[str, int]:
    """Cheap structural-complexity signals for the heuristic fallback."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors
        m = Chem.MolFromSmiles(smiles)
        if m is None:
            return {"heavy": 0, "rings": 0, "rotatable": 0, "stereo": 0}
        return {
            "heavy": int(m.GetNumHeavyAtoms()),
            "rings": int(Descriptors.RingCount(m)),
            "rotatable": int(Lipinski.NumRotatableBonds(m)),
            "stereo": len(Chem.FindMolChiralCenters(m, includeUnassigned=True)),
            "aromatic_rings": int(rdMolDescriptors.CalcNumAromaticRings(m)),
        }
    except Exception:  # noqa: BLE001
        return {"heavy": 0, "rings": 0, "rotatable": 0, "stereo": 0}


# ─────────────────────────────────────────────────────────────────────
# Gemini retrosynthesis — proposer
# ─────────────────────────────────────────────────────────────────────

def _retro_prompt(smiles: str) -> str:
    return (
        "You are a senior synthetic / process chemist. Perform a concise "
        "RETROSYNTHETIC analysis of the target molecule and return a "
        "FORWARD synthetic route a medicinal-chemistry lab could run.\n\n"
        f"Target SMILES: {smiles}\n\n"
        "Rules:\n"
        "  - 2 to 6 steps. Prefer robust, well-precedented reactions "
        "(amide coupling, SNAr, Suzuki/Buchwald, reductive amination, "
        "Boc protect/deprotect, ester hydrolysis, etc.).\n"
        "  - Each step: the named transform, reaction_class, key "
        "reagents, conditions, and the product_smiles AFTER that step. "
        "The FINAL step's product_smiles MUST be the target.\n"
        "  - List the commercial starting materials with a realistic "
        "availability: 'in_stock' (common, <$50/g), 'catalog' "
        "(orderable, days), or 'custom' (must be made / long lead).\n"
        "  - Every SMILES must be a valid, parseable structure.\n\n"
        "Return STRICT JSON only:\n"
        "{\n"
        '  "steps": [{"name": "<transform>", "reaction_class": "<class>", '
        '"reagents": ["..."], "conditions": "<solvent, temp, time>", '
        '"product_smiles": "<SMILES after this step>", '
        '"rationale": "<=160 chars why this step"}],\n'
        '  "starting_materials": [{"name": "<name>", "smiles": "<SMILES>", '
        '"availability": "in_stock|catalog|custom"}],\n'
        '  "overall_notes": "<=200 chars route-level commentary"\n'
        "}\n"
    )


async def _gemini_route(smiles: str) -> Optional[dict[str, Any]]:
    """Ask Gemini for a retrosynthetic route. Returns the parsed JSON
    dict, or None on any failure (caller falls back to a heuristic)."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    primary = os.getenv("LYSOS_SYNTHESIS_MODEL", "gemini-2.5-pro")
    fallback = os.getenv("LYSOS_SYNTHESIS_FALLBACK", "gemini-2.5-flash")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": _retro_prompt(smiles)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 4096,
            "temperature": 0.3,
            "thinkingConfig": {"thinkingBudget": 1024, "includeThoughts": False},
        },
    }
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    for model in (primary, fallback):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=30.0) as cx:
                r = await cx.post(url, headers=headers, json=payload)
            if r.status_code in (429, 503):
                log.warning("synthesis %s returned %d — falling back", model, r.status_code)
                continue
            if r.status_code != 200:
                log.warning("synthesis gemini http %d: %s", r.status_code, r.text[:160])
                return None
            body = r.json()
            parts = ((body.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            raw = "".join(p.get("text", "") for p in parts).strip()
            if not raw:
                continue
            s = raw
            if s.startswith("```"):
                s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.M).strip()
            obj = json.loads(s)
            if isinstance(obj, dict) and obj.get("steps"):
                obj["_model"] = model
                return obj
        except Exception as exc:  # noqa: BLE001
            log.warning("synthesis gemini call failed (%s): %s", model, exc)
            continue
    return None


# ─────────────────────────────────────────────────────────────────────
# Heuristic fallback — when Gemini is unavailable
# ─────────────────────────────────────────────────────────────────────

def _heuristic_route(smiles: str) -> dict[str, Any]:
    """Deterministic skeleton route from RDKit complexity signals — so
    the service still returns something useful with no API key."""
    cx = _complexity(smiles)
    # More rings / rotatable bonds → more disconnections.
    n_steps = max(2, min(6, 1 + cx["rings"] // 2 + cx["rotatable"] // 4))
    steps = [
        {
            "name": f"Disconnection {i + 1}",
            "reaction_class": "generic bond formation",
            "reagents": [],
            "conditions": "to be determined by route scout",
            "product_smiles": smiles if i == n_steps - 1 else "",
            "product_valid": (i == n_steps - 1),
            "rationale": "Heuristic skeleton — connect Gemini for a "
                         "reaction-precedented route.",
        }
        for i in range(n_steps)
    ]
    return {
        "steps": steps,
        "starting_materials": [],
        "overall_notes": "Heuristic estimate from structural complexity "
                         "(no Gemini key). Step count scales with ring + "
                         "rotatable-bond count.",
        "_model": "heuristic",
    }


# ─────────────────────────────────────────────────────────────────────
# Route assembly — validate + cost (server-authoritative)
# ─────────────────────────────────────────────────────────────────────

def _assemble_route(smiles: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Validate every SMILES with RDKit, then compute cost / feasibility
    / lead-time from real signals. The model never sets the numbers."""
    target_canon = _canonical(smiles)
    steps_in = raw.get("steps") or []
    steps: list[dict[str, Any]] = []
    n_invalid = 0
    for i, st in enumerate(steps_in[:6]):
        if not isinstance(st, dict):
            continue
        prod = (st.get("product_smiles") or "").strip()
        prod_canon = _canonical(prod) if prod else None
        valid = prod_canon is not None
        if prod and not valid:
            n_invalid += 1
        steps.append({
            "step": i + 1,
            "name": str(st.get("name") or f"Step {i + 1}")[:80],
            "reaction_class": str(st.get("reaction_class") or "")[:60],
            "reagents": [str(x)[:40] for x in (st.get("reagents") or [])][:8],
            "conditions": str(st.get("conditions") or "")[:120],
            "product_smiles": prod_canon or prod,
            "product_valid": valid,
            "rationale": str(st.get("rationale") or "")[:200],
        })
    n_steps = len(steps) or 1

    # Starting materials — validate + price by availability.
    sms: list[dict[str, Any]] = []
    sm_cost = 0.0
    custom_count = 0
    for sm in (raw.get("starting_materials") or [])[:10]:
        if not isinstance(sm, dict):
            continue
        smi = (sm.get("smiles") or "").strip()
        canon = _canonical(smi) if smi else None
        avail = str(sm.get("availability") or "catalog").lower()
        if avail not in _AVAILABILITY:
            avail = "catalog"
        if avail == "custom":
            custom_count += 1
        cost = _SM_COST_USD[avail]
        sm_cost += cost
        sms.append({
            "name": str(sm.get("name") or "building block")[:80],
            "smiles": canon or smi,
            "smiles_valid": canon is not None,
            "availability": avail,
            "est_cost_usd": round(cost, 2),
        })

    # Does the final step actually land on the target?
    reaches_target = bool(
        steps and target_canon
        and steps[-1].get("product_valid")
        and steps[-1].get("product_smiles") == target_canon
    )

    # ── Cost (server-authoritative) ──
    est_cost = n_steps * _COST_PER_STEP_USD + sm_cost
    cost_band = "low" if est_cost < 300 else "moderate" if est_cost < 800 else "high"

    # ── Lead time ──
    lead_time_days = n_steps * 4 + custom_count * 14 + 3

    # ── Feasibility 0-1 — fewer steps, valid intermediates, stock SMs ──
    feas = 1.0
    feas -= 0.08 * max(0, n_steps - 3)         # step-count penalty
    feas -= 0.15 * n_invalid                   # invalid intermediate penalty
    feas -= 0.05 * custom_count                # custom-material penalty
    if not reaches_target and raw.get("_model") != "heuristic":
        feas -= 0.10                           # route doesn't close on target
    feasibility = round(max(0.1, min(1.0, feas)), 3)

    return {
        "smiles": target_canon or smiles,
        "n_steps": n_steps,
        "steps": steps,
        "starting_materials": sms,
        "route_reaches_target": reaches_target,
        "n_invalid_intermediates": n_invalid,
        "estimated_cost_usd": round(est_cost, 2),
        "cost_band": cost_band,
        "lead_time_days": lead_time_days,
        "feasibility": feasibility,
        "feasibility_band": (
            "ready" if feasibility >= 0.75
            else "workable" if feasibility >= 0.5
            else "hard"
        ),
        "overall_notes": str(raw.get("overall_notes") or "")[:240],
        "model": raw.get("_model") or "unknown",
        "computed_at": time.time(),
    }


# ─────────────────────────────────────────────────────────────────────
# API — compute
# ─────────────────────────────────────────────────────────────────────

class PlanRequest(BaseModel):
    smiles: str
    session_id: Optional[str] = None
    target_pathogen: Optional[str] = None
    save: bool = True          # persist the route as an artifact
    title: Optional[str] = None


@router.post("/synthesis/plan")
async def plan_synthesis(req: PlanRequest) -> dict[str, Any]:
    """SMILES → retrosynthetic route. Gemini proposes, RDKit validates,
    cost/feasibility computed server-side. Auto-saved as an artifact
    unless save=false."""
    smi = (req.smiles or "").strip()
    if not smi:
        raise HTTPException(400, "smiles required")
    if _canonical(smi) is None:
        raise HTTPException(422, f"unparseable SMILES: {smi}")

    raw = await _gemini_route(smi)
    if raw is None:
        raw = _heuristic_route(smi)
    route = _assemble_route(smi, raw)

    artifact_id = None
    if req.save:
        title = req.title or f"Route · {route['n_steps']} steps · {route['cost_band']} cost"
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, route,
            session_id=req.session_id, smiles=route["smiles"], title=title,
        )
        artifact_id = rec["id"]
    route["artifact_id"] = artifact_id
    return route


# ─────────────────────────────────────────────────────────────────────
# API — CRUD over saved routes
# ─────────────────────────────────────────────────────────────────────

@router.get("/synthesis/routes")
async def list_routes(
    session_id: Optional[str] = None,
    smiles: Optional[str] = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List saved synthesis routes, newest first."""
    rows = service_store.list_artifacts(
        kind=_ARTIFACT_KIND, session_id=session_id, smiles=smiles, limit=limit,
    )
    return {"routes": rows, "n": len(rows)}


@router.get("/synthesis/routes/{rid}")
async def get_route(rid: str) -> dict[str, Any]:
    rec = service_store.get_artifact(rid)
    if rec is None or rec.get("kind") != _ARTIFACT_KIND:
        raise HTTPException(404, f"synthesis route not found: {rid}")
    return rec


class RoutePatch(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
    starred: Optional[bool] = None


@router.patch("/synthesis/routes/{rid}")
async def update_route(rid: str, patch: RoutePatch) -> dict[str, Any]:
    """Update user annotations on a saved route (title / notes / star)."""
    rec = service_store.get_artifact(rid)
    if rec is None or rec.get("kind") != _ARTIFACT_KIND:
        raise HTTPException(404, f"synthesis route not found: {rid}")
    payload = dict(rec["payload"])
    if patch.notes is not None:
        payload["user_notes"] = patch.notes[:1000]
    if patch.starred is not None:
        payload["starred"] = bool(patch.starred)
    updated = service_store.update_artifact(rid, payload, title=patch.title)
    return updated or rec


@router.delete("/synthesis/routes/{rid}")
async def delete_route(rid: str) -> dict[str, Any]:
    rec = service_store.get_artifact(rid)
    if rec is None or rec.get("kind") != _ARTIFACT_KIND:
        raise HTTPException(404, f"synthesis route not found: {rid}")
    ok = service_store.delete_artifact(rid)
    return {"deleted": ok, "id": rid}
