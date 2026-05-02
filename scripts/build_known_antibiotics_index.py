"""Build the known-antibiotics index for novelty reward + RAG retrieval.

Sources (all canonicalized via scripts/audit_and_canonicalize.py):
  - ChEMBL bacterial-active subset      (potency-filtered)
  - DBAASP unique AMP sequences          (deduped per-sequence)
  - DRAMP unique AMP sequences
  - DrugBank approved drugs              (with SMILES from resolver)
  - DrugCentral approved drugs           (SMILES inline)
  - NPAtlas antibiotic-producing genera  (Streptomyces, Bacillus, Penicillium, …)

Outputs (both at `data/processed/`):
  - known-antibiotics.smiles  (text format: <smiles>\\t<name>\\t<source>)
  - known-antibiotics.parquet (with optional pre-computed Gemini-embedding-001
    vectors when GEMINI_API_KEY is set — saves $0.05 per consumer)

The novelty reward + RAG retriever load whichever is most efficient.

Usage:

    # Text-only index (fast, no embeddings)
    python scripts/build_known_antibiotics_index.py

    # Full index with Gemini-embedding-001 vectors pre-computed
    GEMINI_API_KEY=... python scripts/build_known_antibiotics_index.py --embed
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] index | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("index")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# Antibiotic-producing genera. NPAtlas hits in these are far more relevant
# than e.g. marine sponge metabolites for AMR-design novelty.
ANTIBIOTIC_GENERA = {
    "Streptomyces", "Bacillus", "Penicillium", "Aspergillus", "Acremonium",
    "Pseudomonas", "Actinomyces", "Micromonospora", "Saccharopolyspora",
    "Amycolatopsis", "Nocardia", "Cephalosporium", "Chromobacterium",
    "Lysobacter",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, default=Path("data/raw"))
    p.add_argument("--output-dir", type=Path,
                   default=Path("data/processed"))
    p.add_argument("--max-rows", type=int, default=None)
    p.add_argument("--pchembl-min", type=float, default=5.0,
                   help="ChEMBL pchembl threshold (5.0 = 10µM = potent)")
    p.add_argument("--embed", action="store_true",
                   help="Compute Gemini-embedding-001 vectors and save .parquet")
    p.add_argument("--output-dim", type=int, default=768,
                   help="Matryoshka dim (768/1536/3072) for embeddings")
    p.add_argument("--push-to-hub", type=str, default=None)
    return p.parse_args()


def _read_canonical(path: Path):
    """Prefer .canonical.csv if present; fallback to raw."""
    canonical = path.with_suffix(".canonical.csv")
    return canonical if canonical.exists() else path


def _load_chembl(root: Path, pchembl_min: float):
    import pandas as pd
    path = _read_canonical(root / "chembl_antibiotics.csv")
    if not path.exists():
        log.warning("ChEMBL missing: %s", path)
        return []
    df = pd.read_csv(path, low_memory=False).dropna(subset=["smiles"])
    if "pchembl_value" in df.columns:
        df["pchembl_value"] = pd.to_numeric(df["pchembl_value"], errors="coerce")
        before = len(df)
        df = df[df["pchembl_value"].fillna(pchembl_min) >= pchembl_min]
        log.info("  ChEMBL: pchembl≥%.1f filter %d → %d", pchembl_min, before, len(df))
    df = df.drop_duplicates(subset=["smiles"])
    log.info("ChEMBL: %d unique active antibacterials", len(df))
    return [
        (str(r["smiles"]), str(r.get("name", "") or "")[:60], "chembl")
        for _, r in df.iterrows()
    ]


def _load_dbaasp(root: Path):
    import pandas as pd
    path = _read_canonical(root / "dbaasp_amps.csv")
    if not path.exists():
        return []
    df = pd.read_csv(path, low_memory=False).dropna(subset=["sequence"])
    df = df.drop_duplicates(subset=["sequence"])
    log.info("DBAASP: %d unique AMP sequences", len(df))
    rows = []
    for _, r in df.iterrows():
        n = r.get("name", "")
        n = str(n) if n == n else ""
        rows.append((str(r["sequence"]), n[:60] or "AMP", "dbaasp"))
    return rows


def _load_dramp(root: Path):
    import pandas as pd
    path = _read_canonical(root / "dramp_amps.csv")
    if not path.exists():
        return []
    df = pd.read_csv(path, low_memory=False).dropna(subset=["sequence"])
    df = df.drop_duplicates(subset=["sequence"])
    log.info("DRAMP: %d unique sequences", len(df))
    rows = []
    for _, r in df.iterrows():
        n = r.get("name") or r.get("dbaasp_id") or ""
        n = str(n) if n == n else ""
        rows.append((str(r["sequence"]), n[:60] or "DRAMP", "dramp"))
    return rows


def _load_drugbank(root: Path):
    """Prefer the SMILES-resolved DrugBank file."""
    import pandas as pd
    enriched = root / "drugbank_with_smiles.csv"
    fallback = _read_canonical(root / "drugbank_open.csv")
    path = enriched if enriched.exists() else fallback
    if not path.exists():
        return []
    df = pd.read_csv(path, low_memory=False)
    if "smiles" not in df.columns:
        log.warning("DrugBank: no smiles column at %s", path)
        return []
    df = df.dropna(subset=["smiles"])
    df = df[df["smiles"].astype(str).str.len() > 5]
    df = df.drop_duplicates(subset=["smiles"])
    log.info("DrugBank: %d drugs with SMILES", len(df))
    return [
        (str(r["smiles"]), str(r.get("name", "") or "")[:60], "drugbank")
        for _, r in df.iterrows()
    ]


def _load_drugcentral(root: Path):
    import pandas as pd
    path = _read_canonical(root / "drugcentral.csv")
    if not path.exists():
        return []
    df = pd.read_csv(path, low_memory=False).dropna(subset=["smiles"])
    df = df.drop_duplicates(subset=["smiles"])
    log.info("DrugCentral: %d drugs", len(df))
    return [
        (str(r["smiles"]), str(r.get("name", "") or "")[:60], "drugcentral")
        for _, r in df.iterrows()
    ]


def _load_npatlas(root: Path):
    import pandas as pd
    path = _read_canonical(root / "npatlas.csv")
    if not path.exists():
        return []
    df = pd.read_csv(path, low_memory=False).dropna(subset=["smiles"])
    if "source_genus" in df.columns:
        before = len(df)
        df = df[df["source_genus"].isin(ANTIBIOTIC_GENERA)]
        log.info("  NPAtlas: filtered to antibiotic-producing genera %d → %d",
                 before, len(df))
    df = df.drop_duplicates(subset=["smiles"])
    log.info("NPAtlas: %d natural products from antibiotic producers", len(df))
    return [
        (str(r["smiles"]), str(r.get("name", "") or "")[:60], "npatlas")
        for _, r in df.iterrows()
    ]


def main() -> int:
    args = parse_args()

    rows: list[tuple[str, str, str]] = []
    rows += _load_chembl(args.data_root, args.pchembl_min)
    rows += _load_drugbank(args.data_root)
    rows += _load_drugcentral(args.data_root)
    rows += _load_npatlas(args.data_root)
    rows += _load_dbaasp(args.data_root)
    rows += _load_dramp(args.data_root)

    seen: set[str] = set()
    unique: list[tuple[str, str, str]] = []
    for s, n, src in rows:
        if s in seen:
            continue
        seen.add(s)
        unique.append((s, n, src))
    if args.max_rows:
        unique = unique[:args.max_rows]
    log.info("Total unique structures across sources: %d", len(unique))

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Plain text index
    out_smiles = args.output_dir / "known-antibiotics.smiles"
    with open(out_smiles, "w") as f:
        f.write("# known-antibiotics index\n")
        f.write("# format: <smiles_or_sequence>\\t<name>\\t<source>\n")
        for s, n, src in unique:
            f.write(f"{s}\t{n}\t{src}\n")
    log.info("Wrote %s (%d entries)", out_smiles, len(unique))

    # Parquet index (always — without vectors if --embed not set)
    import pandas as pd
    df = pd.DataFrame(unique, columns=["smiles", "name", "source"])

    if args.embed:
        if not (os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")):
            log.error("--embed needs GEMINI_API_KEY env var")
            return 2
        from src.embeddings import GeminiEmbedder
        log.info("Embedding %d entries via gemini-embedding-001 "
                 "(output_dim=%d) — est cost ~$%.2f ...",
                 len(df), args.output_dim, 0.025e-6 * len(df) * 80)
        emb = GeminiEmbedder(output_dim=args.output_dim, qps=15.0)
        # Compose document text: smiles + name → richer matching
        texts = [
            f"{r.smiles}" if not r.name else f"{r.smiles} | {r.name}"
            for _, r in df.iterrows()
        ]
        vectors = emb.embed_batch(
            texts, task_type="RETRIEVAL_DOCUMENT", normalize=True,
        )
        df["embedding"] = list(vectors.tolist())
        log.info("  vectors: %s, dim=%d", vectors.shape, vectors.shape[-1])

    out_parquet = args.output_dir / "known-antibiotics.parquet"
    df.to_parquet(out_parquet, index=False)
    log.info("Wrote %s", out_parquet)

    if args.push_to_hub:
        from datasets import Dataset
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        if not token:
            log.error("--push-to-hub needs HF_TOKEN")
            return 3
        ds = Dataset.from_pandas(df, preserve_index=False)
        ds.push_to_hub(args.push_to_hub, token=token, private=False)
        log.info("✓ pushed to %s", args.push_to_hub)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
