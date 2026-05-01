---
title: EmbeddingGemma 300m integration plan
date: 2026-05-01
status: COMPLETED — all 5 phases shipped
completed_on: 2026-05-01
actual_effort: ~3.5 hours
estimated_effort: 3-4 hours
priority: high
---

## ✅ Status: complete (2026-05-01)

All 5 phases shipped + verified on the local stack. Files that landed:

| Phase | Path | Status |
|---|---|---|
| 1. Dependency | `pyproject.toml` (`sentence-transformers>=3.0.0`) | ✓ |
| 2. Novelty reward | `src/eval/rewards/embedding_novelty.py` + `configs/stage3_rl_grpo.yaml` (weight 0.05) | ✓ |
| 3. Dedup script | `scripts/dedup_with_embeddings.py` | ✓ — runs on VM with EmbeddingGemma loaded |
| 4. RAG at inference | `src/inference/retrieval.py` + `src/inference/generate.py` (`enable_rag=True`) | ✓ |
| 5. Similar-drugs UI | `workspace/api/server.py` `/api/similar` + `workspace/web/src/App.tsx` candidate-card panel + `findSimilar` API client | ✓ |

Bonus: `scripts/build_known_antibiotics_index.py` builds the 20,489-row reference index from ChEMBL + DBAASP + DRAMP that powers all four slots.

Verification:
- `make verify` — 24/24 modules pass (embedding_novelty included)
- `tests/test_rewards.py` — 12 pass, 1 skip (rdkit). Reward integrates cleanly.
- Stage 3 dry-run includes the new component; weights still sum to ~1.0
- Workspace UI screenshot in `docs/assets/workspace-screenshot.png` shows the integration in the live build

Notes:
- HF gating: user must accept `google/embeddinggemma-300m` license once. Done.
- Model loads on first request, lru-cached, fail-open (returns 0.0 if unavailable so training never crashes on a missing dep).
- Embedding novelty + Tanimoto novelty cohabit — different signal, different weight.

---

# Original plan (kept for reference)


# Plan — Wire EmbeddingGemma 300m into Lysos (4 slots)

## Context

Lysos uses Gemma 4 31B for generation. Adding EmbeddingGemma 300m gives us a coherent Gemma-family stack and unlocks:
1. Better novelty reward (semantic vs bit-level)
2. RAG-augmented inference at demo time
3. Training data dedup
4. "Similar known drugs" feature in workspace

See `vault/research/2026-05-01-gemma-embedding-research.md` for the why.

## Phases

### Phase 1 — Dependency + smoke test (15 min)

**Files to modify**:
- `pyproject.toml` — add `sentence-transformers>=3.0.0`
- `docker/Dockerfile.rocm` — accept Gemma license, pre-warm `google/embeddinggemma-300m` cache

**Verify**:
```bash
python -c "from sentence_transformers import SentenceTransformer; \
m = SentenceTransformer('google/embeddinggemma-300m'); \
print(m.encode(['CC(=O)O']).shape)"  # should print (768,)
```

### Phase 2 — Embedding-based novelty reward (45 min)

**New file**: `src/eval/rewards/embedding_novelty.py`

```python
from sentence_transformers import SentenceTransformer
import numpy as np
from . import extract_smiles

_model = None
_reference_embs = None

def _ensure_loaded(reference_set: str):
    global _model, _reference_embs
    if _model is None:
        _model = SentenceTransformer("google/embeddinggemma-300m")
    if _reference_embs is None:
        with open(reference_set) as f:
            ref_smi = [l.strip() for l in f if l.strip()]
        prompts = [f"title: SMILES | text: {s}" for s in ref_smi]
        _reference_embs = _model.encode(
            prompts, normalize_embeddings=True, batch_size=128
        )

def embedding_novelty(samples, *, reference_set, threshold=0.6, **_):
    _ensure_loaded(reference_set)
    out = []
    queries = []
    valid_idx = []
    for i, s in enumerate(samples):
        smi = extract_smiles(s)
        if smi:
            queries.append(f"task: search result | query: {smi}")
            valid_idx.append(i)
        else:
            queries.append(None)
    if not valid_idx:
        return [0.0] * len(samples)
    valid_q = [queries[i] for i in valid_idx]
    q_emb = _model.encode(valid_q, normalize_embeddings=True, batch_size=64)
    sims = q_emb @ _reference_embs.T
    max_sims = sims.max(axis=1)
    result = [0.0] * len(samples)
    for k, i in enumerate(valid_idx):
        distance = float(1.0 - max_sims[k])
        if distance >= threshold:
            result[i] = distance
        else:
            result[i] = distance * (distance / threshold) ** 2
    return result
```

