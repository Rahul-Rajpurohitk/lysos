# scripts/

One-shot operational scripts for Lysos. These are tools, not part of the library.

## What's here

| Script | Purpose | When to run |
|---|---|---|
| `smoke_test_rocm.py` | Verifies the entire training stack on AMD MI300X | **FIRST** thing on every fresh AMD Dev Cloud VM |

## Smoke test workflow

The smoke test exists to fail fast. We do NOT want to discover a missing dep or a broken ROCm install 4 hours into a Stage 1 training run that just burned $80 of GPU.

### Run on a fresh AMD Dev Cloud VM

```bash
# 1. SSH into the VM
ssh root@<vm-ip>

# 2. Clone the repo
git clone git@github.com:Rahul-Rajpurohitk/lysos.git
cd lysos

# 3. Build the Docker image (or use the pre-built rocm/pytorch base directly)
docker build -f docker/Dockerfile.rocm -t lysos:rocm .

# 4. Run the container with GPU access
docker run --rm -it \
  --device=/dev/kfd --device=/dev/dri \
  --group-add render --group-add video \
  --ipc=host --network=host --privileged \
  --cap-add=CAP_SYS_ADMIN --security-opt seccomp=unconfined \
  -e HF_TOKEN=$HF_TOKEN \
  -v $(pwd):/workspace -w /workspace \
  lysos:rocm bash

# 5. Inside the container, run the smoke test
python scripts/smoke_test_rocm.py
```

### What the smoke test checks

1. **rocm-smi** reports an MI300-class GPU
2. **PyTorch** is built against ROCm/HIP and `torch.cuda.is_available()` returns True
3. **GPU compute** — a small BF16 matmul completes without NaN
4. **transformers** imports cleanly
5. **PEFT + TRL + accelerate + datasets** all importable (training stack)
6. **RDKit** can parse SMILES + compute descriptors (chemistry stack)
7. **PyTDC** importable (TDC dataset interface for Stage 1)
8. **HF_TOKEN** is set (needed for gated Gemma 4 weights)
9. **optimum** importable (Flash Attention 2 on ROCm)
10. **Gemma 4 tokenizer** loads (verifies HF auth + access to the model)

If any check fails, fix it before kicking off any real training run.

### Expected runtime

< 5 minutes on a single MI300X (mostly waiting for `transformers` first-import + Gemma 4 tokenizer download).

## Future scripts (planned)

- `prepare_amr_data.py` — Download + clean ChEMBL antibiotic subset, DBAASP AMPs, APD3, DRAMP, CARD targets. Output Parquet files for Stage 2.
- `prepare_tdc_data.py` — Pull and instruction-format the ~70 TDC tasks for Stage 1.
- `eval_lysos.py` — Run the held-out AMR benchmark.
- `push_models_to_hub.py` — Push trained checkpoints to HF Hub with model cards.
- `generate_demo_assets.py` — Pre-render starter targets + cached generations for the workspace UI.
