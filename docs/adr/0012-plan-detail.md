# ADR 0012 - supporting detail: the full staged plan

The reasoning behind ADR 0012, kept because the probe outputs and the
rejected designs are the part that is expensive to re-derive. The ADR is
the decision; this is the evidence.

---

I ran the disputed claims rather than trusting any survey. Everything below is grounded in probes against the installed `langgraph 1.2.9` and the actual files.

---

# 1. THE ARCHITECTURE

## The decision that shapes everything

**The graph covers the answering half of the turn and nothing else.** `ConversationService.process_request` is *not* reduced. It stays the ~86-line async generator it is today (`conversation_service.py:1780-1865`), and that is the architecture, not a compromise.

Three probes forced this, and each one kills a different design's centrepiece:

```
$ python probe3.py           # a node downstream of a streaming node, consumer cancels
defer=True  cancel_after=None   deltas=5  persist_ran=['persist']
defer=True  cancel_after=2      deltas=2  persist_ran=[]
defer=False cancel_after=2      deltas=2  persist_ran=[]
```

No node downstream of `generate` runs when the SSE consumer disconnects — `defer` or not. And ten of the eleven `_persist_completed_turn` sites persist **before** their final yields (`:716` before the delta, `:835` before `artifact_ready`, `:956`, `:2798`…). Only the reply path (`:2687`) persists after. So moving persistence into a graph exit node makes ten paths lose turns on disconnect and improves none. Persistence stays where it is.

```
$ python probe2.py           # subgraph custom events
--- v1 no subgraphs      1 event   (the subgraph's search_started is GONE)
--- v2 subgraphs=True    2 events  ns=() and ns=('sub:<uuid>',)
```

Silent. No warning. This is the single sharpest trap in the whole space, and it lands in commit 3 before any subgraph exists.

```
$ python probe4.py
RAISED InvalidUpdateError At key 'hits': Can receive only one value per step.
nodes=1 compile=0.28ms   nodes=16 compile=3.16ms   nodes=30 compile=5.94ms
$ DEFAULT_RECURSION_LIMIT = 10007
$ langgraph.checkpoint.postgres  ->  False (not installed)
```

## `backend/agents/reply/state.py`

```python
"""The answering half of one turn, as the graph carries it.

No reducer appears anywhere in this schema, and that is a claim rather than an
omission: every key below is written by exactly one node, because this graph
has no parallel branch. The sequence it preserves is a real data dependency,
not habit - `_stream_web_search` composes its outbound query from the image
matches `_stream_retrieved_context` just found (conversation_service.py:1572),
and *that* string is what `search_privacy.sanitize` screens. Fan those two
apart and a different sentence leaves the machine, with nothing raised. A
channel one node writes needs no reducer; a reducer here would be a claim
about concurrency this graph does not have.

Nothing here is ever serialized: the graph compiles with no checkpointer, and
`langgraph.checkpoint.postgres` is not even installed. That is why
`plan_result` and `action` may be the live objects the services already pass
around. It is also the first thing that must change if a checkpointer is ever
added - after idempotency keys, never before, because LangGraph re-executes a
resumed node from the top and `ScheduledTaskRepository.create` has no dedupe
key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict


@dataclass(frozen=True, slots=True)
class TurnDeps:
    """Everything a node needs that belongs to one request, not one process.

    This exists so the graph can be compiled once per process instead of once
    per message. `build_assistant_graph(llm)` runs inside `__init__`
    (conversation_service.py:403) and `get_conversation_service` carries no
    `@lru_cache` (dependencies.py:1549), so today every message recompiles.
    These arrive at `astream(context=...)` and a node reads them off
    `runtime.context`.
    """

    service: Any          # the ConversationService; node bodies call its methods
    llm: Any              # LLMClient - a blocking httpx client, see `generate`


class ReplyState(TypedDict):
    # --- written by the caller, read by everything -----------------------
    user_id: str
    query: str
    conversation_id: str
    trace_id: str
    metadata: dict[str, Any]
    active_image_artifact_id: NotRequired[str | None]
    # Already downgraded by `_runnable` before it gets here. That downgrade
    # cannot be a conditional edge: it does not choose a route, it NULLS an
    # action whose service was never wired so the reply cannot describe it as
    # having run. An edge returns a destination and writes nothing.
    action: NotRequired[Any]
    extra_context: NotRequired[dict[str, Any] | None]
    # The turn's single clock reading. Two independent `datetime.now(UTC)`
    # evaluations - one to measure the prompt, one to send it - put a turn
    # straddling midnight on two different dates.
    now: NotRequired[str]

    # --- plan_context ----------------------------------------------------
    plan_result: NotRequired[Any]
    query_embedding: NotRequired[list[float] | None]

    # --- recall / retrieve / memory_write / compose_context ---------------
    history: NotRequired[list[dict[str, Any]]]
    context: NotRequired[dict[str, Any]]
    proposals: NotRequired[list[dict[str, Any]]]

    # --- measure / enforce / assemble -------------------------------------
    # Rendered once, and re-rendered only by `enforce`, which is the node that
    # invalidated it. `_build_system_prompt` runs twice per turn today
    # (graph.py:711 to measure, :736 to send) and the second render is the one
    # that ships, so the report certifies a prompt that was not sent - exactly
    # the property the comment at graph.py:706-708 claims to guarantee.
    system_prompt: NotRequired[str]
    budget_report: NotRequired[Any]
    prompt_messages: NotRequired[list[dict[str, str]]]

    # --- generate ---------------------------------------------------------
    # A real channel. Today the reply exists only in the caller's
    # `response_chunks`; `AssistantState.messages` - the one reducer in the
    # current schema - is written by the node and read by nothing, which is
    # precisely why no node can be placed after generation.
    reply: NotRequired[str]
```

