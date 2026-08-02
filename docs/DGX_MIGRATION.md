# Moving AniOS to a DGX Spark

Written from the shipped stack and NVIDIA's own material, not from assumption.
Every claim below that could be checked was checked.

## Use NVIDIA's playbooks, not a hand port

[`NVIDIA/dgx-spark-playbooks`](https://github.com/NVIDIA/dgx-spark-playbooks)
publishes step-by-step setups for GB10, including one for vLLM. Its vLLM playbook
covers the part that is genuinely different on ARM64 — either a prebuilt
container or a source build with custom LLVM/Triton — which is exactly the work
worth not repeating. Treat those guides as the source of truth for Spark-specific
model recipes, parser plugins, and kernel settings, and keep this repository's
Compose file as the composition on top.

## Image architecture: verified, not assumed

Every image the stack pulls was checked with `docker manifest inspect`:

| Image | Architectures |
| --- | --- |
| `pgvector/pgvector:pg16` | `linux/amd64`, `linux/arm64` |
| `redis:7-alpine` | seven, including `linux/arm64` |
| `vllm/vllm-openai` (the pinned digest) | `linux/amd64`, `linux/arm64` |

Our own images build from `python:3.12-slim` and `node:22-bookworm-slim`, both
multi-arch. So no image in the stack blocks the move. That is a better result
than expected and worth knowing before planning around a rebuild.

## The dependency worth checking, and why it is fine

NVIDIA's porting guide flags that `onnxruntime-gpu` publishes no `aarch64` wheels
on PyPI. This project depends on CPU `onnxruntime` for Nomic vision embeddings,
which is a different package: `onnxruntime` 1.28.0 publishes 14 `aarch64`/`arm64`
wheels including `manylinux_2_28_aarch64`. Verified against the PyPI index rather
than inferred from the name.

## What actually has to be requalified

Nothing above proves the stack *performs*. The repository already has the tools
to answer that, and they should be run on the Spark rather than trusted from the
RTX 5080 numbers:

- `backend/cli/benchmark_inference.py` — enforces exit-code thresholds across
  main TTFT/throughput, native tool correctness, structured output, embedding
  latency, and vision;
- `backend/cli/qualify_models.py` — comparative model qualification;
- `bash scripts/verify-migrations.sh` — schema builds from nothing.

The FP8 profile in particular is tuned to a 16 GB discrete card. GB10's 128 GB
unified memory changes the sizing question completely, so
`--gpu-memory-utilization` and the KV cache dtype are settings to re-derive, not
to carry over.

## What does not move

The iMessage bridge stays on the Mac. That is an Apple hardware constraint rather
than an architectural choice: only a Mac signed into Messages can send. Moving
AniOS changes one URL in `MCP_SERVERS_JSON` and nothing else, because the bridge
was written to be reached over the network rather than spawned locally.

Host ComfyUI is the other host-bound piece, and its GPU sizing assumptions are
tied to the same 16 GB card as vLLM's.
