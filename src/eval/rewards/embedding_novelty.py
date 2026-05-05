"""Reward: semantic novelty via Gemini Embedding 2 (gemini-embedding-2).

Complements Tanimoto-on-ECFP4 (`novelty.py`) — Tanimoto catches direct
fingerprint overlap; embedding distance catches paraphrase-level similarity
(same pharmacophore in a different scaffold).

Uses Google's Gemini Embedding 2 — 3072-d Matryoshka, multimodal-ready,
$0.025 per 1M tokens. For training-time RL the embedder is reused across
rollouts via module-level cache. Reference antibiotics are embedded ONCE
at startup, queries are batched per RL step.

Penalty curve identical to `novelty.py`:
  distance >= threshold → reward = distance
  distance <  threshold → reward = distance * (distance / threshold)^2

Required env: GEMINI_API_KEY (or GOOGLE_API_KEY).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

from . import extract_smiles

log = logging.getLogger(__name__)

_EMBEDDER = None
_REF_EMBS = None
_REF_PATH: str | None = None


def _ensure_loaded(reference_set: str) -> bool:
    """Load embedder + cache reference embeddings if not already loaded."""
    global _EMBEDDER, _REF_EMBS, _REF_PATH

    if _EMBEDDER is None:
        if not (os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")):
            log.warning(
                "GEMINI_API_KEY not set — embedding_novelty returns max-novelty "
                "(fail-open). Get a key at https://aistudio.google.com/apikey"
            )
            return False
        try:
            from src.embeddings import GeminiEmbedder
            _EMBEDDER = GeminiEmbedder(qps=15.0)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not init Gemini Embedder: %s", exc)
            return False

    if _REF_EMBS is None or _REF_PATH != reference_set:
        # PRIMARY PATH: load pre-computed Gemini Embedding 2 vectors from the
        # parquet file produced by scripts/precompute_embeddings.py. This
        # avoids re-embedding 30K reference antibiotics on every training
        # start — Gemini API budget is reserved for query-side embeddings.
        precomputed = Path("artifacts/embeddings/known-antibiotics-gemini-2.parquet")
        if precomputed.exists():
            try:
                import pandas as pd
                df = pd.read_parquet(precomputed)
                _REF_EMBS = np.asarray(df["embedding"].tolist(), dtype=np.float32)
                _REF_PATH = reference_set
                log.info("  loaded %d pre-computed reference embeddings (dim=%d) from %s",
                         len(_REF_EMBS), _REF_EMBS.shape[-1], precomputed)
                return True
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to load pre-computed embeddings: %s. "
                            "Falling back to live embedding.", exc)

        # FALLBACK: live-embed if no precomputed parquet exists.
        ref_path = Path(reference_set)
        if not ref_path.exists():
            log.warning(
                "Reference set %s not found — embedding_novelty returns 1.0",
                ref_path,
            )
            return False
        with open(ref_path, encoding="utf-8", errors="replace") as f:
            ref_smiles = [
                line.strip() for line in f
                if line.strip() and not line.startswith("#")
            ]
        ref_smiles = [s.split()[0] for s in ref_smiles]
        # Use the same enrichment template the precompute uses so query
        # and document embeddings share semantic feature space.
        from src.embeddings.enrichment import build_query_text
        ref_texts = [build_query_text(s, name="reference", source="reference")
                     for s in ref_smiles]
        log.info(
            "Embedding %d reference antibiotics with gemini-embedding-2 "
            "(NO precomputed cache — running live, ~$0.10 call)...",
            len(ref_texts),
        )
        _REF_EMBS = _EMBEDDER.embed_batch(
            ref_texts, task_type="RETRIEVAL_DOCUMENT", normalize=True,
        )
        _REF_PATH = reference_set
        log.info(
            "  cached %d reference embeddings (dim=%d)",
            len(_REF_EMBS), _REF_EMBS.shape[-1],
        )
    return True


def embedding_novelty(
    samples: list[str],
    *,
    reference_set: str = "data/processed/known-antibiotics.smiles",
    threshold: float = 0.6,
    **_,
) -> list[float]:
    """Reward in [0, 1]. Higher = more semantically novel vs known antibiotics.

    Returns list aligned with `samples`. Invalid samples → 0.0.
    """
    if not _ensure_loaded(reference_set):
        # NO FALLBACK. The user's policy is "no useless fallback that degrades
        # quality". If the embedder + reference set aren't loaded, the
        # component is unable to produce a real signal. Raise loudly so the
        # training run is killed and the operator either:
        #   (a) sets GEMINI_API_KEY + verifies reference set, OR
        #   (b) sets weight=0 in configs/stage3_rl_grpo.yaml to disable
        # Either way, NO silent contamination of the composite reward.
        raise RuntimeError(
            "embedding_novelty cannot produce real signal. Set GEMINI_API_KEY + "
            "ensure reference_set exists, OR set weight=0 in stage3_rl_grpo.yaml "
            "to disable this component. NO fallbacks per project policy."
        )

    # Build matching enriched query text per candidate so the asymmetric
    # retrieval (RETRIEVAL_DOCUMENT vs RETRIEVAL_QUERY) operates over the
    # same feature space as the precomputed reference embeddings.
    from src.embeddings.enrichment import build_query_text

    queries: list[str] = []
    valid_idx: list[int] = []
    for i, sample in enumerate(samples):
        smi = extract_smiles(sample)
        if smi:
            queries.append(build_query_text(smi, name="candidate", source="generated"))
            valid_idx.append(i)
    if not valid_idx:
        return [0.0] * len(samples)

    q_embs = _EMBEDDER.embed_batch(
        queries, task_type="RETRIEVAL_QUERY", normalize=True,
    )
    sims = q_embs @ _REF_EMBS.T  # cosine — both unit-normed
    max_sims = sims.max(axis=1)

    out = [0.0] * len(samples)
    for k, i in enumerate(valid_idx):
        distance = float(1.0 - max_sims[k])
        if distance >= threshold:
            out[i] = distance
        else:
            out[i] = distance * (distance / threshold) ** 2
    return out
