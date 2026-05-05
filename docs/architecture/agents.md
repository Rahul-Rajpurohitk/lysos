# Lysos Agents

Lysos uses 4 first-class agents and a set of scoped sub-agents. Each has a
defined role, allowed tools, and output format.

## Designer

**Role**: Generate antimicrobial drug-candidate proposals against a target
pathogen + structural target. Designer is the primary action agent — it
proposes structures, calls in silico tools to evaluate them, reads results,
iterates.

**Inputs**:
- pathogen (one of: MRSA / Mtb / EColi-CRE / KpneuCRE / Abaum / Paer / VRE / NGono)
- constraint profile (lead-like / fragment-extension / macrocycle / AMP-derived / siderophore-conjugate / GMP-friendly)
- resistome briefing (auto-fetched via `get_pathogen_resistome`)
- structural target context (auto-fetched via `find_target_structure`)
- optional anchor scaffold from user/Strategist

**Outputs (per iteration)**:
- 2-5 candidate SMILES with structural rationale
- panel results: predicted MIC + ADMET + hemolysis + composite score
- best-of-batch selection + handoff to Critic

**Tools (most → least frequent)**:
1. `predict_mic_pathogen` — primary activity gate (~200 ms)
2. `predict_admet` — Lipinski/Veber filter (~100 ms)
3. `predict_hemolysis` — safety panel (~200 ms)
4. `score_molecule` — composite scoring (~350 ms)
5. `scaffold_hop` — iteration via bioisostere (~1500 ms)
6. `transform_structure` — single-atom edits (~800 ms)
7. `propose_pocket_aware` — initial proposals from PDB context (~2000 ms)
8. `predict_resistance_escape` — red-team prior to handoff (~300 ms)
9. `estimate_synth_cost` / `predict_synthesis_route` — final feasibility (~250-800 ms)

**Cannot do**:
- Stage-gate decisions (advance / kill the campaign) — Strategist's job
- Adversarial review — Critic's job
- SMILES sanitization (canonical form, valence fixes) — Editor's job
- Wet-lab handoff format — Strategist after Critic clearance
- Modify the candidate ledger directly — Designer APPENDS; Strategist edits/kills

**Output convention**: every Designer turn ends with a structured PROPOSAL
block:

```
PROPOSAL: <SMILES>
RATIONALE: <2-3 sentences citing the resistome briefing + structural rationale>
NEXT: <which tool to call next, and why>
```

## Critic

**Role**: Adversarial review of Designer's candidates. Catch issues
Designer's optimization-loop misses. Critic is intentionally pessimistic —
its job is to BLOCK candidates with hidden flaws.

**Inputs**:
- Candidate SMILES + Designer's score panel results
- Candidate ledger context (prior candidates, similar candidates)
- User constraint profile + interventions

**Review dimensions** (every candidate gets a verdict on each):
1. CHEMISTRY VALIDITY — RDKit parse + sanitize
2. DRUG-LIKENESS — Lipinski + Veber + Egan
3. PAINS / BAD ACTORS — PAINS + Brenk + NIH + Lilly-MedChem rules
4. NOVELTY — Tanimoto vs known-antibiotic index (cliff at 0.4)
5. ESCAPE MUTATIONS — `predict_resistance_escape` verdict
6. MANUFACTURABILITY — SA score + chiral count + step count + cost/g
7. CLINICAL VIABILITY — bioavailability + tissue penetration + indication fit
8. CROSS-RESISTANCE — vs first-line therapy class

**Output format** (per candidate):

```
VERDICT: PASS | WARN | FAIL
PER-DIM:
  chemistry_validity: PASS|WARN|FAIL — <reason>
  drug_likeness:      PASS|WARN|FAIL — <reason>
  PAINS_actors:       PASS|WARN|FAIL — <reason>
  novelty:            PASS|WARN|FAIL — <Tanimoto>
  escape_mutations:   PASS|WARN|FAIL — <verdict + top concern>
  manufacturability:  PASS|WARN|FAIL — <SA + cost>
  clinical_viability: PASS|WARN|FAIL — <route + dosing>
  cross_resistance:   PASS|WARN|FAIL — <vs first-line>
OVERALL: PASS / CONDITIONAL / BLOCKED
REVISIONS:
  - <specific actionable fix for each FAIL dimension>
```

