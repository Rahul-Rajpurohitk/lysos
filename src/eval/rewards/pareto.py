"""Reward: pareto_entry — exploration bonus for entering the Pareto frontier.

For each generated candidate, computes the candidate's vector across N
objective dimensions, then checks whether the candidate dominates ANY point
in the running history (or is non-dominated by all history). If new frontier
entry → bonus 1.0; else 0.0.

The history file at `history_path` is read at the start of each batch and
written back after. We append the top-K candidates from each batch.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_HISTORY: dict[str, list[dict]] = {}


def _load_history(history_path: str) -> list[dict]:
    p = Path(history_path)
    if not p.exists():
        return []
    try:
        with p.open() as f:
            return json.load(f)
    except Exception:
        return []


def _save_history(history_path: str, history: list[dict]) -> None:
    p = Path(history_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with p.open("w") as f:
            json.dump(history[-500:], f)  # cap history to last 500 entries
    except Exception as e:
        log.warning("Failed to write pareto history: %s", e)


def _dominates(a: list[float], b: list[float]) -> bool:
    """a dominates b if a is at least as good in all dims and strictly better in one.
    Higher is better for all dims."""
    if any(av < bv for av, bv in zip(a, b)): return False
    return any(av > bv for av, bv in zip(a, b))


def pareto_entry_bonus(samples: list[str],
                        objectives: list[str] | None = None,
                        history_path: str = "./checkpoints/stage3-rl-grpo/pareto_history.json",
                        component_scores: dict[str, list[float]] | None = None,
                        **_) -> list[float]:
    """component_scores: a dict of {objective_name: [score_per_sample]} produced
    by the trainer aggregating other reward components into this one."""
    if not component_scores or not objectives:
        return [0.0] * len(samples)

    n = len(samples)
    history = _load_history(history_path)
    out = []
    new_entries = []

    for i in range(n):
        vec = [component_scores[o][i] for o in objectives if o in component_scores]
        # Is this vec dominated by ANY point in history?
        dominated = any(_dominates(h["vec"], vec) for h in history)
        if not dominated:
            out.append(1.0)
            new_entries.append({"vec": vec, "smiles": samples[i][:200]})
        else:
            out.append(0.0)

    # Append non-dominated new entries to history; keep history finite
    history.extend(new_entries)
    _save_history(history_path, history)
    return out
