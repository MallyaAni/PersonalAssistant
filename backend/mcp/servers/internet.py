"""Read-only MCP server with Google research and Tavily fallback."""

import json
import os

from mcp.server.fastmcp import FastMCP

from backend.search.google_adk import GoogleADKSearchProvider
from backend.search.hybrid import HybridSearchProvider
from backend.search.quota import SQLiteDailySearchQuota
from backend.search.tavily import TavilySearchProvider, TavilyUsageClient
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
        base_url=os.getenv("SEARCH_BASE_URL") or "https://api.tavily.com",
        api_key=os.getenv("SEARCH_API_KEY") or None,
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


# What each WMO weather code means, in words a reply can use. Open-Meteo
# returns the code; the words are the WMO's own categories, which is data,
# not judgement.
_WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "dense drizzle",
    56: "freezing drizzle",
    57: "dense freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "heavy freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "violent showers",
    85: "light snow showers",
    86: "snow showers",
    95: "thunderstorm",
    96: "thunderstorm with light hail",
    99: "thunderstorm with heavy hail",
}


def _describe_code(code: object) -> str:
    try:
        return _WEATHER_CODES.get(int(code), "unknown conditions")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "unknown conditions"


# Real forecast data for a real question. Web search answered "today's
# weather" from SEO forecast pages and delivered a monthly outlook as
# today; a forecast API returns the actual numbers for the actual day.
# Open-Meteo is free, keyless, and non-commercial-friendly.
@mcp.tool()
async def get_weather(place: str, days: int = 1, units: str = "imperial") -> str:
    """Live current conditions and forecast for a named place.

    Use this, never web search, for any question about weather - right now,
    today, tonight, or the coming days. `place` is a city or town name
    ("Arlington, Virginia"); `days` is how many forecast days to include
    (1 = today, up to 7); `units` is "imperial" or "metric".
    """
    import httpx

    name = (place or "").strip()
    if not name:
        return json.dumps({"error": "no place given"})
    wanted_days = max(1, min(int(days), 7))
    imperial = units != "metric"

    async with httpx.AsyncClient(timeout=15) as client:
        geo = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": name, "count": 1, "language": "en", "format": "json"},
        )
        matches = (geo.json() or {}).get("results") or []
        if not matches:
            return json.dumps({"error": f"no place found for {name!r}"})
        spot = matches[0]
        forecast = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": spot["latitude"],
                "longitude": spot["longitude"],
                "current": (
                    "temperature_2m,apparent_temperature,relative_humidity_2m,"
                    "precipitation,weather_code,wind_speed_10m"
                ),
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,sunrise,sunset"
                ),
                "timezone": "auto",
                "forecast_days": wanted_days,
                **(
                    {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph"}
                    if imperial
                    else {}
                ),
            },
        )
        body = forecast.json() or {}

    current = body.get("current") or {}
    daily = body.get("daily") or {}
    temp_unit = "°F" if imperial else "°C"
    wind_unit = "mph" if imperial else "km/h"
    resolved = ", ".join(
        str(part)
        for part in (spot.get("name"), spot.get("admin1"), spot.get("country"))
        if part
    )
    forecast_days = [
        {
            "date": (daily.get("time") or [None] * wanted_days)[index],
            "conditions": _describe_code(
                (daily.get("weather_code") or [None] * wanted_days)[index]
            ),
            "high": (daily.get("temperature_2m_max") or [None] * wanted_days)[index],
            "low": (daily.get("temperature_2m_min") or [None] * wanted_days)[index],
            "precipitation_chance_percent": (
                daily.get("precipitation_probability_max") or [None] * wanted_days
            )[index],
        }
        for index in range(min(wanted_days, len(daily.get("time") or [])))
    ]
    return json.dumps(
        {
            "place": resolved,
            "timezone": body.get("timezone"),
            "as_of": current.get("time"),
            "current": {
                "conditions": _describe_code(current.get("weather_code")),
                "temperature": current.get("temperature_2m"),
                "feels_like": current.get("apparent_temperature"),
                "humidity_percent": current.get("relative_humidity_2m"),
                "wind": current.get("wind_speed_10m"),
                "units": {"temperature": temp_unit, "wind": wind_unit},
            },
            "daily": forecast_days,
            "source": "open-meteo.com",
        }
    )


# What the shared search key has left, from the provider itself.
#
# Anything about the internet lives on this server, and that includes the
# meter: the credits behind `search_web` are the one fact about it the
# operator keeps asking, and the model had no way to read them - so a
# scheduled "tell me when search credits are low" fired with nothing to say.
# The provider's numbers, not this system's own count: the key is shared with
# whatever else the operator points at it.
async def _usage_report() -> dict[str, object] | None:
    # `or`, not a getenv default: compose passes the variable through as an
    # empty string where it is unset, and an empty base URL reads nothing.
    client = TavilyUsageClient(
        base_url=os.getenv("SEARCH_BASE_URL") or "https://api.tavily.com",
        api_key=os.getenv("SEARCH_API_KEY") or None,
    )
    return await client.report() if client.is_enabled() else None


@mcp.tool()
async def search_credits() -> str:
    """Report the web-search credits left on the shared search key this billing period: plan, spent, limit, remaining, and the share used. Read-only; no credit is spent by asking."""
    report = await _usage_report()
    if report is None:
        return json.dumps(
            {
                "provider": "tavily",
                "error": "usage_unavailable",
                "detail": "The provider's usage endpoint could not be read, so the "
                "balance is unknown - not zero.",
            }
        )
    limit = report.get("limit")
    spent = report.get("spent")
    percent = (
        round(100.0 * float(spent) / float(limit), 1)
        if isinstance(limit, int) and limit > 0 and isinstance(spent, int)
        else None
    )
    return json.dumps(
        {
            "provider": "tavily",
            "plan": report.get("plan"),
            "spent": spent,
            "limit": limit,
            "remaining": report.get("remaining"),
            "percent_used": percent,
            "google_grounding_enabled": os.getenv("GOOGLE_SEARCH_ENABLED", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
            "period": "the provider's current billing period",
        }
    )


# Run the internet server over stdio for the configured AniOS MCP client.
def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
