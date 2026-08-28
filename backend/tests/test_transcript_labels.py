"""Who said what, in every place a conversation is shown to a model.

A group turn carries its speaker on the turn's metadata; every renderer
labels the user side with that name, and a one-to-one turn stays "User"
(or the bare query) byte for byte.
"""

from backend.agents.reply.nodes import assemble
from backend.services.conversation_service import _planner_history
from backend.services.followup import _recent
from backend.services.main_action_selector import render_recent_history
from backend.services.transcript import speaker_label, speaker_name, user_content


def _group_turn(name: str, query: str, response: str = "") -> dict:
    return {"query": query, "response": response, "metadata": {"group": {"speaker_name": name}}}


def test_a_group_turn_names_its_speaker_and_a_direct_turn_does_not():
    assert speaker_name(_group_turn("Jen", "thai?")) == "Jen"
    assert speaker_name({"query": "hi", "metadata": {}}) is None
    assert speaker_name({"query": "hi"}) is None
    assert speaker_name(None) is None
    assert speaker_label(_group_turn("Jen", "thai?")) == "Jen"
    assert speaker_label({"query": "hi"}) == "User"
    assert user_content(_group_turn("Jen", "thai?")) == "Jen: thai?"
    assert user_content({"query": "hi"}) == "hi"


def test_metadata_alone_is_accepted_too():
    assert speaker_name({"group": {"speaker_name": "Ani"}}) == "Ani"
    assert speaker_name({"group": {"speaker_name": "   "}}) is None


def test_the_follow_up_resolver_and_router_label_group_speakers():
    history = [_group_turn("Jen", "thai or pizza?", "Either works - what's the occasion?"), {"query": "plain", "response": "ok"}]
    assert _recent(history) == "Jen: thai or pizza?\nAssistant: Either works - what's the occasion?\nUser: plain\nAssistant: ok"
    assert render_recent_history(history).startswith("Jen: thai or pizza?\nAssistant:")


def test_the_planner_and_reply_messages_carry_the_speaker():
    history = [_group_turn("Jen", "thai?", "sure")]
    assert _planner_history(history)[0] == {"role": "user", "content": "Jen: thai?"}
    state = {"history": history, "system_prompt": "sys", "query": "Ani: and pizza?", "context": {}}
    messages = assemble(state)["prompt_messages"]
    assert messages[1] == {"role": "user", "content": "Jen: thai?"}
    assert messages[2] == {"role": "assistant", "content": "sure"}


def test_a_direct_turn_renders_exactly_as_before():
    history = [{"query": "hello", "response": "hi"}]
    assert assemble({"history": history, "system_prompt": "s", "query": "q", "context": {}})["prompt_messages"][1] == {
        "role": "user",
        "content": "hello",
    }
    assert _recent(history) == "User: hello\nAssistant: hi"
