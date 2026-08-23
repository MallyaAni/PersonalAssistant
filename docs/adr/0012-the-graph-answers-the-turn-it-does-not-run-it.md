# ADR 0012: The graph answers the turn; it does not run the turn

## Status

Accepted 2026-08-23 and **implemented**. Commits 1-6 landed and deployed;
commits 7-9 were reconsidered and dropped, for the reason under
*Amendment* below.

## Context

LangGraph has been a dependency since the beginning and has never been used as
a graph. `backend/agents/graph.py` is 763 lines of which about 690 are
module-level prompt helpers; the graph itself is:

```python
workflow.add_node("assistant", assistant_node)
workflow.set_entry_point("assistant")
workflow.add_edge("assistant", END)
```

One node, straight to `END`, compiled with no checkpointer. There are no
conditional edges, no subgraphs, no `Send`, no `Command`, no `interrupt`, and
no `START` constant anywhere in `backend/`. The only reducer in the state
schema is on a `messages` key that the sole caller never reads.

Everything that decides *what a turn does* happens outside it, in
`ConversationService.process_request`: routing, skill resolution, tool
execution, the search loop, the generating branches, persistence. A bounded
step loop (`backend/services/turn_steps.py`) was added on 2026-08-23 above the
graph rather than inside it, which is what prompted the question of whether the
turn should be a graph at all.

The obvious answer - "the turn IS the graph, invert `ConversationService`" -
was designed three times from different angles and judged nine times. Every
version scored between 3.2 and 4.5 out of 10, and the judges' strongest
findings came from executing code against the installed `langgraph 1.2.9`
rather than reasoning about it.

## Decision

**The graph covers the answering half of a turn and nothing else.**
`ConversationService.process_request` stays the async generator it is today.
That is the architecture, not a compromise.

`backend/agents/reply/` holds a nine-node `StateGraph`:

```
START -> plan_context -> recall -> retrieve -> memory_write
      -> compose_context -> measure -> (enforce)? -> assemble -> generate -> END
```

with one conditional edge, `_after_measure`, and no reducers anywhere in the
schema - because no key is written by more than one node, which is a claim
about this graph rather than an omission. `TurnDeps` rides in
`context_schema`, so collaborators are not smuggled through state.

Three probes forced the shape, and each one killed a different design's
centrepiece:

1. **No node downstream of a streaming node runs when the SSE consumer
   disconnects** - `defer=True` or not. Ten of the eleven `_persist_completed_turn`
   sites persist *before* their final yields, so hoisting persistence into a
   graph exit node would lose turns on every dropped connection, into a
   database with no backups. **Persistence stays at its eleven call sites.**
2. **A subgraph's custom stream events vanish** unless `astream` is passed
   `subgraphs=True`, silently and with no warning. That flag therefore lands
   before any subgraph exists.
3. **`InvalidUpdateError` on two writes to one key in a step**, and
   `DEFAULT_RECURSION_LIMIT` is 10007 - a runaway backstop, not a bound. The
   step loop's five stopping rules stay in code; expressed as graph edges, a
   `break` becomes a `GraphRecursionError` *after* tokens have shipped.

Also decided:

- **No checkpointer.** `langgraph.checkpoint.postgres` is not installed,
  `anios_db` has no backups, and a resumed node re-executes from the top while
  `ScheduledTaskRepository.create` has no dedupe key. A checkpointer is
  reachable only after idempotency keys, never before.
- **Retry policy is a property of side effects.** Read-only nodes retry;
  anything that writes outside the process is `max_attempts=1`. `generate`
  never retries - half a reply is already on the wire.
- **`generate` stays synchronous, deliberately.** `llm.stream_chat` is a
  blocking generator behind a `threading.Lock`; LangGraph runs a sync node on a
  worker thread, so the event loop stays free. Making it `async def` would
  stall every concurrent turn and the iMessage bridge with it.
- **The graph is compiled lazily under `lru_cache`, never at import.** Six
  services build from the root Dockerfile, and an import-time compile turns a
  construction error into a simultaneous fleet boot failure.

## Consequences

**What this buys.** A real conditional edge and a real state channel replacing
a dead reducer; one system-prompt render and one clock per turn instead of two
(the midnight date split and the report/prompt drift both stop); per-node retry
semantics that today do not exist; and a place to put a subgraph when an agent
needs one.

**What it costs.** Nine nodes where there was one, and a second implementation
living behind `REPLY_GRAPH_FULL` for as long as the flag exists. The legacy
branch is *frozen, not maintained*, which is the only thing that stops
two-implementations drift.

**What was rejected, and by what finding**, is recorded in full in the plan
this ADR summarises. The short list: a deferred persistence node (probe 1), any
checkpointer (not installed, no backups, no idempotency), parallel retrieval
fan-out (`_stream_web_search` composes its outbound query from the image
matches `_stream_retrieved_context` just found, so fanning them apart changes
what leaves the machine), and an `AGENTS` registry as graph dispatch (Scout has
no `MainAction` at all - it is a cron in `discovery-worker` - and MCP tools are
shortlisted per user at request time, so neither can be a static node).

**The point of no return is commit 9**, which deletes the legacy branch and the
flag. Every commit before it reverts with an environment variable and a
restart. Commit 9 is safe only because commits 1-8 never touch persistence
ordering, never add a checkpointer, and never reorder retrieval - so what is
deleted is a duplicate of code already proven in production.


## Amendment, 2026-08-23: commits 7-9 dropped

The plan's remaining commits moved `plan_context`, `recall`, `retrieve`,
`memory_write` and `compose_context` into nodes behind a flag (C7), flipped the
flag (C8), and deleted the legacy branch (C9). They are not being done, and
this is a judgement rather than a pause.

Those five phases are ~130 lines of orchestration that call about ten
collaborators on `ConversationService`. As nodes they cannot reach those
collaborators without either the service itself in `TurnDeps` - which a judge
identified as a fatal flaw, and which is a circular coupling wearing a
dataclass - or ten bound callables, which is the same coupling itemised. Either
way the nodes are thin wrappers whose only new property is that they appear in
a diagram. That is ceremony, not architecture, and it is precisely why every
"the turn IS the graph" design scored between 3.2 and 4.5.

The answering half is already a graph: `measure -> (enforce)? -> assemble ->
generate`, with a real conditional edge, per-node retry semantics, one clock
and one prompt render. What C7 would add is *context gathering*, which is the
preparing half - the half this ADR's own title says the graph does not run.

What C7 would have cost is concrete: a second implementation of the reply path
living behind `REPLY_GRAPH_FULL` until C9 deleted it, in a method that appears
in exactly one test file and only against stubs. Two paths, one of them
unmeasured, is the shape of the drift this codebase has been bitten by all
week.

The one genuinely valuable item in C7-C10 was three lines, and it is done:
`SearchPlanner.compose`, `.refine` and `.another_angle` are synchronous
blocking model calls that were invoked bare from inside async generators,
holding the event loop for two or three round trips per search turn - on a host
where the iMessage worker answers serially behind that same loop. They run in
`asyncio.to_thread` now.

If context gathering ever needs to branch - skip recall for a scheduled task,
retrieve differently per channel - that is the moment to revisit this, with a
reason a diagram cannot supply.
