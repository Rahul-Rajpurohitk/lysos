"""Score a Gemma 4 31B-it checkpoint on the 55 held-out named-drug CoT prompts.

Generates responses with the named HF model, scores each completion against the
gold response across 5 axes, and prints a per-task-type breakdown plus an
aggregate quality score. Designed to compare:
  - rahul24raj/lysos-base       (Stage 2 SFT only, v2 dataset)
  - rahul24raj/lysos-rl         (Stage 2 + Stage 3 GRPO RL)
  - google/gemma-4-31B-it       (untuned baseline)

Scoring axes:
  1. citation_recall    — does the completion cite the same named genes/enzymes/
                          trials/drugs as the gold response?
  2. mic_value_recall   — does the completion produce numerically reasonable MIC
                          values that match orders of magnitude in gold?
  3. structure_coverage — does the completion follow the 5-section instruction
                          schema (5 numbered or labeled reasoning steps)?
  4. length_ratio       — is the completion within 0.5x to 2.0x of gold length?
  5. semantic_overlap   — Jaccard token overlap on lowercased word stems
                          (rough but cheap proxy for content match)

Composite score = weighted sum of the 5 axes (weights configurable).

Usage:
  python examples/score_held_out_named_drug.py --model rahul24raj/lysos-rl
  python examples/score_held_out_named_drug.py --model A --model B --output cmp.csv
  python examples/score_held_out_named_drug.py --model rahul24raj/lysos-base --limit 10
"""
import argparse
import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

TEST_JSONL = Path("data/synthetic/named_drug_test_split.jsonl")


NAMED_ENTITY_PATTERNS = [
    r"\b[A-Z][a-z]?[A-Z]{0,2}\d+[A-Za-z]?\b",
    r"\bbla[A-Z]{2,5}\b",
    r"\bAAC\([0-9]+(prime)?\)\b",
    r"\b(POET|MERINO|TANGO|EAGLE|CREDIBLE|SECURE|REVISIT|ATTACK|ZeNix|Nix-TB|EPIC|SAPS|STOP-IT)\b",
    r"\b(vancomycin|daptomycin|linezolid|tigecycline|tedizolid|cefiderocol|"
    r"ceftaroline|ceftolozane|ceftazidime|cefepime|meropenem|imipenem|ertapenem|"
    r"piperacillin|tazobactam|avibactam|relebactam|vaborbactam|durlobactam|"
    r"sulbactam|aztreonam|amoxicillin|ampicillin|penicillin|cefazolin|"
    r"ceftriaxone|polymyxin|colistin|gentamicin|amikacin|tobramycin|plazomicin|"
    r"azithromycin|clarithromycin|doxycycline|minocycline|eravacycline|"
    r"omadacycline|clindamycin|metronidazole|trimethoprim|sulfamethoxazole|"
    r"fluconazole|voriconazole|posaconazole|isavuconazole|amphotericin|"
    r"caspofungin|micafungin|anidulafungin|fidaxomicin|rifampin|rifabutin|"
    r"isoniazid|ethambutol|pyrazinamide|bedaquiline|pretomanid|delamanid|"
    r"flucytosine|nitrofurantoin|fosfomycin|levofloxacin|moxifloxacin|"
    r"ciprofloxacin|gepotidacin|lefamulin|telavancin|oritavancin|dalbavancin)\b",
]


def extract_named_entities(text):
    found = set()
    for pat in NAMED_ENTITY_PATTERNS:
        found.update(re.findall(pat, text, flags=re.IGNORECASE))
    return {e.lower() if isinstance(e, str) else e[0].lower() for e in found if e}


def extract_mic_values(text):
    pattern = r"(?:MIC[0-9]*\s*)?(?:of\s+)?(\d+(?:\.\d+)?)\s*(?:to\s+\d+(?:\.\d+)?\s*)?(?:ug/mL|µg/mL|mg/L|ng/mL)"
    return [float(m) for m in re.findall(pattern, text, flags=re.IGNORECASE)]


def score_citation_recall(gold, pred):
    g = extract_named_entities(gold)
    p = extract_named_entities(pred)
    if not g:
        return 1.0
    return len(g & p) / len(g)


def score_mic_value_recall(gold, pred):
    g_mics = extract_mic_values(gold)
    p_mics = extract_mic_values(pred)
    if not g_mics:
        return 1.0
    if not p_mics:
        return 0.0
    matches = 0
    for gm in g_mics:
        for pm in p_mics:
            if abs(math.log10(max(gm, 1e-6)) - math.log10(max(pm, 1e-6))) < 1.0:
                matches += 1
                break
    return matches / len(g_mics)


def score_structure_coverage(gold, pred):
    patterns = [r"\(1\)", r"\(2\)", r"\(3\)", r"\(4\)", r"\(5\)"]
    matches = sum(1 for p in patterns if re.search(p, pred))
    return matches / 5.0


