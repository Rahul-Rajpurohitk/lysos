"""ADMET Observatory — Service 3.

Five-axis pharmacokinetic + safety panel for an antibiotic candidate.
Each axis is computed from RDKit physchem using established medchem
heuristics (Veber, Egan, Hou, Norinder); the T (toxicity) axis defers
to the existing /molecule/toxicity endpoint (hERG, hepatotox, AMES,
skin sens) for the SMARTS-based toxicophore scan.

THE AGENT ACTION: identify the worst-scoring axis, ask Gemini for one
structural edit that improves it without crashing the others, RDKit-
validate the result, re-panel the analog, and only surface the
improvement if it genuinely moves the worst axis up. The user accepts
with one tap.

Six-layer contract:
  1. service_store CRUD substrate (shared SQLite)
  2. backend compute (this module)
  3. agent tool (workspace/api/agent.py · predict_admet)
  4. workflow (workspace/api/workflows.py · admet_panel)
  5. orchestrator route catalog (workspace/api/orchestrator.py)
  6. frontend card (workspace/web/.../ADMETObservatoryCard.tsx) + dossier feed
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store, session_memory

log = logging.getLogger("lysos.chem_admet")
router = APIRouter(prefix="/chem", tags=["chem_admet"])

_ARTIFACT_KIND = "admet_panel"


# ─────────────────────────────────────────────────────────────────────
# RDKit helpers + non-drug gate (mirror of the other services)
# ─────────────────────────────────────────────────────────────────────

def _canonical(smiles: str) -> Optional[str]:
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles((smiles or "").strip())
        if m is None or m.GetNumAtoms() == 0:
            return None
        return Chem.MolToSmiles(m)
    except Exception:  # noqa: BLE001
        return None


def _non_drug_like_reason(smiles: str) -> Optional[str]:
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles((smiles or "").strip())
        if m is None:
            return None
        n_heavy = m.GetNumHeavyAtoms()
        n_rings = m.GetRingInfo().NumRings()
        if n_heavy < 10:
            return (f"only {n_heavy} heavy atoms — likely a reagent or "
                    "fragment, not a drug candidate")
        if n_rings == 0:
            return "acyclic molecule — no ring system, not a drug-like scaffold"
        return None
    except Exception:  # noqa: BLE001
        return None


def _physchem(smiles: str) -> Optional[dict[str, Any]]:
    """RDKit descriptors used by every axis below."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Crippen, rdMolDescriptors
    except ImportError:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    n_basic_n = sum(
        1 for atom in mol.GetAtoms()
        if atom.GetSymbol() == "N"
        and not atom.GetIsAromatic()
        and atom.GetFormalCharge() <= 0
    )
    return {
        "mw": float(Descriptors.MolWt(mol)),
        "logp": float(Crippen.MolLogP(mol)),
        "tpsa": float(rdMolDescriptors.CalcTPSA(mol)),
        "hbd": int(rdMolDescriptors.CalcNumHBD(mol)),
        "hba": int(rdMolDescriptors.CalcNumHBA(mol)),
        "rotb": int(rdMolDescriptors.CalcNumRotatableBonds(mol)),
        "aromatic_rings": int(rdMolDescriptors.CalcNumAromaticRings(mol)),
        "fraction_csp3": float(rdMolDescriptors.CalcFractionCSP3(mol)),
        "n_heavy": int(mol.GetNumHeavyAtoms()),
        "n_basic_n": n_basic_n,
    }


# ─────────────────────────────────────────────────────────────────────
# REAL MODEL BRIDGE — ADMET-AI (Chemprop-RDKit, 41 TDC endpoints)
#
# Calls the isolated model service (workspace/model_services/admet_service.py),
# which on AMD MI300X is the "Lysos Inference Service". When the service is
# up we use REAL model predictions; otherwise we fall back to the physchem
# heuristics below. Every panel carries a `source` so the UI + honesty layer
# can show provenance.
# ─────────────────────────────────────────────────────────────────────

_ADMET_SERVICE_URL = os.getenv("LYSOS_ADMET_SERVICE_URL", "http://127.0.0.1:7920")


