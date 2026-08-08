"""Sources should grow from where past finds pointed, without becoming a crawler.

The value being tested is compounding: one hand-added curator page surfaces a
venue, the venue turns out to publish its own calendar, and that calendar keeps
working after the curator stops posting or the user moves city. The risk being
tested is the mirror image — that "follow the links" quietly turns into
following everything, or into proposing pages nobody would want as a source.
"""

import json

import pytest

from backend.discovery import link_graph
from backend.discovery.link_graph import (
    MIN_FINDS_PER_HOST,
    LinkGraphExpander,
    harvest_hosts,
    host_of,
)


def _digest(*finds: tuple[str, str]) -> str:
    return json.dumps(
        {"selected": [{"title": title, "url": url} for title, url in finds]}
    )


def test_a_host_linked_once_is_not_yet_evidence():
    digests = (_digest(("Jazz Night", "https://renegadeva.com/jazz")),)

    assert harvest_hosts(digests) == ()


def test_a_host_linked_repeatedly_becomes_a_candidate():
    digests = (
        _digest(("Jazz Night", "https://renegadeva.com/jazz")),
        _digest(("Line Dancing", "https://renegadeva.com/line-dancing")),
    )

    signals = harvest_hosts(digests)

    assert len(signals) == 1
    assert signals[0].host == "renegadeva.com"
    assert signals[0].find_count == MIN_FINDS_PER_HOST
    assert "Jazz Night" in signals[0].examples


def test_the_same_page_linked_twice_is_one_destination():
    # Otherwise a single event relisted across two digests would look like a
    # venue that keeps coming up.
    same = ("Jazz Night", "https://renegadeva.com/jazz")
    digests = (_digest(same), _digest(same))

    assert harvest_hosts(digests) == ()


def test_a_source_the_user_already_follows_is_not_proposed_again():
    digests = (
        _digest(("Jazz", "https://renegadeva.com/jazz")),
        _digest(("Dance", "https://renegadeva.com/dance")),
    )

    assert harvest_hosts(digests, known_urls=("https://www.renegadeva.com/",)) == ()


def test_social_profiles_and_affiliate_links_are_never_candidates():
    # Both reached a delivered digest once. Neither is a venue, and linking one
    # twice does not make it one.
    digests = (
        _digest(
            ("Her page", "https://www.instagram.com/yourdcbestie/"),
            ("50% off a Club membership", "https://click.linksynergy.com/deeplink"),
        ),
        _digest(
            ("Her page again", "https://www.instagram.com/yourdcbestie/?hl=en"),
            ("Another offer", "https://click.linksynergy.com/other"),
        ),
    )

    assert harvest_hosts(digests) == ()


def test_www_and_bare_hosts_are_the_same_venue():
    digests = (
        _digest(("Jazz", "https://www.renegadeva.com/jazz")),
        _digest(("Dance", "https://renegadeva.com/dance")),
    )

    signals = harvest_hosts(digests)

    assert len(signals) == 1
    assert signals[0].find_count == 2


def test_unreadable_history_is_skipped_rather_than_raising():
    # A digest that will not parse is history, not a fault to propagate.
    history = (None, "", "{not json", _digest(("A", "https://x.com/a")))
    assert harvest_hosts(history) == ()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://WWW.Example.COM/path", "example.com"),
        ("https://example.com:8443/x", "example.com"),
        ("not a url", ""),
    ],
)
def test_hosts_are_normalized(url: str, expected: str):
    assert host_of(url) == expected


@pytest.mark.asyncio
async def test_a_venue_page_with_embedded_events_is_proposed(monkeypatch):
    page = """
    <html><script type="application/ld+json">
    [{"@type":"Event","name":"Country Night","url":"https://renegadeva.com/e/1"},
     {"@type":"Event","name":"Line Dancing","url":"https://renegadeva.com/e/2"}]
    </script></html>
    """

    async def _fetch(url, budget=None, **kwargs):
        return page

    monkeypatch.setattr(link_graph, "fetch_feed", _fetch)
    monkeypatch.setattr("backend.discovery.sources.links.fetch_feed", _fetch)

    proposals = await LinkGraphExpander().propose(
        (
            _digest(("Jazz", "https://renegadeva.com/jazz")),
            _digest(("Dance", "https://renegadeva.com/dance")),
        )
    )

    assert len(proposals) == 1
    assert proposals[0].kind == "links"
    assert proposals[0].event_count == 2
    # Proven, not guessed: the titles come from the page that was actually read.
    assert "Country Night" in proposals[0].sample_titles


@pytest.mark.asyncio
async def test_a_host_that_parses_to_nothing_is_never_proposed(monkeypatch):
    # A source that yields nothing contributes silence to every future sweep,
    # which is worse than not having it.
    async def _fetch(url, budget=None, **kwargs):
        return "<html><body>nothing structured here</body></html>"

    monkeypatch.setattr(link_graph, "fetch_feed", _fetch)
    monkeypatch.setattr("backend.discovery.sources.links.fetch_feed", _fetch)

    proposals = await LinkGraphExpander().propose(
        (
            _digest(("Jazz", "https://renegadeva.com/jazz")),
            _digest(("Dance", "https://renegadeva.com/dance")),
        )
    )

    assert proposals == ()


@pytest.mark.asyncio
async def test_an_unreachable_host_degrades_rather_than_failing(monkeypatch):
    async def _fetch(url, budget=None, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(link_graph, "fetch_feed", _fetch)
    monkeypatch.setattr("backend.discovery.sources.links.fetch_feed", _fetch)

    proposals = await LinkGraphExpander().propose(
        (
            _digest(("Jazz", "https://renegadeva.com/jazz")),
            _digest(("Dance", "https://renegadeva.com/dance")),
        )
    )

    assert proposals == ()


@pytest.mark.asyncio
async def test_probing_is_bounded_so_this_never_becomes_a_crawler(monkeypatch):
    fetched: list[str] = []

    async def _fetch(url, budget=None, **kwargs):
        fetched.append(url)
        return "<html></html>"

    monkeypatch.setattr(link_graph, "fetch_feed", _fetch)
    monkeypatch.setattr("backend.discovery.sources.links.fetch_feed", _fetch)

    # Twelve qualifying hosts, well past the ceiling on hosts considered.
    digests = tuple(
        _digest((f"Event {n}", f"https://venue{n}.com/a")) for n in range(12)
    ) + tuple(
        _digest((f"Event {n} again", f"https://venue{n}.com/b")) for n in range(12)
    )

    await LinkGraphExpander().propose(digests)

    hosts = {host_of(url) for url in fetched}
    assert len(hosts) <= link_graph.MAX_HOSTS_CONSIDERED
    assert len(fetched) <= (
        link_graph.MAX_HOSTS_CONSIDERED * link_graph.MAX_PROBES_PER_HOST
    )
