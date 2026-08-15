#!/usr/bin/env bash
set -euo pipefail

if [ ! -d /runpod-volume ]; then
  echo "worker-h3: /runpod-volume não está montado" >&2
  exit 1
fi

LOG_DIR=/runpod-volume/logs
mkdir -p "$LOG_DIR"
: > "$LOG_DIR/h3-comfyui-latest.log"
: > "$LOG_DIR/h3-handler-latest.log"

python -u /comfyui/main.py --disable-auto-launch --disable-metadata \
  --listen 127.0.0.1 --port 8188 --log-stdout \
  > "$LOG_DIR/h3-comfyui-latest.log" 2>&1 &
echo "$!" > /tmp/comfyui.pid
exec python -u /app/handler.py
