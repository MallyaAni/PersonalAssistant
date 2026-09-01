"""A reply to a message beyond the history window still finds its turn.

The bridge resolves any bubble's words from the full thread, but the acting
turn fetches only the last ten rows - so the pointed-at exchange could be
absent, the window could not open at it, and a receipt's raw title leaked to
the resolver (live, 2026-09-01: a reply to the months-old "Try Again Flow"
receipt named the diagram after the failure again). The rescue fetches wider
once, only on the miss, and puts the matched turn at the front where the
shared window and the metadata rendering already handle it.
"""

from __future__ import annotations

import pytest

from backend.services.conversation_service import _rescue_replied_turn

RECEIPT = "Created an editable diagram: Try Again Flow."

OLD_TURN = {
    "query": "try again!",
    "response": RECEIPT,
    "metadata": {
        "artifact_ids": ["id-1"],
        "artifact_status": "ready",
        "trace": {"route": {"label": "Diagrams",
                            "detail": "Roman aqueduct architecture thinking process"}},
    },
}

RECENT = [
    {"query": "brown healthier?", "response": "Not really."},
    {"query": "what time is sunset today", "response": "7:31 PM tonight."},
]


class _Repo:
    def __init__(self, deep):
        self.deep = deep
        self.calls = []

    async def get_history(self, conversation_id, user_id, limit=10):
        self.calls.append(limit)
        return self.deep[-limit:] if limit < len(self.deep) else list(self.deep)


@pytest.mark.asyncio
async def test_a_reply_beyond_the_window_pulls_its_turn_to_the_front():
    repo = _Repo([OLD_TURN, *[dict(t) for t in RECENT for _ in range(1)]])
    out = await _rescue_replied_turn(repo, "c", "u", RECEIPT, list(RECENT))
    assert out[0] is repo.deep[0], "matched turn leads the history"
    assert out[1:] == RECENT
    assert repo.calls == [80], "wider fetch happens once, only on the miss"


@pytest.mark.asyncio
async def test_a_reply_already_in_the_window_changes_nothing():
    history = [dict(OLD_TURN), *RECENT]
    repo = _Repo(history)
    out = await _rescue_replied_turn(repo, "c", "u", RECEIPT, history)
    assert out == history
    assert repo.calls == [], "no second fetch when the turn is in view"


@pytest.mark.asyncio
async def test_a_reply_nowhere_in_the_thread_leaves_history_alone():
    repo = _Repo(list(RECENT))
    out = await _rescue_replied_turn(repo, "c", "u", "some bubble that never existed", list(RECENT))
    assert out == RECENT
