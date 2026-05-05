---
license: cc-by-4.0
language:
  - en
tags:
  - drug-design
  - antimicrobial-resistance
  - amr
  - dataset
  - gemma
  - sft
  - chemistry
  - smiles
  - peptide
size_categories:
  - 100K<n<1M
task_categories:
  - text-generation
  - text2text-generation
---

# Lysos AMR Stage 2 SFT Dataset — pro-v11

**Dataset for Stage-2 supervised fine-tuning of Lysos**, an antimicrobial
drug-design system built on Gemma 4. Pro-v11 is the quality-weighted final
SFT corpus: 379,486 train / 22,936 valid / 50 test.

## What it is

Pro-v11 trains a model to:
1. Design candidate antimicrobial molecules (small molecules + AMPs) against 8 priority pathogens
2. Reason through Designer / Critic / Strategist / Editor agent roles in the Lysos Workbench
3. Use the 25-tool Workbench registry correctly (validated args, structured tool calls, structured tool result interpretation)
4. Cite real PDB residues, real escape mutations, real first-line therapy, real surveillance data
5. Refuse out-of-scope misuse via abstracted-category-token training (no literal harmful names anywhere in corpus)
6. Express calibrated uncertainty via 4-tier confidence convention

## How it was built

### Source layers (built up from pro-v1 to pro-v11 across 8 dataset versions)

| Layer | Rows |
|-------|------|
| Stage-2 chemistry (ChEMBL+DrugBank+NPAtlas+DrugCentral+CO-ADD+TDC+CARD+PDB+PubChem+ZINC+DBAASP+DRAMP) | ~270K |
| Synthetic agentic traces (Designer/Critic/Strategist multi-turn) | ~30K |
| v6 audit fixes (safety_refusal abstracted tokens, tool_arg_validation, held-out eval split) | ~1.5K |
| v8 manual teacher distillation (chem + systems + architecture + raw-data + edge/clinical) | ~43.5K |
| v9 targeted distillation (per-PDB + per-mutation + 3-way + chemistry self-correction + per-indication + tool chains) | ~17K |
| v10 eval-aligned distillation (chem-validity + novelty + tool-arg-precision + refusal extended + reasoning faithfulness + confidence + clinical guidelines + drug repositioning + comparative + stewardship) | ~17.5K |
| v11 quality-weighted resampling (top-quartile rows oversampled 2x, bottom-quartile 0.5x) | resampling |

### Audit history

The corpus was deeply audited in 5 critical-issue findings + fixes:
1. Peptide-as-SMILES contamination (~9K rows from DBAASP/DRAMP) → recovered to proper SMILES via `Chem.MolFromSequence`
2. Stereochemistry undefined on ~20% → re-canonicalized via MolStandardize, tagged stereo_state
3. Tautomer arbitrariness → canonicalized via MolVS TautomerEnumerator
4. List-typed content blocks (~4,354 msgs from Anthropic-format legacy) → flattened to canonical strings
5. Placeholder SMILES suffixes (e.g., 'CCO_h1') in long-form traces → replaced with real RDKit-randomized SMILES
6. Heavy assistant-text duplication (~50% of rows; one canned answer 1,774x) → capped at 12 reps per identical text
7. Short canned answers (<30 chars; 9,812 rows) → wrapped in fuller-context sentence templates

### Quality scoring

Per-row 0-10 score combines:
- token length (longer reasoning = higher weight)
- structural depth (tool-call count, decision blocks, citation count, PDB references)
- source signal (teacher distillation > template synthesis > raw lookup)
- novelty (penalizes short canned outputs and templated prefixes)

Top-quartile rows are oversampled 2x; bottom-quartile rows downsampled 0.5x.

## Schema

| Column | Type | Description |
|--------|------|-------------|
| task | str | Task label (~120 buckets after collapse) |
| pathogen | str / null | One of 8 priority pathogens (or null with primer-injected system msg) |
| messages | str (JSON-serialized) | Chat-formatted conversation: [{"role": "system" / "user" / "assistant" / "tool", "content": "..."}, ...] |
| split | str | "train" / "valid" / "test" |

## Splits

- **train**: 379,486 rows (95% by default; quality-weighted resampled from pro-v10)
- **valid**: 22,936 rows (5% sampled from pro-v10)
- **test**: 50 rows (held-out canary; manually curated; NEVER trained on)

## Pathogen distribution

8 priority pathogens (WHO-tier critical or high):
| Pathogen | WHO Tier | Code |
|----------|----------|------|
| Mycobacterium tuberculosis | Critical | Mtb |
| Carbapenem-resistant Escherichia coli | Critical | EColi-CRE |
| Carbapenem-resistant Klebsiella pneumoniae | Critical | KpneuCRE |
| Acinetobacter baumannii | Critical | Abaum |
| Methicillin-resistant Staphylococcus aureus | High | MRSA |
| Pseudomonas aeruginosa | High | Paer |
| Vancomycin-resistant Enterococcus | High | VRE |
| Neisseria gonorrhoeae | High | NGono |

Generic-chemistry rows (pathogen=null) have a system-prompt pathogen primer
applied at builder time, providing pathogen-specific framing without
distorting metadata.

## Intended use

- Fine-tune Gemma 4 (or any LLM with similar chat template) for antimicrobial drug design
- Supervised fine-tuning before GRPO RL (Stage 3)
- Research benchmarking (zero-shot eval on the held-out test split)

## Out-of-scope use

- This dataset is NOT for designing chemical weapons, controlled substances, or biological agents — every safety_refusal row uses abstracted category tokens (CWC_*, CDC_TIER_*, DEA_SCHEDULE_*, DURC_*, etc.) and the model is trained to refuse such requests regardless of framing.
- The dataset is NOT a substitute for wet-lab validation. Predicted MICs need experimental confirmation before clinical use.
- The dataset is NOT for generating arbitrary biological sequences or for use outside antimicrobial drug-design context.

## Limitations

- Pathogen coverage limited to 8 priority targets; out-of-distribution pathogens (Salmonella, Streptococcus pneumoniae, etc.) have no in-corpus training signal.
- ChEMBL bias: Mtb dominates per-pathogen MIC counts (~4,200 entries vs ~590 for NGono).
- Generic chemistry rows (pathogen=null) have a primer for pathogen context but the underlying chemistry tasks are pathogen-agnostic.
- Stereochemistry: ~20% of pre-cleanup corpus had undefined stereo. Cleanup tags this as stereo_state='undefined'; downstream code can filter/weight.

## Citation

```
@dataset{lysos_amr_stage2_pro_v11,
  title  = {Lysos AMR Stage 2 SFT Dataset (pro-v11)},
  year   = {2026},
  author = {Rajpurohit, Rahul},
  url    = {https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2-pro-v11},
  note   = {Antimicrobial drug-design supervised fine-tuning corpus, AMD MI300X hackathon submission}
}
```

## License

CC-BY-4.0. Free for research + commercial use with attribution.
