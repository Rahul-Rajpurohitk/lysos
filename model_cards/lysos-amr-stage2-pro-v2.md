---
license: apache-2.0
task_categories:
  - text-generation
  - text2text-generation
language:
  - en
size_categories:
  - 100K<n<1M
tags:
  - drug-design
  - antimicrobial-resistance
  - smiles
  - peptide
  - instruction-tuning
  - amr
  - chain-of-thought
  - reasoning
---

# lysos-amr-stage2-pro-v2

A 364,432-train + 29,300-valid instruction-tuning dataset for fine-tuning
**Gemma 4 31B-it** on antimicrobial drug design and clinical reasoning, with
an elite chain-of-thought (CoT) reasoning slice covering 14 named-drug
task types — plus 55 held-out reasoning prompts for independent evaluation.

This is the **default Stage 2 SFT corpus** for the Lysos project (AMD Developer
Hackathon 2026). It supersedes `lysos-amr-stage2-pro` (v1) by adding a
high-quality, named-genes/MIC/trial-cited reasoning slice that targets
the under-specified slots in the original dataset.

## What's new in v2

| Slice | v1 | v2 | Δ |
|---|---:|---:|---:|
| Total train | 364,113 | 364,432 | +319 |
| Total valid | 29,300 | 29,300 | 0 |
| Held-out test (named-drug eval) | 0 | 55 | new |
| `drug_pathogen_reasoning` | 252 | 280 | +28 |
| `drug_mechanism_deep_dive` | 40 | 79 | +39 |
| `counterfactual_design` | 20 | 51 | +31 |
| `resistance_mechanism_explanation` | 12 | 46 | +34 |
| `drug_combination_synergy` | 17 | 44 | +27 |
| `cross_pathogen_spectrum` | 12 | 36 | +24 |
| `structure_activity_comparison` | 15 | 36 | +21 |
| `pathogen_specific_dive` | 6 | 32 | +26 |
| `pk_pd_reasoning` | 8 | 32 | +24 |
| `stewardship_decision` | 7 | 30 | +23 |
| `design_challenge` | 6 | 11 | +5 |
| `candidate_ranking` | 0 | 17 | new |
| `reward_profile_analysis` | 0 | 17 | new |
| `structural_strategy_reasoning` | 0 | 17 | new |

**14 active reasoning task types** plus the original ~13 chemistry/vocabulary
task types from v1, totaling ~27 task types in the final mix.

The 3 brand-new task types (`candidate_ranking`, `reward_profile_analysis`,
`structural_strategy_reasoning`) plug the Stage 3 GRPO reward-objective gap —
they teach the model to reason about multi-objective trade-offs across the
7 reward dimensions (predicted MIC, QED, SA, hemolysis, Tanimoto novelty,
embedding novelty, validity).

## Schema

Each row has:

```json
{
  "task":     "drug_pathogen_reasoning" | ...,
  "split":    "train" | "valid",
  "prompt":   "<instruction + named context>",
  "response": "<gold reasoning + decision>",
  "messages": "[{\"role\": \"user\", \"content\": ...}, ...]"
}
```

Note `messages` is a JSON-encoded string (matches v1 schema for
TRL SFTTrainer compatibility with `text_field=messages`).

## Recommended task_mix

The Stage 2 trainer config (`configs/stage2_amr_sft.yaml` in the Lysos repo)
uses these weights, summing to 1.0 across 26 task types:

