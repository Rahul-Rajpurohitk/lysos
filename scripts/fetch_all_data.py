"""Unified data fetch orchestrator for Lysos.

Runs all real data loaders in sequence:
  1. ChEMBL antibacterial activities
  2. DBAASP antimicrobial peptides
  3. DRAMP AMPs (bulk download + parse)
  4. CARD resistance catalog
  5. (later) APD3, BindingDB

Each step writes to data/raw/, with caching so re-running skips already-fetched
sources. After all fetches, runs prepare_amr_data.py + prepare_tdc_data.py +
prepare_stage3_prompts.py to build the processed datasets.

Usage:

    # Full fetch + process (~30-60 min, network-bound)
    python scripts/fetch_all_data.py

    # Just the data fetches, skip processing
    python scripts/fetch_all_data.py --no-process

    # Limit per-pathogen records (for fast iteration)
    python scripts/fetch_all_data.py --max-per-pathogen 200

    # Push processed datasets to HF Hub
    python scripts/fetch_all_data.py --push-to-hub
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] fetch_all | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch_all")


def step(name: str):
    """Decorator-ish: log the start/end of a major step with timing."""
    def deco(fn):
        def wrapped(*args, **kwargs):
            log.info("=" * 60)
            log.info("STEP: %s", name)
            log.info("=" * 60)
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                log.info("✓ %s completed in %.1fs", name, time.perf_counter() - t0)
                return result
            except Exception as exc:  # noqa: BLE001
                log.error("✗ %s failed after %.1fs: %s", name, time.perf_counter() - t0, exc)
                raise
        return wrapped
    return deco


@step("ChEMBL antibacterial activities")
def fetch_chembl(args: argparse.Namespace) -> bool:
    from src.data.chembl import fetch_amr_activities

    out = args.data_root / "chembl_antibiotics.csv"
    if out.exists() and not args.refresh:
        log.info("Using cached %s", out)
        return True
    df = fetch_amr_activities(out_path=out, max_per_pathogen=args.max_per_pathogen)
    return not df.empty


@step("DBAASP antimicrobial peptides")
def fetch_dbaasp(args: argparse.Namespace) -> bool:
    from src.data.dbaasp import fetch_amps

    out = args.data_root / "dbaasp_amps.csv"
    if out.exists() and not args.refresh:
        log.info("Using cached %s", out)
        return True
    # DBAASP is slow due to N+1 detail fetches; cap conservatively
    cap = min(args.max_per_pathogen, 500)
    df = fetch_amps(out_path=out, max_per_pathogen=cap, fetch_details=True)
    return not df.empty


@step("DRAMP bulk download")
def fetch_dramp(args: argparse.Namespace) -> bool:
    from src.data.dramp import fetch_amps

    out = args.data_root / "dramp_amps.csv"
    if out.exists() and not args.refresh:
        log.info("Using cached %s", out)
        return True
    df = fetch_amps(out_path=out, cache_dir=args.data_root / "dramp_cache")
    return not df.empty


@step("CARD resistance catalog")
def fetch_card(args: argparse.Namespace) -> bool:
    from src.data.card import fetch_resistance

    out = args.data_root / "card_resistance.json"
    if out.exists() and not args.refresh:
        log.info("Using cached %s", out)
        return True
    rows = fetch_resistance(out_path=out, cache_dir=args.data_root / "card_cache")
    return bool(rows)


@step("BindingDB binding affinities (bacterial subset)")
def fetch_bindingdb(args: argparse.Namespace) -> bool:
    from src.data.bindingdb import fetch_bindingdb as _fetch

    out = args.data_root / "bindingdb_antibacterial.csv"
    if out.exists() and not args.refresh:
        log.info("Using cached %s", out)
        return True
    df = _fetch(out_path=out, cache_dir=args.data_root / "bindingdb_cache")
    return not df.empty


@step("PubChem antibacterial bioassays")
def fetch_pubchem(args: argparse.Namespace) -> bool:
    from src.data.pubchem import fetch_pubchem_antibacterial

    out = args.data_root / "pubchem_antibacterial.csv"
    if out.exists() and not args.refresh:
        log.info("Using cached %s", out)
        return True
    df = fetch_pubchem_antibacterial(
        out_path=out,
        max_assays_per_pathogen=min(args.max_per_pathogen // 100 + 1, 5),
    )
    return not df.empty


@step("ZINC drug-like / FDA chemical space")
def fetch_zinc(args: argparse.Namespace) -> bool:
    from src.data.zinc import fetch_zinc_subsets

    out = args.data_root / "zinc_drug_like.csv"
    if out.exists() and not args.refresh:
        log.info("Using cached %s", out)
        return True
    # FDA + investigational + in-trials are small (~10K total) and very useful;
    # "world" is ~250K and still manageable. Skip the giant in-stock-druglike
    # by default — that's a separate opt-in.
    df = fetch_zinc_subsets(
        out_path=out,
        cache_dir=args.data_root / "zinc_cache",
        subsets=["fda", "investigational", "in-trials", "world"],
    )
    return not df.empty


@step("APD3 antimicrobial peptides")
def fetch_apd3(args: argparse.Namespace) -> bool:
    from src.data.apd3 import fetch_apd3_amps

    out = args.data_root / "apd3_amps.csv"
    if out.exists() and not args.refresh:
        log.info("Using cached %s", out)
        return True
    df = fetch_apd3_amps(out_path=out, cache_dir=args.data_root / "apd3_cache")
    return not df.empty


@step("DrugBank Open Data (free tier)")
def fetch_drugbank(args: argparse.Namespace) -> bool:
    from src.data.drugbank import fetch_drugbank_open

    out = args.data_root / "drugbank_open.csv"
    if out.exists() and not args.refresh:
        log.info("Using cached %s", out)
        return True
    df = fetch_drugbank_open(out_path=out, cache_dir=args.data_root / "drugbank_cache")
    return not df.empty


@step("PDB structures for AMR targets")
def fetch_pdb(args: argparse.Namespace) -> bool:
    from src.data.pdb import fetch_pdb_targets

    out = args.data_root / "pdb_amr_targets.csv"
    if out.exists() and not args.refresh:
        log.info("Using cached %s", out)
        return True
    df = fetch_pdb_targets(out_path=out, max_per_pathogen=args.max_per_pathogen)
    return not df.empty


@step("Build Stage 1 TDC corpus")
def build_tdc(args: argparse.Namespace) -> bool:
    cmd = [
        sys.executable, "scripts/prepare_tdc_data.py",
        "--output-dir", str(args.processed_root / "tdc-stage1"),
    ]
    if args.max_per_pathogen:
        cmd.extend(["--max-rows-per-task", str(args.max_per_pathogen * 5)])
    if args.push_to_hub:
        cmd.extend(["--push-to-hub", "rahul24raj/lysos-tdc-stage1"])
    return _run(cmd)


@step("Build Stage 2 AMR corpus")
def build_amr(args: argparse.Namespace) -> bool:
    cmd = [
        sys.executable, "scripts/prepare_amr_data.py",
        "--data-root", str(args.data_root),
        "--output-dir", str(args.processed_root / "amr-stage2"),
    ]
    if args.max_per_pathogen:
        cmd.extend(["--max-rows-per-task", str(args.max_per_pathogen * 5)])
    if args.push_to_hub:
        cmd.extend(["--push-to-hub", "rahul24raj/lysos-amr-stage2"])
    return _run(cmd)


@step("Build Stage 3 RL prompts")
def build_stage3(args: argparse.Namespace) -> bool:
    cmd = [
        sys.executable, "scripts/prepare_stage3_prompts.py",
        "--output-dir", str(args.processed_root / "amr-rl-prompts"),
    ]
    if args.push_to_hub:
        cmd.extend(["--push-to-hub", "rahul24raj/lysos-rl-prompts"])
    return _run(cmd)


def _run(cmd: list[str]) -> bool:
    log.info("$ %s", " ".join(cmd))
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        log.error("Command failed with code %d", r.returncode)
        return False
    return True


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch all real data + build processed datasets")
    p.add_argument("--data-root", type=Path, default=Path("data/raw"))
    p.add_argument("--processed-root", type=Path, default=Path("data/processed"))
    p.add_argument("--max-per-pathogen", type=int, default=2000,
                   help="Cap per pathogen across loaders (default 2000)")
    p.add_argument("--refresh", action="store_true",
                   help="Force re-fetch even if cached files exist")
    p.add_argument("--no-process", action="store_true",
                   help="Skip processing steps (just download raw)")
    p.add_argument("--push-to-hub", action="store_true",
                   help="Push processed datasets to HF Hub (private)")
    p.add_argument("--skip", type=str, default="",
                   help="Comma-separated steps to skip: chembl,dbaasp,dramp,card,tdc,amr,stage3")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    args.data_root.mkdir(parents=True, exist_ok=True)
    args.processed_root.mkdir(parents=True, exist_ok=True)

    skipped = set(s.strip() for s in args.skip.split(",") if s.strip())

    overall_t0 = time.perf_counter()
    successes = []
    failures = []

    # Raw data fetches — order matters: cheap/fast ones first so a failure
    # late in the chain doesn't waste 30 min on the expensive sources.
    fetches = [
        ("zinc", fetch_zinc),                # ~5 MB, fast (uses ZINC subsets)
        ("apd3", fetch_apd3),                # ~1 MB, fast
        ("card", fetch_card),                # ~10 MB, single bulk download
        ("dramp", fetch_dramp),              # ~10 MB, bulk download
        ("drugbank", fetch_drugbank),        # ~5 MB, free-tier
        ("chembl", fetch_chembl),            # ~30 MB, REST API + pagination
        ("dbaasp", fetch_dbaasp),            # ~5 MB but SLOW (N+1 detail fetches)
        ("pubchem", fetch_pubchem),          # ~50-500 MB depending on assays
        ("bindingdb", fetch_bindingdb),      # ~200 MB, bulk download + filter
        ("pdb", fetch_pdb),                  # ~5 MB metadata
    ]
    for name, fn in fetches:
        if name in skipped:
            log.info("Skipping %s (--skip)", name)
            continue
        try:
            ok = fn(args)
            (successes if ok else failures).append(name)
        except Exception as exc:  # noqa: BLE001
            log.error("%s crashed: %s", name, exc)
            failures.append(name)

    if not args.no_process:
        # Build processed datasets
        builders = [
            ("tdc", build_tdc),
            ("amr", build_amr),
            ("stage3", build_stage3),
        ]
        for name, fn in builders:
            if name in skipped:
                log.info("Skipping %s (--skip)", name)
                continue
            try:
                ok = fn(args)
                (successes if ok else failures).append(name)
            except Exception as exc:  # noqa: BLE001
                log.error("%s crashed: %s", name, exc)
                failures.append(name)

    elapsed = time.perf_counter() - overall_t0
    log.info("=" * 60)
    log.info("DONE in %.1fs", elapsed)
    log.info("  ✓ succeeded: %s", successes)
    log.info("  ✗ failed:    %s", failures)

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
