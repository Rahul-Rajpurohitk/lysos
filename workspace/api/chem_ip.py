"""IP / Novelty Sentinel — Service 2, agentic rebuild.

The previous version GRADED a molecule ("freedom 0.63") — a dashboard.
This version ACTS: it honestly assesses prior art, and when close
prior art exists the agent DESIGNS a novelty-escaping variant — a
concrete structural edit that breaks the overlap while preserving the
antibacterial pharmacophore — RDKit-validates it, re-scans it to
PROVE the novelty went up, and queues it so the user accepts with one
word ("apply"). You end with a more patentable molecule, not a score.

Honesty (the previous version's sins, fixed):
  - No fabricated patent numbers. The reference panel lives in a data
    file (data/curated/fto_reference.json) with public-record fields
    only — name, structure, class, approval year, originator,
    patent-era status.
  - The verdict is derived from ONE consistent similarity ladder — it
    can no longer say "analogous IP nearby" when nothing is nearby.
  - Noise-level analogs (<0.45 Tanimoto) are NOT surfaced as threats.
  - Thresholds are env-configurable, not magic inline numbers.

Endpoints (router prefix /chem, mounted under /workbench):
  POST   /chem/ip/fto-scan         SMILES → prior-art report + escape variant
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
_ROOT = Path(__file__).resolve().parents[2]
_REFERENCE_PATH = Path(os.getenv("LYSOS_FTO_REFERENCE",
                                 str(_ROOT / "data" / "curated" / "fto_reference.json")))
_CORPUS_PARQUET = Path(os.getenv("LYSOS_FTO_CORPUS",
                                 str(_ROOT / "data" / "processed"
                                     / "known-antibiotics-canonical.parquet")))
_CORPUS_CAP = int(os.getenv("LYSOS_FTO_CORPUS_CAP", "12000"))

# Similarity ladder — env-configurable, not magic inline numbers.
_T_EXACT = float(os.getenv("LYSOS_FTO_EXACT", "0.985"))      # already published
_T_NEAR = float(os.getenv("LYSOS_FTO_NEAR", "0.85"))         # near-identical
_T_CLOSE = float(os.getenv("LYSOS_FTO_CLOSE", "0.70"))       # close prior art
_T_RELATED = float(os.getenv("LYSOS_FTO_RELATED", "0.55"))   # related prior art
_T_MEANINGFUL = float(os.getenv("LYSOS_FTO_MEANINGFUL", "0.45"))  # below = noise
_T_ESCAPE_TRIGGER = float(os.getenv("LYSOS_FTO_ESCAPE", "0.50"))  # design a variant at/above this


# ─────────────────────────────────────────────────────────────────────
# RDKit + reference loading
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


def _morgan(smiles: str):
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
        m = Chem.MolFromSmiles((smiles or "").strip())
        if m is None or m.GetNumAtoms() == 0:
            return None
        return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)
    except Exception:  # noqa: BLE001
        return None


def _non_drug_like_reason(smiles: str) -> Optional[str]:
    """Return a one-line reason why the input is NOT a drug-like
    candidate (so an IP / novelty analysis is meaningless), else None.
    Catches commodity chemicals (acetic anhydride, DMSO, …) and
    fragments that just happen to be absent from the antibiotic
    corpus."""
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles((smiles or "").strip())
        if m is None:
            return None  # let the caller flag the parse error
        n_heavy = m.GetNumHeavyAtoms()
        n_rings = m.GetRingInfo().NumRings()
        if n_heavy < 10:
            return (f"only {n_heavy} heavy atoms — likely a reagent or "
                    "fragment, not a drug candidate")
        if n_rings == 0:
            return ("acyclic molecule — no ring system, so it isn't a "
                    "drug-like scaffold to clear IP on")
        return None
    except Exception:  # noqa: BLE001
        return None


_REFERENCE: Optional[list[dict[str, Any]]] = None
_REFERENCE_FP: Optional[list[tuple[dict[str, Any], Any]]] = None
_CORPUS_FP: Optional[list[tuple[str, Any]]] = None


def _reference_fps() -> list[tuple[dict[str, Any], Any]]:
    """Load + fingerprint the curated reference panel from the data
    file. Invalid SMILES are dropped."""
    global _REFERENCE, _REFERENCE_FP
    if _REFERENCE_FP is not None:
        return _REFERENCE_FP
    try:
        _REFERENCE = json.loads(_REFERENCE_PATH.read_text()).get("antibiotics", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("FTO reference file unavailable (%s)", exc)
        _REFERENCE = []
    out: list[tuple[dict[str, Any], Any]] = []
    for entry in _REFERENCE:
        fp = _morgan(entry.get("smiles", ""))
        if fp is not None:
            out.append((entry, fp))
    _REFERENCE_FP = out
    log.info("FTO reference panel — %d/%d antibiotics fingerprinted",
             len(out), len(_REFERENCE or []))
    return out


def _corpus_fps() -> list[tuple[str, Any]]:
    """Lazily fingerprint a sample of the broad published-structure
    corpus for prior-art density. Cached; [] if the parquet is missing."""
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
        log.info("FTO prior-art corpus — %d fingerprints", len(out))
    except Exception as exc:  # noqa: BLE001
        log.warning("FTO corpus unavailable (%s)", exc)
    _CORPUS_FP = out
    return out


# ─────────────────────────────────────────────────────────────────────
# Prior-art scan — honest, one consistent similarity ladder
# ─────────────────────────────────────────────────────────────────────

def _verdict(cps: float, ref_hit: Optional[dict[str, Any]]) -> tuple[str, str, str]:
    """Return (verdict, novelty_tier, ip_note) from ONE ladder so the
    output can never contradict itself."""
    if cps >= _T_EXACT:
        return ("not novel — this exact structure is already published",
                "none", "Composition-of-matter is public; not patentable as new.")
    if cps >= _T_NEAR:
        return ("near-identical prior art — novelty very limited",
                "low", "A novelty argument would be hard to sustain.")
    if cps >= _T_CLOSE:
        # Close prior art — is that close thing protected?
        if ref_hit and ref_hit.get("ip_status") == "on-patent":
            return ("close to a protected drug — FTO review needed",
                    "low-medium",
                    f"Near {ref_hit['name']} ({ref_hit.get('originator','—')}), "
                    f"on-patent — clear before committing.")
        return ("close prior art — the novel elements must be argued",
                "medium", "Document what is structurally new vs the closest art.")
    if cps >= _T_RELATED:
        return ("related prior art — novelty is defensible",
                "good", "Related published matter exists; a clear novelty story holds.")
    return ("structurally novel — clear on the available prior art",
            "high", "No close published analog in the corpus.")


def _scan(smiles: str) -> dict[str, Any]:
    """Honest prior-art scan. The headline is structural novelty vs the
    real published corpus; the panel adds the marketed-drug context."""
    canon = _canonical(smiles)
    if canon is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")
    # Commodity-chem / non-drug gate. Acetic anhydride is absent from
    # the antibiotic corpus and would otherwise read as "novelty
    # high" — which is meaningless. Surface the truth instead.
    nd = _non_drug_like_reason(canon)
    if nd:
        return {
            "smiles": canon,
            "novelty_score": 0.0,
            "novelty_tier": "n/a",
            "verdict": f"Not a drug candidate — {nd}",
            "ip_note": ("IP / novelty analysis isn't meaningful for non-"
                        "drug inputs. Load an antibiotic candidate "
                        "(≥10 heavy atoms, at least one ring)."),
            "closest_published": None,
            "closest_published_similarity": 0.0,
            "closest_marketed_drug": None,
            "related_marketed_drugs": [],
            "prior_art": {
                "corpus_size": len(_corpus_fps()),
                "exact_matches": 0, "near_identical": 0,
                "close": 0, "related": 0,
            },
            "non_drug_reason": nd,
            "computed_at": time.time(),
        }
    fp = _morgan(canon)
    if fp is None:
        raise HTTPException(422, f"could not fingerprint: {smiles}")
    from rdkit import DataStructs

    # ── Reference panel — closest marketed antibiotic ──
    ref_hits: list[dict[str, Any]] = []
    for entry, rfp in _reference_fps():
        sim = float(DataStructs.TanimotoSimilarity(fp, rfp))
        ref_hits.append({**{k: entry.get(k) for k in
                            ("name", "smiles", "drug_class", "first_approval",
                             "originator", "ip_status")},
                         "similarity": round(sim, 3)})
    ref_hits.sort(key=lambda h: h["similarity"], reverse=True)
    # Only surface a reference analog if the match is MEANINGFUL — a
    # 0.08-Tanimoto "hit" is noise, never a threat.
    closest_ref = (ref_hits[0] if ref_hits
                   and ref_hits[0]["similarity"] >= _T_MEANINGFUL else None)
    top_ref = [h for h in ref_hits[:3] if h["similarity"] >= _T_MEANINGFUL]

    # ── Broad corpus — closest published structure + density ──
    corpus = _corpus_fps()
    cps = 0.0                     # closest published similarity
    closest_pub: Optional[dict[str, Any]] = None
    exact_pub = near = close = related = 0
    if corpus:
        sims = DataStructs.BulkTanimotoSimilarity(fp, [c[1] for c in corpus])
        for (name, _), s in zip(corpus, sims):
            if s >= _T_EXACT:
                exact_pub += 1
            elif s >= _T_NEAR:
                near += 1
            elif s >= _T_CLOSE:
                close += 1
            elif s >= _T_RELATED:
                related += 1
            if s > cps:
                cps = float(s)
                closest_pub = {"ref": name, "similarity": round(float(s), 3)}

    verdict, novelty_tier, ip_note = _verdict(cps, closest_ref)
    novelty_score = round(max(0.0, min(1.0, 1.0 - cps)), 3)

    return {
        "smiles": canon,
        "novelty_score": novelty_score,
        "novelty_tier": novelty_tier,
        "verdict": verdict,
        "ip_note": ip_note,
        "closest_published": closest_pub,
        "closest_published_similarity": round(cps, 3),
        "closest_marketed_drug": closest_ref,
        "related_marketed_drugs": top_ref,
        "prior_art": {
            "corpus_size": len(corpus),
            "exact_matches": exact_pub,
            "near_identical": near,
            "close": close,
            "related": related,
        },
        "computed_at": time.time(),
    }


# ─────────────────────────────────────────────────────────────────────
# Agentic action — design a novelty-escaping variant
# ─────────────────────────────────────────────────────────────────────

async def _design_escape_variant(scan: dict[str, Any]) -> Optional[dict[str, Any]]:
    """THE agentic payoff. When close prior art exists, ask the agent
    for ONE structural edit that breaks the overlap while keeping the
    antibacterial pharmacophore — then RDKit-validate it and RE-SCAN
    to prove the novelty actually improved. None when no edit is
    needed (already novel) or the design fails."""
    # Non-drug inputs can't have an escape variant.
    if scan.get("non_drug_reason"):
        return None
    cps = scan.get("closest_published_similarity", 0.0)
    if cps < _T_ESCAPE_TRIGGER:
        return None  # already structurally novel — no escape edit needed
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    closest = scan.get("closest_published") or {}
    ref = scan.get("closest_marketed_drug") or {}
    prompt = (
        "You are a medicinal chemist protecting an antibiotic program's "
        "IP. The candidate has close published prior art. Propose ONE "
        "concrete structural modification that REDUCES its structural "
        "similarity to that prior art (raises novelty / patentability) "
        "while PRESERVING the antibacterial pharmacophore — keep the "
        "β-lactam warhead / core mechanism intact; modify the "
        "periphery (side chains, substituents, a ring swap).\n\n"
        f"Candidate SMILES: {scan['smiles']}\n"
        f"Closest published structure similarity: {cps}\n"
        + (f"Closest marketed antibiotic: {ref.get('name')} "
           f"({ref.get('drug_class')})\n" if ref else "")
        + "\nReturn STRICT JSON:\n"
        '{"variant_smiles": "<valid SMILES of the modified molecule>", '
        '"modification": "<=60 chars — the edit>", '
        '"rationale": "<=180 chars — why this breaks the overlap yet '
        'keeps activity>"}\n'
    )
    try:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + os.getenv("LYSOS_IP_MODEL", "gemini-2.5-flash")
               + ":generateContent")
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": 900, "temperature": 0.4,
                "thinkingConfig": {"thinkingBudget": 0, "includeThoughts": False},
            },
        }
        async with httpx.AsyncClient(timeout=25.0) as cx:
            r = await cx.post(url, headers={"x-goog-api-key": key,
                                            "Content-Type": "application/json"},
                              json=payload)
        if r.status_code != 200:
            return None
        parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        raw = "".join(p.get("text", "") for p in parts).strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.M).strip()
        obj = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        log.warning("escape-variant design failed: %s", exc)
        return None

    variant = _canonical(obj.get("variant_smiles", ""))
    if variant is None or variant == scan["smiles"]:
        return None
    # Re-scan the variant — PROVE the novelty improved.
    try:
        v_scan = _scan(variant)
    except HTTPException:
        return None
    novelty_before = scan.get("novelty_score", 0.0)
    novelty_after = v_scan.get("novelty_score", 0.0)
    return {
        "variant_smiles": variant,
        "modification": str(obj.get("modification") or "structural edit")[:80],
        "rationale": str(obj.get("rationale") or "")[:200],
        "novelty_before": novelty_before,
        "novelty_after": novelty_after,
        "novelty_delta": round(novelty_after - novelty_before, 3),
        "closest_similarity_before": scan.get("closest_published_similarity"),
        "closest_similarity_after": v_scan.get("closest_published_similarity"),
        "verdict_after": v_scan.get("verdict"),
        "improved": novelty_after > novelty_before + 0.02,
    }


# ─────────────────────────────────────────────────────────────────────
# API — scan + agentic variant
# ─────────────────────────────────────────────────────────────────────

class FTORequest(BaseModel):
    smiles: str
    session_id: Optional[str] = None
    save: bool = True
    title: Optional[str] = None
    design_variant: bool = True


@router.post("/ip/fto-scan")
async def fto_scan(req: FTORequest) -> dict[str, Any]:
    """SMILES → honest prior-art report. When close prior art exists the
    agent designs a novelty-escaping variant, proves the novelty gain,
    and queues it for one-tap 'apply'. Auto-saved + fed to the dossier."""
    smi = (req.smiles or "").strip()
    if not smi:
        raise HTTPException(400, "smiles required")
    report = _scan(smi)

    escape = await _design_escape_variant(report) if req.design_variant else None
    report["escape_variant"] = escape

    artifact_id = None
    if req.save:
        title = req.title or (
            f"Novelty · {report['novelty_tier']} · score {report['novelty_score']}")
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, report,
            session_id=req.session_id, smiles=report["smiles"], title=title)
        artifact_id = rec["id"]
    report["artifact_id"] = artifact_id

    # ── Agentic close-the-loop — queue the escape variant so the user
    # accepts it with one word. This is the ACTION, not a card. ──
    if escape and escape.get("improved"):
        try:
            from . import session_memory
            session_memory.record_proposal(
                req.session_id or "", escape["variant_smiles"],
                source="ip-sentinel",
                swap_label=f"novelty-escape variant ({escape['modification']})",
                rationale=(f"Lifts novelty {escape['novelty_before']}→"
                           f"{escape['novelty_after']} by escaping the closest "
                           f"prior art. {escape['rationale']}"))
        except Exception as exc:  # noqa: BLE001
            log.debug("escape-variant queue failed: %s", exc)

    # ── Integration backbone — feed the dossier ──
    try:
        from . import candidate_dossier
        candidate_dossier.upsert_facet(
            req.session_id, report["smiles"], "fto", {
                "novelty_score": report["novelty_score"],
                "freedom_score": report["novelty_score"],  # dossier-compat key
                "verdict": report["verdict"],
                "closest_similarity": report["closest_published_similarity"],
                "escape_variant_smiles": (escape or {}).get("variant_smiles"),
                "report_artifact_id": artifact_id,
            })
    except Exception as exc:  # noqa: BLE001
        log.debug("dossier feed (fto) failed: %s", exc)
    return report


@router.get("/ip/reports")
async def list_reports(session_id: Optional[str] = None,
                       smiles: Optional[str] = None,
                       limit: int = 100) -> dict[str, Any]:
    rows = service_store.list_artifacts(
        kind=_ARTIFACT_KIND, session_id=session_id, smiles=smiles, limit=limit)
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
    return {"deleted": service_store.delete_artifact(rid), "id": rid}
