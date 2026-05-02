"""Convert CO-ADD canonical data into Stage 2 training examples.

Generates 3 task types from CO-ADD data:
  1. coadd_mic_prediction — dose-response MIC values
  2. coadd_inhibition_screen — single-conc % inhibition at 32 µg/mL
  3. coadd_selectivity — compound × multiple pathogens (cross-pathogen profile)

Output: data/processed/amr-stage2-coadd/ as HF Dataset
Push:   pushed to HF Hub for inclusion in Stage 2 pro
"""
from __future__ import annotations

import argparse
import json
import logging
import random
from collections import defaultdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] coadd-build | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("coadd-build")

PATHOGEN_FULL = {
    "EColi": "Escherichia coli",
    "Paer": "Pseudomonas aeruginosa",
    "Abaum": "Acinetobacter baumannii",
    "MRSA": "Methicillin-resistant Staphylococcus aureus",
    "KpneuCRE": "Klebsiella pneumoniae",
    "Spneu": "Streptococcus pneumoniae",
}


def _msg(prompt: str, response: str, task: str) -> dict:
    msgs = [{"role": "user", "content": prompt},
            {"role": "assistant", "content": response}]
    return {
        "task": task,
        "split": "train",
        "prompt": prompt,
        "response": response,
        "messages": json.dumps(msgs),  # JSON-encoded for pyarrow compatibility
    }


def build_dr_examples(dr_path: Path) -> list[dict]:
    """Convert dose-response MIC data into MIC-prediction examples."""
    import pandas as pd
    if not dr_path.exists():
        log.error("Missing %s", dr_path)
        return []

    dr = pd.read_csv(dr_path, low_memory=False)
    log.info("Dose-response rows: %d", len(dr))

    out = []
    for _, row in dr.iterrows():
        smi = row.get("smiles_canonical") or row.get("SMILES")
        if not isinstance(smi, str) or not smi:
            continue
        path_short = row.get("pathogen_short")
        if not isinstance(path_short, str):
            continue
        path_full = PATHOGEN_FULL.get(path_short, path_short)
        mic = row.get("mic_ug_per_ml")
        unit = row.get("DRVAL_UNIT", "ug/mL")
        qual = row.get("mic_qualifier", "=")
        if mic is None or pd.isna(mic):
            continue
        try:
            mic_val = float(mic)
        except (TypeError, ValueError):
            continue

        # Build prompt
        if unit == "uM":
            unit_text = "µM"
        else:
            unit_text = "µg/mL"

        if qual in (">", ">="):
            potency_text = f"≥{mic_val:.2f} {unit_text} (essentially inactive at tested range)"
            potency_label = "inactive/weak"
        elif qual in ("<", "<="):
            potency_text = f"≤{mic_val:.2f} {unit_text}"
            potency_label = "potent" if mic_val <= 4 else "moderate"
        else:
            potency_text = f"{mic_val:.2f} {unit_text}"
            if mic_val <= 1: potency_label = "potent"
            elif mic_val <= 8: potency_label = "moderate"
            else: potency_label = "weak"

        prompt = (
            "Instructions: Predict the antibacterial potency category of this compound "
            "against the named pathogen.\n"
            f"Compound SMILES: {smi}\n"
            f"Pathogen: {path_full}\n"
            "Question: Is this compound likely to be potent (MIC ≤ 1 µg/mL), moderate "
            "(MIC 1-8 µg/mL), weak (MIC 8-64 µg/mL), or inactive (MIC > 64 µg/mL)?"
        )

        response = (
            f"Based on CO-ADD dose-response screening data (University of Queensland IMB, "
            f"public release r03 Feb 2020): the measured MIC against {path_full} is "
            f"{potency_text}, classifying this compound as {potency_label}."
        )

        out.append(_msg(prompt, response, task="coadd_mic_prediction"))

    log.info("  → %d MIC-prediction examples", len(out))
    return out


def build_inhibition_examples(inh_path: Path, sample_n: int | None = None) -> list[dict]:
    """Convert single-conc inhibition data into 'active/inactive' classification examples.

    Single-conc data is much larger (637K rows for AMR pathogens). Subsample if requested.
    """
    import pandas as pd
    if not inh_path.exists():
        log.error("Missing %s", inh_path)
        return []

    inh = pd.read_csv(inh_path, low_memory=False)
    log.info("Inhibition rows: %d", len(inh))

    if sample_n and len(inh) > sample_n:
        log.info("Sampling %d / %d rows", sample_n, len(inh))
        inh = inh.sample(n=sample_n, random_state=42).reset_index(drop=True)

    out = []
    for _, row in inh.iterrows():
        smi = row.get("smiles_canonical") or row.get("SMILES")
        if not isinstance(smi, str) or not smi:
            continue
        path_short = row.get("pathogen_short")
        if not isinstance(path_short, str):
            continue
        path_full = PATHOGEN_FULL.get(path_short, path_short)
        inhib = row.get("inhib_ave")
        if pd.isna(inhib):
            continue
        conc = row.get("CONC", "32 ug/mL")

        # Classify based on inhibition %
        if inhib >= 80:
            classification = "ACTIVE — strongly inhibits growth"
        elif inhib >= 50:
            classification = "MODERATE — partial growth inhibition"
        elif inhib >= 20:
            classification = "WEAK — minimal growth inhibition"
        else:
            classification = "INACTIVE — no significant inhibition"

        prompt = (
            "Instructions: Predict whether this compound is active against the named "
            "pathogen at the screening concentration.\n"
            f"Compound SMILES: {smi}\n"
            f"Pathogen: {path_full}\n"
            f"Test concentration: {conc}\n"
            "Question: Active (>80% inhibition), moderate (50-80%), weak (20-50%), "
            "or inactive (<20%)?"
        )

        response = (
            f"Based on CO-ADD single-concentration screening data: at {conc}, the average "
            f"growth inhibition is {inhib:.1f}% — classification: {classification}."
        )

        out.append(_msg(prompt, response, task="coadd_inhibition_screen"))

    log.info("  → %d inhibition-screen examples", len(out))
    return out


