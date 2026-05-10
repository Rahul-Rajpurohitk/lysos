# Lysos

> **Open-source generative antibiotic designer for the AMR pandemic.
> Three-stage fine-tune of Gemma 4 31B-it on AMD MI300X. Multi-agent debate engine. End-to-end live agentic workspace.**

[![Hackathon](https://img.shields.io/badge/AMD%20Developer%20Hackathon-2026-red)](https://lablab.ai)
[![Track](https://img.shields.io/badge/Track%202-Fine--Tuning%20on%20AMD%20GPUs-orange)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()
[![Model](https://img.shields.io/badge/HF%20Model-rahul24raj%2Flysos--base--dpo-yellow)](https://huggingface.co/rahul24raj/lysos-base-dpo)
[![Dataset](https://img.shields.io/badge/HF%20Dataset-rahul24raj%2Flysos--amr--stage2-yellow)](https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2)

---

## TL;DR

Lysos is an end-to-end **open-source antibiotic discovery platform** that takes Google's
**Gemma 4 31B-it** and specializes it for antimicrobial-resistance (AMR) drug design via a
three-stage fine-tune on a single **AMD MI300X**. The fine-tuned Gemma model is wrapped in a
**multi-agent debate engine** (Designer / Critic / Editor / Strategist) and served behind
a live agentic workspace with **5 containers, 12+ slash commands, 7 streaming workflows, and
real-time per-atom resistance scoring** against curated CARD clinical mutations.

Every component is open. Every weight is on Hugging Face. Every dataset is on Hugging Face.
The video walkthrough is on this repo's release page.

---

## Demo videos

| # | Title | Duration | Direct link |
|---|---|---|---|
| **▶ Merged** | Full demo (recommended) | 9:08 | [lysos-demo-merged.mp4](https://github.com/Rahul-Rajpurohitk/lysos/releases/download/v1.0-hackathon-submission/lysos-demo-merged.mp4) |
| 1 | Agentic flow | 0:44 | [lysos-demo-1-agentic-flow.mp4](https://github.com/Rahul-Rajpurohitk/lysos/releases/download/v1.0-hackathon-submission/lysos-demo-1-agentic-flow.mp4) |
| 2 | System tour | 3:04 | [lysos-demo-2-system-tour.mp4](https://github.com/Rahul-Rajpurohitk/lysos/releases/download/v1.0-hackathon-submission/lysos-demo-2-system-tour.mp4) |
| 3 | Full walkthrough | 5:04 | [lysos-demo-3-full-walkthrough.mp4](https://github.com/Rahul-Rajpurohitk/lysos/releases/download/v1.0-hackathon-submission/lysos-demo-3-full-walkthrough.mp4) |

All four are attached to the [v1.0-hackathon-submission release](https://github.com/Rahul-Rajpurohitk/lysos/releases/tag/v1.0-hackathon-submission).

---

## Why Lysos exists

**Antimicrobial resistance is the silent pandemic.**

- **1.27 million deaths every year — today** (WHO)
- **Projected 10 million per year by 2050** (UN)
- **Last fully novel antibiotic class approved: 1987**
- Pharma has largely abandoned antibiotic R&D — too expensive, too slow, too low-margin
- Without working antibiotics, routine surgery, childbirth, cancer chemo, and ICU stays become deadly

We need a new tool. **Lysos generates novel antibacterials against drug-resistant pathogens in seconds, on a single GPU, with publicly verifiable activity scores.** It is open-source end-to-end, built on the latest Gemma 4 frontier model, fine-tuned in three stages on AMD MI300X, and deployed via vllm at an OpenAI-compatible endpoint.

---

## What Lysos does — one paragraph

You type a free-text prompt like *"design a molecule that beats MRSA escape from ceftaroline."* The Lysos orchestrator classifies the intent and delegates to a streaming workflow. Inside the workflow, four agents take turns: **Designer** drafts three candidate SMILES with rationales, **Critic** challenges each one and names the single biggest weakness, **Editor** applies the surgical SAR fix the Critic flagged, **Strategist** picks the winner plus a runner-up plus the next action. Each role is a separate LLM call. Every action is recorded with token cost, p50/p95/p99 latency, and cross-agent handoff edges. The winner SMILES auto-loads to a live 2D builder, a 3D pocket viewer with the docked pose, a per-atom resistance escape map keyed against curated clinical mutations, a 12-axis reward radar, and a per-pathogen Champion table that auto-promotes if the new candidate beats the reigning best. Then you can `/wf harden_candidate`, `/wf compare_top_n`, `/wf pareto_explore` — each is its own SSE-streamed workflow with its own Critic-narrated verdict. The fine-tuned Gemma model behind it all serves from the same MI300X via vllm.

---

## The three-stage fine-tune of Gemma 4 31B on MI300X

Every stage trains a LoRA adapter on top of `google/gemma-4-31B-it`. All adapters are public on Hugging Face.

```
                              google/gemma-4-31B-it (62 GB base)
                                           │
       ┌───────────────────────────────────┼───────────────────────────────────┐
       │                                   │                                   │
   STAGE 1                              STAGE 2                            STAGE 2.5
TxGemma-4 31B (LoRA r=64)         lysos-base (LoRA r=64)             lysos-base-dpo (LoRA r=32)
continued pretraining             SFT on 222,606 AMR examples         DPO on hard-negative pairs
for therapeutics                  (8 priority pathogens)              (10 anti-correlated axes)
~2 hr on 1× MI300X                ~3 hr on 1× MI300X                  ~45 min on 1× MI300X
```

| Stage | HF repo | Purpose | Adapter | Wall-clock |
|---|---|---|---|---|
| **Stage 1** | [`rahul24raj/txgemma-4-31b`](https://huggingface.co/rahul24raj/txgemma-4-31b) | Continued pretraining on therapeutic literature, ChEMBL, drug-target databases | LoRA r=64, α=256 | ~2 hr |
| **Stage 2** | [`rahul24raj/lysos-base`](https://huggingface.co/rahul24raj/lysos-base) | Supervised fine-tuning on **222,606** AMR examples (8 priority pathogens, MIC values, SAR) | LoRA r=64, α=128 | ~3 hr |
| **Stage 2.5** | [`rahul24raj/lysos-base-dpo`](https://huggingface.co/rahul24raj/lysos-base-dpo) | DPO alignment on **10,000** hard-negative Pareto-trap pairs across 10 anti-correlated reward axes | LoRA r=32, α=64 (β=0.1) | ~45 min |

**The dataset behind Stage 2** ([`lysos-amr-stage2`](https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2)) covers ChEMBL bioactivity records filtered to AMR-active scaffolds, MIC labels per pathogen, drug-class SAR reports, literature-mined examples, and curated negative controls. **The dataset behind Stage 2.5** ([`lysos-hard-negatives-v1`](https://huggingface.co/datasets/rahul24raj/lysos-hard-negatives-v1)) is a curated set of 10,000 (preferred, dispreferred) preference pairs where the dispreferred candidate is a Pareto-trap (maxes one axis, fails another), and the preferred candidate is Pareto-balanced.

### Why DPO instead of GRPO?

We initially planned a Stage 3 GRPO run for full RL alignment. After the first attempt we hit:

- **Reward hacking** — the novelty axis on raw embedding distance was being gamed with low-information SMILES that scored high
- **KL drift after step 200** — base capability eroding, the model "forgetting" how to write valid SMILES
- **Reward signal too noisy** for online RL on the available hardware budget

Stage 2.5 DPO replaced it. **DPO directly teaches the model to prefer Pareto-balanced candidates** over candidates that maximize one axis at the cost of others. Stabler signal, faster convergence, no reward hacking, full base capability preserved. The DPO objective matches our actual goal — relative preference over Pareto pairs — better than per-step reward maximization ever did.

---

## Why the AMD MI300X is load-bearing

The single decision that made this submission tractable.

| GPU | VRAM | Can fit Gemma 4 31B bf16 + LoRA + KV cache + agent context coresident? |
|---|---|---|
| H100 SXM | 80 GB | ❌ requires sharding / smaller base |
| H200 | 141 GB | ⚠ tight, no headroom for serving |
| **MI300X** | **192 GB HBM3** | **✅ all coresident, comfortable** |

**What the MI300X enables**:

- **Coresident training and serving** — the same GPU that trains also serves inference, no migration step, no second machine, no cold-storage round-trip
- **No tensor parallelism** — code is single-process, ROCm-native PyTorch, simpler deploy, fewer failure modes
- **Headroom for the agent context** — a workflow can hold the resistance map + scoring history + chat memory + LoRA weights all at once
- **8K+ context length** at full bf16 with LoRA active

**Total wall-clock for the three-stage fine-tune: ~6 hours on 1 GPU.**

---

## The multi-agent debate engine

When the user fires `/wf design_with_debate` (or types something like *"design a molecule for MRSA"* and the orchestrator routes it there), four agent roles take turns. Each role is a **separate LLM call** with a role-specific system prompt.

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

Every call is recorded into a ring buffer that drives the live Agents tab:

- `role`, `action_type`, `message`, `confidence`
- `tokens_in`, `tokens_out`, `cost_usd`
- `elapsed_ms`, `status` (ok / error)
- `triggered_by` (the previous role — drives the cross-agent handoff graph)

The user watches the debate happen in real time — **flow graph animates, cost meter ticks up, latency p50/p95/p99 distributions populate per role**. This is the "agentic flow" video.

### The orchestrator agent

In front of all of this sits a **routing agent** that classifies free user text into one of four execution paths:

| Route | When to use | Example |
|---|---|---|
| `workflow` | Multi-step plan that needs streaming | *"design a molecule"* → `/wf design_with_debate` |
| `slash` | Single command, fast path | *"score this"* → `/score <smiles>` |
| `agent` | Open-ended Q with tool calling | *"tell me about mecA"* → tool-calling agent |
| `answer` | Direct prose, no tool needed | *"what's a Pareto frontier?"* |

Routing decision is itself an LLM call. The user sees the rationale, tokens, and elapsed time in the chat — they can audit *why* the orchestrator picked the path.

---

## The live agentic workspace

```
       ┌──────────────────────────────────────────────────────────────────────────┐
       │  CHAT COMPOSER  ·  /slash palette  ·  + workflow palette                 │
       │  (free text → orchestrator,  /slash → harness,  /wf → SSE workflow)      │
       └────────┬───────────────────────────────────────────────────────┬─────────┘
                │                                                       │
                ▼                                                       ▼
   ┌──────────────────────────────┐                ┌──────────────────────────────┐
   │   LEFT  · chat thread         │                │   RIGHT  · 5 containers      │
   │   ─ user messages              │                │   1. Chemistry  ───┐        │
   │   ─ workflow cards (live SSE)  │                │   2. Scoring       │        │
   │   ─ proposal cards             │                │   3. Agents        │ tabs   │
   │   ─ champion promotion         │                │   4. Knowledge     │        │
   │   ─ score / SAR / compare      │                │   5. Report      ──┘        │
   │     cards                      │                │                              │
   └──────────────────────────────┘                └──────────────────────────────┘
```

| Container | What's inside |
|---|---|
| **Chemistry** | 2D molecule builder with click-to-edit atoms · 3D pocket theater (target picker, halos, contacts) · Resistance escape map (per-atom vulnerability, harden suggestions, side-by-side comparison) · Pareto lab (frontier, axis pickers, dominator explainer) |
| **Scoring** | 12-axis reward radar that re-fetches in real-time on every SMILES change · Score breakdown card with per-axis explanation and improvement suggestion · Atom-level structural-alert panel (PAINS, toxicophores) · Pocket pose with Boltz-2 contacts |
| **Agents** | Multi-agent activity hub · Live cost meter (cumulative LLM spend) · Flow graph (Designer → Critic → Editor → Strategist) · Cross-agent handoff edges · Per-role KPI cards (latency, ok rate, confidence) · Time-spent stacked bar · Latency p50/p95/p99 distributions · Action log filterable by agent + status · Role inspector drilldown |
| **Knowledge** | Pathogen command center · 8×12 pathogen × drug-class pressure heatmap · 4-tier resistance gene network (pathogen → genes → drug classes → first-line therapy) · Mutation atlas per validated PDB · Champion vault (all 8 reigning champions across pathogens) · Antibiotic reference corpus |
| **Report** | Snapshot builder · Markdown export · PDF export · Session trace timeline · Edit log replay |

### Streaming workflows (7)

1. **`design_with_debate`** — the 4-agent debate (the killer demo)
2. **`harden_candidate`** — find weak atoms + AI-bespoke + curated swap suggestions
3. **`compare_top_n`** — side-by-side + Critic narration with axis Δ
4. **`pareto_explore`** — frontier + Critic verdict (advance / A-B / drop / next_action)
5. **`broad_spectrum_screen`** — cross-target spectrum classification
6. **`optimize_for_property`** — single-axis push iterative editor
7. **`discover_and_assess`** — bulk candidate sweep

### Slash commands (12+)

`/design`, `/edit`, `/score`, `/explain`, `/escape`, `/theater`, `/pareto`, `/champion`, `/sar`, `/stress`, `/compare`, `/library`, `/harden`, `/load`, `/swap`, `/fg`, `/datasets`, `/synth`, `/dock`, `/admet`.

---

## Architecture

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

### Reward stack — 12 axes

Every candidate is scored on 12 axes simultaneously. Composite is a weighted sum.

| Axis | Type | Source |
|---|---|---|
| `predicted_mic` | proxy | Trained model + RDKit, pathogen-specific |
| `composite_reward` | derived | Weighted sum (top-level dial) |
| `drug_likeness_qed` | real | RDKit QED (0–1) |
| `synthesizability` | proxy | SAScore / RDKit (0–1) |
| `embedding_novelty` | real | Embedding cosine vs known antibiotic corpus |
| `validity` | real | RDKit parse (0/1) |
| `structural_alerts` | real | PAINS + toxicophore filter (0–1) |
| `hemolysis_safety` | proxy | Curated rule (0–1) |
| `lipinski_pass` | real | RDKit (0/1) |
| `permeability` | proxy | TPSA / MW model (0–1) |
| `metabolic_stability` | proxy | Rule-based (0–1) |
| `robustness` | real | Per-target resistance escape map |

**Real** = direct chemistry computation. **Proxy** = model approximation (clearly badged in the UI).

The **Resistance Escape Map** runs a chemistry-aware predictor against curated CARD clinical mutations to compute per-atom vulnerability + propose hardening swaps via two channels in parallel (curated medchem playbook + AI-bespoke).

### Champion table — per-pathogen reigning best

For each of the 8 priority pathogens, the system maintains a **reigning champion** SMILES that auto-promotes when a new candidate beats it on the configured score axis (default: `fitness = composite × robustness`). Each pathogen card shows: SMILES, composite, robustness, fitness, rationale, last-promoted timestamp. **A/B compare** any new candidate against the reigning champion with per-axis Δ bars rendered live.

### Knowledge brief auto-injection

Every Designer/Critic/Editor/Strategist LLM call gets a **per-pathogen knowledge brief** auto-injected into its prompt — pathogen full name, common syndromes, intrinsic features, clinical context, first-line therapy to avoid, top resistance threats with mechanism + drug-class hits, validated PDB targets, and reasoning rules ("avoid scaffolds that overlap with first-line drugs", "prefer drug classes with low pressure scores", "cite the specific resistance gene by name"). Brief is cached 5 minutes per pathogen, served from `/workbench/knowledge/{pathogen}`. Same brief feeds the Knowledge tab's command-center card so the user sees exactly what the agent sees.

---

## Reproducibility

All training data, configs, and model weights are public:

| Asset | URL |
|---|---|
| Stage 2 SFT dataset (222,606 AMR examples) | <https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2> |
| Stage 2.5 hard-negatives (10K Pareto-trap pairs) | <https://huggingface.co/datasets/rahul24raj/lysos-hard-negatives-v1> |
| Stage 1 adapter | <https://huggingface.co/rahul24raj/txgemma-4-31b> |
| Stage 2 adapter | <https://huggingface.co/rahul24raj/lysos-base> |
| **Stage 2.5 adapter (production)** | <https://huggingface.co/rahul24raj/lysos-base-dpo> |
| Training configs | [`configs/`](configs/) — `stage2_amr_sft.yaml`, `stage2_5_dpo.yaml`, `base.yaml` |

---

## How to run it

### Local backend + frontend (~2 min)

```bash
git clone https://github.com/Rahul-Rajpurohitk/lysos.git
cd lysos

# Backend (FastAPI + RDKit)
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn workspace.api.server:app --host 0.0.0.0 --port 7860 &

# Frontend (React + Vite)
cd workspace/web
npm install
npm run dev
# Open http://localhost:5173
```

**Required env vars** (`.env` at repo root):

- `HF_TOKEN` — write scope, for pushing artifacts and pulling private weights
- `WANDB_API_KEY` — for training run telemetry (optional)
- An LLM API key for the agentic orchestrator (see `docs/API_KEYS_AND_ACCESS.md`)

### AMD MI300X — train and serve

```bash
# Provision an MI300X droplet on amd.digitalocean.com using the
# rocm/7.0_pytorch_training_instinct base image. SSH in, then:

bash scripts/vm_bootstrap.sh                           # ROCm check, deps, HF cache prewarm
bash scripts/run_training_pipeline.sh                  # Stage 2 → 2.5 chain
bash scripts/serve_lysos_vllm.sh --hub --stage 2.5     # vllm on :8000
```

The serve script runs INSIDE a docker container based on `rocm/7.0:rocm7.0_pytorch_training_instinct_20250915`, so the ROCm-built PyTorch is already in place. The container loads `google/gemma-4-31B-it` plus the `rahul24raj/lysos-base-dpo` LoRA adapter and serves an OpenAI-compatible chat completions API.

**Cold start**: ~15 min (62 GB Gemma base download via HF Pro CDN).
**Hot restart**: ~2 min (cache hit on disk).
**Throughput**: ~80 tok/s steady-state at bf16, single MI300X.

---

## Repo layout

```
lysos/
├── README.md                           ← you are here
├── docs/
│   ├── TECH_DOC_FOR_SLIDES.md          ← detailed technical doc for slide creation
│   ├── demo-video-script-90s.md        ← 90s shoot script
│   ├── API_KEYS_AND_ACCESS.md          ← env var setup
│   └── submission-writeup.md
├── configs/
│   ├── base.yaml                       ← shared training defaults
│   ├── stage2_amr_sft.yaml             ← Stage 2 SFT
│   └── stage2_5_dpo.yaml               ← Stage 2.5 DPO
├── scripts/
│   ├── vm_bootstrap.sh                 ← AMD VM one-shot setup
│   ├── deploy_to_vm.sh                 ← rsync + bootstrap + tmux launch
│   ├── run_training_pipeline.sh        ← Stage 2 → 2.5 chain
│   ├── serve_lysos_vllm.sh             ← vllm serve from merged or LoRA
│   ├── verify_keys.py                  ← env var sanity check
│   └── mine_hard_negatives.py          ← Stage 2.5 dataset miner
├── workspace/
│   ├── api/                            ← FastAPI backend
│   │   ├── server.py
│   │   ├── workbench.py                ← 140+ chem endpoints
│   │   ├── chat.py                     ← /api/chat harness entry
│   │   ├── orchestrator.py             ← router + delegate
│   │   ├── workflows.py                ← 7 streaming workflows
│   │   ├── debate.py                   ← multi-agent role wrappers
│   │   ├── champions.py                ← per-pathogen champion table
│   │   ├── knowledge.py                ← pathogen knowledge brief + matrix + network
│   │   ├── chem_3d.py                  ← target picker, place-in-pocket
│   │   ├── chem_resistance.py          ← CARD predictor, escape map, harden
│   │   ├── chem_pareto.py              ← Pareto frontier, score-missing
│   │   └── agent_activity.py           ← in-process agent ring buffer + SSE
│   ├── agents/
│   │   ├── commands.py                 ← 12+ slash command registry
│   │   └── harness/orchestrator.py     ← session state + chat dispatch
│   ├── tools/                          ← per-tool implementations
│   ├── training/                       ← Stage 2 + 2.5 trainers
│   ├── playground/                     ← sqlite store, sandbox runtime
│   └── web/                            ← React + Vite frontend
│       ├── src/workbench/v3/
│       │   ├── WorkbenchV3.tsx         ← top-level shell
│       │   ├── playground/             ← Chemistry / Scoring / Knowledge cards
│       │   └── components/chat/        ← chat composer + cards
│       └── package.json
├── data/processed/                     ← training parquets (gitignored, on HF)
└── pyproject.toml
```

---

## What is open-source

Everything. **MIT license** on the code. **Apache-2.0 / Gemma license terms** on the model weights. **CC-BY** on the datasets. No closed components, no SaaS lock-in, no proprietary dependencies. The full training pipeline + the agentic harness + the chemistry scoring + the FastAPI backend + the React frontend + the deployment scripts all ship in this repo.

---

## Use cases

| Audience | Job-to-be-done |
|---|---|
| Hospital pharmacy researchers | *"What would beat MRSA escape from ceftaroline?"* → run debate, get specific atom-level harden suggestions |
| Computational chemistry teams | Hardening loop against any curated clinical mutation set on any PDB target |
| Antibiotic R&D startups | Explore chemical space they couldn't afford to brute-force; per-pathogen Champion vault tracks progress |
| Educators | Teach SAR with live agentic feedback, watch the Critic call out specific weaknesses |
| Open science | Reproducible end-to-end pipeline — every reward axis, every dataset, every weight is public |

---

## Built for

[**AMD Developer Hackathon 2026**](https://lablab.ai) — Track 2: Fine-Tuning on AMD GPUs

Submission release: [v1.0-hackathon-submission](https://github.com/Rahul-Rajpurohitk/lysos/releases/tag/v1.0-hackathon-submission)

---

## License

MIT — see [LICENSE](LICENSE).
