"""DRAMP antimicrobial peptide loader.

DRAMP — Data Repository of Antimicrobial Peptides.
22,000+ peptides with curated antimicrobial activity data.

Site: http://dramp.cpu-bioinfor.org/

DRAMP doesn't have a documented JSON API, but they publish bulk downloads as
TSV/Excel. We use the bulk download path (mirrored on their site) for
reproducible offline-style fetching.

Strategy:
  1. Try direct download from dramp.cpu-bioinfor.org/downloads/
  2. Parse TSV → standard schema
  3. Fall back to a HuggingFace mirror if download fails

Usage:

    python -m src.data.dramp --output data/raw/dramp_amps.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

log = logging.getLogger("dramp")

# DRAMP bulk-download URLs. They're versioned — when DRAMP updates,
# add new entries here. We try each in order and use the first that works.
DRAMP_URLS = [
    # General AMPs (the big one)
    "http://dramp.cpu-bioinfor.org/downloads/General_Amps.zip",
    # Patent AMPs
    "http://dramp.cpu-bioinfor.org/downloads/Patent_Amps.zip",
    # Clinical AMPs (smaller, curated)
    "http://dramp.cpu-bioinfor.org/downloads/Clinical_Amps.zip",
]

CANONICAL_AAS = set("ACDEFGHIKLMNPQRSTVWY")

# Match DRAMP target_organism strings to our AMR pathogen short codes.
# DRAMP target strings vary; we use case-insensitive substring match.
AMR_TO_DRAMP_KEYWORDS: dict[str, list[str]] = {
    "MRSA": ["staphylococcus aureus", "s. aureus", "mrsa"],
    "Mtb": ["mycobacterium tuberculosis", "m. tuberculosis", "mtb"],
    "EColi-CRE": ["escherichia coli", "e. coli"],
    "KpneuCRE": ["klebsiella pneumoniae", "k. pneumoniae"],
    "Abaum": ["acinetobacter baumannii", "a. baumannii"],
    "Paer": ["pseudomonas aeruginosa", "p. aeruginosa"],
    "VRE": ["enterococcus faecium", "enterococcus faecalis", "e. faecium", "e. faecalis", "vre"],
    "NGono": ["neisseria gonorrhoeae", "n. gonorrhoeae"],
}


def _download(url: str, dest: Path, timeout: float = 60.0) -> bool:
    log.info("Downloading %s → %s", url, dest)
    try:
        r = requests.get(url, timeout=timeout, stream=True, headers={
            "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
        })
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
        log.info("  ✓ %d bytes", dest.stat().st_size)
        return True
    except requests.RequestException as exc:
        log.warning("  ✗ download failed: %s", exc)
        return False


def _extract_zip(zip_path: Path, out_dir: Path) -> list[Path]:
    """Extract ZIP, return list of extracted files."""
    import zipfile

    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir)
        return [out_dir / n for n in zf.namelist()]


def _parse_dramp_table(table_path: Path) -> pd.DataFrame:
    """Parse a DRAMP TSV/CSV/Excel into a normalized DataFrame.

    DRAMP table columns vary across releases. We expect (best-effort):
      - DRAMP_ID, Sequence, Sequence_Length, Target_Organism, Activity,
        Hemolytic_activity, Source, Family, etc.
    """
    if not table_path.exists():
        return pd.DataFrame()

    # Try several read patterns
    for reader_kwargs in [
        {"sep": "\t", "encoding": "utf-8"},
        {"sep": ",", "encoding": "utf-8"},
        {"sep": "\t", "encoding": "latin-1"},
    ]:
        try:
            df = pd.read_csv(table_path, **reader_kwargs)
            if len(df.columns) > 3:
                return df
        except Exception:  # noqa: BLE001
            continue

    # Excel?
    try:
        return pd.read_excel(table_path)
    except Exception:  # noqa: BLE001
        log.warning("Could not parse %s", table_path)
        return pd.DataFrame()


def _normalize_dramp_df(df: pd.DataFrame) -> pd.DataFrame:
    """Map DRAMP column names to our standard schema."""
    if df.empty:
        return df

    # Lowercase column lookup (DRAMP uses inconsistent casing)
    cols = {c.lower(): c for c in df.columns}

    def col(*names: str) -> str | None:
        for n in names:
            if n.lower() in cols:
                return cols[n.lower()]
        return None

    seq_col = col("Sequence", "Peptide_Sequence", "Mature_Sequence")
    target_col = col("Target_Organism", "Target_Bacteria", "Activity_Tested_Against",
                     "Activity_Against", "Target")
    hemo_col = col("Hemolytic_Activity", "Hemolysis", "Toxicity",
                   "Hemolytic_activity")
    name_col = col("Name", "Peptide_Name")
    id_col = col("DRAMP_ID", "ID", "Peptide_ID")

    if not seq_col:
        log.warning("No sequence column found in DRAMP table")
        return pd.DataFrame()

    out_rows = []
    for _, row in df.iterrows():
        seq = str(row[seq_col]).strip().upper()
        if not seq or any(ch not in CANONICAL_AAS for ch in seq):
            continue
        if not (5 <= len(seq) <= 60):
            continue

        target = str(row[target_col]).lower() if target_col else ""

        # Match to AMR pathogen short codes
        for short, keywords in AMR_TO_DRAMP_KEYWORDS.items():
            if any(kw in target for kw in keywords):
                hemo_val = str(row[hemo_col]).lower() if hemo_col else ""
                hemolytic_int = 1 if (
                    "hemolytic" in hemo_val
                    or "high" in hemo_val
                    or hemo_val in {"yes", "y", "1", "true"}
                ) else 0

                out_rows.append({
                    "sequence": seq,
                    "pathogen_short": short,
                    "target_organism": str(row[target_col]) if target_col else "",
                    "hemolytic_int": hemolytic_int,
                    "source": "DRAMP",
                    "mic_ug_per_ml": None,  # DRAMP rarely has numeric MIC
                    "length": len(seq),
                    "name": str(row[name_col]) if name_col else "",
                    "dbaasp_id": str(row[id_col]) if id_col else "",
                })
    return pd.DataFrame(out_rows)


def fetch_amps(out_path: Path | str | None = None,
               cache_dir: Path | str = "data/raw/dramp_cache") -> pd.DataFrame:
    """Fetch DRAMP AMPs across all available bulk downloads.

    Tries each DRAMP_URL in turn; aggregates everything that downloads.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[pd.DataFrame] = []
    for url in DRAMP_URLS:
        zip_name = url.rsplit("/", 1)[-1]
        zip_path = cache_dir / zip_name
        if not zip_path.exists() and not _download(url, zip_path):
            continue

        try:
            files = _extract_zip(zip_path, cache_dir / zip_name.replace(".zip", ""))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not extract %s: %s", zip_path, exc)
            continue

        for f in files:
            if f.suffix.lower() in (".tsv", ".csv", ".xlsx", ".xls"):
                df_raw = _parse_dramp_table(f)
                df_norm = _normalize_dramp_df(df_raw)
                if not df_norm.empty:
                    log.info("  parsed %s → %d AMR-relevant rows", f.name, len(df_norm))
                    all_rows.append(df_norm)

    if not all_rows:
        log.warning("DRAMP: no rows parsed from any source")
        return pd.DataFrame()

    df = pd.concat(all_rows, ignore_index=True)
    df = df.drop_duplicates(subset=["sequence", "pathogen_short"], keep="first")
    log.info("DRAMP total after dedup: %d", len(df))

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False) if out_path.suffix == ".csv" else df.to_parquet(out_path, index=False)
        log.info("Wrote %d rows to %s", len(df), out_path)

    return df


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch DRAMP AMPs (bulk download)")
    p.add_argument("--output", type=Path, default=Path("data/raw/dramp_amps.csv"))
    p.add_argument("--cache-dir", type=Path, default=Path("data/raw/dramp_cache"))
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] dramp | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    df = fetch_amps(out_path=args.output, cache_dir=args.cache_dir)
    if df.empty:
        return 1
    log.info("Per-pathogen counts:\n%s", df["pathogen_short"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
