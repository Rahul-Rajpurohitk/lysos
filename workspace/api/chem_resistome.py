"""Resistome intelligence — the AMR genome/population layer.

The resistance-escape map (chem_resistance.py) answers a per-MOLECULE
question: which clinical mutations threaten THIS candidate's contacts? This
module answers the population-level question a chemist asks before they even
have a molecule: **for this pathogen + drug class, what does the resistance
landscape look like in the wild?**

It mines the curated CARD subset (66 real clinical resistance mutations,
CC-BY 4.0, across 8 WHO/CDC priority pathogens × 11 targets × 16 drug
classes) into a resistome view:

  * per drug-class: the resistance determinants, their clinical frequency,
    the targets they hit, and a "resistance pressure" score (how hard this
    class is already being defeated in the clinic).
  * per pathogen: the full resistance landscape — which classes still have
    headroom vs which are saturated with resistance.
  * mutation hotspots: positions defeated across multiple classes (the
    catalytic residues you must not depend on).

This is the DeepARG-style "what resistance genes exist for this drug"
intelligence, grounded in real CARD data rather than a black-box predictor.
On a genome input (Act II) a DeepARG/cAMRah model slots in behind the same
contract to call resistance genes from raw sequence.

Mounted /workbench/chem/resistome/*.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

log = logging.getLogger("lysos.resistome")
router = APIRouter(prefix="/chem", tags=["resistome"])

_CARD_PATH = (Path(__file__).resolve().parents[2] / "data" / "curated"
              / "card_resistance_subset.json")

# Clinical-frequency → numeric weight (how prevalent the determinant is).
_FREQ_W = {
    "very_high": 1.0, "high": 0.8, "moderate": 0.55,
    "rare": 0.3, "very_rare": 0.15, "unknown": 0.4,
}


@lru_cache(maxsize=1)
def _card() -> dict[str, Any]:
    try:
        return json.loads(_CARD_PATH.read_text())
    except Exception as exc:  # noqa: BLE001
        log.warning("CARD subset unavailable: %s", exc)
        return {"by_pdb": {}}


def _freq_w(label: str) -> float:
    return _FREQ_W.get((label or "unknown").lower(), 0.4)


# ─────────────────────────────────────────────────────────────────────
# Per-pathogen resistome assembly
# ─────────────────────────────────────────────────────────────────────

def _pathogen_targets(pathogen: str) -> list[tuple[str, dict[str, Any]]]:
    """All (pdb_id, entry) for a pathogen (case-insensitive, alias-tolerant)."""
    bp = _card().get("by_pdb", {})
    p = (pathogen or "").lower().replace(" ", "").replace(".", "")
    out = []
    for pdb, e in bp.items():
        ep = (e.get("_pathogen") or "").lower().replace(" ", "").replace(".", "")
        # tolerant match: "mrsa"⊆"mrsa", "ecoli"⊆"ecoli-cre", etc.
        if p and (p in ep or ep in p or p[:4] == ep[:4]):
            out.append((pdb, e))
    return out


def _build_resistome(pathogen: str) -> dict[str, Any]:
    targets = _pathogen_targets(pathogen)
    if not targets:
        # Fall back to the whole database so the view is never empty.
        targets = list(_card().get("by_pdb", {}).items())
        scope = "all-pathogens (no exact match)"
    else:
        scope = pathogen

    # Aggregate per drug-class.
    classes: dict[str, dict[str, Any]] = {}
    # Mutation hotspots: (pdb, position) → set of drug classes defeated there.
    hotspots: dict[tuple[str, int], dict[str, Any]] = {}
    target_meta: dict[str, dict[str, Any]] = {}

    for pdb, e in targets:
        target_meta[pdb] = {
            "pdb_id": pdb,
            "target": e.get("_target", pdb),
            "pathogen": e.get("_pathogen"),
            "n_mutations": len(e.get("mutations", [])),
        }
        for m in e.get("mutations", []):
            cls = m.get("drug_class", "unknown")
            w = _freq_w(m.get("frequency"))
            c = classes.setdefault(cls, {
                "drug_class": cls, "n_determinants": 0,
                "freq_weight_sum": 0.0, "targets": set(),
                "top_mutations": [],
            })
            c["n_determinants"] += 1
            c["freq_weight_sum"] += w
            c["targets"].add(e.get("_target", pdb))
            c["top_mutations"].append({
                "target": e.get("_target", pdb),
                "mutation": f"{m.get('wt','')}{m.get('position','')}{m.get('mutant','')}",
                "frequency": m.get("frequency"),
                "note": m.get("note", ""),
                "_w": w,
            })
            key = (pdb, m.get("position", 0))
            h = hotspots.setdefault(key, {
                "pdb_id": pdb, "target": e.get("_target", pdb),
                "position": m.get("position"), "wt": m.get("wt"),
                "classes": set(), "max_freq_w": 0.0,
            })
            h["classes"].add(cls)
            h["max_freq_w"] = max(h["max_freq_w"], w)

    # Finalize per-class rows with a resistance-pressure score.
    class_rows = []
    for cls, c in classes.items():
        # Pressure = clinical prevalence × breadth (more high-frequency
        # determinants across more targets = harder class to use).
        pressure = min(1.0, c["freq_weight_sum"] / 3.0
                       + 0.1 * (len(c["targets"]) - 1))
        c["top_mutations"].sort(key=lambda x: -x["_w"])
        band = ("saturated" if pressure >= 0.7 else "pressured"
                if pressure >= 0.4 else "headroom")
        class_rows.append({
            "drug_class": cls,
            "n_determinants": c["n_determinants"],
            "n_targets": len(c["targets"]),
            "targets": sorted(c["targets"]),
            "resistance_pressure": round(pressure, 3),
            "band": band,
            "top_determinants": [
                {k: v for k, v in m.items() if k != "_w"}
                for m in c["top_mutations"][:4]
            ],
        })
    class_rows.sort(key=lambda r: -r["resistance_pressure"])

    # Hotspots defeated across ≥2 classes = the residues you can't rely on.
    hotspot_rows = []
    for h in hotspots.values():
        if len(h["classes"]) >= 2:
            hotspot_rows.append({
                "pdb_id": h["pdb_id"], "target": h["target"],
                "position": h["position"], "wt": h["wt"],
                "n_classes_defeated": len(h["classes"]),
                "classes": sorted(h["classes"]),
                "max_clinical_freq_weight": round(h["max_freq_w"], 2),
            })
    hotspot_rows.sort(key=lambda r: (-r["n_classes_defeated"],
                                     -r["max_clinical_freq_weight"]))

    n_det = sum(r["n_determinants"] for r in class_rows)
    n_high = sum(1 for r in class_rows if r["band"] == "saturated")
    return {
        "pathogen": pathogen,
        "scope": scope,
        "n_targets": len(target_meta),
        "n_drug_classes": len(class_rows),
        "n_determinants": n_det,
        "n_saturated_classes": n_high,
        "targets": list(target_meta.values()),
        "drug_class_landscape": class_rows,
        "mutation_hotspots": hotspot_rows[:10],
        "summary": (
            f"{n_det} clinical resistance determinants across "
            f"{len(class_rows)} drug classes and {len(target_meta)} targets "
            f"for {scope}. {n_high} class(es) are resistance-saturated; "
            f"{len(hotspot_rows)} cross-class mutation hotspot(s) identified."),
        "source": "CARD curated subset (CC-BY 4.0) + literature",
        "note": ("Population-level resistance landscape from real clinical "
                 "mutations — the resistance a drug class faces in the wild, "
                 "before you commit a scaffold."),
    }


# ─────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────

@router.get("/resistome/{pathogen}")
async def resistome(pathogen: str) -> dict[str, Any]:
    """The resistance-landscape view for a pathogen: drug-class pressure,
    mutation hotspots, target coverage."""
    return _build_resistome(pathogen)


@router.get("/resistome")
async def resistome_all() -> dict[str, Any]:
    """Cross-pathogen resistome — every drug class ranked by resistance
    pressure across the whole curated database."""
    return _build_resistome("__all__")


@router.get("/resistome/{pathogen}/drug-class/{drug_class}")
async def resistome_class(pathogen: str, drug_class: str) -> dict[str, Any]:
    """Drill into one drug class for a pathogen."""
    r = _build_resistome(pathogen)
    row = next((c for c in r["drug_class_landscape"]
                if c["drug_class"].lower() == drug_class.lower()), None)
    if row is None:
        raise HTTPException(404, f"no resistance data for class '{drug_class}' "
                                 f"in {pathogen}")
    return {"pathogen": pathogen, **row,
            "note": r["note"], "source": r["source"]}
