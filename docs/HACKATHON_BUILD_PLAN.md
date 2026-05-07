# 🧬 LYSOS HACKATHON — MASTER BUILD PLAN

> **Drafted**: 2026-05-07 (T-2 days to submission)
> **Status**: locked, executing autonomously
> **Owner**: Rahul + Claude pair-build
> **One-line**: Turn the scaffolded agentic SaaS into a functioning antimicrobial drug-discovery workspace where 5 containers cooperate, agents drive a real medchem workflow, and one click produces a publishable report.

---

## PART 0: GROUND TRUTH — WHAT WORKS RIGHT NOW

### ✅ Real working business logic

| Surface | Evidence |
|---|---|
| 2D molecule builder + atoms/bonds rails | RDKit-backed, atom-level edit, SMARTS, drag-to-bond, 100% functional |
| Properties dashboard | Real RDKit descriptor stack — MW/LogP/TPSA/QED/Lipinski/Veber all computed |
| Closest-known matching | Tanimoto on Morgan-2 fingerprints vs 30+ curated antibiotics |
| SMARTS pattern detection (41 presets) | Real RDKit substructure matching |
| Library save/load + sessions | SQLite-backed, working |
| Diagnostics (incomplete atoms, valence, fragments) | RDKit sanitization, real |
| Knowledge backend data | 8 pathogens + 30+ antibiotics + drug-class taxonomy + resistome maps loaded |
| Scoring stack components (some) | Validity / QED / SA / novelty / Lipinski / fp32 KL — real. ADMET / hemolysis / MIC — proxy/stub. |
| Live event bus + WS | Real, drives multi-component reactivity |
| Trained model on AMD MI300X | Stages 1, 2, 2.5 all done. Merged 31.3B fp16 model, served via OpenAI-compatible API. |

### ❌ Scaffolded but not functional / broken

| Surface | Issue |
|---|---|
| 3D Mol3DTheaterWindow | Was working pre-decoupling, broke during agentic refactor |
| Agent Reasoning Trace | Shows "latest message" only, not real reasoning chain |
| Docking endpoints | Returns plausible numbers but no real geometry |
| ADMET / hemolysis predictors | Proxy values |
| Synthesis route prediction | Canned steps |
| Resistance-escape prediction | Mock response |
| Boltz-2 pose confidence | Cache empty for novel SMILES |

### ❌ Dropped completely

- Stage 3 GRPO RL (4 failed runs, audit doc preserved as `docs/STAGE3_GRPO_AUDIT.md`)

---

## PART 1: CONTAINER STRATEGY — keep / kill / add

### Decision matrix

| Container | Decision | Reasoning |
|---|---|---|
| **Chemistry** | KEEP + EXPAND massively | Already strongest. Adding 3 antimicrobial-specific services makes it the demo centerpiece. |
| **Knowledge** | KEEP + REBUILD UI | Backend data is real; surfacing is weak. Domain experts NEED reference data. |
| **Scoring** | KEEP + STAMP REALITY | Show honesty per axis (real / proxy / stub) + drill-down. Honest > impressive-looking. |
| **Agents** | KEEP + RESTRUCTURE | Currently broken. Rebuild as workflow-phase tracker + real reasoning chain. |
| **Live** | KILL as a container | Redundant with Agents Action Log. Move system status to top-bar indicator. |
| **Report** | ADD as a new container | The deliverable. Without it, this is "chat that designs molecules" — with it, it's a SaaS. |

### Final 5-container layout

```
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ Chemistry│ Knowledge│ Scoring  │ Agents   │ Report   │
│ (lab)    │ (book)   │ (assay)  │ (team)   │ (output) │
└──────────┴──────────┴──────────┴──────────┴──────────┘
```

System health (WS, agent count, jobs) → thin top status bar, always visible.

---

## PART 2: THE RL SITUATION

### Stages of the model

```
Gemma-4-31B-it base (Google, 31B params, instruction-tuned)
        ↓
Stage 1: TxGemma SFT (therapeutic biomedical domain)         ✅ DONE → rahul24raj/lysos-base
        ↓
Stage 2: AMR SFT (12K antibiotic prompts)                     ✅ DONE → local checkpoint
        ↓
Stage 2.5: DPO with hard-negative pairs (RL-LIKE alignment)  ✅ DONE → rahul24raj/lysos-base-dpo  ← THIS captures the reward signal
        ↓
Stage 3: GRPO RL (full online RL)                             ❌ SHELVED (4 failed runs)
```

