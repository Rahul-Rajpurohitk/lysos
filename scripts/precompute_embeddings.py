"""precompute_embeddings.py — compute + persist all reference embeddings.

Why this exists:
  Today the embedding_novelty reward re-embeds the known-antibiotics
  catalog every time a training run starts. That's:
    * wasted Gemini API budget — you pay each time
    * fragile — depends on Gemini API being live at training start
    * non-portable — embeddings live in process memory only
  Solution: embed once, save as parquet, load from disk forever after.
  You own the embeddings. Same Gemini Embedding 2 (3072-d Matryoshka).

What this writes:
  artifacts/embeddings/known-antibiotics-gemini.parquet
    columns: smiles, name, drug_class, embedding (list[float], 3072)

Cost:
  ~$0.025 per 1M tokens. At ~30K antibiotics × ~30 chars avg ≈ 900K chars
  ≈ ~225K tokens (Gemini char-to-token ratio ~4:1).
  Total cost: ~$0.006. Round up to $0.05 for safety.

Run:
  python3 scripts/precompute_embeddings.py
  python3 scripts/precompute_embeddings.py --limit 100   # sanity smoke
  python3 scripts/precompute_embeddings.py --dry-run     # check inputs only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "embeddings"
sys.path.insert(0, str(ROOT))


def _load_dotenv() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import verify_keys as vk
        vk._load_dotenv(ROOT / ".env")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path,
                    default=ROOT / "data/processed/known-antibiotics-canonical.parquet",
                    help="Parquet with `smiles` column (and optional `name`, `drug_class`)")
    ap.add_argument("--out", type=Path,
                    default=ARTIFACTS / "known-antibiotics-gemini-2.parquet")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only embed N rows (smoke test)")
    ap.add_argument("--batch_size", type=int, default=64,
                    help="Gemini batch size per API call")
    ap.add_argument("--qps", type=float, default=1.5,
                    help="API calls per second (free tier: keep <=1.5)")
    ap.add_argument("--threads", type=int, default=1,
                    help="Parallel embedder threads (free tier: keep at 1)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    _load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[X] GEMINI_API_KEY not set in .env or env. Cannot embed.")
        return 1

    if not args.source.exists():
        print(f"[X] Source not found: {args.source}")
        return 1

    import pandas as pd
    df = pd.read_parquet(args.source)
    if args.limit:
        df = df.head(args.limit)
    print(f"[INFO] Source: {args.source}  rows: {len(df)}")
    print(f"[INFO] Out:    {args.out}")

    if args.dry_run:
        print("[DRY] Would embed columns:", list(df.columns)[:8])
        print("[DRY] Sample row:", df.iloc[0].to_dict())
        return 0

    if "smiles" not in df.columns:
        print(f"[X] Source has no `smiles` column. Got: {list(df.columns)}")
        return 1

    # Use the existing GeminiEmbedder — same one the embedding_novelty reward uses
    try:
        from src.embeddings import GeminiEmbedder
        from src.embeddings.enrichment import build_document_text
    except ImportError as e:
        print(f"[X] Could not import GeminiEmbedder: {e}")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    embedder = GeminiEmbedder(qps=args.qps)

    # Build enriched text per row — uses name + source + stereo + RDKit
    # descriptors. ~150 tokens/row instead of bare ~7-token SMILES, which
    # gives the embedder real semantic context inside the 8192-token
    # window. SAME template used by embedding_novelty + retrieval +
    # dedup so the cosine space stays consistent.
    print(f"[INFO] Building enriched embedding text for {len(df)} rows...")
    enriched_texts = [build_document_text(row) for _, row in df.iterrows()]
    avg_tok = sum(len(t) for t in enriched_texts) / max(1, len(enriched_texts)) / 4
    print(f"[INFO]   avg ~{avg_tok:.0f} tokens/row  (cap: 8192)")
    print(f"[INFO]   sample text: {enriched_texts[0][:120]}...")

    n = len(enriched_texts)
    print(f"[INFO] Embedding {n} rows via Gemini Embedding 2 (gemini-embedding-2)")
    print(f"[INFO] Batch size: {args.batch_size}, dim: 3072 (Matryoshka)")
    print(f"[INFO] qps: {args.qps}  threads: {args.threads}")

    t0 = time.time()
    all_embs: list[list[float]] | None = None
    try:
        all_embs = embedder.embed_batch(
            enriched_texts,
            task_type="RETRIEVAL_DOCUMENT",
            normalize=True,
            threads=args.threads,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[X] Embedding failed: {exc}")
        print("    Free Gemini tier = 100 RPM / 1000 RPD; paid tier = 1500 RPM.")
        print("    The reference-side parquet at")
        print("    artifacts/embeddings/known-antibiotics-gemini-2.parquet")
        print("    already covers the 30,743-row catalog — re-running this script")
        print("    is only needed if you regenerate the canonical reference set.")
        return 1

    elapsed = time.time() - t0
    if all_embs is None or len(all_embs) != n:
        print(f"[X] Got {len(all_embs) if all_embs is not None else 0} embeddings; expected {n}")
        return 1

    print(f"[INFO] Embedded {n} SMILES in {elapsed:.1f}s "
          f"({n/elapsed:.1f} rows/s)")

    # Pack into parquet — stable schema for downstream reuse
    import numpy as np
    arr = np.asarray(all_embs, dtype="float32")
    out_df = df[[c for c in df.columns if c in ("smiles", "name", "drug_class", "inchi_key")]].copy()
    out_df["embedding"] = list(arr)  # row-wise list[float]
    # Provenance metadata
    src_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()[:16]
    out_df.attrs = {
        "source_path": str(args.source),
        "source_sha256_16": src_hash,
        "model": "gemini-embedding-2",
        "dim": 3072,
        "task_type": "RETRIEVAL_DOCUMENT",
        "normalized": True,
        "computed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_rows": n,
    }

    out_df.to_parquet(args.out, index=False)
    # Also write a sidecar JSON manifest with provenance (parquet attrs aren't reliably preserved)
    manifest = args.out.with_suffix(".meta.json")
    manifest.write_text(json.dumps(dict(out_df.attrs), indent=2))

    size_mb = args.out.stat().st_size / 1024 / 1024
    print(f"[OK] Wrote {n} embeddings to {args.out}  ({size_mb:.1f} MB)")
    print(f"[OK] Manifest: {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
