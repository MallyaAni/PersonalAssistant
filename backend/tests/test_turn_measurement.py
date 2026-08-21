"""Counting a turn, without changing it.

This ships in observe-only mode deliberately. Trimming changes what the model
sees, and the section priorities have not been argued against real turn sizes
yet - only against reasoning about which source matters most. Turning
enforcement on before the measurement it is supposed to be built from would
repeat the mistake the whole area exists to prevent: a number chosen first and
justified afterwards.

So what is pinned here is that the count is honest, complete, and free: every
source the prompt was assembled from is represented, the accounting never
raises into a turn, and nothing is altered.
"""

import pytest

from backend.agents.graph import _turn_sections, measure_turn
from backend.config.settings import settings


@pytest.fixture
def budget_enabled():
    original = settings.CONTEXT_BUDGET_ENABLED
    settings.CONTEXT_BUDGET_ENABLED = True
    yield
    settings.CONTEXT_BUDGET_ENABLED = original


def _context():
    return {
        "search": [{"title": "t", "url": "u", "content": "x" * 2_000}],
        "tool_results": [{"tool": "clock", "value": "10:00"}],
        "images": [{"kind": "generated_image", "description": "a harbour"}],
        "recalled_turns": [{"said": "I like jazz", "when": "2026-06-11"}],
        "semantic": [{"content": "lives in Raleigh"}],
        "episodic": [{"content": "asked about bridges last week"}],
    }


def _history():
    return [
        {"query": "first question", "response": "first answer"},
        {"query": "second question", "response": "second answer"},
    ]


# Every source that reaches the prompt has to reach the count, or the report
# describes a turn that was not the one sent.
def test_every_prompt_source_is_represented():
    sections = _turn_sections(_context(), _history(), "now what?", "SYSTEM")

    named = {section.name for section in sections}
    assert named == {
        "system",
        "query",
        "evidence",
        "tools",
        "history",
        "images",
        "recalled",
        "memory",
    }
    assert all(section.items for section in sections), "a source counted as empty"


# Recency is relevance for a conversation, and trimming takes from the tail.
# Oldest-first would discard the turn the follow-up depends on. One item per
# exchange, not per message, so a trim can never keep a response without the
# question it answered.
def test_history_is_ordered_most_recent_first_by_whole_exchanges():
    sections = {s.name: s for s in _turn_sections({}, _history(), "q", "SYSTEM")}

    newest = sections["history"].items[0]
    assert "second question" in newest
    assert "second answer" in newest, "an exchange was split into messages"


def test_both_memory_kinds_are_counted():
    sections = {s.name: s for s in _turn_sections(_context(), [], "q", "SYSTEM")}

    assert len(sections["memory"].items) == 2


# The fixed parts are counted even though they can never be trimmed, or the
# report accounts for only the negotiable half of a turn.
def test_the_untrimmable_parts_are_still_counted(budget_enabled):
    report = measure_turn({}, [], "a question", "SYSTEM PROMPT")

    assert report is not None
    named = {item.name: item for item in report.allocations}
    assert named["system"].tokens > 0
    assert named["query"].tokens > 0


# Room for the reply is reserved from the window, which is the empty-reply
# defect from the same day expressed one level up.
def test_the_reply_budget_is_reserved(budget_enabled):
    report = measure_turn({}, [], "q", "SYSTEM")

    assert report is not None
    assert report.budget_tokens == (
        settings.CONTEXT_BUDGET_TOKENS - settings.MAIN_LLM_MAX_TOKENS
    )


def test_the_switch_turns_measurement_off():
    original = settings.CONTEXT_BUDGET_ENABLED
    settings.CONTEXT_BUDGET_ENABLED = False
    try:
        assert measure_turn(_context(), _history(), "q", "SYSTEM") is None
    finally:
        settings.CONTEXT_BUDGET_ENABLED = original


# Accounting is an improvement to a turn, never a requirement of one. A turn
# must not fail because the thing counting it did.
def test_a_broken_measurement_costs_the_measurement_not_the_turn(
    budget_enabled, monkeypatch
):
    monkeypatch.setattr(
        "backend.agents.graph.plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("boom")),
    )

    assert measure_turn(_context(), _history(), "q", "SYSTEM") is None


# A canary rather than a limit. An ordinary turn sits far under the window
# today; the day that stops being true, this says so before a user does.
def test_an_ordinary_turn_leaves_substantial_headroom(budget_enabled):
    report = measure_turn(_context(), _history(), "What should I do?", "S" * 4_000)

    assert report is not None
    assert report.dropped_total == 0, report.summary()
    assert report.headroom_tokens > report.used_tokens, (
        "an ordinary turn now uses more than half the window: " + report.summary()
    )


def test_enforcement_is_off_by_default():
    # Trimming is not implemented. A flag that silently did nothing would be
    # the exact defect this area exists to stop, so it stays false until the
    # behaviour behind it is real.
    assert settings.CONTEXT_BUDGET_ENFORCE is False


# A remark recalled from the past that is already in the visible history is
# repetition, and repetition reads as emphasis to a model.
def test_a_recalled_remark_already_in_history_is_not_counted_twice(budget_enabled):
    said = "I am interested in horses"
    history = [{"query": said, "response": "tell me more"}]

    with_repeat = measure_turn(
        {"recalled_turns": [{"said": said}, {"said": "I moved to Leeds"}]},
        history,
        "what should I read?",
        "SYSTEM",
    )
    assert with_repeat is not None
    recalled = {i.name: i for i in with_repeat.allocations}["recalled"]
    assert recalled.kept == ("I moved to Leeds",)


def test_a_recalled_remark_absent_from_history_survives(budget_enabled):
    report = measure_turn(
        {"recalled_turns": [{"said": "I am interested in horses"}]},
        [{"query": "something else entirely", "response": "quite"}],
        "what should I read?",
        "SYSTEM",
    )
    assert report is not None
    recalled = {i.name: i for i in report.allocations}["recalled"]
    assert recalled.kept == ("I am interested in horses",)
