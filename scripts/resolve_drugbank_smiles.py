"""Resolve DrugBank InChI Keys to canonical SMILES via PubChem.

Input  : data/raw/drugbank_open.csv (14,630 rows, has inchi_key column)
Output : data/raw/drugbank_open_with_smiles.csv (same rows, +smiles)

PubChem rate limit: 5 req/s. We use 4 threads × 1 req/s/thread = 4 req/s total.
With 14,630 InChI Keys → ~60 minutes wall-clock.

Caches each lookup so re-running is cheap.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger("resolve")

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


def resolve_one(session: requests.Session, inchi_key: str,
                max_retries: int = 4) -> str | None:
    """Query PubChem for SMILES given InChI Key. Returns None on miss.

    Honors 503/429 with exponential backoff. PubChem's PUG REST will rate-limit
    aggressively — back off to 5-10 s on rejection, retry up to max_retries.
    """
    if not inchi_key or len(inchi_key) < 25:
        return None
    backoff = 1.0
    for prop in ("SMILES",):  # PubChem renamed; SMILES is canonical now
        url = f"{PUBCHEM_BASE}/compound/inchikey/{inchi_key}/property/{prop}/CSV"
        for attempt in range(max_retries):
            try:
                r = session.get(url, timeout=20)
            except requests.RequestException:
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue
            if r.status_code == 404:
                return None  # genuinely no record
            if r.status_code in (429, 503):
                # rate-limited; back off
                wait = float(r.headers.get("Retry-After", backoff))
                time.sleep(wait)
                backoff = min(backoff * 2, 30.0)
                continue
            if not r.ok:
                return None
            text = r.text.strip()
            lines = text.split("\n")
            if len(lines) < 2:
                return None
            parts = lines[1].split(",", 1)
            if len(parts) < 2:
                return None
            smi = parts[1].strip().strip('"')
            return smi if smi and len(smi) > 3 else None
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path,
                   default=Path("data/raw/drugbank_open.csv"))
    p.add_argument("--output", type=Path,
                   default=Path("data/raw/drugbank_with_smiles.csv"))
    p.add_argument("--cache", type=Path,
                   default=Path("data/raw/drugbank_smiles_cache.json"))
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--limit", type=int, default=None,
                   help="Cap rows for testing")
    p.add_argument("--rate-per-thread", type=float, default=1.0,
                   help="Sleep this many seconds between requests per thread")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] | %(message)s",
                        datefmt="%H:%M:%S")

    log.info("Reading %s ...", args.input)
    df = pd.read_csv(args.input)
    if args.limit:
        df = df.head(args.limit)
    log.info("  %d rows, %d with InChI Key", len(df),
             df["inchi_key"].astype(str).str.len().gt(20).sum())

    cache = {}
    if args.cache.exists():
        cache = json.loads(args.cache.read_text())
        log.info("Loaded %d cached lookups from %s", len(cache), args.cache)

    keys = [str(k).strip() for k in df["inchi_key"]]
    pending = [k for k in keys if k and len(k) > 20 and k not in cache]
    log.info("Need to resolve %d new InChI Keys (cache hits: %d)",
             len(pending), sum(1 for k in keys if k in cache))

    session = requests.Session()
    session.headers.update({
        "User-Agent": "lysos/0.1 (https://github.com/Rahul-Rajpurohitk/lysos)",
    })

    completed = 0
    last_save = time.time()
    last_throttle_check = time.time()
    cumulative_misses_in_window = 0

    def task(key: str):
        nonlocal completed
        time.sleep(args.rate_per_thread / max(args.threads, 1))
        smi = resolve_one(session, key)
        completed += 1
        return key, smi

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futures = [pool.submit(task, k) for k in pending]
        prev_hits = 0
        for fut in as_completed(futures):
            key, smi = fut.result()
            cache[key] = smi or ""
            if completed % 100 == 0:
                hits = sum(1 for v in cache.values() if v)
                window_hit_rate = (hits - prev_hits) / 100.0
                log.info("  ✓ %d / %d  hits=%d (%.1f%%)  window_hit=%.0f%%",
                         completed, len(pending), hits,
                         100 * hits / max(completed, 1),
                         100 * window_hit_rate)
                # If hit rate in last 100 was very low, we're throttled — pause.
                if window_hit_rate < 0.05 and completed > 200:
                    log.warning("  Hit rate collapse — backing off 60s ...")
                    time.sleep(60)
                prev_hits = hits
                if time.time() - last_save > 30:
                    args.cache.write_text(json.dumps(cache))
                    last_save = time.time()

    args.cache.write_text(json.dumps(cache))
    log.info("Cache saved to %s", args.cache)

    df["smiles_pubchem"] = [cache.get(k, "") for k in keys]
    hits = (df["smiles_pubchem"].astype(str).str.len() > 5).sum()
    log.info("Resolved SMILES for %d / %d rows (%.1f%%)",
             hits, len(df), 100 * hits / max(len(df), 1))

    # Merge: prefer existing smiles, fall back to PubChem-resolved
    if "smiles" in df.columns:
        df["smiles"] = df.apply(
            lambda r: r["smiles"] if pd.notna(r.get("smiles")) and len(str(r.get("smiles"))) > 5
            else r["smiles_pubchem"],
            axis=1,
        )
    else:
        df["smiles"] = df["smiles_pubchem"]

    df.to_csv(args.output, index=False)
    log.info("Wrote %d rows to %s", len(df), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
