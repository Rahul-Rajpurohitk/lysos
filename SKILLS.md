# Lysos Agent Skills

The skill manifest. Every Lysos agent (and the user via `/`) reads this to
decide what to do next. Generated once, edited as the system grows. The
agents do **not** improvise tools — they call from this catalog.

A "skill" is a typed, atomic capability. The harness binds skills to
specific tools, prompts, or sandbox actions. Composition lives in the
**workflows** section, not in individual skills.

---

## 1. Quick reference

| Slash | What it does | Type |
|---|---|---|
| `/design` | Propose new candidates for a target | prompt |
| `/edit <op>` | Apply a deterministic structural transformation | local |
| `/scaffold-hop` | Bioisosteric scaffold replacement | local |
| `/score` | Run the 12-component reward stack on a SMILES | local |
| `/explain <name>` | Mechanism + spectrum + resistance (218-drug enrichment) | local |
| `/similar <smiles>` | Top-K similar known antibiotics (Gemini Embedding 2 cosine) | local |
| `/dock` | Boltz-2 / AutoDock Vina against a pathogen target | local |
| `/admet` | ADMET property predictions | local |
| `/synth` | Retrosynthesis route + cost estimate | local |
| `/resistance <pathogen>` | Pathogen resistome + escape prediction | local |
| `/run` | Execute a sandbox cell (Python, RDKit, py3Dmol) | system |
| `/branch <hint>` | Fork the current candidate as a new design lineage | system |
| `/critique` | Critic agent reviews the active candidate | prompt |
| `/strategize` | Strategist agent picks the next move | prompt |
| `/clear` | Wipe the active workbench session | system |
| `/help` | Show this manifest | system |

---

## 2. Skill catalog

### 2.1 Generative skills (build & break)

Used to **make new** molecules and **edit** existing ones.

| Skill | Tool | Calls when |
|---|---|---|
| `propose_pocket_aware` | `workspace/tools/generative/propose_pocket_aware.py` | User specifies a pocket / target. Returns a panel of candidates seeded from same pocket-class. |
| `scaffold_hop` | `workspace/tools/generative/scaffold_hop.py` | Improve novelty without losing pharmacophore. Returns isosteric replacements. |
| `transform_structure` | `workspace/tools/generative/transform_structure.py` | Editor agent applies a named SMARTS-defined op (10 named ops: add_hydroxyl / add_fluorine / swap halide / ring_close / etc). |
| `optimize_iteratively` | `workspace/tools/generative/optimize_iteratively.py` | RL-style greedy chain of transforms targeting composite reward. |

**Build/break invariants** (the agent must respect):

- Every product must pass RDKit SanitizeMol. If a transform yields invalid SMILES, **report and stop** — do not silently continue.
- Every new SMILES must be **canonicalized** before scoring (so identical molecules score identically across sessions).
- A "branch" forks the lineage; the prior candidate stays in the workbench history.
- Multi-step transforms accumulate **provenance** (op chain) so the user can replay.

### 2.2 Knowledge skills (lookup & explain)

Read-only tools. Pull from local indexes — no LLM call needed.

| Skill | Tool | Calls when |
|---|---|---|
| `explain_mechanism` | `workspace/tools/knowledge/explain_mechanism.py` | "How does this drug work?" → tries `pharma_lookup` (218 named drugs from Gemini 2.5 Pro) first, falls back to class-level template. |
| `find_similar_drugs` | `workspace/tools/scoring/find_similar_drugs.py` | "What does this candidate look like?" → top-K cosine in 30,743 × 3072-d Gemini Embedding 2 space, falls back to Tanimoto on Morgan FP. |
| `compare_molecules` | `workspace/tools/knowledge/compare_molecules.py` | Side-by-side: SMILES diff, scaffold overlap, scoring delta. |
| `get_drug_history` | `workspace/tools/knowledge/get_drug_history.py` | Resolves a drug name → mechanism + clinical timeline + resistance discovery dates. |
| `find_target_structure` | `workspace/tools/knowledge/find_target_structure.py` | Pathogen → target enzyme → PDB IDs. |
| `search_literature` | `workspace/tools/knowledge/search_literature.py` | RAG against literature index — returns citations. |

**Pharma_lookup priority**: when a drug is named, the 218-drug Gemini Pro
enrichment beats the class-level template. The card includes mechanism,
spectrum, indications, resistance_escape, and a full reasoning trace
(~1663 chars/drug, ~135K tokens total).

