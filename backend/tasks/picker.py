"""Which saved item the person means, decided by the model from their words.

Used for tasks ("cancel the weather one") and skills ("forget the morning
one") alike: both are short lists of things the person named by meaning.
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

from backend.core.llm import LLMClient
from backend.core.prompts import load

from .describe import describe_task


# The id of the item `which` refers to, or None when none of them does.
# One candidate is chosen without asking: there is nothing to tell apart.
# Two or more go to the model.
async def pick_one(
    llm: LLMClient,
    which: str,
    items: list[dict[str, Any]],
    describe: Callable[[dict[str, Any]], str],
) -> str | None:
    if not items:
        return None
    if len(items) == 1:
        return str(items[0]["id"])
    ids = [str(item["id"]) for item in items]
    tool = {
        "type": "function",
        "function": {
            "name": "pick_item",
            "description": "Name the one item the person is referring to.",
            "parameters": {
                "type": "object",
                "properties": {"item_id": {"type": "string", "enum": ids}},
                "required": ["item_id"],
                "additionalProperties": False,
            },
        },
    }
    listing = "\n".join(f"- id {item['id']}: {describe(item)}" for item in items)
    messages = [
        {"role": "system", "content": load("tasks/pick")},
        {
            "role": "user",
            "content": f"Items:\n{listing}\n\nThe person said: {which}",
        },
    ]
    try:
        message = await asyncio.to_thread(llm.chat_with_tools, messages, [tool], 64)
    except Exception:
        return None
    return _chosen(message, set(ids))


# The task `which` refers to, described as a task.
async def pick_task(
    llm: LLMClient, which: str, tasks: list[dict[str, Any]]
) -> str | None:
    return await pick_one(llm, which, tasks, describe_task)


# The skill `which` refers to, described by name and what it does.
async def pick_skill(
    llm: LLMClient, which: str, skills: list[dict[str, Any]]
) -> str | None:
    return await pick_one(
        llm,
        which,
        skills,
        lambda skill: (
            f"{skill.get('name', '')} - "
            f"{str(skill.get('description') or skill.get('instruction') or '')[:160]}"
        ),
    )


# The id a pick_item call named, when it named one that was offered.
def _chosen(message: dict[str, Any], offered: set[str]) -> str | None:
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return None
    function = calls[0].get("function") if isinstance(calls[0], dict) else None
    if not isinstance(function, dict):
        return None
    raw = function.get("arguments")
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    item_id = arguments.get("item_id") if isinstance(arguments, dict) else None
    return str(item_id) if item_id in offered else None
