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

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

logger = logging.getLogger(__name__)

# One date parser, in core, imported by everything that reads a date out of
# text (backend/core/dates.py).
from backend.core.dates import stated_date as parse_stated_date
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
from backend.discovery.geography import contradicts_locality
from backend.discovery.listing_filter import looks_like_a_directory

# One query per interest, capped. A user with twenty interests must not turn one
# sweep into twenty metered calls.
MAX_QUERIES_PER_SWEEP = 4
MAX_RESULTS_PER_QUERY = 8

# How many days ahead each successive interest query names its month. The
# general query names the current month; the first interest names the month
# one step ahead, the second two, and so on, so a single sweep asks about
# several upcoming months and the same question is never asked twice in a row.
WINDOW_STEP_DAYS = 7


# The month and year a date this many days ahead falls in. Rolling the window
# forward means a sweep near the end of the month asks about next month, and a
# December sweep asks about January of the next year — both handled by the
# calendar arithmetic rather than by stringly month math.
def _month_year(moment: datetime, days_ahead: int) -> str:
    return (moment + timedelta(days=days_ahead)).strftime("%B %Y")


class WebEventSource(EventSource):
    """Search for local happenings that publish no feed."""

    def __init__(
        self,
        source_id: str,
        search: SearchProvider,
        locality: str,
        subjects: tuple[str, ...],
        budget: RequestBudget | None = None,
        max_queries: int = MAX_QUERIES_PER_SWEEP,
        region: str | None = None,
        include_general: bool = True,
        now: datetime | None = None,
    ) -> None:
        self._source_id = source_id
        self.search = search
        self.locality = locality
        # The sweep's own clock. A rehearsal passes its fixed moment so the
        # rolling month window is reproducible; a live sweep passes None and
        # reads the real time here.
        self.now = now
        # A bare town name is ambiguous to a search engine exactly as it is to a
        # person: querying "hiking near Arlington" returns Texas and Washington
        # alongside Virginia. The region is what makes the query mean one place.
        self.region = region
        # What each query is about. An interest label is the floor — "Run Clubs"
        # — and `aiming.py` substitutes something aimed at this person when
        # memory supports one, such as "casual weekend group runs". Either way
        # it is one short noun phrase, because the skeleton around it is what
        # was measured.
        self.subjects = subjects
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
            except Exception as exc:
                # One failed query degrades coverage, never the sweep - but the
                # failure must be audible, or an exhausted search reads as "the
                # internet had nothing". An all-exhausted sweep logs every query.
                logger.warning(
                    "discovery_search_query_failed source=%s query=%r error=%s",
                    self._source_id,
                    query,
                    exc,
                )
                continue
            events.extend(
                _events_from(self._source_id, results.results, seen_urls, self.region)
            )
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

    # One query per subject, because a combined query returns results matching
    # none of them well. Bounded so the metered cost of a sweep is knowable
    # before it runs.
    #
    # The skeleton is fixed and the subject is the only variable. What a subject
    # says can be aimed at one person; how the query is shaped cannot, because
    # that shape is what was measured.
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
        #
        # The named month rolls forward with the sweep's own clock rather than
        # being frozen to the current one: a sweep that asked "September 2026"
        # every day of September got the same top pages back each time, the
        # novelty filter marked them all seen, and the digest emptied for days
        # while the candidates kept coming (measured 2026-09-17: 10 candidates,
        # 0 novel). Each interest query names a later month than the last, so one
        # sweep spans several upcoming months, and `timedelta` does the boundary
        # arithmetic — December rolls into January and the year advances.
        moment = now or self.now or datetime.now(UTC)
        general_when = _month_year(moment, days_ahead=0)
        queries: list[str] = []
        # One query that names no interest, so a sweep can surface something the
        # user never thought to ask for. Every other query is interest-shaped by
        # construction, which means the loop could only ever return more of what
        # it already knew about. It goes first so a tight budget spends its one
        # request here rather than on the fourth variation of one interest.
        if self.include_general:
            queries.append(f"events happening in {place} {general_when}".strip())
        for index, subject in enumerate(self.subjects[: self.max_queries]):
            topic = clean_text(subject, 60)
            if topic:
                when = _month_year(moment, days_ahead=(index + 1) * WINDOW_STEP_DAYS)
                queries.append(f"{topic} {place} {when}".strip())
        if not queries:
            queries.append(f"local events {place} {general_when}".strip())
        return tuple(queries[: self.max_queries])


# Turn one query's results into typed events, skipping anything already taken and
# anything that is a page listing happenings rather than one happening.
def _events_from(
    source_id: str,
    results: "Iterable[Any]",
    seen_urls: set[str],
    region: str | None = None,
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
        # The query named the place and the result is about a different one.
        # A concerts index for Arlington, Texas reached a digest belonging to
        # someone in Arlington, Virginia; the page said so and nothing read it.
        if contradicts_locality(result.title, result.content, url, region):
            continue
        event = _to_event(source_id, result.title, result.content, url)
        if event is not None:
            events.append(event)
    return events


# Convert one search result while refusing a date the source says has passed.
def _to_event(
    source_id: str, title: str, content: str, url: str
) -> DiscoveredEvent | None:
    cleaned_title = clean_title(title, MAX_TITLE_CHARS)
    if cleaned_title is None:
        return None
    summary = clean_text(content, MAX_SUMMARY_CHARS)
    date_text = f"{cleaned_title} {summary or ''}"
    stated_date = parse_stated_date(date_text)
    if stated_date is not None and stated_date.date() < datetime.now(UTC).date():
        return None
    return DiscoveredEvent(
        source_id=source_id,
        # The URL is the only stable identity a search result has; two feeds
        # describing the same page must deduplicate to one item.
        external_id=url,
        title=cleaned_title,
        # Read, never inferred. None means "worth showing, cannot be scheduled".
        starts_at=stated_date,
        ends_at=None,
        place=clean_text(None, MAX_PLACE_CHARS),
        url=url,
        summary=summary,
    )
