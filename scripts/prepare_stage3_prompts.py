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
    # Generic
    "Generate a single antibacterial small molecule against {name}, prioritizing low MIC, drug-likeness (Lipinski-compliant), and synthetic accessibility.\nOutput the molecule as a SMILES string.",
    "Design a novel small-molecule antibiotic for {name}. The compound should be drug-like (QED > 0.5), synthesizable, and structurally distinct from known antibiotics.\nReturn the molecule as a SMILES string.",
    "Propose a candidate antibacterial drug targeting {name}. Optimize for: low predicted MIC, low hepatotoxicity, and high oral bioavailability.\nOutput a SMILES string.",
    "Generate a structurally novel compound likely to inhibit growth of {name}. Avoid close analogues of penicillins, cephalosporins, and fluoroquinolones.\nOutput as a SMILES string.",
    "Design an antibiotic candidate against {name} that bypasses common resistance mechanisms (efflux pumps, beta-lactamases, ribosomal mutations).\nOutput as a SMILES string.",
    "Propose a single antibacterial molecule against {name}. Constraint: must be a small molecule under 500 Da with at most 5 hydrogen-bond donors and 10 acceptors.\nReturn a SMILES.",
    # Antibiotic-class scaffolded
    "Design a beta-lactam analogue active against {name}. Modify the side chains to evade beta-lactamase hydrolysis.\nReturn as a SMILES string.",
    "Design a fluoroquinolone analogue with activity against {name}. Optimize the C-7 substituent to avoid efflux-mediated resistance.\nReturn as a SMILES string.",
    "Design a tetracycline-class analogue against {name}. Modify ring D to evade ribosomal protection proteins.\nReturn as a SMILES string.",
    "Design a macrolide-class analogue (14-membered ring) against {name}. Modify the cladinose sugar to retain potency despite erm-mediated methylation resistance.\nReturn as a SMILES string.",
    "Design an oxazolidinone analogue with activity against {name}. The compound should retain ribosomal binding without cross-resistance to linezolid.\nReturn as a SMILES string.",
    "Design an aminoglycoside-class scaffold active against {name}. Optimize substituents to avoid aminoglycoside-modifying enzymes.\nReturn as a SMILES string.",
    "Design a glycopeptide-class analogue (vancomycin scaffold) against {name}. Bypass D-Ala-D-Lac resistance.\nReturn as a SMILES string.",
    "Design a polymyxin-class lipopeptide against {name}. Reduce nephrotoxicity while retaining LPS binding.\nReturn as a SMILES.",
    "Design a rifamycin-class compound against {name}. The compound should evade rpoB mutational resistance.\nReturn as a SMILES string.",
    # ADMET-constrained
    "Design an antibacterial against {name} with high oral bioavailability and a half-life suitable for once-daily dosing.\nReturn a SMILES string.",
    "Design an antibacterial against {name} that crosses the blood-brain barrier (LogP 1-3, MW < 400).\nReturn a SMILES.",
    "Design an antibacterial against {name} with no CYP3A4 inhibition liability and minimal QT-prolongation risk.\nReturn a SMILES.",
    "Design an injectable antibacterial against {name}. Solubility >100 mg/mL in saline.\nReturn a SMILES.",
    # Mechanism-of-action constrained
    "Design a novel cell-wall biosynthesis inhibitor active against {name}. Target should not be PBP1, PBP2, or PBP3 specifically.\nReturn a SMILES string.",
    "Design a topoisomerase IV inhibitor with selectivity for {name}. The compound should have minimal cross-reactivity with mammalian topoisomerases.\nReturn a SMILES.",
    "Design a DNA-gyrase inhibitor active against {name}. Differentiate from quinolones by binding to a non-overlapping pocket.\nReturn a SMILES.",
    "Design a bacterial RNA polymerase inhibitor against {name}. Prefer non-rifamycin scaffolds.\nReturn as a SMILES.",
    "Design an LpxC inhibitor active against {name}. Target hydroxamic-zinc binding for selectivity.\nReturn as a SMILES.",
    "Design a folate-pathway antagonist active against {name} (DHFR or DHPS inhibitor) with reduced trimethoprim-sulfonamide cross-resistance.\nReturn as a SMILES.",
    # Combination-style
    "Design a beta-lactamase inhibitor that, in combination with amoxicillin, restores activity against {name}. The inhibitor itself need not be antibacterial.\nReturn the inhibitor SMILES.",
    "Design an efflux-pump inhibitor adjuvant for {name}. The compound should re-sensitize resistant strains to existing antibiotics.\nReturn a SMILES.",
    "Design a permeabilizer of the gram-negative outer membrane to potentiate antibiotic uptake into {name}.\nReturn a SMILES.",
    # Natural-product-inspired
    "Design a natural-product-inspired antibacterial against {name}. Take inspiration from polyketide or non-ribosomal-peptide scaffolds while remaining synthetically tractable.\nReturn a SMILES.",
    "Design a fragment-based antibacterial against {name}. Maximum heavy atoms = 22.\nReturn a SMILES.",
    # Novelty-emphasized
    "Generate a structurally novel antibiotic candidate against {name}. Tanimoto similarity to known antibiotics in the training set must be < 0.4.\nReturn a SMILES.",
]

