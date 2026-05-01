"""BindingDB binding affinity loader.

BindingDB curates measured binding affinities (Ki, Kd, IC50, EC50) between
small molecules and target proteins. ~2.8M total measurements across all
targets. We download the full TSV and filter to bacterial pathogen targets.

Site: https://www.bindingdb.org/

Bulk download: https://www.bindingdb.org/bind/downloads/BindingDB_All_*.tsv.zip
  (date-versioned URLs; we try several recent dates and use the first that works)

The full download is ~1.2 GB compressed (~5 GB extracted). After filtering
to bacterial protein targets we keep ~200 MB of binding data — a significant
multiplier over ChEMBL alone for activity-prediction training.

Usage:

    python -m src.data.bindingdb --output data/raw/bindingdb_antibacterial.csv
"""

from __future__ import annotations

import argparse
import gzip
import logging
import sys
import zipfile
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

log = logging.getLogger("bindingdb")

# BindingDB serves downloads through a JSP servlet wrapper. Files are
# named BindingDB_{flavor}_{YYYYMM}_tsv.zip (verified live 2026-05).
# The base path is /rwd/bind/chemsearch/marvin/SDFdownload.jsp?download_file=...
# We try a few releases; the most recent active is 202604 (April 2026).
_BDB_BASE = "https://www.bindingdb.org/rwd/bind/chemsearch/marvin/SDFdownload.jsp?download_file=/rwd/bind/downloads"
BINDINGDB_URL_TEMPLATES = [
    # BindingDB_BindingDB_Articles is the small curated subset (~17 MB) —
    # fastest download with the highest data quality. Default choice.
    _BDB_BASE + "/BindingDB_BindingDB_Articles_{rel}_tsv.zip",
    # Full BindingDB (~525 MB) — much bigger but covers ChEMBL+PubChem+Patents+more
    _BDB_BASE + "/BindingDB_All_{rel}_tsv.zip",
    # ChEMBL slice (~326 MB) — overlaps with our ChEMBL loader, lower priority
    _BDB_BASE + "/BindingDB_ChEMBL_{rel}_tsv.zip",
]
# Recent releases (YYYYMM). New releases roll monthly; we try several.
BINDINGDB_RELEASES = [
    "202604", "202603", "202602", "202601",
    "202512", "202511", "202510",
]

# Bacterial target keywords for filtering. BindingDB target names are
# inconsistent (organism in target name OR in source organism field) so we
# match on multiple substrings.
BACTERIAL_KEYWORDS = [
    # Pathogens
    "staphylococcus", "mycobacterium", "escherichia", "klebsiella",
    "acinetobacter", "pseudomonas", "enterococcus", "neisseria",
    "streptococcus", "haemophilus", "campylobacter", "salmonella",
    "shigella", "vibrio", "yersinia", "burkholderia", "helicobacter",
    "clostridium", "bacillus", "listeria", "francisella",
    # Common bacterial targets
    "penicillin-binding", "pbp", "dihydrofolate reductase",
    "dna gyrase", "ribosom", "rnap", "rna polymerase",
    "topoisomerase iv", "fts", "mura", "murz", "lpx",
]

AMR_TO_BINDINGDB: dict[str, list[str]] = {
    "MRSA": ["staphylococcus aureus"],
    "Mtb": ["mycobacterium tuberculosis", "mycobacterium smegmatis"],
    "EColi-CRE": ["escherichia coli"],
    "KpneuCRE": ["klebsiella pneumoniae"],
    "Abaum": ["acinetobacter baumannii"],
    "Paer": ["pseudomonas aeruginosa"],
    "VRE": ["enterococcus faecium", "enterococcus faecalis"],
    "NGono": ["neisseria gonorrhoeae"],
}


