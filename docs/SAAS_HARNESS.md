# Lysos SaaS — Harness Architecture

Living spec. Source of truth for what we're building. Updated as decisions
are made. Read this before opening a new feature PR.

## 1. Mental model

**Lysos = the harness around a trained policy.**
The MI300X-trained Gemma 4 31B is a generative drug-design policy. The
SaaS *is* the harness that surrounds it: tools, scoring, UI, agents,
storage, replay. The harness IS the product. Without it the model is
just a checkpoint; with it the user can do work that's worth paying for.

```
                 ┌────────────────────────────────────┐
                 │           Lysos SaaS                │
                 │   (this repo, web + backend)        │
                 │                                     │
   user ────►    │  workflows (W1…W8)                  │  ◄──── 12-axis
                 │      ↓                              │       reward stack
                 │  Orchestrator agent (always aware)  │       (RDKit, ADMET,
                 │      ↓                              │        hemolysis,
                 │  4 specialist agents                │        novelty, …)
                 │  (Designer · Critic · Editor ·      │
                 │   Strategist) + 9 sub-agents        │
                 │      ↓                              │
                 │  policy-call → Gemma 4 31B (MI300X) │  ◄──── trained
                 │      ↓                              │       checkpoint
                 │  trace → SQLite + JSONL + WS        │
                 └────────────────────────────────────┘
```

## 2. Workflow taxonomy (the value units)

| # | User goal | Status | Surfaces | Endpoints |
|---|---|---|---|---|
| **W1** | Design me an antibiotic | planned | chat + 3D + radar | `POST /workbench/design` |
| **W2** | Score this molecule | **building** | radar + chat-card | `POST /workbench/score` |
| **W3** | Explore SAR around a scaffold | planned | scaffold tree + 3D + radar | `POST /workbench/sar/expand` |
| **W4** | Explain this target/mechanism | planned | right artifact pane | `POST /workbench/explain` |
| **W5** | Stress-test a candidate | planned | chat + radar overlay | `POST /workbench/branch` |
| **W6** | Compare N candidates | planned | comparison view | `POST /workbench/compare` |
| **W7** | Replay a session | planned | timeline scrubber | `GET /workbench/sessions/{id}/events` |
| **W8** | Save / organize my work | planned | projects panel | sessions/candidates SQLite (already exists) |

**Build order**: W2 → W1 → W4 → W3 → W5 → W6 → W7+W8.
Reasoning: W2 is the smallest, deterministic, end-to-end test of the
reward stack + chat card render. Once it works, W1 reuses every piece
plus the agent loop. W4 earns the right-pane artifact panel. W3 / W5 /
W6 are scaffolds-on-top.

## 3. Orchestrator agent

A new agent: **the Orchestrator**. Always aware of every sub-agent's
state. Routes user messages, decides debate vs. single-agent dispatch,
reconciles parallel threads.

| Property | Value |
|---|---|
| File | `workspace/agents/orchestrator.py` |
| Entrypoint | `Orchestrator.dispatch(session, message, reply_to=None)` |
| State | reads/writes the same `WorkbenchState` graph.py owns |
| Routing | slash command → cmd handler · `reply_to=<agent>` → that agent only · default → full debate (Designer→Critic→Editor→Strategist) |
| Trace | every dispatch is wrapped in `tracer.span("orchestrator.dispatch")` |
| Aware of | every agent message, tool call, candidate emission, score, user edit, scene event |

The Orchestrator is **NOT** a replacement for the 4 specialists — it's
the dispatcher in front of them, plus the running summary keeper.

## 4. Agent routing modes (combined)

| Mode | Trigger | Effect |
|---|---|---|
| Slash-routed | `/design`, `/critique`, `/edit`, `/plan` | Single-agent dispatch (Designer/Critic/Editor/Strategist) |
| Reply-to | Hover an agent's chat bubble → "↩ Reply to Critic" | Parallel thread scoped to that one agent |
| Full debate | Plain prompt | Default 4-agent loop via Orchestrator |

**No `@`-mentions** — feels chat-app-y, parser fragile.

## 5. Agent message tagging UI

Each `agent_message` in the chat carries:
- `agent_id` — Designer / Critic / Editor / Strategist / Orchestrator / user
- `thread_id` — main thread or a spawned reply-to thread
- `parent_msg_id` — the message this is replying to (if any)

Hover an agent message → reveal `↩ Reply to <agent>` action. Click →
inline mini-composer scoped to that agent. New messages append with
`thread_id = parent.thread_id` so parallel debates render cleanly.

## 6. Per-workflow contracts

### W2 — Score (building now)

**Request:**
```http
POST /workbench/score
{ "smiles": "CCO", "target_pathogen": "MRSA" }
```

**Response:**
```json
{
  "smiles": "CCO",
  "composite": 0.42,
  "components": {
    "validity": 1.0, "drug_likeness_qed": 0.31, "synthesizability": 0.85,
    "hemolysis_safety": 0.92, "novelty": 0.55, "embedding_novelty": 0.61,
    "mic_estimate": 0.18, "pose_quality": 0.0, "spectrum_match": 0.30,
    "resistance_robustness": 0.40, "synth_cost": 0.78, "pareto_entry": 0.0
  },
  "weights": { "validity": 0.10, "drug_likeness_qed": 0.10, ... }
}
```

