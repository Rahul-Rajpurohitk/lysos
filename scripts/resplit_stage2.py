"""Scaffold-aware re-split of the Stage 2 dataset.

Currently `prepare_amr_data.py` shuffles all examples then takes the top
N as eval. That leaks: if the same molecule generates multiple (prompt,
response) examples, copies land in BOTH train and valid (917 exact pairs
+ 4,172 unique SMILES leaked, per `scripts/check_leakage.py`).

This script:
  1. Reads `data/processed/amr-stage2-dedup-hash` (the deduped Stage 2)
  2. Extracts a "molecule key" per row — Murcko scaffold of any SMILES in
     prompt/response, or the drug name otherwise.
  3. Groups examples by molecule key.
  4. Splits the GROUPS, not the rows. Each unique scaffold goes to one side.
  5. Writes `data/processed/amr-stage2-split` with no leakage.

Optionally pushes to HF Hub.

Usage:

    python scripts/resplit_stage2.py
    HF_TOKEN=... python scripts/resplit_stage2.py --push-to-hub rahul24raj/lysos-amr-stage2-split
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import random
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] resplit | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("resplit")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

SMI_RE = re.compile(r"SMILES[:=]\s*([A-Za-z0-9@+\-=#$%\[\]\(\)\\/.]+)")
NAME_RE = re.compile(r"of\s+([A-Z][A-Za-z0-9\-]+)")  # weak but useful


def _scaffold(smi: str) -> str:
    try:
        from rdkit import Chem
        from rdkit.Chem.Scaffolds import MurckoScaffold
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            return ""
        scaf = MurckoScaffold.GetScaffoldForMol(mol)
        return Chem.MolToSmiles(scaf, canonical=True)
    except Exception:  # noqa: BLE001
        return ""


def _row_key(row: dict) -> str:
    """Compute a molecule key for grouping — same molecule = same key."""
    for field in ("prompt", "response"):
        text = str(row.get(field, ""))
        m = SMI_RE.search(text)
        if m:
            scaf = _scaffold(m.group(1))
            if scaf:
                return f"scaffold:{scaf}"
            return f"smi:{m.group(1)}"
    # Sequence-bearing rows (peptide tasks)
    resp = str(row.get("response", ""))
    if re.fullmatch(r"Sequence:\s*[A-Z]{5,80}", resp or ""):
        seq = resp.split()[-1]
        return f"seq:{seq}"
    # Drug-knowledge tasks (drug_id_lookup, drug_synonyms, etc.) —
    # the answer (response) IS the unique key. Hash by full (prompt,
    # response) so each row gets its own group. They have no SMILES
    # leak risk anyway.
    h = hashlib.sha256(
        (str(row.get("prompt", "")).strip().lower() + "||"
         + str(row.get("response", "")).strip().lower())
        .encode("utf-8", errors="ignore"),
    ).hexdigest()[:14]
    return f"row:{h}"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path,
                   default=Path("data/processed/amr-stage2-dedup-hash"))
    p.add_argument("--output", type=Path,
                   default=Path("data/processed/amr-stage2-split"))
    p.add_argument("--valid-frac", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--push-to-hub", type=str, default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        from datasets import Dataset, DatasetDict, concatenate_datasets, load_from_disk
    except ImportError as exc:
        log.error("Missing deps: %s. pip install datasets", exc)
        return 2

    if not args.input.exists():
        log.error("Input %s missing", args.input)
        return 1

    log.info("Loading %s ...", args.input)
    ds = load_from_disk(str(args.input))
    train = concatenate_datasets([ds[s] for s in ds]) if hasattr(ds, "keys") else ds
    log.info("  total %d rows (was train + valid combined)", len(train))

    log.info("Computing molecule keys ...")
    keys: list[str] = []
    for row in train:
        keys.append(_row_key(row))
    train = train.add_column("_mol_key", keys)
    n_groups = len(set(keys))
    log.info("  unique groups (scaffolds + names + seqs + per-task fallback): %d",
             n_groups)

    # Per-task balance: split groups *within each task* by valid_frac.
    rnd = random.Random(args.seed)
    if "task" not in train.column_names:
        log.warning("No 'task' column — splitting groups globally")
        all_groups = sorted(set(keys))
        rnd.shuffle(all_groups)
        n_valid = max(1, int(len(all_groups) * args.valid_frac))
        valid_groups = set(all_groups[:n_valid])
    else:
        valid_groups: set[str] = set()
        # Group by task → groups
        task_to_groups: dict[str, set[str]] = {}
        for t, k in zip(train["task"], keys):
            task_to_groups.setdefault(t, set()).add(k)
        for task, group_set in task_to_groups.items():
            groups = sorted(group_set)
            rnd.shuffle(groups)
            n_valid_t = max(1, int(len(groups) * args.valid_frac))
            valid_groups.update(groups[:n_valid_t])
            log.info("  task %-25s groups=%d  valid_groups=%d",
                     task, len(groups), n_valid_t)

    log.info("Splitting %d rows by group ...", len(train))
    train_idx: list[int] = []
    valid_idx: list[int] = []
    for i, k in enumerate(keys):
        (valid_idx if k in valid_groups else train_idx).append(i)

    log.info("  train rows: %d, valid rows: %d", len(train_idx), len(valid_idx))

    train_ds = train.select(train_idx).remove_columns(["_mol_key"])
    valid_ds = train.select(valid_idx).remove_columns(["_mol_key"])

    # Verification: no exact (prompt, response) pair should leak
    def _h(p, r):
        return hashlib.sha256(
            (str(p).strip().lower() + "||"
             + str(r).strip().lower()).encode("utf-8", errors="ignore"),
        ).hexdigest()[:16]

    train_pairs = {_h(r["prompt"], r.get("response", "")) for r in train_ds}
    valid_pairs = {_h(r["prompt"], r.get("response", "")) for r in valid_ds}
    leak = train_pairs & valid_pairs
    log.info("Post-split exact-pair leak: %d (%.2f%% of valid)",
             len(leak), 100 * len(leak) / max(1, len(valid_ds)))

    train_smi = {SMI_RE.search(r["prompt"]).group(1) if SMI_RE.search(r["prompt"]) else None for r in train_ds}
    valid_smi = {SMI_RE.search(r["prompt"]).group(1) if SMI_RE.search(r["prompt"]) else None for r in valid_ds}
    smi_leak = (train_smi & valid_smi) - {None}
    log.info("Post-split SMILES leak: %d (was 4,172 before)", len(smi_leak))

    out = DatasetDict({"train": train_ds, "valid": valid_ds})
    args.output.mkdir(parents=True, exist_ok=True)
    out.save_to_disk(str(args.output))
    log.info("Wrote %s", args.output)

    if args.push_to_hub:
        import os
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        if not token:
            log.error("--push-to-hub needs HF_TOKEN")
            return 3
        out.push_to_hub(args.push_to_hub, token=token, private=False)
        log.info("✓ pushed to %s", args.push_to_hub)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
