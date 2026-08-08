"""Find local happenings that no calendar feed publishes.

iCalendar feeds cover institutions — venues, museums, universities. They do not
cover a trail association's blog post about Saturday's group hike, or a pop-up
that exists only as a page someone wrote last week. For niche interests that is
most of what actually happens, so search is a second enumerator rather than only
a way to find feeds.

Two rules keep this from undoing the properties the rest of the loop has:

- **a start time is read, never inferred.** A search snippet rarely states a
  zone-aware start, and guessing one produces a calendar entry that is
  confidently wrong. Dates come from an explicit deterministic parse of the text;
  anything else yields an event with no start, which stage 5 will refuse to turn
  into a `VEVENT`. An unschedulable find is still worth showing as a link;
- **the query budget is fixed in advance.** Search is the only metered part of
  this system. A weekly sweep spending a bounded number of queries is affordable;
  an unbounded one is not, and the difference has to be structural.

Results are untrusted third-party text and are bounded and stripped at this
boundary like any feed.
"""

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from backend.core.interfaces import SearchProvider
from backend.discovery.events import (
    MAX_EVENTS_PER_SOURCE,
    MAX_PLACE_CHARS,
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
    DiscoveredEvent,
    EventSource,
    clean_text,
    clean_title,
    clean_url,
)
from backend.discovery.fetching import RequestBudget
from backend.discovery.listing_filter import looks_like_a_directory

# One query per interest, capped. A user with twenty interests must not turn one
# sweep into twenty metered calls.
MAX_QUERIES_PER_SWEEP = 4
MAX_RESULTS_PER_QUERY = 8

# Three-letter stems, so "Sept", "Sep." and "September" all match one branch.
# Listing full names only would silently miss the abbreviations that dominate
# real listings.
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"

# Explicit, unambiguous date forms only. Anything requiring inference — "this
# weekend", "next Saturday", "summer" — is deliberately absent, because
# resolving it needs a reference point the snippet does not carry.
_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 2026-09-12
    re.compile(r"\b(?P<y>20\d{2})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
    # September 12, 2026  /  Sept 12 2026
    re.compile(
        rf"\b(?P<mon>{_MONTHS})[a-z]*\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+"
        rf"(?P<y>20\d{{2}})\b",
        re.IGNORECASE,
    ),
    # 12 September 2026
    re.compile(
        rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<mon>{_MONTHS})[a-z]*\.?,?\s+"
        rf"(?P<y>20\d{{2}})\b",
        re.IGNORECASE,
    ),
)

_MONTH_NUMBERS = {
    name: index
    for index, name in enumerate(
        (
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ),
        start=1,
    )
}


class WebEventSource(EventSource):
    """Search for local happenings that publish no feed."""

    def __init__(
        self,
        source_id: str,
        search: SearchProvider,
        locality: str,
        interests: tuple[str, ...],
        budget: RequestBudget | None = None,
        max_queries: int = MAX_QUERIES_PER_SWEEP,
        region: str | None = None,
        include_general: bool = True,
    ) -> None:
        self._source_id = source_id
        self.search = search
        self.locality = locality
        # A bare town name is ambiguous to a search engine exactly as it is to a
        # person: querying "hiking near Arlington" returns Texas and Washington
        # alongside Virginia. The region is what makes the query mean one place.
        self.region = region
        self.interests = interests
        self.budget = budget
        self.max_queries = max_queries
        self.include_general = include_general

    @property
    def source_id(self) -> str:
        return self._source_id

    async def fetch(self) -> tuple[DiscoveredEvent, ...]:
        if not self.search.is_enabled() or not self.locality:
            return ()

        events: list[DiscoveredEvent] = []
        seen_urls: set[str] = set()
        for query in self._queries():
            if not self._spend_one_request():
                break
            try:
                results = await self.search.search(
                    query, max_results=MAX_RESULTS_PER_QUERY
                )
            except Exception:
                # One failed query degrades coverage, never the sweep.
                continue
            events.extend(_events_from(self._source_id, results.results, seen_urls))
            if len(events) >= MAX_EVENTS_PER_SOURCE:
                return tuple(events[:MAX_EVENTS_PER_SOURCE])
        return tuple(events)

    # Reserve one query against the budget. A spent budget ends the searching
    # rather than raising, because feeds already read must still contribute.
    def _spend_one_request(self) -> bool:
        if self.budget is None:
            return True
        if self.budget.remaining <= 0:
            return False
        self.budget.spend()
        return True

    # One query per interest, because a combined query returns results matching
    # none of them well. Bounded so the metered cost of a sweep is knowable
    # before it runs.
    def _queries(self, now: datetime | None = None) -> tuple[str, ...]:
        place = clean_text(self.locality, 80) or ""
        region = clean_text(self.region, 80)
        if region:
            place = f"{place}, {region}"
        # The month and year are the useful part. "events near X upcoming" is
        # how a directory page describes itself, so that phrasing returns
        # directory pages — measured, not guessed: it kept 0 of 5 results while
        # naming the month kept 6 of 9 across three different interests. A date
        # appears on a page about one happening and not on a landing page.
        moment = now or datetime.now(UTC)
        when = moment.strftime("%B %Y")
        queries: list[str] = []
        # One query that names no interest, so a sweep can surface something the
        # user never thought to ask for. Every other query is interest-shaped by
        # construction, which means the loop could only ever return more of what
        # it already knew about. It goes first so a tight budget spends its one
        # request here rather than on the fourth variation of one interest.
        if self.include_general:
            queries.append(f"events happening in {place} {when}".strip())
        for interest in self.interests[: self.max_queries]:
            label = clean_text(interest, 60)
            if label:
                queries.append(f"{label} {place} {when}".strip())
        if not queries:
            queries.append(f"local events {place} {when}".strip())
        return tuple(queries[: self.max_queries])


