"""The answering half of one turn, as the graph carries it.

**No reducer appears anywhere in this schema, and that is a claim rather than
an omission.** Every key below is written by exactly one node, because this
graph has no parallel branch. The sequence it preserves is a real data
dependency and not habit: `_stream_web_search` composes its outbound query from
the image matches `_stream_retrieved_context` has just found
(`conversation_service.py:1572`), and *that* string is what
`search_privacy.sanitize` screens before it leaves the machine. Fan those two
apart and a different sentence goes to a third party, with nothing raised
anywhere. A channel one node writes needs no reducer; a reducer here would be a
claim about concurrency this graph does not have.

Nothing here is ever serialized. The graph compiles with no checkpointer -
`langgraph.checkpoint.postgres` is not installed, `anios_db` has no backups,
and a resumed node re-executes from the top while
`ScheduledTaskRepository.create` has no dedupe key. That is why `action` may be
the live typed object the services already pass around rather than something
JSON-shaped, and it is the first thing that must change if a checkpointer is
ever added - after idempotency keys, never before.

`user_id` and `conversation_id` are here because they were *missing*. The
schema this replaces declared five keys while its construction site passed six
fields, so LangGraph silently dropped both of them and the node could not have
told you who it was answering.
"""

from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

from backend.core.llm import LLMClient


class ReplyState(TypedDict):
    """One turn's answering half. Written by nodes, read by nodes."""

    # Who and what. Identity was silently absent before this schema existed.
    user_id: str
    conversation_id: str
    trace_id: str
    query: str
    history: list[dict[str, Any]]

    # Frozen once, at the seed, and never re-read from the clock. Two separate
    # renders of the system prompt used to call `datetime.now()` independently,
    # so a turn crossing midnight measured one date and answered with another.
    now: str

    # Everything the reply is written from: evidence, outcomes, save state.
    # One dict rather than a key per contributor, because `_build_system_prompt`
    # and `turn_context_messages` both take it whole.
    context: dict[str, Any]

    # Set by `assemble`, consumed by `generate`. Split out so a test can assert
    # on the exact messages sent without reaching into a model call.
    prompt_messages: NotRequired[list[dict[str, str]]]

    # What the turn said. Replaces a `messages` key that carried the only
    # reducer in the old schema and that no caller ever read.
    reply: NotRequired[str]

    # The measured plan, when context budgeting produced one.
    budget_report: NotRequired[Any]


@dataclass(frozen=True, slots=True)
class TurnDeps:
    """Collaborators a node needs, passed beside the state rather than in it.

    These ride in `context_schema`, so the graph compiles once per process
    instead of once per request. Closing over the client instead - which is
    what the previous builder did - makes the compiled graph a function of its
    collaborators, so caching it either leaks an entry per request or hands
    every turn the first request's client.

    Nothing here is state: it is never checkpointed, never diffed, and never
    streamed. A node reads it with `get_runtime(TurnDeps).context`.
    """

    llm: LLMClient