### Why drop Stage 3 (final word)

- Reference-model bug fixed (commit `16bafa5`) but bf16 precision + reward sparsity caused recurring KL spikes to 10¹¹
- 22+ hours GPU compute burned, 4 attempts
- Documented in `docs/STAGE3_GRPO_AUDIT.md`
- DPO already encoded the reward preference via hard-negative pairs from the same 12-component reward stack
- Stage 2.5 DPO is the production deployable

### What we use INSTEAD of Stage 3 — Best-of-N + Reward-Guided Selection

This is a cheap inference-time substitute that gives ~80% of RL's benefit without training:

```
Designer.acomplete(prompt, n=5)       ← 5 candidates per turn (was 1)
        ↓
RewardStack.score_all(5)              ← rank by composite reward
        ↓
Critic sees top-3 with breakdown      ← reward-aware critique
        ↓
Editor mutates top-1                  ← reward-gradient-driven mutation
        ↓
Strategist watches reward trajectory:
   - 3 iters Δreward < 0.01 → BRANCH
   - reward ≥ 0.75       → TERMINATE
   - reward declining   → REVERT
```

**Estimated build**: ~2 hrs to wire into existing harness.

---

## PART 3: CHEMISTRY CONTAINER — the deep dive

### Already working (do not touch except for halos)

- 2D molecule builder
- Atoms rail (right-side)
- Bonds rail (right-side)
- Properties strip (medchem props · build state · patterns · closest known)
- Library / save / load
- Build tools (fragments / rings / SMILES)

### Adding 3 antimicrobial-specific services

#### 🥇 SERVICE 1: 3D Target-Ligand Theater

**The problem**: chem container has zero biology today. Designing for MRSA needs to SEE the molecule in PBP2a's active site.

**Pathogen → Target curation** (8 pathogens × 2-3 targets each):

| Pathogen | Targets | PDB IDs |
|---|---|---|
| MRSA | PBP2a, MurA, TopoIV | 1MWT, 1A2N, 4Q08 |
| Mtb | InhA, DprE1, RpoB | 1ENY, 4FDO, 5UH6 |
| KP-CRE | NDM-1, KPC-2 | 3SPU, 3DW0 |
| A. baumannii | PBP3, AdeABC | 3UE3, 6Y3N |
| VRE | D-Ala-D-Ala ligase, VanA | 1IOV, 1E4E |
| P. aeruginosa | DNA gyrase, MexAB-OprM | 5TJX, 6IOK |
| E. coli ESBL | CTX-M-15, PBP3 | 4HBT, 4BJP |
| N. gonorrhoeae | PBP2, gyrA | 5OYE, 1AB4 |

**Backend endpoints**:
```
GET  /workbench/chem/targets/{pathogen}              → curated target list
GET  /workbench/chem/target/{pdb_id}                 → cached PDB structure + active site residues
POST /workbench/chem/place-in-pocket                 → ligand placement + contact analysis
       body: {smiles, pdb_id}
       returns: {pose_score, contacts: [{residue, atom_pair, distance}], clashes, binding_atoms[], clashing_atoms[]}
```

**Algorithm** (real, not stub):
1. Fetch PDB from RCSB (cache locally on first hit)
2. Parse co-crystal ligand to identify active site (residues within 5Å)
3. For new candidate: ETKDG conformer via RDKit → align centroid to active-site centroid
4. Compute contacts (atom pairs within 4Å) + clashes (within 1.5Å of protein)
5. Score: `pose_score = (n_contacts / clash_factor) / max_possible_contacts`

**Frontend**:
- Restore `Mol3DTheaterWindow.tsx`
- Add target picker dropdown at top
- NGL stage shows target + ligand (colored by binding atom)
- Right panel: contacts list + pose score
- Bottom: clash count + key contacts

**Halos back to 2D builder**:
- Atoms in `binding_atoms[]` → green halo + "binds" badge
- Atoms in `clashing_atoms[]` → red halo + "clash" badge

