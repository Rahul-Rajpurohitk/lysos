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

Version: 1.1 (May 2026)

---

## 9. Workbench-as-simulation intent (v1.1)

Every workbench control (atom add/delete, bond create/break, scaffold load,
SMARTS match, library save/load, scoring) is exposed as a tool the agents
can call. The workbench is a live simulation that BOTH the human and the
agentic system drive. Same flow:

```
  user clicks atom → backend RDKit edits → DB persists
                  → WS broadcast → all UI cards re-render
       agent calls   ↑ same path   ↑ indistinguishable
```

Therefore: build data model + API + event bus FIRST, UI on top. No
local-state-only "demo" UIs. Every feature must (1) hit a backend endpoint,
(2) persist via the playground store, (3) broadcast on the bus, (4) be
callable from BOTH the user UI AND the agent tool registry — same endpoint
serves both.

Proof of capability: the system must be able to build any known antibiotic
from scratch atom-by-atom (penicillin, vancomycin, ciprofloxacin, etc.).
Agents then USE this same toolkit to discover NEW antibiotics for the
8 priority pathogens.

Apply chemistry rules in the UI: valid bond orders given current valences,
full periodic table for atom-add (with valence tooltips), ring-break
warnings, etc.

See `feedback_workbench_design_pattern.md` in user memory for the full
build pattern (concise sub-containers, top-nav over sidebar, no scroll
on canvases, hover tooltips not text labels).

---

## 10. Chemistry container · agent + user contract (v1.2)

Everything below is a **stable endpoint contract** the Gemma agent can
rely on. Same routes serve the human UI; calling them from the agent
yields visually-identical state changes.

### 10.1 Live state model

Single source of truth: the `playground store` keyed by `chat_id`.
Per-chat state includes `smiles`, `pathogen`, `selected_atoms`,
`edit_log`, `library_view`, `score_view`. UI cards subscribe; agents
write through the same endpoints. WS bus broadcasts every mutation.

### 10.2 Atom-level edit ops · `POST /workbench/molecule/edit`

All ops take `{smiles, op, ...args}` and return `{smiles, n_atoms,
n_bonds}`. RDKit kekulizes before edits and re-sanitizes after; if
sanitize fails on stale aromatic flags, it clears them and retries.

| op | required args | semantics |
|---|---|---|
| `swap_element` | atom_index, new_element | replace element on atom (keeps bonds) |
| `add_atom_at` | atom_index, new_element, bond_order | attach new atom to anchor |
| `delete_atom` | atom_index | remove atom + all incident bonds |
| `add_bond` | atom_index_a, atom_index_b, bond_order | connect two existing atoms |
| `delete_bond` / `break_bond` | bond_index | remove bond between atoms |
| `add_methyl_at` | atom_index | shortcut for `add_atom_at` C single |
| `add_functional_group_at` | atom_index, functional_group | attach FG template (see 10.3) |
| `attach_fragment` | atom_index, fragment_smiles, fragment_anchor_idx, bond_order | attach arbitrary SMILES (rings, custom) |

### 10.3 Functional-group palette

Templates live in `workbench.py::FG_TEMPLATES`. Names accepted by
`add_functional_group_at`:

`hydroxyl, methyl, amine, fluorine, chlorine, bromine, iodine, thiol,
carbonyl, aldehyde, carboxyl, ester, amide, nitro, sulfonyl, sulfonamide,
sulfide, phosphate, phosphonate, cyano, isocyano, azido, trifluoromethyl,
trichloromethyl, ethyl, vinyl, ethynyl, methoxy, ethoxy, isopropyl,
tert-butyl, phenyl`

Branched FGs (atoms 2..n attach to the FG's central heavy atom rather
than chain linearly) are listed in `BRANCHED_FGS`.

### 10.4 Ring/fragment palette · `attach_fragment`

Pass any SMILES as `fragment_smiles`; the backend `CombineMols` it onto
the parent at `atom_index` with `bond_order`. The frontend ships a
22-ring built-in palette (benzene, pyridine, pyrimidine, pyrazine,
imidazole, thiazole, oxazole, furan, thiophene, pyrrole, indole,
benzimidazole, quinoline, cyclopropane … cyclohexane, piperidine,
piperazine, morpholine, tetrahydrofuran, pyrrolidine).

### 10.5 Whole-structure replace · `POST /workbench/molecule/replace`

