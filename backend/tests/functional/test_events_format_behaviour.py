"""Are events presented the agreed way, whatever route produced them?

Arsalon's format, made the default for everyone: the operator's next events
answer arrived through a plain web search without it (2026-08-26), because
the format lived in a skill the router had not invoked. The result ranker
now flags events and the reply renders prompts/reply/events_format.md.

The links are offered, not printed - the typed listing moved to that on
2026-09-05 (backend/core/event_links.py) and this prose fallback must hold
the same line, which it had not until 2026-09-07 (it printed grounded map
links, caught by exercise_search_scenarios on every deploy from 2026-09-06).
The assertions are on the property - no printed address, an offer of the
links, a stated price - so a reworded prompt survives.
"""

from __future__ import annotations

import re

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages

pytestmark = pytest.mark.asyncio

_CONTEXT = {
    "capabilities": [{"label": "Web search", "description": "Look things up."}],
    "search": [
        {
            "title": "Salsa Night at Clarendon Ballroom",
            "url": "https://clarendonballroom.example/salsa",
            "content": "Saturday August 29, 2026, 9 PM, Clarendon Ballroom, Arlington, VA. DJ Mambo. Beginner lesson at 8, $15 at the door.",
            "provider": "brave",
        },
        {
            "title": "Jazz on the Lawn at Lubber Run | Arlington Arts",
            "url": "https://arts.arlingtonva.us/lubber-run",
            "content": "Sunday August 30, 2026, 7 PM, Lubber Run Amphitheater, Arlington, VA. The Bobby Muncy Quartet. Free outdoor concert.",
            "provider": "brave",
        },
    ],
    "search_state": {"ran": True},
    "events_format": True,
}


async def test_events_come_back_in_the_agreed_shape(llm) -> None:
    messages = [{"role": "system", "content": _build_system_prompt(_CONTEXT)}]
    messages.extend(turn_context_messages(_CONTEXT))
    messages.append({"role": "user", "content": "what events are happening in Arlington Virginia this weekend?"})
    text = str(llm.chat(messages, 700, None, 0.0)["content"])
    lowered = text.lower()
    # No address is printed - the map, calendar and page links are offered and
    # sent on request, never written into the listing.
    assert "maps.google.com/?q=" not in lowered, text
    assert "youtube.com/results?search_query=" not in lowered, text
    assert not re.search(r"https?://", lowered), "printed a web address: " + text
    # The links are offered at the end, in the same words the typed listing
    # uses, so the prose fallback and the code listing hold one line.
    assert "want the map" in lowered, "no offer of the links: " + text
    assert "$15" in text or "15" in text, text
    assert "free" in lowered, text
    assert not re.search(r"^#", text, re.M), "a header in a phone message: " + text
    assert "instagram.com/" not in lowered, "invented an Instagram link: " + text
