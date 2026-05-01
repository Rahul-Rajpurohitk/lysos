"""Lysos — quickstart: design 5 candidates against MRSA.

Hits the local FastAPI server (run `make api-dev` first), or change
`API_BASE` to point at the deployed HF Space.

    python examples/quickstart.py
"""

from __future__ import annotations

import json
import os
import sys

import requests

API_BASE = os.environ.get(
    "LYSOS_API",
    "https://lablab-ai-amd-developer-hackathon-lysos.hf.space",
)


def main() -> int:
    health = requests.get(f"{API_BASE}/api/health", timeout=30).json()
    if not health.get("loaded"):
        print(f"server not ready: {health}")
        return 1

    body = {
        "target": "MRSA",
        "n": 5,
        "modality": "smiles",
        "temperature": 1.0,
    }
    print(f"POST {API_BASE}/api/design  body={body}")
    r = requests.post(f"{API_BASE}/api/design", json=body, timeout=120)
    r.raise_for_status()
    out = r.json()

    print(f"\nelapsed: {out['elapsed_s']:.1f}s")
    print(f"target:  {out['pathogen']['name']} ({out['pathogen']['category']})")
    print(f"returned: {out['n_returned']}/{out['n_total']}\n")

    print(f"{'rank':>4}  {'combined':>9}  {'mic':>5}  {'qed':>5}  {'sa':>5}  {'novel':>6}  smiles")
    print("-" * 110)
    for i, c in enumerate(out["candidates"], 1):
        s = c["scores"]
        smi = (c["smiles"] or "")[:50]
        print(
            f"{i:>4}  {c['combined']:>9.3f}  "
            f"{s['predicted_mic']:>5.2f}  "
            f"{s['drug_likeness_qed']:>5.2f}  "
            f"{s['synthesizability']:>5.2f}  "
            f"{s['novelty']:>6.2f}  "
            f"{smi}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
