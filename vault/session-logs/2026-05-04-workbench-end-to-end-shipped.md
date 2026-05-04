# Session log — 2026-05-04 — Workbench end-to-end shipped

## Context
T-0 (kickoff is today, May 4, noon EDT). All non-GPU artifacts of the
Workbench shipped end-to-end. Phase 0 + Phase 1 + Phase 1.5 + Phase 2
of the agentic playground spec all complete and verified.

## What shipped tonight (one continuous heavy build)

### Tools — full 25-tool registry
- `amr/` (5): predict_mic_pathogen, check_resistance_genes,
  predict_resistance_escape, get_pathogen_resistome, find_active_against_mdr
- `scoring/` (6): score_molecule, find_similar_drugs, predict_admet,
  predict_hemolysis, predict_synthesis_route, estimate_synth_cost
- `generative/` (4): transform_structure, propose_pocket_aware,
  scaffold_hop, optimize_iteratively
- `structural/` (3): predict_complex_structure, predict_binding_affinity,
  dock_against_target
- `knowledge/` (5): search_literature, get_drug_history, explain_mechanism,
  compare_molecules, find_target_structure
- `sandbox/` (2): execute_python, render_3d_scene
- All Pydantic-typed, MCP-compatible, K-Dense Skill-format compatible,
  exposed via /workbench/tools/{name} for direct invocation.

### Multi-agent layer
- LangGraph-style state machine with 4 nodes (Designer / Critic / Editor /
  Strategist) in `agents/graph.py`
- `run_workbench_loop` for design mode + `run_red_team_loop` for build-vs-break
- 3 LLM backends: Claude (default placeholder) / vLLM Gemma 4 31B (Day-4
  swap) / mock (deterministic for tests)
- Per-iteration SSE event emission

### FastAPI Workbench routes (8)
- POST   /workbench/sessions
- GET    /workbench/sessions/{id}
- POST   /workbench/sessions/{id}/start
- GET    /workbench/sessions/{id}/events  (SSE)
- GET    /workbench/sessions/{id}/notebook  (export as Jupyter)
- GET    /workbench/skills  (full registry)
- POST   /workbench/tools/{name}  (MCP-compatible direct invocation)
- GET    /workbench/pathogens

### Frontend — light-theme React 19 + Vite Workbench page
Components in `web/src/workbench/components/`:
- `Workbench.tsx` — 4-pane layout with header (pathogen+mode+autonomy+iters
  +export+reset), 3-column main grid, bottom drawers
- `MolViewer.tsx` — 3Dmol.js (lazy CDN) for protein-ligand 3D
- `Mol2D.tsx` — RDKit-JS canvas-draw (no innerHTML)
- `RewardRadar.tsx` — Recharts 8-axis polar radar with current-vs-previous overlay
- `LineageTree.tsx` — pure-SVG git-graph with Pareto stars
- `ChatPanel.tsx` — multi-agent stream (role-coloured messages)
- `MultiAgentColumns.tsx` — 4 vertical streams toggle (Designer/Critic/
  Editor/Strategist columns)
- `ParetoExplorer.tsx` — Recharts 2D scatter with axis selectors
- `ToolCallTimeline.tsx` — collapsible call records with json args/result
- `CandidateList.tsx` — compact list with composite + Pareto stars
- `MoAPanel.tsx` — slide-out side panel (mechanism + resistance concerns)
- `FunctionalGroupPalette.tsx` — 10-button drag-edit palette
- `ReplayScrubber.tsx` — time-travel slider with play/pause/speed
- `ConstraintBar.tsx` — declarative constraint chips with 8 presets
- `ConstraintFromPaper.tsx` — paste abstract → extract constraints (regex v0)
- `SynthesisTree.tsx` — SA gauge + cost panel + interpretation
- `KnowledgeGraph.tsx` — pathogen × resistance × drug-class network (radial SVG)

State: Zustand store + typed REST/SSE client + React Router routes
(`/` legacy, `/workbench` new).

Build clean: 2,395 modules / 640 KB JS / 181 KB gzipped / 1.53s.

### Postgres + Docker
- `workspace/api/db/init/01_schema.sql` — 5 tables (sessions, candidates,
  agent_events, tool_calls, constraints) + 1 view (v_best_candidate)
- `workspace/api/db/repository.py` — psycopg-based repos (no-op fallback
  if Postgres unavailable)
