"""Grow the source list from where past finds actually pointed.

Sources have only ever arrived one of two ways: search found a feed during
setup, or the user pasted a URL. Both stop the moment setup ends, which is why
one hand-curated link page could be the only thing surfacing anything local —
and why losing it, or moving city, would quietly empty the digest.

There is a third way, and it costs no metered search calls because the data is
already on disk. Every delivered digest recorded where each find pointed. A
curated page is a list of *destinations*: the venues, festivals and clubs whose
own pages the curator thought worth linking. A venue that keeps turning up
across sweeps is a venue worth reading directly.

That inverts the dependency in a useful way. The link page is how a venue is
discovered; the venue's own calendar is what keeps working after the curator
stops posting, changes handle, or is left behind in another city.

Two rules keep this from turning into a crawler:

- **nothing is added, only proposed.** A host that clears the threshold is
  offered the way a setup suggestion is, and the user approves it. Automatic
  source acquisition is how a digest fills with things nobody chose;
- **a proposal is proven before it is shown.** The host is fetched and parsed
  with the same adapters a sweep would use, and offered only if real typed
  events come out — the rule `FeedFinder` already follows, for the same reason:
  a plausible URL that parses to nothing becomes a source that silently
  contributes nothing to every future sweep.
"""

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from backend.discovery.events import DiscoveredEvent
from backend.discovery.feed_finder import MIN_EVENTS_TO_SUGGEST, FeedCandidate
from backend.discovery.fetching import RequestBudget, fetch_feed
from backend.discovery.listing_filter import looks_like_a_directory
from backend.discovery.sources.ics import parse_ics
from backend.discovery.sources.links import parse_link_page
from backend.discovery.sources.rss import parse_feed

# How many separate finds a host needs before it is worth a fetch. Two is the
# point where "the curator linked this once" becomes "the curator keeps sending
# people here", and one link is as likely to be a one-off as a venue.
MIN_FINDS_PER_HOST = 2

# Ceilings on the whole operation. This runs against a user's history rather
# than on a sweep's budget, but it still reaches the network, so it is bounded
# the same way: a fixed number of hosts, a fixed number of probes each.
MAX_HOSTS_CONSIDERED = 8
MAX_PROBES_PER_HOST = 2
MAX_PROPOSALS = 5

# How much history to read. Far enough back to see a repeat, near enough that a
# venue which stopped appearing months ago is not resurrected.
MAX_RUNS_READ = 20


@dataclass(frozen=True, slots=True)
class HostSignal:
    """One host, and the evidence for proposing it."""

    host: str
    # Distinct find URLs seen on this host, newest first. The first is what gets
    # probed, because it is the page most recently thought worth linking.
    urls: tuple[str, ...]
    # Titles of the finds that pointed here, so a proposal can say *why*.
    examples: tuple[str, ...]

    @property
    def find_count(self) -> int:
        return len(self.urls)


# Count where past finds pointed, ignoring anything already followed.
#
# `known_urls` is what the user already has: re-proposing a configured source
# is noise, and the digests being read are full of finds that came from exactly
# those sources.
def harvest_hosts(
    digests: tuple[str | None, ...],
    known_urls: tuple[str, ...] = (),
) -> tuple[HostSignal, ...]:
    known_hosts = {host_of(url) for url in known_urls} - {""}
    urls_by_host: dict[str, list[str]] = {}
    titles_by_host: dict[str, list[str]] = {}
    counts: Counter[str] = Counter()
    for digest in digests:
        for title, url in _finds(digest):
            # The same structural test the digest itself passes through. A
            # social profile or an affiliate redirect is not a venue, and one
            # linked twice is still not a venue.
            if looks_like_a_directory(title, url):
                continue
            host = host_of(url)
            if not host or host in known_hosts:
                continue
            seen = urls_by_host.setdefault(host, [])
            if url in seen:
                # The same page linked in two digests is one destination, not
                # two. Counting it twice is how a single event becomes evidence.
                continue
            seen.append(url)
            titles_by_host.setdefault(host, []).append(title)
            counts[host] += 1

    signals = [
        HostSignal(
            host=host,
            urls=tuple(urls_by_host[host]),
            examples=tuple(titles_by_host[host][:3]),
        )
        for host, count in counts.most_common()
        if count >= MIN_FINDS_PER_HOST
    ]
    return tuple(signals[:MAX_HOSTS_CONSIDERED])