`{smiles}` → `{smiles (canonical), n_atoms, n_bonds, n_rings}`. Used
when the agent (or user via the SMILES tab) wants to write a full
candidate in one shot. Validates with RDKit; 422 on unparseable.

### 10.6 Atom context · `GET /workbench/chem/atom/{smiles_b64}/{idx}`

Returns rich atom context the rail consumes:
`element, atomic_number, atomic_mass, formal_charge, is_aromatic,
in_ring, ring_size, explicit_valence, implicit_valence, n_hydrogens,
hybridization (sp/sp²/sp³/sp³d/sp³d²), degree, total_degree,
free_valence, is_chiral, is_isotope, cip_code (R/S), neighbors[],
allowed_attachments[], sar_notes[]`.

### 10.7 Element palette · `GET /workbench/chem/elements`

Returns the 37-element drug-relevant subset with `{sym, Z, valences,
name, group}` per entry. Frontend uses this to render the periodic-
table popover; agent uses it to know the supported atom types.

### 10.8 Known-antibiotic library · seeded reference set

Curated 30+ antibiotic reference set in `workbench.py::ANTIBIOTIC_REFERENCE`
covering β-lactams (penicillins, cephalosporins, carbapenems,
monobactams), fluoroquinolones, aminoglycosides, tetracyclines,
macrolides, glycopeptides, lipopeptides, oxazolidinones, polymyxins,
nitroimidazoles, antimycobacterials, sulfa/diaminopyrimidine,
lincosamides, and recent siderophore-cephalosporin/fluorocycline.

- `GET /workbench/molecule/reference-set` — full curated list
- `GET /workbench/molecule/match-known?smiles=...&top_k=K` — Tanimoto
  on Morgan-2 fingerprints; returns `{matches[], best, is_known}`.
  `is_known` is true when best similarity ≥ 0.95.

The 3D viewer polls match-known on every SMILES change (debounced
250 ms) and shows a tag-detection overlay tier:
  - `EXACT` ≥0.95 (green) — you've built this drug
  - `CLOSE` ≥0.65 (cyan)  — analog of a known drug
  - `WEAK`  ≥0.30 (amber) — distant relative
  - `NOVEL` <0.30 (purple) — possibly novel scaffold

### 10.9 SMARTS substructure search · `POST /workbench/chem/smarts-match`

`{smiles, pattern}` → `{hits: int[], matched_atoms: int[][]}`. The
top-nav SMARTS popover ships 41 presets (β-lactam, fluoroquinolone,
aminoglycoside, tetracycline, oxazolidinone, all common FGs, common
heterocycles, drug-likeness motifs).

### 10.10 Library save/load · `POST/GET/DELETE /workbench/library/molecules`

Persistent SQLite-backed library scoped per-user. Each entry: smiles,
canonical_smiles, name, tags, qed, mw, lipinski_pass.

### 10.11 Properties + scoring · `GET /workbench/molecule/properties`

Lipinski, QED, MW, logP, rotatable bonds, HBA/HBD, TPSA, plus the
12-component reward stack (validity, structural_alerts,
predicted_mic, drug_likeness_qed, synthesizability, hemolysis_safety,
novelty, embedding_novelty, boltz2_pose_conf, spectrum_breadth,
resistance_robustness, pareto_entry).

### 10.12 Agent-tool mapping (slash → endpoint)

| Slash | Endpoint | Purpose |
|---|---|---|
| `/build <smiles>` | `POST /molecule/replace` | one-shot structure |
| `/atom + <element> at <idx>` | `POST /molecule/edit add_atom_at` | atomic add |
| `/atom × at <idx>` | `POST /molecule/edit delete_atom` | atomic delete |
| `/swap <idx> -> <element>` | `POST /molecule/edit swap_element` | element substitution |
| `/bond <a> - <b>` | `POST /molecule/edit add_bond` | bond create |
| `/fg <name> at <idx>` | `POST /molecule/edit add_functional_group_at` | FG attach |
| `/ring <smiles> at <idx>` | `POST /molecule/edit attach_fragment` | ring/fragment attach |
| `/match` | `GET /molecule/match-known` | known-drug detection |
| `/smarts <pattern>` | `POST /chem/smarts-match` | substructure highlight |
| `/score` | `GET /molecule/properties` | full reward stack |

### 10.13 Build dynamics

The user (or agent) can build a molecule three ways, **all producing
the same state**:

