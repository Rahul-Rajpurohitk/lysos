"""PK/PD Target-Attainment Simulator — does the dose actually cure it?

Binding affinity and MIC tell you the drug *can* kill the bug in a dish.
They do NOT tell you whether a real dosing regimen keeps enough free drug
at the site of infection, for long enough, to clear it in a patient. That
gap is what kills antibiotic programs late — and it is exactly the layer a
generic chem platform never has. This service closes it.

The science (all real, all NumPy, nothing faked):
  1. One-compartment population PK. The concentration-time curve is built
     by SUPERPOSITION of single-dose responses (IV bolus, IV infusion, or
     oral first-order absorption) out to steady state — numerically exact,
     no fragile closed forms.
  2. The governing PK/PD index is chosen by ANTIBIOTIC CLASS, the way the
     pharmacometrics literature does it (Craig 1998, Drusano 2004):
       · beta-lactams        → %fT>MIC      (time-dependent)
       · fluoroquinolones    → fAUC/MIC     (conc-dependent w/ time)
       · aminoglycosides     → Cmax/MIC     (concentration-dependent)
       · glycopeptides       → AUC/MIC      (vancomycin AUC:MIC ≥ 400)
       · oxazolidinones      → AUC/MIC
       · lipopeptides        → AUC/MIC
       · polymyxins          → fAUC/MIC
  3. Monte-Carlo Probability of Target Attainment (PTA). We draw a virtual
     population (lognormal CL and V with literature CV%), simulate the SAME
     regimen for each, and compute the fraction hitting the PK/PD target at
     every MIC across the doubling-dilution range. The PK/PD breakpoint is
     the highest MIC at which PTA ≥ 90% — the number a clinical micro lab
     would actually report.

Honesty: class-typical popPK is the input, NOT structure-predicted PK
(structure→CL prediction is unreliable; we will not fake it). The molecule
*does* move the answer through a cLogP-based fraction-unbound estimate and
through the MIC you bring (measured) or the in-silico activity prior (rough,
labelled). Everything is overridable.

Six-layer contract: service_store · this module · agent tool · workflow ·
orchestrator · frontend PKPDSimulatorCard + dossier (regimen facet).
"""
from __future__ import annotations

import logging
import math
import os
import time
from functools import lru_cache
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.pkpd")
router = APIRouter(prefix="/chem", tags=["pkpd"])

_ARTIFACT_KIND = "pkpd_sim"
_SELF = os.getenv("LYSOS_SELF_URL", "http://127.0.0.1:7860")

# NumPy 2.0 renamed trapz → trapezoid; stay version-safe either way.
_trapz = getattr(np, "trapezoid", None) or np.trapz

# ─────────────────────────────────────────────────────────────────────
# Class-typical population PK + the governing PK/PD index.
# Values are adult, ~70 kg, IV-equivalent, from the antimicrobial
# pharmacometrics literature (Craig, Drusano, Mouton, Rybak et al.).
# CL in L/h, V in L, ka in 1/h (oral), CV as fraction. Targets are the
# free-drug PK/PD index thresholds for net stasis vs 1-log cidal effect.
# ─────────────────────────────────────────────────────────────────────

