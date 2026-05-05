"""llm_as_judge_eval.py — Gemini 2.5 Pro qualitative critic for Lysos-RL responses.

Run AFTER Stage 3 finishes and Lysos-RL has produced responses on the
held-out test set. Gemini 2.5 Pro reads each (prompt, response) pair and
scores it on 4 qualitative axes the verifiable reward stack can't capture:

    reasoning_quality     0-10  Are the steps coherent and grounded?
    citation_grounding    0-10  Are referenced drugs / genes / studies real?
    mechanism_plausibility 0-10  Does the proposed mechanism make biochemical sense?
    safety_awareness      0-10  Does the response flag known toxicity / resistance?

Plus a one-paragraph free-text rationale per row.

Output:
  reports/lysos_rl_judge_scores.jsonl

Cost:
  ~50 test rows × ~2K tokens (prompt + response + judge reasoning)
  × ($1.25 input + $10 output / 1M) ≈ $1.00

Run:
  python3 scripts/llm_as_judge_eval.py \\
      --responses reports/lysos_rl_responses.jsonl \\
      --out reports/lysos_rl_judge_scores.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import socket
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


JUDGE_PROMPT = """You are an expert AMR (antimicrobial resistance) clinical pharmacologist
acting as a JUDGE for an AI antibiotic-design system. Score the model's response below
on 4 axes (each 0-10) and write a one-paragraph rationale.

PROMPT GIVEN TO THE MODEL:
{prompt}

MODEL RESPONSE:
{response}

──────────────────────────────────────────────────────────────────────

Return ONLY a JSON object with these EXACT fields:

{{
  "reasoning_quality": <0-10 int>,        // Steps coherent? Grounded in pharmacology?
  "citation_grounding": <0-10 int>,        // Referenced drugs/genes/studies real and accurate?
  "mechanism_plausibility": <0-10 int>,    // Proposed mechanism biochemically valid?
  "safety_awareness": <0-10 int>,          // Flags toxicity / resistance / spectrum gaps?
  "overall": <0-10 int>,                   // Holistic score
  "rationale": "<2-3 sentence rationale>"
}}

Score harshly. 10 = top-tier expert clinician quality. 5 = passable senior PharmD.
0 = hallucinated nonsense. No markdown, no fence. JSON only."""


def gemini_25_pro(prompt: str, api_key: str,
                  model: str = "gemini-2.5-pro",
                  max_tokens: int = 8192,
                  timeout: float = 300.0,
                  capture_thinking: bool = True,
                  max_retries: int = 5) -> dict:
    """Single judge call. Returns dict with text, thinking, token counts.

    Default 8192 since gemini-2.5-pro is a thinking model and judging
    multi-axis scientific responses uses ~1500-2500 thinking tokens
    (the 800-token original budget got us empty responses).
    """
    url = (f"https://generativelanguage.googleapis.com/v1beta/"
           f"models/{model}:generateContent")
    gen_cfg: dict = {
        "temperature": 0.0,
        "maxOutputTokens": max_tokens,
        "responseMimeType": "application/json",
    }
    if capture_thinking:
        gen_cfg["thinkingConfig"] = {"includeThoughts": True}
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
        method="POST",
    )
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
            return {"text": f"<ERR: {last_err}>", "thinking": "",
                    "tokens_in": 0, "tokens_out": 0, "tokens_think": 0,
                    "finish_reason": "ERROR"}
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
        return {"text": f"<ERR: {last_err}>", "thinking": "",
                "tokens_in": 0, "tokens_out": 0, "tokens_think": 0,
                "finish_reason": "ERROR"}
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
    u = d.get("usageMetadata", {})
    return {
        "text": text,
        "thinking": thinking,
        "tokens_in": u.get("promptTokenCount", 0),
        "tokens_out": u.get("candidatesTokenCount", 0),
        "tokens_think": u.get("thoughtsTokenCount", 0),
        "finish_reason": finish_reason,
    }


def parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        i, j = text.find("{"), text.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(text[i:j+1])
            except json.JSONDecodeError:
                pass
    return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--responses", type=Path, required=True,
                    help="JSONL of {prompt, response} pairs to judge")
    ap.add_argument("--out", type=Path, required=True,
                    help="Output JSONL with per-row scores")
    ap.add_argument("--model", default="gemini-2.5-pro")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # Load .env
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                if k.strip() and k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[X] GEMINI_API_KEY not set")
        return 1

    if not args.responses.exists():
        print(f"[X] Responses file not found: {args.responses}")
        return 1

    rows = []
    with args.responses.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if args.limit:
        rows = rows[: args.limit]

    print(f"[INFO] Judging {len(rows)} responses with {args.model}")
    if args.dry_run:
        print(f"[DRY] First row: {rows[0].get('prompt', '?')[:120]}...")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)

    total_in = total_out = total_think = 0
    out_rows = []
    t0 = time.time()
    with args.out.open("w") as f:
        for i, r in enumerate(rows):
            judge_prompt = JUDGE_PROMPT.format(
                prompt=r.get("prompt", "")[:1500],
                response=r.get("response", "")[:2000],
            )
            res = gemini_25_pro(judge_prompt, api_key, model=args.model)
            parsed = parse_json(res["text"])
            out = {
                "prompt_idx": r.get("prompt_idx", i),
                "source": r.get("source"),
                "task": r.get("task"),
                "scores": {
                    "reasoning_quality":     parsed.get("reasoning_quality"),
                    "citation_grounding":    parsed.get("citation_grounding"),
                    "mechanism_plausibility": parsed.get("mechanism_plausibility"),
                    "safety_awareness":      parsed.get("safety_awareness"),
                    "overall":               parsed.get("overall"),
                },
                "rationale": parsed.get("rationale", ""),
                # Judge thinking trace = the rationale chain we'd otherwise
                # have to reconstruct. Keep verbatim for the methods paper.
                "judge_thinking": res.get("thinking", ""),
                "judge_model": args.model,
                "tokens_in": res["tokens_in"],
                "tokens_out": res["tokens_out"],
                "tokens_think": res.get("tokens_think", 0),
                "finish_reason": res.get("finish_reason", ""),
            }
            out_rows.append(out)
            f.write(json.dumps(out) + "\n")
            f.flush()
            total_in += res["tokens_in"]
            total_out += res["tokens_out"]
            total_think += res.get("tokens_think", 0)
            if (i + 1) % 10 == 0 or i == len(rows) - 1:
                billed_out = total_out + total_think
                cost = (total_in / 1e6) * 1.25 + (billed_out / 1e6) * 10.0
                print(f"  [{i+1}/{len(rows)}] in={total_in:,} out={total_out:,} "
                      f"think={total_think:,} cum ${cost:.3f}", flush=True)

    # Roll-up summary
    valid = [r for r in out_rows if r["scores"].get("overall") is not None]
    if valid:
        means = {k: sum(r["scores"][k] for r in valid) / len(valid)
                 for k in ("reasoning_quality", "citation_grounding",
                           "mechanism_plausibility", "safety_awareness", "overall")}
        print(f"\n[OK] Judged {len(valid)} / {len(out_rows)} successfully")
        print(f"[OK] Mean scores:")
        for k, v in means.items():
            print(f"     {k:<24}  {v:.2f}/10")
    cost = (total_in / 1e6) * 1.25 + (total_out / 1e6) * 10.0
    print(f"\n[OK] Wrote {args.out}")
    print(f"[OK] Total: {total_in:,} input + {total_out:,} output ≈ ${cost:.3f}")
    print(f"     elapsed: {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