**UI render:** new chat card type `score_card` shows composite (big), per-
component bar list, accent-colored. Click → expands to full radar + per-
axis explanation (already-exists via existing radar component).

### W1 — Design (next)

**Request:**
```http
POST /workbench/design
{
  "pathogen": "MRSA",
  "objective": "non-toxic macrolide that escapes mecA",
  "constraints": [{"id":"mw","label":"MW < 500"}],
  "iters": 10
}
```

**Response:** streamed via WS — agent_message events from each specialist
+ candidate_added events + iteration_end with composite.

### W4 — Explain (after W1)

**Request:** `POST /workbench/explain { "target": "mecA / PBP2a" }`
**Response:** streamed markdown blocks. Renders into ArtifactPanel right pane.

## 7. Build process (meta-workflow)

This is the workflow we follow to build the workflows.

1. **Plan** — open this doc, pick the next workflow, write its contract
   in §6 if not already there
2. **Backend** — add the endpoint, reuse existing reward/agent/tool
   modules where possible
3. **Smoke test** — curl the endpoint with the canonical input,
   confirm response shape matches the spec
4. **Frontend** — render the response in the chat card / panel
5. **Integration** — wire the slash command + the starter chip + (if
   applicable) a UI launcher button
6. **End-to-end** — vite dev + uvicorn dev, click through the flow,
   confirm trace events fire, confirm 3D / radar updates, confirm
   reply-to threads work
7. **Commit** — single descriptive commit with workflow tag (`W2: score`)
8. **Mark task** — TaskUpdate to completed

No half-shipped workflows. Each W lands fully wired or not at all.

## 8. Shared invariants

- All chat events go through the harness `Tracer` — every action is
  replay-friendly
- All workflow endpoints live under `/workbench/*` — never bypass
- Orchestrator is the sole entry point for free-form user prompts
- Slash commands always go through the registry, never reimplemented
  in routes
- Score is the canonical scalar — every workflow's rewards must use the
  same `score_molecule` to stay consistent
- 3D scene is event-sourced; never mutate state out of band
- Backend is FastAPI; frontend is React + Vite + Allotment; nothing else
  joins without writing it down here first

## 8.5 LLM tiers — agent-tier vs utility-tier (intentional separation)

The agentic system **does NOT** call Gemini or Claude for any drug-design
decision. The trained Lysos-Gemma is the only model that ever sees a
candidate molecule, a critic challenge, or a strategist directive.

| Tier | Who | Model | Why |
|---|---|---|---|
| **Agent** | Designer / Critic / Editor / Strategist (graph.py) | `get_llm()` → `LysosEndpoint` → vLLM-served Gemma 4 31B (the MI300X policy) | The whole point of training |
| **Orchestrator meta-Q&A** | "what has Critic been arguing?" / `/summary` | Pure Python from the ledger | Grounded, deterministic, free |
| **Tools** | RDKit, Boltz-2, ADMET, sascorer, dock | Deterministic | No LLM territory |
| **Utility** | Auto-title chat tabs only | Gemini 2.5 Flash (REST) | 500ms cheap one-shot, doesn't touch agents |

### Auto-title cost controls (`workspace/api/chat.py`)

Env knobs:
- `LYSOS_AUTOTITLE_BACKEND` — `gemini` (default) | `lysos` | `fallback`
- `LYSOS_AUTOTITLE_MAX_PER_DAY` — process-wide cap (default 200)
- `LYSOS_AUTOTITLE_MAX_PER_SESS` — per-chat cap (default 8)
- `LYSOS_AUTOTITLE_MIN_GAP_SEC` — min seconds between calls per session (default 4)

Frontend throttles (`useAutoTitle.ts`):
- Only the **active** chat tab triggers a call (background tabs keep stale)
- Min 1 user message + ≥3 events since last summarization
- 600ms debounce
- Skipped permanently after a manual rename (`userRenamed` flag)

Worst-case daily cost at 200 calls × ~1.5K input + 50 output tokens:
~$0.025/day with Gemini Flash pricing (~$0.75/month). Realistic usage
during a demo is < 30 calls/day → < $0.005.

### Swap path (when Lysos-Gemma is deployed)

1. Run vLLM with the Lysos checkpoint locally or on the demo machine
   (or point `LYSOS_LLM_BASE_URL` to the deployed endpoint).
2. Export `LYSOS_AUTOTITLE_BACKEND=lysos` (or set it in `.env`).
3. Restart uvicorn. From that moment, auto-title prompts route through
   `LysosEndpoint` instead of Gemini Flash, with the same prompt and
   the same budget gates intact.
4. No frontend code changes; no other backend route changes.

That's the entire migration. The Gemini call site is one branch in
chat.py guarded by `_AUTOTITLE_BACKEND == "gemini"`; flipping the env
var bypasses it cleanly.

## 9. Out of scope (for now)

- Auth/multi-tenant — single-user demo for the hackathon
- Async job queues — every workflow runs on the WS connection
- Vector store / RAG — the existing pharma_qa flat parquet is enough
- External molecule databases — we ship with the curated 218-drug
  enrichment set

## 10. Status

Last updated: continuous (we modify this doc as we ship).
Next workflow: **W2 score** — being built right now.
