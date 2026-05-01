"""Stage 1 data preparation: Therapeutics Data Commons → instruction-tuning corpus.

Downloads the curated set of TDC tasks we use to train TxGemma-4, formats them
as instruction/response pairs in Gemma chat-template form, and writes a single
HuggingFace `Dataset` to disk (and optionally pushes to the Hub).

Runs entirely on CPU. Designed to be the FIRST thing we run on kickoff Day 1
(or even before — it doesn't depend on AMD Dev Cloud).

Usage
-----

    # Default: prepare everything, write to data/processed/, do NOT push
    python scripts/prepare_tdc_data.py

    # Only ADMET tasks, push to HF Hub as a private dataset
    python scripts/prepare_tdc_data.py \
        --groups adme,tox \
        --push-to-hub rahul24raj/lysos-tdc-stage1

    # Specific tasks only (debugging)
    python scripts/prepare_tdc_data.py \
        --tasks BBB_Martins,Caco2_Wang,LD50_Zhu

Requires `PyTDC>=1.1.0` and `datasets>=3.0.0` from pyproject.toml.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Set up logging early
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("prepare_tdc")

# -----------------------------------------------------------------------------
# Task catalog — the TDC tasks we use to train TxGemma-4
# -----------------------------------------------------------------------------
#
# Curated to overlap heavily with what Google's published TxGemma prompts use,
# but expanded with newer TDC additions. Grouped by family so we can selectively
# prepare subsets via `--groups`.
#
# Source taxonomy: tdcommons.ai/single_pred_tasks/

ADME_TASKS = [
    "Caco2_Wang",          # Caco-2 cell permeability
    "HIA_Hou",             # Human Intestinal Absorption
    "Pgp_Broccatelli",     # P-glycoprotein efflux
    "Bioavailability_Ma",  # Oral bioavailability
    "Lipophilicity_AstraZeneca",
    "Solubility_AqSolDB",
    "BBB_Martins",         # Blood-brain barrier penetration
    "PPBR_AZ",             # Plasma protein binding
    "VDss_Lombardo",       # Volume of distribution
    "CYP2C19_Veith",
    "CYP2D6_Veith",
    "CYP3A4_Veith",
    "CYP1A2_Veith",
    "CYP2C9_Veith",
    "CYP2C9_Substrate_CarbonMangels",
    "CYP2D6_Substrate_CarbonMangels",
    "CYP3A4_Substrate_CarbonMangels",
    "Half_Life_Obach",
    "Clearance_Hepatocyte_AZ",
    "Clearance_Microsome_AZ",
]

TOX_TASKS = [
    "hERG",                # Cardiotoxicity
    "AMES",                # Mutagenicity
    "DILI",                # Drug-Induced Liver Injury
    "Skin_Reaction",
    "Carcinogens_Lagunin",
    "ClinTox",
    "LD50_Zhu",            # Acute toxicity
    "Tox21",               # Multi-task tox endpoints
]

HTS_TASKS = [
    "HIV",                 # HIV inhibition
    "SARSCoV2_Vitro_Touret",
    "SARSCoV2_3CLPro_Diamond",
]

YIELDS_TASKS = [
    "USPTO_Yields",        # Reaction yields (synthesizability proxy)
    "Buchwald_Hartwig",
]

EPITOPE_TASKS = [
    # Target / binding prediction tasks
    "DAVIS",               # Drug-target binding affinity
    "KIBA",                # Kinase inhibitor binding
    "BindingDB_Kd",
    "BindingDB_IC50",
]

PAIRED_TASKS = [
    # Drug-Drug Interaction
    "DrugBank_DDI",
    "TWOSIDES",
    # Drug-Synergy
    "OncoPolyPharmacology",
]

GROUPS: dict[str, list[str]] = {
    "adme": ADME_TASKS,
    "tox": TOX_TASKS,
    "hts": HTS_TASKS,
    "yield": YIELDS_TASKS,
    "binding": EPITOPE_TASKS,
    "paired": PAIRED_TASKS,
}

ALL_TASKS = sorted({t for tasks in GROUPS.values() for t in tasks})

# -----------------------------------------------------------------------------
# Instruction templates
# -----------------------------------------------------------------------------
#
# Format inspired by Google's TxGemma published prompts (tdc_prompts.json),
# with our own context strings. Keep the "Context" line short and consistent.

TASK_PROMPTS: dict[str, dict[str, str]] = {
    # ADME
    "Caco2_Wang": {
        "context": "Caco-2 cells form a monolayer that simulates the intestinal lining. The Caco-2 permeability coefficient predicts how readily a drug will be absorbed orally.",
        "ask": "Predict the Caco-2 permeability (log Papp, cm/s) for the following drug.",
    },
    "BBB_Martins": {
        "context": "The blood-brain barrier (BBB) blocks most foreign drugs from reaching the central nervous system. BBB-permeable drugs are needed for CNS-targeted therapeutics.",
        "ask": "Will the following drug cross the blood-brain barrier? Answer with Yes or No.",
    },
    "Solubility_AqSolDB": {
        "context": "Aqueous solubility is critical for oral bioavailability. Drugs with low solubility often fail in development.",
        "ask": "Predict the aqueous solubility (log mol/L) of the following compound.",
    },
    # Tox
    "hERG": {
        "context": "hERG channel blockade can cause life-threatening cardiac arrhythmias. Drug developers screen out hERG blockers early.",
        "ask": "Will the following compound block the hERG channel? Answer with Yes or No.",
    },
    "AMES": {
        "context": "The Ames test detects mutagenic compounds. Mutagens are typically excluded from drug development.",
        "ask": "Will the following compound be mutagenic in the Ames test? Answer with Yes or No.",
    },
    "DILI": {
        "context": "Drug-Induced Liver Injury (DILI) is a leading cause of drug withdrawal. Hepatotoxicity prediction is a top safety endpoint.",
        "ask": "Will the following compound cause Drug-Induced Liver Injury? Answer with Yes or No.",
    },
    "LD50_Zhu": {
        "context": "Acute toxicity (LD50) is the dose that kills half the test animals. Drugs with low LD50 are unsafe.",
        "ask": "Predict the LD50 (log[mol/kg]) of the following compound.",
    },
    # HTS
    "HIV": {
        "context": "Compounds that inhibit HIV replication are screened for antiretroviral therapy.",
        "ask": "Will the following compound inhibit HIV replication? Answer with Yes or No.",
    },
    # Binding
    "DAVIS": {
        "context": "Kinase-inhibitor binding affinity guides selectivity in oncology drug design.",
        "ask": "Predict the binding affinity (Kd, log scale) between the following drug and target.",
    },
    "BindingDB_Kd": {
        "context": "BindingDB curates binding affinities between drugs and protein targets.",
        "ask": "Predict the binding affinity (Kd, log scale) between the following drug and target.",
    },
}

DEFAULT_PROMPT_FALLBACK = {
    "context": "Predict the property below.",
    "ask": "Given the input, predict the corresponding output.",
}


# -----------------------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------------------


@dataclass
class TaskBundle:
    name: str
    group: str
    splits: dict[str, "pd.DataFrame"]  # noqa: F821 — pandas imported lazily
    input_col: str
    label_col: str
    is_classification: bool


def _import_tdc():
    """Lazy import so this script can show --help even without PyTDC installed."""
    try:
        from tdc.single_pred import ADME, HTS, Tox, Yields
        from tdc.multi_pred import DTI, DDI, DrugSyn

        return {"ADME": ADME, "Tox": Tox, "HTS": HTS, "Yields": Yields,
                "DTI": DTI, "DDI": DDI, "DrugSyn": DrugSyn}
    except ImportError as exc:
        log.error("PyTDC not installed: %s", exc)
        log.error("Install with: pip install PyTDC>=1.1.0")
        sys.exit(2)


def _task_loader_fn(task_name: str, group: str) -> Callable[[], object]:
    """Return a callable that loads the given task as a TDC dataset object."""
    tdc = _import_tdc()
    # Single-prediction tasks (one input, one output)
    if group in ("adme",):
        return lambda: tdc["ADME"](name=task_name)
    if group in ("tox",):
        return lambda: tdc["Tox"](name=task_name)
    if group in ("hts",):
        return lambda: tdc["HTS"](name=task_name)
    if group in ("yield",):
        return lambda: tdc["Yields"](name=task_name)
    # Multi-prediction tasks (two inputs)
    if group in ("binding",):
        return lambda: tdc["DTI"](name=task_name)
    if group == "paired":
        # DDI vs DrugSyn split — quick heuristic by name
        if "Synergy" in task_name or "Onco" in task_name:
            return lambda: tdc["DrugSyn"](name=task_name)
        return lambda: tdc["DDI"](name=task_name)
    raise ValueError(f"Unknown group {group!r} for task {task_name!r}")


def load_task(task_name: str, group: str) -> TaskBundle | None:
    """Download a single TDC task and return its splits."""
    log.info("Loading task: %s (%s)", task_name, group)
    try:
        loader = _task_loader_fn(task_name, group)
        ds = loader()
        # Standard TDC interface: get_split(method='scaffold' | 'random')
        splits = ds.get_split()
        # Inspect column names (TDC normalizes to 'Drug', 'Drug_ID', 'Y' for single_pred)
        first = next(iter(splits.values()))
        cols = list(first.columns)
        log.info("  splits: %s, cols: %s, n=%d/%d/%d",
                 list(splits.keys()), cols,
                 len(splits.get("train", [])),
                 len(splits.get("valid", [])),
                 len(splits.get("test", [])))
        # Heuristic: input col is "Drug" for single-pred, label col is "Y"
        # For multi-pred (DTI/DDI), input is ("Drug", "Target") or ("Drug1", "Drug2")
        return TaskBundle(
            name=task_name,
            group=group,
            splits=splits,
            input_col="Drug" if "Drug" in cols else cols[0],
            label_col="Y" if "Y" in cols else cols[-1],
            is_classification=_is_classification(first.get("Y")),
        )
    except Exception as exc:  # noqa: BLE001
        log.error("  failed to load %s: %s", task_name, exc)
        return None


def _is_classification(y_series) -> bool:
    """Best-effort detection: integer or {0,1} → classification."""
    if y_series is None:
        return False
    try:
        unique = set(y_series.unique())
        if unique <= {0, 1, 0.0, 1.0}:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


# -----------------------------------------------------------------------------
# Instruction formatting
# -----------------------------------------------------------------------------


def format_example(task: TaskBundle, row: dict) -> dict[str, str]:
    """Convert one TDC row into a prompt/response pair for instruction tuning."""
    prompt_meta = TASK_PROMPTS.get(task.name, DEFAULT_PROMPT_FALLBACK)
    drug_smiles = row.get(task.input_col, "")
    label = row.get(task.label_col, "")

    user_msg = (
        f"Instructions: Answer the following question about drug properties.\n"
        f"Context: {prompt_meta['context']}\n"
        f"Question: {prompt_meta['ask']}\n"
        f"Drug SMILES: {drug_smiles}"
    )

    # Format the answer based on classification vs regression
    if task.is_classification:
        answer = "Yes" if int(label) == 1 else "No"
    else:
        try:
            answer = f"{float(label):.4f}"
        except (TypeError, ValueError):
            answer = str(label)

    return {
        "task": task.name,
        "group": task.group,
        "split": "train",  # caller overrides
        "prompt": user_msg,
        "response": answer,
        # Conversational format for chat-template SFT
        "messages": json.dumps([
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": answer},
        ]),
    }


def task_to_records(task: TaskBundle) -> list[dict]:
    """Flatten all splits of a task into instruction-format records."""
    records: list[dict] = []
    for split_name, df in task.splits.items():
        for _, row in df.iterrows():
            ex = format_example(task, row.to_dict())
            ex["split"] = split_name
            records.append(ex)
    return records


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument(
        "--groups",
        type=str,
        default=",".join(GROUPS.keys()),
        help=f"Comma-separated subset of {list(GROUPS.keys())}",
    )
    p.add_argument(
        "--tasks",
        type=str,
        default=None,
        help="Comma-separated specific task names (overrides --groups)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed/tdc-stage1"),
        help="Directory to write Parquet/Arrow output",
    )
    p.add_argument(
        "--push-to-hub",
        type=str,
        default=None,
        help="If set, push to HF Hub as this dataset name (e.g. rahul24raj/lysos-tdc-stage1)",
    )
    p.add_argument(
        "--max-rows-per-task",
        type=int,
        default=None,
        help="Cap rows per task for debugging",
    )
    p.add_argument(
        "--list-tasks",
        action="store_true",
        help="Just print the catalog and exit",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.list_tasks:
        for group, tasks in GROUPS.items():
            print(f"\n[{group}]")
            for t in tasks:
                print(f"  - {t}")
        print(f"\nTotal: {len(ALL_TASKS)} tasks across {len(GROUPS)} groups")
        return 0

    # Decide what to download
    if args.tasks:
        wanted = [t.strip() for t in args.tasks.split(",")]
        # Match each to its group
        targets: list[tuple[str, str]] = []
        for t in wanted:
            for g, tasks in GROUPS.items():
                if t in tasks:
                    targets.append((g, t))
                    break
            else:
                log.warning("Unknown task: %s (skipping)", t)
    else:
        groups = [g.strip() for g in args.groups.split(",")]
        targets = [(g, t) for g in groups for t in GROUPS.get(g, [])]

    if not targets:
        log.error("Nothing to do. Check --groups / --tasks.")
        return 1

    log.info("Will prepare %d tasks: %s", len(targets), [t[1] for t in targets])

    # Lazy import so --help and --list-tasks work without heavy deps
    try:
        import pandas as pd
        from datasets import Dataset
    except ImportError as exc:
        log.error("Missing dependency: %s. Install with: pip install datasets pandas pyarrow", exc)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_records: list[dict] = []
    for group, task_name in targets:
        bundle = load_task(task_name, group)
        if bundle is None:
            continue
        recs = task_to_records(bundle)
        if args.max_rows_per_task:
            recs = recs[: args.max_rows_per_task]
        all_records.extend(recs)
        log.info("  → %d examples added (%s)", len(recs), task_name)

    if not all_records:
        log.error("No records collected. Aborting.")
        return 1

    log.info("Total examples across all tasks: %d", len(all_records))

    # Convert to HF Dataset
    df = pd.DataFrame(all_records)
    log.info("Per-task counts:\n%s", df["task"].value_counts().to_string())
    ds = Dataset.from_pandas(df, preserve_index=False)

    # Save to disk
    out_path = args.output_dir
    log.info("Writing dataset to %s", out_path)
    ds.save_to_disk(str(out_path))

    # Optional Hub push
    if args.push_to_hub:
        if "HF_TOKEN" not in os.environ and "HUGGINGFACE_TOKEN" not in os.environ:
            log.error("--push-to-hub requires HF_TOKEN env var")
            return 3
        log.info("Pushing to Hub: %s (private)", args.push_to_hub)
        ds.push_to_hub(args.push_to_hub, private=True)
        log.info("✓ pushed")

    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