**Agent tool**:
```python
@tool(category="structural")
def place_in_pocket(smiles: str, pdb_id: str) -> dict:
    """Place a candidate molecule in the active site of a target protein.
    Returns pose score (0-1), contact residues, clash count, and which atoms bind / clash.
    Critic uses this to identify which atoms are doing the binding work."""
```

#### 🥈 SERVICE 2: Resistance-Escape Vulnerability Map

**The problem**: every antimicrobial fails to single-residue mutations. Vancomycin → vanA mutation. Penicillin → β-lactamase. Without predicting escape vectors, agents are designing generic drugs, not antibiotics.

**Backend endpoints**:
```
GET  /workbench/chem/resistance/known/{pdb_id}       → curated CARD subset for this target
POST /workbench/chem/resistance/predict              → mutation × position escape map
       body: {smiles, pdb_id}
       returns: {
         escape_per_residue: {pos: {wt, scores: {mutation_aa: score}}},
         vulnerable_atoms: [{atom_idx, escape_score, top_mutation}],
         n_escape_vectors: int,
         robustness_score: float (0-1, higher = more robust),
         clinical_overlap: [{position, mutation, drug_resistance_class}]
       }
```

**Curated CARD subset** (~400 mutations across 8 pathogens):
- Stored at `data/curated/card_resistance_subset.json`
- Per-mutation: position, wt → mutant aa, drug class affected, frequency, citation

**Algorithm**:
1. From Service 1: get contact residues for this candidate
2. For each contact residue + each amino-acid mutation type:
   - Score = (binding contribution loss after mutation) × (clinical mutation frequency from CARD)
3. Map back to atoms: vulnerable atoms = those touching residues with high mutation scores
4. Robustness = 1 - max(escape_scores)

**Frontend**:
- Heatmap: residue position (X) × mutation type (Y), colored by escape score
- Cells with known clinical mutations get red border
- Click cell → highlight residue in 3D theater
- Side panel: top-5 escape vectors with clinical context

**Halos back to 2D**:
- Vulnerable atoms → orange halo + escape probability badge
- Annotation: "atom 1: 0.85 escape via M385V"

**Agent tool**:
```python
@tool(category="amr")
def predict_resistance_escape(smiles: str, pdb_id: str) -> dict:
    """Predict which point mutations in the target would defeat this candidate.
    Returns vulnerable atoms with escape scores + cross-reference to clinical resistance.
    Strategist uses this for BRANCH decision when escape vectors > 5."""
```

#### 🥉 SERVICE 3: Multi-Candidate Pareto Lab

**The problem**: agents may explore 20 candidates per session. Without a Pareto view, can't tell exploring from wandering.

**Backend endpoints**:
```
GET  /workbench/session/{sid}/candidates             → all candidates in session
GET  /workbench/session/{sid}/pareto                 → Pareto frontier on selected axes
       query: x=metric_a&y=metric_b
       returns: {
         all_points: [{candidate_id, smiles, x_value, y_value, on_pareto: bool}],
         pareto_set: [candidate_id...],
         dominant_candidates: [{id, dominates_count}]
       }
```

**Frontend**:
- Scatter plot card (recharts)
- Default axes: composite_reward (Y) vs predicted_mic (X)
- Axis swap dropdown: any pair from {composite, mic, qed, novelty, sa_score, hemolysis, lipinski_pass, robustness_score, pose_score}
- Pareto-optimal points: green + larger
- Click dot → 2D structure preview + jump to builder
- Compare-mode: select 2-4 → side-by-side diff highlighting changed atoms

**Halos back to 2D**:
- Rank badge on 2D card header: "Pareto rank 3/12 — dominated by candidate_5 on QED"

**Agent tool**:
```python
@tool(category="scoring")
def pareto_summary(session_id: str, x_axis: str = "composite_reward", y_axis: str = "predicted_mic") -> dict:
    """Returns Pareto frontier of candidates explored this session.
    Strategist uses this to detect 'no-improvement' plateaus → BRANCH."""
```

### Bidirectional 2D ↔ Service flow (the agentic loop)

```
2D builder edit → SMILES change → all 3 services auto-fire → halos update on 2D
                                          ↓
                                  agent reads service outputs
                                          ↓
                                  agent calls edit_molecule()
                                          ↓
                                  2D builder updates → loop
```

The **bidirectional halos** mean the agent reads the chem container as ONE workspace where binding (green) + escape (orange) + clashes (red) all converge on the same molecule.

