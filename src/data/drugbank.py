"""DrugBank Open Data loader (free-tier only).

DrugBank publishes several "open data" releases that don't require academic
licensing. We use these for drug knowledge enrichment — name, indication,
SMILES — to support the drug-likeness training task and to seed the model
with knowledge of approved drugs.

Site: https://go.drugbank.com/releases/latest
Open data: https://go.drugbank.com/releases/latest#open-data

Files we try:
    - DrugBank Open Structure Database (small molecules, SMILES + names)
    - DrugBank Open Vocabulary (drug ID → name → CAS mapping)

Both are small (~5 MB combined). License: CC0 / CC-BY-NC for these datasets.

Usage:

    python -m src.data.drugbank --output data/raw/drugbank_open.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("drugbank")

# DrugBank Open Data download URLs. They use timestamped URLs which change;
# we try the latest endpoint patterns and fall back to community mirrors.
DRUGBANK_OPEN_URLS = [
    # Latest open structures CSV (publicly downloadable, no auth)
    "https://go.drugbank.com/releases/latest/downloads/all-open-structures.csv",
    # Open vocabulary (drug ID + name + synonyms)
    "https://go.drugbank.com/releases/latest/downloads/all-drugbank-vocabulary.csv",
]

# Fallback: HuggingFace dataset mirrors of DrugBank Open
HF_FALLBACK_DATASETS = [
    "datasets-server.huggingface.co/rows?dataset=adamerose%2Fdrugbank&config=default&split=train",
]

CANONICAL_DRUG_FIELDS = {
    "drugbank_id": ["DrugBank ID", "DrugBank_ID", "id", "drugbank_id"],
    "smiles": ["SMILES", "smiles", "canonical_smiles", "Canonical SMILES"],
    "name": ["Name", "name", "common_name", "Common Name"],
    "synonyms": ["Synonyms", "synonyms"],
    "cas": ["CAS Number", "CAS_Number", "cas_number", "CAS"],
    "indication": ["Indication", "indication", "Description"],
}


def _download(url: str, dest: Path, timeout: float = 30.0) -> bool:
    log.info("Downloading %s ...", url)
    try:
        r = requests.get(url, timeout=timeout, stream=True, headers={
            "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
        })
        if r.status_code == 403:
            log.info("  ✗ 403 (login wall — DrugBank now requires registration for some files)")
            return False
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=128 * 1024):
                if chunk:
                    f.write(chunk)
                    bytes_written += len(chunk)
        log.info("  ✓ %.2f KB", bytes_written / 1024)
        return True
    except requests.RequestException as exc:
        log.warning("  ✗ %s", exc)
        return False


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map DrugBank column names to our standard schema."""
    cols_lower = {c.lower(): c for c in df.columns}
    out = pd.DataFrame()
    for our_name, candidates in CANONICAL_DRUG_FIELDS.items():
        found = None
        for cand in candidates:
            if cand.lower() in cols_lower:
                found = cols_lower[cand.lower()]
                break
        if found:
            out[our_name] = df[found]
        else:
            out[our_name] = ""
    return out


def fetch_drugbank_open(
    *,
    out_path: Path | str | None = None,
    cache_dir: Path | str = "data/raw/drugbank_cache",
) -> pd.DataFrame:
    """Fetch the open DrugBank subset. Falls back to empty DataFrame if all sources gated."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_dfs: list[pd.DataFrame] = []
    for url in DRUGBANK_OPEN_URLS:
        fname = url.rsplit("/", 1)[-1]
        dest = cache_dir / fname
        if dest.exists() or _download(url, dest):
            df = None
            for enc in ("utf-8", "latin-1", "cp1252", "utf-16"):
                try:
                    df = pd.read_csv(dest, low_memory=False, on_bad_lines="skip",
                                     encoding=enc)
                    if len(df.columns) >= 2:
                        log.info("Parsed %s with encoding=%s: %d rows × %d cols",
                                 fname, enc, len(df), len(df.columns))
                        break
                except (UnicodeDecodeError, Exception):
                    continue
            if df is None:
                log.warning("Could not parse %s with any encoding", dest)
                continue
            norm = _normalize_columns(df)
            if not norm.empty:
                all_dfs.append(norm)

    if not all_dfs:
        log.warning("DrugBank: all open-data URLs gated or unavailable")
        return pd.DataFrame()

    df = pd.concat(all_dfs, ignore_index=True)
    # Filter to entries with valid SMILES
    df = df[df["smiles"].astype(str).str.len() > 5]
    df = df.drop_duplicates(subset=["smiles"], keep="first")
    log.info("DrugBank Open total: %d unique drugs with SMILES", len(df))

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False) if out_path.suffix == ".csv" else df.to_parquet(out_path, index=False)
        log.info("Wrote %d rows to %s", len(df), out_path)
    return df


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch DrugBank Open Data")
    p.add_argument("--output", type=Path, default=Path("data/raw/drugbank_open.csv"))
    p.add_argument("--cache-dir", type=Path, default=Path("data/raw/drugbank_cache"))
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] drugbank | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    df = fetch_drugbank_open(out_path=args.output, cache_dir=args.cache_dir)
    return 0 if not df.empty else 1


if __name__ == "__main__":
    sys.exit(main())