## `backend/agents/reply/graph.py`

```python
"""The answering half, wired.

Read this file to know what happens between "the router decided" and "the
reply is on the wire". What is deliberately NOT here is named at the bottom,
with the reason for each.
"""

from functools import lru_cache
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from backend.agents.reply import nodes
from backend.agents.reply.state import ReplyState, TurnDeps
from backend.config import settings

# A node that writes nothing outside the process may be retried; every node
# that does is at-most-once. `retry_policy=None` is the "not specified"
# sentinel and inherits any graph default, so opting out is explicit.
AT_MOST_ONCE = RetryPolicy(max_attempts=1)
READ_ONLY = RetryPolicy(max_attempts=2, backoff_factor=2.0)


# Whether the measured plan is applied. Off by default: trimming changes what
# the model sees and no section priority here has been argued against real
# turn sizes yet (settings.py:144-154).
def _after_measure(state: ReplyState) -> Literal["enforce", "assemble"]:
    report = state.get("budget_report")
    if report is None or not report.dropped_total:
        return "assemble"
    if not settings.CONTEXT_BUDGET_ENFORCE:
        return "assemble"
    named = {item.name: item for item in report.allocations}
    # A window too small for the system prompt and the question cannot be
    # fixed by dropping enrichment; trimming would send a turn missing its own
    # question. `enforce` logs the refusal loudly and this edge skips it.
    if not (named["system"].complete and named["query"].complete):
        return "assemble"
    return "enforce"


# Build the answering graph. Cached, so it is compiled once per process
# instead of once per request - but lazily, on first use, NOT at import:
# six services build from the root Dockerfile and an import-time compile turns
# any construction error into a simultaneous boot failure across all of them.
@lru_cache(maxsize=1)
def build_reply_graph() -> Any:
    g = StateGraph(ReplyState, context_schema=TurnDeps)

    g.add_node("plan_context",    nodes.plan_context,    retry_policy=READ_ONLY)
    g.add_node("recall",          nodes.recall,          retry_policy=READ_ONLY)
    # One node, on purpose. Inside it the image -> search -> tool order is the
    # data dependency described in state.py. Splitting it into three parallel
    # nodes changes the outbound search string.
    g.add_node("retrieve",        nodes.retrieve,        retry_policy=AT_MOST_ONCE)
    # Strictly upstream of `assemble`, and this edge is the whole reason.
    # Proposals auto-save with no approval round-trip, so the honest state to
    # hand the model is "saved". Told only "you cannot save", it answered
    # "your personal memory has been updated" - true-sounding, passive, and
    # wrong. `_render_save_state` returns "" for a falsy dict, so an ordering
    # mistake here removes the block entirely rather than raising.
    g.add_node("memory_write",    nodes.memory_write,    retry_policy=AT_MOST_ONCE)
    g.add_node("compose_context", nodes.compose_context, retry_policy=AT_MOST_ONCE)
    g.add_node("measure",         nodes.measure)
    g.add_node("enforce",         nodes.enforce)
    g.add_node("assemble",        nodes.assemble)
    # The only sync node in the graph, deliberately. `llm.stream_chat` is a
    # blocking generator behind a threading.Lock; LangGraph runs a sync node
    # on a worker thread (probed: name 'asyncio_0', main? False), so the event
    # loop stays free. Making this `async def` would stall every concurrent
    # turn and the iMessage bridge with it. No retry: half a reply is already
    # on the wire.
    g.add_node("generate",        nodes.generate,        retry_policy=AT_MOST_ONCE)

    g.add_edge(START, "plan_context")
    g.add_edge("plan_context", "recall")
    g.add_edge("recall", "retrieve")
    g.add_edge("retrieve", "memory_write")
    g.add_edge("memory_write", "compose_context")
    g.add_edge("compose_context", "measure")
    g.add_conditional_edges("measure", _after_measure,
                            {"enforce": "enforce", "assemble": "assemble"})
    g.add_edge("enforce", "assemble")
    g.add_edge("assemble", "generate")
    g.add_edge("generate", END)

    return g.compile(name="reply")


# What is NOT in this graph, and why. Each of these was tried on paper and
# each one is a regression, not a simplification.
#
#   persistence - `_persist_completed_turn` stays at its eleven call sites.
#     Probed: no node downstream of a streaming node runs when the SSE
#     consumer disconnects, `defer=True` or not. Ten of the eleven sites
#     persist BEFORE their final yields today, so an exit node would lose
#     those turns on every dropped connection, into a database with no
#     backups.
#
#   routing and branch dispatch - `_generating_branch` picks a route AND
#     `_runnable` nulls an unrunnable action. A conditional edge can do the
#     first and not the second, so collapsing them into one edge silently
#     carries a CreateDiagramAction with no diagram service into the reply as
#     though it had run.
#
#   the decide/act cycle - `turn_steps.run_steps` keeps five stopping rules
#     over `seen: set[str]`, `created: int` and a `monotonic()` clock. As
#     graph edges those need a set-union reducer, a counter reducer and a
#     first-write-wins clock, and a graceful `break` that still answers
#     becomes a GraphRecursionError thrown after tokens are on the wire.
#     Its module docstring records why it lives outside ConversationService:
#     "a test that reimplements the loop proves the reimplementation".
#
#   a checkpointer - not installed (langgraph.checkpoint.postgres is absent),
#     not needed (continuity is `repository.get_history`, there is no
#     approval gate), and actively harmful: resume re-runs a node from the
#     top and every write on this path is unkeyed.
```

