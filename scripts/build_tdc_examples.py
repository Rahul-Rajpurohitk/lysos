"""Build Stage 2 training examples from TDC ADMET + Tox datasets.

Converts each TDC dataset row into:
  - tdc_admet_prediction (for ADME datasets)
  - tdc_toxicity_prediction (for Tox datasets)

Sample at most ~3K rows per dataset to keep example count manageable.
"""
import json
import logging
import random
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] tdc-build | %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("tdc-build")

DATASET_DESC = {
    "caco2_wang": ("Caco-2 cell permeability (predicts oral absorption)",
                    "ADME", "regression", "log(cm/s)",
                    "higher = more permeable; clinically: typically -5 to -7 log(cm/s)"),
    "pampa_ncats": ("PAMPA permeability (parallel artificial membrane permeability assay)",
                    "ADME", "binary", "0/1",
                    "1 = high permeability (good oral absorption likely); 0 = low"),
    "hia_hou": ("Human intestinal absorption", "ADME", "binary", "0/1",
                "1 = absorbed (>30% in humans); 0 = poor absorption"),
    "bbb_martins": ("Blood-brain barrier penetration", "ADME", "binary", "0/1",
                    "1 = penetrant (active in CNS); 0 = excluded by BBB"),
    "bioavailability_ma": ("Oral bioavailability", "ADME", "binary", "0/1",
                            "1 = high oral bioavailability; 0 = low"),
    "vdss_lombardo": ("Volume of distribution at steady state", "ADME", "regression", "L/kg",
                       "small (<1) = stays in plasma; large (>5) = tissue accumulation"),
    "half_life_obach": ("Drug half-life", "ADME", "regression", "hours",
                       "<3hr = short (frequent dosing); >12hr = long (once-daily)"),
    "ppbr_az": ("Plasma protein binding ratio", "ADME", "regression", "% bound",
                ">99% = highly bound (low free drug); <50% = mostly free"),
    "cyp2d6_substrate_carbonmangels": ("CYP2D6 substrate", "ADME", "binary", "0/1",
                                        "1 = metabolized by CYP2D6 (DDI risk)"),
    "cyp3a4_substrate_carbonmangels": ("CYP3A4 substrate", "ADME", "binary", "0/1",
                                        "1 = metabolized by CYP3A4 (major DDI source)"),
    "cyp2c9_substrate_carbonmangels": ("CYP2C9 substrate", "ADME", "binary", "0/1",
                                        "1 = metabolized by CYP2C9"),
    "cyp2d6_veith": ("CYP2D6 inhibitor", "ADME", "binary", "0/1",
                     "1 = inhibits CYP2D6 (causes DDIs)"),
    "cyp3a4_veith": ("CYP3A4 inhibitor", "ADME", "binary", "0/1",
                     "1 = inhibits CYP3A4 (causes major DDIs — common safety issue)"),
    "cyp2c9_veith": ("CYP2C9 inhibitor", "ADME", "binary", "0/1",
                     "1 = inhibits CYP2C9 (warfarin DDI)"),
    "cyp1a2_veith": ("CYP1A2 inhibitor", "ADME", "binary", "0/1",
                     "1 = inhibits CYP1A2 (FQ-class DDI with theophylline)"),
    "clearance_hepatocyte_az": ("Hepatocyte clearance rate", "ADME", "regression", "uL/min/10^6 cells",
                                "high clearance = short half-life; low = accumulation risk"),
    "clearance_microsome_az": ("Microsomal clearance rate", "ADME", "regression", "uL/min/mg",
                                "predicts in vivo metabolic clearance"),
    "herg": ("hERG channel block (cardiac QT prolongation risk)", "Tox", "binary", "0/1",
             "1 = hERG blocker → cardiac arrhythmia risk; major safety filter"),
    "herg_karim": ("hERG block (Karim curated)", "Tox", "binary", "0/1",
                    "1 = hERG blocker (cardiac safety concern)"),
    "ames": ("Ames mutagenicity test", "Tox", "binary", "0/1",
             "1 = mutagenic in S. typhimurium; carcinogenicity warning"),
    "dili": ("Drug-induced liver injury", "Tox", "binary", "0/1",
             "1 = hepatotoxic in clinical use; FDA black box / withdrawal predictor"),
    "skin_reaction": ("Skin sensitization", "Tox", "binary", "0/1",
                      "1 = causes contact dermatitis / allergic skin reaction"),
    "carcinogens_lagunin": ("Carcinogenicity", "Tox", "binary", "0/1",
                             "1 = carcinogenic in animal models or epidemiology"),
    "ld50_zhu": ("Acute oral LD50", "Tox", "regression", "log mol/kg",
                  "lower (more negative log) = more toxic; -3 = highly toxic"),
    "clintox": ("Clinical toxicity (FDA approval failure)", "Tox", "binary", "0/1",
                 "1 = drug failed FDA approval due to toxicity"),
}


