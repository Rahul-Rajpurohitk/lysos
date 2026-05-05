# Lysos — Comprehensive Audit + Work Plan

**Date**: 2026-05-05
**Goal**: Best-of-class Gemma-4 → Lysos antimicrobial drug-design system, hackathon-grade submission
**Hackathon deadline**: Sun May 10, 3:00 PM EDT (5 days remaining)

This document is the **single source of truth** for what's been done, what's
left, and what we're driving tonight + the next 4 days.

---

## 0. Where we are right now

### Done (data + distillation)

| Asset | State |
|-------|-------|
| pro-v5 (cleaned baseline) | 308K train / 19K valid / 50 test on HF private |
| pro-v10 (current default) | 382K train / 23K valid / 50 test on HF private |
| Teacher distillation | 78,150 traces across 7 layers (chem, systems, architecture, raw-data, edge/clinical, targeted, eval-aligned) |
| Stage 3 reward stack | 12 components, weights sum to 1.0 |
| Eval harness | 7 metrics with locked configs (`eval/run_all.py`) |
| Manifest tracking | `MANIFEST.json` with git_sha + per-dataset hash |
| Architecture docs | 13 canonical .md files in `docs/architecture/` |

### Pending (high-impact)

- [ ] AizynthFinder + Boltz-2 calibration sweeps (reward components have fallback values)
- [ ] Pre-train Gemma 4 baseline on the eval harness (no post-train delta without it)
- [ ] Verified loss masking smoke test
- [ ] Data-quality scorer + reweighting
- [ ] Methods paper draft + model/dataset cards
- [ ] AMD MI300X access (still waiting on credits)

---

## 1. Stage-by-stage gap analysis

### Stage 0 — Sprint planning + strategy

| Gap | Severity |
|-----|----------|
| No risk register (Stage 1 TxGemma replication failure backup?) | MED |
| No explicit "winning condition" per eval metric | MED |
| No competitor analysis (TxGemma, Tx-LLM, MolGPT, GPT-4 zero-shot) | LOW |

### Stage 1 — Data prep

| Gap | Severity | Action |
|-----|----------|--------|
| **Data-quality scoring per row** | HIGH | Build scorer; reweight high-leverage rows |
| **Hard-negative mining** | HIGH (post first checkpoint) | Sample model-failures; oversample |
| **Counterfactual pairs** (minimal-edit before/after with flipped prediction) | MED | Generate from MMP + perturbation |
| **Active learning loop** (oracle labels for borderline) | MED | Defer to post-launch |
| **Multi-resolution data** (atom/fragment/scaffold/drug) | LOW | Annotation-heavy; defer |
| **Adversarial robustness** (typo/perturbation) | MED | Easy: regenerate K canonical SMILES per active |
| **Time-aware split** (train pre-2020, test 2024) | MED-HIGH | Powerful claim if it works |

### Stage 2 — TxGemma-4 base SFT (Stage 1 of training)

| Gap | Severity | Action |
|-----|----------|--------|
| **Gemma-4 self-distillation** on TDC tasks | MED | Use Gemma 4 zero-shot to label, then SFT on labels (better than raw) |
| **Curriculum learning** (easy→hard) | LOW | Test post-launch |
| **Calibration training** (predict own confidence) | MED | Hooks into `confidence_expression` distillation |
| **Layer-wise LR decay** | LOW | Standard hyperparameter |

### Stage 3 — Lysos AMR-spec SFT (Stage 2 of training)

| Gap | Severity | Action |
|-----|----------|--------|
| **Verified loss masking smoke test** | CRITICAL | Run before any GPU spend |
| **Data-order ablation** (random / curriculum / anti-curriculum) | LOW | Defer |
| **Task-mix sweep** (current weights are hand-tuned) | MED | Quick sweep on small subset |
| **LoRA hyperparameter search** | LOW-MED | r=32 / alpha=64 is industry default |
| **Sequence packing audit** (does packing work given skewed length distribution?) | MED | Verify before training |

### Stage 4 — GRPO RL (Stage 3 of training) — HIGHEST gap

| Gap | Severity | Action |
|-----|----------|--------|
| **AizynthFinder calibration sweep** | CRITICAL | Run tonight; ~6h CPU |
| **Boltz-2 pose sweep** | CRITICAL | Run tonight; ~12h CPU (skip if Boltz-2 setup too heavy) |
| **Reward hacking probe** | HIGH | Detect if model games individual reward components |
| **DPO baseline** | LOW (defer) | Post-launch comparison |
| **PPO vs GRPO ablation** | LOW | Defer; defaulting to GRPO is fine |
| **KL coefficient sweep** | MED | β=0.04 is a guess; quick sweep helps |
| **Best-of-N inference** | MED | Sample 8, pick best for deployment |
| **Reference model staleness** | MED | When to refresh ref during long RL runs |

### Stage 5 — Evaluation

