# ADR 0013 - supporting detail: the model and modality brief

Written alongside ADR 0012 to answer a separate question: what a truly
multimodal AniOS needs, and what fits on this hardware. Not yet an
accepted decision - it is the brief a decision would be made from.

---

I have what I need — grounded in the live code, compose topology, and measured hardware numbers. Here is the brief.

---

# Design Brief — Model & Modality Axis
## AniOS LangGraph re-architecture

Scope: how a node gets a model, and how a node gets a payload. Everything else (control flow, checkpointing, tool selection) is out of scope and assumed to be designed elsewhere.

---

## 1. What "truly multi-model" means here

**Decision: a capability registry with capability-request resolution at node level. Not cost-aware routing, and not per-node model binding.**

The distinction matters because per-node binding is what already exists and is precisely the thing that hurts. `build_diagram_graph(provider)` (`backend/agents/diagram/agent.py:32`) and `build_presentation_graph(provider)` (`backend/agents/deck/agent.py:97`) close over a provider at graph-compile time. That *is* per-node binding. Its cost is recorded in `docs/MODEL_EVALUATION.md:537` — when the reply engine gained schema enforcement, "six roles moved to the main model" and that was six separate edits, because each site named a model.

The failure mode this system actually suffers is a **capability** mismatch, never a price one. `backend/config/settings.py:86-94` says it outright:

> Three separate outages traced to it before it was named: the presentation revert on 2026-08-14, image recall returning nothing, and Scout's place suggester returning an empty tuple. Each was fixed by moving one call site to Qwen, which is why the fix kept having to be repeated.

`MAIN_LLM_STRUCTURED_OUTPUT` is already a capability registry with exactly one capability and exactly one model. The architecture is the generalisation of a thing this repo has already discovered and half-built.

So: **nodes declare what they need; a registry decides which model provides it.** A node never names a model.

### Not worth building

- **Cost-aware routing.** Every model is local, on owned hardware, already paid for. There is no per-token bill to optimise against. The real scarce resource is VRAM residency (spark1 ~9.9 GB, spark2 ~1.4 GB) and wall clock — those belong in the descriptor as placement facts, not in a pricing model.
- **Ranked fallback chains.** This is `FallbackInferenceProvider`, deleted for cause. See §7.
- **A model that picks the model.** The repo rule "decide meaning with a model, never with a pattern" governs *intent* — which tool, which referent, what to remember. Which model serves a capability is not meaning; it is a lookup, and it must be deterministic, testable, and identical across replays. Making it a model decision would make routing unreproducible and untestable at the same stroke.
- **A generic gateway / LiteLLM-style proxy.** `InferenceProviderKind` has exactly one member (`openai_compatible`, `backend/core/llm.py:13`) and every endpoint here speaks it. `create_inference_provider` is already the adapter seam. Adding a proxy adds a hop and a second place for `reasoning_effort` to go wrong.
- **Per-request dynamic load/unload.** Over-allocating on a GB10 *hangs the box* rather than OOM-killing (`MODEL_EVALUATION.md`, §10). Residency is a deployment decision with a reserve, not a request-time one.

---

## 2. The model registry

Two ideas: a descriptor says what is true of a model, and a requirement says what a node needs. Resolution is set containment.

```python
# backend/core/model_registry.py
"""Declare what each served model can do, and resolve capability requests to one model."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Literal

type Capability = Literal[
    "text",                # prose worth showing a person
    "tool_calling",        # native tools/tool_choice, reproducible at temperature 0
    "schema_enforcement",  # response_format json_schema is a grammar, not a suggestion
    "vision_in",           # accepts image content parts
    "image_out",           # text -> pixels
    "image_edit",          # pixels + instruction -> pixels
    "embedding",           # text or image -> vector
    "transcribe_audio",    # audio -> text
    "speak_text",          # text -> audio
]

type Host = Literal["spark1", "spark2", "external"]


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    """One served model: what it can do, where its weights sit, what it occupies."""

    key: str
    served_model_id: str          # what the endpoint answers to
    base_url: str
    adapter: str                  # only "openai_compatible" today
    capabilities: frozenset[Capability]
    context_window: int
    max_output_tokens: int

    # Emits reasoning_content. A caller must leave headroom above the answer:
    # a reasoning model capped tight returns an empty string, not a short one
    # (MODEL_EVALUATION, "A small token budget breaks a reasoning model").
    emits_reasoning: bool

    # "" means withdraw the parameter entirely. vLLM 400s on "none";
    # ds4-server treats "none" as "do not think". Never guess this.
    reasoning_effort: str

    # Every host whose VRAM this model occupies. A TP=2 model occupies both.
    resident_on: tuple[Host, ...]
    weights_gb: float
    residency: Literal["always", "on_demand"]

    # Measured on this hardware, never taken from a model card, and dated
    # because a number without a date is not evidence.
    decode_tokens_per_second: float
    measured_on: date


@dataclass(frozen=True, slots=True)
class ModelRequirement:
    """What a node needs, stated as capabilities rather than as a name."""

    capabilities: frozenset[Capability]
    min_context: int = 0
    # The budget the caller will actually ask for, so a model that cannot
    # answer inside it is not selected in the first place.
    max_output_tokens: int = 1024


class NoModelSatisfies(RuntimeError):
    """No registered model has every requested capability. Never softened."""
```

