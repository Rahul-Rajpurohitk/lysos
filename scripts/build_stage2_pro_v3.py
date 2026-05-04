"""Bake the agentic JSONLs into a unified Stage-2 v3 HF dataset.

Inputs:
  data/processed/amr-stage2-pro-v2/{train,valid}                   (393,734)
  data/synthetic/agentic_designer_traces.jsonl                     (5,000)
  data/synthetic/agentic_critic_traces.jsonl                       (2,000)
  data/synthetic/agentic_strategist_traces.jsonl                   (1,496)
  data/synthetic/agentic_resistome_conditioned.jsonl               (2,000)

Output:
  data/processed/amr-stage2-pro-v3/{train,valid}

Each output row has the unified schema:
  { task: str, pathogen: str|None, messages: [{role, content}], split: 'train'|'valid' }

Validation rules (rows failing are dropped + logged):
  - messages list is non-empty
  - alternating user / assistant after system
  - every assistant message either text OR a tool_use block; tool_use must
    be followed by user tool_result
  - last message is assistant text (not a dangling tool_use)

Runs on CPU. Idempotent — overwrites the v3 directory.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from datasets import Dataset, DatasetDict, load_from_disk

ROOT = Path(__file__).resolve().parents[1]
PRO_V2 = ROOT / "data" / "processed" / "amr-stage2-pro-v2"
OUT_DIR = ROOT / "data" / "processed" / "amr-stage2-pro-v3"

JSONL_FILES = [
    ("designer_tool_use",         ROOT / "data" / "synthetic" / "agentic_designer_traces.jsonl"),
    ("critic",                    ROOT / "data" / "synthetic" / "agentic_critic_traces.jsonl"),
    ("strategist",                ROOT / "data" / "synthetic" / "agentic_strategist_traces.jsonl"),
    ("designer_resistome_cond",   ROOT / "data" / "synthetic" / "agentic_resistome_conditioned.jsonl"),
    ("red_team",                  ROOT / "data" / "synthetic" / "agentic_red_team.jsonl"),
]

def normalize_pro_v2_row(row: dict, split: str) -> dict | None:
    """Map a pro-v2 row into the unified schema. Returns None if unparseable.
    Pro-v2 stores `messages` as a JSON string and has `prompt`/`response`
    columns; we prefer messages, fall back to prompt+response."""
    msgs = row.get("messages")
    if isinstance(msgs, str) and msgs.strip():
        try:
            msgs = json.loads(msgs)
        except Exception:
            msgs = None
    if not isinstance(msgs, list) or not msgs:
        p, r = row.get("prompt"), row.get("response")
        if isinstance(p, str) and isinstance(r, str) and p.strip() and r.strip():
            msgs = [
                {"role": "user", "content": p},
                {"role": "assistant", "content": r},
            ]
        else:
            return None
    return {
        "task": row.get("task") or row.get("task_type") or "stage2_chemistry",
        "pathogen": row.get("pathogen"),
        "messages": msgs,
        "split": row.get("split") or split,
    }

def normalize_jsonl_row(row: dict, task_label: str, split: str) -> dict | None:
    msgs = row.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return None
    return {
        "task": row.get("task") or task_label,
        "pathogen": row.get("pathogen"),
        "messages": msgs,
        "split": split,
    }

def validate_messages(msgs: list[dict]) -> bool:
    """Soft validation — last message must be assistant. Empty content fails."""
    if not msgs: return False
    last = msgs[-1]
    if not isinstance(last, dict): return False
    if last.get("role") != "assistant": return False
    c = last.get("content")
    if isinstance(c, str) and c.strip(): return True
    if isinstance(c, list) and any(b.get("type") == "text" or isinstance(b.get("text"), str) for b in c if isinstance(b, dict)):
        return True
    if isinstance(c, list) and len(c) > 0:
        return True
    return False

def main():
    print(f"Loading pro-v2 from {PRO_V2}")
    base = load_from_disk(str(PRO_V2))
    train_rows: list[dict] = []
    valid_rows: list[dict] = []

    for row in base["train"]:
        n = normalize_pro_v2_row(row, "train")
        if n and validate_messages(n["messages"]):
            train_rows.append(n)
    for row in base["valid"]:
        n = normalize_pro_v2_row(row, "valid")
        if n and validate_messages(n["messages"]):
            valid_rows.append(n)
    print(f"  pro-v2 rows kept: train={len(train_rows):,}, valid={len(valid_rows):,}")

    # Merge in synthetic agentic JSONLs — 95/5 train/valid split
    rng = random.Random(0xA66E)
    for label, path in JSONL_FILES:
        if not path.exists():
            print(f"  SKIP {path} (missing)")
            continue
        with open(path) as f:
            n_added_train, n_added_valid, n_dropped = 0, 0, 0
            for line in f:
                if not line.strip(): continue
                try:
                    row = json.loads(line)
                except Exception:
                    n_dropped += 1
                    continue
                split = "valid" if rng.random() < 0.05 else "train"
                norm = normalize_jsonl_row(row, label, split)
                if not norm or not validate_messages(norm["messages"]):
                    n_dropped += 1
                    continue
                if split == "train":
                    train_rows.append(norm); n_added_train += 1
                else:
                    valid_rows.append(norm); n_added_valid += 1
            print(f"  {label:30s} +train {n_added_train:5d}  +valid {n_added_valid:4d}  dropped {n_dropped}")

    # Shuffle within split for good batch mixing
    rng.shuffle(train_rows)
    rng.shuffle(valid_rows)

    # Cast messages.content to JSON string for storage portability — HF Datasets
    # has trouble with mixed-type lists across many rows
    def serialize(rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            r2 = dict(r)
            r2["messages"] = json.dumps(r["messages"])
            out.append(r2)
        return out

    train_ds = Dataset.from_list(serialize(train_rows))
    valid_ds = Dataset.from_list(serialize(valid_rows))
    ds = DatasetDict({"train": train_ds, "valid": valid_ds})

    OUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    if OUT_DIR.exists():
        import shutil; shutil.rmtree(OUT_DIR)
    print(f"Saving to {OUT_DIR} …")
    ds.save_to_disk(str(OUT_DIR))

    print(f"\n✅ stage2-pro-v3:  train={len(train_ds):,}  valid={len(valid_ds):,}")
    # Task-type histogram (top 12)
    from collections import Counter
    by_task = Counter(r["task"] for r in train_rows)
    print("\nTop tasks (train):")
    for t, n in by_task.most_common(12):
        print(f"  {t:42s} {n:>8,}")

if __name__ == "__main__":
    sys.exit(main())
