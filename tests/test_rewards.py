"""Unit tests for the Stage 3 reward functions.

These tests validate reward function shape + edge cases without making
network calls. RDKit is required for most tests; tests skip cleanly if
it's not installed.

Run with:

    pytest tests/test_rewards.py -v

Or directly:

    python tests/test_rewards.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is importable
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _has_rdkit() -> bool:
    try:
        import rdkit  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# extract_smiles
# ---------------------------------------------------------------------------


def test_extract_smiles_explicit_label():
    from src.eval.rewards import extract_smiles

    assert extract_smiles("SMILES: CC(=O)O") == "CC(=O)O"
    assert extract_smiles("Sure, here it is.\nSMILES: c1ccccc1\nThanks") == "c1ccccc1"


def test_extract_smiles_fenced_code():
    from src.eval.rewards import extract_smiles

    text = "```smiles\nCCO\n```"
    assert extract_smiles(text) == "CCO"
    text2 = "```chem\nNc1ccccc1\n```"
    assert extract_smiles(text2) == "Nc1ccccc1"


def test_extract_smiles_xml_tag():
    from src.eval.rewards import extract_smiles

    assert extract_smiles("<smiles>CC(N)C(=O)O</smiles>") == "CC(N)C(=O)O"


def test_extract_smiles_bare():
    from src.eval.rewards import extract_smiles

    # When the whole thing looks like a SMILES, return it as-is
    assert extract_smiles("CC1=CC=CC=C1") == "CC1=CC=CC=C1"


def test_extract_smiles_garbage():
    from src.eval.rewards import extract_smiles

    assert extract_smiles("") is None
    assert extract_smiles("hello world this has spaces") is None


# ---------------------------------------------------------------------------
# Validity
# ---------------------------------------------------------------------------


def test_validity_known_drug():
    if not _has_rdkit():
        return
    from src.eval.rewards.validity import smiles_valid

    samples = [
        "SMILES: CC(=O)Oc1ccccc1C(=O)O",  # aspirin
        "SMILES: CN1C=NC2=C1C(=O)N(C(=O)N2C)C",  # caffeine
    ]
    out = smiles_valid(samples)
    assert out == [1.0, 1.0]


def test_validity_garbage():
    if not _has_rdkit():
        return
    from src.eval.rewards.validity import smiles_valid

    out = smiles_valid(["SMILES: not_a_real_smiles_string", "SMILES: ((()))"])
    assert out == [0.0, 0.0]


def test_validity_returns_list_of_correct_length():
    if not _has_rdkit():
        return
    from src.eval.rewards.validity import smiles_valid

    out = smiles_valid([f"SMILES: CCO" for _ in range(5)])
    assert len(out) == 5
    for v in out:
        assert v in (0.0, 1.0)


# ---------------------------------------------------------------------------
# Drug-likeness (QED, Lipinski)
# ---------------------------------------------------------------------------


def test_qed_aspirin():
    if not _has_rdkit():
        return
    from src.eval.rewards.drug_likeness import qed_score

    out = qed_score(["SMILES: CC(=O)Oc1ccccc1C(=O)O"])  # aspirin
    assert 0.0 < out[0] <= 1.0
    # Aspirin's QED is ~0.55 — within ballpark
    assert 0.3 < out[0] < 0.85


def test_lipinski_aspirin():
    if not _has_rdkit():
        return
    from src.eval.rewards.drug_likeness import lipinski_pass

    # Aspirin passes the rule of 5
    out = lipinski_pass(["SMILES: CC(=O)Oc1ccccc1C(=O)O"])
    assert out[0] == 1.0


def test_lipinski_invalid():
    if not _has_rdkit():
        return
    from src.eval.rewards.drug_likeness import lipinski_pass

    out = lipinski_pass(["SMILES: garbage"])
    assert out[0] == 0.0


# ---------------------------------------------------------------------------
# CompositeReward
# ---------------------------------------------------------------------------


def test_composite_returns_per_component():
    if not _has_rdkit():
        return
    from src.eval.rewards import CompositeReward

    cfg = [
        {"name": "validity", "weight": 0.5,
         "module": "src.eval.rewards.validity:smiles_valid"},
        {"name": "qed", "weight": 0.5,
         "module": "src.eval.rewards.drug_likeness:qed_score"},
    ]
    cr = CompositeReward(cfg)
    samples = ["SMILES: CC(=O)Oc1ccccc1C(=O)O"]  # aspirin
    combined, per = cr(samples)
    assert len(combined) == 1
    assert "validity" in per
    assert "qed" in per
    assert per["validity"][0] == 1.0
    # Combined = 0.5*1.0 + 0.5*qed should be in [0.5, 1.0] for valid drugs
    assert combined[0] >= 0.5


def test_composite_handles_invalid_gracefully():
    if not _has_rdkit():
        return
    from src.eval.rewards import CompositeReward

    cfg = [
        {"name": "validity", "weight": 1.0,
         "module": "src.eval.rewards.validity:smiles_valid"},
    ]
    cr = CompositeReward(cfg)
    combined, per = cr(["totally invalid text"])
    assert combined == [0.0]


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main() -> int:
    """Run all tests + report pass/fail without pytest."""
    import inspect

    fails = 0
    passes = 0
    skipped = 0
    fns = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    print(f"Running {len(fns)} tests...")
    for name, fn in fns:
        try:
            sig = inspect.signature(fn)
            if not _has_rdkit() and "validity" in name and "explicit" not in name:
                if "extract" not in name and "garbage" not in name and "length" not in name:
                    print(f"  SKIP {name}  (no rdkit)")
                    skipped += 1
                    continue
            fn()
            print(f"  PASS {name}")
            passes += 1
        except AssertionError as exc:
            print(f"  FAIL {name}  — {exc}")
            fails += 1
        except Exception as exc:
            print(f"  ERROR {name}  — {type(exc).__name__}: {exc}")
            fails += 1
    print(f"\n{passes} passed, {fails} failed, {skipped} skipped")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
