"""Fetch curated subsets of HuggingScience datasets for the Lysos workbench.

Run with:
    python scripts/fetch_huggingscience.py --dataset openadmet
    python scripts/fetch_huggingscience.py --dataset b3db
    python scripts/fetch_huggingscience.py --dataset all       # bulk

Each dataset ID maps to a `download_<name>` function that:
  1. Pulls a bounded sample from HuggingFace Hub
  2. Persists to data/external/<name>.parquet
  3. Optionally derives a Lysos-grounding-shaped extract under
     data/synthetic/external_<name>_qa.jsonl so it can plug into the
     pharma_qa pipeline without changing its consumers.

Per the user's hackathon-first directive: take SUBSETS, not the full
datasets. Tier-2 (SAIR's 1M+ rows) is deferred — too heavy for a demo
laptop. We register the IDs in REGISTRY so the frontend's /datasets
slash can show what's available even before a fetch runs.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = REPO_ROOT / "data" / "external"
SYN_DIR = REPO_ROOT / "data" / "synthetic"


@dataclass
class DatasetSpec:
    name: str               # short ID used by the registry / slash
    hf_id: str              # HuggingFace dataset id
    description: str
    rows: str               # rough size description
    tier: int               # 1 = hackathon-priority, 2 = future-scale
    sample_n: int           # how many rows we actually pull (subset)
    columns_hint: tuple[str, ...] = ()


REGISTRY: list[DatasetSpec] = [
    DatasetSpec(
        name="openadmet_expansionrx",
        hf_id="openadmet/openadmet-expansionrx-challenge-train-data",
        description="RNA-targeted small-molecule ADMET assays (training split).",
        rows="11K+",
        tier=1,
        sample_n=2000,
    ),
    DatasetSpec(
        name="openadmet_cyp",
        hf_id="openadmet/Octant_CYP_inhibition_reactivity_blog_release",
        description="Cytochrome P450 inhibition + reactivity (Octant assays).",
        rows="thousands",
        tier=1,
        sample_n=1500,
    ),
    DatasetSpec(
        name="b3db",
        hf_id="maomlab/B3DB",
        description="Blood-brain barrier permeability (curated, ML-ready).",
        rows="~7K",
        tier=1,
        sample_n=2000,
    ),
    DatasetSpec(
        name="tdc",
        hf_id="maomlab/TDC",
        description="Therapeutics Data Commons multi-task subset.",
        rows="varies",
        tier=1,
        sample_n=1000,
    ),
    DatasetSpec(
        name="eve_bio_dta",
        hf_id="eve-bio/drug-target-activity",
        description="1,397 FDA-approved drugs × target binding measurements.",
        rows="1.4K",
        tier=1,
        sample_n=1397,
    ),
    DatasetSpec(
        name="sair",
        hf_id="SandboxAQ/SAIR",
        description="Public protein-ligand 3D structures + binding affinity (SandboxAQ).",
        rows="1M+",
        tier=2,
        sample_n=10000,
    ),
]


def _spec(name: str) -> Optional[DatasetSpec]:
    for s in REGISTRY:
        if s.name == name:
            return s
    return None


def _ensure_dirs() -> None:
    EXT_DIR.mkdir(parents=True, exist_ok=True)
    SYN_DIR.mkdir(parents=True, exist_ok=True)


def fetch(spec: DatasetSpec) -> Path:
    """Download a bounded sample from HF Hub. Returns the parquet path."""
    _ensure_dirs()
    out = EXT_DIR / f"{spec.name}.parquet"
    if out.exists():
        print(f"[skip] {spec.name}: {out} already exists ({out.stat().st_size // 1024} KB)")
        return out

    try:
        from datasets import load_dataset  # type: ignore[import]
    except ImportError:
        print("[error] `datasets` not installed. Run: pip install datasets pandas pyarrow")
        sys.exit(1)

    print(f"[fetch] {spec.name} ← {spec.hf_id}  (sampling {spec.sample_n} rows)")
    ds = load_dataset(spec.hf_id, split="train", streaming=False)
    sample = ds.select(range(min(spec.sample_n, len(ds))))
    sample.to_parquet(out)
    print(f"[ok] wrote {out} ({len(sample)} rows, {out.stat().st_size // 1024} KB)")
    return out


def write_registry_json() -> None:
    """Persist the registry to disk so the FastAPI server can read it."""
    out = EXT_DIR / "registry.json"
    _ensure_dirs()
    out.write_text(json.dumps([asdict(s) for s in REGISTRY], indent=2))
    print(f"[registry] {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="all",
                    help="One of: " + ", ".join(s.name for s in REGISTRY) + ", all, tier1")
    args = ap.parse_args()

    write_registry_json()

    if args.dataset == "all":
        for s in REGISTRY:
            try:
                fetch(s)
            except Exception as exc:  # noqa: BLE001
                print(f"[fail] {s.name}: {exc}")
        return 0
    if args.dataset == "tier1":
        for s in [s for s in REGISTRY if s.tier == 1]:
            try:
                fetch(s)
            except Exception as exc:
                print(f"[fail] {s.name}: {exc}")
        return 0

    s = _spec(args.dataset)
    if s is None:
        print(f"[error] unknown dataset '{args.dataset}'.\nAvailable: "
              + ", ".join(x.name for x in REGISTRY))
        return 2
    fetch(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
