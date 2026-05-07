#!/bin/bash
# Bring up the local→MI300X inference tunnel for the Lysos workbench.
#
# Forwards local port 7861 to the rocm container's serve.py on lysos-vm:8000,
# which serves the merged Stage 2.5 DPO model (Gemma-4-31B + TxGemma + AMR
# + DPO, fp16, 31.3B params, 59GB on disk, ~5-15 tok/s on MI300X).
#
# Usage:
#   ./scripts/start_inference_tunnel.sh             # establish tunnel
#   ./scripts/start_inference_tunnel.sh --status    # check tunnel + serve.py
#   ./scripts/start_inference_tunnel.sh --stop      # tear down tunnel
#
# Requires: ssh alias `lysos-vm` configured in ~/.ssh/config
# After running this, set LYSOS_INFERENCE_URL=http://localhost:7861/v1 (already
# the workbench default) and start the workbench backend normally.

set -e

LOCAL_PORT="${LYSOS_LOCAL_PORT:-7861}"
REMOTE_HOST="lysos-vm"
REMOTE_PORT=8000

case "${1:-}" in
  --status)
    echo "=== local tunnel on :$LOCAL_PORT ==="
    if lsof -ti :$LOCAL_PORT > /dev/null 2>&1; then
      lsof -ti :$LOCAL_PORT | xargs -I{} ps -p {} -o pid,etime,command | head -3
    else
      echo "no process on :$LOCAL_PORT"
    fi
    echo
    echo "=== tunnel health ==="
    if curl -s --connect-timeout 3 http://localhost:$LOCAL_PORT/health 2>&1; then
      echo
    else
      echo "(unreachable)"
    fi
    echo
    echo "=== serve.py on lysos-vm ==="
    ssh -o ConnectTimeout=10 lysos-vm "docker exec rocm pgrep -af 'serve.py' | head -3" 2>&1 || echo "(SSH unreachable)"
    exit 0
    ;;
  --stop)
    echo "=== stopping tunnel ==="
    pkill -f "ssh.*-fNL.*$LOCAL_PORT:" || echo "no tunnel"
    exit 0
    ;;
esac

# Default: bring up the tunnel.
if curl -s --connect-timeout 1 http://localhost:$LOCAL_PORT/health > /dev/null 2>&1; then
  echo "✓ tunnel already up on :$LOCAL_PORT (health OK)"
  exit 0
fi

# Kill any stale ssh tunnels on this port first.
pkill -f "ssh.*-fNL.*$LOCAL_PORT:" 2>/dev/null || true
sleep 1

echo "=== bringing up tunnel: localhost:$LOCAL_PORT → $REMOTE_HOST:$REMOTE_PORT ==="
ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -fNL "$LOCAL_PORT:localhost:$REMOTE_PORT" "$REMOTE_HOST"

# Verify
sleep 2
if curl -s --connect-timeout 3 http://localhost:$LOCAL_PORT/health > /dev/null 2>&1; then
  echo "✓ tunnel up on :$LOCAL_PORT"
  curl -s http://localhost:$LOCAL_PORT/health
  echo
else
  echo "✗ tunnel established but :$LOCAL_PORT/health unreachable"
  echo "  is serve.py running on $REMOTE_HOST? check with:"
  echo "    ssh $REMOTE_HOST 'docker exec rocm pgrep -af serve.py'"
  exit 1
fi
