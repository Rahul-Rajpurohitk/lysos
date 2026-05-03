"""Fix the 65 v1-inherited rows with empty messages='[]' field.

These are rows where prompt + response are valid but messages was never
serialized correctly during the v1 pro build. Without this fix, the
SFTTrainer would either skip or crash on them.

Rebuilds messages from prompt+response, saves the corrected dataset back
to data/processed/amr-stage2-pro-v2/, and re-pushes to HF Hub.
"""
import json
import sys
from pathlib import Path

from datasets import load_from_disk

LOCAL_DS = Path("data/processed/amr-stage2-pro-v2")


def main():
    print(f"Loading {LOCAL_DS}...")
    ds = load_from_disk(str(LOCAL_DS))
    print(f"  train: {len(ds['train']):,}, valid: {len(ds['valid']):,}")

    fixed = {"train": 0, "valid": 0}
    skipped = 0

    def fix(row):
        nonlocal skipped
        if row["messages"] != "[]":
            return row
        # Need both prompt and response
        if not row["prompt"] or not row["response"]:
            skipped += 1
            return row
        new_msgs = [
            {"role": "user", "content": row["prompt"]},
            {"role": "assistant", "content": row["response"]},
        ]
        row["messages"] = json.dumps(new_msgs, ensure_ascii=False)
        return row

    new_ds = {}
    for split in ds:
        before = sum(1 for m in ds[split]["messages"] if m == "[]")
        new_split = ds[split].map(fix, desc=f"Fixing {split}")
        after = sum(1 for m in new_split["messages"] if m == "[]")
        fixed[split] = before - after
        new_ds[split] = new_split
        print(f"  {split}: fixed {fixed[split]} of {before} empty rows ({after} remain)")

    print(f"\nSkipped (missing prompt/response): {skipped}")

    from datasets import DatasetDict
    import shutil
    out = DatasetDict(new_ds)
    # save to a tmp dir then atomically swap
    tmp = LOCAL_DS.parent / (LOCAL_DS.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    out.save_to_disk(str(tmp))
    shutil.rmtree(LOCAL_DS)
    tmp.rename(LOCAL_DS)
    print(f"  saved corrected dataset back to {LOCAL_DS}")

    # Verify
    final = load_from_disk(str(LOCAL_DS))
    final_empty = sum(1 for m in final["train"]["messages"] if m == "[]") + \
                  sum(1 for m in final["valid"]["messages"] if m == "[]")
    print(f"\n  remaining empty messages after fix: {final_empty}")

    # Push to HF
    print(f"\nPushing fix to rahul24raj/lysos-amr-stage2-pro-v2...")
    out.push_to_hub(
        "rahul24raj/lysos-amr-stage2-pro-v2",
        commit_message="v2.3: rebuild empty messages='[]' field for 65 v1-inherited rows",
    )
    print("Done")


if __name__ == "__main__":
    sys.exit(main() or 0)
