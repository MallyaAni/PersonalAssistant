"""A reply budget too small for thinking returns nothing, not less.

The reply path called `stream_chat(messages)` with no token argument, so it
took the signature default of 1,024 - a number nobody chose, sitting in a
function definition. That looks like a length preference and is not one.

The main model streams its thinking as `reasoning_content`, which the stream
reader does not render. When thinking consumed the budget the stream ended
having emitted no `content` at all, and the turn raised
`Inference provider stream did not contain a message output`. Measured against
the live model: **one reply in six came back empty** on open-ended questions at
1,024, and none at 4,096. That is a user-visible failure, not a degradation,
and it was live.

So the budget is a setting now, it is passed explicitly, and its default is
sized from that measurement rather than from a function signature.
"""

import pytest

from backend.config.settings import settings


# The specific regression: a caller that forgets the argument gets 1,024 again.
def test_the_reply_path_passes_the_configured_budget():
    from pathlib import Path

    # Every call site, found rather than named. This used to point at
    # agents/graph.py, and the reply path moved into agents/reply/nodes.py -
    # a guard that names one file stops guarding the moment the code moves,
    # and says nothing while it does.
    agents = Path(__file__).resolve().parents[1] / "agents"
    calls = [
        (path, line.strip())
        for path in agents.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if "stream_chat(" in line and "def stream_chat" not in line
    ]

    assert calls, "no stream_chat call found under backend/agents"
    for path, line in calls:
        assert "settings.MAIN_LLM_MAX_TOKENS" in line, (
            f"{path.name} calls stream_chat without the budget: {line!r}. "
            "Calling it with only messages silently takes the 1,024 signature "
            "default, which returned an empty reply on one open question in six."
        )


# Sized from the measurement, so a well-meaning reduction has to argue with it.
def test_the_budget_leaves_room_for_thinking_and_an_answer():
    # The longest genuine answer measured spent about 1,600 tokens, most of it
    # thinking. A budget at or below that returns empty replies.
    assert settings.MAIN_LLM_MAX_TOKENS >= 2_048, (
        "below roughly 2k a reasoning model spends the budget thinking and "
        "emits no answer at all"
    )


def test_the_budget_still_bounds_a_runaway():
    # It exists to stop a repetition loop, not to shape answers. At the decode
    # rates measured here an unbounded reply can run for over an hour.
    assert settings.MAIN_LLM_MAX_TOKENS <= 32_768


@pytest.mark.parametrize("value", [0, 100, 64_000])
def test_an_unusable_budget_is_rejected_by_the_schema(value: int):
    from pydantic import ValidationError

    from backend.config.settings import Settings

    with pytest.raises(ValidationError):
        Settings(MAIN_LLM_MAX_TOKENS=value)


# The stream reader's own default is what the defect rode in on. It stays, for
# callers that genuinely want a short bounded answer, but it must not be so low
# that a reasoning model cannot finish - and anything reaching for it should be
# doing so deliberately.
def test_the_stream_default_is_not_silently_reused_as_a_reply_budget():
    import inspect

    from backend.core.llm import OpenAICompatibleInferenceProvider

    signature = inspect.signature(OpenAICompatibleInferenceProvider.stream_chat)
    default = signature.parameters["max_tokens"].default
    assert default <= settings.MAIN_LLM_MAX_TOKENS, (
        "the signature default must never exceed the configured reply budget, "
        "or forgetting the argument would quietly raise the limit instead of "
        "lowering it"
    )