def score_length_ratio(gold, pred):
    if len(gold) == 0:
        return 1.0
    ratio = len(pred) / len(gold)
    if 0.5 <= ratio <= 2.0:
        return 1.0
    elif ratio < 0.5:
        return ratio / 0.5
    else:
        return max(0.0, 2.0 / ratio)


def score_semantic_overlap(gold, pred):
    g_tokens = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", gold)}
    p_tokens = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", pred)}
    if not g_tokens:
        return 0.0
    return len(g_tokens & p_tokens) / len(g_tokens | p_tokens)


SCORERS = {
    "citation_recall":    score_citation_recall,
    "mic_value_recall":   score_mic_value_recall,
    "structure_coverage": score_structure_coverage,
    "length_ratio":       score_length_ratio,
    "semantic_overlap":   score_semantic_overlap,
}

WEIGHTS = {
    "citation_recall":    0.35,
    "mic_value_recall":   0.20,
    "structure_coverage": 0.15,
    "length_ratio":       0.10,
    "semantic_overlap":   0.20,
}


def composite_score(metrics):
    return sum(metrics[m] * WEIGHTS[m] for m in WEIGHTS)


def generate_with_hf_transformers(model_id, prompts, max_new_tokens=1024):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch

    print(f"[gen] Loading {model_id}...")
    tok = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
    )
    model.train(False)  # equivalent to model.eval(), inference mode

    completions = []
    for i, prompt in enumerate(prompts):
        chat = [{"role": "user", "content": prompt}]
        text = tok.apply_chat_template(chat, add_generation_prompt=True, tokenize=False)
        inputs = tok(text, return_tensors="pt").to(model.device)
        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                temperature=1.0,
                pad_token_id=tok.eos_token_id,
            )
        completion = tok.decode(output[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        completions.append(completion)
        if (i + 1) % 5 == 0:
            print(f"  [{i+1}/{len(prompts)}]")
    return completions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", required=True,
                    help="HF model id; repeat to compare multiple models")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--max-new-tokens", type=int, default=1024)
    ap.add_argument("--output", type=str, default=None,
                    help="Optional CSV for side-by-side results")
    args = ap.parse_args()

    print(f"Loading test split from {TEST_JSONL}...")
    rows = []
    with TEST_JSONL.open() as f:
        for line in f:
            rows.append(json.loads(line))
    if args.limit:
        rows = rows[:args.limit]
    print(f"  {len(rows)} prompts loaded")

    task_dist = Counter(r["task"] for r in rows)
    print(f"  task distribution: {dict(task_dist)}")

    all_results = {}

    for model_id in args.model:
        print(f"\n{'='*70}\nScoring: {model_id}\n{'='*70}")
        prompts = [r["prompt"] for r in rows]
        completions = generate_with_hf_transformers(
            model_id, prompts, max_new_tokens=args.max_new_tokens
        )

        per_row_metrics = []
        for row, completion in zip(rows, completions):
            metrics = {name: fn(row["response"], completion) for name, fn in SCORERS.items()}
            metrics["composite"] = composite_score(metrics)
            metrics["task"] = row["task"]
            per_row_metrics.append(metrics)

        all_results[model_id] = per_row_metrics

        task_aggregates = defaultdict(lambda: defaultdict(list))
        for m in per_row_metrics:
            for k, v in m.items():
                if k != "task" and isinstance(v, (int, float)):
                    task_aggregates[m["task"]][k].append(v)

        print(f"\n[{model_id}] per-task aggregate:")
        for task in sorted(task_aggregates):
            scores = task_aggregates[task]
            print(f"  {task:35s}  "
                  f"composite={sum(scores['composite'])/len(scores['composite']):.3f}  "
                  f"citation={sum(scores['citation_recall'])/len(scores['citation_recall']):.3f}  "
                  f"mic={sum(scores['mic_value_recall'])/len(scores['mic_value_recall']):.3f}  "
                  f"structure={sum(scores['structure_coverage'])/len(scores['structure_coverage']):.3f}")

        overall = {k: sum(m[k] for m in per_row_metrics) / len(per_row_metrics)
                   for k in WEIGHTS}
        overall["composite"] = composite_score(overall)
        print(f"\n[{model_id}] OVERALL:")
        for k, v in overall.items():
            print(f"  {k:24s}  {v:.4f}")

    if args.output and len(args.model) > 1:
        with open(args.output, "w", newline="") as f:
            w = csv.writer(f)
            header = ["row_idx", "task"]
            for model_id in args.model:
                for metric in list(WEIGHTS) + ["composite"]:
                    header.append(f"{model_id}__{metric}")
            w.writerow(header)
            for i in range(len(rows)):
                row = [i, rows[i]["task"]]
                for model_id in args.model:
                    m = all_results[model_id][i]
                    for metric in list(WEIGHTS) + ["composite"]:
                        row.append(f"{m[metric]:.4f}")
                w.writerow(row)
        print(f"\nWrote side-by-side comparison to {args.output}")


if __name__ == "__main__":
    sys.exit(main() or 0)
