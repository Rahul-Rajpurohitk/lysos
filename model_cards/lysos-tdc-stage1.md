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
  - therapeutics
  - drug-design
  - admet
  - tox
  - hts
  - tdc
  - instruction-tuning
  - chemistry
---

# lysos-tdc-stage1

A 151,530-example instruction-tuning dataset for chemistry foundation training,
built from the [Therapeutics Data Commons (TDC)](https://tdcommons.ai/) suite
of public ADMET, toxicity, and high-throughput-screening tasks.

This is **Stage 1** of the [Lysos](https://github.com/Rahul-Rajpurohitk/lysos)
training pipeline — used to teach the base Gemma 4 model the general chemistry
prior before AMR specialization in Stage 2.

## Splits

| Split | Rows |
|---|---|
| train | 106,070 |
| valid | 15,153 |
| test | 30,307 |
| **Total** | **151,530** |

## Source tasks (28)

### ADME (20 tasks)

Caco2_Wang · HIA_Hou · Pgp_Broccatelli · Bioavailability_Ma ·
Lipophilicity_AstraZeneca · Solubility_AqSolDB · BBB_Martins · PPBR_AZ ·
VDss_Lombardo · CYP2C19_Veith · CYP2D6_Veith · CYP3A4_Veith · CYP1A2_Veith ·
CYP2C9_Veith · CYP2C9_Substrate_CarbonMangels ·
CYP2D6_Substrate_CarbonMangels · CYP3A4_Substrate_CarbonMangels ·
Half_Life_Obach · Clearance_Hepatocyte_AZ · Clearance_Microsome_AZ

### Tox (8 tasks)

hERG · AMES · DILI · Skin_Reaction · Carcinogens_Lagunin · ClinTox ·
LD50_Zhu · Tox21

### HTS (3 tasks)

HIV · SARSCoV2_Vitro_Touret · SARSCoV2_3CLPro_Diamond

## Format

Each example follows the Gemma 4 chat template:

```json
{
  "task": "BBB_Martins",
  "group": "adme",
  "split": "train",
  "prompt": "Instructions: ...\nContext: The blood-brain barrier (BBB) blocks ...\nQuestion: Will the following drug cross the blood-brain barrier? Answer with Yes or No.\nDrug SMILES: <SMILES>",
  "response": "Yes",
  "messages": "[{\"role\": \"user\", \"content\": \"...\"}, {\"role\": \"assistant\", \"content\": \"Yes\"}]"
}
```

## How it was built

```bash
pip install PyTDC>=1.1.0
python scripts/prepare_tdc_data.py --groups adme,tox,hts
```

PyTDC handles the task downloads from Harvard Dataverse + Zenodo. The script
formats each task as instruction/response with a brief task-specific context,
following Google's TxGemma prompt style.

## Used by

- [`rahul24raj/txgemma-4-31b`](https://huggingface.co/rahul24raj/txgemma-4-31b) —
  Gemma 4 31B-it after Stage 1 (chemistry foundation).
- [`rahul24raj/lysos-base`](https://huggingface.co/rahul24raj/lysos-base) —
  same model after Stage 2 AMR specialization.
- [`rahul24raj/lysos-rl`](https://huggingface.co/rahul24raj/lysos-rl) —
  final Stage 3 RL-tuned model.

## Citation

```bibtex
@software{rajpurohit_lysos_2026,
  author = {Rajpurohit, Rahul},
  title  = {Lysos: An open-source generative drug designer for antimicrobial resistance},
  year   = {2026},
  url    = {https://github.com/Rahul-Rajpurohitk/lysos}
}

@article{huang2021tdc,
  title={Therapeutics Data Commons: Machine Learning Datasets and Tasks for Drug Discovery and Development},
  author={Huang, Kexin and Fu, Tianfan and Gao, Wenhao and Zhao, Yue and Roohani, Yusuf and Leskovec, Jure and Coley, Connor W and Xiao, Cao and Sun, Jimeng and Zitnik, Marinka},
  journal={NeurIPS Datasets and Benchmarks Track},
  year={2021}
}
```
