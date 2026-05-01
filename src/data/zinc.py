"""ZINC chemical space loader.

ZINC is the largest free database of purchasable compounds (>10B in ZINC22).
We pull curated subsets — FDA-approved drugs, world-of-drugs, drug-like
fragments — to give Lysos a strong "chemistry prior" of what drug-like
SMILES distributions look like.

This DATA HAS NO ACTIVITY LABELS — it's a generative prior, not a supervised
signal. Used during Stage 1 / Stage 2 only as a "valid SMILES distribution"
to teach the model what realistic drug-like molecules look like, even when
we don't have antibacterial labels for them.

Site: https://zinc.docking.org/

Subsets we use:
  - fda           ~2,500 FDA-approved drugs
  - world         ~250,000 "world of drugs"
  - in-stock-druglike  ~10M purchasable drug-like

Usage:

    python -m src.data.zinc --output data/raw/zinc_drug_like.csv \\
        --subsets fda,world
"""

from __future__ import annotations

import argparse
import gzip
import logging
import sys
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("zinc")

# ZINC subset URLs (mix of zinc.docking.org and zinc22.docking.org).
# Some URLs change between ZINC15/22 — we try multiple in order.
ZINC_SUBSET_URLS: dict[str, list[str]] = {
    "fda": [
        "https://zinc.docking.org/substances/subsets/fda.smi",
        "https://zinc15.docking.org/substances/subsets/fda.smi",
    ],
    "world": [
        "https://zinc.docking.org/substances/subsets/world.smi.gz",
        "https://zinc15.docking.org/substances/subsets/world.smi.gz",
    ],
    "investigational": [
        "https://zinc.docking.org/substances/subsets/investigational.smi",
    ],
    "in-trials": [
        "https://zinc.docking.org/substances/subsets/in-trials.smi",
    ],
    "natural-products": [
        "https://zinc.docking.org/substances/subsets/natural-products.smi.gz",
    ],
}


def _download_subset(name: str, urls: list[str], dest: Path,
                     timeout: float = 60.0) -> bool:
    if dest.exists():
        log.info("Using cached %s", dest)
        return True

    for url in urls:
        log.info("Trying %s ...", url)
        try:
            r = requests.get(url, timeout=timeout, stream=True, headers={
                "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
            })
            if r.status_code != 200:
                log.info("  ✗ %d", r.status_code)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            bytes_written = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        f.write(chunk)
                        bytes_written += len(chunk)
            log.info("  ✓ %s: %.2f MB", name, bytes_written / 1024 / 1024)
            return True
        except requests.RequestException as exc:
            log.warning("  ✗ %s: %s", url, exc)
            continue
    return False


def _parse_smi(path: Path) -> pd.DataFrame:
    """Parse a .smi or .smi.gz file (one SMILES per line, optional ID)."""
    rows = []
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="ignore") as f:
            for line_idx, line in enumerate(f):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # ZINC .smi format: "SMILES ZINC_ID" (space-separated)
                parts = line.split()
                if not parts:
                    continue
                smi = parts[0]
                zinc_id = parts[1] if len(parts) > 1 else ""
                rows.append({"smiles": smi, "zinc_id": zinc_id})
                if line_idx and line_idx % 100_000 == 0:
                    log.info("  parsed %d lines from %s", line_idx, path.name)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not parse %s: %s", path, exc)
        return pd.DataFrame()
    return pd.DataFrame(rows)


def fetch_zinc_subsets(
    *,
    out_path: Path | str | None = None,
    cache_dir: Path | str = "data/raw/zinc_cache",
    subsets: list[str] | None = None,
) -> pd.DataFrame:
    """Fetch one or more ZINC subsets, return aggregated SMILES DataFrame."""
    cache_dir = Path(cache_dir)
    subsets = subsets or ["fda", "investigational", "in-trials", "world"]

    all_dfs: list[pd.DataFrame] = []
    for sub in subsets:
        urls = ZINC_SUBSET_URLS.get(sub)
        if not urls:
            log.warning("Unknown subset: %s (known: %s)", sub, list(ZINC_SUBSET_URLS))
            continue
        # Pick filename from URL suffix
        suffix = ".smi.gz" if any(".smi.gz" in u for u in urls) else ".smi"
        dest = cache_dir / f"zinc_{sub}{suffix}"
        if not _download_subset(sub, urls, dest):
            continue
        df = _parse_smi(dest)
        if df.empty:
            continue
        df["source"] = f"ZINC-{sub}"
        all_dfs.append(df)
        log.info("ZINC %s: %d compounds", sub, len(df))

    if not all_dfs:
        log.warning("ZINC: no subsets downloaded")
        return pd.DataFrame()

    df = pd.concat(all_dfs, ignore_index=True)
    df = df.drop_duplicates(subset=["smiles"], keep="first")
    log.info("ZINC total (after dedup): %d unique compounds", len(df))

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix == ".parquet":
            df.to_parquet(out_path, index=False)
        else:
            df.to_csv(out_path, index=False)
        log.info("Wrote %d rows to %s", len(df), out_path)
    return df


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch ZINC drug-like subsets")
    p.add_argument("--output", type=Path, default=Path("data/raw/zinc_drug_like.csv"))
    p.add_argument("--cache-dir", type=Path, default=Path("data/raw/zinc_cache"))
    p.add_argument("--subsets", type=str, default="fda,investigational,in-trials,world",
                   help=f"Comma-separated subset names: {list(ZINC_SUBSET_URLS)}")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] zinc | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    subsets = [s.strip() for s in args.subsets.split(",") if s.strip()]
    df = fetch_zinc_subsets(out_path=args.output, cache_dir=args.cache_dir,
                            subsets=subsets)
    if df.empty:
        return 1
    log.info("Per-source counts:\n%s", df["source"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