The live descriptors, from `docker-compose.yml` and `docs/DGX_MIGRATION.md:230-232`:

```python
DEEPSEEK = ModelDescriptor(
    key="deepseek-v4-flash",
    served_model_id="deepseek-v4-flash",
    base_url="http://172.16.8.3:8000",          # ds4-head.service, rank 0
    adapter="openai_compatible",
    capabilities=frozenset({"text", "tool_calling", "schema_enforcement"}),
    context_window=1_000_000,
    max_output_tokens=8192,
    emits_reasoning=True,
    reasoning_effort="",                         # vLLM rejects "none"
    resident_on=("spark1", "spark2"),            # TP=2 spans both
    weights_gb=86.7,
    residency="always",
    decode_tokens_per_second=40.0,
    measured_on=date(2026, 8, 22),
)

QWEN3_VL = ModelDescriptor(
    key="qwen3-vl-8b",
    served_model_id="qwen3-vl-8b",
    base_url="http://172.16.8.5:8001",           # anios-vlm.service
    adapter="openai_compatible",
    capabilities=frozenset({"text", "vision_in", "schema_enforcement"}),
    context_window=32_768,
    max_output_tokens=2048,
    emits_reasoning=False,
    reasoning_effort="",
    resident_on=("spark2",),
    weights_gb=15.7,                             # not the ~10 budgeted
    residency="always",
    decode_tokens_per_second=0.0,
    measured_on=date(2026, 8, 23),
)

FLUX_KLEIN = ModelDescriptor(
    key="flux2-klein-4b",
    served_model_id="flux-2-klein-4b-fp8.safetensors",
    base_url="http://127.0.0.1:8188",            # ComfyUI on spark1
    adapter="comfyui",
    capabilities=frozenset({"image_out"}),
    context_window=0,
    max_output_tokens=0,
    emits_reasoning=False,
    reasoning_effort="",
    resident_on=("spark1",),
    weights_gb=6.5,
    residency="on_demand",
    decode_tokens_per_second=0.0,
    measured_on=date(2026, 8, 23),
)
```

Roles become **named requirements**, one per role that exists today in `backend/core/dependencies.py`:

```python
ROLES: dict[str, ModelRequirement] = {
    # get_llm_client / get_reasoning_llm_client
    "reply":     ModelRequirement(frozenset({"text"}), min_context=32_768, max_output_tokens=2048),
    "reasoning": ModelRequirement(frozenset({"text"}), min_context=32_768, max_output_tokens=2048),
    # get_routing_llm_client - MainActionSelector
    "routing":   ModelRequirement(frozenset({"tool_calling", "schema_enforcement"}), max_output_tokens=512),
    # get_structured_llm_client and everything that follows it
    "structured":       ModelRequirement(frozenset({"schema_enforcement"}), max_output_tokens=1024),
    "deck":             ModelRequirement(frozenset({"schema_enforcement"}), max_output_tokens=4096),
    "diagram":          ModelRequirement(frozenset({"schema_enforcement"}), max_output_tokens=1024),
    "memory_proposal":  ModelRequirement(frozenset({"schema_enforcement"}), max_output_tokens=512),
    "referent":         ModelRequirement(frozenset({"schema_enforcement"}), max_output_tokens=256),
    "artifact_context": ModelRequirement(frozenset({"schema_enforcement"}), max_output_tokens=96),
    # get_vision_provider
    "vision":     ModelRequirement(frozenset({"vision_in", "schema_enforcement"}), max_output_tokens=2048),
    "image":      ModelRequirement(frozenset({"image_out"})),
    "image_edit": ModelRequirement(frozenset({"image_edit"})),
    "embedding":  ModelRequirement(frozenset({"embedding"})),
}
```

