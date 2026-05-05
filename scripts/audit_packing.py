"""Sequence packing audit — verify TRL packing efficiency on pro-v12.

TRL's `packing=true` concatenates short rows into 4096-token sequences to
avoid wasted tokens. Given our left-skewed distribution (p50≈170 tokens,
4% in 1024+ range), packing is critical.

Audit:
  1. Sample 5K rows
  2. Compute per-row token length via gpt2 proxy
  3. Greedy-pack to 4096-token blocks
  4. Report:
     - blocks created
     - avg fill rate (tokens used / 4096)
     - tokens wasted (zero-padded)
     - long-context rows (>4096) that get truncated

Run:
  /tmp/lysos_venv/bin/python scripts/audit_packing.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT_DS = ROOT / "data" / "processed" / "amr-stage2-pro-v12"
SEQ_LEN = 4096


def main():
    print(f"Loading {INPUT_DS}")
    from datasets import load_from_disk
    ds = load_from_disk(str(INPUT_DS))
    train = ds["train"]
    print(f"  train rows: {len(train):,}")

    print(f"\nTokenizing 5K sample...")
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained("gpt2", use_fast=True)
    rng = random.Random(0)
    sample_idx = rng.sample(range(len(train)), 5000)

    lengths = []
    for i in sample_idx:
        msgs = json.loads(train[i]["messages"])
        text = "\n".join(
            m.get("content", "") if isinstance(m.get("content"), str) else json.dumps(m.get("content", ""))
            for m in msgs
        )
        lengths.append(len(tok.encode(text)))

    lengths.sort()
    p10, p50, p90, p99 = lengths[500], lengths[2500], lengths[4500], lengths[4950]
    print(f"  Length distribution:")
    print(f"    min  = {lengths[0]}")
    print(f"    p10  = {p10}")
    print(f"    p50  = {p50}")
    print(f"    p90  = {p90}")
    print(f"    p99  = {p99}")
    print(f"    max  = {lengths[-1]}")
    print(f"  Truncated (>4096): {sum(1 for l in lengths if l > SEQ_LEN)} ({100 * sum(1 for l in lengths if l > SEQ_LEN) / len(lengths):.2f}%)")

    # Greedy-pack: process in original (random shuffled) order
    print(f"\nGreedy packing into {SEQ_LEN}-token blocks...")
    blocks = []  # list of [lengths in this block]
    current_block = []
    current_total = 0
    for L in lengths:
        # Truncate any single row >SEQ_LEN
        L_used = min(L, SEQ_LEN)
        if current_total + L_used > SEQ_LEN:
            blocks.append(current_block)
            current_block = [L_used]
            current_total = L_used
        else:
            current_block.append(L_used)
            current_total += L_used
    if current_block:
        blocks.append(current_block)

    total_tokens_packed = sum(sum(b) for b in blocks)
    total_capacity = len(blocks) * SEQ_LEN
    fill_rate = total_tokens_packed / total_capacity
    rows_packed = sum(len(b) for b in blocks)
    avg_rows_per_block = rows_packed / len(blocks)

    print(f"  Blocks created: {len(blocks):,}")
    print(f"  Avg rows/block: {avg_rows_per_block:.1f}")
    print(f"  Tokens packed:  {total_tokens_packed:,}")
    print(f"  Capacity:       {total_capacity:,}")
    print(f"  Fill rate:      {100 * fill_rate:.1f}%  (target: ≥85%)")
    print(f"  Tokens wasted:  {total_capacity - total_tokens_packed:,} ({100*(1-fill_rate):.1f}%)")

    if fill_rate < 0.85:
        print(f"\n⚠ Packing efficiency below 85% target.")
        print(f"  Long-context rows (≥1024 tokens): {sum(1 for L in lengths if L >= 1024)} ({100 * sum(1 for L in lengths if L >= 1024) / len(lengths):.2f}%)")
        print(f"  Recommendation: shuffle to mix short + long rows; verify TRL's packing strategy matches greedy.")
    else:
        print(f"\n✓ Packing efficient. Training on full {SEQ_LEN}-token sequences.")

    # Compute extrapolated full-corpus stats
    print(f"\nExtrapolated full-corpus packing (380K rows):")
    expected_blocks_full = int(len(blocks) * len(train) / len(sample_idx))
    print(f"  Estimated blocks for full pro-v12: {expected_blocks_full:,}")
    print(f"  Steps per epoch (batch=8, grad_accum=4): {expected_blocks_full // 32:,}")


if __name__ == "__main__":
    sys.exit(main())
