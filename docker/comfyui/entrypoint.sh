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
  # Do not let ComfyUI's requirements pin over the image's own torch build.
  # `|| true`, never a fallback copy: if every line is a torch pin, the right
  # install list is empty — copying the unfiltered file would pip a generic
  # torch wheel over the CUDA build this image exists to provide.
  grep -viE '^(torch|torchvision|torchaudio)([<>=!~ ].*)?$' requirements.txt \
    > /tmp/comfy-reqs.txt || true
  if [ -s /tmp/comfy-reqs.txt ]; then
    python3 -m pip install -r /tmp/comfy-reqs.txt
  fi
fi

# Each custom node's own dependencies, which nothing else installs.
#
# ComfyUI's requirements.txt does not cover custom_nodes, so a node with a
# dependency imports, raises ModuleNotFoundError, and is skipped with a warning
# buried in the boot log - the node simply is not registered, and the failure
# only surfaces later as "that loader does not exist" in an unrelated workflow.
# ComfyUI-GGUF needs `gguf` and is the editor's model loader, so without this
# every image edit fails while ComfyUI itself reports perfectly healthy.
#
# Never fatal: one unsatisfiable custom node must not stop the server, because
# the alternative is losing image generation over a node nothing here uses.
for req in /comfyui/custom_nodes/*/requirements.txt; do
  [ -f "$req" ] || continue
  # Same torch guard as above - a custom node pinning torch would pull a
  # generic wheel over the CUDA build this image exists to provide.
  grep -viE '^(torch|torchvision|torchaudio)([<>=!~ ].*)?$' "$req"     > /tmp/node-reqs.txt || true
  if [ -s /tmp/node-reqs.txt ]; then
    echo "installing dependencies for $(dirname "$req")"
    python3 -m pip install -r /tmp/node-reqs.txt ||       echo "WARNING: could not install $req; that node will not load" >&2
  fi
done

exec python3 main.py --listen 0.0.0.0 --port 8188 "$@"
