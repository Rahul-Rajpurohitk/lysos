"""Candidate Dossier — the integration backbone of the service layer.

Every productized service used to be an island: scoring computed a
composite, resistance computed robustness, synthesis computed a route —
but nothing LINKED them. There was no per-candidate object that said
"here is everything we know about this molecule, and how developable
it therefore is."

The Candidate Dossier is that object. It is keyed by
(session_id, canonical_smiles) and accumulates a FACET per service:

    score       — 12-axis composite + weakest axis
    resistance  — robustness + escape-vector count vs the target
    synthesis   — route step count, cost, feasibility, yield
    target      — the pathogen / gene / mechanism the candidate is for
    fto         — freedom-to-operate (Service 2, later)
    admet       — ADMET / PK panel (Service 3, later)
    regimen     — combination / adjuvant (Service 4, later)

As the user runs services ("as we move"), facets fill in. A
developability rollup turns the facet set into the thing that actually
matters to a drug-discovery user: how fully characterised the
candidate is, how ready it looks, what is still missing, and what the
cross-facet red flags are.

Linkage is harness-level: the workflow executor calls `feed_from_state`
after every run, so ANY workflow that touches a candidate auto-links
its results — no per-service wiring to drift.

Endpoints (router prefix /chem, mounted under /workbench):
  GET /chem/dossier/{session_id}             every candidate dossier (portfolio)
  GET /chem/dossier/{session_id}/candidate   one dossier  (?smiles=…)
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from . import service_store

log = logging.getLogger("api.candidate_dossier")
router = APIRouter(prefix="/chem", tags=["candidate_dossier"])

_ARTIFACT_KIND = "candidate_dossier"

# The six per-candidate developability facets. `target` is pathogen
# context, not a developability axis, so it is tracked but excluded
# from the characterised-fraction maths.
_DEV_FACETS = ["score", "docking", "resistance", "synthesis", "fto", "admet", "regimen"]


# ─────────────────────────────────────────────────────────────────────
# Keys
# ─────────────────────────────────────────────────────────────────────

def _canon(smiles: str) -> Optional[str]:
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
        return s  # fall back to the raw string so the dossier still keys


def _dossier_id(session_id: str, canonical_smiles: str) -> str:
    """Deterministic id so upserts target the SAME dossier."""
    h = hashlib.sha1(f"{session_id or '_'}|{canonical_smiles}".encode()).hexdigest()
    return f"dos_{h[:16]}"


# ─────────────────────────────────────────────────────────────────────
# Developability rollup
# ─────────────────────────────────────────────────────────────────────

def _facet_goodness(facet: str, data: dict[str, Any]) -> Optional[float]:
    """Normalise a facet's headline metric to 0-1 'how good is it'."""
    try:
        if facet == "score":
            v = data.get("composite")
            return float(v) if v is not None else None
        if facet == "resistance":
            v = data.get("robustness")
            return float(v) if v is not None else None
        if facet == "synthesis":
            v = data.get("feasibility")
            return float(v) if v is not None else None
        if facet == "fto":
            # higher = freer to operate
            v = data.get("freedom_score")
            return float(v) if v is not None else None
        if facet == "admet":
            v = data.get("overall_safety_score")
            return float(v) if v is not None else None
        if facet == "regimen":
            v = data.get("best_synergy")
            return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
    return None


def _compute_developability(facets: dict[str, Any]) -> dict[str, Any]:
    """Roll the facet set into a developability verdict."""
    present = [f for f in _DEV_FACETS if isinstance(facets.get(f), dict)]
    characterized = len(present)
    characterized_pct = round(characterized / len(_DEV_FACETS), 3)

    goods = [g for f in present
             if (g := _facet_goodness(f, facets[f])) is not None]
    mean_good = round(sum(goods) / len(goods), 3) if goods else 0.0
    # Readiness rewards BOTH quality and completeness — a 0.9-score
    # candidate with 1/6 facets is not "ready".
    readiness = round(mean_good * (0.4 + 0.6 * characterized_pct), 3)

    gaps = [f for f in _DEV_FACETS if f not in present]

    # Cross-facet red flags.
    flags: list[str] = []
    sc = facets.get("score") or {}
    rs = facets.get("resistance") or {}
    sy = facets.get("synthesis") or {}
    if isinstance(sc.get("composite"), (int, float)) and sc["composite"] < 0.40:
        flags.append("low composite score")
    if isinstance(rs.get("robustness"), (int, float)) and rs["robustness"] < 0.70:
        flags.append("resistance-fragile target binding")
    if isinstance(sy.get("feasibility"), (int, float)) and sy["feasibility"] < 0.50:
        flags.append("synthesis route is hard")
    if sy.get("cost_band") == "high":
        flags.append("high synthesis cost")
    if isinstance(sy.get("overall_yield_pct"), (int, float)) and sy["overall_yield_pct"] < 25:
        flags.append("very low overall synthesis yield")

    tier = ("advance" if readiness >= 0.7 and characterized >= 3
            else "promising" if readiness >= 0.5
            else "early" if characterized >= 1
            else "uncharacterized")

    return {
        "characterized": characterized,
        "total_facets": len(_DEV_FACETS),
        "characterized_pct": characterized_pct,
        "mean_facet_quality": mean_good,
        "readiness": readiness,
        "tier": tier,
        "gaps": gaps,
        "flags": flags,
    }