## `backend/agents/reply/nodes.py` — the shape of a node

```python
# Plan what context this turn needs and embed the question once.
#
# The vector is computed here and threaded through every downstream consumer.
# `_load_image_matches` and `_load_visual_memory_matches` both re-embed when
# handed none, so a state key is the difference between one embedding and
# three.
async def plan_context(state: ReplyState, runtime: Runtime[TurnDeps]) -> dict:
    svc = runtime.context.service
    plan_result = None
    if svc.memory_coordinator is not None:
        plan_result = await svc.memory_coordinator.plan(state["user_id"], state["query"])
    plan = plan_result[0] if plan_result is not None else None
    need_semantic = plan is None or plan.use_semantic
    need_vector = svc.memory_coordinator is not None and (plan is None or plan.needs_vector())
    embedding = (
        await svc.memory.embed_query(state["query"])
        if (need_semantic or need_vector) else None
    )
    return {"plan_result": plan_result, "query_embedding": embedding}


# Attach optional image, search and tool context, in that order.
#
# The body is `_stream_optional_context` unchanged, with one mechanical
# substitution: it pushed events with `yield`, and pushes them with `emit`
# here. The order is load-bearing - see the note in state.py - so this is one
# node and not three.
async def retrieve(state: ReplyState, runtime: Runtime[TurnDeps]) -> dict:
    svc = runtime.context.service
    context = state["context"]
    async for event in svc._stream_optional_context(
        context, state["user_id"], state["query"], state["conversation_id"],
        state["trace_id"], state.get("query_embedding"), state.get("action"),
        state.get("active_image_artifact_id"), history=state.get("history"),
    ):
        emit(event["event"], **event["data"])
    return {"context": context}


# Measure the turn against the window, once, against the prompt that will
# actually be sent.
async def measure(state: ReplyState, runtime: Runtime[TurnDeps]) -> dict:
    system_prompt = _build_system_prompt(state["context"], now=state["now"])
    report = measure_turn(
        state["context"], state.get("history") or [], state["query"], system_prompt
    )
    if report is not None:
        logger.info("trace=%s %s", state["trace_id"], report.summary())
        record_context_report(report, state["trace_id"])
    return {"system_prompt": system_prompt, "budget_report": report}


# Trim the inputs to fit, then re-render the prompt from what survived.
#
# The re-render is the point. `_apply_report` trims episodic and semantic
# memory, which `_build_system_prompt` embeds; without rendering again, the
# report describes a prompt that was not sent.
async def enforce(state: ReplyState, runtime: Runtime[TurnDeps]) -> dict:
    context, history = _apply_report(
        state["context"], state.get("history") or [], state["budget_report"]
    )
    logger.info("trace=%s enforced: dropped %d item(s) to fit the window",
                state["trace_id"], state["budget_report"].dropped_total)
    return {
        "context": context,
        "history": history,
        "system_prompt": _build_system_prompt(context, now=state["now"]),
    }
```