async def _real_admet(smiles: str) -> Optional[dict[str, Any]]:
    """POST the SMILES to the ADMET-AI service. Returns the raw
    {endpoint: value} dict, or None if the service is down / errored."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.post(f"{_ADMET_SERVICE_URL}/predict",
                              json={"smiles": [smiles]})
        if r.status_code != 200:
            return None
        body = r.json()
        if not body.get("ok"):
            return None
        preds = (body.get("predictions") or {}).get(smiles)
        if not isinstance(preds, dict) or "_error" in preds:
            return None
        return preds
    except Exception:  # noqa: BLE001 — service down is expected; fall back
        return None


def _find(raw: dict[str, Any], *needles: str) -> Optional[float]:
    """First endpoint whose name contains any needle (case-insensitive),
    skipping the `_drugbank_approved_percentile` variants."""
    low = {k.lower(): v for k, v in raw.items()}
    for n in needles:
        n = n.lower()
        for k, v in low.items():
            if n in k and "percentile" not in k:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
    return None


def _pctile(raw: dict[str, Any], *needles: str) -> Optional[float]:
    """The `<endpoint>_drugbank_approved_percentile` (0-100) for an
    endpoint — a clean normalized 'how approved-drug-like' signal."""
    low = {k.lower(): v for k, v in raw.items()}
    for n in needles:
        n = n.lower()
        for k, v in low.items():
            if n in k and "percentile" in k:
                try:
                    return float(v) / 100.0
                except (TypeError, ValueError):
                    continue
    return None


def _axes_from_admet_ai(raw: dict[str, Any], pc: dict[str, Any]) -> dict[str, Any]:
    """Map ADMET-AI's real TDC endpoints onto our A/D/M/E/T axis schema.

    Scoring policy (correct + honest):
    - Classification endpoints (HIA, Bioavailability, BBB, CYP*, hERG,
      AMES, DILI, ...) are probabilities in [0,1] — used directly, with the
      right polarity (for tox, lower prob = safer → score = 1-p).
    - Regression endpoints (Half_Life, Clearance, Caco2, Solubility, PPBR,
      VDss) come on log/transformed scales that are NOT human units, so we
      score from each endpoint's `_drugbank_approved_percentile` (0-100 =
      how approved-drug-like the value is). We only DISPLAY a raw number
      when its unit is trustworthy (PPBR %, Caco2 log cm/s, Solubility
      log mol/L); ambiguous-unit endpoints (half-life, clearance, Vd) are
      shown as a percentile-vs-approved instead of a fabricated unit.
    """
    def clamp(x: Optional[float], lo=0.0, hi=1.0) -> Optional[float]:
        return None if x is None else max(lo, min(hi, x))

    def mean(xs: list[Optional[float]]) -> float:
        vals = [x for x in xs if x is not None]
        return sum(vals) / len(vals) if vals else 0.5

    # ── A — Absorption ──
    hia = _find(raw, "HIA_Hou", "HIA")                 # prob high absorption
    bioav = _find(raw, "Bioavailability_Ma", "Bioavailability")
    caco2 = _find(raw, "Caco2_Wang", "Caco2")          # log cm/s (real unit)
    sol = _find(raw, "Solubility_AqSolDB", "Solubility")  # log mol/L (real)
    caco2_pct = _pctile(raw, "Caco2")
    sol_pct = _pctile(raw, "Solubility")
    a_score = mean([hia, bioav, caco2_pct, sol_pct])
    A = {
        "score": round(a_score, 3), "band": _band(a_score, 0.7, 0.45),
        "f_percent": round((bioav if bioav is not None else a_score) * 100, 1),
        "hia_percent": round((hia if hia is not None else a_score) * 100, 1),
        "caco2_logcm_s": round(caco2, 2) if caco2 is not None else None,
        "solubility_logmol_l": round(sol, 2) if sol is not None else None,
        "notes": [],
    }

    # ── D — Distribution ──
    ppb = _find(raw, "PPBR_AZ", "PPBR")                 # % bound (real unit)
    vd_pct = _pctile(raw, "VDss")
    bbb = _find(raw, "BBB_Martins", "BBB")             # prob permeable
    ppb_pct = ppb if (ppb is not None and ppb > 1) else (ppb * 100 if ppb is not None else None)
    # Approved antibiotics span a wide PPB range; score "drug-likeness" of
    # the PPB via its approved-percentile, not a hand-tuned peak.
    ppb_drug_pct = _pctile(raw, "PPBR")
    d_score = mean([ppb_drug_pct, vd_pct])
    D = {
        "score": round(d_score, 3), "band": _band(d_score, 0.7, 0.45),
        "ppb_percent": round(ppb_pct, 1) if ppb_pct is not None else None,
        "free_fraction_percent": round(100 - ppb_pct, 1) if ppb_pct is not None else None,
        "bbb_class": ("permeable" if (bbb or 0) >= 0.5 else "limited"),
        "vd_percentile": round(vd_pct * 100, 0) if vd_pct is not None else None,
        "notes": [],
    }

    # ── M — Metabolism (CYP inhibition probs; lower = better) ──
    cyp3a4 = _find(raw, "CYP3A4_Veith", "CYP3A4")
    cyp2d6 = _find(raw, "CYP2D6_Veith", "CYP2D6")
    cyp2c9 = _find(raw, "CYP2C9_Veith", "CYP2C9")
    hlm = clamp(1.0 - mean([cyp3a4, cyp2d6, cyp2c9]))
    m_score = round(hlm, 3)
    M = {
        "score": m_score, "band": _band(m_score, 0.65, 0.4),
        "cyp3a4_inhib_risk": round(cyp3a4, 3) if cyp3a4 is not None else None,
        "cyp2d6_inhib_risk": round(cyp2d6, 3) if cyp2d6 is not None else None,
        "cyp2c9_inhib_risk": round(cyp2c9, 3) if cyp2c9 is not None else None,
        "hlm_stability": round(hlm, 3),
        "hlm_band": ("stable" if hlm >= 0.65 else "moderate" if hlm >= 0.4 else "labile"),
        "notes": [],
    }

    # ── E — Excretion (score from approved-percentile, not raw log units) ──
    thalf_pct = _pctile(raw, "Half_Life")
    cl_pct = _pctile(raw, "Clearance_Hepatocyte", "Clearance")
    e_score = round(mean([thalf_pct, cl_pct]), 3)
    # Dosing band from the half-life percentile (higher pct = longer t½ =
    # less frequent dosing) — honest framing without a fabricated hour value.
    tp = thalf_pct if thalf_pct is not None else 0.5
    if tp >= 0.66: dose = "infrequent dosing likely (long t½)"
    elif tp >= 0.33: dose = "standard dosing interval"
    else: dose = "frequent dosing likely (short t½)"
    E = {
        "score": e_score, "band": _band(e_score, 0.7, 0.4),
        "t_half_percentile": round(tp * 100, 0),
        "clearance_percentile": round(cl_pct * 100, 0) if cl_pct is not None else None,
        "dose_interval": dose,
        "notes": [],
    }

    # ── T — Toxicity (probabilities; lower = better) ──
    herg = _find(raw, "hERG")
    ames = _find(raw, "AMES")
    dili = _find(raw, "DILI")
    carc = _find(raw, "Carcinogens_Lagunin", "Carcinogen")
    clintox = _find(raw, "ClinTox")
    t_safety = clamp(1.0 - mean([herg, ames, dili, carc, clintox]))
    t_score = round(t_safety, 3)
    def risk(p): return "high" if (p or 0) >= 0.6 else "medium" if (p or 0) >= 0.3 else "low"
    T = {
        "score": t_score, "band": _band(t_score, 0.7, 0.4),
        "herg_risk": risk(herg), "herg_score": round(herg, 3) if herg is not None else None,
        "hepatotox_risk": risk(dili), "hepatotox_score": round(dili, 3) if dili is not None else None,
        "ames_risk": risk(ames), "ames_score": round(ames, 3) if ames is not None else None,
        "carcinogen_risk": risk(carc),
        "notes": [],
    }
    return {"A": A, "D": D, "M": M, "E": E, "T": T}


def _band(score: float, good_at: float, mod_at: float) -> str:
    return "good" if score >= good_at else "moderate" if score >= mod_at else "poor"


# ─────────────────────────────────────────────────────────────────────
# Five-axis predictions — each returns a normalized score 0-1
# (higher = better for the drug program) + a per-axis detail dict.
# HEURISTIC FALLBACK — used when the real ADMET-AI service is unavailable.
# ─────────────────────────────────────────────────────────────────────

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _predict_absorption(pc: dict[str, Any]) -> dict[str, Any]:
    """Veber/Egan/Hou-style oral-F prediction.
    - Veber: TPSA ≤ 140 AND RotBonds ≤ 10 ⇒ likely orally bioavailable.
    - F% heuristic: penalize TPSA above 60, RotBonds above 5.
    - Caco-2 Papp: empirical from LogP + TPSA (Hou 2003).
    - HIA%: Egan 2000 — TPSA-driven."""
    tpsa = pc["tpsa"]; rotb = pc["rotb"]; logp = pc["logp"]; mw = pc["mw"]
    # F% heuristic. F = 100 * sigmoid(-(TPSA/30 + RotB/10 - 5))
    f_pct = 100.0 / (1.0 + math.exp((tpsa / 30.0 + rotb / 10.0 - 5.0)))
    f_pct = max(0.0, min(100.0, f_pct))
    # Caco-2 (log Papp, 10^-6 cm/s scale). Hou: LogPapp ≈ -4.36 + 0.36*LogP - 0.012*TPSA.
    log_papp = -4.36 + 0.36 * logp - 0.012 * tpsa
    papp_e6 = 10.0 ** (log_papp + 6)  # ×1e-6 cm/s, so add 6 to log
    papp_e6 = max(0.05, min(50.0, papp_e6))
    # HIA % (Egan 2000): high when TPSA<131 & -1<LogP<5.88.
    hia_pct = 100.0 if (tpsa < 131 and -1 < logp < 5.88) else 60.0
    if tpsa >= 140: hia_pct = 40.0
    if tpsa >= 200: hia_pct = 20.0
    # Veber pass/fail
    veber_ok = tpsa <= 140 and rotb <= 10
    # Score: weighted mean of normalized F, HIA, Caco-2 strength.
    score = _clamp01(0.5 * (f_pct / 100.0)
                     + 0.3 * (hia_pct / 100.0)
                     + 0.2 * _clamp01((math.log10(papp_e6) + 1.5) / 3.0))
    band = "good" if score >= 0.7 else "moderate" if score >= 0.45 else "poor"
    notes: list[str] = []
    if tpsa > 140: notes.append(f"TPSA {tpsa:.0f} > 140 (Veber-fail)")
    if rotb > 10: notes.append(f"RotB {rotb} > 10 (Veber-fail)")
    if mw > 500: notes.append(f"MW {mw:.0f} > 500")
    return {
        "score": round(score, 3), "band": band,
        "f_percent": round(f_pct, 1),
        "caco2_papp_1e6": round(papp_e6, 2),
        "hia_percent": round(hia_pct, 1),
        "veber_ok": veber_ok,
        "notes": notes,
    }


def _predict_distribution(pc: dict[str, Any]) -> dict[str, Any]:
    """PPB + BBB + Vd. For antibiotics, we generally want:
    - PPB moderate (50-90%) — too high reduces free fraction.
    - BBB usually NO (peripheral); CNS antibiotics need yes.
    - Vd in normal range (0.5-5 L/kg)."""
    logp = pc["logp"]; tpsa = pc["tpsa"]
    # PPB% — empirical from LogP (Yamazaki 2002 style).
    ppb_pct = 100.0 / (1.0 + math.exp(-(logp - 1.5))) * 0.96 + 4
    ppb_pct = max(5.0, min(99.5, ppb_pct))
    # BBB — Egan: TPSA ≤ 90 AND -1 < LogP < 5 ⇒ permeable.
    bbb_perm = (tpsa <= 90) and (-1 < logp < 5)
    bbb_class = "permeable" if bbb_perm else "limited"
    # Vd estimate (L/kg) — rough.
    vd = round(0.5 + max(0, logp) * 0.5, 2)
    # Free fraction (= 1 - PPB / 100)
    f_free = 100.0 - ppb_pct
    # Antibiotic-friendly score: moderate PPB + reasonable Vd.
    ppb_score = _clamp01(1.0 - abs(ppb_pct - 70.0) / 60.0)  # peak at 70%
    vd_score = _clamp01(1.0 - abs(vd - 1.5) / 3.0)
    score = _clamp01(0.6 * ppb_score + 0.4 * vd_score)
    band = "good" if score >= 0.7 else "moderate" if score >= 0.45 else "poor"
    notes: list[str] = []
    if ppb_pct > 95: notes.append(f"PPB {ppb_pct:.0f}% — free fraction {f_free:.1f}%")
    if vd > 5: notes.append(f"Vd {vd} L/kg — wide tissue distribution")
    return {
        "score": round(score, 3), "band": band,
        "ppb_percent": round(ppb_pct, 1),
        "free_fraction_percent": round(f_free, 1),
        "bbb_class": bbb_class,
        "bbb_permeable": bbb_perm,
        "vd_lpkg": vd,
        "notes": notes,
    }


def _predict_metabolism(pc: dict[str, Any]) -> dict[str, Any]:
    """CYP inhibition heuristics + HLM stability.
    - CYP3A4 inhibitors tend to be lipophilic + multi-ring.
    - CYP2D6 binds basic amines.
    - HLM stability correlates with sp3 fraction (more sp3 = more
      stable against oxidative metabolism)."""
    logp = pc["logp"]; ar = pc["aromatic_rings"]
    n_basic_n = pc["n_basic_n"]; csp3 = pc["fraction_csp3"]
    # CYP3A4 inhibition risk
    cyp3a4 = _clamp01(0.18 * max(0, logp - 2.5) + 0.18 * max(0, ar - 2))
    # CYP2D6 inhibition risk
    cyp2d6 = _clamp01(0.20 * max(0, n_basic_n) + 0.10 * max(0, logp - 2))
    # CYP2C9 inhibition (lipophilic acids)
    cyp2c9 = _clamp01(0.15 * max(0, logp - 3) + 0.10 * max(0, pc["hbd"] - 1))
    # HLM stability (higher = more stable)
    hlm = _clamp01(0.45 + 0.55 * csp3 - 0.10 * max(0, logp - 4))
    hlm_band = "stable" if hlm >= 0.65 else "moderate" if hlm >= 0.4 else "labile"
    # Score: HLM weighted higher (drives dose interval); penalize CYP inhibition.
    score = _clamp01(0.55 * hlm
                     + 0.15 * (1 - cyp3a4)
                     + 0.15 * (1 - cyp2d6)
                     + 0.15 * (1 - cyp2c9))
    band = "good" if score >= 0.65 else "moderate" if score >= 0.4 else "poor"
    notes: list[str] = []
    if cyp3a4 >= 0.5: notes.append("likely CYP3A4 inhibitor — DDI risk")
    if cyp2d6 >= 0.5: notes.append("likely CYP2D6 inhibitor — basic-amine driven")
    if hlm < 0.4: notes.append("low HLM stability — fast clearance expected")
    return {
        "score": round(score, 3), "band": band,
        "cyp3a4_inhib_risk": round(cyp3a4, 3),
        "cyp2d6_inhib_risk": round(cyp2d6, 3),
        "cyp2c9_inhib_risk": round(cyp2c9, 3),
        "hlm_stability": round(hlm, 3),
        "hlm_band": hlm_band,
        "notes": notes,
    }


def _predict_excretion(pc: dict[str, Any], met: dict[str, Any]) -> dict[str, Any]:
    """Clearance + dose-interval estimate from LogP + HLM stability.
    Antibiotic-relevant: short t½ means more frequent dosing, which
    hurts compliance."""
    logp = pc["logp"]; mw = pc["mw"]; hlm = met["hlm_stability"]
    # Renal fraction — small + polar molecules go renal (Lombardo 2014 style).
    renal_frac = _clamp01((-0.18 * logp) + 0.55 + (0.001 * (300 - mw)))
    # Total clearance proxy (mL/min/kg) — inversely related to HLM stability.
    cl_total = round(2 + 15 * (1 - hlm), 2)
    # Dose interval — short t½ → frequent dose. Half-life proxy from
    # clearance: t½ ≈ 0.693 * Vd / CL. Use Vd=1 L/kg average for the dosage band.
    t_half_h = round(0.693 * 1.0 / max(0.5, cl_total) * 1000.0, 1)  # hours
    if t_half_h >= 12:
        dose_interval = "q24h (once daily)"
    elif t_half_h >= 6:
        dose_interval = "q12h (twice daily)"
    elif t_half_h >= 3:
        dose_interval = "q8h (three times daily)"
    else:
        dose_interval = "q6h or shorter (frequent dosing)"
    # Score: longer t½ is better for compliance.
    score = _clamp01(min(t_half_h / 12.0, 1.0))
    band = "good" if score >= 0.7 else "moderate" if score >= 0.4 else "poor"
    notes: list[str] = []
    if t_half_h < 4: notes.append(f"short t½ {t_half_h}h — compliance risk")
    if renal_frac > 0.7: notes.append("predominantly renal — dose-adjust for CKD patients")
    return {
        "score": round(score, 3), "band": band,
        "clearance_mlminkg": cl_total,
        "renal_fraction": round(renal_frac, 3),
        "t_half_hours": t_half_h,
        "dose_interval": dose_interval,
        "notes": notes,
    }


async def _predict_toxicity(canon: str) -> dict[str, Any]:
    """Defer to the existing /molecule/toxicity endpoint internally —
    same SMARTS-based hERG/hepatotox/AMES/skin-sens panel that the
    Toxicity card already uses. We translate its `overall_safety_score`
    into our normalized 0-1 axis."""
    from . import workbench  # avoid circular import at module top
    try:
        prof = await workbench.molecule_toxicity(canon)  # type: ignore[attr-defined]
    except HTTPException:
        return {"score": 0.5, "band": "unknown",
                "herg_risk": "unknown", "hepatotox_risk": "unknown",
                "ames_risk": "unknown", "notes": ["toxicity endpoint failed"]}
    # The endpoint already produces overall_safety_score (1 = clean, 0 = unsafe).
    score = float(prof.overall_safety_score)
    band = "good" if score >= 0.7 else "moderate" if score >= 0.4 else "poor"
    notes: list[str] = []
    if prof.herg_risk == "high": notes.append("hERG: high — cardiotox deal-breaker")
    if prof.hepatotox_risk == "high": notes.append("hepatotox: high")
    if prof.ames_risk == "high": notes.append("AMES: high — mutagenic")
    return {
        "score": round(score, 3), "band": band,
        "herg_risk": prof.herg_risk, "herg_score": prof.herg_score,
        "hepatotox_risk": prof.hepatotox_risk, "hepatotox_score": prof.hepatotox_score,
        "ames_risk": prof.ames_risk, "ames_score": prof.ames_score,
        "skin_sens_risk": prof.skin_sens_risk,
        "notes": notes,
    }


async def _build_panel(smiles: str) -> dict[str, Any]:
    """Stitch all five axes into one envelope with a composite + worst-axis."""
    pc = _physchem(smiles)
    if pc is None:
        raise HTTPException(422, f"could not compute descriptors for {smiles}")
    # REAL MODEL FIRST — ADMET-AI service. Heuristics only if it's down.
    source = "heuristic"
    raw = await _real_admet(smiles)
    if raw:
        axes = _axes_from_admet_ai(raw, pc)
        source = "admet-ai"
    else:
        A = _predict_absorption(pc)
        D = _predict_distribution(pc)
        M = _predict_metabolism(pc)
        E = _predict_excretion(pc, M)
        T = await _predict_toxicity(smiles)
        axes = {"A": A, "D": D, "M": M, "E": E, "T": T}
    composite = round(sum(a["score"] for a in axes.values()) / 5.0, 3)
    worst_key = min(axes, key=lambda k: axes[k]["score"])
    worst = {"axis": worst_key, "score": axes[worst_key]["score"],
             "band": axes[worst_key]["band"]}
    tier = ("advance" if composite >= 0.7
            else "promising" if composite >= 0.55
            else "early" if composite >= 0.40
            else "weak")
    return {
        "smiles": smiles, "physchem": pc, "axes": axes, "source": source,
        "composite": composite, "tier": tier, "worst": worst,
        "computed_at": time.time(),
    }


# ─────────────────────────────────────────────────────────────────────
# Agentic action — design an analog that fixes the worst axis
# ─────────────────────────────────────────────────────────────────────

_AXIS_LABEL = {
    "A": "absorption (oral bioavailability)",
    "D": "distribution (PPB / BBB / Vd)",
    "M": "metabolism (CYP inhibition / HLM stability)",
    "E": "excretion (clearance / dose interval)",
    "T": "toxicity (hERG / hepatotox / AMES)",
}

_AXIS_GUIDANCE = {
    "A": "Reduce TPSA (replace polar groups with bioisosteres) or RotBonds (cyclize, rigidify), or trim MW.",
    "D": "Reduce LogP to drop PPB; if BBB needed, lower TPSA below 90 and keep LogP 1-4.",
    "M": "Increase sp3 fraction (add saturated rings, replace aromatic with aliphatic), reduce LogP.",
    "E": "Slow clearance — block known metabolic soft spots (block CH adjacent to aromatic with F, or add bulky group).",
    "T": "If hERG-high: reduce LogP and basic N count; if hepatotox: remove flagged toxicophore.",
}


async def _gemini_admet_fix(panel: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Ask Gemini for ONE structural edit that fixes the worst axis
    while preserving the antibacterial pharmacophore. Re-panel the
    result to PROVE the axis improved; only return when it did."""
    if not os.getenv("GEMINI_API_KEY"):
        return None
    worst = panel["worst"]
    axis_key = worst["axis"]
    axis_label = _AXIS_LABEL[axis_key]
    axis_guidance = _AXIS_GUIDANCE[axis_key]
    axis_detail = panel["axes"][axis_key]
    pc = panel["physchem"]
    prompt = (
        "You are a medicinal chemist optimizing an antibiotic candidate's "
        f"PHARMACOKINETIC profile. Its worst axis is {axis_label} "
        f"(score {worst['score']}, band {worst['band']}). "
        f"Detail: {json.dumps({k: v for k, v in axis_detail.items() if k != 'notes'})}.\n\n"
        f"Physchem: MW {pc['mw']:.0f}, LogP {pc['logp']:.2f}, "
        f"TPSA {pc['tpsa']:.0f}, HBD {pc['hbd']}, HBA {pc['hba']}, "
        f"RotB {pc['rotb']}, aromatic rings {pc['aromatic_rings']}.\n"
        f"Guidance: {axis_guidance}\n\n"
        f"Candidate SMILES: {panel['smiles']}\n\n"
        "Propose ONE concrete structural modification that improves the "
        "WORST axis without crashing the others. PRESERVE the "
        "antibacterial pharmacophore (keep β-lactam, ring system, key "
        "H-bond donors/acceptors). Return STRICT JSON:\n"
        '{"variant_smiles": "<valid SMILES>", '
        '"modification": "<=60 chars edit description>", '
        '"rationale": "<=180 chars why it improves the axis without hurting others>"}\n'
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 700, "temperature": 0.35,
            "thinkingConfig": {"thinkingBudget": 0, "includeThoughts": False},
        },
    }
    primary = os.getenv("LYSOS_ADMET_MODEL", "gemini-2.5-flash")
    fallback = os.getenv("LYSOS_ADMET_FALLBACK", "gemini-2.5-pro")
    key = os.getenv("GEMINI_API_KEY")
    obj: Optional[dict[str, Any]] = None
    for model in (primary, fallback):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=30.0) as cx:
                r = await cx.post(url, headers={"x-goog-api-key": key,
                                                "Content-Type": "application/json"},
                                  json=payload)
            if r.status_code in (429, 503):
                log.warning("admet fix %s %d — falling back", model, r.status_code)
                continue
            if r.status_code != 200:
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
            obj["_model"] = model
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("admet fix gemini failed (%s): %s", model, exc)
    if not obj:
        return None
    variant = _canonical(obj.get("variant_smiles", ""))
    if variant is None or variant == panel["smiles"]:
        return None
    # Re-panel to PROVE the worst axis improved.
    try:
        variant_panel = await _build_panel(variant)
    except HTTPException:
        return None
    before_axis = panel["axes"][axis_key]["score"]
    after_axis = variant_panel["axes"][axis_key]["score"]
    composite_before = panel["composite"]
    composite_after = variant_panel["composite"]
    improved = (after_axis > before_axis + 0.05
                and composite_after >= composite_before - 0.05)
    return {
        "variant_smiles": variant,
        "modification": str(obj.get("modification") or "structural edit")[:80],
        "rationale": str(obj.get("rationale") or "")[:200],
        "axis": axis_key,
        "axis_label": axis_label,
        "score_before": before_axis,
        "score_after": after_axis,
        "composite_before": composite_before,
        "composite_after": composite_after,
        "improved": bool(improved),
        "axes_after": {k: variant_panel["axes"][k]["score"] for k in variant_panel["axes"]},
    }


