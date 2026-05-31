"""Molecular generation — Service 4 (de-novo + lead-optimization).

This is where the Designer agent stops *imagining* SMILES and starts
*generating* real, valid, novel molecules from chemical building blocks.

Two engines behind one contract:
  - **brics** (always-on, local): RDKit BRICS fragment decomposition +
    recombination. Seeds from the candidate (lead-opt) or from a curated
    antibiotic-fragment pool (de-novo). Every output is RDKit-validated,
    canonicalized, deduped, novelty-filtered, and Lipinski-gated. No GPU,
    no API — works offline, instantly.
  - **genmol** (MI300X, Act II): NVIDIA GenMol discrete-diffusion over SAFE
    fragments. Wired as a model-service call (LYSOS_GENMOL_SERVICE_URL),
    falls back to BRICS when the service is down.

The point: real generative chemistry, not an LLM emitting plausible-looking
strings. Output candidates flow straight into scoring + the campaign.

Six-layer contract: service_store · this module · agent tool (generate_
candidates) · workflow (generate_leads) · orchestrator entry · frontend
GeneratorCard + campaign feed.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store, session_memory

log = logging.getLogger("lysos.chem_generate")
router = APIRouter(prefix="/chem", tags=["chem_generate"])

_ARTIFACT_KIND = "generation_run"
_GENMOL_URL = os.getenv("LYSOS_GENMOL_SERVICE_URL", "")  # empty = BRICS only

# A curated antibiotic-fragment seed pool for de-novo runs (no seed SMILES).
# Pharmacophore-bearing fragments from known antibiotic classes — used to
# bias BRICS recombination toward antibacterial chemical space.
_ANTIBIOTIC_SEEDS = [
    "CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O",  # penicillin G core
    "O=C(O)c1cc2cc(F)c(N3CCNCC3)cc2n(C1)C1CC1",                  # fluoroquinolone-like
    "CO[C@]1(NC(=O)C)C(=O)N(C1)S(=O)(=O)O",                       # monobactam-like
    "Cc1ncc([N+](=O)[O-])n1CC(O)CO",                              # nitroimidazole
    "Nc1ccc(S(N)(=O)=O)cc1",                                      # sulfonamide
    "CC(=O)Nc1ccc(O)cc1",                                         # acetanilide motif
    "Oc1ccc2ccccc2c1",                                            # naphthol
    "c1ccc2[nH]ccc2c1",                                           # indole
]


# ─────────────────────────────────────────────────────────────────────
# RDKit helpers
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


def _lipinski_ok(smiles: str) -> bool:
    """Drug-like gate so generated junk never reaches the user."""
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, Crippen, rdMolDescriptors
        m = Chem.MolFromSmiles(smiles)
        if m is None:
            return False
        mw = Descriptors.MolWt(m)
        logp = Crippen.MolLogP(m)
        hbd = rdMolDescriptors.CalcNumHBD(m)
        hba = rdMolDescriptors.CalcNumHBA(m)
        n_heavy = m.GetNumHeavyAtoms()
        # Slightly relaxed Ro5 (antibiotics break it more than oral drugs),
        # but keep a sane envelope so we don't emit nonsense.
        return (150 <= mw <= 700 and -2 <= logp <= 6
                and hbd <= 7 and hba <= 12 and n_heavy >= 12)
    except Exception:  # noqa: BLE001
        return False


def _tanimoto(a: str, b: str) -> float:
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, DataStructs
        ma, mb = Chem.MolFromSmiles(a), Chem.MolFromSmiles(b)
        if ma is None or mb is None:
            return 0.0
        fa = AllChem.GetMorganFingerprintAsBitVect(ma, 2, 2048)
        fb = AllChem.GetMorganFingerprintAsBitVect(mb, 2, 2048)
        return float(DataStructs.TanimotoSimilarity(fa, fb))
    except Exception:  # noqa: BLE001
        return 0.0


# ─────────────────────────────────────────────────────────────────────
# Engine 1 — BRICS fragment recombination (always-on, local)
# ─────────────────────────────────────────────────────────────────────

def _brics_generate(seed: Optional[str], n: int) -> list[str]:
    """Decompose seed (or the antibiotic pool) into BRICS fragments and
    recombine into novel valid molecules. Deterministic-ish: BRICSBuild
    explores combinations; we take the first n valid+drug-like+novel."""
    try:
        from rdkit import Chem
        from rdkit.Chem import BRICS
    except Exception:  # noqa: BLE001
        return []

    sources: list[str] = []
    if seed:
        c = _canonical(seed)
        if c:
            sources.append(c)
    # Always mix in antibiotic seeds so recombination has pharmacophore parts.
    sources.extend(_ANTIBIOTIC_SEEDS)

    mols = [Chem.MolFromSmiles(s) for s in sources]
    mols = [m for m in mols if m is not None]
    if not mols:
        return []

    # Collect BRICS fragments across all sources.
    frags: set[str] = set()
    for m in mols:
        try:
            for f in BRICS.BRICSDecompose(m):
                frags.add(f)
        except Exception:  # noqa: BLE001
            continue
    frag_mols = [Chem.MolFromSmiles(f) for f in frags]
    frag_mols = [f for f in frag_mols if f is not None]
    if len(frag_mols) < 2:
        return []

    out: list[str] = []
    seen: set[str] = set(sources)
    try:
        builder = BRICS.BRICSBuild(frag_mols)
        # BRICSBuild is a generator over recombinations — cap the scan so
        # we never hang on a huge fragment set.
        for i, prod in enumerate(builder):
            if i > 2000 or len(out) >= n:
                break
            try:
                prod.UpdatePropertyCache(strict=False)
                smi = Chem.MolToSmiles(prod)
            except Exception:  # noqa: BLE001
                continue
            if not smi or smi in seen:
                continue
            seen.add(smi)
            if not _lipinski_ok(smi):
                continue
            # Novelty vs the seed — keep genuinely new structures.
            if seed and _tanimoto(smi, _canonical(seed) or seed) > 0.85:
                continue
            out.append(smi)
    except Exception as exc:  # noqa: BLE001
        log.warning("BRICSBuild failed: %s", exc)
    return out


# ─────────────────────────────────────────────────────────────────────
# Engine 2 — GenMol on MI300X (Act II), with BRICS fallback
# ─────────────────────────────────────────────────────────────────────

async def _genmol_generate(seed: Optional[str], n: int) -> Optional[list[str]]:
    """Call the GenMol model service (MI300X). None if unavailable."""
    if not _GENMOL_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=60.0) as cx:
            r = await cx.post(f"{_GENMOL_URL}/generate",
                              json={"seed": seed, "n": n})
        if r.status_code != 200:
            return None
        body = r.json()
        cands = body.get("smiles") or []
        valid = []
        for s in cands:
            c = _canonical(s)
            if c and _lipinski_ok(c):
                valid.append(c)
        return valid or None
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────
# Generation run — assemble + score + rank
# ─────────────────────────────────────────────────────────────────────

async def _score_smiles(api_base: str, smiles: str, pathogen: str) -> Optional[dict[str, Any]]:
    """Score one generated molecule via the existing scorer so generated
    candidates are ranked by the SAME 12-axis stack as everything else."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as cx:
            r = await cx.post(f"{api_base}/workbench/score",
                              json={"smiles": smiles, "target_pathogen": pathogen})
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:  # noqa: BLE001
        return None


