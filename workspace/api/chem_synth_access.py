"""Synthesizability — real synthetic-accessibility scoring.

The synthesis service (chem_synthesis.py) plans a *route* with Gemini. This
module answers the orthogonal, quantitative question a chemist asks first:
**how hard is this to make at all?** — with REAL metrics, not an LLM guess.

Signals (all real, computed per-molecule):
  * **SAScore** (Ertl & Schuffenhauer, J Cheminform 2009) — the field-standard
    synthetic-accessibility score, 1 (easy) → 10 (hard). RDKit's reference
    implementation (fragment contributions + complexity penalties).
  * **AiZynthFinder cache override** — when the molecule is in our 1000-row
    AiZynth calibration cache (real MCTS retrosynthesis runs), we return the
    real route counts + AiZynth reward instead of an estimate.
  * **Structural-complexity breakdown** — rings, stereocentres, spiro,
    fused systems, macrocycle flag — the things that actually drive
    make-difficulty, so the score is explainable.

On MI300X the full AiZynthFinder engine (template-NN policy + MCTS) runs
behind the same contract for any molecule, not just the cache.

Mounted at /workbench/chem/synthesizability. Feeds the dossier `synthesis`
facet and the agent's synthesizability tool.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.synth_access")
router = APIRouter(prefix="/chem", tags=["synth_access"])

_ARTIFACT_KIND = "synthesizability"
_CACHE_PATH = (Path(__file__).resolve().parents[2] / "data" / "processed"
               / "aizynth_calibration_cache.parquet")


# ─────────────────────────────────────────────────────────────────────
# SAScore (RDKit reference implementation)
# ─────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _sascorer():
    """Import RDKit's SA_Score contrib once (it loads a fragment DB)."""
    import sys
    from rdkit.Chem import RDConfig
    sa_dir = os.path.join(RDConfig.RDContribDir, "SA_Score")
    if sa_dir not in sys.path:
        sys.path.append(sa_dir)
    import sascorer  # type: ignore
    return sascorer


def _canonical(smiles: str) -> Optional[str]:
    try:
        from rdkit import Chem
        m = Chem.MolFromSmiles((smiles or "").strip())
        if m is None or m.GetNumAtoms() == 0:
            return None
        return Chem.MolToSmiles(m)
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────
# AiZynth cache (real retrosynthesis runs) — exact-match override
# ─────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _aizynth_cache() -> dict[str, dict[str, Any]]:
    """canonical-SMILES → real AiZynth route stats. Empty if unavailable."""
    out: dict[str, dict[str, Any]] = {}
    try:
        import pandas as pd
        df = pd.read_parquet(_CACHE_PATH)
        for row in df.itertuples(index=False):
            c = _canonical(str(row.smiles))
            if c:
                out[c] = {
                    "n_routes_found": int(row.n_routes_found),
                    "n_solved_routes": int(row.n_solved_routes),
                    "best_route_score": float(row.best_route_score),
                    "aizynth_reward": float(row.synth_reward_aizynth),
                }
        log.info("AiZynth cache loaded — %d molecules", len(out))
    except Exception as exc:  # noqa: BLE001
        log.warning("AiZynth cache unavailable: %s", exc)
    return out


# ─────────────────────────────────────────────────────────────────────
# Complexity breakdown — explainable make-difficulty drivers
# ─────────────────────────────────────────────────────────────────────