Resolution, and the concurrency gate that §5 argues for:

```python
class ModelRegistry:
    """Resolve a capability request to exactly one model, or raise."""

    # Bound concurrency per physical host, never per model: two models sharing
    # a GPU contend, while two calls to one vLLM head batch and get faster.
    def __init__(
        self,
        descriptors: tuple[ModelDescriptor, ...],
        host_slots: dict[Host, int],
    ) -> None:
        self._descriptors = descriptors
        self._slots = {h: asyncio.Semaphore(n) for h, n in host_slots.items()}

    # Return the single model satisfying every requested capability.
    def resolve(self, requirement: ModelRequirement) -> ModelDescriptor:
        candidates = [
            d
            for d in self._descriptors
            if requirement.capabilities <= d.capabilities
            and d.context_window >= requirement.min_context
            and d.max_output_tokens >= requirement.max_output_tokens
        ]
        if not candidates:
            raise NoModelSatisfies(
                f"No model provides {sorted(requirement.capabilities)} "
                f"at >= {requirement.min_context} context"
            )
        # Deterministic and total: resident beats on-demand, faster beats
        # slower, name breaks the tie. This is an ordering, not a chain -
        # nothing falls through to second place at runtime.
        return min(
            candidates,
            key=lambda d: (d.residency != "always", -d.decode_tokens_per_second, d.key),
        )

    # Hold one slot on every host this model's weights occupy.
    @asynccontextmanager
    async def slot(self, descriptor: ModelDescriptor):
        async with AsyncExitStack() as stack:
            for host in sorted(set(descriptor.resident_on)):
                if host in self._slots:
                    await stack.enter_async_context(self._slots[host])
            yield descriptor
```

**The payoff, concretely.** `MAIN_LLM_STRUCTURED_OUTPUT` disappears. Today it is a boolean consulted by `get_structured_llm_client`, which six roles then chain through (`dependencies.py:295`). In the registry it is the word `"schema_enforcement"` in one descriptor's capability set. Flipping it is deleting one word, and every dependent role re-resolves on the next invocation. The comment at `dependencies.py:302-308` — "Expressed as a capability, the same promotion is safe and reverses itself" — is describing this design; it just doesn't have it yet.

**Capabilities are verified, not declared.** A descriptor claiming `schema_enforcement` is a claim about a live endpoint, and this repo's whole discipline is that claims get tested. `backend/cli/qualify_models.py` already probes native tool calling and schema adherence against a running model and returns pass/fail with latency. It becomes the registry's conformance harness: every descriptor's capability set must be reproduced by a probe, run in the deploy gate, so a false claim fails `scripts/gate.sh` rather than a user's turn.

---

## 3. Binding into the graph

**Decision: `RunnableConfig["configurable"]`, carrying the registry. Not closure injection, not a resolver in state.**

**Not state.** LangGraph checkpoints state. A descriptor written into state is serialised into the checkpoint, so a resumed thread rebinds to whatever model was resolved days ago — possibly unloaded, re-quantised, or gone. Model choice is a property of *this invocation*, not of the conversation.

**Not closure.** That is the status quo, compiled once at DI time, and it is why the six-role migration was six edits. It also makes A/B impossible without a redeploy — and `evaluate_reply_quality --save-a / --a-answers` exists precisely to run sequential collect-then-judge comparisons, which with `configurable` becomes a config change.

```python
# backend/agents/binding.py
"""Give every node one model, chosen from what it declared it needs."""

import operator
from dataclasses import dataclass
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from typing_extensions import TypedDict


@dataclass(frozen=True, slots=True)
class ModelEvent:
    """Which model actually served one node, recorded for the reply to cite."""

    node: str
    requirement: frozenset[str]
    resolved: str
    escalated_from: str | None = None


# Recover the registry the graph was invoked with, failing loudly if absent.
def registry_from(config: RunnableConfig) -> ModelRegistry:
    registry = (config.get("configurable") or {}).get("model_registry")
    if not isinstance(registry, ModelRegistry):
        raise RuntimeError("Graph invoked without a model_registry in configurable")
    return registry
```

