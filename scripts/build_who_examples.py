"""Build Stage 2 training examples from WHO MIA 2024 antimicrobial classification.

Generates:
  - who_class_lookup       — "What WHO class does drug X belong to?"
  - who_category_assignment — "Is drug X HPCIA / CIA / HIA / IA / NMI?"
  - who_use_restriction    — "Is drug X authorized for animal use?"
  - who_class_members      — "List drugs in the [class] WHO category"
"""
import json
import logging
import random
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] who-build | %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("who-build")

CATEGORY_DESC = {
    "HPCIA": ("HIGHEST PRIORITY CRITICALLY IMPORTANT ANTIMICROBIALS — most critical class for human "
              "medicine, last-resort therapy for serious multidrug-resistant infections; AMR risk from "
              "agricultural use is highest and most concerning."),
    "CIA": ("CRITICALLY IMPORTANT ANTIMICROBIALS — meets both criteria: (a) sole therapy or one of few "
            "alternatives for serious human infections; (b) used to treat infections caused by bacteria "
            "transmitted from non-human sources or where resistance genes spread from non-human sources."),
    "HIA": ("HIGHLY IMPORTANT ANTIMICROBIALS — meets one of the two CIA criteria. Important for human "
            "medicine but with somewhat lower priority for stewardship than CIA/HPCIA."),
    "IA": ("IMPORTANT ANTIMICROBIALS — meets neither CIA criterion fully but has medical importance. "
           "Used in human medicine but for less critical indications."),
    "NMI": ("NOT MEDICALLY IMPORTANT — antimicrobials NOT currently authorized for human use. Mainly "
            "used in veterinary medicine, animal feed, or agriculture."),
}

USE_DESC = {
    "humans_only": "AUTHORIZED FOR USE IN HUMANS ONLY — must NOT be used in food-producing animals or "
                   "crops to preserve effectiveness in human medicine.",
    "both_humans_animals": "AUTHORIZED FOR USE IN BOTH HUMANS AND ANIMALS — under WHO MIA stewardship, "
                          "use in animals must be carefully justified to mitigate AMR risk to humans.",
    "animals_only": "NOT AUTHORIZED FOR USE IN HUMANS — used only in veterinary medicine, animal feed, "
                    "or agriculture.",
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
    df = pd.read_csv("data/raw/who_mia_curated.csv")
    log.info("Loaded %d WHO MIA drug entries", len(df))

    examples = []

    # Task 1: CLASS LOOKUP
    for _, row in df.iterrows():
        prompt = (f"Instructions: Identify the antimicrobial class of the named drug according to the "
                  f"WHO 2024 List of Medically Important Antimicrobials.\n"
                  f"Drug: {row['drug']}\n"
                  f"Question: What antimicrobial class does this drug belong to?")
        response = (f"{row['drug']} belongs to the {row['class']} class per WHO MIA 2024 classification.")
        if not pd.isna(row.get("notes")) and row["notes"]:
            response += f" Notes: {row['notes']}."
        examples.append(_msg(prompt, response, "who_class_lookup"))

    # Task 2: WHO CATEGORY
    for _, row in df.iterrows():
        prompt = (f"Instructions: Determine the WHO MIA stewardship category for the named drug.\n"
                  f"Drug: {row['drug']}\n"
                  f"Question: Is this drug categorized as HPCIA, CIA, HIA, IA, or NMI in the WHO 2024 list?")
        response = (f"{row['drug']} is categorized as {row['who_category']} in the WHO MIA 2024 list. "
                    f"{CATEGORY_DESC[row['who_category']]}")
        examples.append(_msg(prompt, response, "who_category_assignment"))

    # Task 3: USE RESTRICTION
    for _, row in df.iterrows():
        prompt = (f"Instructions: State the WHO-authorized use restriction for the named drug.\n"
                  f"Drug: {row['drug']}\n"
                  f"Question: Is this drug authorized for use in humans only, both humans and animals, "
                  f"or animals only?")
        response = (f"Per WHO 2024 MIA list: {row['drug']} is {USE_DESC[row['use_authorization']]}")
        examples.append(_msg(prompt, response, "who_use_restriction"))

    # Task 4: CLASS MEMBERS
    by_class = defaultdict(list)
    for _, row in df.iterrows():
        by_class[(row["class"], row["who_category"])].append(row["drug"])
    for (cls, cat), drugs in by_class.items():
        if len(drugs) < 2:
            continue
        prompt = (f"Instructions: List the major members of the named antimicrobial class.\n"
                  f"Class: {cls} ({cat} per WHO 2024 MIA)\n"
                  f"Question: What are the clinically important drugs in this class?")
        response = (f"The {cls} class ({cat}) includes: " + ", ".join(drugs[:15]) +
                    (f" and others." if len(drugs) > 15 else "."))
        examples.append(_msg(prompt, response, "who_class_members"))

    rnd = random.Random(42)
    rnd.shuffle(examples)
    n_eval = max(20, len(examples) // 25)
    eval_set = examples[:n_eval]
    train_set = examples[n_eval:]
    for r in eval_set:
        r["split"] = "valid"

    from collections import Counter
    log.info("Total WHO examples: %d", len(examples))
    for task, n in Counter(e["task"] for e in examples).most_common():
        log.info("  %-30s %d", task, n)

    from datasets import Dataset, DatasetDict
    ds = DatasetDict({
        "train": Dataset.from_list(train_set),
        "valid": Dataset.from_list(eval_set),
    })
    out = Path("data/processed/amr-stage2-who")
    out.mkdir(parents=True, exist_ok=True)
    ds.save_to_disk(str(out))
    log.info("Wrote %s (%d train + %d valid)", out, len(train_set), len(eval_set))


if __name__ == "__main__":
    import pandas as pd
    main()
