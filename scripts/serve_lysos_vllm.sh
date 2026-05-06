#!/usr/bin/env bash
# serve_lysos_vllm.sh — boot vLLM serving Gemma 4 31B + Lysos LoRA adapters.
#
# Run on the AMD MI300X VM (inside the rocm container) AFTER training completes.
# Exposes an OpenAI-compatible chat-completions endpoint that the workspace
# FastAPI server (LYSOS_INFERENCE_URL) hits.
#
# Usage:
#   bash scripts/serve_lysos_vllm.sh                 # serves the latest stage's adapter
#   bash scripts/serve_lysos_vllm.sh --stage 2       # forces Stage 2 adapter
#   bash scripts/serve_lysos_vllm.sh --port 8001     # alt port
#   bash scripts/serve_lysos_vllm.sh --hub           # pull adapter from HF Hub
#                                                    # instead of local checkpoint
#
# Tier strategy:
#   - Stage 3 adapter is the production model (RL-aligned).
#   - Stage 2.5 / Stage 2 / Stage 1 adapters are useful for ablation comparisons.
#   - The server merges the LoRA into the base before serving so inference is
#     fast (no LoRA-aware kernel overhead).

set -euo pipefail

# Defaults
STAGE=auto      # auto = pick latest available
PORT=8000
SOURCE=local    # local | hub
MAX_MODEL_LEN=8192
GPU_MEMORY_UTIL=0.92

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stage)   STAGE="$2"; shift 2 ;;
        --port)    PORT="$2"; shift 2 ;;
        --hub)     SOURCE=hub; shift ;;
        --gpu-util) GPU_MEMORY_UTIL="$2"; shift 2 ;;
        --max-len) MAX_MODEL_LEN="$2"; shift 2 ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1"; exit 1 ;;
    esac
done

# ---------- Resolve adapter ----------
declare -A LOCAL_PATHS=(
    [1]="./checkpoints/stage1-txgemma4"
    [2]="./checkpoints/stage2-amr-sft"
    [2.5]="./checkpoints/stage2_5-dpo"
    [3]="./checkpoints/stage3-rl-grpo"
)
declare -A HUB_IDS=(
    [1]="rahul24raj/txgemma-4-31b"
    [2]="rahul24raj/lysos-base"
    [2.5]="rahul24raj/lysos-base-dpo"
    [3]="rahul24raj/lysos-rl"
)

if [[ "$STAGE" == "auto" ]]; then
    for s in 3 2.5 2 1; do
        if [[ "$SOURCE" == "local" ]] && [[ -d "${LOCAL_PATHS[$s]}" ]]; then
            STAGE=$s; break
        fi
    done
    if [[ "$STAGE" == "auto" ]]; then
        echo "FATAL: no local adapter found. Train first, or use --hub." >&2
        exit 2
    fi
fi

if [[ "$SOURCE" == "local" ]]; then
    ADAPTER_PATH="${LOCAL_PATHS[$STAGE]}"
    if [[ ! -d "$ADAPTER_PATH" ]]; then
        echo "FATAL: local adapter $ADAPTER_PATH not found." >&2
        exit 3
    fi
else
    ADAPTER_PATH="${HUB_IDS[$STAGE]}"
fi

BASE_MODEL="google/gemma-4-31B-it"

echo "============================================================"
echo "  vLLM serve — Lysos Stage $STAGE"
echo "============================================================"
echo "  base   : $BASE_MODEL"
echo "  adapter: $ADAPTER_PATH ($SOURCE)"
echo "  port   : $PORT"
echo "  max_len: $MAX_MODEL_LEN"
echo "  gpu_mem: $GPU_MEMORY_UTIL"
echo

# ---------- Install vLLM if missing ----------
if ! python3 -c "import vllm" 2>/dev/null; then
    echo "[install] vllm not found — installing for ROCm..."
    pip install -q vllm 2>&1 | tail -5
fi

# ---------- Boot ----------
# vLLM auto-merges LoRA when --enable-lora is set with --lora-modules.
# Single-adapter case = simpler: serve as a merged model.
exec python3 -m vllm.entrypoints.openai.api_server \
    --model "$BASE_MODEL" \
    --enable-lora \
    --lora-modules lysos="$ADAPTER_PATH" \
    --max-lora-rank 128 \
    --port "$PORT" \
    --host 0.0.0.0 \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_MEMORY_UTIL" \
    --dtype bfloat16 \
    --trust-remote-code \
    --served-model-name lysos-stage${STAGE}
