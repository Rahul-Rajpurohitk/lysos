# Session log — 2026-05-03 — Workbench spec locked

## Context
T-1 to AMD Hackathon kickoff. Stage 2 v2.3 dataset live on HF. Stage 3 RL prompts re-split (266-prompt leak fixed). 5 validation scripts passing. 3 real bugs caught + fixed pre-kickoff. Embedding stack truth-aligned to Gemini Embedding 2 across all docs/UI/assets.

## Decision
Build the **Lysos Workbench** — an agentic, multi-model interactive playground where the trained Lysos model designs, evaluates, edits, and red-teams antibacterial candidates against drug-resistant pathogens. Spec locked.

## Spec deliverables
- `docs/workbench-spec.md` — full 20-section spec (38 KB) with market research, 8-layer architecture, 25 tool registry, multi-agent state machine, file-by-file module layout, 31 numbered tasks, risk matrix, definition of done.
- `vault/plans/active/2026-05-03-lysos-workbench-agentic-playground.md` — mirror in Obsidian vault.
- 18 Phase-0 tasks created in TaskCreate for execution tracking.

## Key research findings (May 2026)
- **PlayMolecule AI** is the closest competitor (18K researchers, agentic UI, Pyodide sandbox + 3D + chat) — closed inference, generic drug discovery, no AMR focus.
- **Speak to a Protein** (arxiv 2510.17826) is closest UX inspiration (MCP servers + chat + 3D + sandbox) — protein analysis only, no design loop.
- **K-Dense Scientific Agent Skills** (135 skills, open Agent Skills standard) is the skill-format we adopt — no AMR skills exist yet, we contribute the first set.
- **Boltz-2** (MIT) is FEP-level affinity prediction at 1000x speed — affinity reward + binding pose tool.
- **PocketXMol** (Cell 2026) is atom-level pocket-aware generation foundation model — pocket-aware proposer tool.
- **REINVENT 4** (Apache, MolecularAI) is the RL chemistry framework — scaffold-hop / R-group / linker tools.
- **MIT Broad Cell 2025** generated 36M compounds, 24 synthesized, 7 active, 2 leads bactericidal vs MRSA + N. gonorrhoeae — static pipeline, NOT interactive. We add the agentic layer.

## Stack locked
- LangGraph for orchestration (400 production deployments incl JPMorgan/Cisco/LinkedIn)
- MCP for tool layer (Anthropic + Speak-to-a-Protein + K-Dense convergent)
- Vercel AI SDK 6 for frontend chat (ToolLoopAgent, needsApproval HITL)
- Mol* (RCSB-grade) + 3Dmol.js + RDKit-JS + Pyodide for visualization
- Postgres + pgvector for persistence
- vLLM ROCm for serving Gemma 4 31B-it on MI300X (Day 4 swap)
- Claude Sonnet 4.7 as placeholder until Day 4

## Differentiators
1. AMR-first (not generic drug discovery)
2. Multi-agent debate VISIBLE (4 columns)
3. Build-vs-break red-team mode (novel)
4. Open weights end-to-end (Gemma 4 + Boltz-2 + PocketXMol + REINVENT 4)
5. MI300X-native (192 GB enables coresident)
6. Open Agent Skills format (contributes back to K-Dense ecosystem)

## Next
Phase 0 starts now. P0-1 through P0-18 in TaskCreate. End of Phase 0 = end-to-end demo with placeholder model before Mon May 4 noon EDT kickoff.

## References
See `docs/workbench-spec.md` Section 20 for the full source list.
