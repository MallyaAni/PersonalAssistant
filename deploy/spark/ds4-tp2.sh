#!/bin/bash
# Serve DeepSeek-V4-Flash across both Sparks with tensor parallelism.
#
#   ds4-tp2.sh worker     # run FIRST, on animallya-spark2 (rank 1)
#   ds4-tp2.sh head       # then on animallya-spark1 (rank 0), serves :8000
#
# Every non-obvious value here was set from someone else's documented crash;
# the reasoning is in docs/DGX_MIGRATION.md. The short version:
#   - both RoCE twins are given to NCCL and merged, or collectives run at half
#     the port (98 vs 161 Gb/s busbw)
#   - gpu-memory-utilization 0.78, not 0.85: speculative decode allocates on
#     the first real request, so higher values boot and then die under traffic
#   - num_speculative_tokens 5: the DSpark block size. 7 and 10 boot, then
#     crash on every generation
#   - VLLM_MOE_USE_DEEP_GEMM=0: DeepGEMM otherwise wins the MoE backend
#     priority order, so B12X_MXFP4 - the kernel written for DeepSeek V4's
#     native MXFP4 weights on GB10 - is never selected, and decode runs at
#     roughly half speed with nothing in the log calling it a fallback
#   - JIT caches are node-local. Sharing them produces a torch.compile
#     makedirs race, half-written DeepGEMM cubins and an ABI-mismatched
#     FlashInfer sampling.so, and none of the errors mention the cache
set -euo pipefail
ROLE="${1:?usage: ds4-tp2.sh head|worker}"

IMAGE="ghcr.io/anemll/dspark-vllm-gx10:0.1.1"
MODEL="$HOME/hf/DeepSeek-V4-Flash-0731"
HEAD_IP="192.168.100.1"
MASTER_PORT="29501"
CACHE="$HOME/vllm-cache"

mkdir -p "$CACHE"

case "$ROLE" in
  head)   RANK=0; EXTRA=(--host 0.0.0.0 --port 8000) ;;
  worker) RANK=1; EXTRA=(--headless) ;;
  *) echo "role must be head or worker" >&2; exit 1 ;;
esac

exec docker run --rm --name "ds4-$ROLE" \
  --network host --ipc host --shm-size 64g \
  --ulimit memlock=-1 \
  --device /dev/infiniband:/dev/infiniband \
  --gpus all \
  -v "$MODEL:/model:ro" \
  -v "$CACHE:/vllm-cache" \
  -e VLLM_CACHE_ROOT=/vllm-cache \
  -e TORCHINDUCTOR_CACHE_DIR=/vllm-cache/inductor \
  -e TRITON_CACHE_DIR=/vllm-cache/triton \
  -e FLASHINFER_WORKSPACE_BASE=/vllm-cache/flashinfer \
  -e DG_JIT_CACHE_DIR=/vllm-cache/deepgemm \
  -e VLLM_USE_B12X_MOE=1 \
  -e VLLM_MOE_USE_DEEP_GEMM=0 \
  -e VLLM_USE_FLASHINFER_SAMPLER=1 \
  -e VLLM_USE_BREAKABLE_CUDAGRAPH=0 \
  -e VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 \
  -e VLLM_ENGINE_READY_TIMEOUT_S=3600 \
  -e TORCH_CUDA_ARCH_LIST=12.1a \
  -e CUTE_DSL_ARCH=sm_121a \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  -e NCCL_IB_DISABLE=0 \
  -e NCCL_IB_HCA=rocep1s0f1,roceP2p1s0f1 \
  -e NCCL_IB_MERGE_NICS=1 \
  -e NCCL_IB_GID_INDEX=3 \
  -e NCCL_SOCKET_IFNAME=enp1s0f1np1 \
  -e GLOO_SOCKET_IFNAME=enp1s0f1np1 \
  -e TP_SOCKET_IFNAME=enp1s0f1np1 \
  -e NCCL_IGNORE_CPU_AFFINITY=1 \
  -e NCCL_CUMEM_ENABLE=0 \
  -e NCCL_DEBUG=WARN \
  "$IMAGE" \
  /model \
  --served-model-name deepseek-v4-flash \
  --trust-remote-code \
  --tensor-parallel-size 2 --pipeline-parallel-size 1 \
  --nnodes 2 --node-rank "$RANK" \
  --master-addr "$HEAD_IP" --master-port "$MASTER_PORT" \
  --moe-backend flashinfer_b12x \
  --distributed-executor-backend mp \
  --kv-cache-dtype nvfp4_ds_mla \
  --block-size 256 \
  # 512k, not the 1M the model supports. gpu-memory-utilization is a
  # fraction of the WHOLE pool, so what is left for KV depends on what else
  # is already resident - and since the application stack moved onto spark1
  # it now starts in parallel with this on every boot. Profiling against a
  # busy machine found 5.09 GiB free where 1M context needs 7.54 GiB, and the
  # engine exited rather than starting smaller. 512k needs ~3.77 GiB, which
  # fits either way. Measured context use is median 4.4k, p90 11.7k, max
  # 16.1k tokens, so this is still a ~30x margin over the worst real turn.
  --max-model-len 524288 \
  --max-num-seqs 6 \
  --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.78 \
  --enable-prefix-caching \
  --speculative-config '{"method":"dspark","num_speculative_tokens":5,"draft_sample_method":"probabilistic"}' \
  --tokenizer-mode deepseek_v4 \
  --tool-call-parser deepseek_v4 --enable-auto-tool-choice \
  --reasoning-parser deepseek_v4 \
  --generation-config vllm \
  "${EXTRA[@]}"
