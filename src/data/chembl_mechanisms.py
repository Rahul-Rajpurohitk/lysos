"""ChEMBL `mechanism_of_action` table puller.

Pulls the ChEMBL REST `/mechanism` endpoint for every drug in our
`chembl_antibiotics.canonical.csv` corpus. Each row gives:

  - molecule_chembl_id    → links back to our chemistry data
  - mechanism_of_action   → narrative text (e.g. "Carbonic anhydrase VII inhibitor")
  - target_chembl_id      → linked to ChEMBL target (uniprot accession)
  - action_type           → INHIBITOR / AGONIST / etc.
  - mechanism_comment     → freeform text
  - max_phase             → clinical phase (4 = approved drug)
  - direct_interaction    → bool
  - mechanism_refs        → PubMed / DailyMed references

This is the missing PER-DRUG MECHANISM signal that pure activity tables
don't carry. Particularly valuable for Stage 2 reasoning examples.

Usage:

    python -m src.data.chembl_mechanisms --output data/raw/chembl_mechanisms.csv
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("chembl_mech")

CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"
USER_AGENT = "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path,
                   default=Path("data/raw/chembl_mechanisms.csv"))
    p.add_argument("--input-csv", type=Path,
                   default=Path("data/raw/chembl_antibiotics.canonical.csv"),
                   help="Source ChEMBL CSV — links chembl_id to molecule")
    p.add_argument("--rate", type=float, default=0.10)
    p.add_argument("--max-rows", type=int, default=None,
                   help="Cap unique chembl_ids to query")
    return p.parse_args()


def _fetch_mechanisms(session, chembl_id: str) -> list[dict]:
    """Pull mechanism rows for one molecule."""
    url = f"{CHEMBL_BASE}/mechanism.json"
    params = {"molecule_chembl_id": chembl_id, "limit": 50}
    try:
        r = session.get(url, params=params, timeout=20)
        if not r.ok:
            return []
        return r.json().get("mechanisms", []) or []
    except requests.RequestException:
        return []


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
                        datefmt="%H:%M:%S")
    args = parse_args()

    if not args.input_csv.exists():
        log.error("Input %s missing", args.input_csv)
        return 1

    src = pd.read_csv(args.input_csv, low_memory=False)
    if "chembl_id" not in src.columns:
        log.error("No chembl_id column in %s", args.input_csv)
        return 2
    chembl_ids = sorted({c for c in src["chembl_id"].dropna().astype(str)
                         if c.startswith("CHEMBL")})
    if args.max_rows:
        chembl_ids = chembl_ids[: args.max_rows]
    log.info("Querying %d unique chembl_ids ...", len(chembl_ids))

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    rows: list[dict] = []
    for i, cid in enumerate(chembl_ids):
        time.sleep(args.rate)
        for mech in _fetch_mechanisms(session, cid):
            rows.append({
                "molecule_chembl_id": cid,
                "mechanism_of_action": (mech.get("mechanism_of_action") or "").strip(),
                "action_type": mech.get("action_type"),
                "target_chembl_id": mech.get("target_chembl_id"),
                "max_phase": mech.get("max_phase"),
                "direct_interaction": mech.get("direct_interaction"),
                "disease_efficacy": mech.get("disease_efficacy"),
                "mechanism_comment": mech.get("mechanism_comment"),
                "binding_site_comment": mech.get("binding_site_comment"),
                "selectivity_comment": mech.get("selectivity_comment"),
                "mec_id": mech.get("mec_id"),
                "molecular_mechanism": mech.get("molecular_mechanism"),
                "refs": json.dumps(mech.get("mechanism_refs", []))[:500],
            })
        if (i + 1) % 100 == 0:
            log.info("  progress: %d / %d  (rows so far: %d)",
                     i + 1, len(chembl_ids), len(rows))

    df = pd.DataFrame(rows)
    log.info("Fetched %d mechanism rows", len(df))
    if len(df):
        log.info("  with mechanism_of_action text: %d",
                 int((df["mechanism_of_action"].str.len() > 5).sum()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)
    log.info("Wrote %d rows to %s", len(df), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
