"""A transient fact gets a short life, a durable one none.

A captured "feeling tired today" must not steer an unattended weekly
recommendation weeks later, which is what happened on 2026-08-31: a two-day-old
mood aimed the hiking search at "easy scenic nature walks" and put a hiking-
guide page ahead of the dance events the user actually asks for. The classifier
says whether a fact is a temporary state; this pins that the save path honours
it by attaching an expiry - and never attaches one to a durable fact, since
expiring a real trait would quietly delete it.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.services.conversation_service import (
    TRANSIENT_FACT_DAYS,
    ConversationService,
)
from backend.tests.doubles import StubConversationRepository, StubTracer

pytestmark = pytest.mark.asyncio


class RecordingMemory:
    """A memory service that records what a semantic-fact save asked for."""

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    async def save_semantic_memory(
        self,
        user_id: str,
        content: str,
        metadata: dict[str, Any],
        purpose: str = "user_explicit",
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        self.saved.append(
            {
                "content": content,
                "purpose": purpose,
                "expires_at": expires_at,
            }
        )
        return {"id": str(len(self.saved)), "content": content}


def _service(memory: RecordingMemory) -> ConversationService:
    return ConversationService(
        memory=memory,  # type: ignore[arg-type]
        llm=None,  # type: ignore[arg-type]
        repository=StubConversationRepository(),
        tracer=StubTracer(),
    )


async def _save_fact(service: ConversationService, candidate: dict[str, Any]) -> None:
    await service._save_semantic_fact_proposal(
        "u1", "c1", "00000000-0000-0000-0000-000000000000", candidate
    )


async def test_a_transient_fact_is_saved_with_a_short_expiry():
    before = datetime.now(UTC)
    service = _service(RecordingMemory())
    candidate = {
        "kind": "semantic_fact",
        "content": "The user is feeling tired today and wants something chill.",
        "is_preference": False,
        "is_transient": True,
    }

    await _save_fact(service, candidate)
    after = datetime.now(UTC)

    (saved,) = service.memory.saved  # type: ignore[attr-defined]
    assert saved["expires_at"] is not None, saved
    # The life is short and roughly one TRANSIENT_FACT_DAYS window, not forever.
    expected = before + timedelta(days=TRANSIENT_FACT_DAYS)
    assert saved["expires_at"] >= expected - timedelta(minutes=1), saved
    assert saved["expires_at"] <= after + timedelta(days=TRANSIENT_FACT_DAYS), saved


async def test_a_durable_fact_is_saved_without_an_expiry():
    service = _service(RecordingMemory())
    candidate = {
        "kind": "semantic_fact",
        "content": "The user is 30 years old.",
        "is_preference": False,
        "is_transient": False,
    }

    await _save_fact(service, candidate)

    (saved,) = service.memory.saved  # type: ignore[attr-defined]
    assert saved["expires_at"] is None, saved
