"""Cluster training examples by EmbeddingGemma similarity, drop near-duplicates.

Many training corpora have rephrased duplicates that look like distinct
examples to a tokenizer but represent the same underlying task. RDKit
canonical SMILES helps with literal molecule duplicates, but doesn't catch:

  - Different prompt phrasings of the same task
  - Slightly different molecules (one carbon different) that aren't true negatives
  - Same instruction asked of two different molecules with the same answer

Embedding-based dedup catches all of these.

Algorithm:
  1. Embed every example's `messages` (or `prompt`) field with EmbeddingGemma
  2. For each pair (within a task slice) with cosine similarity > threshold:
       union them into one cluster
  3. Keep one representative per cluster (the longest text, by default)
  4. Stratify by task to preserve relative task balance

Usage:

    python scripts/dedup_with_embeddings.py \\
        --input  data/processed/amr-stage2 \\
        --output data/processed/amr-stage2-dedup \\
        --threshold 0.95
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] dedup | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dedup")

# Repo root for imports
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Embedding-based training dedup")
    p.add_argument("--input", type=Path, required=True,
                   help="HF Dataset directory (with train/valid splits)")
    p.add_argument("--output", type=Path, required=True,
                   help="Output directory for the dedup'd dataset")
    p.add_argument("--threshold", type=float, default=0.95,
                   help="Cosine similarity threshold for clustering (default 0.95)")
    p.add_argument("--field", type=str, default="messages",
                   help="Which dataset column to embed (default: messages)")
    p.add_argument("--batch-size", type=int, default=64,
                   help="Batch size for embedding")
    p.add_argument("--per-task", action="store_true", default=True,
                   help="Cluster within each task slice (preserves task balance)")
    p.add_argument("--push-to-hub", type=str, default=None)
    return p.parse_args()


def _load_model():
    from sentence_transformers import SentenceTransformer
    log.info("Loading google/embeddinggemma-300m ...")
    return SentenceTransformer("google/embeddinggemma-300m")


def _cluster_by_threshold(embeddings, threshold: float) -> list[int]:
    """Greedy clustering: assign each row to the first existing cluster it matches.

    Returns a list of cluster IDs (one per row).
    """
    import numpy as np

    n = len(embeddings)
    cluster_ids = [-1] * n
    centroids: list[tuple[int, "np.ndarray"]] = []  # (cluster_id, centroid_emb)

    for i, emb in enumerate(embeddings):
        if not centroids:
            cluster_ids[i] = 0
            centroids.append((0, emb))
            continue
        # Cosine similarity to all existing centroids
        cents = np.array([c[1] for c in centroids])
        sims = cents @ emb  # both unit-normed
        best = int(sims.argmax())
        if sims[best] >= threshold:
            cluster_ids[i] = centroids[best][0]
        else:
            new_id = len(centroids)
            cluster_ids[i] = new_id
            centroids.append((new_id, emb))
    return cluster_ids


def _pick_representative(rows: list[dict], field: str) -> dict:
    """Within a cluster, pick the row with the longest text — usually most informative."""
    return max(rows, key=lambda r: len(str(r.get(field, ""))))


def main() -> int:
    args = parse_args()

    try:
        from datasets import Dataset, DatasetDict, load_from_disk
        import numpy as np
    except ImportError as exc:
        log.error("Missing deps: %s. pip install datasets numpy", exc)
        return 2

    if not args.input.exists():
        log.error("Input dataset not found: %s", args.input)
        return 1

    log.info("Loading %s ...", args.input)
    ds = load_from_disk(str(args.input))
    if not hasattr(ds, "keys"):
        ds = DatasetDict({"train": ds})

    model = _load_model()

    out_splits: dict[str, Dataset] = {}
    for split_name in ds:
        split = ds[split_name]
        log.info("Split %s: %d rows", split_name, len(split))

        # Embed
        texts = [str(r) for r in split[args.field]]
        log.info("  embedding %d rows...", len(texts))
        embs = model.encode(
            texts, normalize_embeddings=True,
            batch_size=args.batch_size, show_progress_bar=True,
        )
        embs = np.asarray(embs)

        # Cluster — per-task slicing if requested
        keep_idx: list[int] = []
        if args.per_task and "task" in split.column_names:
            tasks = split["task"]
            unique_tasks = list(dict.fromkeys(tasks))
            for task in unique_tasks:
                idx = [i for i, t in enumerate(tasks) if t == task]
                sub_embs = embs[idx]
                cluster_ids = _cluster_by_threshold(sub_embs, args.threshold)
                # Keep one per cluster — pick longest text
                clusters: dict[int, list[int]] = {}
                for k, ci in enumerate(cluster_ids):
                    clusters.setdefault(ci, []).append(idx[k])
                for ci, members in clusters.items():
                    if len(members) == 1:
                        keep_idx.append(members[0])
                    else:
                        rows = [split[m] for m in members]
                        winner_local = max(range(len(members)),
                                           key=lambda j: len(str(rows[j].get(args.field, ""))))
                        keep_idx.append(members[winner_local])
                log.info("    task=%s: %d rows → %d clusters",
                         task, len(idx), len(clusters))
        else:
            cluster_ids = _cluster_by_threshold(embs, args.threshold)
            clusters: dict[int, list[int]] = {}
            for i, ci in enumerate(cluster_ids):
                clusters.setdefault(ci, []).append(i)
            for ci, members in clusters.items():
                if len(members) == 1:
                    keep_idx.append(members[0])
                else:
                    rows = [split[m] for m in members]
                    winner = max(range(len(members)),
                                 key=lambda j: len(str(rows[j].get(args.field, ""))))
                    keep_idx.append(members[winner])

        keep_idx = sorted(set(keep_idx))
        deduped = split.select(keep_idx)
        log.info("  → %d rows kept (dropped %d, %.1f%%)",
                 len(deduped), len(split) - len(deduped),
                 100 * (len(split) - len(deduped)) / max(1, len(split)))
        out_splits[split_name] = deduped

    out_ds = DatasetDict(out_splits)
    args.output.mkdir(parents=True, exist_ok=True)
    out_ds.save_to_disk(str(args.output))
    log.info("Wrote %s", args.output)

    if args.push_to_hub:
        import os
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        if not token:
            log.error("--push-to-hub requires HF_TOKEN env var")
            return 3
        out_ds.push_to_hub(args.push_to_hub, private=True, token=token)
        log.info("✓ pushed to %s", args.push_to_hub)

    return 0


if __name__ == "__main__":
    sys.exit(main())