---

## PART 4: KNOWLEDGE CONTAINER — UI rebuild on existing data

### Backend data already real (do not rebuild)

- 8 pathogens with full resistome maps
- 30+ curated antibiotics (penicillins, cephalosporins, fluoroquinolones, glycopeptides, oxazolidinones, etc.)
- Drug-class taxonomy
- Per-pathogen target lists (Service 1 reuses this)

### Cards to build (frontend rebuild on existing endpoints)

**1. Pathogen Profile Card** (replaces flat profile text)
- Header: name + WHO priority + annual mortality
- Resistome panel: known resistance genes with which scaffolds they defeat
- Validated targets: clickable list (loads target into 3D theater)
- Clinical context paragraph
- Recent literature snippets (pre-cached PubMed)

**2. Antibiotic Reference Card** (replaces flat list)
- Per-drug card: 2D structure thumbnail + MoA + drug class + year approved + resistance mechanism
- Search/filter by: pathogen-active, drug class, era
- Click reference drug → load into 2D builder for SAR comparison

**3. Drug-Class Taxonomy Tree**
- Tree view: β-lactams ⊃ penicillins ⊃ amoxicillin
- Per-class: characteristic SMARTS, typical MIC range, common resistance, synthesis profile

### Endpoints (already exist, just consume)

```
GET /workbench/pathogens
GET /workbench/pathogen/{code}/pocket
GET /workbench/molecule/reference-set
GET /workbench/molecule/drug-class-colors
```

### Agent tools (already implemented, surface in UI)

- `get_pathogen_resistome(pathogen)`
- `find_active_against_mdr(pathogens)`
- `get_drug_history(drug_name)`
- `compare_molecules(smiles_a, smiles_b)`
- `find_target_structure(pathogen, mechanism)`

---

## PART 5: SCORING CONTAINER — honesty + drill-down

### Per-axis honesty stamps

| Axis | Source | Status badge | Drill-down content |
|---|---|---|---|
| validity | RDKit parse | 🟢 REAL | "RDKit parses canonical SMILES" |
| predicted_mic | XGBoost (small training) | 🟡 PROXY | "MAE=0.6 log units, indicative only" |
| drug_likeness_qed | RDKit QED | 🟢 REAL | "Bickerton 2012, ≥0.67 = drug-like" |
| synthesizability | RDKit SA score | 🟢 REAL | "Ertl 2009, 1=easy / 10=hard" |
| novelty | Tanimoto distance | 🟢 REAL | "Morgan-2 vs 30+ known antibiotics" |
| embedding_novelty | Gemini embedding | 🟢 REAL | "3072-d cosine distance" |
| hemolysis_safety | Proxy model | 🟡 PROXY | "structural-alert based, unvalidated" |
| structural_alerts | RDKit FILTER | 🟢 REAL | "PAINS + PMI + tox alerts" |
| boltz2_pose_conf | Boltz-2 cache | 🔴 STUB if miss | "predicted complex confidence" |
| binding_affinity | Service 1 derived | 🟢 REAL after Day 1 | "from theater pose_score" |
| logp | RDKit Crippen | 🟢 REAL | "MlogP from Crippen 1999" |
| lipinski_violations | RDKit | 🟢 REAL | "MW/logP/HBD/HBA rule-based" |

### New axis we add (Service 2 enables this)

**robustness_score** (🟢 REAL after Day 1) — from Service 2's resistance-escape map. THIS is the antimicrobial-specific metric that distinguishes Lysos from generic drug design.

### Drill-down per axis

Click any axis on the radar → modal showing:
- Threshold visualization
- Per-atom contributions (where applicable)
- Citation / model card
- Honest limits

---

## PART 6: AGENTS CONTAINER — workflow workspace

### New layout

**1. WORKFLOW PHASE TRACKER** (NEW, top of container)
```
SCOPE → ANCHOR → DESIGN → VALIDATE → STRESS-TEST → REPORT
  ✓        ✓       ⏳         ○            ○            ○
```
- Per-phase: ✓ done / ⏳ active / ○ pending
- Click phase → drill into tools called + evidence gathered
- Strategist controls phase transitions

