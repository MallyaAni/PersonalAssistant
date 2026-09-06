"""send_event_links is a real, router-visible, read-only tool row."""

from backend.tools import parse_builtin
from backend.tools.actions import SendEventLinksAction
from backend.tools.registry import (
    UNATTENDED_WITHHELD,
    builtin_tools,
    core_tool_names,
)


def test_parses_the_which_into_the_action():
    assert parse_builtin("send_event_links", {"which": " the salsa night "}, "") == (
        SendEventLinksAction(which="the salsa night")
    )


def test_a_blank_which_is_not_a_decision():
    # A tool picked without being able to say what for is no call at all, the
    # same rule every built-in required-text argument follows.
    assert parse_builtin("send_event_links", {"which": ""}, "") is None
    assert parse_builtin("send_event_links", {}, "") is None


def test_it_is_a_registered_builtin_row():
    names = {row.name for row in builtin_tools()}
    assert "send_event_links" in names
    row = next(row for row in builtin_tools() if row.name == "send_event_links")
    assert row.label == "Send links for listed events"
    assert row.core
    assert row.contract.effect == "read"


def test_it_is_withheld_from_a_scheduled_firing():
    # A firing carries the person's own words, which can read like a fresh
    # request for links; nothing is sent on an unattended firing.
    assert "send_event_links" in UNATTENDED_WITHHELD
    assert "send_event_links" in core_tool_names()
