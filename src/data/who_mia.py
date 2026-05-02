"""WHO 2024 Medically Important Antimicrobials (MIA) List loader.

Source: https://cdn.who.int/media/docs/default-source/gcp/who-mia-list-2024-lv.pdf
Snapshot: 2024 update (replaces 2019 6th revision of CIA list).

Extracts drug → class → WHO category mappings:
  - HPCIA: Highest Priority Critically Important Antimicrobials
  - CIA:   Critically Important Antimicrobials
  - HIA:   Highly Important Antimicrobials
  - IA:    Important Antimicrobials

Usage authorization categories:
  - Humans only
  - Both humans + animals
  - Not authorized in humans

Output: data/raw/who_mia_drugs.csv
"""
from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] who-mia | %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("who-mia")

# Pages 19-35 contain Tables 1-4 — we extract the per-drug lists from Tables 2, 3, 4
TABLE_2_PAGES = list(range(20, 26))   # Authorized for humans only (HPCIA + others)
TABLE_3_PAGES = list(range(26, 32))   # Both humans + animals
TABLE_4_PAGES = list(range(32, 36))   # Not authorized in humans


def extract_who_drugs(pdf_path: Path):
    """Extract drug class entries from WHO MIA PDF Tables 2, 3, 4."""
    import pdfplumber

    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        # Process Table 2: Authorized for humans only (HPCIA-class)
        for page_idx in TABLE_2_PAGES:
            if page_idx >= len(pdf.pages):
                break
            text = pdf.pages[page_idx].extract_text() or ""
            rows.extend(_parse_table(text, "humans_only", "HPCIA"))

        # Process Table 3: Both humans + animals (HPCIA, CIA, HIA, IA)
        for page_idx in TABLE_3_PAGES:
            if page_idx >= len(pdf.pages):
                break
            text = pdf.pages[page_idx].extract_text() or ""
            rows.extend(_parse_table(text, "humans_and_animals", "varies"))

        # Process Table 4: Not authorized for humans
        for page_idx in TABLE_4_PAGES:
            if page_idx >= len(pdf.pages):
                break
            text = pdf.pages[page_idx].extract_text() or ""
            rows.extend(_parse_table(text, "animals_only", "NMI"))

    return rows


def _parse_table(text: str, use_category: str, default_who_cat: str) -> list[dict]:
    """Parse a WHO table page — extract antimicrobial class + drugs."""
    out = []
    if not text:
        return out

    lines = [l.strip() for l in text.split("\n") if l.strip()]

    current_class = None
    current_subclass = None

    # Heuristic: lines with class labels are followed by drug lists (one per line, lowercase)
    for line in lines:
        # Skip header rows + page numbers + footnotes
        if re.match(r"^(Table|WHO List|CIA:|HPCIA|HIA|IA|Antimicrobial|Authorized|Categorization|aFor)",
                    line, re.IGNORECASE):
            continue
        if re.match(r"^\d+$", line):
            continue

        # Detect class header (Title Case + multiple words usually)
        # Heuristic: starts with capital, has 1-3 capitals + lowercase words, NOT a single drug name
        if (re.match(r"^[A-Z][a-z]+", line)
                and len(line.split()) <= 6
                and not any(line.lower().startswith(prefix) for prefix in
                            ["amikacin", "tobramycin", "gentamicin", "vancomycin", "linezolid"])):
            # Could be a class name like "Aminoglycosides" or "3rd-generation cephalosporins"
            # Save it as candidate class
            current_class = line.split(":")[0].strip()
            continue

        # Detect drug names (lowercase, possibly hyphenated, possibly with parens)
        # Match patterns like "amikacin", "ceftazidime-avibactam", "isoniazid"
        drug_match = re.match(r"^([a-z][a-z0-9\-,/ ]{2,40})(\s+\(.*\))?$", line)
        if drug_match and current_class:
            drug = drug_match.group(1).strip().rstrip(",").strip()
            # Skip obvious garbage / multi-word descriptions
            if len(drug.split()) <= 3 and not any(stop in drug.lower() for stop in
                                                    ["category", "drug class", "for the", "of which"]):
                out.append({
                    "drug": drug,
                    "class": current_class,
                    "who_category": default_who_cat,
                    "use_authorization": use_category,
                })

    return out


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--pdf-path", type=Path,
                   default=Path("data/raw/who_cache/who_mia_2024.pdf"))
    p.add_argument("--output", type=Path,
                   default=Path("data/raw/who_mia_drugs.csv"))
    args = p.parse_args()

    if not args.pdf_path.exists():
        log.error("WHO PDF missing: %s", args.pdf_path)
        return 1

    rows = extract_who_drugs(args.pdf_path)
    log.info("Extracted %d drug entries from WHO MIA list", len(rows))

    # Deduplicate
    seen = set()
    unique = []
    for r in rows:
        key = (r["drug"], r["class"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    log.info("Deduplicated: %d unique drug entries", len(unique))

    # Write CSV
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["drug", "class", "who_category", "use_authorization"])
        writer.writeheader()
        writer.writerows(unique)
    log.info("Wrote %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