1. **Atom-by-atom** — click + atom (palette) → click atoms → swap/bond.
2. **Fragment-by-fragment** — select an atom → Build Tools panel →
   Fragments tab (FG chip) or Rings tab (ring chip) → backend attaches.
3. **Whole-structure** — Build Tools → SMILES tab → paste → apply.

Every mutation appends to `edit_log`, broadcasts on the WS bus, and
re-renders the 2D viewer + atoms rail + 3D match overlay + properties +
score panels — even when the originating actor was an agent.

Version: 1.2 (May 7 2026)

---

## 11. Chemistry-rule gating + structured violations (v1.3)

**Rule of the workbench**: never offer an action the user (or agent)
cannot legally perform. Pre-filter palettes from `/chem/valid-actions`;
on attempt-failure, return a structured `ChemViolation` (not a string)
with code, message, hint, and suggested fix.

### 11.1 Structured violation shape

Returned in 422 `detail` body and embedded in `/chem/diagnostics` +
`/chem/valid-actions blocked_reasons`:

```json
{
  "code": "valence_violation",          // machine-parseable
  "message": "Explicit valence for atom 0 C, 5, is greater than permitted",
  "hint": "Atom would exceed its allowed valence. Pick a different element, lower the bond order, or break a neighbor bond first.",
  "atom_idx": null,
  "bond_idx": null,
  "suggested_fix": "lower bond order or remove a neighbor"
}
```

**Stable codes** (frontend renders them with consistent severity colors):
- `valence_violation`, `aromaticity_violation`, `non_ring_aromatic_atom`,
  `chemistry_violation` → red (block)
- `swap_element_undervalent`, `unparseable_smiles`,
  `atom_index_out_of_range`, `bond_index_out_of_range`,
  `unsupported_element` → red (block)
- `bond_already_exists`, `fg_no_free_valence`, `ring_no_free_valence`,
  `atom_under_valent`, `aromatic_ring_break` → amber (warn)
- `missing_args` → blue (info)

### 11.2 Pre-filter palette · `GET /chem/valid-actions/{smiles_b64}/{atom_idx}`

Returns the per-anchor whitelist used by the BuildTools panel. The
frontend hides invalid options entirely instead of greying them — user
never sees "click then error". Response shape:

```json
{
  "atom_idx": 3,
  "element": "C",
  "free_valence": 1,
  "explicit_valence": 3,
  "valid_elements_for_swap": ["B", "N", "Si", "P", ...],
  "valid_functional_groups": ["hydroxyl", "methyl", ...],
  "valid_rings": true,
  "valid_bond_orders_to_neighbors": {"4": ["single", "double"], ...},
  "blocked_reasons": [ChemViolation, ...]
}
```

Agent usage: call this before suggesting an edit. If the proposed
operation isn't in the whitelist, propose an alternative or break a
neighbor bond first.

### 11.3 Whole-molecule diagnostics · `GET /chem/diagnostics/{smiles_b64}`

Polled by the 2D viewer on every SMILES change (debounced 200 ms).
Returns:

```json
{
  "is_valid": false,
  "n_atoms": 12, "n_bonds": 11,
  "n_fragments": 2,
  "total_formal_charge": 0,
  "incomplete_atoms": [{code: "atom_under_valent", atom_idx: 5, ...}],
  "charge_warnings": [...],
  "fragment_warnings": [...],
  "all_violations": [...]
}
```

The 2D viewer uses `incomplete_atoms` to draw a red pulsing dashed ring
around any atom that's under-valent (e.g. carbon with 3 bonds after a
break). Agent usage: after every edit, fetch diagnostics and address
violations before reporting success.

### 11.4 Bond list · `GET /chem/bonds/{smiles_b64}`

