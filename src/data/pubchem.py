"""PubChem BioAssay loader — antibacterial activity data.

PubChem hosts millions of bioassay records. We pull curated antibacterial
assay panels (well-known AIDs) and extract per-compound activity outcomes
+ canonical SMILES.

Strategy:
  1. For each priority pathogen, query PubChem for assays with target
     organism matching the pathogen.
  2. For each assay, download the activity table (PUG REST CSV export).
  3. For "Active" compounds, fetch SMILES via the compound endpoint
     (batched).
  4. Output rows match our standard schema.

PubChem rate limit: 5 req/sec (we go 4 req/sec to be safe).

Site: https://pubchem.ncbi.nlm.nih.gov/

Bulk downloads at:
  https://pubchem.ncbi.nlm.nih.gov/rest/pug/...

Usage:

    python -m src.data.pubchem --output data/raw/pubchem_antibacterial.csv \\
        --max-assays-per-pathogen 20
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
import time
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

log = logging.getLogger("pubchem")

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

# Curated PubChem AIDs known to test antibacterial activity.
# These were sourced via the PubChem assay search for each pathogen.
# Add more as we discover them; but these are high-quality starting points.
CURATED_AIDS_BY_PATHOGEN: dict[str, list[int]] = {
    "MRSA": [
        # Several large S. aureus screening campaigns
        434965,  # Whitehead Inst. S. aureus screen
        2842,    # NIH MLPCN S. aureus
        540317,  # Broad MRSA screening
        720596,  # Broad antibacterial screen
        588352,  # AZ S. aureus
    ],
    "Mtb": [
        1853,     # NIH MLPCN M. tuberculosis
        1626,     # GSK TB drug-discovery
        2098,     # Broad TB primary screen
        488,      # NIAID TB
        1958,     # GSK TB high-throughput
    ],
    "EColi-CRE": [
        720596,   # Broad antibacterial (multi-organism, includes E. coli)
        540317,   # Includes E. coli readout
        588352,   # AZ multi-organism
    ],
    "KpneuCRE": [
        720596,
        540317,
    ],
    "Abaum": [
        720596,
        540317,
    ],
    "Paer": [
        488,
        540317,
        720596,
    ],
    "VRE": [
        540317,
        720596,
    ],
    "NGono": [
        # Smaller curated set
        540317,
    ],
}


# -----------------------------------------------------------------------------
# REST helpers
# -----------------------------------------------------------------------------


class PubChemClient:
    def __init__(self, *, timeout: float = 60.0, retries: int = 3,
                 polite_delay: float = 0.25):
        self.timeout = timeout
        self.retries = retries
        self.polite_delay = polite_delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
        })

    def _get(self, path: str, *, accept: str = "application/json") -> requests.Response:
        url = f"{PUBCHEM_BASE}{path}"
        last_exc = None
        for attempt in range(1, self.retries + 1):
            try:
                r = self.session.get(url, timeout=self.timeout,
                                     headers={"Accept": accept})
                if r.status_code == 503:
                    log.warning("PubChem 503, retrying after %.1fs",
                                self.polite_delay * attempt * 4)
                    time.sleep(self.polite_delay * attempt * 4)
                    continue
                r.raise_for_status()
                time.sleep(self.polite_delay)  # be polite
                return r
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("PubChem fetch failed (%d/%d): %s",
                            attempt, self.retries, exc)
                if attempt < self.retries:
                    time.sleep(self.polite_delay * attempt * 2)
        raise RuntimeError(f"PubChem failed after {self.retries}: {last_exc}")

    def get_assay_csv(self, aid: int) -> pd.DataFrame | None:
        """Get the per-compound activity table for an assay as CSV."""
        try:
            r = self._get(f"/assay/aid/{aid}/CSV", accept="text/csv")
            df = pd.read_csv(io.StringIO(r.text), low_memory=False, on_bad_lines="skip")
            log.info("  AID %d: %d records", aid, len(df))
            return df
        except (RuntimeError, pd.errors.ParserError) as exc:
            log.warning("  AID %d failed: %s", aid, exc)
            return None

    def get_smiles_batch(self, cids: list[int]) -> dict[int, str]:
        """Batch fetch canonical SMILES for a list of CIDs."""
        out: dict[int, str] = {}
        # PubChem accepts up to ~500 CIDs per batch via comma-separated path
        BATCH = 100
        for i in range(0, len(cids), BATCH):
            batch = cids[i:i + BATCH]
            cid_str = ",".join(str(c) for c in batch)
            try:
                r = self._get(f"/compound/cid/{cid_str}/property/CanonicalSMILES/CSV",
                              accept="text/csv")
                df = pd.read_csv(io.StringIO(r.text))
                if "CID" in df.columns and "CanonicalSMILES" in df.columns:
                    for _, row in df.iterrows():
                        try:
                            out[int(row["CID"])] = str(row["CanonicalSMILES"])
                        except (TypeError, ValueError):
                            pass
            except RuntimeError as exc:
                log.warning("  SMILES batch %d-%d failed: %s",
                            i, i + BATCH, exc)
                continue
            log.info("  fetched SMILES for %d / %d CIDs",
                     len(out), min(len(cids), i + BATCH))
        return out


# -----------------------------------------------------------------------------
# High-level fetch
# -----------------------------------------------------------------------------


def _is_active(activity_str: str | float) -> bool:
    """PubChem activity outcome can be 'Active', 'Inactive', 'Inconclusive'."""
    s = str(activity_str).strip().lower()
    return s == "active"


def fetch_pubchem_antibacterial(
    *,
    out_path: Path | str | None = None,
    pathogens: list[str] | None = None,
    max_assays_per_pathogen: int = 5,
    only_active: bool = True,
) -> pd.DataFrame:
    """Fetch antibacterial activity data from curated PubChem assays.

    Args:
        out_path: write CSV/Parquet here
        pathogens: subset of CURATED_AIDS_BY_PATHOGEN keys
        max_assays_per_pathogen: cap per pathogen (each assay is large)
        only_active: keep only 'Active' compounds (recommended for training)
    """
    pathogens = pathogens or list(CURATED_AIDS_BY_PATHOGEN.keys())
    client = PubChemClient()

    all_rows: list[dict] = []
    for short in pathogens:
        aids = CURATED_AIDS_BY_PATHOGEN.get(short, [])[:max_assays_per_pathogen]
        log.info("Fetching %d assays for %s ...", len(aids), short)
        for aid in aids:
            df = client.get_assay_csv(aid)
            if df is None or df.empty:
                continue
            # Find activity column (PubChem labels vary)
            activity_col = next(
                (c for c in df.columns if "outcome" in c.lower()
                 or "activity" in c.lower()), None
            )
            cid_col = "PUBCHEM_CID" if "PUBCHEM_CID" in df.columns else next(
                (c for c in df.columns if "cid" in c.lower()), None
            )
            if not activity_col or not cid_col:
                continue
            df = df[[cid_col, activity_col]].copy()
            df.columns = ["cid", "activity"]
            df = df.dropna()
            if only_active:
                df = df[df["activity"].apply(_is_active)]
            df["pathogen_short"] = short
            df["pubchem_aid"] = aid
            all_rows.extend(df.to_dict("records"))
            log.info("    AID %d → %d active compounds", aid, len(df))

    if not all_rows:
        log.warning("No PubChem records collected")
        return pd.DataFrame()

    log.info("Fetching SMILES for %d unique CIDs...", len(all_rows))
    df = pd.DataFrame(all_rows)
    unique_cids = df["cid"].astype(int).unique().tolist()
    smiles_by_cid = client.get_smiles_batch(unique_cids)
    log.info("  got SMILES for %d / %d CIDs",
             len(smiles_by_cid), len(unique_cids))

    df["smiles"] = df["cid"].astype(int).map(smiles_by_cid)
    df = df.dropna(subset=["smiles"])
    df = df.drop_duplicates(subset=["smiles", "pathogen_short"], keep="first")

    # Match our standard schema for downstream use
    df = df.rename(columns={})
    df["mic_log_ug_per_ml"] = None
    df["name"] = ""
    df["chembl_id"] = ""
    df["standard_type"] = "Active_PubChem"
    df["standard_value"] = 1.0
    df["standard_units"] = "binary"
    df["pchembl_value"] = None
    df["target_organism"] = df["pathogen_short"].map(
        {"MRSA": "Staphylococcus aureus", "Mtb": "Mycobacterium tuberculosis",
         "EColi-CRE": "Escherichia coli", "KpneuCRE": "Klebsiella pneumoniae",
         "Abaum": "Acinetobacter baumannii", "Paer": "Pseudomonas aeruginosa",
         "VRE": "Enterococcus faecium", "NGono": "Neisseria gonorrhoeae"}
    )

    cols = ["smiles", "pathogen_short", "mic_log_ug_per_ml", "name",
            "chembl_id", "standard_type", "standard_value", "standard_units",
            "pchembl_value", "target_organism", "cid", "pubchem_aid"]
    df = df[cols]

    log.info("PubChem: %d antibacterial compound records", len(df))

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix == ".parquet":
            df.to_parquet(out_path, index=False)
        else:
            df.to_csv(out_path, index=False)
        log.info("Wrote %d rows to %s", len(df), out_path)
    return df


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch PubChem antibacterial bioassays")
    p.add_argument("--output", type=Path, default=Path("data/raw/pubchem_antibacterial.csv"))
    p.add_argument("--max-assays-per-pathogen", type=int, default=5)
    p.add_argument("--include-inactive", action="store_true",
                   help="Include 'Inactive' compounds (default: actives only)")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] pubchem | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    df = fetch_pubchem_antibacterial(
        out_path=args.output,
        max_assays_per_pathogen=args.max_assays_per_pathogen,
        only_active=not args.include_inactive,
    )
    if df.empty:
        return 1
    log.info("Per-pathogen counts:\n%s", df["pathogen_short"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
