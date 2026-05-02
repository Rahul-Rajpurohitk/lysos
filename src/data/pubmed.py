"""PubMed loader — research abstracts on AMR / antibiotic / pathogen topics.

Pulls abstracts via NCBI E-utilities for queries like:

  "MRSA" + "vancomycin" + "resistance"
  "Mycobacterium tuberculosis" + "drug discovery"
  "antimicrobial peptide" + "design"
  "beta-lactamase inhibitor" + "novel"

Each abstract is a self-contained block of expert-level reasoning text:
mechanism of action, resistance, structure-activity relationships, clinical
outcomes. This is the gold for chain-of-thought training.

Rate limit: 3 req/sec without API key, 10 req/sec with. We use 2 req/sec
to be safe.

Usage:

    python -m src.data.pubmed --output data/raw/pubmed_amr.csv \\
        --max-per-query 200
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("pubmed")

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
USER_AGENT = "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)"


# Query plan — designed to span mechanism + resistance + design themes.
# Each query targets a specific reasoning angle.
QUERIES = [
    # Per-pathogen reviews (mechanism + epidemiology)
    ('"Staphylococcus aureus"[MeSH] AND review[pt] AND ("antibacterial" OR "resistance")', "MRSA"),
    ('"Mycobacterium tuberculosis"[MeSH] AND review[pt] AND ("drug" OR "resistance")', "Mtb"),
    ('"Escherichia coli"[MeSH] AND review[pt] AND ("ESBL" OR "carbapenemase")', "EColi-CRE"),
    ('"Klebsiella pneumoniae"[MeSH] AND review[pt] AND "carbapenem"', "KpneuCRE"),
    ('"Acinetobacter baumannii"[MeSH] AND review[pt]', "Abaum"),
    ('"Pseudomonas aeruginosa"[MeSH] AND review[pt] AND "resistance"', "Paer"),
    ('"Enterococcus faecium"[MeSH] AND review[pt] AND "vancomycin"', "VRE"),
    ('"Neisseria gonorrhoeae"[MeSH] AND review[pt] AND "resistance"', "NGono"),

    # Mechanism-of-action reviews
    ('"beta-lactamase" AND review[pt] AND "inhibitor"', "mech_blactam"),
    ('"DNA gyrase" AND "fluoroquinolone" AND review[pt]', "mech_quinolone"),
    ('"cell wall biosynthesis" AND "antibiotic" AND review[pt]', "mech_cellwall"),
    ('"ribosome" AND "antibiotic" AND review[pt]', "mech_ribosome"),
    ('"efflux pump" AND "antibacterial" AND review[pt]', "mech_efflux"),
    ('"polymyxin" AND "lipopolysaccharide" AND review[pt]', "mech_polymyxin"),

    # Antimicrobial peptide design
    ('"antimicrobial peptide" AND ("design" OR "engineering") AND review[pt]', "amp_design"),
    ('"cationic peptide" AND "membrane" AND review[pt]', "amp_membrane"),

    # Drug discovery / generative
    ('"antibiotic discovery" AND "machine learning"', "ai_discovery"),
    ('"natural product" AND "antibiotic" AND review[pt]', "natural_products"),
    ('"new antibiotic" AND "approval"', "new_drugs"),

    # Resistance mechanisms
    ('"horizontal gene transfer" AND "antibiotic resistance" AND review[pt]', "hgt"),
    ('"plasmid" AND "antibiotic resistance" AND review[pt]', "plasmid"),
    ('"mecA" AND "MRSA" AND review[pt]', "mecA"),
    ('"vanA" OR "vanB" AND "Enterococcus"', "van"),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path,
                   default=Path("data/raw/pubmed_amr.csv"))
    p.add_argument("--max-per-query", type=int, default=200)
    p.add_argument("--api-key", type=str, default=None,
                   help="NCBI API key (raises rate limit to 10/s)")
    p.add_argument("--years-back", type=int, default=15,
                   help="Restrict to recent N years")
    return p.parse_args()


def _esearch(session, term: str, retmax: int, api_key: str | None) -> list[str]:
    params = {
        "db": "pubmed", "term": term, "retmax": retmax,
        "retmode": "json", "sort": "relevance",
    }
    if api_key:
        params["api_key"] = api_key
    r = session.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("esearchresult", {}).get("idlist", [])


def _efetch_abstracts(session, pmids: list[str], api_key: str | None) -> list[dict]:
    """Batch-fetch abstracts via efetch (XML, parse out title + abstract)."""
    if not pmids:
        return []
    BATCH = 50
    rows: list[dict] = []
    for i in range(0, len(pmids), BATCH):
        batch = pmids[i:i + BATCH]
        params = {
            "db": "pubmed", "id": ",".join(batch),
            "rettype": "abstract", "retmode": "xml",
        }
        if api_key:
            params["api_key"] = api_key
        try:
            r = session.get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=60)
            if not r.ok:
                continue
            # Parse the XML
            root = ET.fromstring(r.text)
            for art in root.findall(".//PubmedArticle"):
                pmid_el = art.find(".//PMID")
                pmid = pmid_el.text if pmid_el is not None else ""
                title_el = art.find(".//ArticleTitle")
                title = "".join(title_el.itertext()) if title_el is not None else ""
                # Abstract may have multiple sections (Background/Methods/...)
                abstract_parts = []
                for ab in art.findall(".//Abstract/AbstractText"):
                    label = ab.get("Label")
                    text = "".join(ab.itertext()).strip()
                    if label:
                        abstract_parts.append(f"{label}: {text}")
                    else:
                        abstract_parts.append(text)
                abstract = "\n".join(abstract_parts)
                journal = ""
                jel = art.find(".//Journal/Title")
                if jel is not None:
                    journal = jel.text or ""
                year_el = art.find(".//PubDate/Year")
                year = int(year_el.text) if year_el is not None and year_el.text and year_el.text.isdigit() else None
                if abstract and len(abstract) > 100:
                    rows.append({
                        "pmid": pmid,
                        "title": title.strip(),
                        "abstract": abstract,
                        "journal": journal,
                        "year": year,
                    })
        except (requests.RequestException, ET.ParseError) as exc:
            log.warning("  efetch batch %d-%d failed: %s", i, i + BATCH, exc)
            continue
        time.sleep(0.5)  # polite
    return rows


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
                        datefmt="%H:%M:%S")
    args = parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    cur_year = 2026
    year_filter = f' AND ("{cur_year - args.years_back}":3000[dp])'

    all_rows: list[dict] = []
    seen_pmids: set[str] = set()
    for term, label in QUERIES:
        log.info("Query [%s]: %s", label, term[:80])
        ids = _esearch(session, term + year_filter, args.max_per_query, args.api_key)
        new_ids = [i for i in ids if i not in seen_pmids]
        seen_pmids.update(new_ids)
        log.info("  %d hits, %d new", len(ids), len(new_ids))
        rows = _efetch_abstracts(session, new_ids, args.api_key)
        for r in rows:
            r["query_label"] = label
        all_rows.extend(rows)
        time.sleep(0.5)
        log.info("  → %d abstracts kept (cumulative: %d)", len(rows), len(all_rows))

    df = pd.DataFrame(all_rows)
    log.info("Total abstracts: %d (mean abs len = %.0f chars)",
             len(df), df["abstract"].str.len().mean() if len(df) else 0)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    log.info("Wrote %d rows to %s (%.1f MB)",
             len(df), args.output, args.output.stat().st_size / (1024 ** 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
