"""Retrospective validation — the trust centerpiece of Lysos.

A drug-discovery scorer is only credible if it ranks KNOWN ACTIVES above
KNOWN INACTIVES. This module runs that test: it scores ~30 marketed
antibiotics (actives) against a curated set of drug-like non-antibacterials
(decoys: statins, NSAIDs, antihistamines, CNS drugs, ...), then computes the
standard virtual-screening enrichment metrics:

  - ROC-AUC          : probability a random active outranks a random decoy.
                       0.5 = noise, 1.0 = perfect. >0.7 = the scorer works.
  - Enrichment Factor: how many more actives appear in the top X% than
                       random (EF@1%, @5%, @10%).
  - BEDROC (α=20)    : early-recognition-weighted AUC (rewards actives
                       ranked very high — what matters in screening).

This is the single most important honesty signal in the product. The result
is cached (scoring 60 molecules is expensive) and exposed both as an API and
a frontend dashboard with the enrichment curve.

NOT a claim of clinical accuracy — it validates the RANKING, which is exactly
what the platform uses the score for.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.validation")
router = APIRouter(prefix="/chem", tags=["validation"])

_SELF = os.getenv("LYSOS_SELF_URL", "http://127.0.0.1:7860")
_DATA = Path(__file__).resolve().parents[2] / "data"
_CACHE_KIND = "validation_run"

# ── Decoy set — drug-like molecules with NO antibacterial indication.
# Spanning therapeutic areas so the test is honest (not trivially separable
# by size/charge alone). All marketed drugs, canonical SMILES.
_DECOYS: list[dict[str, str]] = [
    {"name": "atorvastatin", "class": "statin",
     "smiles": "CC(C)c1c(C(=O)Nc2ccccc2)c(-c2ccccc2)c(-c2ccc(F)cc2)n1CC[C@@H](O)C[C@@H](O)CC(=O)O"},
    {"name": "ibuprofen", "class": "NSAID",
     "smiles": "CC(C)Cc1ccc(C(C)C(=O)O)cc1"},
    {"name": "naproxen", "class": "NSAID",
     "smiles": "COc1ccc2cc([C@@H](C)C(=O)O)ccc2c1"},
    {"name": "loratadine", "class": "antihistamine",
     "smiles": "CCOC(=O)N1CCC(=C2c3ccc(Cl)cc3CCc3cccnc32)CC1"},
    {"name": "cetirizine", "class": "antihistamine",
     "smiles": "OC(=O)COCCN1CCN(C(c2ccccc2)c2ccc(Cl)cc2)CC1"},
    {"name": "diazepam", "class": "benzodiazepine",
     "smiles": "CN1c2ccc(Cl)cc2C(c2ccccc2)=NCC1=O"},
    {"name": "fluoxetine", "class": "SSRI",
     "smiles": "CNCCC(Oc1ccc(C(F)(F)F)cc1)c1ccccc1"},
    {"name": "sertraline", "class": "SSRI",
     "smiles": "CN[C@H]1CC[C@@H](c2ccc(Cl)c(Cl)c2)c2ccccc21"},
    {"name": "omeprazole", "class": "PPI",
     "smiles": "COc1ccc2[nH]c(S(=O)Cc3ncc(C)c(OC)c3C)nc2c1"},
    {"name": "metformin", "class": "antidiabetic",
     "smiles": "CN(C)C(=N)N=C(N)N"},
    {"name": "amlodipine", "class": "CCB",
     "smiles": "CCOC(=O)C1=C(COCCN)NC(C)=C(C(=O)OC)C1c1ccccc1Cl"},
    {"name": "losartan", "class": "ARB",
     "smiles": "CCCCc1nc(Cl)c(CO)n1Cc1ccc(-c2ccccc2-c2nnn[nH]2)cc1"},
    {"name": "warfarin", "class": "anticoagulant",
     "smiles": "CC(=O)CC(c1ccccc1)c1c(O)c2ccccc2oc1=O"},
    {"name": "caffeine", "class": "stimulant",
     "smiles": "Cn1c(=O)c2c(ncn2C)n(C)c1=O"},
    {"name": "acetaminophen", "class": "analgesic",
     "smiles": "CC(=O)Nc1ccc(O)cc1"},
    {"name": "aspirin", "class": "NSAID",
     "smiles": "CC(=O)Oc1ccccc1C(=O)O"},
    {"name": "propranolol", "class": "beta-blocker",
     "smiles": "CC(C)NCC(O)COc1cccc2ccccc12"},
    {"name": "salbutamol", "class": "bronchodilator",
     "smiles": "CC(C)(C)NCC(O)c1ccc(O)c(CO)c1"},
    {"name": "diphenhydramine", "class": "antihistamine",
     "smiles": "CN(C)CCOC(c1ccccc1)c1ccccc1"},
    {"name": "lansoprazole", "class": "PPI",
     "smiles": "Cc1c(OCC(F)(F)F)ccnc1CS(=O)c1nc2ccccc2[nH]1"},
    {"name": "simvastatin", "class": "statin",
     "smiles": "CCC(C)(C)C(=O)O[C@H]1C[C@@H](C)C=C2C=C[C@H](C)[C@H](CC[C@@H]3C[C@@H](O)CC(=O)O3)[C@@H]21"},
    {"name": "gabapentin", "class": "anticonvulsant",
     "smiles": "NCC1(CC(=O)O)CCCCC1"},
    {"name": "tramadol", "class": "opioid",
     "smiles": "CN(C)C[C@H]1CCCC[C@@]1(O)c1cccc(OC)c1"},
    {"name": "ranitidine", "class": "H2-blocker",
     "smiles": "CNC(=C[N+](=O)[O-])NCCSCc1ccc(CN(C)C)o1"},
    {"name": "verapamil", "class": "CCB",
     "smiles": "COc1ccc(CCN(C)CCCC(C#N)(C(C)C)c2ccc(OC)c(OC)c2)cc1OC"},
    {"name": "clopidogrel", "class": "antiplatelet",
     "smiles": "COC(=O)[C@@H](c1ccccc1Cl)N1CCc2sccc2C1"},
    {"name": "montelukast", "class": "leukotriene-antag",
     "smiles": "CC(C)(O)c1ccccc1CCC(SCC1(CC(=O)O)CC1)c1cccc(/C=C/c2ccc3ccc(Cl)cc3n2)c1"},
    {"name": "sildenafil", "class": "PDE5-inhibitor",
     "smiles": "CCCc1nn(C)c2c1nc([nH]c2=O)-c1cc(S(=O)(=O)N2CCN(C)CC2)ccc1OCC"},
    {"name": "donepezil", "class": "AChE-inhibitor",
     "smiles": "COc1cc2c(cc1OC)C(=O)C(CC1CCN(Cc3ccccc3)CC1)C2"},
    {"name": "lorazepam", "class": "benzodiazepine",
     "smiles": "OC1N=C(c2ccccc2Cl)c2cc(Cl)ccc2NC1=O"},
]


# ─────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────

def _load_actives(limit: int = 40) -> list[dict[str, str]]:
    """Known actives = marketed antibiotics from the processed corpus
    parquet. Capped so the validation run stays fast (each molecule is a
    full /score call). Falls back to a small hardcoded panel if the
    parquet can't be read."""
    pq = _DATA / "processed" / "known-antibiotics-canonical.parquet"
    try:
        import pandas as pd
        df = pd.read_parquet(pq)
        # Find the SMILES + name columns robustly.
        cols = {c.lower(): c for c in df.columns}
        smi_col = next((cols[c] for c in
                        ("canonical_smiles", "smiles", "canonicalsmiles")
                        if c in cols), None)
        name_col = next((cols[c] for c in ("name", "drug_name", "pref_name",
                                           "compound", "title") if c in cols), None)
        if smi_col is None:
            raise ValueError("no smiles column")
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for _, row in df.iterrows():
            smi = str(row[smi_col]).strip()
            if not smi or smi in seen or smi.lower() == "nan":
                continue
            seen.add(smi)
            nm = str(row[name_col]).strip() if name_col else "antibiotic"
            out.append({"name": nm or "antibiotic", "smiles": smi})
            if len(out) >= limit:
                break
        if out:
            return out
    except Exception as exc:  # noqa: BLE001
        log.warning("actives parquet load failed (%s) — using fallback panel", exc)
    return _FALLBACK_ACTIVES


