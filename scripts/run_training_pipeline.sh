#!/usr/bin/env bash
# Lysos training pipeline orchestrator — runs all 3 stages with checkpoint
# resilience + preflight checks + post-stage smoke validation.
#
# This is THE script to run on the AMD MI300X VM after vm_bootstrap.sh.
# It handles VM crashes, OOMs, and HF Hub backup gracefully.
#
# Usage:
#   bash scripts/run_training_pipeline.sh [stage1|stage2|stage3|all]
#
# Default: all 3 stages sequentially.

set -euo pipefail

STAGE="${1:-all}"
LOG_DIR="${LYSOS_HOME:-$HOME/lysos}/training_logs"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d_%H%M%S)"

log() { printf "\033[1;36m[lysos-pipeline]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[lysos-pipeline] FAIL\033[0m %s\n" "$*" >&2; exit 1; }

# Activate venv
if [ -f "/tmp/lysos_venv/bin/activate" ]; then
    source /tmp/lysos_venv/bin/activate
fi

# Preflight before any stage
log "running preflight check"
python3 scripts/preflight_check.py --stage "$STAGE" || fail "preflight failed; fix above + retry"

# ---- Stage 1: TxGemma-4 ----
if [ "$STAGE" = "stage1" ] || [ "$STAGE" = "all" ]; then
    log "=== STAGE 1: TxGemma-4 base SFT (8x MI300X, ~6h) ==="
    python3 scripts/checkpoint_resilience.py --stage 1 --max_retries 3 --allow_hub_recovery \
        2>&1 | tee "$LOG_DIR/stage1_$TS.log" \
        || fail "Stage 1 failed after retries"
    log "Stage 1 complete. Checkpoint pushed to rahul24raj/txgemma-4-31b"

    # Quick post-train smoke
    log "Stage 1 smoke: load + sample"
    python3 -c "
from transformers import AutoModelForCausalLM, AutoTokenizer
m = AutoModelForCausalLM.from_pretrained('rahul24raj/txgemma-4-31b', torch_dtype='bfloat16', device_map='auto')
t = AutoTokenizer.from_pretrained('rahul24raj/txgemma-4-31b')
prompt = 'Predict the cyp3a4 inhibition for SMILES CC(=O)Oc1ccccc1C(=O)O'
ids = t(prompt, return_tensors='pt').to('cuda')
out = m.generate(**ids, max_new_tokens=64, do_sample=False)
print(t.decode(out[0], skip_special_tokens=True))
print('Stage 1 smoke OK')
" || log "Stage 1 smoke had issues; continuing anyway"
fi

# ---- Stage 2: Lysos AMR-spec ----
if [ "$STAGE" = "stage2" ] || [ "$STAGE" = "all" ]; then
    log "=== STAGE 2: Lysos AMR-spec SFT (1x MI300X, ~12h) ==="
    python3 scripts/checkpoint_resilience.py --stage 2 --max_retries 3 --allow_hub_recovery \
        2>&1 | tee "$LOG_DIR/stage2_$TS.log" \
        || fail "Stage 2 failed after retries"
    log "Stage 2 complete. Checkpoint pushed to rahul24raj/lysos-base"
fi

# ---- Stage 3: GRPO RL ----
if [ "$STAGE" = "stage3" ] || [ "$STAGE" = "all" ]; then
    log "=== STAGE 3: GRPO RL with 12-component reward (1x MI300X, ~10h) ==="
    python3 scripts/checkpoint_resilience.py --stage 3 --max_retries 3 --allow_hub_recovery \
        2>&1 | tee "$LOG_DIR/stage3_$TS.log" \
        || fail "Stage 3 failed after retries"
    log "Stage 3 complete. Final model pushed to rahul24raj/lysos-rl"
fi

# Post-pipeline eval
if [ "$STAGE" = "all" ]; then
    log "=== POST-PIPELINE EVAL ==="
    python3 eval/run_all.py --baseline_only --out reports/baseline_post_pipeline.json \
        2>&1 | tee "$LOG_DIR/eval_$TS.log"
    log "Pipeline complete. See reports/ for eval outputs."
fi

log "=== PIPELINE FINISHED ==="
