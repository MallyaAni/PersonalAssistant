# ADR 0009: vLLM Default Local Inference Runtime

## Status

Accepted and runtime verified on the RTX 5080 profile.

## Context

AniOS previously depended on separately managed LM Studio model instances. The
provider-neutral boundary in ADR 0008 removed that application coupling, but
normal startup still relied on external model loading, role-specific residency,
and an operator-restored profile. The current workstation has one 16 GB RTX
5080 and must also retain free local ComfyUI image generation.

## Decision

1. Use the pinned official vLLM OpenAI-compatible image as the default local
   inference runtime under Docker Desktop's Linux/WSL2 NVIDIA runtime.
2. Run two Compose services: `vllm-main` serves pinned Qwen 3.5 4B for main,
   tool, diagram, presentation, architecture-candidate, and vision roles;
   `vllm-embedding` serves pinned Nomic Embed Text v1.5.
3. Pin the container digest and model revisions. Nomic's required remote code
   is also revision-pinned.
4. Start Qwen to health before Nomic. Start host ComfyUI only after both are
   healthy; this order avoids concurrent GPU initialization exhausting the KV
   cache.
5. Keep model and compile caches on the `E:` drive. Treat the context, sequence
   counts, precision, and GPU utilization values as a measured workstation
   profile that requires requalification when changed.
6. Quantize Qwen to FP8 on load and store its KV cache in FP8. The RTX 5080
   reports compute capability 12.0, so FP8 runs on native tensor cores rather
   than emulation. This is what makes the 16k context and ComfyUI coexistence
   fit on one 16 GB card; it is not portable to a pre-Ada GPU.
7. Size each service to its measured footprint rather than a round number.
   Nomic's weights load in 0.26 GiB, so the embedding service reserves 0.06
   utilization instead of the 0.15 that left roughly 2 GiB unused.
8. Send a JSON Schema on every request whose reply is parsed as data. The
   runtime decodes it as a grammar, so a malformed reply cannot be produced.
   Derive the schema from the type that validates the reply so the two cannot
   drift. Decode routing classifiers greedily.
6. Keep inference transport provider-neutral. Dynamic model switching,
   sleep/wake, general GPU-capacity scheduling, and multi-host placement remain
   separate resource-management work.

## Consequences

- A normal Compose startup no longer requires LM Studio or its management API.
- One smaller multimodal Qwen instance covers all generation roles and leaves
  enough capacity for Nomic plus dynamically offloaded ComfyUI work.
- The default runtime is reproducible by image/model revision rather than an
  operator-created GUI profile.
- Native Windows remains unsupported by vLLM; Docker Desktop/WSL2 and the
  NVIDIA container runtime are deployment prerequisites.
- Cold start remains several minutes because the checkpoint loads over a Windows
  bind mount and vLLM profiles multimodal CUDA graphs. Persisted compile cache
  reduces recompilation but does not remove weight loading or warmup.
- FP8 is a measured quality risk, not a free win. vLLM logs that the checkpoint
  carries no calibrated `k_scale`/`q_scale` factors and falls back to 1.0. The
  profile is accepted on measured behaviour, not on an assumption of parity, and
  no head-to-head BF16 quality comparison was run.
- Schema-constrained decoding moves format correctness from prompt wording into
  the runtime, so contract prose is no longer the only thing standing between a
  small model and an unparseable reply. It constrains structure only: a schema
  cannot make Mermaid valid or a slide well argued.

## Evidence

- vLLM 0.23.0 passed chat streaming with terminal completion, exact native tool
  selection, structured output, a vision fixture, and finite 768-dimensional
  Nomic embeddings.
- The operational benchmark passed all five role checks; warm main TTFT was
  0.260 seconds and the three-vector embedding batch was 0.065 seconds.
- Direct AniOS chat produced the exact requested SSE answer and terminal
  `done`; a real Chromium chat rendered/restored a live response with no
  blocking Console or page errors.
- The owning vision API analyzed a 5.47 MB persisted image in 7.31 seconds.
- ComfyUI generated a persisted 2048px HiDream image in 36.47 seconds while
  both vLLM services remained healthy, and a following chat completed.
- After narrow typed-boundary normalization, three consecutive real queued
  presentation jobs reached `ready` with exact slide counts.

## FP8 and schema-constraint evidence

- FP8 halved resident weights from 8.61 GiB to 5.09 GiB. Cached tokens rose from
  45,428 to 64,046 while the context doubled to 16,384, and free GPU memory with
  both services resident rose from 1,860 MiB to 6,588 MiB.
- vLLM selected `CutlassFP8ScaledMMLinearKernel`, confirming the native Blackwell
  FP8 path rather than an emulated one.
- The operational benchmark passed 5/5 on FP8 and improved every latency against
  the BF16 baseline: main TTFT 0.260 s to 0.160 s, main total 1.653 s to 1.173 s,
  27.821 to 39.222 normalized estimated tokens/s, native tool 0.439 s to 0.316 s,
  and the embedding batch 0.065 s to 0.025 s.
- A 16-case labelled freshness set scored 16/16 with zero unusable answers under
  FP8 and greedy decoding, exercising the real classifier rather than a fixture.
- Sending the live `DeckPlan` schema with a prompt that explicitly demanded
  `optional_` field prefixes and null notes produced neither: the grammar
  admitted only declared field names, and an exact three-slide bound held.
- A real queued three-slide job reached `ready` on attempt 1 and rendered through
  `pptxgenjs+libreoffice`, with no correction retry.
- Complete backend suite: 506 passed. Ruff, Black, and full-project MyPy across
  152 source files all passed, restoring the gate ADR 0009 previously left red.
