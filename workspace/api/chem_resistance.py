"""Chemistry resistance services — Service 2: Resistance-Escape Map.

Endpoints:
  GET  /chem/resistance/known/{pdb_id}        curated CARD subset for target
  POST /chem/resistance/predict               candidate × target → escape map
  POST /chem/resistance/harden                vulnerable atom → swap suggestions
  POST /chem/resistance/compare               N candidates × target → side-by-side
  POST /chem/resistance/explain               Gemini explanation of vulnerabilities

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
import re
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


# ─────────────────────────────────────────────────────────────────────
# Chemistry-aware substitution scoring.
#
# The original predict_resistance scored escape as `frequency × distance`
# only — independent of WHAT physicochemical change the mutation makes.
# That misses the real driver of escape: a polar→nonpolar swap at a
# polar-contact position destroys the H-bond; a same-class swap (e.g.,
# K→R, both basic + positively charged) often retains binding.
#
# Grantham (1974) distance is the gold-standard amino-acid substitution
# metric weighing composition + polarity + volume. Range 5 (very similar)
# to 215 (very dissimilar). We normalise to 0..1 and use it as a SECOND
# multiplier on top of frequency × distance — so a clinical mutation
# that's chemically conservative gets a smaller escape score than a
# disruptive mutation at the same position+frequency.
# ─────────────────────────────────────────────────────────────────────

# Reduced Grantham table — symmetric AA→AA distance. Source:
# Grantham R, "Amino-acid difference formula to help explain protein
# evolution" (Science 1974). We store the upper triangle and resolve
# (a,b) regardless of order. Missing pairs default to 100 (mid).
_GRANTHAM: dict[tuple[str, str], int] = {
    ("A", "R"): 112, ("A", "N"):  111, ("A", "D"):  126, ("A", "C"):  195, ("A", "Q"):   91,
    ("A", "E"):  107, ("A", "G"):   60, ("A", "H"):   86, ("A", "I"):   94, ("A", "L"):   96,
    ("A", "K"):  106, ("A", "M"):   84, ("A", "F"):  113, ("A", "P"):   27, ("A", "S"):   99,
    ("A", "T"):   58, ("A", "W"):  148, ("A", "Y"):  112, ("A", "V"):   64,
    ("R", "N"):   86, ("R", "D"):   96, ("R", "C"):  180, ("R", "Q"):   43, ("R", "E"):   54,
    ("R", "G"):  125, ("R", "H"):   29, ("R", "I"):   97, ("R", "L"):  102, ("R", "K"):   26,
    ("R", "M"):   91, ("R", "F"):   97, ("R", "P"):  103, ("R", "S"):  110, ("R", "T"):   71,
    ("R", "W"):  101, ("R", "Y"):   77, ("R", "V"):   96,
    ("N", "D"):   23, ("N", "C"):  139, ("N", "Q"):   46, ("N", "E"):   42, ("N", "G"):   80,
    ("N", "H"):   68, ("N", "I"):  149, ("N", "L"):  153, ("N", "K"):   94, ("N", "M"):  142,
    ("N", "F"):  158, ("N", "P"):   91, ("N", "S"):   46, ("N", "T"):   65, ("N", "W"):  174,
    ("N", "Y"):  143, ("N", "V"):  133,
    ("D", "C"):  154, ("D", "Q"):   61, ("D", "E"):   45, ("D", "G"):   94, ("D", "H"):   81,
    ("D", "I"):  168, ("D", "L"):  172, ("D", "K"):  101, ("D", "M"):  160, ("D", "F"):  177,
    ("D", "P"):  108, ("D", "S"):   65, ("D", "T"):   85, ("D", "W"):  181, ("D", "Y"):  160,
    ("D", "V"):  152,
    ("C", "Q"):  154, ("C", "E"):  170, ("C", "G"):  159, ("C", "H"):  174, ("C", "I"):  198,
    ("C", "L"):  198, ("C", "K"):  202, ("C", "M"):  196, ("C", "F"):  205, ("C", "P"):  169,
    ("C", "S"):  112, ("C", "T"):  149, ("C", "W"):  215, ("C", "Y"):  194, ("C", "V"):  192,
    ("Q", "E"):   29, ("Q", "G"):   87, ("Q", "H"):   24, ("Q", "I"):  109, ("Q", "L"):  113,
    ("Q", "K"):   53, ("Q", "M"):  101, ("Q", "F"):  116, ("Q", "P"):   76, ("Q", "S"):   68,
    ("Q", "T"):   42, ("Q", "W"):  130, ("Q", "Y"):   99, ("Q", "V"):   96,
    ("E", "G"):   98, ("E", "H"):   40, ("E", "I"):  134, ("E", "L"):  138, ("E", "K"):   56,
    ("E", "M"):  126, ("E", "F"):  140, ("E", "P"):   93, ("E", "S"):   80, ("E", "T"):   65,
    ("E", "W"):  152, ("E", "Y"):  122, ("E", "V"):  121,
    ("G", "H"):   98, ("G", "I"):  135, ("G", "L"):  138, ("G", "K"):  127, ("G", "M"):  127,
    ("G", "F"):  153, ("G", "P"):   42, ("G", "S"):   56, ("G", "T"):   59, ("G", "W"):  184,
    ("G", "Y"):  147, ("G", "V"):  109,
    ("H", "I"):   94, ("H", "L"):   99, ("H", "K"):   32, ("H", "M"):   87, ("H", "F"):  100,
    ("H", "P"):   77, ("H", "S"):   89, ("H", "T"):   47, ("H", "W"):  115, ("H", "Y"):   83,
    ("H", "V"):   84,
    ("I", "L"):    5, ("I", "K"):  102, ("I", "M"):   10, ("I", "F"):   21, ("I", "P"):   95,
    ("I", "S"):  142, ("I", "T"):   89, ("I", "W"):   61, ("I", "Y"):   33, ("I", "V"):   29,
    ("L", "K"):  107, ("L", "M"):   15, ("L", "F"):   22, ("L", "P"):   98, ("L", "S"):  145,
    ("L", "T"):   92, ("L", "W"):   61, ("L", "Y"):   36, ("L", "V"):   32,
    ("K", "M"):   95, ("K", "F"):  102, ("K", "P"):  103, ("K", "S"):  121, ("K", "T"):   78,
    ("K", "W"):  110, ("K", "Y"):   85, ("K", "V"):   97,
    ("M", "F"):   28, ("M", "P"):   87, ("M", "S"):  135, ("M", "T"):   81, ("M", "W"):   67,
    ("M", "Y"):   36, ("M", "V"):   21,
    ("F", "P"):  114, ("F", "S"):  155, ("F", "T"):  103, ("F", "W"):   40, ("F", "Y"):   22,
    ("F", "V"):   50,
    ("P", "S"):   74, ("P", "T"):   38, ("P", "W"):  147, ("P", "Y"):  110, ("P", "V"):   68,
    ("S", "T"):   58, ("S", "W"):  177, ("S", "Y"):  144, ("S", "V"):  124,
    ("T", "W"):  128, ("T", "Y"):   92, ("T", "V"):   69,
    ("W", "Y"):   37, ("W", "V"):   88,
    ("Y", "V"):   55,
}


def _grantham(wt: str, mt: str) -> float:
    """Return Grantham distance (5–215) between two amino-acid 1-letter codes.
    Symmetric. Same residue → 0. Unknown pairs → 100 (mid)."""
    if wt == mt:
        return 0.0
    key = (wt, mt) if (wt, mt) in _GRANTHAM else (mt, wt)
    return float(_GRANTHAM.get(key, 100))


def _grantham_factor(wt: str, mt: str) -> float:
    """Map Grantham (0..215) → impact multiplier (0.30..1.0).
    Conservative swaps (low Grantham) get 0.30 — they barely hurt the
    interaction. Disruptive swaps (high Grantham) get 1.0 — full clinical
    frequency × distance impact. Intermediate scales linearly."""
    g = _grantham(wt, mt)
    if g <= 0:
        return 0.30  # silent (same residue) → minimal impact
    # Map [5, 215] → [0.30, 1.0] linearly, clamped.
    norm = max(0.0, min(1.0, (g - 5) / (215 - 5)))
    return 0.30 + 0.70 * norm


# Class-conservation table — how often a residue at this position is
# evolutionarily conserved. For curated CARD positions we mark them as
# HIGH (these positions ARE in clinical mutations, so by definition
# they evolve). Generic fallback = 0.50.
def _conservation_score(target: dict, pos: int) -> float:
    cons = (target or {}).get("_conservation") or {}
    return float(cons.get(str(pos), cons.get(pos, 0.50)))


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
        # Chemistry-aware: Grantham × position conservation. A polar→
        # nonpolar swap at a polar contact is much worse than K→R; a
        # mutation at a highly conserved position is more diagnostic
        # than one at a wobble position.
        chem_factor = _grantham_factor(mut.get("wt", ""), mut.get("mutant", ""))
        cons = _conservation_score(entry, pos)

        if contact is None:
            # No contact at this residue — mutation has no effect on this candidate
            score = 0.0
            dist_factor = 0.0
        else:
            d = contact["distance_a"]
            # Distance factor: 1.0 within 2.5Å, linearly down to 0.5 at 4Å
            if d <= 2.5:
                dist_factor = 1.0
            elif d >= 4.0:
                dist_factor = 0.5
            else:
                dist_factor = 1.0 - 0.5 * ((d - 2.5) / 1.5)
            # Final escape model:
            #   freq        — clinical evidence weight
            #   dist_factor — geometric proximity weight
            #   chem_factor — physicochemical disruption (Grantham)
            #   cons        — evolutionary pressure at this site
            score = freq * dist_factor * chem_factor * (0.5 + 0.5 * cons)

        all_residue_scores[pos]["mutations"][mut["mutant"]] = round(score, 3)
        # Stash factor breakdown for transparency (consumed by the new
        # "explain this score" tooltip in the frontend per-mutation row).
        if "_factors" not in all_residue_scores[pos]:
            all_residue_scores[pos]["_factors"] = {}
        all_residue_scores[pos]["_factors"][mut["mutant"]] = {
            "freq": round(freq, 3),
            "dist": round(dist_factor, 3),
            "chem": round(chem_factor, 3),
            "cons": round(cons, 3),
            "grantham": int(_grantham(mut.get("wt", ""), mut.get("mutant", ""))),
        }

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

    # ── End-to-end enrichment: per-contact-residue detail panel data ──
    # The frontend needs this whether or not the candidate is "robust" —
    # we want to SHOW which residues the candidate touches and what
    # mutations exist at those positions, even when none defeat us.
    # Industry standard (Schrödinger BioLuminate, Cresset Forge): one
    # card per contact residue with distance + per-position mutations
    # color-coded by drug class.
    contact_residue_details: list[dict[str, Any]] = []
    for pos in sorted(contact_by_resid.keys()):
        c = contact_by_resid[pos]
        # Mutations known at THIS position
        muts_here = [m for m in mutations if m["position"] == pos]
        # Contact strength: 1.0 within 2.5Å → 0.0 at 4.0Å (linear).
        d = c["distance_a"]
        if d <= 2.5:
            contact_strength = 1.0
        elif d >= 4.0:
            contact_strength = 0.0
        else:
            contact_strength = 1.0 - ((d - 2.5) / 1.5)
        # Wild-type residue identity (3-letter from the contact, 1-letter from the mutation list if known)
        wt_1letter = muts_here[0]["wt"] if muts_here else ""
        contact_residue_details.append({
            "position": pos,
            "residue_name": c.get("residue_name", ""),
            "residue_chain": c.get("residue_chain", "A"),
            "wt": wt_1letter,
            "ligand_atom_idx": c.get("ligand_atom_idx"),
            "ligand_element": c.get("ligand_element"),
            "distance_a": round(d, 2),
            "contact_strength": round(contact_strength, 3),
            "n_known_mutations": len(muts_here),
            "known_mutations": [
                {
                    "wt": m["wt"], "mutant": m["mutant"],
                    "drug_class": m.get("drug_class", ""),
                    "frequency": m.get("frequency", "rare"),
                    "freq_score": round(_frequency_score(m.get("frequency", "rare")), 3),
                    "note": m.get("note", ""),
                    "escape_score": all_residue_scores.get(pos, {})
                                                     .get("mutations", {})
                                                     .get(m["mutant"], 0.0),
                }
                for m in muts_here
            ],
        })

    # ── Drug-class profile: how robust is the candidate against EACH class? ──
    # Group mutations by drug_class, compute fraction of mutations defeated
    # (escape > 0). Even when robust=1.00 this shows WHICH classes the
    # robustness covers — actionable for the medchem reviewer.
    classes: dict[str, dict[str, Any]] = {}
    for m in mutations:
        cls = m.get("drug_class", "unknown")
        if cls not in classes:
            classes[cls] = {"drug_class": cls, "n_total": 0, "n_threatening": 0,
                            "max_escape": 0.0, "n_contacted": 0}
        classes[cls]["n_total"] += 1
        if m["position"] in contact_by_resid:
            classes[cls]["n_contacted"] += 1
        # escape score for this mutation against this candidate
        sc = all_residue_scores.get(m["position"], {}).get("mutations", {}).get(m["mutant"], 0.0)
        if sc > 0:
            classes[cls]["n_threatening"] += 1
            if sc > classes[cls]["max_escape"]:
                classes[cls]["max_escape"] = sc
    drug_class_profile = []
    for cls, row in classes.items():
        row["max_escape"] = round(row["max_escape"], 3)
        row["robustness"] = round(1.0 - row["max_escape"], 3)
        drug_class_profile.append(row)
    drug_class_profile.sort(key=lambda r: -r["max_escape"])

    result = {
        "pdb_id": pdb_id,
        "smiles": req.smiles,
        "target_name": entry.get("_target", ""),
        "pathogen": entry.get("_pathogen", ""),
        "robustness_score": robustness_score,
        "n_escape_vectors": n_escape_vectors,
        "vulnerable_atoms": vulnerable_atoms,
        "clinical_overlap": clinical_overlap[:20],
        "all_residue_scores": all_residue_scores,
        "contact_residue_details": contact_residue_details,
        "drug_class_profile": drug_class_profile,
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

    # Best-effort: persist + broadcast for agent consumers.
    _broadcast_resistance(result)
    return result


# ─────────────────────────────────────────────────────────────────────
# Hardening, comparison, explanation — the parts that turn the heatmap
# into actionable guidance. These power the new "Harden" / "Compare" /
# "Ask agent" buttons on the lavender-glass card.
# ─────────────────────────────────────────────────────────────────────


# Heuristic substitution table: which substituent swaps are known to
# survive each clinical mutation class. Curated from medchem literature
# rather than a generative model — this gives us a deterministic
# fallback when the agent path is unavailable.
_HARDEN_PLAYBOOK: dict[str, list[dict[str, str]]] = {
    # β-lactams: bulky 6-α / 7-α substituents survive PBP2a S365T, MecA
    "beta_lactam": [
        {"swap": "add 6α-methoxy", "rationale": "Methoxy at 6α blocks the rotated catalytic serine in PBP2a; survives S365T (cefoxitin-class)."},
        {"swap": "side-chain → 2-aminothiazole", "rationale": "Aminothiazole oxime side-chain (cefepime-class) tolerates the wider PBP2a active site."},
        {"swap": "add 6α-fluoro", "rationale": "6α-fluoro reduces β-lactamase hydrolysis without losing PBP affinity (broad-spectrum hardening)."},
    ],
    "methicillin_resistance": [
        {"swap": "C7 acyl → ceftaroline-style", "rationale": "Ceftaroline's C7 acyl anchors PBP2a-N146 ahead of the closed gate."},
        {"swap": "rigidify oxazoline ring", "rationale": "Locking the C3 substituent rigidifies the binding pose against PBP2a."},
    ],
    # Topoisomerase: bulkier C-7 substituents reach over QRDR mutations
    "fluoroquinolone": [
        {"swap": "C7 → 7-piperazinyl", "rationale": "Piperazinyl at C7 reaches past S81F/S83L QRDR escape (gyrA)."},
        {"swap": "C8 → 8-methoxy", "rationale": "8-methoxy stacks against the secondary cleavage site, surviving D426N (parC)."},
    ],
    "rrna_binders": [
        {"swap": "C-2 dimethylaminopropyl", "rationale": "Lengthening the C-2 chain reaches past the A2058G ribosomal escape."},
        {"swap": "fluorinate the macrocycle", "rationale": "Fluorination at C-6 narrows the binding pocket, surviving 23S A2058G."},
    ],
    # Generic fall-through
    "generic": [
        {"swap": "isosteric heteroatom swap (CH₂→O or NH)", "rationale": "Replace the contact carbon with an oxa/aza isostere; preserves geometry, breaks H-bond donor/acceptor pattern the resistance mutation exploits."},
        {"swap": "add steric guard (-CH₃ or -CF₃)", "rationale": "Bulky substituent prevents the mutant residue from making productive contacts."},
        {"swap": "rigidify with fused ring", "rationale": "Locking the rotamer reduces entropic penalty from the mutation."},
    ],
}


def _classify_mutation(mut: dict[str, Any]) -> str:
    """Pick the playbook bucket from drug class / target name.

    Handles drug-class strings with hyphens, underscores, plurals, and
    "all_<class>s" prefix conventions used by the curated CARD subset
    (e.g. "all_beta_lactams", "fluoroquinolones", "β-lactam").
    """
    drug = (mut.get("drug_class") or "").lower()
    # Normalise separators so 'beta_lactam', 'beta-lactam', 'beta lactam'
    # all collapse to the same form.
    norm = drug.replace("_", "-").replace(" ", "-")
    note = (mut.get("note") or "").lower()
    pos = mut.get("position")

    if any(k in norm for k in ("β-lactam", "beta-lactam", "cephalosporin",
                                "penicillin", "carbapenem", "monobactam",
                                "all-beta-lactam")):
        if "meca" in note or pos in {365, 247, 246, 200}:
            return "methicillin_resistance"
        return "beta_lactam"
    if any(k in norm for k in ("fluoroquinolone", "quinolone", "ciproflox", "levoflox")):
        return "fluoroquinolone"
    if any(k in norm for k in ("macrolide", "ketolide", "azithromycin", "erythromycin")):
        return "rrna_binders"
    if any(k in norm for k in ("lincosamide", "clindamycin")):
        return "rrna_binders"
    if any(k in norm for k in ("aminoglycoside", "gentamicin", "amikacin", "tobramycin")):
        return "rrna_binders"
    if any(k in norm for k in ("tetracycline", "tigecycline", "doxycycline")):
        return "rrna_binders"
    if any(k in norm for k in ("oxazolidinone", "linezolid")):
        return "rrna_binders"
    if any(k in norm for k in ("glycopeptide", "vancomycin", "teicoplanin")):
        return "glycopeptide"
    if any(k in norm for k in ("rifamycin", "rifampin", "rifampicin")):
        return "rrna_binders"
    return "generic"


class HardenRequest(BaseModel):
    smiles: str
    pdb_id: str
    atom_idx: int
    use_llm: bool = True


def _swap_label_to_fg(swap_label: str) -> str | None:
    """Map a free-form Gemini/playbook swap label to one of the FG_TEMPLATES
    keys (`hydroxyl`, `methyl`, `carboxyl`, …). Returns None when no
    obvious match — the suggestion is shown without an Apply button.

    Order matters: longest/most-specific labels first so "trifluoromethyl"
    isn't shadowed by "methyl".
    """
    s = (swap_label or "").lower()
    # Order matters: long/specific labels first so 'trifluoromethyl'
    # isn't shadowed by 'methyl', 'phenyl' isn't shadowed by 'ethyl',
    # etc. Also handle "X to Y" / "X -> Y" / "swap to Y" / "add Y"
    # patterns where the FG identity is the LAST chemistry word.
    table = [
        ("trifluoromethyl", "trifluoromethyl"), ("cf3", "trifluoromethyl"),
        ("trichloromethyl", "trichloromethyl"),
        ("spiro-cyclopropyl", "phenyl"),  # closest available — adds a ring atom set
        ("cyclopropyl", "phenyl"),
        ("phenyl", "phenyl"), ("aryl", "phenyl"), ("benzyl", "phenyl"),
        ("sulfonamide", "sulfonamide"), ("sulfonyl", "sulfonyl"),
        ("phosphonate", "phosphonate"), ("phosphate", "phosphate"),
        ("carboxylate", "carboxyl"), ("carboxyl", "carboxyl"),
        ("aldehyde", "aldehyde"), ("carbonyl", "carbonyl"),
        ("ester", "ester"), ("amide", "amide"),
        ("nitro", "nitro"), ("cyano", "cyano"), ("nitrile", "cyano"),
        ("hydroxy", "hydroxyl"), ("phenol", "hydroxyl"),
        ("-oh", "hydroxyl"), (" oh", "hydroxyl"),
        ("methoxy", "methoxy"),
        ("ethoxy", "ethoxy"),
        ("tert-butyl", "tert-butyl"), ("t-butyl", "tert-butyl"),
        ("isopropyl", "isopropyl"),
        ("ethynyl", "ethynyl"), ("vinyl", "vinyl"),
        ("ethyl", "ethyl"),
        ("methyl", "methyl"),
        ("amine", "amine"), ("amino", "amine"), ("-nh2", "amine"),
        ("fluorine", "fluorine"), ("fluoro", "fluorine"),
        ("-f ", "fluorine"), (" f ", "fluorine"),
        ("chlorine", "chlorine"), ("chloro", "chlorine"),
        ("bromine", "bromine"), ("bromo", "bromine"),
        ("iodine", "iodine"), ("iodo", "iodine"),
        ("thiol", "thiol"), ("sulfhydryl", "thiol"),
        ("azide", "azido"), ("azido", "azido"),
        ("isocyanide", "isocyano"),
    ]
    # First pass: look for any FG word in the whole label.
    for needle, fg in table:
        if needle in s:
            return fg
    # Second pass: pull the LAST chemistry-like token (for "swap X to Y"
    # phrasings Gemini sometimes returns). Strip parentheticals first.
    cleaned = re.sub(r"\([^)]*\)", "", s)
    tokens = re.findall(r"[a-z][a-z0-9-]+", cleaned)
    for tok in reversed(tokens):
        for needle, fg in table:
            if needle == tok:
                return fg
    return None


def _apply_fg_to_smiles(smiles: str, atom_idx: int, fg_name: str) -> str | None:
    """Apply a functional group at the given atom index using RDKit and
    return the canonical SMILES of the result. None on any failure —
    callers should treat absence of after_smiles as "non-applicable".
    """
    try:
        from workspace.tools.chem_workbench.edit_molecule import edit_molecule
        result = edit_molecule(
            smiles=smiles,
            op="add_functional_group_at",
            atom_index=atom_idx,
            functional_group=fg_name,
        )
        out = getattr(result, "smiles", None) or (
            result.get("smiles") if isinstance(result, dict) else None
        )
        return out if out and out != smiles else None
    except Exception:  # noqa: BLE001
        return None


@router.post("/resistance/harden")
async def harden_atom(req: HardenRequest) -> dict:
    """Suggest substituent swaps that reduce escape-score for the picked
    vulnerable atom.

    Returns up to 3 ranked suggestions. Each suggestion has:
      - swap: short label of the modification ("add 6α-methoxy")
      - rationale: one-line medchem reason
      - source: "playbook" | "llm" — so the UI can badge it
      - confidence: 0-1 estimate
    """
    pdb_id = req.pdb_id.upper()

    # Re-run the prediction so we know the top mutation that defeats this atom.
    pred = await predict_resistance(PredictResistanceRequest(smiles=req.smiles, pdb_id=pdb_id))
    target_atom = next((v for v in pred["vulnerable_atoms"] if v["atom_idx"] == req.atom_idx), None)
    if target_atom is None:
        # Atom not flagged as vulnerable — return generic playbook anyway
        target_atom = {"atom_idx": req.atom_idx, "escape_score": 0.0, "top_mutation": {"drug_class": "generic", "note": "", "position": 0, "wt": "?", "mutant": "?"}}

    mut = target_atom["top_mutation"]
    bucket = _classify_mutation(mut)

    # ─── PRIMARY PATH — Gemini Pro generates N candidate-specific swaps,
    # each validated through RDKit. This replaces the static playbook
    # table as the PRIMARY suggestion source. The playbook acts only as
    # an emergency fallback if Gemini fails completely.
    llm_suggestions: list[dict[str, Any]] = []
    llm_status = "skipped"
    if req.use_llm:
        import os as _os
        if not _os.getenv("GEMINI_API_KEY"):
            llm_status = "no_api_key"
        else:
            llm_suggestions = await _llm_harden_suggestions_multi(
                req.smiles, pred, target_atom, mut, n=4,
            )
            llm_status = "ok" if llm_suggestions else "call_failed"

    # Build the curated medchem playbook section ALWAYS so the user
    # gets BOTH AI-bespoke + medchem-heuristic priors side by side.
    playbook = list(_HARDEN_PLAYBOOK.get(bucket, _HARDEN_PLAYBOOK["generic"]))[:3]

    # ── Calculative confidence per suggestion ──
    # Replaces the flat 0.65 with a value derived from real signals:
    #   bucket_match    bucket-specific = 1.0, generic fallback = 0.55
    #   chem_disruption Grantham factor of the mutation we're hardening
    #                   against (higher Grantham → suggestion needs to
    #                   work harder → lower base confidence)
    #   atom_feasible   does the candidate atom have a free valence slot
    #                   to actually accept the swap? RDKit-derived.
    #   bond_proximity  closer contact = stronger evidence the mutation
    #                   matters; 1.0 within 2.5Å, 0.5 at 4Å.
    bucket_match = 1.0 if bucket != "generic" else 0.55
    chem_disrupt = _grantham_factor(mut.get("wt", ""), mut.get("mutant", ""))
    chem_inverse = max(0.30, 1.0 - 0.5 * (chem_disrupt - 0.30))  # easier swap → higher conf
    bond_prox = 1.0
    try:
        d = float(mut.get("distance_a", 3.0))
        bond_prox = 1.0 if d <= 2.5 else 0.5 if d >= 4.0 else 1.0 - 0.5 * ((d - 2.5) / 1.5)
    except Exception:
        pass
    atom_feasible = _atom_can_substitute(req.smiles, req.atom_idx)

    suggestions = []
    for i, s in enumerate(playbook):
        # Per-rank decay: rank 1 (top playbook) most relevant, rank 3 less so.
        rank_factor = 1.0 - 0.08 * i
        # The suggestion's own swap chemistry — e.g., bulky guard swaps
        # are easier to add when the target atom has free valence.
        slot_match = atom_feasible if "guard" in s["swap"].lower() or "methyl" in s["swap"].lower() else 0.85
        confidence = round(
            bucket_match * 0.30
            + chem_inverse * 0.25
            + bond_prox * 0.20
            + slot_match * 0.15
            + rank_factor * 0.10,
            3,
        )
        # Per-suggestion factor breakdown for the UI tooltip — same
        # transparency model the heatmap cells use.
        suggestions.append({
            **s,
            "source": "playbook",
            "confidence": confidence,
            "rank": i + 1,
            "_factors": {
                "bucket_match": round(bucket_match, 3),
                "chem_inverse": round(chem_inverse, 3),
                "bond_proximity": round(bond_prox, 3),
                "atom_feasible": round(slot_match, 3),
                "rank_decay": round(rank_factor, 3),
                "grantham": int(_grantham(mut.get("wt", ""), mut.get("mutant", ""))),
            },
        })

    # Annotate each suggestion with `after_smiles` whenever the swap
    # label maps to a known functional group. The frontend uses this to
    # render an "Apply" chip that loads the modified SMILES into 2D + 3D
    # — turning a verbal recommendation into a one-click visual change.
    def _annotate(items: list[dict]) -> list[dict]:
        out = []
        for item in items:
            fg = _swap_label_to_fg(item.get("swap", ""))
            after = _apply_fg_to_smiles(req.smiles, req.atom_idx, fg) if fg else None
            if after and after != req.smiles:
                item = {**item, "after_smiles": after, "fg_applied": fg}
            out.append(item)
        return out

    suggestions = _annotate(suggestions)
    llm_suggestions = _annotate(llm_suggestions)

    # Combined response — BOTH llm_suggestions AND playbook suggestions.
    # The frontend renders them as two separate sections. Each suggestion
    # carries its own _factors so the calculative breakdown is shown for
    # both AI-bespoke and curated entries.
    return {
        "pdb_id": pdb_id,
        "smiles": req.smiles,
        "atom_idx": req.atom_idx,
        "target_atom": target_atom,
        "bucket": bucket,
        # Legacy field — combined list (Gemini first, then playbook) so
        # older clients still see something. New clients should use
        # `gemini_suggestions` / `playbook_suggestions` separately.
        "suggestions": [*llm_suggestions, *suggestions],
        "gemini_suggestions": llm_suggestions,
        "playbook_suggestions": suggestions,
        "llm_status": llm_status,
        "compute_inputs": {
            "bucket": bucket,
            "atom_environment": _atom_environment_string(req.smiles, req.atom_idx),
            "bucket_match": round(bucket_match, 3),
            "chem_disrupt": round(chem_disrupt, 3),
            "chem_inverse": round(chem_inverse, 3),
            "bond_proximity": round(bond_prox, 3),
            "atom_feasible": round(atom_feasible, 3),
            "grantham": int(_grantham(mut.get("wt", ""), mut.get("mutant", ""))),
            "wt": mut.get("wt"), "mutant": mut.get("mutant"),
            "drug_class": mut.get("drug_class"),
            "frequency": mut.get("frequency"),
            "current_robustness": pred.get("robustness_score"),
        },
    }


def _atom_can_substitute(smiles: str, atom_idx: int) -> float:
    """Real RDKit-backed feasibility score: does the candidate atom have
    free valence to accept a new substituent? Returns:
      1.0 — atom has ≥1 free bond slot (most swaps applicable)
      0.7 — atom is in a ring but has no free slot (needs ring-edit)
      0.4 — atom is fully bonded with no free slot (swap = replace, harder)
      0.5 — RDKit unavailable / atom not parseable (mid default).
    """
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        if mol is None or atom_idx < 0 or atom_idx >= mol.GetNumAtoms():
            return 0.5
        atom = mol.GetAtomWithIdx(atom_idx)
        free = atom.GetNumImplicitHs() + atom.GetNumExplicitHs()
        if free >= 1:
            return 1.0
        return 0.7 if atom.IsInRing() else 0.4
    except Exception:
        return 0.5


async def _llm_harden_suggestion(smiles: str, pred: dict, target_atom: dict, mut: dict) -> Optional[dict[str, Any]]:
    """Legacy single-suggestion path — kept for backward compat. Prefer
    `_llm_harden_suggestions_multi` for the live primary list."""
    arr = await _llm_harden_suggestions_multi(smiles, pred, target_atom, mut, n=1)
    return arr[0] if arr else None


async def _llm_harden_suggestions_multi(
    smiles: str, pred: dict, target_atom: dict, mut: dict, n: int = 4,
) -> list[dict[str, Any]]:
    """Gemini Pro call → N bespoke hardening suggestions for THIS candidate
    against THIS mutation at THIS contact. Each suggestion comes back with:
      - swap: short label
      - rationale: medchem reasoning
      - proposed_smiles: a concrete proposed SMILES (validated via RDKit)
      - predicted_robustness_delta: the LLM's estimate
      - mechanism: which chemistry handle it leverages
    The frontend's primary list is built from THIS function (no playbook
    table). Returns [] on any failure — caller decides emergency fallback.
    """
    import os as _os
    key = _os.getenv("GEMINI_API_KEY")
    if not key:
        return []
    model_id = _os.getenv("LYSOS_HARDEN_GEMINI_MODEL", "gemini-2.5-pro")

    # Build atom environment context — what's actually next to the atom?
    atom_ctx = _atom_environment_string(smiles, target_atom["atom_idx"])

    schema_block = (
        '{"suggestions": ['
        '{"swap": "<≤50 char label>",'
        ' "rationale": "<≤180 char one-line medchem reason>",'
        ' "proposed_smiles": "<full SMILES of a candidate analog, or empty>",'
        ' "predicted_robustness_delta": <number between 0.00 and 0.50>,'
        ' "mechanism": "<one of: steric|electronic|conformational|isosteric|h-bond>"'
        '}]}'
    )

    prompt = (
        "You are a senior medicinal chemist working on antimicrobial resistance "
        f"hardening. Generate {n} DISTINCT, candidate-specific substituent swaps "
        "to defeat the escape vector below. Each suggestion must:\n"
        " • Target the SPECIFIC vulnerable atom and its environment\n"
        " • Address the SPECIFIC physicochemical change of the mutation\n"
        " • Be a concrete swap (not a vague principle)\n"
        " • Have a different MECHANISM from the others (steric vs electronic vs conformational vs isosteric vs h-bond)\n"
        f" • Provide a PROPOSED SMILES analog when feasible\n\n"
        f"Candidate SMILES: {smiles}\n"
        f"Vulnerable atom: index {target_atom['atom_idx']}, environment={atom_ctx}\n"
        f"Target: {pred.get('target_name')} ({pred.get('pdb_id')}) in {pred.get('pathogen')}\n"
        f"Defeating mutation: {mut.get('wt')}{mut.get('position')}{mut.get('mutant')}\n"
        f"  drug_class: {mut.get('drug_class')}\n"
        f"  frequency: {mut.get('frequency')} clinical\n"
        f"  contact distance: {mut.get('distance_a', '?')} Å\n"
        f"  residue_name: {mut.get('residue_name', '')}\n"
        f"  note: {mut.get('note', '')}\n"
        f"Current robustness: {pred.get('robustness_score'):.2f}\n\n"
        f"Return STRICT JSON conforming to this schema:\n{schema_block}\n"
        "No markdown, no commentary. JSON only."
    )

    try:
        import httpx
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 4096,           # Pro reasons; need budget
                # Lower temperature so repeated /harden calls on the
                # same atom return CONSISTENT swap suggestions instead
                # of flipping between (e.g.) 2-OH and 2-Nitro on each
                # invocation. 0.2 keeps a touch of variety while
                # anchoring on the highest-likelihood medchem moves.
                "temperature": 0.2,
                "topP": 0.85,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingBudget": 1024, "includeThoughts": False},
            },
        }
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.post(url,
                              headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json=payload)
        if r.status_code != 200:
            log.warning("harden gemini http %s: %s", r.status_code, r.text[:240])
            return []
        d = r.json()
        cands = d.get("candidates") or []
        if not cands:
            return []
        parts = (cands[0].get("content") or {}).get("parts") or []
        if not parts:
            return []
        raw = (parts[0].get("text") or "").strip()
        # Robust JSON extraction: try direct, then strip code fences,
        # then find first {...} balanced block.
        obj = _safe_json(raw)
        if obj is None:
            log.warning("harden gemini parse failed; raw start: %r", raw[:200])
            return []
        items = obj.get("suggestions") if isinstance(obj, dict) else None
        if not isinstance(items, list):
            return []

        # Validate each suggestion through RDKit when proposed_smiles is given
        out: list[dict[str, Any]] = []
        for i, it in enumerate(items[:n]):
            if not isinstance(it, dict):
                continue
            swap = str(it.get("swap") or "").strip()
            rationale = str(it.get("rationale") or "").strip()
            mech = str(it.get("mechanism") or "").strip().lower()
            prop_smi = str(it.get("proposed_smiles") or "").strip()
            try:
                pdelta = float(it.get("predicted_robustness_delta", 0.0))
            except Exception:
                pdelta = 0.0
            if not swap:
                continue
            smi_valid = _smiles_valid(prop_smi) if prop_smi else None
            # Confidence factors: mechanism-specific feasibility + predicted
            # delta + smiles validity (when given) + slight bonus for not
            # being the top mechanism (mechanism diversity).
            mech_feasible = _atom_mechanism_feasibility(smiles, target_atom["atom_idx"], mech)
            base = 0.55 + 0.25 * mech_feasible + 0.15 * min(1.0, max(0.0, pdelta * 2.0))
            if prop_smi:
                base += 0.05 if smi_valid else -0.10
            confidence = round(min(0.95, max(0.30, base)), 3)
            out.append({
                "swap": swap[:80],
                "rationale": rationale[:240],
                "source": "gemini",
                "confidence": confidence,
                "rank": i + 1,
                "mechanism": mech or "unknown",
                "proposed_smiles": prop_smi[:200],
                "proposed_smiles_valid": smi_valid,
                "predicted_robustness_delta": round(pdelta, 3),
                "_factors": {
                    "mech_feasible": round(mech_feasible, 3),
                    "predicted_delta": round(pdelta, 3),
                    "smiles_validated": bool(smi_valid),
                    "rank": i + 1,
                },
            })
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("harden gemini multi failed: %s", exc)
        return []


def _safe_json(raw: str) -> Optional[dict]:
    """Best-effort JSON parse: tries direct, code-fenced, and brace-balanced
    extraction so reasoning models with prose preamble don't break us."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Strip ```json fences
    t = raw.strip()
    if t.startswith("```"):
        t = t.lstrip("`")
        if t.startswith("json"):
            t = t[4:]
        t = t.strip().rstrip("`").strip()
        try:
            return json.loads(t)
        except Exception:
            pass
    # Find first balanced { ... }
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except Exception:
                    return None
    return None


