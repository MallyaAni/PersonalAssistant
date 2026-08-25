# ADR 0015: DeepSeek-V4-Flash on two DGX Sparks, every text role consolidated

## Status

Accepted 2026-08-23, implemented and verified. Supersedes the runtime and
role profile of [ADR 0009](0009-vllm-default-local-inference-runtime.md)
(single RTX 5080, Qwen 3.5 4B for every role); leaves the provider-neutral
boundary of [ADR 0008](0008-provider-neutral-inference-boundary.md) unchanged.
Evidence: `docs/MODEL_EVALUATION.md` ("Decision, 2026-08-20: DeepSeek
stays"), `docs/DGX_MIGRATION.md` (two-Spark commissioning, application move),
`docs/NEXT_SESSION.md` (verified state), Roadmap Milestone 9.

## Context

The system had run on one 16 GB card. That ceiling decided everything: one
small model for every role, FP8 to make a 16k context fit beside ComfyUI, and
no room for a second resident model. A blind six-prompt read-off (2026-08-14)
put DeepSeek-V4-Flash ahead of Qwen and Nemotron for conversation with no
failures; a measured comparison then settled it against public benchmarks
that could not (`MODEL_EVALUATION.md`). DeepSeek-V4-Flash at the chosen
quantisation and context needs roughly 97 GiB of memory per node - more than
one GB10's 121.7 GiB can hold beside anything else - and the build is
text-only.

Two facts about the Sparks shape the decision as much as the model does.
They have no remote management controller and no wake-on-LAN, so a hung
node is recovered by a person pressing a button; and over-allocating GPU
memory hangs a node outright.

## Decision

1. **DeepSeek-V4-Flash serves every text role** - conversation, routing,
   structured output, diagrams, decks, memory classification - from one vLLM
   deployment, tensor-parallel across spark1 (rank 0, `:8000`) and spark2
   (rank 1), with a 1M-token context and an NVFP4 KV cache. Every decision
   role decodes grammar-constrained at temperature 0. The roles stay pinned
   explicitly in compose so that changing one never silently moves another.
2. **Vision is a separate model.** Qwen3-VL-8B serves on spark2 (`:8001`),
   because the DeepSeek build cannot read pixels. It is the only other
   generation model resident.
3. **The application stack lives on spark1**: every container, PostgreSQL,
   Redis, the Nomic text embedder, the Qwen3 reranker, and the Cloudflare
   tunnel. The Sparks talk to each other over the RoCE fabric; containers
   address stores by compose-network name.
4. **Memory headroom is a safety margin, not an optimisation.** GPU
   utilisation is pinned at the measured safe value where a node hosts two
   models (0.81 on spark2); `--kv-cache-memory-bytes` is banned; every new
   GPU tenant is sized against the measured free number; nothing moves a
   model between hosts at request time.
5. **Image generation does not run on the Sparks.** FLUX.2 Klein needs
   headroom neither node has while DeepSeek holds both; it runs on the
   desktop's card and is honestly reported unavailable when that machine is
   off.
6. **Promotion stays acceptance-driven.** A model moves onto a role only
   after the deploy gate and the functional suites pass against it; the
   harness is a gate, never sufficient proof.

## Alternatives considered

- **Keep Qwen 4B for routing and structured output beside DeepSeek.** This
  was the shape on the single card, chosen for routing latency (about a
  second against five to ten) and because DeepSeek then returned unparseable
  JSON for short classifications. On the Sparks the second resident text
  model would cost memory the safety margin cannot spare, and
  grammar-constrained decoding on vLLM removed the structured-output defect,
  so the roles consolidated.
- **DeepSeek on one Spark.** Does not fit at this quantisation and context
  beside anything else; a smaller context or a harsher quantisation was
  measured worse than the split.
- **A cloud fallback for the large model.** Rejected on the same privacy
  posture as every other subsystem: no conversation text leaves the owner's
  machines.
- **Keeping the RTX 5080 stack alongside.** The original Milestone 9 goal;
  abandoned once the Sparks could carry the whole application, because two
  deployments doubled every trap and the desktop was wanted for images.

## Consequences

- Every text call serialises on one deployment, so a turn's latency is set by
  how many model calls it makes, not by any single one.
- Recovery from a hang is physical. The RoCE fabric addresses are still set
  by hand, so a power cycle strands the pair until someone re-sets them
  (netplan is the recorded fix).
- The single-GPU serving lessons (FP8 KV behaviour, startup ordering) are
  historical and kept in `MODEL_EVALUATION.md` and `DGX_MIGRATION.md`.
- A future multimodal generation model would need its own headroom decision
  under rule 4; the capability-registry brief (ADR 0013) is the place that
  decision would be designed.
