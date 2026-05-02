"""EUCAST clinical breakpoints (v15.0 2025) loader.

Source: https://www.eucast.org/fileadmin/src/media/PDFs/EUCAST_files/Breakpoint_tables/
Snapshot: v15.0 valid 2025-01-01 to 2025-12-31

Extracts S/I/R MIC breakpoints (µg/mL) for our priority pathogens:
  - Enterobacterales (E. coli, K. pneumoniae)
  - Pseudomonas
  - Acinetobacter
  - Staphylococcus
  - Enterococcus
  - Streptococcus pneumoniae
  - Neisseria
  - Mycobacterium

Output: data/raw/eucast_breakpoints.csv
  columns: pathogen_group, drug, breakpoint_s_mg_l, breakpoint_r_mg_l, source
"""
from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] eucast | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("eucast")

# Sheets we care about
PRIORITY_SHEETS = [
    "Enterobacterales",
    "Pseudomonas",
    "Acinetobacter",
    "Staphylococcus",
    "Enterococcus",
    "S.pneumoniae",  # may be alternative naming
    "Streptococcus A,B,C,G",
    "Neisseria",
    "Haemophilus",
    "Moraxella",
    "M.tuberculosis",
    "M. tuberculosis",  # alternative spelling
]


def _is_numeric_breakpoint(val) -> bool:
    if val is None:
        return False
    s = str(val).strip()
    if not s or s.lower() in ("ie", "ip", "n/a", "nan", "-", "*"):
        return False
    # Allow forms like "0.5", ">8", "<=2", "0.001"
    return bool(re.match(r"^[<>≤≥]?=?\s*\d+(?:\.\d+)?$", s))


def _to_float(val) -> float | None:
    if not _is_numeric_breakpoint(val):
        return None
    s = str(val).strip().lstrip("<>≤≥=").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_eucast_sheet(df, pathogen_group: str) -> list[dict]:
    """Heuristic parser: looks for 'S ≤' and 'R >' columns + drug names.
    EUCAST layout typically: Antimicrobial agent | S ≤ | R > | Notes."""
    out = []
    if df.empty:
        return out

    # Find header row by looking for 'MIC breakpoints'
    header_row_idx = None
    s_col = None
    r_col = None
    drug_col = 0  # usually first column

    for i, row in df.iterrows():
        row_str = " | ".join(str(v) for v in row.values if v is not None)
        if "MIC breakpoint" in row_str or "S ≤" in row_str or "S\xa0≤" in row_str:
            # Look for S ≤ and R > columns in next 1-2 rows
            for j_offset in range(0, 3):
                if i + j_offset >= len(df):
                    continue
                hdr = df.iloc[i + j_offset]
                for col_idx, val in enumerate(hdr):
                    s = str(val).strip() if val is not None else ""
                    if s.startswith("S") and "≤" in s:
                        s_col = col_idx
                    if s.startswith("R") and (">" in s or "≥" in s):
                        r_col = col_idx
                if s_col is not None and r_col is not None:
                    header_row_idx = i + j_offset
                    break
            if header_row_idx is not None:
                break

    if header_row_idx is None or s_col is None or r_col is None:
        return out

    # Extract drug + breakpoints from rows after header
    for i in range(header_row_idx + 1, len(df)):
        row = df.iloc[i]
        drug = str(row.iloc[drug_col]).strip() if row.iloc[drug_col] is not None else ""
        if not drug or drug.lower() in ("nan", ""):
            continue
        s_val = _to_float(row.iloc[s_col]) if s_col < len(row) else None
        r_val = _to_float(row.iloc[r_col]) if r_col < len(row) else None
        if s_val is None and r_val is None:
            continue
        out.append({
            "pathogen_group": pathogen_group,
            "drug": drug,
            "breakpoint_s_mg_l": s_val,
            "breakpoint_r_mg_l": r_val,
            "source": "EUCAST v15.0 (2025)",
        })

    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--xlsx-path", type=Path,
                   default=Path("data/raw/eucast_cache/eucast_v15.0_breakpoints.xlsx"))
    p.add_argument("--output", type=Path,
                   default=Path("data/raw/eucast_breakpoints.csv"))
    args = p.parse_args()

    if not args.xlsx_path.exists():
        log.error("EUCAST XLSX missing — download from https://www.eucast.org first")
        return 1

    import pandas as pd
    xl = pd.ExcelFile(args.xlsx_path)
    log.info("EUCAST XLSX has %d sheets", len(xl.sheet_names))

    all_rows = []
    for sheet in xl.sheet_names:
        # Match sheet to priority list (case-insensitive substring)
        matched = None
        for prio in PRIORITY_SHEETS:
            if prio.lower() in sheet.lower() or sheet.lower() in prio.lower():
                matched = prio
                break
        if matched is None:
            continue

        try:
            df = pd.read_excel(xl, sheet, header=None)
        except Exception as exc:
            log.warning("Could not read sheet %s: %s", sheet, exc)
            continue

        rows = parse_eucast_sheet(df, matched)
        log.info("  %s: %d breakpoints extracted", sheet, len(rows))
        all_rows.extend(rows)

    if not all_rows:
        log.error("No breakpoints extracted")
        return 1

    df_out = pd.DataFrame(all_rows)
    df_out.to_csv(args.output, index=False)
    log.info("Wrote %s (%d total breakpoints)", args.output, len(df_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