`_build_system_prompt`, `_build_turn_context` and `turn_context_messages` stay module-level in `backend/agents/graph.py` and importable outside a graph run. Eight test files and `backend/cli/evaluate_reply_quality.py` depend on that seam; it is a hard requirement, not an accident.

## The streaming contract

`backend/agents/reply/emit.py`:

```python
# Push one interface event from inside a node.
#
# The name is checked here because the arrangement this replaces dropped
# anything the consumer did not recognise and said nothing anywhere:
# conversation_service.py:2678 tested `type == "message.delta"` and discarded
# every other custom event, so a second event kind was a no-op with no error.
def emit(event: str, **data: Any) -> None:
    if event not in _KINDS:                      # derived from ChatStreamEvent
        raise ValueError(f"{event!r} is not a ChatStreamEvent kind")
    get_stream_writer()({"event": event, "data": data})
```

## `_process_assistant_request` — what it becomes

From 171 lines to ~40:

```python
async def _process_assistant_request(self, user_id, query, conversation_id,
                                     trace_id, metadata, active_image_artifact_id=None,
                                     preselected_action=None, extra_context=None):
    seed: ReplyState = {
        "user_id": user_id, "query": query, "conversation_id": conversation_id,
        "trace_id": trace_id, "metadata": metadata,
        "active_image_artifact_id": active_image_artifact_id,
        "action": preselected_action, "extra_context": extra_context,
        "now": datetime.now(UTC).isoformat(),
        "context": {}, "proposals": [],
    }
    self.tracer.log_step(trace_id, "graph_execution", {"status": "started"})
    final: dict[str, Any] = {}
    async for part in build_reply_graph().astream(
        seed,
        context=TurnDeps(service=self, llm=self.llm),
        stream_mode=["custom", "values"],
        subgraphs=True,     # without it a subgraph's events vanish silently
        version="v2",       # probed: yields {'type','ns','data'} dicts
    ):
        if part["type"] == "custom":
            yield part["data"]          # already a ChatStreamEvent
        else:
            final = part["data"]        # last `values` chunk carries the reply
    self.tracer.log_step(trace_id, "graph_execution", {"status": "completed"})

    # Persistence stays HERE, at the call site, not in an exit node: a node
    # after `generate` does not run when the client disconnects.
    await self._persist_completed_turn(TurnRecord(
        user_id=user_id, conversation_id=conversation_id, query=query,
        response_text=final.get("reply", ""), trace_id=trace_id,
        history=final.get("history") or [], metadata=metadata,
        query_embedding=final.get("query_embedding"),
    ))
    for proposal in final.get("proposals") or []:
        yield {"event": "memory_proposal", "data": proposal}
    yield {"event": "done", "data": {}}
```

Verified shape (`probe5.py`): `stream_mode=["custom","values"]` + `version="v2"` yields `{'type':'values',...}` then `{'type':'custom',...}` per token then a final `values` carrying `reply='hello'`, and the sync node ran on thread `asyncio_0`.

---

# 2. WHY THIS AND NOT THE OTHERS

## Spine: **migration-first**

It alone picked the seam that has a regression oracle. `process_request` is driven by 25+ tests in `backend/tests/test_chat_api.py` (lines 266, 319, 379, 409, 478, 505, 540, 561, 595, 633, 665, 713, 757, 803, 875, 919), including two that assert event ordering. Keeping its signature means every commit is checked by something that already exists. The other two designs dissolve it and lose that.

Its no-checkpointer argument is also the correct one, and it argued it from the code rather than from taste. I verified `langgraph.checkpoint.postgres` is not installed at all.

## Grafted in

**From purist:** the `emit()` name check derived from `ChatStreamEvent`; `version="v2"` + `subgraphs=True` landing before any subgraph exists; `reply` as a real state channel replacing the dead `messages` reducer; the measure/enforce/assemble split with one clock; the `langgraph>=0.0.30` pin; both latent defects as prerequisites. Its `create_agent` rejection is right and I confirmed the premise — `langchain` is absent, only `langchain-core 1.5.0`.

**From extensibility-first:** `TurnDeps` + `context_schema` (`StateGraph(..., context_schema=...)` exists in 1.2.9), which is the single genuinely free win in the whole space; pointer-state discipline; freezing the prompt bytes as an explicit precondition.

## Dropped, with the finding that killed it

