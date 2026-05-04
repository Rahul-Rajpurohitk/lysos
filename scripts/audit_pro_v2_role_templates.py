"""Audit Stage-2 pro-v2 for agent-role output template coverage.

Tells us in 60 seconds whether Gap 2 is real:
  - Designer  → 'PROPOSAL:' + 'RATIONALE:'
  - Critic    → 'WEAKNESS:' + 'TRANSFORMATION:'
  - Strategist→ 'DECISION:' (TERMINATE|CONTINUE|BRANCH)
  - Resistome → 'resistome' / 'resistance_genes' (system-side conditioning)
  - Multi-turn tool use → presence of 'tool_use' / 'tool_result'
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

from datasets import load_from_disk

ROOT = Path(__file__).resolve().parents[1]
DS_PATH = ROOT / "data" / "processed" / "amr-stage2-pro-v2"

PATTERNS = {
    "designer_proposal":   re.compile(r"\bPROPOSAL:\s*\S", re.IGNORECASE),
    "designer_rationale":  re.compile(r"\bRATIONALE:", re.IGNORECASE),
    "critic_weakness":     re.compile(r"\bWEAKNESS:", re.IGNORECASE),
    "critic_transform":    re.compile(r"\bTRANSFORMATION:", re.IGNORECASE),
    "critic_delta":        re.compile(r"\bEXPECTED_DELTA:", re.IGNORECASE),
    "critic_verdict":      re.compile(r"\bVERDICT:\s*(ACCEPT|REJECT)", re.IGNORECASE),
    "strategist_decision": re.compile(r"\bDECISION:\s*(TERMINATE|CONTINUE|BRANCH)", re.IGNORECASE),
    "strategist_terminate":re.compile(r"\bDECISION:\s*TERMINATE", re.IGNORECASE),
    "strategist_continue": re.compile(r"\bDECISION:\s*CONTINUE", re.IGNORECASE),
    "strategist_branch":   re.compile(r"\bDECISION:\s*BRANCH", re.IGNORECASE),
    "resistome_briefing":  re.compile(r"resistome|resistance gene", re.IGNORECASE),
    "tool_use_block":      re.compile(r"<tool_use>|tool_use\":|<tool_call>", re.IGNORECASE),
    "tool_result_block":   re.compile(r"<tool_result>|tool_result\":", re.IGNORECASE),
    "smiles_in_response":  re.compile(r"SMILES:|`[A-Z][^\s`]{8,}`"),
}

def row_text(row: dict) -> str:
    """Extract assistant + system + user text from a row in any reasonable schema."""
    parts = []
    for key in ("system", "prompt", "instruction", "input"):
        v = row.get(key)
        if isinstance(v, str): parts.append(v)
    msgs = row.get("messages")
    if isinstance(msgs, list):
        for m in msgs:
            if isinstance(m, dict):
                c = m.get("content")
                if isinstance(c, str): parts.append(c)
                elif isinstance(c, list):
                    for b in c:
                        if isinstance(b, dict) and isinstance(b.get("text"), str):
                            parts.append(b["text"])
    for key in ("response", "answer", "output", "completion", "assistant"):
        v = row.get(key)
        if isinstance(v, str): parts.append(v)
    return "\n".join(parts)


def main():
    print(f"Loading: {DS_PATH}")
    ds = load_from_disk(str(DS_PATH))
    counts = Counter()
    n_total = 0
    sample_hits: dict[str, list[int]] = {k: [] for k in PATTERNS}

    for split in ("train", "valid"):
        if split not in ds: continue
        sub = ds[split]
        for i, row in enumerate(sub):
            n_total += 1
            text = row_text(row)
            for name, pat in PATTERNS.items():
                if pat.search(text):
                    counts[name] += 1
                    if len(sample_hits[name]) < 3:
                        sample_hits[name].append(i)

    print(f"\nScanned {n_total:,} rows across train+valid.\n")
    print(f"{'Pattern':<28} {'Count':>10} {'%':>7}")
    print("-" * 50)
    for name in PATTERNS:
        c = counts[name]
        pct = 100.0 * c / max(1, n_total)
        flag = ""
        if "designer" in name and c < 1000: flag = " ← LOW"
        if "critic" in name and c < 1000: flag = " ← LOW"
        if "strategist" in name and c < 500: flag = " ← LOW"
        if "tool_use_block" in name and c < 1000: flag = " ← LOW (Gap 1)"
        if "resistome" in name and c < 2000: flag = " ← LOW (Gap 3)"
        print(f"{name:<28} {c:>10,} {pct:>6.2f}%{flag}")
    print("\nGuidance:")
    print("  Designer (PROPOSAL+RATIONALE) target: ≥ 1,000 each")
    print("  Critic (WEAKNESS+TRANSFORMATION+EXPECTED_DELTA) target: ≥ 1,000 each")
    print("  Strategist (DECISION) target: ≥ 500 each (T/C/B variants)")
    print("  Tool-use blocks target: ≥ 5,000 (Gap 1)")
    print("  Resistome conditioning target: ≥ 2,000 (Gap 3)")

if __name__ == "__main__":
    sys.exit(main())
