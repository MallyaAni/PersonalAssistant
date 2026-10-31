import os
import socket
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.events import (
    MAX_EVENTS_PER_SOURCE,
    FeedError,
    clean_text,
    clean_url,
    is_date_only,
)
from backend.discovery.fetching import (
    RequestBudget,
    RequestBudgetExceededError,
    _address_is_public,
    _read_public,
    _require_public_url,
    fetch_bytes,
    fetch_feed,
)
from backend.discovery.sources.ics import MAX_OCCURRENCES_PER_EVENT, parse_ics
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


# A stated time with no offset is not a comparable instant. Left naive, it made
# every downstream aware comparison raise, and the item was dropped instead of
# being offered. UTC is the only reading that does not shift it to the machine's
# own zone.
def test_rss_treats_a_zoneless_event_date_as_utc():
    payload = """<?xml version="1.0"?>
    <rss version="2.0" xmlns:dcterms="http://purl.org/dc/terms/"><channel>
      <item>
        <title>Night market</title>
        <guid>market-8</guid>
        <dcterms:date>2026-08-15T18:00:00</dcterms:date>
      </item>
    </channel></rss>"""

    events = parse_feed(payload, "city")

    assert events[0].starts_at is not None
    assert events[0].starts_at.utcoffset() == timedelta(0)
    assert events[0].starts_at.hour == 18


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


# The poster is what often states the date and venue the listing's prose omits,
# so the image-typed enclosure is read as the event's picture.
def test_rss_reads_an_image_enclosure_as_the_event_picture():
    payload = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>Lantern festival</title>
        <guid>lantern-1</guid>
        <enclosure url="https://city.example/poster.jpg" type="image/jpeg" length="1"/>
      </item>
    </channel></rss>"""

    events = parse_feed(payload, "city")

    assert events[0].media_url == "https://city.example/poster.jpg"


# A podcast's audio enclosure is not a poster, and media:content often sits
# inside media:group rather than directly under the item.
def test_rss_ignores_audio_and_reads_a_nested_media_content_image():
    payload = """<?xml version="1.0"?>
    <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
      <item>
        <title>Night market</title>
        <guid>market-1</guid>
        <enclosure url="https://city.example/episode.mp3" type="audio/mpeg"/>
        <media:group>
          <media:content url="https://city.example/poster.png"
                         type="image/png" medium="image"/>
        </media:group>
      </item>
    </channel></rss>"""

    events = parse_feed(payload, "city")

    assert events[0].media_url == "https://city.example/poster.png"


# A thumbnail is an image by definition, so it is the last resort when the feed
# states no larger picture.
def test_rss_falls_back_to_a_media_thumbnail():
    payload = """<?xml version="1.0"?>
    <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
      <item>
        <title>Open studio</title>
        <guid>studio-1</guid>
        <media:thumbnail url="https://studio.example/thumb.jpg"/>
      </item>
    </channel></rss>"""

    events = parse_feed(payload, "studio")

    assert events[0].media_url == "https://studio.example/thumb.jpg"


def test_atom_reads_an_image_enclosure_link():
    payload = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Gallery opening</title>
        <id>gallery-1</id>
        <link rel="alternate" href="https://gallery.example/opening"/>
        <link rel="enclosure" type="image/jpeg" href="https://gallery.example/poster.jpg"/>
      </entry>
    </feed>"""

    events = parse_feed(payload, "gallery")

    assert events[0].media_url == "https://gallery.example/poster.jpg"


# A calendar commonly attaches a PDF or another .ics first. Only an image-typed
# or image-suffixed attachment is the poster.
def test_ics_reads_an_image_attachment_and_skips_a_pdf():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:poster",
        "SUMMARY:Film night",
        "DTSTART:20260815T200000Z",
        "ATTACH;FMTTYPE=application/pdf:https://venue.example/program.pdf",
        "ATTACH;FMTTYPE=image/jpeg:https://venue.example/poster.jpg",
        "END:VEVENT",
    )

    events = parse_ics(payload, "venue")

    assert events[0].media_url == "https://venue.example/poster.jpg"


def test_ics_reads_the_image_property():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:image",
        "SUMMARY:Recital",
        "DTSTART:20260815T200000Z",
        "IMAGE;VALUE=URI:https://venue.example/recital.png",
        "END:VEVENT",
    )

    events = parse_ics(payload, "venue")

    assert events[0].media_url == "https://venue.example/recital.png"