# Small marketed-antibiotic panel used if the corpus parquet is unreadable.
_FALLBACK_ACTIVES: list[dict[str, str]] = [
    {"name": "amoxicillin", "smiles": "CC1(C)S[C@@H]2[C@H](NC(=O)[C@H](N)c3ccc(O)cc3)C(=O)N2[C@H]1C(=O)O"},
    {"name": "ciprofloxacin", "smiles": "O=C(O)c1cn(C2CC2)c2cc(N3CCNCC3)c(F)cc2c1=O"},
    {"name": "linezolid", "smiles": "CC(=O)NC[C@H]1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1"},
    {"name": "trimethoprim", "smiles": "COc1cc(Cc2cnc(N)nc2N)cc(OC)c1OC"},
    {"name": "metronidazole", "smiles": "Cc1ncc([N+](=O)[O-])n1CCO"},
    {"name": "doxycycline", "smiles": "CC1c2cccc(O)c2C(=O)C2=C(O)C3(O)C(=O)C(C(N)=O)=C(O)C(N(C)C)C3C(O)C12O"},
    {"name": "vancomycin-frag", "smiles": "CC1C(C(CC(O1)OC2C(C(C(OC2OC3=C4C=C5C=C3OC6=C(C=C(C=C6)C(C(C(=O)NC(C(=O)NC5C(=O)NC7C8=CC(=C(C=C8)O)C9=C(C=C(C=C9C(NC(=O)C(C(C1=CC(=C(O4)C=C1)Cl)O)NC7=O)C(=O)O)O)O)O)NC)O)Cl)O)CO)O)O)(C)N"},
    {"name": "azithromycin-frag", "smiles": "CCC1OC(=O)C(C)C(OC2CC(C)(OC)C(O)C(C)O2)C(C)C(OC2OC(C)CC(N(C)C)C2O)C(C)(O)CC(C)CN(C)C(C)C(O)C1(C)O"},
    {"name": "sulfamethoxazole", "smiles": "Cc1cc(NS(=O)(=O)c2ccc(N)cc2)no1"},
    {"name": "rifampicin-frag", "smiles": "CC1C=CC=C(C)C(=O)NC2=C(O)C3=C(O)C(C)=C(OC4OC(C)C(O)C(OC)C4C)C(=O)C3=C(O)C2=O"},
]