_CLASSES: dict[str, dict[str, Any]] = {
    "beta_lactam": {
        "label": "β-lactam (penicillin / cephalosporin / carbapenem)",
        "index": "fT>MIC", "index_label": "%fT>MIC", "index_unit": "%",
        "target_stasis": 40.0, "target_cidal": 60.0,
        "cl": 12.0, "v": 18.0, "ka": 1.0, "fu": 0.75,
        "cv_cl": 0.35, "cv_v": 0.25, "default_route": "infusion",
        "note": "Time-dependent killing; extended/continuous infusion lifts "
                "%fT>MIC. Carbapenems ~40%, cephalosporins ~50–60% for cidal.",
        "examples": ["meropenem", "ceftazidime", "piperacillin"],
    },
    "fluoroquinolone": {
        "label": "fluoroquinolone",
        "index": "fAUC/MIC", "index_label": "fAUC₂₄/MIC", "index_unit": "",
        "target_stasis": 30.0, "target_cidal": 125.0,
        "cl": 25.0, "v": 130.0, "ka": 1.2, "fu": 0.70,
        "cv_cl": 0.30, "cv_v": 0.30, "default_route": "oral",
        "note": "fAUC/MIC ≥ 125 for Gram-negatives; ~30–40 suffices for "
                "Gram-positives. Large V (tissue penetration).",
        "examples": ["ciprofloxacin", "levofloxacin", "moxifloxacin"],
    },
    "aminoglycoside": {
        "label": "aminoglycoside",
        "index": "Cmax/MIC", "index_label": "Cmax/MIC", "index_unit": "",
        "target_stasis": 6.0, "target_cidal": 10.0,
        "cl": 5.5, "v": 18.0, "ka": 0.0, "fu": 0.95,
        "cv_cl": 0.30, "cv_v": 0.20, "default_route": "infusion",
        "note": "Concentration-dependent + post-antibiotic effect → "
                "once-daily extended-interval dosing maximises Cmax/MIC.",
        "examples": ["gentamicin", "amikacin", "tobramycin"],
    },
    "glycopeptide": {
        "label": "glycopeptide (vancomycin)",
        "index": "AUC/MIC", "index_label": "AUC₂₄/MIC", "index_unit": "",
        "target_stasis": 200.0, "target_cidal": 400.0,
        "cl": 4.5, "v": 55.0, "ka": 0.0, "fu": 0.50,
        "cv_cl": 0.30, "cv_v": 0.25, "default_route": "infusion",
        "note": "Vancomycin AUC₂₄/MIC ≥ 400 (MRSA) is the modern target; "
                "AUC-guided dosing has replaced troughs.",
        "examples": ["vancomycin", "teicoplanin"],
    },
    "oxazolidinone": {
        "label": "oxazolidinone (linezolid)",
        "index": "AUC/MIC", "index_label": "AUC₂₄/MIC", "index_unit": "",
        "target_stasis": 50.0, "target_cidal": 100.0,
        "cl": 8.0, "v": 45.0, "ka": 1.5, "fu": 0.69,
        "cv_cl": 0.35, "cv_v": 0.25, "default_route": "oral",
        "note": "AUC/MIC ~80–120 and %T>MIC ~85% both track efficacy; "
                "near-complete oral bioavailability.",
        "examples": ["linezolid", "tedizolid"],
    },
    "lipopeptide": {
        "label": "lipopeptide (daptomycin)",
        "index": "AUC/MIC", "index_label": "AUC₂₄/MIC", "index_unit": "",
        "target_stasis": 200.0, "target_cidal": 400.0,
        "cl": 0.6, "v": 7.0, "ka": 0.0, "fu": 0.08,
        "cv_cl": 0.30, "cv_v": 0.20, "default_route": "infusion",
        "note": "Highly protein-bound; once-daily. Inactivated by pulmonary "
                "surfactant (not for pneumonia).",
        "examples": ["daptomycin"],
    },
    "polymyxin": {
        "label": "polymyxin (colistin)",
        "index": "fAUC/MIC", "index_label": "fAUC₂₄/MIC", "index_unit": "",
        "target_stasis": 12.0, "target_cidal": 25.0,
        "cl": 3.0, "v": 12.0, "ka": 0.0, "fu": 0.45,
        "cv_cl": 0.40, "cv_v": 0.30, "default_route": "infusion",
        "note": "Last-line for carbapenem-resistant Gram-negatives; narrow "
                "therapeutic window, nephrotoxic. fAUC/MIC drives effect.",
        "examples": ["colistin", "polymyxin B"],
    },
    "tetracycline": {
        "label": "tetracycline / glycylcycline",
        "index": "fAUC/MIC", "index_label": "fAUC₂₄/MIC", "index_unit": "",
        "target_stasis": 12.0, "target_cidal": 25.0,
        "cl": 12.0, "v": 130.0, "ka": 1.0, "fu": 0.30,
        "cv_cl": 0.35, "cv_v": 0.30, "default_route": "oral",
        "note": "Bacteriostatic; very large V (extensive tissue distribution). "
                "Tigecycline fAUC/MIC ~ 0.9 (low plasma exposure).",
        "examples": ["doxycycline", "tigecycline", "minocycline"],
    },
}

# Map our 8 priority pathogens to the class most commonly modelled against
# them — used only to seed the UI default, never to constrain the chemist.
_PATHOGEN_DEFAULT_CLASS = {
    "MRSA": "glycopeptide", "Mtb": "fluoroquinolone",
    "EColi-CRE": "beta_lactam", "KpneuCRE": "polymyxin",
    "Abaum": "polymyxin", "Paer": "beta_lactam",
    "Efaecium": "lipopeptide", "Ngono": "beta_lactam",
}

_MIC_GRID = [0.03, 0.06, 0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0]


