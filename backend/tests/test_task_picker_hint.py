"""The task picker sees what the assistant just said, and vague words pick nothing."""

from __future__ import annotations

import json

import pytest

from backend.tasks.picker import pick_task

_TASKS = [
    {"id": "t-stretch", "instruction": "Remind me to stretch", "cadence": "daily", "hour": 18, "minute": 0, "timezone": "America/New_York"},
    {"id": "t-tito", "instruction": "Don Tito reminder", "cadence": "once", "hour": 19, "minute": 0, "timezone": "America/New_York"},
]


class _LLM:
    def __init__(self, pick: str | None) -> None:
        self.pick = pick
        self.messages = None

    def chat_with_tools(self, messages, tools, max_tokens):
        self.messages = messages
        if self.pick is None:
            return {"content": "none"}
        return {"tool_calls": [{"function": {"name": "pick_item", "arguments": json.dumps({"item_id": self.pick})}}]}


@pytest.mark.asyncio
async def test_the_previous_reply_is_handed_to_the_picker() -> None:
    llm = _LLM(None)
    chosen = await pick_task(llm, "this", _TASKS, hint="You mentioned the daily 7 AM Scout check.")
    assert chosen is None
    user = llm.messages[1]["content"]
    assert "What the assistant said just before: You mentioned the daily 7 AM Scout check." in user
    assert "The person said: this" in user


@pytest.mark.asyncio
async def test_without_a_hint_the_prompt_is_unchanged() -> None:
    llm = _LLM("t-tito")
    assert await pick_task(llm, "the don tito one", _TASKS) == "t-tito"
    assert "What the assistant said just before" not in llm.messages[1]["content"]
