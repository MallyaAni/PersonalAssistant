"""A saved memory is on the record, and "forget that" takes it back."""

from __future__ import annotations

import pytest

from backend.agents.graph import _render_task_outcome
from backend.services.conversation_service import ConversationService


class _Memory:
    def __init__(self):
        self.deleted = []
        self.cleared_keys = []
        self.name_cleared = False

    async def delete_memory(self, user_id, memory_type, memory_id):
        self.deleted.append((memory_type, memory_id)); return True

    async def clear_preferred_name(self, user_id):
        self.name_cleared = True; return {}

    async def clear_fact_key(self, user_id, key):
        self.cleared_keys.append(key); return 1


class _Log:
    def __init__(self, latest):
        self.latest = latest; self.undone = []; self.recorded = []

    async def latest_undoable(self, user_id):
        return self.latest

    async def mark_undone(self, user_id, change_id):
        self.undone.append(change_id); return True

    async def record_change(self, user_id, kind, operation, before, after, task_id=None):
        self.recorded.append((kind, operation, before, after)); return {}


def _service(memory, latest):
    service = ConversationService.__new__(ConversationService)
    service.memory = memory
    service.scheduled_tasks = _Log(latest)
    service.discovery_runs = None
    return service


@pytest.mark.asyncio
async def test_a_saved_fact_is_deleted_by_id_and_the_undo_recorded():
    memory = _Memory()
    change = {"id": "c1", "kind": "memory", "operation": "save", "before": None,
              "after": {"kind": "semantic_fact", "memory_type": "semantic", "id": "m9", "value": "My dentist is Dr Lee."}}
    service = _service(memory, change)
    outcome = await service._undo_last_change("ani")
    assert outcome["kind"] == "undone" and outcome["memory"]["value"] == "My dentist is Dr Lee."
    assert memory.deleted == [("semantic", "m9")]
    assert service.scheduled_tasks.undone == ["c1"]
    assert service.scheduled_tasks.recorded[0][:2] == ("memory", "undo")


@pytest.mark.asyncio
async def test_interests_and_a_name_are_taken_back_by_key_and_clear():
    memory = _Memory()
    service = _service(memory, {"id": "c2", "kind": "memory", "operation": "save", "before": None,
                                "after": {"kind": "discovery_interests", "fact_keys": ["interest_salsa", "interest_hiking"], "value": "salsa, hiking"}})
    assert (await service._undo_last_change("ani"))["kind"] == "undone"
    assert memory.cleared_keys == ["interest_salsa", "interest_hiking"]
    service = _service(memory, {"id": "c3", "kind": "memory", "operation": "save", "before": None,
                                "after": {"kind": "preferred_name", "value": "Ani"}})
    assert (await service._undo_last_change("ani"))["kind"] == "undone"
    assert memory.name_cleared


@pytest.mark.asyncio
async def test_a_kind_without_a_way_back_says_so():
    service = _service(_Memory(), {"id": "c4", "kind": "memory", "operation": "save", "before": None,
                                   "after": {"kind": "entity", "undoable": False}})
    outcome = await service._undo_last_change("ani")
    assert outcome["kind"] == "not_undoable"
    assert "cannot be taken back" in _render_task_outcome(outcome)


def test_the_reply_is_told_the_memory_is_forgotten():
    text = _render_task_outcome({"kind": "undone", "change": {"kind": "memory"}, "memory": {"kind": "semantic_fact", "value": "My dentist is Dr Lee."}})
    assert "Forgotten: the memory saved a moment ago (semantic_fact: My dentist is Dr Lee.)" in text
