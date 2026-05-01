# Lysos — Tech Spec

**Author**: Rahul
**Project**: AMD Developer Hackathon 2026
**Date**: 2026-04-30 · last refreshed 2026-05-01 (T-3 to kickoff Mon May 4 12pm EDT)
**Status**: pre-kickoff, all non-GPU artifacts shipped, awaiting AMD MI300X credits

---

## 1. One-line pitch

**Lysos** — an open-source generative drug designer built on Gemma 4, specialized for designing novel antibiotics against drug-resistant bacteria, trained with reinforcement learning on AMD MI300X.

---

## 2. The narrative

Antimicrobial resistance is the silent pandemic. 1.27 million deaths every year today, projected to reach 10 million per year by 2050. Every routine hospital stay, every minor wound, every childbirth becomes deadly without working antibiotics. The pharmaceutical industry has largely abandoned antibiotic R&D — too expensive, too slow, too low-margin.

We need a new tool. **Lysos generates novel antibacterial molecules against resistant pathogens in seconds, on a single GPU, with publicly verifiable activity scores.** It's open-source, built on the latest Gemma 4 frontier model, trained with reinforcement learning for accuracy and novelty, deployed on AMD MI300X — the only single-GPU platform with enough memory to run the full training and inference pipeline coresident.

This is the kind of tool that should exist. We're building it.

---

## 3. Locked decisions

| | |
|---|---|
| **Track** | Track 2 — Fine-Tuning on AMD GPUs |
| **Domain** | Drug discovery / antibiotics / antimicrobial resistance |
| **Base model** | `google/gemma-4-31B-it` (dense, multimodal, frontier) |
| **Training pipeline** | Stage 1 (TxGemma-4 base) → Stage 2 (AMR SFT) → Stage 3 (RL/GRPO) |
| **Scope** | Small molecules primary, antimicrobial peptides bonus |
| **Compute** | Large 8× MI300X for Stage 1 / Small 1× MI300X for Stage 2-3 |
| **Budget** | $300 ceiling. Plan: $170-240. Out-of-pocket after $100 credits: $70-140 |

---

## 4. Architecture

Reference render: `docs/assets/architecture.{svg,png}` (built component-by-component,
shows the MI300X 192 GB memory budget bar).

```
┌───────────────────────────────────────────────────┐
│                   LYSOS WORKSPACE                 │
│                                                   │
│  ┌──────────────────────────────────────────────┐ │
│  │  React + Vite + Tailwind frontend            │ │
│  │  "Design antibacterial molecules for [target]" │
│  └──────────────────┬───────────────────────────┘ │
│                     ▼                             │
│  ┌──────────────────────────────────────────────┐ │
│  │  FastAPI backend  (workspace/api/server.py)  │ │
│  │  6 routes — health · pathogens · design ·    │ │
│  │  design/stream (SSE) · score · similar       │ │
│  └──────────────────┬───────────────────────────┘ │
│                     ▼                             │
│  ┌──────────────────────────────────────────────┐ │
│  │  Two Gemma-family models, coresident         │ │
│  │  ─────────────────────────────────────       │ │
│  │  • Gemma 4 31B-it     — generator (62 GB)    │ │
│  │  • EmbeddingGemma 300m — RAG + novelty (1 GB)│ │
│  │  Input:  target pathogen + modality + RAG ex │ │
│  │  Output: N candidate SMILES / peptides       │ │
│  └──────────────────┬───────────────────────────┘ │
│                     ▼                             │
│  ┌──────────────────────────────────────────────┐ │
│  │  Scoring (coresident, no separate process)   │ │
│  │  • predicted MIC (heuristic v1; ML predictor │ │
│  │    Stage 1 output substituted post-train)    │ │
│  │  • QED + Lipinski drug-likeness  (rdkit)     │ │
│  │  • SA score synthesizability     (rdkit)     │ │
│  │  • hemolysis safety              (DBAASP-trained heuristic)
│  │  • Tanimoto novelty              (Morgan FP)  │ │
│  │  • semantic novelty              (EmbeddingGemma cosine vs 20,489-row index)
│  │  • validity                      (rdkit parse)│ │
│  └──────────────────┬───────────────────────────┘ │
│                     ▼                             │
│  ┌──────────────────────────────────────────────┐ │
│  │  Ranked candidate cards · find-similar-drugs │ │
│  │  panel (top-k known antibiotics by cosine)   │ │
│  └──────────────────────────────────────────────┘ │
│                                                   │
│  All running on AMD Instinct MI300X · 192 GB HBM3 │
│  RL training peak ≈ 152 GB (policy + ref + reward)│
└───────────────────────────────────────────────────┘
```

