"""Build Stage 2 examples from DRAMP clinical-stage AMP database.

96 AMPs in DRAMP's clinical_amps.xlsx with: Name, Sequence, Activity, Medical_use,
Stage_of_development, Company, Target_Organism, ClinicalTrials.gov ID.

Generates:
  - clinical_amp_recognition — "Identify this clinical-stage AMP"
  - clinical_amp_development_stage — "What stage of development is X in?"
  - clinical_amp_indication — "What infection does X treat?"
"""
import json
import logging
import random
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] camp-build | %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("camp-build")


def _msg(prompt: str, response: str, task: str) -> dict:
    return {
        "task": task, "split": "train",
        "prompt": prompt, "response": response,
        "messages": json.dumps([{"role": "user", "content": prompt},
                                {"role": "assistant", "content": response}]),
    }


def main():
    import pandas as pd
    df = pd.read_excel("data/raw/dramp_cache/clinical_amps.xlsx")
    log.info("Loaded %d clinical-stage AMPs", len(df))

    examples = []

    for _, row in df.iterrows():
        name = str(row.get("Name", "")).strip()
        seq = str(row.get("Sequence", "")).strip()
        activity = str(row.get("Activity", "")).strip()
        med_use = str(row.get("Medical_use", "")).strip()
        stage = str(row.get("Stage_of_development", "")).strip()
        company = str(row.get("Company", "")).strip()
        target = str(row.get("Target_Organism", "")).strip()
        ct_id = str(row.get("clinicaltrial", "")).strip()

        if not name or name.lower() == "nan":
            continue

        # Task 1: AMP RECOGNITION (sequence → name + class)
        if seq and len(seq) > 5 and not seq.lower().startswith("nan"):
            prompt = (f"Instructions: Identify this clinical-stage antimicrobial peptide.\n"
                      f"Sequence: {seq[:200]}\n"
                      f"Question: What is the name and clinical context of this AMP?")
            resp_parts = [f"This is {name}"]
            if activity and activity.lower() != "nan":
                resp_parts.append(f"with {activity.lower()} activity")
            if target and target.lower() != "nan":
                resp_parts.append(f"targeting {target}")
            if stage and stage.lower() != "nan":
                resp_parts.append(f"currently at {stage}")
            if company and company.lower() != "nan":
                resp_parts.append(f"developed by {company}")
            response = ", ".join(resp_parts) + "."
            examples.append(_msg(prompt, response, "clinical_amp_recognition"))

        # Task 2: DEVELOPMENT STAGE
        if stage and stage.lower() != "nan":
            prompt = (f"Instructions: State the clinical development stage of the named antimicrobial peptide.\n"
                      f"Drug: {name}\n"
                      f"Question: What is its current stage of clinical development?")
            response = (f"{name} is currently at: {stage}.")
            if med_use and med_use.lower() != "nan":
                response += f" Indication: {med_use}."
            if ct_id and ct_id.lower() != "nan" and "nct" in ct_id.lower():
                response += f" ClinicalTrials.gov: {ct_id}."
            examples.append(_msg(prompt, response, "clinical_amp_development_stage"))

        # Task 3: INDICATION
        if med_use and med_use.lower() != "nan" and len(med_use) > 5:
            prompt = (f"Instructions: State the clinical indication / medical use of the named AMP.\n"
                      f"Drug: {name}\n"
                      f"Question: What infection or condition is this AMP used or developed to treat?")
            response = (f"{name} is used / being developed for: {med_use}.")
            examples.append(_msg(prompt, response, "clinical_amp_indication"))

    rnd = random.Random(42)
    rnd.shuffle(examples)
    n_eval = max(15, len(examples) // 25)
    eval_set = examples[:n_eval]
    train_set = examples[n_eval:]
    for r in eval_set:
        r["split"] = "valid"

    from collections import Counter
    log.info("Total clinical-AMP examples: %d", len(examples))
    for task, n in Counter(e["task"] for e in examples).most_common():
        log.info("  %-40s %d", task, n)

    from datasets import Dataset, DatasetDict
    ds = DatasetDict({
        "train": Dataset.from_list(train_set),
        "valid": Dataset.from_list(eval_set),
    })
    out = Path("data/processed/amr-stage2-clinical-amps")
    out.mkdir(parents=True, exist_ok=True)
    ds.save_to_disk(str(out))
    log.info("Wrote %s (%d train + %d valid)", out, len(train_set), len(eval_set))


if __name__ == "__main__":
    import pandas as pd
    main()
