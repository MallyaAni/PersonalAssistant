"""What a node emits is what the browser receives, with no translation layer.

Before this, a node pushed `{"type": "message.delta", "content": ...}` and the
consumer tested for exactly that string, so every other custom event was
discarded in silence - adding a second event kind was a no-op with no error at
any layer. The node pushed, nothing arrived, and nothing complained.

Two things are pinned here. `emit` raises on a name that is not a
`ChatStreamEvent` kind, so the failure is a stack trace in a test rather than a
missing bubble in production. And the compiled graph really does deliver that
shape through `astream(..., subgraphs=True)` - which matters because
`subgraphs=True` changes the *arity* of what astream yields, and getting that
wrong drops every event rather than some of them.
"""

import pytest

from backend.agents.reply.graph import build_reply_graph
from backend.agents.reply.state import TurnDeps
from backend.agents.reply.emit import _KINDS, emit
from backend.models.schemas import ChatStreamEvent


class _StubLlm:
    """Streams two fixed chunks; the model is not what is under test."""

    def stream_chat(self, messages, max_tokens):
        self.messages = messages
        yield "first "
        yield "second"


# The kinds must come from the schema, or this file guards a copy of a list.
def test_the_kinds_are_the_wire_contract() -> None:
    from typing import get_args, get_type_hints

    declared = set(get_args(get_type_hints(ChatStreamEvent)["event"]))
    assert _KINDS == declared
    assert "delta" in _KINDS


# A name the consumer would drop must fail loudly at the point of emission.
def test_emitting_an_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="not a ChatStreamEvent kind"):
        emit("reasoning_step", note="a kind nobody declared")


# The whole point: the node's output reaches the consumer unchanged.
@pytest.mark.asyncio
async def test_the_compiled_graph_streams_wire_shaped_events() -> None:
    graph = build_reply_graph()
    seed = {
        "user_id": "u",
        "conversation_id": "c",
        "trace_id": "stream-contract",
        "query": "hello",
        "history": [],
        "context": {},
        "now": "2026-08-23T00:00:00+00:00",
    }

    received: list[dict] = []
    # subgraphs=True yields (namespace, event) pairs rather than bare events.
    # Unpacking is the assertion as much as the shape is: read it as a single
    # value and every event silently becomes a tuple nobody matches.
    async for namespace, event in graph.astream(
        seed, stream_mode="custom", subgraphs=True, context=TurnDeps(llm=_StubLlm())
    ):
        assert isinstance(namespace, tuple)
        received.append(event)

    assert received, "the graph emitted nothing"
    for event in received:
        assert set(event) == {"event", "data"}, event
        assert event["event"] in _KINDS
    assert [e["data"]["content"] for e in received] == ["first ", "second"]


# A node that emits nothing must not break the consumer's unpacking.
@pytest.mark.asyncio
async def test_a_silent_turn_streams_no_events_rather_than_failing() -> None:
    class _Silent:
        def stream_chat(self, messages, max_tokens):
            return iter(())

    graph = build_reply_graph()
    seed = {
        "user_id": "u",
        "conversation_id": "c",
        "trace_id": "silent",
        "query": "hello",
        "history": [],
        "context": {},
        "now": "2026-08-23T00:00:00+00:00",
    }
    received = [
        event
        async for _ns, event in graph.astream(
            seed, stream_mode="custom", subgraphs=True, context=TurnDeps(llm=_Silent())
        )
    ]
    assert received == []


# The prompt the node builds must be the prompt a direct render produces.
#
# This is the assertion that makes moving the body safe: C6 splits `answer`
# into measure / enforce / assemble / generate, and the risk of that split is a
# prompt that differs by a section, an order, or a byte. Comparing against the
# helpers directly means the split cannot quietly change what the model reads.
@pytest.mark.asyncio
async def test_the_assembled_prompt_matches_a_direct_render() -> None:
    from backend.agents.graph import _build_system_prompt, turn_context_messages

    llm = _StubLlm()
    graph = build_reply_graph()
    context = {"save_state": {}}
    history = [{"query": "earlier question", "response": "earlier answer"}]
    seed = {
        "user_id": "u",
        "conversation_id": "c",
        "trace_id": "prompt-equality",
        "query": "the newest question",
        "history": history,
        "context": context,
        "now": "2026-08-23T00:00:00+00:00",
    }

    final = await graph.ainvoke(seed, context=TurnDeps(llm=llm))

    expected = [{"role": "system", "content": _build_system_prompt(context)}]
    for turn in history:
        expected.append({"role": "user", "content": turn["query"]})
        expected.append({"role": "assistant", "content": turn["response"]})
    expected.extend(turn_context_messages(context))
    expected.append({"role": "user", "content": "the newest question"})

    assert final["prompt_messages"] == expected
    # And the model really was handed exactly that.
    assert llm.messages == expected
    assert final["reply"] == "first second"


# Identity reaches the node. It did not before: the old schema declared five
# keys while its construction site passed six, so LangGraph dropped user_id and
# conversation_id and the node could not tell who it was answering.
@pytest.mark.asyncio
async def test_the_node_can_see_who_it_is_answering() -> None:
    seen: dict = {}

    class _Recording:
        def stream_chat(self, messages, max_tokens):
            yield "ok"

    graph = build_reply_graph()
    seed = {
        "user_id": "ani.mallya",
        "conversation_id": "conv-42",
        "trace_id": "identity",
        "query": "who am i",
        "history": [],
        "context": {},
        "now": "2026-08-23T00:00:00+00:00",
    }
    final = await graph.ainvoke(seed, context=TurnDeps(llm=_Recording()))
    seen = final

    assert seen["user_id"] == "ani.mallya"
    assert seen["conversation_id"] == "conv-42"
    assert seen["now"] == "2026-08-23T00:00:00+00:00"
