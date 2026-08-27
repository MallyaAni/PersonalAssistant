"""A turn that continues a draft is offered no scheduling, task, Scout, skill
or history tool - the resolver's judgement, applied in code."""

from __future__ import annotations

import json
import os

import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.services.main_action_selector import MainActionSelector


class _Llm:
    """The resolver call (chat, with a schema) and the routing call (chat_with_tools)."""

    def __init__(self, refers_to: str) -> None:
        self.refers_to = refers_to
        self.offered: list[str] = []

    def chat(self, messages, max_tokens=256, response_schema=None, temperature=None):
        return {"content": json.dumps({"self_contained": "make the shift-coverage email more casual", "refers_to": self.refers_to, "subject": ""})}

    def chat_with_tools(self, messages, tools, max_tokens):
        self.offered = [tool["function"]["name"] for tool in tools]
        return {"content": "ok"}


_HISTORY = [{"query": "draft an email to my retail team asking for shift coverage", "response": "Subject: Shift coverage\n\nHi team, ..."}]


def _selector(llm):
    return MainActionSelector(llm, None, "internet", "search_web", tool_orchestration=None, diagram_enabled=True, presentation_enabled=True)


@pytest.mark.asyncio
async def test_a_draft_continuation_is_offered_no_automation():
    llm = _Llm("draft")
    await _selector(llm).select("u", "More casual", _HISTORY, None, skills=[{"id": "s1", "name": "Quick brief", "slug": "quick-brief", "instruction": "x"}])
    assert llm.offered, "the router was called"
    for name in ("schedule_task", "manage_tasks", "scout_schedule", "save_skill", "manage_skills", "search_history"):
        assert name not in llm.offered, llm.offered
    assert not any(name.startswith("skill__") for name in llm.offered), llm.offered
    assert "generate_image" in llm.offered


@pytest.mark.asyncio
async def test_any_other_reading_keeps_the_full_offer():
    llm = _Llm("subject")
    await _selector(llm).select("u", "and the villa?", _HISTORY, None)
    assert "manage_tasks" in llm.offered and "schedule_task" in llm.offered
