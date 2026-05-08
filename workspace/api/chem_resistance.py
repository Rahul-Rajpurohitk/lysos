"""Chemistry resistance services — Service 2: Resistance-Escape Map.

Endpoints:
  GET  /chem/resistance/known/{pdb_id}        curated CARD subset for target
  POST /chem/resistance/predict               candidate × target → escape map

The killer feature for antimicrobial drug design. Generic drug-discovery
software predicts "will it bind?" — but every antibiotic eventually fails
when the target evolves. Lysos predicts escape vectors UPFRONT so the
agent can harden vulnerable atoms before the wet-lab even sees the
candidate.

Algorithm
─────────
1. Load curated clinical mutations for this PDB (data/curated/card_resistance_subset.json)
2. Use Service 1's /place-in-pocket to find which ligand atoms contact each
   active-site residue
3. For each contact residue × clinical mutation:
     escape_score = clinical_frequency × distance_factor × atom_proximity_factor
   where:
     clinical_frequency = mapped from "very_high"/"high"/"moderate"/"low"/"rare"/"very_rare"
     distance_factor    = 1.0 if contact ≤ 2.5Å, scales linearly down to 0.5 at 4Å
     atom_proximity     = which ligand atom the residue contacts
4. Aggregate per ligand atom: top mutation that defeats it + cumulative score
5. Robustness score = 1 - max(per-atom escape scores)

Returns
───────
{
  "robustness_score": 0.0-1.0,
  "n_escape_vectors": int (count of atoms with score > 0.3),
  "vulnerable_atoms": [{atom_idx, escape_score, top_mutation: {position, wt, mutant, drug_class, frequency, note}}],
  "clinical_overlap": [{position, mutation, drug_class, score}],  # mutations matching this candidate's contacts
  "all_residue_scores": {position: {wt, mutations: {aa: score}}}  # for the heatmap UI
}
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger("api.chem_resistance")
router = APIRouter(prefix="/chem", tags=["chem_resistance"])

# Load curated CARD subset at import — static, small (~64 entries)
_CARD_PATH = Path(__file__).resolve().parents[2] / "data" / "curated" / "card_resistance_subset.json"
try:
    _CARD: dict[str, Any] = json.loads(_CARD_PATH.read_text())
except FileNotFoundError:
    log.warning("CARD subset not found at %s — resistance endpoints will return 503", _CARD_PATH)
    _CARD = {"by_pdb": {}, "frequency_score": {}}

_FREQUENCY_SCORE: dict[str, float] = _CARD.get("frequency_score", {})


def _frequency_score(label: str) -> float:
    return _FREQUENCY_SCORE.get(label, 0.30)


@router.get("/resistance/known/{pdb_id}")
async def known_mutations(pdb_id: str) -> dict:
    """Return curated clinical resistance mutations known for this target."""
    pdb_id = pdb_id.upper()
    entry = _CARD.get("by_pdb", {}).get(pdb_id)
    if not entry:
        raise HTTPException(404, f"no curated resistance mutations for PDB {pdb_id}")
    muts = entry.get("mutations", [])
    return {
        "pdb_id": pdb_id,
        "target_name": entry.get("_target", ""),
        "pathogen": entry.get("_pathogen", ""),
        "n_mutations": len(muts),
        "mutations": [
            {
                **m,
                "score": round(_frequency_score(m.get("frequency", "rare")), 3),
            }
            for m in muts
        ],
    }


class PredictResistanceRequest(BaseModel):
    smiles: str
    pdb_id: str


@router.post("/resistance/predict")
async def predict_resistance(req: PredictResistanceRequest) -> dict:
    """Predict per-atom escape vectors for the candidate against the target.

    Pipeline:
      1. Call /chem/place-in-pocket (Service 1) to get contact residues
         for this candidate.
      2. Cross-reference contacts with the curated mutation list.
      3. Aggregate scores per ligand atom.
    """
    pdb_id = req.pdb_id.upper()
    entry = _CARD.get("by_pdb", {}).get(pdb_id)
    if not entry:
        raise HTTPException(404, f"no curated resistance data for PDB {pdb_id}")

    # Reuse Service 1 placement
    from .chem_3d import place_in_pocket as place_endpoint
    from .chem_3d import PlaceInPocketRequest

    placement = await place_endpoint(PlaceInPocketRequest(smiles=req.smiles, pdb_id=pdb_id))
    contacts = placement["contacts"]  # raw contact list (atom-level)

    # Build per-residue contact map: position -> best contact
    # contacts items: {ligand_atom_idx, ligand_element, residue_chain, residue_resid, residue_name, protein_atom, distance_a}
    contact_by_resid: dict[int, dict[str, Any]] = {}
    for c in contacts:
        rid = c["residue_resid"]
        prev = contact_by_resid.get(rid)
        if prev is None or c["distance_a"] < prev["distance_a"]:
            contact_by_resid[rid] = c

    mutations = entry.get("mutations", [])

    # Aggregate per-atom escape scores
    per_atom_scores: dict[int, float] = {}
    per_atom_top_mutation: dict[int, dict[str, Any]] = {}
    clinical_overlap: list[dict[str, Any]] = []

    # Heatmap structure: position → {wt, mutations: {aa: score}}
    all_residue_scores: dict[int, dict[str, Any]] = {}

    for mut in mutations:
        pos = mut["position"]
        contact = contact_by_resid.get(pos)
        # Default heatmap entry whether or not we have a contact
        if pos not in all_residue_scores:
            all_residue_scores[pos] = {"wt": mut["wt"], "mutations": {}}
        freq = _frequency_score(mut.get("frequency", "rare"))

        if contact is None:
            # No contact at this residue — mutation has no effect on this candidate
            score = 0.0
        else:
            d = contact["distance_a"]
            # Distance factor: 1.0 within 2.5Å, linearly down to 0.5 at 4Å
            if d <= 2.5:
                dist_factor = 1.0
            elif d >= 4.0:
                dist_factor = 0.5
            else:
                dist_factor = 1.0 - 0.5 * ((d - 2.5) / 1.5)
            score = freq * dist_factor

        all_residue_scores[pos]["mutations"][mut["mutant"]] = round(score, 3)

        if contact and score > 0:
            atom_idx = contact["ligand_atom_idx"]
            prior = per_atom_scores.get(atom_idx, 0.0)
            if score > prior:
                per_atom_scores[atom_idx] = score
                per_atom_top_mutation[atom_idx] = {
                    "position": pos,
                    "wt": mut["wt"],
                    "mutant": mut["mutant"],
                    "drug_class": mut.get("drug_class", ""),
                    "frequency": mut.get("frequency", "rare"),
                    "note": mut.get("note", ""),
                    "distance_a": contact["distance_a"],
                    "residue_name": contact["residue_name"],
                }
            clinical_overlap.append({
                "position": pos,
                "wt": mut["wt"],
                "mutant": mut["mutant"],
                "drug_class": mut.get("drug_class", ""),
                "frequency": mut.get("frequency", "rare"),
                "score": round(score, 3),
                "ligand_atom_idx": atom_idx,
                "ligand_element": contact["ligand_element"],
                "distance_a": contact["distance_a"],
                "residue_name": contact["residue_name"],
                "note": mut.get("note", ""),
            })

    # Vulnerable atoms (sorted by score desc)
    vulnerable_atoms = [
        {
            "atom_idx": ai,
            "escape_score": round(score, 3),
            "top_mutation": per_atom_top_mutation[ai],
        }
        for ai, score in sorted(per_atom_scores.items(), key=lambda kv: -kv[1])
    ]

    # Robustness = 1 - max escape score (higher = more robust)
    max_escape = max(per_atom_scores.values()) if per_atom_scores else 0.0
    robustness_score = round(1.0 - max_escape, 3)

    # n_escape_vectors = count of atoms with score > 0.3 (clinically meaningful)
    n_escape_vectors = sum(1 for s in per_atom_scores.values() if s > 0.3)

    # Clinical overlap sorted by score
    clinical_overlap.sort(key=lambda c: -c["score"])

    return {
        "pdb_id": pdb_id,
        "smiles": req.smiles,
        "target_name": entry.get("_target", ""),
        "pathogen": entry.get("_pathogen", ""),
        "robustness_score": robustness_score,
        "n_escape_vectors": n_escape_vectors,
        "vulnerable_atoms": vulnerable_atoms,
        "clinical_overlap": clinical_overlap[:20],
        "all_residue_scores": all_residue_scores,
        "n_total_known_mutations": len(mutations),
        "n_residues_with_contacts": len(contact_by_resid),
        "summary": (
            # Distinguish "no contact-residue overlaps with clinical mutations
            # at all" (truly robust) from "overlaps exist but escape scores
            # are below the 0.3 vulnerability threshold". The earlier wording
            # "0 atom(s) vulnerable" was misleading when the heatmap shows
            # weak overlaps because escape_score was sub-threshold.
            f"robust against the {len(mutations)} curated clinical mutation"
            f"{'' if len(mutations) == 1 else 's'} for this target — "
            f"no overlap above 0.30 escape threshold; robustness={robustness_score:.2f}"
            if n_escape_vectors == 0 and len(vulnerable_atoms) == 0
            else (
                f"{n_escape_vectors} atom(s) above the 0.30 escape threshold; "
                f"top vulnerability score={vulnerable_atoms[0]['escape_score']:.2f}; "
                f"robustness={robustness_score:.2f}"
                if n_escape_vectors > 0
                else (
                    f"{len(vulnerable_atoms)} sub-threshold weak spot"
                    f"{'' if len(vulnerable_atoms) == 1 else 's'} (escape "
                    f"< 0.30); top score={vulnerable_atoms[0]['escape_score']:.2f}; "
                    f"robustness={robustness_score:.2f}"
                )
            )
        ),
    }
