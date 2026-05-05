# Datasheet for the Lysos AMR Dataset

Following [Gebru et al. 2018, *Datasheets for Datasets*](https://arxiv.org/abs/1803.09010).
Covers all dataset versions (pro-v3 → pro-v12) and the RL prompts dataset.

## Motivation

### For what purpose was the dataset created?

To train Gemma-4-based language models for antimicrobial drug-design (AMR
candidate generation, MIC prediction, agent-mediated Workbench operation,
out-of-scope refusal). Specifically targets the 8 WHO-priority pathogens
(MRSA, Mtb, EColi-CRE, KpneuCRE, Abaum, Paer, VRE, NGono).

### Who created the dataset?

Rahul Rajpurohit (independent, lablab.ai AMD Developer Hackathon submission).

### Who funded the creation?

No external funding. Hackathon submission.

## Composition

### What do the instances represent?

Each instance is a chat-formatted multi-turn conversation between agents
(system, user, assistant, tool) plus metadata: `task` label, `pathogen`
context, `split` ("train" / "valid" / "test").

### How many instances are there?

Pro-v12 (default): 380,844 train + 23,015 valid + 58 test = **403,917 rows**.

Across versions:
- pro-v3: 409K train (raw aggregation)
- pro-v5: 308K train (cleaned)
- pro-v8-v10: 308K + teacher distillation (43.5K → 78.15K)
- pro-v11: 379K train (quality-weighted)
- pro-v12: 380K train (+counterfactuals + time-aware test)

### Data sources

| Source | Records | Use |
|--------|---------|-----|
| ChEMBL | 13,809 (cleaned) | MIC measurements per pathogen |
| DrugBank Open | 14,630 | Drug name + SMILES + PK |
| NPAtlas | 13,218 | Natural products + producer organism |
| DBAASP + DRAMP | 8,847 (recovered) | AMP corpus |
| DrugCentral | 3,716 | Approved drug cross-validation |
| CO-ADD | ~70K | Open antimicrobial screening |
| TDC | 151,530 | ADME/Tox/HTS instruction tuning |
| CARD | 3,543 | Resistance gene catalog |
| PDB | 3,136 | Structural targets |
| PubChem | 1,268 | BioAssay activity |
| ZINC (synthetic) | ~100K | Property-matched decoys |
| **Manual teacher distillation** | **78,150 + 1,437** | **Authored inline by team** |

### Is there a label or target?

Yes — for SFT, the assistant turns are the labels. For RL, the reward is
multi-component (12 reward modules in `src/eval/rewards/`).

### Is any information missing?

- Wet-lab MIC validation (predictions only; needs experimental confirmation)
- Patient-level outcome data (clinical decisions are de-identified at narrative level)
- Some PK panel entries have null fields (drug-specific data sparseness)

### Are there relationships between individual instances?

Yes — InChI key cross-source dedup ensures no exact-molecule duplicates.
Counterfactual pair instances are explicitly linked. Three-way agent
dialogues span multiple instance roles (Designer, Critic, Strategist
turns belong to one campaign).

### Are there recommended data splits?

- **train (95%)**: SFT training
- **valid (5%)**: Loss-on-eval, early stopping
- **test (50 rows + 8 time-aware)**: held-out canary; never trained on.
  Tests OOD generalization + temporal generalization (2020+ surveillance findings).

### Are there errors, sources of noise, or redundancies?

Caught + fixed in pre-pro-v5 audits:
1. ~9,000 peptide-as-SMILES contamination → recovered to proper SMILES
2. ~20% stereo-undefined → tagged
3. Tautomer arbitrariness → canonicalized
4. ~4,354 list-typed content blocks → flattened
5. Placeholder SMILES suffixes → replaced with real RDKit-randomized
6. ~50% assistant-text duplication (one canned answer 1,774×) → capped at 12 reps
7. 9,812 short canned answers (<30 chars) → wrapped in fuller-context

Remaining noise (acknowledged):
- ChEMBL submission bias toward Mtb (~4.2K vs ~590 NGono)
- TDC ADMET predictors trained on diverse compounds; antibacterial-specific
  predictions less calibrated
- Synthetic agentic traces are templated; teacher distillation is manually
  authored but follows author's mental model (single author bias)

### Is the dataset self-contained?

Yes. All instances bundled. External references (PDB IDs, citation strings)
are textual references, not external data dependencies.

### Does it contain confidential / harmful data?

NO. Specifically:
- Safety_refusal training uses **abstracted category tokens** only
  (`<CWC_SCHEDULE_1_AGENT>`, `<CDC_TIER_1_SELECT_AGENT>`, `<DEA_SCHEDULE_I_CONTROLLED>`,
  `<DURC_*>`, etc.). NO literal harmful chemical / biological agent names.
- Patient-narrative case rounds are from publicly-available textbooks +
  IDSA guidelines, no PHI / patient-identifiable info.

## Collection process

### How was the data acquired?

- ChEMBL, DrugBank Open, NPAtlas, DrugCentral, CARD, PDB, ZINC, PubChem,
  TDC, CO-ADD: bulk programmatic download via official APIs / FTP.
- DBAASP, DRAMP: scraped from public web sources.
- Teacher distillation: manually authored by Claude (Anthropic) in this
  development session via guided generation. NO API spend; all in-session
  authoring.

### Who participated?

- Author: Rahul Rajpurohit
- Teacher distillation co-authoring: Claude Opus 4.7 (in-session)

### Over what timeframe?

Apr 29 → May 5 2026 (single-week hackathon sprint).

### Is the collection consistent with the stated purpose?

Yes — antimicrobial drug-design corpus + AMR-aware multi-agent system training.

## Preprocessing / cleaning / labeling

### Was the data preprocessed?

Yes — comprehensive cleanup pipeline:
1. Stereochemistry canonicalization via RDKit MolStandardize
2. Tautomer canonicalization via MolVS TautomerEnumerator
3. Peptide-as-SMILES recovery via Chem.MolFromSequence
4. Quality scoring + reweighting (top quartile 2× / bottom quartile 0.5×)
5. Pathogen primer injection on null-pathogen rows
6. Loss masking verification

### Is the original raw data preserved?

Yes — `data/raw/` retains source dumps; processed datasets in `data/processed/`.

## Uses

### Has the dataset been used for any tasks?

Yes — SFT (Stages 1 + 2) + GRPO RL (Stage 3) of Lysos models on AMD MI300X.

### Are there other tasks this dataset could be used for?

- Cross-validation against TxGemma + Tx-LLM + GPT-4 zero-shot
- Benchmark for antimicrobial design models
- Source for hard-negative mining / active learning
- Reference for AMR knowledge embeddings

### Are there tasks this dataset should NOT be used for?

- **Designing chemical weapons / select agents / controlled substances** —
  the dataset includes safety refusal training; misuse explicitly prohibited.
- **Substitute for wet-lab validation** — predictions only.
- **Diagnosis or treatment recommendation in clinical settings without
  ID specialist oversight** — the dataset trains design intelligence, not
  clinical prescribing.

## Distribution

### Where is the dataset hosted?

HuggingFace Hub:
- `rahul24raj/lysos-amr-stage2-pro-v3` ... `pro-v12` (currently private)
- `rahul24raj/lysos-rl-prompts-v3` (private)
- `rahul24raj/lysos-tdc-stage1` (public)

Source code: github.com/Rahul-Rajpurohitk/lysos

### Distribution license

CC-BY-4.0 with attribution. Free for research + commercial use. Restrictions:
- **Cannot be used to train models for chemical / biological weapons design**
- Must include attribution + maintain manifest provenance

## Maintenance

### Maintainer + contact

Rahul Rajpurohit, rahulrajpurohitk@gmail.com.

### Is there an erratum?

No formal errata yet. Bug fixes tracked in commit history at
github.com/Rahul-Rajpurohitk/lysos.

### Will the dataset be updated?

Yes — versioned (pro-v3 → pro-v12 already). Updates planned post-
hackathon: live wet-lab feedback → pro-v13+.

### How can others contribute?

- Open issues at github.com/Rahul-Rajpurohitk/lysos/issues
- Pull requests welcome for: more pathogens, more sources, additional
  teacher distillation layers, eval probe additions

## Provenance

Every Lysos artifact embeds a manifest (`data/processed/MANIFEST.json`)
with:
- `git_sha` at build time
- SDK versions (rdkit, datasets, transformers, ...)
- Per-dataset content hash
- Reward stack version + component weights

Reproducibility: given (git_sha, dataset_hash, reward_stack_version), the
same input + training config will produce the same model output.

## Citation

```bibtex
@dataset{lysos2026,
  title  = {Lysos: An Antimicrobial Drug-Design Dataset},
  year   = {2026},
  author = {Rajpurohit, Rahul},
  url    = {https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2-pro-v12},
  version = {v12},
  note   = {AMD Developer Hackathon submission, lablab.ai}
}
```
