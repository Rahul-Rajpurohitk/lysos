"""Reward: Boltz-2 3D pose confidence.

Reads a pre-computed cache of (smiles, pathogen) → ipTM scored by Boltz-2.
Cache is populated by scripts/run_boltz2_sweep.py during the calibration
sweep (CPU-bound, run before GRPO).

If a SMILES is not in the cache (most generated molecules won't be), returns
the `fallback` value to avoid penalizing exploration. To make the signal
useful we run a periodic re-sweep on the active candidates discovered during
RL — this turns the reward into a "warm-cache for known-good poses".
"""
from __future__ import annotations

import logging
from pathlib import Path
from . import extract_smiles

log = logging.getLogger(__name__)
_CACHE: dict[tuple[str, str], float] | None = None


def _load_cache(cache_path: str | Path) -> dict[tuple[str, str], float]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    p = Path(cache_path)
    if not p.exists():
        log.warning("Boltz-2 cache not found at %s; returning empty cache", p)
        _CACHE = {}
        return _CACHE
    import pandas as pd
    df = pd.read_parquet(p)
    _CACHE = {(r["smiles"], r["pathogen"]): float(r["ipTM"]) for r in df.to_dict("records")}
    log.info("Loaded %d Boltz-2 pose entries from %s", len(_CACHE), p)
    return _CACHE


def pose_confidence(samples: list[str], cache_path: str = "data/processed/boltz2_poses_cache.parquet",
                     target_pathogen: str = "MRSA", strict: bool = True,
                     **_) -> list[float]:
    """Real Boltz-2 ipTM signal only. NO fallback that degrades reward quality.

    Per project policy: cache must exist and contain entries for the candidates
    being scored. If the cache is empty or doesn't cover this candidate's
    (smiles, pathogen) pair, the component returns 0.0 (no contribution).

    To DISABLE entirely if you don't have Boltz-2 data: set weight=0 in
    configs/stage3_rl_grpo.yaml.
    """
    cache = _load_cache(cache_path)
    if strict and not cache:
        raise RuntimeError(
            f"boltz2_pose_conf: cache at {cache_path} is empty. Either populate "
            f"it via scripts/calibrate_boltz_proxy.py + real Boltz-2, OR set "
            f"weight=0 for this reward component. NO fallbacks per project policy."
        )

    out = []
    n_hits = 0
    for s in samples:
        smi = extract_smiles(s)
        if smi is None:
            out.append(0.0)
            continue
        v = cache.get((smi, target_pathogen))
        if v is None:
            # Real cache miss: return 0.0 (no positive contribution from
            # uncomputed pose). This is NOT a fallback — it's "no signal".
            out.append(0.0)
        else:
            out.append(float(v))
            n_hits += 1
    if strict and n_hits == 0 and len(samples) > 0:
        log.warning(
            "boltz2_pose_conf: 0/%d cache hits for pathogen=%s. The component "
            "will return all zeros for this batch. Run real Boltz-2 sweep on "
            "the active candidates if you want non-zero pose signal.",
            len(samples), target_pathogen,
        )
    return out
