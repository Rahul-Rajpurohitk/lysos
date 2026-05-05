"""Retrieval over known antibiotics using Gemini Embedding 2.

Used by:
  - Demo workspace ("find similar known drugs" feature)
  - Inference pipeline (RAG-augmented generation: inject top-k known
    antibiotics as in-context examples)

Indexes a corpus of (smiles, name, indication) tuples and returns
nearest-neighbor matches by cosine similarity in gemini-embedding-2's
3072-dim Matryoshka space.

Required env: GEMINI_API_KEY (or GOOGLE_API_KEY).

Usage:

    from src.inference.retrieval import AntibioticRetriever
    retr = AntibioticRetriever("data/processed/known-antibiotics.smiles")
    hits = retr.retrieve("design a beta-lactam for MRSA", k=5)
    for h in hits:
        print(h["smiles"], h["similarity"])
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class IndexedDoc:
    smiles: str
    name: str = ""
    indication: str = ""
    raw: str = ""

    def as_document_text(self) -> str:
        """Text used for indexing — combines all metadata for richer matching."""
        parts = [f"SMILES: {self.smiles}"]
        if self.name:
            parts.append(f"Name: {self.name}")
        if self.indication:
            parts.append(f"Indication: {self.indication}")
        return " | ".join(parts)


class AntibioticRetriever:
    """Gemini-Embedding-2 powered nearest-neighbor index over known antibiotics."""

    def __init__(
        self,
        index_source: str | Path,
        *,
        output_dim: int | None = None,  # None = 3072 default
    ):
        self.index_source = Path(index_source)
        self.output_dim = output_dim
        self._embedder = None
        self._docs: list[IndexedDoc] = []
        self._embeddings = None

    def _load(self):
        if self._embedder is not None:
            return
        from src.embeddings import GeminiEmbedder
        self._embedder = GeminiEmbedder(output_dim=self.output_dim)
        self._build_index()

    def _build_index(self):
        if not self.index_source.exists():
            raise FileNotFoundError(f"Index source not found: {self.index_source}")

        log.info("Building antibiotic index from %s ...", self.index_source)
        self._docs = list(self._read_corpus(self.index_source))
        if not self._docs:
            raise ValueError(f"No documents loaded from {self.index_source}")

        texts = [d.as_document_text() for d in self._docs]
        log.info("  embedding %d documents with gemini-embedding-2...", len(texts))
        self._embeddings = self._embedder.embed_batch(
            texts, task_type="RETRIEVAL_DOCUMENT", normalize=True,
        )
        log.info("  index ready: %d docs, dim=%d",
                 len(self._docs), self._embeddings.shape[-1])

    @staticmethod
    def _read_corpus(path: Path) -> list[IndexedDoc]:
        """Parse a SMILES corpus. Supports:
          - Plain .smi  (one SMILES per line, optional 'name' after space)
          - CSV with columns smiles, name, indication
        """
        docs: list[IndexedDoc] = []
        if path.suffix == ".csv":
            import csv
            with open(path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    smi = row.get("smiles", "").strip()
                    if not smi:
                        continue
                    docs.append(IndexedDoc(
                        smiles=smi,
                        name=row.get("name", ""),
                        indication=row.get("indication", ""),
                        raw=str(row),
                    ))
        else:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(maxsplit=1)
                    smi = parts[0]
                    name = parts[1] if len(parts) > 1 else ""
                    docs.append(IndexedDoc(smiles=smi, name=name, raw=line))
        return docs

    def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        as_query: bool = True,
    ) -> list[dict[str, Any]]:
        """Return top-k nearest documents to the query string.

        Args:
            query: Free text or SMILES.
            k: how many to return
            as_query: if True (default), use query task type for asymmetric
                      retrieval; if False, use SEMANTIC_SIMILARITY (symmetric).
        """
        self._load()
        task_type = "RETRIEVAL_QUERY" if as_query else "SEMANTIC_SIMILARITY"
        q_emb = self._embedder.embed(query, task_type=task_type)
        # normalize (embed() returns un-normalized)
        norm = float(np.linalg.norm(q_emb))
        if norm > 0:
            q_emb = q_emb / norm
        sims = self._embeddings @ q_emb
        top_idx = sims.argsort()[::-1][:k]
        out = []
        for i in top_idx:
            doc = self._docs[int(i)]
            out.append({
                "smiles": doc.smiles,
                "name": doc.name,
                "indication": doc.indication,
                "similarity": float(sims[int(i)]),
            })
        return out

    def index_size(self) -> int:
        if self._embeddings is None:
            return 0
        return len(self._embeddings)


# Module-level singleton helper for FastAPI / serverless reuse


@lru_cache(maxsize=4)
def get_retriever(index_source: str) -> AntibioticRetriever:
    """Memoized retriever — call once per index, reused across requests."""
    return AntibioticRetriever(index_source)
