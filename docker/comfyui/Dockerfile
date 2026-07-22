# Runtime image that drives the user's EXISTING ComfyUI install on an NVIDIA GPU.
#
# The ComfyUI code, custom nodes, and models are bind-mounted at /comfyui by
# Compose. This image only provides Python plus a Blackwell-capable (sm_120,
# RTX 50-series) PyTorch/CUDA 12.8 runtime, then installs the mounted install's
# own requirements on first boot.
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv git libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Blackwell / RTX 50-series needs the CUDA 12.8 PyTorch wheels; the cu128 index
# publishes builds with sm_120 support.
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/cu128

WORKDIR /comfyui

COPY entrypoint.sh /usr/local/bin/comfyui-entrypoint.sh
# Normalize potential Windows CRLF so the shebang works, then make executable.
RUN sed -i 's/\r$//' /usr/local/bin/comfyui-entrypoint.sh \
    && chmod +x /usr/local/bin/comfyui-entrypoint.sh

EXPOSE 8188
ENTRYPOINT ["/usr/local/bin/comfyui-entrypoint.sh"]
