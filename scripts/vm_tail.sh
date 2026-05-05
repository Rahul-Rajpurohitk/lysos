#!/usr/bin/env bash
# vm_tail.sh — live-follow a stage log on the VM.
#
# Usage:
#   bash scripts/vm_tail.sh <host> stage1     # tails the most recent stage1 log
#   bash scripts/vm_tail.sh <host> pipeline   # tails the orchestrator wrapper log
#   bash scripts/vm_tail.sh <host> tmux       # captures the tmux pane (no follow)
#
# To exit the follow: Ctrl-C (does not kill the remote training).

set -euo pipefail

HOST="${1:-}"
WHAT="${2:-pipeline}"

if [[ -z "$HOST" ]]; then
    echo "usage: $0 <ssh-host> {stage1|stage2|stage2_5|stage3|mine|pipeline|tmux}" >&2
    exit 1
fi

case "$WHAT" in
    tmux)
        ssh -t "$HOST" 'tmux capture-pane -t lysos -p | tail -200'
        ;;
    pipeline|stage1|stage2|stage2_5|stage3|mine)
        # Find the most recent matching log on the VM and tail it
        REMOTE_CMD="cd lysos && f=\$(ls -t logs/${WHAT}*.log 2>/dev/null | head -1) && [[ -n \"\$f\" ]] && tail -n 200 -F \"\$f\" || echo 'no $WHAT log yet'"
        ssh -t "$HOST" "$REMOTE_CMD"
        ;;
    *)
        echo "unknown target: $WHAT" >&2
        exit 1
        ;;
esac
