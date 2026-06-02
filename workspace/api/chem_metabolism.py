"""Metabolic Soft-Spot Scanner — where will this molecule get chewed up?

Metabolic lability is a top reason leads fail: a fast-cleared molecule never
reaches the bug. This flags the labile sites — N-/O-dealkylation, aromatic
and benzylic oxidation, ester/amide hydrolysis, S-oxidation, ω-oxidation,
glucuronidation handles — directly on the structure, each with the enzyme
pathway and the standard medicinal-chemistry mitigation.

Honesty: this is a TRANSPARENT rule-based site-of-metabolism flagger (a
curated SMARTS library of well-known labile motifs), not a trained kinetic
model — it tells you WHERE to look and HOW to fix it, with the matched atoms
highlighted. It pairs with the Bioisostere Studio (which makes the fix).

Six-layer contract: service_store · this module · agent tool · workflow ·
orchestrator · frontend MetabolismCard + dossier.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import service_store

log = logging.getLogger("lysos.metabolism")
router = APIRouter(prefix="/chem", tags=["metabolism"])

_ARTIFACT_KIND = "metabolism_scan"

# Curated labile-motif library. severity 1-3 (3 = fastest-cleared liability).
# `mark` is the atom in the SMARTS match to highlight (index into the match).
_RULES: list[dict[str, Any]] = [
    {"id": "n_dealkyl", "label": "N-dealkylation", "smarts": "[NX3;!$(N=*)][CH3,CH2]",
     "pathway": "CYP3A4/2D6 oxidative N-dealkylation", "severity": 2, "mark": 1,
     "fix": "Cap or branch the N-alkyl (e.g. N-CH3→N-cyclopropyl), or add α-F."},
    {"id": "o_dealkyl", "label": "O-dealkylation", "smarts": "[OX2]([CH3,CH2])[#6]",
     "pathway": "CYP O-dealkylation (esp. methoxy)", "severity": 2, "mark": 1,
     "fix": "Replace OMe→OCHF2/OCF3, or ether→bioisostere."},
    {"id": "aryl_oh", "label": "aromatic hydroxylation", "smarts": "[cH1]",
     "pathway": "CYP aromatic ring oxidation (electron-rich C–H)", "severity": 1, "mark": 0,
     "fix": "Block the para/activated position with F or Cl (fluorine scan)."},
    {"id": "benzylic", "label": "benzylic oxidation", "smarts": "[CH2,CH1;!R][c]",
     "pathway": "CYP benzylic C–H oxidation", "severity": 2, "mark": 0,
     "fix": "gem-dimethyl, fluorinate, or ring-fuse the benzylic carbon."},
    {"id": "ester", "label": "ester hydrolysis", "smarts": "[CX3](=O)[OX2][#6]",
     "pathway": "esterase / carboxylesterase hydrolysis", "severity": 3, "mark": 0,
     "fix": "Ester→amide / oxadiazole, or sterically shield the carbonyl."},
    {"id": "amide_hyd", "label": "amide hydrolysis", "smarts": "[CX3](=O)[NX3H1,NX3H2]",
     "pathway": "amidase / protease hydrolysis", "severity": 1, "mark": 0,
     "fix": "N-methylate, or amide→heterocyclic bioisostere if labile."},
    {"id": "thioether", "label": "S-oxidation", "smarts": "[#6][SX2][#6]",
     "pathway": "FMO / CYP sulfoxidation", "severity": 2, "mark": 1,
     "fix": "Pre-oxidise to sulfone, or replace the thioether."},
    {"id": "terminal_me", "label": "ω / terminal-methyl oxidation",
     "smarts": "[CH3][CH2][CH2]", "pathway": "CYP4A ω-oxidation of alkyl chains",
     "severity": 1, "mark": 0,
     "fix": "Shorten the chain, branch it, or cap with CF3."},
    {"id": "aniline", "label": "aniline (reactive-metabolite risk)",
     "smarts": "[NX3H2,NX3H1][c]", "pathway": "CYP → nitroso/quinone-imine (idiosyncratic tox)",
     "severity": 3, "mark": 0,
     "fix": "Acylate the aniline, add ortho-substituents, or remove it."},
    {"id": "phenol_gluc", "label": "phenol (glucuronidation/sulfation)",
     "smarts": "[OX2H][c]", "pathway": "phase-II UGT glucuronidation / SULT",
     "severity": 2, "mark": 0,
     "fix": "Cap phenol→F/OMe, or accept fast phase-II clearance."},
    {"id": "cooh_gluc", "label": "carboxylic acid (acyl-glucuronidation)",
     "smarts": "[CX3](=O)[OX2H1]", "pathway": "phase-II acyl glucuronidation",
     "severity": 1, "mark": 0,
     "fix": "Acid bioisostere (tetrazole/acylsulfonamide) if clearance-limited."},
    {"id": "furan", "label": "furan/thiophene (bioactivation)",
     "smarts": "c1ccoc1,c1ccsc1", "pathway": "CYP epoxidation → reactive metabolite",
     "severity": 3, "mark": 0,
     "fix": "Replace the furan/thiophene ring (known structural alert)."},
]


@lru_cache(maxsize=1)
def _compiled():
    from rdkit import Chem
    out = []
    for r in _RULES:
        # support comma-separated SMARTS alternatives
        patts = [Chem.MolFromSmarts(s) for s in r["smarts"].split(",")]
        patts = [p for p in patts if p is not None]
        if patts:
            out.append((r, patts))
    return out


@lru_cache(maxsize=256)
def _scan(smiles: str) -> dict[str, Any]:
    from rdkit import Chem
    m = Chem.MolFromSmiles((smiles or "").strip())
    if m is None:
        raise HTTPException(422, f"unparseable SMILES: {smiles}")
    canon = Chem.MolToSmiles(m)

    soft_spots = []
    flagged_atoms: set[int] = set()
    for r, patts in _compiled():
        atoms: set[int] = set()
        for patt in patts:
            for match in m.GetSubstructMatches(patt):
                mark = r["mark"] if r["mark"] < len(match) else 0
                atoms.add(match[mark])
        if atoms:
            soft_spots.append({
                "id": r["id"], "label": r["label"], "pathway": r["pathway"],
                "severity": r["severity"], "fix": r["fix"],
                "atoms": sorted(atoms), "count": len(atoms),
            })
            flagged_atoms.update(atoms)

    soft_spots.sort(key=lambda s: (-s["severity"], -s["count"]))
    # weighted liability load → metabolic-stability estimate (0 best → 1 worst)
    load = sum(s["severity"] * s["count"] for s in soft_spots)
    heavy = m.GetNumHeavyAtoms() or 1
    liability = min(1.0, load / (heavy * 0.9))
    stability = round(1.0 - liability, 3)
    band = ("stable" if stability >= 0.7 else
            "moderate" if stability >= 0.45 else "labile")
    n_high = sum(1 for s in soft_spots if s["severity"] == 3)

    return {
        "smiles": canon,
        "soft_spots": soft_spots, "n_soft_spots": len(soft_spots),
        "n_high_severity": n_high,
        "flagged_atoms": sorted(flagged_atoms),
        "metabolic_stability": stability, "band": band,
        "computed_at": time.time(),
        "engine": "Rule-based site-of-metabolism (curated SMARTS library)",
        "note": ("Transparent rule-based flagger of well-known labile motifs — "
                 "where to look and how to fix it, not a kinetic clearance model. "
                 "Highlighted atoms are the predicted soft spots; pair with the "
                 "Bioisostere Studio to make the fix."),
    }


class ScanRequest(BaseModel):
    smiles: str
    session_id: Optional[str] = None
    save: bool = True


@router.post("/metabolism/scan")
async def metabolism_scan(req: ScanRequest) -> dict[str, Any]:
    """Flag metabolic soft spots on the candidate → labile motifs, atoms,
    pathways, and the standard medchem mitigation for each."""
    result = _scan(req.smiles)
    artifact_id = None
    if req.save:
        rec = service_store.save_artifact(
            _ARTIFACT_KIND, result, session_id=req.session_id,
            smiles=result["smiles"],
            title=(f"Metabolism · {result['band']} · "
                   f"{result['n_soft_spots']} soft spots"))
        artifact_id = rec["id"]
    result["artifact_id"] = artifact_id

    if req.session_id:
        try:
            from . import candidate_dossier as _dossier
            _dossier.upsert_facet(req.session_id, result["smiles"], "metabolism", {
                "metabolic_stability": result["metabolic_stability"],
                "band": result["band"], "n_soft_spots": result["n_soft_spots"],
                "n_high_severity": result["n_high_severity"],
            })
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/metabolism/rules")
async def metabolism_rules() -> dict[str, Any]:
    return {"n_rules": len(_RULES), "rules": [
        {k: r[k] for k in ("id", "label", "pathway", "severity", "fix")}
        for r in _RULES]}


@router.get("/metabolism/runs")
async def list_runs(session_id: Optional[str] = None) -> dict[str, Any]:
    return {"items": service_store.list_artifacts(kind=_ARTIFACT_KIND,
                                                  session_id=session_id)}