A node, rewritten from `backend/agents/diagram/agent.py`:

```python
class DiagramState(TypedDict):
    query: str
    specification: NotRequired[DiagramSpecification]
    model_events: Annotated[list[ModelEvent], operator.add]


# Plan one mermaid source on whichever model can enforce the diagram schema.
async def plan_diagram(
    state: DiagramState, config: RunnableConfig
) -> dict[str, Any]:
    registry = registry_from(config)
    requirement = ROLES["diagram"]
    model = registry.resolve(requirement)
    async with registry.slot(model):
        specification = await plan_diagram_on(model, state["query"])
    return {
        "specification": specification,
        # Provenance is a state write, not a log line. This is what makes the
        # reply able to say which model wrote it - the exact thing
        # FallbackInferenceProvider could not do, and was deleted for.
        "model_events": [
            ModelEvent("plan_diagram", requirement.capabilities, model.key)
        ],
    }


workflow = StateGraph(DiagramState)
workflow.add_node("plan_diagram", plan_diagram)
workflow.set_entry_point("plan_diagram")
workflow.add_edge("plan_diagram", END)
DIAGRAM_GRAPH = workflow.compile()
```

Invocation — one compiled graph, any registry:

```python
await DIAGRAM_GRAPH.ainvoke(
    {"query": query, "model_events": []},
    config={"configurable": {"model_registry": registry, "thread_id": trace_id}},
)
```

Two consequences worth stating for the wider design:

- **`model_events` is the accumulator that makes multi-model honest.** Any turn can report the set of models that touched it. Make the reply-composition node read it.
- **The `only=` precedent generalises.** `MainActionSelector.select(only=frozenset(...))` (`main_action_selector.py:240`) narrows what a later step may *see*, structurally, rather than asking a prompt to behave. The registry is the same move for models: a node in an unattended scheduled run can be handed a registry with `image_out` withheld, and no prompt wording is involved.

---

## 4. Modality as first-class state

### What `visual_artifacts` gets right

Genuinely good, and all of it should survive:

- **Bytes are never in the row.** `storage_key` indirects to `BinaryArtifactStore`. This must carry into graph state verbatim — LangGraph checkpoints state to Postgres, so a 3 MB PNG in state means every checkpoint writes 3 MB.
- **Integrity travels with the reference**: `sha256`, `byte_size`.
- **Lineage is an edge, not a note.** `parent_artifact_id` is a real FK, and the comment at `models/artifact.py:53-56` explains why: recall resolves a whole chain by joining on it.
- **Provenance columns exist**: `provider`, `model`. Half the multi-model accountability problem is already solved at the persistence layer.
- **A real lifecycle**: `status` in (pending, ready, failed) plus `error_code`. A failed generation is a first-class state, not an absence.
- **Embeddings are versioned beside the vector**: `embedding_model`, `embedding_dimension`.
- **`to_dict` exposes `content_available`, not `storage_key`** — the API surface doesn't leak storage identity.

### What it gets wrong

1. **`kind` conflates modality with origin.** `'generated_image'` and `'uploaded_image'` are one modality with two histories. A node wanting pixels must enumerate kind strings; adding `'edited_image'` would break every such node. Should be `modality` × `origin`.
2. **`'diagram'` is not a modality.** It is a text source (mermaid, in `source`/`source_format`) that renders to an image. So `kind` mixes *what it is made of* with *what it is*, and a node holding a `'diagram'` cannot know whether `storage_key` or `source` carries the payload without special-casing.
3. **Decks are not in the table at all.** `presentations`, `presentation_revisions`, `presentation_jobs` are separate. So "everything this user owns" cannot be one query, and `ArtifactContextRouter` — constructed with `("image",)` at `dependencies.py:1614` despite its type already reading `Literal["image","document","audio","video"]` — can never gate a document, because there is nothing for it to gate.
4. **Modality-specific columns on a shared table.** `width`/`height` are image-only. Audio needs `duration_seconds`, documents need `page_count`. Column-per-modality does not scale; these belong in a typed descriptor blob.
5. **`Vector(768)` is hardcoded in the column type while `embedding_dimension` is also a column.** Those contradict. A future audio or document embedder with a different width cannot be stored.
6. **`source` is `Text`** — right for mermaid, wrong for a document body.

