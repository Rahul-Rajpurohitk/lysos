# **Lysos** — The Full Build, In Depth

*Open-source antibiotic drug-discovery agentic platform built on Gemma 4 31B-it, three-stage fine-tuned on AMD MI300X. AMD Developer Hackathon 2026, Track 2.*

This doc walks through the entire stack — fine-tuning, agentic loop, chemistry engine, frontend — in plain English plus the exact files, prompts, configs, and code paths that make each piece work.

> **Status**: living doc. Each section dated when materially updated. Incremental progress appended at the end (Part XIV onward).

---

## PART I — The Story (why this exists)

The world has 47 antibiotics in clinical development globally. Only ~12 target WHO priority pathogens. None target the full MRSA + Mtb + CRE *E. coli* + *K. pneumoniae* + *A. baumannii* + *P. aeruginosa* spectrum with a fresh mechanism. Pharma economics make this hard to fund — the antibiotic that works once but kills resistance instead of cultivating it is worth less to a balance sheet than the cancer drug that lasts a decade.

**Lysos** takes Google's Gemma 4 31B-it, specializes it for antimicrobial-resistance (AMR) drug design via a three-stage fine-tune on a single AMD MI300X, and wires that specialized model behind a multi-agent debate engine. Users design candidate molecules against priority pathogens; the agents argue, score, harden, and rank them against a 12-axis reward stack and curated CARD clinical-mutation data.

The thesis of the build: **fine-tuning + agentic UX are complementary, not substitutes**. A SFT-only model writes plausible β-lactams. An agent-only system without a domain-tuned base hallucinates mutation codes. Together, they're a research partner.

---

## PART II — The Three-Stage Fine-Tune (the heart of the submission)

### Why three stages

Standard SFT of a 31B model on 222K AMR examples teaches structure but doesn't teach *preference* — when the Strategist has to pick between two candidate molecules, SFT gives no signal which one is better, only which one is *plausible*. The downstream usage pattern is a discrete preference choice. That's exactly what DPO optimizes for. So:

```
google/gemma-4-31B-it (62 GB base, bf16, 31B params)
                         │
                         ▼
┌────────────────────────────────────────────────────────────────┐
│ STAGE 1 — Therapeutics continued pretraining                   │
│ Adapter: rahul24raj/txgemma-4-31b                              │
│ LoRA r=64, α=256                                               │
│ Data: ChEMBL+DrugBank+pharma-enrichment 218 drugs, 8K tokens   │
│ Purpose: domain-vocabulary (β-lactam, MIC, PBP2a, …)           │
│ Time: ~2 hours on 1× MI300X                                    │
└────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────────┐
│ STAGE 2 — Supervised fine-tune for chemistry+resistance        │
│ Adapter: rahul24raj/lysos-base                                 │
│ LoRA r=64, α=128                                               │
│ Data: rahul24raj/lysos-amr-stage2 (222,606 examples)           │
│ Mix: 8 priority pathogens × {design, score, explain, harden}  │
│ Purpose: instruction-follow chemistry tasks                    │
│ Time: ~3 hours on 1× MI300X                                    │
└────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────────┐
│ STAGE 2.5 — DPO preference alignment                           │
│ Adapter: rahul24raj/lysos-base-dpo (production model)          │
│ LoRA r=32, α=64, β=0.1                                         │
│ Data: rahul24raj/lysos-hard-negatives-v1 (10K Pareto pairs)    │
│ Reference: lysos-base (frozen)                                 │
│ Purpose: Strategist picks winning candidates                   │
│ Time: ~45 min on 1× MI300X                                     │
└────────────────────────────────────────────────────────────────┘
```

### Why DPO and not GRPO

We tried GRPO first. The policy destabilized — the model collapsed onto a single high-reward scaffold (penicillin-G-like) and stopped exploring. The reward signal couldn't differentiate "good but redundant" from "good and novel". DPO with KL-bounded objective fixed this: by training on **paired preferences** rather than scalar rewards, the model learns *the discrimination function* directly. Sample-efficient: 10K pairs in 45 minutes vs GRPO's much longer rollout budget.

