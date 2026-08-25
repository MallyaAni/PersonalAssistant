"""Does a conditional scheduled check stay quiet when there is nothing to say?

"Message me each morning if search credits are below 100" fires every
morning. The reply model is told to answer with exactly NOTHING_TO_REPORT
when the condition does not hold, and the runner drops that reply. Both
halves are measured here against the real reply model: silence when credits
are fine, the number when they are not.
"""

from __future__ import annotations

import json

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.tasks.quiet import is_nothing_to_report

pytestmark = pytest.mark.asyncio

_INSTRUCTION = "message me each morning if search credits are below 100"


def _context(spent: int, limit: int) -> dict:
    return {
        "scheduled_task": True,
        "capabilities": [{"label": "Search credits", "description": "The search meter."}],
        "tool_results": [
            {
                "server_id": "internet",
                "tool_name": "search_credits",
                "content": json.dumps(
                    {
                        "provider": "tavily",
                        "plan": "Researcher",
                        "spent": spent,
                        "limit": limit,
                        "remaining": limit - spent,
                        "percent_used": round(100.0 * spent / limit, 1),
                    }
                ),
                "status": "succeeded",
                "warning_markers": [],
            }
        ],
    }


def _reply(llm, context: dict) -> str:
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": _INSTRUCTION})
    return str(llm.chat(messages, 200, None, 0.0)["content"])


async def test_a_check_with_nothing_to_say_answers_with_the_silence_token(llm) -> None:
    reply = _reply(llm, _context(spent=200, limit=1000))
    assert is_nothing_to_report(reply), reply


async def test_a_check_that_trips_reports_the_number(llm) -> None:
    reply = _reply(llm, _context(spent=993, limit=1000))
    assert not is_nothing_to_report(reply), reply
    assert "7" in reply and ("1,000" in reply or "1000" in reply), reply
