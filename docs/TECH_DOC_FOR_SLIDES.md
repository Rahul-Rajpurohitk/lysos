# Lysos — Technical Document for Slide Creation

> Self-contained. Each `## H2` section is one slide candidate. Each `### H3` is a sub-slide / section header. Numbers, claims, and labels are written so they can be lifted directly into a deck without further editing. Visuals are described in `▶` lines so the design tool knows what to render.

---

## TITLE SLIDE

**LYSOS**
*Open-source generative antibiotic designer for the AMR pandemic.*

Three-stage fine-tune of Gemma 4 31B-it on a single AMD MI300X.
Multi-agent debate engine. End-to-end live agentic workspace.

`AMD Developer Hackathon 2026 — Track 2: Fine-Tuning on AMD GPUs`

▶ Visual: hexagonal lavender/purple molecule rendering on dark gradient. AMD red accent. "v1.0-hackathon-submission" tag bottom-right.

---

## THE PROBLEM — Antimicrobial resistance is the silent pandemic

- **1.27 million deaths every year — today** (WHO)
- **Projected 10 million per year by 2050** (UN)
- **Last fully novel antibiotic class approved: 1987**
- Pharma has largely abandoned antibiotic R&D — too expensive, too slow, too low-margin
- Without working antibiotics: routine surgery, childbirth, cancer chemo, and ICU stays become deadly

▶ Visual: huge "1.27M" number + Earth map with red overlay where AMR deaths are highest. Stat blocks on the right.

---

## THE OPPORTUNITY — A new tool stack is finally possible

| What changed | Why it matters |
|---|---|
| Gemma 4 31B-it ships **March 2026** with chemistry-aware pretraining | Foundation good enough to fine-tune for SAR + MIC reasoning |
| AMD MI300X delivers **192 GB HBM3 on a single GPU** | Coresident base + adapter + KV cache + agent context, no sharding |
| 222K curated AMR examples + 10K hard-negative Pareto pairs | Enough signal for a 3-stage fine-tune to actually generalize |
| RDKit + CARD + ChEMBL all open and queryable | Verifiable scoring on every candidate, no black box |

▶ Visual: 4-quadrant grid. Each quadrant has an icon + the column data.

---

## WHAT WE BUILT — End-to-end, all open-source

```
       ┌─────────────────────────────────────────────────┐
       │  Three-stage fine-tune of Gemma 4 31B           │
       │     Stage 1 → Stage 2 → Stage 2.5 DPO           │
       │     all trained on AMD MI300X                   │
       └─────────────────────────┬───────────────────────┘
                                 │
       ┌─────────────────────────┴───────────────────────┐
       │  Multi-agent debate engine                      │
       │     Designer · Critic · Editor · Strategist     │
       │     Orchestrator router                         │
       └─────────────────────────┬───────────────────────┘
                                 │
       ┌─────────────────────────┴───────────────────────┐
       │  Live agentic workspace                         │
       │     5 containers · 12+ slash · 7 workflows      │
       │     real-time scoring · resistance map · Pareto │
       └─────────────────────────────────────────────────┘
```

**Three pillars. One repo. MIT license. All artifacts public on Hugging Face.**

▶ Visual: stack of 3 horizontal panels with arrows flowing down. Each panel labeled.

---

## STAGE 1 — TxGemma-4 31B (continued pretraining)

**HF**: `rahul24raj/txgemma-4-31b`

| Property | Value |
|---|---|
| Base | `google/gemma-4-31B-it` (62 GB bf16) |
| Adapter type | LoRA |
| Rank / alpha | r=64 / α=256 |
| Target modules | q_proj, k_proj, v_proj, o_proj |
| Dtype | bfloat16 |
| Hardware | 1× AMD MI300X (192 GB HBM3) |
| Wall-clock | ~2 hours |
| Corpus | Therapeutic literature, ChEMBL bioactivity, drug-target databases |

**Goal**: Bias the base toward therapeutic vocabulary — molecule names, reaction types, drug classes, pharmacology terms — without forgetting general capability.

▶ Visual: card with the table + a sparkline of training loss curve.

---

## STAGE 2 — Lysos-base SFT (the AMR specialization)

**HF**: `rahul24raj/lysos-base` · Dataset: `rahul24raj/lysos-amr-stage2`

