"""3D Shape & Flexibility Explorer — the molecule's three-dimensional form.

2D structure and physchem miss a dimension that matters for membrane
permeation, target fit, and (for antibiotics) crossing the Gram-negative
outer membrane: 3D SHAPE and FLEXIBILITY. This service embeds a conformer
ensemble and places the molecule on the canonical PMI shape triangle
(rod ↔ disc ↔ sphere), with flexibility, radius of gyration, asphericity,
and globularity — all real RDKit 3D descriptors, no prediction.

How: RDKit ETKDGv3 embeds N conformers, MMFF-optimises them, and for each
we compute the normalised principal-moment ratios (NPR1=I1/I3, NPR2=I2/I3).
The spread of conformers across the triangle IS the flexibility. Rigid,
rod-like, flat molecules read very differently here — and Gram-negative
entry famously favours small, rigid, planar shapes.

Six-layer contract: service_store · this module · agent tool · workflow ·
orchestrator · frontend ShapeExplorerCard + dossier.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.shape")
router = APIRouter(prefix="/chem", tags=["shape"])

_ARTIFACT_KIND = "shape_profile"


def _classify(npr1: float, npr2: float) -> str:
    """Nearest PMI-triangle vertex: rod (0,1), disc (0.5,0.5), sphere (1,1)."""
    verts = {"rod-like": (0.0, 1.0), "disc-like": (0.5, 0.5), "spherical": (1.0, 1.0)}
    best, bd = "rod-like", 9.9
    for name, (x, y) in verts.items():
        d = (npr1 - x) ** 2 + (npr2 - y) ** 2
        if d < bd:
            bd, best = d, name
    return best


@lru_cache(maxsize=256)
def _profile(smiles: str, n_conf: int) -> dict[str, Any]:
    from rdkit import Chem
    from rdkit.Chem import AllChem, Descriptors3D
    import numpy as np

    mol = Chem.MolFromSmiles((smiles or "").strip())
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")
    canon = Chem.MolToSmiles(mol)
    m = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = 0xC0FFEE          # deterministic ensemble
    ids = list(AllChem.EmbedMultipleConfs(m, numConfs=n_conf, params=params))
    if not ids:
        # fall back to a single embed for awkward molecules
        if AllChem.EmbedMolecule(m, params) != 0:
            raise HTTPException(422, "could not generate a 3D conformer")
        ids = [0]
    energies: dict[int, float] = {}
    try:
        res = AllChem.MMFFOptimizeMoleculeConfs(m, maxIters=400)
        for cid, (_conv, e) in zip(ids, res):
            energies[cid] = float(e)
    except Exception:  # noqa: BLE001
        pass

    confs = []
    for cid in ids:
        try:
            npr1 = float(Descriptors3D.NPR1(m, confId=cid))
            npr2 = float(Descriptors3D.NPR2(m, confId=cid))
            rg = float(Descriptors3D.RadiusOfGyration(m, confId=cid))
            confs.append({"npr1": round(npr1, 3), "npr2": round(npr2, 3),
                          "rg": round(rg, 2), "energy": round(energies.get(cid, 0.0), 1),
                          "shape": _classify(npr1, npr2)})
        except Exception:  # noqa: BLE001
            continue
    if not confs:
        raise HTTPException(422, "no 3D descriptors computable")

    arr1 = np.array([c["npr1"] for c in confs])
    arr2 = np.array([c["npr2"] for c in confs])
    # the lowest-energy conformer is the representative
    rep = min(confs, key=lambda c: c["energy"])
    mean_npr1, mean_npr2 = float(arr1.mean()), float(arr2.mean())
    # flexibility = conformational spread on the triangle (0 rigid → 1 floppy)
    spread = float(np.sqrt(arr1.var() + arr2.var()))
    flexibility = round(min(1.0, spread * 4.0), 3)
    flex_band = ("rigid" if flexibility < 0.12 else
                 "moderate" if flexibility < 0.3 else "flexible")

    from rdkit.Chem import Descriptors3D as D3, Descriptors
    rep_cid = min(energies, key=energies.get) if energies else ids[0]
    try:
        asph = round(float(D3.Asphericity(m, confId=rep_cid)), 3)
        ecc = round(float(D3.Eccentricity(m, confId=rep_cid)), 3)
        spher = round(float(D3.SpherocityIndex(m, confId=rep_cid)), 3)
    except Exception:  # noqa: BLE001
        asph = ecc = spher = None

    return {
        "smiles": canon,
        "n_conformers": len(confs),
        "conformers": confs,
        "representative": rep,
        "mean_npr1": round(mean_npr1, 3), "mean_npr2": round(mean_npr2, 3),
        "shape_class": _classify(mean_npr1, mean_npr2),
        "flexibility": flexibility, "flexibility_band": flex_band,
        "rg": rep["rg"], "asphericity": asph, "eccentricity": ecc,
        "spherocity": spher,
        "rotatable_bonds": int(Descriptors.NumRotatableBonds(mol)),
        "fsp3": round(float(Descriptors.FractionCSP3(mol)), 3),
        "computed_at": time.time(),
        "engine": "RDKit ETKDGv3 conformer ensemble + 3D PMI descriptors",
        "note": ("Shape = normalised principal-moment ratios over an ETKDGv3 "
                 "ensemble; flexibility = the ensemble's spread on the triangle. "
                 "All real RDKit 3D descriptors. Gram-negative outer-membrane "
                 "entry favours small, rigid, planar (rod/disc) shapes."),
    }


class ShapeRequest(BaseModel):
    smiles: str
    n_conformers: int = 16
    session_id: Optional[str] = None
    save: bool = True


@router.post("/shape/profile")
async def shape_profile(req: ShapeRequest) -> dict[str, Any]:
    """Embed a conformer ensemble → PMI shape triangle, flexibility, and 3D
    descriptors for the candidate."""
    n = max(4, min(int(req.n_conformers), 40))
    result = _profile(req.smiles, n)
    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, result, session_id=req.session_id,
            smiles=result["smiles"],
            title=(f"Shape · {result['shape_class']} · {result['flexibility_band']}"))
        artifact_id = rec["id"]
    result["artifact_id"] = artifact_id

    if req.session_id:
        try:
            from . import candidate_dossier as _dossier
            _dossier.upsert_facet(req.session_id, result["smiles"], "shape", {
                "shape_class": result["shape_class"],
                "flexibility": result["flexibility"],
                "flexibility_band": result["flexibility_band"], "rg": result["rg"],
            })
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/shape/runs")
async def list_runs(session_id: Optional[str] = None) -> dict[str, Any]:
    return {"items": service_store.list_artifacts(kind=_ARTIFACT_KIND,
                                                  session_id=session_id)}
