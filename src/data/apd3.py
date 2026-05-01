"""APD3 — Antimicrobial Peptide Database, version 3.

APD3 is the curated antimicrobial peptide database hosted by the University of
Nebraska Medical Center. ~3,500 mature peptide sequences with literature-curated
activity annotations. Smaller than DBAASP / DRAMP but cleaner.

Site: https://aps.unmc.edu/database/anti

APD3 doesn't have a documented JSON API. We use the bulk export they offer
on their downloads page. As of writing, downloads include:

    - https://aps.unmc.edu/database/general/show/all  (HTML; we scrape lightly)
    - Mirror on GitHub (community-maintained TSVs)

We try multiple URLs and fall back to a curated GitHub mirror if the official
site is down.

Usage:

    python -m src.data.apd3 --output data/raw/apd3_amps.csv
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("apd3")

# Multiple fallback URLs. The official APD3 export sometimes returns HTML
# rather than CSV; we try each and parse what we get.
APD3_URLS = [
    "https://aps.unmc.edu/database/files/apd_main.txt",
    "https://aps.unmc.edu/static/database/files/apd_main.txt",
    # Community mirror — open-source curated extracts
    "https://raw.githubusercontent.com/zswgaaa/APD3-mirror/main/APD3.tsv",
]

CANONICAL_AAS = set("ACDEFGHIKLMNPQRSTVWY")

# AMR pathogen → activity-string keyword map (APD3 activity strings are free text)
AMR_TO_APD3_KEYWORDS: dict[str, list[str]] = {
    "MRSA": ["staphylococcus aureus", "s. aureus", "mrsa"],
    "Mtb": ["mycobacterium tuberculosis", "m. tuberculosis", "mtb"],
    "EColi-CRE": ["escherichia coli", "e. coli"],
    "KpneuCRE": ["klebsiella pneumoniae", "k. pneumoniae"],
    "Abaum": ["acinetobacter baumannii", "a. baumannii"],
    "Paer": ["pseudomonas aeruginosa", "p. aeruginosa"],
    "VRE": ["enterococcus faecium", "enterococcus faecalis", "vre"],
    "NGono": ["neisseria gonorrhoeae", "n. gonorrhoeae"],
}


def _try_download(cache_dir: Path) -> Path | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for url in APD3_URLS:
        log.info("Trying %s ...", url)
        dest = cache_dir / url.rsplit("/", 1)[-1]
        if dest.exists():
            log.info("Using cached %s", dest)
            return dest
        try:
            r = requests.get(url, timeout=30, headers={
                "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
                "Accept": "text/plain, */*",
            })
            if r.status_code == 200 and len(r.content) > 1000:
                with open(dest, "wb") as f:
                    f.write(r.content)
                log.info("  ✓ %.2f KB", len(r.content) / 1024)
                return dest
            log.info("  ✗ %d, %d bytes", r.status_code, len(r.content))
        except requests.RequestException as exc:
            log.warning("  ✗ %s", exc)
    return None


def _parse_apd_table(path: Path) -> pd.DataFrame:
    """Parse an APD3 export. Format varies — try TSV first, then heuristic."""
    if not path.exists():
        return pd.DataFrame()

    # Try TSV
    try:
        df = pd.read_csv(path, sep="\t", on_bad_lines="skip", encoding="utf-8",
                         low_memory=False)
        if len(df.columns) >= 3:
            return df
    except Exception:  # noqa: BLE001
        pass

    # Try CSV
    try:
        df = pd.read_csv(path, on_bad_lines="skip", encoding="utf-8",
                         low_memory=False)
        if len(df.columns) >= 3:
            return df
    except Exception:  # noqa: BLE001
        pass

    # Last resort: read raw and extract sequences via regex
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return pd.DataFrame()

    rows = []
    for line in text.splitlines():
        # Generic regex for "ID<tab>name<tab>seq" or similar
        m = re.search(r"\b([ACDEFGHIKLMNPQRSTVWY]{5,60})\b", line)
        if m:
            rows.append({"sequence": m.group(1)})
    return pd.DataFrame(rows)


def _normalize_apd3_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    cols = {c.lower(): c for c in df.columns}

    def col(*names: str) -> str | None:
        for n in names:
            for k, orig in cols.items():
                if n.lower() in k:
                    return orig
        return None

    seq_col = col("sequence", "seq")
    name_col = col("name", "title")
    activity_col = col("activity", "target", "antimicrobial")
    id_col = col("apd", "id")

    if not seq_col:
        log.warning("No sequence column in APD3 table")
        return pd.DataFrame()

    rows = []
    for _, r in df.iterrows():
        seq = str(r[seq_col]).strip().upper()
        if not seq or any(ch not in CANONICAL_AAS for ch in seq):
            continue
        if not (5 <= len(seq) <= 60):
            continue
        # Activity / target may be free text
        activity_text = str(r[activity_col]).lower() if activity_col else ""

        for short, kws in AMR_TO_APD3_KEYWORDS.items():
            if any(kw in activity_text for kw in kws):
                rows.append({
                    "sequence": seq,
                    "pathogen_short": short,
                    "target_organism": activity_text[:200],
                    "hemolytic_int": 1 if "hemolyt" in activity_text else 0,
                    "source": "APD3",
                    "mic_ug_per_ml": None,
                    "length": len(seq),
                    "name": str(r[name_col]) if name_col else "",
                    "dbaasp_id": str(r[id_col]) if id_col else "",
                })
    return pd.DataFrame(rows)


def fetch_apd3_amps(
    *,
    out_path: Path | str | None = None,
    cache_dir: Path | str = "data/raw/apd3_cache",
) -> pd.DataFrame:
    cache_dir = Path(cache_dir)
    src = _try_download(cache_dir)
    if src is None:
        log.warning("APD3: no source available; returning empty")
        return pd.DataFrame()

    raw = _parse_apd_table(src)
    df = _normalize_apd3_df(raw)
    if df.empty:
        # If we couldn't extract per-pathogen labels, return all unique sequences
        # as un-mapped "general AMP" entries. Not as useful but better than nothing.
        seqs = raw[raw.columns[0]].dropna().astype(str)
        canonical = [s.strip().upper() for s in seqs if all(c in CANONICAL_AAS for c in s.strip().upper())]
        canonical = [s for s in canonical if 5 <= len(s) <= 60]
        if canonical:
            df = pd.DataFrame([{
                "sequence": s, "pathogen_short": "general", "target_organism": "",
                "hemolytic_int": 0, "source": "APD3", "mic_ug_per_ml": None,
                "length": len(s), "name": "", "dbaasp_id": "",
            } for s in canonical])
            log.info("APD3: %d unmapped general AMPs", len(df))

    df = df.drop_duplicates(subset=["sequence", "pathogen_short"], keep="first")
    log.info("APD3 total: %d rows", len(df))

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False) if out_path.suffix == ".csv" else df.to_parquet(out_path, index=False)
        log.info("Wrote %d rows to %s", len(df), out_path)
    return df


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch APD3 antimicrobial peptides")
    p.add_argument("--output", type=Path, default=Path("data/raw/apd3_amps.csv"))
    p.add_argument("--cache-dir", type=Path, default=Path("data/raw/apd3_cache"))
    return p.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] apd3 | %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args()
    df = fetch_apd3_amps(out_path=args.output, cache_dir=args.cache_dir)
    if df.empty:
        return 1
    log.info("Per-pathogen counts:\n%s", df["pathogen_short"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