```yaml
# Core chemistry (46%)
generation_for_target: 0.18
activity_prediction: 0.16
peptide_design: 0.08
drug_smiles: 0.02
drug_from_smiles: 0.02

# Safety + properties (12%)
safety_prediction: 0.08
drug_likeness: 0.04

# Drug + natural product knowledge (37%)
natural_product_origin: 0.04
natural_product_smiles: 0.03
natural_product_origin_smiles: 0.03
drug_id_lookup: 0.05
drug_inchi_key: 0.05
drug_synonyms: 0.05
drug_cas_lookup: 0.06
drug_reverse_cas: 0.06

# Elite named-drug reasoning slice (5%) — 25x oversample
drug_pathogen_reasoning: 0.020
drug_mechanism_deep_dive: 0.005
counterfactual_design: 0.004
resistance_mechanism_explanation: 0.003
drug_combination_synergy: 0.003
cross_pathogen_spectrum: 0.003
structure_activity_comparison: 0.002
pathogen_specific_dive: 0.002
pk_pd_reasoning: 0.002
stewardship_decision: 0.002
design_challenge: 0.001
candidate_ranking: 0.001
reward_profile_analysis: 0.001
structural_strategy_reasoning: 0.001
```

The reasoning slice represents 0.2% of the corpus by row count but 5% of
training compute — a deliberate **25x oversample** to give the model an
elite reasoning fingerprint without dominating the chemistry/vocabulary
slots.

## Held-out test set

49 prompts are held out for independent named-drug-reasoning evaluation.
Available as `data/synthetic/named_drug_test_split.jsonl` in the Lysos
repository (also at `data/processed/amr-stage2-pro-v2/test_named_drug.jsonl`
inside the dataset directory).

Stratified by task type (deterministic SHA-256 hash of prompt → top
14% per task), so every reasoning task type has ≥1 held-out example.

The merge script (`scripts/merge_named_drug_into_stage2.py`) verifies
**zero leakage**: any pre-existing prompt in v1 train that matches a
held-out test prompt is filtered out before re-attaching.

## Quality controls

The reasoning slice has been QC'd via `scripts/qc_named_drug.py`:
- ✓ Schema integrity across 388 entries
- ✓ Zero internal duplicate prompts or (prompt, response) pairs
- ✓ Zero held-out test leakage in train
- ✓ Cleaned 2 corrupt entries (truncated/placeholder) detected during QC
- Drug-name resolution: 73 combination drugs (e.g. `ceftaz-avi`,
  `mero-vab`, `sul-dur`, `aztreonam-avibactam`) are flagged as
  "unknown" by the heuristic but are all real combination antibiotics
  that aren't in the canonical `known-antibiotics.parquet` index;
  these are **expected false-positives** in the QC heuristic.

## Provenance

- Reasoning slice authored 2026-04-30 to 2026-05-03 by manual
  curation against named guidelines (IDSA, ATS, AHA, WHO, CDC),
  named trials (POET, MERINO, BPaL Nix-TB, ZeNix, ATTACK,
  Hepburn, van der Horst, Eagle, Geriak, etc.), and named drugs
  (each entry references DrugBank-resolvable molecules with
  specific MIC values, named genes/enzymes, and PK/PD targets).
- See `data/cot/sprint*.yaml` in the Lysos repo for source manifests.
- Schema-converted to Stage 2 pro format via
  `scripts/merge_named_drug_into_stage2.py`.

## Use

This dataset is intended for the Stage 2 SFT phase of the Lysos
training pipeline:

1. **Stage 1** — TxGemma-4 (chemistry foundation on TDC tasks)
2. **Stage 2 (this dataset)** — AMR specialization on top of TxGemma-4
3. **Stage 3** — GRPO RL with 7-component reward stack

Loading example:

```python
from datasets import load_dataset
ds = load_dataset("rahul24raj/lysos-amr-stage2-pro-v2")
print(ds["train"][0])
```

## License

Apache 2.0 — same as v1.

## Citation

```bibtex
@dataset{lysos_amr_stage2_pro_v2_2026,
  author = {Rahul Rajpurohit},
  title  = {lysos-amr-stage2-pro-v2: AMR drug-design + elite reasoning corpus},
  year   = {2026},
  url    = {https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2-pro-v2},
  note   = {AMD Developer Hackathon 2026, Track 2}
}
```
