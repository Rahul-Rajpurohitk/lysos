"""Find the top-k most-similar known antibiotics to a given SMILES.

Hits the /api/similar endpoint which uses EmbeddingGemma 300m to embed
the query and runs cosine search over the 20,489-row known-antibiotics
index built from ChEMBL + DBAASP + DRAMP.

Useful for: novelty checks, scaffold-hop analysis, mechanism-of-action
guesses based on chemical similarity.

    python examples/find_similar_drugs.py "CC1(C)SC2C(NC(=O)C(N)c3ccccc3)C(=O)N2C1C(=O)O"
"""

from __future__ import annotations

import argparse
import os
import sys

import requests

API_BASE = os.environ.get(
    "LYSOS_API",
    "https://lablab-ai-amd-developer-hackathon-lysos.hf.space",
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("smiles")
    p.add_argument("-k", type=int, default=5)
    args = p.parse_args()

    body = {"smiles": args.smiles, "k": args.k}
    r = requests.post(f"{API_BASE}/api/similar", json=body, timeout=60)
    r.raise_for_status()
    hits = r.json()

    if not hits:
        print("no hits")
        return 1

    print(f"\nQuery:   {args.smiles}\n")
    print(f"{'#':>2}  {'sim':>5}  {'name':<30}  {'indication':<28}  smiles")
    print("-" * 110)
    for i, h in enumerate(hits, 1):
        print(
            f"{i:>2}  {h['similarity']:>5.2f}  "
            f"{(h['name'] or '')[:28]:<30}  "
            f"{(h['indication'] or '')[:26]:<28}  "
            f"{h['smiles'][:50]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
