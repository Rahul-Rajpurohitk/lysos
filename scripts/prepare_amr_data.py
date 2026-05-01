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
    bindingdb_csv: Path
    pubchem_csv: Path
    apd3_csv: Path
    dramp_csv: Path
    drugbank_csv: Path
    out_dir: Path


# Only ChEMBL is strictly required — every other source is best-effort
# enrichment. We can train Stage 2 on ChEMBL alone if needed.
REQUIRED_SOURCES = ["chembl"]
OPTIONAL_SOURCES = ["dbaasp", "bindingdb", "pubchem", "apd3", "dramp", "drugbank"]


def _ensure_data(srcs: Sources, fetch: bool) -> dict[str, bool]:
    """Verify raw data exists; optionally fetch from real APIs.

    Required sources missing → FileNotFoundError.
    Optional sources missing → log + return present-map.
    """
    present: dict[str, bool] = {}
    fetchers = {
        "chembl": ("src.data.chembl", "fetch_amr_activities"),
        "dbaasp": ("src.data.dbaasp", "fetch_amps"),
        "bindingdb": ("src.data.bindingdb", "fetch_bindingdb"),
        "pubchem": ("src.data.pubchem", "fetch_pubchem_antibacterial"),
        "apd3": ("src.data.apd3", "fetch_apd3_amps"),
        "dramp": ("src.data.dramp", "fetch_amps"),
        "drugbank": ("src.data.drugbank", "fetch_drugbank_open"),
    }
    paths = {
        "chembl": srcs.chembl_csv,
        "dbaasp": srcs.dbaasp_csv,
        "bindingdb": srcs.bindingdb_csv,
        "pubchem": srcs.pubchem_csv,
        "apd3": srcs.apd3_csv,
        "dramp": srcs.dramp_csv,
        "drugbank": srcs.drugbank_csv,
    }
    for name, path in paths.items():
        if path.exists():
            present[name] = True
            continue
        if fetch:
            mod_name, fn_name = fetchers[name]
            log.info("Fetching %s ...", name)
            try:
                mod = __import__(mod_name, fromlist=[fn_name])
                fn = getattr(mod, fn_name)
                fn(out_path=path)
                present[name] = path.exists()
            except Exception as exc:  # noqa: BLE001
                log.warning("  ✗ %s fetch failed: %s", name, exc)
                present[name] = False
        else:
            present[name] = False
            if name in REQUIRED_SOURCES:
                log.error(
                    "%s data not found at %s\n"
                    "  Run: python -m %s --output %s\n"
                    "  Or:  python scripts/prepare_amr_data.py --fetch",
                    name, path, fetchers[name][0], path,
                )
                raise FileNotFoundError(path)
            log.warning("optional source %s missing at %s (skipping)", name, path)
    return present


# -----------------------------------------------------------------------------
# Build each task slice
# -----------------------------------------------------------------------------


def _load_activity_csv(path: Path, present: dict[str, bool], name: str):
    """Load a CSV if its source was fetched successfully, else None."""
    import pandas as pd

    if not present.get(name) or not path.exists():
        return None
    return pd.read_csv(path)


def build_activity_examples(srcs: Sources, max_rows: int | None,
                            present: dict[str, bool]) -> list[dict]:
    import pandas as pd

    # ChEMBL is the canonical source; BindingDB adds binding affinity data
    frames = []
    for name, path in [("chembl", srcs.chembl_csv), ("bindingdb", srcs.bindingdb_csv)]:
        df = _load_activity_csv(path, present, name)
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        return []
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["smiles", "pathogen_short", "mic_log_ug_per_ml"])
    if max_rows:
        df = df.head(max_rows)
    out = []
    for _, row in df.iterrows():
        pathogen = PATHOGENS_BY_SHORT.get(row["pathogen_short"])
        if not pathogen:
            continue
        out.append(t_activity_prediction(row["smiles"], pathogen, float(row["mic_log_ug_per_ml"])))
    return out


