"""Embedding stack — Gemini Embedding 2 (gemini-embedding-2).

Used for:
  - Building the RAG / novelty index over known antibiotics (offline, one-time)
  - Stage 2 dedup pre-pass (offline)
  - Stage 3 RL reward `embedding_novelty` (batched, online during rollouts)
  - Workspace `find similar drugs` (per-request)

Why Gemini Embedding 2 over EmbeddingGemma 300m:
  - 3072-d Matryoshka (vs 768-d) — more headroom for chemistry similarity
  - Multimodal — opens future image-of-binding-pocket inputs (v2)
  - Production-grade Google API, $0.025 / 1M tokens
  - Ungated — no license-acceptance friction

Generator (Gemma 4 31B) stays on the MI300X. Embedder runs via API.
The pitch becomes: best open generator + best closed embedder. No degraded
fallbacks anywhere in the Lysos pipeline.

Usage:

    from src.embeddings import GeminiEmbedder
    emb = GeminiEmbedder()
    vectors = emb.embed_batch(["smiles 1", "smiles 2"], task_type="RETRIEVAL_DOCUMENT")
"""

from .gemini import GeminiEmbedder

__all__ = ["GeminiEmbedder"]
