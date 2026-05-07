# LYSOS — AMD Developer Hackathon Pitch Deck + Demo Script

**Submission deadline**: 2026-05-09
**Track**: Antimicrobial / Generative AI on AMD MI300X

---

## ONE-LINE

> Lysos is an antimicrobial drug-discovery SaaS. Trained on AMD MI300X across 4 stages of fine-tuning. Served on AMD MI300X. Agentic workflow that designs candidates, validates them in 3D, predicts resistance escape, and produces a publishable medchem report — all auditable, all on AMD.

---

## SLIDE 1 — TITLE

**Lysos** — Agentic Antimicrobial Drug-Discovery SaaS on AMD MI300X
*"Antimicrobial resistance kills 1.27M/year. We built the design lab on AMD."*

---

## SLIDE 2 — THE PROBLEM

- **Antimicrobial resistance** is now bigger than HIV/AIDS in death toll
- The pipeline of new antibiotics is **collapsing** — 0 novel mechanisms approved 2017-2023
- Generic drug-discovery tools predict "will it bind?" — antibiotics need "will bacteria evolve around it?"
- Medicinal chemists need an interactive workbench, not a black-box model

---

## SLIDE 3 — WHAT WE BUILT

A live SaaS where a medicinal chemist defines a target pathogen + constraints, and an autonomous agent system runs the full medchem workflow:

```
SCOPE → ANCHOR → DESIGN → VALIDATE → STRESS-TEST → REPORT
```

- 5 dashboards (Chemistry / Knowledge / Scoring / Agents / Report)
- 3 antimicrobial-specific services in the Chemistry container
- Trained on 12K AMR drug-design prompts + DPO with hard-negative pairs
- Inference-time best-of-N reward-guided generation
- Exportable medchem report (Markdown / JSON / PDF)

---

## SLIDE 4 — THE 4-STAGE TRAINING PIPELINE (all on MI300X)

```
Gemma-4-31B-it (Google base)
        ↓
Stage 1: TxGemma SFT (therapeutic biomedical domain)         → rahul24raj/lysos-base
        ↓
Stage 2: AMR SFT (12K antibiotic-design prompts)              → local checkpoint
        ↓
Stage 2.5: DPO with hard-negative pairs (RL-LIKE alignment)  → rahul24raj/lysos-base-dpo
        ↓ MERGED
Final: 31.3B fp16, served on MI300X via OpenAI-compatible API at /shared-docker/lysos/models/lysos-dpo-merged/
```

Stage 3 GRPO RL was attempted; reference-model bug + bf16 precision blockers
documented in `docs/STAGE3_GRPO_AUDIT.md`. **Inference-time Best-of-N is the
substitute** — same reward stack drives runtime selection without the
training instability.

---

## SLIDE 5 — THE 3 ANTIMICROBIAL-SPECIFIC SERVICES

These distinguish Lysos from generic drug-design SaaS.

### 🥇 3D Target-Ligand Theater
- 8 pathogens × 1-2 curated PDB targets each (PBP2a, NDM-1, InhA, KPC-2, ...)
- RDKit ETKDG conformer + geometric placement in active site
- Returns binding atoms + clashing atoms + key contacts
- Verified: penicillin G in PBP2a hits SER365 (catalytic serine), LYS247, LYS382 — all documented

### 🥈 Resistance-Escape Vulnerability Map
- Curated CARD subset: 64 clinical resistance mutations across 10 targets
- For each candidate × target: per-atom escape score = freq × distance_factor
- The killer feature: bacteria evolve around drugs; we predict HOW upfront
- Verified: penicillin G shows K382Q (ceftaroline-R) vulnerability at atom 2

### 🥉 Multi-Candidate Pareto Lab
- 10 selectable axes (composite, MIC, QED, novelty, robustness, ...)
- Real-time Pareto frontier across the session's exploration
- Strategist agent uses pareto_summary to detect plateau → BRANCH
- Click any dot to load candidate into 2D builder

---

## SLIDE 6 — THE BIDIRECTIONAL CHEMISTRY COCKPIT