**Verdict thresholds**:
- All 8 PASS → OVERALL: PASS → handoff to Strategist for advancement
- ≤2 WARN, 0 FAIL → OVERALL: CONDITIONAL → Designer iterates, addresses WARNs
- ≥1 FAIL → OVERALL: BLOCKED → Designer must redesign or kill

## Strategist

**Role**: High-level campaign decisions. Allocates compute and budget across
pathogens, decides when to TERMINATE / CONTINUE / PIVOT a campaign, formats
wet-lab handoffs, escalates to user when needed.

**Inputs**:
- Workbench candidate ledger (full state of all candidates)
- Compute / budget envelope
- User priorities + WHO tier
- Critic verdicts
- Tool latency + cost estimates

**Decision types**:
1. CAMPAIGN ALLOCATION — at session start, divide compute across pathogens
2. STAGE GATE — advance from generation → optimization → wet-lab
3. PIVOT — switch scaffold class when current plateau'd
4. KILL — terminate a candidate or whole campaign
5. WET-LAB HANDOFF — format top candidates for medchem team
6. USER ESCALATION — request human intervention

**Invocation triggers**:
- Designer: 5 iterations completed without composite > 0.7 → PIVOT
- Designer: ≥3 candidates with composite > 0.85 → STAGE_GATE wet-lab
- Critic: ≥2 BLOCKED candidates in a row → CAMPAIGN_KILL
- Auto: 40% of budget consumed without composite > 0.7 → STRATEGIST_REVIEW
- Auto: tool latency > expected_duration_ms × 3 → SYSTEM_HEALTH_CHECK

**Output format**:

```
DECISION: TERMINATE | CONTINUE | PIVOT | KILL | HANDOFF | ESCALATE
RATIONALE: <2-3 sentences citing ledger evidence>
ALLOCATION_DELTA: <compute redistribution if applicable>
NEXT_AGENT: <designer | critic | editor | user>
TIMEOUT: <max wall-clock for next phase>
```

## Editor

**Role**: Structural sanitization. Lowest-level agent — cleans SMILES
strings, applies named transforms, fixes valence, canonicalizes.

**Inputs**:
- Source SMILES (possibly malformed)
- Optional named transform op (add_methyl, remove_OH, ring_expand, etc.)
- Optional constraint set (preserve specific stereo, retain pharmacophore)

**Invocation triggers**:
- `predict_admet` returned 'invalid SMILES' → Editor canonicalize
- Designer emitted SMILES that fails RDKit parse → Editor fixes valence
- Designer requested a structural transform → Editor applies
- User drag-and-drop edit on the 3D viewer → Editor reflects in SMILES

**Output format**:

```
EDIT_OP: <op_name>
SOURCE_SMILES: <input>
PRODUCT_SMILES: <output, canonical>
SUCCESS: true | false
NOTES: <if false, why; if true, what changed>
```

**Cannot do**: generate new candidates (Designer's job), score candidates
(Designer's job), make strategic decisions (Strategist's job).

## Scoped sub-agents

Lysos spawns scoped sub-agents for specific tasks that need fresh context.
Standard sub-agents:

- **Editor** — SMILES sanitization + named transforms
- **Critic-Novelty** — Tanimoto vs known corpus (just the novelty pillar)
- **Critic-Escape** — adversarial mutation + escape prediction
- **Resistance-Forecaster** — predict where resistance emerges in 24-36 mo
- **Manufacturing-Eval** — stereo + scale + cost trade-offs
- **Clinical-Positioning** — indication + dose + route reasoning
- **Literature-Grounding** — search_literature + cite recent papers
- **Confidence-Calibrator** — when to trust predictors, when to verify

See [subagent-dispatch.md](subagent-dispatch.md) for the dispatcher protocol.
