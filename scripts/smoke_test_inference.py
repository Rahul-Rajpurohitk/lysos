"""Inference smoke test for LysosGenerator API surface (no GPU, no Gemma).

Loads a tiny ungated chat model (HuggingFaceTB/SmolLM2-135M-Instruct) into
LysosGenerator to verify the entire wiring works end-to-end:
  - prompt builder for each pathogen
  - tokenizer chat-template compatibility
  - generation call signature
  - candidate parsing (SMILES extraction from output)
  - scoring stack on the generated outputs
  - to_dict serialization

The MODEL output will be junk (it's a 135M general-chat model, not Gemma 4
31B), but the API SURFACE is exactly what'll run on the MI300X. Catches
shape/signature/import/template bugs before kickoff.

Run:
  python scripts/smoke_test_inference.py
  python scripts/smoke_test_inference.py --target MRSA --n 3
"""
import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Tiny ungated chat model — same chat-template machinery as Gemma 4
SMOKE_MODEL = "HuggingFaceTB/SmolLM2-135M-Instruct"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=SMOKE_MODEL,
                    help=f"HF model for smoke test (default {SMOKE_MODEL})")
    ap.add_argument("--target", default="MRSA",
                    help="Pathogen to design against (default MRSA)")
    ap.add_argument("--n", type=int, default=2,
                    help="Number of candidates to generate (default 2)")
    args = ap.parse_args()

    failures = []

    print(f"=== Inference API surface smoke test ===")
    print(f"  Smoke model: {args.model}")
    print(f"  (Note: outputs will be junk — this only verifies the API surface)")

    print(f"\n[1/5] Importing LysosGenerator...")
    try:
        from src.inference.generate import LysosGenerator, PATHOGEN_CATALOG, Candidate
        print(f"  ✓ LysosGenerator imported")
        print(f"  ✓ PATHOGEN_CATALOG has {len(PATHOGEN_CATALOG)} pathogens: "
              f"{list(PATHOGEN_CATALOG.keys())}")
    except Exception as e:
        failures.append(f"Import failed: {e}")
        print(f"  ❌ {e}")
        return 1

    print(f"\n[2/5] Verify pathogen catalog has all 8 priority pathogens...")
    EXPECTED = {"MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
                "Abaum", "Paer", "VRE", "NGono"}
    missing = EXPECTED - set(PATHOGEN_CATALOG)
    if missing:
        failures.append(f"Pathogens missing from catalog: {missing}")
        print(f"  ❌ Missing: {missing}")
    else:
        print(f"  ✓ all 8 priority pathogens present")

    print(f"\n[3/5] Instantiate generator with smoke model...")
    try:
        gen = LysosGenerator(model_id=args.model)
        print(f"  ✓ instantiated (model_id={gen.model_id})")
    except Exception as e:
        failures.append(f"Instantiation failed: {e}")
        print(f"  ❌ {e}")
        return 1

    print(f"\n[4/5] Run design() on target={args.target} n={args.n}...")
    try:
        candidates = gen.design(target=args.target, n=args.n)
        print(f"  ✓ design() returned {len(candidates)} candidates")
        for i, c in enumerate(candidates):
            preview = (c.smiles or "[no smiles parsed]")[:80]
            print(f"    [{i}] smiles={preview!r} valid={c.scores.get('validity', '?')}")
    except Exception as e:
        failures.append(f"design() failed: {e}")
        print(f"  ❌ {e}")
        return 1

    print(f"\n[5/5] Verify Candidate.to_dict() serialization...")
    if candidates:
        d = candidates[0].to_dict()
        if not isinstance(d, dict):
            failures.append(f"to_dict returned {type(d)}, expected dict")
        elif "smiles" not in d:
            failures.append("to_dict missing 'smiles' key")
        else:
            print(f"  ✓ to_dict returned dict with keys: {list(d.keys())}")

    print(f"\n{'='*70}")
    if failures:
        print(f"❌ {len(failures)} FAILURES:")
        for f in failures:
            print(f"   - {f}")
        return 1
    print(f"✅ ALL CHECKS PASSED — LysosGenerator API surface clean")
    print(f"   When the trained Gemma 4 31B model is on HF, swap --model and ship.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