async def _run_generation(seed: Optional[str], n: int, pathogen: str,
                          api_base: str) -> dict[str, Any]:
    t0 = time.time()
    engine = "brics"
    cands = await _genmol_generate(seed, n * 2)
    if cands:
        engine = "genmol"
    else:
        cands = _brics_generate(seed, n * 3)
    cands = cands[: n * 3]

    # Score + rank. Best-effort scoring; unscored still returned.
    scored: list[dict[str, Any]] = []
    for smi in cands:
        sc = await _score_smiles(api_base, smi, pathogen)
        composite = None
        if isinstance(sc, dict):
            composite = sc.get("composite") or sc.get("composite_reward")
        scored.append({
            "smiles": smi,
            "composite": composite,
            "novelty_vs_seed": round(1.0 - _tanimoto(smi, seed), 3) if seed else None,
        })
    scored.sort(key=lambda x: (x["composite"] is not None, x["composite"] or 0),
                reverse=True)
    top = scored[:n]
    return {
        "seed": seed,
        "pathogen": pathogen,
        "engine": engine,
        "n_requested": n,
        "n_generated": len(cands),
        "n_returned": len(top),
        "candidates": top,
        "elapsed_s": round(time.time() - t0, 2),
        "computed_at": time.time(),
    }


# ─────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    seed: Optional[str] = None          # None = de-novo from antibiotic pool
    n: int = 8
    pathogen: str = "MRSA"
    session_id: Optional[str] = None
    campaign_id: Optional[str] = None
    save: bool = True


@router.post("/generate")
async def generate(req: GenerateRequest) -> dict[str, Any]:
    """Generate n novel, valid, drug-like candidates (de-novo if no seed,
    lead-opt if seeded), scored + ranked. Real fragment chemistry, not LLM
    hallucination."""
    n = max(1, min(int(req.n), 24))
    if req.seed and _canonical(req.seed) is None:
        raise HTTPException(422, f"unparseable seed SMILES: {req.seed}")
    api_base = os.getenv("LYSOS_SELF_URL", "http://127.0.0.1:7860")
    run = await _run_generation(req.seed, n, req.pathogen, api_base)

    artifact_id = None
    if req.save:
        title = (f"Generate · {run['engine']} · {run['n_returned']} leads"
                 + (" (de-novo)" if not req.seed else " (lead-opt)"))
        rec = service_store.save_artifact(_ARTIFACT_KIND, run,
            session_id=req.session_id, smiles=req.seed, title=title)
        artifact_id = rec["id"]
    run["artifact_id"] = artifact_id

    # Feed the campaign — generated leads become campaign candidates.
    if req.campaign_id and run["candidates"]:
        try:
            from . import campaign as _camp
            for c in run["candidates"][:5]:
                _camp.attach_run  # noqa: B018 (ensure module import)
            # Add the top candidate as a campaign candidate via the store.
            rec = service_store.get_artifact(req.campaign_id)
            if rec and rec.get("kind") == "campaign":
                doc = rec["payload"]
                for c in run["candidates"]:
                    if not any(x["smiles"] == c["smiles"] for x in doc.get("candidates", [])):
                        doc.setdefault("candidates", []).append({
                            "smiles": c["smiles"],
                            "label": f"gen ({run['engine']})",
                            "source": "generate",
                            "added_at": time.time(),
                            "rollup": {"composite": c.get("composite")},
                        })
                if doc.get("status") == "scoping":
                    doc["status"] = "exploring"
                service_store.update_artifact(req.campaign_id, payload=doc)
        except Exception as exc:  # noqa: BLE001
            log.warning("campaign feed failed: %s", exc)

    return run


@router.get("/generate/runs")
async def list_runs(session_id: Optional[str] = None) -> dict[str, Any]:
    items = service_store.list_artifacts(kind=_ARTIFACT_KIND, session_id=session_id)
    return {"items": items}


@router.delete("/generate/runs/{rid}")
async def delete_run(rid: str) -> dict[str, Any]:
    return {"deleted": service_store.delete_artifact(rid)}
