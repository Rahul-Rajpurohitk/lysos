#!/usr/bin/env bash
# vm_status.sh — snapshot of training pipeline state on the VM.
#
# Pulls:
#   - tmux pane (last ~80 lines of pipeline output)
#   - GPU utilization (rocm-smi)
#   - HF Hub: which adapter checkpoints exist + sizes
#   - Wandb: latest run state via API
#   - Disk free
#
# Usage:
#   bash scripts/vm_status.sh lysos-vm
#   bash scripts/vm_status.sh lysos-vm --quiet     # just the headline

set -euo pipefail

HOST="${1:-}"
QUIET=0
[[ "${2:-}" == "--quiet" ]] && QUIET=1

if [[ -z "$HOST" ]]; then
    echo "usage: $0 <ssh-host-alias> [--quiet]" >&2
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "============================================================"
echo "  STATUS @ $HOST   $(date -u +%H:%M:%SZ)"
echo "============================================================"

# 1. Is tmux session alive?
echo
echo "[tmux] lysos session:"
ssh "$HOST" 'tmux has-session -t lysos 2>/dev/null && echo "  ALIVE" || echo "  DEAD/EXITED"'

# 2. Last 30 lines of pipeline output
echo
echo "[pipeline] last 30 lines:"
ssh "$HOST" 'tmux capture-pane -t lysos -p 2>/dev/null | tail -30 || echo "  (no tmux output)"'

# 3. GPU utilization
echo
echo "[gpu] rocm-smi:"
ssh "$HOST" 'rocm-smi --showuse 2>/dev/null | grep -E "GPU|use" | head -10 || echo "  rocm-smi unavailable"'

# 4. Disk
echo
echo "[disk] free on \$HOME:"
ssh "$HOST" 'df -h ~ 2>&1 | tail -1'

# 5. HF Hub adapter state (run from local Mac, no SSH needed)
echo
echo "[hf-hub] adapters:"
.venv-cli/bin/python3 -c "
from huggingface_hub import HfApi
import os
p = os.path.expanduser('~/.cache/huggingface/token')
if os.path.exists(p): os.environ.setdefault('HF_TOKEN', open(p).read().strip())
api = HfApi()
for repo, label in [
    ('rahul24raj/txgemma-4-31b',   'Stage 1'),
    ('rahul24raj/lysos-base',      'Stage 2'),
    ('rahul24raj/lysos-base-dpo',  'Stage 2.5'),
    ('rahul24raj/lysos-rl',        'Stage 3'),
]:
    try:
        info = api.model_info(repo, files_metadata=True)
        sb = info.siblings or []
        has_adapter = any(s.rfilename == 'adapter_model.safetensors' for s in sb)
        size_b = sum(s.size or 0 for s in sb)
        size_str = f'{size_b/1e6:.1f}MB' if size_b else '0'
        marker = '✓' if has_adapter else '·'
        last_mod = info.last_modified.strftime('%H:%M:%S') if info.last_modified else '?'
        print(f'  {marker} {label:8s}  {repo:40s}  {size_str:>10s}  upd={last_mod}')
    except Exception as e:
        print(f'  ? {label:8s}  {repo:40s}  ({str(e)[:30]})')
" 2>/dev/null || echo "  (HF Hub query failed — local venv-cli not available?)"

# 6. Wandb run state (heuristic — last 1 run)
if [[ $QUIET -eq 0 ]]; then
    echo
    echo "[wandb] recent run:"
    ssh "$HOST" 'cd lysos && ls -t wandb/run-*/files/output.log 2>/dev/null | head -1 | xargs -I{} tail -3 "{}" 2>/dev/null || echo "  (no wandb runs yet)"'
fi

echo
echo "============================================================"
