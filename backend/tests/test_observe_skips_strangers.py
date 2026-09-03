"""A room message from an unapproved speaker is observed as context and
never classified for memory (the operator's rule, 2026-09-02 evening)."""
import pytest

from backend.services.conversation_service import ConversationService


@pytest.mark.asyncio
async def test_observe_does_not_classify_an_unapproved_speakers_words():
    service = ConversationService.__new__(ConversationService)
    calls: list[str] = []

    async def classify(*args, **kwargs):
        calls.append("classified")
        return ()

    async def attach_group(context, metadata, user_id, query, embedding):
        context["group"] = dict(metadata.get("group") or {})

    async def persist(*args, **kwargs):
        calls.append("persisted")
        return ()

    async def store_turn(*args, **kwargs):
        return None

    service._classify_memory_proposals = classify  # type: ignore[method-assign]
    service._persist_memory_proposals = persist  # type: ignore[method-assign]
    service._attach_group = attach_group  # type: ignore[method-assign]
    # Whatever observe persists before classifying is stubbed the same way the
    # worker tests stub it: only the classifier gate is under test here.
    for name in ("repository", "tracer", "memory"):
        if not hasattr(service, name):
            setattr(service, name, None)
    metadata = {"channel": "imessage_group", "group": {"chat_name": "Mixed", "speaker_user_id": "", "speaker_approved": False, "members": ["u-ani"]}}
    try:
        await service.observe("group:abc", "book me a table", None, metadata)
    except Exception as exc:  # persistence stubs are not the point; the gate is
        assert "classified" not in calls, exc
    assert "classified" not in calls and "persisted" not in calls
