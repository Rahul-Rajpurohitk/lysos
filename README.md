# Lysos

> **The open-source AI antibiotic design lab.**
> A 31B-parameter frontier model, specialized for antimicrobial resistance and
> trained on a single AMD MI300X, wrapped in a transparent multi-agent design
> loop and 25 real chemistry engines. Type what you want to beat. Get ranked,
> novel, scored drug candidates in seconds.

[![License](https://img.shields.io/badge/license-MIT-green)]()
[![Model](https://img.shields.io/badge/HF%20Model-rahul24raj%2Flysos--base--dpo-yellow)](https://huggingface.co/rahul24raj/lysos-base-dpo)
[![Dataset](https://img.shields.io/badge/HF%20Dataset-rahul24raj%2Flysos--amr--stage2-yellow)](https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2)
[![Base](https://img.shields.io/badge/base-Gemma%204%2031B-blue)]()
[![Hardware](https://img.shields.io/badge/trained%20on-AMD%20MI300X-red)]()

---

## What Lysos is

Lysos is an end to end, open-source antibiotic discovery platform. It takes
Google's **Gemma 4 31B-it**, specializes it for antimicrobial-resistance (AMR)
drug design through a staged fine-tune on a single **AMD MI300X**, and serves
that model behind a live agentic workspace: a multi-agent debate engine
(Designer, Critic, Editor, Strategist), 25 real chemistry services, real-time
per-atom resistance scoring against curated clinical mutations, and a 12-axis
reward stack where every number is labeled real or proxy.

Every component is open. Every weight is on Hugging Face. Every dataset is on
Hugging Face. No closed core, no SaaS lock-in.

---

## Why Lysos exists

Antimicrobial resistance is the silent pandemic.

- **1.27 million deaths every year, today** (WHO).
- **Projected ~10 million deaths per year by 2050** (UN).
- **The last fully novel antibiotic class was approved in 1987.** The pipeline
  is effectively dry.
- The economics are broken. Antibiotics are taken for days, priced low, and the
  best ones are held in reserve, so developers cannot recoup a decade and a
  billion dollars of R&D. Big pharma has largely exited the field.
- Without working antibiotics, routine surgery, childbirth, chemotherapy,
  transplants, and ICU care all become high-mortality.

The tools that could help are either closed and expensive or low-level libraries
that are not a usable product. Nothing open, agentic, and resistance-first
existed. Lysos is that thing: it generates novel antibacterials against
drug-resistant pathogens in seconds, on a single GPU, with publicly verifiable
activity scores.

---

## What it does, in one paragraph

You type a free-text prompt like *"design a molecule that beats MRSA escape from
ceftaroline."* The orchestrator classifies the intent and routes it to a
streaming workflow. Inside, four agents take turns: **Designer** drafts three
candidate SMILES with rationales, **Critic** challenges each one and names the
single biggest weakness, **Editor** applies the surgical SAR fix the Critic
flagged, **Strategist** picks the winner plus a runner-up plus the next action.
Each role is a separate LLM call, and every action is recorded with token cost,
p50/p95/p99 latency, and cross-agent handoff edges. The winning SMILES
auto-loads into a 2D builder, a 3D pocket viewer with the docked pose, a per-atom
resistance escape map keyed to curated clinical mutations, a 12-axis reward
radar, and a per-pathogen champion table that auto-promotes when a new candidate
beats the reigning best. From there you can run `/harden`, `/compare`,
`/pareto`, send it through PK/PD attainment, ADMET, synthesis route, and
freedom-to-operate, and roll it all into one developability dossier. Nothing
dead-ends. Every result drives the next action.

---

## The product surface

A chat-first workspace. Free text goes to the orchestrator, `/slash` runs a fast
command, `/wf` runs a streamed workflow. The right side holds five containers.

| Container | What's inside |
|---|---|
| **Chemistry** | 2D builder with click-to-edit atoms, 3D pocket theater (target picker, docked pose, contacts, 2D-formula inset), resistance escape map, Pareto lab, and the full service catalog (peptide lab, bioisostere studio, PK/PD, chemical space, and more) |
| **Scoring** | 12-axis reward radar that re-computes live on every edit, per-axis breakdown with an improvement suggestion, structural-alert panel, pocket pose |
| **Agents** | Live cost meter, Designer to Critic to Editor to Strategist flow graph, cross-agent handoff edges, per-role KPI cards, latency p50/p95/p99 distributions, filterable action log |
| **Knowledge** | Pathogen command center, 8x12 pathogen by drug-class pressure heatmap, 4-tier resistance-gene network, mutation atlas per validated PDB, champion vault, antibiotic reference corpus |
| **Report** | Snapshot builder, Markdown and PDF export, session trace timeline, edit-log replay |

---

## The chemistry engine: 25 services

Every service is built to the same six-layer contract (persistence, backend
module, agent tool, workflow, orchestrator entry, frontend card plus dossier
facet) and carries honest provenance: every output is labeled **real** (direct
chemistry computation) or **proxy** (model approximation), never a fabricated
unit.

| Service | What it does | Basis |
|---|---|---|
| **Scoring / Reward** | 12-axis composite, live on every edit, with per-axis drilldown | RDKit + trained model |
| **3D Target-Ligand Theater** | Protein pocket viewer, target picker, place-in-pocket, contacts, 2D inset | NGL.js + cached PDBs |
| **Docking** | Real binding-energy (ΔG) estimate plus a posed ligand in the pocket | AutoDock Vina (NumPy port) |
| **Resistance-Escape Map** | Per-atom vulnerability vs curated CARD clinical mutations, hardening via curated playbook plus AI-bespoke, side-by-side compare, robustness trajectory | chemistry-aware predictor |
| **Resistome / AMR Landscape** | Population-level pathogen by drug-class resistance-pressure heatmap | curated CARD data |
| **Bioisostere Studio** | Matched-molecular-pair lead-opt: 21 real RDKit transforms, each analog scored and profiled across 10 physicochemical descriptors, swap site highlighted on the structure, liability flags, sort/filter, one-tap apply | RDKit + MCS swap detection |
| **Peptide Lab (AMP)** | Antimicrobial-peptide design: helical wheel with the Eisenberg hydrophobic-moment vector and hydrophobic-face wedge, per-residue hydrophobicity/charge/face track, net charge, amphipathicity, hemolysis, therapeutic index, de-novo AMP generation | real biophysics |
| **Generator** | De-novo and lead-opt molecular generation | BRICS (GenMol planned) |
| **Synthesis Make-Route** | A real, reasoned retrosynthetic route plus cost, with a saved-route shelf | AiZynthFinder |
| **IP / FTO Sentinel** | Freedom-to-operate: patent panel, prior-art corpus, a design-around escape variant | prior-art + RDKit |
| **ADMET Observatory** | Five-axis pharmacokinetic and safety panel | ADMET-AI |
| **PK/PD Simulator** | Steady-state exposure vs MIC, the class's governing PK/PD index, Monte-Carlo PTA to breakpoint | Pop-PK + MC-PTA |
| **Chemical-Space Navigator** | Projects the candidate into chemical space, finds nearest known antibiotics, scores novelty | ChemBERTa/MoLFormer |
| **Property-Space Dashboard** | Places the candidate's physicochemistry against the distribution of ~30k known antibiotics | RDKit + reference corpus |
| **Combination & Adjuvant Lab** | Mechanism-matched synergy design | mechanism pairing |
| **Spectrum** | Broad vs narrow spectrum classification across pathogens | cross-target classifier |
| **Permeability / Entry** | Gram-negative entry (porin uptake, efflux) | rule + descriptor model |
| **Metabolism** | Metabolic soft-spot and lability detection | rule-based |
| **Shape** | Membrane-relevant 3D shape (NPR1/NPR2, radius of gyration, asphericity) | RDKit Descriptors3D |
| **Pareto Lab** | Multi-candidate frontier with axis pickers and a dominator explainer | scoring pipeline |
| **Candidate Dossier** | The integration backbone: pulls every service's output into one developability dossier (radar plus facets) | aggregates all services |
| **Champion Table** | Per-pathogen reigning best, auto-promoted on `fitness = composite x robustness`, A/B vs champion with per-axis Δ | champion store |
| **Knowledge Hub** | Pathogen command center, pressure matrix, resistance-gene network, mutation atlas, antibiotic reference | curated knowledge base |
| **Validation / Trust** | Retrospective check that the scorer ranks known actives above decoys | benchmark harness |
| **Campaign** | The first-class object a discovery team works in, plus an autonomous planner-executor-verifier harness | campaign engine |

---

## The model: staged fine-tune of Gemma 4 31B on AMD MI300X

Each stage trains a LoRA adapter on top of `google/gemma-4-31B-it`. All adapters
and datasets are public.

| Stage | HF repo | Purpose | Adapter | Wall-clock |
|---|---|---|---|---|
| **Stage 1** | [`rahul24raj/txgemma-4-31b`](https://huggingface.co/rahul24raj/txgemma-4-31b) | Therapeutics foundation: chemistry vocabulary (β-lactam, MIC, PBP2a), TDC tasks | LoRA r=64, α=256 | ~2 hr |
| **Stage 2** | [`rahul24raj/lysos-base`](https://huggingface.co/rahul24raj/lysos-base) | AMR specialization SFT on **222,606** examples across 8 pathogens | LoRA r=64, α=128 | ~3 hr |
| **Stage 2.5** | [`rahul24raj/lysos-base-dpo`](https://huggingface.co/rahul24raj/lysos-base-dpo) | DPO preference alignment on **10,000** Pareto-trap pairs (the production model) | LoRA r=32, α=64, β=0.1 | ~45 min |

**Why DPO.** Supervised fine-tuning teaches the model to write plausible
molecules, but not which of two candidates is better. The downstream usage
pattern (the Strategist picking among Designer proposals) is a discrete
preference choice, which is exactly what Direct Preference Optimization
optimizes. DPO is stable (KL-bounded, no reward-model drift), resists reward
hacking (the trade-off is encoded in the pairs, not a gameable proxy), and is
sample efficient. Each preferred candidate is Pareto-balanced, each dispreferred
one is a Pareto trap that maxes one axis and fails another.

**Why the AMD MI300X.** Its 192 GB of HBM3 holds the Gemma 4 31B base in bf16,
the LoRA adapter, the KV cache, and the agent's working context all coresident
on one GPU. An 80 GB H100 cannot; even a 141 GB H200 is tight with no serving
headroom. So the same GPU trains and serves, with no tensor parallelism, no
sharding, and no migration step. Served via vLLM at an OpenAI-compatible
endpoint, around 80 tokens/sec at bf16 on a single MI300X.

The Stage-2 corpus is engineered in layers, not scraped: ChEMBL antibiotics,
antimicrobial peptides, the CARD resistance-gene catalog, natural products, plus
78,150 hand-authored teacher-distillation traces and a pharmacology Q&A layer,
quality-weighted, with a time-aware holdout to prove it is not just memorizing
recent literature.

---

## The reward / scoring stack: 12 axes

Every candidate is scored on 12 axes at once. Composite is a weighted sum.

| Axis | Weight | Type |
|---|---|---|
| predicted_mic | 0.20 | proxy |
| drug_likeness_qed | 0.10 | real |
| synthesizability | 0.10 | proxy |
| hemolysis_safety | 0.10 | proxy |
| pose_confidence | 0.10 | proxy |
| novelty (Tanimoto) | 0.08 | real |
| embedding_novelty | 0.07 | real |
| validity | 0.05 | real |
| structural_alerts | 0.05 | real |
| spectrum_breadth | 0.05 | proxy |
| resistance_robustness | 0.05 | real |
| pareto_entry | 0.05 | derived |

**Real** means direct chemistry computation. **Proxy** means a model
approximation, and the UI badges it as such. A no-fallback policy means a
component either runs at full capability or is explicitly disabled, never
silently degraded to a neutral score.

---

## Architecture

```
                       Browser (React + Vite + TypeScript, :5173)
                         chat composer, 5 containers, slash + workflow palettes
                                          |  HTTP / WS / SSE
                                          v
                       FastAPI backend (:7860)
                         /api/chat, /api/orchestrator/run [SSE]
                         /api/workflows/run [SSE], /workbench/* (140+ endpoints)
                         sqlite session + champion stores, agent-activity ring (SSE)
           +------------------------------+------------------------------+
           v                              v                              v
     RDKit / Vina /                 12-axis scoring               multi-agent debate
     ADMET-AI /                     engine                        (separate LLM calls,
     AiZynthFinder / ChemBERTa                                    recorded with cost+latency)
                                          |
                                          v
                       AMD MI300X, vLLM, Gemma 4 31B + lysos-base-dpo LoRA
                         OpenAI-compatible endpoint (:8000), ~80 tok/s bf16
```

- **Frontend:** React, Vite, TypeScript, NGL.js for WebGL 3D, bespoke SVG
  components (helical wheel, heatmaps, radars, property strips), SSE streaming.
- **Backend:** FastAPI, SQLAlchemy/SQLite, ~40 service modules, 140+ endpoints,
  an agent-activity ring buffer with SSE.
- **Chemistry:** RDKit, AutoDock Vina, ADMET-AI, AiZynthFinder, ChemBERTa /
  MoLFormer embeddings, real peptide biophysics.
- **Model and serving:** PyTorch on ROCm, LoRA/PEFT, TRL (SFT + DPO), vLLM,
  Weights & Biases telemetry.
- **Agentic layer:** a configurable LLM backend powers the orchestrator and the
  agent roles; the served domain model is the project's own fine-tuned Gemma.

---

## Trust, safety, and reliability

- **Honest provenance.** Every score is labeled real or proxy. No faked units.
- **Retrospective validation.** A built-in trust layer checks that the scorer
  ranks known actives above decoys, so credibility is measured, not asserted.
- **Responsible AI.** The training corpus uses abstracted category tokens with
  no literal harmful-agent names, the model is trained to refuse out-of-scope
  misuse, and it expresses calibrated uncertainty via a 4-tier confidence
  convention.
- **Production hardening.** Per-route rate limiting, a SMILES sanitizer that
  rejects injection, a cold-start lock so concurrent first hits cannot trigger
  two model loads, request timeouts, an LRU score cache, structured logs with
  request IDs, a CORS allow-list, and a body-size cap.

---

## The 8 priority pathogens

Lysos targets the WHO 2024 Priority Pathogen List, critical and high tiers. Each
carries a real escape mechanism the agent reasons around.

| Pathogen | Tier | Escape mechanism |
|---|---|---|
| *Staphylococcus aureus* (MRSA) | critical | mecA |
| *Mycobacterium tuberculosis* | critical | rpoB / katG |
| *E. coli* (ESBL+ / CRE) | critical | OXA-48, KPC, NDM |
| *Klebsiella pneumoniae* (CRE) | critical | KPC-producers |
| *Acinetobacter baumannii* | critical | OXA-23/24/58 |
| *Pseudomonas aeruginosa* | critical | mexAB-oprM efflux |
| *Enterococcus faecium* (VRE) | high | vanA / vanB |
| *Neisseria gonorrhoeae* | high | penA, mosaic-23S rRNA |

---

## How to run it

### Local backend + frontend (about 2 minutes)

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

Required env vars (`.env` at repo root):

- `HF_TOKEN` for pushing artifacts and pulling weights.
- An LLM API key for the agentic backend (see `docs/API_KEYS_AND_ACCESS.md`).
- `WANDB_API_KEY` for training telemetry (optional).

### AMD MI300X: train and serve

```bash
# Provision an MI300X with the rocm/7.0 pytorch training image, then:
bash scripts/vm_bootstrap.sh                           # ROCm check, deps, cache prewarm
bash scripts/run_training_pipeline.sh                  # staged training
bash scripts/serve_lysos_vllm.sh --hub --stage 2.5     # vLLM on :8000
```

Cold start is about 15 minutes (62 GB Gemma base download). Hot restart is about
2 minutes. Throughput is around 80 tok/s at bf16 on a single MI300X.

---

## Repo layout

```
lysos/
├── README.md
├── docs/                              technical docs, methods, datasheet, architecture
├── configs/                           training configs (stage1, stage2, stage2_5_dpo, base)
├── scripts/                           build, mine, train, verify, deploy
├── workspace/
│   ├── api/                           FastAPI backend
│   │   ├── server.py
│   │   ├── workbench.py               chem endpoints
│   │   ├── orchestrator.py            router + delegate
│   │   ├── workflows.py               streaming workflows
│   │   ├── debate.py                  multi-agent roles
│   │   ├── champions.py               per-pathogen champion table
│   │   ├── knowledge.py               pathogen brief + matrix + network
│   │   ├── chem_*.py                  the 25-service chemistry engine
│   │   └── agent_activity.py          agent ring buffer + SSE
│   └── web/                           React + Vite frontend
├── src/                               training + inference + reward stack
└── pyproject.toml
```

---

## What is open

Everything. MIT license on the code, Gemma license terms on the model weights,
CC-BY on the datasets. No closed components, no proprietary dependencies. The
full training pipeline, the agentic harness, the chemistry scoring, the FastAPI
backend, the React frontend, and the deployment scripts all ship in this repo.

---

## Use cases

| Audience | Job to be done |
|---|---|
| Academic AMR and computational-chemistry labs | Explore antibacterial chemical space cheaply, reproducibly, on one GPU |
| Antibiotic R&D startups | Generate and triage leads through a full vertical without a large CADD budget |
| Pharma early-discovery teams | Idea generation and fast triage upstream of expensive assays, on-prem capable for IP |
| Hospital and stewardship researchers | "What would beat this resistant strain's escape?" with atom-level harden suggestions |
| Educators and students | Teach SAR with live agentic feedback and watch the Critic call out specific weaknesses |
| Open science | A reproducible end-to-end pipeline where every reward axis, dataset, and weight is public |

---

## License

MIT, see [LICENSE](LICENSE). Built by Rahul Rajpurohit.