def _msg(prompt: str, response: str, task: str) -> dict:
    return {
        "task": task, "split": "train",
        "prompt": prompt, "response": response,
        "messages": json.dumps([{"role": "user", "content": prompt},
                                {"role": "assistant", "content": response}]),
    }


def main():
    import pandas as pd
    examples = []

    for ds_name, (desc, ds_class, task_type, units, interpretation) in DATASET_DESC.items():
        path = Path(f"data/raw/tdc_datasets/{ds_name}.csv")
        if not path.exists():
            log.warning("Missing %s — skipping", path)
            continue

        df = pd.read_csv(path)
        log.info("Loaded %s: %d rows", ds_name, len(df))

        # Sample to manageable size (max 3000 per dataset, prefer balanced for binary)
        if len(df) > 3000:
            df = df.sample(3000, random_state=42).reset_index(drop=True)

        task_label = "tdc_admet_prediction" if ds_class == "ADME" else "tdc_toxicity_prediction"

        # TDC schemas have 'Drug' (SMILES), 'Y' (label) consistently
        smi_col = "Drug" if "Drug" in df.columns else df.columns[0]
        y_col = "Y" if "Y" in df.columns else df.columns[-1]

        for _, row in df.iterrows():
            smi = row[smi_col]
            y = row[y_col]
            if pd.isna(smi) or pd.isna(y):
                continue

            prompt = (f"Instructions: Predict the {desc} for the named compound.\n"
                      f"Compound SMILES: {smi}\n"
                      f"Question: What is the predicted {desc} value (in {units})?")

            if task_type == "binary":
                label = "POSITIVE" if y == 1 else "NEGATIVE"
                response = (f"Per Therapeutics Data Commons benchmark dataset ({ds_name}): {label} "
                            f"({int(y)}). {interpretation}.")
            else:
                response = (f"Per TDC benchmark ({ds_name}): predicted value = {y:.3f} {units}. "
                            f"{interpretation}.")

            examples.append(_msg(prompt, response, task_label))

    rnd = random.Random(42)
    rnd.shuffle(examples)
    n_eval = max(200, len(examples) // 25)
    eval_set = examples[:n_eval]
    train_set = examples[n_eval:]
    for r in eval_set:
        r["split"] = "valid"

    from collections import Counter
    log.info("=" * 60)
    log.info("Total TDC examples: %d", len(examples))
    for task, n in Counter(e["task"] for e in examples).most_common():
        log.info("  %-40s %d", task, n)

    from datasets import Dataset, DatasetDict
    ds = DatasetDict({
        "train": Dataset.from_list(train_set),
        "valid": Dataset.from_list(eval_set),
    })
    out = Path("data/processed/amr-stage2-tdc")
    out.mkdir(parents=True, exist_ok=True)
    ds.save_to_disk(str(out))
    log.info("Wrote %s (%d train + %d valid)", out, len(train_set), len(eval_set))


if __name__ == "__main__":
    import pandas as pd
    main()
