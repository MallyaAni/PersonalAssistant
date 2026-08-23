"""The answering half, wired.

Read this file to know what happens between "the router decided" and "the reply
is on the wire". What is deliberately not here is named at the bottom, with the
reason for each - see also
docs/adr/0012-the-graph-answers-the-turn-it-does-not-run-it.md.
"""

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from backend.agents.reply import nodes
from backend.agents.reply.state import ReplyState, TurnDeps

# Retry is a property of side effects, not of importance. A node that writes
# nothing outside the process may be retried; one that does is at-most-once.
# `generate` never retries under any circumstances - half a reply is already on
# the wire, and a second attempt would append a second answer to the first.
AT_MOST_ONCE = RetryPolicy(max_attempts=1)
READ_ONLY = RetryPolicy(max_attempts=2, backoff_factor=2.0)


# Build the answering graph, compiled once per process.
#
# Cached, but lazily and never at import: six services build from the root
# Dockerfile, and an import-time compile turns any construction error into a
# simultaneous boot failure across the whole fleet rather than one failing
# request.
#
# It takes no arguments on purpose. The previous builder closed over the LLM
# client, which makes the compiled graph a function of its collaborators - so
# caching it either leaks a cache entry per request or hands every later turn
# the first request's client. Collaborators ride in `context_schema` instead.
@lru_cache(maxsize=1)
def build_reply_graph() -> Any:
    graph = StateGraph(ReplyState, context_schema=TurnDeps)

    # measure and assemble are pure given their inputs and write nothing
    # outside the process, so a retry is free. enforce and generate are not:
    # enforce mutates the context the rest of the turn reads, and generate has
    # already put half a reply on the wire.
    graph.add_node("measure", nodes.measure, retry_policy=READ_ONLY)
    graph.add_node("enforce", nodes.enforce, retry_policy=AT_MOST_ONCE)
    graph.add_node("assemble", nodes.assemble, retry_policy=READ_ONLY)
    graph.add_node("generate", nodes.generate, retry_policy=AT_MOST_ONCE)

    graph.add_edge(START, "measure")
    # The only branch in the graph. Trimming is off by default and skipped
    # outright when the untrimmable parts already overflow the window.
    graph.add_conditional_edges(
        "measure", nodes.after_measure, {"enforce": "enforce", "assemble": "assemble"}
    )
    graph.add_edge("enforce", "assemble")
    graph.add_edge("assemble", "generate")
    graph.add_edge("generate", END)

    return graph.compile(name="reply")


# What is NOT in this graph, and why. Each was designed and each is a
# regression rather than a simplification:
#
#   persistence - `_persist_completed_turn` stays at its eleven call sites.
#     Probed on langgraph 1.2.9: no node downstream of a streaming node runs
#     when the SSE consumer disconnects, `defer=True` or not. Ten of the eleven
#     sites persist BEFORE their final yields today, so an exit node would lose
#     those turns on every dropped connection, into a database with no backups.
#
#   any checkpointer - `langgraph.checkpoint.postgres` is not installed, and a
#     resumed node re-executes from the top while `ScheduledTaskRepository.
#     create` has no dedupe key. Reachable only after idempotency keys.
#
#   routing and branch dispatch - `_generating_branch` picks a route AND
#     `_runnable` nulls an unrunnable action. A conditional edge can do the
#     first and not the second, so collapsing them would carry a diagram action
#     with no diagram service into the reply as though it had run.
#
#   the step loop as edges - its five stopping rules are a set, a counter and a
#     clock. As a cycle, a clean `break` becomes GraphRecursionError after
#     tokens have already shipped, and DEFAULT_RECURSION_LIMIT is 10007 rather
#     than a bound worth relying on.
