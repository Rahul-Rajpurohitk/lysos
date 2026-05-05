"""Gemini Embedding 2 wrapper — gemini-embedding-2.

Drop-in replacement for sentence-transformers `SentenceTransformer.encode`
that calls Google's Gemini Embedding API. 3072-d Matryoshka, multimodal-ready,
$0.025/1M tokens.

Configuration:
  - Set `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) env var.
  - Defaults to gemini-embedding-2, 3072d output.
  - Optional Matryoshka downsampling via `output_dim` (768/1536/3072).

Task types (per Google docs):
  - RETRIEVAL_DOCUMENT — for indexing the corpus
  - RETRIEVAL_QUERY    — for query-side embedding
  - SEMANTIC_SIMILARITY — for symmetric similarity
  - CLASSIFICATION     — for classifying
  - CLUSTERING         — for grouping (what dedup wants)

Usage:

    from src.embeddings import GeminiEmbedder
    emb = GeminiEmbedder()  # picks up GEMINI_API_KEY from env

    # one-shot
    v = emb.embed("CC(=O)O")  # → np.ndarray shape (3072,)

    # batched (auto-respects 100-doc limit per call)
    vectors = emb.embed_batch(["smi1", "smi2", ...],
                              task_type="RETRIEVAL_DOCUMENT")  # → (N, 3072)

    # Matryoshka 768 dims
    emb_768 = GeminiEmbedder(output_dim=768)
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Optional

import numpy as np
import requests

log = logging.getLogger("gemini_embed")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
MODEL_NAME = "gemini-embedding-2"
# Per Google docs the API caps at 100 strings per :batchEmbedContents call
BATCH_LIMIT = 100
# Free tier rate cap is 1500 RPM — we throttle below
DEFAULT_QPS = 20.0

VALID_TASK_TYPES = {
    "RETRIEVAL_QUERY",
    "RETRIEVAL_DOCUMENT",
    "SEMANTIC_SIMILARITY",
    "CLASSIFICATION",
    "CLUSTERING",
    "QUESTION_ANSWERING",
    "FACT_VERIFICATION",
    "CODE_RETRIEVAL_QUERY",
}


class GeminiEmbedder:
    """Thin async-friendly wrapper around the Gemini Embedding 2 REST endpoint."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        model: str = MODEL_NAME,
        output_dim: Optional[int] = None,
        qps: float = DEFAULT_QPS,
        timeout: float = 30.0,
        max_retries: int = 8,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        if not self.api_key:
            raise RuntimeError(
                "Gemini Embedding 2 needs GEMINI_API_KEY (or GOOGLE_API_KEY). "
                "Get one at https://aistudio.google.com/apikey, then export it."
            )
        self.model = model
        self.output_dim = output_dim
        self.qps = qps
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self._last_call = 0.0

    # -- core REST calls --------------------------------------------------

    def _post(self, path: str, body: dict) -> dict:
        url = f"{GEMINI_API_BASE}{path}?key={self.api_key}"
        backoff = 2.0
        for attempt in range(self.max_retries):
            # rate-limit
            elapsed = time.time() - self._last_call
            min_interval = 1.0 / self.qps
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            self._last_call = time.time()

            r = self.session.post(url, json=body, timeout=self.timeout)
            if r.status_code in (429, 503):
                # Google encodes actual retryDelay inside JSON error body.
                wait = float(r.headers.get("Retry-After", backoff))
                err_msg = ""
                try:
                    err = r.json()
                    err_msg = err.get("error", {}).get("message", "")[:300]
                    for d in err.get("error", {}).get("details", []) or []:
                        rd = d.get("retryDelay")
                        if isinstance(rd, str) and rd.endswith("s"):
                            try:
                                wait = max(wait, float(rd[:-1]) + 1.0)
                            except ValueError:
                                pass
                except Exception:  # noqa: BLE001
                    pass
                log.warning("Gemini %s — sleep %.1fs (attempt %d/%d) %s",
                            r.status_code, wait, attempt + 1,
                            self.max_retries, err_msg)
                time.sleep(wait)
                backoff = min(backoff * 2, 90.0)
                continue
            if r.ok:
                return r.json()
            log.error("Gemini API %s: %s", r.status_code, r.text[:300])
            r.raise_for_status()
        raise RuntimeError(f"Gemini API: max retries exhausted")

    def _embed_one(self, text: str, task_type: str) -> np.ndarray:
        body = {
            "model": f"models/{self.model}",
            "content": {"parts": [{"text": text}]},
            "taskType": task_type,
        }
        if self.output_dim:
            body["outputDimensionality"] = self.output_dim
        r = self._post(f"/models/{self.model}:embedContent", body)
        return np.asarray(r["embedding"]["values"], dtype=np.float32)

    def _embed_batch_call(
        self, texts: list[str], task_type: str
    ) -> np.ndarray:
        """One :batchEmbedContents call — capped at BATCH_LIMIT strings."""
        body = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": t}]},
                    "taskType": task_type,
                    **(
                        {"outputDimensionality": self.output_dim}
                        if self.output_dim else {}
                    ),
                }
                for t in texts
            ],
        }
        r = self._post(f"/models/{self.model}:batchEmbedContents", body)
        embs = [np.asarray(e["values"], dtype=np.float32)
                for e in r.get("embeddings", [])]
        if not embs:
            raise RuntimeError(f"Gemini returned no embeddings: {r}")
        return np.vstack(embs)

    # -- public API -------------------------------------------------------

    def embed(self, text: str,
              task_type: str = "RETRIEVAL_DOCUMENT") -> np.ndarray:
        if task_type not in VALID_TASK_TYPES:
            raise ValueError(
                f"task_type must be one of {sorted(VALID_TASK_TYPES)}; "
                f"got {task_type!r}"
            )
        return self._embed_one(text, task_type)

    def embed_batch(
        self,
        texts: Iterable[str],
        *,
        task_type: str = "RETRIEVAL_DOCUMENT",
        normalize: bool = True,
        threads: int = 6,
        verbose: bool = True,
    ) -> np.ndarray:
        if task_type not in VALID_TASK_TYPES:
            raise ValueError(f"task_type must be one of {sorted(VALID_TASK_TYPES)}")

        items = list(texts)
        n = len(items)
        if n == 0:
            return np.empty((0, self.output_dim or 3072), dtype=np.float32)

        chunks: list[tuple[int, list[str]]] = []
        for i in range(0, n, BATCH_LIMIT):
            chunks.append((i, items[i:i + BATCH_LIMIT]))

        out: list[Optional[np.ndarray]] = [None] * n

        def _do(start: int, batch: list[str]) -> tuple[int, np.ndarray]:
            return start, self._embed_batch_call(batch, task_type)

        with ThreadPoolExecutor(max_workers=threads) as pool:
            futures = [pool.submit(_do, s, b) for s, b in chunks]
            done = 0
            for fut in as_completed(futures):
                start, mat = fut.result()
                for k, vec in enumerate(mat):
                    out[start + k] = vec
                done += 1
                if verbose and done % 5 == 0:
                    log.info("  embedded %d / %d batches (%d / %d items)",
                             done, len(chunks),
                             min(done * BATCH_LIMIT, n), n)

        result = np.vstack(out)
        if normalize:
            norms = np.linalg.norm(result, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            result = result / norms
        return result

    def encode(self, texts, *, batch_size=64, normalize_embeddings=True,
               show_progress_bar=False, **_):
        """Sentence-Transformers-compatible signature for drop-in replacement."""
        return self.embed_batch(
            texts, task_type="RETRIEVAL_DOCUMENT",
            normalize=normalize_embeddings,
            verbose=show_progress_bar,
        )

    def __repr__(self) -> str:
        return f"GeminiEmbedder(model={self.model!r}, output_dim={self.output_dim})"
