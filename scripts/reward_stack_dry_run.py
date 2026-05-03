"""End-to-end dry run of the Stage 3 reward stack on real antibiotic SMILES.

Proves the 8-component reward function actually computes on real molecules
WITHOUT the MI300X. Loads each component from configs/stage3_rl_grpo.yaml,
feeds in a curated panel of 10 known antibiotics + 5 known-bad strings (to
verify validity scores 0 for invalid SMILES), prints per-component scores,
and writes a JSON baseline.

Usage:
    python scripts/reward_stack_dry_run.py
    python scripts/reward_stack_dry_run.py --pathogen MRSA
    python scripts/reward_stack_dry_run.py --output reports/reward_baseline.json
"""
import argparse
import importlib
import json
import sys
from pathlib import Path

# Add repo root to sys.path so `src` resolves
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import yaml

CONFIG = Path("configs/stage3_rl_grpo.yaml")
DEFAULT_OUTPUT = Path("reports/reward_baseline.json")


# Real antibiotic SMILES from drugbank / chembl
PANEL = [
    # name, SMILES, expected reward profile (rough qualitative)
    ("vancomycin",   "CC1C(C(CC(O1)OC2C(C(C(OC2OC3=C4C=C5C=C3OC6=C(C=C(C=C6)C(C(=O)NC7C(=O)NC8C9=CC(=C(C=C9)O)C1=C(C=C(C=C1C(NC(=O)C(C(C1=CC(=C(O5)C=C1Cl)Cl)O)NC8=O)C(=O)O)O)O)CC(=O)N)O)C(C)NC)O)O)O)NC", "high MIC, low QED, low SA"),
    ("daptomycin",   "CCCCCCCCCC(=O)NC(CC(=O)N)C(=O)NC(CC(=O)O)C(=O)NC1C(=O)NC(C(=O)NC(C(=O)NC(C(=O)NC(C(=O)NC(C(=O)NC(C(=O)NC(C(=O)O1)CC(=O)O)CC2=CN=CC=C2)CCC(=O)O)CO)CC(=O)O)C)CC(C)C", "high MIC, low QED"),
    ("linezolid",    "CC(=O)NCC1CN(C(=O)O1)C2=CC(=C(C=C2)N3CCOCC3)F", "high QED, high SA, high all-around"),
    ("ciprofloxacin","C1CC1N2C=C(C(=O)C3=CC(=C(C=C32)N4CCNCC4)F)C(=O)O", "high QED, moderate MIC"),
    ("doxycycline",  "CC1C2CC3C(C(=O)C(=C(C3(C(=O)C2=C(C4=C1C=CC=C4O)O)O)O)C(=O)N)N(C)C", "tetracycline scaffold"),
    ("amoxicillin",  "CC1(C(N2C(S1)C(C2=O)NC(=O)C(C3=CC=C(C=C3)O)N)C(=O)O)C", "moderate MIC, high QED"),
    ("meropenem",    "CC1C2CC3=C(C(=O)N3C2C(=O)O)SC1NC(=O)CCC4CN(C4=O)CC", "carbapenem scaffold"),
    ("azithromycin", "CCC1C(C(C(N(CC(CC(C(C(C(C(C(=O)O1)C)OC2CC(C(C(O2)C)O)(C)OC)C)OC3C(C(CC(O3)C)N(C)C)O)(C)O)C)C)C)C)O)C", "macrolide scaffold"),
    ("rifampin",     "CC1C=CC=C(C(=O)NC2=C(C3=C(C(=C(C(=C3O)C(=O)C(=C(C1OC)C)O)C)O)C(=N\\N4CCN(CC4)C)/C2=O)O)C", "rifamycin scaffold"),
    ("metronidazole","CC1=NC=C(N1CCO)[N+](=O)[O-]", "small drug, high QED"),
]

INVALID = [
    ("not_a_molecule", "this is not SMILES"),
    ("empty",          ""),
    ("garbage",        "###%%% invalid ###"),
    ("partial_paren",  "C1CC("),
    ("unknown_atom",   "CXY"),
]


