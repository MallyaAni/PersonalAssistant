"""When the router fails, the reply must not answer as though it had checked.

`_select_main_action` used to catch every failure and return None, the same
value as "the router chose nothing". The reply could not tell the two apart,
so a live-fact question after a router outage was answered from training with
no caveat - the 2026-09-04 review's second routing finding. The typed decision
now reaches the reply as a routing note; this measures what the real model
does with that note, because a structural test can only prove the note was
passed.
"""

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.core.dependencies import get_llm_client
from backend.tests.functional.semantic import states

pytestmark = pytest.mark.asyncio


def _ask(question: str, context_data: dict) -> str:
    llm = get_llm_client()
    messages = [
        {"role": "system", "content": _build_system_prompt(context_data)},
        *turn_context_messages(context_data),
        {"role": "user", "content": question},
    ]
    try:
        result = llm.chat(messages, 900, None, 0.0)
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(f"main model unreachable: {type(exc).__name__}")
    return str(result.get("content") or "").strip()


# The reported failure: with no search result and no routing note, the model
# answered a live-fact question as though it knew. Told the router failed, it
# has to say the check did not happen.
async def test_a_router_failure_is_disclosed_on_a_live_fact_question() -> None:
    answer = _ask(
        "What's the weather in Arlington tonight?",
        {"router_unavailable": "the router could not be reached: RuntimeError"},
    )

    assert states(
        answer,
        "says it could not check the weather or does not know it, rather than "
        "giving a forecast or a temperature",
    ), answer
    assert states(
        answer,
        "invites the person to ask again or says the check did not happen",
    ), answer


# NeedsInput is the other half: the router chose a tool but the message did
# not give a required field. The reply must ask for it, not decline and not
# claim the thing was set up.
async def test_missing_input_is_asked_for_rather_than_declined() -> None:
    answer = _ask(
        "Remind me to call the bank.",
        {"needs_input": "a time", "tool": "schedule_task"},
    )

    assert states(answer, "asks what time the reminder should be set for"), answer
    assert states(
        answer, "does not claim the reminder has already been set"
    ), answer
