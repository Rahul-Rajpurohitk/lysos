"""Chemistry pareto services — Service 3: Multi-Candidate Pareto Lab.

Endpoints:
  GET  /chem/session/{sid}/candidates         all candidates with score axes
  GET  /chem/session/{sid}/pareto             Pareto frontier on selected axes

Why this exists
  Without a Pareto view, agents can spawn 20 candidates over a session
  and you can't tell exploring from wandering. The Pareto frontier shows
  WHICH candidates are dominant on the chosen axis pair, so the user
  (and Strategist agent) can detect "we have 3 Pareto-optimal already,
  TERMINATE" or "no Pareto improvement in 5 iterations, BRANCH".

Defaults: x = predicted_mic (lower is better — flipped to "1 - mic_norm"),
          y = composite_reward (higher is better)
Optional axes from any score component or property.

Algorithm
  Standard 2D Pareto: a point P dominates Q iff P >= Q on both axes
  AND P > Q on at least one. Pareto-optimal set = points not dominated
  by any other.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger("api.chem_pareto")
router = APIRouter(prefix="/chem", tags=["chem_pareto"])


# Axis registry — name → (description, "higher_better" | "lower_better", source)
# source = "composite" | components.<key> | properties.<key>
AXIS_REGISTRY: dict[str, dict[str, str]] = {
    "composite_reward": {
        "label": "Composite reward",
        "direction": "higher_better",
        "source": "composite",
        "unit": "0-1",
    },
    "predicted_mic": {
        "label": "Predicted MIC",
        "direction": "higher_better",  # we store mic-likeness (higher = lower MIC = better)
        "source": "components.predicted_mic",
        "unit": "0-1",
    },
    "drug_likeness_qed": {
        "label": "QED (drug-likeness)",
        "direction": "higher_better",
        "source": "components.drug_likeness_qed",
        "unit": "0-1",
    },
    "synthesizability": {
        "label": "Synthesizability",
        "direction": "higher_better",  # 1 - sa_score normalized
        "source": "components.synthesizability",
        "unit": "0-1",
    },
    "novelty": {
        "label": "Novelty (vs known antibiotics)",
        "direction": "higher_better",
        "source": "components.novelty",
        "unit": "0-1",
    },
    "hemolysis_safety": {
        "label": "Hemolysis safety",
        "direction": "higher_better",
        "source": "components.hemolysis_safety",
        "unit": "0-1",
    },
    "validity": {
        "label": "Structural validity",
        "direction": "higher_better",
        "source": "components.validity",
        "unit": "0-1",
    },
    "structural_alerts": {
        "label": "Free of structural alerts",
        "direction": "higher_better",
        "source": "components.structural_alerts",
        "unit": "0-1",
    },
    "boltz2_pose_conf": {
        "label": "Boltz-2 pose confidence",
        "direction": "higher_better",
        "source": "components.boltz2_pose_conf",
        "unit": "0-1",
    },
    "binding_affinity": {
        "label": "Binding affinity",
        "direction": "higher_better",
        "source": "components.binding_affinity",
        "unit": "0-1",
    },
}


def _resolve_value(score_row: Optional[dict], axis: str) -> Optional[float]:
    """Resolve an axis value from a score snapshot."""
    if not score_row:
        return None
    spec = AXIS_REGISTRY.get(axis)
    if not spec:
        return None
    src = spec["source"]
    if src == "composite":
        v = score_row.get("composite")
    elif src.startswith("components."):
        key = src.split(".", 1)[1]
        v = (score_row.get("components") or {}).get(key)
    else:
        v = None
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


@router.get("/session/{sid}/axes")
async def list_axes() -> dict:
    """Return the axis registry for the Pareto Lab axis pickers."""
    return {
        "axes": {k: {**v} for k, v in AXIS_REGISTRY.items()},
    }


@router.get("/session/{sid}/candidates")
async def list_candidates(sid: str) -> dict:
    """Return all candidates from a session with their latest score axes."""
    from workspace.playground.store import get_store
    store = get_store()
    mols = store.list_session_molecules(sid)
    out = []
    for m in mols:
        mid = m.get("id")
        score = store.latest_score(mid)
        axes_values: dict[str, Optional[float]] = {}
        for axis_name in AXIS_REGISTRY:
            axes_values[axis_name] = _resolve_value(score, axis_name)
        out.append({
            "id": mid,
            "smiles": m.get("smiles"),
            "parent_id": m.get("parent_id"),
            "created_by": m.get("created_by"),
            "role": m.get("role"),
            "ts": m.get("ts") or m.get("created_at"),
            "axes": axes_values,
            "composite": score.get("composite") if score else None,
        })
    return {
        "session_id": sid,
        "n": len(out),
        "candidates": out,
    }


def _compute_pareto(points: list[tuple[int, float, float]],
                    x_higher_better: bool, y_higher_better: bool) -> list[int]:
    """Return indices of Pareto-optimal points.
    points: [(idx, x, y)] — idx is the candidate's position in the input array.
    A point P dominates Q iff P >= Q on both axes (in the user's sense)
    AND P > Q on at least one.
    """
    def better_or_equal(a: float, b: float, higher_better: bool) -> bool:
        return a >= b if higher_better else a <= b

    def strictly_better(a: float, b: float, higher_better: bool) -> bool:
        return a > b if higher_better else a < b

    pareto: list[int] = []
    for i, (idx_i, xi, yi) in enumerate(points):
        dominated = False
        for j, (idx_j, xj, yj) in enumerate(points):
            if i == j:
                continue
            if (better_or_equal(xj, xi, x_higher_better)
                and better_or_equal(yj, yi, y_higher_better)
                and (strictly_better(xj, xi, x_higher_better)
                     or strictly_better(yj, yi, y_higher_better))):
                dominated = True
                break
        if not dominated:
            pareto.append(idx_i)
    return pareto


@router.get("/session/{sid}/pareto")
async def session_pareto(sid: str,
                         x: str = "predicted_mic",
                         y: str = "composite_reward") -> dict:
    """Compute Pareto frontier for the session's candidates on selected axes.

    Returns:
      all_points: every candidate with x/y values + on_pareto flag
      pareto_set: list of candidate IDs on the frontier
      x_axis_meta / y_axis_meta: axis registry entries for the picked axes
      stats: n_total, n_pareto, n_with_scores
    """
    if x not in AXIS_REGISTRY:
        raise HTTPException(400, f"unknown x axis: {x} (valid: {list(AXIS_REGISTRY)})")
    if y not in AXIS_REGISTRY:
        raise HTTPException(400, f"unknown y axis: {y} (valid: {list(AXIS_REGISTRY)})")

    candidates = (await list_candidates(sid))["candidates"]

    # Filter to candidates that have BOTH axis values
    valid_points: list[tuple[int, float, float]] = []
    for i, c in enumerate(candidates):
        xv = c["axes"].get(x)
        yv = c["axes"].get(y)
        if xv is None or yv is None:
            continue
        valid_points.append((i, xv, yv))

    x_higher_better = AXIS_REGISTRY[x]["direction"] == "higher_better"
    y_higher_better = AXIS_REGISTRY[y]["direction"] == "higher_better"

    pareto_indices = set(_compute_pareto(valid_points, x_higher_better, y_higher_better))

    all_points = []
    for i, c in enumerate(candidates):
        xv = c["axes"].get(x)
        yv = c["axes"].get(y)
        all_points.append({
            "candidate_id": c["id"],
            "smiles": c["smiles"],
            "created_by": c["created_by"],
            "parent_id": c["parent_id"],
            "x_value": xv,
            "y_value": yv,
            "on_pareto": i in pareto_indices,
            "valid": xv is not None and yv is not None,
        })

    pareto_candidate_ids = [candidates[i]["id"] for i in pareto_indices]

    return {
        "session_id": sid,
        "x_axis": x,
        "y_axis": y,
        "x_axis_meta": AXIS_REGISTRY[x],
        "y_axis_meta": AXIS_REGISTRY[y],
        "all_points": all_points,
        "pareto_set": pareto_candidate_ids,
        "stats": {
            "n_total": len(candidates),
            "n_with_scores": len(valid_points),
            "n_pareto": len(pareto_indices),
        },
    }
