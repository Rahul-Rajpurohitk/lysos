"""build_pharma_qa_layer.py — turn the named-drug enrichment into SFT pairs.

Why this script exists:
  We paid Gemini 2.5 Pro $2.59 to write rich pharmacology JSON + reasoning
  for 218 named antibiotics. That's stored in
  artifacts/embeddings/named-drugs-gemini-enrichment.parquet.

  This script converts each row into 4 Q&A training pairs with the
  reasoning trace as gold chain-of-thought. The result is a new Stage-2
  SFT layer with ~870 training rows of clinical-grade pharmacology
  reasoning — 100% free (no additional API cost), pure local generation.

Output:
  data/synthetic/pharma_qa_layer.jsonl  — JSONL of {messages, task} rows
                                          ready for HF DatasetDict folding

Schema for each row:
  {
    "task": "pharma_qa",
    "drug": <name>,
    "question_type": "mechanism" | "spectrum" | "indications" | "resistance",
    "messages": [
      {"role": "user", "content": <question>},
      {"role": "assistant", "content": <reasoning>\n<answer>}
    ]
  }

The reasoning trace is sliced from the cached `thinking` column (already
paid for) and formatted as a chain-of-thought before the concise answer.
This trains Stage-2 to reason explicitly about drug pharmacology, not
just answer in one line.

Run:
  python3 scripts/build_pharma_qa_layer.py
  python3 scripts/build_pharma_qa_layer.py --limit 10  # smoke test
  python3 scripts/build_pharma_qa_layer.py --include-thinking  # CoT mode
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "artifacts" / "embeddings" / "named-drugs-gemini-enrichment.parquet"
OUT_DEFAULT = ROOT / "data" / "synthetic" / "pharma_qa_layer.jsonl"


# Question templates per axis. Multiple phrasings per axis = better
# generalization across question style.
QUESTION_TEMPLATES = {
    "mechanism": [
        "What is the mechanism of action of {drug}?",
        "How does {drug} kill bacteria? Explain the molecular target.",
        "Describe the mechanism by which {drug} exerts its antibacterial effect.",
        "Mechanism of {drug}: what cellular target does it bind?",
    ],
    "spectrum": [
        "What pathogens does {drug} cover? Describe its spectrum.",
        "Is {drug} active against Gram-negative or Gram-positive bacteria? Which species?",
        "Describe the antibacterial spectrum of {drug} clinically.",
    ],
    "indications": [
        "What is {drug} typically used to treat?",
        "List the major clinical indications for {drug}.",
        "When would a clinician choose {drug} over alternatives?",
    ],
    "resistance": [
        "How do bacteria typically develop resistance to {drug}?",
        "What are the main resistance mechanisms against {drug}?",
        "Which mechanisms allow bacteria to escape {drug}? Mention specific genes/enzymes if known.",
    ],
}


def _summarize_thinking(thinking: str, max_chars: int = 800) -> str:
    """Extract a clean reasoning summary from the raw thinking trace.

    The Gemini thinking trace often includes self-prompts like
    "Okay, let me think about this..." and meta-commentary. We strip
    the most obvious noise but keep the substantive reasoning.
    """
    if not thinking:
        return ""
    text = thinking.strip()
    # Drop the markdown header line (e.g. "**Penicillin G JSON Generation**")
    lines = text.splitlines()
    if lines and lines[0].startswith("**") and lines[0].endswith("**"):
        lines = lines[1:]
    # Re-join, preserve paragraph breaks
    cleaned = "\n".join(lines).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 1].rstrip() + "…"
    return cleaned


def _format_assistant(card: dict, axis: str, *,
                       thinking: str = "",
                       include_thinking: bool = False) -> str:
    """Format the assistant's response: optional CoT then concise answer."""
    answer_field = {
        "mechanism": card["mechanism"],
        "spectrum": card["spectrum"],
        "indications": card["indications"],
        "resistance": card["resistance_escape"],
    }[axis]

    if include_thinking and thinking:
        return (
            f"<reasoning>\n{thinking}\n</reasoning>\n\n"
            f"{answer_field.strip()}"
        )
    return answer_field.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", type=Path, default=PARQUET)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--include-thinking", action="store_true",
                    help="Wrap reasoning trace in <reasoning>…</reasoning> tags "
                         "before the answer (chain-of-thought training mode).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap to N drugs (smoke test).")
    ap.add_argument("--seed", type=int, default=0xBEEF)
    args = ap.parse_args()

    if not args.parquet.exists():
        print(f"[X] Enrichment parquet not found: {args.parquet}")
        print(f"    Run scripts/enrich_named_drugs_with_gemini.py first.")
        return 1

    import pandas as pd
    df = pd.read_parquet(args.parquet)
    print(f"[INFO] Loaded {len(df)} enriched drugs from {args.parquet.name}")
    if args.limit:
        df = df.head(args.limit)

    rng = random.Random(args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        card = {
            "mechanism": str(row.get("mechanism", "")).strip(),
            "spectrum": str(row.get("spectrum", "")).strip(),
            "indications": str(row.get("indications", "")).strip(),
            "resistance_escape": str(row.get("resistance_escape", "")).strip(),
        }
        if not card["mechanism"]:
            continue  # skip empty enrichments
        thinking = _summarize_thinking(str(row.get("thinking", "")))

        for axis, templates in QUESTION_TEMPLATES.items():
            answer = card["resistance_escape"] if axis == "resistance" else card[axis]
            if not answer:
                continue
            q = rng.choice(templates).format(drug=name)
            a = _format_assistant(card, axis,
                                  thinking=thinking,
                                  include_thinking=args.include_thinking)
            rows.append({
                "task": "pharma_qa",
                "drug": name,
                "question_type": axis,
                "messages": [
                    {"role": "user", "content": q},
                    {"role": "assistant", "content": a},
                ],
            })

    rng.shuffle(rows)

    with args.out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    by_axis: dict[str, int] = {}
    for r in rows:
        by_axis[r["question_type"]] = by_axis.get(r["question_type"], 0) + 1
    print(f"[OK] Wrote {len(rows)} Q&A pairs to {args.out}")
    print(f"[OK] By axis: {by_axis}")
    print(f"[OK] CoT mode: {'on (with <reasoning> blocks)' if args.include_thinking else 'off (concise answer only)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
