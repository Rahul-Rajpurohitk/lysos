"""Comparative benchmark — Lysos-RL vs Gemma 4 zero-shot vs GPT-4 zero-shot.

Runs each model through our 7-metric eval harness on the same eval prompts
(test split + OOD + adversarial). Outputs side-by-side comparison for the
methods paper + pitch deck.

Inference adapters expected:
  - Lysos-RL: vLLM at http://localhost:8000
  - Gemma 4 zero-shot: vLLM at http://localhost:8001 (separate serving)
  - GPT-4 zero-shot: OpenAI API (ANTHROPIC-skip; OpenAI key required)

Run:
  /tmp/lysos_venv/bin/python eval/comparative_benchmark.py \\
      --models lysos-rl gemma-4-zero gpt-4-zero \\
      --output reports/comparative_benchmark.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "reports" / "comparative_benchmark.json"


MODEL_ENDPOINTS = {
    "lysos-rl": ("http://localhost:8000", "lysos-rl"),
    "lysos-base": ("http://localhost:8000", "lysos-base"),
    "gemma-4-zero": ("http://localhost:8001", "google/gemma-4-31b-it"),
    "gpt-4-zero": ("openai", "gpt-4o"),
    "claude-zero": ("anthropic", "claude-opus-4-7"),  # if subscription used for distill
}


def call_vllm(endpoint: str, model: str, prompt: str, max_tokens: int = 512) -> str:
    import requests
    try:
        r = requests.post(
            f"{endpoint}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.0,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"<MODEL_UNAVAILABLE: {e}>"


def call_openai(model: str, prompt: str, max_tokens: int = 512) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "<NO_OPENAI_API_KEY>"
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.0,
        )
        return r.choices[0].message.content
    except Exception as e:
        return f"<MODEL_UNAVAILABLE: {e}>"


def call_anthropic(model: str, prompt: str, max_tokens: int = 512) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "<NO_ANTHROPIC_API_KEY>"
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        r = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return r.content[0].text
    except Exception as e:
        return f"<MODEL_UNAVAILABLE: {e}>"


def call_model(label: str, prompt: str) -> str:
    endpoint, model = MODEL_ENDPOINTS[label]
    if endpoint == "openai":
        return call_openai(model, prompt)
    if endpoint == "anthropic":
        return call_anthropic(model, prompt)
    return call_vllm(endpoint, model, prompt)


def load_eval_prompts():
    """Load prompts from held-out test + OOD + adversarial."""
    prompts = []
    test_ds = ROOT / "data" / "processed" / "amr-stage2-pro-v11"
    from datasets import load_from_disk
    ds = load_from_disk(str(test_ds))
    for r in ds["test"]:
        msgs = json.loads(r["messages"])
        user_msg = next((m["content"] for m in msgs if m.get("role") == "user"), None)
        if user_msg:
            prompts.append({"source": "test_holdout", "prompt": user_msg, "task": r["task"]})

    # OOD eval prompts
    ood_path = ROOT / "data" / "synthetic" / "agentic_ood_eval.jsonl"
    if ood_path.exists():
        with open(ood_path) as f:
            for line in f:
                r = json.loads(line)
                prompts.append({"source": "ood", "prompt": r["prompt"], "pathogen": r.get("pathogen")})

    # Adversarial jailbreaks (subset)
    adv_path = ROOT / "data" / "synthetic" / "agentic_adversarial_eval.jsonl"
    if adv_path.exists():
        with open(adv_path) as f:
            for line in f:
                r = json.loads(line)
                if r.get("task") == "adversarial_jailbreak":
                    prompts.append({"source": "jailbreak", "prompt": r["prompt"]})

    return prompts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["lysos-rl", "gemma-4-zero"])
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--max_prompts", type=int, default=200)
    args = ap.parse_args()

    print(f"Loading eval prompts...")
    prompts = load_eval_prompts()[:args.max_prompts]
    print(f"  total prompts: {len(prompts)}")

    results = {"models": list(args.models), "n_prompts": len(prompts), "responses": []}

    for i, p in enumerate(prompts):
        prompt_responses = {"prompt_idx": i, "source": p["source"], "prompt": p["prompt"][:200], "by_model": {}}
        for model in args.models:
            resp = call_model(model, p["prompt"])
            prompt_responses["by_model"][model] = resp[:600]
        results["responses"].append(prompt_responses)
        if i % 20 == 0:
            print(f"  done {i}/{len(prompts)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote comparative benchmark to {args.output}")


if __name__ == "__main__":
    sys.exit(main())