| Property | Value |
|---|---|
| Base | `google/gemma-4-31B-it` (loads Stage 1 conceptually) |
| Adapter type | LoRA |
| Rank / alpha | r=64 / α=128 |
| Examples | **222,606** curated AMR records |
| Pathogens covered | 8 priority (MRSA, Mtb, EColi-CRE, KpneuCRE, Abaum, Paer, VRE, NGono) |
| Loss | Standard causal-LM SFT |
| Wall-clock | ~3 hours on 1× MI300X |

**Dataset composition**:
- ChEMBL bioactivity records (filtered to AMR-active scaffolds)
- MIC (minimum inhibitory concentration) labels per pathogen
- Drug-class structure-activity reports
- Literature-mined SAR examples
- Negative controls (inactive analogs)

▶ Visual: pie chart of dataset composition + horizontal bar of pathogen distribution.

---

## STAGE 2.5 — DPO alignment on Pareto-trap pairs

**HF**: `rahul24raj/lysos-base-dpo` · Hard-negatives: `rahul24raj/lysos-hard-negatives-v1`

| Property | Value |
|---|---|
| Base | `google/gemma-4-31B-it` |
| Adapter type | LoRA on top of Stage 2 |
| Rank / alpha | r=32 / α=64 (smaller — refinement, not retraining) |
| Pairs | **10,000** hard-negative Pareto-trap preference pairs |
| Anti-correlated axes | 10 (potency↔ADMET, activity↔novelty, MIC↔synthesizability, ...) |
| Loss | DPO (β=0.1) — KL-bounded preference learning |
| Wall-clock | ~45 min on 1× MI300X |

### Why DPO and not GRPO?

We initially planned a Stage 3 GRPO run for full RL alignment. After the first attempt:
- Reward hacking on the novelty axis (model produced gibberish that scored high on raw embedding distance)
- KL drift after step 200 — base capability eroding
- Reward signal too noisy for online RL on this hardware budget

Stage 2.5 DPO replaced it. **DPO directly teaches the model to prefer Pareto-balanced candidates** over candidates that maximize one axis at the cost of others. Stabler signal, faster convergence, no reward hacking, full base capability preserved.

▶ Visual: 2D scatter — x=potency, y=ADMET. Two clusters labeled "Pareto-trap (max one axis)" and "Pareto-balanced (preferred)". Arrow from trap to balanced labeled "DPO objective".

---

## WHY THE MI300X IS LOAD-BEARING

The single decision that made the whole project tractable.

| GPU | VRAM | Can fit Gemma 4 31B bf16 + LoRA + KV + agent ctx? |
|---|---|---|
| H100 SXM | 80 GB | ❌ needs sharding or smaller base |
| H200 | 141 GB | ⚠ tight, no headroom for serving |
| MI300X | **192 GB HBM3** | ✅ all coresident, comfortable |

**What this enables**:
- **Coresident training + serving** — same GPU that trains also serves inference, no migration step
- **No tensor parallelism** — code is single-process, ROCm-native PyTorch, simpler deploy
- **Headroom for the agent context** — workflow that holds resistance map + scoring history + chat memory simultaneously
- **8K+ context length** at full bf16 with LoRA active

**Total wall-clock for the 3-stage fine-tune: ~6 hours on 1 GPU.**

▶ Visual: VRAM bar chart comparing H100 / H200 / MI300X. Stack-fill showing bf16 weights / LoRA / KV / agent ctx within the MI300X bar with green headroom on top.

---

## THE MULTI-AGENT DEBATE — Real LLM calls, not simulation

When the user says *"design a molecule that beats MRSA"*, the **Orchestrator** classifies the intent and delegates to the `design_with_debate` workflow. Four roles take turns:

```
        ┌───────────┐    proposes 3      ┌───────────┐    challenges     ┌───────────┐    refines       ┌─────────────┐
        │ DESIGNER  │───── candidates ──▶│  CRITIC   │── per proposal ──▶│  EDITOR   │── via SAR ────▶│  STRATEGIST │
        │  (LLM #1) │                    │  (LLM #2) │                   │  (LLM #3) │                  │   (LLM #4)  │
        └───────────┘                    └───────────┘                   └───────────┘                  └──────┬──────┘
                                                                                                              │
                                                                                  picks winner + runner-up + next action
                                                                                                              │
                                                                                                              ▼
                                                                              winner SMILES auto-loads to 2D + 3D + radar
```

