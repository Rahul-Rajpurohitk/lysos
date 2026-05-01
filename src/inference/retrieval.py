"""Retrieval over known antibiotics using EmbeddingGemma 300m.

Used by:
  - Demo workspace ("find similar known drugs" feature)
  - Inference pipeline (RAG-augmented generation: inject top-k known
    antibiotics as in-context examples)

Indexes a corpus of (smiles, name, indication) tuples and returns
nearest-neighbor matches by cosine similarity in EmbeddingGemma's
768-dim space.

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
    """EmbeddingGemma-powered nearest-neighbor index over known antibiotics."""

    def __init__(
        self,
        index_source: str | Path,
        *,
        model_id: str = "google/embeddinggemma-300m",
        device: str | None = None,
    ):
        self.index_source = Path(index_source)
        self.model_id = model_id
        self.device = device
        self._model = None
        self._docs: list[IndexedDoc] = []
        self._embeddings = None

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                f"sentence-transformers not installed: {exc}. "
                "pip install sentence-transformers"
            ) from exc

        log.info("Loading EmbeddingGemma 300m...")
        self._model = SentenceTransformer(self.model_id, device=self.device)
        self._build_index()

    def _build_index(self):
        if not self.index_source.exists():
            raise FileNotFoundError(f"Index source not found: {self.index_source}")

        log.info("Building antibiotic index from %s ...", self.index_source)
        self._docs = list(self._read_corpus(self.index_source))
        if not self._docs:
            raise ValueError(f"No documents loaded from {self.index_source}")

        texts = [d.as_document_text() for d in self._docs]
        # EmbeddingGemma uses "title: <field> | text: <content>" for documents
        prompts = [f"title: SMILES | text: {t}" for t in texts]
        log.info("  embedding %d documents...", len(prompts))
        self._embeddings = self._model.encode(
            prompts, normalize_embeddings=True, batch_size=128, show_progress_bar=False
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
            query: Free text or SMILES. EmbeddingGemma handles both.
            k: how many to return
            as_query: if True (default), use query prompt prefix; if False,
                      treat as a document for similarity to other documents.
        """
        self._load()
        if as_query:
            prompt = f"task: search result | query: {query}"
        else:
            prompt = f"title: SMILES | text: {query}"
        q_emb = self._model.encode(
            [prompt], normalize_embeddings=True, show_progress_bar=False,
        )[0]

        sims = self._embeddings @ q_emb  # (N,)
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
