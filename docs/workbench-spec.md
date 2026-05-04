# Lysos Workbench — Agentic Molecular Discovery Playground

**Author**: Rahul
**Status**: Spec locked — building
**Date**: 2026-05-03 (T-1 to AMD Hackathon kickoff)
**Scope**: An agentic, multi-model interactive playground where Gemma 4 31B-it on AMD MI300X designs, evaluates, edits, and red-teams antibacterial candidates against drug-resistant pathogens — with full visibility into reasoning, tool calls, and reward trade-offs.
**Companion**: `docs/tech-spec.md` (training pipeline) — the Workbench is the inference-time product layer that consumes the trained Lysos models and scores them in a live agentic loop.

---

## 1. One-line pitch

A live agentic environment where a frontier model designs, evaluates, edits, breaks, and rebuilds antibacterial candidates against drug-resistant pathogens — with full transparency, build-vs-break red-teaming, and 25+ MCP tools wrapping Boltz-2, PocketXMol, REINVENT 4, RDKit, and AMR-specific knowledge bases on a single AMD MI300X.

## 2. Mission, goals, non-goals

**Mission**: Make the agentic drug-design loop visible, reproducible, and forkable — for AMR specifically — so a researcher can actually *watch* the model think, intervene, branch, and ship reproducible candidates.

**Goals**:
1. Multi-agent debate visible in the UI (Designer / Critic / Editor / Strategist as distinct columns).
2. AMR-first tool registry — first set of antimicrobial-specific Open Agent Skills.
3. Open weights end-to-end — Gemma 4 31B-it + Boltz-2 + PocketXMol + REINVENT 4 + Gemini Embedding 2 (closed embedder by deliberate choice).
4. Build-vs-break dual mode — design new molecules OR red-team existing ones for resistance escape.
5. Reproducibility — every session exports as a reproducible Jupyter notebook + JSON event log.
6. Single-MI300X coresident inference — Gemma 4 31B for chat + Boltz-2 + structural models load on demand.

**Non-goals (v1)**:
- Wet-lab robotics (out of hackathon scope; revisit post-submission).
- Multi-user collaboration (single-user v1; collab in stretch).
- Custom training within the playground (the Lysos pipeline trains separately; the Workbench consumes the trained model).
- Mobile / responsive (desktop-first; responsive is post-MVP).

## 3. Market landscape (May 2026, primary research)

### Direct competitors
| Player | Status | Stack | Differentiator | Gap (we fill) |
|---|---|---|---|---|
| PlayMolecule AI | LIVE, 18K researchers, used by Biogen/Pfizer/Novartis/UCB | Pyodide-in-browser sandbox + 3D + MD/FEP/docking + natural-language AI | "First agentic superintelligence in molecular design" | Generic drug discovery, not AMR-first, paywalled tiers, closed inference |
| Speak to a Protein (arxiv 2510.17826) | Late-2025 paper + demo | MCP servers + chat + 3D + Python sandbox | Annotation + manipulation grounded in dialogue | Protein-analysis only, no design loop, no AMR |
| FutureHouse Robin | LIVE, Claude-backed | 5 specialist agents (Crow/Falcon/Owl/Phoenix/Robin) | First AI-generated discovery (ripasudil for AMD) | Literature/hypothesis-heavy, not interactive design |
| K-Dense BYOK | LIVE, open desktop | 135 Scientific Agent Skills + 100+ databases | Open Agent Skills standard | No AMR skills, desktop-only, no 3D playground |
| AstraZeneca ChatInvent | Internal (proprietary) | Multi-agent + GUI | Production-deployed | Closed |
| ChemAgent (ICLR 2025) | Open | Self-updating library + 4-module architecture | Self-improving memory | Reasoning-only, no UI, no design loop |
| Sakana AI Scientist v2 (Nature 2026) | Open | Agentic tree search | First AI workshop paper accepted | ML research not chemistry |
| NVIDIA NeMo Agent | LIVE | Multi-agent + lab robotics | Autonomous protocol execution | Enterprise-only, NVIDIA hardware |

### Foundation models (open) we integrate
- **Boltz-2** (MIT, github.com/jwohlwend/boltz) — protein-ligand structure + affinity at FEP-level accuracy, 1000x faster. Used as: affinity reward signal + binding pose viewer.
- **PocketXMol** (Cell 2026) — atom-level pocket-aware generation foundation model. Used as: pocket-aware proposer tool.
- **REINVENT 4** (Apache, MolecularAI) — RL chemistry generative framework. Used as: scaffold-hop / R-group / linker tools.
- **AlphaFold 3** (research-restricted) — co-folding. Used as: target-structure predictor when only sequence given.
- **Chai-1** (open inference) — multimodal protein/ligand. Backup structural reasoning.
- **DiffDock-L** — generative docking, 43% on PDBBind. Used as: pocket overlay tool.
- **Gemma 4 31B-it** (Google, open weights) — primary generator (designer + critic).
- **Gemini Embedding 2** (`gemini-embedding-001`, 3072d Matryoshka, MTEB top-1) — embeddings layer (RAG, novelty reward, similar-drugs).