# ─────────────────────────────────────────────────────────────────────
# Molecule → fraction unbound (rough, cLogP-based). Honest: this is the
# ONE structure-derived PK input. CL/V stay class-typical (overridable).
# ─────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=512)
def _mol_descriptors(smiles: str) -> dict[str, Any]:
    try:
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors
        m = Chem.MolFromSmiles((smiles or "").strip())
        if m is None:
            return {}
        return {
            "mw": round(Descriptors.MolWt(m), 1),
            "clogp": round(Crippen.MolLogP(m), 2),
            "tpsa": round(Descriptors.TPSA(m), 1),
            "hbd": Descriptors.NumHDonors(m),
            "hba": Descriptors.NumHAcceptors(m),
        }
    except Exception:  # noqa: BLE001
        return {}


def _fu_from_logp(clogp: Optional[float], class_fu: float) -> tuple[float, str]:
    """Estimate fraction unbound from lipophilicity. Higher cLogP → more
    plasma-protein binding → lower fu. Sigmoid centred so cLogP≈2 gives
    fu≈class default; clamped to a physiological floor. Rough — labelled."""
    if clogp is None:
        return class_fu, "class-typical (no structure)"
    # monotone decreasing in clogp; anchored to the class default at clogp=2
    raw = 1.0 / (1.0 + 10 ** (0.45 * (clogp - 2.0)))
    # blend toward the class default so we never stray wildly
    fu = max(0.02, min(0.99, 0.5 * raw + 0.5 * class_fu))
    return round(fu, 3), "estimated from cLogP (rough)"


# ─────────────────────────────────────────────────────────────────────
# One-compartment PK by superposition → steady-state interval curve
# ─────────────────────────────────────────────────────────────────────

def _single_dose_curve(t: np.ndarray, dose: float, v: float, ke: float,
                       ka: float, route: str, t_inf: float, f_bio: float
                       ) -> np.ndarray:
    """Total plasma concentration from ONE dose at time 0, on grid t≥0."""
    t = np.maximum(t, 0.0)
    if route == "oral":
        if ka <= 0:                       # no absorption rate → treat as IV
            return (dose / v) * np.exp(-ke * t)
        if abs(ka - ke) < 1e-6:
            ka = ke + 1e-3
        coef = (f_bio * dose * ka) / (v * (ka - ke))
        return coef * (np.exp(-ke * t) - np.exp(-ka * t))
    if route == "infusion" and t_inf > 0:
        r0 = dose / t_inf                  # zero-order input rate
        c = np.empty_like(t)
        during = t <= t_inf
        c[during] = (r0 / (v * ke)) * (1.0 - np.exp(-ke * t[during]))
        c_end = (r0 / (v * ke)) * (1.0 - np.exp(-ke * t_inf))
        c[~during] = c_end * np.exp(-ke * (t[~during] - t_inf))
        return c
    # IV bolus
    return (dose / v) * np.exp(-ke * t)


def _steady_state_curve(dose: float, tau: float, v: float, ke: float,
                        ka: float, route: str, t_inf: float, f_bio: float,
                        n_pts: int = 160) -> tuple[np.ndarray, np.ndarray]:
    """Steady-state concentration over one dosing interval [0, tau] via
    superposition of enough prior doses to converge (≥7 half-lives)."""
    thalf = math.log(2) / ke
    n_doses = int(max(8, math.ceil(7 * thalf / tau) + 2))
    n_doses = min(n_doses, 400)
    t = np.linspace(0.0, tau, n_pts)
    total = np.zeros_like(t)
    # sum contributions of doses given at -k*tau (k=0..n_doses-1) → conc now
    for k in range(n_doses):
        total += _single_dose_curve(t + k * tau, dose, v, ke, ka,
                                    route, t_inf, f_bio)
    return t, total


def _index_uses_free(index: str) -> bool:
    """Free-drug indices carry an 'f' (fT>MIC, fAUC/MIC). Total-drug indices
    (AUC/MIC for vancomycin, Cmax/MIC for aminoglycosides) do not — and the
    literature targets are calibrated to that convention, so we must match it."""
    return index in ("fT>MIC", "fAUC/MIC")