### Why MI300X

192 GB HBM3 fits **Gemma 4 31B bf16 base + LoRA adapter (~500 MB) + KV cache + agent context coresident on one GPU**. Same GPU trains and serves. No tensor parallelism, no model sharding, no migration step from training to inference. Cost: one droplet, one GPU, one ROCm container.

### Hard-negative mining (the 10K pairs)

For each pathogen, generated ~1,250 Pareto pairs:

1. Designer (lysos-base) proposes 8 candidates.
2. Score each on the 12-axis reward stack.
3. Identify *Pareto-anti-correlated axes*: e.g. `predicted_mic` vs `embedding_novelty` often pull in opposite directions.
4. Pair a Pareto-frontier winner against an off-frontier but similar-composite loser.
5. DPO trains the Strategist to prefer the frontier point.

This is why DPO works here: the model learns to detect Pareto dominance, not just raw composite score.

### Training configs (`configs/stage2_5_dpo.yaml` shape)

```yaml
base_model: rahul24raj/lysos-base
ref_model: rahul24raj/lysos-base
dataset: rahul24raj/lysos-hard-negatives-v1
output_repo: rahul24raj/lysos-base-dpo
lora:
  r: 32
  alpha: 64
  dropout: 0.05
  target_modules: [q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj]
dpo:
  beta: 0.1
  loss_type: sigmoid
  max_length: 4096
  max_prompt_length: 2048
training:
  per_device_batch: 2
  gradient_accumulation: 8   # effective batch 16
  gradient_checkpointing: true
  bf16: true
  learning_rate: 5.0e-7
  warmup_ratio: 0.1
  num_train_epochs: 1
  save_steps: 100
  push_to_hub: true
  push_strategy: checkpoint
wandb:
  project: lysos-amr-stage2-pro-v11
  run_name: stage2_5-dpo-lysos-base-dpo
```

The `push_strategy: checkpoint` is critical: every 100 steps a new checkpoint lands on HF Hub, so a mid-training reboot resumes from the latest pushed adapter. No work loss on AMD droplet reboots.

### vLLM serving on the MI300X

```bash
docker run --device=/dev/kfd --device=/dev/dri --network host --ipc host \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  rocm/7.0:rocm7.0_pytorch_training_instinct_20250915 \
  python -m vllm.entrypoints.openai.api_server \
    --model google/gemma-4-31B-it \
    --enable-lora \
    --lora-modules lysos-dpo=rahul24raj/lysos-base-dpo \
    --max-loras 1 --max-lora-rank 32 \
    --dtype bfloat16 \
    --port 8000
```

Requests hit `:8000/v1/chat/completions` with `model: "lysos-dpo"`. The base + LoRA load once, requests stream at full HBM3 throughput.

---

## PART III — The 12-Axis Reward Stack (scoring honesty)

This is what scores every molecule. The honesty rule: every axis is tagged `real` or `proxy` so the user never confuses an RDKit-computed value (deterministic) with a learned predictor (probabilistic).

| Axis | Weight | Tag | What it computes |
|---|---|---|---|
| `predicted_mic` | 0.30 | proxy | Scaffold prior from Stage 2 SFT corpus (lower = better activity prior) |
| `drug_likeness_qed` | 0.15 | real | Bickerton QED via RDKit |
| `hemolysis_safety` | 0.15 | proxy | Membrane perturbation prior |
| `embedding_novelty` | 0.10 | real | 1 − max cosine to known antibiotic embeddings |
| `novelty` | 0.10 | proxy | Scaffold-tree distance heuristic |
| `synthesizability` | 0.10 | real | Ertl-Schuffenhauer SA score |
| `validity` | 0.05 | real | **Tiered connectivity** (see below) |
| `structural_alerts` | 0.05 | real | RDKit FilterCatalog (PAINS, Brenk, NIH) |

### The validity scoring fix (an honesty-driven rewrite)