def _complexity(smiles: str) -> dict[str, Any]:
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors
    m = Chem.MolFromSmiles(smiles)
    ri = m.GetRingInfo()
    n_rings = ri.NumRings()
    # Spiro + fused ring atoms.
    n_spiro = rdMolDescriptors.CalcNumSpiroAtoms(m)
    n_bridge = rdMolDescriptors.CalcNumBridgeheadAtoms(m)
    n_stereo = len(Chem.FindMolChiralCenters(m, useLegacyImplementation=False,
                                             includeUnassigned=True))
    # Macrocycle = any ring of size >= 12.
    macrocycle = any(len(r) >= 12 for r in ri.AtomRings())
    return {
        "mw": round(float(Descriptors.MolWt(m)), 1),
        "n_rings": n_rings,
        "n_aromatic_rings": int(rdMolDescriptors.CalcNumAromaticRings(m)),
        "n_stereocenters": n_stereo,
        "n_spiro_atoms": int(n_spiro),
        "n_bridgehead_atoms": int(n_bridge),
        "macrocycle": macrocycle,
        "fraction_csp3": round(float(rdMolDescriptors.CalcFractionCSP3(m)), 3),
    }


def _assess(smiles: str) -> dict[str, Any]:
    canon = _canonical(smiles)
    if canon is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")
    sa = float(_sascorer().calculateScore(__import__("rdkit").Chem.MolFromSmiles(canon)))
    cx = _complexity(canon)

    # SAScore → 0-1 ease (1 = easy). SAScore spans ~1-10; map linearly,
    # clamped. This is the headline synthesizability when no AiZynth route
    # is cached.
    ease = max(0.0, min(1.0, (10.0 - sa) / 9.0))
    band = ("easy" if sa <= 3.5 else "moderate" if sa <= 5.5
            else "hard" if sa <= 7.0 else "very hard")

    # AiZynth real-route override.
    cache = _aizynth_cache().get(canon)
    drivers = []
    if cx["n_stereocenters"] >= 4:
        drivers.append(f"{cx['n_stereocenters']} stereocentres")
    if cx["macrocycle"]:
        drivers.append("macrocycle")
    if cx["n_spiro_atoms"] > 0:
        drivers.append(f"{cx['n_spiro_atoms']} spiro atom(s)")
    if cx["n_bridgehead_atoms"] > 0:
        drivers.append(f"{cx['n_bridgehead_atoms']} bridgehead atom(s)")
    if cx["n_rings"] >= 4:
        drivers.append(f"{cx['n_rings']} rings")
    if cx["mw"] > 500:
        drivers.append(f"MW {cx['mw']:.0f}")

    return {
        "smiles": canon,
        "sa_score": round(sa, 2),
        "synth_ease": round(ease, 3),     # 0-1, higher = easier to make
        "band": band,
        "complexity": cx,
        "difficulty_drivers": drivers,
        "aizynth": cache,                 # real route stats if cached, else None
        "source": "aizynth-cache" if cache else "sascore",
        "note": ("SAScore (Ertl & Schuffenhauer 2009): 1=easy → 10=hard, the "
                 "field-standard synthetic-accessibility metric."
                 + (" Real AiZynthFinder retrosynthesis route stats available "
                    "for this molecule." if cache else "")),
    }


# ─────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────

class SynthAccessRequest(BaseModel):
    smiles: str
    session_id: Optional[str] = None
    save: bool = False


@router.get("/synthesizability")
async def synthesizability(smiles: str) -> dict[str, Any]:
    """Quantitative make-difficulty for a SMILES: SAScore + complexity
    breakdown + real AiZynth route stats when cached."""
    return _assess(smiles)


@router.post("/synthesizability")
async def synthesizability_post(req: SynthAccessRequest) -> dict[str, Any]:
    result = _assess(req.smiles)
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, result, session_id=req.session_id,
            smiles=result["smiles"],
            title=f"Synthesizability · SA {result['sa_score']} ({result['band']})")
        result["artifact_id"] = rec["id"]
    if req.session_id:
        try:
            from . import candidate_dossier as _dossier
            _dossier.upsert_facet(req.session_id, result["smiles"], "synthesis", {
                "sa_score": result["sa_score"],
                "synth_ease": result["synth_ease"],
                "synth_band": result["band"],
                "difficulty_drivers": result["difficulty_drivers"],
            })
        except Exception:  # noqa: BLE001
            pass
    return result
