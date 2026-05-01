"""Reward: semantic novelty via EmbeddingGemma 300m.

Complements Tanimoto-on-ECFP4 (`novelty.py`) — Tanimoto catches direct
fingerprint overlap; embedding distance catches paraphrase-level similarity
(same pharmacophore in a different scaffold).

Uses `google/embeddinggemma-300m` (308M params, Gemma 3 architecture) via
sentence-transformers. EmbeddingGemma uses task-specific prompt prefixes:
  - For document indexing: "title: SMILES | text: <smiles>"
  - For query: "task: search result | query: <smiles>"

Cached: model loads once, reference embeddings computed once and reused
across calls (lru_cache + module-level state).

Penalty curve identical to `novelty.py`:
  distance >= threshold → reward = distance
  distance <  threshold → reward = distance * (distance / threshold)^2
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from . import extract_smiles

log = logging.getLogger(__name__)

_MODEL = None
_REF_EMBS = None
_REF_PATH: str | None = None


def _ensure_loaded(reference_set: str) -> bool:
    """Load model + cache reference embeddings if not already loaded."""
    global _MODEL, _REF_EMBS, _REF_PATH

    if _MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            log.warning("sentence-transformers not installed: %s — embedding_novelty will return 0", exc)
            return False
        try:
            log.info("Loading EmbeddingGemma 300m (one-time, ~600MB BF16)...")
            _MODEL = SentenceTransformer("google/embeddinggemma-300m")
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not load EmbeddingGemma: %s — falling back to no-op", exc)
            return False

    if _REF_EMBS is None or _REF_PATH != reference_set:
        ref_path = Path(reference_set)
        if not ref_path.exists():
            log.warning("Reference set %s not found — embedding_novelty returns 1.0 (max novelty)", ref_path)
            return False
        with open(ref_path) as f:
            ref_smiles = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        ref_smiles = [s.split()[0] for s in ref_smiles]  # support "SMILES name" format
        log.info("Embedding %d reference antibiotics with EmbeddingGemma...", len(ref_smiles))
        # EmbeddingGemma prompt: "title: <field> | text: <content>" for documents
        prompts = [f"title: SMILES | text: {s}" for s in ref_smiles]
        _REF_EMBS = _MODEL.encode(
            prompts, normalize_embeddings=True, batch_size=128, show_progress_bar=False
        )
        _REF_PATH = reference_set
        log.info("  cached %d reference embeddings (dim=%d)",
                 len(_REF_EMBS), _REF_EMBS.shape[-1])
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
        # Fail-open: return max novelty so RL doesn't get stuck on missing refs
        return [1.0] * len(samples)

    # Build query prompts; track which inputs were valid
    queries: list[str] = []
    valid_idx: list[int] = []
    for i, sample in enumerate(samples):
        smi = extract_smiles(sample)
        if smi:
            queries.append(f"task: search result | query: {smi}")
            valid_idx.append(i)

    if not valid_idx:
        return [0.0] * len(samples)

    q_embs = _MODEL.encode(
        queries, normalize_embeddings=True, batch_size=64, show_progress_bar=False
    )
    # Cosine similarity to nearest reference (vectors are unit-normed → matmul = cosine)
    sims = q_embs @ _REF_EMBS.T  # (Nvalid, Nref)
    max_sims = sims.max(axis=1)

    out = [0.0] * len(samples)
    for k, i in enumerate(valid_idx):
        distance = float(1.0 - max_sims[k])
        if distance >= threshold:
            out[i] = distance
        else:
            # Quadratic penalty for "too similar"
            out[i] = distance * (distance / threshold) ** 2
    return out
