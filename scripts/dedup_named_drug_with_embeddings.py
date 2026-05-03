"""Find near-duplicates within the named-drug elite CoT slice using embeddings.

Pure-Python, no GPU, runs in seconds on the 388-entry corpus. Catches:
  - Same drug profiled twice with different framings (e.g. vancomycin discussed
    in both drug_mechanism_deep_dive AND reward_profile_analysis).
  - Same pathogen analyzed in different reasoning task types.
  - Paraphrased prompts that bypass the prompt-hash dedup we already did.

Embedding backend (in priority order):
  1. sentence-transformers all-MiniLM-L6-v2 (small, fast, 384d)
  2. EmbeddingGemma 300m if HF_TOKEN set
  3. TF-IDF + cosine fallback (always works, no model dependency)

Output:
  - data/synthetic/named_drug_dedup_report.json — clusters above threshold
  - prints top-K clusters with cosine + token overlap

Usage:
  python scripts/dedup_named_drug_with_embeddings.py
  python scripts/dedup_named_drug_with_embeddings.py --threshold 0.90 --top 30
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SOURCE_JSONL = Path("data/synthetic/named_drug_examples.jsonl")
REPORT = Path("data/synthetic/named_drug_dedup_report.json")


def load_corpus():
    rows = []
    with SOURCE_JSONL.open() as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def embed_with_sentence_transformers(texts):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    print("  using sentence-transformers/all-MiniLM-L6-v2 (384d)")
    m = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return m.encode(texts, show_progress_bar=True, normalize_embeddings=True)


def embed_with_tfidf(texts):
    print("  fallback: TF-IDF cosine")
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize
    v = TfidfVectorizer(ngram_range=(1, 2), max_features=50000, lowercase=True)
    X = v.fit_transform(texts)
    return normalize(X, axis=1, norm="l2")


def cosine_pairwise(embs):
    """Returns dense N×N cosine matrix. Fine for N=388."""
    import numpy as np
    if hasattr(embs, "toarray"):  # sparse from TF-IDF
        return (embs @ embs.T).toarray()
    return embs @ embs.T


def build_clusters(sim_matrix, threshold):
    """Greedy clustering: each row finds its highest-similarity neighbor above threshold."""
    n = sim_matrix.shape[0]
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            s = float(sim_matrix[i, j])
            if s >= threshold:
                pairs.append((s, i, j))
    pairs.sort(reverse=True)
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.85,
                    help="Cosine threshold for near-duplicate (default 0.85)")
    ap.add_argument("--top", type=int, default=20,
                    help="Print top-K cluster pairs (default 20)")
    ap.add_argument("--field", choices=["response", "prompt+response"],
                    default="response",
                    help="Which field(s) to embed for similarity")
    args = ap.parse_args()

    print(f"Loading corpus from {SOURCE_JSONL}...")
    rows = load_corpus()
    print(f"  {len(rows)} entries")

    if args.field == "response":
        texts = [r["response"] for r in rows]
    else:
        texts = [f"{r['prompt']}\n\n{r['response']}" for r in rows]

    print(f"\nEmbedding {len(texts)} texts...")
    embs = embed_with_sentence_transformers(texts)
    if embs is None:
        embs = embed_with_tfidf(texts)

    print(f"\nComputing pairwise cosine (N×N where N={len(texts)})...")
    sim = cosine_pairwise(embs)

    print(f"\nClustering at threshold={args.threshold}...")
    pairs = build_clusters(sim, args.threshold)
    print(f"  {len(pairs)} pair(s) above threshold")

    # Group by task-type co-occurrence
    task_pair_counts = defaultdict(int)
    for s, i, j in pairs:
        ti = rows[i]["task"]
        tj = rows[j]["task"]
        key = tuple(sorted([ti, tj]))
        task_pair_counts[key] += 1

    print(f"\nTop-{args.top} most-similar pairs (cosine ≥ {args.threshold}):")
    for s, i, j in pairs[:args.top]:
        ti = rows[i]["task"]
        tj = rows[j]["task"]
        ni = rows[i]["prompt"].split(":")[-1].strip()[:60]
        nj = rows[j]["prompt"].split(":")[-1].strip()[:60]
        print(f"  cos={s:.3f}  [{ti} ↔ {tj}]")
        print(f"    A: {ni}")
        print(f"    B: {nj}")

    print(f"\nTask-type pairs with most cross-similarity:")
    for (a, b), n in sorted(task_pair_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {n:3d}  {a}  ↔  {b}")

    report = {
        "threshold": args.threshold,
        "n_rows": len(rows),
        "n_pairs_above_threshold": len(pairs),
        "top_pairs": [
            {
                "cosine": float(s),
                "i": i,
                "j": j,
                "task_i": rows[i]["task"],
                "task_j": rows[j]["task"],
                "title_i": rows[i]["prompt"].split(":")[-1].strip()[:120],
                "title_j": rows[j]["prompt"].split(":")[-1].strip()[:120],
            }
            for s, i, j in pairs[:50]
        ],
        "task_pair_counts": {
            f"{a} ↔ {b}": n
            for (a, b), n in sorted(task_pair_counts.items(), key=lambda x: -x[1])
        },
    }
    REPORT.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {REPORT}")
    print(f"\nNote: high cross-task similarity is EXPECTED — same drug discussed")
    print(f"in different reasoning frames. This report is for HUMAN REVIEW;")
    print(f"only delete if the content is actually redundant, not just topical overlap.")


if __name__ == "__main__":
    sys.exit(main() or 0)
