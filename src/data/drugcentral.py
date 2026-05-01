"""DrugCentral loader — open drug structures with INN names + CAS.

DrugCentral (https://drugcentral.org) is a maintained, open-license drug
knowledge base. We use the publicly available `structures.smiles.tsv`
file directly — no API auth, no DUA.

Schema of the source file:
    SMILES \t InChI \t InChIKey \t ID \t INN \t CAS_RN

We normalize to our standard drug-knowledge schema:
    drugbank_id (None — DrugCentral uses its own IDs), smiles, name,
    synonyms (None), cas, inchi_key

Usage:

    python -m src.data.drugcentral --output data/raw/drugcentral.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("drugcentral")

URL = "https://drugcentral.org/static/structures.smiles.tsv"


def fetch_drugcentral(
    *,
    out_path: Path | str | None = None,
    cache_dir: Path | str = "data/raw/drugcentral_cache",
) -> pd.DataFrame:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / "structures.smiles.tsv"

    if not cached.exists():
        log.info("Downloading %s ...", URL)
        r = requests.get(URL, timeout=60, headers={
            "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
        })
        r.raise_for_status()
        cached.write_bytes(r.content)
        log.info("  ✓ %.1f KB", len(r.content) / 1024)

    df = pd.read_csv(cached, sep="\t", on_bad_lines="skip")
    log.info("Loaded %d DrugCentral rows", len(df))

    out = pd.DataFrame({
        "drugcentral_id": df.get("ID"),
        "smiles": df.get("SMILES"),
        "name": df.get("INN"),
        "cas": df.get("CAS_RN"),
        "inchi_key": df.get("InChIKey"),
        "inchi": df.get("InChI"),
    })
    out = out.dropna(subset=["smiles"])
    out = out[out["smiles"].astype(str).str.len() > 5]
    out = out.drop_duplicates(subset=["smiles"], keep="first")
    log.info("After cleanup: %d unique drugs with SMILES", len(out))

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
    p = argparse.ArgumentParser(description="Fetch DrugCentral structures")
    p.add_argument("--output", type=Path,
                   default=Path("data/raw/drugcentral.csv"))
    p.add_argument("--cache-dir", type=Path,
                   default=Path("data/raw/drugcentral_cache"))
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
                        datefmt="%H:%M:%S")
    args = parse_args()
    df = fetch_drugcentral(out_path=args.output, cache_dir=args.cache_dir)
    return 0 if not df.empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