class LinkGraphExpander:
    """Propose sources from where a user's own finds have been pointing."""

    def __init__(self, budget: RequestBudget | None = None) -> None:
        # Its own budget: this is not part of a sweep and must not consume the
        # allowance a sweep depends on.
        self.budget = budget or RequestBudget(
            limit=MAX_HOSTS_CONSIDERED * MAX_PROBES_PER_HOST
        )

    async def propose(
        self,
        digests: tuple[str | None, ...],
        known_urls: tuple[str, ...] = (),
    ) -> tuple[FeedCandidate, ...]:
        proposals: list[FeedCandidate] = []
        for signal in harvest_hosts(digests, known_urls):
            candidate = await self._probe_host(signal)
            if candidate is not None:
                proposals.append(candidate)
            if len(proposals) >= MAX_PROPOSALS:
                break
        # Richest first, matching the setup suggestions: more events is more
        # likely to be the venue's real listing rather than a single page.
        proposals.sort(key=lambda item: item.event_count, reverse=True)
        return tuple(proposals)

    # Try the pages most likely to be a venue's listing: the one that was
    # linked, then the site root. Guessing feed paths is deliberately not done —
    # it multiplies requests against sites that never asked to be probed.
    async def _probe_host(self, signal: HostSignal) -> FeedCandidate | None:
        for url in _probe_urls(signal):
            events, kind = await self._read(url)
            if len(events) >= MIN_EVENTS_TO_SUGGEST:
                return FeedCandidate(
                    kind=kind,
                    url=url,
                    title=signal.host,
                    event_count=len(events),
                    sample_titles=tuple(event.title for event in events[:3]),
                )
        return None

    # Every adapter a sweep has, in the order that settles the format fastest.
    async def _read(self, url: str) -> tuple[tuple[DiscoveredEvent, ...], str]:
        try:
            payload = await fetch_feed(url, budget=self.budget)
        except Exception:
            # Unreachable, too large, refused: not a candidate, not an error.
            return (), ""

        # Each format must clear the bar on its own. Returning the first one
        # that parsed at all would let a single stray VEVENT hide a page whose
        # embedded listing holds twenty.
        events = _parse_quietly(lambda: parse_ics(payload, url, "UTC"))
        if len(events) >= MIN_EVENTS_TO_SUGGEST:
            return events, "ics"

        entries = _parse_quietly(lambda: parse_feed(payload, url))
        schedulable = tuple(item for item in entries if item.is_schedulable)
        if len(schedulable) >= MIN_EVENTS_TO_SUGGEST:
            return schedulable, "rss"

        # A venue page is usually neither: it is HTML with schema.org Events
        # embedded, which is exactly what the link-page adapter reads. Parsed
        # from the document already in hand rather than fetched again, so a
        # candidate site is asked for its page once however many formats are
        # tried against it.
        return _parse_quietly(lambda: parse_link_page(url, payload)), "links"


# The linked page first, then the site root — deduplicated, since a find whose
# URL *is* the root would otherwise be fetched twice.
def _probe_urls(signal: HostSignal) -> tuple[str, ...]:
    ordered: list[str] = []
    for url in (*signal.urls[:1], _root_of(signal.urls[0])):
        if url and url not in ordered:
            ordered.append(url)
    return tuple(ordered[:MAX_PROBES_PER_HOST])


# Title and destination of every find a stored digest describes.
def _finds(digest: str | None) -> tuple[tuple[str, str], ...]:
    if not digest:
        return ()
    try:
        payload = json.loads(digest)
    except (TypeError, ValueError):
        # A digest that will not parse is history, not an error worth raising.
        return ()
    found: list[tuple[str, str]] = []
    # Both halves count. Something surfaced as notable was still a real find.
    for key in ("selected", "notable"):
        for item in payload.get(key) or ():
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if isinstance(url, str) and url:
                found.append((str(item.get("title") or ""), url))
    return tuple(found)


# The registrable-ish host, lowercased and without `www.`, so one venue is not
# counted as two.
def host_of(url: str) -> str:
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _root_of(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


# A parse failure means "not this format", not "expansion is broken".
def _parse_quietly(
    parse: Callable[[], tuple[DiscoveredEvent, ...]],
) -> tuple[DiscoveredEvent, ...]:
    try:
        return tuple(parse())
    except Exception:
        return ()
