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


# What is known about the reader, as `_known_for_ranking` assembles it.
ANI = (
    "interests: salsa dance, bachata dance, swing dancing, live music",
    "Prefers quality events with people in their demographic; cost is not a concern.",
)
JEN = (
    "interests: true crime, mystery books, chocolate, theater",
    "Prefers a quiet evening with a story to a loud room.",
)

MIXED = [
    {
        "title": "Salsa Saturdays at Clarendon Ballroom",
        "url": "https://clarendonballroom.test/salsa",
        "content": "Salsa Saturdays at Clarendon Ballroom, Arlington. Every Saturday from 9pm, live band. Entry $20.",
    },
    {
        "title": "Mystery book club - Central Library",
        "url": "https://library.test/mystery",
        "content": "Mystery book club meets at Central Library, Arlington. Every Saturday from 2pm. Free.",
    },
]
MIXED_EVIDENCE = " ".join(f"{item['title']} {item['content']}" for item in MIXED)


async def test_the_line_it_writes_is_written_for_the_reader(llm):
    # The regression this closes: when the listing became code-rendered, the
    # reply model - which holds the person's memories - stopped being called on
    # events turns, and the extractor was told nothing about them. The one line
    # the model still writes was being written for a generic reader.
    for_ani = await extract_events(get_routing_llm_client(), MIXED, NOW, known=ANI)
    for_jen = await extract_events(get_routing_llm_client(), MIXED, NOW, known=JEN)
    said_to_ani = {event.name: event.what for event in for_ani.events}
    said_to_jen = {event.name: event.what for event in for_jen.events}
    print(f"\nto Ani: {said_to_ani}\nto Jen: {said_to_jen}")

    assert said_to_ani and said_to_jen
    shared = set(said_to_ani) & set(said_to_jen)
    assert shared, (said_to_ani, said_to_jen)
    # At least one event is described differently for the two of them. This is
    # the whole claim: the same page, two readers, two descriptions.
    assert any(said_to_ani[name] != said_to_jen[name] for name in shared), (
        said_to_ani,
        said_to_jen,
    )


async def test_knowing_the_reader_cannot_change_a_single_fact(llm):
    # The safety half. Whatever the description says, every factual field is
    # still a quotation checked against the result it names, so two readers get
    # the same events at the same times from the same sources.
    for_ani = await extract_events(get_routing_llm_client(), MIXED, NOW, known=ANI)
    for_jen = await extract_events(get_routing_llm_client(), MIXED, NOW, known=JEN)

    def facts(found):
        return sorted(
            (e.name, e.venue, e.starts_at, e.start_time, e.price_text, e.source_url)
            for e in found.events
        )

    assert facts(for_ani) == facts(for_jen), (facts(for_ani), facts(for_jen))
    for event in list(for_ani.events) + list(for_jen.events):
        assert states(event.when_text, MIXED_EVIDENCE), event
        assert not URL_IN_TEXT.findall(event.what), event


# The other half of the 2026-09-02 Arlington listing: American calendars
# write "Saturday, September 5" and "Fri, Sep 5 · 7:00 PM" without a year,
# and every such event used to be dropped as undated. The snippets below
# are the shape ARLnow, Patch and Eventbrite really return; the model must
# quote the phrases and the code must date them within the week asked.
US_NOW = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)
US_RESULTS = [
    {
        "url": "https://www.arlnow.com/events",
        "title": "Events | ARLnow",
        "content": (
            "## September 4, 2026  Lawn Games Social - 3351 Fairfax Dr Arlington, Virginia 22201  "
            "Chimney Swift Evening Birdwatching - 2909 16th St S Arlington, Virginia  "
            "## September 9, 2026  Storytime - 3351 Fairfax Dr Arlington, Virginia 22201"
        ),
    },
    {
        "url": "https://patch.com/virginia/arlington-va/calendar",
        "title": "Arlington Events Calendar - Arlington, VA Patch",
        "content": (
            "#### Saturday, September 5   Blithe Spirit 8:00 pm    Little Theatre of Alexandria, 600 Wolfe St, Alexandria  "
            "Courthaus Comedy Bunker 12: D. Lo 7:00 pm    Courthaus Social, 2300 Clarendon Blvd, Arlington  "
            "#### Sunday, September 6   Art Night - Try the Pottery Wheel, BYOB 6:00 pm    Art House 7, 5537 Lee Hwy, Arlington"
        ),
    },
    {
        "url": "https://www.eventbrite.com/d/va--arlington/events",
        "title": "Arlington, VA Events, Calendar & Tickets | Eventbrite",
        "content": (
            "### Salsa Night at Clarendon Ballroom  Fri, Sep 5 · 8:00 PM  Clarendon Ballroom, 3185 Wilson Blvd, Arlington  From $10.00  "
            "### Health IT Summit 2026  Today • 8:00 AM  Bethesda Marriott"
        ),
    },
]


async def test_american_calendar_dates_without_a_year_are_kept_and_dated(llm):
    found = await extract_events(get_routing_llm_client(), US_RESULTS, US_NOW)
    dated = {event.name.casefold(): event.day.isoformat() for event in found.events if event.day is not None}
    assert len(dated) >= 4, (dated, found.undated, found.unsourced)
    for name, day in dated.items():
        assert day.startswith("2026-09"), (name, day)
    week = [day for day in dated.values() if "2026-09-04" <= day <= "2026-09-06"]
    assert len(week) >= 3, dated
