# AMD MI300X / ROCm Gotchas — pinned versions and known traps

Written from the ground up for Lysos's training pipeline so we don't
discover these on the VM at $24/h. Pin versions tight; verify each on
boot via `scripts/vm_bootstrap.sh` and `scripts/preflight_check.py`.

## 1. ROCm version pin

**Use ROCm 6.2** on AMD Developer Cloud (their preinstalled stack as
of May 2026). Avoid 6.0 (older PyTorch wheels), avoid 6.3 (PyTorch wheel
not always synced).

Detect via:

```bash
rocm-smi --version
# expected: ROCm version: 6.2.x
```

If the host VM has a different version, the pip install must use the
matching wheel index (`https://download.pytorch.org/whl/rocm{X}.{Y}`).

## 2. PyTorch + ROCm wheel install

Don't use the default PyPI wheel — it's CUDA-only. The ROCm wheel is
larger (~2 GB) but is what actually targets MI300X.

```bash
pip install torch==2.5.1 torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/rocm6.2
```

Verify:

```python
import torch
assert torch.cuda.is_available()
assert torch.version.hip is not None  # only set on ROCm builds
print(torch.cuda.get_device_name(0))   # should print "AMD Instinct MI300X"
print(torch.cuda.get_device_properties(0).total_memory / 1e9)  # ~191 GB
```

If `torch.version.hip is None` you're on the CUDA build by accident —
reinstall.

## 3. flash-attn-2 on ROCm

The official `flash-attn` PyPI package is CUDA-only. ROCm needs the AMD
fork:

```bash
# Build from source (no precompiled wheel for MI300X yet as of May 2026)
git clone --branch rocm_6.2 https://github.com/ROCm/flash-attention.git
cd flash-attention
GPU_ARCHS="gfx942" python setup.py install   # gfx942 = MI300X
```

Build time: ~30 min on the VM. Cache the resulting .whl in our
data/cache/ to avoid rebuilding on every VM rotation.

