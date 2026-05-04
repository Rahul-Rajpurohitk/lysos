"""Teacher distillation via cloud Claude (#10 from audit).

Uses Anthropic Claude Opus 4.7 (or fallback model) to play Designer ↔ Critic
on real PDB-anchored design targets. Produces high-quality multi-turn agent
traces that template synthesis cannot match.

Default mode: --dry_run prints the target list and skipping API calls.
Live mode: --live --budget_usd 50 actually spends money. The user must opt in
explicitly via --live AND --budget_usd > 0.

Output:
  data/synthetic/agentic_teacher_distill.jsonl

Cost guard:
  - Default budget cap: $50
  - Per-trace estimate: ~$0.04 (Opus 4.7 input + output for ~3K tokens each)
  - Target: ~1,000 traces

Run (dry):
  /tmp/lysos_venv/bin/python scripts/teacher_distill.py --dry_run
Run (live):
  /tmp/lysos_venv/bin/python scripts/teacher_distill.py --live --budget_usd 50 --n 1000
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "synthetic" / "agentic_teacher_distill.jsonl"

PDB_TARGETS = [
    {"pathogen": "MRSA", "target": "PBP2a", "pdb": "1VQQ",
     "rationale": "mecA-encoded transpeptidase; allosteric site engaged by ceftaroline"},
    {"pathogen": "MRSA", "target": "PBP2a", "pdb": "5M18",
     "rationale": "PBP2a in covalent complex with ceftaroline"},
    {"pathogen": "Mtb", "target": "InhA", "pdb": "2NSD",
     "rationale": "enoyl-ACP reductase; INH-NAD adduct binds catalytic Tyr-158"},
    {"pathogen": "Mtb", "target": "RpoB", "pdb": "5UAQ",
     "rationale": "RNA pol; rpoB-S531L is the dominant rifampin-R mutation"},
    {"pathogen": "Mtb", "target": "KatG", "pdb": "1SJ2",
     "rationale": "catalase-peroxidase; activates INH; S315T loss-of-function"},
    {"pathogen": "EColi-CRE", "target": "KPC-2", "pdb": "6Q9B",
     "rationale": "class A serine carbapenemase; covalent avibactam binder at Ser-70"},
    {"pathogen": "EColi-CRE", "target": "NDM-1", "pdb": "3SPU",
     "rationale": "class B Zn-MBL; resistant to avibactam, susceptible to siderophore-cefiderocol"},
    {"pathogen": "EColi-CRE", "target": "OXA-48", "pdb": "3HBR",
     "rationale": "class D carbapenemase; widespread in N. Africa/M. East"},
    {"pathogen": "KpneuCRE", "target": "KPC-3", "pdb": "5VFA",
     "rationale": "KPC variant; D179Y reduces avibactam binding ~10x"},
    {"pathogen": "Abaum", "target": "OXA-23", "pdb": "4JF6",
     "rationale": "class D; durlobactam covalent binder unique among DBOs"},
    {"pathogen": "Paer", "target": "PBP3", "pdb": "3OG7",
     "rationale": "essential transpeptidase; ceftolozane modified side chain"},
    {"pathogen": "Paer", "target": "MexAB-OprM", "pdb": "5O8R",
     "rationale": "tripartite efflux; broad-spectrum drug pump"},
    {"pathogen": "VRE", "target": "VanA", "pdb": "1IOG",
     "rationale": "D-Ala:D-Lac ligase; precursor remodeling vs vancomycin"},
    {"pathogen": "NGono", "target": "PBP2 (penA mosaic)", "pdb": "6P58",
     "rationale": "mosaic XXXIV reduces ceftriaxone affinity"},
    {"pathogen": "NGono", "target": "GyrB", "pdb": "5N6S",
     "rationale": "type II topo; zoliflodacin binds (FDA submitted 2025)"},
]


def make_seed_brief(target: dict) -> str:
    return (
        f"DESIGN BRIEF\n"
        f"  Pathogen: {target['pathogen']}\n"
        f"  Target: {target['target']} (PDB: {target['pdb']})\n"
        f"  Rationale: {target['rationale']}\n\n"
        f"Run a 6-8 turn Designer↔Critic loop. Designer proposes 2-3 candidate "
        f"SMILES, calls in silico panel (predict_mic_pathogen, predict_admet, "
        f"score_molecule), reads results, iterates via scaffold_hop on the "
        f"weakest pillar. Critic does adversarial review (PAINS, novelty, "
        f"escape mutations). Final candidate written with structured rationale.\n"
        f"\n"
        f"Use abstracted category tokens for any out-of-scope concepts; never "
        f"emit literal CW/select-agent names. Stay strictly antimicrobial."
    )


def estimate_cost(n_traces: int, in_tok_per_trace: int = 1500,
                   out_tok_per_trace: int = 2500) -> float:
    """Claude Opus 4.7 pricing: ~$15/M input, ~$75/M output."""
    in_cost = (in_tok_per_trace * n_traces / 1_000_000) * 15
    out_cost = (out_tok_per_trace * n_traces / 1_000_000) * 75
    return in_cost + out_cost


def call_claude_designer_critic(client, target: dict, model_id: str,
                                  max_tokens: int = 3000) -> str | None:
    brief = make_seed_brief(target)
    system = (
        "You play BOTH Designer and Critic agents. Output a 6-8 turn dialogue "
        "in this format:\n\n"
        "[Designer]: ...\n"
        "[Tool]: predict_mic_pathogen({...}) → {...}\n"
        "[Designer]: ...\n"
        "[Critic]: ...\n"
        "[Designer]: ...\n"
        "[Final]: <structured candidate report>\n\n"
        "All molecules must be antimicrobial (target the named bacterial protein). "
        "Use abstracted category tokens for any out-of-scope concept; never emit "
        "literal CW/select-agent/controlled-substance names. Output is plain text."
    )
    try:
        msg = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": brief}],
        )
        return msg.content[0].text
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000,
                    help="Number of teacher traces to generate")
    ap.add_argument("--budget_usd", type=float, default=50.0,
                    help="Hard ceiling on API spend")
    ap.add_argument("--dry_run", action="store_true",
                    help="Don't actually call the API; print plan")
    ap.add_argument("--live", action="store_true",
                    help="Required to enable real API calls")
    ap.add_argument("--model", default="claude-opus-4-7")
    ap.add_argument("--seed", type=int, default=0xDA5_AB1F)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    estimated = estimate_cost(args.n)
    print(f"Plan: {args.n} traces from {len(PDB_TARGETS)} PDB targets.")
    print(f"  Model: {args.model}")
    print(f"  Estimated cost: ${estimated:.2f}")
    print(f"  Budget ceiling: ${args.budget_usd:.2f}")
    if estimated > args.budget_usd:
        print(f"  → estimate exceeds budget. Trimming to fit budget.")
        max_traces = int((args.budget_usd / estimated) * args.n)
        args.n = max_traces
        print(f"  → reduced to {args.n} traces.")

    if args.dry_run or not args.live:
        print(f"\n=== DRY RUN ===")
        print(f"PDB targets to seed:")
        for t in PDB_TARGETS:
            print(f"  {t['pathogen']:10s} {t['target']:15s} (PDB: {t['pdb']})")
        print(f"\nTo actually run: --live --budget_usd 50 --n 1000")
        print(f"\nAPI requirements:")
        print(f"  ANTHROPIC_API_KEY environment variable required")
        print(f"  pip install anthropic")
        return 0

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. Aborting.")
        return 1

    try:
        from anthropic import Anthropic
    except ImportError:
        print("ERROR: 'anthropic' package not installed. Run: pip install anthropic")
        return 1

    client = Anthropic(api_key=api_key)
    if OUT.exists(): OUT.unlink()
    n_done = 0
    spent_usd = 0.0
    with open(OUT, "a") as f:
        for i in range(args.n):
            target = rng.choice(PDB_TARGETS)
            text = call_claude_designer_critic(client, target, args.model)
            if text is None:
                continue
            row = {
                "task": "teacher_distill",
                "pathogen": target["pathogen"],
                "target": target["target"],
                "pdb": target["pdb"],
                "messages": [
                    {"role": "system",
                     "content": ("Designer↔Critic dialogue produced by teacher model. "
                                 "Distilled into Lysos for high-quality reasoning patterns.")},
                    {"role": "user", "content": make_seed_brief(target)},
                    {"role": "assistant", "content": text},
                ],
            }
            f.write(json.dumps(row) + "\n")
            n_done += 1
            spent_usd += estimate_cost(1)
            if n_done % 10 == 0:
                print(f"  done {n_done}/{args.n}  spent ≈ ${spent_usd:.2f}")
            if spent_usd >= args.budget_usd:
                print(f"  Budget reached (${spent_usd:.2f}). Stopping.")
                break
            time.sleep(0.3)  # gentle rate limit

    print(f"\nWrote {n_done} traces to {OUT}")
    print(f"Spent ≈ ${spent_usd:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
