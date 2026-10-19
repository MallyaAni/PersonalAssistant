#!/usr/bin/env bash
# The vLLM command for DeepSeek-V4.1-Flash-1017 (EXL3 2.75 bpw, TP=2). Runs INSIDE
# the serving container; ds41-tp2.sh mounts it at /serve.sh and sets MODEL_DIR,
# RANK and HEADLESS. It is the command sudoingX's launcher (dgx-spark-deepseek-v41
# @ cc59c36, scripts/launch/dsv41_tp2.sh) generates, with HeNryous's
# serve/serve_example.sh values where the two differ, and these choices of ours:
#   - two served names: the honest one first, and the old name as an alias so
#     every client (compose, opencode, tests) keeps working during the change.
#   - --max-num-seqs 2 / --max-num-batched-tokens 2048 / KV 2.5 GiB: the base
#     recipe's measured defaults, not renek's 4 / 4096 / 3.75 GiB. spark1 also
#     carries the app stack, and renek saw the head node dip to 3.1 GiB free
#     with nothing else resident; the watchdog stops the server at 1.5. 2.5 GiB
#     of KV is 660K tokens: two full 320K requests at once.
#   - --max-model-len 262144, the base recipe's default, not renek's 327680:
#     his 314K-prompt peak was the moment the head node dipped to 3.1 GiB
#     free, and spark1 carries ~5 GiB of tenants he did not have. opencode is
#     capped at 196608 context + 65536 output = 256K to fit under this. Raise
#     to 327680 only after a measured low point under a 250K prefill shows
#     >= 3 GiB MemAvailable on BOTH nodes (scripts/spark-dsv41-cutover.sh
#     records it).
#   - vision on (image:4), because this model replaces the separate VLM.
# NEVER put a comment inside the exec block below (see ds4-tp2.sh for the
# incident); every line ends in a backslash.
set -e
exec vllm serve "$MODEL_DIR" --served-model-name deepseek-v4.1-flash-1017 deepseek-v4-flash --host 0.0.0.0 --port 8000 \
  --tensor-parallel-size 2 --nnodes 2 --node-rank "$RANK" --master-addr 192.168.100.1 --master-port 25000 \
  --gpu-memory-utilization 0.86 --max-model-len 262144 --max-num-seqs 2 \
  --max-num-batched-tokens 2048 --load-format auto \
  --engram-config '{"cpu_offload":true,"dp_shared_memory":false,"disk_offload":true,"disk_threads":256}' \
  --compilation-config '{"cudagraph_mode":"FULL_DECODE_ONLY"}' \
  --kernel-config '{"enable_flashinfer_autotune":false}' \
  --enable-auto-tool-choice --tool-call-parser deepseek_v41 --reasoning-parser deepseek_v41 \
  --speculative-config '{"method":"dspark","num_speculative_tokens":5}' \
  --kv-cache-memory-bytes 2684354560 \
  --limit-mm-per-prompt '{"image":4}' --mm-processor-cache-gb 0 --long-prefill-token-threshold 512 \
  $HEADLESS
