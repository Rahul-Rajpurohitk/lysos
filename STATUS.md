# Lysos — End-to-end status (2026-05-01)

> Comprehensive snapshot of what's built, what's pushed, and what's pending.
> Updated as the project evolves. The single page to scan to know where we are.

## TL;DR

- **49+ commits** pushed to [github.com/Rahul-Rajpurohitk/lysos](https://github.com/Rahul-Rajpurohitk/lysos) (private until kickoff)
- **Stage 2 dataset live on HF Hub** — 31,855 instruction examples (30,263 train + 1,592 valid)
- **Stage 3 RL prompts live on HF Hub** — 3,200 prompts
- **All 24 modules verify clean** — `make verify` passes (24/24)
- **12/13 unit tests pass** (1 skip without rdkit) — `make test`
- **Demo workspace docker-buildable** — FastAPI + Vite/React/Tailwind frontend
- **EmbeddingGemma 300m: all 5 integration phases shipped** — novelty reward + dedup + RAG + similar-drugs UI + 20,489-row index
- **Pitch deck + 5-min demo video storyboard committed** — `docs/pitch-deck.md` + `docs/demo-video-storyboard.md`
- Awaiting AMD Dev Cloud credits to land (expected Sat May 2) → first GPU smoke test

---

## 1. Repo + reservations

| Resource | URL | Status |
|---|---|---|
| GitHub repo | github.com/Rahul-Rajpurohitk/lysos | private, 49+ commits |
| HF Space | huggingface.co/spaces/lablab-ai-amd-developer-hackathon/lysos | reserved, private |
| HF Model — TxGemma-4 (Stage 1) | huggingface.co/rahul24raj/txgemma-4-31b | reserved |
| HF Model — Lysos base (Stage 2 SFT) | huggingface.co/rahul24raj/lysos-base | reserved |
| HF Model — Lysos RL (final) | huggingface.co/rahul24raj/lysos-rl | reserved |
| HF Dataset — Stage 2 | huggingface.co/datasets/rahul24raj/lysos-amr-stage2 | **LIVE — 31,855 examples** |
| HF Dataset — RL prompts | huggingface.co/datasets/rahul24raj/lysos-rl-prompts | **LIVE — 3,200 prompts** |

---

## 2. Data layer (10 sources, 4 datasets on HF)

### Real-data loaders (status against live APIs)

| Source | File | Records on disk | Status |
|---|---|---|---|
| **ChEMBL** | `src/data/chembl.py` | **16,462** | ✓ verified live, 8 pathogens |
| **DBAASP** | `src/data/dbaasp.py` | 152 (light) → growing | ✓ verified, heavy fetch in progress |
| **DRAMP** | `src/data/dramp.py` | 8,532 | ✓ URL fix applied + verified |
| **CARD** | `src/data/card.py` | 3,543 | ✓ species-path fix applied |
| **PDB** | `src/data/pdb.py` | 3,136 | ✓ GraphQL schema fix applied |
| **ZINC** | `src/data/zinc.py` | 100 | ✓ partial (FDA + in-trials) |
| **TDC builder** | `scripts/prepare_tdc_data.py` | (runs on VM) | needs PyTDC dep |
| BindingDB | `src/data/bindingdb.py` | 0 | ⚠ JSP-gated, manual download required |
| PubChem | `src/data/pubchem.py` | 0 | ⚠ most curated AIDs retired (only 2 work) |
| APD3 | `src/data/apd3.py` | 0 | ✗ all source URLs 404 (site changed) |
| DrugBank | `src/data/drugbank.py` | 60K cached SDF | ⚠ needs rdkit on VM to parse |

### Processed datasets

| Path | Count | HF Hub | Notes |
|---|---|---|---|
| `data/processed/amr-stage2/` | **31,855** examples | rahul24raj/lysos-amr-stage2 | 30,263 train + 1,592 valid |
| `data/processed/amr-rl-prompts/` | 3,200 prompts | rahul24raj/lysos-rl-prompts | 3,072 train + 128 valid |
| `data/processed/known_antibiotics_index.parquet` | **20,489** rows | (local — used by RAG + novelty) | ChEMBL + DBAASP + DRAMP |
| `data/processed/tdc-stage1/` | (runs on VM) | rahul24raj/lysos-tdc-stage1 (reserved) | needs PyTDC |

### Per-pathogen ChEMBL distribution (heavy run)

```
EColi-CRE:  3,123    Mtb:        2,732    Paer:       2,711
MRSA:       2,605    VRE:        2,409    KpneuCRE:   1,704
Abaum:        601    NGono:        577
Total:     16,462 unique records
```

---

## 3. Training stack (3 stages)

| Stage | Script | Config | Status |
|---|---|---|---|
| **Stage 1 — TxGemma-4** | `src/training/stage1_txgemma4.py` | `configs/stage1_txgemma4.yaml` | code ready, dry-run verified |
| **Stage 2 — AMR SFT** | `src/training/stage2_amr_sft.py` | `configs/stage2_amr_sft.yaml` | code ready, **dataset on HF Hub** |
| **Stage 3 — GRPO RL** | `src/training/stage3_rl_grpo.py` | `configs/stage3_rl_grpo.yaml` | code ready, **prompts on HF Hub** |

Shared SFT runner: `src/training/sft_runner.py`. Both stages 1 and 2 invoke it with different configs.

### Reward stack (Stage 3)

| Component | File | Verified |
|---|---|---|
| validity | `src/eval/rewards/validity.py` | ✓ |
| qed_score | `src/eval/rewards/drug_likeness.py` | ✓ unit test |
| sa_score | `src/eval/rewards/synth.py` | ✓ |
| novelty (Tanimoto) | `src/eval/rewards/novelty.py` | ✓ |
| hemolysis_inverse | `src/eval/rewards/safety.py` | ✓ |
| predict_mic (heuristic) | `src/eval/rewards/activity.py` | ✓ heuristic; ML predictor TBD |
| **CompositeReward** | `src/eval/rewards/__init__.py` | ✓ unit tests pass |

---

## 4. Demo workspace (HF Space-deployable)

### Backend (`workspace/api/`)
- FastAPI server with 6 routes: `/api/health`, `/api/pathogens`, `/api/design`, `/api/design/stream` (SSE), `/api/score`, `/`
- Lazy-loads LysosGenerator on first request
- Pydantic schemas for type-safe req/resp
- CORS open for demo Space hosting

### Frontend (`workspace/web/`)
- Vite + React 18 + TypeScript (strict) + Tailwind 3
- Custom dark biomedical color palette
- Components: Header, PathogenList, PathogenHeader, ControlPanel, ResultsView, AggregateBar, CandidateCard, ScoresStrip, Footer
- API client with typed wrappers (`api.ts`)
- Vite dev proxy → backend on :7860

### Container (`workspace/Dockerfile`)
- Multi-stage build: node:20 builds React → python:3.11 runs FastAPI
- Serves built frontend at /
- Port 7860 (HF Space default)
- Pinned all deps; pre-loads HF cache on startup

---

## 5. Infrastructure + tooling

| Tool | Purpose |
|---|---|
| `Makefile` | `make verify`, `make test`, `make fetch`, `make inventory`, `make docker` |
| `pyproject.toml` | Hatchling project; deps for all of: training, chemistry, fastapi, hf hub |
| `docker/Dockerfile.rocm` | Training environment for AMD MI300X (rocm/pytorch base + Lysos deps) |
| `scripts/smoke_test_rocm.py` | 10-check pre-flight for AMD VM |
| `scripts/verify_loaders.py` | Smoke-imports all 24 modules |
| `scripts/build_known_antibiotics_index.py` | Builds the 20,489-row index for RAG + novelty |
| `scripts/dedup_with_embeddings.py` | Clusters Stage 2 by semantic similarity, slices per task |
| `scripts/data_inventory.py` | Walks data/raw + data/processed, reports sizes + per-pathogen counts |
| `scripts/fetch_all_data.py` | Unified orchestrator for all 10 loaders |
| `scripts/prepare_*.py` | TDC, AMR, Stage 3 prompts dataset builders |
| `tests/test_rewards.py` | 13 unit tests (12 pass, 1 skip-no-rdkit) |

---

## 6. Vault (Obsidian-style research/plans/decisions)

```
vault/
├── refs/
│   ├── embeddinggemma-blog.md   - Google announcement
│   ├── embeddinggemma-hf.md     - HF model card
│   ├── gemini-embedding-2.md    - Gemini API docs
│   └── gemma-collection.md      - Google org current offerings
├── research/
│   └── 2026-05-01-gemma-embedding-research.md
│         - 4 integration slots, code sketches, decision rationale
├── plans/
│   └── 2026-05-01-embeddinggemma-integration.md
│         - 5-phase implementation plan with verification steps
├── decisions/
│   (next ADRs land here)
└── session-logs/
    └── 2026-05-01-data-fetch-session.md
          - Captures every loader, every bug fix, every push
```

---

## 7. Frontier-model knowledge (current as of 2026-05-01)

### Generation (locked)
- **Gemma 4 31B-it** — 33B dense, multimodal (image-text-to-text), Apr 2026 release, 6.56M downloads on HF
- Backup if MoE testing wins: `gemma-4-26B-A4B-it` (26B params, 4B active)

### Embeddings (planned)
- **EmbeddingGemma 300m** — 308M, Gemma 3 architecture, Matryoshka 768→128, 2K context, open weights
- gemini-embedding-2 (multimodal API, paid) — deferred unless we add image features

### Other frontier models tracked
- DeepSeek V4-Pro (862B), V4-Flash (158B) — released 3 days ago, top-trending
- Qwen 3.6 27B / 35B-A3B (multimodal) — 6 days old
- Mistral Medium 3.5 128B — released earlier today
- Kimi K2.6 — 1.1T params

---

## 8. What's pending

### Hard blockers (waiting on external)
1. **AMD Dev Cloud credits** (expected Sat May 2) — gates the smoke test + all training
2. **APD3** alternative source (current URLs all 404)

### High-priority (do once unblocked)
3. **DBAASP heavy fetch** (running now) → re-build Stage 2 with richer AMP corpus
4. **vLLM + Gemma 4 + ROCm smoke test** on first VM session
5. **PyTDC install + Stage 1 dataset build** on VM
6. **Re-run dedup script** on the 31,855-row Stage 2 with EmbeddingGemma to drop near-duplicates

### Done since last STATUS update
- ✓ EmbeddingGemma integration — all 5 phases shipped (novelty reward, RAG, dedup script, similar-drugs UI, 20,489-row index)
- ✓ Pitch deck — `docs/pitch-deck.md` (10 slides, startup format)
- ✓ Demo video storyboard — `docs/demo-video-storyboard.md` (5-min, 8 sections, beat-by-beat with VO)
- ✓ Stage 2 dataset grew 21,007 → 31,855 examples

### Polish + submission (remaining)
7. 16:9 cover image (Slide 1 of pitch deck → PNG export)
8. README polish for public-on-kickoff
9. Build-in-Public social posts (daily, starting kickoff day)
10. Convert pitch deck markdown → PDF (Marp)

---

## 9. Total disk footprint

```
~/IdeaProjects/lysos/                   ~ 65 MB
  ├── data/raw/                          ~54 MB (CARD cache + ChEMBL + DRAMP + DBAASP + PDB + ZINC + DrugBank cached)
  ├── data/processed/                    ~7.5 MB (HF Datasets on disk)
  ├── workspace/web/node_modules/        not yet installed (~ 200 MB after npm install)
  └── code + docs + vault                ~3 MB
```

Local Mac has 154 GB free → no constraint.

VM scratch (5 TB on Small MI300X) → no constraint.

---

## 10. The day of the kickoff (May 4, 12pm EDT)

The plan when the bell rings:

1. Watch kickoff stream
2. Spin up Large 8× MI300X (saved for fast Stage 1)
3. `git pull && make verify` on the VM (smoke test)
4. `make fetch` (cache real data on VM) — should finish in ~30 min
5. `python -m src.training.stage1_txgemma4 --config configs/stage1_txgemma4.yaml`
6. Tweet "kickoff! Lysos training started on AMD MI300X"
7. By end of Day 1: Stage 1 (TxGemma-4 base) checkpoint pushed to HF Hub

By Day 4 we have all 3 stages trained + workspace deployed.
By Day 6 we submit ~24 hours early.

---

_Last updated: 2026-05-01 (post-storyboard) by the build session._
_Next update: after DBAASP heavy completes, or after the pitch-deck PDF + cover image land._
