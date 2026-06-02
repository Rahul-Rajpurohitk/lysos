"""Property-Space Dashboard — is this molecule shaped like an antibiotic?

Instead of a table of numbers, this places the candidate's physicochemical
descriptors ON the real distributions of 30,000+ known antibiotics. For
every property you see the antibiotic histogram, the candidate's position,
its percentile within antibiotic space, and the classical drug-like bound
(which antibiotics famously exceed — so the antibiotic distribution is the
honest reference, not Ro5 alone).

All real: RDKit descriptors for the candidate, empirical distributions from
the curated known-antibiotics dataset (precomputed once, cached). No model,
no prediction — just where the molecule sits in real chemical property space.

Six-layer contract: service_store · this module · agent tool · workflow ·
orchestrator · frontend PropertySpaceCard + dossier.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.propspace")
router = APIRouter(prefix="/chem", tags=["propspace"])

_ARTIFACT_KIND = "propspace_profile"
_PARQUET = (Path(__file__).resolve().parents[2] / "data" / "processed"
            / "known-antibiotics-canonical.parquet")

# Each property: dataset column, label, RDKit getter, classical drug-like
# bound (lo, hi) for the reference band, n histogram bins, and whether higher
# is better (for the verdict). Bounds are Lipinski/Veber/lead-like references.
_PROPS: list[dict[str, Any]] = [
    {"key": "mw", "label": "Mol. weight", "unit": "Da", "lo": 150, "hi": 500,
     "bins": 40, "clip": (0, 900)},
    {"key": "logp", "label": "cLogP", "unit": "", "lo": -1, "hi": 5,
     "bins": 40, "clip": (-6, 10)},
    {"key": "tpsa", "label": "TPSA", "unit": "Å²", "lo": 20, "hi": 140,
     "bins": 40, "clip": (0, 300)},
    {"key": "hbd", "label": "H-bond donors", "unit": "", "lo": 0, "hi": 5,
     "bins": 16, "clip": (0, 16)},
    {"key": "hba", "label": "H-bond acceptors", "unit": "", "lo": 0, "hi": 10,
     "bins": 22, "clip": (0, 22)},
    {"key": "rotatable_bonds", "label": "Rotatable bonds", "unit": "", "lo": 0,
     "hi": 10, "bins": 22, "clip": (0, 22)},
    {"key": "ring_count", "label": "Rings", "unit": "", "lo": 1, "hi": 5,
     "bins": 12, "clip": (0, 12)},
    {"key": "qed", "label": "QED", "unit": "", "lo": 0.5, "hi": 1.0,
     "bins": 40, "clip": (0, 1)},
]


@lru_cache(maxsize=1)
def _distributions() -> dict[str, Any]:
    """Precompute the antibiotic property histograms + sorted arrays (for
    percentiles) once. Cached for the process lifetime."""
    import pandas as pd
    if not _PARQUET.exists():
        raise HTTPException(503, f"property dataset not found at {_PARQUET}")
    df = pd.read_parquet(_PARQUET, columns=[p["key"] for p in _PROPS])
    out: dict[str, Any] = {"n": int(len(df)), "props": {}}
    for p in _PROPS:
        col = pd.to_numeric(df[p["key"]], errors="coerce").dropna().to_numpy()
        lo_c, hi_c = p["clip"]
        col = col[(col >= lo_c) & (col <= hi_c)]
        if col.size == 0:
            continue
        counts, edges = np.histogram(col, bins=p["bins"], range=(lo_c, hi_c))
        out["props"][p["key"]] = {
            "counts": counts.astype(int).tolist(),
            "edges": [round(float(e), 2) for e in edges],
            "sorted": np.sort(col),          # for percentile (kept in-memory)
            "median": round(float(np.median(col)), 2),
            "p10": round(float(np.percentile(col, 10)), 2),
            "p90": round(float(np.percentile(col, 90)), 2),
        }
    log.info("Property-space: distributions for %d antibiotics across %d props",
             out["n"], len(out["props"]))
    return out


def _candidate_descriptors(smiles: str) -> dict[str, float]:
    from rdkit import Chem
    from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors
    m = Chem.MolFromSmiles((smiles or "").strip())
    if m is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")
    return {
        "mw": round(Descriptors.MolWt(m), 1),
        "logp": round(Crippen.MolLogP(m), 2),
        "tpsa": round(Descriptors.TPSA(m), 1),
        "hbd": float(Descriptors.NumHDonors(m)),
        "hba": float(Descriptors.NumHAcceptors(m)),
        "rotatable_bonds": float(Descriptors.NumRotatableBonds(m)),
        "ring_count": float(rdMolDescriptors.CalcNumRings(m)),
        "qed": round(float(Descriptors.qed(m)), 3),
    }


def _percentile(sorted_arr: np.ndarray, v: float) -> float:
    if sorted_arr.size == 0:
        return 0.0
    idx = int(np.searchsorted(sorted_arr, v, side="right"))
    return round(100.0 * idx / sorted_arr.size, 1)


def _profile(smiles: str) -> dict[str, Any]:
    from rdkit import Chem
    dist = _distributions()
    desc = _candidate_descriptors(smiles)
    canon = Chem.MolToSmiles(Chem.MolFromSmiles(smiles.strip()))

    props_out = []
    in_band = 0
    for p in _PROPS:
        d = dist["props"].get(p["key"])
        if d is None:
            continue
        v = desc[p["key"]]
        pct = _percentile(d["sorted"], v)
        within = p["lo"] <= v <= p["hi"]
        if within:
            in_band += 1
        # which histogram bin does the candidate fall in?
        edges = d["edges"]
        cand_bin = max(0, min(len(edges) - 2,
                              int(np.searchsorted(edges, v, side="right") - 1)))
        props_out.append({
            "key": p["key"], "label": p["label"], "unit": p["unit"],
            "value": v, "percentile": pct,
            "drug_like_lo": p["lo"], "drug_like_hi": p["hi"], "within": within,
            "median": d["median"], "p10": d["p10"], "p90": d["p90"],
            "counts": d["counts"], "edges": d["edges"], "cand_bin": cand_bin,
        })

    n = len(props_out)
    typicality = round(in_band / n, 2) if n else 0.0
    band = ("antibiotic-like" if typicality >= 0.75 else
            "atypical" if typicality >= 0.5 else "outlier")
    return {
        "smiles": canon, "descriptors": desc,
        "n_reference": dist["n"],
        "properties": props_out,
        "in_band": in_band, "n_props": n,
        "typicality": typicality, "band": band,
        "engine": "RDKit descriptors vs empirical known-antibiotic distributions",
        "note": ("The reference is the distribution of 30k+ known antibiotics, "
                 "not Ro5 alone — antibiotics frequently exceed classical "
                 "drug-like bounds, so percentile-in-antibiotic-space is the "
                 "honest read. Drug-like bands shown for reference."),
    }


class ProfileRequest(BaseModel):
    smiles: str
    session_id: Optional[str] = None
    save: bool = True


@router.post("/propspace/profile")
async def propspace_profile(req: ProfileRequest) -> dict[str, Any]:
    """Where the candidate sits in known-antibiotic property space —
    per-property distributions, percentiles, and a typicality verdict."""
    result = _profile(req.smiles)
    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, {k: v for k, v in result.items()},
            session_id=req.session_id, smiles=result["smiles"],
            title=f"Prop-space · {result['band']} · {result['in_band']}/{result['n_props']}")
        artifact_id = rec["id"]
    result["artifact_id"] = artifact_id

    if req.session_id:
        try:
            from . import candidate_dossier as _dossier
            _dossier.upsert_facet(req.session_id, result["smiles"], "propspace", {
                "typicality": result["typicality"], "band": result["band"],
                "in_band": result["in_band"], "n_props": result["n_props"],
            })
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/propspace/distributions")
async def propspace_distributions() -> dict[str, Any]:
    """The precomputed antibiotic property histograms (no candidate)."""
    dist = _distributions()
    return {"n_reference": dist["n"], "properties": [
        {"key": p["key"], "label": p["label"], "unit": p["unit"],
         "drug_like_lo": p["lo"], "drug_like_hi": p["hi"],
         "counts": dist["props"][p["key"]]["counts"],
         "edges": dist["props"][p["key"]]["edges"],
         "median": dist["props"][p["key"]]["median"]}
        for p in _PROPS if p["key"] in dist["props"]]}


@router.get("/propspace/runs")
async def list_runs(session_id: Optional[str] = None) -> dict[str, Any]:
    return {"items": service_store.list_artifacts(kind=_ARTIFACT_KIND,
                                                  session_id=session_id)}
