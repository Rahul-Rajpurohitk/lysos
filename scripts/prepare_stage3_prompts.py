"""Stage 3 RL prompts data prep.

GRPO training only needs PROMPTS — the model generates responses, the reward
function scores them, no gold completions needed. This script builds a small
prompts-only dataset covering the AMR pathogen catalog with ask-style variations.

Output: HF Dataset with `prompt` field (and a `messages` field in chat format
for tokenizer.apply_chat_template).

Runs on CPU. Designed to be cheap to regenerate as we tune the prompt mix.

Usage:

    python scripts/prepare_stage3_prompts.py
    python scripts/prepare_stage3_prompts.py --push-to-hub rahul24raj/lysos-rl-prompts
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("stage3_prompts")

PATHOGENS = [
    {"short": "MRSA", "name": "Staphylococcus aureus (MRSA)",
     "context": "Methicillin-resistant Staphylococcus aureus is a major hospital-acquired pathogen causing skin, blood, and bone infections."},
    {"short": "Mtb", "name": "Mycobacterium tuberculosis",
     "context": "M. tuberculosis kills 1.5 million people per year. MDR and XDR strains require new drug classes."},
    {"short": "EColi-CRE", "name": "Escherichia coli (ESBL+ / CRE)",
     "context": "ESBL-producing or carbapenem-resistant E. coli causes severe urinary tract and bloodstream infections."},
    {"short": "KpneuCRE", "name": "Klebsiella pneumoniae (CRE)",
     "context": "Carbapenem-resistant K. pneumoniae is among the WHO's highest priority pathogens; mortality up to 50%."},
    {"short": "Abaum", "name": "Acinetobacter baumannii",
     "context": "Multidrug-resistant A. baumannii causes ICU pneumonia, often pan-resistant."},
    {"short": "Paer", "name": "Pseudomonas aeruginosa",
     "context": "P. aeruginosa is intrinsically resistant to many antibiotics."},
    {"short": "VRE", "name": "Enterococcus faecium (VRE)",
     "context": "Vancomycin-resistant Enterococcus faecium causes bloodstream and endocarditis infections."},
    {"short": "NGono", "name": "Neisseria gonorrhoeae",
     "context": "Drug-resistant gonorrhea is on the verge of becoming untreatable."},
]


# Prompt variations — all ask the model to design something for a pathogen.
# Variations across: modality (small mol vs peptide), constraint emphasis,
# domain framing. Each variation has a SMILES-output and a peptide-output form.

ASK_VARIANTS_SMI = [
    "Generate a single antibacterial small molecule against {name}, prioritizing low MIC, drug-likeness (Lipinski-compliant), and synthetic accessibility.\nOutput the molecule as a SMILES string.",
    "Design a novel small-molecule antibiotic for {name}. The compound should be drug-like (QED > 0.5), synthesizable, and structurally distinct from known antibiotics.\nReturn the molecule as a SMILES string.",
    "Propose a candidate antibacterial drug targeting {name}. Optimize for: low predicted MIC, low hepatotoxicity, and high oral bioavailability.\nOutput a SMILES string.",
    "Design a beta-lactam-class or quinolone-class analogue with activity against {name}, while improving on resistance profiles.\nReturn as a SMILES string.",
    "Generate a structurally novel compound likely to inhibit growth of {name}. Avoid close analogues of penicillins, cephalosporins, and fluoroquinolones.\nOutput as a SMILES string.",
]

ASK_VARIANTS_PEP = [
    "Design a short antimicrobial peptide (10-30 residues) against {name}, prioritizing low hemolytic activity and high antibacterial potency.\nOutput as a single-letter amino-acid sequence.",
    "Generate a novel cationic alpha-helical antimicrobial peptide targeting {name}. Length 12-25 residues, low predicted hemolysis.\nReturn the peptide sequence.",
    "Propose an antimicrobial peptide for {name}. The peptide should be amphipathic, charged, and structurally distinct from melittin/LL-37/magainin.\nOutput as a sequence.",
    "Design an anti-{short} peptide of 15-25 residues with high MIC potency and low hemolysis.\nReturn the amino-acid sequence.",
]


def build_prompt(pathogen: dict, ask: str) -> str:
    """Compose final prompt matching Stage 2 SFT format."""
    intro = "Instructions: Design an antibacterial agent for the following pathogen."
    return (
        f"{intro}\n"
        f"Context: {pathogen['context']}\n"
        f"Question: {ask.format(name=pathogen['name'], short=pathogen['short'])}"
    )


def build_examples(per_pathogen: int, modality_split: float, seed: int) -> list[dict]:
    """Generate prompts. modality_split = fraction that are small-molecule (rest peptide)."""
    rnd = random.Random(seed)
    out = []
    for p in PATHOGENS:
        n_smi = int(per_pathogen * modality_split)
        n_pep = per_pathogen - n_smi
        for _ in range(n_smi):
            ask = rnd.choice(ASK_VARIANTS_SMI)
            out.append(_pack(p, ask, modality="smiles"))
        for _ in range(n_pep):
            ask = rnd.choice(ASK_VARIANTS_PEP)
            out.append(_pack(p, ask, modality="peptide"))
    rnd.shuffle(out)
    return out


def _pack(p: dict, ask: str, modality: str) -> dict:
    prompt = build_prompt(p, ask)
    return {
        "prompt": prompt,
        "pathogen_short": p["short"],
        "pathogen_name": p["name"],
        "modality": modality,
        "split": "train",
        "messages": json.dumps([{"role": "user", "content": prompt}]),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prepare Stage 3 RL prompts dataset")
    p.add_argument("--per-pathogen", type=int, default=400,
                   help="How many prompts per pathogen (default: 400 → 3200 total across 8 pathogens)")
    p.add_argument("--smi-fraction", type=float, default=0.7,
                   help="Fraction of prompts asking for small molecules (rest peptides)")
    p.add_argument("--output-dir", type=Path, default=Path("data/processed/amr-rl-prompts"))
    p.add_argument("--push-to-hub", type=str, default=None)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    log.info("Building %d prompts/pathogen × %d pathogens × smi_fraction=%.2f",
             args.per_pathogen, len(PATHOGENS), args.smi_fraction)
    examples = build_examples(args.per_pathogen, args.smi_fraction, args.seed)

    # Train/eval split
    rnd = random.Random(args.seed)
    rnd.shuffle(examples)
    n_eval = max(40, len(examples) // 25)
    eval_set = examples[:n_eval]
    train_set = examples[n_eval:]
    for r in eval_set:
        r["split"] = "valid"

    log.info("Total prompts: %d (train=%d, valid=%d)",
             len(examples), len(train_set), len(eval_set))

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
        if not (os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")):
            log.error("--push-to-hub requires HF_TOKEN env var")
            return 3
        log.info("Pushing to HF Hub: %s (private)", args.push_to_hub)
        ds.push_to_hub(args.push_to_hub, private=True)
        log.info("✓ pushed")

    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
