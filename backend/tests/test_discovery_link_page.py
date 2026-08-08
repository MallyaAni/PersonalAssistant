"""A hand-curated link page is the opposite of what search returns.

Someone who follows a city keeps a page of what is worth doing this week.
Search will not surface it, because it is not about any one happening — and the
entries on it are exactly the local, specific finds a digest is for.
"""

import os

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

import pytest

from backend.discovery.events import FeedError
from backend.discovery.sources.links import LinkPageEventSource

# The shape a link-in-bio page renders from, reduced to what is read.
_PAGE = """
<html><head>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"links":[
  {"title":"Things Happening (August 3-9)","modifiers":{"autoExpand":false}},
  {"title":"Water Lantern Festival","url":"https://waterlanternfestival.com/dc"},
  {"title":"Phillips Collection Jazz Soiree","url":"https://phillipscollection.org/event/1"},
  {"title":"Water Lantern Festival","url":"https://waterlanternfestival.com/dc"}
]}}
</script>
</head><body></body></html>
"""

_WITH_EVENT = """
<html><head>
<script type="application/ld+json">
{"@type":"Event","name":"Jazz in the Garden","url":"https://venue.example/e/1",
 "startDate":"2026-08-16T18:00:00-04:00","description":"An outdoor concert."}
</script>
</head><body></body></html>
"""


async def _fetch(monkeypatch, document: str):
    async def fake_fetch(url, budget=None, **kwargs):
        return document

    monkeypatch.setattr("backend.discovery.sources.links.fetch_feed", fake_fetch)
    return await LinkPageEventSource("page", "https://example.org/p").fetch()


# Every card with a destination is a find; the headings between them are not.
@pytest.mark.asyncio
async def test_headings_are_not_mistaken_for_happenings(monkeypatch):
    events = await _fetch(monkeypatch, _PAGE)

    titles = [event.title for event in events]
    assert "Water Lantern Festival" in titles
    assert "Phillips Collection Jazz Soiree" in titles
    # A heading has no destination, which is what separates it from a card.
    assert "Things Happening (August 3-9)" not in titles
    assert all(event.url for event in events)


# A page repeats a link in its own data, and one card is one find.
@pytest.mark.asyncio
async def test_a_repeated_link_is_one_find(monkeypatch):
    events = await _fetch(monkeypatch, _PAGE)

    assert len(events) == 2


# Links carry no date. A section heading may name a week, and a week is not a
# start time — inventing one is what would put a wrong appointment in a
# calendar.
@pytest.mark.asyncio
async def test_links_are_undated_rather_than_guessed(monkeypatch):
    events = await _fetch(monkeypatch, _PAGE)

    assert all(event.starts_at is None for event in events)


# A real venue page states its start, and a stated one is read.
@pytest.mark.asyncio
async def test_a_stated_event_date_is_read(monkeypatch):
    events = await _fetch(monkeypatch, _WITH_EVENT)

    assert len(events) == 1
    assert events[0].title == "Jazz in the Garden"
    assert events[0].starts_at is not None
    assert events[0].starts_at.hour == 18


# A page whose shape changed and a page with nothing on it look identical from
# here, and only one of them is worth telling someone about.
@pytest.mark.asyncio
async def test_an_unreadable_page_fails_loudly(monkeypatch):
    with pytest.raises(FeedError):
        await _fetch(monkeypatch, "<html><body>nothing here</body></html>")


# A naive timestamp cannot be placed on a timeline without guessing a zone.
@pytest.mark.asyncio
async def test_a_start_without_a_zone_is_refused(monkeypatch):
    document = _WITH_EVENT.replace(
        '"2026-08-16T18:00:00-04:00"', '"2026-08-16T18:00:00"'
    )

    events = await _fetch(monkeypatch, document)

    assert events[0].starts_at is None