def build_selectivity_examples(dr_path: Path) -> list[dict]:
    """For compounds tested against MULTIPLE pathogens, generate spectrum-profile examples."""
    import pandas as pd
    if not dr_path.exists():
        return []
    dr = pd.read_csv(dr_path, low_memory=False)

    # Group by compound; only keep compounds with ≥3 pathogens tested
    spectrum_data = defaultdict(list)
    for _, row in dr.iterrows():
        smi = row.get("smiles_canonical") or row.get("SMILES")
        path_short = row.get("pathogen_short")
        mic = row.get("mic_ug_per_ml")
        if not isinstance(smi, str) or not isinstance(path_short, str):
            continue
        if mic is None or pd.isna(mic):
            continue
        try:
            mic_val = float(mic)
        except (TypeError, ValueError):
            continue
        spectrum_data[smi].append((path_short, mic_val))

    out = []
    for smi, pathogen_mics in spectrum_data.items():
        if len(pathogen_mics) < 3:
            continue

        # Compute spectrum profile
        path_summary = []
        for path_short, mic in sorted(pathogen_mics, key=lambda x: x[1]):
            path_full = PATHOGEN_FULL.get(path_short, path_short)
            if mic <= 1:
                potency = "potent"
            elif mic <= 8:
                potency = "moderate"
            elif mic <= 32:
                potency = "weak"
            else:
                potency = "essentially inactive"
            path_summary.append(f"  - {path_full}: MIC {mic:.2f} µg/mL ({potency})")

        prompt = (
            "Instructions: Predict the cross-pathogen spectrum profile of this compound "
            "across the priority gram-negative + gram-positive pathogens.\n"
            f"Compound SMILES: {smi}\n"
            "Question: What is the antibacterial spectrum across MRSA, Pseudomonas "
            "aeruginosa, E. coli, K. pneumoniae, and A. baumannii?"
        )

        response = (
            "Based on CO-ADD dose-response screening data, this compound shows the "
            "following antibacterial spectrum:\n" + "\n".join(path_summary)
        )

        out.append(_msg(prompt, response, task="coadd_selectivity_profile"))

    log.info("  → %d selectivity-profile examples (compounds tested ≥3 pathogens)", len(out))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, default=Path("data/raw"))
    p.add_argument("--output", type=Path,
                   default=Path("data/processed/amr-stage2-coadd"))
    p.add_argument("--inhibition-sample", type=int, default=50000,
                   help="Sample size from 637K inhibition rows (default 50K)")
    p.add_argument("--push-to-hub", type=str, default=None)
    args = p.parse_args()

    examples = []
    examples += build_dr_examples(args.data_root / "coadd_doseresponse.canonical.csv")
    examples += build_inhibition_examples(
        args.data_root / "coadd_inhibition.canonical.csv",
        sample_n=args.inhibition_sample,
    )
    examples += build_selectivity_examples(args.data_root / "coadd_doseresponse.canonical.csv")

    if not examples:
        log.error("No examples produced.")
        return 1

    rnd = random.Random(42)
    rnd.shuffle(examples)
    n_eval = max(100, len(examples) // 25)
    eval_set = examples[:n_eval]
    train_set = examples[n_eval:]
    for r in eval_set:
        r["split"] = "valid"

    from collections import Counter
    log.info("=" * 60)
    log.info("Total CO-ADD examples: %d", len(examples))
    for task, n in Counter(e["task"] for e in examples).most_common():
        log.info("  %-30s %d", task, n)
    log.info("Train: %d, Eval: %d", len(train_set), len(eval_set))

    from datasets import Dataset, DatasetDict
    ds = DatasetDict({
        "train": Dataset.from_list(train_set),
        "valid": Dataset.from_list(eval_set),
    })
    args.output.mkdir(parents=True, exist_ok=True)
    ds.save_to_disk(str(args.output))
    log.info("Wrote %s", args.output)

    if args.push_to_hub:
        try:
            from huggingface_hub import HfFolder
            token = HfFolder.get_token()
        except Exception:
            token = None
        if not token:
            import os
            token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        if token:
            ds.push_to_hub(args.push_to_hub, token=token, private=False)
            log.info("✓ pushed to %s", args.push_to_hub)
        else:
            log.warning("No HF token — skipping push")

    return 0


if __name__ == "__main__":
    import pandas as pd
    raise SystemExit(main())
