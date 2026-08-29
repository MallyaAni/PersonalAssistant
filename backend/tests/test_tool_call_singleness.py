"""One tool call per turn, decided by the engine rather than by silence.

The serving runtime defaults `parallel_tool_calls` to true. The request never
set it, and the selector read `tool_calls[0]` and discarded the rest without a
word - so a turn where the model asked for two things did one of them, and
nothing anywhere said which one had gone. Found on 2026-08-29 by reading the
engine's own request schema, not from an incident, which is the cheaper way to
find this class of thing.
"""

from __future__ import annotations

import logging

from backend.core.llm import OpenAICompatibleInferenceProvider
from backend.services.main_action_selector import MainActionSelector


def test_the_request_pins_a_single_tool_call():
    # Read off the real builder rather than restated here, so a change to the
    # payload has to come past this test. The provider talks to a live engine,
    # so its source is the honest thing to assert on without one.
    import inspect

    source = inspect.getsource(OpenAICompatibleInferenceProvider.chat_with_tools)
    assert '"parallel_tool_calls": False' in source, source
    assert '"tool_choice": "auto"' in source


def test_a_second_call_would_be_reported_not_swallowed(caplog):
    offered = {"search_web", "get_weather"}
    message = {
        "tool_calls": [
            {"function": {"name": "search_web", "arguments": '{"query": "x"}'}},
            {"function": {"name": "get_weather", "arguments": "{}"}},
        ]
    }
    with caplog.at_level(logging.WARNING):
        found = MainActionSelector._extract_call(message, offered)
    assert found is not None and found[0] == "search_web"
    assert any("dropping" in record.message or "dropping" in record.getMessage() for record in caplog.records), caplog.text
    assert "get_weather" in caplog.text


def test_one_call_is_the_ordinary_silent_path():
    message = {"tool_calls": [{"function": {"name": "search_web", "arguments": '{"query": "x"}'}}]}
    found = MainActionSelector._extract_call(message, {"search_web"})
    assert found is not None and found[0] == "search_web"


def test_a_tool_nobody_offered_is_still_refused():
    # The authorization guard stays, grammar or no grammar: it must not depend
    # on the model behaving.
    message = {"tool_calls": [{"function": {"name": "delete_everything", "arguments": "{}"}}]}
    assert MainActionSelector._extract_call(message, {"search_web"}) is None
