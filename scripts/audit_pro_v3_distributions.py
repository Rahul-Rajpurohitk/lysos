"""Multi-axis distribution audit on the agentic subset of pro-v3.

Reports per:
  - pathogen
  - task type
  - agent role
  - tool name (which tools get called)
  - iteration depth (number of assistant turns)
  - reward component critiqued
  - transformation op applied
  - strategist decision (T/C/B)
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from datasets import load_from_disk

ROOT = Path(__file__).resolve().parents[1]
ds = load_from_disk(str(ROOT / "data" / "processed" / "amr-stage2-pro-v3"))

# Limit to the agentic synth subset where the patterns we care about exist
AGENTIC_TASKS = {
    "designer_multi_turn_tool_use", "critic_evaluate", "strategist_decide",
    "designer_resistome_conditioned", "predict_resistance_escape",
    "explain_resistance_mechanism", "design_against_resistance_pathway",
    "full_loop_conversation", "tool_error_recovery",
    "negative_example_critique", "constraint_compliance",
    "intervention_reading",
    "editor_apply_transform", "validity_critique",
    "strategist_branch_terminate", "long_conversation",
    "drug_class_prior", "mechanism_cot", "pareto_selection",
    "trajectory_pattern", "loop_recovery_classhop", "scaffold_hop_explicit",
}
TOOL_TASK_PREFIX = "tool_use_"

REWARD_COMPONENTS = ["predicted_mic", "drug_likeness_qed", "synthesizability",
                     "structural_alerts", "hemolysis_safety", "novelty",
                     "embedding_novelty", "validity"]
TRANSFORM_OPS = ["add_hydroxyl", "add_fluorine", "add_methyl", "add_amine",
                 "swap_chloro_to_fluoro", "remove_methyl", "ring_close",
                 "add_carboxyl", "scaffold_hop", "scaffold_review"]
TOOL_NAMES = ["get_pathogen_resistome", "find_similar_drugs",
              "find_active_against_mdr", "check_resistance_genes",
              "find_target_structure", "score_molecule", "predict_admet",
              "predict_complex_structure", "transform_structure",
              "scaffold_hop", "predict_synthesis_route", "estimate_synth_cost",
              "explain_mechanism", "compare_molecules"]

by_pathogen = Counter()
by_task = Counter()
by_role = Counter()
by_tool = Counter()
by_iter_depth = Counter()
by_reward = Counter()
by_transform = Counter()
by_decision = Counter()

for split in ("train", "valid"):
    for row in ds[split]:
        task = row["task"]
        if task not in AGENTIC_TASKS and not task.startswith(TOOL_TASK_PREFIX):
            continue
        by_task[task] += 1
        by_pathogen[row.get("pathogen") or "?"] += 1

        msgs = row["messages"]
        if isinstance(msgs, str):
            try: msgs = json.loads(msgs)
            except: continue
        text_blob = ""
        n_assistant = 0
        for m in msgs:
            r = m.get("role")
            if r == "assistant":
                n_assistant += 1
                # Try to attribute the assistant role from content patterns
                c = m.get("content")
                if isinstance(c, str):
                    if "PROPOSAL:" in c: by_role["designer"] += 1
                    elif "WEAKNESS:" in c or "VERDICT:" in c: by_role["critic"] += 1
                    elif "DECISION:" in c: by_role["strategist"] += 1
                    elif "Applied" in c and "regress" in c: by_role["editor"] += 1
                    elif "Applied" in c: by_role["editor"] += 1
                    text_blob += c + "\n"
                elif isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict):
                            if b.get("type") == "tool_use":
                                by_tool[b.get("name", "?")] += 1
                            elif isinstance(b.get("text"), str):
                                text_blob += b["text"] + "\n"
            elif r == "user":
                c = m.get("content")
                if isinstance(c, str): text_blob += c + "\n"

        by_iter_depth[min(8, n_assistant)] += 1

        # Reward components mentioned
        for comp in REWARD_COMPONENTS:
            if comp in text_blob: by_reward[comp] += 1

        # Transformation ops mentioned
        for op in TRANSFORM_OPS:
            if op in text_blob: by_transform[op] += 1

        # Strategist decision
        m = re.search(r"DECISION:\s*(TERMINATE|CONTINUE|BRANCH)", text_blob)
        if m: by_decision[m.group(1)] += 1

def report(name, counter, sort_by_value=True):
    print(f"\n=== {name} ({sum(counter.values()):,} total) ===")
    items = counter.most_common() if sort_by_value else sorted(counter.items())
    if not items:
        print("  (empty)")
        return
    mx = max(c for _, c in items)
    for k, c in items[:20]:
        bar = "█" * int(40 * c / mx) if mx else ""
        pct = 100 * c / sum(counter.values())
        print(f"  {str(k):<36s} {c:>8,}  {pct:>5.1f}%  {bar}")
    if len(items) > 20:
        print(f"  ... and {len(items) - 20} more")

print("=" * 70)
print(f"AGENTIC SUBSET — {by_task.total():,} rows across {len(by_task)} task types")
print("=" * 70)
report("Pathogens", by_pathogen)
report("Tasks", by_task)
report("Agent role attribution (assistant turns)", by_role)
report("Tool calls (by name)", by_tool)
report("Iteration depth (assistant-turn count per row)", by_iter_depth, sort_by_value=False)
report("Reward components critiqued", by_reward)
report("Transformation ops mentioned", by_transform)
report("Strategist decisions", by_decision)
