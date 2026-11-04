"""A room message from an unapproved speaker is observed as context and
never classified for memory (the operator's rule, 2026-09-02 evening).

The turn itself is still stored: the next answered turn reads the room's
history, and a stranger's line is part of what the room said. Only the
classifier is skipped. The earlier version of this test stubbed neither the
tracer nor the repository, so observe raised before reaching the guard and
the assertions passed without testing anything.
"""
import pytest

from backend.services.conversation_service import ConversationService


class _Tracer:
    def start_trace(self, user_id):
        return "trace-1"


class _Repository:
    def __init__(self):
        self.stored = []
        self.history_reads = []

    async def get_history(self, conversation_id, user_id, limit):
        self.history_reads.append((conversation_id, user_id, limit))
        return []

    async def save_turn(self, conversation_id, turn):
        self.stored.append((conversation_id, dict(turn)))


@pytest.mark.asyncio
async def test_observe_stores_an_unapproved_speakers_turn_and_skips_the_classifier():
    service = ConversationService.__new__(ConversationService)
    calls: list[str] = []
    repository = _Repository()

    async def classify(*args, **kwargs):
        calls.append("classified")
        return ()

    async def attach_group(context, metadata, user_id, query, embedding):
        context["group"] = dict(metadata.get("group") or {})

    async def persist(*args, **kwargs):
        calls.append("persisted")
        return ()

    service._classify_memory_proposals = classify  # type: ignore[method-assign]
    service._persist_memory_proposals = persist  # type: ignore[method-assign]
    service._attach_group = attach_group  # type: ignore[method-assign]
    service.repository = repository
    service.tracer = _Tracer()
    service.history_turn_limit = 20
    metadata = {
        "channel": "imessage_group",
        "group": {
            "chat_name": "Mixed",
            "speaker_user_id": "",
            "speaker_approved": False,
            "members": ["u-ani"],
        },
    }

    conversation_id = await service.observe("group:abc", "book me a table", None, metadata)

    # The room's line is stored, so the next answered turn holds what was said.
    assert len(repository.stored) == 1
    stored_conversation, turn = repository.stored[0]
    assert stored_conversation == conversation_id
    assert turn["query"] == "book me a table"
    assert turn["response"] == ""
    # A stranger's words are nobody's memory: neither the classifier nor the
    # save of its proposals runs.
    assert calls == []