def _index_value(t: np.ndarray, c_total: np.ndarray, fu: float, tau: float,
                 index: str, mic: float) -> float:
    """Compute the governing PK/PD index from the steady-state curve, using
    FREE or TOTAL concentration as the index convention requires."""
    if mic <= 0:
        return float("inf")
    c_eff = (fu * c_total) if _index_uses_free(index) else c_total
    if index == "fT>MIC":
        frac = float(_trapz((c_eff > mic).astype(float), t)) / tau
        return round(100.0 * frac, 1)
    if index == "Cmax/MIC":
        return round(float(np.max(c_eff)) / mic, 2)
    # AUC/MIC (total) or fAUC/MIC (free)
    auc24 = float(_trapz(c_eff, t)) * (24.0 / tau)
    return round(auc24 / mic, 1)


# ─────────────────────────────────────────────────────────────────────
# Monte-Carlo PTA across the MIC grid
# ─────────────────────────────────────────────────────────────────────

def _monte_carlo_pta(dose: float, tau: float, cl: float, v: float, ka: float,
                     route: str, t_inf: float, f_bio: float, fu: float,
                     index: str, target: float, n_patients: int,
                     cv_cl: float, cv_v: float) -> dict[str, Any]:
    """Draw a virtual population, simulate each, return PTA vs MIC."""
    rng = np.random.default_rng(12345)   # fixed seed → reproducible PTA
    n = int(max(200, min(n_patients, 5000)))

    def _lognorm(mean: float, cv: float) -> np.ndarray:
        sigma = math.sqrt(math.log(1 + cv * cv))
        mu = math.log(mean) - 0.5 * sigma * sigma
        return rng.lognormal(mu, sigma, n)

    cls = _lognorm(cl, cv_cl)
    vs = _lognorm(v, cv_v)
    kes = cls / vs

    mic_grid = np.array(_MIC_GRID)
    use_free = _index_uses_free(index)
    # For AUC- and Cmax-based indices the per-patient metric is MIC-free.
    if index in ("AUC/MIC", "fAUC/MIC", "Cmax/MIC"):
        metric = np.empty(n)
        for i in range(n):
            t, c = _steady_state_curve(dose, tau, vs[i], kes[i], ka,
                                       route, t_inf, f_bio, n_pts=120)
            ce = (fu * c) if use_free else c       # free vs total per convention
            if index == "Cmax/MIC":
                metric[i] = float(np.max(ce))
            else:
                metric[i] = float(_trapz(ce, t)) * (24.0 / tau)  # AUC24
        # PTA(MIC) = P(metric/MIC ≥ target)
        pta = [(float(mic), round(float(np.mean((metric / mic) >= target)), 3))
               for mic in mic_grid]
    else:  # fT>MIC — time above threshold depends on MIC, compute per patient
        pta_counts = np.zeros(len(mic_grid))
        for i in range(n):
            t, c = _steady_state_curve(dose, tau, vs[i], kes[i], ka,
                                       route, t_inf, f_bio, n_pts=120)
            ce = fu * c                            # %fT>MIC is a free-drug index
            for j, mic in enumerate(mic_grid):
                frac = float(_trapz((ce > mic).astype(float), t)) / tau * 100.0
                if frac >= target:
                    pta_counts[j] += 1
        pta = [(float(mic), round(float(pta_counts[j] / n), 3))
               for j, mic in enumerate(mic_grid)]

    # PK/PD breakpoint = highest MIC with PTA ≥ 0.90
    breakpoint = None
    for mic, p in pta:
        if p >= 0.90:
            breakpoint = mic
    return {"pta_curve": [{"mic": m, "pta": p} for m, p in pta],
            "pkpd_breakpoint_mg_l": breakpoint, "n_patients": n}


# ─────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────

