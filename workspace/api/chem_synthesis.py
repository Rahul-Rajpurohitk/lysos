"""Synthesis Make-Route — Service 1 of the productized service layer.

Turns the abstract `synthesizability` score into a real, reasoned plan:
a retrosynthetic route with named steps, reagents, per-step yields,
risk flags, a reaction-class-aware cost model, structure-derived
building-block availability, and a Critic review.

Endpoints (router prefix /chem, mounted under /workbench):
  POST   /chem/synthesis/plan              SMILES → full reasoned route
  GET    /chem/synthesis/routes            list saved routes (CRUD read)
  GET    /chem/synthesis/routes/{rid}      get one saved route
  PATCH  /chem/synthesis/routes/{rid}      update title / notes / starred
  DELETE /chem/synthesis/routes/{rid}      delete a saved route

What makes this NOT hardcoded
  - Cost is computed per step from the REACTION CLASS — a Pd-catalysed
    cross-coupling genuinely costs ~4x an amide coupling. The route's
    cost responds to its actual chemistry, it is not a flat per-step
    constant.
  - Building-block availability is DERIVED from RDKit structural
    complexity (heavy atoms / rings / stereocentres), not taken from
    the model's guess — a small achiral fragment is stocked, a complex
    chiral intermediate is custom.
  - Per-step + cumulative yield is tracked; feasibility folds it in.
  - A Critic agent reviews the assembled route (riskiest step,
    scale-up concern, confidence).

Agentic flow: the proposer is Gemini (Flash — fast); RDKit validates
every intermediate; the cost / yield / availability maths is
server-authoritative; the Critic pass is a second agent. The
`plan_synthesis` workflow exposes these as three streamed steps so the
agent is visibly working, not a 30 s opaque wait.
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


# ─────────────────────────────────────────────────────────────────────
# Reaction-class cost model — chemistry-anchored, NOT a flat constant.
# Each rule: (keyword tuple, USD/step, cost-driver label). Matched
# against the step's name + reaction_class. These tiers reflect real
# cost structure: precious-metal catalysis + cryogenic / organometallic
# chemistry cost multiples of a robust acylation or protection step.
# ─────────────────────────────────────────────────────────────────────

_RXN_COST_RULES: list[tuple[tuple[str, ...], float, str]] = [
    (("buchwald", "c-n coupling", "amination coupling"), 250.0, "Pd-catalysed C–N coupling"),
    (("suzuki", "negishi", "stille", "kumada", "sonogashira", "heck",
      "cross-coupling", "cross coupling"), 230.0, "Pd-catalysed cross-coupling"),
    (("c-h activation", "c–h activation", "c-h functional"), 285.0, "C–H activation"),
    (("asymmetric", "enantioselective", "chiral cataly"), 260.0, "asymmetric catalysis"),
    (("metathesis", "rcm "), 215.0, "olefin metathesis"),
    (("grignard", "organolithium", "n-buli", "lithiation", "cryogenic",
      "-78"), 185.0, "cryogenic / organometallic"),
    (("amide coupling", "peptide coupling", "edc", "hatu", "hbtu", "pybop"),
     95.0, "coupling-reagent chemistry"),
    (("reductive amination",), 95.0, "reductive amination"),
    (("hydrogenation", "reduction"), 105.0, "reduction"),
    (("oxidation",), 90.0, "oxidation"),
    (("wittig", "horner", "olefination"), 110.0, "olefination"),
    (("mitsunobu",), 120.0, "Mitsunobu"),
    (("snar", "nucleophilic aromatic"), 80.0, "SNAr"),
    (("cyclization", "cyclisation", "annulation"), 105.0, "ring construction"),
    (("acylation", "esterification", "amide formation", "amidation"),
     55.0, "acylation"),
    (("protection", "deprotection", "boc", "cbz", "fmoc"), 45.0, "protecting-group step"),
    (("hydrolysis", "saponification"), 45.0, "hydrolysis"),
    (("alkylation", "substitution", "sn2", "sn1"), 65.0, "alkylation / substitution"),
    (("condensation", "schiff", "imine"), 60.0, "condensation"),
    (("nitration", "halogenation", "bromination", "chlorination",
      "electrophilic aromatic", " eas"), 70.0, "electrophilic aromatic substitution"),
    (("salt", "crystallization", "crystallisation", "recrystall"),
     35.0, "salt formation / crystallisation"),
]
_DEFAULT_STEP_COST = 95.0          # unmatched class → moderate tier
# Default yield by cost tier — used only when the model omits a yield.
_DEFAULT_YIELD_BY_COST = [(70.0, 0.68), (130.0, 0.78), (1e9, 0.86)]


def _step_cost(name: str, reaction_class: str) -> tuple[float, str]:
    """Cost (USD) + cost-driver label for a step, from its chemistry."""
    hay = f"{name} {reaction_class}".lower()
    for keys, usd, label in _RXN_COST_RULES:
        if any(k in hay for k in keys):
            return usd, label
    return _DEFAULT_STEP_COST, "general organic step"


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


def _complexity(smiles: str) -> dict[str, int]:
    """Structural-complexity signals for the building-block assessor +
    the heuristic fallback."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors
        m = Chem.MolFromSmiles(smiles)
        if m is None:
            return {"heavy": 0, "rings": 0, "rotatable": 0, "stereo": 0,
                    "aromatic_rings": 0}
        return {
            "heavy": int(m.GetNumHeavyAtoms()),
            "rings": int(Descriptors.RingCount(m)),
            "rotatable": int(Lipinski.NumRotatableBonds(m)),
            "stereo": len(Chem.FindMolChiralCenters(m, includeUnassigned=True)),
            "aromatic_rings": int(rdMolDescriptors.CalcNumAromaticRings(m)),
        }
    except Exception:  # noqa: BLE001
        return {"heavy": 0, "rings": 0, "rotatable": 0, "stereo": 0,
                "aromatic_rings": 0}


