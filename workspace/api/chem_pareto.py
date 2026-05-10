"""Chemistry pareto services — Service 3: Multi-Candidate Pareto Lab.

Endpoints:
  GET  /chem/session/{sid}/candidates         all candidates with score axes
  GET  /chem/session/{sid}/pareto             Pareto frontier on selected axes
  GET  /chem/session/{sid}/pareto/multi       multiple axis pairs in one call
  POST /chem/session/{sid}/pareto/explain     Gemini explanation of dominator
  POST /chem/session/{sid}/pareto/score-missing   kick agent scoring on unscored
  POST /chem/session/{sid}/pareto/compare     side-by-side N candidates (table)

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
from typing import Optional

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

    out = {
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
    _emit_frontier_event(sid, out)
    return out


# ─────────────────────────────────────────────────────────────────────
# Multi-pane / explain / score-missing / compare additions
# (powers the new lavender-glass Pareto Lab card)
# ─────────────────────────────────────────────────────────────────────


_DEFAULT_PAIRS: list[tuple[str, str]] = [
    ("predicted_mic", "composite_reward"),
    ("drug_likeness_qed", "synthesizability"),
    ("novelty", "predicted_mic"),
    ("hemolysis_safety", "drug_likeness_qed"),
]


@router.get("/session/{sid}/pareto/multi")
async def session_pareto_multi(sid: str) -> dict:
    """Compute the Pareto frontier for a fixed list of axis pairs in one
    round-trip — the frontend uses this for the 2x2 multi-axis matrix
    view so we don't fan out N requests on mount.
    """
    panels = []
    for x, y in _DEFAULT_PAIRS:
        try:
            data = await session_pareto(sid, x=x, y=y)
        except HTTPException:
            continue
        panels.append({
            "x": x, "y": y,
            "x_axis_meta": data["x_axis_meta"],
            "y_axis_meta": data["y_axis_meta"],
            "all_points": data["all_points"],
            "pareto_set": data["pareto_set"],
            "stats": data["stats"],
        })
    return {"session_id": sid, "panels": panels}


class CompareRequest(BaseModel):
    candidate_ids: list[str]


@router.post("/session/{sid}/pareto/compare")
async def session_pareto_compare(sid: str, req: CompareRequest) -> dict:
    """Side-by-side row-wise comparison across all known axes for the
    selected candidate IDs. UI renders this as a horizontally-scrollable
    parallel-coordinates table.
    """
    if not req.candidate_ids:
        raise HTTPException(400, "candidate_ids required")
    if len(req.candidate_ids) > 5:
        raise HTTPException(400, "max 5 candidates per compare")
    listing = await list_candidates(sid)
    by_id = {c["id"]: c for c in listing["candidates"]}
    rows = []
    for cid in req.candidate_ids:
        c = by_id.get(cid)
        if c is None:
            rows.append({"id": cid, "found": False})
            continue
        rows.append({
            "id": cid, "found": True,
            "smiles": c["smiles"], "created_by": c["created_by"],
            "axes": c["axes"], "composite": c["composite"],
        })
    # Per-axis winner — the candidate with the best value on each axis.
    winners: dict[str, Optional[str]] = {}
    for axis_name, spec in AXIS_REGISTRY.items():
        higher = spec["direction"] == "higher_better"
        best_val = None
        best_id = None
        for r in rows:
            if not r.get("found"):
                continue
            v = r["axes"].get(axis_name)
            if v is None:
                continue
            if best_val is None or (higher and v > best_val) or (not higher and v < best_val):
                best_val, best_id = v, r["id"]
        winners[axis_name] = best_id
    return {"session_id": sid, "rows": rows, "winners": winners}


class ExplainRequest(BaseModel):
    candidate_id: str
    x_axis: str = "predicted_mic"
    y_axis: str = "composite_reward"


@router.post("/session/{sid}/pareto/explain")
async def session_pareto_explain(sid: str, req: ExplainRequest) -> dict:
    """Gemini-powered explanation of WHY a candidate dominates / fails to
    dominate the rest of the session on the picked axes."""
    pareto = await session_pareto(sid, x=req.x_axis, y=req.y_axis)
    target = next((p for p in pareto["all_points"] if p["candidate_id"] == req.candidate_id), None)
    if target is None:
        raise HTTPException(404, f"candidate {req.candidate_id} not in session")
    rationale = await _llm_explain_pareto(pareto, target)
    if not rationale:
        rationale = _heuristic_explain_pareto(pareto, target)
    out = {"session_id": sid, "candidate_id": req.candidate_id,
           "smiles": target["smiles"], "on_pareto": target["on_pareto"],
           "x_axis": req.x_axis, "y_axis": req.y_axis,
           "x_value": target["x_value"], "y_value": target["y_value"],
           "explanation": rationale}
    try:
        from workspace.playground.bus import get_bus
        get_bus().publish(sid, {
            "event": "pareto.explained", "candidate_id": req.candidate_id,
            "smiles": target["smiles"], "on_pareto": target["on_pareto"],
            "explanation": rationale,
        })
    except Exception:
        pass
    return out


def _heuristic_explain_pareto(pareto: dict, target: dict) -> str:
    if target["on_pareto"]:
        return (f"This candidate sits ON the Pareto frontier for "
                f"{pareto['x_axis_meta']['label']} vs "
                f"{pareto['y_axis_meta']['label']}. It is non-dominated — "
                f"no other candidate is better on both axes simultaneously.")
    # Find a dominator
    px = target["x_value"]
    py = target["y_value"]
    if px is None or py is None:
        return ("Candidate has no scores on the selected axes yet — kick "
                "the scoring pipeline to evaluate it.")
    for o in pareto["all_points"]:
        if o["candidate_id"] == target["candidate_id"]:
            continue
        if o["x_value"] is None or o["y_value"] is None:
            continue
        if o["x_value"] >= px and o["y_value"] >= py and (o["x_value"] > px or o["y_value"] > py):
            return (f"Dominated by candidate {o['candidate_id'][:10]}…: it scores "
                    f"{pareto['x_axis_meta']['label']}={o['x_value']:.3f} (vs "
                    f"{px:.3f}) and {pareto['y_axis_meta']['label']}="
                    f"{o['y_value']:.3f} (vs {py:.3f}).")
    return "Status undetermined — heuristic did not find a strict dominator."


async def _llm_explain_pareto(pareto: dict, target: dict) -> Optional[str]:
    import os as _os
    key = _os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    model_id = _os.getenv("LYSOS_PARETO_GEMINI_MODEL", "gemini-2.5-flash")
    others = [p for p in pareto["all_points"] if p["candidate_id"] != target["candidate_id"]
              and p["x_value"] is not None and p["y_value"] is not None][:6]
    other_lines = "\n".join(
        f"  - {p['candidate_id'][:10]} ({p['created_by']}): "
        f"{pareto['x_axis']}={p['x_value']:.3f}, {pareto['y_axis']}={p['y_value']:.3f}"
        f"{' [PARETO]' if p['on_pareto'] else ''}"
        for p in others
    ) or "  - (no others)"
    prompt = (
        "You are a multi-objective optimization reviewer. Explain in 2-3 sentences "
        "(≤300 chars) why this candidate is or is not Pareto-optimal among the "
        "session below. Be concrete — name a dominator candidate id by prefix.\n\n"
        f"Target candidate {target['candidate_id'][:10]} ({target['created_by']}):\n"
        f"  - {pareto['x_axis']} = {target['x_value']}\n"
        f"  - {pareto['y_axis']} = {target['y_value']}\n"
        f"  - on_pareto = {target['on_pareto']}\n\n"
        f"Other candidates:\n{other_lines}\n\n"
        "Plain text only."
    )
    try:
        import httpx
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 384, "temperature": 0.3,
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
        log.debug("pareto explain gemini failed: %s", exc)
        return None


@router.post("/session/{sid}/pareto/score-missing")
async def session_pareto_score_missing(sid: str) -> dict:
    """Compute and persist scores for every candidate in the session
    that doesn't have one yet. End-to-end: runs the same RDKit-based
    reward stack that the harness uses (validity, predicted_mic, QED,
    SA, hemolysis, novelty, structural_alerts), composes a weighted
    composite, persists to playground store, and emits a score.applied
    event so live consumers refresh.
    """
    from workspace.playground.store import get_store, ScoreSnapshot
    from workspace.playground.bus import get_bus
    from .sandbox import _score_smiles
    import time
    import uuid

    store = get_store()
    listing = await list_candidates(sid)
    missing = [c for c in listing["candidates"] if c.get("composite") is None]

    # Identify the session's pathogen — drives the predicted_mic kernel.
    target_pathogen = "MRSA"
    try:
        sess = store.get_session(sid) if hasattr(store, "get_session") else None
        if sess and sess.get("target_pathogen"):
            target_pathogen = sess["target_pathogen"]
    except Exception:
        pass

    # Equal-weight composite across the 7 components above. The exact
    # weights are kept symmetric so per-axis bars on the radar still
    # read directly off `components`. The harness uses the same stack.
    WEIGHTS = {
        "validity": 0.10,
        "predicted_mic": 0.25,
        "drug_likeness_qed": 0.15,
        "synthesizability": 0.10,
        "hemolysis_safety": 0.10,
        "novelty": 0.15,
        "structural_alerts": 0.15,
    }

    scored: list[dict[str, Any]] = []
    bus = get_bus()
    for c in missing:
        smi = c["smiles"]
        try:
            comps = _score_smiles(smi, target_pathogen)
            comps_f = {k: float(comps.get(k, 0.0)) for k in WEIGHTS}
            composite = sum(comps_f[k] * w for k, w in WEIGHTS.items())
            sorted_axes = sorted(comps_f.items(), key=lambda kv: kv[1])
            weakest = sorted_axes[0][0] if sorted_axes else ""
            strongest = sorted_axes[-1][0] if sorted_axes else ""
            snap = ScoreSnapshot(
                id=uuid.uuid4().hex[:12],
                molecule_id=c["id"],
                ts=time.time(),
                composite=round(composite, 4),
                components={k: round(v, 4) for k, v in comps_f.items()},
                weakest=weakest, strongest=strongest,
                model_used="reward_stack_v1",
            )
            store.append_score(snap)
            scored.append({
                "id": c["id"], "smiles": smi,
                "composite": snap.composite,
                "components": snap.components,
            })
            # Live event so the Pareto card / radar refresh in real-time
            bus.publish(sid, {
                "event": "score.applied",
                "candidate_id": c["id"],
                "smiles": smi,
                "composite": snap.composite,
                "components": snap.components,
                "weakest": weakest,
                "strongest": strongest,
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("score-missing failed for %s: %s", c["id"], exc)
            continue

    return {
        "session_id": sid,
        "n_candidates": len(listing["candidates"]),
        "n_missing": len(missing),
        "n_scored": len(scored),
        "scored": scored,
        "target_pathogen": target_pathogen,
    }


def _emit_frontier_event(sid: str, pareto_out: dict) -> None:
    """Publish a `pareto.frontier_changed` event with the current frontier
    membership so agent listeners can detect "we have N Pareto-optimal,
    TERMINATE" triggers. We also tag the axes used so the listener can
    distinguish frontier-on-MIC-vs-QED from frontier-on-novelty-vs-MIC."""
    try:
        from workspace.playground.bus import get_bus
        get_bus().publish(sid, {
            "event": "pareto.frontier_changed",
            "x_axis": pareto_out["x_axis"],
            "y_axis": pareto_out["y_axis"],
            "n_total": pareto_out["stats"]["n_total"],
            "n_pareto": pareto_out["stats"]["n_pareto"],
            "pareto_set": pareto_out["pareto_set"],
        })
    except Exception:
        pass