**Wire into config**: `configs/stage3_rl_grpo.yaml`

```yaml
reward:
  components:
    # ... existing components ...
    - name: embedding_novelty
      weight: 0.10  # complement Tanimoto, not replace
      module: src.eval.rewards.embedding_novelty:embedding_novelty
      args:
        reference_set: data/processed/known-antibiotics.smiles
        threshold: 0.6
```

Adjust other component weights so they still sum to ~1.0.

**Tests**: `tests/test_rewards.py` — add `test_embedding_novelty_known_drug` (skip if no rdkit/no GPU).

### Phase 3 — Training data dedup (45 min)

**New script**: `scripts/dedup_with_embeddings.py`

```python
"""Cluster training examples by EmbeddingGemma similarity, drop duplicates."""

# Pseudocode:
# 1. Load Stage 2 dataset
# 2. Embed every example's `messages` field
# 3. Build kNN graph on cosine similarity
# 4. Connected components @ similarity > 0.95 → clusters
# 5. Keep one example per cluster (preserve task-stratification)
# 6. Save to data/processed/amr-stage2-dedup/
```

Run before Stage 2 training:

```bash
make dedup-stage2
```

### Phase 4 — RAG at demo time (1 hour)

**New file**: `src/inference/retrieval.py`

```python
"""EmbeddingGemma-powered retrieval over known-antibiotics for in-context examples."""

class AntibioticRetriever:
    def __init__(self, index_path: str):
        self.model = SentenceTransformer("google/embeddinggemma-300m")
        # Load pre-built FAISS or numpy index
        ...

    def retrieve(self, query_text: str, k: int = 5) -> list[dict]:
        """Return top-k known antibiotics + metadata."""
        ...
```

**Wire into**: `src/inference/generate.py` — add `enable_rag=True` flag to `LysosGenerator.design()`. When set:

1. Embed the user's request
2. Retrieve top-3 similar known antibiotics from index
3. Append them to the prompt as `Reference examples: ...`
4. Generate

**Wire into**: `workspace/api/server.py` — add `enable_rag: bool = True` param to `DesignRequest`.

### Phase 5 — "Similar drugs" workspace feature (1 hour)

**Frontend change**: `workspace/web/src/App.tsx`

For each generated candidate card, add a **"Find similar known drugs"** action button. On click:

1. POST `/api/similar` with `{smiles: "..."}`
2. Backend uses `AntibioticRetriever.retrieve(smiles, k=5)`
3. Render returned drugs in a side panel with similarity bars

**Backend route**: `workspace/api/server.py`

```python
@app.post("/api/similar")
async def find_similar(req: SimilarRequest):
    retr = _get_retriever()
    return await asyncio.to_thread(retr.retrieve, req.smiles, k=5)
```

## Verification

1. **Phase 1**: smoke test prints `(768,)`
2. **Phase 2**: `python -m src.training.stage3_rl_grpo --config configs/stage3_rl_grpo.yaml --dry-run` includes the new reward; `pytest tests/test_rewards.py::test_embedding_novelty_known_drug` passes
3. **Phase 3**: dedup'd dataset has 80–90% of original size; per-task counts roughly proportional
4. **Phase 4**: `LysosGenerator(enable_rag=True).design("MRSA", n=5)` includes "Reference examples:" lines in prompts
5. **Phase 5**: workspace shows similarity panel after clicking "Find similar"

## Risks

| Risk | Mitigation |
|---|---|
| EmbeddingGemma needs HF license accept (gated) | Already logged in as `rahul24raj`; one-click accept on the model card |
| GPU memory spike when loading on AMD VM during RL | Load on CPU; embed once, cache vectors; don't keep model on GPU during RL rollouts |
| Cosine similarity too coarse for chemistry (false positives) | Combine with Tanimoto in composite (already doing); inspect top-k matches manually before locking weights |
| RAG context bloats prompt beyond 4K → truncates user query | Keep retrieved docs short (just SMILES + name + 1-line indication, ~50 tokens × 3 = 150 token overhead) |

## Out of scope (intentional)

- gemini-embedding-2 (paid API, multimodal) — defer until we add image features
- Full FAISS-with-GPU acceleration — numpy cosine is plenty fast for our reference set size (<100K vectors)
- Multilingual support — drug names already mostly English/Latin