| Dropped | Killed by |
|---|---|
| One deferred exit node for persistence | My probe: no downstream node runs on consumer cancel, `defer` or not. Ten of eleven sites persist *before* streaming today (`:716`, `:835`, `:956`, `:2798`…). Hoisting loses turns into a database with no backups. |
| Any checkpointer | `langgraph.checkpoint.postgres` not installed; anios_db has no backups; resume re-runs nodes from the top and `ScheduledTaskRepository.create` has no dedupe key. |
| `UntrackedValue` for `history` | Only meaningful with a checkpointer, and a judge reproduced it reading back as `None` after resume — silent amnesia. Without a checkpointer it is a solution to a problem this repo does not have. |
| Parallel retrieval fan-out + `merge`/`extend` reducers | `conversation_service.py:1572`: `outbound_query = _image_aware_search_query(chosen_query, image_matches)`, then `search_privacy.sanitize`. Fanning out changes what leaves the machine. Confirmed by reading the chain at `:1483-1535`. Removing the fan-out removes the reducers' only justification. |
| `run_steps` → `act ⇄ decide_next` edges | Five guards over a set, a counter and a clock; `break` becomes `GraphRecursionError` after tokens ship; `DEFAULT_RECURSION_LIMIT` is **10007**, not a bound; and the module docstring states the seam exists so the real loop can be tested. |
| `after_route` collapsing `_generating_branch` + `_runnable` | `_runnable` (`:319`) does not route — it nulls the action. A path function returns a destination and writes nothing. |
| The `AGENTS` registry as graph dispatch | Scout has **no** MainAction (`grep scout backend/tools/actions.py backend/tools/registry.py` returns nothing) — it is a cron in `discovery-worker`. MCP tools are shortlisted per-user at request time and cannot be static nodes. The deck's gate is `not metadata.get("scheduled_task")` (`:1892`) — a per-turn condition no `services` dict can express. |
| Compile-at-import | Six services build from the root Dockerfile; an import-time compile turns a construction error into a simultaneous fleet boot failure. `@lru_cache` on a lazy builder gets compile-once without that. |
| v3 typed streaming | `astream` on 1.2.9 accepts `version: 'v1'|'v2'` only. `LLMClient` is raw httpx, not a `BaseChatModel`, so `stream.messages` would be empty. |

---

# 3. THE STAGED PLAN

Ten commits, straight to `main`. `bash scripts/gate.sh` green on every one. Nothing is down longer than `docker compose up -d --no-deps <service>`.

**C1 — Pin the runtime and kill two latent defects.**
*Files:* `requirements.txt:10`, `pyproject.toml:17`, `conversation_service.py:1950`, `:403`.
`langgraph>=0.0.30` → `langgraph>=1.2.9,<2`. `await` the `_local_now` coroutine. Assign `self.llm = llm`.
*Live effect:* none. *Revert:* `git revert`, redeploy. *Proof:* §6.

**C2 — Frontend tolerates unknown events. Deploy first, alone.**
*Files:* `frontend/src/services/api.ts:1608`.
`parseChatEvent` currently `throw new Error('Chat stream contained an unknown event')` on any name outside a 17-item allowlist — one unknown frame kills the browser stream. Change to skip. Needs a gateway rebuild and redeploy to deep-matter.com; the gateway is a one-shot static build.
*Live effect:* none (nothing emits a new name yet). *Revert:* revert + rebuild. *Proof:* Playwright/manual — a hand-injected `event: nonsense` frame no longer aborts the stream.
**This must be live before C3.** The iMessage worker (`:643`) and task runner (`:217`) already ignore unknowns; only the browser is brittle.

**C3 — The custom channel becomes the wire contract.**
*Files:* `backend/agents/graph.py:754`, `backend/agents/reply/emit.py` (new), `conversation_service.py:2674-2681`.
Node writes `{"event":"delta","data":{"content":chunk}}`; consumer switches to `astream(stream_mode=["custom","values"], subgraphs=True, version="v2")` and relays `part["data"]`, keeping the legacy `type=="message.delta"` branch alongside.
*Live effect:* none — byte-identical SSE. *Revert:* `git revert`. *Proof:* `pytest backend/tests/test_chat_api.py -q` (event ordering assertions at 672-673, 546, 722).
`subgraphs=True` lands **here**, before any subgraph exists, because without it a subgraph's events vanish with nothing raised.

**C4 — One persistence contract, guarded.**
*Files:* new `TurnRecord` dataclass; all 11 `_persist_completed_turn` sites.
All eleven already share the same signature; the variance is only `response_text` and `metadata`. One frozen dataclass at each existing call point, plus an in-process `_saved: set[str]` guard on `trace_id` so a double-call is a logged no-op rather than a duplicate row.
*Live effect:* none. *Revert:* `git revert`. *Proof:* `pytest backend/tests/test_chat_api.py backend/tests/test_diagram_artifacts.py -q` + a new unit test that calls twice and asserts one `save_turn`.

