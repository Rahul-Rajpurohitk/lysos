# Lysos — Pitch Deck

> **AMD Developer Hackathon · May 2026**
> AI-native antibiotic drug-design lab on AMD MI300X.

---

## Slide 1 · Title

**Lysos Workbench**
*The AI drug-design lab for antimicrobial resistance.*

Four specialist agents · 12-axis live reward · MI300X-trained Gemma 4 31B.

---

## Slide 2 · The Problem

- **AMR kills 1.27M people/year** — projected 10M by 2050 (Lancet 2022).
- Pharma has effectively exited antibiotic R&D — average return is **negative** vs. oncology.
- Existing AI tools are **single-agent prompt-and-pray**: one LLM, no critique, no scoring loop, no resistance modeling.
- Designing a new antibiotic requires **simultaneously satisfying 12+ axes**: potency, drug-likeness, toxicity, novelty, synthesizability, spectrum, resistance robustness — no human chemist can hold all of them at once.

---

## Slide 3 · The Solution

A workbench where **four specialist AI agents debate** every candidate, every reward axis, every edit:

| Agent | Job |
|---|---|
| **Designer** | Drafts candidate molecules from a target + objective |
| **Critic** | Red-teams: structural alerts, β-lactamase escape, PAINS, hERG |
| **Editor** | Validates RDKit chemistry, mutates atoms, refines scaffolds |
| **Strategist** | Sets the iteration policy, terminates when Pareto-stable |

Plus an **always-aware Orchestrator** that maintains a session ledger and answers meta-questions ("what has Critic been arguing?").

The user can **drag-edit any atom on the 3D ligand**; the pose recomputes and the agents debate the edit live.

---

## Slide 4 · Architecture

```
┌─────────────────────────────────────────────┐
│  React + Vite frontend                       │
│   chat tabs · slash palette · 3D viewer     │
│   radar · scaffold tree · artifact pane     │
└────────────────┬────────────────────────────┘
                 │  HTTP + SSE + WS
┌────────────────▼────────────────────────────┐
│  FastAPI harness                             │
│   17 slash commands · 7 chat-card kinds     │
│   8 workflow endpoints (W1-W8)              │
│   Orchestrator ledger + Tracer + SQLite     │
└────────────────┬────────────────────────────┘
                 │
   ┌─────────────┼─────────────────────┐
   ▼             ▼                     ▼
┌──────┐  ┌────────────────┐  ┌──────────────────┐
│ RDKit│  │ Reward stack    │  │ Lysos-Gemma 4-31B│
│ Boltz-2│ │ (8-12 axes)     │  │  vLLM on MI300X  │
│ ADMET │  │ MIC/QED/SAscore │  │  (the trained    │
│ pose  │  │ hemolysis/etc   │  │   policy)        │
└──────┘  └────────────────┘  └──────────────────┘
```

**Utility tier (Gemini 2.5 Pro)**: auto-titles chat tabs + drafts /explain briefs (one config flip away from running on Lysos-Gemma instead).

---

## Slide 5 · The 8 Workflows (live demo grid)

| # | Slash | What it does | Where it renders |
|---|---|---|---|
| **W1** | `/design <pathogen> [objective]` | Multi-agent debate, streamed | Chat timeline |
| **W2** | `/score <smiles>` | 12-axis reward breakdown | RewardCard |
| **W3** | `/sar [k=N]` | k mutants, ranked by Δ vs parent | ScaffoldTreeCard |
| **W4** | `/explain <target>` | Grounded markdown brief | Right-pane ArtifactPanel |
| **W5** | `/stress` | Adversarial Critic, structured failure modes | StressTestCard |
| **W6** | `/compare smi1 smi2 …` | N-candidate matrix + component winners | ComparisonCard |
| **W7** | (click row) | Replay a past session in a new tab | Streamed timeline |
| **W8** | `/library` | Saved sessions list | LibraryCard |

Plus utilities: `/datasets` (HuggingScience registry), `/orchestrator` (meta Q&A), reply-to-agent threading, multi-tab chat.

---

## Slide 6 · Live Demo Flow (60-second walkthrough)