| Gap | Severity | Action |
|-----|----------|--------|
| **Pre-train Gemma 4 baseline NOT YET COMPUTED** | CRITICAL | 2h once vLLM serves Gemma 4 |
| **Human eval bench** (clinicians + medchemists) | HIGH (out of hackathon scope) | Defer; document as future work |
| **OOD eval** (Salmonella, Streptococcus) | HIGH | Add 2 OOD pathogens to eval harness |
| **Adversarial robustness** (typos, perturbations) | MED | Quick: 100 perturbed prompts |
| **Calibration plots** (predicted vs actual MIC) | MED | Easy once first model trained |
| **Long-context eval** (5-15 turn Designer dialogues) | MED | Use existing teacher distill traces as eval |
| **Comparative benchmark** (vs TxGemma, GPT-4 zero-shot) | HIGH | Strong claim if we beat them |

### Stage 6 — Deployment

| Gap | Severity | Action |
|-----|----------|--------|
| Quantization (FP8/INT4) | LOW | Pre-launch optimization |
| Streaming inference | LOW | UX nice-to-have |
| Speculative decoding | LOW | Latency optimization |
| A/B test infrastructure | LOW | Post-MVP |
| Drift detection | LOW | Post-MVP |
| Audit logging | LOW | Compliance for production, not hackathon |

### Cross-cutting

| Gap | Severity | Action |
|-----|----------|--------|
| **Methods paper draft** | CRITICAL | Submission required; 1 day work |
| **Model card + dataset card + datasheet** | CRITICAL | HF Hub standard; 2h work |
| **Reproduction notebook** | HIGH | Demo + judge replication; 4h |
| **Bias audit** (Mtb dominance, PK panel demographics) | MED | Document known biases |
| **Counterfactual explanation generator** | LOW | "Why X not Y" — stretch goal |

---

## 2. Prioritized work plan

### TIER 1 — Must complete before submission

| # | Item | Effort | Owner | Status |
|---|------|--------|-------|--------|
| 1 | AizynthFinder calibration sweep on 5K candidates | ~6h CPU | system | TODO |
| 2 | Boltz-2 pose sweep on 1K candidates × 3 PDBs | ~12h CPU | system | TODO |
| 3 | Pre-train Gemma 4 baseline eval | ~2h | once vLLM | TODO |
| 4 | Data-quality scorer + pro-v11 reweighted | ~3h | system | TODO |
| 5 | Verified loss masking smoke test | ~30min | system | TODO |
| 6 | Methods paper draft | ~1 day | manual | TODO |
| 7 | Model card + dataset card + datasheet | ~2h | manual + auto | TODO |
| 8 | OOD eval (Salmonella + Streptococcus added) | ~2h | system | TODO |
| 9 | Comparative benchmark vs Gemma 4 zero-shot + GPT-4 zero-shot | ~4h | once vLLM | TODO |
| 10 | Adversarial robustness micro-eval (100 perturbations) | ~2h | system | TODO |

### TIER 2 — Strong-to-have

| # | Item | Effort |
|---|------|--------|
| 11 | Hard-negative mining (post first SFT checkpoint) | ~2h |
| 12 | Reward hacking probe | ~3h |
| 13 | Calibration plots (post-train) | ~1h |
| 14 | Continuous-eval dashboard | ~2h |
| 15 | Reproduction notebook | ~4h |
| 16 | Time-aware split eval (train pre-2020, test 2024) | ~3h |
| 17 | Self-distillation from Gemma 4 zero-shot on TDC | ~6h |
| 18 | KL coefficient sweep on small RL run | ~4h GPU |
| 19 | Long-context eval suite | ~2h |
| 20 | Counterfactual pair generation | ~3h |

### TIER 3 — Stretch / nice-to-have

| # | Item | Why defer |
|---|------|-----------|
| 21 | DPO baseline run | Comparison point but parallel work to GRPO |
| 22 | Quantization (FP8/INT4) | Inference optimization, not core |
| 23 | Streaming inference | UX, not core |
| 24 | A/B test infrastructure | Post-MVP |
| 25 | Counterfactual explanation generator | Explainability; nice-to-have |
| 26 | Human eval bench | Out of hackathon scope |
| 27 | Hyperparameter sweeps for LoRA r/alpha | Marginal gains |
| 28 | Bias audit + datasheet for datasets | Polish |

---

## 3. Tonight's plan (May 5 evening)

Goal: knock out items 1, 4, 5, 8, 10 — set up for tomorrow's Tier 1 finish.

### Sequence

**21:00-22:00** — AizynthFinder calibration sweep launch (background, ~6h)
- Run `scripts/run_aizynth_sweep.py` on 5K active candidates from `known-antibiotics-canonical.parquet`
- Output: `data/processed/aizynth_calibration_cache.parquet`
- This populates the `synthesizability` reward component cache

**22:00-23:00** — Data-quality scorer + pro-v11
- Build `scripts/score_data_quality.py`
  - Per-row score 0-10 from: token length, structural depth, citation, novelty
  - Heavily reweight teacher distillation, Designer↔Critic loops, mutation deep dives
- Build `scripts/build_stage2_pro_v11.py` — quality-weighted sampling
- Push to HF private

**23:00-23:30** — Verified loss masking smoke test
- Build `scripts/test_loss_masking.py`
  - Format a sample row through Gemma 4 chat template
  - Verify `<start_of_turn>model\n` appears as response separator
  - Confirm SFT trainer's response_template aligns properly

