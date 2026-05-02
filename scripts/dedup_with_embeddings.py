"""Cluster training examples + drop near-duplicates.

Two-pass dedup:
  Pass 1 — content-hash. Drop literal duplicates (same prompt+response).
           Cheap, catches a lot of noise.
  Pass 2 — embedding similarity. Embed remaining rows with EmbeddingGemma,
           cluster greedily by cosine threshold, keep one representative
           per cluster (longest text by default).

Stratifies by task so per-task balance is preserved.

Scale notes:
  - Pass 1 is O(n).
  - Pass 2 is O(n²) within each task slice (greedy centroid match).
    For tasks larger than `--embed-cap` rows we sample down before embedding.
    Default cap = 20,000 — keeps wall-clock under ~10 min on M-series Mac.

Usage:

    python scripts/dedup_with_embeddings.py \\
        --input  data/processed/amr-stage2 \\
        --output data/processed/amr-stage2-dedup \\
        --threshold 0.97

Push directly:

    HF_TOKEN=... python scripts/dedup_with_embeddings.py \\
        --input data/processed/amr-stage2 \\
        --output data/processed/amr-stage2-dedup \\
        --push-to-hub rahul24raj/lysos-amr-stage2-dedup
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] dedup | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dedup")

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Two-pass training data dedup")
    p.add_argument("--input", type=Path, required=True,
                   help="HF Dataset directory (with train/valid splits)")
    p.add_argument("--output", type=Path, required=True,
                   help="Output directory for the dedup'd dataset")
    p.add_argument("--threshold", type=float, default=0.97,
                   help="Embedding cosine threshold for clustering (default 0.97)")
    p.add_argument("--field", type=str, default="prompt",
                   help="Which field to compare for dedup (default: prompt)")
    p.add_argument("--batch-size", type=int, default=64,
                   help="Embedding batch size")
    p.add_argument("--embed-cap", type=int, default=20000,
                   help="Per-task: if a task has more rows than this, sample down "
                        "before embedding (default 20000)")
    p.add_argument("--mode", choices=["hash", "embed", "both"], default="both",
                   help="hash = content-hash only (fast). "
                        "embed = embedding only. "
                        "both = hash first, then embed survivors.")
    p.add_argument("--skip-tasks", type=str,
                   default="drug_id_lookup,drug_inchi_key,drug_synonyms,"
                           "drug_cas_lookup,drug_reverse_cas,drug_smiles,"
                           "drug_from_smiles,drug_structure,"
                           "natural_product_origin,natural_product_origin_smiles",
                   help="Comma-separated task names to skip embedding pass on. "
                        "Templated-prompt tasks (where the prompt is identical "
                        "modulo a single variable) collapse to ~100 clusters "
                        "under embedding similarity, which destroys data. "
                        "These tasks rely on hash dedup (pass 1) only.")
    p.add_argument("--push-to-hub", type=str, default=None)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--model", type=str, default="google/embeddinggemma-300m",
                   help="Embedding model. EmbeddingGemma is gated; falls back to "
                        "all-MiniLM-L6-v2 (open) if access is denied.")
    return p.parse_args()


def _content_hash(prompt: str, response: str) -> str:
    """Stable content hash for literal-duplicate detection."""
    h = hashlib.sha256()
    h.update(str(prompt).strip().lower().encode("utf-8", errors="ignore"))
    h.update(b"\x00")
    h.update(str(response).strip().lower().encode("utf-8", errors="ignore"))
    return h.hexdigest()[:16]


def hash_dedup_per_task(split, log_prefix: str = "") -> tuple[list[int], dict]:
    """Pass 1 — drop literal duplicates by (prompt, response) hash.

    Returns (kept_indices, stats).
    """
    seen: dict[str, int] = {}  # hash -> first idx
    kept: list[int] = []
    n = len(split)
    has_resp = "response" in split.column_names
    by_task_kept: dict[str, int] = {}
    by_task_drop: dict[str, int] = {}
    for i, row in enumerate(split):
        prompt = row.get("prompt", "") or ""
        response = row.get("response", "") if has_resp else ""
        h = _content_hash(prompt, response)
        task = row.get("task", "_")
        if h in seen:
            by_task_drop[task] = by_task_drop.get(task, 0) + 1
            continue
        seen[h] = i
        kept.append(i)
        by_task_kept[task] = by_task_kept.get(task, 0) + 1
    log.info("%shash pass: %d → %d (-%d, %.1f%%)",
             log_prefix, n, len(kept), n - len(kept),
             100 * (n - len(kept)) / max(1, n))
    return kept, {"kept_per_task": by_task_kept, "dropped_per_task": by_task_drop}


def _greedy_cluster(embeddings, threshold: float) -> list[int]:
    """Greedy centroid-match clustering. Returns cluster_id per row."""
    import numpy as np
    n = len(embeddings)
    cluster_ids = [-1] * n
    centroids: list[tuple[int, "np.ndarray"]] = []
    for i, emb in enumerate(embeddings):
        if not centroids:
            cluster_ids[i] = 0
            centroids.append((0, emb))
            continue
        cents = np.asarray([c[1] for c in centroids])
        sims = cents @ emb
        best = int(sims.argmax())
        if sims[best] >= threshold:
            cluster_ids[i] = centroids[best][0]
        else:
            new_id = len(centroids)
            cluster_ids[i] = new_id
            centroids.append((new_id, emb))
    return cluster_ids


def embed_dedup(split, model, *, threshold: float, field: str,
                batch_size: int, embed_cap: int, skip_tasks: set[str],
                seed: int) -> list[int]:
    """Pass 2 — embedding-based per-task clustering.

    Returns kept indices in the original split.
    """
    import numpy as np
    rng = np.random.default_rng(seed)

    has_task = "task" in split.column_names
    keep: list[int] = []
    if has_task:
        unique_tasks = list(dict.fromkeys(split["task"]))
    else:
        unique_tasks = ["_"]

    for task in unique_tasks:
        if has_task:
            idx = [i for i, t in enumerate(split["task"]) if t == task]
        else:
            idx = list(range(len(split)))
        n = len(idx)

        if task in skip_tasks:
            log.info("  task=%s: %d rows (skipped embedding pass)", task, n)
            keep.extend(idx)
            continue

        # Sample down if huge
        sampled = idx
        sampled_size = n
        if n > embed_cap:
            sampled = [int(x) for x in rng.choice(idx, size=embed_cap, replace=False)]
            sampled_size = embed_cap
            log.info("  task=%s: %d rows → sampling %d for embedding pass",
                     task, n, embed_cap)
            # Keep the un-sampled tail outright (random, no dup detection)
            unsampled = sorted(set(idx) - set(sampled))
            keep.extend(int(x) for x in unsampled)

        # Embed
        texts = [str(split[i].get(field, "")) for i in sampled]
        log.info("  task=%s: embedding %d rows...", task, len(texts))
        embs = model.encode(
            texts, normalize_embeddings=True,
            batch_size=batch_size, show_progress_bar=False,
        )
        embs = np.asarray(embs, dtype=np.float32)

        cluster_ids = _greedy_cluster(embs, threshold)
        clusters: dict[int, list[int]] = {}
        for k, ci in enumerate(cluster_ids):
            clusters.setdefault(int(ci), []).append(int(sampled[k]))
        before = len(sampled)
        for ci, members in clusters.items():
            if len(members) == 1:
                keep.append(int(members[0]))
            else:
                # Keep longest text in cluster — usually the most informative
                rows = [split[int(m)] for m in members]
                winner = max(range(len(members)),
                             key=lambda j: len(str(rows[j].get(field, ""))))
                keep.append(int(members[winner]))
        after = len(clusters)
        log.info("  task=%s: %d → %d clusters (-%d, %.1f%% in sampled set)",
                 task, before, after, before - after,
                 100 * (before - after) / max(1, before))

    return sorted(set(keep))


def main() -> int:
    args = parse_args()

    try:
        from datasets import Dataset, DatasetDict, load_from_disk
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

    skip_tasks = {t.strip() for t in args.skip_tasks.split(",") if t.strip()}
    if skip_tasks:
        log.info("Skipping embedding pass for tasks: %s", sorted(skip_tasks))

    model = None
    if args.mode in ("embed", "both"):
        from sentence_transformers import SentenceTransformer
        log.info("Loading %s ...", args.model)
        try:
            model = SentenceTransformer(args.model)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load %s: %s", args.model, exc)
            fallback = "sentence-transformers/all-MiniLM-L6-v2"
            log.warning("Falling back to %s (open, 384d, smaller).", fallback)
            model = SentenceTransformer(fallback)

    out_splits: dict[str, "Dataset"] = {}
    for split_name in ds:
        split = ds[split_name]
        log.info("=" * 60)
        log.info("Split: %s — %d rows", split_name, len(split))

        # Pass 1: content hash
        if args.mode in ("hash", "both"):
            kept_idx, _ = hash_dedup_per_task(split, log_prefix="  ")
            split = split.select(kept_idx)
            log.info("  after hash pass: %d rows", len(split))

        # Pass 2: embedding
        if args.mode in ("embed", "both"):
            kept_idx = embed_dedup(
                split, model,
                threshold=args.threshold,
                field=args.field,
                batch_size=args.batch_size,
                embed_cap=args.embed_cap,
                skip_tasks=skip_tasks,
                seed=args.seed,
            )
            split = split.select(kept_idx)
            log.info("  after embed pass: %d rows", len(split))

        out_splits[split_name] = split

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
        log.info("Pushing to %s ...", args.push_to_hub)
        out_ds.push_to_hub(args.push_to_hub, token=token, private=False)
        log.info("✓ pushed")

    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
