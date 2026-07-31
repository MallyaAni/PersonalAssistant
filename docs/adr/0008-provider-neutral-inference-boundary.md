# ADR 0008: Provider-Neutral Inference Boundary

## Status

Accepted and runtime verified for the current OpenAI-compatible LM Studio
profile.

## Context

AniOS qualifies different models for main chat, diagrams, presentations,
vision, and embeddings. Those application roles must survive a future move to
vLLM, TensorRT-LLM, or another local runtime without making agents, memory,
visual services, or presentation workflows depend on runtime-specific classes.
Inference transport and model lifecycle are different concerns: sending a
request should not grant code authority to unload models or alter GPU
residency.

## Decision

1. Business services depend on neutral `InferenceProvider`,
   `VisionProvider`, and `EmbeddingProvider` contracts.
2. Dependency assembly selects an adapter independently for main,
   presentation, diagram, vision, and embedding roles. Blank role adapters
   inherit the global adapter; endpoints, models, and reasoning controls remain
   role-configurable.
3. The first implemented adapter is `openai_compatible`. It owns buffered,
   streaming, native tool-call, vision, and embedding wire behavior and rejects
   unknown adapter names.
4. `INFERENCE_PROVIDER_NAME` records operator-facing provenance only. It does
   not choose protocol behavior.
5. Model discovery, download, load/unload, context length, parallel slots,
   KV-cache placement, GPU offload, residency checks, and failure restoration
   stay outside the inference adapter. A future deterministic resource manager
   owns those operations.
6. Existing LM-Studio-named imports remain compatibility aliases during
   migration; new dependency assembly uses the neutral factories.
7. A runtime or adapter is promoted only after deterministic provider tests,
   the role qualification harness, direct API/log acceptance, and the owning
   real-browser workflow pass.

## Consequences

- Agents and application services can retain stable contracts while local
  runtimes change.
- Each role can move independently instead of forcing a single provider or
  model on the whole system.
- Runtime lifecycle policy cannot leak into model-generated tool decisions.
- The current qualified LM Studio profile is unchanged.
- OpenAI-compatible syntax alone does not prove semantic compatibility;
  structured output, tool calls, streaming termination, vision payloads, and
  embeddings still require acceptance against each candidate runtime.
- Compatibility aliases add temporary naming debt and can be removed only
  after downstream imports migrate.

## Evidence

- Factory and provider regression tests passed for buffered, structured/tool,
  streaming, and embedding behavior.
- The rebuilt Compose backend resolved every configured role to the
  OpenAI-compatible adapter while retaining Qwen, Gemma, and Nomic model keys.
- A direct chat request emitted `start`, delta events, and terminal `done`;
  the concatenated answer matched its unique marker and backend logs showed
  successful embedding, classifier, and main-model calls.
- A real browser request streamed a non-empty configured-provider response,
  terminated loading, restored the exact rendered response after navigation,
  and produced no blocking Console/page errors.
- The presentation role returned `READY` from Gemma through the same neutral
  text contract.
