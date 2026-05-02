"""Cross-source SMILES dedup + train/test leakage audit.

Runs three independent checks and writes a JSON report:

  1. Cross-source overlap — for each pair of canonical sources, count how
     many canonical SMILES appear in both. Reveals e.g. "ChEMBL ∩ DrugBank
     = 1,234" → those 1,234 molecules are double-counted in Stage 2.

  2. Stage 2 train/valid split contamination — check that no SMILES in
     train also appears in valid, and vice versa. Stage 2 currently doesn't
     do scaffold split; this surfaces leakage.

  3. RL-prompts vs known-antibiotics leakage — Stage 3 scores molecules on
     novelty against the known-antibiotics index. If RL prompts directly
     namedrop a known antibiotic, the model can game novelty by copying.
     We flag any prompt that contains a known-antibiotic name as text.

Output:
  data/audits/leakage.json — full report

Usage:

    python scripts/check_leakage.py
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] leakage | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("leakage")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, default=Path("data/raw"))
    p.add_argument("--processed", type=Path, default=Path("data/processed"))
    p.add_argument("--audits", type=Path, default=Path("data/audits"))
    return p.parse_args()


def _load_canonical_smiles(path: Path) -> set[str]:
    """Read a CSV; return set of canonical SMILES (or sequences for AMPs)."""
    if not path.exists():
        return set()
    import pandas as pd
    df = pd.read_csv(path, low_memory=False)
    col = None
    for c in ("smiles", "sequence"):
        if c in df.columns:
            col = c
            break
    if col is None:
        return set()
    return set(
        df[col].dropna().astype(str).str.strip().tolist()
    ) - {"", "nan", "None"}


def cross_source_overlap(data_root: Path) -> dict:
    """Section 1: pairwise SMILES overlap across canonical sources."""
    sources = {
        "chembl":      data_root / "chembl_antibiotics.canonical.csv",
        "drugbank":    data_root / "drugbank_open.canonical.csv",
        "drugcentral": data_root / "drugcentral.canonical.csv",
        "npatlas":     data_root / "npatlas.canonical.csv",
        "pubchem":     data_root / "pubchem_antibacterial.canonical.csv",
        "zinc":        data_root / "zinc_drug_like.canonical.csv",
        "dbaasp":      data_root / "dbaasp_amps.canonical.csv",
        "dramp":       data_root / "dramp_amps.canonical.csv",
    }
    sets: dict[str, set[str]] = {}
    for k, p in sources.items():
        sets[k] = _load_canonical_smiles(p)
        log.info("  %s: %d unique", k, len(sets[k]))

    overlap_matrix: dict[str, dict[str, int]] = {}
    pair_overlaps: list[dict] = []
    keys = list(sets.keys())
    for i, a in enumerate(keys):
        overlap_matrix[a] = {}
        for j, b in enumerate(keys):
            if i >= j:
                continue
            inter = len(sets[a] & sets[b])
            overlap_matrix[a][b] = inter
            if inter > 0:
                pair_overlaps.append({
                    "a": a, "b": b,
                    "intersection": inter,
                    "a_size": len(sets[a]), "b_size": len(sets[b]),
                    "frac_a": round(inter / max(1, len(sets[a])), 3),
                    "frac_b": round(inter / max(1, len(sets[b])), 3),
                })
    pair_overlaps.sort(key=lambda r: r["intersection"], reverse=True)

    union = set()
    for s in sets.values():
        union |= s
    return {
        "per_source_unique": {k: len(v) for k, v in sets.items()},
        "union_unique": len(union),
        "pair_overlaps_top": pair_overlaps[:30],
        "duplicated_across_2plus": sum(
            1 for s in union
            if sum(1 for src_set in sets.values() if s in src_set) >= 2
        ),
    }


def stage2_split_leak(processed: Path) -> dict:
    """Section 2: Stage 2 train/valid contamination."""
    path = processed / "amr-stage2"
    if not path.exists():
        return {"error": f"{path} missing"}
    from datasets import load_from_disk
    ds = load_from_disk(str(path))
    if "valid" not in ds or "train" not in ds:
        return {"error": "no train/valid split"}

    # Compare hashes of (prompt, response) pairs since the dataset doesn't
    # surface raw SMILES per-row uniformly.
    import hashlib
    def _h(prompt, response):
        return hashlib.sha256(
            (str(prompt).strip().lower() + "||"
             + str(response).strip().lower()).encode("utf-8", errors="ignore")
        ).hexdigest()[:16]

    train_hashes = {
        _h(r["prompt"], r.get("response", "")) for r in ds["train"]
    }
    valid_hashes = {
        _h(r["prompt"], r.get("response", "")) for r in ds["valid"]
    }
    leak = train_hashes & valid_hashes

    # Also check SMILES leak (extracted from messages)
    SMI_RE = re.compile(r"SMILES[:=]\s*([A-Za-z0-9@+\-=#$%\[\]\(\)\\/.]+)")
    def _smiles(row):
        for field in ("prompt", "response"):
            text = str(row.get(field, ""))
            m = SMI_RE.search(text)
            if m:
                return m.group(1)
        return None

    train_smi = {_smiles(r) for r in ds["train"] if _smiles(r)}
    valid_smi = {_smiles(r) for r in ds["valid"] if _smiles(r)}
    smi_leak = train_smi & valid_smi

    return {
        "train_rows": len(ds["train"]),
        "valid_rows": len(ds["valid"]),
        "exact_pair_leak": len(leak),
        "exact_pair_leak_frac": round(len(leak) / max(1, len(ds["valid"])), 4),
        "smiles_leak_unique": len(smi_leak),
        "train_unique_smiles": len(train_smi),
        "valid_unique_smiles": len(valid_smi),
    }


def rl_prompts_vs_known(processed: Path) -> dict:
    """Section 3: RL prompts that namedrop known antibiotics
    (would let the model game novelty)."""
    rl_path = processed / "amr-rl-prompts"
    known_path = processed / "known-antibiotics.smiles"
    if not rl_path.exists() or not known_path.exists():
        return {"error": "RL prompts or known-antibiotics index missing"}

    from datasets import load_from_disk
    ds = load_from_disk(str(rl_path))

    known_names: set[str] = set()
    with open(known_path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.strip().split("\t")
            if len(parts) < 2:
                continue
            n = parts[1].strip()
            if n and len(n) >= 3 and n.replace("_", " ").replace("-", "").isascii():
                known_names.add(n.lower())

    # Single-word antibiotic NAMES we'd care about (curated)
    canonical_drug_names = {
        "vancomycin", "ampicillin", "penicillin", "amoxicillin", "methicillin",
        "ciprofloxacin", "levofloxacin", "moxifloxacin", "linezolid",
        "daptomycin", "polymyxin", "colistin", "tigecycline", "gentamicin",
        "tobramycin", "amikacin", "streptomycin", "neomycin",
        "tetracycline", "doxycycline", "minocycline", "rifampin",
        "isoniazid", "pyrazinamide", "ethambutol", "azithromycin",
        "erythromycin", "clarithromycin", "clindamycin", "trimethoprim",
        "sulfamethoxazole", "ceftriaxone", "cefotaxime", "ceftazidime",
        "meropenem", "imipenem", "ertapenem", "aztreonam", "fosfomycin",
        "nitrofurantoin", "metronidazole", "rifaximin", "bacitracin",
        "mupirocin", "chloramphenicol", "fusidic", "magainin", "melittin",
    }
    target_names = canonical_drug_names | known_names

    hits_per_prompt: list[dict] = []
    for split_name in ("train", "valid"):
        if split_name not in ds:
            continue
        for i, row in enumerate(ds[split_name]):
            text = str(row.get("prompt", "")).lower()
            for name in target_names:
                if f" {name}" in text or text.startswith(name):
                    hits_per_prompt.append({
                        "split": split_name, "i": i,
                        "drug_name": name,
                        "pathogen": row.get("pathogen_short"),
                        "prompt_excerpt": text[:140],
                    })
                    break  # one hit per prompt is enough
    return {
        "names_checked": len(target_names),
        "rl_prompt_hits": len(hits_per_prompt),
        "hits_first_15": hits_per_prompt[:15],
    }


def main() -> int:
    args = parse_args()
    args.audits.mkdir(parents=True, exist_ok=True)

    log.info("=" * 60)
    log.info("Section 1: cross-source SMILES overlap")
    log.info("=" * 60)
    section1 = cross_source_overlap(args.data_root)
    log.info("Top-5 source pairs by overlap:")
    for r in section1["pair_overlaps_top"][:5]:
        log.info("  %s ∩ %s = %d  (%.0f%% of %s, %.0f%% of %s)",
                 r["a"], r["b"], r["intersection"],
                 100 * r["frac_a"], r["a"], 100 * r["frac_b"], r["b"])
    log.info("Total union: %d unique molecules", section1["union_unique"])
    log.info("Duplicated across 2+ sources: %d", section1["duplicated_across_2plus"])

    log.info("=" * 60)
    log.info("Section 2: Stage 2 train/valid leakage")
    log.info("=" * 60)
    section2 = stage2_split_leak(args.processed)
    if "error" not in section2:
        log.info("  train: %d rows, valid: %d rows",
                 section2["train_rows"], section2["valid_rows"])
        log.info("  exact-pair leakage: %d (%.2f%% of valid)",
                 section2["exact_pair_leak"],
                 100 * section2["exact_pair_leak_frac"])
        log.info("  SMILES leakage: %d unique SMILES in both train+valid",
                 section2["smiles_leak_unique"])

    log.info("=" * 60)
    log.info("Section 3: RL prompts namedropping known drugs")
    log.info("=" * 60)
    section3 = rl_prompts_vs_known(args.processed)
    if "error" not in section3:
        log.info("  RL prompts mentioning a known drug name: %d",
                 section3["rl_prompt_hits"])

    report = {
        "cross_source_overlap": section1,
        "stage2_split_leak": section2,
        "rl_known_drug_namedrops": section3,
    }
    out = args.audits / "leakage.json"
    out.write_text(json.dumps(report, indent=2))
    log.info("\nFull report: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
