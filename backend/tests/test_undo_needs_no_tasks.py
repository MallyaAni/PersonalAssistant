"""Undo reads the change log, not the task list: with no reminders at all,
"forget that" and "undo that" still work (the sweep found them answering
"none", 2026-08-27)."""

from __future__ import annotations

import pytest

from backend.services.conversation_service import ConversationService
from backend.tools import ManageTasksAction


class _Tasks:
    async def list_for_user(self, user_id, enabled_only=False):
        return []

    async def latest_undoable(self, user_id, conversation_id=None):
        return {"id": "c1", "kind": "memory", "operation": "save", "before": None,
                "after": {"kind": "semantic_fact", "memory_type": "semantic", "id": "m1", "value": "My dentist is Dr Lee."}}

    async def mark_undone(self, user_id, change_id):
        return True

    async def record_change(self, *args, **kwargs):
        return {}


class _Memory:
    def __init__(self):
        self.deleted = []

    async def delete_memory(self, user_id, memory_type, memory_id):
        self.deleted.append(memory_id); return True


@pytest.mark.asyncio
async def test_undo_with_no_tasks_still_takes_back_the_last_change():
    service = ConversationService.__new__(ConversationService)
    service.scheduled_tasks = _Tasks()
    service.memory = _Memory()
    service.discovery_runs = None
    service.main_action_selector = None
    outcome = await service._manage_tasks("ani", ManageTasksAction(operation="undo"))
    assert outcome["kind"] == "undone", outcome
    assert service.memory.deleted == ["m1"]