# Turn one query's results into typed events, skipping anything already taken and
# anything that is a page listing happenings rather than one happening.
def _events_from(
    source_id: str, results: "Iterable[Any]", seen_urls: set[str]
) -> list[DiscoveredEvent]:
    events: list[DiscoveredEvent] = []
    for result in results:
        url = clean_url(result.url)
        if url is None or url in seen_urls:
            continue
        seen_urls.add(url)
        # An embedding scores "Events in Arlington" as an excellent match for
        # someone interested in local events, which is exactly the wrong answer,
        # so this is decided structurally rather than semantically.
        if looks_like_a_directory(result.title, url):
            continue
        event = _to_event(source_id, result.title, result.content, url)
        if event is not None:
            events.append(event)
    return events


def _to_event(
    source_id: str, title: str, content: str, url: str
) -> DiscoveredEvent | None:
    cleaned_title = clean_title(title, MAX_TITLE_CHARS)
    if cleaned_title is None:
        return None
    summary = clean_text(content, MAX_SUMMARY_CHARS)
    return DiscoveredEvent(
        source_id=source_id,
        # The URL is the only stable identity a search result has; two feeds
        # describing the same page must deduplicate to one item.
        external_id=url,
        title=cleaned_title,
        # Read, never inferred. None means "worth showing, cannot be scheduled".
        starts_at=extract_explicit_date(f"{cleaned_title} {summary or ''}"),
        ends_at=None,
        place=clean_text(None, MAX_PLACE_CHARS),
        url=url,
        summary=summary,
    )


# Pull a date out of text only when the text states one outright.
#
# Returns midnight UTC on that day. That is a deliberate compromise: the day is
# what the source actually asserted, and a fabricated clock time would be
# invented precision. A calendar entry built from this reads as an all-day event
# rather than claiming a start nobody published.
def extract_explicit_date(text: str, now: datetime | None = None) -> datetime | None:
    moment = now or datetime.now(UTC)
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        groups = match.groupdict()
        month = groups.get("m")
        if month is None:
            month_name = (groups.get("mon") or "").lower()
            month_number = _month_number(month_name)
        else:
            month_number = int(month)
        if month_number is None or not 1 <= month_number <= 12:
            continue
        try:
            parsed = datetime(
                int(groups["y"]), month_number, int(groups["d"]), tzinfo=UTC
            )
        except ValueError:
            continue
        # A page describing last year's hike is not an upcoming event.
        if parsed < moment:
            continue
        return parsed
    return None


def _month_number(name: str) -> int | None:
    for full, number in _MONTH_NUMBERS.items():
        if full.startswith(name[:3]) and name:
            return number
    return None
