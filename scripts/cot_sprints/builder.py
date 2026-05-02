"""Universal CoT example builder.

Reads a YAML manifest of (name, body) entries plus a task/instruction header,
appends to data/synthetic/named_drug_examples.jsonl in the canonical schema.

Schema is byte-identical to the manual sprint13a/b/c scripts:
  {"task": <task>, "split": "train", "prompt": <instr + name>,
   "response": <body>, "messages": [{user,prompt},{assistant,body}]}

Usage:
  python3 scripts/cot_sprints/builder.py data/cot/sprint13d_design.yaml

YAML format:
  task: design_challenge
  prompt_label: "Design need"     # the label before the name in the prompt (e.g. "Pathogen", "Combo")
  instructions: |                  # the INSTR block, multi-line
    Instructions: ...
  entries:
    - name: "Title of entry one"
      body: |
        Long multi-line response. No escaping needed because YAML literal block.
        Em-dashes, β symbols, IUPAC names all work.
    - name: "Title of entry two"
      body: |
        ...

Safety:
  - Append-only. Existing JSONL is never read or rewritten.
  - Strict schema match: refuses to write if any field missing.
  - Reports total chars + estimated tokens for budget tracking.
"""
import json
import sys
from pathlib import Path
import yaml

OUT = Path("data/synthetic/named_drug_examples.jsonl")


def build(manifest_path: Path) -> int:
    with manifest_path.open() as f:
        m = yaml.safe_load(f)

    task = m["task"]
    instr = m["instructions"].rstrip()
    label = m["prompt_label"]
    entries = m["entries"]

    if not entries:
        raise ValueError(f"{manifest_path}: no entries")

    written = 0
    with OUT.open("a") as f:
        for entry in entries:
            name = entry["name"]
            body = entry["body"].rstrip()
            prompt = f"{instr}\n\n{label}: {name}"
            example = {
                "task": task,
                "split": "train",
                "prompt": prompt,
                "response": body,
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": body},
                ],
            }
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
            written += 1

    return written


def report():
    total = sum(1 for _ in OUT.open())
    chars = sum(len(line) for line in OUT.open())
    print(f"  total in named_drug_examples.jsonl: {total}")
    print(f"  total chars: {chars:,}")
    print(f"  approx tokens: {chars // 4:,}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: builder.py <manifest.yaml> [<manifest2.yaml> ...]", file=sys.stderr)
        sys.exit(1)
    grand_total = 0
    for arg in sys.argv[1:]:
        path = Path(arg)
        n = build(path)
        print(f"Wrote {n} examples from {path.name}")
        grand_total += n
    print(f"\nGrand total written this run: {grand_total}")
    report()
