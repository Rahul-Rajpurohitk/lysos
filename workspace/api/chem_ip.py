"""IP / FTO Sentinel — Service 2 of the productized service layer.

Answers the question that decides whether a molecule is worth anything:
is it novel, or is it already patented / published? The `novelty`
reward axis is a number; freedom-to-operate (FTO) is a *decision* — and
no antibiotic program commits a cent without it.

Two evidence layers, both real:
  1. Curated patent panel — ~20 named antibiotics with patent status
     (public-domain / marketed-generic / marketed-patented / clinical).
     The candidate's Tanimoto similarity to these gives the
     CLAIM-OVERLAP risk. The sophistication: similarity to an
     OFF-PATENT drug is fine — you cannot infringe a dead patent;
     similarity to an ON-PATENT or clinical compound is the real risk.
  2. Broad prior-art corpus — the 30k-structure canonical antibiotic
     set (ChEMBL). Bulk-Tanimoto gives PRIOR-ART DENSITY: how crowded
     the chemical neighbourhood is + the single closest published
     structure (a ChEMBL id = a real published reference).

freedom_score (0-1, higher = freer) + a verdict (clear / watch /
blocked) combine both. Every scan feeds the candidate dossier.

Endpoints (router prefix /chem, mounted under /workbench):
  POST   /chem/ip/fto-scan         SMILES → freedom-to-operate report
  GET    /chem/ip/reports          list saved reports (CRUD)
  GET    /chem/ip/reports/{rid}    one report
  DELETE /chem/ip/reports/{rid}    delete a report
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("api.chem_ip")
router = APIRouter(prefix="/chem", tags=["chem_ip"])

_ARTIFACT_KIND = "fto_report"
_CORPUS_PARQUET = (Path(__file__).resolve().parents[2]
                   / "data" / "processed" / "known-antibiotics-canonical.parquet")
_CORPUS_CAP = 12000          # prior-art density sample size


# ─────────────────────────────────────────────────────────────────────
# Curated patent panel — named antibiotics with IP status.
#  status: public-domain | marketed-generic | marketed-patented | clinical
# Most antibiotics are OFF patent (public-domain / marketed-generic) —
# that is the whole point of the claim-overlap logic below.
# ─────────────────────────────────────────────────────────────────────

_FTO_PANEL: list[dict[str, Any]] = [
    {"name": "Penicillin G", "smiles": "O=C(O)C1N2C(=O)C(NC(=O)Cc3ccccc3)C2SC1(C)C",
     "drug_class": "penicillin", "status": "public-domain", "patent": "expired 1949", "assignee": "—", "year": 1945},
    {"name": "Amoxicillin", "smiles": "O=C(O)C1N2C(=O)C(NC(=O)C(N)c3ccc(O)cc3)C2SC1(C)C",
     "drug_class": "penicillin", "status": "marketed-generic", "patent": "expired", "assignee": "Beecham", "year": 1972},
    {"name": "Ampicillin", "smiles": "O=C(O)C1N2C(=O)C(NC(=O)C(N)c3ccccc3)C2SC1(C)C",
     "drug_class": "penicillin", "status": "marketed-generic", "patent": "expired", "assignee": "Beecham", "year": 1961},
    {"name": "Cephalexin", "smiles": "O=C(O)C1=C(C)CSC2C(NC(=O)C(N)c3ccccc3)C(=O)N12",
     "drug_class": "cephalosporin", "status": "marketed-generic", "patent": "expired", "assignee": "Eli Lilly", "year": 1967},
    {"name": "Cefadroxil", "smiles": "O=C(O)C1=C(C)CSC2C(NC(=O)C(N)c3ccc(O)cc3)C(=O)N12",
     "drug_class": "cephalosporin", "status": "marketed-generic", "patent": "expired", "assignee": "Bristol-Myers", "year": 1978},
    {"name": "Cefepime", "smiles": "CON=C(c1csc(N)n1)C(=O)NC1C(=O)N2C(C(=O)O)=C(C[N+]3(C)CCCC3)CSC12",
     "drug_class": "cephalosporin", "status": "marketed-generic", "patent": "expired", "assignee": "Bristol-Myers Squibb", "year": 1994},
    {"name": "Avibactam", "smiles": "NC(=O)C1C2CCN1C(=O)N2OS(=O)(=O)O",
     "drug_class": "β-lactamase inhibitor", "status": "marketed-patented", "patent": "US8148540 / family", "assignee": "Allergan / Pfizer", "year": 2015},
    {"name": "Clavulanic acid", "smiles": "OC(=O)C1C(=CCO)OC2CC(=O)N12",
     "drug_class": "β-lactamase inhibitor", "status": "public-domain", "patent": "expired", "assignee": "Beecham", "year": 1985},
    {"name": "Sulbactam", "smiles": "CC1(C)C(C(=O)O)N2C(=O)CC2S1(=O)=O",
     "drug_class": "β-lactamase inhibitor", "status": "marketed-generic", "patent": "expired", "assignee": "Pfizer", "year": 1986},
    {"name": "Ciprofloxacin", "smiles": "O=C(O)C1=CN(C2CC2)c2cc(N3CCNCC3)c(F)cc2C1=O",
     "drug_class": "fluoroquinolone", "status": "marketed-generic", "patent": "expired", "assignee": "Bayer", "year": 1987},
    {"name": "Levofloxacin", "smiles": "CC1COc2c(N3CCN(C)CC3)c(F)cc3c(=O)c(C(=O)O)cn1c23",
     "drug_class": "fluoroquinolone", "status": "marketed-generic", "patent": "expired", "assignee": "Daiichi Sankyo", "year": 1996},
    {"name": "Norfloxacin", "smiles": "O=C(O)C1=CN(CC)c2cc(N3CCNCC3)c(F)cc2C1=O",
     "drug_class": "fluoroquinolone", "status": "marketed-generic", "patent": "expired", "assignee": "Kyorin", "year": 1986},
    {"name": "Moxifloxacin", "smiles": "COc1c(N2CC3CCCNC3C2)c(F)cc2c(=O)c(C(=O)O)cn(C3CC3)c12",
     "drug_class": "fluoroquinolone", "status": "marketed-generic", "patent": "expired", "assignee": "Bayer", "year": 1999},
    {"name": "Linezolid", "smiles": "CC(=O)NCC1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1",
     "drug_class": "oxazolidinone", "status": "marketed-generic", "patent": "expired 2015", "assignee": "Pharmacia / Pfizer", "year": 2000},
    {"name": "Trimethoprim", "smiles": "COc1cc(Cc2cnc(N)nc2N)cc(OC)c1OC",
     "drug_class": "DHFR inhibitor", "status": "public-domain", "patent": "expired", "assignee": "Burroughs Wellcome", "year": 1968},
    {"name": "Sulfamethoxazole", "smiles": "Cc1cc(NS(=O)(=O)c2ccc(N)cc2)no1",
     "drug_class": "sulfonamide", "status": "public-domain", "patent": "expired", "assignee": "—", "year": 1961},
    {"name": "Metronidazole", "smiles": "Cc1ncc([N+](=O)[O-])n1CCO",
     "drug_class": "nitroimidazole", "status": "public-domain", "patent": "expired", "assignee": "Rhône-Poulenc", "year": 1960},
    {"name": "Chloramphenicol", "smiles": "OCC(NC(=O)C(Cl)Cl)C(O)c1ccc([N+](=O)[O-])cc1",
     "drug_class": "amphenicol", "status": "public-domain", "patent": "expired", "assignee": "—", "year": 1949},
    {"name": "Nitrofurantoin", "smiles": "O=C1CN(N=Cc2ccc([N+](=O)[O-])o2)C(=O)N1",
     "drug_class": "nitrofuran", "status": "public-domain", "patent": "expired", "assignee": "—", "year": 1953},
    {"name": "Isoniazid", "smiles": "NNC(=O)c1ccncc1",
     "drug_class": "antitubercular", "status": "public-domain", "patent": "expired", "assignee": "—", "year": 1952},
    {"name": "Fosfomycin", "smiles": "CC1OC1P(=O)(O)O",
     "drug_class": "phosphonate", "status": "public-domain", "patent": "expired", "assignee": "—", "year": 1969},
]

# Lazy-built fingerprint caches (Morgan r2, 2048 bits).
_PANEL_FP: Optional[list[tuple[dict[str, Any], Any]]] = None
_CORPUS_FP: Optional[list[tuple[str, Any]]] = None


def _morgan(smiles: str):
    """Morgan fingerprint (r2, 2048 bit), or None on parse failure."""
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
        m = Chem.MolFromSmiles((smiles or "").strip())
        if m is None or m.GetNumAtoms() == 0:
            return None
        return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)
    except Exception:  # noqa: BLE001
        return None


def _canonical(smiles: str) -> Optional[str]:
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles((smiles or "").strip())
        if m is None or m.GetNumAtoms() == 0:
            return None
        return Chem.MolToSmiles(m)
    except Exception:  # noqa: BLE001
        return None


def _panel_fps() -> list[tuple[dict[str, Any], Any]]:
    """Fingerprint the curated panel once. Invalid SMILES are dropped."""
    global _PANEL_FP
    if _PANEL_FP is not None:
        return _PANEL_FP
    out: list[tuple[dict[str, Any], Any]] = []
    for entry in _FTO_PANEL:
        fp = _morgan(entry["smiles"])
        if fp is not None:
            out.append((entry, fp))
        else:
            log.warning("FTO panel: dropped unparseable %s", entry.get("name"))
    _PANEL_FP = out
    log.info("FTO panel ready — %d/%d entries fingerprinted",
             len(out), len(_FTO_PANEL))
    return out


def _corpus_fps() -> list[tuple[str, Any]]:
    """Lazily fingerprint a sample of the broad antibiotic corpus for
    prior-art density. Cached. Empty list if the parquet is missing."""
    global _CORPUS_FP
    if _CORPUS_FP is not None:
        return _CORPUS_FP
    out: list[tuple[str, Any]] = []
    try:
        import pandas as pd
        df = pd.read_parquet(_CORPUS_PARQUET, columns=["smiles", "name"])
        for _, row in df.head(_CORPUS_CAP).iterrows():
            fp = _morgan(str(row.get("smiles") or ""))
            if fp is not None:
                out.append((str(row.get("name") or "structure"), fp))
        log.info("FTO prior-art corpus ready — %d fingerprints", len(out))
    except Exception as exc:  # noqa: BLE001
        log.warning("FTO corpus unavailable (%s) — density signal disabled", exc)
    _CORPUS_FP = out
    return out


# ─────────────────────────────────────────────────────────────────────
# FTO scan
# ─────────────────────────────────────────────────────────────────────

# Patent statuses that represent a LIVE exclusivity an analog could
# block against. public-domain / marketed-generic = dead patent = safe.
_LIVE_IP = {"marketed-patented", "clinical"}


def _claim_risk(similarity: float, status: str) -> tuple[str, float]:
    """Claim-overlap risk + a 0-1 risk weight from similarity to an
    analog AND that analog's patent status. Similarity to an OFF-patent
    drug carries (almost) no IP risk — you cannot infringe a dead claim."""
    live = status in _LIVE_IP
    if not live:
        # Closest analog's patent is dead — only a faint composition
        # risk if it is near-identical to a very recent generic.
        if similarity >= 0.92:
            return "low-medium", 0.35
        return "low", 0.12
    # Closest analog has live exclusivity.
    if similarity >= 0.85:
        return "high", 0.90
    if similarity >= 0.70:
        return "medium", 0.62
    if similarity >= 0.55:
        return "low-medium", 0.38
    return "low", 0.15


async def _scan(smiles: str) -> dict[str, Any]:
    """Core FTO computation — panel claim-overlap + corpus prior-art."""
    canon = _canonical(smiles)
    if canon is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")
    fp = _morgan(canon)
    if fp is None:
        raise HTTPException(422, f"could not fingerprint: {smiles}")

    from rdkit import DataStructs

    # ── Curated patent panel — claim-overlap ──
    panel_hits: list[dict[str, Any]] = []
    for entry, pfp in _panel_fps():
        sim = float(DataStructs.TanimotoSimilarity(fp, pfp))
        panel_hits.append({**{k: entry[k] for k in
                              ("name", "smiles", "drug_class", "status",
                               "patent", "assignee", "year")},
                           "similarity": round(sim, 3)})
    panel_hits.sort(key=lambda h: h["similarity"], reverse=True)
    top_panel = panel_hits[:3]
    closest = top_panel[0] if top_panel else None

    # The IP risk is driven by the closest LIVE-patent analog, not just
    # the closest analog overall (similarity to an expired drug is OK).
    closest_live = next((h for h in panel_hits if h["status"] in _LIVE_IP), None)
    risk_basis = closest_live or closest
    if risk_basis:
        claim_risk, risk_w = _claim_risk(risk_basis["similarity"], risk_basis["status"])
    else:
        claim_risk, risk_w = "low", 0.1

    # ── Broad corpus — prior-art density ──
    corpus = _corpus_fps()
    near_092 = near_070 = near_055 = 0
    closest_pub: Optional[dict[str, Any]] = None
    best_pub_sim = -1.0
    if corpus:
        sims = DataStructs.BulkTanimotoSimilarity(fp, [c[1] for c in corpus])
        for (name, _), s in zip(corpus, sims):
            if s >= 0.92:
                near_092 += 1
            if s >= 0.70:
                near_070 += 1
            if s >= 0.55:
                near_055 += 1
            if s > best_pub_sim:
                best_pub_sim = s
                closest_pub = {"ref": name, "similarity": round(float(s), 3)}
    # Density penalty — a crowded neighbourhood erodes freedom.
    density_penalty = min(0.35, 0.04 * near_070 + 0.18 * (near_092 > 0))

    # ── freedom_score (0-1, higher = freer) + verdict ──
    freedom = max(0.0, min(1.0, 1.0 - risk_w - density_penalty))
    if freedom >= 0.66 and claim_risk in ("low", "low-medium"):
        verdict = "clear to operate"
    elif freedom >= 0.4:
        verdict = "watch — analogous IP nearby"
    else:
        verdict = "blocked — likely within a live claim"

    return {
        "smiles": canon,
        "freedom_score": round(freedom, 3),
        "verdict": verdict,
        "claim_overlap_risk": claim_risk,
        "closest_analog": closest,
        "closest_live_patent_analog": closest_live,
        "top_panel_analogs": top_panel,
        "closest_published_structure": closest_pub,
        "prior_art": {
            "corpus_size": len(corpus),
            "near_identical_092": near_092,
            "similar_070": near_070,
            "related_055": near_055,
        },
        "computed_at": time.time(),
    }


async def _ip_narrative(report: dict[str, Any]) -> dict[str, Any]:
    """IP-analyst agent — a short freedom-to-operate assessment over the
    computed evidence. Deterministic fallback when Gemini is off."""
    closest = report.get("closest_analog") or {}
    live = report.get("closest_live_patent_analog")
    pa = report.get("prior_art") or {}
    fallback = {
        "assessment": (
            f"Closest known antibiotic is {closest.get('name','—')} "
            f"({closest.get('similarity','—')} Tanimoto, "
            f"{closest.get('status','—')}). "
            + (f"Closest LIVE-patent analog: {live['name']} "
               f"({live['similarity']} sim, {live.get('assignee','—')}). "
               if live else "No live-patent analog within the panel. ")
            + f"{pa.get('similar_070',0)} published structures within 0.70 "
              f"Tanimoto — "
            + ("a crowded neighbourhood." if pa.get('similar_070', 0) > 8
               else "a relatively open neighbourhood.")),
        "recommended_action": (
            "Commission a formal FTO search before synthesis."
            if report.get("claim_overlap_risk") in ("high", "medium")
            else "Document the novelty rationale; a light FTO check suffices."),
        "model": "deterministic",
    }
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return fallback
    prompt = (
        "You are an IP analyst for an antibiotics program. Give a concise, "
        "honest freedom-to-operate read on this candidate.\n\n"
        f"Candidate: {report.get('smiles')}\n"
        f"Closest known antibiotic: {closest.get('name')} "
        f"({closest.get('similarity')} Tanimoto, status {closest.get('status')}, "
        f"assignee {closest.get('assignee')})\n"
        f"Closest LIVE-patent analog: {live}\n"
        f"Prior-art density: {pa}\n"
        f"Computed claim-overlap risk: {report.get('claim_overlap_risk')}; "
        f"freedom_score {report.get('freedom_score')}\n\n"
        "Return STRICT JSON:\n"
        '{"assessment": "<=240 chars — the freedom-to-operate picture", '
        '"recommended_action": "<=160 chars — concrete next step"}\n'
    )
    try:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + os.getenv("LYSOS_IP_MODEL", "gemini-2.5-flash")
               + ":generateContent")
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": 800, "temperature": 0.3,
                "thinkingConfig": {"thinkingBudget": 0, "includeThoughts": False},
            },
        }
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.post(url, headers={"x-goog-api-key": key,
                                            "Content-Type": "application/json"},
                              json=payload)
        if r.status_code != 200:
            return fallback
        parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        raw = "".join(p.get("text", "") for p in parts).strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.M).strip()
        obj = json.loads(raw)
        return {
            "assessment": str(obj.get("assessment") or fallback["assessment"])[:280],
            "recommended_action": str(obj.get("recommended_action")
                                      or fallback["recommended_action"])[:200],
            "model": os.getenv("LYSOS_IP_MODEL", "gemini-2.5-flash"),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("IP narrative failed: %s", exc)
        return fallback


# ─────────────────────────────────────────────────────────────────────
# API — compute
# ─────────────────────────────────────────────────────────────────────

class FTORequest(BaseModel):
    smiles: str
    session_id: Optional[str] = None
    save: bool = True
    title: Optional[str] = None


@router.post("/ip/fto-scan")
async def fto_scan(req: FTORequest) -> dict[str, Any]:
    """SMILES → freedom-to-operate report. Tanimoto vs the curated
    patent panel + the broad prior-art corpus, with an IP-analyst
    narrative. Auto-saved + fed to the candidate dossier."""
    smi = (req.smiles or "").strip()
    if not smi:
        raise HTTPException(400, "smiles required")
    report = await _scan(smi)
    report["narrative"] = await _ip_narrative(report)

    artifact_id = None
    if req.save:
        title = req.title or (
            f"FTO · {report['verdict']} · freedom {report['freedom_score']}")
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, report,
            session_id=req.session_id, smiles=report["smiles"], title=title,
        )
        artifact_id = rec["id"]
    report["artifact_id"] = artifact_id

    # ── Integration backbone — link the FTO facet into the dossier ──
    try:
        from . import candidate_dossier
        candidate_dossier.upsert_facet(
            req.session_id, report["smiles"], "fto", {
                "freedom_score": report["freedom_score"],
                "verdict": report["verdict"],
                "claim_overlap_risk": report["claim_overlap_risk"],
                "closest_name": (report.get("closest_analog") or {}).get("name"),
                "closest_similarity": (report.get("closest_analog") or {}).get("similarity"),
                "report_artifact_id": artifact_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("dossier feed (fto) failed: %s", exc)
    return report


# ─────────────────────────────────────────────────────────────────────
# API — CRUD over saved FTO reports
# ─────────────────────────────────────────────────────────────────────

@router.get("/ip/reports")
async def list_reports(
    session_id: Optional[str] = None,
    smiles: Optional[str] = None,
    limit: int = 100,
) -> dict[str, Any]:
    rows = service_store.list_artifacts(
        kind=_ARTIFACT_KIND, session_id=session_id, smiles=smiles, limit=limit,
    )
    return {"reports": rows, "n": len(rows)}


@router.get("/ip/reports/{rid}")
async def get_report(rid: str) -> dict[str, Any]:
    rec = service_store.get_artifact(rid)
    if rec is None or rec.get("kind") != _ARTIFACT_KIND:
        raise HTTPException(404, f"FTO report not found: {rid}")
    return rec


@router.delete("/ip/reports/{rid}")
async def delete_report(rid: str) -> dict[str, Any]:
    rec = service_store.get_artifact(rid)
    if rec is None or rec.get("kind") != _ARTIFACT_KIND:
        raise HTTPException(404, f"FTO report not found: {rid}")
    ok = service_store.delete_artifact(rid)
    return {"deleted": ok, "id": rid}
