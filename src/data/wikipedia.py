"""Wikipedia loader — drug + pathogen + AMR concept articles.

We pull plain-text article extracts for:
  1. Every approved antibiotic (~150 named drugs)
  2. Each priority pathogen + its resistant strains
  3. Each major AMR concept (β-lactamase, efflux pump, vancomycin resistance, ...)

Each Wikipedia article gives us a free, well-curated, fact-checked
explanation of mechanism / history / indication / resistance — exactly
the *reasoning context* missing from raw lookup tables.

Usage:

    python -m src.data.wikipedia --output data/raw/wikipedia_amr.csv

Output columns:
    title, smiles, mechanism, indication, resistance, full_extract, source_url

License: Wikipedia content is CC-BY-SA 4.0. We ship the text as-is and
attribute via the source_url column.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("wikipedia")

WIKI_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)"

# Antibiotic drug names — comprehensive list of clinically used antibacterials.
# Each is a Wikipedia page title.
ANTIBIOTIC_TITLES = [
    # β-lactams (penicillins)
    "Penicillin", "Amoxicillin", "Ampicillin", "Methicillin", "Oxacillin",
    "Cloxacillin", "Flucloxacillin", "Piperacillin", "Ticarcillin",
    "Mezlocillin", "Carbenicillin", "Penicillin G", "Penicillin V",
    "Dicloxacillin", "Nafcillin",
    # β-lactams (cephalosporins)
    "Cefazolin", "Cephalexin", "Cefalotin", "Cefadroxil", "Cefuroxime",
    "Ceftriaxone", "Cefotaxime", "Cefepime", "Ceftazidime", "Cefoxitin",
    "Cefepime", "Ceftaroline", "Ceftolozane",
    # β-lactams (carbapenems)
    "Imipenem", "Meropenem", "Ertapenem", "Doripenem", "Aztreonam",
    # β-lactamase inhibitors
    "Clavulanic acid", "Sulbactam", "Tazobactam", "Avibactam", "Vaborbactam",
    "Relebactam",
    # Fluoroquinolones
    "Ciprofloxacin", "Levofloxacin", "Moxifloxacin", "Ofloxacin",
    "Norfloxacin", "Gatifloxacin", "Gemifloxacin", "Delafloxacin",
    # Aminoglycosides
    "Gentamicin", "Tobramycin", "Amikacin", "Streptomycin", "Neomycin",
    "Kanamycin", "Paromomycin", "Plazomicin",
    # Tetracyclines
    "Tetracycline", "Doxycycline", "Minocycline", "Tigecycline",
    "Eravacycline", "Omadacycline",
    # Macrolides + ketolides
    "Erythromycin", "Azithromycin", "Clarithromycin", "Telithromycin",
    "Fidaxomicin",
    # Glycopeptides + lipoglycopeptides
    "Vancomycin", "Teicoplanin", "Telavancin", "Dalbavancin", "Oritavancin",
    # Lipopeptides
    "Daptomycin",
    # Polymyxins
    "Polymyxin B", "Colistin",
    # Oxazolidinones
    "Linezolid", "Tedizolid", "Sutezolid",
    # Nitrofurans / nitroimidazoles / sulfonamides
    "Nitrofurantoin", "Metronidazole", "Trimethoprim", "Sulfamethoxazole",
    "Sulfadiazine", "Sulfisoxazole",
    # Anti-tuberculosis
    "Isoniazid", "Rifampicin", "Pyrazinamide", "Ethambutol", "Bedaquiline",
    "Pretomanid", "Delamanid",
    # Misc / topical / older
    "Chloramphenicol", "Clindamycin", "Lincomycin", "Mupirocin", "Bacitracin",
    "Fosfomycin", "Fusidic acid", "Rifaximin", "Spectinomycin",
    "Quinupristin/dalfopristin", "Pristinamycin",
]

PATHOGEN_TITLES = [
    "Staphylococcus aureus", "Methicillin-resistant Staphylococcus aureus",
    "Mycobacterium tuberculosis", "Multidrug-resistant tuberculosis",
    "Escherichia coli", "ESBL-producing Enterobacteriaceae",
    "Klebsiella pneumoniae", "Carbapenem-resistant Enterobacteriaceae",
    "Acinetobacter baumannii", "Pseudomonas aeruginosa",
    "Vancomycin-resistant Enterococcus", "Enterococcus faecium",
    "Neisseria gonorrhoeae",
]

AMR_CONCEPT_TITLES = [
    "Antimicrobial resistance", "Antibiotic", "Beta-lactamase",
    "Penicillin-binding protein", "Efflux pump", "Methicillin resistance",
    "Vancomycin resistance", "Linezolid resistance", "Fluoroquinolone resistance",
    "Aminoglycoside resistance", "Multiple drug resistance", "Cell wall",
    "Peptidoglycan", "Lipopolysaccharide", "Bacterial outer membrane",
    "DNA gyrase", "Topoisomerase IV", "30S ribosomal subunit",
    "50S ribosomal subunit", "Folate metabolism",
    "Mobile genetic elements", "Plasmid", "Integron", "Transposon",
    "Comprehensive Antibiotic Resistance Database",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path,
                   default=Path("data/raw/wikipedia_amr.csv"))
    p.add_argument("--titles", type=str, default="all",
                   help="Comma-separated subset, or 'all'")
    return p.parse_args()


def _fetch_extract(session: requests.Session, title: str) -> dict | None:
    """Pull plain-text extract for one Wikipedia title."""
    params = {
        "action": "query", "format": "json",
        "prop": "extracts|pageprops",
        "explaintext": "true",
        "exsectionformat": "plain",
        "titles": title,
        "redirects": 1,
    }
    try:
        r = session.get(WIKI_API, params=params, timeout=20)
        if not r.ok:
            return None
        pages = r.json().get("query", {}).get("pages", {})
        if not pages:
            return None
        page = next(iter(pages.values()))
        if page.get("missing"):
            return None
        return {
            "wikipedia_title": page.get("title", title),
            "pageid": page.get("pageid"),
            "extract": page.get("extract", ""),
        }
    except requests.RequestException:
        return None


def _section(text: str, names: list[str], window: int = 1500) -> str:
    """Extract the first section whose header matches any of `names`."""
    if not text:
        return ""
    lower = text.lower()
    for name in names:
        idx = lower.find("\n" + name.lower())
        if idx > -1:
            return text[idx:idx + window].strip()
    return ""


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
                        datefmt="%H:%M:%S")
    args = parse_args()

    if args.titles == "all":
        titles = ANTIBIOTIC_TITLES + PATHOGEN_TITLES + AMR_CONCEPT_TITLES
    else:
        titles = [t.strip() for t in args.titles.split(",") if t.strip()]
    titles = sorted(set(titles))
    log.info("Fetching %d Wikipedia articles ...", len(titles))

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    rows = []
    for i, title in enumerate(titles):
        if i and i % 25 == 0:
            log.info("  progress: %d / %d", i, len(titles))
        time.sleep(0.1)  # polite
        d = _fetch_extract(session, title)
        if not d or not d["extract"]:
            log.debug("  no extract: %s", title)
            continue
        text = d["extract"]
        rows.append({
            "title": d["wikipedia_title"],
            "pageid": d["pageid"],
            "extract": text,
            "extract_len": len(text),
            "mechanism": _section(text, ["mechanism of action", "mechanism", "pharmacodynamics"]),
            "indication": _section(text, ["medical uses", "indications", "uses"]),
            "resistance": _section(text, ["resistance", "mechanisms of resistance"]),
            "history": _section(text, ["history", "discovery"]),
            "source_url": f"https://en.wikipedia.org/wiki/{d['wikipedia_title'].replace(' ', '_')}",
        })

    df = pd.DataFrame(rows)
    log.info("Total articles fetched: %d", len(df))
    log.info("  mean extract length: %.0f chars",
             df["extract_len"].mean() if len(df) else 0)
    n_with_mech = (df["mechanism"].astype(str).str.len() > 50).sum()
    log.info("  with mechanism section: %d", int(n_with_mech))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    log.info("Wrote %d articles to %s (%.1f MB)",
             len(df), args.output, args.output.stat().st_size / (1024 ** 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
