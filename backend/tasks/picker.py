"""Which saved task the person means, decided by the model from their words."""

import asyncio
from typing import Any

from backend.core.llm import LLMClient
from backend.core.prompts import load

from .describe import describe_task


# The id of the task `which` refers to, or None when none of them does.
# One task is chosen without asking: with a single candidate there is
# nothing to tell apart. Two or more go to the model.
async def pick_task(
    llm: LLMClient, which: str, tasks: list[dict[str, Any]]
) -> str | None:
    if not tasks:
        return None
    if len(tasks) == 1:
        return str(tasks[0]["id"])
    ids = [str(task["id"]) for task in tasks]
    tool = {
        "type": "function",
        "function": {
            "name": "pick_task",
            "description": "Name the one task the person is referring to.",
            "parameters": {
                "type": "object",
                "properties": {"task_id": {"type": "string", "enum": ids}},
                "required": ["task_id"],
                "additionalProperties": False,
            },
        },
    }
    listing = "\n".join(f"- id {task['id']}: {describe_task(task)}" for task in tasks)
    messages = [
        {"role": "system", "content": load("tasks/pick")},
        {
            "role": "user",
            "content": f"Tasks:\n{listing}\n\nThe person said: {which}",
        },
    ]
    try:
        message = await asyncio.to_thread(llm.chat_with_tools, messages, [tool], 64)
    except Exception:
        return None
    return _chosen(message, set(ids))


# The id a pick_task call named, when it named one that was offered.
def _chosen(message: dict[str, Any], offered: set[str]) -> str | None:
    import json

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
    task_id = arguments.get("task_id") if isinstance(arguments, dict) else None
    return str(task_id) if task_id in offered else None
