#!/usr/bin/env bash
# Install the bind-mounted ComfyUI install's Python dependencies into the
# container (keeping the CUDA 12.8 torch already provided by the image), then
# launch ComfyUI bound to every interface so the backend can reach it.
set -euo pipefail

cd /comfyui

if [ ! -f main.py ]; then
  echo "ERROR: /comfyui is not a ComfyUI install (no main.py)." >&2
  echo "Set COMFYUI_HOST_PATH to your ComfyUI directory in .env." >&2
  exit 1
fi

if [ -f requirements.txt ]; then
  # Do not let ComfyUI's requirements pin over the CUDA 12.8 torch build.
  grep -viE '^(torch|torchvision|torchaudio)([<>=!~ ].*)?$' requirements.txt \
    > /tmp/comfy-reqs.txt || cp requirements.txt /tmp/comfy-reqs.txt
  python3 -m pip install -r /tmp/comfy-reqs.txt
fi

exec python3 main.py --listen 0.0.0.0 --port 8188 "$@"
