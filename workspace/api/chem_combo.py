"""Combination & Adjuvant Lab — the AMR-era frontline strategy.

Against resistant pathogens, monotherapy often loses; the win comes from
PAIRING the active agent with an adjuvant that disarms the resistance
mechanism. Ceftazidime-avibactam, meropenem-vaborbactam, amoxicillin-
clavulanate — every one is a β-lactam rescued by a β-lactamase inhibitor.
This service recommends those pairings, mechanism-first.

How it stays honest (no fabricated synergy numbers):
  1. The pathogen's COMPROMISED drug classes come straight from the CARD
     resistance landscape (the resistome service) — real data.
  2. A curated knowledge base of real adjuvant classes (β-lactamase
     inhibitors, efflux-pump inhibitors, outer-membrane permeabilizers,
     PK boosters) each declares the resistance MECHANISM it counters and
     the marketed combinations that prove it.
  3. An adjuvant is recommended only when its mechanism counters a class
     the pathogen actually resists AND it partners the candidate's class.
     The evidence shown is the MECHANISM + the real marketed precedent —
     not a made-up FIC index. An illustrative isobologram is drawn and
     LABELLED as a mechanism-based schematic, never as measured data.

Six-layer contract: service_store · this module · agent tool · workflow ·
orchestrator · frontend CombinationLabCard + dossier.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.combo")
router = APIRouter(prefix="/chem", tags=["combo"])

_ARTIFACT_KIND = "combo_suggest"
_SELF = os.getenv("LYSOS_SELF_URL", "http://127.0.0.1:7860")

# ─────────────────────────────────────────────────────────────────────
# Curated adjuvant / potentiator knowledge base. Every entry is a real
# clinical or clinical-stage strategy. `counters` are substrings matched
# against the pathogen's compromised drug-class names (from CARD); the
# `partner_classes` are the antibiotic classes the adjuvant is paired with.
# ─────────────────────────────────────────────────────────────────────

_ADJUVANTS: list[dict[str, Any]] = [
    {"id": "avibactam", "name": "Avibactam", "klass": "β-lactamase inhibitor (DBO)",
     "mechanism": "Reversible covalent inhibition of serine β-lactamases "
                  "(class A incl. KPC/ESBL, class C AmpC, some class D OXA).",
     "counters": ["beta_lactam", "cephalosporin", "carbapenem", "ceftazidime",
                  "ceftaroline", "ampicillin", "ceftazidime_avibactam"],
     "partner_classes": ["beta_lactam"],
     "real_combos": ["ceftazidime-avibactam", "aztreonam-avibactam (vs MBL)"],
     "stage": "marketed", "tier": 1},
    {"id": "vaborbactam", "name": "Vaborbactam", "klass": "β-lactamase inhibitor (boronate)",
     "mechanism": "Cyclic boronate inhibitor of class A carbapenemases "
                  "(esp. KPC); restores carbapenem activity.",
     "counters": ["carbapenem", "beta_lactam"],
     "partner_classes": ["beta_lactam"],
     "real_combos": ["meropenem-vaborbactam"],
     "stage": "marketed", "tier": 1},
    {"id": "relebactam", "name": "Relebactam", "klass": "β-lactamase inhibitor (DBO)",
     "mechanism": "DBO inhibitor of class A (KPC) and class C (AmpC) "
                  "β-lactamases; restores carbapenem activity.",
     "counters": ["carbapenem", "beta_lactam", "cephalosporin"],
     "partner_classes": ["beta_lactam"],
     "real_combos": ["imipenem-cilastatin-relebactam"],
     "stage": "marketed", "tier": 1},
    {"id": "clavulanate", "name": "Clavulanate", "klass": "β-lactamase inhibitor (β-lactam)",
     "mechanism": "Suicide inhibitor of class A β-lactamases (incl. "
                  "staphylococcal blaZ, many ESBLs).",
     "counters": ["beta_lactam", "ampicillin", "cephalosporin"],
     "partner_classes": ["beta_lactam"],
     "real_combos": ["amoxicillin-clavulanate", "ticarcillin-clavulanate"],
     "stage": "marketed", "tier": 1},
    {"id": "tazobactam", "name": "Tazobactam", "klass": "β-lactamase inhibitor (β-lactam)",
     "mechanism": "Class A β-lactamase inhibitor; broadens penicillin cover "
                  "to many ESBL producers.",
     "counters": ["beta_lactam", "ampicillin", "cephalosporin"],
     "partner_classes": ["beta_lactam"],
     "real_combos": ["piperacillin-tazobactam", "ceftolozane-tazobactam"],
     "stage": "marketed", "tier": 1},
    {"id": "paben", "name": "PAβN", "klass": "efflux-pump inhibitor",
     "mechanism": "Competitive inhibitor of RND efflux pumps (e.g. MexAB-OprM, "
                  "AcrAB-TolC); re-sensitises efflux-mediated resistance.",
     "counters": ["fluoroquinolone", "tetracycline", "chloramphenicol", "novobiocin"],
     "partner_classes": ["fluoroquinolone", "tetracycline"],
     "real_combos": ["research tool (not clinically approved)"],
     "stage": "research", "tier": 3},
    {"id": "spr741", "name": "SPR741 / PMBN", "klass": "outer-membrane permeabiliser",
     "mechanism": "Polymyxin-derived potentiator that disrupts the Gram-"
                  "negative outer membrane, admitting otherwise-excluded "
                  "drugs (rifampicin, macrolides, fusidic acid).",
     "counters": ["beta_lactam", "cephalosporin", "vancomycin", "novobiocin"],
     "partner_classes": ["macrolide", "ansamycin", "glycopeptide"],
     "real_combos": ["SPR741 + rifampicin (clinical-stage)"],
     "stage": "clinical-stage", "tier": 2},
    {"id": "probenecid", "name": "Probenecid", "klass": "PK booster",
     "mechanism": "Blocks renal tubular secretion of β-lactams → higher, "
                  "longer plasma exposure (raises %fT>MIC) without touching "
                  "the resistance mechanism.",
     "counters": ["beta_lactam", "cephalosporin", "ampicillin"],
     "partner_classes": ["beta_lactam"],
     "real_combos": ["amoxicillin-probenecid", "cefazolin-probenecid"],
     "stage": "marketed", "tier": 2},
]

# Map our pathogen codes / candidate hints to a coarse antibiotic class so we
# can tell whether the candidate is a valid PARTNER for an adjuvant.
_CLASS_ALIASES = {
    "beta_lactam": ["beta_lactam", "β-lactam", "penicillin", "cephalosporin",
                    "carbapenem", "monobactam", "lactam"],
    "fluoroquinolone": ["fluoroquinolone", "quinolone"],
    "tetracycline": ["tetracycline", "glycylcycline"],
    "glycopeptide": ["glycopeptide", "vancomycin"],
    "macrolide": ["macrolide"],
    "ansamycin": ["ansamycin", "rifam"],
}


def _norm(s: str) -> str:
    return (s or "").lower().replace("-", "_").replace(" ", "_")


def _candidate_class(drug_class: Optional[str]) -> Optional[str]:
    if not drug_class:
        return None
    n = _norm(drug_class)
    for canon, aliases in _CLASS_ALIASES.items():
        if any(a in n for a in aliases):
            return canon
    return n


async def _compromised_classes(pathogen: str) -> list[dict[str, Any]]:
    """Pull the pathogen's resistance landscape → the drug classes it is
    under pressure on, from the real CARD-backed resistome service."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.get(f"{_SELF}/workbench/chem/resistome/{pathogen}")
            if r.status_code != 200:
                return []
            land = r.json().get("drug_class_landscape", [])
            out = []
            for c in land:
                dc = c.get("drug_class", "")
                n = c.get("n_determinants", c.get("n_mutations", 0)) or 0
                band = (c.get("pressure_band") or c.get("pressure")
                        or ("saturated" if n >= 3 else "pressured" if n >= 1
                            else "headroom"))
                if n > 0 or band in ("saturated", "pressured"):
                    out.append({"drug_class": dc, "n_determinants": n, "band": band})
            return out
    except Exception:  # noqa: BLE001
        return []