def _atom_environment_string(smiles: str, idx: int) -> str:
    """Human-readable description of the atom's local environment for the LLM:
    element, hybridization, aromaticity, ring membership, neighbours, valence."""
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        if mol is None or idx < 0 or idx >= mol.GetNumAtoms():
            return f"atom_{idx}"
        a = mol.GetAtomWithIdx(idx)
        nbrs = [
            f"{n.GetSymbol()}({mol.GetBondBetweenAtoms(idx, n.GetIdx()).GetBondTypeAsDouble():.1f})"
            for n in a.GetNeighbors()
        ]
        return (
            f"{a.GetSymbol()} {a.GetHybridization()} "
            f"{'aromatic ' if a.GetIsAromatic() else ''}"
            f"{'in-ring ' if a.IsInRing() else ''}"
            f"degree={a.GetDegree()} "
            f"freeH={a.GetNumImplicitHs() + a.GetNumExplicitHs()} "
            f"charge={a.GetFormalCharge()} "
            f"neighbours=[{', '.join(nbrs)}]"
        )
    except Exception:
        return f"atom_{idx}"


def _smiles_valid(smi: str) -> bool:
    if not smi:
        return False
    try:
        from rdkit import Chem
        return Chem.MolFromSmiles(smi) is not None
    except Exception:
        return False


