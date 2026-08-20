"""Where this turn's volatile material sits, and what it costs to get it wrong.

Prefix caching reuses KV blocks for an unchanged prefix, and one volatile byte
early invalidates everything after it. The per-turn blocks - the memory-save
note, recalled remarks, search results, images, tool output - sat inside the
system message, ahead of the history. History is append-only and would cache
perfectly; it never got the chance.

Measured on the reply model over a 34k-token conversation, second turn:

    volatile inside the system message   33.12s   reuse 1.05x   (no caching)
    volatile after the history            2.00s   reuse 16.32x

The compose file has carried a comment since it was written claiming AniOS
"repeats a stable system/tool prefix across turns". It did not.

The content and its internal order are unchanged; only its position moves. So
what these tests pin is that nothing is lost, that the flag restores the old
arrangement byte for byte, and that the prefix genuinely stops varying.
"""

import pytest

from backend.agents.graph import _build_system_prompt, _build_turn_context
from backend.config.settings import settings


def _context(save_value: str = "lives in Leeds", finding: str = "evidence one"):
    return {
        "search": [{"title": "t", "url": "u", "content": finding}],
        "recalled_turns": [{"said": "I like jazz", "when": "2026-06-11"}],
        "memory_save": {"saved": True, "value": save_value},
        "profile": {"name": "Ani"},
    }


@pytest.fixture
def ordering(request):
    original = settings.CONTEXT_CACHE_ORDERING
    settings.CONTEXT_CACHE_ORDERING = request.param
    yield request.param
    settings.CONTEXT_CACHE_ORDERING = original


# The whole point: the prefix must not change when only the turn does.
def test_the_system_prompt_stops_varying_between_turns():
    settings_before = settings.CONTEXT_CACHE_ORDERING
    settings.CONTEXT_CACHE_ORDERING = True
    try:
        first = _build_system_prompt(_context("lives in Leeds", "evidence one"))
        second = _build_system_prompt(_context("lives in York", "evidence two"))
        assert first == second, "the cacheable prefix still varies per turn"
    finally:
        settings.CONTEXT_CACHE_ORDERING = settings_before


# ...and that this was genuinely broken before, so the test has a subject.
def test_the_old_ordering_did_vary_between_turns():
    settings_before = settings.CONTEXT_CACHE_ORDERING
    settings.CONTEXT_CACHE_ORDERING = False
    try:
        first = _build_system_prompt(_context("lives in Leeds", "evidence one"))
        second = _build_system_prompt(_context("lives in York", "evidence two"))
        assert first != second
    finally:
        settings.CONTEXT_CACHE_ORDERING = settings_before


# Moving material is only safe if none of it goes missing.
def test_nothing_is_lost_by_moving_it():
    context = _context()
    settings_before = settings.CONTEXT_CACHE_ORDERING
    try:
        settings.CONTEXT_CACHE_ORDERING = False
        old = _build_system_prompt(context)
        settings.CONTEXT_CACHE_ORDERING = True
        new = _build_system_prompt(context) + _build_turn_context(context)
    finally:
        settings.CONTEXT_CACHE_ORDERING = settings_before

    for probe in ("evidence one", "I like jazz", "lives in Leeds", "Ani"):
        assert probe in old
        assert probe in new, f"{probe!r} was lost in the move"


def test_the_moved_block_carries_the_per_turn_material():
    block = _build_turn_context(_context())

    assert "evidence one" in block
    assert "I like jazz" in block
    assert "lives in Leeds" in block


def test_a_turn_with_nothing_volatile_adds_no_message():
    assert _build_turn_context({}) == ""


# The flag exists because this changes prompt structure, and structure changes
# behaviour in ways only a functional test can rule out. It has to restore the
# previous arrangement exactly, not approximately.
def test_the_flag_restores_the_previous_prompt():
    context = _context()
    settings_before = settings.CONTEXT_CACHE_ORDERING
    try:
        settings.CONTEXT_CACHE_ORDERING = False
        first = _build_system_prompt(context)
        settings.CONTEXT_CACHE_ORDERING = True
        _build_system_prompt(context)
        settings.CONTEXT_CACHE_ORDERING = False
        again = _build_system_prompt(context)
    finally:
        settings.CONTEXT_CACHE_ORDERING = settings_before

    assert first == again


# The stable prompt must still change when something genuinely stable-per-day
# changes, or it would be caching a stale date.
def test_the_date_still_reaches_the_prompt():
    from datetime import UTC, datetime

    settings_before = settings.CONTEXT_CACHE_ORDERING
    settings.CONTEXT_CACHE_ORDERING = True
    try:
        prompt = _build_system_prompt({}, now=datetime(2026, 8, 20, tzinfo=UTC))
        assert "2026-08-20" in prompt
    finally:
        settings.CONTEXT_CACHE_ORDERING = settings_before


# The role is not cosmetic. Chat templates hoist system messages to the front,
# so the same block sent as a system message is relocated back above the
# history and caches nothing. Measured on the reply model: 1.05x as a system
# message against 8.26x as a user message, identical text.
def test_the_moved_block_is_sent_as_a_user_message():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "agents" / "graph.py").read_text(
        encoding="utf-8"
    )

    assert '{"role": "user", "content": turn_context}' in source, (
        "the per-turn block must be a user message; as a system message the "
        "chat template hoists it above the history and the cache never hits"
    )