**C5 — `ReplyState`, `TurnDeps`, compile once.**
*Files:* new `backend/agents/reply/{state,graph,nodes}.py`; `conversation_service.py:403` and `:2662-2682`.
Still exactly one node. `AgentState` (`backend/agents/state.py`) is deleted — one construction site, no test imports, and two of its six fields were being silently dropped by the graph schema. `now` is frozen into the seed.
*Live effect:* none; removes a per-request 0.28 ms compile. *Revert:* `git revert`. *Proof:* gate + a byte-equality assertion that `prompt_messages` matches a direct `_build_system_prompt` + `turn_context_messages` call.

**C6 — Split the node into measure / enforce / assemble / generate.**
*Files:* `backend/agents/reply/{graph,nodes}.py`, `backend/agents/graph.py` (helpers stay module-level).
One system-prompt render, one clock, and `enforce` re-renders after trimming.
*Live effect:* **the first real one** — the midnight date split and the report/prompt drift stop. *Revert:* `git revert`.
*Proof:* gate, `pytest backend/tests/test_cache_ordering.py`, **plus a new `backend/tests/functional/test_reply_graph_behaviour.py`** run with `ANIOS_REQUIRE_FUNCTIONAL=1` asserting on a real reply — evidence still cited, save-state still reported honestly. Prompt assembly moved; a structural test proves the call happened and cannot tell you the answer got worse.

**C7 — The rest of the spine, behind `REPLY_GRAPH_FULL` (default `False`).**
*Files:* `backend/agents/reply/nodes.py`, `conversation_service.py`.
`plan_context`, `recall`, `retrieve`, `memory_write`, `compose_context` become nodes. `retrieve` calls `_stream_optional_context` unchanged, substituting `emit` for `yield`. `_process_assistant_request` keeps its current body as the frozen `else` branch — **frozen, not maintained**, which is what stops the two-implementations drift.
*Live effect:* none while the flag is off. *Revert:* env var + restart.
*Proof:* `bash scripts/gate.sh --all` with the flag both ways; the functional test from C6 must pass under both.

**C8 — Flip the flag, one service at a time.**
`REPLY_GRAPH_FULL=true` on `backend` only; leave `discovery-worker` on legacy for a day, then flip both.
*Live effect:* the graph serves real traffic. *Revert:* env var + `docker compose up -d --no-deps backend`. Note: never a bare `docker compose up -d` on spark1 — redis is still on an anonymous volume and holds the iMessage cursor.
*Proof:* the real iMessage thread, and turn rows read back.

**C9 — Delete the legacy path and the flag. ← POINT OF NO RETURN.**
Removes the frozen `else` branch and `REPLY_GRAPH_FULL`. Every commit before it reverts with an env var and a restart; this one is the first where reverting needs a code change and a redeploy.
*What makes it safe:* it lands only after C8 has served live traffic for at least a week with no incident, the C6 functional test green under `ANIOS_REQUIRE_FUNCTIONAL=1`, and `test_chat_api.py`'s 25 turns passing. And it is safe *at all* only because C1-C8 never touched persistence ordering, never added a checkpointer, and never reordered retrieval — so the only thing being deleted is a duplicate of code that has already been proven in production.

**C10 — Optional, and I would drop it: the search subgraph.**
The one part worth taking from it is three lines: `search_planner.compose/refine/another_angle` are synchronous blocking model calls awaited inline in an async generator (`:1569, 1695, 1701, 1703`), two or three per search turn, on a server `memory/coordinator.py:305` already learned to protect. Wrap them in `asyncio.to_thread`. Do that as its own commit. The subgraph itself buys visibility into rounds 2 and 3, which needs a frontend renderer nobody has asked for. See §5.

---

# 4. WHAT THIS FIXES

Concrete failing behaviours, not classes of risk:

1. **A turn that straddles UTC midnight measures one date and sends another.** `_build_system_prompt` is called at `graph.py:711` and again at `:736`; both default `now=None` and independently evaluate `datetime.now(UTC)` at `:367`. Fixed by C5 (`now` in the seed) + C6 (one render).

2. **The budget report certifies a prompt that was not sent.** `_apply_report` trims `episodic`/`semantic` (`:655-661`); `_build_system_prompt` embeds up to five of each (`:394-400`). The comment at `graph.py:706-708` claims "planned and sent are the same thing by construction". They are not. C6's `enforce` re-render makes the claim true.

3. **Every turn renders the full system prompt twice** and re-serializes the personal-memory JSON twice. C6.

4. **Any custom event that is not `message.delta` is silently discarded** at `:2678`. Adding an event kind is a no-op with no error anywhere. C3, and `emit()` raises on an unknown name.

5. **The reply does not exist inside the graph.** `AssistantState.messages` — the only reducer in the schema — is written by the node and read by nothing; `conversation_service.py:2684` reassembles the text from the stream. This is why no node can follow generation. C5/C6.

