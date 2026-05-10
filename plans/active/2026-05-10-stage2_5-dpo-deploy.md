# Deploy Stage 2.5 DPO training to AMD MI300X VM (lysos-vm)

## Context

GRPO failed in earlier training, so we're falling back to the prepared
Stage 2.5 DPO alignment phase. The lysos-vm AMD droplet was killed and
just got powered back on (165.245.141.167, 1× MI300X, ROCm 7.0,
Ubuntu 24.04, 192GB) — but the disk was reset, so we need a full
bootstrap. HF token + wandb netrc were copied over before an
auto-reboot (kernel security update), then the connection dropped
mid-`.env` scp. SSH is back up now (uptime ~2min after re-boot).

Goal: bootstrap the VM, run Stage 2.5 DPO (`configs/stage2_5_dpo.yaml`,
~30–60min on 10K hard-negative pairs at 1× MI300X), and push the
merged DPO adapter to `rahul24raj/lysos-base-dpo` (private) on HF Hub.
The HF Space + final agent stack already point at this model id, so
once the push completes the agent backend will pick it up.

## Critical files / scripts (all already in repo, reuse)

| Path | Role |
|---|---|
| `configs/stage2_5_dpo.yaml` | DPO config — loads `rahul24raj/lysos-base` as ref, trains LoRA r=32 on `data/processed/lysos-hard-negatives-v1.parquet`, pushes to `rahul24raj/lysos-base-dpo` every 100 steps |
| `scripts/vm_bootstrap.sh` | Idempotent VM bootstrap — ROCm check, repo clone/update, pyproject editable install, HF cache prewarm, smoke tests |
| `scripts/run_training_pipeline.sh` | Multi-stage trainer (Stage 2 → 2.5 → 3) — invokes the Stage 2.5 path for DPO |
| `scripts/verify_keys.py` | Required-vs-recommended key sanity check (live API ping per key) |
| `scripts/vm_status.sh lysos-vm` | Snapshot: tmux tail, GPU util, HF checkpoint sizes, wandb run state, disk |
| `scripts/vm_tail.sh lysos-vm` | Live tail of the training tmux session |

Hard-negatives parquet is **already on HF** as `rahul24raj/lysos-hard-negatives-v1` (vm_bootstrap.sh pulls it via `huggingface-cli` to `data/processed/`).

## Current VM state (audited 2026-05-10)

- ✅ SSH up — `ssh lysos-vm` → root, kernel 6.8, hostname `2`
- ✅ MI300X visible (`Card Series: AMD Instinct MI300X VF`)
- ✅ Disk: 421G free of 697G
- ✅ `~/.cache/huggingface/token` (37 bytes, mode 600)
- ✅ `~/.netrc` (132 bytes, mode 600, wandb entry)
- ❌ `~/lysos/.env` — scp interrupted by reboot, **must re-ship**
- ❌ Repo not cloned
- ❌ No HF model cache
- ❌ No Python venv / deps

## Approach (incremental, monitorable)

Driven by sequenced SSH calls — incremental so any failure surfaces
before sinking time into a long step. Each step has a clear pass/fail.

### Step 1 — re-ship `.env` (lost in reboot)
```bash
scp -q /Users/rahulrajpurohit/IdeaProjects/lysos/.env lysos-vm:/tmp/.env_lysos
ssh lysos-vm 'mkdir -p ~/lysos && mv /tmp/.env_lysos ~/lysos/.env && chmod 600 ~/lysos/.env'
```
Verify: `ssh lysos-vm 'grep -c GEMINI_API_KEY ~/lysos/.env'` returns ≥1.

### Step 2 — clone repo + run vm_bootstrap.sh
```bash
ssh lysos-vm 'curl -sSL https://raw.githubusercontent.com/Rahul-Rajpurohitk/lysos/main/scripts/vm_bootstrap.sh | bash'
```
This script will:
- ROCm check (rocm-smi --showproductname)
- `git clone https://github.com/Rahul-Rajpurohitk/lysos.git ~/lysos` (uses our latest pushes including champion table, knowledge brief, etc.)
- `pip install -e .` from pyproject (~3-5min)
- Install `sentence-transformers` separately
- Prewarm Gemma 4 31B-it cache (~15min on HF Pro endpoints, 62GB)
- Smoke: `verify_loaders.py` + `smoke_test_rocm.py`
- Pull HF datasets to `data/processed/`