### What we beat
- MIT Broad Cell 2025 — 36M compounds, 24 synthesized, 7 active, 2 leads bactericidal vs MRSA + N. gonorrhoeae. **Static pipeline, not interactive.** We add the interactive agentic layer.
- REINVENT 4 has antibiotic case studies but no UI.
- No public agentic playground specifically for AMR.

## 4. Product positioning

> **The Cursor / Replit Agent for AMR drug design — an interactive agentic environment where a frontier model designs, evaluates, edits, and red-teams antibacterial candidates with full visibility into reasoning, tool calls, and reward trade-offs, on a single AMD MI300X.**

Differentiator at the AMD Hackathon: every other entry will ship a textbox + output list. We ship the equivalent of Cursor-for-drug-design.

## 5. Eight-layer architecture

```
L7 Observability        LangSmith + Phoenix Arize + OpenTelemetry traces
L6 Persistence          Postgres + pgvector (sessions / candidates / embeddings)
                        S3 / local FS (artifacts: PDBs, MOL files, MD frames)
L5 Frontend             React 19 + Vite + Tailwind + shadcn/ui
                        Mol* + 3Dmol.js + RDKit-JS + Pyodide sandbox
                        Vercel AI SDK 6 chat + tool-call timeline streaming
L4 API Gateway          FastAPI + SSE + WebSocket + MCP server endpoints
                        Per-session event bus, rate limiting, auth
L3 Memory               pgvector for episodic memory (past candidates + scores)
                        Self-updating skill library (ChemAgent pattern) per session
L2 Orchestration        LangGraph state machine
                        4-agent debate: Designer + Critic + Editor + Strategist
                        Time-travel + branching primitives built into state
L1 Agent Core           Gemma 4 31B-it (designer + critic) via vLLM ROCm
                        Function calling enabled; streaming JSON tool calls
                        Sub-models invoked: Boltz-2, PocketXMol, REINVENT 4, RDKit
L0 Tool Registry (MCP)  25+ Pydantic-typed tools, K-Dense skill format
                        Reusable across Claude / GPT-4 / Gemma / local
```

## 6. Frontend / UX

### 6.1 Layout — 4-pane + collapsible drawers

