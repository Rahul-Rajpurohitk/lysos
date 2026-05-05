#!/usr/bin/env bash
# run_full_pipeline.sh — fire the entire Lysos training pipeline end-to-end.
#
# Designed for a fresh AMD MI300X VM after `bash scripts/vm_bootstrap.sh`.
# Stops on first non-zero. Logs each stage to logs/<stage>.<utc>.log.
#
# Stages:
#   1. Stage 1 — TxGemma chemistry foundation (8x MI300X recommended)
#   2. Stage 2 — AMR specialization SFT (1x MI300X)
#   3. Mine hard negatives — uses the Stage 2 model to make Pareto-trap pairs
#   4. Stage 2.5 — DPO alignment on the mined pairs
#   5. Stage 3 — GRPO RL with the 12-component verifiable reward stack
#
# Usage:
#   bash scripts/run_full_pipeline.sh            # full pipeline
#   bash scripts/run_full_pipeline.sh --skip-1   # if Stage 1 already pushed
#   bash scripts/run_full_pipeline.sh --start-from stage2_5
#   bash scripts/run_full_pipeline.sh --smoke    # smoke-test every stage
#   bash scripts/run_full_pipeline.sh --dry-run  # print configs, no training
#
# Exit codes:
#   0 = all stages succeeded + pushed to HF
#   1 = setup error (missing env, bad config)
#   2 = a training stage failed
#   3 = mining failed
#   4 = HF push failed (local checkpoint preserved)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ---------- args ----------
SKIP_STAGES=()
START_FROM=""
SMOKE=0
DRY_RUN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-1) SKIP_STAGES+=("1"); shift ;;
        --skip-2) SKIP_STAGES+=("2"); shift ;;
        --skip-mine) SKIP_STAGES+=("mine"); shift ;;
        --skip-2_5) SKIP_STAGES+=("2_5"); shift ;;
        --skip-3) SKIP_STAGES+=("3"); shift ;;
        --start-from) START_FROM="$2"; shift 2 ;;
        --smoke) SMOKE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

# ---------- env ----------
mkdir -p logs
UTC=$(date -u +%Y%m%dT%H%M%SZ)

# Resolve credentials with the same priority verify_keys.py uses:
#   .env -> ~/.cache/huggingface/token (HF) -> ~/.netrc (WANDB)
# This is robust to .env having empty values and to credentials living in
# their canonical CLI-provisioned cache locations.
eval "$(python3 -c '
import os
from pathlib import Path

ROOT = Path.cwd()

# 1. .env (only fills keys not already in env)
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip("\"").strip("\x27")
        if k and v and k not in os.environ:
            os.environ[k] = v

# 2. HF token from ~/.cache/huggingface/token
if not os.environ.get("HF_TOKEN"):
    for p in (Path.home()/".cache/huggingface/token", Path.home()/".huggingface/token"):
        if p.exists():
            t = p.read_text().strip()
            if t:
                os.environ["HF_TOKEN"] = t
                break

# 3. WANDB key from ~/.netrc
if not os.environ.get("WANDB_API_KEY"):
    nrc = Path.home()/".netrc"
    if nrc.exists():
        in_block = False
        for line in nrc.read_text().splitlines():
            s = line.strip()
            if s.startswith("machine "):
                in_block = "api.wandb.ai" in s
            elif in_block and s.startswith("password "):
                t = s.split(None,1)[1].strip()
                if t:
                    os.environ["WANDB_API_KEY"] = t
                    break

# Emit only the keys we actually want, properly escaped for eval
import shlex
for k in ("HF_TOKEN","WANDB_API_KEY","GEMINI_API_KEY","GOOGLE_API_KEY",
         "OPENAI_API_KEY","ANTHROPIC_API_KEY"):
    v = os.environ.get(k, "")
    if v:
        print(f"export {k}={shlex.quote(v)}")
')"

if [[ -z "${HF_TOKEN:-}" ]]; then
    echo "FATAL: HF_TOKEN not resolvable from .env, ~/.cache/huggingface/token, or env." >&2
    echo "       Run: huggingface-cli login" >&2
    exit 1
fi
if [[ -z "${WANDB_API_KEY:-}" ]]; then
    echo "WARN: WANDB_API_KEY missing — wandb logging will skip. Run: wandb login"
fi
echo "[ok] credentials: HF=set WANDB=$([[ -n "${WANDB_API_KEY:-}" ]] && echo set || echo skip) GEMINI=$([[ -n "${GEMINI_API_KEY:-}" ]] && echo set || echo skip)"

