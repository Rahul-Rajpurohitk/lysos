#!/usr/bin/env bash
# Lysos — one-shot VM bootstrap on AMD Developer Cloud.
#
# Run this on a fresh AMD MI300X VM to get from zero to "ready to train".
# Idempotent — safe to re-run after partial failures.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/Rahul-Rajpurohitk/lysos/main/scripts/vm_bootstrap.sh | bash
#   # OR after cloning the repo:
#   bash scripts/vm_bootstrap.sh
#
# What it does (in order):
#   1. Verify ROCm / MI300X visible to userspace
#   2. Clone or update the Lysos repo at ~/lysos
#   3. Install Python deps (pyproject.toml editable + sentence-transformers)
#   4. Pre-warm HF cache: Gemma 4 31B-it + EmbeddingGemma 300m
#   5. Run smoke tests: verify_loaders + smoke_test_rocm
#   6. Pull the live HF datasets to local data/processed/
#   7. Print "next steps" with the exact training command

set -euo pipefail

REPO_DIR="${LYSOS_HOME:-$HOME/lysos}"
REPO_URL="${LYSOS_REPO_URL:-https://github.com/Rahul-Rajpurohitk/lysos.git}"
LOG_PREFIX="\033[1;36m[lysos]\033[0m"

log()  { printf "%b %s\n" "$LOG_PREFIX" "$*"; }
fail() { printf "\033[1;31m[lysos] FAIL\033[0m %s\n" "$*" >&2; exit 1; }

# ---- 1. ROCm check ----
log "step 1/7 · checking ROCm"
if command -v rocm-smi >/dev/null 2>&1; then
    rocm-smi --showproductname --showmeminfo vram | head -20 || true
else
    fail "rocm-smi not found. Are we on an AMD GPU host? (expected ROCm 6.x preinstalled)"
fi

# ---- 2. Repo ----
log "step 2/7 · clone / update repo at $REPO_DIR"
if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" fetch --all --quiet
    git -C "$REPO_DIR" reset --hard origin/main
else
    git clone --depth=1 "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

# ---- 3. Python deps ----
log "step 3/7 · install Python deps"
python3 -m pip install --upgrade --quiet pip
python3 -m pip install --quiet -e .
python3 -m pip install --quiet \
    sentence-transformers \
    datasets \
    pyarrow \
    xgboost \
    joblib \
    accelerate \
    peft \
    trl \
    wandb \
    "trl>=0.11" \
    bitsandbytes 2>/dev/null || log "  (warn) bitsandbytes optional; pip may have skipped"

# ---- 3.5. Live key validation (BEFORE downloading 60GB of model weights) ----
log "step 3.5/7 · verifying API keys (HF + Gemini + WANDB)"
python3 scripts/verify_keys.py
case $? in
    0) log "  ✓ all keys live" ;;
    2) log "  (warn) recommended keys missing — training runs degraded" ;;
    *) fail "REQUIRED key missing/invalid. Fix .env or export, then re-run." ;;
esac

# ---- 4. Pre-warm HF cache ----
log "step 4/7 · pre-warming HF cache (Gemma 4 + EmbeddingGemma)"
if [ -z "${HF_TOKEN:-}" ]; then
    log "  (warn) HF_TOKEN not set — gated models will fail. Set with: export HF_TOKEN=hf_..."
fi
python3 - <<'PY'
import os
import logging
logging.getLogger("transformers").setLevel(logging.WARNING)
print("  - downloading google/embeddinggemma-300m ...")
try:
    from sentence_transformers import SentenceTransformer
    SentenceTransformer("google/embeddinggemma-300m")
    print("    ✓ EmbeddingGemma cached")
except Exception as e:
    print(f"    ✗ EmbeddingGemma failed: {e}")

print("  - downloading google/gemma-4-31B-it (will take ~10 min on first pull) ...")
try:
    from huggingface_hub import snapshot_download
    snapshot_download("google/gemma-4-31B-it", allow_patterns=["*.json", "*.safetensors"])
    print("    ✓ Gemma 4 31B-it cached")
except Exception as e:
    print(f"    ✗ Gemma 4 failed: {e}")
PY

# ---- 5. Smoke tests ----
log "step 5/7 · running smoke tests"
python3 scripts/verify_loaders.py
python3 scripts/smoke_test_rocm.py || log "  (warn) ROCm smoke test reported issues — review above"

# ---- 6. Pull live datasets (pro-v12 + rl-prompts-v3 + tdc + reward caches) ----
log "step 6/7 · pulling live HF datasets"
python3 - <<'PY'
from datasets import load_dataset
print("  - rahul24raj/lysos-amr-stage2-pro-v12 (Stage 2 SFT corpus, 380K rows) ...")
load_dataset("rahul24raj/lysos-amr-stage2-pro-v12")
print("    ✓")
print("  - rahul24raj/lysos-rl-prompts-v3 (Stage 3 RL prompts, 12K) ...")
load_dataset("rahul24raj/lysos-rl-prompts-v3")
print("    ✓")
print("  - rahul24raj/lysos-tdc-stage1 (Stage 1 TDC ADMET corpus, 151K rows) ...")
load_dataset("rahul24raj/lysos-tdc-stage1")
print("    ✓")
PY

log "step 6.5/7 · downloading reward caches (synth + boltz proxy)"
mkdir -p data/processed
# These are small (<10MB each); shipped via git-lfs from the repo
ls data/processed/synth_calibration_cache.parquet 2>/dev/null \
    && echo "  ✓ synth_calibration_cache present" \
    || echo "  (warn) synth_calibration_cache missing — run scripts/calibrate_synth_cache.py"
ls data/processed/boltz2_poses_cache.parquet 2>/dev/null \
    && echo "  ✓ boltz2_poses_cache present" \
    || echo "  (warn) boltz2_poses_cache missing — run scripts/calibrate_boltz_proxy.py"
ls data/processed/aizynth_calibration_cache.parquet 2>/dev/null \
    && echo "  ✓ aizynth_calibration_cache present" \
    || echo "  (warn) aizynth cache missing — synthesizability reward will use SAscore fallback"

# ---- 7. next steps ----
log "step 7/7 · ready to train"
cat <<'EOF'

================================================================
 Lysos — bootstrap complete
================================================================
 Next:

   # Stage 1 (TxGemma-4 base) — needs Large 8x MI300X
   python -m src.training.stage1_txgemma4 --config configs/stage1_txgemma4.yaml

   # Stage 2 (AMR SFT) — Small 1x MI300X is plenty
   python -m src.training.stage2_amr_sft --config configs/stage2_amr_sft.yaml

   # Stage 3 (GRPO RL) — needs Small 1x MI300X
   python -m src.training.stage3_rl_grpo --config configs/stage3_rl_grpo.yaml

   # Workspace demo (HF Space-deployable)
   make api-dev

================================================================
EOF
