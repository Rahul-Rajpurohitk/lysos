"""Tests for the Pareto-trap detector in scripts/mine_hard_negatives.py.

Synthesizes a candidate score matrix that has a clear Pareto trap and
verifies the miner picks it as a (chosen, rejected) pair with the right
axis labels.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_quartile_mask_basic():
    from mine_hard_negatives import _quartile_mask
    arr = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    high = _quartile_mask(arr, q=0.75, above=True)
    assert high.sum() == 2  # top quartile = top 2
    low = _quartile_mask(arr, q=0.25, above=False)
    assert low.sum() == 2


def test_pareto_trap_detection():
    """Synthetic K=8 candidates. Plant a clear trap on (predicted_mic high,
    hemolysis_safety low) and verify the miner picks it."""
    from mine_hard_negatives import find_pairs_for_prompt, REWARD_COMPONENTS

    # K=8, C=12. Candidate 7 = clear trap (mic=0.9 high, hemolysis=0.05 low).
    # Candidate 0 = balanced (high composite, mic=0.6, hemolysis=0.7).
    np.random.seed(0)
    K = 8
    C = len(REWARD_COMPONENTS)
    scores = np.random.uniform(0.3, 0.6, size=(K, C)).astype(np.float32)
    weights = np.ones(C, dtype=np.float32) / C

    # Index of components we plant:
    mic_i = REWARD_COMPONENTS.index("predicted_mic")
    hemo_i = REWARD_COMPONENTS.index("hemolysis_safety")

    # Trap candidate
    scores[7, mic_i] = 0.95
    scores[7, hemo_i] = 0.05
    # Balanced winner
    scores[0, :] = 0.7
    scores[0, mic_i] = 0.6
    scores[0, hemo_i] = 0.7

    candidates = [f"PROPOSAL: SMILES: CCC{i}" for i in range(K)]
    pairs = find_pairs_for_prompt(
        prompt="design MRSA",
        candidates=candidates,
        scores=scores,
        component_names=REWARD_COMPONENTS,
        weights=weights,
        max_pairs_per_axis=2,
    )

    # We expect at least one pair on the (predicted_mic, hemolysis_safety) axis
    mic_hemo_pairs = [p for p in pairs
                      if p.hard_axis_x == "predicted_mic"
                      and p.hard_axis_y == "hemolysis_safety"]
    assert len(mic_hemo_pairs) >= 1, "miner should detect the planted trap"

    # The rejected should be candidate 7 (the trap), chosen should be balanced.
    p = mic_hemo_pairs[0]
    assert p.rejected.endswith("CCC7"), f"rejected should be candidate 7, got {p.rejected}"
    # gap_y > 0 means chosen has higher hemolysis_safety than rejected
    assert p.gap_y > 0, f"gap_y should be positive, got {p.gap_y}"


def test_no_pairs_when_no_trap():
    """If all candidates are equally balanced, no pairs should fire."""
    from mine_hard_negatives import find_pairs_for_prompt, REWARD_COMPONENTS

    K = 8
    C = len(REWARD_COMPONENTS)
    scores = np.full((K, C), 0.5, dtype=np.float32)  # all equal
    weights = np.ones(C, dtype=np.float32) / C
    candidates = [f"PROPOSAL: SMILES: C{i}" for i in range(K)]
    pairs = find_pairs_for_prompt(
        prompt="x",
        candidates=candidates,
        scores=scores,
        component_names=REWARD_COMPONENTS,
        weights=weights,
        max_pairs_per_axis=2,
    )
    # With identical scores, no candidate is "high X, low Y" — should be 0 pairs
    # (or at most ties broken by index, but the chosen/rejected check will dedup)
    for p in pairs:
        assert p.gap_x != 0 or p.gap_y != 0, (
            f"degenerate pair: gap_x={p.gap_x}, gap_y={p.gap_y}"
        )


def test_smiles_dedup():
    """If chosen and rejected have the same SMILES, drop the pair."""
    from mine_hard_negatives import find_pairs_for_prompt, REWARD_COMPONENTS

    K = 4
    C = len(REWARD_COMPONENTS)
    scores = np.array([
        [0.9] * C,                         # candidate 0 — high all
        [0.1] * C,                         # candidate 1 — low all
        [0.9] * C,                         # candidate 2 — duplicate of 0
        [0.5] * C,                         # candidate 3 — middle
    ], dtype=np.float32)
    # Force trap structure manually: candidate 0 high mic, low hemolysis
    mic_i = REWARD_COMPONENTS.index("predicted_mic")
    hemo_i = REWARD_COMPONENTS.index("hemolysis_safety")
    scores[1, mic_i] = 0.95
    scores[1, hemo_i] = 0.05  # candidate 1 is the trap

    weights = np.ones(C, dtype=np.float32) / C
    # Same SMILES on multiple candidates — should be deduped.
    candidates = [
        "PROPOSAL: SMILES: CCO",   # 0
        "PROPOSAL: SMILES: CC",    # 1 (trap)
        "PROPOSAL: SMILES: CCO",   # 2 (dup of 0)
        "PROPOSAL: SMILES: CCC",   # 3
    ]
    pairs = find_pairs_for_prompt(
        prompt="x",
        candidates=candidates,
        scores=scores,
        component_names=REWARD_COMPONENTS,
        weights=weights,
        max_pairs_per_axis=2,
    )
    # No same-SMILES pair should appear in the output
    for p in pairs:
        assert p.chosen_smiles != p.rejected_smiles or p.chosen_smiles is None
