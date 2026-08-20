"""Read-only MCP server with Google research and Tavily fallback."""

import json
import os

from mcp.server.fastmcp import FastMCP

from backend.search.google_adk import GoogleADKSearchProvider
from backend.search.hybrid import HybridSearchProvider
from backend.search.quota import SQLiteDailySearchQuota
from backend.search.tavily import TavilySearchProvider
from backend.search.types import SearchResults

mcp = FastMCP("AniOS Internet Search")
# How much of one source survives, and how much the whole payload may carry.
#
# Both were fixed numbers - 500 characters a result, 3,500 for the payload -
# and they silently outranked SEARCH_MAX_CONTENT_CHARS, which the provider
# applied and this then discarded. 500 characters is about eighty words, so a
# benchmark table or a specification never reached the model and answers were
# assembled from titles. The payload bound still exists to stay under the
# generic MCP result cap, because a truncation mid-JSON corrupts the result
# rather than shortening it.
_RESULT_CHARS = int(os.getenv("SEARCH_RESULT_CHARS", "2500"))
_MAX_SERIALIZED_RESULT_CHARS = int(os.getenv("SEARCH_PAYLOAD_CHARS", "24000"))


# Compose the Google-first provider policy from operator-owned environment.
def _build_search_provider() -> HybridSearchProvider:
    max_results = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
    max_content_chars = int(os.getenv("SEARCH_MAX_CONTENT_CHARS", "2000"))
    google = GoogleADKSearchProvider(
        api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"),
        enabled=os.getenv("GOOGLE_SEARCH_ENABLED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        model=os.getenv("GOOGLE_SEARCH_MODEL", "gemini-3.6-flash"),
        timeout_seconds=float(os.getenv("GOOGLE_SEARCH_TIMEOUT_SECONDS", "30")),
        max_results=max_results,
        max_content_chars=max_content_chars,
        max_output_tokens=int(os.getenv("GOOGLE_SEARCH_MAX_OUTPUT_TOKENS", "2048")),
        quota=SQLiteDailySearchQuota(
            path=os.getenv(
                "GOOGLE_SEARCH_QUOTA_DB_PATH",
                "data/search/google_search_quota.sqlite3",
            ),
            provider="google",
            daily_limit=int(os.getenv("GOOGLE_SEARCH_DAILY_LIMIT", "450")),
        ),
    )
    tavily = TavilySearchProvider(
        base_url=os.getenv("SEARCH_BASE_URL", "https://api.tavily.com"),
        api_key=os.getenv("SEARCH_API_KEY"),
        max_results=max_results,
        timeout_seconds=float(os.getenv("SEARCH_TIMEOUT_SECONDS", "15")),
        max_content_chars=max_content_chars,
        min_score=float(os.getenv("SEARCH_MIN_SCORE", "0.4")),
        search_depth=os.getenv("SEARCH_DEPTH", "basic"),
    )
    return HybridSearchProvider(
        primary=google,
        fallback=tavily,
        max_results=max_results,
    )


# What the envelope costs before any excerpt is added to it.
#
# The dropped count is part of that envelope: added after the size was measured
# it pushed the payload past its bound, which is the mid-JSON truncation the
# bound exists to prevent.
def _serialized_length(
    provider: str, entries: list[dict[str, object]], dropped: int = 0
) -> int:
    payload: dict[str, object] = {"provider": provider, "results": entries}
    if dropped:
        payload["dropped_for_space"] = dropped
    return len(json.dumps(payload, ensure_ascii=False))


# Below this a source says nothing useful, so it is better dropped and counted
# than kept as a fragment that looks like evidence.
_MIN_RESULT_CHARS = 200


# One payload with each excerpt cut to the given share.
def _serialize(
    provider: str,
    skeleton: list[dict[str, object]],
    items: list,
    share: int,
    dropped: int,
) -> str:
    results = [
        {**entry, "content": item.content[:share]}
        for entry, item in zip(skeleton, items, strict=True)
    ]
    payload: dict[str, object] = {"provider": provider, "results": results}
    # Stated rather than left implicit: a model reading five sources should
    # know whether five is all there were.
    if dropped:
        payload["dropped_for_space"] = dropped
    return json.dumps(payload, ensure_ascii=False)


# How many sources can carry their titles, URLs and a real excerpt.
#
# Derived from what one source costs, not from what is left after paying for
# all of them: that remainder goes negative once enough come back, so eighty
# sources kept exactly one. Degradation has to stay gradual at every size, not
# only the sizes anyone happened to try.
def _affordable_count(provider: str, skeleton: list[dict[str, object]]) -> int:
    envelope = _serialized_length(provider, [])
    each = (_serialized_length(provider, skeleton) - envelope) / len(skeleton)
    estimate = int(
        (_MAX_SERIALIZED_RESULT_CHARS - envelope) // (each + _MIN_RESULT_CHARS)
    )
    count = max(1, min(len(skeleton), estimate))
    # That average is an estimate; step down until the real serialization fits.
    while count > 1 and (
        _serialized_length(provider, skeleton[:count], len(skeleton) - count)
        + count * _MIN_RESULT_CHARS
        > _MAX_SERIALIZED_RESULT_CHARS
    ):
        count -= 1
    return count


# Serialize results within the payload budget, sharing it across them.
#
# The budget used to be raced for rather than divided: each source took up to
# its own cap and whichever came first spent the payload, so the rest were
# dropped by a `break` that left no trace. Twelve sources became six, silently,
# and the ones that vanished were simply the later ones - not the weaker ones.
# Three settings that can disagree (`SEARCH_MAX_RESULTS` times
# `SEARCH_RESULT_CHARS` against `SEARCH_PAYLOAD_CHARS`) resolved themselves by
# throwing evidence away.
#
# Dividing what is left after the fixed fields means the count and the budget
# can no longer contradict each other: more sources means a shorter excerpt
# from each, which degrades instead of deleting. `SEARCH_RESULT_CHARS` stays as
# a ceiling so a single result cannot swallow the payload when few come back.
def _encode_results(found: SearchResults) -> str:
    items = list(found.results)
    if not items:
        return json.dumps({"provider": found.provider, "results": []})

    # What the titles, URLs and scores cost, so only the remainder is shared.
    skeleton = [
        {
            "title": item.title[:200],
            "url": item.url[:500],
            "content": "",
            "score": item.score,
            "provider": item.provider,
        }
        for item in items
    ]
    spare = _MAX_SERIALIZED_RESULT_CHARS - _serialized_length(found.provider, skeleton)
    share = min(_RESULT_CHARS, max(0, spare) // len(items))

    dropped = 0
    if share < _MIN_RESULT_CHARS:
        # Too many sources to say anything useful about each. Keep as many as
        # can carry a real excerpt and report the rest as dropped, rather than
        # returning a page of stubs.
        keep = _affordable_count(found.provider, skeleton)
        dropped = len(items) - keep
        items = items[:keep]
        skeleton = skeleton[:keep]
        spare = _MAX_SERIALIZED_RESULT_CHARS - _serialized_length(
            found.provider, skeleton, dropped
        )
        share = min(_RESULT_CHARS, max(0, spare) // len(items))

    # Escaping is invisible to the plan above, which measures empty excerpts: a
    # newline or a quote costs two characters once serialized, and real pages
    # are full of both. Measured on a live search the payload came out 148
    # characters over its bound this way, which synthetic content never shows.
    # Shrink the share until what actually serializes fits.
    encoded = _serialize(found.provider, skeleton, items, share, dropped)
    while share > 0 and len(encoded) > _MAX_SERIALIZED_RESULT_CHARS:
        overflow = len(encoded) - _MAX_SERIALIZED_RESULT_CHARS
        share = max(0, share - max(1, -(-overflow // len(items))))
        encoded = _serialize(found.provider, skeleton, items, share, dropped)
    return encoded


# Search with Google first, Tavily fallback, or both for explicit verification.
@mcp.tool()
async def search_web(query: str, max_results: int = 0) -> str:
    """Research a minimized public query with bounded free-provider policy."""
    provider = _build_search_provider()
    # The caller may ask for fewer, never more: this argument defaulted to 5
    # and was passed straight through, so it quietly outranked
    # SEARCH_MAX_RESULTS and the configured count never applied.
    configured = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
    wanted = min(max_results, configured) if max_results > 0 else configured
    found = await provider.search(query, max_results=wanted)
    return _encode_results(found)


# Run the internet server over stdio for the configured AniOS MCP client.
def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
