"""Take amr-rl-prompts (12K bare prompts, ZERO resistome briefings) and
produce amr-rl-prompts-v2 where every prompt carries a system message
with the pathogen's resistome briefing.

Without this, GRPO rollouts go in blind. With this, every rollout has
the same context the inference-time Designer agent sees.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workspace"))
sys.path.insert(0, str(ROOT / "scripts"))

from datasets import Dataset, DatasetDict, load_from_disk
from synth_agentic_traces import get_resistome_briefing

SRC = ROOT / "data" / "processed" / "amr-rl-prompts"
DST = ROOT / "data" / "processed" / "amr-rl-prompts-v2"

DESIGNER_SYS = (
    "You are the **Designer** agent in the Lysos Workbench. Use tools to "
    "ground your proposal. Output PROPOSAL: <SMILES> and RATIONALE: "
    "<2-3 sentences citing the resistome briefing>."
)

print(f"Loading {SRC}")
ds = load_from_disk(str(SRC))

# Cache resistome briefings per pathogen (8 calls, not 12K)
briefings: dict[str, str] = {}

def enrich_row(row: dict) -> dict:
    p = row.get("pathogen_short") or "?"
    if p not in briefings:
        briefings[p] = get_resistome_briefing(p)
    sys_msg = DESIGNER_SYS + "\n\n" + briefings[p]

    # Original prompt was a `messages` JSON-string with [user]; prepend system.
    msgs_raw = row.get("messages")
    if isinstance(msgs_raw, str):
        try: msgs = json.loads(msgs_raw)
        except: msgs = [{"role": "user", "content": row.get("prompt", "")}]
    else:
        msgs = msgs_raw or [{"role": "user", "content": row.get("prompt", "")}]
    enriched = [{"role": "system", "content": sys_msg}] + msgs
    return {
        "prompt":         row.get("prompt", ""),
        "pathogen_short": p,
        "pathogen_name":  row.get("pathogen_name", ""),
        "modality":       row.get("modality", "smiles"),
        "split":          row.get("split", "train"),
        "messages":       json.dumps(enriched),
    }

new_train = [enrich_row(r) for r in ds["train"]]
new_valid = [enrich_row(r) for r in ds["valid"]]

if DST.exists():
    import shutil; shutil.rmtree(DST)
out_ds = DatasetDict({
    "train": Dataset.from_list(new_train),
    "valid": Dataset.from_list(new_valid),
})
out_ds.save_to_disk(str(DST))
print(f"✅ amr-rl-prompts-v2:  train={len(out_ds['train']):,}  valid={len(out_ds['valid']):,}")
print(f"  briefings cached for: {sorted(briefings.keys())}")