Returns every bond with `{bond_idx, atom_a, atom_b, order, in_ring,
is_aromatic}`. Used by the 2D viewer to translate a click on a bond
glyph (RDKit's SVG class `bond-N`) into the correct `bond_index` for
`break_bond`.

### 11.5 Bond-break gesture (user + agent)

User: click any bond in the 2D viewer → `/molecule/edit op:break_bond`.
Aromatic ring bonds are blocked client-side with hint "delete an atom
from the ring instead" — never destroys aromaticity by accident.

Agent: same `op:break_bond` with `bond_index`. Recommended: poll
`/chem/diagnostics` after every break and reconnect any incomplete
atoms.

### 11.6 ViolationToast · frontend rendering contract

Every backend 422 with structured detail is rendered as a toast with:
- severity icon (⚠ block / ⓘ warn / ⓘ info) — color from tier table
- main message (the original error text)
- hint (human-readable explanation)
- "try: <suggested_fix>" (if provided)
- atom/bond context tag (if `atom_idx` or `bond_idx` present)
- code (greyed, monospace, for debugging)

Auto-dismisses after 4s. Manual ✕ to close.

### 11.7 Subheaders → hover tooltips

UI rule: short labels (ATOMS · BUILD · 4 atoms · 6 aromatic · etc) are
self-explanatory. Long descriptions go in the parent's `title` attribute
so they appear on hover instead of taking permanent screen space.

### 11.8 Layout — one-shot visibility

Search bars, submission bars, fragment chips must all be visible without
internal scroll. The chem container default height was bumped 1320 →
1620 to accommodate the BuildTools panel below the atoms rail.

### 11.9 Click-first interaction model (v1.4)

User preference: drag-and-drop is NOT required. Every gesture must have
a click path on BOTH the SVG visual AND the right-side rail. The agent
calls the same endpoints either way, so the user/agent contract stays
identical regardless of which input modality the human uses.

**Click parity matrix:**

| Action | SVG click | Rail click | Endpoint |
|---|---|---|---|
| Select atom | click heteroatom label | click atoms-rail row | (UI state) |
| Multi-select | shift-click atom | shift-click row | (UI state) |
| Add atom (any element) | (atoms-rail '+ atom' → palette) | '+ atom' → palette | edit add_atom_at |
| Swap element | atom popover → swap | row '⇆' → palette | edit swap_element |
| Add neighbor | atom popover → +X | row '+' → palette | edit add_atom_at |
| Delete atom | (in popover) | row '×' | edit delete_atom |
| Add bond | shift-click 2 atoms → toolbar | shift-click rows → toolbar | edit add_bond |
| Break bond | click bond glyph | bonds-rail row '×' | edit break_bond |
| Attach FG | (BuildTools fragments tab) | BuildTools fragments tab | edit add_functional_group_at |
| Attach ring | (BuildTools rings tab) | BuildTools rings tab | edit attach_fragment |
| Replace SMILES | n/a | BuildTools SMILES tab | replace |

Drag-to-bond remains as a secondary gesture (mousedown atom A → mouseup
atom B) but no critical workflow depends on it.

### 11.10 Bonds rail · `BondsRail` component

A new section sits between the atoms list and the BuildTools panel.
Each row visualizes the shared-between-atoms nature of bonds:

```
[idx] ⓒ atom_a — glyph — ⓒ atom_b · [r] · ×
```

- **Click row** → highlight bond on SVG (drives `hoveredBondIdx`)
- **× button** → break bond (`/molecule/edit op:break_bond`)
- **Aromatic ring bonds** are visually disabled (button greyed) — clicking
  them would shatter the ring; the violation toast guides the user to
  delete an atom from the ring instead.
- **Header collapses** if the user wants more space for atoms.

Driven by `GET /chem/bonds/{smiles_b64}`. Same endpoint the agent uses
to enumerate bonds before suggesting a break.

### 11.11 Visual feedback channels

The 2D viewer overlay system has 4 distinct ring/halo channels, each
keyed to a different state source:

| Channel | Color | Trigger | Animation |
|---|---|---|---|
| Selected atom | amber border | `selected: Set<number>` | static |
| Multi-cursor (per-actor) | teal/red/blue | `cursors: Record<actor, ...>` | static |
| SMARTS hit | green | `smartsHits: number[]` | pulse |
| Recently broken | amber dashed | `recentlyBroken` (4s after break) | pulse |
| Incomplete (under-valent) | red dashed | `diagnostics.incomplete_atoms` | pulse |
| Hovered bond | red glow | `hoveredBondIdx` (rail OR SVG) | static |

The atoms-rail rows ALSO color their left border to match: incomplete
atoms get red border + red-tinted bg; recently-broken atoms get amber
border + amber bg. So the same state is visible whether the user is
looking at the structure or the inventory list.

### 11.12 Rail width — 320 px

Bumped from 268 to 320 to accommodate the bonds list rows (which
visualize two atom bubbles + glyph + chips + delete in a single row).
The 2D viewer SVG still has plenty of width budget (chem container is
1500 wide, rail 320, leaving ~1180 for the SVG).

Version: 1.4 (May 8 2026)

---

## 12. Agent tool registry · chem_workbench category (v1.5)

The chem-edit operations the human UI uses are now ALSO registered as
`@tool`-decorated functions in the global registry, exposed at:

- `GET  /workbench/skills` — full tool catalog (35 tools across 7 cats)
- `POST /workbench/tools/{tool_name}` — direct MCP-style dispatch
- `GET  /workbench/skills` returns JSON Schema input/output for every
  tool, compatible with Anthropic / OpenAI / Gemini / Gemma 4
  function-calling.

### 12.1 The 10 chem_workbench tools

| Tool | Purpose | Input | Output |
|---|---|---|---|
| `edit_molecule` | atom/bond level edit (swap, add, delete, attach) | smiles + op + args | new SMILES |
| `replace_smiles` | one-shot whole-structure write | full SMILES | canonical + counts |
| `inspect_atom` | rich chem context for one atom | smiles + atom_idx | hyb, valence, neighbors, CIP |
| `valid_actions` | pre-filter palette by chemistry rules | smiles + atom_idx | valid elements/FGs/rings/orders |
| `diagnostics` | whole-molecule health check | smiles | incomplete atoms + warnings |
| `list_bonds` | enumerate every bond | smiles | bond_idx + endpoints + order |
| `match_known` | Tanimoto match vs antibiotic library | smiles + top_k | matches + similarity + is_known |
| `list_elements` | the 37-element palette | (none) | full periodic-table subset |
| `attach_fragment` | attach SMILES fragment (rings, custom) | smiles + anchor + frag_smiles | new SMILES |
| `attach_functional_group` | attach named FG | smiles + anchor + fg_name | new SMILES |

### 12.2 Workflow patterns

**Building a candidate from scratch (atom-by-atom)**
```python
1. list_elements()                          # know what's available
2. replace_smiles({smiles: "C"})            # start with methane
3. valid_actions({smiles, atom_idx: 0})     # what can I do to atom 0?
4. edit_molecule({op: "add_atom_at", ...})  # add neighbor
5. diagnostics({smiles})                    # verify result is valid
6. match_known({smiles})                    # is this a known drug?
```

**Building a candidate (whole-structure, fast-path)**
```python
1. replace_smiles({smiles: "<full-smiles>"})  # one-shot
2. diagnostics({smiles})                       # verify
3. match_known({smiles})                       # find analog
```

**Mutating an existing candidate**
```python
1. inspect_atom({smiles, atom_idx})            # read state
2. valid_actions({smiles, atom_idx})           # what's allowed?
3. edit_molecule({op: ..., ...})               # mutate
4. list_bonds({smiles}) → for break_bond       # if breaking
5. diagnostics({smiles})                       # verify
```

### 12.3 Actor attribution

Every edit-class tool accepts an `actor` field (defaults to "agent").
The UI reads this to color-code who made the change:

- `user` → amber halo
- `designer` → green halo
- `critic` → red halo
- `editor` → blue halo
- `strategist` → purple halo

Multiple actors can edit concurrently; the SVG renders all halos
side-by-side so the user sees who's doing what in real time.

### 12.4 Structured errors

All tools raise `ValueError` with a structured payload (dict with
`code`, `message`, `hint`, `suggested_fix`, `atom_idx?`, `bond_idx?`)
on chemistry violations. The `Tool.call()` wrapper captures these into
the standard `{tool, args, result, error, duration_ms}` record format
the agent loop expects.

### 12.5 Backend module split

- `workspace/tools/chem_workbench/_chem_lib.py` — shared constants
  (ELEMENTS, FG_TEMPLATES, BRANCHED_FGS, DEFAULT_VALENCE) used by both
  the FastAPI endpoints AND the @tool functions.
- `workspace/tools/chem_workbench/<tool>.py` — one file per tool.
- The existing `/workbench/molecule/edit` REST endpoint and the
  `edit_molecule` tool produce IDENTICAL output for the same input —
  human UI and agent function-call both update the same playground
  store.

Verified e2e:
- `POST /workbench/tools/edit_molecule {smiles: c1ccccc1, op: swap_element,
   atom_index: 0, new_element: N, actor: designer}` → c1ccncc1 (pyridine)
- `POST /workbench/tools/match_known` on penicillin G → similarity 1.0
- `GET /workbench/skills` → 35 tools across 7 categories.

Version: 1.5 (May 9 2026)

