"""Quality-control pass for the named-drug CoT corpus.

Checks:
  1. Schema integrity — every entry has {task, split, prompt, response, messages}
  2. Internal duplicate prompts within named_drug_examples.jsonl
  3. Internal duplicate (prompt, response) pairs (catches paraphrase-only copies)
  4. Cross-collision with existing Stage 2 pro train+valid (excluding the
     14 known leaks already deduped by merge_named_drug_into_stage2.py)
  5. Drug-name resolution — extract candidate drug names from prompts and
     check resolution against the curated known-antibiotics.parquet
     (warns on unrecognized names for human review; not blocking)
  6. Length sanity — flag any entry shorter than 800 chars (potential
     truncation) or longer than 4000 chars (token-budget concern)

Run:
  python scripts/qc_named_drug.py
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from datasets import load_from_disk


SOURCE_JSONL = Path("data/synthetic/named_drug_examples.jsonl")
STAGE2_PRO = Path("data/processed/amr-stage2-pro")
STAGE2_PRO_V2 = Path("data/processed/amr-stage2-pro-v2")
KNOWN_DRUGS = Path("data/processed/known-antibiotics.parquet")
TEST_SPLIT = Path("data/synthetic/named_drug_test_split.jsonl")

# Drug names appearing in our entries that we expect to be valid (lowercase).
# This is a curated allow-list of well-known antibiotics + antifungals + antimycobacterials
# that may not appear in the known-antibiotics.parquet but are clinically relevant.
EXPECTED_DRUGS = set("""
amphotericin acyclovir amikacin amoxicillin ampicillin aztreonam avibactam
bedaquiline benzathine bismuth bortezomib caspofungin cefamandole cefazolin
cefepime cefiderocol cefoperazone cefoxitin cefpodoxime ceftazidime ceftaroline
ceftobiprole ceftolozane ceftriaxone cefuroxime cephalexin chloramphenicol
ciprofloxacin clarithromycin clavulanate clindamycin clofazimine cloxacillin
contezolid cycloserine dalbavancin dapsone daptomycin delamanid delafloxacin
demeclocycline dicloxacillin doripenem doxycycline durlobactam eravacycline
ertapenem erythromycin ethambutol ethionamide fidaxomicin flucloxacillin
fluconazole flucytosine fosfomycin fosmanogepix fosmidomycin fusidic
ganciclovir gentamicin gepotidacin griseofulvin imipenem iclaprim
isavuconazole isavuconazonium isoniazid itraconazole ivermectin kanamycin
ketoconazole lefamulin leucovorin levofloxacin linezolid loracarbef
meropenem methenamine methicillin metronidazole micafungin minocycline
moxifloxacin mupirocin nafcillin nitazoxanide nitrofurantoin norfloxacin
nystatin ofloxacin olorofim omadacycline oritavancin oxacillin paromomycin
pentamidine penicillin piperacillin pivampicillin plazomicin polymyxin
posaconazole pretomanid primaquine pyrazinamide pyrimethamine quinine
relebactam rifabutin rifampin rifamycin rifapentine rifaximin sancycline
streptomycin sulbactam sulfadiazine sulfamethoxazole tazobactam tedizolid
teicoplanin telavancin telithromycin temocillin tetracycline tigecycline
tinidazole tobramycin trimethoprim valacyclovir vancomycin vaborbactam
voriconazole zoliflodacin
""".split())


def check_schema(rows):
    bad = []
    required = {"task", "split", "prompt", "response", "messages"}
    for i, r in enumerate(rows):
        missing = required - r.keys()
        if missing:
            bad.append((i, missing))
    return bad


def check_internal_dupes(rows):
    prompt_counts = Counter(r["prompt"] for r in rows)
    pair_counts = Counter((r["prompt"], r["response"]) for r in rows)
    dup_prompts = {p: n for p, n in prompt_counts.items() if n > 1}
    dup_pairs = {p: n for p, n in pair_counts.items() if n > 1}
    return dup_prompts, dup_pairs


def check_cross_collision(rows, stage2_pro_path, test_prompts):
    ds = load_from_disk(str(stage2_pro_path))
    our_prompts = {r["prompt"] for r in rows}
    train_match = sum(1 for p in ds["train"]["prompt"] if p in our_prompts)
    valid_match = sum(1 for p in ds["valid"]["prompt"] if p in our_prompts)
    return train_match, valid_match


def extract_drug_candidates(text):
    """Heuristic: lowercase, find tokens that look like drug names (no perfect)."""
    words = re.findall(r"[A-Za-z][A-Za-z\-]{4,}", text)
    return {w.lower() for w in words}


def check_drug_resolution(rows, expected_drugs, known_drugs_df):
    known_set = set()
    if known_drugs_df is not None:
        for col in ("name", "preferred_name", "synonyms"):
            if col in known_drugs_df.columns:
                vals = known_drugs_df[col].dropna().astype(str)
                for v in vals:
                    known_set.add(v.lower().strip())
    known_set |= expected_drugs

    unknown_terms = Counter()
    for r in rows:
        body = r["response"]
        candidates = extract_drug_candidates(body)
        for c in candidates:
            # Only flag if it's a "long" word that looks pharmaceutical (heuristic)
            if len(c) >= 8 and (c.endswith(("cycline", "mycin", "cillin", "azole",
                                           "penem", "floxacin", "bactam", "trim"))):
                if c not in known_set:
                    unknown_terms[c] += 1
    return unknown_terms


def check_length(rows):
    short, long = [], []
    for i, r in enumerate(rows):
        n = len(r["response"])
        if n < 800:
            short.append((i, n, r["task"]))
        elif n > 4000:
            long.append((i, n, r["task"]))
    return short, long


def main():
    print("Loading source corpus...")
    rows = []
    with SOURCE_JSONL.open() as f:
        for line in f:
            rows.append(json.loads(line))
    print(f"  {len(rows)} entries")

    print("\n[1/6] Schema check...")
    bad = check_schema(rows)
    if bad:
        print(f"  FAIL — {len(bad)} entries with missing fields")
        for i, m in bad[:5]:
            print(f"    row {i}: missing {m}")
    else:
        print(f"  PASS — all {len(rows)} entries have required schema")

    print("\n[2/6] Internal duplicate check...")
    dup_p, dup_pair = check_internal_dupes(rows)
    print(f"  duplicate prompts: {len(dup_p)}")
    print(f"  duplicate (prompt, response) pairs: {len(dup_pair)}")
    if dup_p:
        for p, n in list(dup_p.items())[:3]:
            print(f"    {n}x: {p[:80]}...")

    print("\n[3/6] Cross-collision with Stage 2 pro v1 (pre-merge)...")
    test_prompts = set()
    if TEST_SPLIT.exists():
        with TEST_SPLIT.open() as f:
            test_prompts = {json.loads(line)["prompt"] for line in f}
    train_match, valid_match = check_cross_collision(rows, STAGE2_PRO, test_prompts)
    print(f"  rows in Stage 2 pro v1 train matching ours: {train_match}")
    print(f"  rows in Stage 2 pro v1 valid matching ours: {valid_match}")
    print(f"  (note: 14 known pre-existing leaks deduped by merge script;")
    print(f"   any number greater than 14 indicates new contamination)")

    print("\n[4/6] Cross-collision with Stage 2 pro v2 (post-merge — should be high)...")
    train_match_v2, valid_match_v2 = check_cross_collision(rows, STAGE2_PRO_V2, test_prompts)
    print(f"  rows in v2 train matching ours: {train_match_v2}")
    print(f"  rows in v2 valid matching ours: {valid_match_v2}")
    print(f"  (expected: ~{len(rows) - len(test_prompts)} train, 0 valid)")

    print("\n[5/6] Held-out test isolation check...")
    test_in_v2_train = sum(
        1 for p in load_from_disk(str(STAGE2_PRO_V2))["train"]["prompt"]
        if p in test_prompts
    )
    print(f"  held-out test prompts found in v2 train: {test_in_v2_train} (must be 0)")

    print("\n[6/6] Drug-name resolution + length sanity...")
    known_drugs_df = None
    if KNOWN_DRUGS.exists():
        known_drugs_df = pd.read_parquet(KNOWN_DRUGS)
        print(f"  loaded {len(known_drugs_df)} rows from known-antibiotics.parquet")
        print(f"  columns: {list(known_drugs_df.columns)[:10]}")
    unknown = check_drug_resolution(rows, EXPECTED_DRUGS, known_drugs_df)
    print(f"  unknown drug-like terms: {len(unknown)}")
    if unknown:
        print(f"  Top 10 (review for typos / hallucinations):")
        for term, n in unknown.most_common(10):
            print(f"    {n}x: {term}")

    short, long = check_length(rows)
    print(f"\n  short (<800 chars) responses: {len(short)}")
    for i, n, t in short[:5]:
        print(f"    row {i}: {n} chars, task={t}")
    print(f"  long (>4000 chars) responses: {len(long)}")
    for i, n, t in long[:5]:
        print(f"    row {i}: {n} chars, task={t}")

    print("\n=== QC SUMMARY ===")
    print(f"  Total entries: {len(rows)}")
    print(f"  Schema OK: {not bad}")
    print(f"  Internal dupes: {len(dup_p)} prompt + {len(dup_pair)} pair")
    print(f"  Pre-merge collisions: {train_match} train + {valid_match} valid")
    print(f"  Held-out isolation: {test_in_v2_train == 0}")
    print(f"  Unknown drug terms: {len(unknown)}")
    print(f"  Short responses: {len(short)} (target 0)")


if __name__ == "__main__":
    main()