### The state model

```python
type Modality = Literal["text", "image", "document", "audio", "video"]
type Origin = Literal["uploaded", "generated", "edited", "rendered", "derived"]


@dataclass(frozen=True, slots=True)
class Payload:
    """Where an artifact's content is. Never the content itself."""

    mime_type: str
    storage_key: str | None = None     # binary, via BinaryArtifactStore
    inline_source: str | None = None   # mermaid, markdown, an ASR transcript
    source_format: str | None = None
    byte_size: int | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """One owned artifact, addressed by modality rather than by kind."""

    id: str
    modality: Modality
    origin: Origin
    status: Literal["pending", "ready", "failed"]
    payload: Payload
    parent_id: str | None = None
    produced_by: str | None = None        # ModelDescriptor.key
    title: str | None = None
    error_code: str | None = None
    # Modality-specific facts, so the envelope never grows a column per
    # modality: width/height, page_count, duration_seconds.
    descriptor: dict[str, Any] = field(default_factory=dict)


class ModalState(TypedDict):
    artifacts: Annotated[dict[str, ArtifactRef], merge_artifacts]
    # What "that one" refers to, resolved once by ReferentResolver rather than
    # re-guessed by every node that needs a picture.
    focus: tuple[str, ...]
    model_events: Annotated[list[ModelEvent], operator.add]
```

The accessor is the whole point — a node asks for a modality, never a kind:

```python
# Return the in-focus, ready artifacts of one modality, focus order preserved.
def focused(state: ModalState, modality: Modality) -> tuple[ArtifactRef, ...]:
    return tuple(
        artifact
        for key in state["focus"]
        if (artifact := state["artifacts"].get(key))
        and artifact.modality == modality
        and artifact.status == "ready"
    )
```

A vision node writes `focused(state, "image")` and correctly receives uploads, generations, edits, *and rendered diagrams* — because a rendered diagram is an image. Today it would have to know three `kind` strings, one of which may carry no bytes.

**Migration is additive, and must be.** The dev DB holds real user data with WAL archiving off and no replica; destructive DDL is banned here. So: add `modality`, `origin`, `descriptor` as nullable columns, backfill by pure function (`uploaded_image` → (image, uploaded); `generated_image` → (image, generated), or (image, edited) where `parent_artifact_id` is set; `diagram` → (image, generated) with the mermaid in `payload.inline_source`), and keep `kind` populated through the transition. Decks do **not** need a table move — `presentation_revisions` is the right editing model and revisions matter. Project each deck into an `ArtifactRef` with `modality="document"` at graph-entry time, which is enough to make the modality gate and recall see it.

Then `ArtifactContextRouter(get_structured_llm_client(), ("image",))` becomes `("image", "document")` with no prompt change — its prompt already describes documents.

---

## 5. Concurrency

**Plainly: yes, two models can be called concurrently today, and the lock does not prevent it — it never did. The constraint that actually binds is physical, not the lock.**

The lock does far less than it appears to:

- `self._request_lock = threading.Lock()` is created in `__init__` (`backend/core/llm.py:67`), so it is **per instance**.
- `get_llm_client()` and `get_routing_llm_client()` carry **no `@lru_cache`** (`dependencies.py:247`, `:259`), and neither does `get_conversation_service` (`:1549`). Every HTTP request builds fresh providers with fresh locks. Two concurrent turns share nothing.
- Even inside one turn, the reply role and the routing role are *different instances*, so they hold *different locks*. A graph that fans out to both already runs unserialised.
- The docstring — "Keep one client instance's request order deterministic across providers" — describes an intent the wiring does not deliver.

Contrast with the paths that got this right, and which show the correct shape: `get_image_provider` **is** `@lru_cache(maxsize=1)` and holds `asyncio.Semaphore(IMAGE_MAX_CONCURRENCY)` (`artifacts/image.py:161`), so that bound is genuinely process-wide. `get_embedding_provider` is cached and holds a `BoundedSemaphore`. The LLM path is the odd one out.

**What the architecture must therefore assume:**