def _atom_mechanism_feasibility(smiles: str, idx: int, mech: str) -> float:
    """Mechanism-specific feasibility — does the candidate atom support
    the proposed swap mechanism?
      steric / isosteric → needs free valence (uses _atom_can_substitute)
      electronic         → easier if atom is sp2 or aromatic (resonance)
      conformational     → easier if atom is in a ring
      h-bond             → easier if atom has H or lone pair (N/O)
    """
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        if mol is None or idx < 0 or idx >= mol.GetNumAtoms():
            return 0.5
        a = mol.GetAtomWithIdx(idx)
        if mech in ("steric", "isosteric"):
            return _atom_can_substitute(smiles, idx)
        if mech == "electronic":
            return 1.0 if a.GetIsAromatic() else 0.7 if a.GetHybridization() in (
                Chem.HybridizationType.SP2,) else 0.4
        if mech == "conformational":
            return 1.0 if a.IsInRing() else 0.5
        if mech == "h-bond":
            return 1.0 if a.GetSymbol() in ("N", "O") else 0.4
        return 0.65
    except Exception:
        return 0.5


class CrossTargetRequest(BaseModel):
    smiles: str
    pdb_ids: Optional[list[str]] = None  # default = ALL curated targets


@router.post("/resistance/cross-target")
async def cross_target_risk(req: CrossTargetRequest) -> dict:
    """Run resistance prediction for ONE candidate against MANY targets.

    Useful for broad-spectrum analysis: "is my MRSA-targeting candidate
    also robust if it ends up in E. coli?" The frontend uses this for a
    cross-pathogen risk matrix on the Resistance card.
    """
    targets = req.pdb_ids or list(_CARD.get("by_pdb", {}).keys())
    if not targets:
        raise HTTPException(503, "no curated targets available")
    rows: list[dict[str, Any]] = []
    for pdb in targets[:12]:  # cap to avoid runaway
        pdb = pdb.upper()
        entry = _CARD.get("by_pdb", {}).get(pdb)
        if not entry:
            continue
        try:
            r = await predict_resistance(PredictResistanceRequest(smiles=req.smiles, pdb_id=pdb))
        except HTTPException as exc:
            rows.append({"pdb_id": pdb, "target_name": entry.get("_target", ""),
                         "pathogen": entry.get("_pathogen", ""),
                         "error": str(exc.detail), "valid": False})
            continue
        rows.append({
            "pdb_id": pdb,
            "target_name": r.get("target_name") or entry.get("_target", ""),
            "pathogen": r.get("pathogen") or entry.get("_pathogen", ""),
            "robustness_score": r["robustness_score"],
            "n_escape_vectors": r["n_escape_vectors"],
            "n_residues_with_contacts": r["n_residues_with_contacts"],
            "n_total_known_mutations": r["n_total_known_mutations"],
            "top_drug_classes_at_risk": [
                p["drug_class"] for p in (r.get("drug_class_profile") or [])
                if p.get("max_escape", 0) > 0
            ][:3],
            "valid": True,
        })

    # Aggregate stats
    valid_rows = [r for r in rows if r.get("valid")]
    avg_rob = (
        sum(r["robustness_score"] for r in valid_rows) / len(valid_rows)
        if valid_rows else 0.0
    )
    weakest = (
        min(valid_rows, key=lambda r: r["robustness_score"])["pdb_id"]
        if valid_rows else None
    )
    strongest = (
        max(valid_rows, key=lambda r: r["robustness_score"])["pdb_id"]
        if valid_rows else None
    )
    spectrum = (
        "broad-spectrum" if avg_rob >= 0.7 and len(valid_rows) >= 3
        else "narrow-spectrum" if avg_rob >= 0.5
        else "fragile"
    )
    return {
        "smiles": req.smiles,
        "n_targets": len(rows),
        "rows": rows,
        "avg_robustness": round(avg_rob, 3),
        "weakest_pdb_id": weakest,
        "strongest_pdb_id": strongest,
        "spectrum": spectrum,
    }


