---
license: apache-2.0
task_categories:
  - text-generation
  - text2text-generation
language:
  - en
size_categories:
  - 10K<n<100K
tags:
  - drug-design
  - antimicrobial-resistance
  - smiles
  - peptide
  - instruction-tuning
  - amr
---

# lysos-amr-stage2

A 31,855-example instruction-tuning dataset for fine-tuning generative drug
design models on antimicrobial resistance.

## Sources

| Source | Records | API / format |
|---|---|---|
| ChEMBL | 16,462 | REST · per-pathogen activity (MIC, MBC, IC50, Ki) |
| DBAASP | growing | REST + N+1 detail · antimicrobial peptides + hemolysis |
| DRAMP | 8,532 | XLSX bulk · curated AMP records |
| CARD | 3,543 | tarball · resistance-determinant proteins |
| ZINC | 100 | subsets · FDA + in-trials drug-like SMILES |
| PDB (RCSB) | 3,136 | GraphQL · AMR-pathogen target metadata |

All sources are public and use open / permissive licenses.

## Format

Each example has:

```json
{
  "task": "design_molecule" | "score_smiles" | "compare_drugs" | ...,
  "split": "train" | "valid",
  "prompt": "<the instruction>",
  "response": "<the gold completion>",
  "messages": [
    {"role": "user",      "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

The `messages` field follows the Gemma 4 chat template and is what training
loaders should consume directly.

## Splits

| Split | Rows |
|---|---|
| train | 30,263 |
| valid | 1,592 |

## Tasks covered

- `design_molecule` — given a target pathogen, generate a candidate SMILES
- `design_peptide` — given a target pathogen, generate a candidate sequence
- `score_smiles` — given a SMILES, predict drug-likeness / SA / MIC
- `compare_drugs` — given two SMILES, identify the more potent one
- `explain_resistance` — given a CARD entry, explain the resistance mechanism
- `target_match` — given a PDB structure, identify the parent pathogen
- (full list in `vault/research/2026-04-30-stage2-task-taxonomy.md`)

## Used by

- [`rahul24raj/lysos-base`](https://huggingface.co/rahul24raj/lysos-base)
  — Gemma 4 31B-it after AMR specialization SFT
- [`rahul24raj/lysos-rl`](https://huggingface.co/rahul24raj/lysos-rl) —
  the same model after Stage 3 GRPO RL

## Citation

If you use this dataset, please cite the parent project:

```bibtex
@software{rajpurohit_lysos_2026,
  author = {Rajpurohit, Rahul},
  title  = {Lysos: An open-source generative drug designer for antimicrobial resistance},
  year   = {2026},
  url    = {https://github.com/Rahul-Rajpurohitk/lysos}
}
```