Earlier, `smiles_valid` just ran `MolFromSmiles is not None`. That happily accepted `CC(C)C(CO)N1CC(NC(=O)Cc2ccccc2)C1S.O.O` (a broken structure + two floating waters) as `validity=1.00`. The 2D viewer was screaming "3 fragments + isolated atoms" while the score said "perfect."

Fixed to a tiered scoring:

```
1.0   single connected drug-like molecule
0.7   main candidate + solvent fragments (H₂O, ions, formate, acetate, halogen acids)
0.3   multiple disconnected real fragments (split structure)
0.0   only isolated atoms / only solvent / unparseable
```

Solvent list: `O`, `[H]O[H]`, `[Na+]`, `[K+]`, `[Cl-]`, `[Br-]`, `[I-]`, `[F-]`, `Cl`, `Br`, `I`, `F`, `[OH-]`, `[NH4+]`, formate, acetate. Solvent check fires BEFORE the isolated-atom check so a lone oxygen (water) counts as solvent, not as a stray atom.

Verified live on `CC(C)C(CO)N1CC(NC(=O)Cc2ccccc2)C1S.O.O`: validity drops 1.00 → 0.70, composite drops 0.625 → 0.610. Penicillin G clean: 1.00. `CC.CC` (two unrelated frags): 0.30. `C.[Na+].[Cl-]` (no real molecule): 0.00.

---

## PART IV — The Agentic Workspace, Layer by Layer

### 4.1 The Orchestrator Agent (the front door)

Every chat message — slash OR free text — flows through `/api/orchestrator/run`. Modern agentic apps (Claude, Cursor) never reject a user's message; the agent always sees it. Lysos does the same.

The orchestrator (Gemini 2.5 Pro, Flash fallback on 503/429) classifies intent into four routes:

| Route | When it fires | Example user input |
|---|---|---|
| `workflow` | Multi-step plan needed | "design a new β-lactam for MRSA" → `design_with_debate` |
| `slash` | Single-purpose command | `/score`, `/help`, `/load c1ccccc1`, `/champion MRSA` |
| `agent` | Open-ended, multi-tool reasoning | "think on top of it", "build something that beats this" |
| `answer` | Pure prose, no tool needed | "what does MIC mean?", "explain DPO" |

The system prompt the orchestrator sees on every call:

```
Session context:
  current_smiles: O=C(Cc1ccccc1)NC1CN(C(CO)C2CCO2)C1S
  pathogen: MRSA
  last_composite: 0.645
  candidate_count: 7

Recent chat (oldest → newest):
  - user: design a beta-lactam against MRSA
  - assistant: (debate winner SMILES + score)
  - editor: I'd apply para-Fluoro → c1ccc(F)cc1...
  - user: then apply

## Session memory
- current SMILES: `O=C(Cc1ccccc1)NC1CN(C(CO)C2CCO2)C1S`
- last score: composite=0.645, weakest=embedding_novelty
- last harden: robustness=0.81, vulnerable_atoms=[4, 11, 13]
- **PENDING PROPOSAL** (from editor): `para-Fluoro` →
  `O=C(Cc1ccc(F)cc1)NC1CN(...)C1S` — if user says 'apply', 'do it',
  'go ahead', etc., this is the SMILES they mean.

Routes: workflow | slash | agent | answer
[7 workflows + 5 slash routes listed with what_it_does]
```

Output is strict JSON: `{route, rationale, name, inputs, answer}`.

### 4.2 The Pending Proposals Queue (the conversational-context fix)

This was the killer engineering moment. Three sources of "current SMILES" were fighting:

1. `recent_messages` — chat history. Parent SMILES cited many times.
2. `currentSmiles` — frontend canvas state. Only updates on load.
3. `session_memory.brief` — cached cross-turn state. Holds the last loaded SMILES.

When the user said "then apply", any of these could win the tie. The parent kept winning over the freshly-proposed hardened variant.

Fix: a **per-session pending-proposals deque** in `session_memory.py`. Distinct from "loaded" state.