def build_generation_examples(srcs: Sources, max_rows: int | None,
                              present: dict[str, bool]) -> list[dict]:
    import pandas as pd

    # Use ChEMBL potent compounds + BindingDB high-affinity binders + PubChem actives
    frames = []
    df_chembl = _load_activity_csv(srcs.chembl_csv, present, "chembl")
    if df_chembl is not None:
        if "pchembl_value" in df_chembl.columns:
            df_chembl = df_chembl[df_chembl["pchembl_value"] >= 5.0]
        frames.append(df_chembl.dropna(subset=["smiles", "pathogen_short"]))

    df_bdb = _load_activity_csv(srcs.bindingdb_csv, present, "bindingdb")
    if df_bdb is not None:
        # Keep all BindingDB rows (they're already filtered to bacterial)
        frames.append(df_bdb.dropna(subset=["smiles", "pathogen_short"]))

    df_pubchem = _load_activity_csv(srcs.pubchem_csv, present, "pubchem")
    if df_pubchem is not None:
        frames.append(df_pubchem.dropna(subset=["smiles", "pathogen_short"]))

    if not frames:
        return []
    df = pd.concat(frames, ignore_index=True)
    if max_rows:
        df = df.head(max_rows)
    out = []
    for _, row in df.iterrows():
        pathogen = PATHOGENS_BY_SHORT.get(row["pathogen_short"])
        if not pathogen:
            continue
        out.append(t_generation_for_target(pathogen, row["smiles"]))
    return out


def build_peptide_examples(srcs: Sources, max_rows: int | None,
                           present: dict[str, bool]) -> list[dict]:
    import pandas as pd

    # AMP sources: DBAASP + APD3 + DRAMP — all share the same schema
    frames = []
    for name, path in [("dbaasp", srcs.dbaasp_csv),
                       ("apd3", srcs.apd3_csv),
                       ("dramp", srcs.dramp_csv)]:
        df = _load_activity_csv(path, present, name)
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        return []
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["sequence", "pathogen_short"])
    if "hemolytic_int" in df.columns:
        df = df[df["hemolytic_int"] == 0]
    if max_rows:
        df = df.head(max_rows)
    out = []
    for _, row in df.iterrows():
        pathogen = PATHOGENS_BY_SHORT.get(row["pathogen_short"])
        if not pathogen:
            continue
        out.append(t_peptide_design(pathogen, row["sequence"]))
    return out


def build_safety_examples(srcs: Sources, max_rows: int | None,
                          present: dict[str, bool]) -> list[dict]:
    import pandas as pd

    frames = []
    for name, path in [("dbaasp", srcs.dbaasp_csv),
                       ("apd3", srcs.apd3_csv),
                       ("dramp", srcs.dramp_csv)]:
        df = _load_activity_csv(path, present, name)
        if df is not None and not df.empty:
            frames.append(df)
    if not frames:
        return []
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["sequence"])
    rows = []
    for _, row in df.iterrows():
        rows.append(t_safety_prediction(row["sequence"], True, int(row.get("hemolytic_int", 0))))
    if max_rows:
        rows = rows[:max_rows]
    return rows


def build_drug_likeness_examples(srcs: Sources, max_rows: int | None,
                                 present: dict[str, bool]) -> list[dict]:
    import pandas as pd

    try:
        from rdkit import Chem, RDLogger
        from rdkit.Chem import QED, Crippen, Descriptors, Lipinski
        RDLogger.DisableLog("rdApp.*")
    except ImportError:
        log.warning("rdkit not installed; skipping drug_likeness task slice. "
                    "(Run on the AMD VM Docker container where rdkit is present.)")
        return []

    # Drug-likeness training pulls from ChEMBL + DrugBank (broad drug knowledge)
    frames = []
    for name, path in [("chembl", srcs.chembl_csv), ("drugbank", srcs.drugbank_csv)]:
        df = _load_activity_csv(path, present, name)
        if df is not None and not df.empty:
            frames.append(df[["smiles"]] if "smiles" in df.columns else None)
    frames = [f for f in frames if f is not None]
    if not frames:
        return []
    df = pd.concat(frames, ignore_index=True)
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
        bindingdb_csv=args.data_root / "bindingdb_antibacterial.csv",
        pubchem_csv=args.data_root / "pubchem_antibacterial.csv",
        apd3_csv=args.data_root / "apd3_amps.csv",
        dramp_csv=args.data_root / "dramp_amps.csv",
        drugbank_csv=args.data_root / "drugbank_open.csv",
        out_dir=args.output_dir,
    )

    # Verify (or fetch) real data; returns presence map for optional sources
    present = _ensure_data(srcs, fetch=args.fetch)
    log.info("Sources present: %s",
             {k: v for k, v in present.items() if v})

    log.info("Building task slices from real data...")
    activity = build_activity_examples(srcs, args.max_rows_per_task, present)
    generation = build_generation_examples(srcs, args.max_rows_per_task, present)
    peptide = build_peptide_examples(srcs, args.max_rows_per_task, present)
    safety = build_safety_examples(srcs, args.max_rows_per_task, present)
    drug_like = build_drug_likeness_examples(srcs, args.max_rows_per_task, present)

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