# ─────────────────────────────────────────────────────────────────────
# Linkage API — services call upsert_facet
# ─────────────────────────────────────────────────────────────────────

def upsert_facet(
    session_id: Optional[str],
    smiles: str,
    facet: str,
    data: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Attach (or refresh) one service's result onto the candidate's
    dossier, then recompute developability. Returns the full dossier,
    or None when the SMILES is unusable.

    This is the ONE linkage call every service makes — score,
    resistance, synthesis, knowledge, fto, admet, regimen."""
    canon = _canon(smiles)
    if not canon:
        return None
    sid = session_id or "_global"
    did = _dossier_id(sid, canon)
    existing = service_store.get_artifact(did)
    payload: dict[str, Any] = existing["payload"] if existing else {
        "session_id": sid,
        "smiles": canon,
        "facets": {},
        "created_at": time.time(),
    }
    facets = payload.setdefault("facets", {})
    facets[facet] = {**data, "_updated_at": time.time()}
    payload["developability"] = _compute_developability(facets)
    payload["updated_at"] = time.time()

    dev = payload["developability"]
    title = (f"{canon[:24]} · {dev['characterized']}/{dev['total_facets']} "
             f"facets · {dev['tier']}")
    rec = service_store.save_artifact(
        _ARTIFACT_KIND, payload, session_id=sid, smiles=canon,
        title=title, artifact_id=did,
    )
    return rec["payload"]


def get_dossier(session_id: Optional[str], smiles: str) -> Optional[dict[str, Any]]:
    canon = _canon(smiles)
    if not canon:
        return None
    rec = service_store.get_artifact(_dossier_id(session_id or "_global", canon))
    return rec["payload"] if rec else None


def list_dossiers(session_id: Optional[str]) -> list[dict[str, Any]]:
    """Every candidate dossier in a session — the portfolio view."""
    rows = service_store.list_artifacts(
        kind=_ARTIFACT_KIND, session_id=session_id or "_global", limit=200,
    )
    return [r["payload"] for r in rows]


def dossier_summary(session_id: Optional[str], smiles: str) -> str:
    """One-line dossier summary for the agent context / session brief."""
    dos = get_dossier(session_id, smiles)
    if not dos:
        return ""
    dev = dos.get("developability") or {}
    facets = dos.get("facets") or {}
    bits: list[str] = []
    sc = facets.get("score") or {}
    if sc.get("composite") is not None:
        bits.append(f"score {sc['composite']:.3f}")
    rs = facets.get("resistance") or {}
    if rs.get("robustness") is not None:
        bits.append(f"robustness {rs['robustness']:.2f}")
    sy = facets.get("synthesis") or {}
    if sy.get("feasibility") is not None:
        bits.append(f"synthesis {sy.get('cost_band','?')}-cost/"
                    f"feasibility {sy['feasibility']:.2f}")
    line = (f"Candidate dossier: {dev.get('characterized', 0)}/"
            f"{dev.get('total_facets', 6)} facets characterised, "
            f"readiness {dev.get('readiness', 0)}, tier {dev.get('tier', '?')}.")
    if bits:
        line += " " + " · ".join(bits) + "."
    if dev.get("flags"):
        line += " Flags: " + "; ".join(dev["flags"]) + "."
    if dev.get("gaps"):
        line += " Not yet run: " + ", ".join(dev["gaps"]) + "."
    return line


# ─────────────────────────────────────────────────────────────────────
# Harness hook — auto-link from any workflow's final state
# ─────────────────────────────────────────────────────────────────────

def feed_from_state(state: dict[str, Any]) -> list[str]:
    """Called by the workflow executor after every run. Inspects the
    workflow's final state and upserts whatever facets it can find —
    so ANY workflow that touches a candidate auto-links its results
    into that candidate's dossier, with no per-workflow wiring.

    Returns the list of facets fed (for logging/telemetry)."""
    sid = state.get("_session_id") or state.get("session_id")
    smi = (state.get("smiles") or state.get("current_smiles")
           or state.get("winner") or "")
    if not smi:
        # design_with_debate stores the winner under debate.winner
        deb = state.get("debate") or {}
        smi = deb.get("winner") or ""
    if not smi or not _canon(smi):
        return []

    fed: list[str] = []

    # ── score facet ──
    score = state.get("winner_score") or state.get("score")
    if score is None:
        scored = state.get("scored")
        if isinstance(scored, list) and scored:
            score = scored[0]
    if isinstance(score, dict) and score.get("composite") is not None:
        upsert_facet(sid, smi, "score", {
            "composite": score.get("composite"),
            "weakest": score.get("weakest"),
        })
        fed.append("score")

    # ── resistance facet ──
    pred = state.get("prediction") or state.get("resistance")
    if isinstance(pred, dict) and pred.get("robustness_score") is not None:
        va = pred.get("vulnerable_atoms") or []
        upsert_facet(sid, smi, "resistance", {
            "robustness": pred.get("robustness_score"),
            "n_vulnerable": len(va),
            "target": pred.get("target_name") or pred.get("pdb_id"),
        })
        fed.append("resistance")

    # ── synthesis facet ──
    route = state.get("synthesis_route")
    if isinstance(route, dict) and route.get("n_steps") and not route.get("error"):
        upsert_facet(sid, smi, "synthesis", {
            "n_steps": route.get("n_steps"),
            "cost_usd": route.get("estimated_cost_usd"),
            "cost_band": route.get("cost_band"),
            "feasibility": route.get("feasibility"),
            "overall_yield_pct": route.get("overall_yield_pct"),
            "route_artifact_id": route.get("artifact_id"),
        })
        fed.append("synthesis")

    # ── fto facet ──
    fto = state.get("fto_report")
    if isinstance(fto, dict) and fto.get("novelty_score") is not None:
        esc = fto.get("escape_variant") or {}
        upsert_facet(sid, smi, "fto", {
            "novelty_score": fto.get("novelty_score"),
            "freedom_score": fto.get("novelty_score"),  # dossier-compat key
            "verdict": fto.get("verdict"),
            "closest_similarity": fto.get("closest_published_similarity"),
            "escape_variant_smiles": esc.get("variant_smiles"),
        })
        fed.append("fto")

    # ── docking facet ──
    dock = state.get("dock_result") or state.get("docking")
    if isinstance(dock, dict) and dock.get("affinity_kcal_mol") is not None:
        upsert_facet(sid, smi, "docking", {
            "affinity_kcal_mol": dock.get("affinity_kcal_mol"),
            "band": dock.get("affinity_band"),
            "target": dock.get("target_name") or dock.get("pdb_id"),
            "n_interactions": dock.get("n_interactions"),
            "engine": dock.get("engine"),
        })
        fed.append("docking")

    # ── admet facet ──
    admet = state.get("admet_panel")
    if isinstance(admet, dict) and admet.get("composite") is not None \
            and not admet.get("error"):
        worst = admet.get("worst") or {}
        fix = admet.get("fix") or {}
        upsert_facet(sid, smi, "admet", {
            "composite": admet.get("composite"),
            "tier": admet.get("tier"),
            "weakest_axis": worst.get("axis"),
            "weakest_score": worst.get("score"),
            "fix_smiles": fix.get("variant_smiles") if fix.get("improved") else None,
            "panel_artifact_id": admet.get("artifact_id"),
            "source": admet.get("source", "heuristic"),
        })
        fed.append("admet")

    # ── target facet (pathogen context) ──
    pathogen = state.get("pathogen")
    if pathogen:
        upsert_facet(sid, smi, "target", {
            "pathogen": pathogen,
            "pdb_id": state.get("pdb_id"),
        })
        fed.append("target")

    if fed:
        log.info("dossier fed facets %s for %s", fed, smi[:32])
    return fed


# ─────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────

@router.get("/dossier/{session_id}")
async def list_session_dossiers(session_id: str) -> dict[str, Any]:
    """The session's whole candidate portfolio with developability."""
    dossiers = list_dossiers(session_id)
    dossiers.sort(
        key=lambda d: (d.get("developability") or {}).get("readiness", 0),
        reverse=True,
    )
    return {"session_id": session_id, "n": len(dossiers), "dossiers": dossiers}


@router.get("/dossier/{session_id}/candidate")
async def get_candidate_dossier(session_id: str, smiles: str) -> dict[str, Any]:
    """One candidate's full dossier."""
    dos = get_dossier(session_id, smiles)
    if dos is None:
        raise HTTPException(404, f"no dossier for {smiles} in {session_id}")
    return dos
