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
import socket
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
                  max_tokens: int = 8192,
                  timeout: float = 300.0,
                  capture_thinking: bool = True,
                  max_retries: int = 5) -> dict:
    """Single Gemini 2.5 Pro generation. Returns dict with response + usage.

    Captures the full reasoning trace via `thinkingConfig.includeThoughts=True`.
    For each call you get back BOTH the visible answer AND the thinking trace
    so we can compare not just answers but reasoning chains in the methods
    paper. See TECH_DOC §5.8.1 for the budget gotcha.
    """
    url = (f"https://generativelanguage.googleapis.com/v1beta/"
           f"models/{model}:generateContent")
    gen_cfg: dict = {
        "temperature": 0.0,
        "maxOutputTokens": max_tokens,
    }
    if capture_thinking:
        gen_cfg["thinkingConfig"] = {"includeThoughts": True}
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
        method="POST",
    )
    t0 = time.time()
    last_err = ""
    d: dict | None = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            body_text = ""
            try:
                body_text = e.read().decode("utf-8", errors="ignore")[:200]
            except Exception:
                pass
            last_err = f"HTTP {e.code}: {body_text}"
            if e.code == 429 or e.code >= 500:
                wait = min(8 * (attempt + 1), 60)
                print(f"    [retry {attempt+1}/{max_retries}] HTTP {e.code} — sleep {wait}s",
                      flush=True)
                time.sleep(wait)
                continue
            return {
                "response": f"<HTTP_ERROR_{e.code}: {last_err}>",
                "thinking": "",
                "tokens_in": 0, "tokens_out": 0, "tokens_think": 0,
                "finish_reason": "ERROR",
                "latency_ms": int((time.time() - t0) * 1000),
            }
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as e:
            last_err = f"{type(e).__name__}: {e}"
            wait = min(5 * (attempt + 1), 45)
            print(f"    [retry {attempt+1}/{max_retries}] {last_err} — sleep {wait}s",
                  flush=True)
            time.sleep(wait)
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(2 * (attempt + 1))
    if d is None:
        return {
            "response": f"<ERROR: {last_err}>",
            "thinking": "",
            "tokens_in": 0, "tokens_out": 0, "tokens_think": 0,
            "finish_reason": "ERROR",
            "latency_ms": int((time.time() - t0) * 1000),
        }

    text = ""
    thinking = ""
    finish_reason = ""
    for cand in d.get("candidates", []):
        finish_reason = cand.get("finishReason", finish_reason) or finish_reason
        for part in cand.get("content", {}).get("parts", []) or []:
            t = part.get("text", "")
            if part.get("thought") is True:
                thinking += t
            else:
                text += t

    usage = d.get("usageMetadata", {})
    return {
        "response": text,
        "thinking": thinking,
        "tokens_in": usage.get("promptTokenCount", 0),
        "tokens_out": usage.get("candidatesTokenCount", 0),
        "tokens_think": usage.get("thoughtsTokenCount", 0),
        "finish_reason": finish_reason,
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
    ap.add_argument("--max_tokens", type=int, default=8192,
                    help="Combined thinking+output budget (gemini-2.5-pro is "
                         "a thinking model; <2000 → empty output). Default 8192.")
    ap.add_argument("--no-thinking", action="store_true",
                    help="Disable thinking-trace capture (we still pay for "
                         "thinking tokens, just don't get them back).")
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
    total_think = 0
    t0 = time.time()
    print(f"[INFO] Running Gemini {args.model} on {len(prompts)} prompts...")
    with args.out.open("w") as f:
        for i, p in enumerate(prompts):
            r = gemini_25_pro(p["prompt"], api_key,
                              model=args.model,
                              max_tokens=args.max_tokens,
                              capture_thinking=not args.no_thinking)
            row = {
                "prompt_idx": i,
                "source": p["source"],
                "task": p.get("task"),
                "prompt": p["prompt"],
                "response": r["response"],
                "thinking": r.get("thinking", ""),
                "tokens_in": r["tokens_in"],
                "tokens_out": r["tokens_out"],
                "tokens_think": r.get("tokens_think", 0),
                "finish_reason": r.get("finish_reason", ""),
                "latency_ms": r["latency_ms"],
                "model": args.model,
            }
            rows.append(row)
            total_in += r["tokens_in"]
            total_out += r["tokens_out"]
            total_think += r.get("tokens_think", 0)
            f.write(json.dumps(row) + "\n")
            f.flush()  # incremental — kill-resilient
            if (i + 1) % 10 == 0 or i == len(prompts) - 1:
                rate = (i + 1) / (time.time() - t0)
                billed_out = total_out + total_think
                cost = (total_in / 1e6) * 1.25 + (billed_out / 1e6) * 10.0
                print(f"  [{i+1}/{len(prompts)}] {rate:.2f} p/s "
                      f"in={total_in:,} out={total_out:,} think={total_think:,} "
                      f"cost≈${cost:.3f}", flush=True)

    billed_out = total_out + total_think
    cost = (total_in / 1e6) * 1.25 + (billed_out / 1e6) * 10.0
    print(f"\n[OK] Wrote {len(rows)} rows to {args.out}")
    print(f"[OK] Total: {total_in:,} in + {total_out:,} out + "
          f"{total_think:,} think ≈ ${cost:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
