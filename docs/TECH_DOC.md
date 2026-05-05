# Lysos — Technical Documentation

> Single source of truth for the Lysos antimicrobial drug-design system.
> Updated continuously as the system evolves. Last edit: 2026-05-05.

## Table of contents

- [1. Mission + context](#1-mission--context)
- [2. System overview](#2-system-overview)
- [3. Data layer](#3-data-layer)
- [4. Reward stack](#4-reward-stack)
- [5. Training pipeline](#5-training-pipeline)
- [6. Inference layer](#6-inference-layer)
- [7. Workspace API](#7-workspace-api)
- [8. HF Space + demo](#8-hf-space--demo)
- [9. Monitoring + dashboards](#9-monitoring--dashboards)
- [10. Reliability + ops protection](#10-reliability--ops-protection)
- [11. Key + secrets management](#11-key--secrets-management)
- [12. Test coverage](#12-test-coverage)
- [13. Deployment](#13-deployment)
- [14. Reproducibility](#14-reproducibility)
- [15. File map](#15-file-map)
- [16. Glossary](#16-glossary)

---

## 1. Mission + context

### 1.1 What we're building

Lysos is a **generative drug-design system specialized for antimicrobial
resistance (AMR)**. Given a WHO-priority pathogen and a constraint profile,
the system proposes novel small-molecule and peptide candidates that:

1. Have a high probability of activity (low MIC) against the target.
2. Avoid known cross-resistance pressure (pivots around first-line therapy classes).
3. Pass druglikeness, synthesizability, and hemolysis-safety filters.
4. Are novel (low Tanimoto + low embedding similarity to known antibiotics).
5. Predict a plausible 3D pose against the canonical target structure.

### 1.2 Hackathon context

- **Event**: AMD Developer Hackathon — May 4-10, 2026 (lablab.ai).
- **Track 2**: Fine-Tuning on AMD MI300X. Eligible for Grand Prize +
  HF Most-Liked Space stack.
- **Compute budget**: $300 ($100 free credits + $200 self-funded).
- **Deliverables**: trained model on HF (`rahul24raj/lysos-rl`),
  HF Space demo, methods paper, datasheet, comparator benchmark.

### 1.3 Why AMD MI300X is necessary

Stage 3 GRPO training holds:
- Policy model in BF16 (~62 GB)
- Frozen reference model in BF16 (~62 GB)
- Activations + gradients during gen + grad step
- KV cache for G generations per prompt

Total RAM during training is >150 GB. H100 (80 GB) cannot fit. MI300X
(192 GB HBM3e) can. This is the architectural reason Lysos exists in its
current form.

### 1.4 The 8 priority pathogens

Lysos targets the WHO 2024 priority pathogen list, critical and high tiers:

| Short    | Full name                        | Tier     | First-line resistance escape |
|----------|----------------------------------|----------|------------------------------|
| MRSA     | Staph aureus (MRSA)              | critical | mecA → flucloxacillin out    |
| Mtb      | Mycobacterium tuberculosis       | critical | rpoB / katG mutations        |
| EColi-CRE| E. coli (ESBL+ / CRE)           | critical | OXA-48, KPC, NDM             |
| KpneuCRE | Klebsiella pneumoniae (CRE)      | critical | KPC-producers                |
| Abaum    | Acinetobacter baumannii          | critical | OXA-23/24/58 carbapenemases  |
| Paer     | Pseudomonas aeruginosa           | critical | mexAB-oprM efflux            |
| VRE      | Enterococcus faecium (VRE)       | high     | vanA/vanB                    |
| NGono    | Neisseria gonorrhoeae            | high     | penA, mosaic-23S rRNA        |

Defined in `workspace/api/server.py` (PATHOGENS list) and
`src/inference/generate.py`.

---

## 2. System overview

### 2.1 Layer diagram

```
                      ┌────────────────────────────────────┐
                      │       HF Space / Demo (Gradio)     │
                      │     space/app.py + space/README    │
                      └───────────────┬────────────────────┘
                                      │ HTTPS
                      ┌───────────────▼────────────────────┐
                      │       Workspace API (FastAPI)      │
                      │     workspace/api/server.py        │
                      │     + hardening.py + workbench.py  │
                      └───────────────┬────────────────────┘
                                      │ python call
                      ┌───────────────▼────────────────────┐
                      │   Inference (LysosGenerator)       │
                      │   src/inference/generate.py        │
                      │   + retrieval.py + RAG             │
                      └───────────────┬────────────────────┘
                                      │ HF Hub model load
                      ┌───────────────▼────────────────────┐
                      │   Trained model: rahul24raj/lysos-rl
                      │   = Gemma 4 31B + S1 + S2 + S2.5 + S3 LoRA
                      └────────────────────────────────────┘

                      ┌─────────────  TRAINING  ───────────┐
                      │   Stage 1: TxGemma-4 SFT           │
                      │     src/training/stage1_txgemma4.py│
                      │   Stage 2: AMR SFT (pro-v12)       │
                      │     src/training/stage2_amr_sft.py │
                      │   Stage 2.5: DPO hard-negatives    │
                      │     src/training/stage2_5_dpo.py   │
                      │   Stage 3: GRPO RL                 │
                      │     src/training/stage3_rl_grpo.py │
                      └────────────────┬───────────────────┘
                                       │ logs to wandb
                      ┌────────────────▼───────────────────┐
                      │   wandb project: lysos             │
                      │   panels: train/, reward/, cost/   │
                      └────────────────────────────────────┘
```

### 2.2 Core concepts

| Concept          | Definition                                                       |
|------------------|------------------------------------------------------------------|
| **Stage 1**      | Chemistry foundation SFT on TDC tasks (151K rows)               |
| **Stage 2**      | AMR specialization SFT on Pro-v12 (~380K rows)                  |
| **Stage 2.5**    | DPO alignment on hard-negative Pareto-trap pairs (~10K)         |
| **Stage 3**      | GRPO RL with verifiable 12-component reward stack               |
| **CompositeReward** | Weighted sum of 12 reward components, sum=1.0                |
| **Hard negative** | Candidate that is high on one reward axis but low on an anti-correlated one (Pareto trap) |
| **Workbench**    | Multi-agent state machine with 25 tools (4 first-class + 9 sub-agents) |
| **Gemini Embedding 2** | `gemini-embedding-2` API model, 3072-d Matryoshka, 8192-token input window, multimodal-ready. Used by `embedding_novelty` reward + `retrieval` + `dedup`. NOT the older `gemini-embedding-001`. |
| **Enrichment template** | Shared text template (`src/embeddings/enrichment.py`) used by all 5 embedding call sites — produces `Drug: <name> (source). Type: small molecule/peptide. Stereochemistry. SMILES. InChIKey. Physicochemical (MW, logP, TPSA, QED). Lipinski (HBA/HBD/rot/rings/heavy)`. ~86 tokens/row average. |
| **Pre-computed embeddings** | `artifacts/embeddings/known-antibiotics-gemini-2.parquet` — 30,743 rows × 3072-d, L2-normalized, computed once. Reward stack reads from disk, no live API calls during training. 362.7 MB. |

---

## 3. Data layer

### 3.1 Stage 1 corpus — `rahul24raj/lysos-tdc-stage1`

Therapeutics Data Commons instruction-tuning data. Replicates Google's
TxGemma recipe on a Gemma 4 base.

- **Rows**: 151,000
- **Tasks**: 22 ADMET prediction tasks (CYP3A4 inhibition, BBB
  permeability, HIA, hERG, Caco-2 permeability, AMES toxicity,
  hepatotoxicity, etc).
- **Format**: chat with `<start_of_turn>user/model` markers.
- **Built by**: `scripts/build_tdc_examples.py`

### 3.2 Stage 2 corpus — `rahul24raj/lysos-amr-stage2-pro-v12`

The AMR specialization corpus. 12 versions, v12 is current default.

- **Rows**: 380,000 train / 29,000 valid / 50 test (held-out named-drug)
- **Sources**: ChEMBL antibiotic subset, DBAASP/APD3/DRAMP antimicrobial
  peptides, CARD resistance gene catalog, NPAtlas natural products,
  DrugCentral drug index, manually-authored teacher distillation.
- **Teacher distillation**: 78,150 traces across 7 layers (chem, systems,
  architecture, raw-data, edge/clinical, targeted, eval-aligned). Authored
  by hand, no API spend (avoids policy filter on CW/CDC names — uses
  abstracted category tokens).
- **Quality weighting**: top-quartile rows oversampled 2×, bottom-quartile
  downsampled 0.5× (pro-v11 → pro-v12).
- **Counterfactual pairs**: 1,437 MMP-mined activity cliffs added in v12.
- **27 task types in train**, 8 categories of held-out eval slices.
- **Built by**: `scripts/build_stage2_pro_v8.py` … `pro_v12.py` +
  `clean_chemistry_corpus.py` + `clean_pro_v4_to_v5.py`.

Version lineage:
```
pro-v3   (32 agentic gaps + safety/refusal/tool-arg/held-out-eval)
pro-v4   + tool-call-results + long-form-traces + pk-panel + decoys + activity-cliffs + smiles-augmentation + pathogen-primer + canonical-chemistry
pro-v5   cleaned (list→string, placeholder SMILES replaced, dedup capped at 12)
pro-v6   + 3,000 chem teacher traces
pro-v7   + 5K chem + 6.5K systems teacher
pro-v8   + 43.5K teacher across 5 layers
pro-v9   + 60.65K teacher across 6 layers
pro-v10  + 78.15K teacher across 7 layers
pro-v11  pro-v10 quality-weighted (top-quartile 2× over, bottom 0.5× under)
pro-v12  pro-v11 + 1,437 counterfactual pairs + 8 time-aware test rows  ← DEFAULT
```

### 3.3 Stage 3 RL prompts — `rahul24raj/lysos-rl-prompts-v3`

Prompt-only dataset for GRPO (RL generates responses).

- **Rows**: 12,000 train + 600 valid
- **Enrichment**: each prompt carries a Workbench-brief (resistome target +
  structural target + first-line therapy + lit snippet + constraint
  profile + novelty gate).
- **Built by**: `scripts/build_workbench_briefs.py`

### 3.4 Stage 2.5 hard-negative pairs — `rahul24raj/lysos-hard-negatives-v1` (pending mine on VM)

DPO pair dataset of (chosen, rejected) Pareto traps.

- **Rows**: ~10K target pairs
- **Format**: parquet with `prompt`, `chosen`, `rejected`,
  `chosen_smiles`, `rejected_smiles`, `chosen_scores`, `rejected_scores`,
  `chosen_composite`, `rejected_composite`, `hard_axis_x`, `hard_axis_y`,
  `gap_x`, `gap_y`.
- **Hard axes**: 10 anti-correlated reward-component pairs (see §4.4).
- **Mined by**: `scripts/mine_hard_negatives.py` (after Stage 2 SFT lands).

### 3.5 Reward calibration caches

Pre-computed score caches to make reward calls fast at training time:

| Cache                                              | Built by                              | Use                       |
|----------------------------------------------------|---------------------------------------|---------------------------|
| `data/processed/synth_calibration_cache.parquet`   | `scripts/calibrate_synth_cache.py`    | SAscore baseline          |
| `data/processed/aizynth_calibration_cache.parquet` | `scripts/run_aizynth_priority_sweep.py` | retrosynthesis routes    |
| `data/processed/boltz2_poses_cache.parquet`        | `scripts/calibrate_boltz_proxy.py`    | Boltz-2 ipTM (proxy until real Boltz-2) |
| `data/processed/known-antibiotics-canonical.parquet` | `scripts/clean_chemistry_corpus.py`  | novelty Tanimoto reference|
| `data/processed/known-antibiotics.smiles`          | `scripts/build_known_antibiotics_index.py` | embedding_novelty reference set |

### 3.6 Time-aware split

50 rows held out where `disclosure_year >= 2023` to test that the model
isn't memorizing recent data.
Built by `scripts/build_time_aware_split.py`.

---

## 4. Reward stack

### 4.1 The 12 components (sum = 1.0)

Defined in `configs/stage3_rl_grpo.yaml` and `src/eval/rewards/`.

| Component             | Weight | Module                                          | What it scores |
|-----------------------|--------|-------------------------------------------------|----------------|
| validity              | 0.05   | `src.eval.rewards.validity:smiles_valid`        | RDKit parses SMILES |
| structural_alerts     | 0.05   | `src.eval.rewards.structural_alerts:structural_alerts_score` | Brenk + PAINS reactive groups |
| predicted_mic         | 0.20   | `src.eval.rewards.activity:predict_mic`         | xgboost MIC predictor (or heuristic fallback)|
| drug_likeness_qed     | 0.10   | `src.eval.rewards.drug_likeness:qed_score`      | RDKit QED |
| synthesizability      | 0.10   | `src.eval.rewards.synth:sa_score`               | SAscore (low is hard, inverted) + AiZynth route depth |
| hemolysis_safety      | 0.10   | `src.eval.rewards.safety:hemolysis_inverse`     | xgboost on 8K hemolysis dataset |
| novelty               | 0.08   | `src.eval.rewards.novelty:tanimoto_distance_to_known` | 1 - max Tanimoto on ECFP4 |
| embedding_novelty     | 0.07   | `src.eval.rewards.embedding_novelty:embedding_novelty` | 1 - cosine in **gemini-embedding-2** (3072-d, 8K input, multimodal). Reads pre-computed `artifacts/embeddings/known-antibiotics-gemini-2.parquet` for 30K refs. Query side enriched via `build_query_text()` (RDKit-derived MW/logP/TPSA/QED/Lipinski) so doc + query share feature space. |
| boltz2_pose_conf      | 0.10   | `src.eval.rewards.boltz2_pose:pose_confidence`  | Boltz-2 ipTM (cached) |
| spectrum_breadth      | 0.05   | `src.eval.rewards.spectrum:multi_pathogen_breadth` | mean MIC across 8 pathogens |
| resistance_robustness | 0.05   | `src.eval.rewards.resistance:robustness_score`  | retained activity under known escape mutations |
| pareto_entry          | 0.05   | `src.eval.rewards.pareto:pareto_entry_bonus`    | bonus for joint Pareto-front membership |

### 4.2 Composition

`CompositeReward` in `src/eval/rewards/__init__.py`:

```python
combined[i] = sum(weight_c * per_component[c][i] for c in components)
```

Per-component scores returned alongside combined for wandb logging.

### 4.3 No-fallback policy (committed 2026-05-04)

Earlier versions had `fail-open` fallbacks that returned neutral 0.5
when an external dep was missing (Gemini API key, Boltz-2 cache).
This silently degraded the composite reward by ~7% with no signal.

**Current policy**:
- All reward components either run at full capability OR are explicitly
  disabled (weight=0 in config).
- No silent degradation. `embedding_novelty` raises `RuntimeError` if
  GEMINI_API_KEY is missing. `boltz2_pose_conf` raises if cache empty
  with strict=True (default).
- VM startup script verifies all required keys before training.

### 4.4 Hard axis catalog (Stage 2.5 DPO)

Anti-correlated reward-component pairs that the policy will commonly
fall into without hard-negative pre-alignment. From
`docs/hard_negative_mining.md` and `scripts/mine_hard_negatives.py`:

```
predicted_mic     × hemolysis_safety   — membrane disruptor trap
predicted_mic     × synthesizability   — active in silico, impossible to make
novelty           × validity           — new scaffold but invalid valence
novelty           × drug_likeness_qed  — novel but breaks rule-of-5
boltz2_pose_conf  × predicted_mic      — docks but doesn't bind
spectrum_breadth  × resistance_robust  — broad-spectrum but fragile
structural_alerts × novelty            — PAINS reactive group
hemolysis_safety  × predicted_mic      — safe but inactive
drug_likeness_qed × embedding_novelty  — looks druglike via mimicry
validity          × predicted_mic      — valid junk SMILES
```

### 4.5 Reward fn safety wrapper (Stage 3)

Wrapped in `stage3_rl_grpo.py:reward_callable`:
- Per-batch try/except — composite crash → zero reward, training continues
- NaN/Inf scrubbed before reaching the policy gradient
- Length-mismatch defended (pad/truncate)
- Counters logged: `reward/crashes_total`, `reward/non_finite_zeroed`
- One step of bad reward < killing a 10h GRPO run

---

## 5. Training pipeline

### 5.1 Stage 1 — TxGemma-4

**Goal**: replicate Google's TxGemma instruction tuning on Gemma 4 base.

- Model: `google/gemma-4-31b-it` (ungated, 8M+ HF downloads)
- Data: TDC corpus (151K rows, 22 ADMET tasks)
- LoRA: r=64, alpha=128, target_modules q/k/v/o_proj
- Hardware: Large 8× MI300X (DeepSpeed ZeRO-3)
- Time: ~6 hours
- Output: `rahul24raj/txgemma-4-31b`
- Config: `configs/stage1_txgemma4.yaml`
- Entry: `python -m src.training.stage1_txgemma4`

### 5.2 Stage 2 — AMR specialization SFT

**Goal**: layer AMR domain knowledge on top of Stage 1.

- Model: load `rahul24raj/txgemma-4-31b` adapter, merge into Gemma 4 base
- Data: `lysos-amr-stage2-pro-v12` (380K train)
- LoRA: r=64, alpha=128, fresh adapter on merged base
- Hardware: Small 1× MI300X
- Time: ~12 hours
- Output: `rahul24raj/lysos-base`
- Config: `configs/stage2_amr_sft.yaml`
- Entry: `python -m src.training.stage2_amr_sft`

### 5.3 Stage 2.5 — DPO hard-negative alignment

**Goal**: pre-align the policy along anti-correlated reward axes before GRPO.

- Model: load `rahul24raj/lysos-base` adapter, merge into Gemma 4
- Data: `lysos-hard-negatives-v1` (~10K DPO pairs from `mine_hard_negatives.py`)
- Hyperparams: beta=0.1, r=32 LoRA, 1 epoch, lr=5e-7
- Hardware: Small 1× MI300X
- Time: ~30-60 minutes
- Output: `rahul24raj/lysos-base-dpo`
- Config: `configs/stage2_5_dpo.yaml`
- Entry: `python -m src.training.stage2_5_dpo`
- Cost-saving: $21 of DPO ≈ saves $50-100 of GRPO that would otherwise
  spend time fumbling toward Pareto balance.

### 5.4 Stage 3 — GRPO RL

**Goal**: refine policy on the verifiable 12-component reward stack.

- Model: load `rahul24raj/lysos-base-dpo` adapter, merge into Gemma 4
- Reference: same model frozen (KL constraint, beta=0.04)
- Data: `lysos-rl-prompts-v3` (12K prompts)
- Reward: 12-component CompositeReward (weights sum=1.0)
- Hyperparams: G=8 generations per prompt, T=1.0, top_p=0.95
- Hardware: Small 1× MI300X (192 GB RAM is the moat)
- Time: ~10-15 hours
- Output: `rahul24raj/lysos-rl`
- Config: `configs/stage3_rl_grpo.yaml`
- Entry: `python -m src.training.stage3_rl_grpo`

### 5.5 Shared infrastructure

| File                                     | Purpose |
|------------------------------------------|---------|
| `src/training/sft_runner.py`             | Shared SFT runner used by Stage 1 + 2 |
| `src/training/cost_callback.py`          | Live wandb cost emission + budget hard-stop |
| `src/training/eval_callback.py`          | Mid-training eval (50 candidates × 12 reward) |
| `src/training/hub_push.py`               | 4-retry hub push with read-after-write verify |
| `scripts/checkpoint_resilience.py`       | 3-retry stage runner with HF Hub backup recovery |
| `scripts/run_training_pipeline.sh`       | One-command orchestrator (Stages 1 → 2 → 2.5 → 3) |
| `scripts/preflight_check.py`             | 7-section validation gate |
| `scripts/verify_keys.py`                 | Live API check for HF + Gemini + WANDB |
| `scripts/smoke_pipeline_e2e.py`          | CPU smoke (tiny-gpt2) running all 3 stages in 22s |

### 5.6 Context-length budget

Gemma 4 31B native `max_position_embeddings = 262,144`. We use a fraction
of it during fine-tuning to keep memory + wall-time tractable on the
target hardware:

| Stage   | Field                  | Old   | Current  | Why                              |
|---------|------------------------|-------|----------|----------------------------------|
| 1       | `max_seq_length`       | 4096  | **8192** | TDC reasoning chains fit fully (some teacher traces hit 6-7K) |
| 2       | `max_seq_length`       | 4096  | **8192** | pro-v12 named-drug elite CoT rows + long teacher distillation traces no longer truncated |
| 2.5 DPO | `max_length`           | 2048  | **4096** | DPO chosen+rejected pairs occasionally exceed 2K combined |
| 2.5 DPO | `max_prompt_length`    | 768   | **1024** | matches our richer prompt enrichment |
| 3 GRPO  | `max_prompt_length`    | 1024  | **2048** | RL prompts include resistome briefing + first-line context + lit snippet |
| 3 GRPO  | `max_completion_length`| 512   | **1024** | longer reasoning traces during generation |

Stage 1 (8× MI300X ZeRO-3 with optimizer offload to CPU): 8192 fits easily.
Stage 2 / 2.5 / 3 (1× MI300X with gradient_checkpointing): 8192 / 4096 fits
within VRAM budget; ~10-15% throughput cost vs 4096 due to attention being
quadratic up to the sliding window (1024).

### 5.7 TRL version compatibility

The training scripts handle TRL 0.x and 1.x via signature-introspection
filters. Built-in shims:
- `SFTConfig.max_seq_length` (0.x) → `max_length` (1.x)
- `DataCollatorForCompletionOnlyLM` (0.x) → `SFTConfig(completion_only_loss=True)` (1.x)
- `tokenizer=` (0.x) → `processing_class=` (1.x)
- `GRPOTrainer.ref_model` (0.x) → built from `args.beta` (1.x)

If a kwarg is dropped by the running TRL, training logs a warning
listing what was filtered.

### 5.8 Gemini Pro auxiliary scripts (not on the GPU pipeline)

Three Gemini 2.5 Pro scripts that run before/after training on the laptop
or VM. Total ~$8.75 of the $25 budget. All three capture the model's
reasoning trace via `thinkingConfig.includeThoughts=true` — we pay for
thinking tokens regardless, so we always retrieve them.

| Script                                          | When           | Cost  | What it produces |
|-------------------------------------------------|----------------|-------|------------------|
| `scripts/enrich_named_drugs_with_gemini.py`     | pre-training   | ~$2.50 | `artifacts/embeddings/named-drugs-gemini-enrichment.parquet` — mechanism / spectrum / indications / resistance_escape JSON + **full reasoning trace** for **218 top named antibiotics** (Wave 1 core 107 + Wave 2 broader-class ~80 + Wave 3 combos/comparators ~31). Powers `src.embeddings.pharma_lookup` for Stage-2 SFT prompt enrichment, RAG re-ranking, and gold-standard pharmacology chain-of-thought. ~135K tokens of reasoning trace stored. |
| `scripts/run_gemini_comparator.py`              | post-Stage-3   | ~$5.00 | `reports/gemini_25_pro_baseline.jsonl` — Gemini 2.5 Pro zero-shot responses + thinking on 200-prompt eval set. Direct head-to-head with Lysos-RL, plus reasoning-vs-reasoning analysis for the methods paper. |
| `scripts/llm_as_judge_eval.py`                  | post-Stage-3   | ~$1.25 | `reports/lysos_rl_judge_scores.jsonl` — qualitative scores (reasoning_quality / citation_grounding / mechanism_plausibility / safety_awareness, each 0-10) + `judge_thinking` rationale chain for 50 held-out responses. |

#### 5.8.1 gemini-2.5-pro thinking-budget gotcha

`gemini-2.5-pro` is a *thinking* model: `maxOutputTokens` is the combined
budget for thinking + visible output. For pharmacology prompts the
thinking phase consumes ~700-1500 tokens (judge / comparator: 1500-2500).
Setting `maxOutputTokens=600` results in `finishReason=MAX_TOKENS`, empty
`content.parts`, and `thoughtsTokenCount` ~= the budget. All three
scripts now default to **8192**. Cost = (input × $1.25/M) + ((output +
thinking) × $10/M); thinking is billed at output rates whether or not
you `includeThoughts=true`, so always capture it.

#### 5.8.2 thinking-trace consumption

Every row in the enrichment parquet has a `thinking` column (~2000 chars
on average) with the model's step-by-step pharmacology reasoning. Access
patterns:

```python
from src.embeddings import get_pharma_thinking, format_pharma_card
trace = get_pharma_thinking("amoxicillin")        # ~2000 chars CoT
card = lookup_pharma("amoxicillin")
print(format_pharma_card(card))                   # one-line briefing
```

Downstream consumers:
- **Stage-2 SFT data builders**: optionally append `thinking` as
  reasoning trace before the JSON answer for chain-of-thought training
- **RAG retrieval rerank**: when `enrich_pharma=True`, top-k hits get
  mechanism/spectrum/resistance_escape attached
- **Comparator analysis**: head-to-head reasoning chains (Lysos vs
  Gemini Pro thinking) become the qualitative section of the paper

#### 5.8.3 retry hardening

All three scripts: `timeout=300s`, `max_retries=5`, exponential backoff
(8s × attempt for 429/5xx, 5s × attempt for network). Incremental
parquet checkpoints every 20 rows + atomic `.tmp → rename` so a kill
or crash never corrupts in-flight data.

### 5.9 Tokenizer alignment guard

When Stage 2/2.5/3 loads from a previously trained adapter,
`sft_runner.py` reads the prior tokenizer and asserts vocab_size matches
the base model. Drift here silently corrupts embeddings → assertion
forces an explicit fix before training.

---

## 6. Inference layer

### 6.1 LysosGenerator

`src/inference/generate.py` — the canonical inference entry point.

- Loads model + adapter once (cached at module level)
- `design(target, n, modality, ...)` → list of Candidate objects
- `Candidate.smiles | sequence | raw | scores | combined`
- Uses transformers `.generate()` with diverse temperatures
- `score=True` runs the full 12-component reward on the output

### 6.2 Retrieval (RAG)

`src/inference/retrieval.py` — Gemini Embedding 2 over known antibiotics.

- Embeds the index once at startup (~$0.05 one-time)
- Per-query embed at design time
- Returns top-k SMILES + names
- `--enable_rag --rag_k 3` injects 3 reference antibiotics as
  in-context examples to the design prompt

### 6.3 Best-of-N inference

`scripts/best_of_n_inference.py` — generate N=20 candidates, score all,
return top-K by composite. Used by the workbench for "more aggressive"
designs.

---

## 7. Workspace API

### 7.1 Endpoints

`workspace/api/server.py` + `workspace/api/workbench.py`:

```
GET  /api/health           liveness
GET  /api/ready            distinguishes loaded model from running server
GET  /api/pathogens        list of 8 priority pathogens
POST /api/design           batch generate + score
POST /api/design/stream    SSE-stream candidates
POST /api/similar          top-k neighbors via Gemini Embedding 2
GET  /api/score            score arbitrary SMILES manually
POST /workbench/sessions   create agentic session
GET  /workbench/sessions/{sid}  session state
POST /workbench/sessions/{sid}/start  start the multi-agent loop
POST /workbench/sessions/{sid}/intervene  inject constraint or directive
GET  /workbench/sessions/{sid}/events  SSE event stream
GET  /workbench/sessions/{sid}/notebook  export to .ipynb
GET  /workbench/skills     list configured agent skills
GET  /workbench/tools/{name}  tool metadata
GET  /workbench/molecule/3d  3D viewer payload
POST /workbench/molecule/edit  scaffold-hop / fragment-replace
GET  /workbench/pathogen/{code}/pocket  PDB pocket coords
GET  /workbench/pathogens  workbench-formatted pathogen list
```

### 7.2 Hardening (`workspace/api/hardening.py`)

- **Rate limiting**: per-(IP, route) token bucket. Design 5/min,
  score+similar 30/min, default 120/min. No `slowapi` dep.
- **SMILES sanitizer**: rejects HTML/JS injection, length, char-class.
  Wired into `/api/score` + `/api/similar`.
- **Cold-start lock**: `asyncio.Lock` around `_get_generator()` so
  concurrent first hits don't trigger two parallel 60GB model loads.
- **Design timeout**: 5 min default (`LYSOS_DESIGN_TIMEOUT_S`); raises 504.
- **LRU cache**: `/api/score` deterministic by (smiles, target), 256-entry.
- **Structured JSON access logs** with request_id + elapsed_ms.
- **`X-Request-ID` + `X-Process-Time-Ms`** response headers.
- **Body-size cap**: 1 MB default (`LYSOS_MAX_BODY_BYTES`).
- **CORS**: tight allow-list (huggingface.co, *.hf.space, localhost dev
  ports) — `LYSOS_CORS_ALLOWED_ORIGINS` override.
- **Sanitized error JSON** `{error, request_id}` (no traceback leak).

### 7.3 Tests

`workspace/tests/test_server_hardening.py` — 9 tests covering injection,
unknown pathogen, ready/health split, request-id headers, rate-limit,
cache idempotence, sanitizer unit.

---

## 8. HF Space + demo

### 8.1 Frontend

`space/app.py` — Gradio UI:
- 8-pathogen dropdown
- Constraint profile selector (PK preset, oral, IV, topical)
- "Design" button calls Lysos workspace API
- Renders top-K candidates with per-component score bars
- 3D viewer for the top candidate via py3Dmol

`space/README.md` — Space frontmatter (sdk: gradio, license: cc-by-4.0).
`space/requirements.txt` — minimal Space deps.

### 8.2 React frontend (advanced)

`workspace/web/` — React + Vite + Tailwind frontend for the workbench.
Built with `cd workspace/web && npm install && npm run build`. Output
served by `workspace/api/server.py` from `web/dist/`.

---

## 9. Monitoring + dashboards

### 9.1 wandb project — `rahulrajpurohit005-lysos/lysos`

URL: https://wandb.ai/rahulrajpurohit005-lysos/lysos

Created by `scripts/setup_wandb_dashboard.py` with `define_metric()`
calls for every metric our training emits, so wandb auto-organizes
panels into groups (train/, eval/, reward/, cost/, system/, grpo/).

Sections in the custom workspace view:
1. **Training core**: loss, learning_rate, grad_norm, eval/loss
2. **GRPO (Stage 3)**: reward, kl, policy_loss, advantage_mean
3. **Reward decomposition**: 12 components + bar plot of weighted contributions
4. **Mid-training eval**: avg_composite, n_valid (50 candidates), avg_qed, avg_novelty
5. **Hardware (MI300X)**: GPU util, GPU mem, system RAM, disk
6. **Cost protection**: hours_elapsed, $/hour, projected_total, budget_pct_used

### 9.2 Cost panel emitter

`src/training/cost_callback.py`:
- Logs `cost/hours_elapsed`, `cost/per_hour`, `cost/spent_usd`,
  `cost/projected_total_usd`, `cost/budget_pct_used` every step.
- **Hard-stops training** if projected total exceeds budget × 1.05.
  Tunable: `LYSOS_BUDGET_USD`, `LYSOS_HARD_STOP_ON_BUDGET`.
- GPU class set per-stage by `run_training_pipeline.sh`:
  `LYSOS_GPU_CLASS=mi300x_large_8gpu` for Stage 1
  `LYSOS_GPU_CLASS=mi300x_small_1gpu` for Stages 2, 2.5, 3

---

## 10. Reliability + ops protection

### 10.1 The chain of safety nets

```
preflight_check.py  ← gate 1: keys + deps + datasets + reward stack OK
        │
        ▼
checkpoint_resilience.py  ← gate 2: 3-retry per stage with HF Hub recovery
        │
        ▼
cost_callback (in-trainer)  ← gate 3: live cost panel + budget hard-stop
        │
        ▼
hub_push retry (post-stage)  ← gate 4: 4-retry + read-after-write verify
        │
        ▼
trained model on HF Hub (private)
```

### 10.2 Checkpoint resilience

`scripts/checkpoint_resilience.py`:
- Auto-detects last local checkpoint.
- Verifies file integrity (required files exist).
- Falls back to HF Hub pull if local corrupted (`--allow_hub_recovery`).
- 3-retry on crash with exponential backoff.

### 10.3 Hub push retry

`src/training/hub_push.py`:
- 4-retry exponential-backoff push (30s, 60s, 120s, 240s).
- Read-after-write verify via `HfApi.model_info`.
- On exhaustion: log local checkpoint dir + manual recovery command.

### 10.4 Reward callback safety (Stage 3)

`src/training/stage3_rl_grpo.py:reward_callable`:
- Per-batch try/except — composite crash → zero reward, training continues.
- NaN/Inf scrubbed.
- Length-mismatch defended.
- Counters: `reward/crashes_total`, `reward/non_finite_zeroed`.

### 10.5 Disk monitor

`scripts/disk_monitor.py` — checks `df` every N steps, alerts to
wandb if free space < 10 GB.

---

## 11. Key + secrets management

### 11.1 Required keys

| Key                | Storage              | Verifier method |
|--------------------|----------------------|-----------------|
| `HF_TOKEN`         | `~/.cache/huggingface/token` (chmod 600) | `huggingface_hub.whoami()` via API |
| `GEMINI_API_KEY`   | `.env` (gitignored)  | `embedContent` 1-token round-trip |
| `WANDB_API_KEY`    | `~/.netrc` (chmod 600) | GraphQL `{viewer{username entity}}` |
| `ANTHROPIC_API_KEY`| shell env            | `messages` POST round-trip |
| `OPENAI_API_KEY`   | shell env (optional, for comparator) | `/v1/models` GET |

### 11.2 Verifier — `scripts/verify_keys.py`

Single-source pre-flight check:
- Loads `.env` if present.
- Falls back to `~/.cache/huggingface/token` (HF) and `~/.netrc` (wandb).
- Live API call per key (no spoofing — actually exercises the credential).
- Exit 0 = all green, 1 = required missing, 2 = recommended missing.

Wired into:
- `scripts/preflight_check.py` (auth section)
- `scripts/vm_bootstrap.sh` (step 3.5, before 60 GB Gemma download)
- `scripts/run_training_pipeline.sh` (preflight gate)

### 11.3 No-fallback policy

When a credential or cache is missing, components RAISE rather than
silently degrade. See §4.3.

### 11.4 .gitignore

```
.env
.env.local
.env.*.local
.venv-cli/
wandb/
__pycache__/
*.py[cod]
```

---

## 12. Test coverage

| Suite                                         | Count | What it covers |
|-----------------------------------------------|-------|----------------|
| `workspace/tests/test_server_hardening.py`    | 9     | Rate-limit, sanitizer, request-id, cache, ready/health |
| `scripts/tests/test_hard_negative_mine.py`    | 4     | Pareto-trap detection, dedup, no-false-positives |
| `scripts/test_loss_masking.py`                | 4     | Prompt vs response token masking on real templates |
| `scripts/smoke_pipeline_e2e.py`               | end-to-end | All 3 training stages run on tiny-gpt2 in 22s |

CI invocation:
```bash
.venv-cli/bin/python -m pytest workspace/tests/ scripts/tests/ -v
.venv-cli/bin/python scripts/test_loss_masking.py
.venv-cli/bin/python scripts/smoke_pipeline_e2e.py
```

---

## 13. Deployment

### 13.1 VM bootstrap

`scripts/vm_bootstrap.sh` runs end-to-end on a fresh AMD MI300X VM:

```
1. Verify ROCm + MI300X visible
2. Clone / update repo at ~/lysos
3. Install Python deps (pyproject.toml + sentence-transformers + xgboost + peft + trl + accelerate + wandb + bitsandbytes)
3.5. Verify keys (HF + Gemini + WANDB) — fail-fast before downloading 60 GB
4. Pre-warm HF cache (Gemma 4 31B + EmbeddingGemma)
5. Run smoke tests (verify_loaders + smoke_test_rocm)
6. Pull live HF datasets (pro-v12 + rl-prompts-v3 + tdc-stage1)
6.5. Verify reward caches (synth + boltz proxy + aizynth)
7. Print "ready to train" with command
```

### 13.2 Training pipeline

```bash
ssh mi300x-vm
cd ~/lysos
bash scripts/run_training_pipeline.sh
```

Runs Stages 1 → 2 → 2.5 (mine + DPO) → 3 sequentially, with preflight,
checkpoint resilience, cost callback, and post-pipeline eval.

### 13.3 Recovery from VM crash

If the VM reboots mid-training:
1. SSH back in.
2. `bash scripts/run_training_pipeline.sh stage<N>` — N is the stage you
   were on. checkpoint_resilience auto-detects the last good checkpoint.
3. If local checkpoint corrupted: pass `--allow_hub_recovery` to pull
   the last pushed checkpoint from HF Hub.

### 13.4 HF Space deployment

```bash
huggingface-cli upload rahul24raj/lysos-workbench space/ . --repo-type=space
```

The Space is built as a Gradio app from `space/app.py`. Workspace API
is colocated in the Space container. Pro tier provides ZeroGPU at no
extra cost.

---

## 14. Reproducibility

### 14.1 Single source of truth

| Artefact                | File                              |
|-------------------------|-----------------------------------|
| Methods paper           | `docs/methods_paper.md` (v0)      |
| Datasheet (Gebru-style) | `docs/datasheet.md`               |
| Risk register           | `docs/risk_register.md`           |
| Reproduction guide      | `docs/REPRODUCE.md`               |
| Bias audit              | `docs/bias_audit.md`              |
| Comparator analysis     | `docs/competitor_analysis.md`     |
| API key matrix          | `docs/API_KEYS_AND_ACCESS.md`     |
| Audit + work plan       | `docs/AUDIT_AND_WORK_PLAN.md`     |
| Hard-negative mining    | `docs/hard_negative_mining.md`    |
| Architecture            | `docs/architecture/` (13 .md files) |
| **THIS doc**            | `docs/TECH_DOC.md`                |

### 14.2 Architecture canonicals

`docs/architecture/`:
- `agents.md` — 4 first-class + 9 sub-agents
- `tools.md` — 25-tool registry
- `ledger.md` — session state
- `state-machine.md` — workbench loop
- `handoff-protocol.md` — agent → agent
- `error-escalation.md` — error → escalation tree
- `api-contracts.md` — REST + SSE
- `pipeline.md` — training pipeline
- `stage-gates.md` — preflight gates
- `intervention.md` — mid-loop user injection
- `branch-merge.md` — alt-design exploration
- `subagent-dispatch.md` — agent routing
- `confidence.md` — confidence calibration
- `sprint-workflow.md` — dev workflow

---

## 15. File map

### 15.1 Repo top-level

```
lysos/
├── pyproject.toml          # editable install, deps
├── README.md
├── LICENSE                  # MIT for code, CC-BY-4.0 for data
├── .gitignore               # .env, .venv-cli, wandb, __pycache__
├── .env                     # GEMINI_API_KEY (gitignored)
├── configs/                 # YAML configs for each stage
├── data/                    # raw + processed corpora
├── docs/                    # methods, datasheet, architecture, this file
├── reports/                 # bench + audit JSON outputs
├── scripts/                 # build / mine / train / verify
├── space/                   # HF Space (Gradio app + frontmatter)
├── src/                     # the package itself
├── workspace/               # FastAPI + React workbench
└── tests/                   # cross-cutting tests (most live alongside source)
```

### 15.2 `src/` layout

```
src/
├── __init__.py
├── config.py                # YAML config loader + CLI overrides
├── embeddings/              # Gemini Embedding 2 wrapper
│   ├── __init__.py
│   └── gemini.py
├── eval/                    # eval suite + reward stack
│   ├── rewards/
│   │   ├── __init__.py             # CompositeReward + extract_smiles
│   │   ├── activity.py             # predict_mic
│   │   ├── boltz2_pose.py          # cached Boltz-2 ipTM
│   │   ├── drug_likeness.py        # qed_score
│   │   ├── embedding_novelty.py    # Gemini cosine
│   │   ├── novelty.py              # Tanimoto
│   │   ├── pareto.py               # joint front bonus
│   │   ├── resistance.py           # robustness under mutations
│   │   ├── safety.py               # hemolysis_inverse
│   │   ├── spectrum.py             # multi-pathogen breadth
│   │   ├── structural_alerts.py    # PAINS/Brenk
│   │   ├── synth.py                # SAscore + AiZynth depth
│   │   └── validity.py             # smiles_valid
│   └── ...
├── inference/               # serving
│   ├── generate.py                 # LysosGenerator
│   └── retrieval.py                # RAG via Gemini Embedding 2
└── training/
    ├── __init__.py
    ├── sft_runner.py               # shared Stage 1+2 SFT
    ├── stage1_txgemma4.py
    ├── stage2_amr_sft.py
    ├── stage2_5_dpo.py             # DPO hard-negative alignment
    ├── stage3_rl_grpo.py           # GRPO RL
    ├── cost_callback.py            # wandb cost panel + budget hard-stop
    ├── eval_callback.py            # mid-training eval
    └── hub_push.py                 # 4-retry hub push with verify
```

### 15.3 `scripts/` (selected, alphabetical)

```
scripts/
├── audit_*.py               # 8 corpus auditors
├── build_*.py               # 16 corpus builders (TDC, AMR, peptide, decoys, MMP, etc)
├── calibrate_*.py           # synth + boltz proxy caches
├── checkpoint_resilience.py # 3-retry stage runner
├── clean_*.py               # corpus cleaners (chemistry canon, pro-v5 fixes)
├── cost_tracker.py          # offline cost tally from logs
├── dedup_*.py               # 2 dedup scripts (Tanimoto + Gemini embedding)
├── deploy_to_hf_space.py
├── disk_monitor.py
├── mine_hard_negatives.py   # ★ Stage 2.5 pair miner
├── preflight_check.py       # ★ pre-train validation gate
├── run_aizynth_priority_sweep.py
├── run_training_pipeline.sh # ★ pipeline orchestrator
├── score_data_quality.py    # quality-weighted resampling
├── setup_wandb_dashboard.py # dashboard + metric schema
├── smoke_pipeline_e2e.py    # ★ CPU end-to-end smoke
├── tests/
│   └── test_hard_negative_mine.py
├── test_loss_masking.py
├── verify_keys.py           # ★ live API key verifier
└── vm_bootstrap.sh          # ★ AMD VM zero-to-train bootstrap
```

★ = paths most likely to need attention during ops.

### 15.4 `workspace/` layout

```
workspace/
├── requirements-api.txt
├── api/
│   ├── __init__.py
│   ├── server.py                  # legacy /api/* + workbench mount + static
│   ├── workbench.py               # /workbench/* (sessions, tools, SSE)
│   ├── notebook.py                # session → ipynb export
│   ├── hardening.py               # ★ rate limit + sanitizer + lock + headers
│   └── db/                        # postgres persistence
├── agents/
│   ├── graph.py                   # multi-agent state machine
│   ├── llm.py                     # LLM router
│   ├── prompts.py
│   └── state.py
├── tools/                          # 25-tool registry
│   ├── amr/                        # 5
│   ├── scoring/                    # 6
│   ├── structural/                 # 3
│   ├── generative/                 # 4
│   ├── knowledge/                  # 5
│   └── sandbox/                    # 2
├── tests/
│   ├── test_tools.py
│   └── test_server_hardening.py    # 9 hardening tests
└── web/                            # React + Vite + Tailwind frontend
```

### 15.5 `configs/`

```
configs/
├── base.yaml                       # shared defaults
├── stage1_txgemma4.yaml
├── stage2_amr_sft.yaml
├── stage2_5_dpo.yaml               # ★ Stage 2.5 DPO
├── stage3_rl_grpo.yaml
├── accelerate_8gpu_zero3.yaml      # DeepSpeed ZeRO-3 (Stage 1)
└── accelerate_1gpu.yaml             # Stages 2/2.5/3
```

---

## 16. Glossary

| Term       | Definition |
|------------|------------|
| **AMR**    | Antimicrobial Resistance |
| **AMP**    | Antimicrobial Peptide |
| **DPO**    | Direct Preference Optimization (Rafailov et al. 2023) — preference learning without an explicit reward model |
| **GRPO**   | Group Relative Policy Optimization (DeepSeekMath) — RL with verifiable rewards, no value model |
| **MIC**    | Minimum Inhibitory Concentration; the lowest drug concentration that prevents bacterial growth |
| **MMP**    | Matched Molecular Pair — two molecules differing by one defined transformation; used for activity-cliff mining |
| **PAINS**  | Pan-Assay Interference Compounds — known false-positive scaffolds |
| **PDB**    | Protein Data Bank |
| **PEFT**   | Parameter-Efficient Fine-Tuning |
| **QED**    | Quantitative Estimate of Drug-likeness (Bickerton 2012) |
| **SAS**    | Synthetic Accessibility Score (Ertl & Schuffenhauer 2009) |
| **SFT**    | Supervised Fine-Tuning |
| **TDC**    | Therapeutics Data Commons (Huang et al. 2021) |
| **WHO PPL**| WHO Priority Pathogen List (2024) |
| **ZeRO-3** | DeepSpeed memory optimization sharding optimizer + grad + params across GPUs |

---

## Maintenance protocol

This document is the **single source of truth** for the Lysos system.
Every PR that changes architecture, adds a stage, modifies a reward
component, or alters the API surface MUST update the relevant section
in this doc as part of the same commit.

When in doubt, search for the keyword first; if it's not in this doc,
it's not part of the documented system.

