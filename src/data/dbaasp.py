"""DBAASP v3 antimicrobial peptide loader.

DBAASP — Database of Antimicrobial Activity and Structure of Peptides.
~25,000 peptides with measured MIC values, hemolytic activity, etc.

API verified live (2026-05):
  - Listing endpoint: GET https://dbaasp.org/peptides?targets=<org>&limit=N&offset=N&format=json
  - Detail endpoint: GET https://dbaasp.org/peptides/<id>?format=json
  - Listing returns {"totalCount": N, "data": [...]}
  - Listing records have: id, dbaaspId, name, sequence (empty for multimers),
    sequenceLength, complexity ("monomer" or "multimer"), monomers
  - Detail records have: targetActivities, hemoliticCytotoxicActivities
    (note typo: "hemolitic" not "hemolytic"), smiles, unusualAminoAcids

Strategy:
  1. List peptides matching target organism (cheap, paginated)
  2. Filter to monomers with canonical AAs only (skip multimers, D-AAs)
  3. Fetch detail for each (rate-limited, polite delay)
  4. Extract MIC vs queried organism, hemolysis flag

Usage:

    python -m src.data.dbaasp --output data/raw/dbaasp_amps.csv \\
        --max-per-pathogen 500
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

log = logging.getLogger("dbaasp")

DBAASP_LIST = "https://dbaasp.org/peptides"
DBAASP_DETAIL = "https://dbaasp.org/peptides/{pep_id}"

# AMR pathogen → DBAASP target organism strings (matches NCBI taxonomy)
AMR_DBAASP_ORGANISMS: dict[str, list[str]] = {
    "MRSA": ["Staphylococcus aureus"],
    "Mtb": ["Mycobacterium tuberculosis"],
    "EColi-CRE": ["Escherichia coli"],
    "KpneuCRE": ["Klebsiella pneumoniae"],
    "Abaum": ["Acinetobacter baumannii"],
    "Paer": ["Pseudomonas aeruginosa"],
    "VRE": ["Enterococcus faecium", "Enterococcus faecalis"],
    "NGono": ["Neisseria gonorrhoeae"],
}

CANONICAL_AAS = set("ACDEFGHIKLMNPQRSTVWY")


# -----------------------------------------------------------------------------
# REST client
# -----------------------------------------------------------------------------


class DBAASPClient:
    def __init__(self, *, timeout: float = 30.0, retries: int = 3,
                 retry_delay: float = 2.0, polite_delay: float = 0.2):
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self.polite_delay = polite_delay
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
        })

    def _get(self, url: str, params: dict | None = None) -> dict:
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 429:
                    delay = float(r.headers.get("Retry-After", self.retry_delay * attempt))
                    log.warning("DBAASP 429, sleeping %.1fs", delay)
                    time.sleep(delay)
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, json.JSONDecodeError) as exc:
                last_exc = exc
                log.warning("DBAASP fetch failed (%d/%d): %s", attempt, self.retries, exc)
                if attempt < self.retries:
                    time.sleep(self.retry_delay * attempt)
        raise RuntimeError(f"DBAASP request failed: {last_exc}")

    def list_peptides_by_organism(
        self,
        organism: str,
        *,
        page_size: int = 100,
        max_records: int | None = None,
    ) -> list[dict]:
        records: list[dict] = []
        offset = 0
        while True:
            params = {
                "targets": organism,
                "limit": page_size,
                "offset": offset,
                "format": "json",
            }
            data = self._get(DBAASP_LIST, params)
            page = data.get("data") or []  # NOTE: "data" not "peptides"
            if not page:
                break
            records.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)
            if max_records and len(records) >= max_records:
                records = records[:max_records]
                break
            time.sleep(self.polite_delay)
        return records

    def get_detail(self, peptide_id: int) -> dict:
        url = DBAASP_DETAIL.format(pep_id=peptide_id)
        return self._get(url, {"format": "json"})


# -----------------------------------------------------------------------------
# High-level fetch
# -----------------------------------------------------------------------------


def fetch_amps(
    *,
    out_path: Path | str | None = None,
    pathogens: list[str] | None = None,
    max_per_pathogen: int = 500,
    fetch_details: bool = True,
) -> pd.DataFrame:
    """Fetch DBAASP AMPs for AMR pathogens, with detail fetch for MIC/hemolysis.

    Args:
        out_path: optional CSV/Parquet output
        pathogens: subset of AMR_DBAASP_ORGANISMS keys
        max_per_pathogen: cap PER LISTING query (detail fetch caps at this too)
        fetch_details: if True, follow each listing with a detail fetch
                       (slow but gets MIC + hemolysis); if False, just sequences

    Returns:
        DataFrame with one row per (peptide, target_organism).
    """
    pathogens = pathogens or list(AMR_DBAASP_ORGANISMS.keys())
    client = DBAASPClient()

    rows: list[dict] = []
    for short in pathogens:
        for org in AMR_DBAASP_ORGANISMS.get(short, []):
            log.info("Listing DBAASP peptides for %s ...", org)
            try:
                peptides = client.list_peptides_by_organism(org, max_records=max_per_pathogen)
            except RuntimeError as exc:
                log.error("Skipping %s: %s", org, exc)
                continue
            log.info("  → %d peptides listed", len(peptides))

            # Filter to monomers with canonical AAs (skip multimers + D-AA modifications)
            usable = []
            for p in peptides:
                if p.get("complexity") != "monomer":
                    continue
                seq = (p.get("sequence") or "").strip().upper()
                if not seq or any(ch not in CANONICAL_AAS for ch in seq):
                    continue
                if not (5 <= len(seq) <= 60):  # reasonable AMP length
                    continue
                usable.append(p)
            log.info("  → %d usable monomers (after AA + length filter)", len(usable))

            if not fetch_details:
                # Skip the detail fetch — assemble what we have
                for p in usable:
                    rows.append(_basic_row(p, pathogen_short=short, target_organism=org))
                continue

            # Detail fetch: pull MIC + hemolysis per peptide
            log.info("  fetching details for %d peptides...", len(usable))
            for i, p in enumerate(usable, 1):
                try:
                    detail = client.get_detail(p["id"])
                except RuntimeError as exc:
                    log.warning("  skip detail for id=%s: %s", p.get("id"), exc)
                    continue
                row = _detail_row(detail, p, pathogen_short=short, target_organism=org)
                if row is not None:
                    rows.append(row)
                if i % 25 == 0:
                    log.info("    detail fetch %d / %d (%d rows so far)", i, len(usable), len(rows))
                time.sleep(client.polite_delay)

    df = pd.DataFrame(rows)
    log.info("Total DBAASP records: %d", len(df))
    if df.empty:
        log.warning("Got 0 records — check API connectivity?")
        return df
    df = df.drop_duplicates(subset=["sequence", "pathogen_short"], keep="first")
    log.info("After dedup: %d", len(df))

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix == ".parquet":
            df.to_parquet(out_path, index=False)
        else:
            df.to_csv(out_path, index=False)
        log.info("Wrote %d rows to %s", len(df), out_path)
    return df


# -----------------------------------------------------------------------------
# Row builders
# -----------------------------------------------------------------------------


def _basic_row(p: dict, *, pathogen_short: str, target_organism: str) -> dict:
    seq = (p.get("sequence") or "").strip().upper()
    return {
        "sequence": seq,
        "pathogen_short": pathogen_short,
        "target_organism": target_organism,
        "hemolytic_int": 0,
        "source": "DBAASP",
        "mic_ug_per_ml": None,
        "length": len(seq),
        "name": p.get("name") or p.get("majorName") or "",
        "dbaasp_id": p.get("dbaaspId") or "",
    }


def _detail_row(detail: dict, listing: dict, *, pathogen_short: str,
                target_organism: str) -> dict | None:
    """Combine listing + detail into one row with MIC + hemolysis extracted.

    DBAASP detail schema (verified live 2026-05):
      targetActivities: [
        {
          "targetSpecies": {"name": "Staphylococcus aureus ATCC 25923"},
          "activityMeasureGroup": {"name": "MIC"},
          "activityMeasureValue": "MIC",   # string label, ignore
          "concentration": "4",             # numeric value as STRING
          "unit": {"name": "µM"},          # dict — extract .name
          "activity": 4.27708,              # derived metric
        }
      ]
      hemoliticCytotoxicActivities: similar structure (note 'hemolitic' typo)
    """
    seq = ((detail.get("sequence") or listing.get("sequence") or "")
           .strip().upper())
    if not seq or any(ch not in CANONICAL_AAS for ch in seq):
        return None

    # Compute peptide MW for µM → µg/mL conversion
    mw_g_per_mol = _peptide_mw(seq)

    mic_ug_per_ml = None
    matching: list[float] = []
    for ta in (detail.get("targetActivities") or []):
        species = ta.get("targetSpecies") or {}
        species_name = (species.get("name") if isinstance(species, dict) else species or "")
        if not isinstance(species_name, str) or target_organism.lower() not in species_name.lower():
            continue
        # Filter to MIC-class measurements only
        amg = ta.get("activityMeasureGroup") or {}
        amg_name = (amg.get("name") if isinstance(amg, dict) else "") or ""
        if "MIC" not in amg_name.upper() and "MBC" not in amg_name.upper():
            continue

        try:
            conc = float(ta.get("concentration") or 0)
            if conc <= 0:
                continue
            unit_obj = ta.get("unit") or {}
            unit_name = (unit_obj.get("name") if isinstance(unit_obj, dict) else unit_obj or "") or ""
            unit_lower = unit_name.lower()

            if "µg/ml" in unit_lower or "ug/ml" in unit_lower or "μg/ml" in unit_lower:
                matching.append(conc)
            elif "ng/ml" in unit_lower:
                matching.append(conc / 1000.0)
            elif "mg/ml" in unit_lower:
                matching.append(conc * 1000.0)
            elif "µm" in unit_lower or "um" in unit_lower or "μm" in unit_lower:
                # Convert µM → µg/mL using peptide MW: c[µM] × MW[g/mol] / 1000
                if mw_g_per_mol > 0:
                    matching.append(conc * mw_g_per_mol / 1000.0)
            elif "nm" in unit_lower:
                if mw_g_per_mol > 0:
                    matching.append(conc * mw_g_per_mol / 1_000_000.0)
        except (TypeError, ValueError):
            continue
    if matching:
        mic_ug_per_ml = min(matching)

    # Hemolytic flag — DBAASP types may include "Erythrocytes" / "Hemolysis"
    hemo_blocks = (detail.get("hemoliticCytotoxicActivities")
                   or detail.get("hemolyticCytotoxicActivities")
                   or [])
    hemolytic_int = 0
    for h in hemo_blocks:
        try:
            conc = float(h.get("concentration") or 0)
            unit_obj = h.get("unit") or {}
            unit_name = (unit_obj.get("name") if isinstance(unit_obj, dict) else unit_obj or "")
            unit_lower = (unit_name or "").lower()
            in_ug = "µg/ml" in unit_lower or "ug/ml" in unit_lower or "μg/ml" in unit_lower
            if in_ug and 0 < conc <= 100:
                hemolytic_int = 1
                break
            # µM with conversion
            in_um = "µm" in unit_lower or "um" in unit_lower or "μm" in unit_lower
            if in_um and mw_g_per_mol > 0:
                conc_ug_ml = conc * mw_g_per_mol / 1000.0
                if 0 < conc_ug_ml <= 100:
                    hemolytic_int = 1
                    break
        except (TypeError, ValueError):
            continue

    return {
        "sequence": seq,
        "pathogen_short": pathogen_short,
        "target_organism": target_organism,
        "hemolytic_int": hemolytic_int,
        "source": "DBAASP",
        "mic_ug_per_ml": mic_ug_per_ml,
        "length": len(seq),
        "name": detail.get("name") or detail.get("majorName") or listing.get("name") or "",
        "dbaasp_id": detail.get("dbaaspId") or listing.get("dbaaspId") or "",
    }


# Average residue molecular weights (water-loss-adjusted); add water once.
_AA_MW: dict[str, float] = {
    "A": 89.094, "R": 174.203, "N": 132.119, "D": 133.104, "C": 121.158,
    "E": 147.131, "Q": 146.146, "G": 75.067, "H": 155.156, "I": 131.175,
    "L": 131.175, "K": 146.189, "M": 149.211, "F": 165.192, "P": 115.131,
    "S": 105.093, "T": 119.120, "W": 204.228, "Y": 181.191, "V": 117.148,
}
_WATER_MW = 18.015


def _peptide_mw(seq: str) -> float:
    """Compute approximate peptide MW from sequence (Da / g/mol)."""
    if not seq:
        return 0.0
    total = 0.0
    for ch in seq:
        if ch not in _AA_MW:
            return 0.0
        total += _AA_MW[ch] - _WATER_MW
    return total + _WATER_MW


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch DBAASP antimicrobial peptides")
    p.add_argument("--output", type=Path, default=Path("data/raw/dbaasp_amps.csv"))
    p.add_argument("--max-per-pathogen", type=int, default=500,
                   help="Cap per pathogen — detail fetches are slow, default conservative")
    p.add_argument("--no-details", action="store_true",
                   help="Skip detail fetch (fast, but no MIC/hemolysis)")
    p.add_argument("--pathogens", type=str, default=None)
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] dbaasp | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    pathogens = args.pathogens.split(",") if args.pathogens else None
    df = fetch_amps(
        out_path=args.output,
        pathogens=pathogens,
        max_per_pathogen=args.max_per_pathogen,
        fetch_details=not args.no_details,
    )
    if df.empty:
        return 1
    log.info("Per-pathogen counts:\n%s", df["pathogen_short"].value_counts().to_string())
    log.info("Hemolytic distribution:\n%s",
             df.get("hemolytic_int", pd.Series()).value_counts().to_string()
             if "hemolytic_int" in df else "(no detail data)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