### 2.3 Scoring skills (the reward stack)

Reads the 12-component reward stack used in Stage 3 GRPO RL.

| Skill | Tool | Returns |
|---|---|---|
| `score_molecule` | `workspace/tools/scoring/score_molecule.py` | Composite reward + per-component breakdown |
| `predict_admet` | `workspace/tools/scoring/predict_admet.py` | TDC-trained ADMET panel |
| `predict_hemolysis` | `workspace/tools/scoring/predict_hemolysis.py` | xgboost RBC lysis predictor (CV AUROC 0.813) |
| `estimate_synth_cost` | `workspace/tools/scoring/estimate_synth_cost.py` | $/g + step count via SAscore + AiZynth cache |
| `predict_synthesis_route` | `workspace/tools/scoring/predict_synthesis_route.py` | AiZynth retrosynthesis route preview |

**Score interpretation** (composite ∈ [-1, 2]):
- < 0.0 → broken candidate (validity / structural alerts failed)
- 0.0 – 0.5 → drug-like but weak signal
- 0.5 – 1.0 → typical baseline candidate
- 1.0 – 1.5 → strong candidate; promote in Pareto
- > 1.5 → exceptional, prioritize for downstream eval

### 2.4 Structural skills (3D)

Run inside the **molecular sandbox** (see §4). All produce 3D artifacts.

| Skill | Tool | Returns |
|---|---|---|
| `predict_complex_structure` | `workspace/tools/structural/predict_complex_structure.py` | Boltz-2 ligand-receptor pose + ipTM/pTM |
| `dock_against_target` | `workspace/tools/structural/dock_against_target.py` | AutoDock Vina docking score |
| `predict_binding_affinity` | `workspace/tools/structural/predict_binding_affinity.py` | DiffDock or RoseTTAFold-AA refinement |

### 2.5 AMR-specific skills

The unique pieces — what makes Lysos beat a generic drug-design model.

| Skill | Tool | Returns |
|---|---|---|
| `predict_mic_pathogen` | `workspace/tools/amr/predict_mic_pathogen.py` | Pathogen-specific MIC (xgboost on Morgan FP + 8-pathogen one-hot) |
| `find_active_against_mdr` | `workspace/tools/amr/find_active_against_mdr.py` | Filters known-active library by pathogen + MIC threshold |
| `get_pathogen_resistome` | `workspace/tools/amr/get_pathogen_resistome.py` | CARD resistance-gene catalog by pathogen |
| `check_resistance_genes` | `workspace/tools/amr/check_resistance_genes.py` | "Will erm A2058 methylation defeat this candidate?" |
| `predict_resistance_escape` | `workspace/tools/amr/predict_resistance_escape.py` | Probability that ≥2 known mechanisms are escaped |

### 2.6 Sandbox skills (run code, render 3D)

Make 3D + Python execution available to BOTH the agent and the user.

| Skill | Tool | What it does |
|---|---|---|
| `execute_python` | `workspace/tools/sandbox/execute_python.py` | Runs a Python cell with rdkit/pandas/numpy/py3Dmol/matplotlib pre-imported. Streams stdout to the chat. Cell I/O persists across calls within a session. |
| `render_3d_scene` | `workspace/tools/sandbox/render_3d_scene.py` | Builds a 3D scene (protein + ligand pose + binding-site highlighting). Returns an HTML/JSON artifact that the right panel renders via py3Dmol. |

**Sandbox invariants**:

- Every cell run is **reproducible** — same inputs → same outputs (random seeds set).
- Cells share a **session-scoped namespace** so `mol_a = ...` in cell 1 is visible in cell 2.
- The **3D scene** is a first-class artifact: agent and user both edit it. Modifications stream back as scene events (`add_ligand`, `highlight_residue`, `set_camera`).
- Output renders in the **right panel** as an .md-style document with embedded interactive views (not a card grid).

---

## 3. Workflows (the patterns)

### 3.1 Design loop (the default)

```
user: "Design a beta-lactam for MRSA"
  → Strategist: parse target, propose pocket = PBP_active_site
  → Designer: /design → 8 candidates from POCKET_SEEDS
  → Designer: /score each (composite reward)
  → Critic: pick weakest axis on the top candidate
  → Editor: /edit add_hydroxyl OR /scaffold-hop
  → Critic: /score the edit, verify improvement
  → repeat 3-5 cycles
  → present top 3 with rationale
```

