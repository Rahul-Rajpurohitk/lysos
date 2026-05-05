"""Reward: Synthetic Accessibility — SAscore + AiZynthFinder route blend.

Two independent signals combined into one [0, 1] reward:

  * SA score (Ertl & Schuffenhauer 2009): cheap RDKit-only heuristic, runs
    on every candidate. 1 (easy) → 10 (hard); inverted to [0, 1].
  * AiZynthFinder cache: real USPTO retrosynthesis route depth + score
    for the top 1000 priority candidates (pre-computed by
    `scripts/run_aizynth_priority_sweep.py`). When a candidate's SMILES
    is in the cache, we BLEND aizynth's signal in.

When the cache lacks the candidate, reward is SA-only. When the cache
hits, reward = 0.6*SA + 0.4*aizynth so the policy gets the
solved-route bonus without losing the SA signal entirely.

This wiring captures the 2+ hours of CPU compute spent populating the
cache. Without it, Stage 3 RL throws that signal away.
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import extract_smiles

log = logging.getLogger(__name__)

# Module-level lazy-loaded AiZynth cache: smiles -> (top_score, depth, n_routes)
_AIZYNTH_CACHE: dict[str, tuple[float, int, int]] | None = None
_AIZYNTH_PATH = "data/processed/aizynth_calibration_cache.parquet"


def _try_load_sa_scorer():
    """SA scorer ships with rdkit-contrib but isn't always on path. Lazy load."""
    try:
        # rdkit-contrib path
        import sys
        from rdkit.Chem import RDConfig
        sa_dir = f"{RDConfig.RDContribDir}/SA_Score"
        if sa_dir not in sys.path:
            sys.path.append(sa_dir)
        import sascorer  # noqa: F401
        return sascorer
    except Exception as exc:  # noqa: BLE001
        log.warning("sascorer not available: %s", exc)
        return None


_SA = _try_load_sa_scorer()


def _load_aizynth_cache(path: str = _AIZYNTH_PATH) -> dict[str, tuple[float, int, int]]:
    """Lazy-load aizynth cache from parquet. Returns {} if not present."""
    global _AIZYNTH_CACHE
    if _AIZYNTH_CACHE is not None:
        return _AIZYNTH_CACHE
    p = Path(path)
    if not p.exists():
        log.info("AiZynth cache not at %s — synth reward uses SAscore only", p)
        _AIZYNTH_CACHE = {}
        return _AIZYNTH_CACHE
    try:
        import pandas as pd
        df = pd.read_parquet(p)
    except Exception as exc:  # noqa: BLE001
        log.warning("AiZynth cache load failed: %s — synth reward uses SAscore only", exc)
        _AIZYNTH_CACHE = {}
        return _AIZYNTH_CACHE
    out: dict[str, tuple[float, int, int]] = {}
    for r in df.to_dict("records"):
        smi = r.get("smiles")
        if not isinstance(smi, str):
            continue
        out[smi] = (
            float(r.get("best_route_score", 0.0) or 0.0),
            int(r.get("best_route_depth", 0) or 0),
            int(r.get("n_routes_found", 0) or 0),
        )
    _AIZYNTH_CACHE = out
    log.info("Loaded %d AiZynth route entries from %s", len(out), p)
    return _AIZYNTH_CACHE


def _aizynth_to_reward(top_score: float, depth: int, n_routes: int) -> float:
    """Map AiZynth route stats to a [0, 1] reward.

    Rationale:
      * top_score in [0, 1] is AiZynth's own quality estimator — use directly.
      * depth: deep routes are harder; penalize >6 steps mildly.
      * n_routes: more found routes = more confidence; cap at 5.
    """
    if n_routes == 0:
        return 0.0
    base = max(0.0, min(1.0, top_score))
    # Step penalty: routes <= 5 steps are pristine; ramp down to 0.5x at depth 12.
    if depth > 5:
        base *= max(0.5, 1.0 - 0.07 * (depth - 5))
    # Confidence weight: 5+ routes = full weight; 1-4 routes = scaled
    confidence = min(1.0, n_routes / 5.0)
    return base * confidence


def sa_score(
    samples: list[str],
    *,
    aizynth_cache_path: str = _AIZYNTH_PATH,
    aizynth_blend: float = 0.4,
    **_,
) -> list[float]:
    """Reward in [0, 1] = (1 - aizynth_blend) * SA + aizynth_blend * AiZynth.

    For candidates NOT in the AiZynth cache, returns SA-only (the AiZynth
    contribution is 0, so the formula collapses to (1-blend)*SA which is
    misleading; we instead return raw SA when no cache hit).

    aizynth_blend=0.4 means: when cache hits, blend 60% SA + 40% AiZynth.
    Set aizynth_blend=0 to disable the cache for an experiment.
    """
    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")

    cache = _load_aizynth_cache(aizynth_cache_path)
    n_cache_hits = 0

    if _SA is None:
        return [_heuristic_synth(s) for s in samples]

    out = []
    for sample in samples:
        smi = extract_smiles(sample)
        if smi is None:
            out.append(0.0)
            continue
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            out.append(0.0)
            continue
        try:
            sa = _SA.calculateScore(mol)
            sa_reward = max(0.0, min(1.0, (10.0 - sa) / 9.0))
        except Exception:  # noqa: BLE001
            out.append(0.0)
            continue

        cache_hit = cache.get(smi)
        if cache_hit is None or aizynth_blend <= 0:
            out.append(sa_reward)
        else:
            n_cache_hits += 1
            ai_reward = _aizynth_to_reward(*cache_hit)
            blended = (1.0 - aizynth_blend) * sa_reward + aizynth_blend * ai_reward
            out.append(max(0.0, min(1.0, blended)))

    if n_cache_hits and len(samples) >= 8:
        log.debug("synth reward: %d/%d AiZynth cache hits in batch",
                  n_cache_hits, len(samples))
    return out


def _heuristic_synth(sample: str) -> float:
    """Cheap fallback if sascorer is missing — based on ring count + size."""
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Descriptors

    RDLogger.DisableLog("rdApp.*")

    smi = extract_smiles(sample)
    if smi is None:
        return 0.0
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return 0.0
    # Penalize: many rings, very high MW, many stereocenters
    n_rings = Descriptors.RingCount(mol) or 0
    mw = Descriptors.MolWt(mol)
    n_stereo = sum(1 for atom in mol.GetAtoms() if atom.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED)
    score = 1.0
    if n_rings > 6:
        score -= 0.2 * (n_rings - 6)
    if mw > 700:
        score -= 0.3
    if n_stereo > 5:
        score -= 0.1 * (n_stereo - 5)
    return max(0.0, min(1.0, score))