1. **Do not add a global lock. vLLM wants concurrency.** Measured on this hardware (`MODEL_EVALUATION.md` §8): 85.7 tok/s at c=1, 135.7 at c=2, 282.6 at c=4, **383.5 at c=6**. Continuous batching turns concurrency into 4.5× aggregate throughput. Serialising at the client throws that away and makes every parallel branch in the graph pointless.

2. **The blast radius is per-host, not per-model.** The main model is TP=2 across spark1 and spark2 (`ds4-head.service` on spark1:8000, `ds4-worker.service` rank 1 on spark2). The VLM (`anios-vlm.service`) sits **on spark2**, on the same GPU as that rank-1 worker, and took 15.7 GB leaving ~1.4 GB. So a vision call and a main-model call contend for one card — and because TP=2 is a lockstep collective, a straggler on spark2 stalls the main model **for every user**, not just for that turn.

3. **Therefore the bound belongs on the host.** Unbounded fan-out to one endpoint is good; unbounded fan-out across endpoints sharing a GPU is not. This is exactly what `ModelRegistry.slot()` implements: acquire a semaphore for every host in `resident_on`, so a TP=2 model counts against both Sparks and a vision call contends with it correctly. Nodes get concurrency for free and cannot accidentally stampede spark2.

4. **Two fixes the graph should carry in.** Replace the per-request `httpx.Client` (`llm.py:280` — a new client, and so a new TCP connection, on every single call) with one pooled `httpx.AsyncClient` per endpoint held by the registry. And make the inference path natively async: today every call is sync httpx wrapped in `asyncio.to_thread`, so a six-way fan-out burns six OS threads doing nothing but blocking on a socket.

5. **One serialisation is real and must stay:** image generation. `IMAGE_MAX_CONCURRENCY` defaults to 1, FLUX loads on demand into spark1's ~9.9 GB, and over-allocation hangs the box. That semaphore is load-bearing.

---

## 6. What's missing, and what it costs

Budget: **spark1 ~9.9 GB free** (holds the TP=2 head *and* the entire application stack), **spark2 ~1.4 GB free** (full — the VLM overran its budget). Over-allocation on a GB10 hangs rather than OOM-kills, so the margin is not negotiable. **spark2 is closed for business.** Everything new lands on spark1's 9.9 GB, of which FLUX already claims 6.5 GB on demand.

The decisive insight for ordering: **documents and audio-in are converters, not new terminal modalities.** Both reduce to text and rejoin the existing graph with no downstream plumbing. Image-out and vision-in are the only genuinely non-text terminals, and both already exist. That makes the cheap things also the high-value things.

| Capability | Cost on this hardware | Verdict |
|---|---|---|
| **Documents in** (PDF/DOCX → text) | **~0 GB VRAM.** `pypdf` / `python-docx` on CPU. Scanned pages route to the *existing* Qwen3-VL-8B, already paid for. | **Do first.** |
| **Audio in** (ASR) | **~1.6 GB.** whisper-large-v3-turbo (809M) at fp16 on spark1. | **Do second.** |
| **Audio out** (TTS) | **~0.3 GB.** Kokoro-82M. Piper is ~60 MB and CPU-only if even that is tight. | Third, gated on a delivery surface. |
| **Stronger VLM** (`VISION_ESCALATION_*`, wired but unset) | Needs a second VLM; spark2 has 1.4 GB. **Does not fit.** | Not without hardware. |
| **Video in** | Does not fit and should not be attempted. | Approximate by sampling frames into the existing VLM. |

**Recommended order:**

1. **Documents.** Zero VRAM, and it activates machinery that is already built and inert: `ArtifactContextRouter`'s type already reads `"document"`, and its prompt already says "A document is required when the answer depends on the contents of one of their files." Adding `"document"` to the availability tuple plus a text-extraction node is most of the work. Biggest capability gain per byte, by a wide margin.
2. **Audio in.** ~1.6 GB, and the largest UX gain — voice notes over the iMessage bridge. Output is text, so nothing downstream changes.
3. **Audio out.** Cheap, but pointless until there is somewhere to send it.
4. **Video / escalation VLM.** Defer; these are hardware decisions.

**One hard requirement this creates.** ASR resident (1.6 GB) plus FLUX on demand (6.5 GB) is 8.1 GB of 9.9, leaving 1.8 GB — and a breach hangs the box rather than failing. So the registry must own a **per-host VRAM ledger with a reserve**: `residency="on_demand"` weights are refused a load when `sum(resident) + weights_gb > capacity - reserve`. That refusal is a clean `NoModelSatisfies`, which the graph already knows how to surface. This is the one place where "cost-aware" is real here, and the cost is gigabytes.

