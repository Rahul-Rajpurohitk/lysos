# Lysos — Tech Spec

**Author**: Rahul
**Project**: AMD Developer Hackathon 2026
**Date**: 2026-04-30 (T-4 to kickoff Mon May 4 12pm EDT)

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

```
┌───────────────────────────────────────────────────┐
│                   LYSOS WORKSPACE                 │
│  ┌──────────────────────────────────────────────┐ │
│  │ "Design antibacterial molecules for [target]"│ │
│  └──────────────────┬───────────────────────────┘ │
│                     ▼                             │
│  ┌──────────────────────────────────────────────┐ │
│  │ Lysos generative model (Gemma 4 + RL)        │ │
│  │ Input: target protein / pathogen + spec      │ │
│  │ Output: 50-100 candidate SMILES / sequences  │ │
│  └──────────────────┬───────────────────────────┘ │
│                     ▼                             │
│  ┌──────────────────────────────────────────────┐ │
│  │ Scoring engines (coresident on MI300X)       │ │
│  │ • Predicted MIC (antibacterial activity)     │ │
│  │ • Drug-likeness (QED, Lipinski)              │ │
│  │ • Synthesizability (SA score)                │ │
│  │ • Hemolysis / safety                         │ │
│  │ • Novelty vs known antibiotics               │ │
│  │ • DiffDock binding pose prediction           │ │
│  └──────────────────┬───────────────────────────┘ │
│                     ▼                             │
│  ┌──────────────────────────────────────────────┐ │
│  │ Ranked candidate list w/ 3D viz, downloads   │ │
│  └──────────────────────────────────────────────┘ │
│                                                   │
│  All running on AMD Instinct MI300X 192GB         │
└───────────────────────────────────────────────────┘
```

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
| Data | • ChEMBL antibiotic subset (~50K compounds with MIC data)<br>• DBAASP antimicrobial peptides (~17K AMPs)<br>• APD3 (~3K AMPs)<br>• DRAMP (~22K AMPs)<br>• PDB structures of resistant pathogen targets (MRSA PBPs, M. tuberculosis InhA, gram-neg porins)<br>• Curated negative examples (off-target binding, hemolytic peptides) |
| Method | Continued LoRA fine-tune with new specialty data |
| Hardware | Small 1× MI300X |
| Time | 15-20 GPU-hours |
| Cost | $30-40 |
| Output | `rahul24raj/lysos-base` on HF Hub |
| Tasks | • Predict MIC for given molecule + pathogen<br>• Generate antibacterial molecule for target<br>• Generate AMP sequence for target<br>• Predict hemolytic activity<br>• Score drug-likeness |

### Stage 3 — RL with verifiable rewards (GRPO)

Train the generator to produce molecules that score well on multiple objectives.

| Item | Detail |
|---|---|
| Algorithm | GRPO (Group Relative Policy Optimization, DeepSeek-R1 style) — no value model needed |
| Reward components | • Predicted MIC against target pathogen (use Stage 2 model itself as predictor + external models like CARD-RGI) → 0.4 weight<br>• QED drug-likeness (RDKit deterministic) → 0.15<br>• SA score synthesizability (RDKit) → 0.10<br>• Hemolysis prediction (HemoPI / DBAASP) → 0.15<br>• Novelty (Tanimoto distance to nearest known antibiotic) → 0.15<br>• Validity (RDKit can parse SMILES) → 0.05 |
| Hardware | Small 1× MI300X — but RL holds policy + reference + reward predictor coresident (~150GB) — this is THE MI300X-specific moment |
| Time | 15-25 GPU-hours |
| Cost | $30-50 |
| Output | `rahul24raj/lysos-rl` on HF Hub (final model) |
| Eval | Side-by-side: Stage 2 model vs Stage 3 model on 10 standardized AMR design tasks |

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

### Frontend / workspace
- **Next.js + Tailwind + shadcn/ui** — clean modern web UI
- **3Dmol.js** or **Mol***  — 3D molecule visualization in browser
- **Plotly** for property charts
- **Server-Sent Events (SSE)** for streaming generation
- **FastAPI** backend connecting UI to model

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

## 13. Stretch goals (if Day 4 is ahead of schedule)

- 26B-A4B MoE variant comparison (the "MoE on MI300X" angle)
- Live wet-lab partnership outreach (academic AMR labs)
- HF Science leaderboard submission (Therapeutics domain)
- Add tuberculosis-specific pathogen benchmark
- Add genomic sequencing input to predict resistance mutations
- Continued pre-training extension to peptides as a separate fine-tune

---

## 14. Open items still to do

- [ ] Verify ROCm + Gemma 4 + Optimum-AMD compatibility with smoke test
- [ ] Verify TRL GRPO trainer works on ROCm
- [ ] Reserve project name / HF Space slug `lysos` in event org
- [ ] Reserve GitHub repo name
- [ ] Choose color palette + design system for workspace UI
- [ ] Draft pitch deck skeleton
- [ ] Finalize Stage 3 reward function weights via small-scale test
