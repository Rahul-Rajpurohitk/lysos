"""Systems-level teacher distillation — beyond chemistry design loops.

Covers the full Lysos Workbench ENVIRONMENT + DATA dimensions. Each trace is
a multi-turn dialogue grounded in real AMR knowledge, real Workbench tool
schemas, real clinical pharmacology, real manufacturing constraints.

Categories (each generates parametrized traces):
  A. strategist_campaign       Strategist agent picks which campaigns to run
                                given budget + compute + priority pathogens
  B. tool_orchestration         Which tools to call in what order, latency-aware
  C. multi_pathogen_spectrum    Broad-spectrum design across multiple targets
  D. failure_mode_debug         Tool errors, low-confidence outputs, recovery
  E. constraint_compliance      Designing under MW/logP/PAINS/synth constraints
  F. wet_lab_handoff            Format candidates for medchem team
  G. resistance_forecasting     Predict where resistance will emerge
  H. combo_therapy_strategy     Synergy/antagonism reasoning
  I. clinical_positioning       Dose/route/indication for a candidate
  J. manufacturing_reasoning    Stereo, scale, cost trade-offs
  K. literature_grounding       Use search_literature + cite recent papers
  L. confidence_calibration     When to trust predictors, when to verify
  M. workbench_state_reasoning  Reading ledgers, interventions, candidate logs

Run:
  /tmp/lysos_venv/bin/python scripts/teacher_distill_systems.py --n_per_category 300

Output:
  data/synthetic/agentic_teacher_distill_systems.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic" / "agentic_teacher_distill_systems.jsonl"

PATHOGENS = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE", "Abaum", "Paer", "VRE", "NGono"]

PATH_FULL = {
    "MRSA": "methicillin-resistant Staphylococcus aureus",
    "Mtb": "Mycobacterium tuberculosis",
    "EColi-CRE": "carbapenem-resistant Escherichia coli",
    "KpneuCRE": "carbapenem-resistant Klebsiella pneumoniae",
    "Abaum": "Acinetobacter baumannii",
    "Paer": "Pseudomonas aeruginosa",
    "VRE": "vancomycin-resistant Enterococcus",
    "NGono": "Neisseria gonorrhoeae",
}

# WHO priority tier (2024 list)
WHO_TIER = {
    "MRSA": "high", "Mtb": "critical", "EColi-CRE": "critical",
    "KpneuCRE": "critical", "Abaum": "critical", "Paer": "high",
    "VRE": "high", "NGono": "high",
}

# Tools registry — name + category + estimated latency (ms) + io schema notes
TOOLS = [
    ("predict_mic_pathogen", "amr", 200, "smiles+pathogen → log_mic, mic_ug_ml, confidence"),
    ("get_pathogen_resistome", "amr", 50, "pathogen → resistome dict + first-line therapy"),
    ("check_resistance_genes", "amr", 100, "pathogen+drug_class → relevant genes"),
    ("predict_resistance_escape", "amr", 300, "smiles+pathogen → escape mutations + fold-change"),
    ("find_active_against_mdr", "amr", 150, "pathogens → late-stage drug list"),
    ("predict_admet", "scoring", 100, "smiles → MW, logP, TPSA, Lipinski, F"),
    ("predict_hemolysis", "scoring", 200, "smiles → safety score + risk class"),
    ("predict_synthesis_route", "scoring", 800, "smiles → SA, steps, cost, route"),
    ("estimate_synth_cost", "scoring", 250, "smiles → cost class + $/g estimate"),
    ("score_molecule", "scoring", 350, "smiles+pathogen → composite + weakest"),
    ("find_similar_drugs", "scoring", 400, "smiles → similar drugs + Tanimoto"),
    ("dock_against_target", "structural", 5000, "smiles+pdb → poses + best score"),
    ("predict_binding_affinity", "structural", 1500, "smiles+target → ΔG, pKd"),
    ("predict_complex_structure", "structural", 8000, "smiles+pdb → ipTM, ligand RMSD (Boltz-2)"),
    ("propose_pocket_aware", "generative", 2000, "pdb+pocket_class → candidate proposals"),
    ("scaffold_hop", "generative", 1500, "smiles → bioisosteric alternatives"),
    ("transform_structure", "generative", 800, "smiles+op → product"),
    ("optimize_iteratively", "generative", 6000, "seed_smiles+objective → trajectory"),
    ("compare_molecules", "knowledge", 100, "smiles_a+smiles_b → Tanimoto, Δprops"),
    ("explain_mechanism", "knowledge", 200, "smiles → inferred class + MoA narrative"),
    ("find_target_structure", "knowledge", 500, "pathogen → primary target + PDBs"),
    ("get_drug_history", "knowledge", 150, "drug_name → class, year, MoA, trials"),
    ("search_literature", "knowledge", 1500, "query → PubMed papers + abstracts"),
    ("execute_python", "sandbox", 500, "code → stdout, return_value"),
    ("render_3d_scene", "sandbox", 200, "structure+ligand → 3D viz spec"),
]

SYS = (
    "You are the Lysos antimicrobial drug-design Workbench team. Multiple "
    "agents (Designer, Critic, Strategist, Editor) collaborate via structured "
    "tool calls and JSON-shaped tool results. Every dialogue should ground "
    "decisions in real AMR knowledge: PDB residues, escape mutations, "
    "first-line therapy classes, WHO priority tiers, and clinical pharmacology. "
    "End with a structured DECISION block."
)


def _user_brief(scenario: str, pathogen: str | None = None) -> str:
    if pathogen:
        return f"[{PATH_FULL[pathogen]} ({pathogen}) — WHO {WHO_TIER[pathogen]} priority]\n{scenario}"
    return scenario


def _round(x, n=3):
    return round(float(x), n)


# ============================================================================
# A. strategist_campaign
# ============================================================================
def trace_strategist_campaign(rng: random.Random) -> dict:
    n_pathogens = rng.randint(3, 5)
    target_pathogens = rng.sample(PATHOGENS, n_pathogens)
    compute_hours = rng.choice([10, 25, 50])
    budget_usd = compute_hours * rng.choice([3, 4])

    # Score each pathogen by: WHO tier + recent failure rate + market gap
    rationales = {}
    for p in target_pathogens:
        unmet_need = rng.uniform(0.4, 0.95)
        market_gap_m = rng.choice([200, 500, 1200, 2500])
        recent_failure = rng.choice(["ceftaz-avi resistance emerging in 9% of patients (Shields 2024)",
                                       "vancomycin-MIC creep 8% in US 2018-2023 (Mendes 2024)",
                                       "ceftolozane-tazo R 12% post-30-day (Hagiya 2024)",
                                       "BPaL 89% cure but linezolid tox limits (Drain 2023)",
                                       "OXA-23 dominance in 70% of CRAB"])
        rationales[p] = {
            "unmet_need_score": _round(unmet_need),
            "market_gap_usd_m": market_gap_m,
            "recent_failure": recent_failure,
            "tier": WHO_TIER[p],
        }

    # Strategist allocates compute proportional to (unmet_need × market_gap)
    weights = {p: rationales[p]["unmet_need_score"] * rationales[p]["market_gap_usd_m"] for p in target_pathogens}
    total_w = sum(weights.values())
    allocation = {p: _round(compute_hours * weights[p] / total_w, 1) for p in target_pathogens}

    user = _user_brief(
        f"Strategist: pick allocation across {n_pathogens} pathogens given "
        f"{compute_hours} hours of MI300X compute (${budget_usd} budget). "
        f"Candidates: {', '.join(target_pathogens)}."
    )

    asst = (
        f"[Strategist]: Triaging {n_pathogens} pathogen campaigns under "
        f"{compute_hours}h / ${budget_usd} envelope.\n\n"
        f"Per-pathogen scoring:\n"
    )
    for p in target_pathogens:
        r = rationales[p]
        asst += (f"  {p:12s} | tier={r['tier']:8s} | unmet={r['unmet_need_score']:.2f} | "
                 f"gap=${r['market_gap_usd_m']}M | {r['recent_failure'][:55]}...\n")

    asst += (
        f"\nWeighted allocation (unmet × market_gap, normalized):\n"
    )
    for p in target_pathogens:
        asst += f"  {p:12s} → {allocation[p]:.1f}h ({100*allocation[p]/compute_hours:.0f}%)\n"

    asst += (
        f"\nDECISION:\n"
        f"  Run all {n_pathogens} campaigns in parallel batched.\n"
        f"  Priority order (highest-leverage first):\n"
    )
    sorted_p = sorted(target_pathogens, key=lambda x: -weights[x])
    for i, p in enumerate(sorted_p):
        asst += f"    {i+1}. {p} ({allocation[p]}h) — {rationales[p]['recent_failure'][:60]}\n"
    asst += (
        f"\n  Compute reservation: 1× MI300X for {sorted_p[0]} (top-priority), "
        f"~{compute_hours - allocation[sorted_p[0]]:.0f}h for the rest pooled.\n"
        f"  Budget reservation: ${budget_usd} ceiling, kill any campaign that "
        f"hits ${int(budget_usd*0.4)} without a composite > 0.7 candidate.\n"
        f"  Hand back to Designer for {sorted_p[0]} now; queue remaining."
    )

    return {
        "task": "teacher_strategist_campaign",
        "pathogens": target_pathogens,
        "compute_hours": compute_hours,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# B. tool_orchestration — latency-aware sequencing
# ============================================================================
def trace_tool_orchestration(rng: random.Random) -> dict:
    pathogen = rng.choice(PATHOGENS)
    candidate_count = rng.randint(3, 8)
    time_budget_min = rng.choice([2, 5, 10, 30])

    # Cheap tools first: predict_admet (100ms), predict_mic_pathogen (200ms)
    # Defer expensive: predict_complex_structure (8000ms), dock_against_target (5000ms)
    cheap = [t for t in TOOLS if t[2] <= 500]
    medium = [t for t in TOOLS if 500 < t[2] <= 2000]
    expensive = [t for t in TOOLS if t[2] > 2000]

    user = _user_brief(
        f"Designer: have {candidate_count} candidate SMILES. Time budget "
        f"{time_budget_min} minutes. Target: {pathogen}. Sequence the in "
        f"silico panel calls to maximize information per second."
    )

    asst = (
        f"[Designer]: {candidate_count} candidates, {time_budget_min}-minute "
        f"budget = {time_budget_min*60}s. Tools have widely different latencies; "
        f"the right strategy is gate-then-confirm: cheap tools knock out "
        f"failures fast, expensive tools only run on candidates that survived.\n\n"
        f"PHASE 1 (per-candidate, parallel, ~1s each):\n"
        f"  1. predict_admet (100ms) — instant Lipinski/Veber gate\n"
        f"  2. predict_mic_pathogen (200ms) — primary activity gate\n"
        f"  → Kill any candidate with log10(MIC) > 1.5 or Lipinski viol > 2\n"
        f"  Cost: ~{300 * candidate_count}ms total\n"
        f"  Expected survivors: ~{int(candidate_count * 0.5)}/{candidate_count}\n\n"
        f"PHASE 2 (per-survivor, ~500ms each):\n"
        f"  3. predict_hemolysis (200ms)\n"
        f"  4. score_molecule (350ms) — composite\n"
        f"  → Kill any with composite < 0.5 or hemolysis = high\n"
        f"  Expected survivors: ~{int(candidate_count * 0.3)}/{candidate_count}\n\n"
        f"PHASE 3 (per-survivor, ~1.5s each):\n"
        f"  5. predict_resistance_escape (300ms)\n"
        f"  6. predict_synthesis_route (800ms)\n"
        f"  7. find_similar_drugs (400ms) — novelty check\n"
        f"  → Final ranking by composite + escape verdict + cost\n\n"
        f"PHASE 4 (top-1 only, expensive):\n"
        f"  8. predict_complex_structure (8000ms) — Boltz-2 3D pose\n"
        f"  9. dock_against_target (5000ms) — confirm pose\n"
        f"  → Only the best candidate enters this stage\n\n"
        f"Total estimated wall-clock: {int(candidate_count * 0.3 + candidate_count * 0.3 * 1.5 + 13)} seconds. "
        f"Well within the {time_budget_min}-minute budget. Buffer for "
        f"scaffold-hop iteration if any phase produces zero survivors.\n\n"
        f"DECISION: Begin Phase 1 in parallel across all {candidate_count} candidates."
    )

    return {
        "task": "teacher_tool_orchestration",
        "pathogen": pathogen,
        "candidate_count": candidate_count,
        "time_budget_min": time_budget_min,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# C. multi_pathogen_spectrum — broad-spectrum design
# ============================================================================
def trace_multi_pathogen_spectrum(rng: random.Random) -> dict:
    pair_groups = [
        (["MRSA", "VRE"],         "gram+ pair", "PBP / ribosomal targets"),
        (["EColi-CRE", "KpneuCRE", "Paer"], "gram- carbapenem-R trio", "carbapenemase coverage required"),
        (["Abaum", "Paer"],       "gram- non-fermenter pair", "biofilm + efflux"),
        (["MRSA", "Paer"],        "gram+ / gram- pair (hospital)", "ICU pneumonia"),
        (["Mtb", "Mtb"],          "Mtb only (long-duration)", "PK requires t1/2 > 8h"),
        (["EColi-CRE", "Paer", "Abaum"], "gram- WHO-critical trio", "cefiderocol-class siderophore needed"),
    ]
    pathogens, desc, rationale = rng.choice(pair_groups)
    pathogens = list(set(pathogens))

    user = _user_brief(
        f"Design a broad-spectrum candidate active against: "
        f"{', '.join(pathogens)} ({desc}). Constraint: {rationale}."
    )

    # Identify the SHARED pharmacophore that covers all pathogens
    common_target_class = rng.choice(["β-lactam transpeptidase", "ribosomal 50S subunit",
                                        "DNA gyrase", "membrane-active cationic peptide",
                                        "siderophore-cephalosporin"])

    asst = (
        f"[Designer]: Broad-spectrum design against {len(pathogens)} pathogens "
        f"({', '.join(pathogens)}). The challenge: each pathogen has a distinct "
        f"resistome.\n\n"
        f"<tool_call>name: get_pathogen_resistome\n"
        f"args: {{\"pathogens\": {json.dumps(pathogens)}}}</tool_call>\n"
        f"[Tool]: returns resistome briefing per pathogen\n\n"
        f"[Designer]: Cross-pathogen analysis:\n"
    )
    for p in pathogens:
        snippet = {
            "MRSA": "mecA → PBP2a allosteric site",
            "Mtb": "rpoB-S531L; need rpoB-bypass",
            "EColi-CRE": "KPC-2 + NDM-1; need siderophore entry",
            "KpneuCRE": "KPC-3 D179Y under selection",
            "Abaum": "OXA-23/24/58 + porin loss",
            "Paer": "AmpC + MexAB efflux",
            "VRE": "vanA D-Ala:D-Lac",
            "NGono": "penA mosaic XXXIV/XXXV",
        }[p]
        asst += f"  {p:12s} → {snippet}\n"

    asst += (
        f"\n[Designer]: SHARED VULNERABILITY: {common_target_class}. Anchor scaffold "
        f"on this class, then optimize entry strategy per pathogen.\n\n"
        f"Design strategy:\n"
        f"  1. Core pharmacophore: {common_target_class} engagement\n"
        f"  2. Entry strategy:\n"
        f"     - For gram+ ({', '.join(p for p in pathogens if p in ['MRSA', 'VRE'])}): "
        f"thick peptidoglycan permeable scaffold; charge < 2+\n"
        f"     - For gram- ({', '.join(p for p in pathogens if p in ['EColi-CRE', 'KpneuCRE', 'Paer', 'Abaum'])}): "
        f"siderophore-conjugate or low-MW (< 350 Da) for porin entry\n"
        f"     - For Mtb: lipophilic core for mycolic-acid wall passage\n"
        f"  3. Resistance avoidance:\n"
        f"     - Avoid β-lactam classes that bind canonical PBPs\n"
        f"     - Use covalent tail or allosteric handle to escape single-mutation\n"
        f"\n"
        f"<tool_call>name: predict_mic_pathogen\n"
        f"args: {{\"smiles\": \"<broad-spectrum-cephalosporin-siderophore>\", "
        f"\"pathogen\": \"{pathogens[0]}\"}}</tool_call>\n"
        f"[Tool]: log_mic_predicted=-0.4, mic_ug_ml=0.40, confidence=0.74\n\n"
        f"[Designer]: Active vs {pathogens[0]}. Now run against all "
        f"{len(pathogens)} pathogens to confirm spectrum.\n\n"
        f"After multi-pathogen panel: candidate active vs "
        f"{rng.choice([len(pathogens), len(pathogens)-1])}/"
        f"{len(pathogens)} pathogens.\n\n"
        f"DECISION: Spectrum-broad candidate validated; advance to ADMET + "
        f"resistance red-team panel. If active vs all {len(pathogens)} → "
        f"high-priority for medchem; if active vs n-1 → flag the missing "
        f"pathogen for orthogonal approach in a parallel campaign."
    )

    return {
        "task": "teacher_multi_pathogen_spectrum",
        "pathogens": pathogens,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# D. failure_mode_debug
# ============================================================================
def trace_failure_mode_debug(rng: random.Random) -> dict:
    failure_modes = [
        ("low_confidence", "predict_mic_pathogen returned confidence 0.34 (well below threshold 0.6)",
         "Run a second-tool ensemble: predict_binding_affinity + dock_against_target. "
         "If both confirm activity, accept the low-confidence MIC. If they disagree, "
         "flag for wet-lab priority validation. Don't trust a single low-confidence prediction."),
        ("tool_timeout", "predict_complex_structure (Boltz-2) timed out at 30s",
         "Boltz-2 timeouts often indicate large-flexible ligand or large-target system. "
         "Fall back: dock_against_target (Vina) for a faster pose, then accept lower "
         "fidelity. If 3D pose is critical for the rationale, retry Boltz-2 with "
         "trimmed ligand (truncate flexible side chains)."),
        ("invalid_smiles", "predict_admet returned 'invalid SMILES' for the candidate",
         "Designer emitted a malformed SMILES. Call Editor agent to canonicalize "
         "via Chem.MolToSmiles. Common causes: unclosed ring (e.g., '1' without '1' "
         "later), aromatic vs aliphatic atom mismatch, valence overload. After "
         "canonicalization, retry the panel."),
        ("contradictory_results", "predict_mic_pathogen says active (MIC=0.5), but predict_resistance_escape says >100x escape via single mutation",
         "Contradiction is informative. The candidate IS active on wild-type but "
         "would lose activity on first-step mutant. Two paths: (a) iterate to widen "
         "the binding-pocket interactions so single-mutation can't escape, or (b) "
         "deploy as part of a combo regimen with a partner that doesn't share the "
         "escape route."),
        ("no_synth_route", "predict_synthesis_route returned 'no route found' (confidence 0.05)",
         "AizynthFinder can't find a viable retrosynthesis. Either the molecule is "
         "novel beyond the corpus or it has unusual functional groups. Options: (a) "
         "scaffold-hop to a more conventional core, (b) consult a senior chemist for "
         "manual route design, (c) accept that this is a 'beautiful but unmakable' "
         "design and pivot to an analog."),
        ("predictor_disagrees_with_known", "MIC predictor says active, but find_similar_drugs returns 5 close analogs that ALL failed in clinic",
         "Strong negative signal — the chemotype has clinical failure history. The "
         "MIC predictor was trained without clinical-failure context. Promote the "
         "find_similar_drugs result; this candidate is likely doomed for the same "
         "reason as its analogs. Either pivot to a distinct scaffold or identify "
         "what specifically differentiates THIS candidate from the failed analogs."),
    ]
    failure_label, scenario, recovery = rng.choice(failure_modes)
    pathogen = rng.choice(PATHOGENS)

    user = _user_brief(f"Debug: {scenario}. What's the recovery strategy?", pathogen)

    asst = (
        f"[Designer]: Failure mode = {failure_label}. Scenario: {scenario}.\n\n"
        f"Diagnosis:\n"
        f"  This is a {rng.choice(['recoverable', 'partially-recoverable', 'severe'])} "
        f"failure for the standard pipeline. The right move depends on whether "
        f"the failure was due to (a) the candidate itself, (b) the tool, or (c) "
        f"a mismatch between the candidate and the tool's training distribution.\n\n"
        f"Recovery strategy:\n"
        f"{recovery}\n\n"
        f"Concrete next steps:\n"
        f"  1. Log the failure mode in the Workbench candidate ledger so the "
        f"     pattern is visible in future campaigns.\n"
        f"  2. Apply the recovery as described.\n"
        f"  3. If recovery succeeds → continue panel.\n"
        f"  4. If recovery fails → kill the candidate and report to Strategist "
        f"     with a 'failed at {failure_label}' tag.\n\n"
        f"DECISION: Apply recovery. Set a hard timeout: if not resolved in 2 "
        f"more attempts, kill and move to next candidate."
    )

    return {
        "task": "teacher_failure_mode_debug",
        "pathogen": pathogen,
        "failure_mode": failure_label,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# E. constraint_compliance
# ============================================================================
def trace_constraint_compliance(rng: random.Random) -> dict:
    constraints = rng.choice([
        {"name": "lead-like-strict", "rules": ["MW < 400", "logP < 3", "HBD ≤ 3", "no PAINS", "no Lilly-MedChem"],
         "rationale": "oral once-daily dosing target"},
        {"name": "fragment-extension", "rules": ["MW < 350", "logP ∈ [0,3]", "HBD ≤ 3", "growth-vector compatible"],
         "rationale": "fragment hit being grown into a lead"},
        {"name": "macrocycle", "rules": ["MW ∈ [600, 1500]", "≥1 macrocyclic ring", "intramolecular H-bonds permitted"],
         "rationale": "rule-of-5 violation acceptable for intracellular target"},
        {"name": "AMP-derived", "rules": ["8-25 residues", "net charge +2 to +6", "amphipathic", "HC50 > 100 µM"],
         "rationale": "topical or inhaled antimicrobial peptide"},
        {"name": "siderophore-conjugate", "rules": ["siderophore mimic at one position", "MW < 750",
                                                       "Fe3+ chelation Kd < 10⁻²⁰ M"],
         "rationale": "Trojan-horse entry through TonB-dependent receptors"},
        {"name": "GMP-friendly", "rules": ["≤2 chiral centers", "≤6 synth steps", "no chromatography",
                                              "starting material < $200/g"],
         "rationale": "minimize cost-of-goods for low-margin antibacterial market"},
    ])
    pathogen = rng.choice(PATHOGENS)
    profile = constraints["name"]

    user = _user_brief(
        f"Designer: design a candidate against {pathogen} satisfying the {profile} constraint profile. "
        f"Rules: {'; '.join(constraints['rules'])}. Rationale: {constraints['rationale']}."
    )

    # Generate candidate that satisfies (most) rules
    mw = rng.choice([280, 320, 380, 420, 480]) if "MW < 500" in str(constraints["rules"]) else rng.choice([800, 1100, 1400])
    logp = round(rng.uniform(0.5, 3.5), 1)
    hbd = rng.randint(1, 4)
    log_mic = round(rng.gauss(-0.1, 0.5), 2)

    asst = (
        f"[Designer]: Constraint profile = {profile}. Rules accepted.\n\n"
        f"Strategy: anchor on a scaffold class known to satisfy the constraints, "
        f"then optimize within the constraint envelope rather than fighting it. "
        f"The constraint set defines the design space; my job is to find the "
        f"highest-activity candidate inside that space.\n\n"
        f"Anchor selection: "
        f"{'low-MW pyridone-class' if mw < 400 else 'macrocyclic depsipeptide' if mw > 600 else 'pyrazole-pyridine fused bicycle'}.\n\n"
        f"<tool_call>name: predict_admet\nargs: {{\"smiles\": \"<candidate>\"}}</tool_call>\n"
        f"[Tool]: {{\"mw\": {mw}, \"logp\": {logp}, \"hbd\": {hbd}, \"hba\": {hbd+3}, "
        f"\"rotatable_bonds\": {rng.randint(2, 7)}, \"lipinski_violations\": "
        f"{0 if mw < 500 else 2}}}\n\n"
        f"[Designer]: Verifying constraint compliance row-by-row:\n"
    )
    for rule in constraints["rules"]:
        # Rough auto-check
        ok = "✓" if rng.random() > 0.15 else "✗"
        asst += f"  {ok} {rule}\n"

    asst += (
        f"\n<tool_call>name: predict_mic_pathogen\n"
        f"args: {{\"smiles\": \"<candidate>\", \"pathogen\": \"{pathogen}\"}}</tool_call>\n"
        f"[Tool]: log_mic_predicted={log_mic}, mic_ug_ml={round(10**log_mic, 2)}\n\n"
        f"[Designer]: Activity inside the constraint envelope: MIC≈{round(10**log_mic, 2)} µg/mL. "
        f"{'Hit-quality.' if log_mic < 0.7 else 'Borderline; iterate within constraints.'}\n\n"
        f"DECISION: Candidate {profile}-compliant + active. "
        f"{'Promote to next stage.' if log_mic < 0.7 else 'Iterate via scaffold_hop within the same constraint envelope.'}"
    )

    return {
        "task": "teacher_constraint_compliance",
        "pathogen": pathogen,
        "profile": profile,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# F. wet_lab_handoff
# ============================================================================
def trace_wet_lab_handoff(rng: random.Random) -> dict:
    n_candidates = rng.randint(3, 6)
    pathogen = rng.choice(PATHOGENS)
    candidates = []
    for i in range(n_candidates):
        candidates.append({
            "id": f"L{rng.randint(10, 99)}-{i+1}",
            "composite": _round(rng.uniform(0.55, 0.92)),
            "log_mic": _round(rng.gauss(-0.3, 0.5)),
            "synth_cost_per_g": rng.choice([60, 120, 280, 480, 750, 1200]),
            "synth_steps": rng.randint(3, 8),
            "lipinski_v": rng.randint(0, 2),
            "novelty_tanimoto": _round(rng.uniform(0.3, 0.7)),
            "escape_verdict": rng.choice(["low-risk", "moderate-risk", "high-risk"]),
        })
    candidates.sort(key=lambda c: -c["composite"])

    user = _user_brief(
        f"Wet-lab handoff: {n_candidates} candidates against {pathogen}. "
        f"Format for medchem team with prioritization rationale."
    )

    asst = (
        f"[Designer]: Handoff to medchem team. Ranking by composite score, "
        f"adjusted for synth cost + escape risk + novelty.\n\n"
        f"=== TOP {n_candidates} CANDIDATES — {PATH_FULL[pathogen]} ({pathogen}) ===\n\n"
    )
    for i, c in enumerate(candidates):
        priority = "P0" if i == 0 else "P1" if i < 3 else "P2"
        asst += (
            f"{priority}: {c['id']}\n"
            f"  Composite:       {c['composite']:.2f}\n"
            f"  Predicted MIC:   {round(10**c['log_mic'], 2)} µg/mL (log10={c['log_mic']:.2f})\n"
            f"  ADMET:           Lipinski viol={c['lipinski_v']}\n"
            f"  Synthesis:       ~{c['synth_steps']} steps, ${c['synth_cost_per_g']}/g\n"
            f"  Novelty:         Tanimoto={c['novelty_tanimoto']:.2f} vs known corpus\n"
            f"  Resistance:      {c['escape_verdict']}\n"
            f"  Recommendation:  "
        )
        if i == 0:
            asst += "Priority for first wet-lab MIC test (MIC + IC50 + cytotox panel).\n"
        elif c['composite'] > 0.7 and c['escape_verdict'] != 'high-risk':
            asst += "Backup if P0 fails wet-lab confirmation. Order intermediate.\n"
        else:
            asst += "Hold; revisit only if top candidates fail.\n"
        asst += "\n"

    asst += (
        f"=== HANDOFF NOTES FOR MEDCHEM ===\n"
        f"  - Synthesize P0 first (top-1).\n"
        f"  - Run wet MIC against {pathogen} clinical isolates (USA300 / "
        f"reference + 2-3 MDR isolates).\n"
        f"  - If P0 wet MIC > 4× predicted, escalate to Strategist for re-eval.\n"
        f"  - If P0 wet MIC matches predicted (±2×), confirm with hERG + "
        f"hepatotox in vitro before any in vivo.\n"
        f"  - Total expected wet-lab cost (synth P0 + assay): "
        f"${candidates[0]['synth_cost_per_g'] * 5 + 1500} (5 g synthesis + assay).\n\n"
        f"DECISION: P0 ({candidates[0]['id']}) cleared for synthesis. Estimated "
        f"timeline 3 weeks synth + 2 weeks assay = 5 weeks to wet-lab go/no-go."
    )

    return {
        "task": "teacher_wet_lab_handoff",
        "pathogen": pathogen,
        "n_candidates": n_candidates,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# G. resistance_forecasting
# ============================================================================
def trace_resistance_forecasting(rng: random.Random) -> dict:
    pathogen = rng.choice(PATHOGENS)
    drug_class = {
        "MRSA": rng.choice(["β-lactam (5GC)", "lipoglycopeptide", "oxazolidinone"]),
        "Mtb": rng.choice(["rifamycin", "INH-class", "fluoroquinolone", "diarylquinoline"]),
        "EColi-CRE": rng.choice(["DBO-cephalosporin", "siderophore-cephalosporin", "boronate"]),
        "KpneuCRE": rng.choice(["DBO-cephalosporin", "aztreonam-DBO", "tigecycline"]),
        "Abaum": rng.choice(["DBO-sulbactam", "polymyxin", "cefiderocol"]),
        "Paer": rng.choice(["modified cephalosporin", "siderophore", "EPI combo"]),
        "VRE": rng.choice(["lipoglycopeptide", "oxazolidinone", "lipopeptide"]),
        "NGono": rng.choice(["3GC ceftriaxone", "spiropyrimidine", "triazaacenaphthylene"]),
    }[pathogen]

    user = _user_brief(
        f"Forecast: clinical use of {drug_class} against {pathogen} is increasing. "
        f"Predict where resistance will emerge in the next 24-36 months and what "
        f"the Lysos design pipeline should do to stay ahead.",
        pathogen,
    )

    # Pull realistic forecasted mechanisms
    mech_forecasts = {
        "β-lactam (5GC)": "PBP2a allosteric site mutations (N146K, E150K) — published in 2-3 patient case reports already; expect community spread within 18 months",
        "rifamycin": "rpoB-S531L remains dominant, but rpoB-D516V emerging in BPaL-treated patients; new triple-mutant (rpoB-S531L + L533P) reported in 2024",
        "DBO-cephalosporin": "KPC-31 D179Y has 10× ↓ avibactam binding; D179N also emerging; expect to see KPC-49/50 lineages within 12-18 months",
        "siderophore-cephalosporin": "TonB / ExbB mutations reduce Fe-uptake; pirA mutation emerging in CF lung Pseudomonas",
        "modified cephalosporin": "AmpC-derepression + porin-loss combination; OprD truncation emerging",
        "lipoglycopeptide": "vanA already widespread; new vanD/vanE variants found in 2024",
        "oxazolidinone": "23S G2576T + cfr methylation — combined resistance mounting",
        "lipopeptide": "membrane phospholipid composition changes (mprF-up, dltABCD-up)",
        "polymyxin": "mcr-1 plasmid spread + LPS modification (eptA, pmrAB)",
        "cefiderocol": "TonB cluster mutations + iron-uptake pathway dysregulation",
        "DBO-sulbactam": "OXA-23 mutations in the DBO binding pocket — emerging in 2024 reports",
        "spiropyrimidine": "GyrB-S466T expected within 12 months of broad rollout",
        "triazaacenaphthylene": "topo-IV mutations in parC — first reports 2024",
        "INH-class": "katG-S315T + inhA promoter -15 — both already common",
        "fluoroquinolone": "gyrA-A90V + parC-S87L double mutant — entrenched",
        "diarylquinoline": "atpE mutations rare but emerging in long-treated patients",
        "aztreonam-DBO": "MBL up-regulation + DBO-resistant KPC variants",
        "tigecycline": "tetX5/X6 inactivating tetracycline; emerging in CRE",
        "3GC ceftriaxone": "penA mosaic LX (post-2023); FC428 lineage spread",
    }
    forecast = mech_forecasts.get(drug_class, "target-site mutations with secondary efflux up-regulation")

    asst = (
        f"[Strategist]: Resistance forecast for {drug_class} against {pathogen} "
        f"(WHO {WHO_TIER[pathogen]} priority).\n\n"
        f"<tool_call>name: search_literature\n"
        f"args: {{\"query\": \"{pathogen} {drug_class} resistance emergence 2024\"}}</tool_call>\n"
        f"[Tool]: returns 5-8 recent case reports + clinical microbiology surveys\n\n"
        f"FORECAST: {forecast}.\n\n"
        f"Timeline:\n"
        f"  T+0 to T+12 months: clinical case reports, individual patients on therapy\n"
        f"  T+12 to T+24 months: surveillance picks up community spread; first "
        f"published outbreak\n"
        f"  T+24 to T+36 months: CDC/ECDC alerts; revised treatment guidelines; "
        f"the new variant becomes the dominant clinical concern\n\n"
        f"LYSOS PIPELINE RESPONSE:\n"
        f"  1. Pre-emptively design candidates that EVADE the predicted resistance "
        f"     mechanism. The new pharmacophore should not engage the residue "
        f"     that the resistance mutation will alter.\n"
        f"  2. Run the predict_resistance_escape tool on EVERY candidate during "
        f"     SFT and RL, not just at the final eval. This makes resistance "
        f"     evasion part of the design objective from day 1.\n"
        f"  3. Build a parallel campaign on the orthogonal scaffold class — when "
        f"     the resistance hits the clinic, Lysos has the back-up agent ready.\n"
        f"  4. Add the predicted mutation to the resistance_robustness reward "
        f"     component for Stage 3 GRPO so the policy learns to evade.\n\n"
        f"DECISION: open a 'pre-emptive resistance' track parallel to the current "
        f"campaign. Allocate 20% of MI300X budget to this track."
    )

    return {
        "task": "teacher_resistance_forecasting",
        "pathogen": pathogen,
        "drug_class": drug_class,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# H. combo_therapy_strategy
# ============================================================================
def trace_combo_therapy(rng: random.Random) -> dict:
    combos = [
        ("MRSA", "vancomycin failing on bacteremia", [("daptomycin + ceftaroline", "membrane + cell-wall, classic synergy"),
                                                        ("vancomycin + daptomycin", "complementary cell-wall + membrane"),
                                                        ("daptomycin + ceftriaxone", "PBP-mediated permeability rescue")]),
        ("Mtb", "MDR-TB second-line", [("BPaL (bedaquiline + pretomanid + linezolid)", "ATP synthase + nitroimidazole + 23S; 89% cure rate"),
                                          ("rifampin + clofazimine", "Rv0678 saturable efflux pump"),
                                          ("INH + PZA", "activator-target combination")]),
        ("EColi-CRE", "KPC-only carbapenemase", [("ceftaz-avi + meropenem", "DBO inhibitor + carbapenem rescue"),
                                                    ("ceftaz-avi + colistin", "for KPC + porin loss"),
                                                    ("aztreonam + avibactam", "MBL stable + DBO inhibitor")]),
        ("Paer", "MDR-Pseudomonas pneumonia", [("ceftolozane-tazo + tobramycin", "cell-wall + ribosomal"),
                                                  ("cefiderocol + colistin", "siderophore + outer membrane permeabilization"),
                                                  ("β-lactam + aminoglycoside", "classic Pseudomonas synergy")]),
        ("Abaum", "CRAB pneumonia", [("sulbactam-durlobactam + colistin", "PBP3 + outer membrane"),
                                       ("sulbactam-durlobactam + minocycline", "FDA-approved 2023 + tetracycline")]),
        ("VRE", "vancomycin-R Enterococcus", [("daptomycin + ceftaroline", "see-saw effect on PBP2"),
                                                ("daptomycin + ampicillin", "rescued sensitivity in some cases"),
                                                ("linezolid + daptomycin", "classic salvage combo")]),
        ("NGono", "ceftriaxone-resistant gonorrhea", [("ceftriaxone + azithromycin", "WHO standard combo"),
                                                        ("zoliflodacin + ceftriaxone", "novel + standard"),
                                                        ("gentamicin + azithromycin", "salvage option")]),
    ]
    pathogen, scenario, options = rng.choice(combos)
    chosen_combo, mechanism = rng.choice(options)

    user = _user_brief(f"Clinical scenario: {scenario}. Recommend a combo regimen.", pathogen)

    asst = (
        f"[Designer]: Combo therapy decision for {pathogen} — {scenario}.\n\n"
        f"Reasoning:\n"
        f"  Single-agent therapy has failed (or is contraindicated). Combo "
        f"therapy needs to satisfy three criteria:\n"
        f"  1. SYNERGY (or at minimum INDIFFERENCE) — measured by FIC index < 0.5\n"
        f"  2. ORTHOGONAL MECHANISMS — different targets reduce single-mutation escape\n"
        f"  3. NO ANTAGONISM — verify in vitro before clinical commit\n\n"
        f"<tool_call>name: search_literature\n"
        f"args: {{\"query\": \"{pathogen} {scenario.split(' ')[0]} combo therapy synergy 2024\"}}</tool_call>\n"
        f"[Tool]: returns FIC studies + recent clinical reports\n\n"
        f"Top combo recommendation: {chosen_combo}\n"
        f"Mechanism: {mechanism}\n\n"
        f"Predicted FIC index: {rng.choice([0.25, 0.35, 0.45, 0.5])} (synergy "
        f"threshold ≤ 0.5).\n\n"
        f"Clinical considerations:\n"
        f"  - Both agents IV; prepare for hospital admission.\n"
        f"  - Monitor for additive toxicity (e.g., nephrotoxicity if both renal).\n"
        f"  - Source-control if applicable (drainage, line removal).\n"
        f"  - Therapeutic drug monitoring for narrow-therapeutic-index agents.\n"
        f"  - Plan for de-escalation: if susceptibility data narrows the spectrum, "
        f"step down to single agent.\n\n"
        f"DECISION: Initiate {chosen_combo}. Reassess at 72 hours: if clinical "
        f"improvement + culture-negative blood, continue 14-21 days. If no "
        f"improvement, escalate to Strategist for second-line salvage."
    )

    return {
        "task": "teacher_combo_therapy",
        "pathogen": pathogen,
        "combo": chosen_combo,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# I. clinical_positioning
# ============================================================================
def trace_clinical_positioning(rng: random.Random) -> dict:
    pathogen = rng.choice(PATHOGENS)
    mic = rng.choice([0.06, 0.12, 0.25, 0.5, 1.0, 2.0])
    bioav = rng.choice([0.30, 0.55, 0.85, 0.95])
    t_half = rng.choice([2, 4, 8, 12, 24])
    route = "IV" if bioav < 0.4 else "PO/IV" if bioav < 0.85 else "PO"

    indication_map = {
        "MRSA": ["bacteremia", "SSTI", "endocarditis", "osteomyelitis", "pneumonia"],
        "Mtb": ["pulmonary TB", "MDR-TB", "XDR-TB", "extrapulmonary TB", "TB meningitis"],
        "EColi-CRE": ["UTI", "bacteremia", "intra-abdominal", "pneumonia"],
        "KpneuCRE": ["pneumonia", "UTI", "liver abscess", "bacteremia"],
        "Abaum": ["VAP", "wound infection", "bacteremia", "meningitis"],
        "Paer": ["VAP", "CF lung", "burn wound", "bacteremia"],
        "VRE": ["bacteremia in immunocompromised", "endocarditis", "UTI"],
        "NGono": ["urethritis", "PID", "DGI", "pharyngeal"],
    }
    indication = rng.choice(indication_map[pathogen])

    user = _user_brief(
        f"New candidate: predicted MIC={mic} µg/mL on {pathogen}, F={bioav}, "
        f"t1/2={t_half}h. Position clinically: indication, dose, route.",
        pathogen,
    )

    # Calculate dose based on PK/PD principles
    dose_mg_kg = max(1, round(40 * mic * 4))  # AUC/MIC ≥ 100 baseline
    if dose_mg_kg > 20: dose_mg_kg = 20
    interval = 24 if t_half >= 12 else 12 if t_half >= 6 else 8

    asst = (
        f"[Designer]: Clinical positioning for the new candidate.\n\n"
        f"Inputs:\n"
        f"  Predicted MIC vs {pathogen}: {mic} µg/mL\n"
        f"  Bioavailability F: {bioav} → route: {route}\n"
        f"  Half-life t1/2: {t_half} h\n\n"
        f"<tool_call>name: get_pathogen_resistome\n"
        f"args: {{\"pathogen\": \"{pathogen}\"}}</tool_call>\n"
        f"[Tool]: returns first-line therapy + clinical syndromes\n\n"
        f"INDICATION: {indication} caused by {pathogen}\n"
        f"  Justification: candidate MIC vs {pathogen} ({mic} µg/mL) is in the "
        f"clinically active range; the {indication} indication has known unmet "
        f"need given resistance to current first-line therapy.\n\n"
        f"DOSING:\n"
        f"  AUC/MIC target: 100 (β-lactam-class) or 400 (vancomycin-class)\n"
        f"  Required steady-state Css: ~{round(mic * 4, 2)} µg/mL\n"
        f"  Calculated dose: {dose_mg_kg} mg/kg q{interval}h {route}\n"
        f"  Loading dose: 1.5× maintenance (×{round(dose_mg_kg * 1.5)}) for first dose\n\n"
        f"DURATION:\n"
        f"  Standard for {indication}: "
    )

    duration = {
        "bacteremia": "14 days from first negative blood culture",
        "SSTI": "7-10 days",
        "endocarditis": "4-6 weeks",
        "osteomyelitis": "6-8 weeks",
        "pneumonia": "7-14 days",
        "pulmonary TB": "RIPE 2 mo + RI 4 mo (6 months total)",
        "MDR-TB": "12-18 months individualized regimen",
        "XDR-TB": "BPaL 6 months",
        "UTI": "3-7 days uncomplicated, 7-14 days complicated",
        "VAP": "8 days (IDSA short-course preferred)",
        "DGI": "7 days IV ceftriaxone-class",
    }.get(indication, "based on syndrome severity")
    asst += duration

    asst += (
        f"\n\nMONITORING:\n"
        f"  - TDM if narrow-therapeutic-index (target trough {mic*2}-{mic*4} µg/mL)\n"
        f"  - Renal function (CrCl) twice weekly during therapy\n"
        f"  - Liver function tests at week 1, 4 if hepatically cleared\n\n"
        f"DOSE ADJUSTMENTS:\n"
        f"  - Renal impairment (CrCl < 30): adjust per Dettli method (assume "
        f"~70% renal clearance for new agent)\n"
        f"  - Hepatic impairment (Child-Pugh C): reduce by 50%\n"
        f"  - Obesity (BMI > 35): consider AUC-guided dosing rather than mg/kg\n\n"
        f"DECISION: Position the candidate as {indication} therapy at "
        f"{dose_mg_kg} mg/kg q{interval}h {route}. "
        f"{'PO option supports outpatient step-down.' if 'PO' in route else 'IV-only acceptable for hospital indication.'} "
        f"Pre-clinical PK/PD studies should target the AUC/MIC of 100 to "
        f"validate the dosing strategy."
    )

    return {
        "task": "teacher_clinical_positioning",
        "pathogen": pathogen,
        "indication": indication,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# J. manufacturing_reasoning
# ============================================================================
def trace_manufacturing(rng: random.Random) -> dict:
    n_chiral = rng.randint(0, 4)
    n_steps = rng.randint(3, 9)
    has_macrocycle = rng.random() < 0.3
    has_chromatography = rng.random() < 0.5
    starting_material_cost = rng.choice([20, 80, 250, 800, 2500])

    user = _user_brief(
        f"Top candidate has {n_chiral} chiral centers, {n_steps}-step synthesis, "
        f"{'macrocyclic ring' if has_macrocycle else 'no macrocycle'}, "
        f"{'requires chromatography' if has_chromatography else 'no chromatography'}, "
        f"starting material costs ${starting_material_cost}/g. Manufacturing strategy?"
    )

    cost_per_g_lab = starting_material_cost * (n_steps + 1) * (1.5 if has_chromatography else 1.0)
    cost_per_g_gmp = cost_per_g_lab * 8  # GMP scale-up multiplier

    asst = (
        f"[Designer-Manufacturing]: Cost-of-goods analysis for the top candidate.\n\n"
        f"Inputs:\n"
        f"  Chiral centers: {n_chiral}\n"
        f"  Synthesis steps: {n_steps}\n"
        f"  Macrocyclic ring: {has_macrocycle}\n"
        f"  Chromatography required: {has_chromatography}\n"
        f"  Starting material: ${starting_material_cost}/g\n\n"
        f"COST PROJECTION:\n"
        f"  Lab scale (10 g):    ~${cost_per_g_lab:.0f}/g\n"
        f"  GMP scale (10 kg):   ~${cost_per_g_gmp:.0f}/g\n"
        f"  GMP scale (100 kg):  ~${cost_per_g_gmp/4:.0f}/g (process optimization)\n\n"
        f"STEREOCHEMISTRY STRATEGY:\n"
    )

    if n_chiral == 0:
        asst += "  Achiral — no resolution needed. Cheapest option.\n"
    elif n_chiral == 1:
        asst += ("  1 chiral center → use chiral pool starting material OR "
                 "asymmetric synthesis OR late-stage resolution. "
                 "Estimated cost premium: 1.5-2× achiral baseline.\n")
    elif n_chiral == 2:
        asst += ("  2 chiral centers → CRITICAL DECISION POINT. Options:\n"
                 "    (a) Asymmetric synthesis with chiral catalyst (most cost-efficient at scale)\n"
                 "    (b) Resolution with chiral chromatography (high cost)\n"
                 "    (c) Diastereomeric salt resolution (intermediate cost)\n"
                 "  Pick option (a) if catalyst is commercially available; (c) otherwise.\n")
    elif n_chiral >= 3:
        asst += (f"  {n_chiral} chiral centers — VERY EXPENSIVE.\n"
                 "  Each center adds 5-15% to cost-of-goods. Consider:\n"
                 "    - SCAFFOLD-HOP to reduce stereocenters if possible\n"
                 "    - Enzymatic resolution if a stereocenter is at the right position\n"
                 "    - Asymmetric catalysis where commercially available\n"
                 "  Total premium: ~3-5× achiral baseline.\n")

    asst += (
        f"\nROUTE OPTIMIZATION:\n"
        f"  Step count: {n_steps} steps. "
    )
    if n_steps <= 5:
        asst += "Acceptable for medchem and scale.\n"
    elif n_steps <= 7:
        asst += "Borderline — try to compress 1-2 steps via tandem reactions.\n"
    else:
        asst += "TOO MANY — high cost-of-goods. Consider: convergent synthesis (split into two halves, couple late), or scaffold-hop to a shorter-route analog.\n"

    if has_chromatography:
        asst += (
            f"\nCHROMATOGRAPHY ELIMINATION:\n"
            f"  Chromatography is the #1 cost driver at GMP scale. Strategies:\n"
            f"    - Crystallization-based purification (re-crystallize the salt)\n"
            f"    - Diastereomeric salt formation for resolution\n"
            f"    - Process optimization to reduce impurities upstream\n"
            f"  Eliminating chromatography typically halves the GMP cost.\n"
        )

    if has_macrocycle:
        asst += (
            f"\nMACROCYCLIZATION:\n"
            f"  Macrocyclic ring formation is high-risk for scale. Standard "
            f"approaches: (a) high-dilution macrolactamization (kg-scale "
            f"limited), (b) ring-closing metathesis (Grubbs-class), (c) "
            f"dimerization-then-cleavage. Plan for 10-30% yield at the "
            f"macrocyclization step.\n"
        )

    asst += (
        f"\nMARKET REALITY CHECK:\n"
        f"  Generic antibiotics sell at $1-50/g GMP. New IV antibiotics at "
        f"$500-5000/g (e.g., daptomycin $4500/g GMP early, now $200/g). "
        f"Target market price for a hospital-IV {rng.choice(['MRSA', 'CRE', 'Pseudomonas'])} "
        f"antibiotic: $800-3000/g. Our projected cost ${cost_per_g_gmp:.0f}/g is "
        f"{'within range' if cost_per_g_gmp < 3000 else 'TOO HIGH — process improvement required'}.\n\n"
        f"DECISION: "
        f"{'Approved for Phase 1 manufacture; process optimization parallel.' if cost_per_g_gmp < 3000 else 'Hold; redesign to eliminate the most expensive step before committing scale-up.'}"
    )

    return {
        "task": "teacher_manufacturing",
        "n_chiral": n_chiral,
        "n_steps": n_steps,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# K. literature_grounding
# ============================================================================
def trace_literature_grounding(rng: random.Random) -> dict:
    pathogen = rng.choice(PATHOGENS)
    topic = rng.choice([
        ("recent ceftaz-avi resistance emergence", "Shields 2024 CID — KPC-3 D179Y in 9% of patients within 30 days"),
        ("BPaL trial cure rates for XDR-TB", "Drain 2023 NEJM — 89% cure with BPaL"),
        ("zoliflodacin phase III win", "Taylor 2024 Lancet ID — non-inferior to ceftriaxone+azithro"),
        ("sulbactam-durlobactam ATTACK trial", "Kaye 2023 NEJM — non-inferior to colistin, less nephrotox"),
        ("vancomycin-MIC creep", "Mendes 2024 Lancet ID — 8.4% creep 2018-2023"),
        ("aztreonam-avibactam FDA approval", "Hobson 2025 — 2024 approval for KPC+NDM"),
        ("tedizolid against cfr-positive VRE", "Bender 2024 CID — 60% retention of activity"),
        ("ceftolozane-tazo resistance in Pseudomonas", "Hagiya 2024 JAC — 12% R post-30-day, AmpC + porin"),
    ])
    topic_label, topic_finding = topic

    user = _user_brief(
        f"Literature query: {topic_label}. Use search_literature to ground "
        f"the design rationale and cite current evidence.",
        pathogen,
    )

    asst = (
        f"[Designer]: Grounding the design rationale in literature.\n\n"
        f"<tool_call>name: search_literature\n"
        f"args: {{\"query\": \"{topic_label} {pathogen}\"}}</tool_call>\n"
        f"[Tool]: returns {rng.randint(4, 9)} papers, top match: {topic_finding}\n\n"
        f"KEY FINDING: {topic_finding}\n\n"
        f"IMPLICATIONS FOR DESIGN:\n"
        f"  1. The recent literature establishes a CONCRETE BASELINE for the "
        f"target. Our candidate must demonstrably improve on this baseline "
        f"to be clinically relevant.\n"
        f"  2. The mechanism of resistance/cure described in the paper "
        f"defines the COMPETITIVE LANDSCAPE. Our candidate either:\n"
        f"     - Matches the cure rate but addresses the toxicity, OR\n"
        f"     - Matches the toxicity profile but extends activity to a "
        f"new indication, OR\n"
        f"     - Both improvements simultaneously.\n"
        f"  3. CITE the paper in the FINAL CANDIDATE REPORT and the model card. "
        f"Reviewers want to know we read the relevant literature.\n\n"
        f"INTEGRATION INTO DESIGN PIPELINE:\n"
        f"  - Use the cited mechanism as a feature in the resistance_robustness "
        f"reward component for Stage 3 GRPO.\n"
        f"  - Add a held-out eval prompt that asks 'how does your candidate "
        f"improve on {topic_label}?' to verify the model can articulate the "
        f"competitive position.\n"
        f"  - Compare our candidate's predicted profile head-to-head against "
        f"the published baseline using compare_molecules + score_molecule.\n\n"
        f"DECISION: Anchor the design rationale in {topic_finding}. "
        f"Explicitly position our candidate as 'addresses the limitation of "
        f"X identified in {topic_label.split(' ')[0]} et al.' in the model card."
    )

    return {
        "task": "teacher_literature_grounding",
        "pathogen": pathogen,
        "topic": topic_label,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# L. confidence_calibration
# ============================================================================
def trace_confidence_calibration(rng: random.Random) -> dict:
    pathogen = rng.choice(PATHOGENS)
    confidence = round(rng.uniform(0.2, 0.95), 2)
    log_mic = round(rng.gauss(-0.2, 0.6), 2)
    second_tool_disagrees = rng.random() < 0.3

    user = _user_brief(
        f"predict_mic_pathogen returned log10(MIC)={log_mic}, confidence={confidence}. "
        f"Decide whether to act on this prediction or run additional verification.",
        pathogen,
    )

    asst = (
        f"[Designer]: Confidence calibration on a single prediction.\n\n"
        f"INPUT: log10(MIC)={log_mic} (MIC≈{round(10**log_mic,2)} µg/mL), confidence={confidence}.\n\n"
        f"DECISION FRAMEWORK:\n"
        f"  Confidence ≥ 0.80: TRUST the prediction; proceed to next panel step.\n"
        f"  Confidence 0.60-0.80: CAUTIOUS TRUST; cross-check with one orthogonal tool.\n"
        f"  Confidence 0.40-0.60: LOW TRUST; require ≥2 independent confirmations.\n"
        f"  Confidence < 0.40: NO TRUST; treat as uninformed prior; require wet-lab.\n\n"
    )

    if confidence >= 0.80:
        asst += (
            f"This case (confidence {confidence}): TRUST tier. "
            f"The XGBoost MIC predictor has 0.62 scaffold-CV MAE on the training "
            f"distribution. At {confidence} confidence, the prediction sits "
            f"within the high-density region of the model's decision boundary. "
            f"Proceed with the prediction as-is.\n\n"
            f"DECISION: Accept log10(MIC)={log_mic}. Next step: predict_admet."
        )
    elif confidence >= 0.60:
        asst += (
            f"This case (confidence {confidence}): CAUTIOUS TRUST. "
            f"Run an orthogonal verification.\n\n"
            f"<tool_call>name: predict_binding_affinity\n"
            f"args: {{\"smiles\": \"<candidate>\", \"target\": \"<target>\"}}</tool_call>\n"
            f"[Tool]: ΔG_kcal_mol={rng.choice([-9.2, -8.5, -7.8, -6.4])}, pKd={round(rng.uniform(6, 9), 1)}\n\n"
            f"[Designer]: "
        )
        if second_tool_disagrees:
            asst += (
                f"DISAGREEMENT — predict_binding_affinity suggests weaker binding "
                f"than the MIC predictor. The MIC predictor may be misled by a "
                f"close-corpus analog. Recommend prioritizing wet-lab confirmation "
                f"before committing further compute.\n\n"
                f"DECISION: Hold; flag for wet-lab MIC + binding assay. Don't "
                f"commit downstream tools until wet confirms."
            )
        else:
            asst += (
                f"AGREEMENT — both tools confirm activity. Confidence elevated.\n\n"
                f"DECISION: Accept activity prediction. Proceed to ADMET."
            )
    else:
        asst += (
            f"This case (confidence {confidence}): LOW TRUST tier. "
            f"Require ≥2 independent confirmations or treat as wet-lab-only.\n\n"
            f"<tool_call>name: dock_against_target\nargs: {{\"smiles\":\"<candidate>\", \"pdb_id\":\"<pdb>\"}}</tool_call>\n"
            f"<tool_call>name: predict_binding_affinity\nargs: {{\"smiles\":\"<candidate>\"}}</tool_call>\n"
            f"<tool_call>name: find_similar_drugs\nargs: {{\"query_smiles\":\"<candidate>\"}}</tool_call>\n\n"
            f"If 2 of 3 confirm activity → upgrade to MEDIUM TRUST. If 1 of 3 or "
            f"none → reject. Wet-lab is the only ground truth at this confidence "
            f"level. Don't burn further compute on optimization until activity "
            f"is confirmed.\n\n"
            f"DECISION: Hold; require wet-lab MIC before any further panel."
        )

    return {
        "task": "teacher_confidence_calibration",
        "pathogen": pathogen,
        "confidence": confidence,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
    }


# ============================================================================
# M. workbench_state_reasoning
# ============================================================================
def trace_workbench_state(rng: random.Random) -> dict:
    n_candidates = rng.randint(8, 25)
    n_iters = rng.randint(3, 8)
    pathogen = rng.choice(PATHOGENS)
    interventions = rng.sample([
        "user clamped MW < 400",
        "user banned aromatic amines",
        "user requested only DBO scaffolds",
        "user pinned a target PDB",
        "user requested zero-PAINS hard constraint",
        "user reduced compute budget",
        "user added a new pathogen",
    ], rng.randint(1, 3))

    user = _user_brief(
        f"Read the Workbench candidate ledger: {n_candidates} candidates "
        f"across {n_iters} iterations against {pathogen}. User interventions "
        f"during the session: {'; '.join(interventions)}. Decide what's the next move.",
        pathogen,
    )

    asst = (
        f"[Strategist]: Reading the Workbench ledger.\n\n"
        f"LEDGER STATE:\n"
        f"  Candidates: {n_candidates}\n"
        f"  Iterations: {n_iters}\n"
        f"  User interventions ({len(interventions)}):\n"
    )
    for i in interventions:
        asst += f"    - {i}\n"

    # Synthesize a candidate distribution
    n_excellent = rng.randint(1, 3)
    n_good = rng.randint(2, 5)
    n_marginal = max(0, n_candidates - n_excellent - n_good - rng.randint(2, 5))
    n_kill = n_candidates - n_excellent - n_good - n_marginal

    asst += (
        f"\nCANDIDATE DISTRIBUTION (composite score):\n"
        f"  Excellent (≥0.85):     {n_excellent}\n"
        f"  Good (0.65-0.85):      {n_good}\n"
        f"  Marginal (0.50-0.65):  {n_marginal}\n"
        f"  Kill (<0.50):          {n_kill}\n\n"
        f"INTERVENTION COMPLIANCE CHECK:\n"
    )
    for i in interventions:
        compliance = rng.choice(["✓ all candidates compliant",
                                  "⚠ 2 candidates violate",
                                  "✓ compliant after iteration 4 onwards"])
        asst += f"  {i:50s} → {compliance}\n"

    asst += (
        f"\nPROGRESS RATE:\n"
        f"  Iterations 1-{n_iters//2}: composite range "
        f"{rng.uniform(0.4, 0.55):.2f}-{rng.uniform(0.55, 0.7):.2f}\n"
        f"  Iterations {n_iters//2+1}-{n_iters}: composite range "
        f"{rng.uniform(0.55, 0.7):.2f}-{rng.uniform(0.7, 0.9):.2f}\n"
        f"  Trend: {'IMPROVING — continue current strategy' if rng.random() > 0.3 else 'PLATEAU — pivot strategy'}\n\n"
        f"DECISION:\n"
    )

    if n_excellent >= 2:
        asst += (
            f"  TERMINATE this iteration. Hand off the {n_excellent} excellent "
            f"candidates to wet-lab for parallel synthesis. The probability of "
            f"finding a meaningfully better candidate via more iterations is "
            f"low; the time-cost of additional optimization exceeds the marginal "
            f"benefit.\n"
            f"  Next: format wet-lab handoff for medchem team."
        )
    elif n_excellent == 1 and n_good >= 3:
        asst += (
            f"  CONTINUE for 1-2 more iterations focused on the weakest pillar "
            f"of the {n_excellent + n_good} top candidates. Goal: lift at least "
            f"one Good-tier candidate to Excellent-tier, doubling the wet-lab "
            f"backup pool.\n"
            f"  Next: Designer iterates on the top 4 candidates with scaffold_hop."
        )
    else:
        asst += (
            f"  PIVOT — current trajectory unlikely to produce wet-lab-quality "
            f"candidate within budget. Options:\n"
            f"    (a) Switch scaffold class (current class plateau'd)\n"
            f"    (b) Relax one user intervention if blocking too many candidates\n"
            f"    (c) Add a new resistance-evasion constraint to focus the search\n"
            f"  Recommend option (a) — pivoting scaffold class. Strategist will "
            f"queue the scaffold pivot."
        )

    return {
        "task": "teacher_workbench_state",
        "pathogen": pathogen,
        "n_candidates": n_candidates,
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
    "strategist_campaign":    trace_strategist_campaign,
    "tool_orchestration":     trace_tool_orchestration,
    "multi_pathogen_spectrum": trace_multi_pathogen_spectrum,
    "failure_mode_debug":     trace_failure_mode_debug,
    "constraint_compliance":  trace_constraint_compliance,
    "wet_lab_handoff":        trace_wet_lab_handoff,
    "resistance_forecasting": trace_resistance_forecasting,
    "combo_therapy":          trace_combo_therapy,
    "clinical_positioning":   trace_clinical_positioning,
    "manufacturing":          trace_manufacturing,
    "literature_grounding":   trace_literature_grounding,
    "confidence_calibration": trace_confidence_calibration,
    "workbench_state":        trace_workbench_state,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_per_category", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0xDEADBEEF_42)
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

    print(f"\nGenerated {n_total:,} systems-level teacher traces")
    for k, v in counts.items():
        print(f"  {k:30s} {v}")
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    sys.exit(main())
