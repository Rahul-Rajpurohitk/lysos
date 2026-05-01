"""NPAtlas loader — natural products database (~33K compounds with SMILES + source).

NPAtlas (https://www.npatlas.org) is the curated open natural products
database. Key value for AMR drug design: many real antibiotics ARE natural
products (penicillins, vancomycin, polymyxins, gramicidins, daptomycin,
streptomycin, ...). NPAtlas gives us a chemistry prior over the natural-
product manifold.

We pull the bulk TSV which has ~33 columns. We extract the most useful
ones for Stage 2 SFT.

Source: https://www.npatlas.org/static/downloads/NPAtlas_download.tsv

Output schema:
    smiles, name, source_organism (genus species), source_type
    (Bacterium / Fungus / etc.), molecular_formula, inchi_key, npaid

Usage:

    python -m src.data.npatlas --output data/raw/npatlas.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("npatlas")

URL = "https://www.npatlas.org/static/downloads/NPAtlas_download.tsv"

# Filter to genera that are known antibiotic producers — keeps the corpus
# smaller AND more relevant for Lysos. Set to None for full corpus.
ANTIBIOTIC_PRODUCING_GENERA = {
    "Streptomyces",     # vancomycin, streptomycin, tetracycline, neomycin, ...
    "Bacillus",         # bacitracin, polymyxin, gramicidin
    "Penicillium",      # penicillin
    "Aspergillus",      # cephalosporins
    "Acremonium",       # cephalosporin precursors
    "Pseudomonas",      # mupirocin, pyrrolnitrin
    "Actinomyces",      # erythromycin, lincomycin
    "Micromonospora",   # gentamicin, sisomicin
    "Saccharopolyspora", # erythromycin
    "Amycolatopsis",    # rifamycin, vancomycin
    "Nocardia",         # rifampin precursors
    "Cephalosporium",   # cephalosporin precursors
    "Chromobacterium",  # violacein
    "Lysobacter",       # lysobactin
}


def fetch_npatlas(
    *,
    out_path: Path | str | None = None,
    cache_dir: Path | str = "data/raw/npatlas_cache",
    antibiotic_producers_only: bool = False,
) -> pd.DataFrame:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / "NPAtlas_download.tsv"

    if not cached.exists():
        log.info("Downloading %s (~33 MB)...", URL)
        r = requests.get(URL, timeout=300, stream=True, headers={
            "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
        })
        r.raise_for_status()
        with open(cached, "wb") as f:
            total = 0
            for chunk in r.iter_content(chunk_size=64 * 1024):
                f.write(chunk)
                total += len(chunk)
        log.info("  ✓ %.1f MB", total / (1024 ** 2))

    log.info("Parsing NPAtlas TSV...")
    df = pd.read_csv(cached, sep="\t", on_bad_lines="skip", low_memory=False)
    log.info("  loaded %d rows × %d cols", len(df), len(df.columns))

    out = pd.DataFrame({
        "npaid": df.get("npaid"),
        "smiles": df.get("compound_smiles"),
        "name": df.get("compound_name"),
        "molecular_formula": df.get("compound_molecular_formula"),
        "inchi_key": df.get("compound_inchikey"),
        "source_genus": df.get("genus"),
        "source_species": df.get("origin_species"),
        "source_type": df.get("origin_type"),
    })
    out = out.dropna(subset=["smiles"])
    out = out[out["smiles"].astype(str).str.len() > 5]
    log.info("  with SMILES: %d", len(out))

    if antibiotic_producers_only:
        before = len(out)
        out = out[out["source_genus"].isin(ANTIBIOTIC_PRODUCING_GENERA)]
        log.info("  filtered to antibiotic-producing genera: %d (was %d)",
                 len(out), before)

    out = out.drop_duplicates(subset=["smiles"], keep="first")
    log.info("After dedup by SMILES: %d unique compounds", len(out))

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix == ".csv":
            out.to_csv(out_path, index=False)
        else:
            out.to_parquet(out_path, index=False)
        log.info("Wrote %d rows to %s", len(out), out_path)

    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch NPAtlas natural products")
    p.add_argument("--output", type=Path, default=Path("data/raw/npatlas.csv"))
    p.add_argument("--cache-dir", type=Path,
                   default=Path("data/raw/npatlas_cache"))
    p.add_argument("--antibiotic-producers-only", action="store_true",
                   help="Filter to genera known to produce antibiotics "
                        "(Streptomyces, Bacillus, Penicillium, ...) — "
                        "smaller, more relevant corpus.")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
                        datefmt="%H:%M:%S")
    args = parse_args()
    df = fetch_npatlas(
        out_path=args.output,
        cache_dir=args.cache_dir,
        antibiotic_producers_only=args.antibiotic_producers_only,
    )
    return 0 if not df.empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
