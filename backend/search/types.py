from dataclasses import dataclass


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