**Each role is a separate LLM call** with a role-specific system prompt. Every call is recorded into a ring buffer with:
- `role`, `action_type`, `message`, `confidence`
- `tokens_in`, `tokens_out`, `cost_usd`
- `elapsed_ms`, `status` (ok / error)
- `triggered_by` (the previous role — drives the cross-agent handoff graph)

▶ Visual: 4 colored agent circles (Designer green, Critic red, Editor blue, Strategist purple) connected by arrows. Below each: live counter "0 → 3 → 6 → 1" showing actions per role.

---

## THE ORCHESTRATOR — Front-door router

Every user message — slash, free text, or button click — first hits the orchestrator agent. It classifies the intent into one of four routes:

| Route | When | Example |
|---|---|---|
| `workflow` | Multi-step plan | "design a molecule" → `/wf design_with_debate` |
| `slash` | Single command | "score this" → `/score <smiles>` |
| `agent` | Open-ended Q | "tell me about mecA" → tool-calling agent |
| `answer` | Direct prose | "what's a Pareto frontier?" → no tool |

Routing decision is itself an LLM call with the user's message + ambient context (active SMILES, pathogen, PDB). Recorded with rationale + tokens. The user can audit *why* a path was chosen.

▶ Visual: input "design a better molecule" branching into 4 routes with dotted lines, the chosen workflow path highlighted.

---

## THE LIVE WORKSPACE — 5 containers, 1 chat, 12+ slash, 7 workflows

| Container | What's in it |
|---|---|
| **Chemistry** | 2D molecule builder with click-to-edit atoms · 3D pocket theater (target picker, halos, contacts) · Resistance escape map (per-atom vulnerability, harden suggestions, comparison) · Pareto lab (frontier, axis pickers, dominator explainer) |
| **Scoring** | 12-axis reward radar (real-time on every SMILES change) · Score breakdown card with per-axis explanation + improvement suggestion · Atom-level structural-alert panel (PAINS, toxicophores) · Pocket pose with Boltz-2 contacts |
| **Agents** | Multi-agent activity hub · Live cost meter (cumulative LLM spend) · Flow graph (Designer → Critic → Editor → Strategist) · Cross-agent handoff edges · Per-role KPI cards (latency, ok rate, confidence) · Time-spent stacked bar · Latency p50/p95/p99 distributions · Action log filterable by agent + status · Role inspector drilldown |
| **Knowledge** | Pathogen command center · 8×12 pathogen × drug-class pressure heatmap · 4-tier resistance gene network (pathogen → genes → drug classes → first-line therapy) · Mutation atlas per validated PDB · Champion vault (all 8 reigning champions across pathogens) · Antibiotic reference corpus |
| **Report** | Snapshot builder · Markdown export · PDF export · Session trace timeline · Edit log replay |

**Slash commands**: `/design`, `/edit`, `/score`, `/explain`, `/escape`, `/theater`, `/pareto`, `/champion`, `/sar`, `/stress`, `/compare`, `/library`, `/harden`, `/load`, `/swap`, `/fg`, `/datasets`, `/synth`, `/dock`, `/admet`.

**Workflows** (SSE-streamed, all auto-record to agent activity):
1. `design_with_debate` — 4-agent debate (the killer demo)
2. `harden_candidate` — find weak atoms + AI-bespoke + curated swap suggestions
3. `compare_top_n` — side-by-side + Critic narration
4. `pareto_explore` — frontier + Critic verdict (advance / A-B / drop)
5. `broad_spectrum_screen` — cross-target spectrum classification
6. `optimize_for_property` — single-axis push iterative editor
7. `discover_and_assess` — bulk candidate sweep

▶ Visual: 5-tab UI screenshot, each container labeled with its key card, connected to a chat composer at the bottom.

---

## ARCHITECTURE — One stack, three planes