The 2D builder is the operating table. Three services orbit it.

```
       ┌─────────────────────────────────┐
       │     2D MOLECULE BUILDER         │
       │  edit, click, hover, drag-bond  │
       │   atoms 0,1,2,3,4,5             │
       └─────────────┬───────────────────┘
                     │ current SMILES
       ┌─────────────┼─────────────┐
       │             │             │
       ▼             ▼             ▼
   ┌────────┐  ┌──────────┐  ┌──────────┐
   │ 3D     │  │ ESCAPE   │  │ PARETO   │
   │ pose   │  │ map      │  │ frontier │
   └────────┘  └──────────┘  └──────────┘
       │             │             │
       └─────────────┼─────────────┘
                     ▼
          HALOS BACK ON THE 2D ATOMS
          green = binding (Service 1)
          red   = clashing (Service 1)
          orange dashed = vulnerable (Service 2)
          rank badge   = Pareto position (Service 3)
```

Same atoms, same canvas, all signals overlaid. Agent reasons:
> "atom 5 is binding (green) but vulnerable (orange) via K382Q for ceftaroline-R.
> Keep contact, harden vulnerability — swap to fluorinated carbon."

---

## SLIDE 7 — THE AGENTIC WORKFLOW

5 specialists driving an explicit 6-phase protocol:

| Agent | Role | Exit signal |
|---|---|---|
| **Designer** | Best-of-N candidate proposal anchored in resistome | reward ≥ threshold |
| **Critic** | 12-axis decomposition + identifies weakest dimension | composite ≥ 0.75 → ACCEPT |
| **Editor** | Applies single-atom transformation | improved composite |
| **Strategist** | Plateau detection + BRANCH/TERMINATE/RED-TEAM | global termination |
| **Orchestrator** | Per-session ledger + meta-routing | n/a |

Workflow phases visible in the Agents container as live progress strip:
SCOPE → ANCHOR → DESIGN → VALIDATE → STRESS-TEST → REPORT

---

## SLIDE 8 — HONEST SCORING (no fake authority)

12-axis reward stack with explicit honesty stamps:

| Axis | Status | Source |
|---|---|---|
| validity, drug_likeness_qed, synthesizability, novelty, structural_alerts | 🟢 REAL | RDKit + Bickerton + Morgan-2 |
| predicted_mic, hemolysis_safety, resistance_robustness | 🟡 PROXY | XGBoost / structural-alert / heuristic |
| boltz2_pose_conf, spectrum_breadth | 🔴 STUB | Cache empty / not implemented |
| binding_affinity, pareto_entry | 🟢 REAL (Day-1) | Service 1 / Service 3 |

Honesty > impressive-looking. Judges see exactly which numbers to trust.

---

## SLIDE 9 — THE DELIVERABLE (Report container)

One click → snapshot every dashboard → structured medchem report:
- Cover: pathogen + duration + n_candidates
- Workflow audit (which phases completed + tool counts)
- Top-3 candidates with full property breakdown
- Per-candidate: 3D pose + resistance escape + Pareto rank
- Agent rationale + tool-call distribution
- Next experiments (wet-lab follow-up)

Export: Markdown · JSON · PDF (browser print)

This is what separates "chat that designs molecules" from "SaaS that delivers a report".

---

## SLIDE 10 — AMD MI300X SHOWCASE

**Trained on AMD MI300X** (4 stages, ~22h GPU compute documented across stages 1-2.5)
**Served on AMD MI300X** (custom OpenAI-compatible FastAPI server, sdpa attention, 5-15 tok/s)
**59GB merged fp16 model** (lysos-base-dpo) on persistent disk
**SSH tunnel** (`./scripts/lysos.sh up/down/status`) for cost-controlled hot-swap
**Open**: 4-stage pipeline + reward stack + tool registry — all reproducible

The reward signal that aligned the model is the SAME reward signal that
guides the agents at inference time. Continuity from training to deployment.

---

## DEMO VIDEO SCRIPT (3 minutes)

