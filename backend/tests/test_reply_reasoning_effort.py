"""The reply may reason without every bounded helper inheriting that effort.

The serving engine counts thinking tokens against `max_tokens`. The streamed
reply has a large budget, but the search planner, document facts, vision
reasoner and digest writer share the same client with budgets of a few hundred
to a few thousand tokens, where thinking consumes the budget and returns empty
content. So the reply gets its own client and its own setting.
"""

import pytest

from backend.config.settings import settings
from backend.core.dependencies import get_llm_client, get_reply_llm_client
from backend.core.llm import LLMClient
from backend.services.conversation_service import ConversationService
from backend.tests.doubles import (
    StubConversationRepository,
    StubMemoryService,
    StubTracer,
)


class _RecordingLLM(LLMClient):
    """Stream a fixed answer and count how often the reply path used it."""

    # Hold the answer this fake returns and how often it was streamed.
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.streamed = 0

    # Return the fixed answer for non-streaming callers.
    def generate_text(self, prompt, max_tokens=512):
        return self.answer

    # Return the fixed answer for ordinary chat callers.
    def chat(self, messages, max_tokens=512):
        return {"content": self.answer}

    # Stream the fixed answer and record that the reply path reached this client.
    def stream_chat(self, messages, max_tokens=512):
        self.streamed += 1
        yield self.answer


# Drain a turn and return only what the person would read.
async def _answer(service: ConversationService, query: str) -> str:
    chunks: list[str] = []
    async for event in service.process_request(
        "reply-effort-user",
        query,
        "11111111-1111-4111-8111-111111111111",
    ):
        if event["event"] == "delta":
            chunks.append(event["data"]["content"])
    return "".join(chunks)


# An unset reply effort follows the main one; a configured value wins.
@pytest.mark.parametrize(
    ("reply_effort", "expected"),
    [("", "low"), ("high", "high")],
)
def test_the_reply_effort_falls_back_only_when_empty(
    monkeypatch: pytest.MonkeyPatch, reply_effort: str, expected: str
) -> None:
    monkeypatch.setattr(settings, "MAIN_LLM_REASONING_EFFORT", "low")
    monkeypatch.setattr(settings, "REPLY_LLM_REASONING_EFFORT", reply_effort)

    assert get_reply_llm_client().reasoning_effort == expected


# The reply client moves only the effort, never the model it talks to.
def test_the_reply_client_keeps_the_main_model_with_its_own_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIN_LLM_REASONING_EFFORT", "none")
    monkeypatch.setattr(settings, "REPLY_LLM_REASONING_EFFORT", "high")

    main = get_llm_client()
    reply = get_reply_llm_client()

    assert main.reasoning_effort == "none"
    assert reply.reasoning_effort == "high"
    assert reply.base_url == main.base_url
    assert reply.model == main.model


# A caller that does not distinguish the two keeps replying on the main client.
@pytest.mark.asyncio
async def test_a_service_without_a_reply_client_replies_on_the_main_client() -> None:
    llm = _RecordingLLM("main answer")
    service = ConversationService(
        memory=StubMemoryService(),
        llm=llm,
        repository=StubConversationRepository(),
        tracer=StubTracer(),
    )

    assert await _answer(service, "hello") == "main answer"
    assert llm.streamed == 1


# A configured reply client is the one the reply turn streams from.
@pytest.mark.asyncio
async def test_a_service_with_a_reply_client_hands_it_to_the_reply_turn() -> None:
    main = _RecordingLLM("main answer")
    reply = _RecordingLLM("reply answer")
    service = ConversationService(
        memory=StubMemoryService(),
        llm=main,
        reply_llm=reply,
        repository=StubConversationRepository(),
        tracer=StubTracer(),
    )

    assert await _answer(service, "hello") == "reply answer"
    assert reply.streamed == 1
    assert main.streamed == 0
