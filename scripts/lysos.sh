#!/bin/bash
# Lysos inference lifecycle — one command to manage the whole stack.
#
# Manages:
#   1. serve.py on lysos-vm (rocm container, port 8000) — pins the merged
#      Stage 2.5 DPO model to MI300X. This is what costs GPU compute.
#   2. SSH tunnel from local:7861 → lysos-vm:8000 — workbench reads from
#      LYSOS_INFERENCE_URL=http://localhost:7861/v1.
#
# Usage:
#   ./scripts/lysos.sh up        bring server + tunnel up (~30s model load)
#   ./scripts/lysos.sh down      stop server + tunnel (frees GPU)
#   ./scripts/lysos.sh status    show current state of both
#   ./scripts/lysos.sh restart   down + up
#   ./scripts/lysos.sh logs      tail the most recent serve.py log on VM
#   ./scripts/lysos.sh test      send one chat completion through the chain
#
# Requires:
#   - ssh alias `lysos-vm` configured in ~/.ssh/config
#   - merged model at /shared-docker/lysos/models/lysos-dpo-merged on the VM
#   - serve.py at /shared-docker/lysos/scripts/serve.py on the VM
#
# What this does NOT touch:
#   - The merged model on disk (keep it; recreating takes 15 min + 59GB)
#   - The VM itself (use lablab dashboard / `sudo poweroff` if you want to
#     drop VM-level cost too)
#   - The workbench backend / frontend (run those in your normal dev loop)

set -e

LOCAL_PORT="${LYSOS_LOCAL_PORT:-7861}"
REMOTE_HOST="lysos-vm"
REMOTE_PORT=8000
SERVE_PY=/shared-docker/lysos/scripts/serve.py
LOGS_DIR=/shared-docker/lysos/logs
HF_TOKEN_PATH="${HOME}/.lysos_hf_token"  # optional override; falls back to .env

GREEN="\033[32m"; RED="\033[31m"; CYAN="\033[36m"; DIM="\033[2m"; NC="\033[0m"

check_tunnel() {
  curl -s --connect-timeout 2 http://localhost:$LOCAL_PORT/health > /dev/null 2>&1
}

check_serve_remote() {
  local pid
  pid=$(ssh -o ConnectTimeout=10 "$REMOTE_HOST" \
        "docker exec rocm pgrep -f 'serve.py' 2>/dev/null | head -1" 2>/dev/null)
  echo -n "$pid"
}

cmd_status() {
  echo "=== Lysos inference status ==="
  echo
  echo "[1/3] local tunnel on :$LOCAL_PORT"
  if lsof -ti :$LOCAL_PORT > /dev/null 2>&1; then
    lsof -ti :$LOCAL_PORT | xargs -I{} ps -p {} -o pid,etime,command 2>/dev/null | tail -n+2 | head -3
    if check_tunnel; then
      echo -e "  ${GREEN}✓ tunnel reachable${NC}  $(curl -s http://localhost:$LOCAL_PORT/health)"
    else
      echo -e "  ${RED}✗ port bound but /health unreachable (server down on VM?)${NC}"
    fi
  else
    echo -e "  ${DIM}— no tunnel${NC}"
  fi
  echo

  echo "[2/3] serve.py on $REMOTE_HOST"
  local pid
  pid=$(check_serve_remote)
  if [ -n "$pid" ]; then
    ssh -o ConnectTimeout=10 "$REMOTE_HOST" \
        "docker exec rocm ps -p $pid -o pid,etime,cmd 2>/dev/null | tail -n+2" 2>/dev/null | head -3
    echo -e "  ${GREEN}✓ serve.py up (PID $pid)${NC}"
  else
    echo -e "  ${DIM}— serve.py NOT running${NC}"
  fi
  echo

  echo "[3/3] GPU activity"
  ssh -o ConnectTimeout=10 "$REMOTE_HOST" \
      "docker exec rocm rocm-smi --showuse 2>/dev/null | grep -E 'GPU\\[0\\]' | head -3" 2>/dev/null \
      || echo -e "  ${DIM}(rocm-smi unavailable)${NC}"
  echo
}

