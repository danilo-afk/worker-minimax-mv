#!/usr/bin/env bash
set -euo pipefail

if [ ! -d /runpod-volume ]; then
  echo "worker-music3: /runpod-volume não está montado" >&2
  exit 1
fi

LOG_DIR=/runpod-volume/logs
mkdir -p "$LOG_DIR"
: > "$LOG_DIR/comfyui-latest.log"
: > "$LOG_DIR/handler-latest.log"

echo "worker-music3: iniciando ComfyUI"
python -u /comfyui/main.py \
  --disable-auto-launch \
  --disable-metadata \
  --listen 127.0.0.1 \
  --port 8188 \
  --log-stdout \
  > "$LOG_DIR/comfyui-latest.log" 2>&1 &

echo "worker-music3: iniciando handler RunPod"
exec python -u /app/handler.py