DiffDock-based docking is intentionally not in v1 — adds 10+ GB and ~30s latency
per candidate; out of scope for the hackathon submission. Listed in "stretch goals."

---

## 5. Training pipeline (3 stages)

### Stage 1 — TxGemma-4 (chemistry foundation)

Replicate Google's TxGemma training recipe on Gemma 4 base. Becomes a community-released foundation model.

| Item | Detail |
|---|---|
| Base | `google/gemma-4-31B-it` |
| Data | Therapeutics Data Commons (TDC) — ~70 tasks, instruction-formatted |
| Method | QLoRA (rank 64) with HF Optimum-AMD on ROCm |
| Hardware | Large 8× MI300X (Stage 1 only — fast wall-clock) |
| Time | 6-8 wall-clock hours, ~50-65 GPU-hours total |
| Cost | $90-120 |
| Output | `rahul24raj/txgemma-4-31b` on HF Hub (open release) |
| Eval | TDC standard benchmarks — must match or beat TxGemma 27B |

### Stage 2 — Lysos AMR specialization

Fine-tune the chemistry-aware base on antimicrobial-specific data.

| Item | Detail |
|---|---|
| Base | TxGemma-4 from Stage 1 |
| Dataset (built + LIVE on HF Hub) | [`rahul24raj/lysos-amr-stage2`](https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2) — **222,606 instruction examples** drawn from real public APIs |
| Source breakdown | ChEMBL bacterial-activity REST: 16,462 records · DBAASP REST+detail: 6,256 AMPs · DRAMP XLSX bulk: 8,532 · DrugBank Open vocabulary: 14,630 entries · PDB GraphQL: 3,136 · CARD tarball: 3,543 · ZINC partial: 100 |
| 9 task types | `generation_for_target` 2,776 · `activity_prediction` 8,789 · `peptide_design` 4,621 · `safety_prediction` 14,004 · `drug_likeness` (rdkit-only, ~10K on VM) · `drug_id_lookup` 13,937 · `drug_inchi_key` 13,915 · `drug_synonyms` 13,012 · `drug_cas_lookup` 10,557 · `drug_reverse_cas` 10,516 |
| Method | Continued LoRA fine-tune (rank 64) with task-mix weights from `configs/stage2_amr_sft.yaml` |
| Hardware | Small 1× MI300X |
| Time | 15-20 GPU-hours |
| Cost | $30-40 |
| Output | `rahul24raj/lysos-base` on HF Hub |

### Stage 3 — RL with verifiable rewards (GRPO)

Train the generator to produce molecules that score well on multiple objectives.

