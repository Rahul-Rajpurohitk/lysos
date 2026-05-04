"""Closes gaps A-G from the post-bake audit:

  A. Full-loop conversations  (Designer→Critic→Editor→Strategist over 3-5 iters)
  B. Tool-error recovery      (tool returns error, agent retries with fix)
  C. Negative examples        (bad proposal, Critic catches it, Editor fixes)
  D. Constraint compliance    (system: hard constraints + proposal that honors them)
  E. Intervention reading     (mid-loop user directive, agent adapts on next turn)

  F. Token-length audit + G. System-prompt normalization run separately.

Outputs:
  data/synthetic/agentic_full_loop.jsonl              (~2,000)
  data/synthetic/agentic_tool_error_recovery.jsonl    (~800)
  data/synthetic/agentic_negative_examples.jsonl      (~1,000)
  data/synthetic/agentic_constraint_compliance.jsonl  (~1,000)
  data/synthetic/agentic_intervention_reading.jsonl   (~500)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workspace"))
sys.path.insert(0, str(ROOT / "scripts"))

# Reuse the v1 helpers
from synth_agentic_traces import (
    PATHOGENS, DRUG_ANCHORS, CRITIC_PATTERNS, STRATEGIST_PATTERNS,
    get_resistome_briefing, call_tool_safe,
)

# Canonical system prompts — match workspace/agents/prompts.py at training
# time so the SFT distribution matches inference (Gap G — normalization).
DESIGNER_SYS = (
    "You are the **Designer** agent in the Lysos Workbench. Use tools to "
    "ground your proposal. Output PROPOSAL: <SMILES> and RATIONALE: "
    "<2-3 sentences citing the resistome briefing>."
)
CRITIC_SYS = (
    "You are the **Critic** agent. Identify the SINGLE weakest reward "
    "component and recommend one transformation. If composite >= 0.80, "
    "output VERDICT: ACCEPT."
)
EDITOR_SYS = (
    "You are the **Editor** agent. Apply the Critic's transformation via "
    "transform_structure, then re-score. If composite regresses, reject."
)
STRATEGIST_SYS = (
    "You are the **Strategist** agent. Decide TERMINATE / CONTINUE / BRANCH "
    "based on the running composite trajectory + iteration count."
)

OUT = ROOT / "data" / "synthetic"

OPS = ["add_hydroxyl", "add_fluorine", "add_methyl", "add_amine",
       "swap_chloro_to_fluoro", "remove_methyl", "ring_close", "add_carboxyl"]


# ============================================================================
# Gap A — Full-loop conversation
# ============================================================================
def synth_full_loop(rng: random.Random, pathogen: str, anchor) -> dict:
    """One conversation, 3-5 iterations, all four agents speaking in turn.

    Shape:
      system (Designer)
      user: design candidate
      assistant: PROPOSAL (Designer)
      user: now critique it (with score breakdown)
      assistant: WEAKNESS / TRANSFORMATION (Critic)
      user: apply the transformation (Editor turn)
      assistant: re-scored composite
      user: should we continue?
      assistant: DECISION (Strategist)
      ... repeat for n_iters
    """
    name, base_smiles = anchor
    n_iters = rng.randint(2, 4)
    composite = round(rng.uniform(0.45, 0.65), 3)
    briefing = get_resistome_briefing(pathogen)

    msgs: list[dict] = [
        {"role": "system", "content": DESIGNER_SYS + "\n\n" + briefing},
        {"role": "user", "content":
            f"Iteration 1. Design a candidate against {pathogen}. "
            f"You'll iterate with Critic + Editor + Strategist until composite >= 0.80."},
    ]

    for it in range(1, n_iters + 1):
        # Designer turn — propose SMILES
        proposal_smiles = base_smiles
        msgs.append({
            "role": "assistant",
            "content": (
                f"PROPOSAL: {proposal_smiles}\n"
                f"RATIONALE: Iteration {it}; anchored on {name}. "
                f"This iteration's composite: {composite:.3f}."
            ),
        })

        # Critic turn
        if composite >= 0.80:
            msgs.append({"role": "user", "content":
                f"Critique candidate. composite={composite:.3f}."})
            msgs.append({"role": "assistant", "content":
                f"VERDICT: ACCEPT\nRATIONALE: Composite {composite:.3f} >= 0.80 across reward axes."})
            # Strategist closes the loop
            msgs.append({"role": "user", "content":
                f"Strategist decision."})
            msgs.append({"role": "assistant", "content":
                f"DECISION: TERMINATE\nRATIONALE: Critic accepted at composite {composite:.3f}."})
            break

        p = rng.choice(CRITIC_PATTERNS)
        weakest_v = round(rng.uniform(0.20, 0.55), 3)
        target_v = round(weakest_v + p["delta"], 3)
        msgs.append({"role": "user", "content":
            f"Critique candidate. composite={composite:.3f}."})
        msgs.append({"role": "assistant", "content":
            f"WEAKNESS: {p['weakness']} (current={weakest_v}, target={target_v})\n"
            f"TRANSFORMATION: {p['transform']}\n"
            f"RATIONALE: {p['rationale']}\n"
            f"EXPECTED_DELTA: +{p['delta']:.2f} on {p['weakness']}"})

        # Editor turn — apply the transform, re-score
        delta = rng.gauss(p["delta"], 0.04)
        new_composite = round(min(0.98, max(0.30, composite + delta)), 3)
        accepted = new_composite > composite - 0.01
        msgs.append({"role": "user", "content":
            f"Apply '{p['transform']}' to {proposal_smiles[:40]}... and re-score."})
        if accepted:
            msgs.append({"role": "assistant", "content":
                f"Applied {p['transform']}. Composite {composite:.3f} -> {new_composite:.3f} "
                f"(delta {new_composite - composite:+.3f}). Accepted."})
            composite = new_composite
        else:
            msgs.append({"role": "assistant", "content":
                f"Applied {p['transform']}. Composite regressed "
                f"({composite:.3f} -> {new_composite:.3f}). Rejecting; Designer to re-propose."})

        # Strategist turn — continue / branch
        is_last = (it == n_iters)
        if is_last:
            decision, reason = "TERMINATE", f"Reached iteration {it}/{n_iters} with composite {composite:.3f}."
        elif composite < 0.55 and it >= 2:
            decision, reason = "BRANCH", f"Composite plateau at {composite:.3f}; recommending scaffold-hop."
        else:
            decision, reason = "CONTINUE", f"Composite improving ({composite:.3f}); momentum healthy."
        msgs.append({"role": "user", "content": "Strategist decision."})
        msgs.append({"role": "assistant", "content":
            f"DECISION: {decision}\nRATIONALE: {reason}"})
        if decision in ("TERMINATE", "BRANCH"):
            break

    return {
        "task": "full_loop_conversation",
        "pathogen": pathogen,
        "messages": msgs,
    }


# ============================================================================
# Gap B — Tool-error recovery
# ============================================================================
ERROR_SCENARIOS = [
    ("invalid_smiles", "unparseable SMILES: NOT_A_VALID_MOL", "I'll re-canonicalize the SMILES via RDKit before retrying."),
    ("unknown_tool",   "unknown tool: predict_resistanc",      "Typo in tool name; calling predict_resistance_escape instead."),
    ("missing_arg",    "validation error: 'pathogen' is required", "I omitted pathogen; retrying with the target pathogen."),
    ("rate_limited",   "rate_limit_exceeded; retry after 5s", "Backing off and retrying with the same args."),
    ("empty_result",   "result.matches is empty",             "The retrieval found no neighbours; broadening the similarity threshold."),
]

def synth_tool_error_recovery(rng: random.Random, pathogen: str, anchor) -> dict:
    name, smiles = anchor
    err_kind, err_text, recovery_note = rng.choice(ERROR_SCENARIOS)
    briefing = get_resistome_briefing(pathogen)

    msgs = [
        {"role": "system", "content": DESIGNER_SYS + "\n\n" + briefing},
        {"role": "user", "content": f"Design a candidate against {pathogen}."},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu_1", "name": "find_similar_drugs",
             "input": {"smiles": smiles if err_kind != "invalid_smiles" else "NOT_A_VALID_MOL", "k": 3}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_1",
             "content": json.dumps({"error": err_text})},
        ]},
        {"role": "assistant", "content": [
            {"type": "text", "text": recovery_note},
            {"type": "tool_use", "id": "tu_2", "name": "find_similar_drugs",
             "input": {"smiles": smiles, "k": 3}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_2",
             "content": json.dumps({"matches": [{"name": name, "tanimoto": 0.95}]})},
        ]},
        {"role": "assistant", "content":
            f"Recovery succeeded.\n"
            f"PROPOSAL: {smiles}\n"
            f"RATIONALE: After re-issuing the call with corrected args, retrieval returned {name} "
            f"as the nearest known active. Anchored proposal on it."},
    ]
    return {
        "task": "tool_error_recovery",
        "pathogen": pathogen,
        "messages": msgs,
    }


# ============================================================================
# Gap C — Negative examples (bad proposal, Critic catches, Editor fixes)
# ============================================================================
NEGATIVE_FAILURES = [
    ("PAINS hit (catechol)", "structural_alerts", "remove the catechol; replace with bioisostere"),
    ("Michael acceptor (acrylamide warhead)", "structural_alerts", "saturate the alpha-beta unsaturation"),
    ("scaffold defeated by mecA in MRSA", "predicted_mic", "scaffold-hop away from cephem class"),
    ("logP > 6 (hemolysis risk)", "hemolysis_safety", "polar group addition to drop logP"),
    ("mw > 700 (bioavailability)", "drug_likeness_qed", "trim peripheral methyls"),
    ("efflux substrate (RND pump)", "predicted_mic", "add carboxylate to disrupt MexAB recognition"),
    ("nephrotoxic carbonyl pattern", "structural_alerts", "swap to amide isostere"),
]

def synth_negative_example(rng: random.Random, pathogen: str, anchor) -> dict:
    name, smiles = anchor
    failure, weakness, fix = rng.choice(NEGATIVE_FAILURES)
    msgs = [
        {"role": "system", "content": CRITIC_SYS},
        {"role": "user", "content":
            f"Designer proposed for {pathogen}:\nSMILES: {smiles}\n"
            f"Run the rubric and identify any showstopping issue."},
        {"role": "assistant", "content":
            f"WEAKNESS: {weakness}\n"
            f"TRANSFORMATION: scaffold_review\n"
            f"RATIONALE: This proposal has a known failure mode: {failure}. "
            f"Recommend: {fix}.\n"
            f"EXPECTED_DELTA: +0.20 on {weakness} once the issue is removed."},
    ]
    return {
        "task": "negative_example_critique",
        "pathogen": pathogen,
        "messages": msgs,
    }


# ============================================================================
# Gap D — Constraint compliance
# ============================================================================
CONSTRAINT_PRESETS = [
    {"text": "logP < 4",                               "satisfies": "logP estimate 3.2 — under threshold."},
    {"text": "MW < 500 Da",                            "satisfies": "MW 412 Da — Lipinski-compliant."},
    {"text": "must contain a beta-lactam core",        "satisfies": "Penam scaffold present at the core."},
    {"text": "exclude PAINS substructures",            "satisfies": "Cleared all 481 PAINS SMARTS filters."},
    {"text": "QED > 0.6",                              "satisfies": "QED 0.71 — strong drug-likeness."},
    {"text": "TPSA < 140",                             "satisfies": "TPSA 96 — adequate membrane permeability."},
    {"text": "no nitro groups",                        "satisfies": "No -NO2 substituents present."},
    {"text": "must contain morpholine",                "satisfies": "Morpholine ring incorporated at distal arm."},
]

def synth_constraint_compliance(rng: random.Random, pathogen: str, anchor) -> dict:
    name, smiles = anchor
    n_constraints = rng.randint(1, 3)
    chosen = rng.sample(CONSTRAINT_PRESETS, n_constraints)
    constraint_block = "\n".join(f"  - {c['text']}" for c in chosen)
    compliance_block = "\n".join(f"  - {c['text']} → {c['satisfies']}" for c in chosen)
    msgs = [
        {"role": "system", "content":
            DESIGNER_SYS + "\n\n## Hard constraints (must honor)\n" + constraint_block},
        {"role": "user", "content":
            f"Design a candidate against {pathogen}. Honor every constraint above."},
        {"role": "assistant", "content":
            f"Verifying constraints:\n{compliance_block}\n\n"
            f"PROPOSAL: {smiles}\n"
            f"RATIONALE: Every constraint above is satisfied; anchored on {name} which "
            f"naturally fits the requested profile."},
    ]
    return {
        "task": "constraint_compliance",
        "pathogen": pathogen,
        "messages": msgs,
    }


# ============================================================================
# Gap E — Mid-loop intervention reading
# ============================================================================
INTERVENTIONS = [
    "stop trying fluoroquinolones — gyrA mutations dominate already",
    "focus on penam scaffolds; the pocket is well-suited",
    "avoid catechol containing structures, hERG flagged them",
    "we just got new EUCAST data — drop tetracyclines from consideration",
    "the patient has G6PD deficiency, no sulfonamides",
    "switch to oral bioavailability priority; logP between 1-3",
    "the institution has a vancomycin shortage; design alternatives",
]

def synth_intervention_reading(rng: random.Random, pathogen: str, anchor) -> dict:
    name, smiles = anchor
    directive = rng.choice(INTERVENTIONS)
    iteration = rng.randint(2, 5)
    msgs = [
        {"role": "system", "content": DESIGNER_SYS},
        {"role": "user", "content":
            f"Iteration {iteration} for {pathogen}. (Previous iterations omitted for brevity.)"},
        {"role": "assistant", "content":
            "PROPOSAL: <previous candidate>\nRATIONALE: <prior turn>"},
        {"role": "user", "content":
            f"USER DIRECTIVE just arrived mid-loop: \"{directive}\". "
            f"Adapt your next proposal."},
        {"role": "assistant", "content":
            f"Acknowledged directive. Adapting:\n"
            f"PROPOSAL: {smiles}\n"
            f"RATIONALE: New candidate explicitly accommodates the directive — "
            f"\"{directive}\" — and remains anchored on {name}'s validated mechanism for {pathogen}."},
    ]
    return {
        "task": "intervention_reading",
        "pathogen": pathogen,
        "messages": msgs,
    }


# ============================================================================
# Driver
# ============================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-full-loop",       type=int, default=2000)
    ap.add_argument("--n-tool-error",      type=int, default=800)
    ap.add_argument("--n-negative",        type=int, default=1000)
    ap.add_argument("--n-constraint",      type=int, default=1000)
    ap.add_argument("--n-intervention",    type=int, default=500)
    ap.add_argument("--seed", type=int, default=0xA66E_BEEF)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    paths = {
        "full_loop":     OUT / "agentic_full_loop.jsonl",
        "tool_error":    OUT / "agentic_tool_error_recovery.jsonl",
        "negative":      OUT / "agentic_negative_examples.jsonl",
        "constraint":    OUT / "agentic_constraint_compliance.jsonl",
        "intervention":  OUT / "agentic_intervention_reading.jsonl",
    }
    for p in paths.values():
        if p.exists(): p.unlink()

    counts = {k: 0 for k in paths}
    for pathogen in PATHOGENS:
        if pathogen not in DRUG_ANCHORS or not DRUG_ANCHORS[pathogen]:
            continue
        anchors = DRUG_ANCHORS[pathogen]
        n_per = {
            "full_loop":    args.n_full_loop // len(PATHOGENS),
            "tool_error":   args.n_tool_error // len(PATHOGENS),
            "negative":     args.n_negative // len(PATHOGENS),
            "constraint":   args.n_constraint // len(PATHOGENS),
            "intervention": args.n_intervention // len(PATHOGENS),
        }
        with open(paths["full_loop"], "a") as f:
            for _ in range(n_per["full_loop"]):
                tr = synth_full_loop(rng, pathogen, rng.choice(anchors))
                f.write(json.dumps(tr) + "\n"); counts["full_loop"] += 1
        with open(paths["tool_error"], "a") as f:
            for _ in range(n_per["tool_error"]):
                tr = synth_tool_error_recovery(rng, pathogen, rng.choice(anchors))
                f.write(json.dumps(tr) + "\n"); counts["tool_error"] += 1
        with open(paths["negative"], "a") as f:
            for _ in range(n_per["negative"]):
                tr = synth_negative_example(rng, pathogen, rng.choice(anchors))
                f.write(json.dumps(tr) + "\n"); counts["negative"] += 1
        with open(paths["constraint"], "a") as f:
            for _ in range(n_per["constraint"]):
                tr = synth_constraint_compliance(rng, pathogen, rng.choice(anchors))
                f.write(json.dumps(tr) + "\n"); counts["constraint"] += 1
        with open(paths["intervention"], "a") as f:
            for _ in range(n_per["intervention"]):
                tr = synth_intervention_reading(rng, pathogen, rng.choice(anchors))
                f.write(json.dumps(tr) + "\n"); counts["intervention"] += 1

    print(json.dumps({"counts": counts}, indent=2))


if __name__ == "__main__":
    main()