cmd_up() {
  echo "=== Lysos inference UP ==="

  # Step 1 — start serve.py on the VM if not already running.
  echo "[1/3] checking serve.py on $REMOTE_HOST..."
  local pid
  pid=$(check_serve_remote)
  if [ -n "$pid" ]; then
    echo -e "  ${GREEN}✓ serve.py already running (PID $pid)${NC}"
  else
    echo "  starting serve.py..."
    local ts
    ts=$(date -u +%Y%m%dT%H%M%SZ)
    local log="$LOGS_DIR/serve_$ts.log"
    ssh "$REMOTE_HOST" "docker exec -d rocm bash -c 'cd /shared-docker/lysos && python3 scripts/serve.py 2>&1 | tee $log'" \
      > /dev/null
    echo "  log: $REMOTE_HOST:$log"
    echo -n "  waiting for model load (up to 60s)..."
    for i in $(seq 1 12); do
      sleep 5
      pid=$(check_serve_remote)
      if [ -n "$pid" ] && ssh "$REMOTE_HOST" "docker exec rocm grep -q 'Uvicorn running' $log 2>/dev/null"; then
        echo -e " ${GREEN}ready${NC}"
        break
      fi
      echo -n "."
    done
    if [ -z "$pid" ]; then
      echo -e " ${RED}failed${NC}"
      echo "  check log: ssh $REMOTE_HOST 'tail -30 $log'"
      exit 1
    fi
  fi

  # Step 2 — establish SSH tunnel.
  echo "[2/3] checking tunnel..."
  if check_tunnel; then
    echo -e "  ${GREEN}✓ tunnel already up${NC}"
  else
    pkill -f "ssh.*-fNL.*$LOCAL_PORT:" 2>/dev/null || true
    sleep 1
    echo "  bringing up: localhost:$LOCAL_PORT → $REMOTE_HOST:$REMOTE_PORT"
    ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -fNL \
        "$LOCAL_PORT:localhost:$REMOTE_PORT" "$REMOTE_HOST"
    sleep 2
    if check_tunnel; then
      echo -e "  ${GREEN}✓ tunnel up${NC}"
    else
      echo -e "  ${RED}✗ tunnel failed${NC}"
      exit 1
    fi
  fi

  # Step 3 — sanity test.
  echo "[3/3] smoke test (one chat completion)..."
  local resp
  resp=$(curl -s -X POST http://localhost:$LOCAL_PORT/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d '{"model":"lysos-base-dpo","messages":[{"role":"user","content":"Say HELLO."}],"max_tokens":12,"temperature":0.1}' \
       2>/dev/null)
  local content
  content=$(echo "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin)["choices"][0]["message"]["content"][:80])' 2>/dev/null || echo "")
  if [ -n "$content" ]; then
    echo -e "  ${GREEN}✓ model replied:${NC} $content"
  else
    echo -e "  ${RED}✗ chat completion failed${NC}"
    echo "  raw: $resp"
    exit 1
  fi
  echo
  echo -e "${CYAN}Lysos is UP.${NC} Workbench: ./scripts/start_workbench.sh (or your usual dev loop)"
}

cmd_down() {
  echo "=== Lysos inference DOWN ==="

  echo "[1/2] stopping serve.py on $REMOTE_HOST..."
  local pid
  pid=$(check_serve_remote)
  if [ -n "$pid" ]; then
    ssh "$REMOTE_HOST" "docker exec rocm kill $pid 2>&1 || docker exec rocm kill -9 $pid" > /dev/null 2>&1 || true
    sleep 2
    if [ -z "$(check_serve_remote)" ]; then
      echo -e "  ${GREEN}✓ serve.py stopped (was PID $pid) — GPU compute released${NC}"
    else
      echo -e "  ${RED}✗ serve.py still running, try manually${NC}"
    fi
  else
    echo "  (serve.py already stopped)"
  fi

  echo "[2/2] tearing down tunnel..."
  if pkill -f "ssh.*-fNL.*$LOCAL_PORT:" 2>/dev/null; then
    echo -e "  ${GREEN}✓ tunnel killed${NC}"
  else
    echo "  (no tunnel)"
  fi
  echo
  echo -e "${CYAN}Lysos is DOWN.${NC} Bring back with: ./scripts/lysos.sh up"
}

cmd_logs() {
  ssh "$REMOTE_HOST" "ls -t $LOGS_DIR/serve_*.log 2>/dev/null | head -1 | xargs -I{} tail -50 {}"
}

cmd_test() {
  if ! check_tunnel; then
    echo -e "${RED}tunnel not up — run: ./scripts/lysos.sh up${NC}"
    exit 1
  fi
  echo "=== chat smoke test ==="
  echo "prompt: Suggest one antibiotic SMILES for MRSA. Just the SMILES."
  echo
  curl -s -X POST http://localhost:$LOCAL_PORT/v1/chat/completions \
       -H 'Content-Type: application/json' \
       -d '{"model":"lysos-base-dpo","messages":[{"role":"user","content":"Suggest one antibiotic SMILES for MRSA. Just the SMILES."}],"max_tokens":80,"temperature":0.7}' \
    | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("model:", d.get("model"))
print("smiles:", d["choices"][0]["message"]["content"][:200])
print("tokens:", d.get("usage"))
'
}

cmd_vmoff() {
  echo "=== VM POWER OFF ==="
  echo "stopping serve.py first..."
  cmd_down
  echo
  echo "powering off $REMOTE_HOST (sudo poweroff)..."
  ssh -o ServerAliveInterval=5 -o ServerAliveCountMax=2 "$REMOTE_HOST" \
      "sudo poweroff" 2>&1 | head -3 || true
  echo
  echo -e "${CYAN}VM is shutting down.${NC} Persistent disk (model + scripts) is preserved."
  echo "Bring back online: lablab.ai dashboard → Start instance, then ./scripts/lysos.sh up"
}

cmd_vmon() {
  echo "=== VM POWER ON ==="
  echo -n "waiting for $REMOTE_HOST SSH..."
  for i in $(seq 1 60); do
    if ssh -o ConnectTimeout=5 "$REMOTE_HOST" "echo ok" 2>/dev/null > /dev/null; then
      echo -e " ${GREEN}up${NC}"
      break
    fi
    echo -n "."
    sleep 5
  done
  if ! ssh -o ConnectTimeout=5 "$REMOTE_HOST" "echo ok" 2>/dev/null > /dev/null; then
    echo -e " ${RED}timeout${NC} (start the VM via lablab.ai dashboard first)"
    exit 1
  fi
  echo
  echo "ensuring rocm container is running..."
  ssh "$REMOTE_HOST" "docker start rocm 2>&1 || true" | head -3
  sleep 3
  echo
  cmd_up
}

case "${1:-status}" in
  up)        cmd_up ;;
  down)      cmd_down ;;
  status)    cmd_status ;;
  restart)   cmd_down; sleep 2; cmd_up ;;
  logs)      cmd_logs ;;
  test)      cmd_test ;;
  vmoff)     cmd_vmoff ;;
  vmon)      cmd_vmon ;;
  *)         echo "usage: $0 {up|down|status|restart|logs|test|vmoff|vmon}"; exit 2 ;;
esac
