# ADR 0006: Hybrid Supervisor and Qualified Model Roles

## Status

Accepted and runtime verified for the current local model set.

## Context

AniOS needs a main agent that stays responsive while focused agents perform
longer work. One large model for every stage wastes local GPU capacity and
couples every subsystem to one provider contract. A completely free-form
model router would also make high-level routing slower and less predictable,
and could blur the application's authorization boundary.

Model suitability cannot be inferred from parameter count or a small prompt
sample. Presentation generation, in particular, requires progressive strict
typed output that differs from ordinary chat, native tool selection, and
Mermaid planning.

## Decision

1. Run a typed `MainSupervisorAgent` LangGraph step before ordinary retrieval.
   Its registered deterministic policy currently delegates explicit
   presentation creation and otherwise selects the ordinary response path.
2. Keep execution authority outside the supervisor. A decision can name only a
   registered capability; application services still authorize, enqueue,
   invoke, persist, and report the work.
3. Keep semantic MCP discovery and native tool selection in the ordinary path.
   The configured main model can select at most one live-validated eligible
   tool, after which application-owned policy and invocation gates apply.
4. Configure the main, presentation, and diagram roles independently by model,
   endpoint, and reasoning effort. Blank role settings fall back through the
   main and legacy LM Studio settings for compatibility.
5. Surface `agent_started` and `agent_finished` events containing the exact
   specialist and configured model so a user can see delegation without seeing
   private prompts or results.
6. Use `backend.cli.qualify_models` as a repeatable bounded gate for supervisor
   and tool decisions plus progressive presentation contracts. Never promote a
   model from the harness alone; repeat the owning subsystem's real API,
   worker, browser, state, and log acceptance path.
7. For the current RTX 5080 runtime, select `qwen/qwen3.5-9b` for the main
   response/tool-selection and diagram roles. Retain
   `google/gemma-4-12b` for the presentation role and vision.

## Evidence

- Both candidates passed the five bounded supervisor/tool cases and one
  progressive two-slide harness run. Qwen completed the corrected six-case
  run in 10.441 seconds versus Gemma in 28.504 seconds.
- Qwen completed a real ordinary chat response and a real diagram request.
- Qwen failed the actual presentation worker contract after both bounded
  correction attempts because it added an unsupported `optional_key_message`
  field. That evidence overrides its smaller harness pass.
- Gemma completed the actual progressive presentation worker path with exactly
  two slides and a validated editable PPTX.

## Consequences

Benefits:

- ordinary chat and tool selection use a smaller, faster local model;
- presentation work remains isolated in its durable specialist worker;
- each role can move to another local host without changing business logic;
- deterministic explicit routing is fast, testable, and cannot invent tools or
  permissions;
- the user sees which agent and model accepted delegated work.

Costs and limitations:

- the current supervisor registry contains only the presentation capability;
- explicit diagrams still use their existing deterministic branch before the
  supervisor;
- the main supervisor does not yet compare all tools and agents in one decision
  or ask/resume an ambiguity clarification;
- one RTX 5080 remains a shared physical capacity boundary even when multiple
  model roles are loaded;
- results are local qualification evidence, not a permanent claim that one
  model is best after models, quantization, prompts, or hardware change.

## Alternatives considered

- One Gemma client for every role was rejected because it kept ordinary chat
  tied to the largest current model and prevented independent qualification.
- Qwen for every role was rejected because the real presentation worker failed
  its strict typed contract.
- A free-form LLM supervisor for every turn was deferred because deterministic
  registered intents currently provide lower latency and clearer routing
  guarantees. A future unified capability registry may add a bounded model
  choice only for ambiguous cases.
