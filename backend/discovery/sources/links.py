"""Read a curated link page — the sort a person maintains by hand.

Someone who follows a city closely keeps a page of what is worth doing this
week. Those pages are the opposite of what search returns: chosen by a human,
current, and specific, and search will not surface them because they are not
about any one happening.

They are also not feeds. A link page publishes a title and a destination and
nothing else, so this adapter reads exactly that and yields **undated** events.
Individual links carry no date; a section heading might say "August 3-9", and a
week is not a start time. Turning that into an appointment would be inventing
one, which the rest of this subsystem refuses to do — so these surface as links
worth a look, and the venue page each points at is where a real date lives.

Two shapes are read, both stated rather than inferred:

- **schema.org `Event` JSON-LD**, which real venue pages embed and which carries
  a genuine `startDate` when present;
- **the page's own embedded link data**, which is how a link-in-bio service
  renders its cards. That is a private shape rather than a standard, so a
  failure to find it is reported as an unreadable source rather than as a page
  with nothing on it — a source that silently yields zero is indistinguishable
  from one nobody configured.
"""

import json
import re
from datetime import datetime
from typing import Any

from backend.discovery.events import (
    MAX_EVENTS_PER_SOURCE,
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
    DiscoveredEvent,
    EventSource,
    FeedError,
    clean_text,
    clean_url,
)
from backend.discovery.fetching import RequestBudget, fetch_feed

_NEXT_DATA = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S | re.I
)
_JSON_LD = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I
)

# A heading on a link page — "Things Happening (August 3-9)", "DISCOUNTS" — has
# no destination. Requiring a URL is what separates the cards from the dividers
# between them, without needing to know what any particular page calls them.
_WEB_SCHEMES = ("http://", "https://")


class LinkPageEventSource(EventSource):
    """One hand-curated page of links."""

    # Matches the other adapters: an id, a URL, and the run's request budget.
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
        document = await fetch_feed(self.url, budget=self.budget)
        events = list(_events_from_json_ld(self._source_id, document))
        events.extend(_events_from_embedded_links(self._source_id, document))
        if not events:
            # Loud rather than empty. A page whose shape changed and a page with
            # nothing on it look identical from here, and only one of them is
            # worth telling someone about.
            raise FeedError("No links or events could be read from that page.")
        return tuple(_deduplicate(events)[:MAX_EVENTS_PER_SOURCE])


# Real venue pages embed schema.org Events, which carry an explicit start.
def _events_from_json_ld(source_id: str, document: str) -> list[DiscoveredEvent]:
    found: list[DiscoveredEvent] = []
    for block in _JSON_LD.findall(document)[:20]:
        try:
            payload = json.loads(block)
        except ValueError:
            continue
        for node in _walk(payload):
            types = node.get("@type")
            kinds = types if isinstance(types, list) else [types]
            if not any(str(kind).lower() == "event" for kind in kinds):
                continue
            url = clean_url(_first_string(node.get("url")))
            title = clean_text(_first_string(node.get("name")), MAX_TITLE_CHARS)
            if not url or not title:
                continue
            found.append(
                DiscoveredEvent(
                    source_id=source_id,
                    external_id=url,
                    title=title,
                    starts_at=_parse_start(node.get("startDate")),
                    ends_at=None,
                    place=None,
                    url=url,
                    summary=clean_text(
                        _first_string(node.get("description")), MAX_SUMMARY_CHARS
                    ),
                )
            )
    return found


# The page's own link cards. Every entry with a real destination is a link
# someone chose to put there; everything else is a heading between them.
def _events_from_embedded_links(source_id: str, document: str) -> list[DiscoveredEvent]:
    match = _NEXT_DATA.search(document)
    if match is None:
        return []
    try:
        payload = json.loads(match.group(1))
    except ValueError:
        return []
    found: list[DiscoveredEvent] = []
    for node in _walk(payload):
        raw_url = node.get("url")
        if not isinstance(raw_url, str) or not raw_url.lower().startswith(_WEB_SCHEMES):
            continue
        title = clean_text(_first_string(node.get("title")), MAX_TITLE_CHARS)
        url = clean_url(raw_url)
        if not title or not url:
            continue
        found.append(
            DiscoveredEvent(
                source_id=source_id,
                external_id=url,
                title=title,
                # No date is stated per link, and the week a section heading
                # names is not a start time.
                starts_at=None,
                ends_at=None,
                place=None,
                url=url,
                summary=None,
            )
        )
    return found


# Every mapping in a nested structure, so a shape can change around the fields
# being read without this needing to know its layout.
def _walk(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk(value))
    return found


def _first_string(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                return item
    return None


# Read an explicit ISO start, or nothing. A date that needs a reference point to
# resolve is not a date this adapter will supply.
def _parse_start(value: Any) -> datetime | None:
    raw = _first_string(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    # A naive timestamp cannot be placed on a timeline without guessing a zone.
    return parsed if parsed.tzinfo is not None else None


# One card per destination. A page often repeats a link in its own data.
def _deduplicate(events: list[DiscoveredEvent]) -> list[DiscoveredEvent]:
    seen: set[str] = set()
    unique: list[DiscoveredEvent] = []
    for event in events:
        if event.url in seen:
            continue
        seen.add(str(event.url))
        unique.append(event)
    return unique