If flash-attn-2 build fails (it's brittle on ROCm), fall back to:

```yaml
# configs/stage*.yaml
model:
  attn_impl: sdpa   # PyTorch native scaled-dot-product attention
                     # ~10-15% slower than flash-attn-2 but ROCm-stable
```

`sdpa` is what the configs already default to via the `attn_impl` field
— upgrading to `flash_attention_2` is opt-in.

## 4. bitsandbytes-rocm

The default `bitsandbytes` PyPI package targets CUDA. For ROCm you need
the AMD fork:

```bash
pip install bitsandbytes-rocm
# OR build from source if pre-built wheel missing for the running Python
```

Lysos uses bitsandbytes only for 8-bit optimizer states (Stage 1 ZeRO-3
offload). If install fails on the VM:

```yaml
# configs/stage1_txgemma4.yaml
training:
  optim: adamw_torch     # was: paged_adamw_8bit
                          # adamw_torch uses 4x more optimizer-state memory
                          # but works without bitsandbytes entirely
```

The DeepSpeed ZeRO-3 CPU offload (configured in
`configs/accelerate_8gpu_zero3.yaml`) covers most of the optimizer-state
pressure. We can ship Stage 1 with `adamw_torch` if bitsandbytes is
flaky on the VM.

## 5. RCCL vs NCCL

PyTorch's `torch.distributed` works the same on AMD as on NVIDIA, but
the underlying collective library is RCCL not NCCL. The env var name is
the same:

```bash
export NCCL_DEBUG=INFO   # works on RCCL too — same env name
```

But if RCCL falls back to TCP (instead of using the InfiniBand /
RoCE fabric), you'll see ~10x slowdown. Check via:

```bash
# After accelerate launch, the log should show:
#   RCCL INFO Init: NET/Plugin/RoCE
# If it says NET/Socket, it's using TCP — slow.
```

Set `NCCL_IB_DISABLE=0` (the default) and verify the pod has IB.

## 6. DeepSpeed ZeRO-3 quirks

- `zero3_save_16bit_model: true` — without this, every checkpoint
  rehydrates to FP32 and is 2× larger on disk.
- `zero3_init_flag: true` — required so the 31B model loads
  shard-by-shard. Without it, Pod OOMs on `from_pretrained`.
- `offload_optimizer_device: cpu` — saves ~30 GB of GPU memory at the
  cost of 10-15% step throughput. Worth it on Stage 1 (8x = lots of
  CPU RAM).
- `stage3_gather_16bit_weights_on_model_save: true` — required for the
  `trainer.save_model()` call to work without OOM.

These are all set in `configs/accelerate_8gpu_zero3.yaml`. Validated by
`scripts/validate_deepspeed.py` (L1 schema check).

## 7. HBM3 memory pressure

MI300X has 192 GB HBM3, but the actual usable amount depends on:

- Reserved by the driver (~6-8 GB)
- Reserved by the runtime (~2 GB)
- Effective usable: ~180-184 GB

Stage 3 GRPO holds:
- Policy (BF16): ~62 GB
- Reference (BF16): ~62 GB (TRL 1.x materializes from beta)
- Activations + grads: ~20-30 GB
- KV cache for G generations: ~10-15 GB
- DeepSpeed/optim overhead: ~10-15 GB

Total: ~165-185 GB. **One MI300X is just barely enough.** Watch
`nvidia-smi` style via `rocm-smi --showmeminfo vram` and abort if util > 95%.

## 8. Gradient checkpointing on ROCm

`gradient_checkpointing=True` works on ROCm but use `use_reentrant=False`
explicitly:

```python
model.gradient_checkpointing_enable(
    gradient_checkpointing_kwargs={"use_reentrant": False}
)
```

The reentrant version has known correctness issues with PEFT on ROCm
6.x. We do this in `src/training/sft_runner.py` and
`src/training/stage3_rl_grpo.py`.

## 9. Tokenizer fast-path

`AutoTokenizer.from_pretrained(..., use_fast=True)` is required on
ROCm — the slow tokenizer path has thread-safety issues in some
PEFT/Accelerate combos. We default to fast everywhere.

## 10. HF_HUB_ENABLE_HF_TRANSFER

Set this to 1 to use the `hf-transfer` Rust binary for parallelized
multipart downloads. Cuts Gemma 4 31B (~62 GB) download from ~30 min
to ~10 min.

```bash
export HF_HUB_ENABLE_HF_TRANSFER=1
```

Already in our `.env` template and `vm_bootstrap.sh`. `pip install` of
`hf_xet` provides the binary.

## 11. CPU RAM headroom

The MI300X VM also has ~1.4 TB of CPU RAM. ZeRO-3 optimizer offload
uses this aggressively (Stage 1: 8 × ~30 GB = 240 GB optimizer state on
CPU). Ensure no other heavy processes (e.g., a forgotten Jupyter
kernel) are eating CPU RAM:

```bash
free -h | head -3
# expected: 1.4T total, 1.0T+ available
```

## 12. Persistent storage

AMD Dev Cloud Small instances have ~500 GB local NVMe. We need:
- ~62 GB Gemma 4 weights
- ~5 GB EmbeddingGemma
- ~30 GB datasets (pro-v12 + rl-prompts + tdc)
- ~10 GB checkpoints per stage × 4 stages = 40 GB
- ~10 GB pip cache + system

Total: ~150 GB. Comfortable. The Large 8x instance has ~2 TB local.

`scripts/disk_monitor.py` logs free space to wandb every step; abort if
< 10 GB.

## 13. Hugging Face rate limits + Pro

Without HF Pro, model + dataset downloads cap at ~50 MB/s. With Pro,
parallel-multipart hits ~500 MB/s. Lysos runs use Pro (rahul24raj
account). Verified in `scripts/verify_keys.py:check_hf` (`isPro=True`).

## 14. Recovery from VM crash mid-training

ROCm's host driver occasionally panics (~1% of long runs). When it
does:

1. The training process dies with a CUDA / HIP error.
2. `scripts/checkpoint_resilience.py` retries up to 3× with backoff.
3. If local checkpoint is corrupted, `--allow_hub_recovery` pulls the
   last pushed checkpoint from HF Hub (we push every 200 steps via
   `push_strategy: checkpoint`).
4. If the VM itself reboots, SSH back in and re-run
   `bash scripts/run_training_pipeline.sh stage<N>`.

## 15. Cost

| GPU class           | Current rate (May 2026) |
|---------------------|--------------------------|
| MI300X Small (1×)   | $3/h                     |
| MI300X Large (8×)   | $24/h                    |

Verified via the Cost callback's hard-stop logic
(`src/training/cost_callback.py`). LYSOS_BUDGET_USD=300 default,
`hard_stop=True` aborts training if projected total >315.

## Quick verification (run on the VM after bootstrap)

```bash
python -c "
import torch, sys
print('torch', torch.__version__)
print('hip ', torch.version.hip)
print('cuda available', torch.cuda.is_available())
print('device', torch.cuda.get_device_name(0))
print('mem (GB)', torch.cuda.get_device_properties(0).total_memory / 1e9)
sys.exit(0 if torch.version.hip else 1)
"
```

If exit=0 and you see "AMD Instinct MI300X" + ~191 GB, you're cleared.
If exit=1, you're on a CUDA wheel — reinstall with the ROCm index.