```
┌─ Lysos Workbench ──────────────────────────────────────────────────────────┐
│ [Pathogen: MRSA ▾]  [Mode: Design ▾]  [Autonomy: Co-pilot ▾]  [● Auto-save]│
├────────────────────────────────────────────────────────────────────────────┤
│ ┌─ Multi-Agent Conversation ─┐ ┌─ 3D Stage (Mol*) ──┐ ┌─ Reward Radar ──┐ │
│ │ Designer ► Critic ► Editor │ │ Rotatable scene    │ │  ╱─MIC─╲ 0.83   │ │
│ │ ► Strategist columns       │ │ Binding pose       │ │  ╱      ╲       │ │
│ │ Streaming chat + tools     │ │ Protein surface    │ │ ╱  ●     ╲      │ │
│ │                            │ │ Pocket highlight   │ │ ╲        ╱      │ │
│ │ [Pause][Branch][Override]  │ │ ↓ 2D RDKit-JS ↓    │ │  ╲QED╱ 0.79     │ │
│ └────────────────────────────┘ └────────────────────┘ └─────────────────┘ │
├────────────────────────────────────────────────────────────────────────────┤
│ ┌─ Lineage Tree (git-graph) ─────────────────────────────────────────────┐ │
│ │   ●─●─●─●═●  ← current path (best)                                     │ │
│ │       └─●─●─●  ← branched from c12, scaffold-hop variant               │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
│ ┌─ Tool-Call Timeline (collapsible) ─────────────────────────────────────┐ │
│ │ 14:23 predict_mic("CN1...")           → 0.41 (MRSA)                    │ │
│ │ 14:24 predict_binding_affinity()      → ΔG = -8.3 kcal/mol (Boltz-2)   │ │
│ │ 14:25 predict_resistance_escape()     → [PBP2a Glu447Lys ...]          │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
│ ┌─ Constraint Bar ───────────────────────────────────────────────────────┐ │
│ │ [logP < 5] [exclude PAINS] [require thiazole] [+constraint]            │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 UX patterns adopted from 2026 research

| Pattern | Source | Lysos Workbench implementation |
|---|---|---|
| Reasoning surfaced with confidence | Smashing Mag agentic UX 2026 | Tool calls render with predicted score + confidence band |
| Variable autonomy (slider, not toggle) | UXmag agentic patterns 2026 | Auto-pilot / Co-pilot / Manual modes |
| Goal-first onboarding | UX Collective Mar 2026 | Landing: "What pathogen?" not a tutorial |
| Code playgrounds as design files | Anima Skill 2026 | Pyodide cells embedded in conversation; user can edit + re-run |
| MCP servers for tools | Speak-to-a-Protein 2025 | Every tool is an MCP endpoint, reusable across LLMs |
| Time-travel / replay | Cursor / Replit Agent | Lineage tree IS the replay; scrub to any node and re-run |
| HITL approval beats | Vercel AI SDK 6 `needsApproval` | "Run docking? 30s expected" prompts before expensive ops |
| Multi-agent visible debate | FutureHouse Robin pattern | 4 agents in 4 columns, conversation between them visible |
| Structured output streaming | Vercel AI SDK 6 unified generate | Tool calls stream as typed Pydantic objects, render live |

### 6.3 Frontend stack
- **React 19** + Vite + TypeScript (strict)
- **Tailwind 3** + shadcn/ui base components
- **Mol*** for 3D protein-ligand viz (RCSB PDB-grade)
- **3Dmol.js** for fast molecule cards in chat
- **RDKit-JS** for 2D depictions + atom-level edit ops in browser
- **Pyodide** for browser-side RDKit + analysis
- **Zustand** for state (no Redux boilerplate)
- **TanStack Query** for server state + caching
- **Vercel AI SDK 6** for streaming chat + tool-call timeline + HITL approval
- **lucide-react** for icons

### 6.4 Information architecture
- Routes:
  - `/` — landing (goal-first onboarding)
  - `/session/:id` — workbench (4-pane layout)
  - `/gallery` — public sessions (stretch)
  - `/skills` — browse all 25+ skills the agent can call
- State persistence: every meaningful agent action saved to Postgres + pgvector

## 7. Backend / API

### 7.1 Stack
- **FastAPI** (Python 3.11+) + Uvicorn
- **SSE** (Server-Sent Events) via `sse-starlette` for streaming agent events
- **WebSocket** for bidirectional collaboration channel (stretch)
- **Pydantic v2** for tool schemas + request/response models
- **MCP server endpoints** at `/mcp/...` exposing all 25+ tools to any LLM

### 7.2 Endpoints (REST + SSE)
```
GET  /health
GET  /pathogens                              # 8 priority pathogens + metadata
POST /sessions                               # create session, returns session_id
GET  /sessions/:id                           # session state
GET  /sessions/:id/events  (SSE)             # streaming agent events
POST /sessions/:id/messages                  # user input → triggers agent loop
POST /sessions/:id/branch                    # fork from a node
POST /sessions/:id/intervene                 # user override (edit, take-over)
POST /sessions/:id/approve  (HITL)           # approve expensive tool call
GET  /sessions/:id/notebook                  # export as Jupyter
GET  /candidates/:id                         # candidate detail
POST /tools/:tool_name                       # direct tool invocation (MCP-compatible)
GET  /skills                                 # list all 25+ skills
```

### 7.3 SSE event types
```
event: agent_thought       data: {agent, thought, confidence}
event: tool_call_start     data: {tool, args, expected_duration}
event: tool_call_result    data: {tool, result, duration, error?}
event: candidate_added     data: {id, smiles, scores, parent_id}
event: lineage_updated     data: {tree}
event: approval_needed     data: {tool, args, reason}
event: agent_idle          data: {final_candidate?}
event: error               data: {code, message}
```

## 8. Tool Registry (Layer 0) — 25 tools, MCP-compatible

All tools are Pydantic-typed, MCP-server-exposed, K-Dense Skill-format-compatible.

### 8.1 AMR-specific (NEW — first set in Open Agent Skills standard)
```python
@tool def predict_mic_pathogen(smi: str, pathogen: Pathogen) -> MicPrediction
@tool def check_resistance_genes(smi: str, pathogen: Pathogen) -> list[ResistanceGene]
@tool def predict_resistance_escape(smi: str, pathogen: Pathogen) -> list[Mutation]
@tool def get_pathogen_resistome(pathogen: Pathogen) -> ResistomeSummary
@tool def find_active_against_mdr(target_set: list[Pathogen]) -> list[KnownDrug]
```

### 8.2 Structural / property scoring
```python
@tool def score_molecule(smi: str) -> RewardBreakdown                # 8-component
@tool def find_similar_drugs(smi: str, k: int = 5) -> list[SimilarDrug]
@tool def predict_admet(smi: str) -> AdmetProfile
@tool def predict_hemolysis(smi: str) -> HemolysisRisk
@tool def predict_synthesis_route(smi: str) -> RetrosynthesisTree    # AiZynthFinder
@tool def estimate_synth_cost(smi: str) -> CostEstimate
```

### 8.3 Generative (delegate to specialized models)
```python
@tool def propose_pocket_aware(target_pdb: str, n: int = 10) -> list[Smiles]   # PocketXMol
@tool def transform_structure(smi: str, op: TransformOp) -> Smiles             # REINVENT 4
@tool def scaffold_hop(smi: str) -> list[Smiles]                               # REINVENT 4
@tool def optimize_iteratively(smi: str, objective: Objective, n_steps: int) -> Trajectory
```

### 8.4 Structure / docking (Boltz-2 + DiffDock-L)
```python
@tool def predict_complex_structure(protein: str, ligand: str) -> Boltz2Result
@tool def predict_binding_affinity(protein: str, ligand: str) -> Affinity
@tool def dock_against_target(smi: str, pdb_id: str) -> DockingResult
```

### 8.5 Knowledge / retrieval
```python
@tool def search_literature(query: str, year_range: tuple) -> list[Paper]
@tool def get_drug_history(drug_name: str) -> DrugDevelopmentHistory
@tool def explain_mechanism(smi: str, target: str) -> Explanation
@tool def compare_molecules(a: str, b: str) -> MoleculeDiff
```

### 8.6 Sandbox
```python
@tool def execute_python(code: str, context: dict) -> ExecutionResult   # Pyodide
@tool def render_3d_scene(structure: str, ligands: list) -> MolStarScene
```

## 9. Multi-Agent State Machine (LangGraph)

### 9.1 Nodes
- **Designer** (Gemma 4 31B-it, designer prompt) — proposes candidate SMILES given target + constraints
- **Critic** (Gemma 4 31B-it, critic prompt) — scores candidate, identifies weakest reward dimension, suggests next move
- **Editor** (rule-based, RDKit + REINVENT 4) — applies critic's suggestion deterministically
- **Strategist** (lightweight LLM or rules) — decides loop termination, picks next sub-objective, manages curriculum
- **Memory** (pgvector retrieval) — fetches past candidates with similar profile for in-context examples

### 9.2 Edges (transitions)
```
Strategist --start--> Designer
Designer  --propose--> Critic
Critic    --high_score--> Strategist (continue or terminate)
Critic    --needs_edit--> Editor
Editor    --modified--> Critic
Strategist --loop_end--> Final_node
*         --user_intervene--> User_input_node
*         --user_branch--> Strategist (with new fork)
```

### 9.3 State schema
```python
class WorkbenchState(BaseModel):
    session_id: str
    target_pathogen: Pathogen
    constraints: list[Constraint]
    autonomy_level: Literal["auto", "copilot", "manual"]
    current_candidate: Candidate | None
    lineage: Tree[Candidate]
    history: list[AgentMessage]
    tools_used: list[ToolCallRecord]
    pareto_frontier: list[Candidate]