### 3.2 Eval loop (post-Stage-3)

```
user: "How does Lysos-RL compare to Gemini Pro on test set?"
  → load reports/gemini_25_pro_baseline.jsonl (already computed)
  → run Lysos-RL on same 99 prompts via /api/inference (vLLM)
  → /critique pairs of (Lysos vs Gemini) responses
  → llm_as_judge_eval.py for 4-axis score
  → render leaderboard in right panel
```

### 3.3 Mechanism deep-dive

```
user: "Why does ceftaroline work on MRSA?"
  → /explain ceftaroline → pharma_lookup card
  → /find_target_structure MRSA → PBP2a PDB ID
  → /predict_complex_structure ceftaroline + PBP2a → Boltz-2 pose
  → /render_3d_scene → right panel artifact
  → narrate from pharma_lookup.thinking trace
```

### 3.4 Branch & A/B

```
user: "Branch this candidate, try sulfonamide cap"
  → fork lineage in workbench
  → /edit add_sulfonamide
  → /score both branches, /score the parent
  → render Pareto plot (parent + 2 branches) in right panel
```

---

## 4. Sandbox architecture

### 4.1 What it is

A first-class, session-scoped Python execution + 3D-rendering environment. **Both** agent and user can:

- Add cells (Python)
- Edit/run/delete cells
- Manipulate the 3D scene (rotate, highlight residue, add ligand pose)
- Save cell + scene snapshots as part of the session

### 4.2 Why a sandbox (not just tool calls)

- Agentic loops produce intermediate state worth keeping (a parsed mol, a score table, a docking pose). Without a sandbox, every tool call is amnesiac.
- The user often wants to **fork** a step — re-run with different params.
- Reproducibility for the methods paper: every figure traces back to a runnable cell.

### 4.3 Implementation

- Backend runtime: **isolated subprocess per session** with rdkit / py3Dmol / pandas / numpy / matplotlib pre-imported. Resource caps: 30s CPU, 4GB RAM, no network by default (toggleable).
- Communication: **JSON-RPC over WS** — `cell_run`, `cell_output`, `scene_update`, `scene_event`.
- Persistence: cells + outputs + 3D-scene state snapshot to `~/.lysos/sessions/<id>.jsonl` on every change.
- Right panel rendering: each session is rendered as **markdown with embedded artifacts** (cells = code blocks, outputs = inline output blocks, 3D scene = inline iframe with py3Dmol). Looks like a Claude artifact, behaves like a Jupyter notebook.

---

## 5. Slash command grammar

Inside the chat composer:

```
/                           # opens the skill picker (filtered by typing)
/design <free text>         # prompt-type: sends to LLM with /design constraints
/edit <op>                  # local: parses op, calls transform_structure
/run <python|smiles>        # system: executes in active sandbox cell
/help                       # system: renders this file
/clear                      # system: wipes session
```

**Extension rule**: every new tool must register a slash form here AND in `workspace/agents/commands.py`. No silent tools.

---

## 6. Identity & tone (for the agent itself)

The Lysos agent is:

- **Domain-expert**, not generalist. Cite specific drugs, mechanisms, resistance genes by name. No hand-waving.
- **Iterative**, not one-shot. Always offer the next move (edit / branch / dock / synth).
- **Honest about uncertainty**. If a reward is `fallback=0.0`, say so. Don't invent confidence.
- **Sandbox-first**. When the user asks "show me", the answer is a runnable cell, not a wall of text.
- **Compositional**. Chain skills explicitly: "I'll `/score`, then `/critique` the weakest axis, then `/edit`."

---

## 7. Operating bounds

- The agent never **deletes** a session or candidate without explicit user confirmation.
- The agent never **uploads** anything (drugs, pdb files, code) to a third party without explicit user consent.
- Reward components that fail must return **`source: "fallback"`** so the UI can surface them as untrusted.
- `pharma_lookup` results are CC-BY-4.0; cite source in the artifact view.

---

## 8. Update log

This file is the source of truth. Update it when:

- A new tool is added (must include slash form + when-to-call line in §2)
- A workflow changes (update §3)
- The sandbox protocol changes (update §4.3)
- The reward stack changes weighting (update §2.3)

Version: 1.0 (initial — May 2026)