**2. AGENT REASONING CHAIN** (REBUILD)
- Per agent: chronological view of `think → tool-call → result → think`
- NOT just latest message — the full reasoning sequence
- Tool calls expandable: input → output → duration
- Auto-scrolls in real-time

**3. AGENT ROSTER + METRICS** (KEEP, polish)
- One row per agent: state + n_actions + last_op + avg_confidence
- Color-coded heartbeat
- Click row → drill into action log

**4. ACTION LOG** (KEEP, polish)
- DB-backed already
- Better filters, linkable from snapshots

### Phase definitions

| Phase | What happens | Tools used | Exit condition |
|---|---|---|---|
| SCOPE | User defines pathogen + constraints + criteria | (none — just config) | User submits goal |
| ANCHOR | Designer queries resistome, picks scaffold class | `get_pathogen_resistome`, `find_similar_drugs`, `find_active_against_mdr` | Designer outputs starting SMILES |
| DESIGN | Designer/Critic/Editor loop with reward feedback | `replace_smiles`, `edit_molecule`, `score_molecule`, `place_in_pocket`, `predict_resistance_escape` | Plateau or reward ≥ 0.75 |
| VALIDATE | Top candidates run through full validation | `place_in_pocket`, `predict_resistance_escape`, `predict_admet`, `compare_molecules` | All top-3 candidates validated |
| STRESS-TEST | Adversarial Critic + red-team escape | `predict_resistance_escape`, `predict_resistance_escape` | All candidates stress-tested |
| REPORT | Snapshot all containers + assemble PDF | `report.snapshot_all`, `report.render` | PDF generated |

---

## PART 7: REPORT CONTAINER — the deliverable (NEW)

### Top half: Snapshot Builder
- "Capture all containers" button
- Snapshots: Chemistry (top candidate 2D + 3D + escape + Pareto position) + Knowledge (target context) + Scoring (radar) + Agents (workflow phase + key decisions)
- Preview each snapshot
- User can drag to reorder, toggle inclusion

### Bottom half: Report Preview
Renders combined snapshots as structured medchem report:
- **Cover**: target pathogen + constraints + final composite score
- **Summary**: top 3 candidates side-by-side
- **Per-candidate**: structure + theater pose + escape analysis + score breakdown
- **Workflow audit**: tools called per phase
- **Agent rationale**: key decisions + dissents
- **Next experiments**: what wet-lab should test
- Live preview updates as user adjusts snapshots

### Export buttons
- PDF (HTML → Puppeteer/Playwright → PDF)
- Markdown (for AI handoff or paper draft)
- JSON-trace (full session for replay)

### Backend
```
POST /workbench/report/snapshot/{sid}                 capture all container states
GET  /workbench/report/{sid}/preview?format=html      render combined report
GET  /workbench/report/{sid}/export?format=pdf|md|json
```

---

## PART 8: BUILD ORDER — concrete schedule

### Day 1 (today, ~8 productive hours)

| Phase | Tasks | Output |
|---|---|---|
| **A** (1-2h) | Service 1 backend: targets endpoint + PDB cache + place-in-pocket algorithm | `/chem/targets`, `/chem/target/{pdb}`, `/chem/place-in-pocket` working |
| **B** (3-4h) | Service 1 frontend: revive Mol3DTheater + target picker + atom halos to 2D | 3D theater shows ligand in pocket; 2D shows binding/clash halos |
| **C** (5h) | Service 2 backend: curated CARD subset + escape predictor heuristic | `/chem/resistance/predict` working |
| **D** (6h) | Service 2 frontend: heatmap card + atom halos to 2D | Escape map visible; vulnerable atoms highlighted on 2D |
| **E** (7h) | Service 3 backend + frontend: Pareto rollup + scatter plot | Pareto Lab shows all candidates with frontier highlighted |
| **F** (8h) | Best-of-N + Reward-Guided Selection wiring | Designer generates n=5, Critic reads ranked, Strategist watches gradient |

### Day 2 (~8 productive hours)

| Phase | Tasks | Output |
|---|---|---|
| **G** (1-2h) | Knowledge container UI rebuild | Pathogen profile + antibiotic browser + drug-class tree all functional |
| **H** (3h) | Scoring honesty pass | Status badges per axis + drill-down modals |
| **I** (4-5h) | Agents container restructure | Workflow Phase Tracker + Real Reasoning Chain |
| **J** (6-7h) | Report container | Snapshot + Preview + PDF export |
| **K** (8h) | Pitch deck + demo video script | Submission-ready |

