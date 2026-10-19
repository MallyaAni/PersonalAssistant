#!/bin/bash
# Serve DeepSeek-V4.1-Flash-1017 (EXL3 2.75 bpw, HeNryous build) across both
# Sparks with tensor parallelism. Replaces ds4-tp2.sh (V4-Flash-0731) from
# 2026-10-19; that script stays on both boxes as the rollback.
#
#   ds41-tp2.sh worker    # run FIRST, on spark2 (rank 1)
#   ds41-tp2.sh head      # then on spark1 (rank 0), serves :8000
#
# Source of the values: sudoingX/dgx-spark-deepseek-v41 @ cc59c36
# (scripts/launch/dsv41_tp2.sh, the docker run line and RECIPE_ENV) and
# HeNryous/deepseek-v41-1017-dgx-spark (serve/serve_example.sh, DOCKER_ENV).
# Where the two set the same knob, serve_example wins, as it does there.
# The vLLM command itself is ds41-serve.sh, mounted at /serve.sh.
#
# What is OURS and why:
#   - Fabric devices. The recipe defaults to enp1s0f0np0 / rocep1s0f0; on
#     these boxes those ports are DOWN and the cabled pair is enp1s0f1np1 /
#     rocep1s0f1 (192.168.100.x) with the twin enP2p1s0f1np1 / roceP2p1s0f1
#     (192.168.101.x), checked with ibdev2netdev on 2026-10-19. NCCL gets both
#     twins (the recipe lists both: +3% prefill); the plugin's RDMA ring stays
#     on one. GID index 3 is the RoCE v2 IPv4 entry here (ds4-tp2.sh, same).
#   - systemd, not the recipe's ssh-driven launcher: the launcher starts
#     detached containers from the head over ssh; here each node runs its own
#     rank in the foreground under ds41-{head,worker}.service, like ds4. The
#     unit's ExecStartPre drops the page cache as root before each start, which
#     the launcher does with sudo: GB10 CUDA cannot reclaim page cache, and
#     vLLM sizes its pools from what it sees free.
#   - Caches are node-local in ~/.cache/dsv41-serve (torch extensions, the
#     DSpark Markov token list, vLLM caches). Build the JIT kernels there once
#     per image BEFORE the first start, with the ds4 server down - building
#     next to loaded weights has run a node out of memory and left a stale
#     lock (HeNryous README). scripts/spark-dsv41-cutover.sh does this.
#   - Engram tables (203 GB) stay on NVMe and are read at lookup time
#     (disk_offload, 256 reader threads); they take no GPU memory. They MUST
#     be shards 47/48 of deepseek-ai/DeepSeek-V4.1-Flash-1017 - the older
#     V4.1 repo has same-named, same-sized files with different content.
#   - Memory: --gpu-memory-utilization 0.86 only gates the startup check
#     because the KV pool is pinned (2.5 GiB per rank). Expected resident per
#     rank is ~93 GiB of weights + KV + ~6 GiB runtime. spark1 also hosts the
#     app stack and the embedder (shrunk to 0.02 of the pool in the same
#     change); spark2 no longer hosts the VLM - this model serves vision.
#     The server's own watchdog stops it at ~1.5 GiB free. If MemAvailable
#     sits under 3 GiB on either node under load, lower --max-model-len to
#     262144 in ds41-serve.sh before anything else.
#   - Known trap: literal DeepSeek special tokens inside user text become
#     real special tokens on this image. The README's defuse is a zero-width
#     space after '<' in untrusted text before it reaches vLLM. AniOS does not
#     do this yet (tracked in NEXT_SESSION.md).
#   - NEVER put a comment inside the exec block below: every line there ends
#     in a backslash, so a '#' silently deletes the rest of the command.
set -euo pipefail
ROLE="${1:?usage: ds41-tp2.sh head|worker}"

IMAGE="ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v4i"
MODEL_DIR="$HOME/models/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-DGX-Spark"
CACHE="$HOME/.cache/dsv41-serve"
SERVE="$HOME/ds41-serve.sh"