6. **History is loaded twice per turn** for the same conversation (`:1803` and `:2579`), and the query is re-embedded when `_load_image_matches`/`_load_visual_memory_matches` are handed no vector. C7.

7. **`metadata or {}` is re-derived at five call sites** (`:1810, 1826, 1842, 1846, 1860`). C5.

8. **`langgraph>=0.0.30` is an API-incompatible floor.** `get_stream_writer` does not exist in 0.0.x and `stream_mode="custom"` is far later; a clean install near the floor is an `ImportError` at `graph.py:6`, not a degraded runtime. Same class as the two open-pin scars `requirements.txt` already carries. C1.

9. **`local_now=self._local_now(user_id)` at `:1950` is an un-awaited coroutine** — truthy, so `MainActionSelector` renders `Current date and time: <coroutine object ...>` into the step-2 routing prompt. **This is the blocker on `NEXT_SESSION.md` decision 1.** `TURN_MAX_STEPS=3` cannot be flipped safely until C1 is live, because a task dated in the past fires the moment the worker looks. C1.

10. **`self.llm` is read at `:2044` and `:2287` and never assigned** — `AttributeError` for any composition where `main_action_selector` is None. C1.

11. **The `discovery-worker` has no `ROUTING_LLM_MODEL`** (NEXT_SESSION, open) — not fixed by this work, and `TurnDeps` makes it *visible*: the deps record names what a turn depends on in one place, which is where a missing model setting becomes obvious rather than latent.

