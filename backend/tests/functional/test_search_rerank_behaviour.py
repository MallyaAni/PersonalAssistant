"""Does the main model put the local, on-date results first?

An Arlington weekend query returned a festival at Snowshoe, West Virginia
among the listings (2026-08-25), and the 0.6B cross-encoder, tried first,
ranked it second. This sends the real results shape to the real model with
the person's place and asserts the far-away and off-date results sink below
every local, on-date one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.core.dependencies import get_routing_llm_client
from backend.core.result_ranking import order_by_usefulness
from backend.services.conversation_service import _rerank_web_results

pytestmark = pytest.mark.asyncio

_RESULTS = [
    {
        "title": "Ballhooter Festival 2026 | Bandsintown",
        "url": "https://www.bandsintown.com/c/arlington-va",
        "content": "Ballhooter Festival 2026 at Snowshoe Mountain, West Virginia. Two days of music on the mountain.",
    },
    {
        "title": "DC JazzFest at The Wharf",
        "url": "https://www.dcjazzfest.org/",
        "content": "DC JazzFest returns to The Wharf, Washington DC, September 5-6, 2026.",
    },
    {
        "title": "Arlington Farmers Market | Arlington County",
        "url": "https://www.arlingtonva.us/Government/Programs/Farmers-Markets",
        "content": "Saturday August 29, 2026, 8 AM to noon, Courthouse Plaza, Arlington, VA. Produce, bakers, music.",
    },
    {
        "title": "Jazz on the Lawn at Lubber Run | Arlington Arts",
        "url": "https://arts.arlingtonva.us/lubber-run",
        "content": "Sunday August 30, 2026, 7 PM, Lubber Run Amphitheater, Arlington, VA. Free outdoor concert.",
    },
]
_QUESTION = "what events are happening in Arlington Virginia this weekend?"
_NOW = datetime(2026, 8, 25, 18, 0, tzinfo=UTC)


async def test_far_away_and_off_date_results_sink_below_the_local_on_date_ones() -> None:
    llm = get_routing_llm_client()
    candidates = [dict(r) for r in _RESULTS]

    async def rank_call(question, documents):
        return await order_by_usefulness(llm, _QUESTION, "Arlington, Virginia", candidates, now=_NOW)

    ordered = await _rerank_web_results(rank_call, _QUESTION, candidates, keep=8)
    titles = [r["title"] for r in ordered]
    assert all("rerank_score" in r for r in ordered), ordered
    local = [i for i, t in enumerate(titles) if "Arlington" in t]
    assert titles.index("Ballhooter Festival 2026 | Bandsintown") > max(local), titles
    assert titles.index("DC JazzFest at The Wharf") > max(local), titles
