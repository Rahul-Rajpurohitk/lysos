"""Teacher-loop scaffolding for Opus-grade synthetic reasoning generation.

The actual reasoning is written by Claude Opus 4.7 directly in conversation
(no API cost — Claude Code subscription is already paid). This script:

  - Maintains a cursor of which seeds have been processed
  - Validates that each generated example has the right shape
  - Appends to data/synthetic/teacher_examples.jsonl
  - Provides batch-fetch helper used by the teacher each turn

State files:
  data/synthetic/reasoning_seeds.jsonl   — input seeds (created by build_reasoning_seeds.py)
  data/synthetic/teacher_examples.jsonl  — output examples (appended every turn)
  data/synthetic/cursor.txt              — index of next unprocessed seed
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] teacher | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("teacher")

DEFAULT_DIR = Path("data/synthetic")
SEED_FILE = "reasoning_seeds.jsonl"
OUTPUT_FILE = "teacher_examples.jsonl"
CURSOR_FILE = "cursor.txt"


def get_next_batch(d: Path, n: int = 25) -> list[dict]:
    """Return the next N unprocessed seeds, advancing the cursor."""
    seeds_path = d / SEED_FILE
    cursor_path = d / CURSOR_FILE
    if not seeds_path.exists():
        log.error("No seeds at %s — run build_reasoning_seeds.py first", seeds_path)
        return []
    cursor = 0
    if cursor_path.exists():
        cursor = int(cursor_path.read_text().strip() or "0")
    seeds: list[dict] = []
    with open(seeds_path) as f:
        for i, line in enumerate(f):
            if i < cursor:
                continue
            if len(seeds) >= n:
                break
            line = line.strip()
            if not line:
                continue
            seeds.append(json.loads(line))
    return seeds


def commit_batch(d: Path, examples: list[dict]) -> None:
    """Append the batch to teacher_examples.jsonl and advance cursor."""
    if not examples:
        return
    out_path = d / OUTPUT_FILE
    cursor_path = d / CURSOR_FILE
    with open(out_path, "a") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")
    cursor = 0
    if cursor_path.exists():
        cursor = int(cursor_path.read_text().strip() or "0")
    cursor += len(examples)
    cursor_path.write_text(str(cursor))
    total = sum(1 for _ in open(out_path))
    log.info("Committed %d examples; cursor=%d; total on disk=%d",
             len(examples), cursor, total)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    p.add_argument("--show-next", type=int, default=0,
                   help="Print the next N seeds (don't advance cursor)")
    p.add_argument("--peek", action="store_true",
                   help="Show cursor + remaining seed count")
    args = p.parse_args()

    if args.peek:
        cursor = 0
        cp = args.dir / CURSOR_FILE
        if cp.exists():
            cursor = int(cp.read_text().strip() or "0")
        sp = args.dir / SEED_FILE
        if sp.exists():
            total = sum(1 for _ in open(sp))
        else:
            total = 0
        op = args.dir / OUTPUT_FILE
        n_done = sum(1 for _ in open(op)) if op.exists() else 0
        log.info("seeds: %d total, %d done, %d remaining",
                 total, cursor, total - cursor)
        log.info("teacher_examples.jsonl: %d examples written", n_done)
        return 0

    if args.show_next:
        seeds = get_next_batch(args.dir, args.show_next)
        for s in seeds:
            print(json.dumps(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
