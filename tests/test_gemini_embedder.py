"""Quick smoke test for the Gemini Embedder.

Skips if GEMINI_API_KEY isn't set. When the key is present, validates
that one-shot + batch embedding work and produce 3072-d vectors.

Run:  GEMINI_API_KEY=... python tests/test_gemini_embedder.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _need_key():
    if not (os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")):
        print("SKIP: no GEMINI_API_KEY / GOOGLE_API_KEY env var set")
        sys.exit(0)


def test_one_shot():
    from src.embeddings import GeminiEmbedder
    e = GeminiEmbedder()
    v = e.embed("CC(=O)Oc1ccccc1C(=O)O")  # aspirin
    assert v.shape == (3072,), f"expected (3072,), got {v.shape}"
    print(f"  PASS one-shot: shape={v.shape}, norm={float((v * v).sum()) ** 0.5:.3f}")


def test_batch():
    from src.embeddings import GeminiEmbedder
    e = GeminiEmbedder()
    smis = [
        "CC(=O)Oc1ccccc1C(=O)O",                                  # aspirin
        "CC1(C)SC2C(NC(=O)C(N)c3ccccc3)C(=O)N2C1C(=O)O",          # ampicillin
        "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",                            # caffeine
    ]
    mat = e.embed_batch(smis, task_type="SEMANTIC_SIMILARITY",
                        normalize=True, verbose=False)
    assert mat.shape == (3, 3072), f"expected (3, 3072), got {mat.shape}"
    # cosine similarity ampicillin vs aspirin should be larger than vs caffeine
    cos_a_amp = float(mat[0] @ mat[1])
    cos_a_caf = float(mat[0] @ mat[2])
    print(f"  PASS batch: shape={mat.shape}")
    print(f"    cos(aspirin, ampicillin) = {cos_a_amp:.3f}")
    print(f"    cos(aspirin, caffeine)   = {cos_a_caf:.3f}")


def test_matryoshka():
    from src.embeddings import GeminiEmbedder
    e = GeminiEmbedder(output_dim=768)
    v = e.embed("CC(=O)Oc1ccccc1C(=O)O")
    assert v.shape == (768,), f"expected (768,) for matryoshka, got {v.shape}"
    print(f"  PASS matryoshka 768: shape={v.shape}")


if __name__ == "__main__":
    _need_key()
    print("Testing GeminiEmbedder ...")
    test_one_shot()
    test_batch()
    test_matryoshka()
    print("OK")
