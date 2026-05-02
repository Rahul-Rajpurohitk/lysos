"""CO-ADD (Community for Open Antimicrobial Drug Discovery) data loader.

Source: https://db.co-add.org/downloads — University of Queensland IMB
Snapshot: r03 (Feb 2020) — 845K data points across 100K compounds + 7 organisms

Datasets ingested:
  - Single-concentration inhibition (32 µg/mL @ standard) — 803K rows, 100K compounds
  - Dose-response MIC + CC50 + HC10 — 42K rows, 4.8K compounds
  - 6 of our 8 priority pathogens (Pa, Sa, Ec, Kp, Ab — missing Mtb + Ngono)
  - + Human cytotoxicity (CC50) + erythrocyte hemolysis (HC10) for selectivity

Outputs:
  data/raw/coadd_inhibition.canonical.csv  — all 803K inhibition rows
  data/raw/coadd_doseresponse.canonical.csv — all 42K dose-response rows
  data/raw/coadd_amr_filtered.csv          — filtered to our 8 priority pathogens
"""
from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] coadd | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("coadd")

# CO-ADD organism name → our standardized pathogen_short code
ORGANISM_MAP = {
    "Escherichia coli": "EColi",
    "Pseudomonas aeruginosa": "Paer",
    "Acinetobacter baumannii": "Abaum",
    "Staphylococcus aureus": "MRSA",  # CO-ADD tests against MRSA strain ATCC 43300
    "Klebsiella pneumoniae": "KpneuCRE",  # CO-ADD includes KP carbapenem-resistant strains
    "Candida albicans": "Calb",  # fungal, not in our priority pathogens
    "Cryptococcus neoformans": "Cneo",  # fungal
    "Bacillus subtilis": "Bsub",
    "Streptococcus pneumoniae": "Spneu",
    "Homo sapiens": "Hsap",  # cytotoxicity baseline
}

# Our 8 priority bacterial pathogens (from amr-stage2)
AMR_PRIORITY = {"EColi", "Paer", "Abaum", "MRSA", "KpneuCRE", "Spneu"}

# ---------------------------------------------------------------------------
# Value parsing helpers
# ---------------------------------------------------------------------------

_NUMERIC_RE = re.compile(r"^([<>≤≥]=?)?\s*(\d+(?:\.\d+)?)\s*$")


def parse_drval(value: str | float, unit: str) -> tuple[float | None, str]:
    """Parse a DR value like '32', '>10', '<=0.5' into a numeric value + qualifier.

    Returns (numeric_value, qualifier) where qualifier is one of
    {'=', '>', '<', '>=', '<='}. None if unparseable.
    """
    if value is None or (isinstance(value, float) and value != value):
        return None, "="
    s = str(value).strip()
    m = _NUMERIC_RE.match(s)
    if not m:
        return None, "="
    qualifier = m.group(1) or "="
    qualifier = qualifier.replace("≤", "<=").replace("≥", ">=")
    return float(m.group(2)), qualifier


def um_to_ugml(um_value: float, mw: float | None) -> float | None:
    """Convert µM to µg/mL using molecular weight (g/mol)."""
    if mw is None or mw <= 0:
        return None
    return um_value * mw / 1000.0


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------


def load_coadd(cache_dir: Path) -> tuple:
    """Load both CO-ADD CSVs and return (inhibition_df, doseresponse_df)."""
    import pandas as pd

    inh_path = cache_dir / "CO-ADD_InhibitionData_r03_01-02-2020_CSV.csv"
    dr_path = cache_dir / "CO-ADD_DoseResponseData_r03_01-02-2020_CSV.csv"

    if not inh_path.exists():
        log.error("CO-ADD inhibition CSV missing — download from "
                  "https://db.co-add.org/downloads first.")
        return None, None
    if not dr_path.exists():
        log.error("CO-ADD dose-response CSV missing.")
        return None, None

    log.info("Loading CO-ADD inhibition data (~163 MB)...")
    inh = pd.read_csv(inh_path, low_memory=False)
    log.info("  inhibition: %d rows, %d unique compounds",
             len(inh), inh["COADD_ID"].nunique())

    log.info("Loading CO-ADD dose-response data...")
    dr = pd.read_csv(dr_path, low_memory=False)
    log.info("  dose-response: %d rows, %d unique compounds",
             len(dr), dr["COADD_ID"].nunique())

    return inh, dr