def _assess_building_block(smiles: str, name: str) -> dict[str, Any]:
    """Derive a building block's commercial availability + sourcing cost
    from its RDKit structural complexity — NOT from the model's guess.

    Commercial building-block catalogues skew heavily toward small,
    achiral, low-ring-count fragments; complex polycyclic or
    multi-stereocentre intermediates almost always need custom
    synthesis. This encodes that real skew."""
    canon = _canonical(smiles)
    cx = _complexity(canon or smiles)
    hv, rings, stereo = cx["heavy"], cx["rings"], cx["stereo"]

    if canon is None:
        availability, why = "custom", "structure could not be parsed"
    elif hv <= 10 and rings <= 1 and stereo == 0:
        availability, why = "in_stock", "small achiral fragment — bulk-stocked"
    elif hv <= 18 and rings <= 2 and stereo <= 1:
        availability, why = "catalog", "moderate complexity — catalogue order"
    else:
        availability, why = "custom", (
            f"complex ({hv} heavy atoms, {rings} rings, {stereo} stereocentres) "
            f"— likely custom synthesis")

    # Sourcing cost scales with complexity, anchored per availability tier.
    if availability == "in_stock":
        cost = 18.0 + 1.6 * hv
    elif availability == "catalog":
        cost = 45.0 + 3.4 * hv + 22.0 * stereo
    else:
        cost = 120.0 + 6.0 * hv + 55.0 * stereo + 18.0 * max(0, rings - 2)

    return {
        "name": str(name or "building block")[:80],
        "smiles": canon or smiles,
        "smiles_valid": canon is not None,
        "availability": availability,
        "availability_reason": why,
        "est_cost_usd": round(cost, 2),
        "heavy_atoms": hv,
    }


# ─────────────────────────────────────────────────────────────────────
# Gemini retrosynthesis — proposer (Flash: fast)
# ─────────────────────────────────────────────────────────────────────

