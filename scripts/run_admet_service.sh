#!/usr/bin/env bash
# Run the Lysos ADMET model service (real ADMET-AI / Chemprop).
# Local dev uses .venv-models on CPU; on AMD MI300X this same service
# runs with a ROCm PyTorch wheel for batched GPU inference.
#
#   scripts/run_admet_service.sh            # foreground on :7920
#   LYSOS_ADMET_PORT=7921 scripts/run_admet_service.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${LYSOS_ADMET_PORT:-7920}"
VENV=".venv-models"

if [ ! -x "$VENV/bin/uvicorn" ]; then
  echo "[admet-service] $VENV not ready — install with:"
  echo "  $VENV/bin/pip install admet-ai fastapi uvicorn"
  exit 1
fi

echo "[admet-service] starting on :$PORT (real ADMET-AI model)"
exec "$VENV/bin/uvicorn" workspace.model_services.admet_service:app \
  --host 127.0.0.1 --port "$PORT"
