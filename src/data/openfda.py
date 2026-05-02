"""OpenFDA drug-label loader — clinical reasoning text per FDA-approved drug.

Pulls the FDA's openFDA `drug/label.json` API for every antibiotic-relevant
drug we know about. Each label has rich text: indications_and_usage,
clinical_pharmacology, contraindications, warnings, drug_interactions,
adverse_reactions, mechanism_of_action.

For our generative model, this is *clinical reasoning text* — it explains
WHY a drug is used a certain way, what interactions matter, what failures
have been observed. Pure expert prose, public, free.

Endpoints:
  - https://api.fda.gov/drug/label.json?search=openfda.generic_name:<DRUG>&limit=1
  - 240 requests/min unguarded; ~7 req/sec to be polite

Output schema (one row per drug):
  drug_name, indications, clinical_pharmacology, mechanism_of_action,
  contraindications, warnings, drug_interactions, adverse_reactions,
  pediatric_use, geriatric_use, label_url

Usage:

    python -m src.data.openfda --output data/raw/openfda_labels.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("openfda")

ENDPOINT = "https://api.fda.gov/drug/label.json"
USER_AGENT = "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)"

# Antibiotics we want clinical labels for. ~150 generic names covering
# all major classes. Most exist on FDA label.
ANTIBIOTIC_QUERIES = [
    # β-lactams
    "penicillin", "amoxicillin", "ampicillin", "methicillin", "oxacillin",
    "cloxacillin", "dicloxacillin", "nafcillin", "piperacillin", "ticarcillin",
    "carbenicillin", "mezlocillin",
    # Cephalosporins
    "cefazolin", "cephalexin", "cefadroxil", "cefuroxime", "ceftriaxone",
    "cefotaxime", "cefepime", "ceftazidime", "cefoxitin", "ceftaroline",
    "cefiderocol", "ceftolozane",
    # Carbapenems / monobactam
    "imipenem", "meropenem", "ertapenem", "doripenem", "aztreonam",
    # β-lactamase inhibitors
    "clavulanate", "sulbactam", "tazobactam", "avibactam", "vaborbactam",
    "relebactam",
    # Quinolones
    "ciprofloxacin", "levofloxacin", "moxifloxacin", "ofloxacin",
    "norfloxacin", "gemifloxacin", "delafloxacin",
    # Aminoglycosides
    "gentamicin", "tobramycin", "amikacin", "streptomycin", "neomycin",
    "kanamycin", "plazomicin",
    # Tetracyclines
    "tetracycline", "doxycycline", "minocycline", "tigecycline",
    "eravacycline", "omadacycline",
    # Macrolides + ketolides
    "erythromycin", "azithromycin", "clarithromycin",
    "telithromycin", "fidaxomicin",
    # Glycopeptides + lipoglycopeptides
    "vancomycin", "teicoplanin", "telavancin", "dalbavancin", "oritavancin",
    # Lipopeptides + polymyxins
    "daptomycin", "polymyxin", "colistin",
    # Oxazolidinones
    "linezolid", "tedizolid",
    # Sulfa / nitrofurans / nitroimidazoles
    "trimethoprim", "sulfamethoxazole", "sulfadiazine", "nitrofurantoin",
    "metronidazole",
    # Anti-TB
    "isoniazid", "rifampin", "rifampicin", "pyrazinamide", "ethambutol",
    "bedaquiline", "pretomanid", "delamanid",
    # Other
    "chloramphenicol", "clindamycin", "lincomycin", "mupirocin", "bacitracin",
    "fosfomycin", "rifaximin", "spectinomycin",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path,
                   default=Path("data/raw/openfda_labels.csv"))
    p.add_argument("--api-key", default=None,
                   help="openFDA API key (raises rate limit)")
    p.add_argument("--rate", type=float, default=0.20,
                   help="Sleep between requests (sec)")
    return p.parse_args()


def _section(label: dict, key: str, max_chars: int = 1500) -> str:
    """openFDA returns each label section as a list of strings (often one)."""
    val = label.get(key)
    if not val:
        return ""
    if isinstance(val, list):
        text = "\n".join(str(x) for x in val if x)
    else:
        text = str(val)
    text = text.strip()
    if len(text) > max_chars:
        cut = text[:max_chars].rsplit(". ", 1)[0]
        return cut + "."
    return text


def _fetch(session, query: str, api_key: str | None) -> dict | None:
    params = {
        "search": f"openfda.generic_name:{query}",
        "limit": 1,
    }
    if api_key:
        params["api_key"] = api_key
    try:
        r = session.get(ENDPOINT, params=params, timeout=30)
        if r.status_code == 404:
            return None
        if not r.ok:
            log.warning("  %s -> %s", query, r.status_code)
            return None
        results = r.json().get("results", [])
        return results[0] if results else None
    except requests.RequestException as exc:
        log.warning("  %s -> %s", query, exc)
        return None


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
                        datefmt="%H:%M:%S")
    args = parse_args()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    rows: list[dict] = []
    seen: set[str] = set()
    for i, q in enumerate(ANTIBIOTIC_QUERIES):
        if q in seen:
            continue
        seen.add(q)
        time.sleep(args.rate)
        label = _fetch(session, q, args.api_key)
        if not label:
            continue
        openfda = label.get("openfda", {})
        names = openfda.get("generic_name", [q])
        rows.append({
            "drug_name": names[0] if names else q,
            "brand_names": "|".join(openfda.get("brand_name", []))[:200],
            "rxcui": "|".join(openfda.get("rxcui", []))[:50],
            "indications_and_usage": _section(label, "indications_and_usage"),
            "clinical_pharmacology": _section(label, "clinical_pharmacology"),
            "mechanism_of_action": _section(label, "mechanism_of_action"),
            "contraindications": _section(label, "contraindications", 800),
            "warnings": _section(label, "warnings", 1000),
            "drug_interactions": _section(label, "drug_interactions", 1500),
            "adverse_reactions": _section(label, "adverse_reactions", 1000),
            "pediatric_use": _section(label, "pediatric_use", 800),
            "geriatric_use": _section(label, "geriatric_use", 600),
            "label_url": "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm",
        })
        if (i + 1) % 20 == 0:
            log.info("  progress: %d / %d (kept: %d)",
                     i + 1, len(ANTIBIOTIC_QUERIES), len(rows))

    df = pd.DataFrame(rows)
    log.info("Fetched %d FDA labels", len(df))
    if len(df):
        log.info("  mean indications length: %.0f chars",
                 df["indications_and_usage"].str.len().mean())
        log.info("  with mechanism_of_action: %d",
                 int((df["mechanism_of_action"].str.len() > 50).sum()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    log.info("Wrote %d rows to %s (%.1f MB)",
             len(df), args.output, args.output.stat().st_size / (1024 ** 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
