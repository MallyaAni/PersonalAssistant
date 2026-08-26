"""Does the reply know where the person is?

"Good ramen near me?" and "how long to drive to Dulles?" were answered "I
don't know where you are" for an account whose locality was Arlington,
Virginia (2026-08-26, found by sweep_journeys). The router had the place;
the reply now does too.
"""

from __future__ import annotations

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.tests.functional.semantic import states

pytestmark = pytest.mark.asyncio

_CONTEXT = {
    "capabilities": [{"label": "Web search", "description": "Look things up."}],
    "place": "Arlington, Virginia",
    "search_state": {"failed": True, "quota": "today", "shared": False, "resets": "tomorrow"},
}


@pytest.mark.parametrize(
    "question",
    ["how long will it take me to drive to Dulles airport at 5pm?", "good ramen place near me for dinner tonight?"],
)
async def test_the_reply_uses_the_persons_place_instead_of_asking(llm, question) -> None:
    messages = [{"role": "system", "content": _build_system_prompt(_CONTEXT)}]
    messages.extend(turn_context_messages(_CONTEXT))
    messages.append({"role": "user", "content": question})
    text = str(llm.chat(messages, 400, None, 0.0)["content"])
    assert text.strip()
    assert not states(text, "The reply asks the reader where they are or says it does not know their location."), text
    assert states(text, "The reply treats Arlington, Virginia as where the reader is."), text