# ─────────────────────────────────────────────────────────────────────
# API — compute
# ─────────────────────────────────────────────────────────────────────

class ADMETRequest(BaseModel):
    smiles: str
    session_id: Optional[str] = None
    save: bool = True
    title: Optional[str] = None
    design_fix: bool = True


@router.post("/admet/panel")
async def admet_panel(req: ADMETRequest) -> dict[str, Any]:
    """SMILES → full 5-axis ADMET panel + optional agentic fix-design.
    Saved as an artifact unless save=false."""
    smi = (req.smiles or "").strip()
    if not smi:
        raise HTTPException(400, "smiles required")
    canon = _canonical(smi)
    if canon is None:
        raise HTTPException(422, f"unparseable SMILES: {smi}")

    nd = _non_drug_like_reason(canon)
    if nd:
        empty = {
            "smiles": canon, "physchem": None, "axes": {},
            "composite": 0.0, "tier": "n/a",
            "worst": {"axis": None, "score": 0.0, "band": "n/a"},
            "fix": None, "non_drug_reason": nd,
            "computed_at": time.time(),
        }
        artifact_id = None
        if req.save:
            rec = service_store.save_artifact(_ARTIFACT_KIND, empty,
                session_id=req.session_id, smiles=canon,
                title=f"Not applicable · {nd[:40]}")
            artifact_id = rec["id"]
        empty["artifact_id"] = artifact_id
        return empty

    panel = await _build_panel(canon)
    if req.design_fix:
        panel["fix"] = await _gemini_admet_fix(panel)
        if panel["fix"] and panel["fix"].get("improved") and req.session_id:
            try:
                session_memory.record_proposal(
                    req.session_id,
                    kind="admet_fix",
                    smiles=panel["fix"]["variant_smiles"],
                    rationale=panel["fix"]["modification"],
                )
            except Exception:  # noqa: BLE001
                pass
    else:
        panel["fix"] = None

    artifact_id = None
    if req.save:
        title = req.title or (
            f"ADMET · {panel['tier']} · composite {panel['composite']} · "
            f"weakest {panel['worst']['axis']}")
        rec = service_store.save_artifact(_ARTIFACT_KIND, panel,
            session_id=req.session_id, smiles=canon, title=title)
        artifact_id = rec["id"]
    panel["artifact_id"] = artifact_id

    # Direct dossier feed so an ADMET panel run straight from the card
    # (not via a workflow) lands in the candidate's developability picture.
    if req.session_id and not panel.get("non_drug_reason"):
        try:
            from . import candidate_dossier as _dossier
            worst = panel.get("worst") or {}
            _dossier.upsert_facet(req.session_id, canon, "admet", {
                "composite": panel.get("composite"),
                "tier": panel.get("tier"),
                "weakest_axis": worst.get("axis"),
                "source": panel.get("source", "heuristic"),
            })
        except Exception:  # noqa: BLE001
            pass
    return panel


