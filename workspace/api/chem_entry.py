"""Gram-Negative Entry Predictor — will it even get INTO the bug?

The single biggest reason antibiotics fail against Gram-negatives (E. coli,
Klebsiella, Acinetobacter, Pseudomonas — four of our eight priority
pathogens) is the outer membrane: most molecules simply never accumulate
inside. Richter & Hergenrother (Nature 2017) distilled the predictive
"eNTRy rules" from a large accumulation screen:

  N — an ionizable NITROGEN (a primary amine is the strongest signal)
  T — low globularity (Three-dimensional flatness): glob ≤ 0.25
  R — RIGIDITY: rotatable bonds ≤ 5

Compounds satisfying all three tend to accumulate in E. coli. This service
computes each criterion (real RDKit: amine SMARTS, a PMI-based globularity
proxy from a 3D conformer, rotatable-bond count) and returns a pass/fail
checklist + an entry verdict, flagging which Gram-negative targets are
gated by permeability.

Honest: globularity here is a PMI proxy (I1/I3) of the published surface-
area definition, and the rules are a screen-derived heuristic, not a
guarantee — but they are the field-standard first filter for Gram-negative
campaigns. Six-layer contract: service_store · module · agent tool ·
workflow · orchestrator · frontend GramEntryCard + dossier.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.entry")
router = APIRouter(prefix="/chem", tags=["entry"])

_ARTIFACT_KIND = "gram_entry"
_GLOB_MAX = 0.25
_ROT_MAX = 5
# The Gram-negative members of our priority panel (entry-gated).
_GRAM_NEG = ["EColi-CRE", "KpneuCRE", "Abaum", "Paer"]


@lru_cache(maxsize=256)
def _entry(smiles: str) -> dict[str, Any]:
    from rdkit import Chem
    from rdkit.Chem import AllChem, Descriptors, Descriptors3D

    mol = Chem.MolFromSmiles((smiles or "").strip())
    if mol is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")
    canon = Chem.MolToSmiles(mol)

    # N — ionizable nitrogen. Primary amine is the strongest eNTRy signal;
    # other basic amines count for partial credit.
    prim_amine = mol.HasSubstructMatch(Chem.MolFromSmarts("[NX3;H2;!$(NC=O);!$(N=*)]"))
    basic_amine = mol.HasSubstructMatch(
        Chem.MolFromSmarts("[NX3;!$(NC=O);!$(N=*);!$(n)]"))
    has_n = prim_amine or basic_amine

    # R — rotatable bonds.
    rot = int(Descriptors.NumRotatableBonds(mol))

    # T — globularity proxy: NPR1 (I1/I3) of a single ETKDG conformer.
    glob: Optional[float] = None
    try:
        m3 = Chem.AddHs(mol)
        p = AllChem.ETKDGv3(); p.randomSeed = 0xC0FFEE
        if AllChem.EmbedMolecule(m3, p) == 0:
            AllChem.MMFFOptimizeMolecule(m3, maxIters=300)
            glob = round(float(Descriptors3D.NPR1(m3)), 3)
    except Exception:  # noqa: BLE001
        glob = None

    crit = [
        {"key": "N", "label": "Ionizable nitrogen",
         "pass": bool(has_n),
         "detail": ("primary amine" if prim_amine else
                    "basic amine (weaker)" if basic_amine else "none — add a primary amine"),
         "weight": 0.5},
        {"key": "T", "label": "Low globularity (flat)",
         "pass": bool(glob is not None and glob <= _GLOB_MAX),
         "detail": (f"glob {glob} (≤ {_GLOB_MAX})" if glob is not None else "3D failed"),
         "weight": 0.25},
        {"key": "R", "label": "Rigidity (few rot. bonds)",
         "pass": bool(rot <= _ROT_MAX),
         "detail": f"{rot} rotatable (≤ {_ROT_MAX})",
         "weight": 0.25},
    ]
    n_pass = sum(1 for c in crit if c["pass"])
    # entry score: primary-amine-weighted; all three → likely accumulator
    score = 0.0
    score += (0.5 if prim_amine else 0.25 if basic_amine else 0.0)
    score += 0.25 if (glob is not None and glob <= _GLOB_MAX) else 0.0
    score += 0.25 if rot <= _ROT_MAX else 0.0
    score = round(score, 3)
    band = ("likely-accumulator" if (prim_amine and n_pass == 3) else
            "borderline" if n_pass >= 2 else "unlikely")

    # actionable guidance
    tips = []
    if not has_n:
        tips.append("Install a primary amine — the dominant eNTRy predictor.")
    elif not prim_amine:
        tips.append("Upgrade the basic amine to a primary amine for stronger entry.")
    if glob is not None and glob > _GLOB_MAX:
        tips.append(f"Flatten the scaffold (globularity {glob} > {_GLOB_MAX}) — add rigidity / aromatic character.")
    if rot > _ROT_MAX:
        tips.append(f"Reduce rotatable bonds ({rot} > {_ROT_MAX}) — ring-fuse or shorten chains.")
    if not tips:
        tips.append("Meets all three eNTRy rules — good Gram-negative entry profile.")

    return {
        "smiles": canon,
        "criteria": crit, "n_pass": n_pass,
        "entry_score": score, "band": band,
        "has_primary_amine": prim_amine, "globularity": glob,
        "rotatable_bonds": rot,
        "gram_negative_targets": _GRAM_NEG,
        "gated": band != "likely-accumulator",
        "tips": tips,
        "computed_at": time.time(),
        "engine": "eNTRy rules (Richter & Hergenrother, Nature 2017) — RDKit descriptors",
        "note": ("eNTRy: ionizable Nitrogen + low globularity (Three-D flat) + "
                 "Rigidity → Gram-negative accumulation. Globularity is a PMI "
                 "proxy (I1/I3); rules are a screen-derived heuristic, the "
                 "field-standard first filter for Gram-negative entry."),
    }


class EntryRequest(BaseModel):
    smiles: str
    session_id: Optional[str] = None
    save: bool = True


@router.post("/entry/predict")
async def entry_predict(req: EntryRequest) -> dict[str, Any]:
    """Score the candidate against the eNTRy rules → Gram-negative entry
    likelihood + per-criterion checklist + fixes."""
    result = _entry(req.smiles)
    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, result, session_id=req.session_id,
            smiles=result["smiles"],
            title=f"Gram-entry · {result['band']} · {result['n_pass']}/3")
        artifact_id = rec["id"]
    result["artifact_id"] = artifact_id

    if req.session_id:
        try:
            from . import candidate_dossier as _dossier
            _dossier.upsert_facet(req.session_id, result["smiles"], "entry", {
                "entry_score": result["entry_score"], "band": result["band"],
                "n_pass": result["n_pass"],
                "has_primary_amine": result["has_primary_amine"],
            })
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/entry/runs")
async def list_runs(session_id: Optional[str] = None) -> dict[str, Any]:
    return {"items": service_store.list_artifacts(kind=_ARTIFACT_KIND,
                                                  session_id=session_id)}
