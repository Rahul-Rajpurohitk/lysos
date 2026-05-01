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
    "inchi_key": ["Standard InChI Key", "InChI Key", "inchi_key", "InChIKey"],
    "accession": ["Accession Numbers", "accession_numbers"],
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


def _parse_sdf_smiles_lite(extract_dir):
    """Best-effort SMILES extraction from SDF without rdkit.

    SDFs typically have a `> <SMILES>` or `> <CANONICAL_SMILES>` data tag
    block. We do a simple regex scan over the file. This won't handle all
    SDF variants but gets a basic SMILES list for free.
    """
    if extract_dir is None or not extract_dir.exists():
        return None
    import re
    smiles_re = re.compile(r"> +<\s*(canonical_)?smiles\s*>\s*\n([^\n]+)", re.IGNORECASE)
    rows = []
    sdf_files = list(extract_dir.glob("*.sdf"))
    for sdf in sdf_files:
        try:
            with open(sdf, encoding="latin-1", errors="ignore") as f:
                text = f.read()
            for m in smiles_re.finditer(text):
                smi = m.group(2).strip()
                if smi and len(smi) > 3:
                    rows.append({
                        "drugbank_id": "",
                        "smiles": smi,
                        "name": "",
                        "synonyms": "",
                        "cas": "",
                        "indication": "",
                    })
        except Exception:  # noqa: BLE001
            continue
    if not rows:
        return None
    return pd.DataFrame(rows)


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
            # DrugBank Open Data files are misnamed: "all-open-structures.csv"
            # is actually a ZIP containing an SDF. We detect by magic bytes.
            with open(dest, "rb") as f:
                magic = f.read(4)
            if magic.startswith(b"PK"):
                # DrugBank publishes both vocabulary AND structures as ZIP-wrapped
                # files mislabelled .csv. Extract first; then parse whatever is
                # inside (real CSV → vocabulary; SDF → structures).
                try:
                    import zipfile
                    extract_dir = dest.parent / dest.stem
                    extract_dir.mkdir(exist_ok=True)
                    with zipfile.ZipFile(dest) as zf:
                        zf.extractall(extract_dir)
                    log.info("  → extracted %s to %s/", dest.name, extract_dir.name)
                except Exception as exc:  # noqa: BLE001
                    log.warning("  could not extract: %s", exc)
                    continue

                # 1. Try to parse any *.csv inside the extracted archive
                csv_inside = list(extract_dir.glob("*.csv"))
                for inner_csv in csv_inside:
                    try:
                        inner_df = pd.read_csv(inner_csv, low_memory=False,
                                               on_bad_lines="skip")
                        log.info("  parsed inner CSV %s: %d rows × %d cols",
                                 inner_csv.name, len(inner_df), len(inner_df.columns))
                        norm = _normalize_columns(inner_df)
                        if not norm.empty:
                            all_dfs.append(norm)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("  could not parse %s: %s", inner_csv.name, exc)

                # 2. SDF files: try the lite SMILES tag scan (won't work for the
                # current DrugBank SDF which uses pure mol blocks, but harmless)
                df_sdf = _parse_sdf_smiles_lite(extract_dir)
                if df_sdf is not None and not df_sdf.empty:
                    log.info("  parsed %d SMILES from SDF via lite scan", len(df_sdf))
                    all_dfs.append(df_sdf)
                elif list(extract_dir.glob("*.sdf")):
                    log.info("  found .sdf with mol-block structures; skipping "
                             "SMILES extraction (needs rdkit on VM)")
                continue

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
    # Keep entries with EITHER a SMILES or an InChI Key (both useful for Stage 2).
    # Vocabulary-only rows (name + InChI Key, no SMILES) still seed knowledge tasks.
    has_smiles = df["smiles"].astype(str).str.len() > 5
    has_inchi = df.get("inchi_key", pd.Series([""] * len(df))).astype(str).str.len() > 5
    df = df[has_smiles | has_inchi]
    # Dedup by name (vocabulary entries) and SMILES (structure entries) separately
    if "name" in df.columns:
        df = df.drop_duplicates(subset=["name"], keep="first")
    log.info(
        "DrugBank Open total: %d entries (%d with SMILES, %d with InChI Key)",
        len(df), int(has_smiles.sum()), int(has_inchi.sum()),
    )

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
