import os

os.environ["DEBUG"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

import pytest

from backend.core.egress import OutboundPrivacyPolicy
from backend.presentations.research import (
    DeckResearch,
    DeckSource,
    render_sources,
    research_subject,
)
from backend.search.types import SearchResult, SearchResults


class _StubSearch:
    """Record what a deck would send outward and return fixed results."""

    def __init__(self, results=(), enabled=True, error=None):
        self._results = results
        self._enabled = enabled
        self._error = error
        self.queries: list[str] = []

    def is_enabled(self) -> bool:
        return self._enabled

    async def search(self, query, max_results=None):
        self.queries.append(query)
        if self._error is not None:
            raise self._error
        return SearchResults(query=query, results=tuple(self._results), provider="stub")


def _result(url="https://example.org/a", title="Apollo", content="Six landings."):
    return SearchResult(title=title, url=url, content=content, score=0.9)


# Verify a deck brief produces bounded sources through one search.
@pytest.mark.asyncio
async def test_gather_returns_bounded_sources():
    search = _StubSearch(results=[_result(), _result(url="https://example.org/b")])

    sources = await DeckResearch(search).gather("A deck about the Apollo programme")

    assert [source.url for source in sources] == [
        "https://example.org/a",
        "https://example.org/b",
    ]
    assert search.queries == ["A deck about the Apollo programme"]


# Verify only the configured number of sources reaches the planner, since every
# source is repeated into every slide request.
@pytest.mark.asyncio
async def test_gather_truncates_sources_and_content():
    results = [_result(url=f"https://example.org/{index}") for index in range(9)]
    results[0] = _result(url="https://example.org/long", content="x" * 5_000)
    search = _StubSearch(results=results)

    sources = await DeckResearch(search, max_sources=3, max_content_chars=50).gather(
        "brief"
    )

    assert len(sources) == 3
    assert len(sources[0].content) == 50


# Verify a brief carrying a secret never leaves the machine. A deck brief is
# user-written prose heading outward, so it passes the same shared gate a chat
# query does rather than a second copy of the rules.
@pytest.mark.asyncio
async def test_a_brief_carrying_a_secret_is_never_sent():
    search = _StubSearch(results=[_result()])

    sources = await DeckResearch(search, OutboundPrivacyPolicy()).gather(
        "Build a deck explaining our key sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFF"
    )

    assert sources == ()
    assert search.queries == []


# Verify a deck is still produced when grounding cannot run. A deck the user can
# edit is worth more than no deck, and the contract still forbids figures the
# sources do not support.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "search",
    [
        _StubSearch(enabled=False),
        _StubSearch(error=RuntimeError("provider down")),
    ],
)
async def test_research_failure_degrades_instead_of_failing_the_deck(search):
    assert await DeckResearch(search).gather("brief") == ()


# Verify an unconfigured provider is simply absent rather than an error path.
@pytest.mark.asyncio
async def test_missing_provider_is_disabled():
    research = DeckResearch(None)

    assert research.is_enabled() is False
    assert await research.gather("brief") == ()


# Verify sources reach the model as quoted, attributed, untrusted data carrying
# the rule that produced this subsystem: a figure must come from a source.
def test_rendered_sources_bind_figures_to_the_sources():
    rendered = render_sources(
        (DeckSource(title="Apollo", url="https://example.org/a", content="Six."),)
    )

    assert "https://example.org/a" in rendered
    assert "untrusted" in rendered
    assert "do not invent one" in rendered


# Verify the empty case states the constraint rather than staying silent. With
# no statement either way the model treats an empty context as permission to
# fill it in, which is the behaviour being fixed.
def test_rendered_sources_without_results_still_forbids_invention():
    rendered = render_sources(())

    assert "No researched sources" in rendered
    assert "cannot support" in rendered


# Verify the deck's construction wording is stripped before the query leaves the
# machine. Sent verbatim, "create a deck ... with a statistic slide, 4 slides"
# returned a slideware marketing page, because most of those words describe the
# artifact rather than the subject.
@pytest.mark.parametrize(
    ("brief", "expected"),
    [
        (
            "Create a deck about the Apollo moon landing programme, 4 slides.",
            "the Apollo moon landing programme",
        ),
        (
            "Make me a 5-slide presentation on the economics of offshore wind",
            "the economics of offshore wind",
        ),
        (
            "Generate a powerpoint about our Q3 hiring plan, 3 slides",
            "our Q3 hiring plan",
        ),
        # A brief that is already a subject is left alone.
        ("The history of the Silk Road", "The history of the Silk Road"),
    ],
)
def test_research_subject_strips_deck_construction_wording(brief, expected):
    assert research_subject(brief) == expected


# Verify a brief made entirely of construction wording still searches something
# rather than sending an empty query.
def test_research_subject_never_returns_nothing():
    assert research_subject("Create a presentation, 3 slides") != ""


# Verify the subject, not the brief, is what the provider receives.
@pytest.mark.asyncio
async def test_gather_sends_the_subject_rather_than_the_brief():
    search = _StubSearch(results=[_result()])

    await DeckResearch(search).gather(
        "Create a deck about the Apollo programme with a chart slide, 4 slides."
    )

    assert search.queries == ["the Apollo programme"]
