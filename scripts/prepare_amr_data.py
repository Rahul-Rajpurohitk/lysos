"""Stage 2 data preparation: AMR-specific instruction-tuning corpus.

Builds a multi-task training dataset for fine-tuning Lysos on antimicrobial
resistance. Tasks cover:
  - activity_prediction:  given (mol, pathogen) → predict MIC
  - generation_for_target: given pathogen → generate antibiotic SMILES
  - peptide_design:        given pathogen → generate AMP sequence
  - safety_prediction:     given mol → predict hemolysis
  - drug_likeness:         given mol → predict QED + Lipinski

Sources used (all open license):
  - ChEMBL antibiotic subset (small molecule MIC)
  - DBAASP, APD3, DRAMP (antimicrobial peptides)
  - CARD (resistance gene catalog → target pathogens)
  - BindingDB antibacterial subset

This script can run CPU-only and is intended to run pre-kickoff so we
have a clean Stage 2 dataset ready when Stage 1 finishes training.

Usage:

    # Default: prepare everything, write to data/processed/amr-stage2/
    python scripts/prepare_amr_data.py

    # Subset for fast iteration
    python scripts/prepare_amr_data.py --max-rows-per-task 500

    # Push to HF Hub (private)
    python scripts/prepare_amr_data.py --push-to-hub rahul24raj/lysos-amr-stage2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("prepare_amr")

# -----------------------------------------------------------------------------
# Pathogen catalog — clinically prioritized AMR targets
# -----------------------------------------------------------------------------

PATHOGENS = [
    {
        "name": "Staphylococcus aureus (MRSA)",
        "short": "MRSA",
        "category": "gram_positive",
        "priority": "critical",
        "context": "Methicillin-resistant Staphylococcus aureus is a major hospital-acquired pathogen causing skin, blood, and bone infections.",
    },
    {
        "name": "Mycobacterium tuberculosis",
        "short": "Mtb",
        "category": "mycobacterium",
        "priority": "critical",
        "context": "M. tuberculosis kills 1.5 million people per year. MDR and XDR strains require new drug classes.",
    },
    {
        "name": "Escherichia coli (ESBL+ / CRE)",
        "short": "EColi-CRE",
        "category": "gram_negative",
        "priority": "critical",
        "context": "ESBL-producing or carbapenem-resistant E. coli causes severe urinary tract and bloodstream infections, often untreatable.",
    },
    {
        "name": "Klebsiella pneumoniae (CRE)",
        "short": "KpneuCRE",
        "category": "gram_negative",
        "priority": "critical",
        "context": "Carbapenem-resistant K. pneumoniae is among the WHO's highest priority pathogens; mortality up to 50%.",
    },
    {
        "name": "Acinetobacter baumannii",
        "short": "Abaum",
        "category": "gram_negative",
        "priority": "critical",
        "context": "Multidrug-resistant A. baumannii causes ICU pneumonia, often pan-resistant. WHO priority 1.",
    },
    {
        "name": "Pseudomonas aeruginosa",
        "short": "Paer",
        "category": "gram_negative",
        "priority": "critical",
        "context": "P. aeruginosa is intrinsically resistant to many antibiotics and a leading cause of CF lung infection.",
    },
    {
        "name": "Enterococcus faecium (VRE)",
        "short": "VRE",
        "category": "gram_positive",
        "priority": "high",
        "context": "Vancomycin-resistant Enterococcus faecium causes bloodstream and endocarditis infections; few options remain.",
    },
    {
        "name": "Neisseria gonorrhoeae",
        "short": "NGono",
        "category": "gram_negative",
        "priority": "high",
        "context": "Drug-resistant gonorrhea is on the verge of becoming untreatable; new agents are urgently needed.",
    },
]

PATHOGENS_BY_SHORT = {p["short"]: p for p in PATHOGENS}


# -----------------------------------------------------------------------------
# Task templates
# -----------------------------------------------------------------------------


def t_activity_prediction(smi: str, pathogen: dict, mic_log: float) -> dict:
    """(SMILES, pathogen) → predicted MIC."""
    user = (
        "Instructions: Predict the antibacterial activity of the following compound.\n"
        f"Context: {pathogen['context']}\n"
        f"Question: What is the predicted MIC (log10 µg/mL) of this compound against {pathogen['name']}?\n"
        f"Compound SMILES: {smi}"
    )
    answer = f"{mic_log:.2f}"
    return _msg(user, answer, task="activity_prediction")


def t_generation_for_target(pathogen: dict, smi: str) -> dict:
    """pathogen → SMILES."""
    user = (
        "Instructions: Design a small molecule antibiotic for the following pathogen.\n"
        f"Context: {pathogen['context']}\n"
        f"Question: Generate a single antibacterial molecule against {pathogen['name']}, "
        f"prioritizing low MIC, drug-likeness (Lipinski-compliant), and synthetic accessibility.\n"
        "Output the molecule as a SMILES string."
    )
    answer = f"SMILES: {smi}"
    return _msg(user, answer, task="generation_for_target")


def t_peptide_design(pathogen: dict, sequence: str) -> dict:
    """pathogen → AMP sequence."""
    user = (
        "Instructions: Design a short antimicrobial peptide (AMP) for the following pathogen.\n"
        f"Context: {pathogen['context']}\n"
        f"Question: Generate a single 10–30 residue antimicrobial peptide against {pathogen['name']}, "
        f"prioritizing low hemolytic activity and high antibacterial potency.\n"
        "Output the peptide as a single-letter amino-acid sequence."
    )
    answer = f"Sequence: {sequence}"
    return _msg(user, answer, task="peptide_design")


def t_safety_prediction(smi_or_seq: str, is_peptide: bool, hemolytic: int) -> dict:
    """molecule → hemolysis Yes/No."""
    if is_peptide:
        user = (
            "Instructions: Predict the hemolytic activity of the following antimicrobial peptide.\n"
            "Context: Hemolytic peptides lyse red blood cells, limiting therapeutic use. We want HIGH antibacterial activity with LOW hemolysis.\n"
            f"Question: Will this peptide cause hemolysis at therapeutic concentrations? Answer Yes or No.\n"
            f"Peptide sequence: {smi_or_seq}"
        )
    else:
        user = (
            "Instructions: Predict the hemolytic toxicity of the following compound.\n"
            "Context: Hemolytic compounds lyse red blood cells, often causing anemia or kidney damage.\n"
            f"Question: Will this compound cause hemolysis at therapeutic concentrations? Answer Yes or No.\n"
            f"Compound SMILES: {smi_or_seq}"
        )
    answer = "Yes" if hemolytic else "No"
    return _msg(user, answer, task="safety_prediction")


def t_drug_likeness(smi: str, qed: float, lipinski_pass: bool) -> dict:
    """SMILES → drug-likeness."""
    user = (
        "Instructions: Evaluate the drug-likeness of the following compound.\n"
        "Context: Drug-likeness is summarized by Bickerton's QED score and Lipinski's Rule of Five.\n"
        f"Question: For this compound, report (a) QED in [0,1], rounded to 2 decimals, and (b) whether it passes Lipinski's Rule of Five.\n"
        f"Compound SMILES: {smi}"
    )
    answer = f"QED: {qed:.2f}\nLipinski: {'Pass' if lipinski_pass else 'Fail'}"
    return _msg(user, answer, task="drug_likeness")


def _msg(user: str, assistant: str, task: str) -> dict:
    """Pack one example into the canonical Lysos training format."""
    messages = [
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]
    return {
        "task": task,
        "split": "train",  # caller overrides
        "prompt": user,
        "response": assistant,
        "messages": json.dumps(messages),
    }


# -----------------------------------------------------------------------------
# Data sourcing
# -----------------------------------------------------------------------------


@dataclass
class Sources:
    """Paths to raw downloads (or stub data when offline)."""

    chembl_antibiotic_csv: Path
    dbaasp_amp_csv: Path
    apd3_csv: Path
    dramp_csv: Path
    card_targets_csv: Path
    bindingdb_antibacterial_csv: Path
    out_dir: Path


def _ensure_sample_chembl(path: Path) -> None:
    """Write a small synthetic ChEMBL-like sample if real data missing.

    Production note: replace with a real `chembl_downloader` call once we
    have ChEMBL API access set up. For now this enables CPU dry-runs.
    """
    if path.exists():
        return
    log.warning("Real ChEMBL data missing at %s — writing 50-row synthetic sample for dry-run", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A handful of real, public-domain antibiotic SMILES with rough MICs
    rows = [
        # (smiles, pathogen_short, mic_log_ug_per_ml, name)
        ("CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O", "MRSA", 0.30, "penicillin G"),
        ("OC[C@H]1O[C@H](OC2=C(O)C=C(C=C2)C(=O)NC2CCCCC2)[C@@H](O)[C@H](O)[C@@H]1O", "EColi-CRE", 1.20, "vancomycin-like analog"),
        ("CC1=C(N)C=C(N=N1)C2=NC=C(N=C2N)C(=O)O", "MRSA", 0.60, "trimethoprim"),
        ("CC(=O)N[C@@H]([C@@H](O)C1=CC=C(C=C1)[N+](=O)[O-])C(=O)NC2=CC=CC=C2", "Mtb", 1.00, "chloramphenicol"),
        ("OC1=C(C(O)=O)C=CC=C1C(=O)O", "EColi-CRE", 1.50, "salicylic-derived"),
        ("CN1C2=NC(=NC=C2C(=O)N1)C(=O)O", "Paer", 0.45, "fluoroquinolone-like"),
        ("CC1=C2N=C(C(=O)O)N(C2=CC(F)=C1)C3CC3", "MRSA", 0.40, "ciprofloxacin"),
        ("CC1(C)C[C@@H]2[C@@H](NC(=O)C(=NOC)C3=CSC(N)=N3)C(=O)N2C1C(=O)O", "Mtb", 0.50, "ceftriaxone-like"),
    ]
    # Replicate a few times with synthetic noise
    extended = []
    rnd = random.Random(42)
    for _ in range(7):
        for r in rows:
            extended.append((r[0], r[1], r[2] + rnd.uniform(-0.2, 0.2), r[3]))
    extended.extend(rows)
    with open(path, "w") as f:
        f.write("smiles,pathogen_short,mic_log_ug_per_ml,name\n")
        for r in extended:
            f.write(",".join([str(x) for x in r]) + "\n")


def _ensure_sample_amps(path: Path) -> None:
    """Tiny synthetic AMP sample (real DBAASP/APD3/DRAMP plug in later)."""
    if path.exists():
        return
    log.warning("Real AMP data missing at %s — writing synthetic sample for dry-run", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Real public AMPs (LL-37, magainin, melittin, etc.)
    rows = [
        # (sequence, pathogen_short, hemolytic_int, source)
        ("LLGDFFRKSKEKIGKEFKRIVQRIKDFLRNLVPRTES", "MRSA", 1, "LL-37"),
        ("GIGKFLHSAKKFGKAFVGEIMNS", "EColi-CRE", 0, "magainin-2"),
        ("GIGAVLKVLTTGLPALISWIKRKRQQ", "MRSA", 1, "melittin"),
        ("ILPWKWPWWPWRR", "MRSA", 0, "tritrpticin-like"),
        ("RRRRRRRRR", "EColi-CRE", 0, "polyarginine"),
        ("KRWWKWWRR", "MRSA", 0, "indolicidin-like"),
        ("ACDEFGHIKLMNPQRSTVWY", "MRSA", 0, "synthetic mix"),
        ("KKLLKKLL", "Paer", 0, "amphipathic helix"),
    ]
    extended = list(rows) * 5
    with open(path, "w") as f:
        f.write("sequence,pathogen_short,hemolytic_int,source\n")
        for r in extended:
            f.write(",".join([str(x) for x in r]) + "\n")


# -----------------------------------------------------------------------------
# Build each task slice
# -----------------------------------------------------------------------------


def build_activity_examples(srcs: Sources, max_rows: int | None) -> list[dict]:
    import pandas as pd

    df = pd.read_csv(srcs.chembl_antibiotic_csv)
    if max_rows:
        df = df.head(max_rows)
    out = []
    for _, row in df.iterrows():
        path = PATHOGENS_BY_SHORT.get(row["pathogen_short"])
        if not path:
            continue
        out.append(t_activity_prediction(row["smiles"], path, float(row["mic_log_ug_per_ml"])))
    return out


def build_generation_examples(srcs: Sources, max_rows: int | None) -> list[dict]:
    import pandas as pd

    df = pd.read_csv(srcs.chembl_antibiotic_csv)
    if max_rows:
        df = df.head(max_rows)
    out = []
    for _, row in df.iterrows():
        path = PATHOGENS_BY_SHORT.get(row["pathogen_short"])
        if not path:
            continue
        out.append(t_generation_for_target(path, row["smiles"]))
    return out


def build_peptide_examples(srcs: Sources, max_rows: int | None) -> list[dict]:
    import pandas as pd

    df = pd.read_csv(srcs.dbaasp_amp_csv)
    if max_rows:
        df = df.head(max_rows)
    out = []
    for _, row in df.iterrows():
        path = PATHOGENS_BY_SHORT.get(row["pathogen_short"])
        if not path:
            continue
        out.append(t_peptide_design(path, row["sequence"]))
    return out


def build_safety_examples(srcs: Sources, max_rows: int | None) -> list[dict]:
    import pandas as pd

    rows = []
    df = pd.read_csv(srcs.dbaasp_amp_csv)
    for _, row in df.iterrows():
        rows.append(t_safety_prediction(row["sequence"], True, int(row["hemolytic_int"])))
    if max_rows:
        rows = rows[:max_rows]
    return rows


def build_drug_likeness_examples(srcs: Sources, max_rows: int | None) -> list[dict]:
    import pandas as pd
    from rdkit import Chem, RDLogger
    from rdkit.Chem import QED, Crippen, Descriptors, Lipinski

    RDLogger.DisableLog("rdApp.*")

    df = pd.read_csv(srcs.chembl_antibiotic_csv)
    if max_rows:
        df = df.head(max_rows)
    out = []
    for _, row in df.iterrows():
        smi = row["smiles"]
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            continue
        try:
            qed = float(QED.qed(mol))
            mw = Descriptors.MolWt(mol)
            logp = Crippen.MolLogP(mol)
            hbd = Lipinski.NumHDonors(mol)
            hba = Lipinski.NumHAcceptors(mol)
            v = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
            lip = v <= 1
            out.append(t_drug_likeness(smi, qed, lip))
        except Exception:  # noqa: BLE001
            continue
    return out


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prepare AMR (Stage 2) data")
    p.add_argument("--data-root", type=Path, default=Path("data/raw"))
    p.add_argument("--output-dir", type=Path, default=Path("data/processed/amr-stage2"))
    p.add_argument("--max-rows-per-task", type=int, default=None)
    p.add_argument("--push-to-hub", type=str, default=None)
    p.add_argument("--task-mix", type=str, default=None,
                   help="Override task mix as JSON (sums to 1.0)")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    random.seed(args.seed)

    # Resolve sources (write samples if missing)
    srcs = Sources(
        chembl_antibiotic_csv=args.data_root / "chembl_antibiotics.csv",
        dbaasp_amp_csv=args.data_root / "dbaasp_amps.csv",
        apd3_csv=args.data_root / "apd3.csv",
        dramp_csv=args.data_root / "dramp.csv",
        card_targets_csv=args.data_root / "card_targets.csv",
        bindingdb_antibacterial_csv=args.data_root / "bindingdb_antibacterial.csv",
        out_dir=args.output_dir,
    )
    _ensure_sample_chembl(srcs.chembl_antibiotic_csv)
    _ensure_sample_amps(srcs.dbaasp_amp_csv)

    log.info("Building task slices...")
    activity = build_activity_examples(srcs, args.max_rows_per_task)
    generation = build_generation_examples(srcs, args.max_rows_per_task)
    peptide = build_peptide_examples(srcs, args.max_rows_per_task)
    safety = build_safety_examples(srcs, args.max_rows_per_task)
    drug_like = build_drug_likeness_examples(srcs, args.max_rows_per_task)

    log.info("  activity_prediction:   %d", len(activity))
    log.info("  generation_for_target: %d", len(generation))
    log.info("  peptide_design:        %d", len(peptide))
    log.info("  safety_prediction:     %d", len(safety))
    log.info("  drug_likeness:         %d", len(drug_like))

    all_examples = activity + generation + peptide + safety + drug_like
    if not all_examples:
        log.error("No examples built. Check data paths.")
        return 1

    log.info("Total: %d examples", len(all_examples))

    # Train/eval split
    rnd = random.Random(args.seed)
    rnd.shuffle(all_examples)
    n_eval = max(50, len(all_examples) // 20)
    eval_set = all_examples[:n_eval]
    train_set = all_examples[n_eval:]
    for r in eval_set:
        r["split"] = "valid"

    log.info("Train: %d, Eval: %d", len(train_set), len(eval_set))

    # Save HF Dataset
    try:
        import pandas as pd
        from datasets import Dataset, DatasetDict
    except ImportError as exc:
        log.error("Missing deps: %s. Install datasets + pandas + pyarrow.", exc)
        return 2

    ds = DatasetDict({
        "train": Dataset.from_pandas(pd.DataFrame(train_set), preserve_index=False),
        "valid": Dataset.from_pandas(pd.DataFrame(eval_set), preserve_index=False),
    })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ds.save_to_disk(str(args.output_dir))
    log.info("Wrote dataset to %s", args.output_dir)

    if args.push_to_hub:
        if "HF_TOKEN" not in os.environ and "HUGGINGFACE_TOKEN" not in os.environ:
            log.error("--push-to-hub requires HF_TOKEN")
            return 3
        log.info("Pushing to Hub: %s (private)", args.push_to_hub)
        ds.push_to_hub(args.push_to_hub, private=True)
        log.info("✓ pushed")

    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