**Buffer**: 0 hours. Cut features, not corners.

---

## PART 9: HACKATHON ALIGNMENT — the pitch story

After all this, the narrative is:

> Lysos is an antimicrobial drug-discovery SaaS running on AMD MI300X.
>
> A medicinal chemist defines target pathogen + design constraints. The agentic system traverses a real medchem workflow — anchor → design → validate → stress-test — calling 35+ tools across 7 services on AMD hardware. The user watches in real-time as candidates evolve in the 2D builder, dock against pathogen targets in 3D, get analyzed for resistance-escape vulnerabilities, and converge to a Pareto-optimal frontier.
>
> When done, one click captures every dashboard into a publishable medchem report.
>
> Trained on AMD MI300X across 4 stages of fine-tuning. Served on AMD MI300X. The reward signal that aligned the model is the same reward signal that guides the agents at inference time.

---

## PART 10: NEW ENDPOINTS REFERENCE

### Service 1 (Theater)
```
GET  /workbench/chem/targets/{pathogen}
GET  /workbench/chem/target/{pdb_id}
POST /workbench/chem/place-in-pocket
```

### Service 2 (Escape Map)
```
GET  /workbench/chem/resistance/known/{pdb_id}
POST /workbench/chem/resistance/predict
```

### Service 3 (Pareto Lab)
```
GET  /workbench/session/{sid}/candidates
GET  /workbench/session/{sid}/pareto
```

### Report
```
POST /workbench/report/snapshot/{sid}
GET  /workbench/report/{sid}/preview
GET  /workbench/report/{sid}/export
```

---

## PART 11: NEW AGENT TOOLS (registry additions)

```python
# Existing categories stay; adding to structural + amr + scoring

@tool(category="structural")
def list_targets(pathogen: str) -> list[dict]: ...

@tool(category="structural")
def place_in_pocket(smiles: str, pdb_id: str) -> dict: ...

@tool(category="amr")
def predict_resistance_escape(smiles: str, pdb_id: str) -> dict: ...

@tool(category="scoring")
def pareto_summary(session_id: str, x_axis: str, y_axis: str) -> dict: ...

@tool(category="report")
def snapshot_all(session_id: str) -> dict: ...

@tool(category="report")
def render_report(session_id: str, format: str = "html") -> str: ...
```

---

## PART 12: CONTEXT ANCHORS (so we don't lose ground)

### Already done in this session (do not redo)
- Stage 3 GRPO killed + audit doc preserved
- Stage 2.5 DPO merged + deployed on MI300X (`/shared-docker/lysos/models/lysos-dpo-merged/`)
- serve.py inference server in rocm container, port 8000
- SSH tunnel script (`scripts/lysos.sh up/down/status/restart/logs/test/vmoff/vmon`)
- Workbench wired to MI300X via OpenAI-compatible endpoint
- Chem 2D builder fixed: bond hover, atom-number highlight, hit circles, layout
- Properties strip moved below diagram, responsive 4/2/1-column layout
- Build panel duplicate header removed
- 2D builder is fully interactive end-to-end

### Files to remember
- `workspace/web/src/workbench/v3/playground/Mol2DBuilderWindow.tsx` — the 2D builder (5K+ lines, do not break)
- `workspace/web/src/workbench/v3/playground/Mol3DTheaterWindow.tsx` — needs revival for Service 1
- `workspace/api/workbench.py` — backend routes
- `workspace/agents/harness/orchestrator.py` — agent harness (where workflow phases will live)
- `workspace/agents/llm.py` — LLM endpoint (LysosEndpoint default = lysos-base-dpo via MI300X)
- `src/eval/rewards/` — 12-component reward stack
- `data/curated/known-antibiotics.json` — 30+ antibiotic library
- `data/curated/card_resistance_subset.json` — TO CREATE for Service 2

### Daily ritual
```bash
./scripts/lysos.sh up                                                                    # bring model online
.venv-cli/bin/python3 -m uvicorn workspace.api.server:app --port 7860 --reload &        # backend
cd workspace/web && npm run dev                                                          # frontend on 5173
```

### Cost-saving ritual (when not using model)
```bash
./scripts/lysos.sh down                                                                 # frees GPU compute
```

