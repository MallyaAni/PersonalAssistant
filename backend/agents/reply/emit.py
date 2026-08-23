"""Push one interface event from inside a graph node.

A node cannot `yield`. The reply path is an async generator today and every
event it sends the browser is a `yield`; a LangGraph node returns a state
update instead, so anything it wants to say mid-run goes through LangGraph's
custom stream channel. This is that channel, with one rule attached.

**The rule is that an unknown event name raises here rather than vanishing.**
The arrangement this replaces did the opposite: the consumer tested
`type == "message.delta"` and silently discarded every other custom event, so
adding a second event kind was a no-op with no error at any layer - the node
pushed, nothing arrived, nothing complained. Checking the name at the point of
emission turns that into a stack trace in a test rather than a missing bubble
in production.

The kinds come from `ChatStreamEvent` itself, so this file cannot drift from
the wire contract. The browser also has an allowlist, and it deliberately
*skips* what it does not know - the asymmetry is intentional. A backend that
invents a name has a bug; a browser that meets a newer backend has version
skew, and only one of those should break a reply.
"""

from typing import Any, get_args, get_type_hints

from langgraph.config import get_stream_writer

from backend.models.schemas import ChatStreamEvent

# Derived, never copied. A literal list here would be a second source of truth
# that agrees with the first until someone adds an event to one of them.
_KINDS: frozenset[str] = frozenset(
    get_args(get_type_hints(ChatStreamEvent)["event"])
)


# Send one event to the interface from inside a node.
def emit(event: str, /, **data: Any) -> None:
    if event not in _KINDS:
        raise ValueError(
            f"{event!r} is not a ChatStreamEvent kind; "
            f"add it to ChatStreamEvent and to the browser's allowlist first"
        )
    get_stream_writer()({"event": event, "data": data})


# Send an event that is already assembled, for callers holding a whole dict.
#
# `_decide` and the generating branches build ChatStreamEvent values today and
# yield them; this lets that code move into a node unchanged apart from the
# verb, which is what keeps the migration reviewable.
def emit_event(event: ChatStreamEvent) -> None:
    emit(event["event"], **event.get("data", {}))
