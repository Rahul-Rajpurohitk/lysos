"""DBAASP v3 antimicrobial peptide loader.

DBAASP — Database of Antimicrobial Activity and Structure of Peptides.
~17,000 peptides with measured MIC values, hemolytic activity, secondary
structure, and target organism annotations.

API base: https://dbaasp.org/peptides
API docs: https://dbaasp.org/info?section=services

We use the public read-only JSON endpoints. No auth required as of writing.

Usage:

    from src.data.dbaasp import fetch_amps

    df = fetch_amps(out_path="data/raw/dbaasp_amps.csv")

CLI:

    python -m src.data.dbaasp --output data/raw/dbaasp_amps.csv \\
        --max-records 20000

The output schema matches what scripts/prepare_amr_data.py expects:
  sequence, pathogen_short, hemolytic_int, source, mic_ug_per_ml,
  length, name, dbaasp_id
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

DBAASP_API = "https://dbaasp.org/peptides"
DBAASP_PEPTIDE_DETAIL = "https://dbaasp.org/peptides/{pep_id}"

# Map our AMR pathogen short codes to DBAASP target organism filter strings.
# DBAASP organism strings are pretty consistent with NCBI taxonomy.
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


# -----------------------------------------------------------------------------
# REST helpers
# -----------------------------------------------------------------------------


class DBAASPClient:
    def __init__(self, *, base_url: str = DBAASP_API, timeout: float = 30.0,
                 retries: int = 3, retry_delay: float = 2.0):
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
        })

    def _request(self, url: str, params: dict | None = None) -> dict | list:
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
                log.warning("DBAASP fetch failed (attempt %d/%d): %s", attempt, self.retries, exc)
                if attempt < self.retries:
                    time.sleep(self.retry_delay * attempt)
        raise RuntimeError(f"DBAASP request failed after {self.retries} attempts: {last_exc}")

    def list_peptides_by_organism(
        self,
        organism: str,
        *,
        page_size: int = 100,
        max_records: int | None = None,
    ) -> list[dict]:
        """Fetch peptides whose `targets` include the given organism."""
        records: list[dict] = []
        offset = 0
        while True:
            params = {
                "limit": page_size,
                "offset": offset,
                "format": "json",
                "targets": organism,
            }
            payload = self._request(self.base_url, params)
            page = payload if isinstance(payload, list) else payload.get("peptides", [])
            if not page:
                break
            records.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)
            if max_records and len(records) >= max_records:
                records = records[:max_records]
                break
            log.info("  %s: fetched %d so far", organism, len(records))
            time.sleep(0.2)  # be polite
        return records

    def get_peptide_detail(self, peptide_id: int | str) -> dict:
        url = DBAASP_PEPTIDE_DETAIL.format(pep_id=peptide_id)
        return self._request(url)


# -----------------------------------------------------------------------------
# High-level fetch
# -----------------------------------------------------------------------------


def fetch_amps(
    *,
    out_path: Path | str | None = None,
    pathogens: list[str] | None = None,
    max_per_pathogen: int = 5000,
    fetch_details: bool = False,
) -> pd.DataFrame:
    """Fetch DBAASP AMPs for AMR pathogens.

    Args:
        out_path: optional output CSV/Parquet
        pathogens: subset of AMR_DBAASP_ORGANISMS keys
        max_per_pathogen: cap rows per pathogen
        fetch_details: if True, fetch full record per peptide (slower, more fields)

    Returns:
        DataFrame with one row per (peptide, target_organism) combination.
    """
    pathogens = pathogens or list(AMR_DBAASP_ORGANISMS.keys())
    client = DBAASPClient()

    rows: list[dict] = []
    for short in pathogens:
        for org in AMR_DBAASP_ORGANISMS.get(short, []):
            log.info("Fetching DBAASP for organism=%s", org)
            try:
                peptides = client.list_peptides_by_organism(
                    org, max_records=max_per_pathogen,
                )
            except RuntimeError as exc:
                log.error("Skipping %s: %s", org, exc)
                continue
            log.info("  %s: %d peptides", org, len(peptides))
            for pep in peptides:
                row = _normalize_peptide(pep, pathogen_short=short, target_organism=org)
                if row is not None:
                    rows.append(row)

    df = pd.DataFrame(rows)
    log.info("Total DBAASP records: %d", len(df))
    if df.empty:
        log.warning("No DBAASP records collected. Check API connectivity.")
        return df

    # Dedup by (sequence, pathogen_short)
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
# Normalization
# -----------------------------------------------------------------------------


def _normalize_peptide(pep: dict, *, pathogen_short: str, target_organism: str) -> dict | None:
    """Convert one DBAASP peptide record into our standard schema."""
    seq = pep.get("sequence") or pep.get("seq") or ""
    seq = seq.strip().upper()
    if not seq or any(ch not in "ACDEFGHIKLMNPQRSTVWY" for ch in seq):
        # DBAASP includes some non-canonical (e.g., d-amino acids); skip those for now
        return None

    # Best-effort MIC extraction. DBAASP records often have a "targets" list with
    # per-strain MIC values; we use the minimum MIC across matching strains.
    mic_ug_per_ml = None
    targets = pep.get("targetActivities") or pep.get("targets") or []
    matching_mics: list[float] = []
    for t in targets:
        target_name = (t.get("organism") or t.get("targetSpecies") or "").lower()
        if target_organism.lower() not in target_name:
            continue
        mic_val = t.get("activityMeasureValue") or t.get("activity") or t.get("mic")
        units = t.get("activityMeasureUnit") or t.get("units") or "ug/ml"
        try:
            mic = float(mic_val)
            if "ug/ml" in str(units).lower() or "μg" in str(units).lower():
                matching_mics.append(mic)
            elif "ng/ml" in str(units).lower():
                matching_mics.append(mic / 1000.0)
        except (TypeError, ValueError):
            continue
    if matching_mics:
        mic_ug_per_ml = min(matching_mics)

    # Hemolytic activity (1 = hemolytic, 0 = not). DBAASP has a hemolyticAndCytotoxicActivity field.
    hemolytic_int = _extract_hemolytic_flag(pep)

    return {
        "sequence": seq,
        "pathogen_short": pathogen_short,
        "target_organism": target_organism,
        "hemolytic_int": hemolytic_int,
        "source": "DBAASP",
        "mic_ug_per_ml": mic_ug_per_ml,
        "length": len(seq),
        "name": pep.get("name") or pep.get("commonName") or "",
        "dbaasp_id": pep.get("id") or pep.get("dbaaspId") or "",
    }


def _extract_hemolytic_flag(pep: dict) -> int:
    """Extract a binary hemolytic-or-not flag from DBAASP record."""
    hemo_blocks = pep.get("hemolyticAndCytotoxicActivities") or pep.get("hemolytic") or []
    if not hemo_blocks:
        # DBAASP sometimes has top-level "hemolytic" boolean
        v = pep.get("hemolytic")
        if isinstance(v, bool):
            return 1 if v else 0
        return 0  # absence of evidence ≠ proof of safety, but we default to non-hemolytic
    # If any record reports hemolysis at therapeutic conc (<= 100 ug/mL), call it hemolytic.
    for h in hemo_blocks:
        try:
            mic = float(h.get("activity") or h.get("activityMeasureValue") or 0)
            units = (h.get("units") or h.get("activityMeasureUnit") or "ug/ml").lower()
            if "ug/ml" in units and 0 < mic <= 100:
                return 1
        except (TypeError, ValueError):
            continue
    return 0


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch DBAASP antimicrobial peptides")
    p.add_argument("--output", type=Path, default=Path("data/raw/dbaasp_amps.csv"))
    p.add_argument("--max-per-pathogen", type=int, default=5000)
    p.add_argument("--pathogens", type=str, default=None,
                   help=f"Comma-separated subset of {list(AMR_DBAASP_ORGANISMS)}")
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
    )
    log.info("Per-pathogen counts:\n%s", df["pathogen_short"].value_counts().to_string())
    return 0 if not df.empty else 1


if __name__ == "__main__":
    sys.exit(main())