```
                            ┌──────────────────────────────────────┐
                            │  Browser (React + Vite, port 5173)   │
                            │   chat composer · 5 containers       │
                            │   slash palette · workflow palette   │
                            │   SSE subscribers · MarkdownText     │
                            │   12 chat-card kinds (proposal,      │
                            │   workflow, champion, score, ...)    │
                            └──────────────────┬───────────────────┘
                                               │  HTTP / WS / SSE
                                               ▼
                            ┌──────────────────────────────────────┐
                            │  FastAPI backend (port 7860)         │
                            │   /api/chat → command harness        │
                            │   /api/orchestrator/run [SSE]        │
                            │   /api/workflows/run [SSE]           │
                            │   /workbench/* (140+ endpoints)      │
                            │   sqlite session + champion stores   │
                            └──────────────────┬───────────────────┘
                ┌──────────────────────────────┼──────────────────────────────┐
                ▼                              ▼                              ▼
        ┌──────────────┐               ┌──────────────┐               ┌──────────────┐
        │   RDKit      │               │ Chemistry    │               │ Multi-agent  │
        │ (props,      │               │ scoring      │               │ debate       │
        │ edits,       │               │ (12 axes)    │               │ (4 LLM calls │
        │ validity)    │               │              │               │ per round)   │
        └──────────────┘               └──────────────┘               └──────┬───────┘
                                                                             │
                                                  recorded into agent_activity ring
                                                  (tokens, cost, latency, handoff)
                                                                             │
                                                                             ▼
                            ┌──────────────────────────────────────┐
                            │  AMD MI300X · vllm 0.20+             │
                            │  Gemma 4 31B + lysos-base-dpo LoRA   │
                            │  OpenAI-compatible endpoint :8000    │
                            └──────────────────────────────────────┘
```

▶ Visual: 3-tier diagram — browser, backend, GPU compute.

---

## DATA FLOW — `/wf design_with_debate` end-to-end

```
USER: "design a molecule for MRSA better than the seed"
   │
   ▼
ORCHESTRATOR  ──── classifies intent ────▶  workflow: design_with_debate
   │
   ▼
WORKFLOW step 1 · DEBATE (inline)
   │   ├── Designer call → 3 SMILES proposals + rationale
   │   ├── Critic call → critiques each proposal, names weakness
   │   ├── Editor call → applies critic's suggested fix
   │   └── Strategist call → picks winner + runner-up + next_action
   │
   ▼
WORKFLOW step 2 · SCORE WINNER (HTTP tool)
   │   └── score_explain(winner_smiles, MRSA) → 12-axis decomposition
   │
   ▼
WORKFLOW.done → state_dump emitted to frontend
   │
   ▼
FRONTEND
   ├── auto-load winner SMILES into 2D + 3D + radar
   ├── render workflow card with steps + summary
   ├── emit candidate_added events for Pareto Lab
   ├── auto-promote winner if it beats reigning champion
   └── show ProposalCard with Apply / Compare / Let-agent-decide
```

Total wall-clock for one debate round: **~25 seconds**, **~0.005 USD** in LLM cost.

▶ Visual: vertical flow diagram, each node colored by which subsystem it belongs to.

---

## REWARD STACK — 12 axes, real-time

Every candidate is scored on 12 axes simultaneously. Composite is a weighted sum.

| Axis | Type | Source | Notes |
|---|---|---|---|
| `predicted_mic` | proxy | trained model + RDKit | Pathogen-specific |
| `composite_reward` | derived | weighted sum | Top-level dial |
| `drug_likeness_qed` | real | RDKit QED | 0-1 |
| `synthesizability` | proxy | SAScore / RDKit | 0-1 |
| `embedding_novelty` | real | LLM embedding cosine | vs known antibiotics |
| `validity` | real | RDKit parse | 0/1 |
| `structural_alerts` | real | PAINS + toxicophore filter | 0-1 |
| `hemolysis_safety` | proxy | curated rule | 0-1 |
| `lipinski_pass` | real | RDKit | 0/1 |
| `permeability` | proxy | TPSA / MW model | 0-1 |
| `metabolic_stability` | proxy | rule-based | 0-1 |
| `robustness` | real | resistance escape map | per target PDB |