# ─────────────────────────────────────────────────────────────────────
# Metrics — standard virtual-screening enrichment
# ─────────────────────────────────────────────────────────────────────

def _roc_auc(labels_by_rank: list[int]) -> float:
    """ROC-AUC via the Mann-Whitney U relationship. labels_by_rank is the
    label (1=active, 0=decoy) ordered best-score-first."""
    n_pos = sum(labels_by_rank)
    n_neg = len(labels_by_rank) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    # Sum of ranks of positives (rank 1 = best). Convert to ascending rank
    # for the U statistic: higher score should give higher rank-sum for AUC.
    # We iterate best-first; assign descending weight.
    # AUC = (sum over actives of #decoys ranked below it) / (n_pos*n_neg)
    decoys_below = 0
    concordant = 0
    # Walk from worst to best, counting decoys seen so far.
    for lab in reversed(labels_by_rank):
        if lab == 0:
            decoys_below += 1
        else:
            concordant += decoys_below
    return round(concordant / (n_pos * n_neg), 4)


def _enrichment_factor(labels_by_rank: list[int], frac: float) -> float:
    """EF@frac = (actives in top frac / molecules in top frac) /
    (total actives / total molecules)."""
    n = len(labels_by_rank)
    n_pos = sum(labels_by_rank)
    if n == 0 or n_pos == 0:
        return 0.0
    k = max(1, int(round(n * frac)))
    hits = sum(labels_by_rank[:k])
    return round((hits / k) / (n_pos / n), 2)


def _bedroc(labels_by_rank: list[int], alpha: float = 20.0) -> float:
    """BEDROC — early-recognition-weighted AUC (Truchon & Bayly 2007).
    NOTE: BEDROC is designed for low active-rate screening (~1%). On a
    balanced active:decoy set its dynamic range collapses, so we report
    it but lean on ROC-AUC as the headline. Canonical formula:

        Ra  = n_active / N
        RIE = (Σ_actives e^(-α·rank/N)) / (Ra · (1-e^-α)/(e^(α/N)-1))
        BEDROC = RIE · Ra·sinh(α/2)/(cosh(α/2)-cosh(α/2-α·Ra))
                 + 1/(1-e^(α(1-Ra)))
    """
    N = len(labels_by_rank)
    n_pos = sum(labels_by_rank)
    if n_pos == 0 or n_pos == N:
        return 0.0
    ra = n_pos / N
    try:
        s = sum(math.exp(-alpha * (i + 1) / N)
                for i, lab in enumerate(labels_by_rank) if lab == 1)
        denom_rand = ra * (1 - math.exp(-alpha)) / (math.exp(alpha / N) - 1)
        rie = s / denom_rand
        bedroc = (rie * ra * math.sinh(alpha / 2)
                  / (math.cosh(alpha / 2) - math.cosh(alpha / 2 - alpha * ra))
                  + 1.0 / (1 - math.exp(alpha * (1 - ra))))
        return round(max(0.0, min(1.0, bedroc)), 4)
    except (ZeroDivisionError, OverflowError, ValueError):
        top = max(1, int(N * 0.1))
        return round(sum(labels_by_rank[:top]) / n_pos, 4)


# ─────────────────────────────────────────────────────────────────────
# Scoring + run
# ─────────────────────────────────────────────────────────────────────

