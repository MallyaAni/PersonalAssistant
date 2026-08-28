"""Read-only MCP server with Google research and Tavily fallback."""

import json
import os

import httpx

from mcp.server.fastmcp import FastMCP

from backend.search.brave import BraveSearchProvider
from backend.search.google_adk import GoogleADKSearchProvider
from backend.search.hybrid import EveryProviderExhausted, HybridSearchProvider
from backend.search.quota import (
    SearchQuotaExceededError,
    SQLiteDailySearchQuota,
    SQLiteMonthlySearchQuota,
)
from backend.search.tavily import TavilySearchProvider, TavilyUsageClient
from backend.search.types import SearchResults

mcp = FastMCP("AniOS Internet Search")

# Status codes that mean "the key's plan is spent", not "try again".
_QUOTA_STATUSES = frozenset({402, 429, 432})
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
    brave = BraveSearchProvider(
        api_key=os.getenv("BRAVE_SEARCH_API_KEY") or None,
        max_results=max_results,
        timeout_seconds=float(os.getenv("SEARCH_TIMEOUT_SECONDS") or "15"),
        max_content_chars=max_content_chars,
        quota=SQLiteMonthlySearchQuota(
            path=os.getenv("BRAVE_SEARCH_QUOTA_DB_PATH") or "data/search/brave_search_quota.sqlite3",
            provider="brave",
            monthly_limit=int(os.getenv("BRAVE_SEARCH_MONTHLY_LIMIT") or "900"),
        ),
    )
    # The chain is order, not mixing: the operator names it, the better one
    # first, the next when the first has spent its period. Brave leads by
    # default since 2026-08-25 - a broad, fresh index at ~1,000 free requests
    # a month; Tavily's richer extracted text follows when Brave is out.
    order = [
        name.strip().lower()
        for name in (os.getenv("SEARCH_PROVIDER_ORDER") or "brave,google,tavily").split(",")
        if name.strip()
    ]
    by_name = {"brave": brave, "google": google, "tavily": tavily}
    chain = [by_name[name] for name in order if name in by_name]
    for provider in (brave, google, tavily):
        if provider not in chain:
            chain.append(provider)
    return HybridSearchProvider(
        primary=chain[-2] if len(chain) > 1 else chain[0],
        fallback=chain[-1],
        max_results=max_results,
        ahead=tuple(chain[:-2]),
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
    try:
        found = await provider.search(query, max_results=wanted)
    except (EveryProviderExhausted, SearchQuotaExceededError):
        # Every rung has spent its period: a fact the caller acts on - mark
        # the pool spent, tell the person which allowance - not a retry.
        return json.dumps(
            {"provider": "all", "error": "quota_exhausted", "status": 402, "results": []}
        )
    except httpx.HTTPStatusError as exc:
        # The provider saying the plan is spent (Tavily: 432; 402 and 429
        # from others) is a fact the caller must act on - mark the pool
        # spent, tell the person - not an outage to retry. Returned as a
        # payload so the reason survives the MCP boundary.
        status = exc.response.status_code
        if status in _QUOTA_STATUSES:
            return json.dumps(
                {"provider": "tavily", "error": "quota_exhausted", "status": status, "results": []}
            )
        raise
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
    82: "heavy showers",
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
#
# Two sources. For the United States the National Weather Service - free,
# keyless, official, and what the phone forecasts people compare against;
# on 2026-08-27 Open-Meteo called a 29%-chance day "violent showers" and a
# mostly-sunny Saturday "overcast" for Washington while NWS said "chance of
# showers" and "mostly sunny". Open-Meteo everywhere else and as fallback.

# Place names the geocoder does not know as written. Open-Meteo's search
# returns nothing for "Washington, DC", "Washington DC" or "DC" - the first
# thing a person in this area asks about - though "Washington" and a ZIP
# both resolve. Written spellings people use, mapped to what resolves.
_PLACE_ALIASES: dict[str, tuple[str, str]] = {
    "dc": ("Washington", "District of Columbia"),
    "washington dc": ("Washington", "District of Columbia"),
    "washington d.c.": ("Washington", "District of Columbia"),
    "washington, d.c.": ("Washington", "District of Columbia"),
    "washington, dc": ("Washington", "District of Columbia"),
    "the district": ("Washington", "District of Columbia"),
    "nyc": ("New York", "New York"),
    "new york city": ("New York", "New York"),
    "la": ("Los Angeles", "California"),
    "sf": ("San Francisco", "California"),
    "philly": ("Philadelphia", "Pennsylvania"),
    "nova": ("Arlington", "Virginia"),
    "northern virginia": ("Arlington", "Virginia"),
    "dmv": ("Washington", "District of Columbia"),
    "dmv area": ("Washington", "District of Columbia"),
    "the dmv": ("Washington", "District of Columbia"),
}
# The same table keyed without dots, so "D.C." and "DC" meet.
_ALIASES_BY_KEY = {key.replace(".", ""): value for key, value in _PLACE_ALIASES.items()}
_US_STATES = {
    "al": "Alabama", "ak": "Alaska", "az": "Arizona", "ar": "Arkansas", "ca": "California",
    "co": "Colorado", "ct": "Connecticut", "de": "Delaware", "dc": "District of Columbia",
    "fl": "Florida", "ga": "Georgia", "hi": "Hawaii", "id": "Idaho", "il": "Illinois",
    "in": "Indiana", "ia": "Iowa", "ks": "Kansas", "ky": "Kentucky", "la": "Louisiana",
    "me": "Maine", "md": "Maryland", "ma": "Massachusetts", "mi": "Michigan", "mn": "Minnesota",
    "ms": "Mississippi", "mo": "Missouri", "mt": "Montana", "ne": "Nebraska", "nv": "Nevada",
    "nh": "New Hampshire", "nj": "New Jersey", "nm": "New Mexico", "ny": "New York",
    "nc": "North Carolina", "nd": "North Dakota", "oh": "Ohio", "ok": "Oklahoma", "or": "Oregon",
    "pa": "Pennsylvania", "ri": "Rhode Island", "sc": "South Carolina", "sd": "South Dakota",
    "tn": "Tennessee", "tx": "Texas", "ut": "Utah", "vt": "Vermont", "va": "Virginia",
    "wa": "Washington", "wv": "West Virginia", "wi": "Wisconsin", "wy": "Wyoming",
}
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# The searches to try for a written place, most specific first: an alias
# when one applies, the whole string, then the part before the comma with
# the state after it remembered so the right "Arlington" is chosen.
def place_candidates(name: str) -> list[tuple[str, str | None]]:
    cleaned = " ".join(name.split())
    lowered = cleaned.casefold().replace(".", "").strip(" ,")
    if lowered in _ALIASES_BY_KEY:
        return [_ALIASES_BY_KEY[lowered]]
    candidates: list[tuple[str, str | None]] = [(cleaned, None)]
    head, _, tail = cleaned.partition(",")
    tail = tail.strip()
    if tail:
        region = _US_STATES.get(tail.casefold().strip(" ."), tail)
        candidates.append((head.strip(), region))
        if head.casefold().replace(".", "").strip() in _ALIASES_BY_KEY:
            candidates.insert(0, _ALIASES_BY_KEY[head.casefold().replace(".", "").strip()])
    else:
        words = cleaned.split()
        if len(words) >= 2 and words[-1].casefold().strip(".") in _US_STATES:
            candidates.append((" ".join(words[:-1]), _US_STATES[words[-1].casefold().strip(".")]))
    return candidates


# The best of the geocoder's matches: the one in the named region when a
# region was named, else the first (the geocoder's own ranking).
def choose_match(matches: list[dict], region: str | None) -> dict | None:
    if not matches:
        return None
    if region:
        wanted = region.casefold()
        for match in matches:
            admin = str(match.get("admin1") or "").casefold()
            if wanted and (wanted in admin or admin in wanted):
                return match
    return matches[0]


# Plain words for a forecast day: the WMO category, softened by the rain
# chance the same source reports - code 82 with a 29% chance is "a chance
# of showers", not "violent showers".
def describe_day(code: object, precipitation_chance: object) -> str:
    words = _describe_code(code)
    try:
        chance = int(precipitation_chance)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        chance = None
    wet = words not in ("clear sky", "mainly clear", "partly cloudy", "overcast", "fog", "depositing rime fog", "unknown conditions")
    if wet and chance is not None and chance < 40:
        kind = "storms" if "thunder" in words else ("snow" if "snow" in words else "showers")
        return f"chance of {kind} ({chance}%)"
    return words


def _weekday(date_text: object) -> str | None:
    from datetime import date

    try:
        return _WEEKDAYS[date.fromisoformat(str(date_text)[:10]).weekday()]
    except (TypeError, ValueError):
        return None


# The NWS daily forecast for a US point as rows, or None when it cannot be
# had. Periods come as day/night pairs; the day carries the conditions and
# high, its night the low.
async def _nws_daily(client: "httpx.AsyncClient", latitude: float, longitude: float, wanted_days: int) -> list[dict] | None:
    headers = {"User-Agent": "AniOS personal assistant (weather lookup)", "Accept": "application/geo+json"}
    try:
        point = await client.get(f"https://api.weather.gov/points/{latitude:.4f},{longitude:.4f}", headers=headers)
        forecast_url = ((point.json() or {}).get("properties") or {}).get("forecast")
        if not forecast_url:
            return None
        forecast = await client.get(forecast_url, headers=headers)
        periods = ((forecast.json() or {}).get("properties") or {}).get("periods") or []
    except Exception:
        return None
    rows: dict[str, dict] = {}
    for period in periods:
        day = str(period.get("startTime") or "")[:10]
        if not day:
            continue
        row = rows.setdefault(day, {"date": day, "weekday": _weekday(day), "conditions": None, "high": None, "low": None, "precipitation_chance_percent": None})
        chance = (period.get("probabilityOfPrecipitation") or {}).get("value")
        if period.get("isDaytime"):
            row["conditions"] = period.get("shortForecast")
            row["high"] = period.get("temperature")
            row["precipitation_chance_percent"] = chance
        else:
            row["low"] = period.get("temperature")
            if row["conditions"] is None:
                row["conditions"] = f"tonight: {period.get('shortForecast')}"
            if row["precipitation_chance_percent"] is None:
                row["precipitation_chance_percent"] = chance
    ordered = [rows[key] for key in sorted(rows)][:wanted_days]
    return ordered or None


# Words that point at a place without naming one. Shape, not intent: the
# geocoder will match them to a town somewhere, which is worse than asking.
_DEICTIC_PLACES = frozenset({
    "", "here", "right here", "there", "my location", "my current location", "current location",
    "my area", "the area", "where i am", "where i live", "my city", "my town", "home", "at home",
    "outside", "near me", "around me", "nearby", "local", "locally", "my place", "this area",
    "the local area", "our area", "our location", "unknown", "n/a", "none", "null",
})


def not_a_place(place: str) -> bool:
    cleaned = " ".join(str(place or "").casefold().replace("?", "").replace(".", "").split())
    return cleaned in _DEICTIC_PLACES


@mcp.tool()
async def get_weather(place: str, days: int = 1, units: str = "imperial") -> str:
    """Live current conditions and forecast for a named place.

    Use this, never web search, for any question about weather - right now,
    today, tonight, or the coming days. Not for travel time, directions,
    distance, or traffic: a clock time in "how long to drive to the airport
    at 5pm" is when they leave, and that is a web search. `place` is a city or
    town name as the person wrote it ("Arlington, Virginia", "DC", "NYC", a
    ZIP code); `days` is how many forecast days to include, counting today
    as 1, up to 7 - for "this weekend" or a named day, enough days to reach
    that day from today in the person's zone (asked on a Thursday, the
    weekend needs 4); `units` is "imperial" or "metric". `place` must name a
    real place - "here", "my location" or "outside" are refused - so when the
    person says "here" or names no place, pass the place the context says
    they are in ("they are in Arlington, Virginia" means place="Arlington,
    Virginia"); only when no place is known at all, call no tool and let the
    reply ask where they are.
    """
    # A place that is not a place: "here", "my location", "outside". The
    # geocoder resolves such words literally - "here" is Here, Togdheer,
    # Somalia, whose 83 °F and clear sky were reported to a group in Virginia
    # as its own weather (2026-08-28). No place named means no forecast: the
    # reply asks where they are.
    if not_a_place(place):
        return json.dumps({
            "error": "no_place",
            "place": place,
            "message": "No place was named and none is on record; ask where they are rather than guessing.",
        })
    name = (place or "").strip()
    if not name:
        return json.dumps({"error": "no place given"})
    wanted_days = max(1, min(int(days), 7))
    imperial = units != "metric"

    async with httpx.AsyncClient(timeout=15) as client:
        spot = None
        tried: list[str] = []
        for query, region in place_candidates(name):
            tried.append(query)
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": query, "count": 5, "language": "en", "format": "json"},
            )
            spot = choose_match((geo.json() or {}).get("results") or [], region)
            if spot:
                break
        if not spot:
            return json.dumps({"error": f"no place found for {name!r}", "tried": tried})
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
        nws_rows = (
            await _nws_daily(client, float(spot["latitude"]), float(spot["longitude"]), wanted_days)
            if imperial and str(spot.get("country_code") or "").upper() == "US"
            else None
        )

    current = body.get("current") or {}
    daily = body.get("daily") or {}
    temp_unit = "°F" if imperial else "°C"
    wind_unit = "mph" if imperial else "km/h"
    resolved = ", ".join(
        str(part)
        for part in (spot.get("name"), spot.get("admin1"), spot.get("country"))
        if part
    )
    if nws_rows:
        forecast_days = nws_rows
        source = "weather.gov (National Weather Service); current conditions open-meteo.com"
    else:
        forecast_days = [
            {
                "date": (daily.get("time") or [None] * wanted_days)[index],
                "weekday": _weekday((daily.get("time") or [None] * wanted_days)[index]),
                "conditions": describe_day(
                    (daily.get("weather_code") or [None] * wanted_days)[index],
                    (daily.get("precipitation_probability_max") or [None] * wanted_days)[index],
                ),
                "high": (daily.get("temperature_2m_max") or [None] * wanted_days)[index],
                "low": (daily.get("temperature_2m_min") or [None] * wanted_days)[index],
                "precipitation_chance_percent": (
                    daily.get("precipitation_probability_max") or [None] * wanted_days
                )[index],
            }
            for index in range(min(wanted_days, len(daily.get("time") or [])))
        ]
        source = "open-meteo.com"
    covered = [row.get("weekday") for row in forecast_days if row.get("weekday")]
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
            # Which days the rows cover, so a reply asked about the weekend
            # says so when Saturday or Sunday is not among them.
            "covers": covered,
            "source": source,
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
                "brave": await _brave_meter(),
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
            "brave": await _brave_meter(),
            "order": os.getenv("SEARCH_PROVIDER_ORDER") or "brave,google,tavily",
            "summary": _meter_summary(report, await _brave_meter()),
        }
    )