**Real** = direct chemistry computation. **Proxy** = model approximation (clearly badged so the user knows what's authoritative).

The **Resistance Escape Map** runs a chemistry-aware predictor against curated CARD clinical mutations to compute per-atom vulnerability + propose hardening swaps via two channels (curated medchem playbook + AI-bespoke).

▶ Visual: radar chart with the 12 axes labeled around the perimeter, two overlaid polygons (current candidate + champion) for comparison.

---

## CHAMPION TABLE — Per-pathogen reigning best

For each of the 8 priority pathogens, the system maintains a **reigning champion** SMILES that auto-promotes when a new candidate beats it on the configured score axis (default: `fitness = composite × robustness`).

| Pathogen | Drug class focus | Validated targets |
|---|---|---|
| MRSA | β-lactams, vancomycin alternatives | PBP2a (1VQQ), MurA (1A2N) |
| Mtb | BPaLM combo, novel targets | InhA (2X22), DprE1 (4FDO) |
| EColi-CRE | Carbapenem-resistant | KPC-2, OXA-48 |
| KpneuCRE | Carbapenemases | KPC, OXA-48 |
| Abaum | Sulbactam-durlobactam class | OXA-23 |
| Paer | Anti-Pseudomonas | MexAB-OprM efflux, OprD |
| VRE | Cell-wall + ribosome | vanA Tn1546, cfr |
| NGono | Cephalosporin-resistant | PBP2 (penA) |

Each pathogen card shows: SMILES, composite, robustness, fitness, rationale, last-promoted timestamp. **A/B compare** any new candidate against the reigning champion with per-axis Δ bars.

▶ Visual: 2×4 grid of trophy-cards, one per pathogen. Active pathogen (MRSA) highlighted.

---

## KNOWLEDGE BRIEF — How agents stay grounded

Every Designer/Critic/Editor/Strategist LLM call gets a **per-pathogen knowledge brief** auto-injected into its prompt:

```
# Methicillin-resistant Staphylococcus aureus (MRSA) — pathogen brief

Common syndromes: bacteremia, endocarditis, pneumonia, SSTI, osteomyelitis

Intrinsic features: gram-positive cocci; low-affinity PBP2a (mecA);
                    biofilm-forming on hardware

Clinical context: mecA/PBP2a is the defining feature. Ceftaroline is the
                  only cephalosporin active vs MRSA via allosteric PBP2a binding.

First-line therapy (avoid me-too compounds in this space):
  - vancomycin AUC 400-600
  - daptomycin 8-12 mg/kg
  - linezolid (preferred for pneumonia)
  - ceftaroline (anti-MRSA ceph)

Top resistance threats:
  - mecA / PBP2a — alters target binding (hits all_beta_lactams_except_anti_MRSA_cephs)
  - Erm A/B/C — methylates 23S rRNA (hits macrolides, lincosamides, streptogramin_B)
  - tetK / tet(M) — efflux + ribosome protection (hits tetracyclines)
  - blaZ / penicillinase — hydrolyzes β-lactam ring (hits penicillin_G)

Validated targets:
  - PBP2a (Penicillin Binding Protein 2a) — PDB 1VQQ
  - MurA (UDP-N-acetylglucosamine 1-carboxyvinyltransferase) — PDB 1A2N

Reasoning rules for this pathogen:
  1. Avoid scaffolds that overlap with first-line drugs (cross-resistance risk).
  2. Anticipate top resistance mechanisms — bake escape into your design.
  3. Prefer drug classes with low pressure scores.
  4. Cite the specific resistance gene by name when justifying a critique.
```

Brief is cached 5 minutes per pathogen, served from `/workbench/knowledge/{pathogen}`. Same brief feeds the Knowledge tab's command-center card so the user sees exactly what the agent sees.

▶ Visual: a screenshot of the Knowledge tab's "View agent brief" panel rendered with bold + bullets.

---

## RESISTANCE NETWORK — 4-tier graph

```
               ┌──────────────────┐
               │      MRSA        │   ← TIER 0 · pathogen
               │  (purple node)   │
               └─────────┬────────┘
            ┌────────────┼────────────┐
            ▼            ▼            ▼
      ┌──────────┐  ┌──────────┐  ┌──────────┐
      │  mecA /  │  │ Erm A/B/C│  │  tetK /  │   ← TIER 1 · resistance genes
      │  PBP2a   │  │          │  │  tet(M)  │      (red nodes)
      └─────┬────┘  └────┬─────┘  └────┬─────┘
            │ blocks     │ blocks      │ blocks
            ▼            ▼             ▼
   ┌──────────────┐  ┌─────────────────┐  ┌─────────────────┐
   │ all_beta_    │  │ macrolides      │  │ tetracyclines   │   ← TIER 2 · drug classes
   │ lactams      │  │ + lincosamides  │  │                 │      (orange)
   │ (except MRSA │  │ + streptogram B │  │                 │
   │ cephs)       │  │                 │  │                 │
   └──────────────┘  └─────────────────┘  └─────────────────┘

   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │ vancomycin   │  │ daptomycin   │  │ linezolid    │  │ ceftaroline  │   ← TIER 3 · first-line
   │  AUC 400-600 │  │ 8-12 mg/kg   │  │ pneum.pref   │  │ anti-MRSA    │      (green)
   └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
```

Click any gene node → fires `/explain <gene>` for full context. Click a drug node → loads its SMILES into the workspace.

▶ Visual: the SVG graph from the screenshot, rendered cleanly with the 4 colored tiers and labels.

---

## DEPLOYMENT — vllm on MI300X

```
                ┌──────────────────────────────────────────────────┐
                │  AMD MI300X droplet (amd.digitalocean.com)        │
                │  ROCm 7.0 · 192 GB HBM3 · Ubuntu 24.04            │
                │                                                  │
                │  ┌────────────────────────────────────────────┐  │
                │  │  rocm/7.0_pytorch_training_instinct        │  │
                │  │  (docker container — ROCm-built PyTorch    │  │
                │  │   already in place)                        │  │
                │  │                                            │  │
                │  │   pip install vllm                         │  │
                │  │     ↓                                      │  │
                │  │   python -m vllm.entrypoints.openai.       │  │
                │  │     api_server                             │  │
                │  │     --model google/gemma-4-31B-it          │  │
                │  │     --enable-lora                          │  │
                │  │     --lora-modules                         │  │
                │  │       lysos=rahul24raj/lysos-base-dpo      │  │
                │  │     --port 8000 --host 0.0.0.0             │  │
                │  │     --gpu-memory-utilization 0.92          │  │
                │  │     --dtype bfloat16                       │  │
                │  └────────────────────────────────────────────┘  │
                │                                                  │
                └──────────────────────┬───────────────────────────┘
                                       │  OpenAI-compatible chat API
                                       ▼
                ┌──────────────────────────────────────────────────┐
                │  FastAPI backend (LYSOS_INFERENCE_URL=...)       │
                │  routes /api/agent/run through vllm endpoint     │
                └──────────────────────────────────────────────────┘
```

**Cold start**: ~15 min (62 GB Gemma base download via HF Pro CDN).
**Hot restart**: ~2 min (cache hit on disk).
**Throughput**: ~80 tok/s steady-state at bf16, single MI300X.

▶ Visual: stacked diagram with the docker container highlighted, GPU at the bottom, dataflow arrows up.

---

## WHAT'S OPEN-SOURCE

Everything. MIT license on the code. Apache-2.0 / Gemma license terms on the model weights. CC-BY on the datasets.

| Asset | URL |
|---|---|
| GitHub repo | github.com/Rahul-Rajpurohitk/lysos |
| Stage 1 adapter | huggingface.co/rahul24raj/txgemma-4-31b |
| Stage 2 adapter | huggingface.co/rahul24raj/lysos-base |
| **Stage 2.5 adapter (production)** | **huggingface.co/rahul24raj/lysos-base-dpo** |
| Stage 2 SFT dataset | huggingface.co/datasets/rahul24raj/lysos-amr-stage2 |
| Stage 2.5 hard-negatives | huggingface.co/datasets/rahul24raj/lysos-hard-negatives-v1 |
| Demo videos | github.com/Rahul-Rajpurohitk/lysos/releases/tag/v1.0-hackathon-submission |

▶ Visual: 4-icon row (GitHub, HuggingFace, video, license) with arrow to "100% open".

---

## USE CASES

| Audience | Job-to-be-done |
|---|---|
| Hospital pharmacy researchers | "What would beat MRSA escape from ceftaroline?" → run debate, get specific atom-level harden suggestions |
| Computational chemistry teams | Hardening loop against any curated clinical mutation set on any PDB target |
| Antibiotic R&D startups | Explore chemical space they couldn't afford to brute-force; per-pathogen Champion vault tracks progress |
| Educators | Teach SAR with live agentic feedback, watch the Critic call out specific weaknesses |
| Open science | Reproducible end-to-end pipeline — every reward axis, every dataset, every weight is public |

▶ Visual: 5 user-persona cards in a row.

---

## KEY NUMBERS — Quick reference

| Metric | Value |
|---|---|
| Total deaths from AMR per year | 1.27 M (today) |
| Projected by 2050 | 10 M / year |
| Last new antibiotic class approved | 1987 |
| Lysos training data | 222,606 examples + 10,000 DPO pairs |
| Priority pathogens covered | 8 |
| Validated PDB targets | 16+ across pathogens |
| Reward axes scored per candidate | 12 (mix of real + proxy) |
| Streaming workflows | 7 |
| Slash commands | 12+ |
| LLM agents collaborating | 5 (Designer, Critic, Editor, Strategist, Orchestrator) |
| Backend routes | 140+ FastAPI endpoints |
| Lines of frontend TypeScript/React | ~25,000 |
| Total wall-clock for 3-stage fine-tune | ~6 hours on 1 MI300X |
| Cost per debate round | ~$0.005 |
| Inference throughput | ~80 tok/s bf16 single MI300X |

▶ Visual: stat-blocks grid, 3 columns × 5 rows.

---

## DEMO FLOW — What the videos show

**Video 1 · Agentic flow (0:44)**
Multi-agent debate triggered, 4 roles light up the Agents tab in real-time. Cost meter ticks. Cross-agent handoff edges fill in.

**Video 2 · System tour (3:04)**
Knowledge tab → resistance network → click a gene → `/explain` brief renders. Switch to Chemistry → 2D builder → 3D pocket. Run a workflow.

**Video 3 · Full walkthrough (5:04)**
Training story → live system → harden a candidate → score updates → Pareto frontier → champion vault. End-to-end agentic loop.

**Merged (9:08)** — all three concatenated for the lablab submission.

▶ Visual: three video thumbnails in a row + arrow to merged.

---

## CALL TO ACTION

> **Lysos is open-source, end-to-end, reproducible, and live.**
>
> Clone the repo. Pull the model. Fire up the workspace.
> Generate a candidate against your favorite resistant pathogen in 25 seconds.
>
> AMR doesn't wait. Neither does this stack.

▶ Visual: huge "github.com/Rahul-Rajpurohitk/lysos" QR code + closing tagline. AMD MI300X badge bottom-right. Hackathon 2026 ribbon.

---

## APPENDIX A · Slide deck structure recommendation

20-slide deck flow:

1. Title
2. The problem (1.27M deaths)
3. The opportunity (Gemma 4 + MI300X)
4. What we built (3 pillars)
5. Stage 1 — TxGemma-4
6. Stage 2 — Lysos-base SFT
7. Stage 2.5 — DPO alignment
8. Why MI300X is load-bearing
9. The multi-agent debate
10. The orchestrator
11. Live workspace tour (5 containers)
12. Architecture diagram
13. Data flow — debate end-to-end
14. Reward stack — 12 axes
15. Champion table
16. Knowledge brief
17. Resistance network
18. Deployment (vllm on MI300X)
19. Open-source assets
20. Call to action + key numbers

---

## APPENDIX B · Style notes for the design tool

- Color system: **dark gradient backgrounds (#0a0a14 → #1a1a2e)** with **purple/lavender accents (#8458ff)** for the agentic theme. **AMD red (#ED1C24)** for hackathon callouts. **Green (#39e08e)** for "real chemistry" / validated. **Amber (#f59e0b)** for "proxy" / approximate.
- Typography: clean sans-serif for body (Inter / SF Pro), monospace for SMILES + technical IDs (JetBrains Mono).
- Diagrams: flat 2D, no 3D illustrations. Connectors as solid lines with arrows at endpoints. Subtle drop shadows on cards.
- Density: each slide should fit on one screen at 1080p without scrolling. Use the H3 sub-sections to split if needed.
- Don't add stock photography. Use schematic chemistry — hexagons, tier-graphs, bar charts, radar charts.
