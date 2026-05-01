"""Score one SMILES on the full Lysos reward stack — no API needed.

Imports the project's reward modules directly. Useful for offline scoring
without the FastAPI server, or as a verification tool when comparing
generated candidates against known antibiotics.

    python examples/score_smiles.py "CC1(C)SC2C(NC(=O)C(N)c3ccccc3)C(=O)N2C1C(=O)O"   # ampicillin
    python examples/score_smiles.py --target Mtb "CN1CCN(c2nc3ccc(F)cc3c(=O)c2C(=O)O)CC1"  # ciprofloxacin
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.eval.rewards import CompositeReward  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("smiles", help="canonical SMILES to score")
    p.add_argument(
        "--target",
        default="MRSA",
        choices=[
            "MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
            "Abaum", "Paer", "VRE", "NGono",
        ],
    )
    args = p.parse_args()

    composite = CompositeReward()
    scores = composite.score(args.smiles, target=args.target)

    print(f"\nSMILES:  {args.smiles}")
    print(f"target:  {args.target}\n")

    print(f"  validity              {scores.get('validity', 0):.3f}")
    print(f"  drug_likeness_qed     {scores.get('drug_likeness_qed', 0):.3f}")
    print(f"  synthesizability      {scores.get('synthesizability', 0):.3f}")
    print(f"  hemolysis_safety      {scores.get('hemolysis_safety', 0):.3f}")
    print(f"  predicted_mic         {scores.get('predicted_mic', 0):.3f}")
    print(f"  novelty               {scores.get('novelty', 0):.3f}")
    print(f"  embedding_novelty     {scores.get('embedding_novelty', 0):.3f}")
    print(f"  ─────────────────────")
    print(f"  COMBINED              {scores.get('combined', 0):.3f}\n")
    return 0 if scores.get("validity", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