ASK_VARIANTS_PEP = [
    # Generic
    "Design a short antimicrobial peptide (10-30 residues) against {name}, prioritizing low hemolytic activity and high antibacterial potency.\nOutput as a single-letter amino-acid sequence.",
    "Generate a novel cationic alpha-helical antimicrobial peptide targeting {name}. Length 12-25 residues, low predicted hemolysis.\nReturn the peptide sequence.",
    "Propose an antimicrobial peptide for {name}. The peptide should be amphipathic, charged, and structurally distinct from melittin/LL-37/magainin.\nOutput as a sequence.",
    "Design an anti-{short} peptide of 15-25 residues with high MIC potency and low hemolysis.\nReturn the amino-acid sequence.",
    # Structural-class
    "Design a beta-defensin-inspired AMP active against {name}. Cysteine-stabilized fold, 25-40 residues.\nReturn as a sequence.",
    "Design a tachyplesin-class disulfide-stabilized AMP against {name}. 16-20 residues.\nReturn as a sequence.",
    "Design a proline-rich AMP (Bac7-class) targeting {name} via ribosome inhibition. 20-35 residues.\nReturn as a sequence.",
    "Design a cyclic AMP against {name} with at least one disulfide bond. 12-20 residues.\nReturn as a sequence.",
    # Charge / hydrophobicity constrained
    "Design an AMP against {name} with net charge +4 to +8 and hydrophobicity 30-45%. 18-25 residues.\nReturn as a sequence.",
    "Design a tryptophan-rich AMP active against {name}. At least 3 Trp residues, 12-20 residues total.\nReturn as a sequence.",
    "Design a histidine-rich AMP that activates only at acidic pH (intracellular targeting). 15-25 residues, MIC against {name}.\nReturn as a sequence.",
    # Cell-penetrating
    "Design an arginine-rich cell-penetrating AMP targeting intracellular pathogens, optimized for {name}.\nReturn as a sequence.",
    # Lipid-tagged / lipopeptide
    "Design a lipopeptide against {name} with a C12-C16 fatty acid tail and a cyclized peptide head (12-15 residues).\nReturn as a sequence.",
    # Hybrid / chimeric
    "Design a chimeric AMP against {name} fusing the pore-forming N-terminus of magainin with the membrane-targeting C-terminus of LL-37. Retain potency, reduce hemolysis.\nReturn as a sequence.",
    # Selectivity-focused
    "Design a salt-tolerant AMP against {name} that retains potency at physiological NaCl (150 mM). 18-30 residues.\nReturn as a sequence.",
    "Design an AMP against {name} with selectivity index (HC50/MIC) > 50.\nReturn as a sequence.",
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
    p.add_argument("--per-pathogen", type=int, default=1500,
                   help="How many prompts per pathogen (default: 1500 → 12000 total across 8 pathogens)")
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
