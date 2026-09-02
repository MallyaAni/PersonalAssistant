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


# Tokens the model may spend on its answer: a tool call carrying up to
# `count` ids. Saved items carry UUIDs, and a UUID is some 25 tokens of hex
# and dashes, so a fixed 64 held one id and not two: "delete the paused
# ones" over two real reminders came back truncated, parsed as nothing, and
# the reply reported a deletion that never happened (sweep, 2026-09-02).
# The functional test had passed on ids like "t-stretch".
def _answer_budget(count: int) -> int:
    return 64 + 40 * max(1, count)


# The id of the item `which` refers to, or None when none of them does.
# One candidate is chosen without asking: there is nothing to tell apart.
# Two or more go to the model.
async def pick_one(
    llm: LLMClient,
    which: str,
    items: list[dict[str, Any]],
    describe: Callable[[dict[str, Any]], str],
    hint: str = "",
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
            "description": (
                "Name the one item the person is referring to, or none when "
                "what they mean is not one of the items."
            ),
            "parameters": {
                "type": "object",
                # "none" is offered explicitly: a model given only ids reaches
                # for the closest one rather than declining to call.
                "properties": {"item_id": {"type": "string", "enum": [*ids, "none"]}},
                "required": ["item_id"],
                "additionalProperties": False,
            },
        },
    }
    listing = "\n".join(f"- id {item['id']}: {describe(item)}" for item in items)
    # What the assistant said just before is what "this", "that" and "it"
    # point at. Without it, "adjust this to daily at 3pm" after a message
    # about Scout's own sweep picked the person's stretch reminder - the
    # only daily task - and moved it (2026-08-26).
    said = f"What the assistant said just before: {hint.strip()[:600]}\n\n" if hint.strip() else ""
    messages = [
        {"role": "system", "content": load("tasks/pick")},
        {
            "role": "user",
            "content": f"{said}Items:\n{listing}\n\nThe person said: {which}",
        },
    ]
    try:
        message = await asyncio.to_thread(llm.chat_with_tools, messages, [tool], _answer_budget(1))
    except Exception:
        return None
    return _chosen(message, set(ids))


# The task `which` refers to, described as a task.
async def pick_task(
    llm: LLMClient, which: str, tasks: list[dict[str, Any]], hint: str = ""
) -> str | None:
    return await pick_one(llm, which, tasks, describe_task, hint=hint)


# Every task `which` refers to - one or several. "Delete the paused ones"
# names a set, so a picker that returned only one id would leave the rest
# scheduled. See pick_many.
async def pick_many_tasks(
    llm: LLMClient, which: str, tasks: list[dict[str, Any]], hint: str = ""
) -> list[str]:
    return await pick_many(llm, which, tasks, describe_task, hint=hint)


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


# The ids `which` refers to - possibly several ("the paused ones", "all the
# weather ones") - or an empty list when none of them does. One id is a
# valid answer; so is an empty one. A single `pick_one` cannot cancel a set:
# "delete the paused ones" (a real utterance) named several tasks and only
# one could ever be chosen, so the rest were silently kept.
async def pick_many(
    llm: LLMClient,
    which: str,
    items: list[dict[str, Any]],
    describe: Callable[[dict[str, Any]], str],
    hint: str = "",
) -> list[str]:
    if not items:
        return []
    ids = [str(item["id"]) for item in items]
    tool = {
        "type": "function",
        "function": {
            "name": "pick_items",
            "description": (
                "Name every item the person's words cover, or none when what "
                "they mean is not among the items. Their words may name one "
                "item or several."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_ids": {
                        "type": "array",
                        "items": {"type": "string", "enum": ids},
                    }
                },
                "required": ["item_ids"],
                "additionalProperties": False,
            },
        },
    }
    listing = "\n".join(f"- id {item['id']}: {describe(item)}" for item in items)
    # What the assistant said just before is what "this", "that" and "it"
    # point at, exactly as in pick_one.
    said = f"What the assistant said just before: {hint.strip()[:600]}\n\n" if hint.strip() else ""
    messages = [
        {"role": "system", "content": load("tasks/pick_many")},
        {
            "role": "user",
            "content": f"{said}Items:\n{listing}\n\nThe person said: {which}",
        },
    ]
    try:
        message = await asyncio.to_thread(llm.chat_with_tools, messages, [tool], _answer_budget(len(ids)))
    except Exception:
        return []
    return _chosen_many(message, set(ids))


# The ids a pick_items call named, in the order given, when each was offered.
def _chosen_many(message: dict[str, Any], offered: set[str]) -> list[str]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        return []
    function = calls[0].get("function") if isinstance(calls[0], dict) else None
    if not isinstance(function, dict):
        return []
    raw = function.get("arguments")
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    item_ids = arguments.get("item_ids") if isinstance(arguments, dict) else None
    if not isinstance(item_ids, list):
        return []
    return [str(item_id) for item_id in item_ids if str(item_id) in offered]