# ---------- helpers ----------
should_run() {
    local stage="$1"
    if [[ -n "$START_FROM" ]]; then
        case "$START_FROM:$stage" in
            stage1:*) ;;
            stage2:1) return 1 ;;
            mine:1|mine:2) return 1 ;;
            stage2_5:1|stage2_5:2|stage2_5:mine) return 1 ;;
            stage3:1|stage3:2|stage3:mine|stage3:2_5) return 1 ;;
        esac
    fi
    if [[ ${#SKIP_STAGES[@]} -gt 0 ]]; then
        for skip in "${SKIP_STAGES[@]}"; do
            if [[ "$skip" == "$stage" ]]; then
                echo "[skip] stage $stage (--skip-$stage)"
                return 1
            fi
        done
    fi
    return 0
}

run_stage() {
    local stage="$1"; shift
    local logf="logs/stage${stage}.${UTC}.log"
    echo
    echo "============================================================"
    echo "  STAGE $stage  -  $(date -u +%H:%M:%SZ)"
    echo "  log: $logf"
    echo "============================================================"
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "DRY: $*"
        return 0
    fi
    set +e
    "$@" 2>&1 | tee "$logf"
    local rc=${PIPESTATUS[0]}
    set -e
    if [[ $rc -ne 0 ]]; then
        echo "STAGE $stage FAILED (rc=$rc). See $logf" >&2
        return $rc
    fi
}

# ---------- 1. Stage 1: TxGemma chemistry foundation ----------
if should_run 1; then
    SMOKE_FLAG=""
    [[ $SMOKE -eq 1 ]] && SMOKE_FLAG="--smoke-test"
    run_stage 1 \
        python -m src.training.stage1_txgemma4 \
            --config configs/stage1_txgemma4.yaml \
            $SMOKE_FLAG
fi

# ---------- 2. Stage 2: AMR SFT ----------
if should_run 2; then
    SMOKE_FLAG=""
    [[ $SMOKE -eq 1 ]] && SMOKE_FLAG="--smoke-test"
    run_stage 2 \
        python -m src.training.stage2_amr_sft \
            --config configs/stage2_amr_sft.yaml \
            $SMOKE_FLAG
fi

# ---------- 3. Mine hard negatives (real, with Stage 2 model) ----------
if should_run mine; then
    if [[ $SMOKE -eq 1 ]]; then
        run_stage mine \
            python scripts/mine_hard_negatives.py \
                --prompts data/processed/amr-rl-prompts-v3 \
                --max_prompts 32 --candidates_per_prompt 8 \
                --use_stub_generator \
                --max_pairs_per_axis 30 \
                --out data/processed/lysos-hard-negatives-v1.parquet
    else
        run_stage mine \
            python scripts/mine_hard_negatives.py \
                --prompts rahul24raj/lysos-rl-prompts-v3 \
                --candidates_per_prompt 20 \
                --max_pairs_per_axis 200 \
                --model_id rahul24raj/lysos-base \
                --out data/processed/lysos-hard-negatives-v1.parquet
        # Also push to HF for redundancy
        if [[ $DRY_RUN -eq 0 ]]; then
            python -c "
from huggingface_hub import HfApi
api = HfApi()
api.create_repo('rahul24raj/lysos-hard-negatives-v1', repo_type='dataset',
                private=True, exist_ok=True)
api.upload_file(path_or_fileobj='data/processed/lysos-hard-negatives-v1.parquet',
                path_in_repo='hard-negatives.parquet',
                repo_id='rahul24raj/lysos-hard-negatives-v1',
                repo_type='dataset',
                commit_message='Mined post-Stage-2 with rahul24raj/lysos-base')
print('[OK] hard-negatives pushed to HF')
"
        else
            echo "DRY: would push data/processed/lysos-hard-negatives-v1.parquet to rahul24raj/lysos-hard-negatives-v1"
        fi
    fi
fi

# ---------- 4. Stage 2.5: DPO alignment ----------
if should_run 2_5; then
    SMOKE_FLAG=""
    [[ $SMOKE -eq 1 ]] && SMOKE_FLAG="--smoke-test"
    run_stage 2_5 \
        python -m src.training.stage2_5_dpo \
            --config configs/stage2_5_dpo.yaml \
            $SMOKE_FLAG
fi

# ---------- 5. Stage 3: GRPO RL ----------
if should_run 3; then
    SMOKE_FLAG=""
    [[ $SMOKE -eq 1 ]] && SMOKE_FLAG="--smoke-test"
    run_stage 3 \
        python -m src.training.stage3_rl_grpo \
            --config configs/stage3_rl_grpo.yaml \
            $SMOKE_FLAG
fi

echo
echo "============================================================"
echo "  PIPELINE DONE  -  $(date -u +%H:%M:%SZ)"
echo "============================================================"
echo "  Stage 1 -> rahul24raj/txgemma-4-31b"
echo "  Stage 2 -> rahul24raj/lysos-base"
echo "  Stage 2.5 -> rahul24raj/lysos-base-dpo"
echo "  Stage 3 -> rahul24raj/lysos-rl"
echo
echo "  Inference: python -m src.inference.generate \\"
echo "      --model rahul24raj/lysos-rl --prompt 'Design a beta-lactam for MRSA'"
echo
echo "  Eval leaderboard: python scripts/run_eval_leaderboard.py"