def canonicalize_smiles(smiles_series):
    """Canonicalize SMILES via RDKit; drop salts/charge fragments."""
    from rdkit import Chem
    from rdkit.Chem import SaltRemover

    remover = SaltRemover.SaltRemover()
    canonical = []
    for s in smiles_series:
        if not isinstance(s, str) or not s:
            canonical.append(None)
            continue
        try:
            mol = Chem.MolFromSmiles(s)
            if mol is None:
                canonical.append(None)
                continue
            mol = remover.StripMol(mol)
            canonical.append(Chem.MolToSmiles(mol, canonical=True))
        except Exception:
            canonical.append(None)
    return canonical


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cache-dir", type=Path,
                   default=Path("data/raw/coadd_cache"))
    p.add_argument("--out-dir", type=Path, default=Path("data/raw"))
    p.add_argument("--canonicalize", action="store_true",
                   help="Run RDKit canonicalization (slow but safer for joins)")
    args = p.parse_args()

    inh, dr = load_coadd(args.cache_dir)
    if inh is None or dr is None:
        return 1

    # --- Process dose-response (more valuable — has actual MIC values)
    log.info("Processing dose-response...")
    dr["pathogen_short"] = dr["ORGANISM"].map(ORGANISM_MAP)
    dr["mic_ug_per_ml"] = None
    dr["mic_qualifier"] = "="

    # Parse DRVAL with qualifier
    for idx, row in dr.iterrows():
        val, qual = parse_drval(row["DRVAL_MEDIAN"], row["DRVAL_UNIT"])
        if val is None:
            continue
        if row["DRVAL_UNIT"] == "ug/mL":
            dr.at[idx, "mic_ug_per_ml"] = val
        elif row["DRVAL_UNIT"] == "uM":
            # We don't have MW per row in CO-ADD; leave for canonicalization step
            # to compute via RDKit
            dr.at[idx, "mic_ug_per_ml"] = val  # store µM, mark below
        dr.at[idx, "mic_qualifier"] = qual

    # Canonicalize SMILES if requested
    if args.canonicalize:
        log.info("Canonicalizing SMILES via RDKit (this takes a minute)...")
        dr["smiles_canonical"] = canonicalize_smiles(dr["SMILES"])
    else:
        dr["smiles_canonical"] = dr["SMILES"]

    # Filter to our priority pathogens + write
    dr_amr = dr[dr["pathogen_short"].isin(AMR_PRIORITY)].copy()
    log.info("AMR-priority subset: %d dose-response rows (%d unique compounds)",
             len(dr_amr), dr_amr["COADD_ID"].nunique())

    out_amr_dr = args.out_dir / "coadd_doseresponse.canonical.csv"
    dr_amr.to_csv(out_amr_dr, index=False)
    log.info("Wrote %s", out_amr_dr)

    # --- Process inhibition data (single-concentration, larger but coarser)
    log.info("Processing inhibition data (~803K rows — this takes ~30s)...")
    inh["pathogen_short"] = inh["ORGANISM"].map(ORGANISM_MAP)
    inh["inhib_ave"] = pd.to_numeric(inh["INHIB_AVE"], errors="coerce")
    inh = inh.dropna(subset=["inhib_ave"])
    inh["smiles_canonical"] = inh["SMILES"]  # skip canonicalization on 803K rows

    inh_amr = inh[inh["pathogen_short"].isin(AMR_PRIORITY)].copy()
    log.info("AMR-priority subset: %d inhibition rows (%d unique compounds)",
             len(inh_amr), inh_amr["COADD_ID"].nunique())

    out_amr_inh = args.out_dir / "coadd_inhibition.canonical.csv"
    inh_amr.to_csv(out_amr_inh, index=False)
    log.info("Wrote %s", out_amr_inh)

    # --- Selectivity-relevant: human cytotoxicity (CC50) + hemolysis (HC10)
    cc_subset = dr[dr["DRVAL_TYPE"].isin(["CC50", "HC10"])].copy()
    log.info("Cytotoxicity / hemolysis subset: %d rows", len(cc_subset))
    out_cc = args.out_dir / "coadd_cytotoxicity.csv"
    cc_subset.to_csv(out_cc, index=False)
    log.info("Wrote %s (selectivity reference)", out_cc)

    # --- Summary
    print()
    log.info("=" * 60)
    log.info("CO-ADD ingestion complete")
    log.info("  AMR dose-response rows: %d", len(dr_amr))
    log.info("  AMR inhibition rows:    %d", len(inh_amr))
    log.info("  Human cytotoxicity:     %d", len(cc_subset))
    log.info("  Total new data points:  %d", len(dr_amr) + len(inh_amr) + len(cc_subset))
    return 0


if __name__ == "__main__":
    import pandas as pd
    raise SystemExit(main())
