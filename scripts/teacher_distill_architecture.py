"""Architecture / system-awareness teacher distillation.

The model trained on Lysos must KNOW the Workbench architecture end-to-end so
sub-agents can be reliably spawned, dispatched, and coordinated. These traces
document the system as if it were fully built (even though parts are still
being implemented), giving the model a complete mental map.

Categories (each generates parametrized traces):
  A. agent_role_designer        what Designer is + can/can't do
  B. agent_role_critic          what Critic is + review format
  C. agent_role_strategist      high-level decisions, when to invoke
  D. agent_role_editor          structural transforms, sanitization
  E. agent_handoff_protocol     Designer<->Critic<->Strategist handoff
  F. tool_registry_orientation  full tool catalog with categories
  G. tool_decision_tree         which tool for which question
  H. candidate_ledger_format    ledger schema + read/write rules
  I. state_machine              Designer/Critic state transitions
  J. stage_gate_criteria        Stage 1 -> 2 -> 3 advancement
  K. intervention_handler       user interventions mid-flow
  L. error_escalation           error handling chain
  M. branch_merge_strategy      campaign forking + reconciliation
  N. end_to_end_pipeline_map    Sprint planning -> SFT -> RL -> eval -> deploy
  O. subagent_dispatcher        parent agent invokes subagent with scoped task
  P. confidence_convention      uniform uncertainty reporting
  Q. tool_error_codes           per-tool failure modes
  R. system_self_description    'what is Lysos' end-to-end answer
  S. api_contract               tool request/response envelopes
  T. sprint_planning            workflow Lysos uses to plan + execute sprints

Run:
  /tmp/lysos_venv/bin/python scripts/teacher_distill_architecture.py --n_per_category 400

Output:
  data/synthetic/agentic_teacher_distill_architecture.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic" / "agentic_teacher_distill_architecture.jsonl"

PATHOGENS = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE", "Abaum", "Paer", "VRE", "NGono"]

SYS = (
    "You are a Lysos system-architecture explainer. Your job is to walk a "
    "developer or sub-agent through the Lysos antimicrobial drug-design "
    "Workbench architecture: agents, tools, ledger, state machines, "
    "intervention handling, error escalation, stage gates. Always provide "
    "concrete code-shaped formats (JSON envelopes, tool signatures, state "
    "names) so the answer is actionable, not abstract."
)

TOOLS_FULL = [
    ("amr",        "predict_mic_pathogen",       200,  "smiles, pathogen",                 "log_mic_predicted, mic_ug_ml, confidence"),
    ("amr",        "get_pathogen_resistome",     50,   "pathogen",                         "resistome dict + first-line therapy"),
    ("amr",        "check_resistance_genes",     100,  "pathogen, drug_class_or_smiles",   "relevant_genes list"),
    ("amr",        "predict_resistance_escape",  300,  "smiles, pathogen",                 "escape_mutations + red_team_verdict"),
    ("amr",        "find_active_against_mdr",    150,  "pathogens",                        "drug list with MIC ranges"),
    ("scoring",    "predict_admet",              100,  "smiles",                           "MW/logP/TPSA/Lipinski/F"),
    ("scoring",    "predict_hemolysis",          200,  "smiles",                           "safety_score + risk_class"),
    ("scoring",    "predict_synthesis_route",    800,  "smiles",                           "SA_score, steps, cost, route"),
    ("scoring",    "estimate_synth_cost",        250,  "smiles",                           "cost_class + USD/g estimate"),
    ("scoring",    "score_molecule",             350,  "smiles, target_pathogen",          "composite + weakest pillar"),
    ("scoring",    "find_similar_drugs",         400,  "query_smiles",                     "matches with Tanimoto"),
    ("structural", "dock_against_target",        5000, "smiles, pdb_id",                   "poses + best_score"),
    ("structural", "predict_binding_affinity",   1500, "smiles, target",                   "delta_g, pkd_predicted"),
    ("structural", "predict_complex_structure",  8000, "smiles, target_pdb_id",            "ipTM, pTM, ligand_RMSD (Boltz-2)"),
    ("generative", "propose_pocket_aware",       2000, "target_pdb, pocket_class",         "candidate proposals"),
    ("generative", "scaffold_hop",               1500, "smiles, n_proposals",              "bioisosteric alternatives"),
    ("generative", "transform_structure",        800,  "smiles, op",                       "single-product transform"),
    ("generative", "optimize_iteratively",       6000, "seed_smiles, objective, max_iters","optimization trajectory"),
    ("knowledge",  "compare_molecules",          100,  "smiles_a, smiles_b",               "Tanimoto + delta-properties"),
    ("knowledge",  "explain_mechanism",          200,  "smiles",                           "inferred_class + MoA narrative"),
    ("knowledge",  "find_target_structure",      500,  "pathogen",                         "primary_target + PDB list"),
    ("knowledge",  "get_drug_history",           150,  "drug_name",                        "class, year, MoA, trials"),
    ("knowledge",  "search_literature",          1500, "query",                            "papers + abstracts"),
    ("sandbox",    "execute_python",             500,  "code",                             "stdout, return_value"),
    ("sandbox",    "render_3d_scene",            200,  "structure, ligand_smiles",         "3D viz spec"),
]


def _round(x, n=3):
    return round(float(x), n)


# ============================================================================
# A. agent_role_designer
# ============================================================================
def trace_agent_role_designer(rng: random.Random) -> dict:
    user = "Explain the Designer agent's role in the Lysos Workbench. What can it do, what can't it do, and what tools does it call most often?"

    asst = (
        "[Designer-Role-Spec]:\n\n"
        "ROLE: Generate antimicrobial drug-candidate proposals against a target pathogen + structural target. Designer is the primary action agent — it proposes structures, calls in silico tools to evaluate them, reads results, iterates.\n\n"
        "INPUTS:\n"
        "  - pathogen (one of 8 priority: MRSA / Mtb / EColi-CRE / KpneuCRE / Abaum / Paer / VRE / NGono)\n"
        "  - constraint profile (lead-like / fragment-extension / macrocycle / AMP-derived / siderophore-conjugate / GMP-friendly)\n"
        "  - resistome briefing (auto-fetched via get_pathogen_resistome)\n"
        "  - structural target context (auto-fetched via find_target_structure)\n"
        "  - optional: anchor scaffold provided by user/Strategist\n\n"
        "OUTPUTS (per iteration):\n"
        "  - 2-5 candidate SMILES with structural rationale\n"
        "  - panel results: predicted MIC + ADMET + hemolysis + composite score\n"
        "  - best-of-batch selection + handoff to Critic\n\n"
        "TOOLS Designer calls (most → least frequent):\n"
        "  1. predict_mic_pathogen — primary activity gate (~200 ms)\n"
        "  2. predict_admet         — Lipinski/Veber filter (~100 ms)\n"
        "  3. predict_hemolysis     — safety panel (~200 ms)\n"
        "  4. score_molecule        — composite scoring (~350 ms)\n"
        "  5. scaffold_hop          — iteration via bioisostere (~1500 ms)\n"
        "  6. transform_structure   — single-atom edits (~800 ms)\n"
        "  7. propose_pocket_aware  — initial proposals from PDB context (~2000 ms)\n"
        "  8. predict_resistance_escape — red-team prior to handoff (~300 ms)\n"
        "  9. estimate_synth_cost / predict_synthesis_route — final feasibility (~250-800 ms)\n\n"
        "WHAT DESIGNER CANNOT DO:\n"
        "  - Make stage-gate decisions (advance / kill the campaign) — that's Strategist.\n"
        "  - Adversarial review — that's Critic.\n"
        "  - SMILES sanitization (canonical form, valence fixes) — that's Editor.\n"
        "  - Wet-lab handoff format — that's a Strategist call after Critic clearance.\n"
        "  - Modify the candidate ledger directly — Designer appends new entries; Strategist edits / kills.\n\n"
        "OUTPUT CONVENTION:\n"
        "  Every Designer turn ends with a structured PROPOSAL block:\n"
        "    PROPOSAL: <SMILES>\n"
        "    RATIONALE: <2-3 sentences citing the resistome briefing + structural rationale>\n"
        "    NEXT: <which tool to call next, and why>\n\n"
        "OUTPUT FORMAT (when handing off to Critic):\n"
        "  HANDOFF_TO: critic\n"
        "  CANDIDATE_ID: <ledger id>\n"
        "  CONCERN: <weakest pillar identified>\n"
        "  ASK: <specific question for Critic to address>\n\n"
        "DECISION: Designer proposes; Critic evaluates; Strategist routes."
    )

    return {
        "task": "teacher_arch_designer_role",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# B. agent_role_critic
# ============================================================================
def trace_agent_role_critic(rng: random.Random) -> dict:
    user = "Explain the Critic agent's role. How does it score candidates? What's the output format?"

    asst = (
        "[Critic-Role-Spec]:\n\n"
        "ROLE: Adversarial review of Designer's candidates. Catch issues that Designer's optimization-loop misses. Critic is intentionally pessimistic — its job is to BLOCK candidates that have hidden flaws.\n\n"
        "INPUTS:\n"
        "  - Candidate SMILES + Designer's score panel results\n"
        "  - Candidate ledger context (prior candidates, similar candidates)\n"
        "  - User constraint profile + interventions\n\n"
        "REVIEW DIMENSIONS (every candidate gets a verdict on each):\n"
        "  1. CHEMISTRY VALIDITY   — RDKit parse + sanitize\n"
        "  2. DRUG-LIKENESS        — Lipinski + Veber + Egan\n"
        "  3. PAINS / BAD ACTORS   — PAINS + Brenk + NIH + Lilly-MedChem rules\n"
        "  4. NOVELTY              — Tanimoto vs known-antibiotic index (cliff at 0.4)\n"
        "  5. ESCAPE MUTATIONS     — predict_resistance_escape verdict\n"
        "  6. MANUFACTURABILITY    — SA score + chiral count + step count + cost/g\n"
        "  7. CLINICAL VIABILITY   — bioavailability + tissue penetration + indication fit\n"
        "  8. CROSS-RESISTANCE     — cf first-line therapy class\n\n"
        "OUTPUT FORMAT (per candidate):\n"
        "  VERDICT: PASS | WARN | FAIL\n"
        "  PER-DIM:\n"
        "    chemistry_validity:    PASS|WARN|FAIL — <reason>\n"
        "    drug_likeness:         PASS|WARN|FAIL — <reason>\n"
        "    PAINS_actors:          PASS|WARN|FAIL — <reason>\n"
        "    novelty:               PASS|WARN|FAIL — <reason + Tanimoto>\n"
        "    escape_mutations:      PASS|WARN|FAIL — <verdict + top concern>\n"
        "    manufacturability:     PASS|WARN|FAIL — <SA + cost>\n"
        "    clinical_viability:    PASS|WARN|FAIL — <route + dosing>\n"
        "    cross_resistance:      PASS|WARN|FAIL — <vs first-line>\n"
        "  OVERALL: PASS / CONDITIONAL / BLOCKED\n"
        "  REVISIONS:\n"
        "    - <specific actionable fix for each FAIL dimension>\n\n"
        "VERDICT THRESHOLD:\n"
        "  - All 8 dimensions PASS → OVERALL: PASS → handoff to Strategist for advancement\n"
        "  - ≤2 WARN, 0 FAIL → OVERALL: CONDITIONAL → Designer iterates, addresses WARNs, re-submits\n"
        "  - ≥1 FAIL → OVERALL: BLOCKED → Designer must redesign or kill the candidate\n\n"
        "OUTPUT FORMAT (when handing off):\n"
        "  HANDOFF_TO: designer | strategist\n"
        "  CANDIDATE_ID: <ledger id>\n"
        "  VERDICT: PASS | CONDITIONAL | BLOCKED\n"
        "  REASON: <one-sentence summary>\n\n"
        "DECISION: Critic blocks before Strategist commits compute."
    )

    return {
        "task": "teacher_arch_critic_role",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# C. agent_role_strategist
# ============================================================================
def trace_agent_role_strategist(rng: random.Random) -> dict:
    user = "Explain the Strategist agent's role. When does Designer or Critic call it? What decisions does it make?"

    asst = (
        "[Strategist-Role-Spec]:\n\n"
        "ROLE: High-level campaign decisions. Allocates compute and budget across pathogens, decides when to TERMINATE, CONTINUE, or PIVOT a campaign, formats wet-lab handoffs, escalates to user when interventions are needed.\n\n"
        "INPUTS:\n"
        "  - Workbench candidate ledger (full state of all candidates across iterations)\n"
        "  - Compute / budget envelope\n"
        "  - User priorities + WHO tier\n"
        "  - Critic verdicts (BLOCKED / CONDITIONAL / PASS)\n"
        "  - Tool latency + cost estimates\n\n"
        "DECISION TYPES:\n"
        "  1. CAMPAIGN ALLOCATION — at session start, divide compute across pathogens\n"
        "  2. STAGE GATE          — advance from generation → optimization → wet-lab\n"
        "  3. PIVOT               — switch scaffold class when current plateau'd\n"
        "  4. KILL                — terminate a candidate or whole campaign\n"
        "  5. WET-LAB HANDOFF     — format top candidates for medchem team\n"
        "  6. USER ESCALATION     — request human intervention for ambiguous cases\n\n"
        "INVOCATION TRIGGERS:\n"
        "  - Designer: when 5 iterations completed without composite > 0.7 → PIVOT\n"
        "  - Designer: when ≥3 candidates with composite > 0.85 → STAGE_GATE wet-lab\n"
        "  - Critic: ≥2 BLOCKED candidates in a row → CAMPAIGN_KILL\n"
        "  - Auto: 40% of budget consumed without composite > 0.7 → STRATEGIST_REVIEW\n"
        "  - Auto: tool latency > expected_duration_ms × 3 → SYSTEM_HEALTH_CHECK\n\n"
        "OUTPUT FORMAT (decision block):\n"
        "  DECISION: TERMINATE | CONTINUE | PIVOT | KILL | HANDOFF | ESCALATE\n"
        "  RATIONALE: <2-3 sentences citing ledger evidence>\n"
        "  ALLOCATION_DELTA: <compute redistribution if applicable>\n"
        "  NEXT_AGENT: <designer | critic | editor | user>\n"
        "  TIMEOUT: <max wall-clock for next phase>\n\n"
        "WHAT STRATEGIST CANNOT DO:\n"
        "  - Generate new candidate SMILES — that's Designer.\n"
        "  - Adversarial review per candidate — that's Critic.\n"
        "  - Edit/canonicalize SMILES — that's Editor.\n"
        "  - Run tools directly — Strategist coordinates, doesn't execute.\n\n"
        "DECISION: Strategist is the campaign manager; Designer + Critic + Editor are line workers."
    )

    return {
        "task": "teacher_arch_strategist_role",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# D. agent_role_editor
# ============================================================================
def trace_agent_role_editor(rng: random.Random) -> dict:
    user = "What is the Editor agent? When is it called?"

    asst = (
        "[Editor-Role-Spec]:\n\n"
        "ROLE: Structural sanitization. Editor is the lowest-level agent — it cleans SMILES strings, applies named transforms, fixes valence issues, canonicalizes, and returns a clean structure ready for tool invocation.\n\n"
        "INPUTS:\n"
        "  - Source SMILES (possibly malformed)\n"
        "  - Optional named transform op (add_methyl, remove_OH, ring_expand, etc.)\n"
        "  - Optional constraint set (preserve specific stereo, retain pharmacophore)\n\n"
        "INVOCATION TRIGGERS:\n"
        "  - predict_admet returned 'invalid SMILES' → Editor canonicalize\n"
        "  - Designer emitted a SMILES that fails RDKit parse → Editor fixes valence\n"
        "  - Designer requested a structural transform (Critic suggested 'remove the catechol') → Editor applies\n"
        "  - User drag-and-drop edit on the 3D viewer → Editor reflects in SMILES\n\n"
        "OUTPUT FORMAT:\n"
        "  EDIT_OP: <op_name>\n"
        "  SOURCE_SMILES: <input>\n"
        "  PRODUCT_SMILES: <output, canonical>\n"
        "  SUCCESS: true | false\n"
        "  NOTES: <if false, why; if true, what changed>\n\n"
        "TOOL DEPENDENCIES:\n"
        "  - transform_structure (single-atom transforms)\n"
        "  - sanitize via Chem.MolFromSmiles + Chem.SanitizeMol\n"
        "  - canonicalize via Chem.MolToSmiles(canonical=True, isomericSmiles=True)\n\n"
        "WHAT EDITOR CANNOT DO:\n"
        "  - Generate new candidates — Designer's job.\n"
        "  - Score candidates — Designer's job (Editor is purely structural).\n"
        "  - Make strategic decisions — Strategist's job.\n\n"
        "DECISION: Editor is the syntax-only agent. Designer is the semantics agent."
    )

    return {
        "task": "teacher_arch_editor_role",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# E. agent_handoff_protocol
# ============================================================================
def trace_agent_handoff_protocol(rng: random.Random) -> dict:
    user = "Explain the agent-to-agent handoff protocol. How does Designer pass to Critic, and Critic to Strategist?"

    asst = (
        "[Handoff-Protocol]:\n\n"
        "Every handoff is a structured JSON envelope. The receiving agent reads the envelope and either acts on it or rejects with a typed error.\n\n"
        "DESIGNER -> CRITIC envelope:\n"
        "{\n"
        '  \"type\": \"handoff\",\n'
        '  \"from\": \"designer\",\n'
        '  \"to\": \"critic\",\n'
        '  \"candidate_id\": \"L42-3\",\n'
        '  \"smiles\": \"OC(=O)[C@H]1N2C(=O)...\",\n'
        '  \"score_panel\": {\"mic_ug_ml\": 0.4, \"composite\": 0.78, \"weakest\": \"novelty\"},\n'
        '  \"design_rationale\": \"5GC anchor with extended thiopyridyl tail\",\n'
        '  \"specific_concerns\": [\"novelty Tanimoto 0.62 vs ceftaroline\"],\n'
        '  \"ask\": \"verify cross-resistance to vancomycin via novelty + escape panels\",\n'
        '  \"timestamp_ms\": 1714824930000\n'
        "}\n\n"
        "CRITIC -> DESIGNER envelope (verdict CONDITIONAL):\n"
        "{\n"
        '  \"type\": \"handoff\",\n'
        '  \"from\": \"critic\",\n'
        '  \"to\": \"designer\",\n'
        '  \"candidate_id\": \"L42-3\",\n'
        '  \"verdict\": \"CONDITIONAL\",\n'
        '  \"per_dim_scores\": {\"chemistry\": \"PASS\", \"drug_likeness\": \"PASS\", \"PAINS\": \"PASS\", \"novelty\": \"WARN\", \"escape\": \"WARN\", \"manufacturability\": \"PASS\", \"clinical\": \"PASS\", \"cross_resistance\": \"PASS\"},\n'
        '  \"required_revisions\": [\n'
        '    {\"dim\": \"novelty\", \"action\": \"scaffold_hop on heteroaryl tail to reduce Tanimoto < 0.5\"},\n'
        '    {\"dim\": \"escape\", \"action\": \"widen pocket interactions to evade mecA-N146K\"}\n'
        '  ]\n'
        "}\n\n"
        "CRITIC -> STRATEGIST envelope (verdict PASS):\n"
        "{\n"
        '  \"type\": \"handoff\",\n'
        '  \"from\": \"critic\",\n'
        '  \"to\": \"strategist\",\n'
        '  \"candidate_id\": \"L42-3\",\n'
        '  \"verdict\": \"PASS\",\n'
        '  \"all_dims_pass\": true,\n'
        '  \"recommended_action\": \"advance_to_wet_lab\",\n'
        '  \"summary\": \"All 8 review dimensions PASS. Composite 0.84, low escape risk, manufacturable at $480/g.\"\n'
        "}\n\n"
        "STRATEGIST -> DESIGNER envelope (PIVOT decision):\n"
        "{\n"
        '  \"type\": \"handoff\",\n'
        '  \"from\": \"strategist\",\n'
        '  \"to\": \"designer\",\n'
        '  \"action\": \"pivot_scaffold\",\n'
        '  \"new_anchor\": \"oxadiazine-cephalosporin (away from current 5GC plateau)\",\n'
        '  \"rationale\": \"5 iterations on 5GC scaffold without composite > 0.7. Time to switch class.\",\n'
        '  \"compute_remaining_min\": 12\n'
        "}\n\n"
        "ERROR ENVELOPE (any agent can emit):\n"
        "{\n"
        '  \"type\": \"error\",\n'
        '  \"from\": \"<agent>\",\n'
        '  \"error_code\": \"INVALID_SMILES | TOOL_TIMEOUT | LEDGER_LOCK | AMBIGUOUS_CONSTRAINT\",\n'
        '  \"recovery\": \"retry | escalate | abort\",\n'
        '  \"detail\": \"...\"\n'
        "}\n\n"
        "DECISION: All handoffs MUST use this envelope. Free-text handoffs are rejected by the message router."
    )

    return {
        "task": "teacher_arch_handoff_protocol",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# F. tool_registry_orientation
# ============================================================================
def trace_tool_registry_orientation(rng: random.Random) -> dict:
    user = "Walk me through the full Lysos tool registry. What are the categories, latencies, and when do I use each?"

    rows = "\n".join(
        f"  {cat:11s} | {name:30s} | {lat:>5}ms | in: {inp:30s} | out: {out}"
        for cat, name, lat, inp, out in TOOLS_FULL
    )

    asst = (
        f"[Tool-Registry-Orientation]:\n\n"
        f"Lysos has 25 tools organized into 6 categories. Each tool has a typed input model, "
        f"typed output model, expected_duration_ms, and tags. Designer/Critic/Editor invoke "
        f"tools via structured tool_call envelopes; the router dispatches to the appropriate "
        f"backend (local Python, RDKit, ML predictor, ROCm-Boltz2 service).\n\n"
        f"FULL REGISTRY (category | tool | latency | input | output):\n\n"
        f"{rows}\n\n"
        f"CATEGORY USAGE:\n"
        f"  amr        — pathogen-specific knowledge + activity prediction (cheap, fast)\n"
        f"  scoring    — small-molecule property prediction (cheap, used in every panel)\n"
        f"  structural — 3D pose + binding affinity (expensive, only on top candidates)\n"
        f"  generative — propose / iterate / transform (medium cost)\n"
        f"  knowledge  — literature + drug history + comparison (medium-cost)\n"
        f"  sandbox    — Python execution + 3D rendering (cheap)\n\n"
        f"DECISION TREE — which tool to call:\n"
        f"  Need pathogen-specific MIC?       → predict_mic_pathogen\n"
        f"  Need ADMET stoplight?              → predict_admet\n"
        f"  Need 3D binding pose?              → predict_complex_structure (Boltz-2) OR dock_against_target (Vina)\n"
        f"  Need scaffold variants?            → scaffold_hop\n"
        f"  Need synthesis cost?               → predict_synthesis_route\n"
        f"  Need to validate novelty?          → find_similar_drugs + compare_molecules\n"
        f"  Need resistance verdict?           → predict_resistance_escape\n"
        f"  Need pathogen briefing?            → get_pathogen_resistome\n"
        f"  Need to find a target structure?   → find_target_structure\n"
        f"  Need clinical context for a drug?  → get_drug_history\n"
        f"  Need recent literature?            → search_literature\n"
        f"  Need to run custom math?           → execute_python\n\n"
        f"LATENCY GROUPS (for orchestration planning):\n"
        f"  CHEAP (≤300ms):       all amr (except resistance_escape) + most scoring + compare_molecules + execute_python\n"
        f"  MEDIUM (300-2000ms):  generative + structural-light + knowledge\n"
        f"  EXPENSIVE (>2000ms):  predict_complex_structure (Boltz-2), dock_against_target (Vina), optimize_iteratively\n\n"
        f"DECISION: cheap tools first as gates; expensive tools only on survivors."
    )

    return {
        "task": "teacher_arch_tool_registry",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# G. tool_decision_tree
# ============================================================================
def trace_tool_decision_tree(rng: random.Random) -> dict:
    questions = [
        ("I have a SMILES and want to know if it's active against MRSA.",
         "predict_mic_pathogen(smiles, pathogen='MRSA') — primary tool. If confidence < 0.6, also call predict_binding_affinity(smiles, target='PBP2a') for cross-check."),
        ("I want to find the structural target for Mtb.",
         "find_target_structure(pathogen='Mtb') — returns InhA / KatG / RpoB with PDB ids. Use the primary_target field for downstream propose_pocket_aware calls."),
        ("I need 3D pose visualization of a candidate against KPC-2.",
         "Two options: (a) predict_complex_structure(smiles, target_pdb_id='6Q9B') — Boltz-2, gives ipTM + RMSD (8s); (b) dock_against_target(smiles, pdb_id='6Q9B') — Vina, faster but less accurate (5s). Use (a) for Critic review, (b) for Designer triage."),
        ("I want to explore alternative scaffolds for a hit molecule.",
         "scaffold_hop(smiles, n_proposals=6) — returns bioisosteric alternatives. If you need rule-driven transforms (add methyl, remove OH), use transform_structure(smiles, op=...) instead."),
        ("I want to know if my candidate is too similar to an existing antibiotic.",
         "find_similar_drugs(query_smiles=smiles) — returns Tanimoto-ranked matches against the 20K-row known-antibiotic index. Plus compare_molecules(smiles_a, smiles_b) for pairwise check. Cliff at Tanimoto 0.6."),
        ("I want to know if my candidate violates Lipinski.",
         "predict_admet(smiles) — returns MW/logP/HBD/HBA/Lipinski violations. Plus structural_alerts via score_molecule for PAINS check."),
        ("I want to know if my candidate is hemolytic.",
         "predict_hemolysis(smiles) — returns safety_score + risk_class (low/medium/high). Trained on DBAASP hemolysis labels."),
        ("I want to predict which mutations would make my candidate fail.",
         "predict_resistance_escape(smiles, pathogen) — returns top escape mutations + fold-change + red_team_verdict. Always run before wet-lab handoff."),
        ("I need a synthesis route + cost estimate.",
         "predict_synthesis_route(target_smiles) — returns SA score, step count, cost, route. Use estimate_synth_cost for a quick cost estimate without full retrosynthesis."),
        ("I want to know what's clinically used against KpneuCRE.",
         "get_pathogen_resistome(pathogen='KpneuCRE') — returns first-line therapy + resistome. Plus find_active_against_mdr(pathogens=['KpneuCRE']) for late-stage drug list."),
    ]
    q, a = rng.choice(questions)

    user = q

    asst = f"[Tool-Decision-Tree]:\n\n{a}\n\nDECISION: route the call as described above."

    return {
        "task": "teacher_arch_tool_decision_tree",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# H. candidate_ledger_format
# ============================================================================
def trace_candidate_ledger_format(rng: random.Random) -> dict:
    user = "Show me the format of the Workbench candidate ledger. How are entries structured?"

    asst = (
        "[Candidate-Ledger-Format]:\n\n"
        "The candidate ledger is a Postgres table with the following schema. Designer APPENDS, Critic UPDATES verdict, Strategist UPDATES status. The ledger is the single source of truth for the campaign state.\n\n"
        "Schema (lysos.candidates):\n"
        "  candidate_id          TEXT PRIMARY KEY  -- e.g. L42-3 (campaign 42, candidate 3)\n"
        "  campaign_id           TEXT              -- references campaign\n"
        "  iteration             INT               -- which design iteration\n"
        "  parent_candidate_id   TEXT NULL         -- if scaffold-hopped from another\n"
        "  smiles                TEXT NOT NULL     -- canonical SMILES\n"
        "  smiles_hash           TEXT              -- InChI key for dedup\n"
        "  pathogen              TEXT NOT NULL\n"
        "  target_protein        TEXT              -- e.g. PBP2a\n"
        "  target_pdb            TEXT              -- e.g. 1VQQ\n"
        "  scaffold_class        TEXT              -- e.g. '5GC ceftaroline-class'\n"
        "  designer_rationale    TEXT              -- Designer's structural reasoning\n"
        "  panel_scores          JSONB             -- { mic_ug_ml, admet, hemolysis, composite }\n"
        "  panel_confidence      JSONB             -- { tool_name: confidence_score }\n"
        "  critic_verdict        TEXT              -- PASS | CONDITIONAL | BLOCKED | NULL\n"
        "  critic_findings       JSONB             -- per-dimension findings\n"
        "  strategist_status     TEXT              -- proposed | review | approved | killed | wet_lab\n"
        "  resistance_verdict    TEXT              -- low-risk | moderate-risk | high-risk\n"
        "  synth_cost_per_g      INT               -- USD\n"
        "  synth_steps           INT\n"
        "  novelty_tanimoto      REAL              -- vs known-corpus index\n"
        "  created_at            TIMESTAMP\n"
        "  updated_at            TIMESTAMP\n\n"
        "READ patterns (Designer + Critic):\n"
        "  -- Latest 5 candidates in current iteration\n"
        "  SELECT * FROM lysos.candidates WHERE campaign_id = $1 AND iteration = (SELECT MAX(iteration) FROM lysos.candidates WHERE campaign_id = $1) ORDER BY panel_scores->>'composite' DESC LIMIT 5;\n\n"
        "  -- All BLOCKED candidates (for Strategist KILL decision)\n"
        "  SELECT * FROM lysos.candidates WHERE campaign_id = $1 AND critic_verdict = 'BLOCKED';\n\n"
        "  -- Top wet-lab candidates\n"
        "  SELECT * FROM lysos.candidates WHERE strategist_status = 'wet_lab' ORDER BY panel_scores->>'composite' DESC;\n\n"
        "WRITE patterns:\n"
        "  Designer APPEND: INSERT new candidate with strategist_status = 'proposed'\n"
        "  Critic UPDATE:   UPDATE critic_verdict, critic_findings\n"
        "  Strategist UPDATE: UPDATE strategist_status (advance / kill)\n\n"
        "DEDUPLICATION:\n"
        "  smiles_hash UNIQUE constraint prevents duplicate proposals within a campaign. "
        "If Designer tries to insert a candidate whose InChI key already exists, the insert "
        "fails — Designer must scaffold-hop or proceed with the existing candidate.\n\n"
        "DECISION: ledger is append-mostly. Killed candidates are kept (with strategist_status = 'killed') for audit trail."
    )

    return {
        "task": "teacher_arch_candidate_ledger",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# I. state_machine
# ============================================================================
def trace_state_machine(rng: random.Random) -> dict:
    user = "What states does the Designer agent transition through during a campaign? Draw the state machine."

    asst = (
        "[Designer-State-Machine]:\n\n"
        "States:\n"
        "  IDLE                    — waiting for user / Strategist invocation\n"
        "  ABSORBING_CONTEXT       — fetching resistome briefing + target structure\n"
        "  GENERATING              — proposing candidate SMILES\n"
        "  SCORING                 — panel calls (predict_mic + predict_admet + ...)\n"
        "  ITERATING               — applying scaffold_hop on weakest candidate\n"
        "  HANDING_OFF_TO_CRITIC   — emitting handoff envelope\n"
        "  WAITING_ON_CRITIC       — paused, awaiting Critic verdict\n"
        "  ADDRESSING_REVISIONS    — applying Critic's required revisions\n"
        "  HANDING_OFF_TO_STRATEGIST — emitting handoff envelope (after Critic PASS)\n"
        "  BLOCKED                 — error or BLOCKED verdict; awaiting recovery\n"
        "  TERMINATED              — campaign over (success or kill)\n\n"
        "Transitions:\n"
        "  IDLE → ABSORBING_CONTEXT       (on Strategist 'start_campaign' or user 'design X against Y')\n"
        "  ABSORBING_CONTEXT → GENERATING (after get_pathogen_resistome + find_target_structure return)\n"
        "  GENERATING → SCORING           (after candidate batch proposed)\n"
        "  SCORING → ITERATING            (composite < 0.65, has compute remaining)\n"
        "  SCORING → HANDING_OFF_TO_CRITIC (composite ≥ 0.65, ready for review)\n"
        "  ITERATING → SCORING            (after scaffold_hop returns)\n"
        "  HANDING_OFF_TO_CRITIC → WAITING_ON_CRITIC (envelope sent)\n"
        "  WAITING_ON_CRITIC → ADDRESSING_REVISIONS  (verdict CONDITIONAL)\n"
        "  WAITING_ON_CRITIC → HANDING_OFF_TO_STRATEGIST (verdict PASS)\n"
        "  WAITING_ON_CRITIC → BLOCKED                 (verdict BLOCKED)\n"
        "  ADDRESSING_REVISIONS → SCORING (revisions applied)\n"
        "  BLOCKED → IDLE                 (Strategist resets the campaign)\n"
        "  HANDING_OFF_TO_STRATEGIST → TERMINATED (Strategist accepted handoff)\n"
        "  ANY_STATE → BLOCKED            (on tool error / timeout)\n"
        "  ANY_STATE → TERMINATED         (on Strategist KILL)\n\n"
        "Persistence:\n"
        "  State is stored in the ledger as `designer_state` column (per campaign). On crash, "
        "Designer resumes from the persisted state. Tool results from the previous state are "
        "preserved in the ledger so re-running doesn't lose work.\n\n"
        "DECISION: Designer is a finite state machine with 11 states. Persisted to ledger. Recoverable."
    )

    return {
        "task": "teacher_arch_state_machine",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# J. stage_gate_criteria
# ============================================================================
def trace_stage_gate_criteria(rng: random.Random) -> dict:
    user = "What's the criteria for advancing a candidate from Stage 1 (initial proposal) to Stage 2 (in silico panel) to Stage 3 (wet-lab handoff)?"

    asst = (
        "[Stage-Gate-Criteria]:\n\n"
        "Lysos has 4 candidate stages with explicit advancement gates. A candidate cannot skip stages.\n\n"
        "STAGE 1: INITIAL PROPOSAL\n"
        "  - Designer has proposed the SMILES with structural rationale\n"
        "  - SMILES is RDKit-parseable (Editor verified)\n"
        "  - Initial scaffold class identified\n"
        "  - Ledger entry created\n"
        "  GATE → STAGE 2: SMILES is valid + scaffold class is in the supported list\n\n"
        "STAGE 2: IN SILICO PANEL\n"
        "  - All cheap tools called (predict_mic_pathogen, predict_admet, predict_hemolysis)\n"
        "  - Composite score computed via score_molecule\n"
        "  - Confidence ≥ 0.5 on activity prediction\n"
        "  - At most 2 Lipinski violations\n"
        "  GATE → STAGE 3:\n"
        "    - composite ≥ 0.65 AND\n"
        "    - mic_ug_ml ≤ 4 (active range) AND\n"
        "    - hemolysis risk ≤ medium AND\n"
        "    - lipinski_violations ≤ 2 AND\n"
        "    - confidence ≥ 0.6\n\n"
        "STAGE 3: CRITIC REVIEW + RED-TEAM\n"
        "  - Critic has scored all 8 dimensions\n"
        "  - predict_resistance_escape returned a verdict\n"
        "  - find_similar_drugs ran for novelty check\n"
        "  - predict_synthesis_route ran for synth feasibility\n"
        "  GATE → STAGE 4:\n"
        "    - Critic verdict PASS (all 8 dimensions PASS) OR CONDITIONAL after revisions accepted\n"
        "    - resistance verdict ≤ moderate-risk\n"
        "    - novelty Tanimoto < 0.6 vs known corpus\n"
        "    - synthesis cost ≤ $2000/g GMP estimate\n\n"
        "STAGE 4: WET-LAB HANDOFF\n"
        "  - Strategist has approved\n"
        "  - Handoff envelope emitted to medchem team\n"
        "  - Synthesis priority (P0/P1/P2) assigned\n"
        "  - Wet-lab MIC + cytotox ordered\n"
        "  GATE → CLINICAL CANDIDATE: wet-lab MIC matches predicted ±2× AND cytotox cleared\n\n"
        "FAIL PATHS:\n"
        "  - Stage 2 fails: Designer iterates (scaffold_hop) up to 5 times\n"
        "  - After 5 iterations without Stage 3 advancement: Strategist PIVOTs scaffold class\n"
        "  - Stage 3 BLOCKED: Designer redesigns or KILL\n"
        "  - Stage 4 wet-lab fails (MIC > 4× predicted): Strategist re-evaluates the candidate's whole panel for systematic prediction error\n\n"
        "DECISION: 4 explicit stages, explicit gates. Non-skippable."
    )

    return {
        "task": "teacher_arch_stage_gates",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# K. intervention_handler
# ============================================================================
def trace_intervention_handler(rng: random.Random) -> dict:
    user = "How does the Designer agent handle a user intervention mid-campaign?"

    interventions = [
        ("user clamped MW < 400", "All future proposals must have MW < 400. Re-validate the current candidate batch; kill any that violate."),
        ("user banned aromatic amines", "Add 'aromatic amine' to the structural-alerts BLOCK list. Editor screens future candidates; existing candidates with aromatic amines are flagged for revision or kill."),
        ("user pinned PDB target to 5M18", "All propose_pocket_aware calls now use target_pdb='5M18'. Existing candidates not anchored to 5M18 are downgraded in priority."),
        ("user requested only DBO scaffolds", "Restrict scaffold class to DBO (diazabicyclooctane). All future propose_pocket_aware + scaffold_hop calls filter for DBO. Existing non-DBO candidates are killed."),
        ("user reduced compute budget by 50%", "Halve all per-tool retry counts. Suspend expensive tools (predict_complex_structure, dock_against_target) for triage; only run on top-1 candidate."),
        ("user added a new pathogen NGono", "Spawn a parallel campaign for NGono. Allocate 20% of remaining compute. Initial Designer call seeded with NGono resistome briefing."),
    ]
    intervention, response = rng.choice(interventions)

    asst = (
        f"[Intervention-Handler]:\n\n"
        f"INTERVENTION RECEIVED: {intervention}\n\n"
        f"PROCESSING:\n"
        f"  1. Append to lysos.interventions table with timestamp + agent context.\n"
        f"  2. Broadcast to all active agents via the message bus.\n"
        f"  3. Each agent updates its constraint state.\n"
        f"  4. Designer pauses current iteration; Strategist evaluates impact.\n\n"
        f"RESPONSE: {response}\n\n"
        f"COMPLIANCE CHECK ON EXISTING CANDIDATES:\n"
        f"  - Iterate through ledger.candidates WHERE campaign_id = $current AND strategist_status NOT IN ('killed', 'wet_lab').\n"
        f"  - For each candidate, run the new constraint over its panel data.\n"
        f"  - Mark non-compliant candidates as 'intervention_violation'.\n"
        f"  - Strategist decides: revise (Designer applies fix) or kill.\n\n"
        f"REPLAY:\n"
        f"  After intervention is applied, Designer resumes from the previous state with the new constraints in effect. "
        f"Tool results from the previous state are preserved in the ledger so the campaign doesn't restart from scratch.\n\n"
        f"INTERVENTION ENVELOPE FORMAT:\n"
        f"{{\n"
        f'  \"type\": \"intervention\",\n'
        f'  \"source\": \"user\",\n'
        f'  \"campaign_id\": \"<id>\",\n'
        f'  \"directive\": \"<intervention>\",\n'
        f'  \"target_agents\": [\"designer\", \"critic\", \"strategist\"],\n'
        f'  \"effective_at\": \"now | next_iteration\",\n'
        f'  \"timestamp\": \"...\"\n'
        f"}}\n\n"
        f"DECISION: interventions are processed as first-class events; existing candidates are re-validated against the new constraint."
    )

    return {
        "task": "teacher_arch_intervention",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": f"Mid-campaign user intervention: {intervention}. How does Designer handle?"},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# L. error_escalation
# ============================================================================
def trace_error_escalation(rng: random.Random) -> dict:
    user = "What's the error escalation chain when a tool fails?"

    asst = (
        "[Error-Escalation-Chain]:\n\n"
        "Errors flow up the agent hierarchy: tool → designer → critic → strategist → user.\n\n"
        "LEVEL 0: TOOL\n"
        "  Tool returns a structured error code:\n"
        "    INVALID_INPUT, TIMEOUT, SERVICE_UNAVAILABLE, MODEL_UNCERTAIN, NO_ROUTE_FOUND\n"
        "  Tool retries once internally before returning error.\n\n"
        "LEVEL 1: DESIGNER\n"
        "  Designer receives error → tries recovery:\n"
        "    INVALID_INPUT     → Editor canonicalize + retry\n"
        "    TIMEOUT           → Retry with smaller batch / shorter context\n"
        "    SERVICE_UNAVAILABLE → Wait + retry once; if still down, escalate\n"
        "    MODEL_UNCERTAIN   → Run orthogonal tool for cross-check; if both agree, accept; if not, escalate\n"
        "    NO_ROUTE_FOUND    → Try scaffold_hop to a more conventional core; if still no route, escalate\n"
        "  After 1 recovery attempt, escalate to LEVEL 2.\n\n"
        "LEVEL 2: CRITIC\n"
        "  Critic does NOT handle errors directly — it reviews completed candidates. "
        "  But Critic CAN trigger error escalation if it detects a systematic issue "
        "  (e.g., 5 consecutive candidates fail predict_resistance_escape — likely a service issue).\n\n"
        "LEVEL 3: STRATEGIST\n"
        "  Strategist receives error escalation → decides:\n"
        "    DEPENDENT_TOOL_DOWN → Pause the campaign; resume when the tool is back up.\n"
        "    SYSTEMATIC_FAILURE  → Switch tool family (e.g., dock_against_target instead of predict_complex_structure).\n"
        "    BUDGET_EXHAUSTED    → Kill the campaign + emit summary to user.\n"
        "    CRITICAL_ERROR      → Pause + escalate to user.\n\n"
        "LEVEL 4: USER\n"
        "  User receives a notification with:\n"
        "    - Campaign id + state at time of error\n"
        "    - Error chain (which tool, which agent, what was tried)\n"
        "    - Suggested actions (continue, pivot, kill)\n"
        "  User can intervene with one of the standard interventions.\n\n"
        "ERROR ENVELOPE:\n"
        "{\n"
        '  \"type\": \"error\",\n'
        '  \"campaign_id\": \"<id>\",\n'
        '  \"agent\": \"designer | critic | strategist\",\n'
        '  \"error_code\": \"INVALID_INPUT | TIMEOUT | SERVICE_UNAVAILABLE | MODEL_UNCERTAIN | NO_ROUTE_FOUND\",\n'
        '  \"context\": {\"tool\": \"<name>\", \"smiles\": \"...\"},\n'
        '  \"recovery_attempted\": [\"<step1>\", \"<step2>\"],\n'
        '  \"escalation_target\": \"strategist | user\"\n'
        "}\n\n"
        "RETRY POLICY:\n"
        "  Idempotent tools (read-only): retry up to 3 times with exponential backoff.\n"
        "  Mutating tools (none in current Lysos): retry once, then escalate.\n\n"
        "DECISION: errors escalate level by level. Each agent has its scope of recovery."
    )

    return {
        "task": "teacher_arch_error_escalation",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# M. branch_merge_strategy
# ============================================================================
def trace_branch_merge(rng: random.Random) -> dict:
    user = "When does the Strategist branch a campaign? When does it merge branches?"

    asst = (
        "[Branch-Merge-Strategy]:\n\n"
        "Lysos campaigns can branch when there's a strategic decision point that requires exploring multiple paths in parallel. Branches are independent sub-campaigns.\n\n"
        "BRANCH TRIGGERS (Strategist initiates):\n"
        "  1. SCAFFOLD CLASS PIVOT — current scaffold plateau'd; spawn a parallel campaign on a different scaffold class\n"
        "  2. CONSTRAINT EXPLORATION — same target with two constraint profiles (lead-like vs macrocycle)\n"
        "  3. PATHOGEN PRIORITIZATION — split a multi-pathogen campaign into per-pathogen branches\n"
        "  4. MECHANISM EXPLORATION — same pathogen, two distinct target proteins (PBP3 vs MexAB efflux)\n"
        "  5. RED-TEAM EXPLORATION — given a candidate, branch to design its successor that evades the predicted escape\n\n"
        "BRANCH ENVELOPE:\n"
        "{\n"
        '  \"type\": \"branch\",\n'
        '  \"parent_campaign_id\": \"...\",\n'
        '  \"branch_id\": \"<parent>-A\",\n'
        '  \"divergence_reason\": \"scaffold_class_pivot | constraint_exploration | ...\",\n'
        '  \"shared_context\": [\"resistome_briefing\", \"target_structure\"],\n'
        '  \"divergent_constraint\": {\"scaffold_class\": \"DBO\"},\n'
        '  \"compute_allocation_pct\": 30\n'
        "}\n\n"
        "MERGE TRIGGERS:\n"
        "  1. CONVERGENCE — both branches independently produced the same candidate (de-dup via smiles_hash)\n"
        "  2. RESOURCE SCARCITY — running out of compute; pick the higher-composite branch\n"
        "  3. GOAL SATISFIED — one branch produced a clear winner; absorb the other\n"
        "  4. STAGE 4 HANDOFF — both branches reached wet-lab; merge into a single handoff list\n\n"
        "MERGE ENVELOPE:\n"
        "{\n"
        '  \"type\": \"merge\",\n'
        '  \"branches\": [\"<parent>-A\", \"<parent>-B\"],\n'
        '  \"target_branch\": \"<parent>\",\n'
        '  \"merge_strategy\": \"top_K_by_composite | union | dedup\",\n'
        '  \"K\": 5\n'
        "}\n\n"
        "AUDIT TRAIL:\n"
        "  Every branch / merge is logged in lysos.campaigns with full provenance. "
        "  Reconstructing 'how did we get to this candidate' walks the branch tree.\n\n"
        "DECISION: branch on strategic divergence; merge when convergence or resource scarcity."
    )

    return {
        "task": "teacher_arch_branch_merge",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# N. end_to_end_pipeline_map
# ============================================================================
def trace_end_to_end_pipeline(rng: random.Random) -> dict:
    user = "Map the end-to-end Lysos pipeline from sprint planning through deployment."

    asst = (
        "[End-to-End-Pipeline-Map]:\n\n"
        "Lysos has 7 sequential stages from sprint planning to model deployment. Each stage has its own data artifacts, configs, and verification harness.\n\n"
        "STAGE 0: SPRINT PLANNING\n"
        "  - Define which (pathogen, target) campaigns to run\n"
        "  - Allocate compute / budget envelope per campaign\n"
        "  - Curate the resistome briefing + target PDBs\n"
        "  - Lock the constraint profile per campaign\n"
        "  Artifacts: sprint config YAML, campaign plan markdown\n\n"
        "STAGE 1: DATA PREP (CPU)\n"
        "  - Source ingestion (ChEMBL, DrugBank, NPAtlas, DBAASP, DRAMP, etc.)\n"
        "  - Standardization (chemistry corpus cleanup: peptide-as-SMILES detection, stereo, tautomer)\n"
        "  - Synthetic data generation (decoys, augmentation, agentic traces, teacher distill)\n"
        "  - Dataset bake (pro-vN)\n"
        "  - Smoke tests + manifest hash\n"
        "  Artifacts: data/processed/amr-stage2-pro-vN, MANIFEST.json\n\n"
        "STAGE 2: STAGE-1 SFT (TxGemma-4) — 8× MI300X, ~6h\n"
        "  - Replicate Google's TxGemma recipe on Gemma 4 base\n"
        "  - 28 ADME/Tox/HTS task instruction tuning\n"
        "  - Output: rahul24raj/txgemma-4-31b\n\n"
        "STAGE 3: STAGE-2 SFT (Lysos AMR-spec) — 1× MI300X, ~12h\n"
        "  - SFT on amr-stage2-pro-vN (~320K rows for v7)\n"
        "  - Multi-task mixing per task_mix in config\n"
        "  - Response template: <start_of_turn>model\\n\n"
        "  - Output: rahul24raj/lysos-base\n\n"
        "STAGE 4: STAGE-3 GRPO RL — 1× MI300X, ~10h\n"
        "  - Group-relative policy optimization on amr-rl-prompts-v3\n"
        "  - 12-component reward stack (validity, MIC, ADMET, novelty, ...)\n"
        "  - Reference model = Stage 2 base (frozen)\n"
        "  - Output: rahul24raj/lysos-rl\n\n"
        "STAGE 5: EVAL HARNESS\n"
        "  - 7 quantitative leaderboard metrics (chem_validity, novelty_tanimoto, MIC_RMSE, ADMET_pass, tool_call_accuracy, refusal_robustness, reasoning_faithfulness)\n"
        "  - Locked configs (eval/run_all.py with EVAL_CONFIG)\n"
        "  - Pre-train baseline + post-train deltas\n"
        "  Artifacts: reports/eval_v3.json\n\n"
        "STAGE 6: DEPLOYMENT\n"
        "  - vLLM serving (rocm/vllm:latest container on MI300X)\n"
        "  - Lysos Workbench frontend (FastAPI + React/Vite)\n"
        "  - HF Space for public demo (Docker SDK)\n"
        "  - Model card + dataset card + manifest exposure\n"
        "  Artifacts: workspace/api, workspace/web, HF Space\n\n"
        "FEEDBACK LOOP (continuous):\n"
        "  - Wet-lab results inform predictor calibration\n"
        "  - User interventions trigger constraint updates\n"
        "  - Failure modes feed back into the eval harness\n\n"
        "DECISION: 7-stage pipeline, each gated by its own verification. Manifest-tracked for reproducibility."
    )

    return {
        "task": "teacher_arch_pipeline_map",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# O. subagent_dispatcher
# ============================================================================
def trace_subagent_dispatcher(rng: random.Random) -> dict:
    user = "How does the parent agent dispatch a scoped task to a sub-agent?"

    asst = (
        "[Subagent-Dispatcher]:\n\n"
        "Lysos uses scoped sub-agents for tasks that need fresh context. The parent agent (Strategist or Designer) emits a dispatch envelope; the sub-agent runs in isolation with the scoped task only.\n\n"
        "WHY SUB-AGENTS:\n"
        "  - Context window discipline: parent doesn't pollute its context with sub-task details\n"
        "  - Parallelism: multiple sub-agents run simultaneously\n"
        "  - Specialization: different sub-agents have different system prompts + tool subsets\n\n"
        "DISPATCH ENVELOPE:\n"
        "{\n"
        '  \"type\": \"dispatch\",\n'
        '  \"parent_agent\": \"designer | strategist\",\n'
        '  \"subagent_role\": \"editor | critic | red_team | resistance_forecaster | manufacturing_eval\",\n'
        '  \"scoped_task\": \"<one-sentence task description>\",\n'
        '  \"scoped_inputs\": {\"smiles\": \"...\", \"pathogen\": \"...\"},\n'
        '  \"allowed_tools\": [\"predict_resistance_escape\", \"check_resistance_genes\"],\n'
        '  \"timeout_ms\": 30000,\n'
        '  \"return_format\": \"json | structured_text\"\n'
        "}\n\n"
        "RETURN ENVELOPE:\n"
        "{\n"
        '  \"type\": \"dispatch_return\",\n'
        '  \"dispatch_id\": \"<uuid>\",\n'
        '  \"subagent_role\": \"...\",\n'
        '  \"result\": {\"verdict\": \"low-risk\", \"summary\": \"...\"},\n'
        '  \"tool_calls_made\": [\"predict_resistance_escape\"],\n'
        '  \"wall_clock_ms\": 850\n'
        "}\n\n"
        "STANDARD SUB-AGENTS:\n"
        "  - Editor               : SMILES sanitization + named transforms\n"
        "  - Critic               : 8-dimension review\n"
        "  - Red-Team             : adversarial mutation + escape prediction\n"
        "  - Resistance-Forecaster: predict where resistance emerges in 24-36 mo\n"
        "  - Manufacturing-Eval   : stereo + scale + cost trade-offs\n"
        "  - Clinical-Positioning : indication + dose + route reasoning\n"
        "  - Literature-Grounding : search_literature + cite recent papers\n"
        "  - Confidence-Calibrator: when to trust predictors, when to verify\n\n"
        "EXAMPLE DISPATCH:\n"
        "  Designer needs a quick novelty check before handoff. It dispatches a Novelty sub-agent:\n"
        "  {\n"
        '    \"type\": \"dispatch\",\n'
        '    \"parent_agent\": \"designer\",\n'
        '    \"subagent_role\": \"critic_novelty\",\n'
        '    \"scoped_task\": \"compute Tanimoto of candidate vs known-antibiotic index; report top-3 matches\",\n'
        '    \"scoped_inputs\": {\"smiles\": \"OC(=O)[C@H]1...\"},\n'
        '    \"allowed_tools\": [\"find_similar_drugs\", \"compare_molecules\"],\n'
        '    \"timeout_ms\": 5000\n'
        "  }\n\n"
        "DECISION: scoped sub-agents for context discipline + parallelism. Always pass allowed_tools to limit blast radius."
    )

    return {
        "task": "teacher_arch_subagent_dispatcher",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# P. confidence_convention
# ============================================================================
def trace_confidence_convention(rng: random.Random) -> dict:
    user = "How does Lysos report confidence and uncertainty? What's the convention?"

    asst = (
        "[Confidence-Reporting-Convention]:\n\n"
        "Every Lysos tool that emits a prediction also emits a confidence score in [0, 1]. Agents must propagate these scores in their outputs and use them in downstream decision-making.\n\n"
        "TOOL-LEVEL CONFIDENCE:\n"
        "  predict_mic_pathogen     → confidence ∈ [0, 1] from XGBoost + scaffold-CV proximity\n"
        "  predict_admet            → confidence ∈ [0, 1] from descriptor-domain coverage\n"
        "  predict_hemolysis        → confidence ∈ [0, 1] from training-distribution match\n"
        "  predict_binding_affinity → confidence ∈ [0, 1] from energy-function decomposition\n"
        "  predict_complex_structure → ipTM ∈ [0, 1] (Boltz-2 native confidence)\n"
        "  estimate_synth_cost       → confidence ∈ [0, 1] from route-finder agreement\n"
        "  predict_resistance_escape → red_team_verdict ∈ {low, moderate, high} mapped to [0.25, 0.5, 0.85] confidence-weighted\n\n"
        "AGENT-LEVEL DECISIONS:\n"
        "  Tier 1 (≥0.80): TRUST. Proceed without verification.\n"
        "  Tier 2 (0.60-0.80): CAUTIOUS TRUST. One orthogonal verification required.\n"
        "  Tier 3 (0.40-0.60): LOW TRUST. Two orthogonal verifications + flag for review.\n"
        "  Tier 4 (<0.40): NO TRUST. Wet-lab only.\n\n"
        "PROPAGATION:\n"
        "  Composite confidence = geometric mean of per-pillar confidences. \n"
        "  E.g., MIC conf 0.8 + ADMET conf 0.7 + hemolysis conf 0.85 → composite_conf = (0.8 × 0.7 × 0.85)^(1/3) ≈ 0.78.\n\n"
        "OUTPUT CONVENTION:\n"
        "  Every numeric prediction comes with its confidence in the same JSON object:\n"
        "    {\"log_mic_predicted\": -0.42, \"mic_ug_ml\": 0.38, \"confidence\": 0.78}\n"
        "  Composite scores carry their propagated confidence:\n"
        "    {\"composite\": 0.74, \"confidence\": 0.71, \"weakest\": \"novelty\", \"weakest_conf\": 0.55}\n\n"
        "AGENT-OUTPUT FORMAT:\n"
        "  When Designer reports a candidate, it includes confidence-aware hedges:\n"
        "  PROPOSAL: <SMILES>\n"
        "  EXPECTED MIC: 0.4 ± 0.2 µg/mL (confidence 0.78)\n"
        "  CAVEAT: hemolysis prediction is in Tier 2 confidence; recommend in vitro confirmation before commit.\n\n"
        "MISSING-CONFIDENCE HANDLING:\n"
        "  If a tool returns no confidence field, Designer assumes 0.5 (low) and downgrades the candidate accordingly.\n\n"
        "DECISION: confidence is propagated through every layer + dictates verification depth."
    )

    return {
        "task": "teacher_arch_confidence_convention",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# Q. tool_error_codes
# ============================================================================
def trace_tool_error_codes(rng: random.Random) -> dict:
    tool_choice = rng.choice(TOOLS_FULL)
    cat, name, lat, inp, out = tool_choice

    user = f"What error codes can {name} return, and how should Designer handle each?"

    asst = (
        f"[Tool-Error-Codes — {name}]:\n\n"
        f"Tool: {name} ({cat}, expected_duration_ms={lat})\n"
        f"Input schema: {inp}\n"
        f"Output schema: {out}\n\n"
        f"ERROR CODES:\n"
        f"  INVALID_INPUT          — input schema validation failed\n"
        f"    Recovery: Editor canonicalize SMILES; retry once\n"
        f"  TIMEOUT                — exceeded {lat * 5}ms\n"
        f"    Recovery: split batch in half; retry; if still TIMEOUT → escalate\n"
        f"  SERVICE_UNAVAILABLE    — backend service down\n"
        f"    Recovery: exponential backoff retry up to 3 times; then escalate\n"
    )

    if "predict" in name or "score" in name:
        asst += (
            f"  MODEL_UNCERTAIN        — confidence < 0.4\n"
            f"    Recovery: Designer marks the candidate as Tier 4; require wet-lab\n"
            f"  OUT_OF_DOMAIN          — input outside training distribution\n"
            f"    Recovery: skip this tool for this candidate; use orthogonal tools\n"
        )
    if "synthesis" in name:
        asst += (
            f"  NO_ROUTE_FOUND         — AizynthFinder couldn't find a viable retrosynthesis\n"
            f"    Recovery: scaffold_hop to a more conventional core; retry\n"
        )
    if "complex_structure" in name or "dock" in name:
        asst += (
            f"  POSE_NOT_CONVERGED     — sampling didn't converge\n"
            f"    Recovery: increase n_poses; or fall back to simpler scoring (predict_binding_affinity)\n"
            f"  TARGET_NOT_FOUND       — PDB id not in mirror\n"
            f"    Recovery: find_target_structure(pathogen) for valid PDB\n"
        )

    asst += (
        f"\nERROR ENVELOPE FORMAT:\n"
        f"{{\n"
        f'  \"tool\": \"{name}\",\n'
        f'  \"error_code\": \"<one of above>\",\n'
        f'  \"detail\": \"...\",\n'
        f'  \"retry_count\": <n>,\n'
        f'  \"recovery_attempted\": [\"<step1>\"]\n'
        f"}}\n\n"
        f"DECISION: each tool has a known error vocabulary; Designer routes by error code, not free-text."
    )

    return {
        "task": "teacher_arch_tool_error_codes",
        "tool": name,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# R. system_self_description
# ============================================================================
def trace_system_self_description(rng: random.Random) -> dict:
    user = "What is Lysos? Explain end-to-end."

    asst = (
        "[Lysos-Self-Description]:\n\n"
        "Lysos is an open-source generative drug-design system specialized for antimicrobial resistance (AMR). It combines a Gemma-4-based LLM, a 12-component reward stack, a 25-tool Workbench, and a multi-agent orchestrator on MI300X hardware.\n\n"
        "MISSION:\n"
        "  Design novel antibacterial candidates against the 8 WHO-priority pathogens (MRSA, Mtb, EColi-CRE, KpneuCRE, Abaum, Paer, VRE, NGono) — pivoting AROUND existing first-line therapy classes to reduce cross-resistance pressure.\n\n"
        "TECHNICAL STACK:\n"
        "  Base model:       google/gemma-4-31b-it (locked)\n"
        "  Embeddings:       EmbeddingGemma 300m (novelty + RAG) + Gemini Embedding 2 (3072d Matryoshka)\n"
        "  Pipeline:         3-stage SFT + RL\n"
        "    Stage 1: TxGemma-4 base (replicate TxGemma recipe on Gemma 4)\n"
        "    Stage 2: AMR specialization SFT on amr-stage2-pro-v7 (~320K rows)\n"
        "    Stage 3: GRPO RL with 12-component reward stack on amr-rl-prompts-v3 (12K prompts)\n"
        "  Hardware:         8× MI300X for Stage 1, 1× MI300X for Stages 2-3\n"
        "  Budget:           $300 ceiling, $170-240 expected for full pipeline\n\n"
        "AGENT TEAM:\n"
        "  Designer    — proposes candidates, calls panel tools, iterates\n"
        "  Critic      — adversarial 8-dimension review\n"
        "  Strategist  — campaign allocation + stage gates + handoffs\n"
        "  Editor      — SMILES sanitization + named transforms\n"
        "  + scoped sub-agents (Red-Team, Resistance-Forecaster, Manufacturing-Eval, Clinical-Positioning, Literature-Grounding, Confidence-Calibrator, Novelty-Checker)\n\n"
        "TOOLS:\n"
        "  25 tools across 6 categories (amr, scoring, structural, generative, knowledge, sandbox)\n\n"
        "DATA:\n"
        "  Sources: ChEMBL, DrugBank Open, NPAtlas, DBAASP, DRAMP, DrugCentral, PubChem, COADD, TDC, CARD\n"
        "  Curated: 39,590 cleaned chemistry rows + 8,847 peptide actives + 320K agentic-trace rows\n"
        "  HF Hub: rahul24raj/lysos-amr-stage2-pro-v7, rahul24raj/lysos-rl-prompts-v3\n\n"
        "EVAL:\n"
        "  7 quantitative metrics: chem_validity, novelty_tanimoto, MIC_RMSE, ADMET_pass, tool_call_accuracy, refusal_robustness, reasoning_faithfulness\n"
        "  Locked configs in eval/run_all.py + EVAL_CONFIG\n\n"
        "DEPLOYMENT:\n"
        "  vLLM (rocm/vllm:latest) on MI300X\n"
        "  Lysos Workbench frontend (FastAPI + React/Vite)\n"
        "  HF Space (Docker SDK) for public demo\n\n"
        "DECISION: Lysos is the antimicrobial drug-design counterpart to TxGemma — specialized + open + accountable."
    )

    return {
        "task": "teacher_arch_system_self_description",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# S. api_contract
# ============================================================================
def trace_api_contract(rng: random.Random) -> dict:
    tool_choice = rng.choice(TOOLS_FULL)
    cat, name, lat, inp, out = tool_choice

    user = f"Show me the full API contract for {name}: request shape, response shape, error responses, idempotency."

    asst = (
        f"[API-Contract — {name}]:\n\n"
        f"Tool: {name} ({cat}, expected_duration_ms={lat})\n\n"
        f"REQUEST SHAPE (JSON):\n"
        f"{{\n"
        f'  \"tool_name\": \"{name}\",\n'
        f'  \"input\": {{ /* schema: {inp} */ }},\n'
        f'  \"request_id\": \"<uuid v4>\",\n'
        f'  \"timeout_ms\": {lat * 3},\n'
        f'  \"trace_context\": {{ \"campaign_id\": \"...\", \"candidate_id\": \"...\", \"agent\": \"designer\" }}\n'
        f"}}\n\n"
        f"RESPONSE SHAPE (success):\n"
        f"{{\n"
        f'  \"request_id\": \"<echoed>\",\n'
        f'  \"tool_name\": \"{name}\",\n'
        f'  \"status\": \"ok\",\n'
        f'  \"output\": {{ /* schema: {out} */ }},\n'
        f'  \"backend\": \"<implementation backend name>\",\n'
        f'  \"wall_clock_ms\": <int>,\n'
        f'  \"cached\": <bool>\n'
        f"}}\n\n"
        f"RESPONSE SHAPE (error):\n"
        f"{{\n"
        f'  \"request_id\": \"<echoed>\",\n'
        f'  \"tool_name\": \"{name}\",\n'
        f'  \"status\": \"error\",\n'
        f'  \"error_code\": \"INVALID_INPUT | TIMEOUT | SERVICE_UNAVAILABLE | MODEL_UNCERTAIN\",\n'
        f'  \"error_detail\": \"...\",\n'
        f'  \"retry_after_ms\": <int>\n'
        f"}}\n\n"
        f"IDEMPOTENCY:\n"
        f"  All Lysos tools are read-only / idempotent.\n"
        f"  Same input → same output (modulo non-deterministic samplers, which are seeded).\n"
        f"  Safe to retry without side effects.\n"
        f"\n"
        f"CACHING:\n"
        f"  Inputs are content-hashed (SHA-256 of input JSON).\n"
        f"  Cached outputs in Redis with TTL = 24h.\n"
        f"  Designer can pass `force_recompute: true` to bypass cache.\n"
        f"\n"
        f"AUTH:\n"
        f"  All tool calls require an agent JWT (signed by Strategist) with allowed-tools claim.\n"
        f"  Designer's JWT typically allows: all `amr` + `scoring` + `generative` + most `knowledge`.\n"
        f"  Editor's JWT allows: only `transform_structure` + `compare_molecules`.\n"
        f"\n"
        f"OBSERVABILITY:\n"
        f"  Every call emits an OpenTelemetry span with: tool_name, input_hash, output_hash, "
        f"  wall_clock_ms, agent, campaign_id, candidate_id. Aggregated in the Workbench analytics.\n\n"
        f"DECISION: tool calls are typed JSON envelopes with idempotency + caching + auth + observability."
    )

    return {
        "task": "teacher_arch_api_contract",
        "tool": name,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# T. sprint_planning
# ============================================================================
def trace_sprint_planning(rng: random.Random) -> dict:
    user = "How does Lysos plan and execute a sprint?"

    asst = (
        "[Sprint-Planning-Workflow]:\n\n"
        "Lysos sprints are 2-week design + eval cycles that produce a discrete deliverable (new dataset version, reward-stack change, model checkpoint, eval result).\n\n"
        "SPRINT STRUCTURE:\n"
        "  Day 1     : Sprint planning meeting (decide deliverables, allocate compute)\n"
        "  Days 2-3  : Data prep (CPU work)\n"
        "  Days 4-9  : Training + iteration (GPU work)\n"
        "  Days 10-12: Eval + analysis\n"
        "  Days 13-14: Retrospective + write-up\n\n"
        "PLANNING ARTIFACTS:\n"
        "  vault/plans/active/YYYY-MM-DD-<topic>.md (Obsidian-tracked)\n"
        "    Contains: sprint goals, design decisions, tool choices, success criteria\n"
        "  vault/implementation-logs/YYYY-MM-DD-session-log.md\n"
        "    Live log of every session, every commit, every decision\n"
        "  vault/plans/completed/<topic>.md after sprint ends\n\n"
        "DELIVERABLES (per sprint type):\n"
        "  DATA SPRINT:    new dataset version (pro-vN+1) + smoke tests + push to HF\n"
        "  REWARD SPRINT:  new reward components + calibration sweeps + config update\n"
        "  TRAIN SPRINT:   new model checkpoint + eval baseline + comparison to prior\n"
        "  EVAL SPRINT:    new eval metric + locked config + leaderboard update\n"
        "  DEPLOY SPRINT:  new vLLM container + Workbench wire-up + HF Space update\n\n"
        "GO/NO-GO CRITERIA:\n"
        "  At day 10 (eval phase start), the sprint either advances to write-up "
        "  (deliverable hits its success criterion) or rolls back and re-plans. "
        "  Rolled sprints write a retrospective explaining the failure.\n\n"
        "CONTINUOUS COMMITS:\n"
        "  Every meaningful unit of work gets committed + pushed to GitHub. "
        "  No batched commits. NO `Co-Authored-By` attribution.\n\n"
        "MEMORY DISCIPLINE:\n"
        "  Plans are NEVER deleted (persistent context).\n"
        "  Session logs append-only.\n"
        "  Retrospectives capture what was tried and what worked.\n\n"
        "DECISION: 2-week sprints, vault-tracked, continuous commits, explicit go/no-go gates."
    )

    return {
        "task": "teacher_arch_sprint_planning",
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# Driver
# ============================================================================
GENERATORS = {
    "designer_role":           trace_agent_role_designer,
    "critic_role":             trace_agent_role_critic,
    "strategist_role":         trace_agent_role_strategist,
    "editor_role":             trace_agent_role_editor,
    "handoff_protocol":        trace_agent_handoff_protocol,
    "tool_registry":           trace_tool_registry_orientation,
    "tool_decision_tree":      trace_tool_decision_tree,
    "candidate_ledger":        trace_candidate_ledger_format,
    "state_machine":           trace_state_machine,
    "stage_gate_criteria":     trace_stage_gate_criteria,
    "intervention_handler":    trace_intervention_handler,
    "error_escalation":        trace_error_escalation,
    "branch_merge":            trace_branch_merge,
    "pipeline_map":            trace_end_to_end_pipeline,
    "subagent_dispatcher":     trace_subagent_dispatcher,
    "confidence_convention":   trace_confidence_convention,
    "tool_error_codes":        trace_tool_error_codes,
    "system_self_description": trace_system_self_description,
    "api_contract":            trace_api_contract,
    "sprint_planning":         trace_sprint_planning,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_per_category", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0xCAFE_BABE_42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    if OUT.exists(): OUT.unlink()
    counts = {}
    n_total = 0
    with open(OUT, "a") as f:
        for label, fn in GENERATORS.items():
            for _ in range(args.n_per_category):
                row = fn(rng)
                f.write(json.dumps(row) + "\n")
                counts[label] = counts.get(label, 0) + 1
                n_total += 1

    print(f"\nGenerated {n_total:,} architecture / system-awareness traces")
    for k, v in counts.items():
        print(f"  {k:30s} {v}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