---

## STATUS BOARD

- [x] Service 1 backend (targets + PDB cache + place-in-pocket) — `457821b`
- [x] Service 1 frontend (revive Mol3D + target picker + halos) — `d1441a8`
- [x] Service 2 backend (CARD subset + escape predictor) — `2cd28c8`
- [x] Service 2 frontend (heatmap + halos) — `b0e64e7`
- [x] Service 3 (Pareto Lab backend + scatter plot) — `ee2010e`
- [x] Best-of-N + Reward-Guided Selection — `141be4a`
- [x] Knowledge container — ValidatedTargetsCard added — `5cdf93e`
- [x] Scoring honesty pass — `7cd97c5`
- [x] Agents Workflow Phase Tracker — `1915ad8`
- [x] Agents Reasoning Chain rewrite — `c534209`
- [x] Report container (snapshot + preview + export) + Live → Report — `6b77b9c`
- [x] Pitch deck + demo video script — `docs/HACKATHON_PITCH.md`

---

**Last updated**: 2026-05-07. **All 13 tasks checked off.**

---

## SUMMARY OF DELIVERABLES

### Backend modules added
- `workspace/api/chem_3d.py` — Service 1 (Theater)
- `workspace/api/chem_resistance.py` — Service 2 (Escape Map)
- `workspace/api/chem_pareto.py` — Service 3 (Pareto Lab)
- `workspace/api/report.py` — Report deliverable
- `data/curated/card_resistance_subset.json` — 64 clinical mutations
- `workspace/agents/state.py` — phase tracking extensions
- `workspace/agents/graph.py` — `run_designer_best_of_n`
- `workspace/api/workbench.py` — `/sessions/{sid}/workflow` endpoint

### Frontend cards added
- `Mol3DTheaterWindow.tsx` (rewritten with target picker + pose HUD + contacts panel)
- `ResistanceEscapeMapCard.tsx` (heatmap + clinical-overlap)
- `ParetoLabCard.tsx` (scatter plot + axis pickers)
- `WorkflowPhaseTracker.tsx` (6-phase strip)
- `AgentReasoningTraceWindow.tsx` (rewrote: think → tool → result chain)
- `ReportBuilderCard.tsx` (snapshot + preview + export)
- `ValidatedTargetsCard.tsx` (Knowledge: curated targets list)
- `Mol2DBuilderWindow.tsx` (extended: bindingAtoms, clashingAtoms, vulnerableAtoms halos)

### Tools added (registry now 37 from 35)
- `place_in_pocket(smiles, pdb_id)` — Service 1
- `map_resistance_vulnerability(smiles, pdb_id)` — Service 2

### Container layout (final)
1. **Chemistry** — 2D + 3D Theater + Resistance Escape Map + Pareto Lab + properties + library + atoms/bonds rails (the centerpiece)
2. **Knowledge** — pathogen profile + validated targets + antibiotic reference + drug-class colors
3. **Scoring** — 12-axis breakdown with 🟢/🟡/🔴 honesty stamps + radar
4. **Agents** — Workflow Phase Tracker + Reasoning Chain (real think→tool→result) + roster + metrics + action log
5. **Report** — Snapshot + preview + export (.md / .json / PDF) — replaces Live; audit trail moves into this container

### Key commit chain (chronological)
```
3aaa225 lock in master plan
457821b Service 1 backend
d1441a8 Service 1 frontend (3D theater + halos)
2cd28c8 Service 2 backend (CARD)
b0e64e7 Service 2 frontend (escape heatmap)
ee2010e Service 3 (Pareto)
141be4a Best-of-N reward-guided
1915ad8 Workflow Phase Tracker
6b77b9c Report container
7cd97c5 Scoring honesty stamps
c534209 Reasoning chain rewrite
5cdf93e Knowledge ValidatedTargetsCard
[next]  HACKATHON_PITCH.md
```

### Pitch story (docs/HACKATHON_PITCH.md)
1-line + 10-slide deck + 3-min demo script. Covers: training pipeline, 3 services, bidirectional cockpit, agentic workflow, honest scoring, deliverable, AMD showcase.

---

**Ready for submission.** Run `./scripts/lysos.sh up` to bring the model online, then start the workbench and you have the full demo.
