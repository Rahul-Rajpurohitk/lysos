"""CARD (Comprehensive Antibiotic Resistance Database) loader.

CARD curates resistance genes, mutations, and pathogen → resistance mechanism
mappings. Used here for resistance-context enrichment of training prompts —
the model can learn "for MRSA, we expect mecA-mediated resistance to
β-lactams; design accordingly."

CARD provides a JSON download at:
    https://card.mcmaster.ca/latest/data

We extract:
  - Gene/protein name (e.g., "mecA", "blaOXA-48")
  - Resistance mechanism (e.g., "antibiotic target alteration")
  - Drug class affected (β-lactams, fluoroquinolones, etc.)
  - Source pathogen
  - Reference sequence (optional, for protein context in prompts)

Usage:

    python -m src.data.card --output data/raw/card_resistance.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tarfile
from pathlib import Path

import requests

log = logging.getLogger("card")

CARD_BULK_URL = "https://card.mcmaster.ca/latest/data"
CARD_BROAD_URL = "https://card.mcmaster.ca/latest/ontology"


# CARD pathogen names → our AMR short codes
AMR_TO_CARD_PATHOGENS: dict[str, list[str]] = {
    "MRSA": ["staphylococcus aureus"],
    "Mtb": ["mycobacterium tuberculosis"],
    "EColi-CRE": ["escherichia coli"],
    "KpneuCRE": ["klebsiella pneumoniae"],
    "Abaum": ["acinetobacter baumannii"],
    "Paer": ["pseudomonas aeruginosa"],
    "VRE": ["enterococcus faecium", "enterococcus faecalis"],
    "NGono": ["neisseria gonorrhoeae"],
}


def _download(url: str, dest: Path, timeout: float = 120.0) -> bool:
    log.info("Downloading %s → %s", url, dest)
    try:
        r = requests.get(url, timeout=timeout, stream=True, headers={
            "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
            "Accept": "*/*",
        })
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=128 * 1024):
                if chunk:
                    f.write(chunk)
        log.info("  ✓ %d bytes", dest.stat().st_size)
        return True
    except requests.RequestException as exc:
        log.warning("  ✗ download failed: %s", exc)
        return False


def _extract_tarball(tar_path: Path, out_dir: Path) -> list[Path]:
    """Extract a tar.gz / tar.bz2."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:*") as tf:
        tf.extractall(out_dir)
        return [out_dir / m.name for m in tf.getmembers() if m.isfile()]


def fetch_resistance(
    *,
    out_path: Path | str | None = None,
    cache_dir: Path | str = "data/raw/card_cache",
    pathogens: list[str] | None = None,
) -> list[dict]:
    """Fetch CARD resistance gene catalog filtered to AMR pathogens.

    Returns a list of dicts with one entry per (gene, pathogen, drug_class).
    """
    cache_dir = Path(cache_dir)
    pathogens = pathogens or list(AMR_TO_CARD_PATHOGENS.keys())

    # CARD bulk download is a tarball with multiple files
    tar_path = cache_dir / "card-data.tar.bz2"
    if not tar_path.exists():
        if not _download(CARD_BULK_URL, tar_path):
            log.error("Could not download CARD bulk data")
            return []

    extracted = _extract_tarball(tar_path, cache_dir)
    log.info("Extracted %d files", len(extracted))

    # Find card.json (the main ontology)
    card_json_path = next((p for p in extracted if p.name == "card.json"), None)
    if card_json_path is None:
        # Try aro_index.tsv as a fallback
        log.error("card.json not found in CARD tarball")
        return []

    with open(card_json_path) as f:
        ontology = json.load(f)

    log.info("Loaded CARD ontology: %d records", len(ontology))

    out_rows: list[dict] = []
    for record_id, record in ontology.items():
        if not isinstance(record, dict):
            continue

        # Pathogen filter via CARD's "ARO_taxa" field (and various nested places)
        species_strs = _extract_species(record)
        matched_short = None
        for short in pathogens:
            keywords = AMR_TO_CARD_PATHOGENS[short]
            if any(any(kw in s.lower() for s in species_strs) for kw in keywords):
                matched_short = short
                break
        if matched_short is None:
            continue

        # Drug classes (via CARD ontology relations)
        drug_classes = _extract_drug_classes(record)
        # Resistance mechanism
        mechanism = _extract_mechanism(record)

        gene_name = record.get("ARO_name") or record.get("model_name") or ""
        if not gene_name:
            continue

        out_rows.append({
            "pathogen_short": matched_short,
            "gene_name": gene_name,
            "drug_classes": ",".join(sorted(drug_classes)),
            "resistance_mechanism": mechanism,
            "card_id": record.get("ARO_accession") or record_id,
            "description": record.get("ARO_description", "")[:500],
        })

    log.info("Filtered to %d AMR-relevant CARD records", len(out_rows))

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix == ".json":
            with open(out_path, "w") as f:
                json.dump(out_rows, f, indent=2)
        else:
            import pandas as pd
            df = pd.DataFrame(out_rows)
            (df.to_csv(out_path, index=False) if out_path.suffix == ".csv"
             else df.to_parquet(out_path, index=False))
        log.info("Wrote %d rows to %s", len(out_rows), out_path)

    return out_rows


def _extract_species(record: dict) -> list[str]:
    """Pull species names from various places in a CARD record."""
    species: list[str] = []
    taxa = record.get("ARO_taxa") or record.get("organism") or []
    if isinstance(taxa, list):
        for t in taxa:
            name = (t.get("species") or t.get("name") if isinstance(t, dict) else t) or ""
            if name:
                species.append(str(name))
    # Sometimes nested under model_sequences
    seqs = record.get("model_sequences", {})
    if isinstance(seqs, dict):
        for v in seqs.values():
            if isinstance(v, dict):
                org = v.get("NCBI_taxonomy", {}).get("NCBI_taxonomy_name", "")
                if org:
                    species.append(str(org))
    return species


def _extract_drug_classes(record: dict) -> set[str]:
    classes: set[str] = set()
    cats = record.get("ARO_category", {})
    if isinstance(cats, dict):
        for cat in cats.values():
            if not isinstance(cat, dict):
                continue
            ckind = cat.get("category_aro_class_name", "")
            if ckind == "Drug Class":
                name = cat.get("category_aro_name", "")
                if name:
                    classes.add(str(name))
    return classes


def _extract_mechanism(record: dict) -> str:
    cats = record.get("ARO_category", {})
    if not isinstance(cats, dict):
        return ""
    for cat in cats.values():
        if isinstance(cat, dict) and cat.get("category_aro_class_name") == "Resistance Mechanism":
            return str(cat.get("category_aro_name", ""))
    return ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch CARD resistance catalog")
    p.add_argument("--output", type=Path, default=Path("data/raw/card_resistance.json"))
    p.add_argument("--cache-dir", type=Path, default=Path("data/raw/card_cache"))
    p.add_argument("--pathogens", type=str, default=None)
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] card | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    pathogens = args.pathogens.split(",") if args.pathogens else None
    rows = fetch_resistance(out_path=args.output, cache_dir=args.cache_dir,
                            pathogens=pathogens)
    if not rows:
        return 1
    log.info("Per-pathogen counts:")
    from collections import Counter
    counter = Counter(r["pathogen_short"] for r in rows)
    for short, n in counter.most_common():
        log.info("  %s: %d", short, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
