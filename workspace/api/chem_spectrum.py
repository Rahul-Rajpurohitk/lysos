"""Spectrum Coverage Matrix — narrow or broad? Real per-pathogen binding.

Spectrum is the defining property of an antibiotic, and it is the ONE thing
the molecule-intrinsic composite score can't tell you (that score is the
same for every pathogen). So this docks the candidate into EACH of the eight
priority pathogens' validated targets and reports the predicted binding ΔG
per pathogen — a real, varying coverage signal — then classifies the agent
as narrow / moderate / broad-spectrum.

Honest: this is the same AutoDock-Vina scoring function used in the 3D
theater, run against each pathogen's primary validated target (the PDB the
platform already curates). Docking is rigid + seeded, so ΔG is a ranking
signal, not a kcal/mol oracle — and it is a binding proxy, not a measured MIC.
Runs the eight docks concurrently (~a few seconds); manual-triggered.

Six-layer contract: service_store · this module · agent tool · workflow ·
orchestrator · frontend SpectrumMatrixCard + dossier.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.spectrum")
router = APIRouter(prefix="/chem", tags=["spectrum"])

_ARTIFACT_KIND = "spectrum_matrix"
_COVERED_DG = -4.0          # affinity ≤ this (good/strong) counts as covered


def _primary_targets() -> list[dict[str, Any]]:
    """Each pathogen's primary validated target (pathogen, pdb, name)."""
    from .chem_3d import PATHOGEN_TARGETS
    out = []
    for pathogen, targets in PATHOGEN_TARGETS.items():
        if not targets:
            continue
        t = targets[0]
        out.append({"pathogen": pathogen, "pdb_id": t["pdb_id"],
                    "target": t.get("short_name") or t.get("name") or t["pdb_id"],
                    "target_full": t.get("name", "")})
    return out


def _dock_one(smiles: str, pdb_id: str) -> Optional[dict[str, Any]]:
    """Run one rigid dock (sync) — returns affinity + band, or None on failure."""
    try:
        from .chem_dock import _dock
        r = _dock(smiles, pdb_id, False)
        return {"affinity_kcal_mol": r.get("affinity_kcal_mol"),
                "band": r.get("affinity_band"),
                "n_interactions": r.get("n_interactions"),
                "engine": r.get("engine")}
    except Exception as exc:  # noqa: BLE001
        log.warning("spectrum dock failed for %s: %s", pdb_id, exc)
        return None


async def _run_spectrum(smiles: str) -> dict[str, Any]:
    from rdkit import Chem
    m = Chem.MolFromSmiles((smiles or "").strip())
    if m is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")
    canon = Chem.MolToSmiles(m)

    t0 = time.time()
    targets = _primary_targets()
    # Dock all pathogens concurrently (threads — the dock is NumPy-heavy).
    results = await asyncio.gather(
        *[asyncio.to_thread(_dock_one, canon, t["pdb_id"]) for t in targets])

    rows = []
    for t, r in zip(targets, results):
        dg = r.get("affinity_kcal_mol") if r else None
        band = r.get("band") if r else None
        covered = dg is not None and dg <= _COVERED_DG
        rows.append({
            "pathogen": t["pathogen"], "target": t["target"],
            "target_full": t["target_full"], "pdb_id": t["pdb_id"],
            "affinity_kcal_mol": dg, "band": band,
            "n_interactions": r.get("n_interactions") if r else None,
            "covered": covered,
        })
    # Best (most negative) first → the spectrum reads strongest-coverage-down.
    rows.sort(key=lambda x: (x["affinity_kcal_mol"] if x["affinity_kcal_mol"]
                             is not None else 0.0))
    scored = [x for x in rows if x["affinity_kcal_mol"] is not None]
    n_cov = sum(1 for x in rows if x["covered"])
    n_tot = len(rows)
    spectrum = ("broad" if n_cov >= max(6, n_tot - 1) else
                "moderate" if n_cov >= 3 else
                "narrow" if n_cov >= 1 else "no-coverage")
    best = scored[0] if scored else None
    mean_dg = round(sum(x["affinity_kcal_mol"] for x in scored) / len(scored), 2) \
        if scored else None

    return {
        "smiles": canon, "rows": rows,
        "n_covered": n_cov, "n_pathogens": n_tot,
        "spectrum": spectrum, "best": best, "mean_affinity": mean_dg,
        "covered_threshold": _COVERED_DG,
        "elapsed_s": round(time.time() - t0, 2),
        "computed_at": time.time(),
        "engine": "AutoDock-Vina scoring fn · per-pathogen validated target",
        "note": ("Each cell is a real rigid dock of the candidate into that "
                 "pathogen's primary validated target — a binding-coverage "
                 "ranking signal, not a measured MIC. Covered = ΔG ≤ "
                 f"{_COVERED_DG} kcal/mol."),
    }


class SpectrumRequest(BaseModel):
    smiles: str
    session_id: Optional[str] = None
    save: bool = True


@router.post("/spectrum/run")
async def spectrum_run(req: SpectrumRequest) -> dict[str, Any]:
    """Dock the candidate into all 8 priority-pathogen targets → spectrum
    coverage matrix + narrow/broad classification."""
    result = await _run_spectrum(req.smiles)
    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, result, session_id=req.session_id,
            smiles=result["smiles"],
            title=(f"Spectrum · {result['spectrum']} · "
                   f"{result['n_covered']}/{result['n_pathogens']}"))
        artifact_id = rec["id"]
    result["artifact_id"] = artifact_id

    if req.session_id:
        try:
            from . import candidate_dossier as _dossier
            _dossier.upsert_facet(req.session_id, result["smiles"], "spectrum", {
                "spectrum": result["spectrum"], "n_covered": result["n_covered"],
                "n_pathogens": result["n_pathogens"],
                "best_pathogen": result["best"]["pathogen"] if result["best"] else None,
            })
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/spectrum/targets")
async def spectrum_targets() -> dict[str, Any]:
    """The per-pathogen primary targets the spectrum docks against."""
    t = _primary_targets()
    return {"n_pathogens": len(t), "targets": t}


@router.get("/spectrum/runs")
async def list_runs(session_id: Optional[str] = None) -> dict[str, Any]:
    return {"items": service_store.list_artifacts(kind=_ARTIFACT_KIND,
                                                  session_id=session_id)}
