"""Build stage2-pro-v4 — the final pre-GPU dataset.

Closes audit gaps #2, #3, #5, #6, #7, #8, #9, #10, #12 on top of pro-v3.

What's new vs pro-v3:
  - tool_call_with_result            from agentic_tool_results.jsonl (3,950)
  - long_form_designer_loop          from agentic_long_form_traces.jsonl (5,000)
  - pk_steady_state / renal / ddi    from agentic_pk_panel.jsonl (468)
  - decoy_negative                   from agentic_decoy_negatives.jsonl (~5K)
  - activity_cliff                   from agentic_activity_cliffs.jsonl (~1K)
  - smiles_aug                       from agentic_smiles_augmented.jsonl (~400K)
  - teacher_distill                  from agentic_teacher_distill.jsonl (when API spend approved)
  - PATHOGEN_PRIMER applied to all pathogen=None rows (8 priority pathogens)
  - TASK COLLAPSE: 108 → ~40 task buckets via canonical mapping

Output:
  data/processed/amr-stage2-pro-v4

Run:
  /tmp/lysos_venv/bin/python scripts/build_stage2_pro_v4.py
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

from datasets import Dataset, DatasetDict, load_from_disk

ROOT = Path(__file__).resolve().parents[1]
PRO_V3 = ROOT / "data" / "processed" / "amr-stage2-pro-v3"
OUT_DIR = ROOT / "data" / "processed" / "amr-stage2-pro-v4"

# New JSONL files we add on top of pro-v3
NEW_JSONL_FILES = [
    ("tool_call_with_result",   ROOT / "data" / "synthetic" / "agentic_tool_results.jsonl"),
    ("long_form_designer_loop", ROOT / "data" / "synthetic" / "agentic_long_form_traces.jsonl"),
    ("pk_panel",                ROOT / "data" / "synthetic" / "agentic_pk_panel.jsonl"),
    ("decoy_negative",          ROOT / "data" / "synthetic" / "agentic_decoy_negatives.jsonl"),
    ("activity_cliff",          ROOT / "data" / "synthetic" / "agentic_activity_cliffs.jsonl"),
    ("smiles_aug",              ROOT / "data" / "synthetic" / "agentic_smiles_augmented.jsonl"),
    ("teacher_distill",         ROOT / "data" / "synthetic" / "agentic_teacher_distill.jsonl"),
]

PATHOGENS = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE", "Abaum", "Paer", "VRE", "NGono"]
PATHOGEN_FULL = {
    "MRSA": "methicillin-resistant Staphylococcus aureus",
    "Mtb": "Mycobacterium tuberculosis",
    "EColi-CRE": "carbapenem-resistant Escherichia coli",
    "KpneuCRE": "carbapenem-resistant Klebsiella pneumoniae",
    "Abaum": "Acinetobacter baumannii",
    "Paer": "Pseudomonas aeruginosa",
    "VRE": "vancomycin-resistant Enterococcus",
    "NGono": "Neisseria gonorrhoeae",
}

# Canonical mapping for task collapse — 108 source tasks → ~40 buckets
TASK_COLLAPSE = {
    # Name ↔ SMILES lookups (collapsed)
    "drug_smiles": "name_to_smiles",
    "drug_from_smiles": "name_to_smiles",
    "natural_product_smiles": "name_to_smiles",
    "natural_product_origin_smiles": "name_to_smiles",
    "drug_id_lookup": "name_to_smiles",
    "drug_inchi_key": "name_to_inchi",
    "drug_synonyms": "name_to_synonyms",
    "drug_cas_lookup": "name_to_cas",
    "drug_reverse_cas": "cas_to_name",
    # Activity / MIC
    "activity_prediction": "mic_prediction",
    "coadd_mic_prediction": "mic_prediction",
    "predict_mic_pathogen": "mic_prediction",
    # Generation
    "generation_for_target": "smiles_generation_pathogen",
    "peptide_design": "peptide_generation_pathogen",
    # Drug history / mechanism
    "drug_history": "drug_history",
    "explain_mechanism": "mechanism_explain",
    "mechanism_cot": "mechanism_explain",
    # Reasoning
    "abstract_summarize": "literature_reasoning",
    "abstract_qa": "literature_reasoning",
    "resistance_gene_explain": "resistance_reasoning",
    "designer_resistome_conditioned": "resistance_reasoning",
    # ADMET / Tox
    "tdc_admet_prediction": "admet_panel",
    "tdc_toxicity_prediction": "tox_panel",
    "drug_likeness": "drug_likeness",
    "safety_prediction": "safety_panel",
    # CoADD inhibition / selectivity
    "coadd_inhibition_screen": "coadd_screen",
    "coadd_selectivity_profile": "coadd_screen",
    # Natural products
    "natural_product_origin": "natural_product_origin",
    "natural_products": "natural_product_origin",
    # Editor / transforms
    "editor_apply_transform": "editor_transform",
    "editor_explicit": "editor_transform",
    "transform_structure": "editor_transform",
    "scaffold_hop": "scaffold_hop",
    "scaffold_hop_explicit": "scaffold_hop",
    # Critic
    "critic_evaluate": "critic_review",
    "validity_critique": "critic_review",
    # Strategist
    "strategist_decide": "strategist",
    "strategist_branch_terminate": "strategist",
    "strat_branch_terminate": "strategist",
    # Designer
    "designer_multi_turn_tool_use": "designer_tool_use",
    "designer_tool_use": "designer_tool_use",
    # Pareto / Trajectory
    "pareto_selection": "pareto_selection",
    "trajectory_pattern": "trajectory_pattern",
    # Loop / class priors
    "loop_recovery": "loop_recovery",
    "full_loop_conversation": "full_loop",
    "full_loop": "full_loop",
    "drug_class_prior": "class_priors",
    "class_priors": "class_priors",
    # Coverage / negative
    "tool_coverage_backfill": "tool_coverage",
    "negative_example": "negative_example",
    "constraint_compliance": "constraint_compliance",
    "intervention_reading": "intervention_reading",
    "long_conversation": "long_conversation",
    # v5 — keep individual labels
    # v6 — keep individual labels
}


def collapse_task(task: str) -> str:
    """Map a source task label to canonical bucket. Strips _smiles_aug suffix
    so augmented rows merge with their base task."""
    if isinstance(task, str) and task.endswith("_smiles_aug"):
        task = task[: -len("_smiles_aug")]
    return TASK_COLLAPSE.get(task, task)


def apply_pathogen_primer(rng: random.Random, msgs: list[dict], pathogen: str | None) -> list[dict]:
    """If pathogen is None, prepend a system-prompt context primer naming a
    randomly-chosen priority pathogen."""
    if pathogen: return msgs
    pat = rng.choice(PATHOGENS)
    primer = (
        f"Context primer: this task is being run within the Lysos antimicrobial "
        f"design context against {PATHOGEN_FULL[pat]} ({pat}). The chemistry "
        f"reasoning that follows applies to that pathogen-target frame."
    )
    if not msgs: return msgs
    if msgs[0].get("role") == "system":
        # Augment existing system prompt
        new_first = dict(msgs[0])
        new_first["content"] = (msgs[0].get("content") or "") + "\n\n" + primer
        return [new_first] + msgs[1:]
    else:
        return [{"role": "system", "content": primer}] + msgs


def normalize_jsonl_row(row: dict, task_label: str, split: str,
                         rng: random.Random, apply_primer: bool = True) -> dict | None:
    msgs = row.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return None
    pathogen = row.get("pathogen")
    if apply_primer and not pathogen:
        msgs = apply_pathogen_primer(rng, msgs, pathogen)
    row_split = row.get("split")
    final_split = row_split if row_split in ("train", "valid", "test") else split
    return {
        "task": collapse_task(row.get("task") or task_label),
        "pathogen": pathogen,
        "messages": msgs,
        "split": final_split,
    }


def normalize_pro_v3_row(row: dict, rng: random.Random) -> dict | None:
    msgs_str = row.get("messages")
    if isinstance(msgs_str, str):
        try:
            msgs = json.loads(msgs_str)
        except Exception:
            return None
    elif isinstance(msgs_str, list):
        msgs = msgs_str
    else:
        return None
    if not msgs: return None
    pathogen = row.get("pathogen")
    msgs = apply_pathogen_primer(rng, msgs, pathogen)
    return {
        "task": collapse_task(row.get("task") or "stage2_chemistry"),
        "pathogen": pathogen,
        "messages": msgs,
        "split": row.get("split") or "train",
    }


def validate_messages(msgs: list[dict]) -> bool:
    if not msgs: return False
    last = msgs[-1]
    if not isinstance(last, dict): return False
    if last.get("role") not in ("assistant", "tool"): return False
    c = last.get("content")
    if isinstance(c, str) and c.strip(): return True
    if isinstance(c, list) and c: return True
    return False


def main():
    print(f"Loading pro-v3 from {PRO_V3}")
    base = load_from_disk(str(PRO_V3))
    train_rows: list[dict] = []
    valid_rows: list[dict] = []
    test_rows: list[dict] = []

    rng = random.Random(0xCAFE_FAD3)

    print(f"  pro-v3 splits: {dict((k, len(base[k])) for k in base.keys())}")
    for r in base["train"]:
        n = normalize_pro_v3_row(r, rng)
        if n and validate_messages(n["messages"]):
            train_rows.append(n)
    for r in base["valid"]:
        n = normalize_pro_v3_row(r, rng)
        if n and validate_messages(n["messages"]):
            valid_rows.append(n)
    if "test" in base:
        for r in base["test"]:
            n = normalize_pro_v3_row(r, rng)
            if n and validate_messages(n["messages"]):
                test_rows.append(n)
    print(f"  carried over: train={len(train_rows):,} valid={len(valid_rows):,} test={len(test_rows):,}")

    # Merge in new JSONLs
    for label, path in NEW_JSONL_FILES:
        if not path.exists():
            print(f"  SKIP {label} ({path.name}) — file missing")
            continue
        with open(path) as f:
            n_added_train, n_added_valid, n_added_test, n_dropped = 0, 0, 0, 0
            for line in f:
                if not line.strip(): continue
                try:
                    row = json.loads(line)
                except Exception:
                    n_dropped += 1; continue
                split = "valid" if rng.random() < 0.05 else "train"
                norm = normalize_jsonl_row(row, label, split, rng, apply_primer=True)
                if not norm or not validate_messages(norm["messages"]):
                    n_dropped += 1; continue
                final = norm["split"]
                if final == "train":
                    train_rows.append(norm); n_added_train += 1
                elif final == "valid":
                    valid_rows.append(norm); n_added_valid += 1
                elif final == "test":
                    test_rows.append(norm); n_added_test += 1
                else:
                    n_dropped += 1
            print(f"  {label:32s} +train {n_added_train:6d}  +valid {n_added_valid:5d}  +test {n_added_test:4d}  dropped {n_dropped}")

    rng.shuffle(train_rows); rng.shuffle(valid_rows); rng.shuffle(test_rows)

    def serialize(rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            r2 = dict(r)
            r2["messages"] = json.dumps(r["messages"])
            out.append(r2)
        return out

    train_ds = Dataset.from_list(serialize(train_rows))
    valid_ds = Dataset.from_list(serialize(valid_rows))
    splits = {"train": train_ds, "valid": valid_ds}
    if test_rows:
        splits["test"] = Dataset.from_list(serialize(test_rows))
    ds = DatasetDict(splits)

    OUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    if OUT_DIR.exists():
        import shutil; shutil.rmtree(OUT_DIR)
    print(f"\nSaving to {OUT_DIR} …")
    ds.save_to_disk(str(OUT_DIR))

    test_n = len(splits["test"]) if "test" in splits else 0
    print(f"\n✅ stage2-pro-v4:  train={len(train_ds):,}  valid={len(valid_ds):,}  test={test_n:,}")
    by_task = Counter(r["task"] for r in train_rows)
    print(f"\nTotal task buckets: {len(by_task)} (was 108 in pro-v3)")
    print(f"Top 15 (train):")
    for t, n in by_task.most_common(15):
        print(f"  {t:42s} {n:>8,}")

    # Pathogen distribution audit
    pat_dist = Counter(r["pathogen"] or "(none)" for r in train_rows)
    print(f"\nPathogen distribution (train):")
    for p, n in sorted(pat_dist.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {str(p):20s} {n:>8,}")


if __name__ == "__main__":
    sys.exit(main())
