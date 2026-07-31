import os
from datetime import UTC

import httpx
import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.events import (
    MAX_EVENTS_PER_SOURCE,
    FeedError,
    clean_text,
    clean_url,
)
from backend.discovery.fetching import (
    RequestBudget,
    RequestBudgetExceededError,
    fetch_feed,
)
from backend.discovery.sources.ics import parse_ics
from backend.discovery.sources.rss import parse_feed


def _calendar(*blocks: str) -> str:
    body = "\r\n".join(blocks)
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n{body}\r\nEND:VCALENDAR\r\n"


# A folded line, escaped punctuation, and a zone-qualified start are the three
# things a real venue calendar uses that a naive line split gets wrong.
def test_ics_unfolds_lines_unescapes_text_and_resolves_a_zone():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:evt-1@venue",
        "SUMMARY:Jazz night\\, upstairs\\; late set",
        "DESCRIPTION:First line\\nSecond line with a folded",
        "  continuation",
        "DTSTART;TZID=America/New_York:20260815T190000",
        "DTEND;TZID=America/New_York:20260815T230000",
        "LOCATION:The Cellar",
        "URL:https://venue.example/jazz",
        "END:VEVENT",
    )

    events = parse_ics(payload, "venue")

    assert len(events) == 1
    event = events[0]
    assert event.external_id == "evt-1@venue"
    assert event.title == "Jazz night, upstairs; late set"
    assert event.summary == "First line Second line with a folded continuation"
    assert event.place == "The Cellar"
    assert event.url == "https://venue.example/jazz"
    assert event.starts_at is not None
    assert event.starts_at.hour == 19
    assert event.starts_at.utcoffset() is not None
    assert event.is_schedulable is True


# An escaped backslash immediately before a comma must stay a literal
# backslash. Chained replacements re-read it as an escaped comma and eat it.
def test_ics_unescapes_a_literal_backslash_before_punctuation():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:esc",
        "SUMMARY:AC\\\\\\,DC tribute",
        "DTSTART:20260815T200000Z",
        "END:VEVENT",
    )

    events = parse_ics(payload, "venue")

    assert events[0].title == "AC\\,DC tribute"


def test_ics_reads_utc_and_all_day_values():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:utc",
        "SUMMARY:Broadcast",
        "DTSTART:20260815T230000Z",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:allday",
        "SUMMARY:Street fair",
        "DTSTART;VALUE=DATE:20260816",
        "END:VEVENT",
    )

    events = parse_ics(payload, "venue", default_timezone="America/New_York")
    by_id = {event.external_id: event for event in events}

    assert by_id["utc"].starts_at is not None
    assert by_id["utc"].starts_at.tzinfo == UTC
    assert by_id["utc"].starts_at.hour == 23
    # An all-day entry becomes midnight in the calendar's own zone.
    assert by_id["allday"].starts_at is not None
    assert by_id["allday"].starts_at.hour == 0
    assert by_id["allday"].starts_at.utcoffset() is not None


# A quoted TZID legally contains a colon-free value, but the quoting itself must
# not cause the property to be split at the wrong place.
def test_ics_handles_a_quoted_parameter_value():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:quoted",
        "SUMMARY:Recital",
        'DTSTART;TZID="America/New_York":20260815T200000',
        "END:VEVENT",
    )

    events = parse_ics(payload, "venue")

    assert events[0].starts_at is not None
    assert events[0].starts_at.hour == 20


# An unknown zone must degrade to the configured default rather than discarding
# an otherwise usable listing.
def test_ics_falls_back_when_a_zone_is_unknown():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:badzone",
        "SUMMARY:Talk",
        "DTSTART;TZID=Mars/Olympus:20260815T200000",
        "END:VEVENT",
    )

    events = parse_ics(payload, "venue", default_timezone="America/New_York")

    assert events[0].starts_at is not None
    assert events[0].starts_at.utcoffset() is not None


def test_ics_skips_untitled_events_and_synthesizes_a_missing_identifier():
    payload = _calendar(
        "BEGIN:VEVENT",
        "DTSTART:20260815T200000Z",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "SUMMARY:Open mic",
        "DTSTART:20260817T200000Z",
        "END:VEVENT",
    )

    events = parse_ics(payload, "venue")

    assert len(events) == 1
    assert events[0].title == "Open mic"
    # Without a UID the identity still has to be stable across runs.
    assert "Open mic" in events[0].external_id


