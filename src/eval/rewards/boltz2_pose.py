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
                     target_pathogen: str = "MRSA", fallback: float = 0.5,
                     **_) -> list[float]:
    cache = _load_cache(cache_path)
    out = []
    for s in samples:
        smi = extract_smiles(s)
        if smi is None:
            out.append(0.0)
            continue
        v = cache.get((smi, target_pathogen), fallback)
        out.append(float(v))
    return out
