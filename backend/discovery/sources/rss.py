"""Read venue and community listings published as RSS or Atom.

A feed item states when it was *published*, not when the happening occurs, and
the two are rarely the same. This adapter therefore yields events with no start
time unless the item carries an explicit event date, and lets a later stage
decide what to do with an undated candidate. Inventing a start from `pubDate`
would produce calendar entries that are confidently wrong, which is worse than
having none.

Parsed with the standard library. ElementTree does not resolve external
entities, and the payload is already byte-bounded before it arrives here, which
together cover the two attacks that matter for untrusted XML.
"""

from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

from backend.discovery.events import (
    MAX_EVENTS_PER_SOURCE,
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
    DiscoveredEvent,
    EventSource,
    FeedError,
    clean_text,
    clean_title,
    clean_url,
)
from backend.discovery.fetching import RequestBudget, fetch_feed

_ATOM = "{http://www.w3.org/2005/Atom}"
# Some publishers carry a real event date in a namespaced element. Where one is
# present it is preferred over any publication timestamp.
_EVENT_DATE_TAGS = (
    "{http://purl.org/dc/terms/}date",
    "{http://schemas.google.com/g/2005}when",
    "start_date",
    "eventDate",
)


class RssEventSource(EventSource):
    """One RSS or Atom listing feed."""

    def __init__(
        self,
        source_id: str,
        url: str,
        budget: RequestBudget | None = None,
    ) -> None:
        self._source_id = source_id
        self.url = url
        self.budget = budget

    @property
    def source_id(self) -> str:
        return self._source_id

    async def fetch(self) -> tuple[DiscoveredEvent, ...]:
        payload = await fetch_feed(self.url, budget=self.budget)
        return parse_feed(payload, self._source_id)


# Turn one RSS or Atom document into bounded, normalized events.
def parse_feed(payload: str, source_id: str) -> tuple[DiscoveredEvent, ...]:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise FeedError(f"Feed is not well-formed XML: {source_id}") from exc

    entries = root.findall(".//item") or root.findall(f".//{_ATOM}entry")
    events: list[DiscoveredEvent] = []
    for entry in entries[:MAX_EVENTS_PER_SOURCE]:
        event = _build_event(entry, source_id)
        if event is not None:
            events.append(event)
    return tuple(events)


def _build_event(entry: ElementTree.Element, source_id: str) -> DiscoveredEvent | None:
    title = clean_title(_text(entry, "title", f"{_ATOM}title"), MAX_TITLE_CHARS)
    if title is None:
        return None

    url = clean_url(_link(entry))
    # Prefer the publisher's own identifier so a re-titled item stays one event.
    external_id = (
        clean_text(_text(entry, "guid", f"{_ATOM}id"), MAX_TITLE_CHARS) or url or title
    )

    return DiscoveredEvent(
        source_id=source_id,
        external_id=external_id,
        title=title,
        starts_at=_event_start(entry),
        ends_at=None,
        place=None,
        url=url,
        summary=clean_text(
            _text(entry, "description", f"{_ATOM}summary", f"{_ATOM}content"),
            MAX_SUMMARY_CHARS,
        ),
    )


def _text(entry: ElementTree.Element, *tags: str) -> str | None:
    for tag in tags:
        found = entry.find(tag)
        if found is not None and found.text:
            return found.text
    return None


# RSS puts the target in <link>text</link>; Atom puts it in a href attribute.
def _link(entry: ElementTree.Element) -> str | None:
    rss_link = entry.find("link")
    if rss_link is not None and rss_link.text:
        return rss_link.text
    for candidate in entry.findall(f"{_ATOM}link"):
        relation = candidate.get("rel", "alternate")
        href = candidate.get("href")
        if relation == "alternate" and href:
            return href
    return None


# Return a real event date when the publisher supplies one, and otherwise
# nothing. Publication time is deliberately not used as a substitute.
def _event_start(entry: ElementTree.Element) -> datetime | None:
    for tag in _EVENT_DATE_TAGS:
        found = entry.find(tag)
        if found is None:
            continue
        raw = (found.get("startTime") or found.text or "").strip()
        parsed = _parse_timestamp(raw)
        if parsed is not None:
            return parsed
    return None


def _parse_timestamp(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
