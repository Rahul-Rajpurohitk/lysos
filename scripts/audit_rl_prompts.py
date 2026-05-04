"""Audit the Stage-3 GRPO prompt set."""
import json
from collections import Counter
from datasets import load_from_disk

ds = load_from_disk("/Users/rahulrajpurohit/IdeaProjects/lysos/data/processed/amr-rl-prompts")
print(f"Splits: {list(ds.keys())}")
print(f"Columns: {ds['train'].column_names}")
print()
r = ds['train'][0]
for k, v in r.items():
    if isinstance(v, str):
        print(f"  {k}: str ({len(v)} chars)  preview: {v[:200]!r}")
    else:
        print(f"  {k}: {type(v).__name__}  {str(v)[:200]!r}")

print()
# Distribution
by_pathogen = Counter()
by_constraint = Counter()
has_resistome = 0
mentions_smiles = 0
n = 0
for split in ds.keys():
    for row in ds[split]:
        n += 1
        text = " ".join(str(v) for v in row.values() if isinstance(v, str))
        for p in ["MRSA","Mtb","EColi-CRE","KpneuCRE","Abaum","Paer","VRE","NGono"]:
            if p in text: by_pathogen[p] += 1; break
        if "resistome" in text.lower() or "resistance gene" in text.lower():
            has_resistome += 1
        if "logP" in text or "MW" in text or "QED" in text or "constraint" in text.lower():
            by_constraint["has_constraint"] += 1
        if "SMILES" in text:
            mentions_smiles += 1

print(f"Total prompts: {n:,}")
print(f"\nPathogen distribution:")
for p, c in by_pathogen.most_common():
    print(f"  {p:<12s} {c:>6,} ({100*c/n:.1f}%)")
print(f"\nWith resistome briefing: {has_resistome:,} ({100*has_resistome/n:.1f}%)")
print(f"With explicit constraint: {by_constraint['has_constraint']:,}")
print(f"Mentions SMILES:          {mentions_smiles:,}")
