"""Build a seed list of (drug, pathogen, mechanism) tuples that need
chain-of-thought reasoning explanations.

Output: data/synthetic/reasoning_seeds.jsonl  — one seed per line, where
each seed is a structured record the *teacher* (Claude Opus 4.7 in this
project, since Claude Code is already paid → free top-tier CoT) will
expand into a 200-400 token explanation.

Seed types (high priority first):
  1. drug_pathogen_mic     — (drug, pathogen, measured MIC, drug class) →
                             "Why does X have this MIC against Y?"
  2. resistance_overcome   — (drug, resistance gene from CARD) →
                             "How would you redesign X to evade gene Z?"
  3. structure_activity    — pair of similar drugs with different MICs
                             → "Compare A and B; explain potency gap"
  4. mechanism_of_action   — drug → mechanism explanation (Wikipedia /
                             ChEMBL has it for ~200 drugs, expand to
                             5K via similar-class transfer)
  5. cross_pathogen_spectrum — drug + activity profile across 8 pathogens
                              → "Why is the spectrum what it is?"

After generation, the synthetic JSONL gets merged into amr-stage2-pro.

Usage:

    python scripts/build_reasoning_seeds.py
    # Then iteratively:
    python scripts/teacher_generate.py --batch 50  # called by Claude
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] seeds | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("seeds")


PATHOGEN_LIST = [
    "MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
    "Abaum", "Paer", "VRE", "NGono",
]
PATHOGEN_NAMES = {
    "MRSA": "Methicillin-resistant Staphylococcus aureus",
    "Mtb": "Mycobacterium tuberculosis",
    "EColi-CRE": "Carbapenem-resistant Escherichia coli",
    "KpneuCRE": "Carbapenem-resistant Klebsiella pneumoniae",
    "Abaum": "Multidrug-resistant Acinetobacter baumannii",
    "Paer": "Pseudomonas aeruginosa",
    "VRE": "Vancomycin-resistant Enterococcus faecium",
    "NGono": "Drug-resistant Neisseria gonorrhoeae",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, default=Path("data/raw"))
    p.add_argument("--output", type=Path,
                   default=Path("data/synthetic/reasoning_seeds.jsonl"))
    p.add_argument("--per-pathogen", type=int, default=300,
                   help="Per-pathogen seed cap")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def _safe_str(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


def build_drug_pathogen_seeds(data_root: Path, per_pathogen: int) -> list[dict]:
    """Top scaffolds × 8 pathogens, with their measured MIC."""
    import pandas as pd
    chembl = data_root / "chembl_antibiotics.canonical.csv"
    if not chembl.exists():
        chembl = data_root / "chembl_antibiotics.csv"
    if not chembl.exists():
        return []

    df = pd.read_csv(chembl, low_memory=False)
    df = df.dropna(subset=["smiles", "mic_log_ug_per_ml", "pathogen_short"])
    df["mic_log_ug_per_ml"] = pd.to_numeric(df["mic_log_ug_per_ml"],
                                            errors="coerce")
    df = df.dropna(subset=["mic_log_ug_per_ml"])
    df = df[(df["mic_log_ug_per_ml"] >= -3) & (df["mic_log_ug_per_ml"] <= 4)]

    # For each pathogen, pick representative range: high-potency, mid, low
    rng = random.Random(42)
    out: list[dict] = []
    for pathogen in PATHOGEN_LIST:
        sub = df[df["pathogen_short"] == pathogen]
        if len(sub) == 0:
            continue
        sub = sub.drop_duplicates(subset=["smiles"], keep="first")
        # Bin by potency
        strong = sub[sub["mic_log_ug_per_ml"] <= 0.3]   # ≤ 2 µg/mL
        mid    = sub[(sub["mic_log_ug_per_ml"] > 0.3) & (sub["mic_log_ug_per_ml"] <= 1.5)]  # 2-32
        weak   = sub[sub["mic_log_ug_per_ml"] > 1.5]    # ≥ 32
        n_each = max(1, per_pathogen // 3)
        for bucket, label in [(strong, "potent"), (mid, "moderate"), (weak, "weak")]:
            for _, row in bucket.sample(
                min(n_each, len(bucket)), random_state=42
            ).iterrows():
                out.append({
                    "kind": "drug_pathogen_mic",
                    "smiles": _safe_str(row["smiles"]),
                    "pathogen_short": pathogen,
                    "pathogen_full": PATHOGEN_NAMES[pathogen],
                    "mic_log_ug_per_ml": float(row["mic_log_ug_per_ml"]),
                    "mic_ug_per_ml": float(10 ** row["mic_log_ug_per_ml"]),
                    "potency": label,
                    "drug_name": _safe_str(row.get("name", "")),
                    "chembl_id": _safe_str(row.get("chembl_id", "")),
                })
    log.info("  drug_pathogen_mic seeds: %d", len(out))
    return out


def build_mechanism_seeds(data_root: Path) -> list[dict]:
    """Use Wikipedia drug overviews as seeds for mechanism elaboration."""
    import pandas as pd
    wiki = data_root / "wikipedia_amr.csv"
    if not wiki.exists():
        return []
    df = pd.read_csv(wiki)
    out: list[dict] = []
    for _, row in df.iterrows():
        title = _safe_str(row.get("title"))
        mech = _safe_str(row.get("mechanism", ""))[:1000]
        if title and mech and len(mech) > 100:
            out.append({
                "kind": "mechanism_deep_dive",
                "drug_name": title,
                "wikipedia_mechanism": mech,
            })
    log.info("  mechanism_deep_dive seeds: %d", len(out))
    return out


def build_resistance_overcome_seeds(data_root: Path) -> list[dict]:
    """For each major resistance gene, ask 'how to overcome it'."""
    import pandas as pd
    card_csv = data_root / "card_resistance.json"
    if not card_csv.exists():
        return []
    try:
        with open(card_csv) as f:
            data = json.load(f)
        rows = data if isinstance(data, list) else list(data.values())
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    seen_genes: set[str] = set()
    for r in rows:
        gene = (r.get("aro_name") or r.get("gene_name") or r.get("name") or "").strip()
        desc = (r.get("aro_description") or r.get("description") or "").strip()
        drug_class = (r.get("drug_class") or r.get("drugs") or "").strip()
        if not gene or len(gene) > 40 or gene in seen_genes:
            continue
        seen_genes.add(gene)
        if desc and drug_class:
            out.append({
                "kind": "resistance_overcome",
                "gene_name": gene,
                "gene_description": desc[:600],
                "drug_class": drug_class[:200],
            })
        if len(out) > 800:
            break
    log.info("  resistance_overcome seeds: %d", len(out))
    return out


def main() -> int:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    seeds = []
    seeds += build_drug_pathogen_seeds(args.data_root, args.per_pathogen)
    seeds += build_mechanism_seeds(args.data_root)
    seeds += build_resistance_overcome_seeds(args.data_root)

    rng = random.Random(args.seed)
    rng.shuffle(seeds)

    with open(args.output, "w") as f:
        for s in seeds:
            f.write(json.dumps(s) + "\n")
    log.info("Wrote %d seeds to %s", len(seeds), args.output)

    from collections import Counter
    log.info("By kind:")
    for k, n in Counter(s["kind"] for s in seeds).most_common():
        log.info("  %-25s %d", k, n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