# A venue's weekly calendar usually began months ago and has no end date. Read
# literally, it contributes one stale date; expanded, it contributes the
# instances a sweep can actually act on.
def test_a_weekly_series_expands_into_upcoming_occurrences():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:weekly-yoga",
        "SUMMARY:Yoga",
        "DTSTART;TZID=America/New_York:20261005T180000",
        "RRULE:FREQ=WEEKLY;BYDAY=MO,WE",
        "END:VEVENT",
    )

    events = parse_ics(
        payload,
        "venue",
        "America/New_York",
        now=datetime(2026, 10, 31, 12, 0, tzinfo=UTC),
    )

    assert len(events) > 1
    # The first actionable instance is the Monday after the sweep, at the
    # calendar's own wall-clock time rather than a shifted UTC hour.
    assert events[0].starts_at is not None
    assert events[0].starts_at.date() == date(2026, 11, 2)
    assert events[0].starts_at.hour == 18
    assert all(
        event.starts_at is not None and event.starts_at.hour == 18
        for event in events
    )
    # Each instance is its own find with its own stable identity.
    assert len({event.external_id for event in events}) == len(events)


# COUNT and UNTIL are the two ways a feed says a series ends, and both are
# inclusive of the day they name.
def test_count_and_until_bound_a_series():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:daily",
        "SUMMARY:Workshop",
        "DTSTART:20261102T190000Z",
        "RRULE:FREQ=DAILY;COUNT=3",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:until",
        "SUMMARY:Class",
        "DTSTART:20261102T190000Z",
        "RRULE:FREQ=DAILY;UNTIL=20261104T190000Z",
        "END:VEVENT",
    )

    events = parse_ics(
        payload, "venue", now=datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    )

    by_uid: dict[str, list] = {}
    for event in events:
        by_uid.setdefault(event.external_id.split("|", 1)[0], []).append(event)
    assert len(by_uid["daily"]) == 3
    assert len(by_uid["until"]) == 3


# EXDATE removes an instance the venue is closed, and RDATE adds one that the
# weekly pattern does not describe.
def test_exdate_removes_an_occurrence_and_rdate_adds_one():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:market",
        "SUMMARY:Market",
        "DTSTART:20261102T100000Z",
        "RRULE:FREQ=WEEKLY;BYDAY=MO",
        "RDATE:20261105T100000Z",
        "EXDATE:20261109T100000Z",
        "END:VEVENT",
    )

    events = parse_ics(
        payload, "venue", now=datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    )
    starts = {event.starts_at for event in events}

    assert datetime(2026, 11, 2, 10, 0, tzinfo=UTC) in starts
    assert datetime(2026, 11, 5, 10, 0, tzinfo=UTC) in starts
    assert datetime(2026, 11, 9, 10, 0, tzinfo=UTC) not in starts


# An unsupported frequency must not discard the listing; it degrades to the one
# date the entry states.
def test_an_unsupported_rule_leaves_a_single_event():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:hourly",
        "SUMMARY:Tour",
        "DTSTART:20261102T190000Z",
        "RRULE:FREQ=HOURLY;COUNT=4",
        "END:VEVENT",
    )

    events = parse_ics(
        payload, "venue", now=datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    )

    assert len(events) == 1
    assert events[0].external_id == "hourly"


# A series whose COUNT ran out before the sweep is over, not a happening to
# offer. Emitting its old dates would put stale finds in a digest.
def test_a_series_that_already_ended_is_not_offered():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:over",
        "SUMMARY:Past workshop",
        "DTSTART:20260901T190000Z",
        "RRULE:FREQ=DAILY;COUNT=3",
        "END:VEVENT",
    )

    events = parse_ics(
        payload, "venue", now=datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    )

    assert events == ()


# One feed entry must not be able to flood a source's allowance, no matter how
# long its rule runs.
def test_a_recurring_series_is_bounded_per_event():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:forever",
        "SUMMARY:Daily class",
        "DTSTART:20261101T190000Z",
        "RRULE:FREQ=DAILY",
        "END:VEVENT",
    )

    events = parse_ics(
        payload, "venue", now=datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    )

    assert len(events) == MAX_OCCURRENCES_PER_EVENT


# An override is the venue moving one instance. The master series must not also
# offer the slot it replaced.
def test_an_override_replaces_its_occurrence():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:series",
        "SUMMARY:Talk",
        "DTSTART:20261102T190000Z",
        "RRULE:FREQ=WEEKLY;BYDAY=MO",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:series",
        "RECURRENCE-ID:20261109T190000Z",
        "SUMMARY:Talk (late start)",
        "DTSTART:20261109T200000Z",
        "END:VEVENT",
    )

    events = parse_ics(
        payload, "venue", now=datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    )
    ninth = [event for event in events if event.starts_at.date() == date(2026, 11, 9)]

    assert len(ninth) == 1
    assert ninth[0].starts_at.hour == 20
    assert ninth[0].title == "Talk (late start)"