---

## 7. The trap, and how to avoid re-creating it

`JSONFallbackWriter` (94 lines) and `FallbackInferenceProvider` (86 lines) plus `MAIN_LLM_STANDBY_*` were deleted because, as `dependencies.py:238-245` records, "an outage did not fail, it silently answered worse, and nothing in the reply said which model had written it."

The principle is not "never fall back." It is:

> **Fall back on reachability. Never on quality. Never substitute downward on capability. Always leave a trace.**

Three failure classes, three different answers:

| Failure | Detectable? | Response |
|---|---|---|
| **Transport** — connection refused, timeout, 5xx | Yes, unambiguously | Retry the *same* model with backoff, then fail loudly. Legitimate resilience. |
| **Capability** — schema ignored, tool call malformed | Yes | **Never paper over with another model.** The descriptor lied. Fail the turn, and fail the gate. |
| **Quality** — the answer is worse | **No, not at runtime** | Never fall back on it. This is `JSONFallbackWriter` exactly. |

The middle row is the one that re-creates the mistake, because a schema failure looks locally like something another model could fix — and `JSONFallbackWriter` was born from precisely that reasoning. The registry's answer: a capability claim is a **tested property of a descriptor**, not a runtime hope. `qualify_models.py` proves it in the deploy gate. A model that fails the probe never enters the registry, so the runtime never meets the situation that tempts substitution.

Mechanically:

- **`resolve()` returns one model or raises.** There is no ranked chain to slide down. The ordering in `min(...)` is for determinism, not for failover — nothing consults second place at runtime.
- **Escalation upward is allowed and encouraged.** `vision_analysis_service.py:447` is the model to generalise: the VLM declares its own uncertainty (`needs_reasoning`, or `grounding == "unsupported"` with `unsupported_reason == "model_uncertain"` and candidates present), and the graph hands a **typed intermediate** — the observation text, not the pixels — to a *more* capable model. That is a capability escalation carrying a declared reason, and it is recorded in `model_events` with `escalated_from`. Downward substitution on failure is the banned move; upward escalation on declared uncertainty is the sanctioned one.
- **Every degradation is visible in state.** `model_events` accumulates across the graph, the reply node can cite it, and a turn served by anything other than first choice can say so. The deleted standby's defect was silence; the accumulator is the structural fix.
- **Resilience comes from capacity, not substitution** — retry, per-host bounded concurrency, prefix caching (measured 18.5× at our p90 prefix), queueing. None of those change the answer.

One inherited trap the registry should close permanently. `MODEL_EVALUATION.md` records that `reasoning_effort="none"` 400s on every vLLM request while ds4-server honours it, and that `llm.py` handles this by sending the value and withdrawing it on rejection (`_retry_without_reasoning`). That is a runtime probe standing in for a fact nobody wrote down. It is a **descriptor field** (`reasoning_effort=""` means withdraw), verified by the conformance probe. Keep `_retry_without_reasoning` as a belt, but the registry should mean it never fires.

---

## Build sequence

1. `ModelDescriptor` / `ModelRequirement` / `ModelRegistry` + `ROLES`, with `qualify_models.py` extended into a conformance probe wired into `scripts/gate.sh`. No graph changes. `MAIN_LLM_STRUCTURED_OUTPUT` becomes one capability word and is deleted.
2. `registry_from(config)` + `model_events`; convert the three existing graphs (`agents/graph.py`, `agents/diagram/agent.py`, `agents/deck/agent.py`) from closure injection to `configurable`. Behaviour-identical, and provably so.
3. Pooled async client per endpoint + per-host `slot()`. This is where the 4.5× batching gain becomes reachable.
4. `ArtifactRef` / `Payload` / `focused()`; additive migration on `visual_artifacts`; project decks into refs. Open `ArtifactContextRouter` to `("image", "document")`.
5. Document extraction, then ASR, against the VRAM ledger.

**Every step that adds or alters a prompt owes a functional test in `backend/tests/functional/`** — including step 4, which changes what the artifact-context prompt is offered. Structural tests will show the registry resolved and the node ran; they cannot show the answer got worse, which is the entire failure this axis exists to prevent.