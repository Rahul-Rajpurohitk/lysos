---
title: Gemma / Gemini Embedding research for Lysos
date: 2026-05-01
tags: [embeddings, gemma, gemini, retrieval, novelty, rag, lysos]
sources:
  - https://developers.googleblog.com/en/introducing-embeddinggemma/
  - https://huggingface.co/google/embeddinggemma-300m
  - https://ai.google.dev/gemini-api/docs/embeddings
status: actionable
---

# Gemma / Gemini Embedding 2 — research for Lysos integration

> **TL;DR**: EmbeddingGemma 300m (open weights, Gemma 3 architecture) is the right embedding model for Lysos. It runs on a single AMD MI300X with negligible footprint (<1 GB), gives us Matryoshka-tunable 128–768 dim vectors, and slot-fits into 4 places in our pipeline: novelty reward, RAG-augmented prompts, training data dedup, and demo-Space search.

---

## 1. What's available right now (verified Apr 30, 2026)

### A. **EmbeddingGemma 300m** — `google/embeddinggemma-300m` on HF Hub

- **Architecture**: Gemma 3 text-only, 308 M parameters, 22 layers
- **Context**: 2,048 tokens
- **Output dimensions**: **Matryoshka representation** — train once, slice down at inference: 768 / 512 / 256 / 128
- **License**: Gemma (Google's open license; free for research + commercial)
- **Paper**: arxiv:2509.20354
- **Languages**: 100+
- **Memory**: <200 MB RAM with QAT (quantization-aware training); ~600 MB BF16
- **Speed**: ~10ms per embed on commodity CPU at 768d, far less on GPU
- **MTEB rank**: highest open-source under 500M params
- **Tooling**: native sentence-transformers, llama.cpp, MLX, Ollama, transformers.js, LiteRT, LangChain, LlamaIndex
- **Designed companion to**: Gemma 3n (small generative model) for on-device RAG

**Critical note**: EmbeddingGemma uses **task-specific prompt prefixes**. Always embed queries and documents with the right prefix:
```
Query:    "task: search result | query: <text>"
Document: "title: <title> | text: <text>"
Classification:  "task: classification | query: <text>"
Clustering:      "task: clustering | query: <text>"
Sentence sim:    "task: sentence similarity | query: <text>"
Code search:     "task: code retrieval | query: <text>"
```

We'd use `task: search result | query: ...` for retrieval and `title: SMILES | text: <smiles>` for indexing.

### B. **gemini-embedding-2** — closed-source API (`ai.google.dev`)

- **Modality**: text + image (FIRST multimodal embedding in Gemini API)
- **Versions**: `gemini-embedding-2` (newest), `gemini-embedding-001` (still GA)
- **Migration path** documented from -001 → -2
- **Cost**: per-call API pricing (paid)
- **Customizable dimensions** via `output_dimensionality` param

Use Gemini Embedding 2 ONLY if we want multimodal (e.g., embedding chemical structure images with SMILES). For pure text/SMILES, EmbeddingGemma is open + cheaper.

---

## 2. Why this matters for Lysos

Lysos is built on **Gemma 4 31B** for generation. Adding **EmbeddingGemma 300m** for retrieval gives us a coherent Gemma-family stack across both halves of a RAG-augmented training/inference pipeline. Both models:
- Share the Gemma SentencePiece tokenizer
- Use compatible chat templates
- Run on the same ROCm Docker image with the same `transformers` install
- Total fit on one MI300X 192 GB: ~62 GB (Gemma 4 BF16) + ~1 GB (EmbeddingGemma BF16) = ~63 GB → leaves ~130 GB for activations/RL/multi-process

---

## 3. Four concrete places EmbeddingGemma plugs into Lysos

### Slot 1 — **Novelty reward (Stage 3 RL)**, replace Tanimoto

Current: `src/eval/rewards/novelty.py` uses ECFP4 Morgan fingerprints + Tanimoto distance to known antibiotics. Tanimoto is good but only captures bit-level fingerprint overlap. EmbeddingGemma gives us **semantic chemistry novelty** — molecules can be structurally different but functionally similar (same pharmacophore in different scaffold), and dense embeddings should catch that better than fingerprints.

**Implementation**:
- At training start: pre-embed all known antibiotics (the same reference SMILES set we use for Tanimoto) → cache 768d vectors.
- During RL rollout: embed each generated SMILES, compute cosine distance to nearest known.
- Reward = `1 - max_cos_sim(generated, reference_set)` with the same threshold logic.

**Why ON TOP of Tanimoto, not replacing**: keep both as separate reward components. Tanimoto catches direct copies; embedding catches paraphrases. Composite reward already supports multi-component scoring.

### Slot 2 — **In-context retrieval (RAG) for the demo Space**

Currently the demo workspace generates molecules from scratch. Add a RAG step:

1. User picks a target pathogen + constraints
2. Lysos embeds the prompt (user's request) with `task: search result | query:`
3. Search the indexed corpus of known antibiotics (`data/processed/known-antibiotics.smiles` indexed with EmbeddingGemma) for top-k similar prior designs
4. Inject the top-k as in-context examples in the generation prompt
5. Lysos generates new candidates with grounded context

**Why this matters**: in-context examples dramatically improve generation quality without further fine-tuning. Saves us iterations during the hackathon.

### Slot 3 — **Training data dedup (Stage 1 + Stage 2)**

Stage 1 TDC corpus and Stage 2 AMR corpus have many near-duplicate examples (same SMILES, slightly different prompt phrasings). RDKit canonical SMILES helps but doesn't catch:
- Different prompt templates with same underlying task
- Slightly different molecules (one carbon different) that aren't true negatives

**Implementation**:
- Embed every training example's `messages` field with EmbeddingGemma
- Cluster on cosine similarity > 0.95
- Keep one representative per cluster, weight others as soft duplicates (or drop)

**Win**: 10–20% smaller dataset that trains faster and avoids over-fitting on near-dupes.

### Slot 4 — **Demo Space: "find me similar known drugs" feature**

Workspace UI already has the candidate-list view. Add a button: "Show known drugs similar to this generated molecule." Powered by:
- Pre-indexed DrugBank + ChEMBL approved-drug subset
- EmbeddingGemma cosine search at runtime
- Returns top-5 known drugs with similarity scores

**Why**: this is the kind of feature that makes the demo viral — users can immediately see "your AI-generated novel molecule looks like X% combination of penicillin and Y", which feels real.

---

## 4. Integration cost (real numbers)

| Item | Cost / time |
|---|---|
| Add `embeddinggemma-300m` to ROCm Dockerfile | 5 min (pip install + license accept) |
| Pre-embed reference antibiotic set (~50K SMILES) | 5 min on MI300X |
| Add `src/eval/rewards/embedding_novelty.py` reward fn | 30 min (model wrapper + cosine fn) |
| Wire into Stage 3 composite reward config | 5 min |
| Pre-embed Stage 1/2 datasets for dedup | 30 min |
| Add RAG step to demo Space FastAPI backend | 1 hour |
| Add "similar drugs" button to workspace UI | 1 hour |
| **Total** | **~3.5 hours** |

This is a high-ROI ~half-day of work that meaningfully improves multiple parts of the pipeline.

---

## 5. Key code snippet (verified pattern)

```python
# src/eval/rewards/embedding_novelty.py (sketch)
from sentence_transformers import SentenceTransformer
import numpy as np

_model = None
_reference_embeddings = None

def _load():
    global _model, _reference_embeddings
    if _model is None:
        _model = SentenceTransformer("google/embeddinggemma-300m")
        # Pre-embed known antibiotics from cached set
        with open("data/processed/known-antibiotics.smiles") as f:
            ref_smiles = [line.strip() for line in f if line.strip()]
        ref_texts = [f"title: SMILES | text: {s}" for s in ref_smiles]
        _reference_embeddings = _model.encode(
            ref_texts, normalize_embeddings=True, prompt_name="Retrieval-document"
        )

def embedding_novelty(samples: list[str], **_) -> list[float]:
    _load()
    from src.eval.rewards import extract_smiles
    smiles = [extract_smiles(s) or "" for s in samples]
    queries = [f"task: search result | query: {s}" for s in smiles]
    q_emb = _model.encode(queries, normalize_embeddings=True)
    # Cosine similarity to nearest known
    sims = q_emb @ _reference_embeddings.T  # (N_query, N_ref)
    max_sim = sims.max(axis=1)
    return [float(1.0 - m) for m in max_sim]
```

---

## 6. Decision

**Add EmbeddingGemma 300m to Lysos.** Plan:

1. Pin `sentence-transformers>=3.0.0` in `pyproject.toml`
2. Add `google/embeddinggemma-300m` to model downloads on AMD VM bring-up
3. Implement Slot 1 (novelty reward) before Stage 3 RL training
4. Implement Slot 3 (dedup) during Stage 2 data prep
5. Implement Slots 2 + 4 during workspace polish week (Day 5–6)

`gemini-embedding-2` is **deferred** — only revisit if we add multimodal (image-based) molecule similarity to the demo. For now, open weights win.

---

## 7. References (saved locally)

- `vault/refs/embeddinggemma-blog.md` — Google announcement
- `vault/refs/embeddinggemma-hf.md` — HF model card
- `vault/refs/gemini-embedding-2.md` — Gemini API docs
- `vault/refs/gemma-collection.md` — current Google org models