def _match(adj: dict[str, Any], compromised: list[dict[str, Any]],
           cand_class: Optional[str]) -> dict[str, Any]:
    """Score an adjuvant against the pathogen's compromised classes."""
    comp_norm = [_norm(c["drug_class"]) for c in compromised]
    hits = []
    for cc, cn in zip(compromised, comp_norm):
        if any(_norm(k) in cn or cn in _norm(k) for k in adj["counters"]):
            hits.append(cc)
    # Does the candidate's class partner this adjuvant?
    partners_candidate = (cand_class is not None
                          and cand_class in adj["partner_classes"])
    if hits and partners_candidate:
        interaction, band = "synergy (mechanism-matched)", "strong"
    elif hits:
        interaction, band = "potentiation if partnered with a "  \
            f"{adj['partner_classes'][0]}", "moderate"
    else:
        interaction, band = "no mechanism match for this pathogen", "weak"
    # rank: tier (1 best) then #hits then candidate-partner
    rank = (0 if hits else 1, adj["tier"], -len(hits),
            0 if partners_candidate else 1)
    return {"hits": hits, "interaction": interaction, "band": band,
            "partners_candidate": partners_candidate, "_rank": rank}


def _isobologram(band: str) -> list[dict[str, float]]:
    """Illustrative isobologram curve for the interaction band (NOT measured).
    Synergy bows toward the origin (FIC < 1); additivity is the diagonal."""
    # convexity factor: strong synergy bows in hard, weak ≈ additive line
    k = {"strong": 0.28, "moderate": 0.55, "weak": 1.0}.get(band, 1.0)
    pts = []
    for i in range(11):
        fa = i / 10.0                      # fractional dose of drug A
        # convex curve through (0,1)-(1,0): fb = (1-fa)^(1/k)-ish; use power
        fb = (1.0 - fa) ** (1.0 / k) if k < 1.0 else (1.0 - fa)
        pts.append({"a": round(fa, 3), "b": round(fb, 3)})
    return pts