Explicitly **not** fixed, and I will not pretend otherwise: `opinion_about_image` → `edit_image` 4/51, `agent_config` 0/12, `writing_followup` 6/12. Those are routing defects. Every one of them lives upstream of this graph, in `MainActionSelector`. `agent_config` in particular is diagnosed correctly in NEXT_SESSION as needing a structural fix (its own tool, or Scout's sweep as an ordinary scheduled task) — no graph shape changes it.

---

# 5. WHAT IT COSTS

**Latency.** Nine sequential supersteps with no checkpointer add roughly 1-3 ms of Pregel overhead per turn — against a 1.78 s median routing call and a multi-second generation, that is under 0.2%. The graph *removes* more than it adds: one full system-prompt render plus one personal-memory JSON serialization (C6), one duplicate `get_history` round-trip (C7), and the 0.28 ms per-request compile (C5). Net: slightly faster.

**Memory.** Zero new persistent storage. No checkpointer means no checkpoint tables, so the O(N²) growth story — a 200-turn thread at 5.3 GB — never applies. `ReplyState` holds the same dicts the generator already held as locals, held once instead of threaded. The `@lru_cache` graph is one compiled object per process. spark1's ~9.9 GB free is untouched, which matters because FLUX.2-klein-4B at 6.5 GB is still waiting for that budget.

**Complexity.** Nine nodes, one conditional edge, zero reducers, no checkpointer, no `Command`, no `interrupt`, no subgraph. That is genuinely simpler than 171 lines of sequential async generator with a `context` dict mutated in place by four functions and replaced wholesale by a fifth.

**What is not worth it, and should be dropped from scope:**

- **The search subgraph (C10).** The round loop works. Making it a cycle buys visibility into rounds 2 and 3, which the frontend cannot render without a new component nobody has asked for — and the alternative (three indicators for one logical search) is a UI regression the other direction. Take the three-line `asyncio.to_thread` fix and leave the loop alone.
- **The unique index on `conversations`.** I considered `(conversation_id, trace_id)` as an idempotency key. It is genuinely valuable and genuinely independent — but it is **not a precondition for anything here**, because no node in this design re-runs. Ship it on its own merits, after C9, with `scripts/backup-db.sh` first and `CREATE UNIQUE INDEX CONCURRENTLY` so it fails loudly on existing duplicates rather than resolving them. Do not couple it to the graph.
- **`_ROW_FOR_ACTION` / `_detail` / `describe_action` / `waiting_line` keyed by `capability_id` instead of by type.** This is the real extensibility win — roughly forty lines, no graph — and it is the reason a second `DelegateAction` currently inherits the deck's label. It belongs in this repo's near future and it belongs in a different commit series.

---

# 6. THE FIRST COMMIT, IN FULL

**Three edits, four files, zero live effect, and it unblocks a decision already waiting in `NEXT_SESSION.md`.**

### `requirements.txt` line 10
```diff
-langgraph>=0.0.30
+# 0.0.x has no `langgraph.config.get_stream_writer` and no
+# `stream_mode="custom"`, so a clean install resolving near the old floor was
+# an ImportError at backend/agents/graph.py:6, not a degraded runtime. Same
+# open-pin failure as the two already recorded in this file.
+langgraph>=1.2.9,<2
```

### `pyproject.toml` line 17
```diff
-    "langgraph>=0.0.30",
+    "langgraph>=1.2.9,<2",
```

### `backend/services/conversation_service.py` line 1950
```diff
-                local_now=self._local_now(user_id) if query else None,
+                local_now=await self._local_now(user_id) if query else None,
```
`_local_now` is `async def` (`:592`). Un-awaited it is a coroutine object, and a coroutine is truthy, so `main_action_selector.py:318` renders `Current date and time: <coroutine object ConversationService._local_now at 0x…>` straight into the step-2 routing prompt. Latent only because `TURN_MAX_STEPS` ships at 1. The sibling call at `:494` awaits correctly.

### `backend/services/conversation_service.py` line 403
```diff
         self.memory = memory
+        # Read at :2044 and :2287 when no main action selector is wired.
+        # Unreachable in the assembled app and an AttributeError everywhere
+        # else, which is exactly the kind of thing a test double finds first.
+        self.llm = llm
         self.assistant_graph = build_assistant_graph(llm)
```

### The command that proves it

```sh
# 1. the pin resolves to what is actually installed
.venv/Scripts/python.exe -c "import importlib.metadata as m; \
  v=m.version('langgraph'); assert v.startswith('1.2'), v; print('langgraph', v)"

# 2. neither defect survives - both assert on real objects, not on the diff
.venv/Scripts/python.exe - <<'PY'
import ast, inspect
import backend.services.conversation_service as cs

src = inspect.getsource(cs.ConversationService._task_turn_context)
tree = ast.parse(inspect.cleandoc(src))
calls = [n for n in ast.walk(tree)
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
         and n.func.attr == "_local_now"]
assert calls, "no _local_now call found - did the line move?"
for c in calls:
    parents = [p for p in ast.walk(tree) if isinstance(p, ast.Await)
               and (p.value is c or (isinstance(p.value, ast.IfExp) and p.value.body is c))]
    assert parents, "_local_now is passed un-awaited"
print("local_now: awaited")

assert "self.llm = llm" in inspect.getsource(cs.ConversationService.__init__)
print("self.llm: assigned")
PY

# 3. nothing regressed structurally
.venv/Scripts/python.exe -m pytest backend/tests/test_chat_api.py \
    backend/tests/test_diagram_artifacts.py -q -p no:cacheprovider

# 4. the deploy gate, which is what deploy.sh blocks on
bash scripts/gate.sh          # 7 passed, 0 skipped, ~3 min
```

### The behavioural proof, which the above cannot give

The gate measures routing tool selection; it cannot see a prompt field. Add one case to `backend/tests/functional/test_task_reschedule_behaviour.py` that drives a **second** routing step at `TURN_MAX_STEPS=2` against the real router and asserts the rendered clock line matches a date shape, not `<coroutine`. Run it with a skip counting as a failure:

```sh
ANIOS_REQUIRE_FUNCTIONAL=1 bash scripts/gate.sh \
    backend/tests/functional/test_task_reschedule_behaviour.py
```

### Revert
`git revert <sha>` and redeploy. No schema change, no data change, no flag.

### What this unblocks
`NEXT_SESSION.md` decision 1 — flipping `TURN_MAX_STEPS` from 1 to 3 — is currently unsafe for exactly this reason. After this commit it is the env change and restart that document already describes.

---

## WHAT TO CHECK FIRST WHERE THE SURVEYS LEFT IT OPEN

| Unknown | How to settle it |
|---|---|
| Is `CONTEXT_BUDGET_ENFORCE` ready to turn on? | `wc -l data/telemetry/context_reports.jsonl` on spark1 and histogram `dropped_total` by section. The priorities have never been argued against real turn sizes; C6 makes the report trustworthy for the first time, so measure *after* C6, not before. |
| Does the `enforce` path ever actually run? | It has never fired in production (`CONTEXT_BUDGET_ENFORCE=False` since it was written). Before C6 ships, drive it once with the flag on in the functional container and diff the assembled prompt against the report. |
| Do the six uncounted context collections matter? | `working`, `entities`, `knowledge`, `summaries`, `procedures`, `toolbox` are embedded in the system prompt with no `Section` in `_turn_sections`, so they are invisible to the budget and untrimmable. After C6, `stream_mode=["updates"]` gives a per-node trace for free — measure their token share on ten real turns before deciding whether to give them sections. |
| Does the double-count between `system` and `memory` sections distort the plan? | Same trace. Episodic/semantic are counted once inside untrimmable `system` and again in trimmable `memory` (priority 6), so trimming `memory` cannot recover what the same memories cost in the prompt. |
| Is `discovery-worker`'s missing `ROUTING_LLM_MODEL` still latent? | `docker compose exec discovery-worker env | grep -E 'ROUTING|MAIN_LLM'`. Same model today; it stops being latent the moment the two diverge. |