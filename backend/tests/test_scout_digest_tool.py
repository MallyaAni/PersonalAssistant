"""scout_digest: what Scout already sent, asked in the chat.

Scout pushes its digest on its own schedule, and nothing in the chat could
read one back: "what did you send me?" was answered from conversation history,
which never contains a digest, or from guesswork. The tool is a read, so the
things worth proving are that it is offered like a read (not withheld as an
automation), that it reaches the stored rows, and that the reply is told the
list is history rather than a new recommendation.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.agents.graph import _render_scout_digest_outcome
from backend.discovery.feedback import SentFind
from backend.tools import (
    AUTOMATION_TOOLS,
    UNATTENDED_WITHHELD,
    ScoutDigestAction,
    builtin_tools,
    describe_action,
    parse_builtin,
)

_NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def test_the_call_becomes_a_typed_action_with_or_without_a_window():
    assert parse_builtin("scout_digest", {}, "") == ScoutDigestAction()
    assert parse_builtin(
        "scout_digest", {"since": "2026-10-31", "until": "2026-10-31"}, ""
    ) == ScoutDigestAction(since="2026-10-31", until="2026-10-31")


def test_it_is_a_read_not_an_automation():
    names = {row.name for row in builtin_tools()}
    assert "scout_digest" in names
    # Offered on a scheduled firing too: "every Monday tell me what Scout sent"
    # is a legitimate task, and reading changes nothing.
    assert "scout_digest" not in AUTOMATION_TOOLS
    assert "scout_digest" not in UNATTENDED_WITHHELD
    assert describe_action(ScoutDigestAction()) == ("What Scout sent", "all")
    assert describe_action(ScoutDigestAction(since="2026-10-31")) == (
        "What Scout sent",
        "2026-10-31",
    )


def test_the_reply_is_told_these_are_history_and_carry_their_reactions():
    text = _render_scout_digest_outcome(
        {
            "kind": "digest",
            "count": 2,
            "items": [
                {
                    "title": "A jazz trio plays",
                    "locality": "Arlington, Virginia",
                    "when": "2026-11-01",
                    "reaction": "liked",
                },
                {"title": "A winery evening", "locality": None, "when": "2026-10-30",
                 "reaction": "disliked"},
            ],
        }
    )
    assert '"A jazz trio plays" (Arlington, Virginia), sent 2026-11-01' in text
    assert "thumbs-up" in text
    assert "thumbs-down" in text
    # The list is what was already sent, not a fresh shortlist to offer again.
    assert "history, not new suggestions" in text
    assert "do not offer them again" in text


def test_nothing_sent_and_a_failed_read_do_not_invite_an_invention():
    empty = _render_scout_digest_outcome({"kind": "empty"})
    assert "nothing sent" in empty
    assert "do not invent" in empty
    failed = _render_scout_digest_outcome({"kind": "failed"})
    assert "could not check" in failed
    assert "do not guess" in failed


@pytest.mark.asyncio
async def test_the_service_reads_the_stored_rows_with_the_stated_window():
    from backend.services.conversation_service import ConversationService

    class _Sent:
        def __init__(self):
            self.calls = []

        async def sent_for(self, user_id, since=None, until=None, limit=40):
            self.calls.append((user_id, since, until))
            return (
                SentFind(title="A jazz trio plays", locality="Arlington", sent_at=_NOW,
                         reaction="liked"),
            )

    service = ConversationService.__new__(ConversationService)
    service.sent_finds = _Sent()
    service.discovery_profile = None

    outcome = await service._apply_scout_digest(
        "ani", ScoutDigestAction(since="2026-10-31", until="2026-10-31")
    )

    assert outcome["kind"] == "digest"
    assert outcome["count"] == 1
    assert outcome["items"][0]["title"] == "A jazz trio plays"
    assert outcome["items"][0]["reaction"] == "liked"
    # A bare date as the upper bound means the whole of that day, resolved to
    # instants before it reaches the repository.
    user, since, until = service.sent_finds.calls[0]
    assert user == "ani"
    assert since == datetime(2026, 10, 31, tzinfo=UTC)
    assert until == datetime(2026, 11, 1, tzinfo=UTC)

    # A malformed date degrades to an unbounded read rather than to no read.
    await service._apply_scout_digest("ani", ScoutDigestAction(since="last week"))
    assert service.sent_finds.calls[1] == ("ani", None, None)

    # Nothing on record is reported as nothing, not as a failure.
    service.sent_finds.sent_for = (
        lambda user_id, since=None, until=None, limit=40: _empty()
    )
    empty = await service._apply_scout_digest("ani", ScoutDigestAction())
    assert empty["kind"] == "empty"


async def _empty():
    return ()


@pytest.mark.asyncio
async def test_with_no_repository_wired_the_tool_is_unavailable():
    # `_execute_step` only consults the frame's unattended flag for the
    # automation block; scout_digest is a read, so it runs on an attended turn
    # and needs a repository to answer from.
    from backend.services.conversation_service import ConversationService

    service = ConversationService.__new__(ConversationService)
    service.sent_finds = None
    kind, outcome = await service._execute_step(
        "ani", ScoutDigestAction(), {}, _frame()
    )
    assert kind == "digest"
    assert outcome["kind"] == "unavailable"


def _frame():
    from backend.services.conversation_service import _StepFrame

    return _StepFrame(
        context={}, query="", conversation_id="", trace_id="", query_embedding=None,
        history=[], emit=lambda event: None, image_matches=[], unattended=False,
    )