case "$ROLE" in
  head)   RANK=0; SELF_IP=192.168.100.1; HEADLESS="" ;;
  worker) RANK=1; SELF_IP=192.168.100.2; HEADLESS="--headless" ;;
  *) echo "role must be head or worker" >&2; exit 1 ;;
esac
[ -d "$MODEL_DIR" ] || { echo "$MODEL_DIR missing" >&2; exit 1; }
[ -f "$SERVE" ] || { echo "$SERVE missing" >&2; exit 1; }
[ -f "$CACHE/markov_top_tokens.json" ] || { echo "$CACHE/markov_top_tokens.json missing" >&2; exit 1; }
mkdir -p "$CACHE"

exec docker run --rm --name "ds41-$ROLE" \
  --network host --ipc host --shm-size 64g \
  --gpus all --device /dev/infiniband \
  --ulimit memlock=-1 --ulimit stack=67108864 \
  --entrypoint /bin/bash \
  -v "$MODEL_DIR:$MODEL_DIR:ro" \
  -v "$SERVE:/serve.sh:ro" \
  -v "$CACHE:/root/.cache" \
  -e MODEL_DIR="$MODEL_DIR" \
  -e RANK="$RANK" \
  -e HEADLESS="$HEADLESS" \
  -e NCCL_IB_HCA=rocep1s0f1,roceP2p1s0f1 \
  -e NCCL_IB_GID_INDEX=3 \
  -e NCCL_IB_DISABLE=0 \
  -e NCCL_NET=IB \
  -e NCCL_SOCKET_IFNAME=enp1s0f1np1 \
  -e GLOO_SOCKET_IFNAME=enp1s0f1np1 \
  -e TP_SOCKET_IFNAME=enp1s0f1np1 \
  -e VLLM_HOST_IP="$SELF_IP" \
  -e VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=1800 \
  -e VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 \
  -e VLLM_DISABLED_KERNELS=FlashInferCutlassMxfp8LinearKernel \
  -e HF_HUB_OFFLINE=1 \
  -e VLLM_EXL3_MOE_PARALLEL_GROUPS=1 \
  -e EXL3_MOE_COOP_WIDE=1 \
  -e EXL3_INT8_GEMV=0 \
  -e VLLM_DSPARK_DEPTH_POLICY=conf \
  -e VLLM_DSPARK_ROUND_MS=33.26,36.33,38.91,42.23,46.03,48.15 \
  -e VLLM_DSPARK_DRAFT_MS=0 \
  -e VLLM_DSPARK_MARKOV_CACHE=/root/.cache/markov_top_tokens.json \
  -e EXL3_L2PF=attn,moe,next \
  -e EXL3_RDMA_AR=1 \
  -e VLLM_SHORT_CTX_BOUNDS=512,1025 \
  -e EXL3_ROUTER=1 \
  -e EXL3_L2PF_HC=1 \
  -e VLLM_DSPARK_LOCAL_ARGMAX=1 \
  -e EXL3_SMOE_FLAGS=-DSMOE_RUNFLAGS=1 \
  -e VLLM_DSV41_MHC_OVERLAP=1 \
  -e VLLM_ENGRAM_DISK_SPIN_MS=1000 \
  -e EXL3_MROW_GROUPED=1 \
  -e VLLM_EXL3_MOE_TF_PROMPT=1 \
  -e TORCH_EXTENSIONS_DIR=/root/.cache/torch_extensions \
  -e NCCL_MIN_NCHANNELS=4 \
  -e NCCL_MAX_NCHANNELS=4 \
  -e VLLM_PREFILL_EVERY_N_STEPS=24 \
  -e VLLM_PREFILL_THROTTLE_MIN_PRIO=5 \
  -e VLLM_SPARSE_INDEXER_MAX_LOGITS_MB=128 \
  -e EXL3_RDMA_DEVICES=rocep1s0f1 \
  -e NCCL_PROTO=^LL128 \
  -e NCCL_CUMEM_ENABLE=0 \
  -e NCCL_CUMEM_HOST_ENABLE=0 \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  -e VLLM_INDEXER_TP_SHARD_MIN_ROWS=2048 \
  -e EXL3_RDMA_CPU=14 \
  "$IMAGE" /serve.sh
