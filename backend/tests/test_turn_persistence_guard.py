"""One turn writes one row, whatever the code above it does.

`repository.save_turn` is a bare `session.add` plus `commit` with no
idempotency key, and eleven call sites in `ConversationService` reach it. Today
every pair of them is a mutually exclusive error/success branch inside one
method, so a turn persists once - but nothing enforces that, the branches are
hundreds of lines apart, and the database on the other side holds real
conversations and has no backups.

This is the enforcement. A second write for the same trace is a logged no-op
rather than a duplicate row, which matters most while the reply path is being
moved into a graph: the whole class of mistake that move can make is running a
persistence step twice.

Scope is deliberate. `get_conversation_service` is not cached, so an instance
spans one request - the set therefore covers exactly the window a double-write
can occur in, and cannot grow without bound.
"""

import pytest

from backend.services.conversation_service import ConversationService


class _Repository:
    """Counts writes; nothing else about persistence is under test."""

    def __init__(self) -> None:
        self.saved: list[dict] = []

    async def save_turn(self, conversation_id, payload):
        self.saved.append({"conversation_id": conversation_id, **payload})

    async def count_turns(self, conversation_id, user_id):
        return len(self.saved)


def _service(repository: _Repository) -> ConversationService:
    # Only persistence collaborators matter here; the rest of the workflow is
    # never entered, so it is left unbuilt rather than elaborately faked.
    service = ConversationService.__new__(ConversationService)
    service.repository = repository
    service.memory_coordinator = None
    service._persisted_traces = set()
    return service


async def _recall_vector(self, query, query_embedding=None):
    return {}


# The ordinary case must still write.
@pytest.mark.asyncio
async def test_a_turn_is_persisted_once(monkeypatch) -> None:
    monkeypatch.setattr(ConversationService, "_recall_vector", _recall_vector)
    repository = _Repository()
    service = _service(repository)

    await service._persist_completed_turn(
        "u", "c", "q", "answer", "trace-1", [], {}
    )

    assert len(repository.saved) == 1
    assert repository.saved[0]["response"] == "answer"


# The same trace twice is the bug this exists for.
@pytest.mark.asyncio
async def test_the_same_trace_never_writes_twice(monkeypatch) -> None:
    monkeypatch.setattr(ConversationService, "_recall_vector", _recall_vector)
    repository = _Repository()
    service = _service(repository)

    await service._persist_completed_turn(
        "u", "c", "q", "first", "trace-1", [], {}
    )
    await service._persist_completed_turn(
        "u", "c", "q", "second - a duplicate write", "trace-1", [], {}
    )

    assert len(repository.saved) == 1, repository.saved
    # The first write wins. A later call is a mistake, not a correction, so it
    # must not overwrite an answer the person has already been shown.
    assert repository.saved[0]["response"] == "first"


# Different turns must not be confused for one another.
@pytest.mark.asyncio
async def test_different_traces_each_write(monkeypatch) -> None:
    monkeypatch.setattr(ConversationService, "_recall_vector", _recall_vector)
    repository = _Repository()
    service = _service(repository)

    await service._persist_completed_turn("u", "c", "q", "a", "trace-1", [], {})
    await service._persist_completed_turn("u", "c", "q", "b", "trace-2", [], {})

    assert len(repository.saved) == 2


# A turn with no trace id must not be silently swallowed by the guard.
@pytest.mark.asyncio
async def test_a_turn_without_a_trace_is_still_written(monkeypatch) -> None:
    monkeypatch.setattr(ConversationService, "_recall_vector", _recall_vector)
    repository = _Repository()
    service = _service(repository)

    await service._persist_completed_turn("u", "c", "q", "a", "", [], {})
    await service._persist_completed_turn("u", "c", "q", "b", "", [], {})

    # Two writes, because an empty trace identifies nothing. Deduplicating on
    # it would collapse unrelated turns into one - a far worse failure than the
    # duplicate this guards against.
    assert len(repository.saved) == 2