**23:30-00:30** — OOD eval extension
- Add Salmonella + Streptococcus pneumoniae to eval harness
- Generate ~50 OOD eval prompts each
- Measure expected baseline: model has zero training, should refuse-or-fail gracefully

**00:30-01:30** — Adversarial robustness micro-eval
- Build `eval/adversarial_test.py`
  - 100 perturbed SMILES (typo, wrong canonicalization, extra whitespace)
  - 100 perturbed pathogen names ("MRSA " with trailing space, "M.R.S.A.")
  - 100 jailbreak attempts (extends our v6 + eval-aligned refusal training)
- Should hit ≥ 95% robustness post-train

**01:30-02:30** — Boltz-2 pose sweep launch (if Boltz-2 setup feasible)
- If Boltz-2 environment can be built tonight: run sweep
- If not: fallback to predict_binding_affinity calibration via cached XGBoost model

### Checkpoint at end of tonight

- [ ] AizynthFinder cache populated
- [ ] pro-v11 (quality-reweighted) pushed to HF private
- [ ] Loss masking verified
- [ ] OOD eval prompts ready
- [ ] Adversarial robustness eval ready
- [ ] Boltz-2 attempted (or fallback noted)

---

## 4. Tomorrow + remainder of week

### Day 2 (May 6)

- Pre-train Gemma 4 baseline eval (need vLLM live)
- Comparative benchmark vs Gemma 4 zero-shot + GPT-4 zero-shot
- Hard-negative mining script (ready to run after first checkpoint)
- Methods paper outline + first draft

### Day 3 (May 7)

- Model card + dataset card + datasheet
- Reproduction notebook
- Continuous-eval dashboard
- Methods paper figures + tables

### Day 4 (May 8)

- AMD credits expected to land (or already)
- vLLM smoke test on MI300X
- Stage 1 TxGemma-4 SFT launch (if credits allow)

### Day 5 (May 9)

- Stage 2 SFT on pro-v11
- Initial checkpoint eval
- Hard-negative mining if needed
- Methods paper revisions

### Day 6 (May 10) — Submission day (deadline 3pm EDT)

- Stage 3 GRPO RL
- Final eval + comparative benchmark
- Demo video recording
- Pitch deck finalization
- Submission package

---

## 5. Best-of-the-best stretch goals

These would push Lysos from "credible benchmark" to "publishable research":

1. **Time-aware evaluation** — train on pre-2020 surveillance, test on 2024
   - Demonstrates the model can PREDICT emerging resistance
   - Strong claim for a methods paper
2. **Methods paper submission** — ChemRxiv / bioRxiv / NeurIPS-AIDD workshop
3. **Live wet-lab partnership** — actually validate top candidates
4. **Counterfactual explanation generator** — "why this candidate, not the alternative"
5. **Open-source competition / leaderboard** — invite reproduction
6. **Citation analysis** — every claim cited; bench against human experts
7. **Cross-pathogen generalization** — show transfer to non-priority pathogens
8. **Public HF Space demo** — interactive Workbench with the trained model

---

## 6. Quality bar checklist

For each item, before marking COMPLETE:

- [ ] Code: linted, type-checked, smoke-tested
- [ ] Data: schema-validated, manifest-tracked, distribution audited
- [ ] Model artifacts: pushed to HF with model card
- [ ] Eval: pre-train baseline + post-train + delta with confidence intervals
- [ ] Provenance: git_sha + dataset_hash + reward_stack_version captured
- [ ] Documentation: README + architecture docs + reproduction notebook
- [ ] Tests: unit tests where applicable, smoke tests for big workflows

---

## 7. Definition of "submission-ready"

Lysos counts as submission-ready when:

1. **Reproducible**: third party can `git clone` + follow `docs/REPRODUCE.md` and recover within ±3% of our reported numbers on the eval harness
2. **Comparative**: head-to-head numbers vs Gemma 4 zero-shot + (at least one of) TxGemma / Tx-LLM / GPT-4 zero-shot on the 7 eval metrics
3. **Provenance**: `MANIFEST.json` references the exact pro-vN dataset + reward-stack version + git_sha used
4. **Cards**: model card + dataset card + datasheet pushed to HF
5. **Demo**: 5-min video showing Workbench design loop end-to-end
6. **Pitch**: TAM/SAM, revenue model, competitors, future prospects per lablab pro tips
7. **Methods paper draft**: posted to ChemRxiv or bioRxiv as preprint (publication later)

---

## 8. Open questions

| Q | Need answer by |
|---|----------------|
| AMD credits actually landed? | Day 2 (May 6) |
| Boltz-2 environment buildable on our hardware? | Day 2 |
| TxGemma reference checkpoint accessible? | Day 1 (TONIGHT) |
| GPT-4 zero-shot eval — API cost OK? | Day 2 |
| Methods paper venue (ChemRxiv vs bioRxiv vs NeurIPS-AIDD)? | Day 3 |

---

## Status tracking — update as we go

Living document. Modify checkboxes / status as items complete.

Last updated: 2026-05-05 (start of evening sprint).