# A feed is someone else's data, so one source cannot decide how much work a
# run does.
def test_ics_is_bounded_per_source():
    blocks = []
    for index in range(MAX_EVENTS_PER_SOURCE + 25):
        blocks += [
            "BEGIN:VEVENT",
            f"UID:evt-{index}",
            f"SUMMARY:Show {index}",
            "DTSTART:20260815T200000Z",
            "END:VEVENT",
        ]

    events = parse_ics(_calendar(*blocks), "venue")

    assert len(events) == MAX_EVENTS_PER_SOURCE


# A calendar may carry any URL scheme; only web links may reach a notification.
def test_non_web_urls_are_dropped():
    assert clean_url("javascript:alert(1)") is None
    assert clean_url("data:text/html;base64,AAAA") is None
    assert clean_url("file:///etc/passwd") is None
    assert clean_url("https://venue.example/x") == "https://venue.example/x"


def test_control_characters_are_stripped_and_text_is_bounded():
    assert clean_text("Jazz\x00 night\x07", 100) == "Jazz night"
    assert clean_text("   ", 100) is None
    assert clean_text("x" * 500, 10) == "x" * 10


def test_rss_reads_items_and_prefers_the_publisher_identifier():
    payload = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>Ceramics open studio</title>
        <link>https://studio.example/open</link>
        <guid>studio-42</guid>
        <description>Drop in and throw a pot.</description>
        <pubDate>Tue, 04 Aug 2026 09:00:00 +0000</pubDate>
      </item>
    </channel></rss>"""

    events = parse_feed(payload, "studio")

    assert len(events) == 1
    assert events[0].external_id == "studio-42"
    assert events[0].title == "Ceramics open studio"
    assert events[0].url == "https://studio.example/open"
    # A publication date is not an event date, so nothing is scheduled from it.
    assert events[0].starts_at is None
    assert events[0].is_schedulable is False


def test_rss_uses_an_explicit_event_date_when_one_is_present():
    payload = """<?xml version="1.0"?>
    <rss version="2.0" xmlns:dcterms="http://purl.org/dc/terms/"><channel>
      <item>
        <title>Night market</title>
        <guid>market-7</guid>
        <dcterms:date>2026-08-15T18:00:00-04:00</dcterms:date>
      </item>
    </channel></rss>"""

    events = parse_feed(payload, "city")

    assert events[0].starts_at is not None
    assert events[0].starts_at.hour == 18
    assert events[0].is_schedulable is True


def test_atom_entries_read_the_alternate_link_href():
    payload = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Gallery opening</title>
        <id>gallery-9</id>
        <link rel="alternate" href="https://gallery.example/opening"/>
        <summary>New works.</summary>
      </entry>
    </feed>"""

    events = parse_feed(payload, "gallery")

    assert events[0].url == "https://gallery.example/opening"
    assert events[0].external_id == "gallery-9"


def test_malformed_xml_raises_a_feed_error():
    with pytest.raises(FeedError, match="not well-formed"):
        parse_feed("<rss><channel><item>", "broken")


def test_request_budget_refuses_an_unbounded_run():
    budget = RequestBudget(limit=2)
    budget.spend()
    budget.spend()

    assert budget.remaining == 0
    with pytest.raises(RequestBudgetExceededError):
        budget.spend()


@pytest.mark.asyncio
async def test_fetch_rejects_a_non_web_scheme_without_spending_budget():
    budget = RequestBudget(limit=5)

    with pytest.raises(FeedError, match="http or https"):
        await fetch_feed("file:///etc/passwd", budget=budget)

    assert budget.spent == 0


# An oversized body must be abandoned rather than held, so the ceiling is
# enforced while streaming rather than after the response is complete.
@pytest.mark.asyncio
async def test_fetch_abandons_a_body_over_the_ceiling():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 4_096)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(FeedError, match="exceeded"):
            await fetch_feed(
                "https://venue.example/feed.ics", max_bytes=1_024, client=client
            )


@pytest.mark.asyncio
async def test_fetch_returns_the_decoded_body_within_bounds():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"BEGIN:VCALENDAR")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        body = await fetch_feed("https://venue.example/feed.ics", client=client)

    assert body == "BEGIN:VCALENDAR"
