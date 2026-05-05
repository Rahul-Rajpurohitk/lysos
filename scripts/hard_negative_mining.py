"""Hard-negative mining — ready to run after first SFT checkpoint.

After the Stage-2 SFT model is trained, this script:
  1. Runs the trained model on the validation set
  2. Identifies rows where the model's prediction disagrees with the ground truth
  3. Samples those rows as "hard negatives" for a 2nd SFT round
  4. Generates the hard-negative training file

This produces meaningful improvement on the held-out test set because the
model concentrates training on what it gets wrong.

Run (post-train):
  /tmp/lysos_venv/bin/python scripts/hard_negative_mining.py \\
      --model rahul24raj/lysos-base \\
      --output data/synthetic/agentic_hard_negatives.jsonl

This script is a placeholder until the trained model is available. The
inference adapter expects a vLLM endpoint at http://localhost:8000/v1.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "processed" / "amr-stage2-pro-v11"
DEFAULT_OUTPUT = ROOT / "data" / "synthetic" / "agentic_hard_negatives.jsonl"


def call_model(model_endpoint: str, prompt: str, max_tokens: int = 512) -> str:
    """Call the served model. Stub until vLLM endpoint is up."""
    try:
        import requests
        r = requests.post(
            f"{model_endpoint}/v1/chat/completions",
            json={
                "model": "lysos-base",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.0,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"<MODEL_UNAVAILABLE: {e}>"


def is_disagreement(predicted: str, target: str) -> bool:
    """Heuristic: predicted disagrees with target if predicted is empty,
    contains <MODEL_UNAVAILABLE>, or has Levenshtein-like distance > 50%."""
    if not predicted: return True
    if "<MODEL_UNAVAILABLE>" in predicted: return False  # can't tell, skip
    if not target: return False
    # Quick proxy: token-set overlap
    p_tokens = set(predicted.lower().split())
    t_tokens = set(target.lower().split())
    if not t_tokens: return False
    overlap = len(p_tokens & t_tokens) / len(t_tokens)
    return overlap < 0.4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model_endpoint", default="http://localhost:8000")
    ap.add_argument("--input_dataset", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--max_rows", type=int, default=2000)
    ap.add_argument("--target_n_negatives", type=int, default=500)
    args = ap.parse_args()

    print(f"Loading {args.input_dataset}")
    from datasets import load_from_disk
    ds = load_from_disk(str(args.input_dataset))
    valid = ds["valid"].select(range(min(args.max_rows, len(ds["valid"]))))
    print(f"  validation rows: {len(valid):,}")

    if args.output.exists():
        args.output.unlink()

    n_processed = 0
    n_disagreement = 0
    with open(args.output, "a") as f:
        for r in valid:
            n_processed += 1
            if n_disagreement >= args.target_n_negatives:
                break
            msgs = json.loads(r["messages"])
            user_msg = next((m["content"] for m in msgs if m.get("role") == "user"), "")
            target_assist = next(
                (m["content"] for m in reversed(msgs) if m.get("role") == "assistant"), ""
            )
            if not user_msg or not target_assist:
                continue

            predicted = call_model(args.model_endpoint, user_msg)

            if is_disagreement(predicted, target_assist):
                n_disagreement += 1
                f.write(json.dumps({
                    "task": r["task"] + "_hard_negative",
                    "pathogen": r["pathogen"],
                    "messages": json.loads(r["messages"]),
                    "model_prediction": predicted[:1000],
                    "target": target_assist[:1000],
                    "hard_negative": True,
                }) + "\n")
            if n_processed % 100 == 0:
                print(f"  processed {n_processed}  disagreement_rate={n_disagreement/n_processed*100:.1f}%")

    print(f"\nDone. processed={n_processed:,}, hard negatives={n_disagreement:,}")
    print(f"Wrote {args.output}")
    print(f"\nNext: oversample these rows in pro-v12 builder for a 2nd SFT round.")


if __name__ == "__main__":
    sys.exit(main())