@router.get("/admet/panels")
async def list_panels(session_id: Optional[str] = None) -> dict[str, Any]:
    items = service_store.list_artifacts(_ARTIFACT_KIND, session_id=session_id)
    return {"items": items}


@router.delete("/admet/panels/{rid}")
async def delete_panel(rid: str) -> dict[str, Any]:
    n = service_store.delete_artifact(_ARTIFACT_KIND, rid)
    return {"deleted": n}


# ─────────────────────────────────────────────────────────────────────
# Antibacterial-activity prior — calls the trained classifier on the
# model service (/predict_activity). A structural-similarity prior to
# known antibacterials, NOT a guaranteed MIC.
# ─────────────────────────────────────────────────────────────────────

@router.get("/activity")
async def predict_activity(smiles: str) -> dict[str, Any]:
    canon = _canonical(smiles)
    if canon is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")
    try:
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.post(f"{_ADMET_SERVICE_URL}/predict_activity",
                              json={"smiles": [canon]})
        if r.status_code == 200:
            body = r.json()
            if body.get("ok"):
                preds = (body.get("predictions") or {}).get(canon) or {}
                prob = preds.get("activity_probability")
                if prob is not None:
                    band = ("likely active" if prob >= 0.7
                            else "borderline" if prob >= 0.4 else "unlikely")
                    return {
                        "smiles": canon,
                        "activity_probability": prob,
                        "band": band,
                        "model": body.get("model"),
                        "model_auc": body.get("model_auc"),
                        "source": "trained-classifier",
                        "note": ("structural-similarity prior to known "
                                 "antibacterials — not a guaranteed MIC"),
                    }
    except Exception:  # noqa: BLE001
        pass
    return {"smiles": canon, "activity_probability": None,
            "band": "unavailable", "source": "offline",
            "note": "activity model service is offline"}
