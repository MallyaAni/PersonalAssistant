"""discuss_image: talking about the picture is neither an edit nor a re-show."""

from __future__ import annotations

import os

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.services.conversation_service import _runnable
from backend.tools import DiscussImageAction, describe_action, parse_builtin


def test_the_call_becomes_an_action_with_or_without_words():
    assert parse_builtin("discuss_image", {"about": " which hat "}, "") == DiscussImageAction(about="which hat")
    assert parse_builtin("discuss_image", {}, "") == DiscussImageAction(about="")


def test_nothing_runs_for_it_and_the_person_sees_why():
    assert _runnable(DiscussImageAction(about="which hat")) is None
    assert describe_action(DiscussImageAction(about="which hat")) == ("About the picture", "which hat")
