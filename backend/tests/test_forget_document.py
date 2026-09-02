"""'Forget that document' removes the stored document: the undo path's receipt
for a knowledge_document reaches the store's delete, and nothing else."""
import pytest

from backend.services.conversation_service import ConversationService

pytestmark = pytest.mark.asyncio


class _Knowledge:
    def __init__(self):
        self.deleted: list[tuple[str, str]] = []

    async def delete(self, user_id, document_id):
        self.deleted.append((user_id, document_id))
        return True


class _AgentMemory:
    def __init__(self):
        self.knowledge = _Knowledge()


async def test_a_document_receipt_deletes_the_document():
    service = ConversationService.__new__(ConversationService)
    service.agent_memory = _AgentMemory()
    receipt = {"kind": "knowledge_document", "id": "doc-1", "title": "Itinerary.pdf", "undoable": True}
    assert await service._forget_saved("ani", receipt) is True
    assert service.agent_memory.knowledge.deleted == [("ani", "doc-1")]


async def test_without_a_store_the_receipt_is_not_forgotten():
    service = ConversationService.__new__(ConversationService)
    receipt = {"kind": "knowledge_document", "id": "doc-1", "undoable": True}
    assert await service._forget_saved("ani", receipt) is False
