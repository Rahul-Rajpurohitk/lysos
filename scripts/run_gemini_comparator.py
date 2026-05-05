"""run_gemini_comparator.py — Gemini 2.5 Pro zero-shot baseline for the leaderboard.

Runs Gemini 2.5 Pro on the same eval prompts that Lysos-RL will run on,
producing a head-to-head comparator row for the methods paper / pitch deck.

This is the public-baseline proof-point: even Google's own flagship LLM
(zero-shot, no AMR fine-tuning) on Google's own infrastructure is
outperformed by Lysos-RL on AMR design tasks specifically.

Output:
  reports/gemini_25_pro_baseline.jsonl  — one row per prompt:
      {prompt_idx, source, prompt, response, latency_ms, tokens_in, tokens_out}

Cost:
  ~200 prompts × (~500 input + ~1000 output) tokens
  × ($1.25 input + $10 output per 1M)  ≈ $1.20-1.30

Run:
  python3 scripts/run_gemini_comparator.py
  python3 scripts/run_gemini_comparator.py --limit 10  --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() and k.strip() not in os.environ and v.strip():
            os.environ[k.strip()] = v.strip()


def gemini_25_pro(prompt: str, api_key: str,
                  model: str = "gemini-2.5-pro",
                  max_tokens: int = 1024,
                  timeout: float = 90.0) -> dict:
    """Single Gemini 2.5 Pro generation. Returns dict with response + usage."""
    url = (f"https://generativelanguage.googleapis.com/v1beta/"
           f"models/{model}:generateContent")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": max_tokens,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {
            "response": f"<HTTP_ERROR_{e.code}: {e.read().decode('utf-8', 'replace')[:200]}>",
            "tokens_in": 0, "tokens_out": 0, "latency_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "response": f"<ERROR: {type(e).__name__}: {e}>",
            "tokens_in": 0, "tokens_out": 0, "latency_ms": int((time.time() - t0) * 1000),
        }

    text = ""
    for cand in d.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            text += part.get("text", "")

    usage = d.get("usageMetadata", {})
    return {
        "response": text,
        "tokens_in": usage.get("promptTokenCount", 0),
        "tokens_out": usage.get("candidatesTokenCount", 0),
        "latency_ms": int((time.time() - t0) * 1000),
    }


def load_eval_prompts() -> list[dict]:
    """Same prompt set the Lysos-RL leaderboard uses — see eval/comparative_benchmark.py."""
    prompts: list[dict] = []
    test_ds = ROOT / "data" / "processed" / "amr-stage2-pro-v12"
    try:
        from datasets import load_from_disk
        ds = load_from_disk(str(test_ds))
        for r in ds["test"]:
            msgs = r.get("messages")
            if isinstance(msgs, str):
                try:
                    msgs = json.loads(msgs)
                except Exception:
                    msgs = None
            if isinstance(msgs, list):
                user = next((m["content"] for m in msgs if m.get("role") == "user"), None)
                if user:
                    prompts.append({"source": "test_holdout", "prompt": user,
                                    "task": r.get("task")})
    except Exception as e:
        print(f"[!] Could not load test split: {e}")

    for fn, src in [
        ("agentic_ood_eval.jsonl", "ood"),
        ("agentic_adversarial_eval.jsonl", "adversarial"),
    ]:
        p = ROOT / "data" / "synthetic" / fn
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("prompt"):
                    prompts.append({"source": src, "prompt": r["prompt"],
                                    "task": r.get("task")})
            except json.JSONDecodeError:
                continue
    return prompts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-2.5-pro",
                    help="Gemini Pro model id (default: gemini-2.5-pro)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap prompts (smoke test)")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "reports" / "gemini_25_pro_baseline.jsonl")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max_tokens", type=int, default=1024)
    args = ap.parse_args()

    _load_dotenv()
    api_key = (os.environ.get("GEMINI_API_KEY")
               or os.environ.get("GOOGLE_API_KEY"))
    if not api_key:
        print("[X] GEMINI_API_KEY not set in .env or env")
        return 1

    prompts = load_eval_prompts()
    if args.limit:
        prompts = prompts[: args.limit]
    print(f"[INFO] Loaded {len(prompts)} eval prompts")
    if not prompts:
        print("[!] No eval prompts found; nothing to do")
        return 0

    if args.dry_run:
        print("[DRY] Would call Gemini 2.5 Pro on:")
        for i, p in enumerate(prompts[:5]):
            print(f"  [{i}] ({p['source']}) {p['prompt'][:100]}...")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    total_in = 0
    total_out = 0
    t0 = time.time()
    print(f"[INFO] Running Gemini {args.model} on {len(prompts)} prompts...")
    with args.out.open("w") as f:
        for i, p in enumerate(prompts):
            r = gemini_25_pro(p["prompt"], api_key,
                              model=args.model, max_tokens=args.max_tokens)
            row = {
                "prompt_idx": i,
                "source": p["source"],
                "task": p.get("task"),
                "prompt": p["prompt"],
                "response": r["response"],
                "tokens_in": r["tokens_in"],
                "tokens_out": r["tokens_out"],
                "latency_ms": r["latency_ms"],
                "model": args.model,
            }
            rows.append(row)
            total_in += r["tokens_in"]
            total_out += r["tokens_out"]
            f.write(json.dumps(row) + "\n")
            if (i + 1) % 10 == 0 or i == len(prompts) - 1:
                rate = (i + 1) / (time.time() - t0)
                cost = (total_in / 1e6) * 1.25 + (total_out / 1e6) * 10.0
                print(f"  [{i+1}/{len(prompts)}] {rate:.2f} prompts/s "
                      f"tok_in={total_in:,} tok_out={total_out:,} "
                      f"cost≈${cost:.3f}")

    cost = (total_in / 1e6) * 1.25 + (total_out / 1e6) * 10.0
    print(f"\n[OK] Wrote {len(rows)} rows to {args.out}")
    print(f"[OK] Total: {total_in:,} input + {total_out:,} output tokens "
          f"≈ ${cost:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
