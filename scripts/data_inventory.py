"""Lysos data inventory — report sizes + row counts of all data on disk.

Walks data/raw/ + data/processed/, prints a table of:
  - file path
  - file size (bytes / human-readable)
  - row count (for CSV/Parquet)
  - per-pathogen distribution (where applicable)

Use this after a fetch_all_data.py run to see what we actually have.

Usage:

    python scripts/data_inventory.py
    python scripts/data_inventory.py --json   # machine output
    python scripts/data_inventory.py --root data/   # custom root
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
log = logging.getLogger("inventory")


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if nbytes < 1024.0:
            return f"{nbytes:6.1f} {unit}"
        nbytes /= 1024.0
    return f"{nbytes:6.1f} PB"


def _count_rows(path: Path) -> tuple[int, dict | None]:
    """Return (row_count, per_pathogen_dict_or_None) for a tabular file."""
    if path.suffix == ".csv":
        try:
            import pandas as pd
            df = pd.read_csv(path, low_memory=False)
            return _count_with_pathogen(df)
        except Exception:  # noqa: BLE001
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    return sum(1 for _ in f) - 1, None
            except Exception:  # noqa: BLE001
                return -1, None
    elif path.suffix == ".parquet":
        try:
            import pandas as pd
            df = pd.read_parquet(path)
            return _count_with_pathogen(df)
        except Exception:  # noqa: BLE001
            return -1, None
    elif path.suffix == ".json":
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                return len(data), None
            return 1, None
        except Exception:  # noqa: BLE001
            return -1, None
    return -1, None


def _count_with_pathogen(df) -> tuple[int, dict | None]:
    n = len(df)
    if "pathogen_short" in df.columns:
        return n, df["pathogen_short"].value_counts().to_dict()
    return n, None


def _walk_dir(root: Path) -> list[dict[str, Any]]:
    """Return list of file-info dicts for tabular files under root."""
    if not root.exists():
        return []
    items = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix in (".csv", ".parquet", ".json", ".tsv"):
            try:
                size = p.stat().st_size
            except OSError:
                continue
            n_rows, by_pathogen = _count_rows(p)
            items.append({
                "path": str(p.relative_to(root.parent if root.parent.exists() else root)),
                "size_bytes": size,
                "size_human": _human_size(size),
                "n_rows": n_rows,
                "by_pathogen": by_pathogen,
            })
    return items


def _walk_processed(root: Path) -> list[dict[str, Any]]:
    """Walk processed data: HF Datasets are dirs, not single files."""
    if not root.exists():
        return []
    items = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        # Compute total dir size + look for dataset_info.json or HF files
        total_size = sum(p.stat().st_size for p in sub.rglob("*") if p.is_file())
        # Try to count rows via HF datasets
        n_rows, by_pathogen = _count_hf_dataset(sub)
        items.append({
            "path": str(sub),
            "size_bytes": total_size,
            "size_human": _human_size(total_size),
            "n_rows": n_rows,
            "by_pathogen": by_pathogen,
        })
    return items


def _count_hf_dataset(path: Path) -> tuple[int, dict | None]:
    """Try loading a HF Dataset on disk and counting rows + pathogen split."""
    try:
        from datasets import load_from_disk
        ds = load_from_disk(str(path))
    except Exception:  # noqa: BLE001
        return -1, None
    total = 0
    by_p: Counter = Counter()
    if hasattr(ds, "keys"):  # DatasetDict
        for split_name in ds:
            split = ds[split_name]
            total += len(split)
            if "pathogen_short" in split.column_names:
                for v in split["pathogen_short"]:
                    by_p[v] += 1
    else:
        total = len(ds)
        if "pathogen_short" in ds.column_names:
            for v in ds["pathogen_short"]:
                by_p[v] += 1
    return total, dict(by_p) if by_p else None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lysos data inventory")
    p.add_argument("--root", type=Path, default=Path("data"))
    p.add_argument("--json", action="store_true", help="Output as JSON")
    return p.parse_args()


def _print_table(title: str, items: list[dict]) -> int:
    if not items:
        print(f"\n=== {title} ===")
        print("  (none)")
        return 0
    print(f"\n=== {title} ===")
    print(f"{'PATH':<48} {'SIZE':>10}  {'ROWS':>10}  {'PATHOGENS':<40}")
    print("-" * 120)
    total_bytes = 0
    total_rows = 0
    for it in items:
        path_disp = it["path"][-48:]
        size = it["size_human"]
        rows = it["n_rows"]
        rows_disp = f"{rows:,}" if rows >= 0 else "?"
        by_p = it["by_pathogen"]
        if by_p:
            top = sorted(by_p.items(), key=lambda x: -x[1])[:4]
            p_disp = " ".join(f"{k}:{v}" for k, v in top)
        else:
            p_disp = "-"
        print(f"{path_disp:<48} {size:>10}  {rows_disp:>10}  {p_disp:<40}")
        total_bytes += it["size_bytes"]
        if rows > 0:
            total_rows += rows
    print("-" * 120)
    print(f"{'TOTAL':<48} {_human_size(total_bytes):>10}  {total_rows:>10,}")
    return total_bytes


def main() -> int:
    args = parse_args()

    raw_items = _walk_dir(args.root / "raw")
    proc_items = _walk_processed(args.root / "processed")

    if args.json:
        out = {
            "raw": raw_items,
            "processed": proc_items,
            "totals": {
                "raw_bytes": sum(i["size_bytes"] for i in raw_items),
                "processed_bytes": sum(i["size_bytes"] for i in proc_items),
                "raw_rows": sum(i["n_rows"] for i in raw_items if i["n_rows"] > 0),
                "processed_rows": sum(i["n_rows"] for i in proc_items if i["n_rows"] > 0),
            },
        }
        print(json.dumps(out, indent=2))
        return 0

    raw_bytes = _print_table("RAW DATA  (data/raw/)", raw_items)
    proc_bytes = _print_table("PROCESSED  (data/processed/)", proc_items)

    print("\n" + "=" * 80)
    print(f"{'GRAND TOTAL':<48} {_human_size(raw_bytes + proc_bytes):>10}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
