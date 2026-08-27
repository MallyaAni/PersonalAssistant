"""A search that already ran is not narrated as about to happen.

The sweep's "place nearby" journey on the deployed build of 2026-08-26
answered "Let me check what's around. Based on a quick search, I found..."
with eight live results in hand. The search-state block now forbids the
narration; this pins it against the real reply model.
"""

from __future__ import annotations

import re

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages

pytestmark = pytest.mark.asyncio

_NARRATED = re.compile(
    r"let me (check|look|search|find|see)|i'?ll (check|look|search|find)|give me a (sec|moment)|checking now|looking that up",
    re.IGNORECASE,
)

_RESULTS = [
    {"title": "Ramen Nippon - Arlington", "url": "https://example.com/nippon",
     "content": "Tonkotsu and shoyu ramen in Clarendon, open until 10 PM daily; counter seating, no reservations."},
    {"title": "Yume Ramen, Ballston", "url": "https://example.com/yume",
     "content": "Spicy miso ramen and vegetarian broth near Ballston Metro, open 5-9:30 PM tonight."},
    {"title": "Arlington ramen guide", "url": "https://example.com/guide",
     "content": "Three ramen spots within 15 minutes of Rosslyn, with hours and price ranges."},
]


async def test_a_reply_with_results_in_hand_does_not_narrate_the_check(llm) -> None:
    context = {
        "channel": "imessage",
        "search": _RESULTS,
        "search_state": {"ran": True},
        "place": "Arlington, Virginia",
    }
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": "good ramen place near me for dinner tonight?"})
    for _ in range(2):
        text = str(llm.chat(messages, 400, None, 0.0)["content"])
        assert not _NARRATED.search(text), text
        assert "ramen" in text.lower(), text
