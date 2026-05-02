"""Per-source data audit + RDKit canonicalization.

Runs on every raw CSV in `data/raw/`. For each source:

  1. Parse SMILES with RDKit. Drop unparseable.
  2. Canonicalize SMILES (`Chem.MolToSmiles(mol, isomericSmiles=True)`).
  3. Detect:
     - duplicate canonical SMILES within source
     - label conflicts (same SMILES, different labels)
     - NaN-string contamination
     - unit anomalies (MIC > 100,000 µg/mL is unphysical)
  4. Write a CLEAN copy at `data/raw/<source>.canonical.csv` and a JSON
     audit report at `data/raw/<source>.audit.json`.

Goals:
  - Every downstream consumer (prepare_amr_data, build_known_antibiotics_index)
    should read the *.canonical.csv* files, not the raw fetch output.
  - Audit JSON gives a per-source quality bar we can put in the pitch deck.

Usage:

    python scripts/audit_and_canonicalize.py
    python scripts/audit_and_canonicalize.py --sources chembl,drugbank
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] audit | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("audit")


SOURCES = {
    "chembl":      ("data/raw/chembl_antibiotics.csv",      "smiles"),
    "dbaasp":      ("data/raw/dbaasp_amps.csv",             "sequence"),
    "dramp":       ("data/raw/dramp_amps.csv",              "sequence"),
    "drugbank":    ("data/raw/drugbank_open.csv",           "smiles"),
    "drugcentral": ("data/raw/drugcentral.csv",             "smiles"),
    "npatlas":     ("data/raw/npatlas.csv",                 "smiles"),
    "pubchem":     ("data/raw/pubchem_antibacterial.csv",   "smiles"),
    "zinc":        ("data/raw/zinc_drug_like.csv",          "smiles"),
    "pdb":         ("data/raw/pdb_amr_targets.csv",         None),
    "card":        ("data/raw/card_resistance.json",        None),
}

VALID_AMINO = set("ACDEFGHIKLMNPQRSTVWY")


def _canonical_smiles(s: str) -> Optional[str]:
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(s)
        if mol is None:
            return None
        return Chem.MolToSmiles(mol, isomericSmiles=True, canonical=True)
    except Exception:  # noqa: BLE001
        return None


def _audit_smiles_csv(path: Path, smi_col: str) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(path, low_memory=False, on_bad_lines="skip")
    n_in = len(df)
    if smi_col not in df.columns:
        return df, {"error": f"missing column {smi_col!r}", "rows_in": n_in}

    # Strip NaN / empty / 'nan' strings
    df[smi_col] = df[smi_col].astype(str).str.strip()
    blank_mask = (df[smi_col].str.lower().isin(["", "nan", "none", "null"]))
    n_blank = int(blank_mask.sum())
    df = df[~blank_mask].copy()

    # Canonicalize
    log.info("  canonicalizing %d SMILES ...", len(df))
    df["smiles_raw"] = df[smi_col]
    df[smi_col] = df["smiles_raw"].map(_canonical_smiles)
    n_unparseable = int(df[smi_col].isna().sum())
    df = df.dropna(subset=[smi_col]).copy()

    # Duplicate detection (canonical key)
    dup_mask = df.duplicated(subset=[smi_col], keep=False)
    n_dup_rows = int(dup_mask.sum())
    n_unique_smiles = df[smi_col].nunique()

    # Label conflicts: same canonical SMILES with multiple distinct labels
    label_conflicts: list[dict] = []
    for label_col in ("mic_log_ug_per_ml", "Y", "standard_value", "hemolytic_int"):
        if label_col not in df.columns:
            continue
        grouped = df.groupby(smi_col)[label_col].nunique()
        bad_smi = grouped[grouped > 1].head(20)
        for s in bad_smi.index:
            sub = df[df[smi_col] == s][[smi_col, label_col]].head(3)
            label_conflicts.append({
                "smiles": s[:80],
                "label_col": label_col,
                "values": sub[label_col].dropna().astype(str).tolist(),
            })

    # Unit-anomaly check (only meaningful for MIC-bearing tables)
    unit_anomalies: list[dict] = []
    if "mic_log_ug_per_ml" in df.columns:
        mic_log = pd.to_numeric(df["mic_log_ug_per_ml"], errors="coerce")
        # plausible MIC range: log10(0.001 µg/mL) = -3, log10(1024 µg/mL) ≈ 3
        bad_mic = (mic_log > 4) | (mic_log < -4)
        unit_anomalies = [
            {"smiles": str(df.iloc[i][smi_col])[:80],
             "mic_log_ug_per_ml": float(mic_log.iloc[i])}
            for i in df.index[bad_mic][:10]
        ]
        n_unit_anomalies = int(bad_mic.sum())
    else:
        n_unit_anomalies = 0

    audit = {
        "rows_in": n_in,
        "rows_blank_dropped": n_blank,
        "rows_unparseable_smiles": n_unparseable,
        "rows_out": len(df),
        "duplicate_canonical_rows": n_dup_rows,
        "unique_canonical_smiles": int(n_unique_smiles),
        "label_conflicts_first_20": label_conflicts,
        "mic_unit_anomalies": n_unit_anomalies,
        "mic_anomaly_examples_first_10": unit_anomalies,
    }
    return df, audit


def _audit_peptide_csv(path: Path, seq_col: str) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(path, low_memory=False, on_bad_lines="skip")
    n_in = len(df)
    if seq_col not in df.columns:
        return df, {"error": f"missing column {seq_col!r}", "rows_in": n_in}

    df[seq_col] = df[seq_col].astype(str).str.strip().str.upper()
    blank_mask = (df[seq_col].str.lower().isin(["", "nan", "none", "null"]))
    n_blank = int(blank_mask.sum())
    df = df[~blank_mask].copy()

    # Reject sequences with non-canonical aa chars
    def _aa_ok(s: str) -> bool:
        return len(s) >= 5 and len(s) <= 200 and set(s).issubset(VALID_AMINO)
    df["_ok"] = df[seq_col].map(_aa_ok)
    n_bad_aa = int((~df["_ok"]).sum())
    df = df[df["_ok"]].drop(columns=["_ok"]).copy()

    n_dup = int(df.duplicated(subset=[seq_col]).sum())
    n_unique = df[seq_col].nunique()

    audit = {
        "rows_in": n_in,
        "rows_blank_dropped": n_blank,
        "rows_bad_aa_dropped": n_bad_aa,
        "rows_out": len(df),
        "duplicate_sequence_rows": n_dup,
        "unique_sequences": int(n_unique),
    }
    return df, audit


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sources", default=",".join(SOURCES.keys()),
                   help="comma-separated subset")
    p.add_argument("--out-dir", type=Path, default=Path("data/raw"))
    p.add_argument("--audit-dir", type=Path, default=Path("data/audits"))
    args = p.parse_args()

    args.audit_dir.mkdir(parents=True, exist_ok=True)
    selected = [s.strip() for s in args.sources.split(",") if s.strip()]
    summary: dict[str, dict] = {}

    for src in selected:
        if src not in SOURCES:
            log.warning("Unknown source: %s — skipping", src)
            continue
        path_str, smi_col = SOURCES[src]
        path = Path(path_str)
        if not path.exists():
            log.warning("Source missing: %s — skipping", path)
            summary[src] = {"missing": True}
            continue
        log.info("Auditing %s (%s) ...", src, path)

        if smi_col is None:
            # Sources without SMILES/sequence (PDB metadata, CARD JSON) — skip
            log.info("  no canonicalization for %s (metadata-only)", src)
            summary[src] = {"skipped": "metadata only"}
            continue

        if src in ("dbaasp", "dramp"):
            df, audit = _audit_peptide_csv(path, smi_col)
        else:
            df, audit = _audit_smiles_csv(path, smi_col)

        summary[src] = audit

        out_path = args.out_dir / f"{path.stem}.canonical{path.suffix}"
        df.to_csv(out_path, index=False)
        log.info("  → %d rows clean → %s", len(df), out_path)

        audit_path = args.audit_dir / f"{src}.audit.json"
        audit_path.write_text(json.dumps(audit, indent=2))
        log.info("  audit → %s", audit_path)

    summary_path = args.audit_dir / "_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    # Print a tight summary table
    print()
    print("=" * 78)
    print(f"{'source':14} {'in':>8} {'out':>8} {'unique':>8} {'unparseable':>12} {'dup':>6}")
    print("-" * 78)
    for src, a in summary.items():
        if a.get("missing") or a.get("skipped"):
            print(f"{src:14} {'-':>8} {'-':>8} {'-':>8} {a.get('skipped') or 'missing':>12}")
            continue
        print(
            f"{src:14} "
            f"{a.get('rows_in', 0):>8} "
            f"{a.get('rows_out', 0):>8} "
            f"{a.get('unique_canonical_smiles') or a.get('unique_sequences', 0):>8} "
            f"{a.get('rows_unparseable_smiles', 0):>12} "
            f"{a.get('duplicate_canonical_rows') or a.get('duplicate_sequence_rows', 0):>6}"
        )
    print("=" * 78)
    print(f"Per-source audits: {args.audit_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