# An all-day series keeps whole days: the date is the fact the feed stated, and
# it must stay readable as a date after expansion.
def test_a_recurring_all_day_series_keeps_whole_days():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:fair",
        "SUMMARY:Street fair",
        "DTSTART;VALUE=DATE:20261102",
        "RRULE:FREQ=WEEKLY;BYDAY=MO",
        "END:VEVENT",
    )

    events = parse_ics(
        payload,
        "venue",
        "America/New_York",
        now=datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
    )

    assert len(events) > 1
    for event in events:
        assert event.starts_at is not None
        assert is_date_only(event.starts_at)


# An all-day series crossing the daylight-saving change still ends at midnight.
# Its absolute length is 25 hours, and carrying that onto later instances would
# move their end to 1am.
def test_a_recurring_all_day_series_keeps_whole_days_across_dst():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:dst-fair",
        "SUMMARY:Street fair",
        "DTSTART;VALUE=DATE:20261031",
        "DTEND;VALUE=DATE:20261101",
        "RRULE:FREQ=WEEKLY;BYDAY=SA",
        "END:VEVENT",
    )

    events = parse_ics(
        payload,
        "venue",
        "America/New_York",
        now=datetime(2026, 10, 31, 12, 0, tzinfo=UTC),
    )
    later = [
        event for event in events if event.starts_at.date() == date(2026, 11, 7)
    ]

    assert len(later) == 1
    assert later[0].ends_at is not None
    assert later[0].ends_at.date() == date(2026, 11, 8)
    assert later[0].ends_at.hour == 0


# The first instance keeps the bare identifier it had before expansion existed,
# so a series already announced is not announced again under a new name.
def test_the_first_occurrence_keeps_the_bare_identifier():
    payload = _calendar(
        "BEGIN:VEVENT",
        "UID:compat",
        "SUMMARY:Class",
        "DTSTART:20261102T190000Z",
        "RRULE:FREQ=WEEKLY;COUNT=2",
        "END:VEVENT",
    )

    events = parse_ics(
        payload, "venue", now=datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    )

    assert events[0].external_id == "compat"
    assert events[1].external_id == "compat|2026-11-09T19:00:00+00:00"


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


# A picture is bytes, not text, and the host's declared type is what tells the
# caller whether it is worth showing to a vision model.
@pytest.mark.asyncio
async def test_fetch_bytes_returns_the_body_and_its_declared_type():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"\x89PNG\r\n\x1a\nrest",
            headers={"content-type": "image/png"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        body, declared = await fetch_bytes(
            "https://venue.example/poster.png", client=client
        )

    assert body.startswith(b"\x89PNG")
    assert declared == "image/png"


# A feed URL is user-supplied, so fetching one is a request-forgery primitive
# unless the destination is checked. Everything that is not clearly public is
# refused; the cloud metadata address is the one that turns a feed into
# credentials, and loopback reaches this application's own API.
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.10",
        "172.16.4.2",
        "169.254.169.254",
        "0.0.0.0",
        "::1",
        "fd00::1",
        "::ffff:127.0.0.1",
    ],
)
def test_non_public_addresses_are_refused(address):
    assert _address_is_public(address) is False


@pytest.mark.parametrize("address", ["93.184.216.34", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(address):
    assert _address_is_public(address) is True


# Resolution is what makes the check meaningful for a hostname: a feed may name
# a public-looking host that resolves to the metadata service.
@pytest.mark.asyncio
async def test_a_host_resolving_inside_the_network_is_refused(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))
        ],
    )

    with pytest.raises(FeedError, match="non-public"):
        await _require_public_url("http://feeds.example/latest")


# A redirect is another destination, and it must be checked before it is
# contacted rather than trusted because the first hop was public.
@pytest.mark.asyncio
async def test_a_redirect_into_the_network_is_refused_before_it_is_followed(
    monkeypatch,
):
    resolved: list[str] = []

    def fake_getaddrinfo(host, port, *args, **kwargs):
        resolved.append(host)
        if host == "feeds.example":
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
            ]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://localhost/admin"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        with pytest.raises(FeedError, match="non-public"):
            await _read_public(
                client, "http://feeds.example/latest", RequestBudget(), 1_024
            )

    # The redirect was resolved and refused; it was never requested.
    assert resolved == ["feeds.example", "localhost"]