def _try_download(cache_dir: Path) -> Path | None:
    """Try recent BindingDB releases; return the path of the downloaded zip."""
    cache_dir.mkdir(parents=True, exist_ok=True)

    for tmpl in BINDINGDB_URL_TEMPLATES:
        for rel in BINDINGDB_RELEASES:
            url = tmpl.format(rel=rel)
            # Pick a unique cache filename based on the URL flavor + release
            flavor = "Articles" if "Articles" in tmpl else (
                "All" if "_All_" in tmpl else "ChEMBL"
            )
            zip_path = cache_dir / f"bindingdb_{flavor}_{rel}.tsv.zip"
            if zip_path.exists():
                log.info("Using cached %s", zip_path)
                return zip_path
            log.info("Trying %s/%s ...", flavor, rel)
            try:
                r = requests.get(url, timeout=60, stream=True, headers={
                    "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
                })
                if r.status_code != 200:
                    log.info("  ✗ %d", r.status_code)
                    continue
                with open(zip_path, "wb") as f:
                    bytes_written = 0
                    last_log = 0
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            bytes_written += len(chunk)
                            if bytes_written - last_log > 50 * 1024 * 1024:
                                log.info("  ... %.1f MB", bytes_written / 1024 / 1024)
                                last_log = bytes_written
                log.info("  ✓ %.1f MB downloaded", bytes_written / 1024 / 1024)
                return zip_path
            except requests.RequestException as exc:
                log.info("  ✗ %s", exc)
                continue
    log.error("Could not download BindingDB from any candidate URL")
    return None


def _stream_filtered_rows(zip_path: Path, *, bacterial_only: bool = True,
                          chunk_size: int = 100_000) -> Iterator[pd.DataFrame]:
    """Stream BindingDB TSV in chunks, yielding filtered DataFrames.

    BindingDB's full TSV has ~50 columns and ~3M rows. We use Pandas
    chunked reading to avoid loading the whole thing into memory.
    Filter to rows where target organism matches bacterial keywords.
    """
    with zipfile.ZipFile(zip_path) as zf:
        # The zip contains one big TSV
        tsv_name = next((n for n in zf.namelist() if n.endswith(".tsv")), None)
        if tsv_name is None:
            log.error("No .tsv inside %s", zip_path)
            return

        with zf.open(tsv_name) as f:
            # Read in chunks so we don't blow memory
            for chunk_idx, chunk in enumerate(pd.read_csv(
                f, sep="\t", chunksize=chunk_size, low_memory=False,
                on_bad_lines="skip", encoding="utf-8", dtype=str,
            )):
                if chunk_idx == 0:
                    log.info("BindingDB columns: %d, sample: %s",
                             len(chunk.columns), list(chunk.columns)[:8])

                if bacterial_only:
                    # BindingDB columns include "Target Source Organism According to Curator or DataSource"
                    # and "Target Name Assigned by Curator or DataSource"
                    org_col = next((c for c in chunk.columns if "Target Source Organism" in c), None)
                    name_col = next((c for c in chunk.columns if "Target Name" in c), None)
                    if not org_col and not name_col:
                        # Schema changed?
                        yield chunk
                        continue
                    org_str = (chunk[org_col].fillna("").str.lower() if org_col
                               else pd.Series([""] * len(chunk)))
                    name_str = (chunk[name_col].fillna("").str.lower() if name_col
                                else pd.Series([""] * len(chunk)))
                    mask = pd.Series([False] * len(chunk))
                    for kw in BACTERIAL_KEYWORDS:
                        mask = mask | org_str.str.contains(kw, regex=False, na=False)
                        mask = mask | name_str.str.contains(kw, regex=False, na=False)
                    chunk = chunk[mask]

                if not chunk.empty:
                    yield chunk

                if (chunk_idx + 1) % 10 == 0:
                    log.info("  processed %d chunks", chunk_idx + 1)


