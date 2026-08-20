"""Recall searches what the user said, not only what a classifier kept.

An account with fourteen stored conversations had zero rows in semantic memory.
Her job, her constraints and her frustration were never lost - they sit in
`conversations` - but only the promoted subset was searchable, and the 4B
classifier that decides what gets promoted captures attributes ("my dog is
Biscuit") and misses circumstances ("I cover phone lines for executives"). A
category it was never taught is a thing that can never be remembered.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.agents.graph import _build_system_prompt, _render_recalled_turns
from backend.config.settings import settings


@pytest.fixture
def recall_enabled():
    original = settings.MEMORY_RECALL_TURNS_ENABLED
    settings.MEMORY_RECALL_TURNS_ENABLED = True
    yield
    settings.MEMORY_RECALL_TURNS_ENABLED = original


def test_recalled_turns_are_quoted_as_the_users_own_words():
    rendered = _render_recalled_turns(
        [{"said": "I cover phone lines for executives", "when": "2026-08-19"}]
    )

    assert "I cover phone lines for executives" in rendered
    # The distinction that matters: a promoted fact is something the
    # application asserts; this is something they told us and may have changed.
    assert "their own words" in rendered
    assert "attribute them as something they told you" in rendered
    assert "may have stopped being true" in rendered


def test_nothing_is_claimed_when_nothing_was_recalled():
    assert _render_recalled_turns([]) == ""
    assert _render_recalled_turns([{"said": "   "}]) == ""


def test_the_prompt_carries_recalled_turns():
    prompt = _build_system_prompt(
        {"recalled_turns": [{"said": "I have two kids", "when": "2026-08-01"}]},
        now=datetime(2026, 8, 19, tzinfo=UTC),
    )

    assert "I have two kids" in prompt
    assert "Recalled from earlier:" in prompt


def test_no_recall_block_appears_without_recalled_turns():
    prompt = _build_system_prompt({}, now=datetime(2026, 8, 19, tzinfo=UTC))

    assert "Recalled from earlier:" not in prompt


class StubRecallMemory:
    """Return one controlled recall without reaching a database."""

    def __init__(self, turns: list[dict[str, Any]] | None = None) -> None:
        self.turns = turns or []
        self.calls: list[dict[str, Any]] = []

    async def get_recalled_turns(
        self,
        user_id: str,
        query_embedding: list[float],
        top_k: int,
        max_cosine_distance: float,
        exclude_conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "user_id": user_id,
                "top_k": top_k,
                "distance": max_cosine_distance,
                "excluded": exclude_conversation_id,
            }
        )
        return self.turns


def _service(memory: Any):
    from backend.services.conversation_service import ConversationService
    from backend.tests.doubles import (
        StubConversationRepository,
        StubTracer,
    )

    return ConversationService(
        memory=memory,
        llm=None,  # type: ignore[arg-type]
        repository=StubConversationRepository(),
        tracer=StubTracer(),
    )


# The switch is what makes this reversible without a redeploy, so it is pinned
# here rather than left to whatever the default happens to be.
@pytest.mark.asyncio
async def test_the_switch_turns_recall_off():
    original = settings.MEMORY_RECALL_TURNS_ENABLED
    settings.MEMORY_RECALL_TURNS_ENABLED = False
    memory = StubRecallMemory([{"said": "something"}])
    try:
        recalled = await _service(memory)._recall_past_turns("u", "c", [0.1] * 768)
    finally:
        settings.MEMORY_RECALL_TURNS_ENABLED = original

    assert recalled == []
    assert memory.calls == []


# The current conversation's recent turns are already supplied as history;
# recalling them again would spend the context budget repeating what is
# directly above.
@pytest.mark.asyncio
async def test_the_current_conversation_is_excluded(recall_enabled):
    memory = StubRecallMemory()

    await _service(memory)._recall_past_turns("u", "conversation-1", [0.1] * 768)

    assert memory.calls[0]["excluded"] == "conversation-1"
    assert memory.calls[0]["distance"] == (
        settings.MEMORY_RECALL_TURNS_MAX_COSINE_DISTANCE
    )


# Without a query embedding there is nothing to search with, and computing one
# here would duplicate the turn's own.
@pytest.mark.asyncio
async def test_no_embedding_means_no_recall(recall_enabled):
    memory = StubRecallMemory([{"said": "something"}])

    assert await _service(memory)._recall_past_turns("u", "c", None) == []
    assert memory.calls == []


# Recall is an improvement to a turn, never a requirement of one.
@pytest.mark.asyncio
async def test_a_failed_recall_costs_the_recall_and_not_the_turn(recall_enabled):
    class BrokenMemory:
        async def get_recalled_turns(self, *args: Any, **kwargs: Any):
            raise RuntimeError("database unavailable")

    assert (
        await _service(BrokenMemory())._recall_past_turns("u", "c", [0.1] * 768) == []
    )


# A question the user once asked says nothing about them, and it embeds close
# to the question they are asking now - closer than the statement that would
# answer it. Measured on real history: "what do I like to watch?" matched an
# earlier "What are my interests?" at 0.361 and the true answer at 0.380.
def test_a_past_question_is_not_recalled():
    from backend.services.postgres_memory_service import _is_a_question

    assert _is_a_question("What are my interests?")
    assert _is_a_question("  do you have podcast recommendations?  ")
    assert not _is_a_question("I cover phone lines for executives")
    assert not _is_a_question("Please remember I am interested in horses")


# People repeat themselves, and three slots spent on one interest stated three
# times crowd out the other two things they said.
@pytest.mark.asyncio
async def test_repeats_do_not_consume_the_recall_budget():
    from backend.services.postgres_memory_service import PostgresMemoryService

    class Turn:
        def __init__(self, said: str) -> None:
            self.query = said
            self.created_at = None

    class Repo:
        async def get_recalled_turns(self, *args: Any, **kwargs: Any):
            return [
                (Turn("I am interested in horses"), 0.30),
                (Turn("i am interested in horses"), 0.31),
                (Turn("What are my interests?"), 0.32),
                (Turn("I cover phone lines for executives"), 0.38),
            ]

    service = PostgresMemoryService.__new__(PostgresMemoryService)
    service.repo = Repo()

    recalled = await service.get_recalled_turns("u", [0.1] * 768, 3, 0.45)

    said = [item["said"] for item in recalled]
    assert said == ["I am interested in horses", "I cover phone lines for executives"]