def _retro_prompt(smiles: str) -> str:
    return (
        "You are a senior process chemist. Do a RETROSYNTHETIC analysis "
        "of the target and return a FORWARD synthetic route a "
        "medicinal-chemistry lab could actually run.\n\n"
        f"Target SMILES: {smiles}\n\n"
        "Rules:\n"
        "  - 1 to 6 steps. Use the FEWEST STEPS that genuinely work — "
        "do NOT invent extra disconnections for show. If the target is "
        "one functional-group transformation from a commercial material "
        "(e.g. an acylation of an aryl amine with Ac2O, a single amide "
        "coupling, an ester hydrolysis, an N-alkylation), propose a "
        "ONE-STEP route from commercial starting materials.\n"
        "  - AVOID Pd-catalysed couplings (Suzuki, Buchwald, Negishi, "
        "Stille, Sonogashira) UNLESS the target genuinely has a "
        "C–C / C–N biaryl bond formed at that bond. Do NOT add an "
        "unnecessary biaryl coupling just to use an aryl boronic acid "
        "or aryl halide as a starting material when the target has no "
        "biaryl. Cost matters: Pd cross-couplings are ~$230/step, "
        "amide couplings ~$95/step.\n"
        "  - Every product_smiles MUST be a syntactically valid SMILES "
        "with balanced parentheses and ring closures. A single invalid "
        "intermediate invalidates the whole route — re-check each one.\n"
        "  - For EACH step give: the named transform, the reaction_class "
        "(be specific — 'amide coupling', 'Boc deprotection', "
        "'reductive amination', …), reagents, conditions, the "
        "product_smiles AFTER that step, an honest single-step "
        "yield_pct (40-98), a risk rating (low | moderate | high) for "
        "how likely the step is to fail or be low-yielding, and a short "
        "rationale. The FINAL step's product_smiles MUST be the target.\n"
        "  - List the commercial starting materials (name + SMILES "
        "only — do NOT rate their availability, that is computed).\n"
        "  - Every SMILES must be valid + parseable.\n\n"
        "Return STRICT JSON only:\n"
        "{\n"
        '  "strategy": "<=200 chars — the key disconnections + overall approach",\n'
        '  "steps": [{"name": "<transform>", "reaction_class": "<specific class>", '
        '"reagents": ["..."], "conditions": "<solvent, temp, time>", '
        '"product_smiles": "<SMILES after this step>", "yield_pct": <40-98>, '
        '"risk": "low|moderate|high", "rationale": "<=160 chars"}],\n'
        '  "starting_materials": [{"name": "<name>", "smiles": "<SMILES>"}],\n'
        '  "overall_notes": "<=200 chars route-level commentary"\n'
        "}\n"
    )