def load_module(spec):
    """Load a 'src.eval.rewards.X:func' spec."""
    mod_path, fn_name = spec.split(":")
    mod = importlib.import_module(mod_path)
    return getattr(mod, fn_name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pathogen", default="MRSA",
                    help="Target pathogen for activity.predict_mic (default MRSA)")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT),
                    help=f"JSON report path (default {DEFAULT_OUTPUT})")
    args = ap.parse_args()

    print(f"Loading reward config from {CONFIG}...")
    cfg = yaml.safe_load(CONFIG.read_text())
    components = cfg["reward"]["components"]
    print(f"  {len(components)} components configured")

    # Resolve each component to a callable
    fns = {}
    weights = {}
    for c in components:
        name = c["name"]
        weights[name] = c["weight"]
        try:
            fns[name] = load_module(c["module"])
        except Exception as e:
            print(f"  ⚠ Could not load {name} from {c['module']}: {e}")
            fns[name] = None

    valid_fns = {k: v for k, v in fns.items() if v is not None}
    print(f"  {len(valid_fns)}/{len(components)} components loaded successfully")

    panel_results = []
    print(f"\n{'='*70}")
    print(f"Real antibiotics panel (target_pathogen={args.pathogen}):")
    print(f"{'='*70}")
    print(f"{'name':16s} {'valid':6s} {'mic':6s} {'qed':6s} {'sa':6s} {'safe':6s} "
          f"{'tani':6s} {'embd':6s} {'alrt':6s} {'COMP':6s}")

    for name, smi, _ in PANEL:
        scores = {}
        for comp_name, fn in valid_fns.items():
            try:
                # All reward fns take a list of samples, return list of floats
                args_in = [smi]
                comp_args = next((c.get("args", {}) for c in components
                                 if c["name"] == comp_name), {})
                if comp_name == "predicted_mic":
                    comp_args = {**comp_args, "target_pathogen": args.pathogen}
                result = fn(args_in, **comp_args) if comp_args else fn(args_in)
                if isinstance(result, list):
                    result = result[0]
                scores[comp_name] = float(result)
            except Exception as e:
                scores[comp_name] = None
                print(f"  ⚠ {comp_name}({name}): {e}")

        # composite (NaN-safe: skip None components from weighted sum, normalize)
        active_w = {k: weights[k] for k, v in scores.items() if v is not None}
        wsum = sum(active_w.values()) or 1.0
        composite = sum(
            (scores[k] or 0.0) * (active_w[k] / wsum)
            for k in active_w
        )
        panel_results.append({
            "name": name, "smiles": smi, "scores": scores, "composite": composite,
        })

        v = scores.get("validity")
        m = scores.get("predicted_mic")
        q = scores.get("drug_likeness_qed")
        s = scores.get("synthesizability")
        sf = scores.get("hemolysis_safety")
        t = scores.get("novelty")
        e = scores.get("embedding_novelty")
        a = scores.get("structural_alerts")
        def fmt(x):
            return f"{x:.3f}" if isinstance(x, float) else " n/a "
        print(f"{name:16s} {fmt(v):6s} {fmt(m):6s} {fmt(q):6s} {fmt(s):6s} "
              f"{fmt(sf):6s} {fmt(t):6s} {fmt(e):6s} {fmt(a):6s} {composite:.3f}")

    print(f"\n{'='*70}")
    print(f"Invalid-SMILES sanity panel (validity should be 0.0):")
    print(f"{'='*70}")
    invalid_results = []
    for name, smi in INVALID:
        if fns.get("validity") is None:
            continue
        try:
            v = fns["validity"]([smi])[0]
        except Exception as exc:
            v = None
        invalid_results.append({"name": name, "smiles": smi, "validity": v})
        marker = "✓" if v == 0.0 else "⚠"
        print(f"  {marker} {name:18s} → validity={v}")

    # Aggregate summary
    print(f"\n{'='*70}")
    print(f"Per-component aggregate (real-antibiotics panel, mean):")
    print(f"{'='*70}")
    for comp_name in valid_fns:
        vals = [r["scores"][comp_name] for r in panel_results
                if r["scores"][comp_name] is not None]
        if vals:
            avg = sum(vals) / len(vals)
            print(f"  {comp_name:30s}  mean={avg:.3f}  weight={weights[comp_name]:.2f}")

    # Save JSON
    out = {
        "pathogen": args.pathogen,
        "components": [c["name"] for c in components],
        "weights": weights,
        "panel_results": panel_results,
        "invalid_results": invalid_results,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2))
    print(f"\nSaved baseline to {args.output}")
    print(f"This is the reference scoreboard — re-run after Stage 3 GRPO to detect")
    print(f"reward changes (or just to confirm the stack still computes deterministically).")


if __name__ == "__main__":
    sys.exit(main() or 0)