class CompareRequest(BaseModel):
    smiles_list: list[str]
    pdb_id: str
    labels: Optional[list[str]] = None


@router.post("/resistance/compare")
async def compare_resistance(req: CompareRequest) -> dict:
    """Run the predict pipeline for N candidates against the same target
    and return a parallel comparison (robustness, vector counts, top
    vulnerable atom, common-residue overlap).

    Used by the new "Compare" mode on the lavender-glass card.
    """
    if not req.smiles_list:
        raise HTTPException(400, "smiles_list is empty")
    if len(req.smiles_list) > 8:
        raise HTTPException(400, "max 8 candidates per compare call")
    pdb_id = req.pdb_id.upper()

    rows: list[dict[str, Any]] = []
    residue_hit_counts: dict[int, int] = {}
    for i, smi in enumerate(req.smiles_list):
        try:
            r = await predict_resistance(PredictResistanceRequest(smiles=smi, pdb_id=pdb_id))
        except HTTPException as exc:
            rows.append({
                "label": (req.labels[i] if req.labels and i < len(req.labels) else f"cand_{i+1}"),
                "smiles": smi, "error": str(exc.detail), "valid": False,
            })
            continue
        # Track residue hits for the "common weak residues" summary
        for c in r.get("clinical_overlap", []):
            pos = c["position"]
            residue_hit_counts[pos] = residue_hit_counts.get(pos, 0) + 1
        rows.append({
            "label": (req.labels[i] if req.labels and i < len(req.labels) else f"cand_{i+1}"),
            "smiles": smi,
            "valid": True,
            "robustness_score": r["robustness_score"],
            "n_escape_vectors": r["n_escape_vectors"],
            "n_residues_with_contacts": r["n_residues_with_contacts"],
            "top_vulnerable_atom": r["vulnerable_atoms"][0] if r["vulnerable_atoms"] else None,
            "n_clinical_overlaps": len(r["clinical_overlap"]),
            "summary": r["summary"],
        })

    # Common weak residues — positions where ≥2 of N candidates share a
    # clinical-overlap mutation. These are the residues the agent should
    # collectively harden against.
    n_valid = sum(1 for r in rows if r.get("valid"))
    common_residues = sorted(
        [
            {"position": pos, "n_candidates": cnt,
             "fraction": (cnt / n_valid) if n_valid else 0.0}
            for pos, cnt in residue_hit_counts.items()
            if cnt >= max(2, n_valid // 2)
        ],
        key=lambda r: -r["n_candidates"],
    )

    return {
        "pdb_id": pdb_id,
        "rows": rows,
        "n": len(req.smiles_list),
        "n_valid": n_valid,
        "common_weak_residues": common_residues,
        "best_idx": (
            max(range(len(rows)), key=lambda i: rows[i].get("robustness_score") or -1)
            if any(r.get("valid") for r in rows) else None
        ),
    }


class ExplainRequest(BaseModel):
    smiles: str
    pdb_id: str
    session_id: Optional[str] = None


@router.post("/resistance/explain")
async def explain_resistance(req: ExplainRequest) -> dict:
    """Plain-language explanation of why this candidate is robust /
    vulnerable, suitable for the agent reasoning panel."""
    pred = await predict_resistance(PredictResistanceRequest(smiles=req.smiles, pdb_id=req.pdb_id))
    rationale = await _llm_explain(pred)
    if not rationale:
        rationale = _heuristic_explain(pred)
    out = {"pdb_id": pred["pdb_id"], "smiles": pred["smiles"],
           "robustness_score": pred["robustness_score"],
           "n_escape_vectors": pred["n_escape_vectors"],
           "explanation": rationale}
    if req.session_id:
        try:
            from workspace.playground.bus import get_bus
            get_bus().publish(req.session_id, {
                "event": "resistance.explained", "smiles": req.smiles,
                "pdb_id": pred["pdb_id"],
                "robustness_score": pred["robustness_score"],
                "n_escape_vectors": pred["n_escape_vectors"],
                "explanation": rationale,
            })
        except Exception:
            pass
    return out


def _heuristic_explain(pred: dict) -> str:
    if not pred["vulnerable_atoms"]:
        return (f"This candidate is {pred['robustness_score']:.2f}-robust against "
                f"{pred['n_total_known_mutations']} curated clinical mutations on "
                f"{pred['target_name']}. No atom is exposed to a known escape vector "
                f"above the 0.30 threshold.")
    top = pred["vulnerable_atoms"][0]
    m = top["top_mutation"]
    return (f"Vulnerability driver: ligand atom {top['atom_idx']} is exposed to "
            f"{m['wt']}{m['position']}{m['mutant']} ({m['drug_class']}, "
            f"freq={m['frequency']}). Escape score {top['escape_score']:.2f} — "
            f"consider a substituent swap at atom {top['atom_idx']} to break "
            f"this contact. Overall robustness {pred['robustness_score']:.2f}.")


async def _llm_explain(pred: dict) -> Optional[str]:
    import os as _os
    key = _os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    model_id = _os.getenv("LYSOS_EXPLAIN_GEMINI_MODEL", "gemini-2.5-flash")
    bullet_lines = []
    for v in pred["vulnerable_atoms"][:5]:
        m = v["top_mutation"]
        bullet_lines.append(f"  - atom {v['atom_idx']}: {m['wt']}{m['position']}{m['mutant']} "
                            f"({m.get('drug_class', 'unknown')}, escape={v['escape_score']:.2f})")
    bullets = "\n".join(bullet_lines) or "  - (none)"
    prompt = (
        "You are an antimicrobial medchem reviewer. In 3-4 short sentences "
        "(≤350 chars total), explain this candidate's resistance profile so a "
        "lead chemist understands BOTH the strengths and the weakness vectors.\n\n"
        f"SMILES: {pred['smiles']}\n"
        f"Target: {pred['target_name']} ({pred['pdb_id']}), pathogen {pred['pathogen']}\n"
        f"Robustness score: {pred['robustness_score']:.2f} (1.0 = fully robust)\n"
        f"Escape vectors above 0.30: {pred['n_escape_vectors']}\n"
        f"Top vulnerable atoms:\n{bullets}\n\n"
        "Output plain text only — no JSON, no markdown."
    )
    try:
        import httpx
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 512, "temperature": 0.3,
                "responseMimeType": "text/plain",
            },
        }
        async with httpx.AsyncClient(timeout=10.0) as cx:
            r = await cx.post(url,
                              headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json=payload)
        if r.status_code != 200:
            return None
        d = r.json()
        cands = d.get("candidates") or []
        if not cands:
            return None
        parts = (cands[0].get("content") or {}).get("parts") or []
        if not parts:
            return None
        return (parts[0].get("text") or "").strip()[:600] or None
    except Exception as exc:  # noqa: BLE001
        log.debug("explain gemini failed: %s", exc)
        return None


def _broadcast_resistance(result: dict) -> None:
    """Publish a resistance.predicted event so agent listeners + replay
    pick it up. We don't gate on a session id — the bus is fan-out and a
    no-op if nobody's subscribed.
    """
    try:
        # Active sessions: publish to all known channels for fan-out.
        from workspace.playground.bus import get_bus
        bus = get_bus()
        ev = {
            "event": "resistance.predicted",
            "pdb_id": result["pdb_id"],
            "smiles": result["smiles"],
            "robustness_score": result["robustness_score"],
            "n_escape_vectors": result["n_escape_vectors"],
            "vulnerable_atoms": result["vulnerable_atoms"][:3],
        }
        for sid in list(getattr(bus, "_channels", {}).keys()):
            try:
                bus.publish(sid, dict(ev))
            except Exception:
                continue
    except Exception:
        pass
