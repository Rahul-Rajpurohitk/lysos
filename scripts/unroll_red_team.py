"""Unroll sprint16_red_team.yaml into Stage-2 SFT rows.

For every record in the YAML (pathogen × drug × escape mutations) we emit
three independent SFT examples:

  1. predict_resistance_escape — given (drug, pathogen) → return mutation
     ledger with target gene, mechanism, fold-shift, time-to-failure.

  2. why_does_X_fail — mechanistic CoT explaining the molecular reason a
     specific mutation defeats the drug.

  3. design_against_pathogen_with_X_resistance — conditioned generation
     that explicitly avoids the listed mechanism.

Output:
  data/synthetic/agentic_red_team.jsonl

Then build_stage2_pro_v3.py picks it up automatically (added to its
JSONL_FILES list).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = ROOT / "data" / "cot" / "sprint16_red_team.yaml"
OUT_PATH = ROOT / "data" / "synthetic" / "agentic_red_team.jsonl"


def render_predict_escape(rec: dict) -> dict:
    drug = rec["drug"]
    pathogen = rec["pathogen"]
    drug_class = rec.get("drug_class", "?")
    muts = rec["escape_mutations"]
    # Format the ledger in JSON for the assistant turn (matches the tool output)
    ledger = [
        {
            "target": m["target"],
            "mutation": m["mutation"],
            "mechanism": m["mechanism"],
            "fold_shift_mic": m.get("fold_shift_mic"),
            "population_frequency": m.get("population_frequency"),
            "time_to_failure_months": m.get("time_to_failure_months"),
            "cross_resistance": m.get("cross_resistance", []),
        }
        for m in muts
    ]
    return {
        "task": "predict_resistance_escape",
        "pathogen": pathogen,
        "messages": [
            {"role": "system", "content":
                "You are an antimicrobial-resistance analyst. Given a drug and pathogen, "
                "return the catalogued escape mutations with mechanism, fold-shift in MIC, "
                "population frequency, and projected time-to-failure under continuous selection."},
            {"role": "user", "content":
                f"Drug: {drug} (class: {drug_class})\n"
                f"Pathogen: {pathogen}\n\n"
                f"List the predicted escape mutations and mechanisms."},
            {"role": "assistant", "content":
                json.dumps({"escape_mutations": ledger,
                            "n_mutations": len(ledger),
                            "drug": drug,
                            "pathogen": pathogen}, indent=2)},
        ],
    }


def render_mechanism_cot(rec: dict) -> list[dict]:
    """One row per top mutation with mechanistic chain-of-thought."""
    drug = rec["drug"]
    pathogen = rec["pathogen"]
    out = []
    for m in rec["escape_mutations"]:
        rationale = (
            f"The mutation {m['mutation']} sits in {m['target']}. "
            f"Mechanism: {m['mechanism']}. "
            f"This shifts MIC ~{m.get('fold_shift_mic', '?')}x, "
            f"observed at population frequency {m.get('population_frequency', '?')}; "
            f"time-to-failure under continuous selection is ~{m.get('time_to_failure_months', '?')} months."
        )
        if m.get("cross_resistance"):
            rationale += f" Cross-resistance to: {', '.join(m['cross_resistance'])}."
        out.append({
            "task": "explain_resistance_mechanism",
            "pathogen": pathogen,
            "messages": [
                {"role": "system", "content":
                    "You are a clinical microbiologist. Explain why a specific mutation "
                    "defeats a specific antibiotic in molecular detail."},
                {"role": "user", "content":
                    f"Why does {pathogen} carrying the {m['target']} mutation "
                    f"\"{m['mutation']}\" stop responding to {drug}?"},
                {"role": "assistant", "content": rationale},
            ],
        })
    return out


def render_design_avoiding(rec: dict) -> dict:
    """Conditioned generation that AVOIDS the listed escape mechanism."""
    drug = rec["drug"]
    pathogen = rec["pathogen"]
    drug_class = rec.get("drug_class", "?")
    # Pick the strongest mutation (highest fold_shift_mic) as the target
    muts = sorted(rec["escape_mutations"],
                  key=lambda x: x.get("fold_shift_mic", 0), reverse=True)
    top = muts[0]
    rationale = (
        f"The dominant escape pathway for {drug} in {pathogen} is "
        f"{top['target']} {top['mutation']} ({top['mechanism']}). "
        f"To dodge it, propose a candidate that either "
        f"(a) changes the drug class entirely, or "
        f"(b) preserves binding even when {top['target']} is altered. "
        f"A class-shift away from {drug_class} is the safer first move."
    )
    return {
        "task": "design_against_resistance_pathway",
        "pathogen": pathogen,
        "messages": [
            {"role": "system", "content":
                "You are the Designer agent. The user wants a candidate that avoids "
                "a specific known resistance mechanism."},
            {"role": "user", "content":
                f"Design a candidate against {pathogen} that AVOIDS the dominant "
                f"escape pathway documented for {drug}: {top['target']} {top['mutation']}.\n"
                f"Class to avoid: {drug_class}."},
            {"role": "assistant", "content":
                f"PROPOSAL_PATHWAY: scaffold-hop away from {drug_class}\n"
                f"RATIONALE: {rationale}"},
        ],
    }


def main():
    data = yaml.safe_load(YAML_PATH.read_text())
    records = data["records"]
    rows: list[dict] = []
    for rec in records:
        rows.append(render_predict_escape(rec))
        rows.extend(render_mechanism_cot(rec))
        rows.append(render_design_avoiding(rec))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    by_task: dict[str, int] = {}
    for r in rows:
        by_task[r["task"]] = by_task.get(r["task"], 0) + 1
    print(f"✅ Wrote {len(rows)} rows → {OUT_PATH}")
    for t, n in sorted(by_task.items(), key=lambda kv: -kv[1]):
        print(f"  {t:42s} {n:>5}")


if __name__ == "__main__":
    main()
