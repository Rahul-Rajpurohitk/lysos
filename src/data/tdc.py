"""TDC (Therapeutics Data Commons) loader for AMR + ADMET datasets.

Source: https://tdcommons.ai
PyTDC package: pip install PyTDC

AMR-relevant + safety-relevant datasets ingested:
  ADME (absorption, distribution, metabolism, excretion):
    - Caco2_Wang        (passive permeability, predicts oral absorption)
    - PAMPA_NCATS       (parallel artificial membrane permeability)
    - HIA_Hou           (human intestinal absorption)
    - BBB_Martins       (blood-brain barrier penetration)
    - Bioavailability_Ma
    - VDss_Lombardo     (volume of distribution)
    - Half_Life_Obach   (drug half-life)
    - PPBR_AZ           (plasma protein binding)
    - CYP2D6_Substrate_CarbonMangels (drug-drug interaction prediction)
    - CYP3A4_Substrate_CarbonMangels
    - CYP2C9_Substrate_CarbonMangels
    - CYP2D6_Veith
    - CYP3A4_Veith
    - CYP2C9_Veith
    - CYP1A2_Veith
    - Clearance_Hepatocyte_AZ
    - Clearance_Microsome_AZ

  TOX (toxicity):
    - hERG               (cardiac toxicity QT prolongation)
    - hERG_Karim
    - AMES               (mutagenicity Ames test)
    - DILI               (drug-induced liver injury)
    - Skin_Reaction
    - Carcinogens_Lagunin
    - LD50_Zhu           (acute oral toxicity)
    - ClinTox            (clinical trial toxicity)

Output: data/raw/tdc_datasets/ — one CSV per dataset
        data/processed/amr-stage2-tdc/ — Stage 2 training examples
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] tdc | %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("tdc")

# Dataset registry: (TDC class, dataset name, task type, units/notes)
ADME_DATASETS = [
    ("ADME", "Caco2_Wang", "regression", "log(cm/s) — passive intestinal permeability"),
    ("ADME", "PAMPA_NCATS", "binary", "0=low/1=high parallel-artificial-membrane permeability"),
    ("ADME", "HIA_Hou", "binary", "0=low/1=high human intestinal absorption"),
    ("ADME", "BBB_Martins", "binary", "0=non-penetrant/1=penetrant blood-brain barrier"),
    ("ADME", "Bioavailability_Ma", "binary", "0=low/1=high oral bioavailability"),
    ("ADME", "VDss_Lombardo", "regression", "L/kg — volume of distribution at steady state"),
    ("ADME", "Half_Life_Obach", "regression", "hours — elimination half-life"),
    ("ADME", "PPBR_AZ", "regression", "% plasma protein bound"),
    ("ADME", "CYP2D6_Substrate_CarbonMangels", "binary", "0=no/1=yes substrate of CYP2D6"),
    ("ADME", "CYP3A4_Substrate_CarbonMangels", "binary", "0=no/1=yes substrate of CYP3A4"),
    ("ADME", "CYP2C9_Substrate_CarbonMangels", "binary", "0=no/1=yes substrate of CYP2C9"),
    ("ADME", "CYP2D6_Veith", "binary", "0=non-inhibitor/1=inhibitor of CYP2D6"),
    ("ADME", "CYP3A4_Veith", "binary", "0=non-inhibitor/1=inhibitor of CYP3A4"),
    ("ADME", "CYP2C9_Veith", "binary", "0=non-inhibitor/1=inhibitor of CYP2C9"),
    ("ADME", "CYP1A2_Veith", "binary", "0=non-inhibitor/1=inhibitor of CYP1A2"),
    ("ADME", "Clearance_Hepatocyte_AZ", "regression", "µL/min/10⁶ cells — hepatocyte clearance"),
    ("ADME", "Clearance_Microsome_AZ", "regression", "µL/min/mg — microsomal clearance"),
]

TOX_DATASETS = [
    ("Tox", "hERG", "binary", "0=non-blocker/1=hERG blocker (cardiac QT risk)"),
    ("Tox", "hERG_Karim", "binary", "0=non-blocker/1=hERG blocker (Karim curated set)"),
    ("Tox", "AMES", "binary", "0=non-mutagenic/1=mutagenic in Ames test"),
    ("Tox", "DILI", "binary", "0=safe/1=drug-induced liver injury"),
    ("Tox", "Skin_Reaction", "binary", "0=non-sensitizer/1=skin sensitizer"),
    ("Tox", "Carcinogens_Lagunin", "binary", "0=non-carcinogen/1=carcinogen"),
    ("Tox", "LD50_Zhu", "regression", "log mol/kg — acute oral LD50"),
    ("Tox", "ClinTox", "binary", "0=approved/1=failed clinical trial for tox"),
]


def fetch_dataset(tdc_class: str, name: str, cache_dir: Path):
    """Pull a TDC dataset to cache + return the underlying DataFrame."""
    if tdc_class == "ADME":
        from tdc.single_pred import ADME
        ds = ADME(name=name, path=str(cache_dir))
    elif tdc_class == "Tox":
        from tdc.single_pred import Tox
        ds = Tox(name=name, path=str(cache_dir))
    else:
        raise ValueError(f"Unknown class {tdc_class}")
    return ds.get_data()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cache-dir", type=Path, default=Path("data/raw/tdc_datasets"))
    args = p.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    all_datasets = ADME_DATASETS + TOX_DATASETS
    log.info("Fetching %d TDC datasets...", len(all_datasets))

    summary = []
    for tdc_class, name, task_type, notes in all_datasets:
        try:
            df = fetch_dataset(tdc_class, name, args.cache_dir)
            log.info("  %-40s %s rows", name, f"{len(df):,}")
            # Save as canonical CSV
            out_csv = args.cache_dir / f"{name.lower()}.csv"
            df.to_csv(out_csv, index=False)
            summary.append({"name": name, "rows": len(df), "task": task_type, "notes": notes})
        except Exception as exc:
            log.warning("  FAILED %s: %s", name, exc)
            summary.append({"name": name, "rows": 0, "task": task_type, "notes": f"ERROR: {exc}"})

    log.info("=" * 60)
    log.info("Total datasets fetched: %d", len([s for s in summary if s["rows"] > 0]))
    log.info("Total rows: %d", sum(s["rows"] for s in summary))

    # Write summary
    import pandas as pd
    pd.DataFrame(summary).to_csv(args.cache_dir / "_summary.csv", index=False)
    log.info("Wrote summary to %s", args.cache_dir / "_summary.csv")


if __name__ == "__main__":
    main()
