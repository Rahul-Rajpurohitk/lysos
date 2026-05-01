---
license: apache-2.0
library_name: transformers
base_model: rahul24raj/lysos-base
tags:
  - drug-design
  - antimicrobial-resistance
  - generative-chemistry
  - smiles
  - peptide
  - gemma
  - reinforcement-learning
  - grpo
language:
  - en
pipeline_tag: text-generation
datasets:
  - rahul24raj/lysos-amr-stage2
  - rahul24raj/lysos-rl-prompts
metrics:
  - validity
  - drug-likeness
  - synthetic-accessibility
  - predicted-mic
  - hemolysis-safety
  - novelty
---

# Lysos-RL

Generative drug designer for antimicrobial resistance, built on Gemma 4 31B-it
and trained with Group Relative Policy Optimization (GRPO) using verifiable
rewards.

> **Status**: model card stub. The actual checkpoint will be pushed here when
> Stage 3 RL training completes on the AMD MI300X.

## Model description

Lysos generates candidate antibacterial molecules — either small molecules
(SMILES) or antimicrobial peptides — given a target pathogen specification.
Each generation is scored on a six-component verifiable composite reward:

| Component | What it checks |
|---|---|
| `validity` | RDKit-parseable structure |
| `drug_likeness_qed` | Bickerton's QED + Lipinski's Rule of Five |
| `synthesizability` | Ertl's SA score (1–10, lower is easier) |
| `hemolysis_safety` | Inverse predicted hemolytic activity |
| `predicted_mic` | log10(1/MIC) heuristic predictor (Stage 1) → ML predictor (Stage 3) |
| `novelty` | Tanimoto distance to known antibiotics + EmbeddingGemma cosine novelty |

## Training

### Stage 1 — TxGemma-4 chemistry foundation

Replicates Google's TxGemma recipe on the Therapeutics Data Commons (~50
ADMET, binding, and toxicity tasks). Outputs a chemistry-aware Gemma 4 base.

### Stage 2 — AMR specialization SFT

Supervised fine-tune on
[`rahul24raj/lysos-amr-stage2`](https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2)
— 222,606 instruction-tuning examples drawn from real public sources:

- ChEMBL (REST API) — 16,462 bacterial activity records
- DBAASP — 6,256 antimicrobial peptides with per-strain MIC + hemolysis
- DRAMP — 8,532 peptide records
- DrugBank Open — 14,630 drug names + synonyms + InChI Keys + CAS
- CARD — 3,543 resistance-target proteins
- PDB (RCSB) — 3,136 AMR-pathogen target structures
- ZINC — FDA-approved + investigational drug-like SMILES

### Stage 3 — GRPO RL with verifiable rewards

Reinforcement learning on
[`rahul24raj/lysos-rl-prompts`](https://huggingface.co/datasets/rahul24raj/lysos-rl-prompts)
— 3,200 generation prompts spanning 8 priority pathogens. Each rollout is
scored by the six-component composite reward and the policy is updated with
GRPO (DeepSeek-R1 style).

## Hardware

Trained on a single AMD Instinct MI300X (192 GB HBM3) on the AMD Developer
Cloud. The MI300X's memory capacity is what makes coresident policy +
reference + reward training possible on a single card.

## Evaluation

Stage 2 (SFT) baseline vs Stage 3 (RL-tuned) comparison:

| Metric | Stage 2 SFT | Stage 3 RL | Δ |
|---|---|---|---|
| Validity rate | 87% | 94% | +7% |
| Mean predicted MIC | 0.41 | 0.62 | +50% |
| Mean QED | 0.54 | 0.61 | +13% |
| Mean novelty (semantic) | 0.68 | 0.79 | +16% |
| Composite reward | +0.51 | +0.69 | +35% |

> Numbers above are training targets — replaced with empirical scores after
> Stage 3 RL completes.

## Intended use

- Research tool for designing novel antibacterial chemotypes against
  resistant pathogens (MRSA, M. tuberculosis, ESBL+ E. coli, K. pneumoniae
  CRE, A. baumannii, P. aeruginosa, VRE, N. gonorrhoeae).
- Inputs to downstream wet-lab screening — every Lysos candidate must be
  experimentally validated before any clinical inference.

## Out of scope

- Direct clinical use. This is a generative design model, not a clinical
  decision-support tool. Outputs are unvalidated.
- Toxicology endpoints beyond hemolysis. Other ADMET endpoints require
  domain-specific predictors not bundled here.

## Limitations

- The MIC predictor in this v1 is a heuristic; expect noisy individual scores.
  The aggregate ranking is more reliable than any single value.
- Novelty is measured *against the training set*. Truly novel scaffolds
  cannot be guaranteed.
- Generated molecules have not been wet-lab validated.

## Citation

```bibtex
@software{rajpurohit_lysos_2026,
  author = {Rajpurohit, Rahul},
  title  = {Lysos: An open-source generative drug designer for antimicrobial resistance},
  year   = {2026},
  url    = {https://github.com/Rahul-Rajpurohitk/lysos}
}
```

## Acknowledgments

- Gemma 4 + EmbeddingGemma — Google
- TxGemma — Google (training-recipe inspiration)
- AMD Developer Cloud — compute on MI300X
- lablab.ai + AMD Developer Hackathon — venue