async def _estimate_mic(smiles: str, pathogen: str) -> tuple[Optional[float], str]:
    """No measured MIC → derive a rough one from the in-silico activity
    prior. Clearly labelled; the PTA-vs-MIC curve is the real deliverable."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.get(f"{_SELF}/workbench/chem/activity",
                             params={"smiles": smiles})
            if r.status_code == 200:
                p = r.json().get("activity_probability")
                if p is not None:
                    # map prob∈[0,1] → MIC∈[0.25 .. 16] mg/L (log-linear, rough)
                    p = max(0.02, min(0.98, float(p)))
                    log_mic = math.log2(16.0) - p * (math.log2(16.0) - math.log2(0.25))
                    return round(2 ** log_mic, 3), "from in-silico activity prior (rough)"
    except Exception:  # noqa: BLE001
        pass
    return None, "unavailable"


def _resolve_class(drug_class: Optional[str], pathogen: str) -> tuple[str, dict]:
    key = (drug_class or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in _CLASSES:
        return key, _CLASSES[key]
    # fuzzy: substring against keys + labels
    for k, c in _CLASSES.items():
        if key and (key in k or key in c["label"].lower()):
            return k, c
    default = _PATHOGEN_DEFAULT_CLASS.get(pathogen, "beta_lactam")
    return default, _CLASSES[default]


def _simulate(smiles: str, pathogen: str, drug_class: Optional[str],
              dose_mg: float, interval_h: float, route: str,
              infusion_h: float, weight_kg: float, mic_mg_l: Optional[float],
              fu_override: Optional[float], cl_override: Optional[float],
              v_override: Optional[float], n_patients: int,
              mic_source: str) -> dict[str, Any]:
    t0 = time.time()
    cls_key, cls = _resolve_class(drug_class, pathogen)
    desc = _mol_descriptors(smiles)

    # PK params: class-typical, weight-scaled, with optional overrides.
    wt_scale = max(0.3, min(3.0, weight_kg / 70.0))
    cl = float(cl_override) if cl_override else cls["cl"] * wt_scale
    v = float(v_override) if v_override else cls["v"] * wt_scale
    ka = cls["ka"]
    if fu_override is not None:
        fu, fu_src = float(fu_override), "user override"
    else:
        fu, fu_src = _fu_from_logp(desc.get("clogp"), cls["fu"])
    ke = cl / v
    thalf = math.log(2) / ke

    route = route if route in ("bolus", "infusion", "oral") else cls["default_route"]
    t_inf = max(0.0, infusion_h) if route == "infusion" else 0.0
    f_bio = 1.0  # oral bioavailability folded into class V; honest default

    # Nominal steady-state curve (typical patient) for display.
    t, c_total = _steady_state_curve(dose_mg, interval_h, v, ke, ka,
                                     route, t_inf, f_bio, n_pts=160)
    c_free = fu * c_total
    cmax = float(np.max(c_total)); cmin = float(np.min(c_total))
    auc_tau = float(_trapz(c_total, t)); auc24 = auc_tau * (24.0 / interval_h)

    index = cls["index"]
    target_cidal = cls["target_cidal"]; target_stasis = cls["target_stasis"]

    # MIC: measured if given, else estimated from activity prior.
    mic = mic_mg_l
    if mic is None:
        # _estimate_mic is async; caller passes resolved value via mic_mg_l.
        mic = None
    idx_at_mic = _index_value(t, c_total, fu, interval_h, index, mic) if mic else None
    if idx_at_mic is not None:
        idx_at_mic = float(idx_at_mic)
    attained = bool(idx_at_mic is not None and idx_at_mic >= target_cidal)
    attained_stasis = bool(idx_at_mic is not None and idx_at_mic >= target_stasis)

    pta = _monte_carlo_pta(dose_mg, interval_h, cl, v, ka, route, t_inf,
                           f_bio, fu, index, target_cidal, n_patients,
                           cls["cv_cl"], cls["cv_v"])

    # Concentration-time series (downsample for transport).
    step = max(1, len(t) // 80)
    curve = [{"t": round(float(tt), 2),
              "total": round(float(ct), 3),
              "free": round(float(cf), 3)}
             for tt, ct, cf in zip(t[::step], c_total[::step], c_free[::step])]

    band = ("attained-cidal" if attained else
            "attained-stasis" if attained_stasis else
            "not-attained" if idx_at_mic is not None else "no-mic")

    return {
        "smiles": smiles, "pathogen": pathogen,
        "drug_class": cls_key, "class_label": cls["label"],
        "descriptors": desc,
        "regimen": {"dose_mg": dose_mg, "interval_h": interval_h,
                    "route": route, "infusion_h": t_inf,
                    "weight_kg": weight_kg, "doses_per_day": round(24.0 / interval_h, 2)},
        "pk": {"cl_l_h": round(cl, 2), "v_l": round(v, 2),
               "ke_h": round(ke, 4), "thalf_h": round(thalf, 2),
               "fu": fu, "fu_source": fu_src, "ka_h": ka},
        "exposure": {"cmax_mg_l": round(cmax, 2), "cmin_mg_l": round(cmin, 3),
                     "auc24_mg_h_l": round(auc24, 1),
                     "fauc24_mg_h_l": round(auc24 * fu, 1)},
        "index": index, "index_label": cls["index_label"],
        "index_unit": cls["index_unit"],
        "target_stasis": target_stasis, "target_cidal": target_cidal,
        "mic_mg_l": mic, "mic_source": mic_source,
        "index_at_mic": idx_at_mic,
        "attained_cidal": attained, "attained_stasis": attained_stasis,
        "band": band,
        "curve": curve,
        "pta_curve": pta["pta_curve"],
        "pkpd_breakpoint_mg_l": pta["pkpd_breakpoint_mg_l"],
        "n_patients": pta["n_patients"],
        "class_note": cls["note"], "class_examples": cls["examples"],
        "elapsed_s": round(time.time() - t0, 2),
        "computed_at": time.time(),
        "engine": "1-compartment popPK + Monte-Carlo PTA (NumPy)",
        "provenance": (
            "Class-typical population PK (literature), weight-scaled, "
            "simulated by superposition to steady state. PK/PD index chosen "
            "by antibiotic class. PTA = Monte-Carlo over a virtual population "
            "(lognormal CL/V). PK params are class-typical, not structure-"
            "predicted; fu is cLogP-estimated; MIC is measured or in-silico."),
    }


# ─────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────

class Regimen(BaseModel):
    dose_mg: float = 1000.0
    interval_h: float = 8.0
    route: str = "infusion"        # bolus | infusion | oral
    infusion_h: float = 0.5
    weight_kg: float = 70.0


class SimRequest(BaseModel):
    smiles: str
    pathogen: str = "MRSA"
    drug_class: Optional[str] = None
    regimen: Regimen = Regimen()
    mic_mg_l: Optional[float] = None
    fu: Optional[float] = None
    cl_l_h: Optional[float] = None
    v_l: Optional[float] = None
    n_patients: int = 1500
    session_id: Optional[str] = None
    save: bool = True


@router.post("/pkpd/simulate")
async def pkpd_simulate(req: SimRequest) -> dict[str, Any]:
    """Simulate a dosing regimen → concentration-time curve, PK/PD index
    attainment, and Monte-Carlo PTA across the MIC range."""
    from rdkit import Chem
    if Chem.MolFromSmiles((req.smiles or "").strip()) is None:
        raise HTTPException(422, f"unparseable SMILES: {req.smiles}")

    mic = req.mic_mg_l
    mic_source = "measured (user)" if mic is not None else ""
    if mic is None:
        mic, mic_source = await _estimate_mic(req.smiles, req.pathogen)

    rg = req.regimen
    result = _simulate(
        req.smiles, req.pathogen, req.drug_class,
        rg.dose_mg, rg.interval_h, rg.route, rg.infusion_h, rg.weight_kg,
        mic, req.fu, req.cl_l_h, req.v_l, req.n_patients, mic_source)

    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, result, session_id=req.session_id,
            smiles=req.smiles,
            title=(f"PK/PD · {result['class_label'].split(' ')[0]} · "
                   f"{result['band']}"))
        artifact_id = rec["id"]
    result["artifact_id"] = artifact_id

    # Dossier feed — regimen facet (already a first-class developability axis).
    if req.session_id:
        try:
            from . import candidate_dossier as _dossier
            _dossier.upsert_facet(req.session_id, req.smiles, "regimen", {
                "drug_class": result["drug_class"],
                "index": result["index_label"],
                "index_at_mic": result["index_at_mic"],
                "attained_cidal": result["attained_cidal"],
                "pkpd_breakpoint_mg_l": result["pkpd_breakpoint_mg_l"],
                "regimen": (f"{int(rg.dose_mg)} mg "
                            f"q{int(rg.interval_h)}h {rg.route}"),
            })
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/pkpd/classes")
async def pkpd_classes(pathogen: Optional[str] = None) -> dict[str, Any]:
    """The PK/PD reference table — class → governing index, targets, typical
    PK. The studio's class browser + default selector read this."""
    default = _PATHOGEN_DEFAULT_CLASS.get(pathogen or "", None)
    return {
        "default_class": default,
        "mic_grid": _MIC_GRID,
        "classes": [{
            "key": k, "label": c["label"],
            "index": c["index_label"], "index_raw": c["index"],
            "target_stasis": c["target_stasis"],
            "target_cidal": c["target_cidal"],
            "cl_l_h": c["cl"], "v_l": c["v"], "fu": c["fu"],
            "default_route": c["default_route"],
            "note": c["note"], "examples": c["examples"],
        } for k, c in _CLASSES.items()],
    }


@router.get("/pkpd/runs")
async def list_runs(session_id: Optional[str] = None) -> dict[str, Any]:
    return {"items": service_store.list_artifacts(kind=_ARTIFACT_KIND,
                                                  session_id=session_id)}
