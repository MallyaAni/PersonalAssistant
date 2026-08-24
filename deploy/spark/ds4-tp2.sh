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
#   - Do NOT set --kv-cache-memory-bytes here. It was tried on 2026-08-23
#     to bank memory for an image model and it is a HARD CAP, not a
#     hint: at 5 GiB the engine refused to start because 1M context
#     needs 7.21 GiB, and it kept refusing at every utilization value
#     because the cap does not scale with the fraction. Let the
#     utilization fraction size KV, and reclaim memory by lowering it.
#   - NEVER put a comment inside the exec block below. Every line there ends
#     in a backslash, so bash joins them into one command and a '#' comments
#     out everything after it. An explanatory comment added above
#     --max-model-len on 2026-08-23 silently dropped --max-model-len,
#     --gpu-memory-utilization, --speculative-config, --tokenizer-mode, the
#     tool-call and reasoning parsers and the role's own --host/--port. The
#     server came up on vLLM defaults and nothing said so; the only visible
#     symptom was a config dump reading max_seq_len=1048576 and
#     speculative_config=None. Put the reasoning up here instead.
#   - THE CEILING IS SPARK2, NOT SPARK1. Utilization is a fraction of the
#     whole 121.69 GiB pool and BOTH nodes must satisfy it, but they are not
#     symmetric: spark1 has ~116 GiB free while spark2 also hosts the VLM and
#     has ~105 GiB. 0.90 asks for 109.5 GiB - fine on spark1, refused on
#     spark2, and the head then hangs at parallel_state waiting for a rank
#     that already died. 0.81 asks 98.6 GiB against spark2's measured 100.5 GiB free, and
#     still leaves ~8.7 GiB of KV against the 7.54 GiB that 1M context
#     needs. Measured: at 0.78 the KV pool was 5.0 GiB, so weights plus
#     overhead are ~89.9 GiB and every extra point of utilization is
#     ~1.2 GiB of KV. The margin on spark2 is ~1.9 GiB - thin, and the
#     way to widen it is to trim the VLM's KV on spark2, not to raise
#     this.
#     Raise this only after checking `free -g` on SPARK2.
#   - 1M context at 0.83 utilization, and --speculative-config REMOVED. These
#     three go together and the reason is worth reading before changing any of
#     them.
#
#     From 2026-08-23 morning until that night this file carried an
#     explanatory comment INSIDE the exec block. Every line there ends in a
#     backslash, so bash joined them and the '#' commented out everything
#     after it: --max-model-len, --gpu-memory-utilization, --speculative-config,
#     --tokenizer-mode, both parsers, and the role's own --host/--port. vLLM ran
#     on its defaults - utilization 0.9, context 1M from the model card, no
#     speculative decode - and served fine all day. Nothing said so.
#
#     Fixing the comment made 0.78 apply for the first time, which left 5.0 GiB
#     for KV where 1M needs 7.54 and even 512k needs 5.47, and the engine
#     refused to start. So 1M was only ever working *because* of the bug.
#
#     0.90 is therefore not a new setting; it is the value that has actually
#     been running. Speculative decode stays off because it was also off during
#     that whole period, and because the note below records that a high
#     utilization plus spec decode boots, passes a smoke test, and then dies on
#     the first real request. Re-enabling it is a separate change that needs
#     its own load test, not a line added here.
#   - (superseded) 256k sizing: Sized by the engine's own
#     arithmetic, not by preference: at 0.78 utilization the weights leave
#     5.0 GiB for KV, 512k needs 5.47 GiB, and vLLM refuses to start rather
#     than serving a shorter context. It reports the largest length that
#     fits (406016); 256k sits under that with room. Measured context use is
#     median 4.4k, p90 11.7k, max 16.1k tokens - still ~16x the worst turn.
#   - the old note, kept because the reasoning still holds: gpu-memory-utilization is a
#     fraction of the WHOLE pool, so what is left for KV depends on what is
#     already resident, and the application stack now starts in parallel
#     with this on every boot. Measured context use is median 4.4k, p90
#     11.7k, max 16.1k tokens - a ~30x margin over the worst real turn.
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
  --max-model-len 1048576 \
  --max-num-seqs 6 \
  --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.81 \
  --enable-prefix-caching \
  --tokenizer-mode deepseek_v4 \
  --tool-call-parser deepseek_v4 --enable-auto-tool-choice \
  --reasoning-parser deepseek_v4 \
  --generation-config vllm \
  "${EXTRA[@]}"