1. **0:00** · Pick **MRSA** from the workbench hero. `/design MRSA β-lactam that escapes mecA` auto-fires.
2. **0:08** · Designer streams a candidate SMILES into the chat. Click it → 3D viewer loads PBP2a + the ligand.
3. **0:18** · `/score` the candidate → radar fills with 12 component bars; weakest shown in red.
4. **0:25** · `/sar k=5` → 5 mutant variants ranked by Δ-vs-parent. Click best → 3D updates, radar shifts.
5. **0:35** · `/stress` → Gemini Critic flags 4 failure modes (KPC hydrolysis, PAINS, hERG, hepatotox), each with a fix.
6. **0:48** · `/explain mecA` → grounded markdown brief streams into the right pane (Mechanism / Spectrum / Resistance / Design implications), citing the curated 387-drug pharma corpus.
7. **0:55** · `/library` → see all past sessions; click a row → replay the entire run in a new chat tab.
8. **1:00** · Final shot: wandb dashboard showing the Stage 1 SFT curve climbing on AMD MI300X.

---

## Slide 7 · Training Pipeline (the trained policy)

**Gemma 4 31B base · 4-stage fine-tune on 1× MI300X**:

| Stage | Data | Loss | Tokens | Time | Goal |
|---|---|---|---|---|---|
| **1. SFT** | TxGemma + AMR Stage 2 corpus | xent | ~26M | ~9h | Domain knowledge |
| **2. SFT-pro** | hard-negative mined examples | xent | ~12M | ~3h | Edge cases |
| **2.5. DPO** | preference pairs (good vs bad mol) | DPO | — | ~2h | Calibrate Critic |
| **3. GRPO** | live-RL with 12-axis composite | RL | — | ~6h | Policy → Pareto-front candidates |

**As of demo recording**: Stage 1 at step **1113/1654 (67%)**, loss 0.247, accuracy 92.0%. Cosine LR decay on schedule. Clean epoch-1→2 transition (loss dropped 0.286 → 0.258 at step 875).

Wandb run id: `zynunpjr` · MI300X 100% utilized · 19.4 s/iter · ETA ~3h to checkpoint.

---

## Slide 8 · Stack

- **Model**: Gemma 4 31B-it (4-stage fine-tune)
- **Hardware**: AMD MI300X · ROCm 7.0 · PyTorch 2.6 · transformers 5.8 · peft 0.19 · trl 1.3 · SDPA attention
- **Reward components**: RDKit (validity, QED, SAscore), Boltz-2 (3D pose), TDC predictors (ADMET, hemolysis), Gemini embedding (novelty), curated MIC/spectrum tables
- **Backend**: FastAPI · SQLite session store · SSE + WebSockets · 17 slash commands
- **Frontend**: React 18 · Vite · Allotment splitter panes · NGL viewer · framer-motion · 7 chat-card kinds
- **Knowledge corpus**: 387 deep drug mechanism profiles + 872 pharma Q/A pairs (curated with Gemini 2.5 Pro thinking traces)
- **External**: HuggingScience dataset registry (OpenADMET, B3DB, TDC, eve-bio DTA, SAIR — all on demand)

---

## Slide 9 · Roadmap

**Hackathon (delivered)**:
- 8 workflows W1–W8 end-to-end · Orchestrator awareness · drag-edit chemistry · auto-naming · multi-tab chat · 12-axis reward stack · pharma grounding corpus · MI300X Stage 1 training underway.

**Next 30 days**:
- Stages 2 + 2.5 + 3 (DPO + GRPO RL on MI300X)
- Pull tier-1 HuggingScience datasets into grounding pipeline
- Swap Gemini utilities → deployed Lysos-Gemma (one env var: `LYSOS_AUTOTITLE_BACKEND=lysos`)
- Boltz-2 pose docking integrated into reward stack

**90 days**:
- Multi-tenant SaaS (auth, billing, project shares)
- SAIR-grounded structure search (1M+ protein-ligand pairs → neighbour-pose panel)
- Actual wet-lab partnership for top-N candidates → MIC validation
- Antibody-modality expansion (Ginkgo GDPa1 grounding)