def _normalize_bindingdb(df: pd.DataFrame) -> pd.DataFrame:
    """Map BindingDB columns to our standard schema."""
    if df.empty:
        return df

    cols = {c.lower(): c for c in df.columns}

    def col(*names: str) -> str | None:
        for n in names:
            for k, orig in cols.items():
                if n.lower() in k:
                    return orig
        return None

    smi_col = col("ligand smiles", "smiles")
    name_col = col("ligand chembl id", "ligand name")
    target_col = col("target source organism")
    target_name_col = col("target name")
    ki_col = col("ki (nm)")
    ic50_col = col("ic50 (nm)")
    kd_col = col("kd (nm)")
    ec50_col = col("ec50 (nm)")

    if not smi_col:
        log.warning("No SMILES column found")
        return pd.DataFrame()

    rows = []
    for _, r in df.iterrows():
        smi = str(r[smi_col]).strip()
        if not smi or smi == "nan":
            continue
        target = str(r[target_col]).strip().lower() if target_col else ""

        # Match to AMR pathogen short codes
        for short, kws in AMR_TO_BINDINGDB.items():
            if any(kw in target for kw in kws):
                # Pick the best available affinity (Ki > Kd > IC50 > EC50)
                affinity_nm = None
                affinity_type = None
                for c, kind in [(ki_col, "Ki"), (kd_col, "Kd"),
                                (ic50_col, "IC50"), (ec50_col, "EC50")]:
                    if c is None:
                        continue
                    try:
                        v = float(r[c]) if r[c] not in (None, "", "nan") else None
                        if v and v > 0:
                            affinity_nm = v
                            affinity_type = kind
                            break
                    except (TypeError, ValueError):
                        continue

                # Convert nM → log10(MIC µg/mL approximation)
                # We don't have exact MW here; skip mic_log conversion.
                rows.append({
                    "smiles": smi,
                    "pathogen_short": short,
                    "mic_log_ug_per_ml": None,
                    "name": str(r[name_col])[:100] if name_col else "",
                    "chembl_id": "",
                    "standard_type": affinity_type or "",
                    "standard_value": affinity_nm,
                    "standard_units": "nM" if affinity_nm else "",
                    "pchembl_value": None,
                    "target_organism": str(r[target_col]) if target_col else "",
                })
                break  # one row per BindingDB record per pathogen
    return pd.DataFrame(rows)


def fetch_bindingdb(
    *,
    out_path: Path | str | None = None,
    cache_dir: Path | str = "data/raw/bindingdb_cache",
    chunk_size: int = 100_000,
) -> pd.DataFrame:
    cache_dir = Path(cache_dir)
    zip_path = _try_download(cache_dir)
    if zip_path is None:
        return pd.DataFrame()

    log.info("Streaming + filtering BindingDB to bacterial targets...")
    chunks_norm: list[pd.DataFrame] = []
    rows_seen = 0
    rows_kept = 0
    for chunk in _stream_filtered_rows(zip_path, bacterial_only=True, chunk_size=chunk_size):
        rows_seen += len(chunk)
        norm = _normalize_bindingdb(chunk)
        if not norm.empty:
            chunks_norm.append(norm)
            rows_kept += len(norm)

    log.info("BindingDB: %d bacterial rows -> %d AMR-mapped rows", rows_seen, rows_kept)
    if not chunks_norm:
        return pd.DataFrame()

    df = pd.concat(chunks_norm, ignore_index=True)
    df = df.drop_duplicates(subset=["smiles", "pathogen_short", "standard_type"], keep="first")
    log.info("After dedup: %d", len(df))

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
    p = argparse.ArgumentParser(description="Fetch BindingDB bacterial subset")
    p.add_argument("--output", type=Path, default=Path("data/raw/bindingdb_antibacterial.csv"))
    p.add_argument("--cache-dir", type=Path, default=Path("data/raw/bindingdb_cache"))
    p.add_argument("--chunk-size", type=int, default=100_000)
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] bindingdb | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    df = fetch_bindingdb(out_path=args.output, cache_dir=args.cache_dir,
                        chunk_size=args.chunk_size)
    if df.empty:
        return 1
    log.info("Per-pathogen counts:\n%s", df["pathogen_short"].value_counts().to_string())
    log.info("Per-affinity-type counts:\n%s", df["standard_type"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
