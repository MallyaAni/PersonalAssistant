"""An invoked skill's instruction is routed with the message that invoked it."""

from __future__ import annotations

import pytest

from backend.services.conversation_service import ConversationService
from backend.services.main_action_selector import MainAction, SearchAction
from backend.tests.doubles import StubConversationRepository, StubMemoryService, StubTracer
from backend.tools.actions import UseSkillAction


class _RecordingSelector:
    def __init__(self) -> None:
        self.routed: list[str] = []

    async def select(self, user_id, query, history, active_image_artifact_id, **kwargs) -> MainAction:
        self.routed.append(query)
        return SearchAction(query="events in Canggu this weekend", max_results=None)

    def describe_capabilities(self):
        return []


class _NoopLLM:
    def generate_text(self, prompt, max_tokens=512):
        return "unused"

    def chat(self, messages, max_tokens=512, response_schema=None, temperature=None):
        return {"content": "unused"}

    def stream_chat(self, messages, max_tokens=512):
        yield "ok"


@pytest.mark.asyncio
async def test_the_instruction_travels_with_the_message_that_invoked_it() -> None:
    selector = _RecordingSelector()
    service = ConversationService(
        memory=StubMemoryService(),
        llm=_NoopLLM(),  # type: ignore[arg-type]
        repository=StubConversationRepository(),
        tracer=StubTracer(),
        main_action_selector=selector,  # type: ignore[arg-type]
    )
    skill = UseSkillAction("pack:what-s-on", "What's on", "Search the web now for what is on.", source="pack")
    inner, context = await service._resolve_skill(
        "arsalon", skill, [], None, False, asked="what's on in canggu this weekend?"
    )
    assert isinstance(inner, SearchAction)
    assert selector.routed == [
        "Search the web now for what is on.\n\nThe message this is for: what's on in canggu this weekend?"
    ]
    assert context["skill"]["name"] == "What's on"


@pytest.mark.asyncio
async def test_without_a_message_the_instruction_is_routed_alone() -> None:
    selector = _RecordingSelector()
    service = ConversationService(
        memory=StubMemoryService(),
        llm=_NoopLLM(),  # type: ignore[arg-type]
        repository=StubConversationRepository(),
        tracer=StubTracer(),
        main_action_selector=selector,  # type: ignore[arg-type]
    )
    skill = UseSkillAction("s1", "morning brief", "Give the weather then the tasks.")
    await service._resolve_skill("u", skill, [], None, False)
    assert selector.routed == ["Give the weather then the tasks."]
