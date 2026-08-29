"""What the model returns when asked to quote instead of to write.

The listing that reached a phone on 2026-08-29 had invented map links and
"Time: Sundays, 4 PM - 10 PM" - The Lawn's opening hours, printed where an
event's start time goes. The links are fenced now; this is the other half.
The reply model no longer writes the listing at all: one constrained call
turns results into records whose every factual field is a phrase copied from
the result it names, and code renders the rest
(`backend/core/event_extraction.py`, `backend/core/events_listing.py`).

Structural tests prove the checks reject what they should. Only this one can
say whether the model, asked for quotations, actually gives quotations - and
whether it correctly refuses to call a venue's opening hours an event time.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.core.dependencies import get_routing_llm_client
from backend.core.event_extraction import extract_events
from backend.core.events_listing import render_listing
from backend.core.grounding import states
from backend.core.links import URL_IN_TEXT, template_is_grounded

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)  # a Saturday

# Canggu as the providers actually returned it: one page that states a night,
# one that states only opening hours, one dated one-off, one pure directory.
RESULTS = [
    {
        "title": "The Lawn Canggu - Sunday Sessions",
        "url": "https://www.thelawncanggu.com/whats-on",
        "content": "Sunday Sessions at The Lawn, Batu Bolong. Every Sunday from 4pm with resident DJ Dea. Free entry before 6pm.",
    },
    {
        "title": "La Brisa Bali",
        "url": "https://labrisabali.com/events",
        "content": "La Brisa, Echo Beach, Canggu. Open daily 11am until late, kitchen until 10pm. Beachfront restaurant and bar.",
    },
    {
        "title": "Potato Head Beach Club - Sunset Session",
        "url": "https://potatohead.co/events",
        "content": "Sunset Session on Saturday 5 September 2026 at Potato Head, Seminyak. Doors 6pm, entry IDR 250k.",
    },
    {
        "title": "20 best beach clubs in Bali",
        "url": "https://example-travel.test/bali-beach-clubs",
        "content": "Our roundup of the twenty best beach clubs across Bali, updated regularly.",
    },
]
EVIDENCE = " ".join(f"{item['title']} {item['content']}" for item in RESULTS)


async def test_every_field_it_returns_was_really_in_the_result_it_names(llm):
    found = await extract_events(get_routing_llm_client(), RESULTS, NOW)
    print(f"\nkept={[e.name for e in found.events]} undated={found.undated} "
          f"hours={found.opening_hours} unsourced={found.unsourced}")

    # It must find something; a call that returns nothing on these results is
    # a broken prompt, not a cautious one.
    assert found.events, found

    for event in found.events:
        # The record names a result, and the phrase it read the time from is
        # in that result word for word. This is the check the 29 August
        # listing did not have.
        assert states(event.when_text, EVIDENCE), event
        assert event.source_url in {item["url"] for item in RESULTS}, event
        assert event.starts_at is not None, event
        # No model wrote a URL anywhere in the record.
        assert not URL_IN_TEXT.findall(f"{event.name} {event.venue} {event.what}"), event


async def test_a_venues_opening_hours_never_become_an_events_start_time(llm):
    # The exact failure. La Brisa publishes hours and no event; whatever else
    # the model does, it must not turn "open daily 11am until late" into a
    # night out.
    found = await extract_events(get_routing_llm_client(), RESULTS, NOW)
    for event in found.events:
        if "brisa" in event.venue.casefold():
            assert "open daily" not in event.when_text.casefold(), event
            assert "until late" not in event.when_text.casefold(), event


async def test_the_rendered_listing_carries_only_addresses_we_can_vouch_for(llm):
    found = await extract_events(get_routing_llm_client(), RESULTS, NOW)
    listing = render_listing(found, NOW)
    print(f"\n--- listing ---\n{listing}\n")
    assert listing.strip(), found
    sources = {item["url"] for item in RESULTS}
    for url in URL_IN_TEXT.findall(listing):
        cleaned = url.rstrip(".,;:!?)]}\"'")
        assert cleaned in sources or template_is_grounded(cleaned, EVIDENCE), (cleaned, listing)
    for invented in ("maps.app.goo.gl", "youtu.be/", "instagram.com"):
        assert invented not in listing, listing


async def test_a_directory_page_is_not_read_as_an_event(llm):
    # "20 best beach clubs in Bali" is a listicle. An extractor that turns it
    # into an event produces a listing that sends someone nowhere.
    found = await extract_events(get_routing_llm_client(), RESULTS, NOW)
    for event in found.events:
        assert "20 best" not in event.name.casefold(), event
        assert "roundup" not in event.what.casefold(), event
