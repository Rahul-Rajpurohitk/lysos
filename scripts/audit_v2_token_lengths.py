"""Token-length audit on the v2 dataset against max_seq_length=4096.

Tokenizes every train + valid example with the Gemma 4 31B-it tokenizer (or
a compatible tokenizer fallback if the gated model isn't accessible) and
reports rows that would be SILENTLY TRUNCATED by the SFT trainer.

Critical for catching the case where elite reasoning entries (avg ~1700 chars,
some up to 7100 chars) might exceed the 4096 token budget and lose signal.

Usage:
  python scripts/audit_v2_token_lengths.py
  python scripts/audit_v2_token_lengths.py --tokenizer google/gemma-2-2b
  python scripts/audit_v2_token_lengths.py --max-seq 4096 --warn-at 0.85
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokenizer", default="gpt2",
                    help="Tokenizer for sizing (default gpt2, ungated). "
                         "Gemma 4 BPE differs by ~5-10% but identifies the same outlier rows.")
    ap.add_argument("--max-seq", type=int, default=4096,
                    help="Max seq length the trainer enforces (default 4096 from config)")
    ap.add_argument("--warn-at", type=float, default=0.85,
                    help="Flag rows that exceed warn_at * max_seq tokens (default 0.85)")
    ap.add_argument("--source", default="data/processed/amr-stage2-pro-v2",
                    help="Local v2 dataset dir")
    ap.add_argument("--limit-per-task", type=int, default=None,
                    help="Sample N rows per task type (default: all)")
    args = ap.parse_args()

    print(f"Loading tokenizer {args.tokenizer}...")
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.tokenizer)
    print(f"  vocab size: {tok.vocab_size}")

    print(f"\nLoading dataset {args.source}...")
    from datasets import load_from_disk
    ds = load_from_disk(args.source)
    print(f"  train: {len(ds['train']):,}, valid: {len(ds['valid']):,}")

    warn_threshold = int(args.max_seq * args.warn_at)
    print(f"\nMax-seq-length: {args.max_seq}")
    print(f"Warn threshold: {warn_threshold} tokens ({args.warn_at:.0%} of max)")
    print(f"Truncation hard limit: {args.max_seq} tokens — anything above is SILENTLY DROPPED\n")

    # Group rows by task
    by_task = defaultdict(list)
    for split in ("train", "valid"):
        for i in range(len(ds[split])):
            r = ds[split][i]
            by_task[r["task"]].append((split, i, r))

    # Sample per-task if limit set
    if args.limit_per_task:
        import random
        random.seed(0)
        for task in by_task:
            if len(by_task[task]) > args.limit_per_task:
                by_task[task] = random.sample(by_task[task], args.limit_per_task)

    # Tokenize and measure
    over_max = []   # actually exceed max_seq
    over_warn = []  # over warn but under max
    per_task_dist = defaultdict(list)

    print("Tokenizing... (this may take 1-2 min)")
    total_rows = sum(len(rows) for rows in by_task.values())
    counter = 0
    for task, rows in by_task.items():
        for split, idx, r in rows:
            counter += 1
            if counter % 25000 == 0:
                print(f"  [{counter}/{total_rows}]")
            # The actual training input is the formatted chat;
            # we approximate by tokenizing prompt + response (close enough)
            text = (r.get("prompt") or "") + " " + (r.get("response") or "")
            tokens = tok(text, add_special_tokens=False)["input_ids"]
            n = len(tokens)
            per_task_dist[task].append(n)
            if n > args.max_seq:
                over_max.append({"split": split, "idx": idx, "task": task,
                                 "n_tokens": n, "prompt_head": r["prompt"][:80]})
            elif n > warn_threshold:
                over_warn.append({"split": split, "idx": idx, "task": task,
                                  "n_tokens": n, "prompt_head": r["prompt"][:80]})

    # Per-task summary
    print(f"\n{'='*70}")
    print(f"Per-task token-length distribution")
    print(f"{'='*70}")
    print(f"{'task':40s} {'n':>6s} {'p50':>5s} {'p90':>5s} {'p99':>5s} {'max':>5s}")
    for task in sorted(per_task_dist):
        vals = sorted(per_task_dist[task])
        n = len(vals)
        p50 = vals[n // 2]
        p90 = vals[min(int(n * 0.9), n - 1)]
        p99 = vals[min(int(n * 0.99), n - 1)]
        mx = vals[-1]
        marker = "⚠" if mx > warn_threshold else " "
        print(f"{marker} {task:38s} {n:6d} {p50:5d} {p90:5d} {p99:5d} {mx:5d}")

    # Truncation report
    print(f"\n{'='*70}")
    print(f"Rows that exceed max_seq_length={args.max_seq} (TRUNCATED, signal LOST)")
    print(f"{'='*70}")
    print(f"  count: {len(over_max)}")
    if over_max:
        for o in over_max[:20]:
            print(f"  [{o['split']}:{o['idx']}] task={o['task']} n_tokens={o['n_tokens']}")
            print(f"    {o['prompt_head']}...")

    print(f"\n{'='*70}")
    print(f"Rows over warn threshold={warn_threshold} (close to truncation)")
    print(f"{'='*70}")
    print(f"  count: {len(over_warn)}")
    over_warn_by_task = Counter(o["task"] for o in over_warn)
    for task, n in over_warn_by_task.most_common(10):
        print(f"  {n:5d}  {task}")

    # Save report
    report = {
        "tokenizer": args.tokenizer,
        "max_seq": args.max_seq,
        "warn_at": args.warn_at,
        "warn_threshold": warn_threshold,
        "n_total": total_rows,
        "n_over_max": len(over_max),
        "n_over_warn": len(over_warn),
        "per_task_summary": {
            task: {
                "n": len(vals),
                "p50": sorted(vals)[len(vals)//2],
                "p90": sorted(vals)[min(int(len(vals)*0.9), len(vals)-1)],
                "p99": sorted(vals)[min(int(len(vals)*0.99), len(vals)-1)],
                "max": max(vals),
            } for task, vals in per_task_dist.items()
        },
        "over_max_examples": over_max[:50],
    }
    out = Path("reports/v2_token_length_audit.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"\nSaved report to {out}")

    if over_max:
        print(f"\n⚠ ACTION: {len(over_max)} rows exceed max_seq — consider raising")
        print(f"  max_seq_length to 5120 or 6144 in configs/stage2_amr_sft.yaml,")
        print(f"  OR shortening those entries.")
        return 1
    print(f"\n✅ ALL {total_rows:,} rows fit within max_seq_length={args.max_seq}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
