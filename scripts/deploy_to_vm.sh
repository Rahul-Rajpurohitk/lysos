#!/usr/bin/env bash
# deploy_to_vm.sh — rsync repo + data + artifacts to AMD MI300X VM,
#                   bootstrap deps, kick off training pipeline in tmux.
#
# Prerequisite: ~/.ssh/config entry for the host alias. e.g.:
#
#     Host lysos-vm
#       HostName <ip-or-host>
#       User <user>
#       IdentityFile ~/.ssh/lysos_vm
#       ServerAliveInterval 30
#
# Usage:
#   bash scripts/deploy_to_vm.sh lysos-vm
#   bash scripts/deploy_to_vm.sh lysos-vm --skip-rsync
#   bash scripts/deploy_to_vm.sh lysos-vm --skip-bootstrap
#   bash scripts/deploy_to_vm.sh lysos-vm --dry-run

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${1:-}"
shift || true
if [[ -z "$HOST" ]]; then
    echo "usage: $0 <ssh-host-alias> [--skip-rsync] [--skip-bootstrap] [--dry-run] [--smoke]" >&2
    exit 1
fi

SKIP_RSYNC=0
SKIP_BOOTSTRAP=0
DRY=0
SMOKE_FLAG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-rsync) SKIP_RSYNC=1; shift ;;
        --skip-bootstrap) SKIP_BOOTSTRAP=1; shift ;;
        --dry-run) DRY=1; shift ;;
        --smoke) SMOKE_FLAG="--smoke"; shift ;;
        *) echo "unknown arg: $1"; exit 1 ;;
    esac
done

REMOTE_DIR="lysos"
TMUX_SESSION="lysos"

run() {
    if [[ $DRY -eq 1 ]]; then
        echo "DRY: $*"
    else
        echo "+ $*"
        "$@"
    fi
}

echo "============================================================"
echo "  DEPLOY TO VM: $HOST"
echo "============================================================"

# ---------- 1. SSH sanity ----------
echo
echo "[1/5] SSH connectivity check..."
if [[ $DRY -eq 0 ]]; then
    if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" 'true' 2>/dev/null; then
        echo "FATAL: cannot SSH to $HOST. Check ~/.ssh/config and key permissions." >&2
        exit 2
    fi
    echo "  OK  - $(ssh "$HOST" 'hostname')"
    GPUS=$(ssh "$HOST" 'rocm-smi --showproductname 2>/dev/null | grep -c "Card series" || echo 0')
    echo "  GPUs detected: $GPUS"
fi

# ---------- 2. rsync repo + data + artifacts ----------
if [[ $SKIP_RSYNC -eq 0 ]]; then
    echo
    echo "[2/5] rsync repo (this will take ~3-8 min)..."
    # Source code (small, fast)
    run rsync -az --delete \
        --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
        --exclude '.venv*' --exclude 'logs' --exclude 'checkpoints' \
        --exclude 'wandb' --exclude '.idea' --exclude '.vscode' \
        --exclude 'workspace/web/node_modules' \
        --exclude 'workspace/web/dist' \
        --info=stats2 \
        "$ROOT/" "$HOST:$REMOTE_DIR/"
    # Pre-computed data (~1.5GB total)
    echo
    echo "[2b/5] rsync data/processed + artifacts (~1.5GB)..."
    run rsync -az --info=progress2 \
        "$ROOT/data/processed/" "$HOST:$REMOTE_DIR/data/processed/"
    run rsync -az --info=progress2 \
        "$ROOT/artifacts/" "$HOST:$REMOTE_DIR/artifacts/"
    # .env (separately, sensitive)
    if [[ -f "$ROOT/.env" ]]; then
        run rsync -az "$ROOT/.env" "$HOST:$REMOTE_DIR/.env"
        echo "  OK - .env synced"
    fi
fi

# ---------- 3. Bootstrap deps on the VM ----------
if [[ $SKIP_BOOTSTRAP -eq 0 ]]; then
    echo
    echo "[3/5] bootstrap deps (~10-15 min on first run)..."
    run ssh "$HOST" "cd $REMOTE_DIR && bash scripts/vm_bootstrap.sh"
fi

# ---------- 4. Launch pipeline in tmux ----------
echo
echo "[4/5] launching pipeline in tmux session '$TMUX_SESSION'..."
LAUNCH_CMD="cd $REMOTE_DIR && bash scripts/run_full_pipeline.sh $SMOKE_FLAG 2>&1 | tee logs/pipeline.\$(date -u +%Y%m%dT%H%M%SZ).log"
if [[ $DRY -eq 1 ]]; then
    echo "DRY: ssh $HOST tmux new-session -d -s $TMUX_SESSION \"$LAUNCH_CMD\""
else
    # Kill any prior session, fresh start
    ssh "$HOST" "tmux kill-session -t $TMUX_SESSION 2>/dev/null || true"
    ssh "$HOST" "tmux new-session -d -s $TMUX_SESSION \"$LAUNCH_CMD\""
    echo "  OK - tmux session '$TMUX_SESSION' started on $HOST"
fi

# ---------- 5. Show how to monitor ----------
echo
echo "[5/5] DEPLOYED. Monitor with:"
echo
echo "  bash scripts/vm_status.sh $HOST           # snapshot status"
echo "  bash scripts/vm_tail.sh $HOST stage1      # live tail Stage 1 log"
echo "  bash scripts/vm_tail.sh $HOST pipeline    # live tail orchestrator"
echo "  ssh $HOST 'tmux attach -t $TMUX_SESSION'  # attach interactively"
echo
echo "  Adapters land on HF Hub as they save:"
echo "    rahul24raj/txgemma-4-31b      (Stage 1)"
echo "    rahul24raj/lysos-base         (Stage 2)"
echo "    rahul24raj/lysos-base-dpo     (Stage 2.5)"
echo "    rahul24raj/lysos-rl           (Stage 3)"