async def _score(cx: httpx.AsyncClient, smiles: str, pathogen: str) -> Optional[float]:
    try:
        r = await cx.post(f"{_SELF}/workbench/score",
                          json={"smiles": smiles, "target_pathogen": pathogen})
        if r.status_code != 200:
            return None
        return float(r.json().get("composite"))
    except Exception:  # noqa: BLE001
        return None


async def run_validation(pathogen: str = "MRSA") -> dict[str, Any]:
    actives = _load_actives()
    decoys = _DECOYS
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=45.0) as cx:
        for a in actives:
            s = await _score(cx, a["smiles"], pathogen)
            if s is not None:
                rows.append({"name": a["name"], "smiles": a["smiles"],
                             "label": 1, "score": s})
        for d in decoys:
            s = await _score(cx, d["smiles"], pathogen)
            if s is not None:
                rows.append({"name": d["name"], "smiles": d["smiles"],
                             "label": 0, "score": s, "class": d.get("class")})
    rows.sort(key=lambda r: r["score"], reverse=True)
    labels = [r["label"] for r in rows]
    n_active = sum(labels)
    n_decoy = len(labels) - n_active

    auc = _roc_auc(labels)
    metrics = {
        "roc_auc": auc,
        "ef_1pct": _enrichment_factor(labels, 0.01),
        "ef_5pct": _enrichment_factor(labels, 0.05),
        "ef_10pct": _enrichment_factor(labels, 0.10),
        "bedroc_20": _bedroc(labels, 20.0),
        "n_active": n_active,
        "n_decoy": n_decoy,
    }
    # ROC curve points (for the frontend plot).
    roc_points = _roc_curve(labels)
    # Verdict.
    if auc >= 0.8:
        verdict = "strong — the scorer cleanly separates antibiotics from non-antibacterials"
    elif auc >= 0.65:
        verdict = "working — antibiotics rank above decoys well above chance"
    elif auc >= 0.55:
        verdict = "directional — antibiotics rank above decoys, but the composite is a developability score (decoys are also marketed drugs), so full separation isn't expected without the activity head"
    else:
        verdict = "at chance — the composite does not discriminate on this set"

    return {
        "pathogen": pathogen,
        "metrics": metrics,
        "verdict": verdict,
        "method": ("Retrospective virtual screen: {na} marketed antibiotics "
                   "(actives) vs {nd} marketed non-antibacterials (decoys: "
                   "statins, NSAIDs, CNS, antihistamines, ...), ranked by the "
                   "Lysos composite. ROC-AUC = P(random active outranks random "
                   "decoy). Validates RANKING, not clinical accuracy.").format(
                       na=n_active, nd=n_decoy),
        "roc_points": roc_points,
        "ranked": [{"name": r["name"], "label": r["label"],
                    "score": round(r["score"], 3),
                    "class": r.get("class")} for r in rows],
        "computed_at": time.time(),
    }


def _roc_curve(labels_by_rank: list[int]) -> list[dict[str, float]]:
    n_pos = sum(labels_by_rank) or 1
    n_neg = (len(labels_by_rank) - sum(labels_by_rank)) or 1
    tp = fp = 0
    pts = [{"fpr": 0.0, "tpr": 0.0}]
    for lab in labels_by_rank:
        if lab == 1:
            tp += 1
        else:
            fp += 1
        pts.append({"fpr": round(fp / n_neg, 4), "tpr": round(tp / n_pos, 4)})
    return pts


# ─────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────

class ValidationRequest(BaseModel):
    pathogen: str = "MRSA"
    refresh: bool = False


@router.post("/validation/run")
async def validation_run(req: ValidationRequest) -> dict[str, Any]:
    """Run (or return cached) retrospective validation for a pathogen."""
    cache_id = f"validation-{req.pathogen}"
    if not req.refresh:
        cached = service_store.get_artifact(cache_id)
        if cached and cached.get("payload"):
            return {"id": cache_id, "cached": True, **cached["payload"]}
    result = await run_validation(req.pathogen)
    service_store.save_artifact(
        _CACHE_KIND, result, smiles=None,
        title=f"Validation · {req.pathogen} · AUC {result['metrics']['roc_auc']}",
        artifact_id=cache_id)
    return {"id": cache_id, "cached": False, **result}


@router.get("/validation/latest")
async def validation_latest(pathogen: str = "MRSA") -> dict[str, Any]:
    cache_id = f"validation-{pathogen}"
    cached = service_store.get_artifact(cache_id)
    if cached and cached.get("payload"):
        return {"id": cache_id, "cached": True, **cached["payload"]}
    return {"id": None, "cached": False, "metrics": None,
            "note": "no validation run yet — POST /validation/run"}