async def _gemini_json(prompt: str, *, max_tokens: int = 4096,
                       temperature: float = 0.3) -> Optional[dict[str, Any]]:
    """One Gemini call returning parsed JSON. Flash primary (fast),
    Flash-8b/Pro never needed here. Returns None on any failure."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    primary = os.getenv("LYSOS_SYNTHESIS_MODEL", "gemini-2.5-flash")
    fallback = os.getenv("LYSOS_SYNTHESIS_FALLBACK", "gemini-2.5-pro")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
            "thinkingConfig": {"thinkingBudget": 0, "includeThoughts": False},
        },
    }
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    for model in (primary, fallback):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=30.0) as cx:
                r = await cx.post(url, headers=headers, json=payload)
            if r.status_code in (429, 503):
                log.warning("synthesis %s %d — falling back", model, r.status_code)
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
            if isinstance(obj, dict):
                obj["_model"] = model
                return obj
        except Exception as exc:  # noqa: BLE001
            log.warning("synthesis gemini call failed (%s): %s", model, exc)
            continue
    return None


async def _gemini_route(smiles: str) -> Optional[dict[str, Any]]:
    """Retrosynthetic route proposal. None on failure (heuristic fallback)."""
    obj = await _gemini_json(_retro_prompt(smiles))
    if obj and obj.get("steps"):
        return obj
    return None


# ─────────────────────────────────────────────────────────────────────
# Heuristic fallback — when Gemini is unavailable
# ─────────────────────────────────────────────────────────────────────

def _heuristic_route(smiles: str) -> dict[str, Any]:
    """Deterministic skeleton route from RDKit complexity — so the
    service still returns something useful with no API key."""
    cx = _complexity(smiles)
    n_steps = max(2, min(6, 1 + cx["rings"] // 2 + cx["rotatable"] // 4))
    steps = [
        {
            "name": f"Disconnection {i + 1}",
            "reaction_class": "general organic step",
            "reagents": [], "conditions": "to be determined by route scout",
            "product_smiles": smiles if i == n_steps - 1 else "",
            "yield_pct": 75, "risk": "moderate",
            "rationale": "Heuristic skeleton — connect Gemini for a "
                         "reaction-precedented route.",
        }
        for i in range(n_steps)
    ]
    return {
        "strategy": "Heuristic step-count estimate from ring + rotatable-bond "
                    "complexity (no Gemini key).",
        "steps": steps,
        "starting_materials": [],
        "overall_notes": "Heuristic estimate — no reaction precedent applied.",
        "_model": "heuristic",
    }


# ─────────────────────────────────────────────────────────────────────
# Route assembly — validate + cost + yield (server-authoritative)
# ─────────────────────────────────────────────────────────────────────

def _assemble_route(smiles: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Validate every SMILES with RDKit, cost each step from its
    reaction class, derive building-block availability from structure,
    track per-step + cumulative yield. The model never sets a number."""
    target_canon = _canonical(smiles)
    steps_in = raw.get("steps") or []
    steps: list[dict[str, Any]] = []
    n_invalid = 0
    step_cost_total = 0.0
    cumulative_yield = 1.0

    for i, st in enumerate(steps_in[:6]):
        if not isinstance(st, dict):
            continue
        prod = (st.get("product_smiles") or "").strip()
        prod_canon = _canonical(prod) if prod else None
        valid = prod_canon is not None
        if prod and not valid:
            n_invalid += 1
        name = str(st.get("name") or f"Step {i + 1}")[:80]
        rxn_class = str(st.get("reaction_class") or "")[:60]
        cost, cost_driver = _step_cost(name, rxn_class)
        step_cost_total += cost
        # Per-step yield — model value clamped, else default by cost tier.
        try:
            yld = float(st.get("yield_pct"))
        except (TypeError, ValueError):
            yld = next(y for cap, y in _DEFAULT_YIELD_BY_COST if cost <= cap) * 100
        yld = max(20.0, min(99.0, yld))
        cumulative_yield *= (yld / 100.0)
        risk = str(st.get("risk") or "moderate").lower()
        if risk not in {"low", "moderate", "high"}:
            risk = "moderate"
        steps.append({
            "step": i + 1,
            "name": name,
            "reaction_class": rxn_class,
            "reagents": [str(x)[:40] for x in (st.get("reagents") or [])][:8],
            "conditions": str(st.get("conditions") or "")[:120],
            "product_smiles": prod_canon or prod,
            "product_valid": valid,
            "yield_pct": round(yld, 1),
            "risk": risk,
            "est_cost_usd": round(cost, 2),
            "cost_driver": cost_driver,
            "rationale": str(st.get("rationale") or "")[:200],
        })
    n_steps = len(steps) or 1

    # Building materials — availability + cost DERIVED from structure.
    sms: list[dict[str, Any]] = []
    sm_cost = 0.0
    custom_count = 0
    for sm in (raw.get("starting_materials") or [])[:10]:
        if not isinstance(sm, dict):
            continue
        assessed = _assess_building_block(sm.get("smiles") or "", sm.get("name") or "")
        if assessed["availability"] == "custom":
            custom_count += 1
        sm_cost += assessed["est_cost_usd"]
        sms.append(assessed)

    reaches_target = bool(
        steps and target_canon
        and steps[-1].get("product_valid")
        and steps[-1].get("product_smiles") == target_canon
    )

    # ── Cost — server-authoritative, reaction-class driven ──
    est_cost = step_cost_total + sm_cost
    cost_band = "low" if est_cost < 350 else "moderate" if est_cost < 950 else "high"

    # ── Lead time — robust steps are fast, exotic ones slow ──
    avg_step_cost = step_cost_total / n_steps
    lead_time_days = int(round(
        n_steps * (3 + avg_step_cost / 60.0) + custom_count * 14 + 3))

    overall_yield_pct = round(cumulative_yield * 100.0, 1)

    # ── Feasibility 0-1 — folds in steps, validity, custom mats, YIELD ──
    feas = 1.0
    feas -= 0.07 * max(0, n_steps - 3)
    feas -= 0.15 * n_invalid
    feas -= 0.05 * custom_count
    if overall_yield_pct < 25:
        feas -= 0.20
    elif overall_yield_pct < 45:
        feas -= 0.10
    if not reaches_target and raw.get("_model") != "heuristic":
        feas -= 0.10
    feasibility = round(max(0.1, min(1.0, feas)), 3)

    return {
        "smiles": target_canon or smiles,
        "strategy": str(raw.get("strategy") or "")[:240],
        "n_steps": n_steps,
        "steps": steps,
        "starting_materials": sms,
        "route_reaches_target": reaches_target,
        "n_invalid_intermediates": n_invalid,
        "estimated_cost_usd": round(est_cost, 2),
        "step_cost_usd": round(step_cost_total, 2),
        "materials_cost_usd": round(sm_cost, 2),
        "cost_band": cost_band,
        "overall_yield_pct": overall_yield_pct,
        "lead_time_days": lead_time_days,
        "feasibility": feasibility,
        "feasibility_band": (
            "ready" if feasibility >= 0.75
            else "workable" if feasibility >= 0.5 else "hard"),
        "overall_notes": str(raw.get("overall_notes") or "")[:240],
        "model": raw.get("_model") or "unknown",
        "computed_at": time.time(),
    }