# One sentence a reply can relay without misreading the numbers: which rung
# serves now, and what each has left. Read back wrongly once ("Brave is set to
# run after Tavily") from the raw fields.
def _meter_summary(tavily: dict[str, object], brave: dict[str, object] | None) -> str:
    order = [
        name.strip().lower()
        for name in (os.getenv("SEARCH_PROVIDER_ORDER") or "brave,google,tavily").split(",")
        if name.strip()
    ]
    remaining = {}
    if brave is not None:
        remaining["brave"] = int(brave.get("remaining") or 0)
    tavily_left = tavily.get("remaining")
    remaining["tavily"] = int(tavily_left) if isinstance(tavily_left, int) else 0
    serving = next((name for name in order if remaining.get(name, 0) > 0), None)
    parts = []
    if brave is not None:
        parts.append(f"Brave has {remaining['brave']} of {brave.get('limit')} requests left this month")
    parts.append(
        f"Tavily has {remaining['tavily']} of {tavily.get('limit')} credits left this billing period"
    )
    if serving:
        return f"Searches are served by {serving} right now; " + "; ".join(parts) + "."
    return "Every search rung is spent: " + "; ".join(parts) + "."


# Brave's meter is local: the provider bills in dollars and reports no
# monthly request count, so the count that stops us is the one kept here.
async def _brave_meter() -> dict[str, object] | None:
    if not (os.getenv("BRAVE_SEARCH_API_KEY") or "").strip():
        return None
    limit = int(os.getenv("BRAVE_SEARCH_MONTHLY_LIMIT") or "900")
    quota = SQLiteMonthlySearchQuota(
        path=os.getenv("BRAVE_SEARCH_QUOTA_DB_PATH") or "data/search/brave_search_quota.sqlite3",
        provider="brave",
        monthly_limit=limit,
    )
    used = await quota.used()
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "period": "this calendar month, counted locally under the free credit",
    }


# Run the internet server over stdio for the configured AniOS MCP client.
def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