def _suggest(smiles: str, pathogen: str, drug_class: Optional[str],
             compromised: list[dict[str, Any]]) -> dict[str, Any]:
    t0 = time.time()
    cand_class = _candidate_class(drug_class)
    scored = []
    for adj in _ADJUVANTS:
        m = _match(adj, compromised, cand_class)
        scored.append({
            "id": adj["id"], "name": adj["name"], "klass": adj["klass"],
            "mechanism": adj["mechanism"], "stage": adj["stage"],
            "real_combos": adj["real_combos"],
            "partner_classes": adj["partner_classes"],
            "counters_hit": [h["drug_class"] for h in m["hits"]],
            "interaction": m["interaction"], "band": m["band"],
            "partners_candidate": m["partners_candidate"],
            "isobologram": _isobologram(m["band"]),
            "_rank": m["_rank"],
        })
    scored.sort(key=lambda s: s["_rank"])
    for s in scored:
        s.pop("_rank", None)
    n_matched = sum(1 for s in scored if s["counters_hit"])
    top = scored[0] if scored and scored[0]["counters_hit"] else None
    return {
        "smiles": smiles, "pathogen": pathogen,
        "candidate_class": cand_class,
        "compromised_classes": compromised,
        "n_compromised": len(compromised),
        "suggestions": scored, "n_matched": n_matched,
        "top": top,
        "elapsed_s": round(time.time() - t0, 3),
        "computed_at": time.time(),
        "engine": "CARD resistance landscape × curated adjuvant KB (mechanism match)",
        "note": ("Recommendations are mechanism-based: an adjuvant is matched "
                 "when it disarms a resistance mechanism the pathogen actually "
                 "carries (CARD) and partners the candidate's class. Evidence is "
                 "the mechanism + the marketed combination precedent. The "
                 "isobologram is an illustrative schematic of the predicted "
                 "interaction, not a measured FIC."),
    }


class ComboRequest(BaseModel):
    smiles: str
    pathogen: str = "MRSA"
    drug_class: Optional[str] = None
    session_id: Optional[str] = None
    save: bool = True


@router.post("/combo/suggest")
async def combo_suggest(req: ComboRequest) -> dict[str, Any]:
    """Mechanism-matched adjuvant / combination recommendations for the
    candidate against the pathogen's real resistance landscape."""
    compromised = await _compromised_classes(req.pathogen)
    result = _suggest(req.smiles, req.pathogen, req.drug_class, compromised)
    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, result, session_id=req.session_id,
            smiles=req.smiles,
            title=(f"Combo · {result['n_matched']} adjuvant match(es) · "
                   f"{req.pathogen}"))
        artifact_id = rec["id"]
    result["artifact_id"] = artifact_id

    if req.session_id and result.get("top"):
        try:
            from . import candidate_dossier as _dossier
            _dossier.upsert_facet(req.session_id, req.smiles, "combination", {
                "top_adjuvant": result["top"]["name"],
                "interaction": result["top"]["band"],
                "n_matched": result["n_matched"],
                "precedent": (result["top"]["real_combos"][0]
                              if result["top"]["real_combos"] else None),
            })
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/combo/adjuvants")
async def combo_adjuvants() -> dict[str, Any]:
    """The curated adjuvant / potentiator knowledge base."""
    return {"n_adjuvants": len(_ADJUVANTS), "adjuvants": [
        {k: a[k] for k in ("id", "name", "klass", "mechanism", "partner_classes",
                           "real_combos", "stage", "tier")} for a in _ADJUVANTS]}


@router.get("/combo/runs")
async def list_runs(session_id: Optional[str] = None) -> dict[str, Any]:
    return {"items": service_store.list_artifacts(kind=_ARTIFACT_KIND,
                                                  session_id=session_id)}
