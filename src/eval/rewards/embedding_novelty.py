"""Reward: semantic novelty via Gemini Embedding 2 (gemini-embedding-001).

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
        ref_path = Path(reference_set)
        if not ref_path.exists():
            log.warning(
                "Reference set %s not found — embedding_novelty returns 1.0",
                ref_path,
            )
            return False
        with open(ref_path) as f:
            ref_smiles = [
                line.strip() for line in f
                if line.strip() and not line.startswith("#")
            ]
        ref_smiles = [s.split()[0] for s in ref_smiles]  # support "SMILES name"
        log.info(
            "Embedding %d reference antibiotics with gemini-embedding-001 "
            "(this is a one-time ~$0.05 call)...", len(ref_smiles),
        )
        _REF_EMBS = _EMBEDDER.embed_batch(
            ref_smiles, task_type="RETRIEVAL_DOCUMENT", normalize=True,
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
        # Fail CLOSED: return neutral 0.5 instead of fail-open 1.0
        # Fail-open would flood the policy with max novelty reward and the
        # model would learn to ignore the (unrelated) Tanimoto novelty signal.
        return [0.5] * len(samples)

    queries: list[str] = []
    valid_idx: list[int] = []
    for i, sample in enumerate(samples):
        smi = extract_smiles(sample)
        if smi:
            queries.append(smi)
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
