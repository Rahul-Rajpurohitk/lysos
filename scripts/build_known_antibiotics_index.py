"""Build the known-antibiotics index for novelty reward + RAG retrieval.

Sources (all already on disk after running fetch_all_data.py):
  - data/raw/chembl_antibiotics.csv  (ChEMBL bacterial activities)
  - data/raw/dbaasp_amps.csv          (DBAASP AMPs)
  - data/raw/drugbank_cache/*.csv     (DrugBank Open Data, if rdkit available)

Output:
  data/processed/known-antibiotics.smiles
    Format: <smiles>  <name>           (one per line, space-separated)

The novelty reward fns + RAG retriever both consume this file.

Usage:

    python scripts/build_known_antibiotics_index.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] index | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("index")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build known-antibiotics index")
    p.add_argument("--data-root", type=Path, default=Path("data/raw"))
    p.add_argument("--output", type=Path,
                   default=Path("data/processed/known-antibiotics.smiles"))
    p.add_argument("--max-rows", type=int, default=None,
                   help="Cap output (useful for fast iteration)")
    p.add_argument("--include-active-only", action="store_true",
                   help="Only include compounds with pchembl_value >= 5 (potent)")
    return p.parse_args()


def _load_chembl(path: Path, only_active: bool) -> list[tuple[str, str]]:
    if not path.exists():
        log.warning("ChEMBL file missing: %s", path)
        return []
    import pandas as pd

    df = pd.read_csv(path, low_memory=False)
    df = df.dropna(subset=["smiles"])
    if only_active and "pchembl_value" in df.columns:
        df = df[df["pchembl_value"] >= 5.0]
    df = df.drop_duplicates(subset=["smiles"])
    log.info("ChEMBL: %d unique antibacterial SMILES", len(df))
    rows = []
    for _, r in df.iterrows():
        name = (r.get("name") or "")
        if not isinstance(name, str):
            name = str(name)
        rows.append((str(r["smiles"]), name.strip()))
    return rows


def _load_dbaasp(path: Path) -> list[tuple[str, str]]:
    """DBAASP entries are peptides — we keep their sequences as 'SMILES-equivalent'
    for retrieval purposes. Real chemistry would convert, but the embedding model
    works on text similarity anyway."""
    if not path.exists():
        log.warning("DBAASP file missing: %s", path)
        return []
    import pandas as pd

    df = pd.read_csv(path, low_memory=False)
    df = df.dropna(subset=["sequence"])
    df = df.drop_duplicates(subset=["sequence"])
    log.info("DBAASP: %d unique AMP sequences", len(df))
    rows = []
    for _, r in df.iterrows():
        seq = str(r["sequence"])
        raw_name = r.get("name", "")
        name_str = str(raw_name) if raw_name == raw_name else ""  # NaN check
        name = f"AMP_{name_str[:30]}"
        rows.append((seq, name))
    return rows


def _load_dramp(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    import pandas as pd

    df = pd.read_csv(path, low_memory=False)
    df = df.dropna(subset=["sequence"])
    df = df.drop_duplicates(subset=["sequence"])
    log.info("DRAMP: %d unique AMP sequences", len(df))
    rows = []
    for _, r in df.iterrows():
        seq = str(r["sequence"])
        raw_name = r.get("name", "") or r.get("dbaasp_id", "")
        name_str = str(raw_name) if raw_name == raw_name else ""
        name = f"DRAMP_{name_str}"
        rows.append((seq, name))
    return rows


def main() -> int:
    args = parse_args()

    rows: list[tuple[str, str]] = []
    rows += _load_chembl(args.data_root / "chembl_antibiotics.csv",
                         args.include_active_only)
    rows += _load_dbaasp(args.data_root / "dbaasp_amps.csv")
    rows += _load_dramp(args.data_root / "dramp_amps.csv")

    # Dedup across sources by structure key
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for s, n in rows:
        if s in seen:
            continue
        seen.add(s)
        unique.append((s, n))

    if args.max_rows:
        unique = unique[: args.max_rows]

    log.info("Total unique structures: %d", len(unique))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        f.write("# known-antibiotics index — built by scripts/build_known_antibiotics_index.py\n")
        f.write("# format: <smiles_or_sequence>  <name>\n")
        for s, n in unique:
            line = s if not n else f"{s}\t{n}"
            f.write(line + "\n")

    log.info("Wrote %d entries to %s", len(unique), args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