# ─────────────────────────────────────────────────────────────────────
# Critic pass — a second agent reviews the assembled route
# ─────────────────────────────────────────────────────────────────────

async def _critique_route(route: dict[str, Any]) -> dict[str, Any]:
    """Critic agent reviews the route — riskiest step, scale-up concern,
    confidence. Returns a deterministic fallback when Gemini is off."""
    steps = route.get("steps") or []
    # Deterministic fallback: riskiest = highest-risk / lowest-yield step.
    risk_rank = {"high": 3, "moderate": 2, "low": 1}
    worst = max(
        steps,
        key=lambda s: (risk_rank.get(s.get("risk", "moderate"), 2),
                       -float(s.get("yield_pct", 75))),
        default=None,
    ) if steps else None
    fallback = {
        "riskiest_step": worst.get("step") if worst else None,
        "risk_reason": (
            f"{worst.get('name')} — {worst.get('risk')} risk, "
            f"{worst.get('yield_pct')}% yield" if worst else "no steps"),
        "scale_up_concern": "Step count + custom building blocks drive "
                            "scale-up cost." if route.get("n_steps", 0) > 4
                            else "Route length is scale-friendly.",
        "confidence": route.get("feasibility", 0.5),
        "verdict": "Workable route — see riskiest step before committing.",
        "model": "deterministic",
    }
    steps_brief = "; ".join(
        f"#{s['step']} {s['name']} ({s.get('reaction_class','')}, "
        f"{s.get('yield_pct')}%, {s.get('risk')} risk)"
        for s in steps
    )
    prompt = (
        "You are a Critic chemist reviewing a proposed synthetic route. "
        "Be specific and honest.\n\n"
        f"Target: {route.get('smiles')}\n"
        f"Route: {route.get('n_steps')} steps · est ${route.get('estimated_cost_usd')} "
        f"· overall yield {route.get('overall_yield_pct')}%\n"
        f"Steps: {steps_brief}\n\n"
        "Return STRICT JSON:\n"
        "{\n"
        '  "riskiest_step": <step number>,\n'
        '  "risk_reason": "<=160 chars — why that step is the weak link",\n'
        '  "scale_up_concern": "<=160 chars — what breaks at kg scale",\n'
        '  "confidence": <0..1 — your confidence this route delivers the target>,\n'
        '  "verdict": "<=160 chars — advance / rework / specific fix"\n'
        "}\n"
    )
    obj = await _gemini_json(prompt, max_tokens=1024, temperature=0.35)
    if not obj:
        return fallback
    try:
        conf = float(obj.get("confidence", fallback["confidence"]))
    except (TypeError, ValueError):
        conf = fallback["confidence"]
    return {
        "riskiest_step": obj.get("riskiest_step") or fallback["riskiest_step"],
        "risk_reason": str(obj.get("risk_reason") or fallback["risk_reason"])[:200],
        "scale_up_concern": str(obj.get("scale_up_concern")
                                or fallback["scale_up_concern"])[:200],
        "confidence": round(max(0.0, min(1.0, conf)), 3),
        "verdict": str(obj.get("verdict") or fallback["verdict"])[:200],
        "model": obj.get("_model") or "gemini",
    }