```python
_proposals: dict[str, deque[dict[str, Any]]] = {}
_MAX_PROPOSALS = 8

def record_proposal(session_id, smiles, *, source, swap_label, rationale):
    """Queue a pending agent suggestion."""

def pop_proposal(session_id):
    """Return + remove the most recent un-applied proposal."""

def peek_proposal(session_id):
    """Read without consuming — used by brief() for prompt context."""

def clear_proposal_for(session_id, smiles):
    """Drop matching entries when user loads via a different path."""
```

The orchestrator runs a **regex pre-flight** BEFORE calling Gemini:

```python
accept_re = re.compile(
    r"^(apply|apply that|apply it|do it|go ahead|then apply|"
    r"yes apply|yes do it|use that|use that one|make the change|"
    r"ship it|approved|accept|accept it|ok apply)\.?\s*$",
    re.IGNORECASE,
)
if accept_re.match(req.text.strip()):
    pending = session_memory.pop_proposal(req.session_id)
    if pending:
        return {
            "route": "slash",
            "name": "/load",
            "inputs": {"smiles": pending["smiles"]},
            "source": "pending-proposal-fastpath",
        }
```

### 4.3 The Specialist Agents (real Gemini calls, not templates)

Each workflow step can declare a `narrator_role`. After the tool returns, the workflow executor fires a Gemini call with a role-specific system prompt to write **real reasoning** over the result.

| Role | Persona summary |
|---|---|
| **Designer** | Proposes new candidate antibiotics; reviews scaffold output |
| **Critic** | Strict fact rules: count `vulnerable_atoms`, cite real atom indices + mutation codes |
| **Editor** | Strict input rules: pick ONE swap from `gemini_suggestions` verbatim |
| **Strategist** | Commit to ONE next move with one-line justification |

Each role's prompt has STRICT FACT RULES to prevent hallucination (no inventing mutation codes, no fabricating clash atoms, no deflection).

### 4.4 The Debate Engine (`design_with_debate`)

Four agent roles take turns over N rounds:

```
Designer ──drafts──► Critic ──challenges──► Editor ──refines──► [next round]
                                                                       │
                                                                       ▼
                                                                Strategist
                                                                picks winner
```

Each role is a separate Gemini Pro call. The winner SMILES auto-loads into 2D + 3D.

### 4.5 The 27-Tool Agent Loop

When orchestrator routes to `agent`, Gemini gets the full tool registry: scoring, resistance, harden, pose, RDKit edits, session/Pareto/champion queries, and `propose_next_action`. Each call streams as `tool.call` / `tool.result` SSE.

### 4.6 The `propose_next_action` Contract

System prompt mandate: every multi-tool analysis MUST call this tool BEFORE the final answer. Records into `pending_proposals` queue so the user can accept with one word.

### 4.7 Engineered Truncation

`_truncate_for_event` is a three-stage compactor that preserves high-signal summary fields (`key_contacts`, `vulnerable_atoms`, `binding_atoms`, `clashing_atoms`, `composite`, `robustness_score`, `gemini_suggestions`, `after_smiles`, `mechanism`, `predicted_robustness_delta`, …) even at the size limit. The agent's `tool_response_parts` always get the full untruncated data; truncation is purely for SSE display.

### 4.8 Per-Agent Thread Replies

When user clicks "Reply to Editor" on a chat bubble, the harness builds a role-specific system prompt with `{title, role, history, smiles, pathogen, pdb}` — last 14 visible chat messages shipped from frontend. Forbids generic deflection.

### 4.9 Resilience: Pro → Flash auto-fallback

Both agent loop and orchestrator retry on `gemini-2.5-flash` when `gemini-2.5-pro` returns 503/429. Env-overridable.

---

## PART V — The 7 Workflows

All workflows stream as SSE: `workflow.start` → `workflow.plan` → per-step `step.start` / `step.progress` / `step.done` / `step.narration` / `step.apply_smiles` → `workflow.done`.

