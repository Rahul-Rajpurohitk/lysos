"""Long-context evaluation suite.

Tests Designer in 5-15 turn dialogues with tool calls. Uses our existing
long-form-trace teacher distillation as held-out eval (sample 100 traces;
prefix-only as input, expect model to complete the trace).

Output: data/synthetic/agentic_long_context_eval.jsonl (held-out 100 traces)

Run:
  /tmp/lysos_venv/bin/python eval/long_context_eval.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "synthetic" / "agentic_long_form_traces.jsonl"
OUT = ROOT / "data" / "synthetic" / "agentic_long_context_eval.jsonl"


def main():
    print(f"Loading {INPUT}")
    rows = []
    with open(INPUT) as f:
        for line in f:
            rows.append(json.loads(line))
    print(f"  long-form rows: {len(rows):,}")

    # Sample 100 held-out
    rng = random.Random(0xCAFE_E2)
    sample = rng.sample(rows, min(100, len(rows)))

    if OUT.exists():
        OUT.unlink()

    n_eval = 0
    with open(OUT, "a") as f:
        for r in sample:
            msgs = r["messages"]
            # Take prefix: system + user + first 1-2 assistant turns + tool result
            # Model's task: continue the dialogue
            prefix_len = min(4, len(msgs) - 2)  # leave at least 2 messages as expected
            prefix = msgs[:prefix_len]
            expected_continuation = msgs[prefix_len:]
            row = {
                "task": "long_context_eval",
                "pathogen": r.get("pathogen"),
                "scale": r.get("scale", "unknown"),
                "n_total_turns": len(msgs),
                "prefix_turns": prefix_len,
                "expected_continuation_turns": len(expected_continuation),
                "messages_prefix": prefix,
                "expected_messages": expected_continuation,
                "evaluation_criteria": [
                    "Designer continues the dialogue with appropriate next tool call",
                    "Tool calls have valid arguments matching tool schema",
                    "Designer reads tool results and updates reasoning",
                    "Critic / Strategist invocations follow handoff envelope format",
                    "Final candidate report includes SMILES + composite + recommendation",
                ],
            }
            f.write(json.dumps(row) + "\n")
            n_eval += 1

    print(f"\nWrote {n_eval} long-context eval rows to {OUT}")
    print(f"Each row has a prefix (system + user + 1-2 assistant turns) and expected continuation.")
    print(f"Model is evaluated on:")
    print(f"  - Tool call format correctness")
    print(f"  - Sequential reasoning over tool results")
    print(f"  - Handoff envelope formatting")
    print(f"  - Final candidate report structure")


if __name__ == "__main__":
    sys.exit(main())