```

### 9.4 Time-travel + branching
- Every state transition is persisted (Postgres `agent_events` table).
- Branching = fork the state at a node-id, replay from there with new input.
- Replay = walk the state log forward, visualizing each tool call.

## 10. Foundation Model Integration

### 10.1 Gemma 4 31B-it (primary generator)
- Served via **vLLM ROCm** on MI300X.
- Function-calling enabled (Pydantic schemas → JSON for tool descriptions).
- Streaming JSON tool calls handled by Vercel AI SDK 6 on the frontend.
- Prompt templates for Designer, Critic, Strategist roles in `src/agents/prompts/`.

### 10.2 Boltz-2 (binding affinity + structure)
- Loaded on demand via Boltz-2 inference API (MIT-licensed).
- Coresident with Gemma 4 on MI300X (Boltz-2 is small, ~1-2 GB GPU RAM).
- Wrapped as `predict_complex_structure` and `predict_binding_affinity` tools.
- Fallback: cached results from prior runs in pgvector.

### 10.3 PocketXMol (pocket-aware proposer)
- Loaded on demand when target PDB is provided.
- Wrapped as `propose_pocket_aware` tool.
- Used when designer agent calls "I need a pocket-aware proposal".

### 10.4 REINVENT 4 (RL chemistry transforms)
- Wrapped as `transform_structure`, `scaffold_hop`, `optimize_iteratively` tools.
- Pre-compiled scoring TOML config aligned with our 8-component reward.

### 10.5 Gemini Embedding 2 (embeddings layer)
- API-based (`gemini-embedding-001`, 3072d Matryoshka).
- Used for: novelty reward (Stage 3 GRPO), RAG retrieval, similar-drug search.
- Cost: ~$0.025/1M tokens — well within budget.

## 11. Data Layer

### 11.1 Postgres schema
```sql
CREATE TABLE sessions (
  id UUID PRIMARY KEY,
  user_id UUID,
  target_pathogen TEXT NOT NULL,
  mode TEXT NOT NULL,                  -- design | red_team
  autonomy TEXT NOT NULL,              -- auto | copilot | manual
  constraints JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE candidates (
  id UUID PRIMARY KEY,
  session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
  parent_id UUID REFERENCES candidates(id),
  smiles TEXT NOT NULL,
  inchi_key TEXT,
  scores JSONB,                        -- 8-component reward
  embedding vector(3072),              -- Gemini Embedding 2
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON candidates USING ivfflat (embedding vector_cosine_ops);

CREATE TABLE agent_events (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,            -- thought | tool_call | candidate_added | ...
  agent TEXT,                          -- designer | critic | editor | strategist
  payload JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tool_calls (
  id UUID PRIMARY KEY,
  session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
  tool_name TEXT NOT NULL,
  args JSONB,
  result JSONB,
  duration_ms INTEGER,
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE constraints (
  id UUID PRIMARY KEY,
  session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
  type TEXT NOT NULL,                  -- property | smarts | exclude_pains | ...
  value JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 11.2 S3 / local FS layout
```
artifacts/
├── sessions/
│   └── {session_id}/
│       ├── pdbs/             # target structures
│       ├── docking/          # DiffDock outputs
│       ├── md/               # OpenMM trajectories
│       └── notebooks/        # exported Jupyter
└── shared/
    ├── pathogen_resistomes/
    └── known_antibiotics_index/
```

## 12. Security / Auth / Multi-tenancy (path to product)

- **v1 (hackathon)**: single-user, no auth, local Docker
- **v2 (post-hackathon)**: HF OAuth or magic-link email; per-user session isolation; per-org rate limiting
- **v3 (commercial)**: SSO, RBAC, audit logs, per-tenant Postgres schemas, signed S3 URLs
- **Per-tool rate limiting** even in v1 to prevent runaway expensive ops (Boltz-2, DiffDock)

## 13. Observability

- **LangSmith** traces every LangGraph state transition + tool call.
- **Phoenix Arize** for OTel traces of the inference layer (latency, throughput, error rate).
- **OpenTelemetry** at the FastAPI level (request latency, SSE throughput).
- **Custom event log** (Postgres `agent_events`) for replay + debugging.
- **wandb** for the training-side traces (Stage 1/2/3 — separate from the Workbench).

## 14. Build phases — Day-by-day

### Phase 0: Pre-kickoff (Sat May 3 PM → Sun May 4 AM, no MI300X)
- Goal: scaffold the entire Workbench and demo end-to-end with Claude Sonnet 4.7 as placeholder
- Deliverables:
  - Monorepo at `workspace/` (FastAPI + React 19 + Vite)
  - LangGraph 4-agent state machine
  - 10 baseline tools (the AMR-specific 5 + score_molecule + find_similar_drugs + predict_complex_structure + transform_structure + execute_python)
  - 4-pane UI with Mol* + 3Dmol.js + RDKit-JS + chat + lineage tree (skeleton)
  - SSE streaming end-to-end
  - Postgres schema + migrations
  - Docker Compose for local dev
- Done when: a user can pick MRSA, watch the placeholder agent propose 3 candidates, see them scored, see them on the lineage tree, see tool calls in the timeline.

### Phase 1: Day 1 (Mon May 4) — kickoff, Stage 1 training
- Workbench parallel: add 10 more tools (admet, hemolysis, synthesis_route, dock_against_target, predict_resistance_escape, etc)
- Polish lineage tree + Pareto explorer
- Build constraint bar + drag-edit functional groups
- Goal: 20/25 tools complete, 12/25 creative features

### Phase 2: Day 2 (Tue May 5) — Stage 2 training
- Workbench parallel: multi-agent debate UI (4 columns visible)
- Build-vs-break mode toggle + red-team workflow
- Pyodide sandbox cells in chat
- Goal: 25/25 tools, 18/25 creative features

### Phase 3: Day 3 (Wed May 6) — Stage 3 RL training
- Workbench parallel: pocket overlay (Boltz-2 binding pose) + DiffDock integration
- Replay scrubber
- Constraint synthesis from paper abstract
- Goal: 22/25 creative features, polish + bug fixes

### Phase 4: Day 4 (Thu May 7) — RL training finishes, MODEL SWAP
- **Single config flip: Claude API → vLLM Gemma 4 31B on MI300X**
- Smoke test: rerun a known session with the new model, compare outputs
- Capture wandb screenshots + rocm-smi for the demo
- Goal: 25/25 features, real Lysos model serving

### Phase 5: Day 5 (Fri May 8) — record, polish, public-gallery
- Record demo video showing the agentic loop
- Public gallery URL (read-only) for community sessions
- Notebook export polish
- Goal: submission-ready

### Phase 6: Day 6 (Sat May 9) — submit early
- Final submission package
- Build-in-public posts
- Submitted ~24h before deadline

## 15. Tasks — Numbered, with dependencies

### Phase 0 tasks (pre-kickoff)
1. **[P0-1]** Create `workspace/` monorepo with FastAPI backend + React 19 frontend skeletons
2. **[P0-2]** Set up Docker Compose with Postgres + pgvector + Redis
3. **[P0-3]** Postgres schema + migrations (sessions, candidates, agent_events, tool_calls, constraints)
4. **[P0-4]** FastAPI base — health, pathogens, sessions, SSE endpoint
5. **[P0-5]** Implement 5 AMR-specific tools (predict_mic_pathogen, check_resistance_genes, predict_resistance_escape, get_pathogen_resistome, find_active_against_mdr)
6. **[P0-6]** Implement 5 baseline tools (score_molecule, find_similar_drugs, predict_complex_structure-stub, transform_structure, execute_python)
7. **[P0-7]** LangGraph state machine with Designer/Critic/Editor/Strategist nodes
8. **[P0-8]** Wire Claude Sonnet 4.7 as placeholder via Anthropic API
9. **[P0-9]** Frontend: 4-pane layout with Tailwind + shadcn/ui shells
10. **[P0-10]** Frontend: Mol* embed with sample PDB
11. **[P0-11]** Frontend: 3Dmol.js molecule cards
12. **[P0-12]** Frontend: RDKit-JS 2D rendering
13. **[P0-13]** Frontend: SSE streaming chat with Vercel AI SDK 6
14. **[P0-14]** Frontend: tool-call timeline component
15. **[P0-15]** Frontend: lineage tree (basic) with d3-tree
16. **[P0-16]** Frontend: reward radar (8-axis polar chart)
17. **[P0-17]** Frontend: pathogen selector + autonomy slider
18. **[P0-18]** End-to-end smoke: pick MRSA → agent proposes 3 candidates → all visible

### Phase 1-3 tasks (Day 1-3)
19. **[P1-1..15]** Add tools 11-25 (admet, hemolysis, synthesis_route, dock_against_target, etc.)
20. **[P2-1..6]** Multi-agent debate columns + build-vs-break toggle + Pyodide cells
21. **[P3-1..4]** Pocket overlay + DiffDock + replay scrubber + constraint-from-paper

### Phase 4 tasks (Day 4 — model swap)
22. **[P4-1]** Deploy vLLM ROCm with Gemma 4 31B-it on MI300X
23. **[P4-2]** Test function-calling format compatibility
24. **[P4-3]** Update `LYSOS_LLM_ENDPOINT` env var → swap from Claude to vLLM
25. **[P4-4]** Run regression test (compare known session outputs Claude-vs-Gemma)
26. **[P4-5]** Capture wandb + rocm-smi screenshots for demo

### Phase 5-6 tasks (record + submit)
27. **[P5-1]** Record 5-min demo video
28. **[P5-2]** Public gallery (read-only sessions)
29. **[P5-3]** Notebook export polish
30. **[P6-1]** Submit to lablab portal
31. **[P6-2]** Final social posts

## 16. File-by-file module layout

```
workspace/
├── api/                                  # FastAPI backend
│   ├── server.py                         # FastAPI app + routes
│   ├── sse.py                            # SSE event bus
│   ├── deps.py                           # dependency injection
│   ├── auth.py                           # (v2) auth middleware
│   ├── schemas/                          # Pydantic request/response models
│   │   ├── sessions.py
│   │   ├── candidates.py
│   │   ├── tools.py
│   │   └── events.py
│   ├── routers/
│   │   ├── sessions.py
│   │   ├── tools.py
│   │   └── mcp.py                        # MCP endpoint exposing all tools
│   ├── db/
│   │   ├── models.py                     # SQLAlchemy models
│   │   ├── migrations/                   # Alembic
│   │   └── pgvector_setup.sql
│   └── tests/
├── agents/                               # LangGraph state machine
│   ├── graph.py                          # main state graph
│   ├── nodes/
│   │   ├── designer.py
│   │   ├── critic.py
│   │   ├── editor.py
│   │   └── strategist.py
│   ├── prompts/                          # role-specific prompt templates
│   │   ├── designer.md
│   │   ├── critic.md
│   │   ├── strategist.md
│   │   └── system.md
│   ├── memory.py                         # pgvector retrieval
│   ├── llm.py                            # LLM endpoint abstraction (Claude/vLLM swap)
│   └── tests/
├── tools/                                # MCP-compatible tool registry
│   ├── __init__.py
│   ├── base.py                           # @tool decorator + Pydantic schemas
│   ├── amr/                              # AMR-specific (the new contribution)
│   │   ├── predict_mic_pathogen.py
│   │   ├── check_resistance_genes.py
│   │   ├── predict_resistance_escape.py
│   │   ├── get_pathogen_resistome.py
│   │   └── find_active_against_mdr.py
│   ├── scoring/
│   │   ├── score_molecule.py
│   │   ├── predict_admet.py
│   │   ├── predict_hemolysis.py
│   │   └── ...
│   ├── generative/
│   │   ├── propose_pocket_aware.py       # PocketXMol
│   │   ├── transform_structure.py        # REINVENT 4
│   │   └── scaffold_hop.py
│   ├── structural/
│   │   ├── predict_complex_structure.py  # Boltz-2
│   │   ├── predict_binding_affinity.py
│   │   └── dock_against_target.py        # DiffDock-L
│   ├── knowledge/
│   │   ├── search_literature.py
│   │   ├── get_drug_history.py
│   │   └── explain_mechanism.py
│   ├── sandbox/
│   │   ├── execute_python.py
│   │   └── render_3d_scene.py
│   └── tests/
├── web/                                  # React 19 frontend
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── components/
│   │   │   ├── ChatPanel.tsx
│   │   │   ├── ToolCallTimeline.tsx
│   │   │   ├── LineageTree.tsx
│   │   │   ├── RewardRadar.tsx
│   │   │   ├── MolViewer.tsx             # Mol*
│   │   │   ├── MolCard.tsx               # 3Dmol.js
│   │   │   ├── Mol2D.tsx                 # RDKit-JS
│   │   │   ├── ConstraintBar.tsx
│   │   │   ├── PathogenSelector.tsx
│   │   │   ├── AutonomySlider.tsx
│   │   │   ├── ParetoExplorer.tsx
│   │   │   └── PyodideCell.tsx
│   │   ├── api/                          # typed API client
│   │   │   ├── sessions.ts
│   │   │   ├── tools.ts
│   │   │   └── sse.ts
│   │   ├── stores/                       # Zustand
│   │   │   ├── sessionStore.ts
│   │   │   └── lineageStore.ts
│   │   ├── lib/
│   │   │   ├── molstar.ts
│   │   │   ├── threedmol.ts
│   │   │   └── rdkit.ts
│   │   └── types.ts
│   ├── public/
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── tsconfig.json
├── docker-compose.yml                    # postgres + redis + api + web
├── Dockerfile.api
├── Dockerfile.web
└── README.md
```

## 17. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ROCm + vLLM + Gemma 4 31B function-calling incompatibility | Medium | High | Test pre-kickoff with smaller Gemma; fall back to Claude API if blocking |
| Boltz-2 ROCm wheels not ready | Medium | Medium | CPU inference fallback (slower but works); use cached results during demo |
| LangGraph + LangSmith eat too much context window | Low | Medium | Trim conversation history aggressively; only keep last 3 turns + summary |
| Stage 3 GRPO ROCm training fails | Medium | High | Captured in tech-spec.md risks; fall back to DPO (one-line config flip) |
| Mol* loading slow for large proteins | Low | Low | Lazy-load + progressive surface generation |
| Pyodide bundle too heavy (40+ MB) | Low | Low | Code-split; load only when user opens a sandbox cell |
| HITL approval interrupts demo flow | Low | Medium | Auto-approve cheap tools; require approval only for >5s ops |
| Demo video too long | Medium | Low | Storyboard at 4:30 max; cut ruthlessly |
| Pareto chart with 100+ candidates renders slowly | Low | Low | Canvas instead of SVG; downsample below 500 |
| Multi-agent debate confusing for judges | Medium | Medium | Each agent's column collapsible; default-collapsed all but Designer |

## 18. Definition of Done — per phase

### Phase 0 (pre-kickoff)
- [ ] Pick MRSA → agent proposes 3 candidates with placeholder model
- [ ] All 3 candidates render in Mol* + 3Dmol.js + RDKit-JS
- [ ] Tool-call timeline shows 10+ tool calls with results
- [ ] Lineage tree shows 3-node graph
- [ ] SSE streaming end-to-end with no dropped events
- [ ] Postgres persists sessions + candidates + events
- [ ] Docker Compose boots all services in <60s

### Phase 4 (model swap)
- [ ] Gemma 4 31B-it serves on vLLM ROCm
- [ ] Function-calling JSON parses correctly
- [ ] Same session inputs produce semantically similar outputs vs Claude
- [ ] No latency regression beyond 2x (acceptable for demo)
- [ ] Wandb + rocm-smi screenshots captured

### Phase 6 (submit)
- [ ] Public HF Space deployed with demo session preloaded
- [ ] 5-min demo video on YouTube
- [ ] Pitch deck PDF on lablab portal
- [ ] Submission writeup at 280/1500/250-word lengths
- [ ] All HF artifacts (datasets, models, Space) live and indexable

## 19. Stretch (post-hackathon)
- Multi-user collaboration (cursor-style live presence)
- Public gallery + leaderboard
- Plugin SDK — third parties add tools via `@tool` decorator + K-Dense skill format
- Real wet-lab integration via Coscientist-pattern robotics API
- Mobile-responsive (tablet at minimum)
- Per-org rate limiting + tenant isolation
- API as a product (programmatic users alongside UI users)
- Custom training on the user's own dataset (Stage 2 fine-tune in browser)
- VR mode (Mol* supports it)

## 20. References / sources

### Direct competitors
- [PlayMolecule AI](https://playmolecule.ai/) — first agentic superintelligence in molecular design
- [Speak to a Protein (arxiv 2510.17826)](https://arxiv.org/abs/2510.17826) — interactive multimodal protein co-scientist
- [FutureHouse](https://www.futurehouse.org/) — AI co-scientist agents (Crow / Falcon / Owl / Phoenix / Robin)
- [K-Dense BYOK](https://github.com/K-Dense-AI/k-dense-byok) — open-source desktop AI co-scientist
- [K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills) — 135 skills, open Agent Skills standard
- [ChemAgent](https://github.com/gersteinlab/ChemAgent) — ICLR 2025 self-updating chemistry library
- [open-coscientist-agents](https://github.com/conradry/open-coscientist-agents) — Google DeepMind co-scientist clone
- [Sakana AI Scientist](https://sakana.ai/ai-scientist-nature/) — Nature 2026
- [Virtual Biotech (bioRxiv 2026)](https://www.biorxiv.org/content/10.64898/2026.02.23.707551v1)

### Foundation models
- [Boltz-2 (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12262699/) — affinity prediction at FEP-level
- [PocketXMol (Cell 2026)](https://www.cell.com/cell/fulltext/S0092-8674(26)00050-4) — pocket-aware atom-level
- [REINVENT 4](https://github.com/MolecularAI/REINVENT4) — RL chemistry generative
- [DiffDock-L assessment](https://pmc.ncbi.nlm.nih.gov/articles/PMC11142318/) — generative docking benchmark

### Frameworks
- [LangGraph](https://langfuse.com/blog/2025-03-19-ai-agent-comparison) — production agent orchestration
- [Vercel AI SDK 6](https://vercel.com/blog/ai-sdk-6) — ToolLoopAgent + HITL
- [Anthropic Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview) — Tool Search Tool
- [Speakeasy framework comparison](https://www.speakeasy.com/blog/ai-agent-framework-comparison)

### Visualization
- [Mol* in Protein Science 2026](https://onlinelibrary.wiley.com/doi/abs/10.1002/pro.70514) — web 3D molecular graphics
- [3Dmol.js](https://3dmol.csb.pitt.edu/)
- [RDKit-JS](https://www.rdkitjs.com/)

### UX patterns 2026
- [Designing For Agentic AI - Smashing Magazine 2026](https://www.smashingmagazine.com/2026/02/designing-agentic-ai-practical-ux-patterns/)
- [Beyond Generative: Rise Of Agentic AI - Smashing Magazine 2026](https://www.smashingmagazine.com/2026/01/beyond-generative-rise-agentic-ai-user-centric-design/)
- [Secrets of Agentic UX - UX Magazine](https://uxmag.com/articles/secrets-of-agentic-ux-emerging-design-patterns-for-human-interaction-with-ai-agents)
- [State of Design 2026 - When Interfaces Become Agents - Medium](https://tejjj.medium.com/state-of-design-2026-when-interfaces-become-agents-fc967be10cba)

### Generative AMR (prior art)
- [De novo antibiotic design - Cell 2025](https://www.cell.com/cell/abstract/S0092-8674(25)00855-4) — MIT Broad, 36M generated, 2 leads bactericidal
- [AI antimicrobial discovery - MDPI 2026](https://www.mdpi.com/2076-2607/14/2/394)
- [ChemCrow - Nature 2024](https://www.nature.com/articles/s42256-024-00832-8)

### Multi-agent in drug discovery
- [AI agents in drug discovery - ScienceDirect 2026](https://www.sciencedirect.com/science/article/pii/S1359644626000553)
- [Democratising real-world drug discovery through agentic AI - ScienceDirect 2026](https://www.sciencedirect.com/science/article/pii/S1359644626000103)

---

**Status: spec locked. Phase 0 begins now.**
