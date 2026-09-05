"""discuss_image: talking about the picture is neither an edit nor a re-show."""

from __future__ import annotations

import os

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.services.conversation_service import (
    _NOT_IN_LOOP,
    ConversationService,
    _StepFrame,
)
from backend.tools import DiscussImageAction, describe_action, parse_builtin


def test_the_call_becomes_an_action_with_or_without_words():
    assert parse_builtin("discuss_image", {"about": " which hat "}, "") == DiscussImageAction(about="which hat")
    assert parse_builtin("discuss_image", {}, "") == DiscussImageAction(about="")


# Nothing runs for it: the turn's executor carries out no step for a
# discussion, so the reply answers from the picture's description already in
# its context - and the loop never offers it as a later step for the same
# reason, whatever its contract says.
@pytest.mark.asyncio
async def test_nothing_runs_for_it_and_the_person_sees_why():
    service = ConversationService.__new__(ConversationService)
    frame = _StepFrame(
        context={"user_id": "u", "query": "which hat"},
        query="which hat",
        conversation_id="",
        trace_id="",
        query_embedding=None,
        history=[],
        emit=lambda event: None,
        image_matches=[],
        unattended=False,
    )
    assert await service._execute_step("u", DiscussImageAction(about="which hat"), {}, frame) is None
    assert "discuss_image" in _NOT_IN_LOOP
    assert describe_action(DiscussImageAction(about="which hat")) == ("About the picture", "which hat")