| Workflow | Steps | Purpose |
|---|---|---|
| `design_with_debate` | debate → score_winner | Multi-agent design loop |
| `harden_candidate` | predict → pick_atoms → harden_each | Find weak atoms + propose hardening swaps |
| `broad_spectrum_screen` | cross_target | Test SMILES against all priority pathogens |
| `compare_top_n` | score_each → rank | Side-by-side N candidates |
| `optimize_for_property` | score → identify_weakest → improve | Iterative edit toward one axis |
| `pareto_explore` | fetch → score_missing → critic_narrate | Multi-objective Pareto frontier |
| `discover_and_assess` | generate → score → screen | Bulk candidate sweep |

---

## PART VI — The Chemistry Engine (custom + RDKit)

- **`predict_resistance`** — escape score = freq×0.30 + dist×0.30 + chem×0.15 + cons×0.15 + grantham×0.10. Returns `vulnerable_atoms`, `clinical_overlap`, `drug_class_profile`, `robustness_score`.
- **`harden_atom`** — Gemini Pro generates 4 candidate swaps with `proposed_smiles` + `mechanism`. Curated playbook fallback. Confidence is calculative across 5 factors. `_swap_label_to_fg` maps Gemini swap labels to RDKit FG_TEMPLATES.
- **`place_in_pocket`** — RDKit ETKDG → distance grid → pose_score. Returns structured `binding_atoms`, `clashing_atoms`, `key_contacts` top-8.
- **Champion table** — per-pathogen sqlite, auto-promote on `fitness = composite × robustness` beats.

---

## PART VII — The Frontend (React + Vite + TypeScript)

- **Top-level**: Chat (resizable left pane) + Main container (Chemistry/Scoring/Agents/Report/Knowledge tabs).
- **Chat surfaces**: `TightComposer`, `SlashPalette`, `WorkflowCard`, `OrchestratorCard`, `ChampionCard`, `RewardCard`, `ProposalCard`, `ExplainCard`, `StressTestCard`.
- **Streaming indicator**: `pendingChat` state + auto-clear useEffect.
- **Session persistency**: `lysos.session.v1` localStorage with versioned schema, 500 events/tab cap.
- **Auto-apply pipeline**: `step.apply_smiles` SSE event → `loadSmilesIntoCanvas` → editor echo chat row.

---

## PART VIII — The Complete Demo Loop (end to end)

```
1. User: "design a beta-lactam against MRSA"
2. Orchestrator → workflow:design_with_debate
3. Designer → Critic → Editor → Strategist (2 rounds)
4. Winner SMILES auto-loads + auto-scores
5. User: "harden this"
6. predict_resistance → critic narration → pick_atoms → harden_each
7. Editor narration: "I'd apply 6α-methoxy → COC1(...)C1S"
8. step.apply_smiles SSE → canvas updates automatically
9. propose_next_action queues the SMILES
10. User: "apply"
11. Orchestrator fast-path pops queue → /load → canvas locks in hardened variant
12. User: "score against the champion"
13. /champion MRSA → ChampionCard A/B with fitness delta
```

---

## PART IX — Repo Layout

```
lysos/
├── workspace/api/           FastAPI backend (:7860)
│   ├── server.py
│   ├── chat.py, orchestrator.py, agent.py, workflows.py
│   ├── debate.py, chem_resistance.py, chem_3d.py
│   ├── champions.py, session_memory.py, knowledge.py
│   └── playground.py, report.py
├── workspace/agents/        Harness + role prompts + slash registry
├── workspace/tools/chem_workbench/  RDKit edit ops, FG templates
├── workspace/web/           Vite + React frontend (:5173)
│   └── src/workbench/v3/    WorkbenchV3 + chat components
├── src/eval/rewards/        12-axis reward fns
├── src/train/               Stage 1/2/2.5 training scripts
├── configs/                 stage1_pretrain.yaml / stage2_sft.yaml / stage2_5_dpo.yaml
├── scripts/                 run_training_pipeline.sh, vm_bootstrap.sh, serve_lysos_vllm.sh
├── data/                    processed parquets, card_subset, pdb_cache
└── docs/                    TECH_DOC.md, this file, SKILLS.md
```

---

## PART X — Deployed Artifacts