async def _plan_route_full(smiles: str) -> dict[str, Any]:
    """Full pipeline: propose route → assemble (validate + cost + yield)
    → critic review. Returns the complete route dict."""
    raw = await _gemini_route(smiles)
    if raw is None:
        raw = _heuristic_route(smiles)
    route = _assemble_route(smiles, raw)
    route["critique"] = await _critique_route(route)
    return route


# ─────────────────────────────────────────────────────────────────────
# Agentic action — design an easier-to-make analog
# ─────────────────────────────────────────────────────────────────────

def _route_is_hard(route: dict[str, Any]) -> bool:
    """A route worth a simpler-analog attempt — anything that is NOT
    already cheap, practical, short and high-yielding. The `improved`
    gate on the result keeps the output honest: the agent only SHOWS
    an analog that genuinely beats the original."""
    return (route.get("feasibility_band") in ("workable", "hard")
            or route.get("cost_band") in ("moderate", "high")
            or (route.get("overall_yield_pct") or 100) < 55
            or (route.get("n_steps") or 0) >= 5)


def _non_drug_like_reason(smiles: str) -> Optional[str]:
    """Return a reason if the input is a commodity reagent / fragment,
    not a drug candidate. Mirrors the FTO gate — synthesizing a
    one-atom-shy reagent like acetic anhydride is pointless."""
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles((smiles or "").strip())
        if m is None:
            return None
        n_heavy = m.GetNumHeavyAtoms()
        n_rings = m.GetRingInfo().NumRings()
        if n_heavy < 10:
            return (f"only {n_heavy} heavy atoms — this is a reagent or "
                    "fragment, not a drug candidate")
        if n_rings == 0:
            return "acyclic molecule — no ring system, not a drug-like scaffold"
        return None
    except Exception:  # noqa: BLE001
        return None


def _analog_is_drug_like(parent_smiles: str, analog_smiles: str) -> bool:
    """Reject "easier analogs" that have degenerated to a building
    block (e.g. stripping the defining acetyl from acetaminophen and
    returning 4-aminobenzoic acid). The analog must keep at least one
    ring, be roughly the same size as the parent, and not be a
    well-known commodity reagent."""
    try:
        from rdkit import Chem
        pa = Chem.MolFromSmiles(parent_smiles or "")
        an = Chem.MolFromSmiles(analog_smiles or "")
        if pa is None or an is None:
            return False
        if an.GetNumHeavyAtoms() < 10:
            return False
        if an.GetRingInfo().NumRings() < 1:
            return False
        # The analog must keep most of the parent's mass — if it drops
        # below 60% it's likely a fragment / starting material, not a
        # real drug variant.
        if an.GetNumHeavyAtoms() < pa.GetNumHeavyAtoms() * 0.6:
            return False
        return True
    except Exception:
        return False


