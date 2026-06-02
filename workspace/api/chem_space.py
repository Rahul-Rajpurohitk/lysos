"""Chemical-Space Navigator — where does this molecule sit, and is it novel?

A medicinal chemist's orientation tool: project the candidate into the
chemical space of known antibiotics, see its nearest marketed neighbours,
and read a novelty score. Answers two questions a binding score can't:
  · "What does my molecule look like?" → nearest known antibiotic + class
  · "Is it a fresh chemotype or a me-too?" → novelty = 1 − max Tanimoto

All real cheminformatics, all local:
  1. A curated, RDKit-VALIDATED reference set of marketed antibiotics
     (each SMILES is parsed at import; anything that fails to parse is
     dropped, so nothing fake ever ships into the map).
  2. Morgan (ECFP4) fingerprints for the candidate + every reference.
  3. 2-D projection by PCA (NumPy SVD) on the bit matrix — deterministic,
     no random seed, labelled as a projection (distances are approximate;
     the exact metric is Tanimoto, reported separately).
  4. Nearest neighbours by exact Tanimoto; novelty = 1 − max similarity.

Six-layer contract: service_store · this module · agent tool · workflow ·
orchestrator · frontend ChemicalSpaceCard + dossier.
"""
from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.space")
router = APIRouter(prefix="/chem", tags=["space"])

_ARTIFACT_KIND = "space_map"
_SELF = os.getenv("LYSOS_SELF_URL", "http://127.0.0.1:7860")

# ─────────────────────────────────────────────────────────────────────
# Curated reference antibiotics. Every SMILES is validated at import; any
# that fails to parse is dropped (logged), so the map only ever contains
# real, canonicalizable structures. Spread across the major MOA classes.
# ─────────────────────────────────────────────────────────────────────

_REFERENCE_RAW: list[dict[str, str]] = [
    # β-lactams
    {"name": "Penicillin G", "klass": "β-lactam",
     "smiles": "CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O"},
    {"name": "Amoxicillin", "klass": "β-lactam",
     "smiles": "CC1(C)S[C@@H]2[C@H](NC(=O)[C@H](N)c3ccc(O)cc3)C(=O)N2[C@H]1C(=O)O"},
    {"name": "Ampicillin", "klass": "β-lactam",
     "smiles": "CC1(C)S[C@@H]2[C@H](NC(=O)[C@H](N)c3ccccc3)C(=O)N2[C@H]1C(=O)O"},
    {"name": "Cephalexin", "klass": "β-lactam",
     "smiles": "CC1=C(C(=O)O)N2C(=O)[C@@H](NC(=O)[C@H](N)c3ccccc3)[C@H]2SC1"},
    {"name": "Meropenem", "klass": "β-lactam",
     "smiles": "C[C@@H]1[C@@H]2[C@H](C(=O)N2C(=C1S[C@@H]1CN[C@H](C1)C(=O)N(C)C)C(=O)O)[C@@H](C)O"},
    # fluoroquinolones
    {"name": "Ciprofloxacin", "klass": "fluoroquinolone",
     "smiles": "O=C(O)c1cn(C2CC2)c3cc(N4CCNCC4)c(F)cc3c1=O"},
    {"name": "Levofloxacin", "klass": "fluoroquinolone",
     "smiles": "CC1COc2c(N3CCN(C)CC3)c(F)cc3c(=O)c(C(=O)O)cn1c23"},
    {"name": "Norfloxacin", "klass": "fluoroquinolone",
     "smiles": "CCn1cc(C(=O)O)c(=O)c2cc(F)c(N3CCNCC3)cc21"},
    # tetracyclines
    {"name": "Tetracycline", "klass": "tetracycline",
     "smiles": "CN(C)C1C(=O)C(C(N)=O)=C(O)C2(O)C(=O)C3=C(O)c4c(O)cccc4C(C)(O)C3CC12O"},
    {"name": "Doxycycline", "klass": "tetracycline",
     "smiles": "CC1c2cccc(O)c2C(=O)C2=C(O)C3(O)C(=O)C(C(N)=O)=C(O)C(N(C)C)C3C(O)C12O"},
    # sulfonamides / DHFR
    {"name": "Sulfamethoxazole", "klass": "sulfonamide",
     "smiles": "Cc1cc(NS(=O)(=O)c2ccc(N)cc2)no1"},
    {"name": "Sulfadiazine", "klass": "sulfonamide",
     "smiles": "Nc1ccc(S(=O)(=O)Nc2ncccn2)cc1"},
    {"name": "Trimethoprim", "klass": "DHFR inhibitor",
     "smiles": "COc1cc(Cc2cnc(N)nc2N)cc(OC)c1OC"},
    # oxazolidinone
    {"name": "Linezolid", "klass": "oxazolidinone",
     "smiles": "CC(=O)NC[C@H]1CN(c2ccc(N3CCOCC3)c(F)c2)C(=O)O1"},
    # nitro drugs
    {"name": "Metronidazole", "klass": "nitroimidazole",
     "smiles": "Cc1ncc([N+](=O)[O-])n1CCO"},
    {"name": "Nitrofurantoin", "klass": "nitrofuran",
     "smiles": "O=C1CN(/N=C/c2ccc([N+](=O)[O-])o2)C(=O)N1"},
    # amphenicol
    {"name": "Chloramphenicol", "klass": "amphenicol",
     "smiles": "OC[C@@H](NC(=O)C(Cl)Cl)[C@H](O)c1ccc([N+](=O)[O-])cc1"},
    # anti-mycobacterials
    {"name": "Isoniazid", "klass": "anti-mycobacterial",
     "smiles": "NNC(=O)c1ccncc1"},
    {"name": "Pyrazinamide", "klass": "anti-mycobacterial",
     "smiles": "NC(=O)c1cnccn1"},
    {"name": "Ethambutol", "klass": "anti-mycobacterial",
     "smiles": "CC[C@@H](CO)NCCN[C@@H](CC)CO"},
    # macrolide (medium)
    {"name": "Clarithromycin", "klass": "macrolide",
     "smiles": "CC[C@H]1OC(=O)[C@H](C)[C@@H](O[C@H]2C[C@@](C)(OC)[C@@H](O)[C@H](C)O2)[C@H](C)[C@@H](O[C@@H]2O[C@H](C)C[C@@H](N(C)C)[C@H]2O)[C@](C)(OC)C[C@@H](C)C(=O)[C@H](C)[C@@H](O)[C@]1(C)O"},
    # phosphonic / others
    {"name": "Fosfomycin", "klass": "phosphonic acid",
     "smiles": "C[C@H]1O[C@@H]1P(=O)(O)O"},
    {"name": "Rifaximin-core", "klass": "ansamycin",
     "smiles": "CC1C=CC=C(C)C(=O)NC2=C(O)C3=C(O)C(C)=C4OC(C)(C=CC(OC(C)=O)C(C)C(O)C(C)C(O)C(C)C(O)C1C)Oc4c3C(=O)C2=O"},
]