---

## Slide 10 · Why Lysos Wins

| Differentiator | Other AI drug tools | Lysos |
|---|---|---|
| **Multi-agent debate** | Single LLM, no self-critique | 4 specialists × 9 sub-agents, transcript-grounded |
| **Reward** | One metric (often docking score alone) | 12 axes · live radar per edit |
| **User involvement** | Read-only outputs | Drag-edit any atom; agents debate the user's edit |
| **Trained policy** | Generic LLM prior | Gemma 4 31B · 4-stage AMR fine-tune on MI300X |
| **Workflow coverage** | One-shot generate | 8 distinct user-goal flows (design, score, SAR, explain, stress, compare, replay, library) |
| **Trace replay** | None | Every event in JSONL; click any past session to re-watch |
| **Grounding** | Hallucinates | 387-drug curated corpus + HuggingScience tier-1 ready |

**Built by Rahul Rajpurohit** for the AMD Developer Hackathon · May 2026.
GitHub: [Rahul-Rajpurohitk/lysos](https://github.com/Rahul-Rajpurohitk/lysos)

---

# Demo Video Script (60-90 seconds)

```
[0:00–0:05]  HERO SHOT
  Camera: full workbench, Stream tab active, hero visible.
  V/O: "Lysos — an AI drug-design lab for antimicrobial resistance."

[0:05–0:15]  PICK PATHOGEN + DESIGN
  Action: hover MRSA pill, click. Hero collapses, /design auto-fires.
  Camera: zoom into chat panel as Designer message streams.
  V/O: "Pick a WHO-priority pathogen. Four AI agents start debating
        candidates — Designer drafts, Critic challenges, Editor refines."

[0:15–0:25]  SCORE
  Action: click the streamed SMILES → 3D viewer loads PBP2a.
  Type /score → RewardCard fills with 8-12 bars.
  Camera: highlight the composite (big number) + weakest component.
  V/O: "Every candidate is scored on 12 axes — potency, drug-likeness,
        toxicity, novelty — with a live radar."

[0:25–0:40]  DRAG-EDIT + SAR
  Action: click an atom on the 3D ligand → arm "swap N" op.
          Click a different atom → mutation runs, radar shifts.
          Type /sar k=5 → ScaffoldTreeCard with 5 ranked mutants.
  V/O: "Click any atom. The pose recomputes, the agents debate the
        edit, the score updates. Or expand the parent into k mutants
        and rank them by improvement."

[0:40–0:55]  STRESS + EXPLAIN
  Action: type /stress → Gemini Critic returns 4 attack vectors.
          Type /explain mecA → markdown brief streams into right pane.
  Camera: split view of chat + artifact pane.
  V/O: "Adversarial Critic finds failure modes you'd miss — KPC
        hydrolysis, PAINS, hERG. /explain pulls a grounded brief
        on the target from a curated 387-drug pharma corpus."

[0:55–1:05]  COMPARE + REPLAY
  Action: type /compare s1 s2 s3 → side-by-side matrix with crowns.
          Type /library → past sessions list, click → new tab replays.
  V/O: "Compare candidates head-to-head. Replay any past session
        with one click — every event was traced."

[1:05–1:25]  TRAINING SHOT
  Camera: switch to wandb dashboard, Stage 1 SFT curve.
  V/O: "Behind it: Gemma 4 31B fine-tuned in 4 stages on AMD MI300X.
        TxGemma supervision, AMR-specific SFT, DPO preferences,
        GRPO reinforcement on the same 12-axis reward you saw above.
        Step 1100 of 1654, loss 0.247, on schedule."

[1:25–1:30]  CLOSE
  Camera: tagline + GitHub.
  V/O: "Lysos. Built by Rahul Rajpurohit for the AMD Developer
        Hackathon, May 2026."
```

**Recording notes**:
- 1080p screen capture, 30fps min
- Browser zoom 100%, tabs hidden
- Cursor hovers stay 0.5s before each click for legibility
- Voiceover ~140 wpm, stay under 1:30 total