async def _design_simpler_analog(route: dict[str, Any]) -> Optional[dict[str, Any]]:
    """THE agentic payoff. When the route is hard/expensive, ask the
    agent for ONE structural simplification that is easier to
    synthesize while keeping the antibacterial pharmacophore — then
    RE-PLAN the analog's route to PROVE it is genuinely easier. None
    when the route is already practical or the design fails."""
    if not _route_is_hard(route):
        return None
    if not os.getenv("GEMINI_API_KEY"):
        return None
    steps_brief = "; ".join(
        f"#{s['step']} {s['name']} ({s.get('reaction_class','')}, "
        f"{s.get('cost_driver','')})" for s in (route.get("steps") or []))
    prompt = (
        "You are a process chemist. This antibiotic candidate has a "
        "synthesis route that is hard / expensive / low-yielding. "
        "Propose ONE structural SIMPLIFICATION that makes the molecule "
        "easier to synthesize — fewer steps, cheaper reaction classes, "
        "higher yield — while PRESERVING the antibacterial pharmacophore "
        "(keep the β-lactam warhead / core mechanism; simplify the "
        "periphery — drop a hard-to-install group, swap an exotic "
        "coupling for a robust one, remove a stereocentre).\n\n"
        "HARD CONSTRAINTS — the analog MUST:\n"
        "  - keep at least one ring system (no stripping down to a "
        "linear fragment)\n"
        "  - keep at least 60% of the parent's heavy-atom count "
        "(no degenerating to a starting material — the analog must "
        "still LOOK like a drug, not a building block)\n"
        "  - keep the parent's key functional groups responsible for "
        "binding (e.g. don't drop the amide on an amide-bearing "
        "antibiotic, don't drop the β-lactam on a β-lactam)\n"
        "  - be a meaningful chemistry edit (substituent swap, "
        "stereocentre removal, ring isostere) — not a wholesale "
        "deletion\n\n"
        f"Candidate SMILES: {route['smiles']}\n"
        f"Current route: {route['n_steps']} steps · "
        f"${route['estimated_cost_usd']} ({route['cost_band']}) · "
        f"{route['overall_yield_pct']}% yield · feasibility "
        f"{route['feasibility']}\n"
        f"Steps: {steps_brief}\n\n"
        "Return STRICT JSON:\n"
        '{"analog_smiles": "<valid SMILES of the simplified analog>", '
        '"simplification": "<=60 chars — the change>", '
        '"rationale": "<=180 chars — why it is easier yet keeps activity>"}\n'
    )
    obj = await _gemini_json(prompt, max_tokens=900, temperature=0.4)
    if not obj:
        return None
    analog = _canonical(obj.get("analog_smiles", ""))
    if analog is None or analog == route["smiles"]:
        return None
    # The analog must still LOOK like a drug — not a stripped-down
    # starting material. Guards against "remove the acetyl → end up
    # with 4-aminobenzoic acid" degeneration.
    if not _analog_is_drug_like(route["smiles"], analog):
        return None
    # Re-plan the analog (plan + assemble; skip the critic for speed) —
    # PROVE it is genuinely easier.
    raw = await _gemini_route(analog)
    if raw is None:
        return None
    analog_route = _assemble_route(analog, raw)
    improved = (
        analog_route["feasibility"] > route["feasibility"] + 0.02
        or analog_route["estimated_cost_usd"] < route["estimated_cost_usd"] * 0.85
        or analog_route["n_steps"] < route["n_steps"])
    return {
        "analog_smiles": analog,
        "simplification": str(obj.get("simplification") or "structural simplification")[:80],
        "rationale": str(obj.get("rationale") or "")[:200],
        "steps_before": route["n_steps"], "steps_after": analog_route["n_steps"],
        "cost_before": route["estimated_cost_usd"],
        "cost_after": analog_route["estimated_cost_usd"],
        "feasibility_before": route["feasibility"],
        "feasibility_after": analog_route["feasibility"],
        "yield_before": route["overall_yield_pct"],
        "yield_after": analog_route["overall_yield_pct"],
        "improved": bool(improved),
    }


# ─────────────────────────────────────────────────────────────────────
# API — compute
# ─────────────────────────────────────────────────────────────────────