- `workspace/api/notebook.py` — nbformat v4 export of complete session
- `workspace/docker-compose.yml` — Postgres pgvector/pgvector:pg16 + Redis 7
  + API + Web with healthchecks, env-driven LLM backend
- `workspace/Dockerfile.api` — Python 3.11 + RDKit + FastAPI
- `workspace/Dockerfile.web` — Multi-stage node→nginx with /workbench proxy
- `workspace/requirements-api.txt` — 18 runtime deps pinned

### Tests
- `workspace/tests/test_tools.py` — 13 unit tests, ALL PASS:
  - registry has exactly 25 tools
  - all 5 AMR tools present
  - get_pathogen_resistome MRSA → 4 genes including mecA
  - predict_mic_pathogen returns valid reward in [0, 1]
  - score_molecule returns 8-component breakdown
  - predict_admet computes MW/Lipinski
  - transform_structure swap_chloro_to_fluoro works
  - compare_molecules Tanimoto bounded
  - get_drug_history(linezolid) returns 2000 approval year
  - find_target_structure(MRSA) returns PDB 1VQQ
  - predict_resistance_escape(VRE) returns mutations
  - invalid SMILES → validity=0 (graceful)
  - schemas_for_anthropic format compatible

### Live FastAPI smoke (uvicorn 127.0.0.1:7861)
- GET  /workbench/skills → total=25, 6 categories ✓
- GET  /workbench/pathogens → 8 priority pathogens ✓
- POST /workbench/sessions → valid UUID returned ✓
- POST /workbench/tools/get_pathogen_resistome → MRSA: 4 genes,
  first_line=[vancomycin, daptomycin] ✓

### Smoke tests (in-process)
- Mock LLM design loop: MRSA → propose linezolid → score (composite=0.859)
  → similar drugs found → Strategist TERMINATE ✓
- Red-team mode: MRSA → 4-gene resistome loaded → 5-drug panel →
  "Red-team analysis complete" ✓
- 8 new tools tested individually: PBP2a target lookup, ADMET (MW 337,
  QED 1.00), hemolysis safe, $50/g 3-step synthesis, Tanimoto vs
  ciprofloxacin, ΔG=-9.85 nanomolar binding, drug history retrieved ✓

## What remains for Day 1+ (GPU-blocked or Day-1+ work)

- ROCm + Gemma 4 31B-it smoke test on MI300X
- Real Boltz-2 + PocketXMol + REINVENT 4 inference (replace synthetic_dev)
- vLLM Gemma 4 31B serving — single env flip on Day 4
  (`LYSOS_LLM_BACKEND=vllm`)
- HF Space deploy (workspace Dockerfile + nginx proxy ready)
- Demo video recording (needs trained model + final UI polish)

## Files changed today (workspace-only)

Backend Python (~3K lines):
  agents/        (5 files: __init__, state, llm, prompts, graph)
  api/           (workbench.py, notebook.py, db/{__init__, repository,
                  init/01_schema.sql})
  tools/         (25 tool files across 6 categories + base.py + __init__s)
  tests/         (test_tools.py — 13 tests)

Frontend TypeScript (~2.5K lines):
  web/src/workbench/
    Workbench.tsx, types.ts, api.ts, store.ts
    components/ (15 files)
  web/src/main.tsx (router)

DevOps:
  docker-compose.yml, Dockerfile.api, Dockerfile.web, requirements-api.txt

Docs (yesterday — already shipped):
  docs/workbench-spec.md (38 KB, 20 sections)
  vault/plans/active/2026-05-03-lysos-workbench-agentic-playground.md
  vault/session-logs/2026-05-03-workbench-spec-locked.md

## Commit history this push (since spec lock)

- 0b44d5d Workbench spec locked
- 5d2056a Phase 0 — agentic playground scaffolded end-to-end
- 8081182 Phase 1 — 25 tools, Postgres + Docker, multi-agent UI, Pareto
- fa9d683 Phase 1.5 — red-team + drag-edit + replay + MoA + constraints
- 1ee61af Phase 2 — notebook export + synth tree + knowledge graph + tests

All pushed to github.com/Rahul-Rajpurohitk/lysos main.

## Next session
Day 1 (Mon May 4 noon EDT): ROCm smoke + Gemma 4 31B-it boot on MI300X +
real Boltz-2/PocketXMol/REINVENT 4 ROCm wheels. Workbench is ready to
consume the trained models on Day 4 with a single env flip.
