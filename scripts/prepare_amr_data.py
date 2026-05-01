"""Stage 2 data preparation: AMR-specific instruction-tuning corpus.

Builds a multi-task training dataset for fine-tuning Lysos on antimicrobial
resistance. Tasks cover:
  - activity_prediction:  given (mol, pathogen) → predict MIC
  - generation_for_target: given pathogen → generate antibiotic SMILES
  - peptide_design:        given pathogen → generate AMP sequence
  - safety_prediction:     given mol → predict hemolysis
  - drug_likeness:         given mol → predict QED + Lipinski

Sources used (all open license, REAL data — no synthetic stubs):
  - ChEMBL antibacterial activities (src/data/chembl.py)
  - DBAASP antimicrobial peptides   (src/data/dbaasp.py)
  - (later) APD3, DRAMP, CARD

Usage:

    # 1. Fetch raw data first (one-time, ~5-15 min)
    python -m src.data.chembl --output data/raw/chembl_antibiotics.csv
    python -m src.data.dbaasp --output data/raw/dbaasp_amps.csv

    # 2. Build the Stage 2 instruction corpus
    python scripts/prepare_amr_data.py

    # OR: --fetch in one go (fetch + build)
    python scripts/prepare_amr_data.py --fetch

    # Cap rows per task for fast iteration
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
        "split": "train",
        "prompt": user,
        "response": assistant,
        "messages": json.dumps(messages),
    }


# -----------------------------------------------------------------------------
# Data sourcing — REAL loaders
# -----------------------------------------------------------------------------


@dataclass
class Sources:
    """Paths to raw downloads from real data loaders."""

    chembl_csv: Path
    dbaasp_csv: Path
    out_dir: Path


def _ensure_data(srcs: Sources, fetch: bool) -> None:
    """Verify raw data exists; optionally fetch it from real APIs."""
    if not srcs.chembl_csv.exists():
        if fetch:
            log.info("Fetching ChEMBL antibacterial activities...")
            from src.data.chembl import fetch_amr_activities
            fetch_amr_activities(out_path=srcs.chembl_csv)
        else:
            log.error(
                "ChEMBL data not found at %s\n"
                "  Run: python -m src.data.chembl --output %s\n"
                "  Or:  python scripts/prepare_amr_data.py --fetch",
                srcs.chembl_csv, srcs.chembl_csv,
            )
            raise FileNotFoundError(srcs.chembl_csv)

    if not srcs.dbaasp_csv.exists():
        if fetch:
            log.info("Fetching DBAASP antimicrobial peptides...")
            from src.data.dbaasp import fetch_amps
            fetch_amps(out_path=srcs.dbaasp_csv)
        else:
            log.error(
                "DBAASP data not found at %s\n"
                "  Run: python -m src.data.dbaasp --output %s\n"
                "  Or:  python scripts/prepare_amr_data.py --fetch",
                srcs.dbaasp_csv, srcs.dbaasp_csv,
            )
            raise FileNotFoundError(srcs.dbaasp_csv)


# -----------------------------------------------------------------------------
# Build each task slice
# -----------------------------------------------------------------------------


def build_activity_examples(srcs: Sources, max_rows: int | None) -> list[dict]:
    import pandas as pd

    df = pd.read_csv(srcs.chembl_csv)
    # Drop rows where MIC didn't normalize
    df = df.dropna(subset=["smiles", "pathogen_short", "mic_log_ug_per_ml"])
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

    df = pd.read_csv(srcs.chembl_csv)
    # Only generate from highly potent compounds (pchembl >= 5, ie IC50 <= 10µM)
    if "pchembl_value" in df.columns:
        df = df[df["pchembl_value"] >= 5.0]
    df = df.dropna(subset=["smiles", "pathogen_short"])
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

    df = pd.read_csv(srcs.dbaasp_csv)
    df = df.dropna(subset=["sequence", "pathogen_short"])
    # Only use peptides with non-hemolytic activity for generation training
    if "hemolytic_int" in df.columns:
        df = df[df["hemolytic_int"] == 0]
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

    df = pd.read_csv(srcs.dbaasp_csv)
    df = df.dropna(subset=["sequence"])
    rows = []
    for _, row in df.iterrows():
        rows.append(t_safety_prediction(row["sequence"], True, int(row.get("hemolytic_int", 0))))
    if max_rows:
        rows = rows[:max_rows]
    return rows


def build_drug_likeness_examples(srcs: Sources, max_rows: int | None) -> list[dict]:
    import pandas as pd
    from rdkit import Chem, RDLogger
    from rdkit.Chem import QED, Crippen, Descriptors, Lipinski

    RDLogger.DisableLog("rdApp.*")

    df = pd.read_csv(srcs.chembl_csv)
    df = df.dropna(subset=["smiles"])
    df = df.drop_duplicates(subset=["smiles"])
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
    p.add_argument("--fetch", action="store_true",
                   help="Fetch raw data from ChEMBL/DBAASP APIs first if missing")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    random.seed(args.seed)

    srcs = Sources(
        chembl_csv=args.data_root / "chembl_antibiotics.csv",
        dbaasp_csv=args.data_root / "dbaasp_amps.csv",
        out_dir=args.output_dir,
    )

    # Verify (or fetch) real data
    _ensure_data(srcs, fetch=args.fetch)

    log.info("Building task slices from real data...")
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
        log.error("No examples built. Real data may be empty — check the raw CSVs.")
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

    try:
        import pandas as pd
        from datasets import Dataset, DatasetDict
    except ImportError as exc:
        log.error("Missing deps: %s. pip install datasets pandas pyarrow", exc)
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