| Item | Detail |
|---|---|
| Algorithm | GRPO (Group Relative Policy Optimization, DeepSeek-R1 style) — no value model needed |
| Prompts (LIVE on HF Hub) | [`rahul24raj/lysos-rl-prompts`](https://huggingface.co/datasets/rahul24raj/lysos-rl-prompts) — 3,200 prompts (3,072 train + 128 valid) across 8 priority pathogens × 2 modalities |
| Reward components (configs/stage3_rl_grpo.yaml) | • predicted MIC → 0.40 (heuristic v1; Stage-2 ML predictor swap-in post-training)<br>• drug_likeness QED → 0.15<br>• synthesizability SA → 0.10<br>• hemolysis_safety → 0.15<br>• novelty (Tanimoto Morgan FP) → 0.10<br>• embedding_novelty (EmbeddingGemma cosine vs 20,489-row index) → 0.05<br>• validity (rdkit parse) → 0.05 |
| Hardware | Small 1× MI300X — but RL holds policy + frozen reference + reward predictor + KV-cache + grads coresident (~152 GB peak) — this is THE MI300X-specific moment, busts H100 80 GB |
| Time | 15-25 GPU-hours |
| Cost | $30-50 |
| Output | `rahul24raj/lysos-rl` on HF Hub (final model) |
| Eval | Side-by-side: Stage 2 model vs Stage 3 model on 6-component composite reward, log per component to wandb to detect reward-hacking |

---

## 6. Datasets

### Therapeutic foundation (Stage 1)
- **Therapeutics Data Commons (TDC)** — https://tdcommons.ai
- ~70 tasks across ADMET, target prediction, drug interactions, toxicity
- Already instruction-formatted by Google for TxGemma training
- Open license

### AMR specialization (Stage 2)
- **ChEMBL 34** — 2.4M molecules, antibiotic subset extractable via target/MoA filters
- **BindingDB** — 2.8M binding affinities, antibacterial subsets
- **DBAASP v3** — 17K antimicrobial peptides with MIC values, public license
- **APD3** — 3K AMPs, curated, https://aps.unmc.edu
- **DRAMP** — 22K AMPs http://dramp.cpu-bioinfor.org
- **CARD (Comprehensive Antibiotic Resistance Database)** — resistance genes, all major resistant pathogens
- **PDB** — 3D structures for targets (MRSA, M. tuberculosis, gram-negative porins, etc)
- **HemoPI** — hemolytic peptide predictor training set

### Negative / safety
- **OncoGE** — known toxic compounds for negative training
- **DrugBank** — withdrawn drugs (learn what NOT to design)

### Evaluation
- **MoleculeNet** benchmark suite (BBBP, Tox21, ClinTox, BACE) — for chemistry sanity
- **TDC ADMET benchmarks** — for Stage 1 validation
- **Held-out AMR benchmark** (we'll construct from CARD + recent literature)

---

## 7. Tools / frameworks

### Training
- **PyTorch + ROCm 6.2+** — core
- **HF Transformers** — Gemma 4 support
- **HF Optimum-AMD** — Flash Attention 2, GPTQ, ONNX Runtime on ROCm
- **HF TRL** — SFT trainer + GRPO trainer (verify ROCm compat)
- **Unsloth** — fast LoRA fine-tuning (verify Gemma 4 + ROCm support)
- **DeepSpeed** — memory optimization for Stage 1 on Large 8× config
- **Bitsandbytes** — 4-bit quantization for QLoRA

### Chemistry
- **RDKit** — SMILES parsing, descriptors, similarity, drug-likeness
- **DeepChem** — molecular ML utilities
- **AutoDock Vina** (or VinaGPU on ROCm) — classical docking baseline
- **DiffDock** — neural docking (PyTorch, ROCm-compatible)
- **Boltz-2** — protein-ligand structure prediction (HF Science)
- **PyTDC** — TDC dataset Python interface

### Inference / serving
- **vLLM ROCm** — `rocm/vllm:latest` Docker for fast inference at demo time
- **HF Optimum-AMD** for quantized inference if needed

### Frontend / workspace (CHOSEN, BUILT, VERIFIED)
- **Vite + React 18 + TypeScript (strict)** — `workspace/web/` (Next.js abandoned in favor of leaner stack)
- **Tailwind 3** + custom dark biomedical color palette
- **lucide-react** for icons; no shadcn/ui (kept the bundle tiny)
- **Server-Sent Events (SSE)** via `sse-starlette` for streaming generation
- **FastAPI** backend at `workspace/api/server.py`
- Build verified: 1573 modules, 160 KB JS / 51 KB gzipped + 15 KB CSS / 4 KB gzipped
- 3D molecule viz deferred to Q3 (Mol*/3Dmol.js post-hackathon)

### Deployment
- **HF Spaces** — final demo deployment
- **GitHub** — public open-source repo
- **HF Hub** — model + dataset releases

---

## 8. Compute plan (verified pricing)

DigitalOcean / AMD Developer Cloud verified pricing (Apr 30, 2026):
- 1× MI300X (Small): **$1.99/GPU/hour**
- 8× MI300X (Large): **$1.88/GPU/hour** = $15.04/hour total

| Stage | Config | Wall-clock | Cost |
|---|---|---|---|
| Stage 0 — env + smoke | Small | 5 hrs | $9.95 |
| Stage 1 — TxGemma-4 | Large 8× | 6-8 hrs | $90-120 |
| Stage 2 — AMR SFT | Small | 15-20 hrs | $30-40 |
| Stage 3 — RL/GRPO | Small | 15-25 hrs | $30-50 |
| Demo + benchmarks + ablations | Small | 5-10 hrs | $10-20 |
| **Total expected** | | | **$170-240** |
| **Out-of-pocket after $100 credits** | | | **$70-140** |
| **Worst-case with restarts (20% buffer)** | | | **$200-290** |
| **Out-of-pocket worst-case** | | | **$100-190** |

Within $300 budget. Comfortable cushion.

---

## 9. Deliverables (what we ship by Sun May 10 3pm EDT)

1. **Open-source models on HF Hub**
   - `rahul24raj/txgemma-4-31b` — chemistry foundation
   - `rahul24raj/lysos-base` — AMR specialist (post-SFT)
   - `rahul24raj/lysos-rl` — final RL-tuned designer
2. **Public GitHub repo** — `rahul24raj/lysos`
   - Training code (Stage 1, 2, 3)
   - Inference / generation code
   - Evaluation scripts
   - Workspace UI
   - One-command Docker bring-up (AMD AI Playbook style)
3. **Interactive HF Space** — `lablab-ai-amd-developer-hackathon/lysos`
   - Web UI for live demo
   - Pre-loaded with 5 starter targets (MRSA, M. tuberculosis, etc.)
4. **Public datasets on HF Hub** (where licensing allows)
   - Curated AMR training set
   - Held-out evaluation set
5. **5-min demo video (MP4)**
6. **Pitch deck (PDF, 10-12 slides, startup-format)**
7. **16:9 cover image (PNG)**
8. **Two technical blog posts on HF / Medium** (Build-in-Public)
9. **Daily social posts on X + LinkedIn** with @lablabai @AIatAMD tags

---

## 10. Six-day execution plan

### Day 0 (Sun May 3) — pre-kickoff prep
- Watch 5 official AMD/lablab workshops
- Final environment dry-run on local CPU
- Lock final dataset URLs + DUA approvals where needed
- Slide deck skeleton drafted

### Day 1 (Mon May 4) — foundation training
- 12pm EDT: kickoff stream
- 1pm: spin up Large 8× MI300X
- 2-10pm: Stage 1 (TxGemma-4) training kicks off
- Parallel: build workspace UI scaffold (no model needed)
- Parallel: AMR dataset prep + cleaning
- Evening: Stage 1 finishes; first social post

### Day 2 (Tue May 5) — specialization training
- Stage 2 (AMR SFT) kicks off on Small MI300X
- Parallel: workspace UI gets first end-to-end flow with Stage 1 model
- Build scoring engine integrations (RDKit, DiffDock)
- Daily social post with progress

### Day 3 (Wed May 6) — RL training begins
- Stage 3 (GRPO) kicks off
- Parallel: workspace UI integrates scoring + 3D viz
- First end-to-end generation demo working
- Daily social post

### Day 4 (Thu May 7) — RL finalization + integration
- Stage 3 completes; final model on HF Hub
- Workspace UI polished, pre-loaded targets working
- Demo dry-run #1
- Slides locked
- Daily social post

### Day 5 (Fri May 8) — polish + record
- Demo video shot, edited
- Cover image finalized
- Submission writeup drafted
- Buffer day for final bugs
- Daily social post

### Day 6 (Sat May 9) — final assembly + submit
- Final submission package assembled
- Submitted ~24 hours early (NOT at deadline)
- If on-site invite arrives, fly to SF
- Daily social post

### Day 7 (Sun May 10) — submission deadline 3pm EDT
- Buffer for any last fixes
- If on-site: pitch at 5pm EDT

---

## 11. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Stage 1 TxGemma-4 quality misses TxGemma-27B benchmark | Medium | High | Fall back to direct Gemma 4 → AMR specialization (skip TxGemma-4 release angle) |
| ROCm + Gemma 4 + GRPO tooling has gaps | Medium | High | Smoke-test by Apr 30. If broken, switch RL to DPO (simpler, more mature) or skip RL stage |
| Reward function design (Stage 3) doesn't converge | Medium | High | Use simpler reward (just MIC + QED) for v1, add complexity if working |
| MIMIC/PhysioNet DUA approval doesn't land in time | Low | Low | Use only fully open data (ChEMBL, DBAASP, etc.) — already covered above |
| Demo crashes during pitch | Medium | High | Pre-recorded fallback video; deterministic seed for live demo |
| Wall-clock training overruns 6-day window | Medium | Medium | Use Large 8× for Stage 1 to compress wall-clock. Have CPU-only inference fallback for demo. |
| Idle VM accidental burn ($48/24hrs) | Medium | Low | Hard rule: destroy VM at end of every session. Set $50 alert in DigitalOcean. |
| Demo video runs > 5 min | Medium | Medium | Pre-storyboard at 4:30 max |

---

## 12. Why we win

| Criterion | Why Lysos wins |
|---|---|
| **Application of Technology** | Three frontier techniques in one project: foundation-model fine-tuning + multi-objective RL + multi-model coresident serving |
| **Originality** | First open-source frontier-model AMR drug designer. TxGemma was a property predictor; we built the generator. |
| **Business Value** | $50B antimicrobial market; $100B AMR economic cost; 10M projected deaths/year by 2050. Verifiable unmet need. |
| **Presentation** | Visceral demo (live drug design), real social mission (AMR crisis), clean workspace UI |
| **AMD Utilization** | RL training holds policy + reference + reward predictor coresident — busts H100 80GB. Single-GPU 192GB MI300X is the prerequisite, not optional. |

---

## 12.5 EmbeddingGemma 300m — retrieval + novelty layer (added 2026-05-01)

We add `google/embeddinggemma-300m` (308M params, Gemma 3 architecture, Matryoshka 768→128 dims, 2K context, open weights) as a second model in the stack. Coexists with Gemma 4 31B on the same MI300X (~63 GB total).

Four integration slots:

| Slot | Where | Why |
|---|---|---|
| **Novelty reward** | `src/eval/rewards/embedding_novelty.py` (new) | Semantic novelty complements Morgan-fingerprint Tanimoto — catches paraphrase-level similarity that bit-vectors miss |
| **RAG at inference** | `src/inference/retrieval.py` (new) | Top-k known antibiotics injected into prompt as in-context examples |
| **Training dedup** | `scripts/dedup_with_embeddings.py` (new) | Cluster Stage 2 training corpus; 10–20% smaller dataset, no near-dupe over-fit |
| **"Similar drugs" UI** | `workspace/api/server.py` + workspace UI | Each generated candidate gets a "Find similar known drugs" panel — viral demo feature |

Total integration cost: ~3.5 hours. Plan: `vault/plans/2026-05-01-embeddinggemma-integration.md`.

`gemini-embedding-2` (closed multimodal API) deferred — revisit only if we add image-based molecule similarity.

---

## 13. Stretch goals (if Day 4 is ahead of schedule)

- 26B-A4B MoE variant comparison (the "MoE on MI300X" angle)
- Live wet-lab partnership outreach (academic AMR labs)
- HF Science leaderboard submission (Therapeutics domain)
- Add tuberculosis-specific pathogen benchmark
- Add genomic sequencing input to predict resistance mutations
- Continued pre-training extension to peptides as a separate fine-tune

---

## 14. Open items — status as of 2026-05-01

### Done (struck-through, kept as record)

- [x] ~~Reserve project name / HF Space slug `lysos` in event org~~ → reserved
- [x] ~~Reserve GitHub repo name~~ → `github.com/Rahul-Rajpurohitk/lysos`
- [x] ~~Choose color palette + design system for workspace UI~~ → dark biomedical, `#00e6b9` accent, JetBrains Mono for values, Inter for narrative
- [x] ~~Draft pitch deck skeleton~~ → `docs/pitch-deck.md` (10 slides, Marp frontmatter)
- [x] ~~Finalize Stage 3 reward function weights~~ → `configs/stage3_rl_grpo.yaml` (7 components, sum=1.0)
- [x] ~~Stage 2 dataset built + pushed~~ → 222,606 examples on HF Hub
- [x] ~~Workspace UI verified rendering end-to-end~~ → real screenshot in `docs/assets/workspace-screenshot.png`
- [x] ~~EmbeddingGemma 300m integration~~ → all 5 phases shipped

### GPU-blocked (need MI300X — Sat May 2 expected)

- [ ] Verify ROCm + Gemma 4 + Optimum-AMD compatibility — `scripts/smoke_test_rocm.py` ready
- [ ] Verify TRL GRPO trainer works on ROCm
- [ ] Stage 1 (TxGemma-4) actual training — needs PyTDC installed on VM
- [ ] Real wandb screenshots → swap into `reward-curves.svg`
- [ ] Real `rocm-smi` capture → swap into `rocm-smi-mockup.svg`

### Optional / cheap to ship pre-credits

- [ ] Wider ChEMBL re-fetch (8K/pathogen, 8 standard_types) — code ready, ~30 min runtime
- [ ] EmbeddingGemma dedup pass on the 222,606-row Stage 2 — script ready, 5-10 min on a beefy machine
- [ ] PubChem fresh-AID discovery via eutils (most curated retired)
- [ ] APD3 GitHub mirror (current site URLs all 404)
- [ ] Marp PDF render of `docs/pitch-deck.md` (one `npm i -g @marp-team/marp-cli` away)
- [ ] Submission writeup ≤ 1500 chars at `docs/submission-writeup.md`