### 0:00–0:20 — Cold-open
- Black screen + voiceover: "1.27 million people died from antimicrobial resistance last year."
- Cut to: typed `MRSA` in the pathogen picker
- Voiceover: "Today, designing a new antibiotic takes a team of medicinal chemists 5+ years. Lysos lets one chemist do it in an afternoon — on AMD."

### 0:20–0:50 — The Chemistry container (the centerpiece)
- Show 2D builder with benzene scaffold loaded
- Click `Library` → load Penicillin G
- Voiceover: "Real chemistry: atom-level edits, RDKit-validated, drag-to-bond."
- Open `3D Theater` — pick PBP2a (1VQQ) target
- Show pose loading: NGL renders the protein, ligand snaps into active site
- Voiceover: "Service one: pose the candidate against MRSA's PBP2a. Real PDB structure, real contacts."
- Pan to 2D builder → green halos on atoms 4, 6, 11; red halo on atom 2
- Voiceover: "Same atoms, both views. Green binds, red clashes."

### 0:50–1:20 — Resistance Escape (the killer feature)
- Open Resistance Escape Map heatmap
- Voiceover: "Service two: every antibiotic eventually fails to a single mutation. We predict which atoms are vulnerable."
- Click on a heatmap cell with red border (clinical mutation)
- Voiceover: "K382Q — the ceftaroline-resistance mutation. 0.339 escape probability for atom 2 of penicillin G."
- 2D builder shows orange dashed pulse on atom 2
- Voiceover: "The agent sees the vulnerability and hardens that atom."

### 1:20–1:50 — The Agentic Workflow
- Switch to Agents container
- Show Workflow Phase Tracker: highlighted DESIGN, with VALIDATE next
- Show Reasoning Trace columns: Designer thinks → calls get_pathogen_resistome → reads result → calls find_similar_drugs → emits PROPOSAL
- Voiceover: "Five specialists. Real tool calls. Auditable thinking. Best-of-N reward-guided selection."

### 1:50–2:20 — Pareto Lab
- Switch to Pareto Lab
- Voiceover: "Service three: we tracked all 47 candidates explored. 5 are Pareto-optimal across reward and MIC."
- Click on a green-haloed point → SMILES loads into 2D builder

### 2:20–2:50 — The Report (deliverable)
- Switch to Report container
- Click `Capture snapshot`
- Voiceover: "One click → publishable medchem report."
- Show preview: cover, top-3 candidates, validation table, agent rationale, next experiments
- Click `.md` export → file downloads

### 2:50–3:00 — Closing
- Voiceover: "Trained on AMD MI300X. Served on AMD MI300X. Open pipeline. Real biochemistry. Auditable agents."
- "Lysos. Antimicrobial drug discovery, agentic and accountable."
- Logo + GitHub URL

---

## TECHNICAL CREDITS

- Base model: Gemma-4-31B-it (Google)
- Training pipeline: TRL + PEFT + transformers, on ROCm 7.0 + PyTorch 2.9 nightly
- Inference: custom OpenAI-compat FastAPI server (sdpa attention)
- Frontend: React + Vite + NGL + RDKit-WASM
- Backend: FastAPI + SQLite + WebSocket event bus
- Reward stack: 12 components, 7 categories, 37 tools
- AMD MI300X: ROCm 7.0, ~640GB VRAM (single instance)

## REPRODUCIBILITY

```bash
# Pull the deployable adapters from HF Hub
huggingface-cli download rahul24raj/lysos-base
huggingface-cli download rahul24raj/lysos-base-dpo

# Re-merge on any GPU machine
python3 scripts/merge_dpo.py
# → ~15 min, produces 59GB lysos-dpo-merged/

# Spin up serving (any compatible GPU)
python3 scripts/serve.py
# → OpenAI-compat endpoint on :8000

# Workbench
.venv-cli/bin/python3 -m uvicorn workspace.api.server:app --port 7860
cd workspace/web && npm run dev
```

---

*Generated 2026-05-07. Delivered for AMD Developer Hackathon submission 2026-05-09.*
