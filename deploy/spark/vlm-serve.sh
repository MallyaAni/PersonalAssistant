#!/bin/bash
# Serve Qwen3-VL-8B (AWQ 4-bit) as AniOS's vision model, on spark2.
#
# Sizing notes, because two defaults here are traps on a DGX Spark:
#   - --gpu-memory-utilization is a fraction of the WHOLE 121 GiB unified
#     pool, not of what is free. The reply model already holds ~94 GB, so
#     0.85 would try to take 103 GB and hang the machine - PyTorch does not
#     OOM cleanly on GB10, it freezes the box. 0.10 = ~12.1 GB, which fits
#     the ~16 GB actually available with headroom.
#   - mm_processor_cache_gb defaults to 4 GiB, a third of our budget, and
#     nothing warns you. Set to 0.
#   - kv-cache-memory-bytes is set EXPLICITLY (2 GiB). Trusting the
#     utilization fraction alone produced 7.46 GiB of KV on top of 7.1 GB of
#     weights - about 16 GB total - and left the box with 538 MB free. The
#     profiler sizes KV from what it observes free at startup, so on a
#     nearly-full machine that fraction is not the cap it appears to be.
#   - AWQ (W4A16/Marlin), not NVFP4: CUTLASS FP4 kernels target sm_120 and
#     silently emit wrong output on sm_121 (vLLM #50925).
set -euo pipefail

IMAGE="ghcr.io/anemll/dspark-vllm-gx10:0.1.1"
MODEL="$HOME/hf/Qwen3-VL-8B-AWQ"
CACHE="$HOME/vllm-cache-vlm"

mkdir -p "$CACHE"

exec docker run --rm --name anios-vlm \
  --network host --ipc host --shm-size 8g \
  --ulimit memlock=-1 \
  --gpus all \
  -v "$MODEL:/model:ro" \
  -v "$CACHE:/vllm-cache" \
  -e VLLM_CACHE_ROOT=/vllm-cache \
  -e TORCHINDUCTOR_CACHE_DIR=/vllm-cache/inductor \
  -e TRITON_CACHE_DIR=/vllm-cache/triton \
  -e TORCH_CUDA_ARCH_LIST=12.1a \
  -e CUTE_DSL_ARCH=sm_121a \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  "$IMAGE" \
  /model \
  --served-model-name qwen3-vl-8b \
  --trust-remote-code \
  --host 0.0.0.0 --port 8001 \
  --gpu-memory-utilization 0.09 \
  --kv-cache-memory-bytes 3221225472 \
  --max-model-len 16384 \
  --max-num-seqs 4 \
  --limit-mm-per-prompt '{"image":4}' \
  --mm-processor-cache-gb 0 \
  --enable-prefix-caching