| Asset | URL |
|---|---|
| GitHub | <https://github.com/Rahul-Rajpurohitk/lysos> |
| HF Space | <https://huggingface.co/spaces/rahul24raj/lysos> |
| Stage 1 | <https://huggingface.co/rahul24raj/txgemma-4-31b> |
| Stage 2 | <https://huggingface.co/rahul24raj/lysos-base> |
| Stage 2.5 (prod) | <https://huggingface.co/rahul24raj/lysos-base-dpo> |
| Stage 2 dataset | <https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2> |
| Hard-negatives | <https://huggingface.co/datasets/rahul24raj/lysos-hard-negatives-v1> |

---

## PART XI — The Honesty Patches (a chronicle)

Each bug the user caught taught the build something.

1. **Validity 1.00 on broken structure** → tiered connectivity scoring
2. **`/champion MRSA` showed comparison but didn't load** → auto-load in ChampionCard useEffect
3. **Harden suggestions had no clickable SMILES** → use Gemini's `proposed_smiles` first
4. **`pick_atoms` step showed `{}`** → move logic to `inline_fn`
5. **Critic narration was a template** → real Gemini per-step narrators
6. **Critic said "zero escape vectors"** → strict fact rules
7. **Editor invented "meta-Hydroxymethyl"** → strict input rules
8. **"then apply" loaded the original** → pending-proposal queue + fast-path
9. **Agent narrates but never executes** → `step.apply_smiles` SSE
10. **Hand-waving in final answer** → `propose_next_action` contract
11. **Hallucinated clash atoms** → engineered truncation
12. **Empty 0.8s response** → Pro→Flash auto-fallback
13. **`/HELP` returned "Unknown command"** → case-insensitive + unknown-slash fallthrough
14. **Markdown nested `**...**`** → flat bold + plain prose
15. **Per-agent reply gave deflection** → role-specific system prompt with activity log
16. **Session wiped on refresh** → versioned localStorage
17. **Score card clipped** → overflow:visible + flex:0 0 auto
18. **Streaming indicator silent** → pendingChat state
19. **Slash palette ate Enter** → textarea owns Enter
20. **`/wf <unknown>` 404** → inline workflow picker

---

## PART XII — Run It Locally

```bash
git clone https://github.com/Rahul-Rajpurohitk/lysos.git
cd lysos
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

uvicorn workspace.api.server:app --host 0.0.0.0 --port 7860 &
cd workspace/web && npm install && npm run dev
```

Env vars:

```bash
GEMINI_API_KEY=...
LYSOS_AGENT_GEMINI_MODEL=gemini-2.5-pro
LYSOS_AGENT_GEMINI_FALLBACK=gemini-2.5-flash
LYSOS_ORCHESTRATOR_MODEL=gemini-2.5-pro
LYSOS_ORCHESTRATOR_FALLBACK=gemini-2.5-flash
LYSOS_NARRATOR_MODEL=gemini-2.5-pro
LYSOS_DEBATE_MODEL=gemini-2.5-pro
```

---

## PART XIII — License

MIT (code) · Apache-2.0 / Gemma terms (weights) · CC-BY (datasets).

Built by Rahul Rajpurohit for the AMD Developer Hackathon 2026, Track 2 — Fine-Tuning on AMD GPUs.

---

## PART XIV — Incremental Progress Log

> Append new sections here as work continues. Each entry dated.

### 2026-05-11 — `compare_top_n` smiles_list crash + auto-fill from session
- **Bug**: User typed "lets A/B test both" after loading a SMILES → orchestrator routed to `workflow:compare_top_n` → step `compare` raised `args_fn raised: 'smiles_list'` (KeyError, no smiles_list in state).
- **Root cause**: The orchestrator dispatched the workflow with no `smiles_list` input, and the workflow's `args_fn` did a bare `st["smiles_list"]` lookup.
- **Fix**: workflow `args_fn` auto-fills `smiles_list` from session candidates (recent loaded SMILES + champion) when not provided. Frontend ships recent SMILES from chat history. Orchestrator prompt teaches "A/B test" intent to populate smiles_list from `current_smiles` + champion.
