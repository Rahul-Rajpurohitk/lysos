"""Convert EUCAST clinical breakpoints into Stage 2 training examples.

Generates 3 task types:
  1. eucast_breakpoint_lookup — "What's the S/R breakpoint for [drug] vs [pathogen]?"
  2. eucast_susceptibility_classification — "Is MIC X µg/mL clinically susceptible?"
  3. eucast_pathogen_drug_match — "Which drugs have approved breakpoints for [pathogen]?"

Output: data/processed/amr-stage2-eucast/
"""
import json
import logging
import random
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] eucast-build | %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("eucast-build")

PATHOGEN_FULL = {
    "Enterobacterales": "Enterobacterales (E. coli, Klebsiella, Enterobacter, etc.)",
    "Pseudomonas": "Pseudomonas aeruginosa",
    "Acinetobacter": "Acinetobacter baumannii complex",
    "Staphylococcus": "Staphylococcus aureus",
    "Enterococcus": "Enterococcus faecalis / faecium",
    "Streptococcus A,B,C,G": "Beta-hemolytic Streptococci (groups A, B, C, G)",
    "S.pneumoniae": "Streptococcus pneumoniae",
    "M.tuberculosis": "Mycobacterium tuberculosis",
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
    df = pd.read_csv("data/raw/eucast_breakpoints.csv")
    log.info("Loaded %d EUCAST breakpoints", len(df))

    examples = []

    # Task 1: BREAKPOINT LOOKUP
    for _, row in df.iterrows():
        path = PATHOGEN_FULL.get(row["pathogen_group"], row["pathogen_group"])
        drug = row["drug"]
        s = row["breakpoint_s_mg_l"]
        r = row["breakpoint_r_mg_l"]
        if pd.isna(s) and pd.isna(r):
            continue

        prompt = (f"Instructions: State the EUCAST clinical breakpoints for the named drug-pathogen pair.\n"
                  f"Drug: {drug}\nPathogen: {path}\n"
                  f"Question: What are the EUCAST v15.0 (2025) susceptibility breakpoints (S ≤ and R >)?")

        parts = []
        if not pd.isna(s):
            parts.append(f"SUSCEPTIBLE if MIC ≤ {s:.4g} mg/L")
        if not pd.isna(r):
            parts.append(f"RESISTANT if MIC > {r:.4g} mg/L")
        if not pd.isna(s) and not pd.isna(r) and s < r:
            parts.append(f"INTERMEDIATE / SUSCEPTIBLE-INCREASED-EXPOSURE: MIC > {s:.4g} but ≤ {r:.4g} mg/L")

        response = (f"Per EUCAST v15.0 clinical breakpoints (valid 2025-01-01 to 2025-12-31) for "
                    f"{drug} against {path}: " + "; ".join(parts) + ".")
        examples.append(_msg(prompt, response, "eucast_breakpoint_lookup"))

    # Task 2: CLASSIFICATION at specific MIC
    test_mics = [0.06, 0.125, 0.25, 0.5, 1, 2, 4, 8, 16, 32]
    for _, row in df.iterrows():
        path = PATHOGEN_FULL.get(row["pathogen_group"], row["pathogen_group"])
        drug = row["drug"]
        s = row["breakpoint_s_mg_l"]
        r = row["breakpoint_r_mg_l"]
        if pd.isna(s) or pd.isna(r):
            continue

        # Pick 2 representative test MICs spanning the breakpoint
        for mic in [s/2, (s+r)/2 if r > s else s, r*1.5]:
            if mic <= 0:
                continue
            prompt = (f"Instructions: Classify a measured MIC according to EUCAST clinical breakpoints.\n"
                      f"Drug: {drug}\nPathogen: {path}\nMeasured MIC: {mic:.4g} mg/L\n"
                      f"Question: Is this isolate clinically Susceptible (S), Susceptible/Increased-Exposure (I), "
                      f"or Resistant (R)?")

            if mic <= s:
                cls = f"SUSCEPTIBLE (S) — at standard dosing the drug is expected to be effective."
            elif mic > r:
                cls = f"RESISTANT (R) — therapeutic failure is highly likely; drug should not be used."
            else:
                cls = (f"SUSCEPTIBLE / INCREASED EXPOSURE (I) — drug may work at high-dose regimens "
                       f"or with concentration-enhancing measures (prolonged infusion, etc.).")

            response = (f"Classification: {cls} EUCAST v15.0 breakpoints for {drug} vs {path}: "
                        f"S ≤ {s:.4g} mg/L, R > {r:.4g} mg/L.")
            examples.append(_msg(prompt, response, "eucast_susceptibility_classification"))

    # Task 3: DRUGS APPROVED FOR EACH PATHOGEN GROUP
    by_path = defaultdict(list)
    for _, row in df.iterrows():
        by_path[row["pathogen_group"]].append((row["drug"],
                                                row["breakpoint_s_mg_l"],
                                                row["breakpoint_r_mg_l"]))
    for path_short, drugs in by_path.items():
        path_full = PATHOGEN_FULL.get(path_short, path_short)
        # Sample top 10 drugs to keep response reasonable
        drugs_str = "\n".join([f"  - {d}: S ≤ {s:.4g} mg/L, R > {r:.4g} mg/L"
                                for d, s, r in drugs[:10] if not (pd.isna(s) and pd.isna(r))])
        prompt = (f"Instructions: List the major antibiotics with approved EUCAST clinical breakpoints "
                  f"for the named pathogen group.\nPathogen group: {path_full}\n"
                  f"Question: Which drugs have established S/R breakpoints?")
        response = (f"EUCAST v15.0 (2025) provides clinical breakpoints for the following antibiotics "
                    f"against {path_full}:\n{drugs_str}\n(Plus additional agents — full list at "
                    f"www.eucast.org/clinical_breakpoints.)")
        examples.append(_msg(prompt, response, "eucast_pathogen_drug_match"))

    rnd = random.Random(42)
    rnd.shuffle(examples)
    n_eval = max(50, len(examples) // 25)
    eval_set = examples[:n_eval]
    train_set = examples[n_eval:]
    for r in eval_set:
        r["split"] = "valid"

    from collections import Counter
    log.info("Total EUCAST examples: %d", len(examples))
    for task, n in Counter(e["task"] for e in examples).most_common():
        log.info("  %-40s %d", task, n)

    from datasets import Dataset, DatasetDict
    ds = DatasetDict({
        "train": Dataset.from_list(train_set),
        "valid": Dataset.from_list(eval_set),
    })
    out = Path("data/processed/amr-stage2-eucast")
    out.mkdir(parents=True, exist_ok=True)
    ds.save_to_disk(str(out))
    log.info("Wrote %s (%d train + %d valid)", out, len(train_set), len(eval_set))


if __name__ == "__main__":
    import pandas as pd
    main()