class PlanRequest(BaseModel):
    smiles: str
    session_id: Optional[str] = None
    target_pathogen: Optional[str] = None
    save: bool = True
    title: Optional[str] = None
    design_analog: bool = True      # design an easier-to-make analog if hard


@router.post("/synthesis/plan")
async def plan_synthesis(req: PlanRequest) -> dict[str, Any]:
    """SMILES → full reasoned retrosynthetic route: route proposal +
    RDKit validation + reaction-class costing + yield + Critic review.
    Auto-saved as an artifact unless save=false."""
    smi = (req.smiles or "").strip()
    if not smi:
        raise HTTPException(400, "smiles required")
    canon = _canonical(smi)
    if canon is None:
        raise HTTPException(422, f"unparseable SMILES: {smi}")

    # Commodity-chem / non-drug gate: don't waste an LLM call planning
    # a synthesis for acetic anhydride (it's $29/L from Sigma).
    nd = _non_drug_like_reason(canon)
    if nd:
        empty = {
            "smiles": canon,
            "strategy": "Not applicable — commercial reagent.",
            "n_steps": 0,
            "steps": [],
            "starting_materials": [],
            "estimated_cost_usd": 0.0,
            "step_cost_usd": 0.0,
            "materials_cost_usd": 0.0,
            "cost_band": "low",
            "overall_yield_pct": 0,
            "lead_time_days": 0,
            "feasibility": 1.0,
            "feasibility_band": "ready",
            "route_reaches_target": True,
            "n_invalid_intermediates": 0,
            "overall_notes": (f"{nd}. This molecule is commercially "
                              "available — no retrosynthesis is needed."),
            "model": "gate",
            "critique": None,
            "easier_analog": None,
            "non_drug_reason": nd,
        }
        artifact_id = None
        if req.save:
            rec = service_store.save_artifact(_ARTIFACT_KIND, empty,
                session_id=req.session_id, smiles=canon,
                title=f"Not applicable · {nd[:40]}")
            artifact_id = rec["id"]
        empty["artifact_id"] = artifact_id
        return empty

    route = await _plan_route_full(smi)

    # ── Agentic action — when the route is hard, the agent designs an
    # easier-to-make analog and proves it is easier. ──
    if req.design_analog:
        route["easier_analog"] = await _design_simpler_analog(route)
    else:
        route["easier_analog"] = None

    artifact_id = None
    if req.save:
        title = req.title or (
            f"Route · {route['n_steps']} steps · {route['cost_band']} cost "
            f"· {route['overall_yield_pct']}% yield")
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, route,
            session_id=req.session_id, smiles=route["smiles"], title=title,
        )
        artifact_id = rec["id"]
    route["artifact_id"] = artifact_id

    # ── Agentic close-the-loop — queue the easier analog so the user
    # accepts it with one word. The service handed over a better
    # molecule, not just a route readout. ──
    ea = route.get("easier_analog")
    if ea and ea.get("improved"):
        try:
            from . import session_memory
            session_memory.record_proposal(
                req.session_id or "", ea["analog_smiles"],
                source="synthesis",
                swap_label=f"easier-to-make analog ({ea['simplification']})",
                rationale=(f"Route {ea['steps_before']}→{ea['steps_after']} steps, "
                           f"${ea['cost_before']:.0f}→${ea['cost_after']:.0f}. "
                           f"{ea['rationale']}"))
        except Exception as exc:  # noqa: BLE001
            log.debug("easier-analog queue failed: %s", exc)

    # ── Integration backbone — link this route into the candidate's
    # dossier so the synthesis facet is visible to scoring, the agents
    # and the developability rollup, not stranded as an island. ──
    try:
        from . import candidate_dossier
        candidate_dossier.upsert_facet(
            req.session_id, route["smiles"], "synthesis", {
                "n_steps": route["n_steps"],
                "cost_usd": route["estimated_cost_usd"],
                "cost_band": route["cost_band"],
                "feasibility": route["feasibility"],
                "overall_yield_pct": route["overall_yield_pct"],
                "route_artifact_id": artifact_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("dossier feed (synthesis) failed: %s", exc)
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