@lru_cache(maxsize=1)
def _reference() -> list[dict[str, Any]]:
    """Validate + fingerprint the reference set once. Drops unparseable
    entries so the map only contains real structures."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    out: list[dict[str, Any]] = []
    dropped = []
    for r in _REFERENCE_RAW:
        m = Chem.MolFromSmiles(r["smiles"].strip())
        if m is None:
            dropped.append(r["name"])
            continue
        fp = AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048)
        out.append({"name": r["name"], "klass": r["klass"],
                    "smiles": Chem.MolToSmiles(m), "_fp": fp})
    if dropped:
        log.info("Chem-space reference: dropped %d unparseable (%s)",
                 len(dropped), ", ".join(dropped))
    log.info("Chem-space reference: %d validated antibiotics", len(out))
    return out


def _fp(smiles: str):
    from rdkit import Chem
    from rdkit.Chem import AllChem
    m = Chem.MolFromSmiles((smiles or "").strip())
    if m is None:
        return None, None
    return AllChem.GetMorganFingerprintAsBitVect(m, 2, nBits=2048), Chem.MolToSmiles(m)


def _bits_to_array(fp) -> np.ndarray:
    from rdkit.DataStructs import ConvertToNumpyArray
    arr = np.zeros((fp.GetNumBits(),), dtype=np.float64)
    ConvertToNumpyArray(fp, arr)
    return arr


def _pca_2d(mat: np.ndarray) -> np.ndarray:
    """Deterministic 2-D PCA via SVD on a mean-centred bit matrix."""
    if mat.shape[0] < 2:
        return np.zeros((mat.shape[0], 2))
    centred = mat - mat.mean(axis=0, keepdims=True)
    # economy SVD; columns of Vt are principal directions
    try:
        _u, _s, vt = np.linalg.svd(centred, full_matrices=False)
    except np.linalg.LinAlgError:
        return np.zeros((mat.shape[0], 2))
    comps = vt[:2].T                       # (nbits, 2)
    proj = centred @ comps                 # (n, 2)
    # normalise to a friendly [-1, 1] box for the UI
    mx = np.abs(proj).max(axis=0, keepdims=True)
    mx[mx == 0] = 1.0
    return proj / mx


def _build_map(query_smiles: list[str], pathogen: str) -> dict[str, Any]:
    from rdkit import DataStructs
    t0 = time.time()
    ref = _reference()
    ref_fps = [r["_fp"] for r in ref]

    queries: list[dict[str, Any]] = []
    seen = set()
    for s in query_smiles:
        fp, canon = _fp(s)
        if fp is None or canon in seen:
            continue
        seen.add(canon)
        sims = DataStructs.BulkTanimotoSimilarity(fp, ref_fps)
        order = sorted(range(len(ref)), key=lambda i: sims[i], reverse=True)
        neighbours = [{"name": ref[i]["name"], "klass": ref[i]["klass"],
                       "tanimoto": round(float(sims[i]), 3)} for i in order[:3]]
        max_sim = float(max(sims)) if sims else 0.0
        queries.append({
            "smiles": canon, "_fp": fp,
            "nearest": neighbours,
            "novelty": round(1.0 - max_sim, 3),
            "novelty_band": ("novel" if max_sim < 0.4 else
                             "analogue" if max_sim < 0.7 else "me-too"),
        })
    if not queries:
        raise HTTPException(422, "no parseable candidate SMILES")

    # Stack candidate + reference fingerprints → one PCA projection.
    all_fps = [q["_fp"] for q in queries] + ref_fps
    mat = np.vstack([_bits_to_array(fp) for fp in all_fps])
    coords = _pca_2d(mat)
    nq = len(queries)

    points = []
    for i, q in enumerate(queries):
        points.append({"kind": "candidate", "label": "candidate",
                       "smiles": q["smiles"],
                       "x": round(float(coords[i, 0]), 4),
                       "y": round(float(coords[i, 1]), 4),
                       "novelty": q["novelty"], "novelty_band": q["novelty_band"],
                       "nearest": q["nearest"]})
    for j, r in enumerate(ref):
        c = coords[nq + j]
        points.append({"kind": "reference", "label": r["name"],
                       "klass": r["klass"], "smiles": r["smiles"],
                       "x": round(float(c[0]), 4), "y": round(float(c[1]), 4)})

    classes = sorted({r["klass"] for r in ref})
    primary = queries[0]
    return {
        "pathogen": pathogen,
        "n_reference": len(ref), "n_candidates": nq,
        "classes": classes,
        "points": points,
        "primary_novelty": primary["novelty"],
        "primary_novelty_band": primary["novelty_band"],
        "primary_nearest": primary["nearest"],
        "elapsed_s": round(time.time() - t0, 3),
        "computed_at": time.time(),
        "engine": "Morgan ECFP4 + PCA(SVD) projection · Tanimoto NN",
        "note": ("2-D layout is a PCA projection of ECFP4 bit vectors — "
                 "distances are approximate. Novelty and nearest-neighbour "
                 "use exact Tanimoto on the same fingerprints."),
    }


class MapRequest(BaseModel):
    smiles: str
    pathogen: str = "MRSA"
    extra_smiles: Optional[list[str]] = None   # compare several at once
    session_id: Optional[str] = None
    save: bool = True


@router.post("/space/map")
async def space_map(req: MapRequest) -> dict[str, Any]:
    """Project the candidate (+ any extras) into known-antibiotic chemical
    space → interactive map points, nearest neighbours, novelty."""
    qs = [req.smiles] + (req.extra_smiles or [])
    result = _build_map(qs, req.pathogen)
    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, result, session_id=req.session_id,
            smiles=result["points"][0]["smiles"],
            title=(f"Chem-space · novelty {result['primary_novelty']} · "
                   f"{result['primary_novelty_band']}"))
        artifact_id = rec["id"]
    result["artifact_id"] = artifact_id

    if req.session_id:
        try:
            from . import candidate_dossier as _dossier
            _dossier.upsert_facet(req.session_id, result["points"][0]["smiles"],
                                  "space", {
                "novelty": result["primary_novelty"],
                "band": result["primary_novelty_band"],
                "nearest": result["primary_nearest"][0]["name"]
                          if result["primary_nearest"] else None,
            })
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/space/reference")
async def space_reference() -> dict[str, Any]:
    """The validated reference antibiotic set (names + classes)."""
    ref = _reference()
    return {"n_reference": len(ref),
            "classes": sorted({r["klass"] for r in ref}),
            "antibiotics": [{"name": r["name"], "klass": r["klass"],
                             "smiles": r["smiles"]} for r in ref]}


@router.get("/space/runs")
async def list_runs(session_id: Optional[str] = None) -> dict[str, Any]:
    return {"items": service_store.list_artifacts(kind=_ARTIFACT_KIND,
                                                  session_id=session_id)}
