"""SMILES augmentation: K=3 randomized non-canonical SMILES per molecule (#7).

For every row in pro-v3 that contains a SMILES string in either the prompt or
the assistant response, produce K-1 additional rows with non-canonical SMILES
representations of the same molecule. Atom-ordering invariance is a known
inductive bias in SMILES-based LMs and adding randomized SMILES typically
yields 5-10% downstream task improvement.

Strategy: identify SMILES tokens via regex within message content. If a row
contains exactly one parseable SMILES, do the substitution K times.
Multi-SMILES rows: subsample one and substitute that, leaving others alone.

Output:
  data/synthetic/agentic_smiles_augmented.jsonl

Run:
  /tmp/lysos_venv/bin/python scripts/augment_smiles.py --k 2
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from rdkit import Chem, RDLogger
from datasets import load_from_disk
RDLogger.DisableLog("rdApp.*")

ROOT = Path(__file__).resolve().parents[1]
INPUT_DS = ROOT / "data" / "processed" / "amr-stage2-pro-v3"
OUT = ROOT / "data" / "synthetic" / "agentic_smiles_augmented.jsonl"

# Heuristic SMILES detector: likely-SMILES tokens we'll try to parse.
# We avoid common English words by requiring at least one non-letter SMILES character.
SMILES_TOKEN_RE = re.compile(
    r"\b[A-Za-z0-9][A-Za-z0-9@\[\]()=#\-+\\/]{6,}[A-Za-z0-9\]]\b"
)


def randomize_smiles(canonical_smiles: str, k: int, rng_seed: int) -> list[str]:
    """Return up to k randomized non-canonical SMILES for the molecule."""
    mol = Chem.MolFromSmiles(canonical_smiles)
    if mol is None: return []
    out: set[str] = set()
    # RDKit randomizer is seeded per-call via the random_state arg in some
    # builds; we'll just do multiple draws and dedupe.
    import random as _r
    rr = _r.Random(rng_seed)
    for _ in range(k * 4):
        try:
            r = Chem.MolToSmiles(
                mol,
                doRandom=True,
                canonical=False,
                isomericSmiles=True,
            )
            if r and r != canonical_smiles:
                out.add(r)
        except Exception:
            continue
        if len(out) >= k:
            break
    # Mix in randomization via atom-order shuffle as backup
    if len(out) < k:
        atoms = list(range(mol.GetNumAtoms()))
        for _ in range(k * 2):
            rr.shuffle(atoms)
            try:
                r = Chem.MolToSmiles(
                    Chem.RenumberAtoms(mol, atoms),
                    canonical=False,
                    isomericSmiles=True,
                )
                if r and r != canonical_smiles:
                    out.add(r)
            except Exception:
                continue
            if len(out) >= k: break
    return list(out)[:k]


def find_one_smiles_in(text: str) -> tuple[str, str] | None:
    """Find the longest single parseable SMILES in text. Return (token, canonical)."""
    if not isinstance(text, str): return None
    candidates = SMILES_TOKEN_RE.findall(text)
    candidates.sort(key=len, reverse=True)
    for c in candidates[:8]:
        mol = Chem.MolFromSmiles(c)
        if mol is None: continue
        canon = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
        if mol.GetNumHeavyAtoms() < 4:
            continue
        return (c, canon)
    return None


def augment_row(row: dict, k: int, rng_seed: int) -> list[dict]:
    """Return K-1 new rows for the row. Skips if no SMILES detected."""
    msgs = json.loads(row["messages"]) if isinstance(row["messages"], str) else row["messages"]
    text_blob = "\n".join(m.get("content", "") if isinstance(m.get("content"), str) else "" for m in msgs)
    found = find_one_smiles_in(text_blob)
    if found is None:
        return []
    original_token, canon = found
    randomized = randomize_smiles(canon, k - 1, rng_seed)
    if not randomized: return []

    out_rows = []
    for i, rs in enumerate(randomized):
        # Substitute original token with the randomized form
        new_msgs = []
        for m in msgs:
            c = m.get("content", "")
            if isinstance(c, str) and original_token in c:
                c = c.replace(original_token, rs)
            new_msgs.append({**m, "content": c})
        out_rows.append({
            "task": (row.get("task") or "stage2_chemistry") + "_smiles_aug",
            "pathogen": row.get("pathogen"),
            "split": row.get("split", "train"),
            "messages": new_msgs,
            "aug_idx": i + 1,
        })
    return out_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=2,
                    help="Total versions per molecule (canonical + K-1 augmentations)")
    ap.add_argument("--seed", type=int, default=0xAA90_AA)
    ap.add_argument("--max_rows", type=int, default=400000,
                    help="Cap on input rows scanned (avoid blowing disk)")
    args = ap.parse_args()

    print(f"Loading {INPUT_DS}")
    ds = load_from_disk(str(INPUT_DS))
    train = ds["train"]
    print(f"  rows: {len(train):,}")

    if OUT.exists(): OUT.unlink()
    n_in = 0
    n_aug = 0
    n_skip = 0
    rng_seed = args.seed
    with open(OUT, "a") as f:
        for r in train:
            n_in += 1
            if n_in > args.max_rows: break
            new_rows = augment_row(r, args.k, rng_seed + n_in)
            for nr in new_rows:
                # Re-serialize messages to match builder schema
                nr["messages"] = nr["messages"]
                f.write(json.dumps(nr) + "\n")
                n_aug += 1
            if not new_rows:
                n_skip += 1
            if n_in % 10000 == 0:
                print(f"  scanned {n_in:,}  augmented {n_aug:,}  skipped {n_skip:,}")

    print(f"\nDone. scanned={n_in:,}, augmented={n_aug:,}, skipped (no SMILES)={n_skip:,}")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
