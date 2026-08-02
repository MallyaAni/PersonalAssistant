"""Find candidate feeds once, so the weekly loop never needs search.

The division of labour matters. Search *discovers sources*; sources *discover
events*. Enumerating events by search would put the one metered component of the
system on a recurring background path, and would ask a model to infer start
times from prose — which produces calendar entries that are confidently wrong.
Finding a venue's calendar URL has neither problem: it happens when the user
configures the agent, and its output is a URL that is then verified by fetching
it.

Nothing here trusts the search result. A candidate is only offered after AniOS
has fetched it, parsed it with the same adapter a sweep would use, and seen real
typed events come out.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from backend.core.interfaces import SearchProvider
from backend.discovery.events import DiscoveredEvent, FeedError, clean_text
from backend.discovery.fetching import RequestBudget, fetch_feed
from backend.discovery.sources.ics import parse_ics
from backend.discovery.sources.rss import parse_feed

# Setup is interactive, so the ceiling here is about not surprising the user
# with a burst of metered calls, not about a background loop.
MAX_SEARCH_QUERIES = 3
MAX_CANDIDATES_VALIDATED = 8
MAX_SUGGESTIONS = 5

# A candidate must yield at least this many typed events to be worth offering.
# One event is as likely to be a parse accident as a real calendar.
MIN_EVENTS_TO_SUGGEST = 2

# URLs that look like a feed. Checked before spending a fetch on them, since
# most search results are ordinary pages.
_FEED_HINTS = re.compile(
    r"(\.ics(\?|$)|/ical|ical/|\.rss(\?|$)|/feed/?($|\?)|\.xml(\?|$)|/atom)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class FeedCandidate:
    """One validated feed, ready to be added as a source."""

    kind: str
    url: str
    title: str
    event_count: int
    # A sample the user can recognize. Proof the feed is what it claims, rather
    # than asking them to trust a URL.
    sample_titles: tuple[str, ...]


class FeedFinder:
    """Propose feeds for a locality and interests, then prove each one works."""

    def __init__(self, search: SearchProvider) -> None:
        self.search = search

    async def suggest(
        self,
        locality: str,
        interests: tuple[str, ...],
        max_queries: int = MAX_SEARCH_QUERIES,
    ) -> tuple[FeedCandidate, ...]:
        if not self.search.is_enabled():
            return ()

        seen_urls: set[str] = set()
        candidates: list[str] = []
        for query in _queries(locality, interests, max_queries):
            try:
                results = await self.search.search(query, max_results=10)
            except Exception:
                # A search failure degrades the suggestion list rather than
                # failing setup; the user can still add a URL by hand.
                continue
            for result in results.results:
                url = clean_text(result.url, 2_048)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                if _FEED_HINTS.search(url):
                    candidates.append(url)

        return await self._validate(candidates[:MAX_CANDIDATES_VALIDATED])

    # Offer only what actually parses. A URL that looks like a feed and is not
    # one would otherwise become a source that silently contributes nothing to
    # every sweep.
    async def _validate(self, urls: list[str]) -> tuple[FeedCandidate, ...]:
        budget = RequestBudget(limit=max(len(urls), 1))
        validated: list[FeedCandidate] = []
        for url in urls:
            candidate = await self._probe(url, budget)
            if candidate is not None:
                validated.append(candidate)
            if len(validated) >= MAX_SUGGESTIONS:
                break
        # Richest first: a calendar with more events is more likely to be the
        # venue's real listing rather than a stub.
        validated.sort(key=lambda item: item.event_count, reverse=True)
        return tuple(validated)

    async def _probe(self, url: str, budget: RequestBudget) -> FeedCandidate | None:
        try:
            payload = await fetch_feed(url, budget=budget)
        except FeedError:
            return None
        except Exception:
            return None

        # iCalendar first: it is the source of record for anything that must
        # reach a calendar, and a document that parses as one is not RSS.
        events = _parse_quietly(lambda: parse_ics(payload, url, "UTC"))
        if len(events) >= MIN_EVENTS_TO_SUGGEST:
            return _candidate("ics", url, events)

        # RSS rarely carries a real start time, so it is offered only when it
        # actually produced schedulable items rather than bare headlines.
        entries = _parse_quietly(lambda: parse_feed(payload, url))
        schedulable = tuple(item for item in entries if item.is_schedulable)
        if len(schedulable) >= MIN_EVENTS_TO_SUGGEST:
            return _candidate("rss", url, schedulable)
        return None


# A parse failure means "not this format", not "setup is broken".
def _parse_quietly(
    parse: Callable[[], tuple[DiscoveredEvent, ...]],
) -> tuple[DiscoveredEvent, ...]:
    try:
        return parse()
    except Exception:
        return ()


def _candidate(
    kind: str, url: str, events: tuple[DiscoveredEvent, ...]
) -> FeedCandidate:
    return FeedCandidate(
        kind=kind,
        url=url,
        title=_title_for(url),
        event_count=len(events),
        sample_titles=tuple(item.title for item in events[:3]),
    )


# Queries are constructed from the user's own stated locality and interests and
# nothing else. No memory, no conversation, and no identifying detail beyond the
# place they already asked the agent to watch.
def _queries(locality: str, interests: tuple[str, ...], limit: int) -> tuple[str, ...]:
    place = clean_text(locality, 80) or ""
    queries = [f"{place} events calendar ics feed".strip()]
    for interest in interests[: max(limit - 1, 0)]:
        label = clean_text(interest, 60)
        if label:
            queries.append(f"{place} {label} events calendar subscribe ics".strip())
    return tuple(queries[:limit])


# A readable name from the host, so the user recognizes what they are adding.
def _title_for(url: str) -> str:
    without_scheme = url.split("://", 1)[-1]
    host = without_scheme.split("/", 1)[0]
    return host.removeprefix("www.") or url
