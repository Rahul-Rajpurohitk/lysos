"""Fix the train/valid prompt leak in lysos-rl-prompts.

Root cause: 376 unique prompts replicated ~30x for GRPO group sampling.
The valid split was sampled at row-level (not unique-prompt level), so all
266 valid unique prompts also appear in train — 100% leakage.

Fix: deterministically pick 2 unique prompts per pathogen (16 total) for
valid; ALL replicas of those prompts go to valid. Train gets the other
360 unique prompts and their replicas. This preserves GRPO replication
within each split.
"""
import hashlib
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

from datasets import Dataset, DatasetDict, load_dataset


HUB_ID = "rahul24raj/lysos-rl-prompts"
LOCAL_OUT = Path("data/processed/amr-rl-prompts")
VALID_PROMPTS_PER_PATHOGEN = 2


def stable_hash(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def main():
    print(f"Loading {HUB_ID}...")
    ds = load_dataset(HUB_ID)
    train, valid = ds["train"], ds["valid"]
    print(f"  train: {len(train):,}, valid: {len(valid):,}")

    # Pool train + valid into one corpus
    all_rows = list(train) + list(valid)
    print(f"  pooled: {len(all_rows):,} rows")

    # Group rows by (pathogen, prompt) — replicas of the same prompt
    by_path_prompt = defaultdict(list)
    for r in all_rows:
        by_path_prompt[(r["pathogen_short"], r["prompt"])].append(r)
    print(f"  unique (pathogen, prompt) tuples: {len(by_path_prompt):,}")

    # Per pathogen: deterministically pick N unique prompts for valid
    by_pathogen_prompts = defaultdict(list)
    for (path, prompt), rows in by_path_prompt.items():
        by_pathogen_prompts[path].append(prompt)

    valid_unique_prompts = set()
    for path, prompts in by_pathogen_prompts.items():
        sorted_prompts = sorted(prompts, key=stable_hash)
        # take VALID_PROMPTS_PER_PATHOGEN with smallest hash → goes to valid
        for p in sorted_prompts[:VALID_PROMPTS_PER_PATHOGEN]:
            valid_unique_prompts.add((path, p))

    print(f"  valid unique (pathogen, prompt) tuples: {len(valid_unique_prompts)}")

    # Allocate ALL replicas to their split
    train_rows, valid_rows = [], []
    for (path, prompt), rows in by_path_prompt.items():
        target = valid_rows if (path, prompt) in valid_unique_prompts else train_rows
        for r in rows:
            r["split"] = "valid" if target is valid_rows else "train"
            target.append(r)

    print(f"\nNew split: {len(train_rows):,} train + {len(valid_rows):,} valid")

    # Verify zero leak
    train_p = set(r["prompt"] for r in train_rows)
    valid_p = set(r["prompt"] for r in valid_rows)
    new_leak = train_p & valid_p
    print(f"  prompt-level leak: {len(new_leak)} (target: 0)")
    assert len(new_leak) == 0, f"Still leaking: {len(new_leak)} prompts"

    # Pathogen distribution check
    train_path_count = Counter(r["pathogen_short"] for r in train_rows)
    valid_path_count = Counter(r["pathogen_short"] for r in valid_rows)
    print(f"\n  pathogen × split:")
    for p in sorted(train_path_count):
        print(f"    {p:12s}  train={train_path_count[p]:5d}  valid={valid_path_count[p]:4d}")

    # Save locally
    out = DatasetDict({
        "train": Dataset.from_list(train_rows),
        "valid": Dataset.from_list(valid_rows),
    })
    if LOCAL_OUT.exists():
        shutil.rmtree(LOCAL_OUT)
    out.save_to_disk(str(LOCAL_OUT))
    print(f"\nSaved to {LOCAL_OUT}")

    print(f"Pushing to {HUB_ID}...")
    out.push_to_hub(
        HUB_ID,
        commit_message=(
            "v2: fix train/valid prompt leakage. Original split was "
            "row-level, leaving 100% of 266 unique valid prompts also "
            "present in train. New split: 2 unique prompts per pathogen "
            "to valid (16 total), all GRPO replicas grouped together. "
            "Zero prompt-level leakage."
        ),
    )
    print("Done")


if __name__ == "__main__":
    sys.exit(main() or 0)
