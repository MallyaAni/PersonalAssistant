"""'Forget that document' takes back the document, not the newest change."""
import uuid

import pytest

from backend.services.conversation_service import ConversationService, _turn_conversation, _turn_query

pytestmark = pytest.mark.asyncio


class _Ledger:
    def __init__(self):
        self.calls = []

    async def latest_undoable(self, user_id, conversation_id=None, receipt_kind=None):
        self.calls.append(receipt_kind)
        return None


def _service():
    service = ConversationService.__new__(ConversationService)
    service.scheduled_tasks = _Ledger()
    return service


async def test_the_words_document_or_file_target_a_document_receipt():
    for phrase in ("forget that document", "drop the file I sent", "undo the pdf", "forget that attachment"):
        service = _service()
        _turn_query.set(phrase)
        _turn_conversation.set("")
        assert (await service._undo_last_change("ani"))["kind"] == "nothing_to_undo"
        assert service.scheduled_tasks.calls == ["knowledge_document"], phrase


async def test_plain_forget_that_takes_the_newest_change_of_any_kind():
    service = _service()
    _turn_query.set("forget that")
    _turn_conversation.set("")
    await service._undo_last_change("ani")
    assert service.scheduled_tasks.calls == [None]


# The ledger itself, against the real table: a memory receipt written after
# a document receipt, and the document is still the one found by kind.
async def test_the_ledger_finds_the_newest_document_receipt_behind_a_newer_memory():
    try:
        from backend.database.session import AsyncSessionLocal
        from backend.tasks.repository import ScheduledTaskRepository
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"ledger not importable here: {type(exc).__name__}")
    user_id = f"undo-{uuid.uuid4().hex[:8]}"
    conversation = str(uuid.uuid4())
    try:
        async with AsyncSessionLocal() as session:
            ledger = ScheduledTaskRepository(session)
            await ledger.record_change(user_id, "memory", "save", None, {"kind": "knowledge_document", "id": "doc-1", "undoable": True}, conversation_id=conversation)
            await ledger.record_change(user_id, "memory", "save", None, {"kind": "semantic_fact", "id": "fact-1", "undoable": True}, conversation_id=conversation)
            newest = await ledger.latest_undoable(user_id, conversation)
            assert newest["after"]["kind"] == "semantic_fact"
            document = await ledger.latest_undoable(user_id, conversation, receipt_kind="knowledge_document")
            assert document is not None and document["after"]["id"] == "doc-1"
            assert await ledger.latest_undoable(user_id, conversation, receipt_kind="scout_schedule") is None
    except (ConnectionError, OSError) as exc:
        pytest.skip(f"database unreachable: {type(exc).__name__}")
