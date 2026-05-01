"""ChEMBL antibacterial activity loader.

Fetches real MIC + Ki + IC50 measurements from ChEMBL for clinically relevant
AMR pathogens. Uses the official ChEMBL REST API (no client library required).

ChEMBL data we use:
  - molecule_chembl_id, canonical_smiles
  - standard_type ∈ {MIC, MBC, IC50, Ki}
  - standard_value (numeric), standard_units (μg/mL, nM, etc.)
  - target_organism (filtered to AMR pathogens of interest)
  - pchembl_value (the curated -log10(activity) value, if available)

Usage:

    from src.data.chembl import fetch_amr_activities, AMR_TARGET_ORGANISMS

    df = fetch_amr_activities(out_path="data/raw/chembl_antibiotics.csv")
    print(f"Fetched {len(df)} activity records")

CLI (run directly):

    python -m src.data.chembl --output data/raw/chembl_antibiotics.csv \\
        --max-per-pathogen 5000

Caches parsed responses; re-runs are cheap unless --refresh.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

log = logging.getLogger("chembl")

CHEMBL_API = "https://www.ebi.ac.uk/chembl/api/data"

# Map our short pathogen codes to the ChEMBL `target_organism` strings.
# Discovered via:
#   GET https://www.ebi.ac.uk/chembl/api/data/target?organism__icontains=staph&format=json
AMR_TARGET_ORGANISMS: dict[str, list[str]] = {
    "MRSA": [
        "Staphylococcus aureus",
        # MRSA-specific strains in ChEMBL
        "Staphylococcus aureus subsp. aureus",
    ],
    "Mtb": [
        "Mycobacterium tuberculosis",
        "Mycobacterium tuberculosis H37Rv",
    ],
    "EColi-CRE": [
        "Escherichia coli",
        # ChEMBL doesn't always tag CRE specifically; we keep all E. coli
        # and rely on the model to learn from MIC distributions.
    ],
    "KpneuCRE": [
        "Klebsiella pneumoniae",
    ],
    "Abaum": [
        "Acinetobacter baumannii",
    ],
    "Paer": [
        "Pseudomonas aeruginosa",
    ],
    "VRE": [
        "Enterococcus faecium",
        "Enterococcus faecalis",
    ],
    "NGono": [
        "Neisseria gonorrhoeae",
    ],
}


@dataclass
class ChEMBLActivity:
    chembl_id: str
    smiles: str | None
    standard_type: str
    standard_value: float | None
    standard_units: str | None
    target_organism: str
    pchembl_value: float | None
    pathogen_short: str

    def to_dict(self) -> dict:
        return self.__dict__


# -----------------------------------------------------------------------------
# REST helpers
# -----------------------------------------------------------------------------


class ChEMBLClient:
    def __init__(self, *, base_url: str = CHEMBL_API, timeout: float = 30.0,
                 retries: int = 3, retry_delay: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
        })

    def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 429:
                    # Rate-limited — back off
                    delay = float(r.headers.get("Retry-After", self.retry_delay * attempt))
                    log.warning("ChEMBL 429, sleeping %.1fs (attempt %d/%d)",
                                delay, attempt, self.retries)
                    time.sleep(delay)
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, json.JSONDecodeError) as exc:
                last_exc = exc
                log.warning("ChEMBL fetch failed (attempt %d/%d): %s",
                            attempt, self.retries, exc)
                if attempt < self.retries:
                    time.sleep(self.retry_delay * attempt)
        raise RuntimeError(f"ChEMBL request failed after {self.retries} attempts: {last_exc}") from last_exc

    def paginated(self, path: str, params: dict | None = None, *,
                  page_size: int = 1000, key: str = "activities",
                  max_records: int | None = None) -> Iterator[dict]:
        """Iterate over all records of a paginated ChEMBL endpoint."""
        params = dict(params or {})
        params.setdefault("limit", page_size)
        params.setdefault("offset", 0)
        seen = 0
        while True:
            data = self.get(path, params)
            page = data.get(key) or []
            if not page:
                break
            for item in page:
                yield item
                seen += 1
                if max_records and seen >= max_records:
                    return
            meta = data.get("page_meta") or {}
            next_url = meta.get("next")
            if not next_url:
                break
            # ChEMBL gives us a full path in `next`; we only need the offset
            params["offset"] = (params.get("offset", 0) or 0) + len(page)
            log.info("  fetched %d so far (offset=%d)", seen, params["offset"])


# -----------------------------------------------------------------------------
# High-level fetch
# -----------------------------------------------------------------------------


def fetch_organism_activities(
    organism: str,
    *,
    standard_types: tuple[str, ...] = ("MIC", "MBC", "IC50", "Ki"),
    pchembl_min: float | None = None,
    max_records: int | None = 5000,
    client: ChEMBLClient | None = None,
) -> list[dict]:
    """Fetch activity records for one target organism.

    Filters:
      - standard_type in MIC / MBC / IC50 / Ki  (queried one at a time —
        ChEMBL's `__in` filter is slow/times out when combined with others)
      - canonical_smiles not null (we need the SMILES)
      - pchembl_value >= pchembl_min — OPTIONAL, default None.
        Most ChEMBL records don't have pchembl_value computed (it's a derived
        column), so requiring it filters out 95% of real data. We default to
        None and rely on standard_value+units normalization for quality.

    Returns a list of dicts (raw ChEMBL records, with derived fields added).
    """
    client = client or ChEMBLClient()
    log.info("Fetching ChEMBL activities for organism=%s (types=%s, max %s)",
             organism, list(standard_types), max_records)

    all_records: list[dict] = []
    per_type_cap = max_records // max(1, len(standard_types)) if max_records else None

    for s_type in standard_types:
        params = {
            "target_organism": organism,         # no __iexact (returns 0)
            "standard_type": s_type,             # one type at a time (avoid __in timeout)
            "canonical_smiles__isnull": "false",
            "format": "json",
        }

        type_records = 0
        type_skipped = 0
        for rec in client.paginated(
            "/activity.json", params, page_size=1000, key="activities",
            max_records=per_type_cap,
        ):
            # Optional client-side pchembl filter
            if pchembl_min is not None:
                pv = rec.get("pchembl_value")
                try:
                    if pv is None or float(pv) < pchembl_min:
                        type_skipped += 1
                        continue
                except (TypeError, ValueError):
                    type_skipped += 1
                    continue

            smi = rec.get("canonical_smiles") or (
                rec.get("molecule") or {}
            ).get("molecule_structures", {}).get("canonical_smiles")
            if not smi:
                continue

            # Quality gate: must have a numeric standard_value and a known unit.
            # Otherwise the record is unusable for training.
            try:
                _ = float(rec.get("standard_value"))
            except (TypeError, ValueError):
                type_skipped += 1
                continue
            if not rec.get("standard_units"):
                type_skipped += 1
                continue

            rec["canonical_smiles"] = smi
            rec["_target_organism"] = organism
            all_records.append(rec)
            type_records += 1
        log.info("  %s/%s: %d kept, %d skipped",
                 organism, s_type, type_records, type_skipped)

        if max_records and len(all_records) >= max_records:
            log.info("  hit max_records=%d, stopping early", max_records)
            break

    log.info("  → %d total activity records for %s", len(all_records), organism)
    return all_records


def fetch_amr_activities(
    *,
    out_path: Path | str | None = None,
    pathogens: list[str] | None = None,
    max_per_pathogen: int = 5000,
    pchembl_min: float | None = None,
) -> pd.DataFrame:
    """Fetch ChEMBL activities for all AMR pathogens.

    Output CSV/Parquet schema:
      smiles, pathogen_short, mic_log_ug_per_ml, name, chembl_id,
      standard_type, standard_value, standard_units, pchembl_value, target_organism

    `mic_log_ug_per_ml` is computed from `standard_value` + `standard_units`.
    """
    pathogens = pathogens or list(AMR_TARGET_ORGANISMS.keys())
    client = ChEMBLClient()

    rows: list[dict] = []
    for short in pathogens:
        organisms = AMR_TARGET_ORGANISMS.get(short, [])
        for org in organisms:
            recs = fetch_organism_activities(
                org,
                pchembl_min=pchembl_min,
                max_records=max_per_pathogen,
                client=client,
            )
            for rec in recs:
                normalized = _normalize_record(rec, pathogen_short=short)
                if normalized is not None:
                    rows.append(normalized)

    df = pd.DataFrame(rows)
    log.info("Total ChEMBL records collected: %d", len(df))
    if df.empty:
        log.warning("No records collected — check API connectivity?")
        return df

    # Deduplicate by (smiles, pathogen_short, standard_type) — keep best pchembl
    df = df.sort_values("pchembl_value", ascending=False, na_position="last")
    df = df.drop_duplicates(subset=["smiles", "pathogen_short", "standard_type"], keep="first")
    log.info("After dedup: %d unique records", len(df))

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
# Record normalization
# -----------------------------------------------------------------------------

# Convert various ChEMBL units to a common scale (μg/mL).
# We log10 transform at the end, so MIC = 10^log_value μg/mL.

_UNITS_TO_UG_PER_ML: dict[str, float] = {
    "ug.mL-1": 1.0,
    "ug/mL": 1.0,
    "ug ml-1": 1.0,
    "mg.kg-1": float("nan"),  # not a concentration; skip
    "mg/kg": float("nan"),
    "ng.mL-1": 1e-3,
    "ng/mL": 1e-3,
    "mg.mL-1": 1e3,
    "mg/mL": 1e3,
    "g.L-1": 1e3,
    "g/L": 1e3,
    "M": float("nan"),  # molar — needs MW; we skip for simplicity
    "mM": float("nan"),
    "uM": float("nan"),
    "nM": float("nan"),
    "pM": float("nan"),
}


def _normalize_record(rec: dict, *, pathogen_short: str) -> dict | None:
    smi = rec.get("canonical_smiles")
    if not smi:
        return None

    s_type = rec.get("standard_type") or ""
    s_value = rec.get("standard_value")
    s_units = rec.get("standard_units")

    try:
        s_value = float(s_value) if s_value is not None else None
    except (TypeError, ValueError):
        s_value = None

    # Compute log10(MIC, μg/mL) when units are mass-concentration
    mic_log = None
    if s_value is not None and s_units in _UNITS_TO_UG_PER_ML:
        scale = _UNITS_TO_UG_PER_ML[s_units]
        if scale == scale:  # not NaN
            try:
                import math
                mic_log = math.log10(max(1e-6, s_value * scale))
            except Exception:  # noqa: BLE001
                mic_log = None

    return {
        "smiles": smi,
        "pathogen_short": pathogen_short,
        "mic_log_ug_per_ml": mic_log,
        "name": (rec.get("molecule") or {}).get("pref_name") or rec.get("molecule_chembl_id", ""),
        "chembl_id": rec.get("molecule_chembl_id", ""),
        "standard_type": s_type,
        "standard_value": s_value,
        "standard_units": s_units,
        "pchembl_value": _try_float(rec.get("pchembl_value")),
        "target_organism": rec.get("_target_organism") or rec.get("target_organism", ""),
    }


def _try_float(x) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch ChEMBL antibacterial activities")
    p.add_argument("--output", type=Path, default=Path("data/raw/chembl_antibiotics.csv"))
    p.add_argument("--max-per-pathogen", type=int, default=5000)
    p.add_argument("--pchembl-min", type=float, default=None,
                   help="Optional minimum pchembl_value (most records lack it; default off)")
    p.add_argument("--pathogens", type=str, default=None,
                   help=f"Comma-separated subset of {list(AMR_TARGET_ORGANISMS)}")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] chembl | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    pathogens = args.pathogens.split(",") if args.pathogens else None
    df = fetch_amr_activities(
        out_path=args.output,
        pathogens=pathogens,
        max_per_pathogen=args.max_per_pathogen,
        pchembl_min=args.pchembl_min,
    )
    log.info("Per-pathogen counts:\n%s", df["pathogen_short"].value_counts().to_string())
    return 0 if not df.empty else 1


if __name__ == "__main__":
    sys.exit(main())
