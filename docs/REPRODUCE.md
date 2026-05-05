# Reproducing Lysos

End-to-end reproduction guide: clone → install → train → eval → benchmark.

## Prerequisites

- Linux or macOS
- Python 3.13 (data prep) + Python 3.12 (AizynthFinder, in separate venv)
- ~50GB disk for datasets + models
- AMD MI300X GPU for training (Stage 1: 8x; Stages 2-3: 1x)
- HuggingFace account + API token (for dataset/model download)

## 1. Clone

```bash
git clone https://github.com/Rahul-Rajpurohitk/lysos.git
cd lysos
```

## 2. Install (Python 3.13 main venv)

```bash
python3.13 -m venv /tmp/lysos_venv
source /tmp/lysos_venv/bin/activate
pip install -r requirements.txt
```

Key dependencies:
- `rdkit` 2024.03+ — chemistry standardization
- `datasets` 4.0+ — HF datasets
- `transformers` 4.56+ — Gemma 4 + tokenization
- `peft` 0.13+ — LoRA fine-tuning
- `trl` 0.17+ — SFT + GRPO trainers
- `xgboost` 2.1+ — MIC predictor
- `accelerate` 1.1+ — distributed training

## 3. Install AizynthFinder (Python 3.12 sub-venv, optional but recommended)

```bash
brew install python@3.12  # or apt install python3.12-venv
python3.12 -m venv /tmp/aizynth_venv
source /tmp/aizynth_venv/bin/activate
pip install aizynthfinder
mkdir -p /tmp/aizynth_data
download_public_data /tmp/aizynth_data
```

## 4. Pull pre-built datasets from HuggingFace

```bash
# Fastest: pull the final pro-v11 directly
python -c "from datasets import load_dataset; ds = load_dataset('rahul24raj/lysos-amr-stage2-pro-v11'); ds.save_to_disk('data/processed/amr-stage2-pro-v11')"
python -c "from datasets import load_dataset; ds = load_dataset('rahul24raj/lysos-rl-prompts-v3'); ds.save_to_disk('data/processed/amr-rl-prompts-v3')"
```

Or rebuild from sources (longer):

```bash
# Clean chemistry corpus
python scripts/clean_chemistry_corpus.py

# Generate teacher distillation (78K traces total)
python scripts/teacher_distill_inline.py --n 5000             # chem
python scripts/teacher_distill_systems.py --n_per_category 500 # systems
python scripts/teacher_distill_architecture.py --n_per_category 500
python scripts/teacher_distill_raw_data.py --n_per_category 600
python scripts/teacher_distill_edge_and_clinical.py --n_per_category 500
python scripts/teacher_distill_targeted.py
python scripts/teacher_distill_eval_aligned.py

# Run synth-cost calibration (real route data)
/tmp/aizynth_venv/bin/python scripts/run_aizynth_priority_sweep.py
python scripts/calibrate_synth_cache.py

# Build dataset
python scripts/build_stage2_pro_v10.py
python scripts/score_data_quality.py
python scripts/build_stage2_pro_v11.py
```

## 5. Verify dataset integrity

```bash
python scripts/smoke_test_stage2_v3.py    # 11-check verification
python scripts/test_loss_masking.py        # Gemma chat template alignment
```

## 6. Train

### Stage 1: TxGemma-4 base (skip if downloading our checkpoint)

```bash
# 8x MI300X, ~6h
accelerate launch --config_file configs/accelerate_8gpu.yaml \
    scripts/train_stage1_txgemma.py \
    --config configs/stage1_txgemma4.yaml
```

Or pull our checkpoint:
```bash
huggingface-cli download rahul24raj/txgemma-4-31b
```

### Stage 2: Lysos AMR-spec SFT

```bash
# 1x MI300X, ~12h
accelerate launch --config_file configs/accelerate_1gpu.yaml \
    scripts/train_stage2_sft.py \
    --config configs/stage2_amr_sft.yaml
```

Or pull:
```bash
huggingface-cli download rahul24raj/lysos-base
```

### Stage 3: GRPO RL

```bash
# 1x MI300X, ~10h
accelerate launch --config_file configs/accelerate_1gpu.yaml \
    scripts/train_stage3_grpo.py \
    --config configs/stage3_rl_grpo.yaml
```

Or pull:
```bash
huggingface-cli download rahul24raj/lysos-rl
```

## 7. Eval

### 7-metric leaderboard

```bash
# Pre-train baseline (Gemma 4 zero-shot)
python eval/run_all.py --model google/gemma-4-31b-it --out reports/baseline.json

# Lysos-RL post-train
python eval/run_all.py --model rahul24raj/lysos-rl --out reports/lysos_rl.json

# Comparison
python eval/compare.py reports/baseline.json reports/lysos_rl.json
```

### OOD eval (Salmonella + S. pneumoniae)

```bash
python eval/ood_eval.py
python eval/run_ood.py --model rahul24raj/lysos-rl --prompts data/synthetic/agentic_ood_eval.jsonl
```

### Adversarial robustness

```bash
python eval/adversarial_eval.py
python eval/run_adversarial.py --model rahul24raj/lysos-rl --probes data/synthetic/agentic_adversarial_eval.jsonl
```

## 8. Workbench demo

```bash
# Start vLLM with Lysos-RL
docker run --gpus all rocm/vllm:latest --model rahul24raj/lysos-rl --port 8000

# Start Workbench backend
cd workspace/api
uvicorn app:app --port 8001

# Start Workbench frontend
cd ../web
npm install && npm run dev
```

Open http://localhost:5173 and try:
> "Design a candidate against MRSA"

## 9. Provenance

Every Lysos artifact embeds a manifest (`data/processed/MANIFEST.json`)
that captures:
- `git_sha` at build time
- SDK versions (rdkit, datasets, transformers, torch, ...)
- Per-dataset content hash (SHA-256 short)
- Reward stack version + component weights

To verify reproducibility:

```bash
python scripts/build_dataset_manifest.py
diff <(jq . data/processed/MANIFEST.json) <(jq . path/to/published/MANIFEST.json)
```

## 10. Known issues + workarounds

| Issue | Workaround |
|-------|-----------|
| AizynthFinder Python 3.13 incompat | Use `/tmp/aizynth_venv` with Python 3.12 |
| Boltz-2 not installed | Reward component falls back to predict_binding_affinity |
| LFS warning on long-form-traces.jsonl | Optional `git lfs install` for the synthetic dir |
| Gemma 4 access gated | Request access via HuggingFace; or use Gemma 2 27B (smaller, less capable) |

## 11. Citation

```bibtex
@article{lysos2026,
  title = {Lysos: An Antimicrobial Drug-Design System Built on Gemma 4},
  author = {Rajpurohit, Rahul},
  year = {2026},
  url = {https://github.com/Rahul-Rajpurohitk/lysos},
  note = {AMD Developer Hackathon submission, lablab.ai}
}
```

## 12. Support

- Issues: https://github.com/Rahul-Rajpurohitk/lysos/issues
- Discussions: https://huggingface.co/datasets/rahul24raj/lysos-amr-stage2-pro-v11/discussions
- Email: rahulrajpurohitk@gmail.com
