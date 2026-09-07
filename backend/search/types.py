from contextvars import ContextVar
from dataclasses import dataclass

# A search that must cost as little as the provider allows.
#
# The deploy harnesses spend the same live Tavily allowance people do, and by
# 2026-09-06 they were three quarters of it: the journey sweep and the search
# harness run on every deploy, each asking real questions of a real provider.
# What they measure is which tool was chosen and how the answer is shaped -
# neither of which improves with a deeper search. Set per request from the
# caller's identity, read by the provider that bills.
frugal_search: ContextVar[bool] = ContextVar("frugal_search", default=False)


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One untrusted third-party result returned by a search provider.

    Every field originates outside the trust boundary. Titles and content are
    data to be quoted, never instructions: they must not be able to authorize a
    tool call, change permissions, or override a confirmation requirement.
    """

    title: str
    url: str
    content: str
    score: float | None
    provider: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResults:
    """Bounded, ranked result set for one executed query."""

    query: str
    results: tuple[SearchResult, ...]
    provider: str
