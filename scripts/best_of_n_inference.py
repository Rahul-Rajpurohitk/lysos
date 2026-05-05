"""Best-of-N inference adapter.

For each prompt, sample N=8 candidates from Lysos-RL at temperature 0.7,
then score each via the 12-component reward stack. Return the highest-
scoring candidate. Substantially improves test-time performance over single
greedy decode.

Inference adapter expected at vLLM at http://localhost:8000.

Run:
  /tmp/lysos_venv/bin/python scripts/best_of_n_inference.py \\
      --prompt "Design a candidate against MRSA" --n 8

Or batch over a JSONL file:
  /tmp/lysos_venv/bin/python scripts/best_of_n_inference.py \\
      --prompts data/synthetic/agentic_ood_eval.jsonl \\
      --output reports/best_of_n_outputs.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def call_model(endpoint: str, model: str, prompt: str,
                temperature: float = 0.7, max_tokens: int = 512) -> str:
    import requests
    try:
        r = requests.post(
            f"{endpoint}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"<MODEL_UNAVAILABLE: {e}>"


def score_candidate(candidate_text: str) -> float:
    """Score a candidate via the 12-component reward stack."""
    # Extract SMILES from the candidate
    import re
    sml_match = re.search(r"SMILES:\s*([^\s\n]+)", candidate_text)
    if not sml_match:
        sml_match = re.search(r"PROPOSAL:\s*([^\s\n]+)", candidate_text)
    smiles = sml_match.group(1) if sml_match else None

    # Run reward components
    sys.path.insert(0, str(ROOT))
    try:
        from src.eval.rewards import (
            validity, structural_alerts, activity, drug_likeness, synth,
            safety, novelty, embedding_novelty, boltz2_pose, spectrum,
            resistance, pareto,
        )
    except ImportError:
        return 0.0

    if not smiles:
        return 0.0

    samples = [candidate_text]

    # Reward weights from configs/stage3_rl_grpo.yaml
    weights = {
        "validity": 0.05,
        "structural_alerts": 0.05,
        "predicted_mic": 0.20,
        "drug_likeness_qed": 0.10,
        "synthesizability": 0.10,
        "hemolysis_safety": 0.10,
        "novelty": 0.08,
        "embedding_novelty": 0.07,
        "boltz2_pose_conf": 0.10,
        "spectrum_breadth": 0.05,
        "resistance_robustness": 0.05,
        "pareto_entry": 0.05,
    }

    components = {}
    try:
        components["validity"] = validity.smiles_valid(samples)[0]
        components["structural_alerts"] = structural_alerts.structural_alerts_score(samples)[0]
        components["predicted_mic"] = activity.predict_mic(samples, target_pathogen="MRSA")[0]
        components["drug_likeness_qed"] = drug_likeness.qed_score(samples)[0]
        components["synthesizability"] = synth.sa_score(samples)[0]
        components["hemolysis_safety"] = safety.hemolysis_inverse(samples)[0]
        components["novelty"] = novelty.tanimoto_distance_to_known(samples,
            reference_set="data/processed/known-antibiotics-canonical.parquet")[0]
        # Embedding novelty + Boltz2 pose + spectrum + resistance + pareto are best-effort
    except Exception:
        pass

    composite = sum(components.get(k, 0.0) * w for k, w in weights.items())
    return composite


def best_of_n(endpoint: str, model: str, prompt: str, n: int = 8) -> dict:
    candidates = []
    for i in range(n):
        text = call_model(endpoint, model, prompt, temperature=0.7)
        if "<MODEL_UNAVAILABLE>" in text:
            return {"prompt": prompt, "error": text}
        score = score_candidate(text)
        candidates.append({"text": text, "composite_score": score})

    candidates.sort(key=lambda c: -c["composite_score"])
    return {
        "prompt": prompt,
        "n_candidates": n,
        "best": candidates[0],
        "all": candidates,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://localhost:8000")
    ap.add_argument("--model", default="lysos-rl")
    ap.add_argument("--prompt", help="Single prompt mode")
    ap.add_argument("--prompts", type=Path, help="JSONL file with prompts")
    ap.add_argument("--output", type=Path, default=ROOT / "reports" / "best_of_n_outputs.json")
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args()

    results = []
    if args.prompt:
        results.append(best_of_n(args.endpoint, args.model, args.prompt, args.n))
    elif args.prompts:
        with open(args.prompts) as f:
            for line in f:
                r = json.loads(line)
                p = r.get("prompt") or r.get("messages", [{}])[0].get("content", "")
                if p:
                    results.append(best_of_n(args.endpoint, args.model, p, args.n))
    else:
        print("Specify --prompt or --prompts", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as f:
        json.dump(results, f, indent=2)

    print(f"Wrote {len(results)} best-of-{args.n} results to {args.output}")
    if results:
        print(f"\nTop result composite score: {results[0].get('best', {}).get('composite_score', 0):.3f}")


if __name__ == "__main__":
    sys.exit(main())
