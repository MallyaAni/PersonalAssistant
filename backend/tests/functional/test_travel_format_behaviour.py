"""Is a trip answered by its shape first, with fares labelled for what they are?

The operator asked for the cheapest nonstop to Rome and back from the
Amalfi coast (2026-08-26) and got "ITA nonstop Rome to Amalfi from $86": a
route that does not exist, a teaser presented as a quote, no reasoning
about the legs. This sends aggregator-style evidence to the real reply
model with the trip format and holds the answer to the shape first, the
airport Amalfi actually uses, no fare for a non-route, and every price
labelled indicative.
"""

from __future__ import annotations

import re

import pytest

from backend.agents.graph import _build_system_prompt, turn_context_messages
from backend.tests.functional.semantic import states

pytestmark = pytest.mark.asyncio

_CONTEXT = {
    "capabilities": [{"label": "Web search", "description": "Look things up."}],
    "search": [
        {
            "title": "Cheap Flights from Washington to Rome (IAD - FCO) | Skyscanner",
            "url": "https://www.skyscanner.com/routes/iad/fco/",
            "content": "Nonstop flights from Washington Dulles to Rome Fiumicino from $412 one way. United flies nonstop daily. October is one of the cheapest months.",
            "provider": "brave",
        },
        {
            "title": "Cheap Flights from Rome to Amalfi Coast | KAYAK",
            "url": "https://www.kayak.com/flight-routes/Rome-FCO/Amalfi-Coast",
            "content": "Fly from Rome to Amalfi Coast from $86. ITA Airways offers the most nonstop flights. The closest airport to the Amalfi Coast is Naples.",
            "provider": "brave",
        },
        {
            "title": "Flights from Naples (NAP) to Washington, D.C. | Google Flights",
            "url": "https://www.google.com/travel/flights/flights-from-naples-to-washington.html",
            "content": "No nonstop flights from Naples to Washington. One-stop from $520 via JFK or Newark. Nonstop Naples to New York JFK operates seasonally through October.",
            "provider": "brave",
        },
    ],
    "search_state": {"ran": True},
    "travel_format": True,
}
_QUESTION = (
    "i took off work from October 2 to 16. planning one way trip to rome and "
    "then back from amalfi coast. cheapest non stop option ironically?"
)


async def test_a_trip_is_answered_by_its_shape_with_fares_labelled_indicative(llm) -> None:
    messages = [{"role": "system", "content": _build_system_prompt(_CONTEXT)}]
    messages.extend(turn_context_messages(_CONTEXT))
    messages.append({"role": "user", "content": _QUESTION})
    text = str(llm.chat(messages, 700, None, 0.0)["content"])
    lowered = text.lower()
    assert "naples" in lowered, text
    assert not re.search(r"rome\s*(to|-|→)\s*amalfi", lowered), "sold a flight to Amalfi: " + text
    assert "indicative" in lowered or "teaser" in lowered or "not a quote" in lowered, text
    assert states(
        text,
        "The reply explains the shape of the trip - which airports each leg uses and "
        "whether a nonstop exists - before or alongside any prices, and says that no "
        "nonstop flies from Naples to Washington.",
    ), text
    assert not states(
        text,
        "The reply presents a specific dollar fare as the actual price for the "
        "reader's dates rather than as an indicative or example figure.",
    ), text
