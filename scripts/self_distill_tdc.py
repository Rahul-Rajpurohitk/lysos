"""Self-distillation: use Gemma 4 zero-shot to relabel TDC tasks.

Standard SFT trains on raw TDC labels (binary yes/no). Self-distillation
generates richer, narrative-form labels via the base model (Gemma 4 zero-
shot), then SFT trains on those richer labels. This is what TxGemma and
similar systems do.

Strategy:
  1. For each TDC task type (28 of them), sample 100-500 rows
  2. Format as question prompt for Gemma 4 (e.g., "Predict whether SMILES X
     inhibits cyp3a4")
  3. Get Gemma 4 zero-shot response (a paragraph with reasoning)
  4. Pair (prompt, Gemma response) as new SFT row
  5. Optionally: filter via a critic model (Gemma 4 reflexion) for quality

Output: data/synthetic/agentic_tdc_self_distill.jsonl

Run (when vLLM serves Gemma 4 at http://localhost:8000):
  /tmp/lysos_venv/bin/python scripts/self_distill_tdc.py \\
      --endpoint http://localhost:8000 \\
      --max_per_task 500 \\
      --output data/synthetic/agentic_tdc_self_distill.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TDC_INPUT = ROOT / "data" / "processed" / "tdc-stage1"
DEFAULT_OUT = ROOT / "data" / "synthetic" / "agentic_tdc_self_distill.jsonl"


# TDC task → richer prompt template
TASK_TEMPLATES = {
    "tdc_admet_prediction": (
        "Given the SMILES `{smiles}`, predict whether the compound passes "
        "the {assay_name} assay. Reason through the structural features that "
        "drive your prediction (logP, TPSA, ionizable groups, structural "
        "alerts). End with PREDICTION: POSITIVE/NEGATIVE and CONFIDENCE: 0-1."
    ),
    "tdc_toxicity_prediction": (
        "Given the SMILES `{smiles}`, predict toxicity in the {assay_name} "
        "assay. Consider mechanistic basis (CYP inhibition, hERG, mitochondrial). "
        "End with PREDICTION + CONFIDENCE."
    ),
    "drug_likeness": (
        "Given the SMILES `{smiles}`, evaluate drug-likeness via Lipinski + "
        "Veber + Egan rules. Report MW, logP, HBD, HBA, TPSA, rotatable bonds. "
        "End with VERDICT: drug-like/borderline/not-drug-like + RATIONALE."
    ),
}


def call_model(endpoint: str, prompt: str, max_tokens: int = 512) -> str:
    import requests
    try:
        r = requests.post(
            f"{endpoint}/v1/chat/completions",
            json={
                "model": "google/gemma-4-31b-it",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"<MODEL_UNAVAILABLE: {e}>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://localhost:8000")
    ap.add_argument("--max_per_task", type=int, default=500)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--dry_run", action="store_true")
    args = ap.parse_args()

    print(f"Loading TDC dataset {TDC_INPUT}")
    if not TDC_INPUT.exists():
        print("TDC dataset not found. Run scripts/prepare_tdc_data.py first.")
        return 1
    from datasets import load_from_disk
    ds = load_from_disk(str(TDC_INPUT))
    train = ds["train"]
    print(f"  TDC train rows: {len(train):,}")

    if args.dry_run:
        print(f"\n=== DRY RUN ===")
        print(f"Would query {args.endpoint} for self-distillation labels")
        print(f"Per-task limit: {args.max_per_task}")
        print(f"\nSample row:")
        print(f"  task: {train[0].get('task', '?')}")
        msgs = json.loads(train[0]['messages']) if isinstance(train[0].get('messages'), str) else train[0].get('messages', [])
        print(f"  user prompt: {msgs[0].get('content', '')[:150] if msgs else '?'}")
        return 0

    if args.output.exists():
        args.output.unlink()

    n_done = 0
    n_per_task = {}
    with open(args.output, "a") as f:
        for r in train:
            task = r.get("task", "unknown")
            if n_per_task.get(task, 0) >= args.max_per_task:
                continue
            msgs = r["messages"]
            if isinstance(msgs, str):
                msgs = json.loads(msgs)
            user_msg = next((m["content"] for m in msgs if m.get("role") == "user"), None)
            if not user_msg:
                continue

            response = call_model(args.endpoint, user_msg)
            if "<MODEL_UNAVAILABLE>" in response:
                print(f"Model endpoint unavailable; aborting after {n_done}")
                break

            new_row = {
                "task": task + "_self_distill",
                "pathogen": r.get("pathogen"),
                "messages": [
                    {"role": "system", "content": "You are a drug-design expert reasoning over molecular properties + assay outcomes."},
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": response},
                ],
            }
            f.write(json.dumps(new_row) + "\n")
            n_done += 1
            n_per_task[task] = n_per_task.get(task, 0) + 1

            if n_done % 50 == 0:
                print(f"  done {n_done}  per-task: {dict(list(n_per_task.items())[:5])}")

    print(f"\nWrote {n_done} self-distill rows to {args.output}")
    print(f"\nPer-task counts:")
    for task, n in sorted(n_per_task.items(), key=lambda kv: -kv[1]):
        print(f"  {task:35s} {n}")


if __name__ == "__main__":
    sys.exit(main())