Pass: bootstrap exits 0 + prints "ready to train".

### Step 3 — verify keys
```bash
ssh lysos-vm 'cd ~/lysos && set -a && source .env && python3 scripts/verify_keys.py'
```
Pass: exit 0 (or exit 2 with only optional/recommended warnings).

### Step 4 — launch Stage 2.5 DPO in detached tmux
```bash
ssh lysos-vm 'cd ~/lysos && set -a && source .env && tmux new-session -d -s lysos \
  "bash scripts/run_training_pipeline.sh --stage 2.5 --config configs/stage2_5_dpo.yaml 2>&1 | tee logs/stage2_5_dpo_$(date +%Y%m%d_%H%M).log"'
```
The DPO config has `push_to_hub: true` + `push_strategy: checkpoint` + `save_steps: 100`, so an HF checkpoint lands every ~100 steps. Total: 1 epoch over 10K pairs at effective batch 16 = ~625 steps ≈ 30–60 min.

### Step 5 — monitor
```bash
bash scripts/vm_status.sh lysos-vm        # one-shot snapshot
bash scripts/vm_tail.sh lysos-vm          # live tmux tail
```
Watch for: DPO loss decreasing, `pushing checkpoint` log lines, HF endpoint `rahul24raj/lysos-base-dpo` populating.

### Step 6 — final push + verification
On training completion, the script auto-pushes the final merged adapter
to `rahul24raj/lysos-base-dpo` (private). Verify:
```bash
huggingface-cli repo info rahul24raj/lysos-base-dpo --type model
# Should show 1+ commit, adapter_model.safetensors present
```

The agent backend at `workspace/api/agent.py` already routes through the
Lysos model id env var — once HF has the artifact, the local agent will
pick it up on next backend restart.

## Risk & mitigation

| Risk | Mitigation |
|---|---|
| Gemma 4 prewarm fails (62GB) | vm_bootstrap.sh exits non-zero; we retry with `huggingface-cli download google/gemma-4-31b-it --resume`. HF Pro endpoint accelerates. |
| MI300X OOM at 4096 max-length | Config already uses `gradient_checkpointing: true` + per-device batch 2. Fall back to `max_length: 2048` if seen. |
| HF push 401 | Verify `~/.cache/huggingface/token` has write scope — re-token via `huggingface-cli login` if needed. |
| Auto-reboot mid-training | Train log + checkpoints auto-resume from latest HF checkpoint. tmux re-launch just re-runs the same command. |
| Wandb fails to attach | Recommended-only; training proceeds. We re-attach via `setup_wandb_dashboard.py` post-hoc. |

## Verification end-to-end

1. `ssh lysos-vm 'rocm-smi'` — MI300X showing >80% utilization during step
2. `bash scripts/vm_tail.sh lysos-vm | head -30` — DPO loss trending down (typical curve: 0.69 → 0.4-0.5 over ~600 steps)
3. `huggingface-cli repo info rahul24raj/lysos-base-dpo --type model` — adapter file present, ≤500MB
4. Wandb run page — `lysos-amr-stage2-pro-v11` workspace, run name `stage2_5-dpo-lysos-base-dpo`, `train/loss` chart visible
5. Pull the adapter locally + run a smoke generation:
   ```bash
   python3 -c "from transformers import AutoModelForCausalLM; m = AutoModelForCausalLM.from_pretrained('rahul24raj/lysos-base-dpo'); print('ok')"
   ```

## Out of scope (do NOT do in this run)

- Stage 3 (GRPO/PPO RL) — that's a separate, longer run; skipped because GRPO already failed once
- HF Space deploy — done separately via `deploy_to_hf_space.py` after we have the model live
- vLLM serving — done separately via `serve_lysos_vllm.sh`
- Deploying any of the workbench frontend/backend changes from this session — that's already pushed to GitHub main and will auto-pull on the local app, no VM involvement
