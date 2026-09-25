"""Fresh display evidence is independent of calendar expectations and feed gaps."""

import importlib
import json
from collections import deque
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from curl_cffi import requests

from backend.market import alpaca_trading, execution_quotes
from backend.market import session_prices as prices


# Parse explicitly dated observations without relying on the machine's timezone.
def instant(value):
    return datetime.fromisoformat(value)


# Construct public synthetic quote evidence with independently dated prices.
def quote(at, midpoint=101, **changes):
    return {
        "t": at.isoformat(),
        "bp": midpoint - 1,
        "ap": midpoint + 1,
        "bs": 10,
        "as": 20,
        **changes,
    }


class Clock:
    # Keep cache and backoff time independent of the quote's wall-clock age.
    def __init__(self, tick=100):
        self.tick = tick

    # Return a controllable monotonic instant without sleeping during tests.
    def __call__(self):
        return self.tick


class QuoteResponses:
    # Retain an exact response script and the actual requested feed/symbol pairs.
    def __init__(self, *replies):
        self.replies = deque(replies)
        self.calls = []

    # Allow only credential-free latest-quote GET inputs and consume one reply.
    def __call__(self, url, headers):
        address = urlsplit(url)
        assert address.scheme == "https"
        assert address.netloc == "data.alpaca.markets"
        assert address.path == "/v2/stocks/quotes/latest"
        query = parse_qs(address.query)
        assert set(query) == {"symbols", "feed"}
        assert headers == {}
        assert len(query["symbols"]) == len(query["feed"]) == 1
        feed = query["feed"][0]
        assert feed in {"sip", "iex", "boats", "overnight"}
        self.calls.append((feed, tuple(query["symbols"][0].split(","))))
        if not self.replies:
            pytest.fail("The quote reader exceeded its scripted read budget")
        reply = self.replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        status, payload = reply
        return status, (
            payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        )


# Fail before any real network, account, broker-clock or execution read can occur.
def forbidden(*args, **kwargs):
    pytest.fail("Display-price acceptance must not touch another external boundary")


# Supply no secret or account identity to the synthetic provider.
def empty_credentials():
    return {}


# Reset runtime state per case without asserting on its private cache implementation.
@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    importlib.reload(prices)
    monkeypatch.setattr(prices.alpaca, "credentials", empty_credentials)
    monkeypatch.setattr(prices.alpaca, "alpaca_transport", forbidden)
    monkeypatch.setattr(alpaca_trading, "client_from_env", forbidden)
    monkeypatch.setattr(alpaca_trading, "urllib_transport", forbidden)
    monkeypatch.setattr(execution_quotes, "fetch", forbidden)
    monkeypatch.setattr(requests, "get", forbidden)


# Existing pre/post/overnight controls still preserve source and display-only meaning.
@pytest.mark.parametrize(
    ("stamp", "feed"),
    [
        ("2026-09-24T07:00:00-04:00", "sip"),
        ("2026-09-24T18:00:00-04:00", "sip"),
        ("2026-09-24T22:00:00-04:00", "boats"),
    ],
)
def test_existing_fresh_primary_needs_no_fallback(stamp, feed):
    now = instant(stamp)
    read = QuoteResponses((200, {"quotes": {"ZZZ": quote(now), "AAA": quote(now)}}))
    result = prices.fetch(["ZZZ", "AAA", "ZZZ"], now, read, Clock())
    assert read.calls == [(feed, ("AAA", "ZZZ"))]
    assert set(result["quotes"]) == {"AAA", "ZZZ"}
    assert result["signal_scope"] == "regular-session"
    for row in result["quotes"].values():
        assert row["price"] == 101
        assert row["status"] == "fresh"
        assert row["feed"] == feed
        assert row["indicative"] is False
        assert "eligible" not in row


# Calendar expectations do not suppress an independently available fresh quote.
@pytest.mark.parametrize(
    ("stamp", "schedule", "feed"),
    [
        ("2026-09-24T12:00:00-04:00", "regular", "sip"),
        ("2026-09-26T12:00:00-04:00", "closed", "sip"),
        ("2026-09-25T21:00:00-04:00", "closed", "boats"),
        ("2026-09-06T21:00:00-04:00", "closed", "boats"),
        ("2026-09-07T12:00:00-04:00", "closed", "sip"),
        ("2039-01-03T12:00:00-05:00", "unknown", "sip"),
        ("2039-01-03T21:00:00-05:00", "unknown", "boats"),
    ],
)
def test_expected_schedule_is_not_an_availability_gate(stamp, schedule, feed):
    now = instant(stamp)
    read = QuoteResponses((200, {"quotes": {"AAA": quote(now)}}))
    result = prices.fetch(["AAA"], now, read, Clock())
    assert read.calls == [(feed, ("AAA",))]
    assert result["session"] == schedule
    assert result["quotes"]["AAA"]["status"] == "fresh"
    assert result["quotes"]["AAA"]["price"] == 101
    assert result["quotes"]["AAA"]["session"] == schedule
    assert result["signal_scope"] == "regular-session"


# A recent observation keeps its original phase while its full age budget remains.
@pytest.mark.parametrize(
    ("stamp", "previous", "current", "feed"),
    [
        ("2026-09-24T04:00:01-04:00", "overnight", "pre-market", "sip"),
        ("2026-09-24T09:30:01-04:00", "pre-market", "regular", "sip"),
        ("2026-09-24T16:00:01-04:00", "regular", "post-market", "sip"),
        ("2026-09-24T20:00:01-04:00", "post-market", "overnight", "boats"),
    ],
)
def test_recent_previous_phase_quote_is_not_discarded_or_relabelled(
    stamp, previous, current, feed
):
    now = instant(stamp)
    observed = now - timedelta(seconds=2)
    read = QuoteResponses((200, {"quotes": {"AAA": quote(observed)}}))
    result = prices.fetch(["AAA"], now, read, Clock())
    row = result["quotes"]["AAA"]
    assert read.calls == [(feed, ("AAA",))]
    assert result["session"] == current
    assert row["session"] == previous
    assert instant(row["at"]) == observed
    assert instant(row["valid_until"]) == observed + timedelta(seconds=60)
    assert row["status"] == "fresh"
    assert row["price"] == 101
    assert "eligible" not in row


# Partial success keeps good primary evidence and falls back only for unresolved names.
def test_mixed_primary_batch_selects_each_symbols_own_source_and_time():
    now = instant("2026-09-24T22:00:00-04:00")
    primary_at = now - timedelta(seconds=12)
    fallback_at = now - timedelta(seconds=1)
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    primary = {
        "AAA": quote(primary_at, 101),
        "BBB": quote(now - timedelta(seconds=61), 201),
        "CCC": quote(now, 301, ap=0),
        "EEE": quote(now + timedelta(seconds=1), 501),
        "FFF": None,
    }
    fallback = {symbol: quote(fallback_at, 601) for symbol in symbols}
    read = QuoteResponses((200, {"quotes": primary}), (200, {"quotes": fallback}))
    result = prices.fetch(symbols, now, read, Clock())
    assert read.calls == [
        ("boats", tuple(symbols)),
        ("overnight", tuple(symbols[1:])),
    ]
    retained = result["quotes"]["AAA"]
    assert retained["price"] == 101
    assert retained["feed"] == "boats"
    assert retained["indicative"] is False
    assert instant(retained["at"]) == primary_at
    for symbol in symbols[1:]:
        row = result["quotes"][symbol]
        assert row["price"] == 601
        assert row["feed"] == "overnight"
        assert row["indicative"] is True
        assert row["session"] == "overnight"
        assert instant(row["at"]) == fallback_at
    assert result["signal_scope"] == "regular-session"


# HTTP success with missing or malformed quote evidence still permits a valid fallback.
@pytest.mark.parametrize(
    "primary",
    [
        {"quotes": {}},
        {"quotes": None},
        {"quotes": []},
        {"quotes": {"AAA": {}}},
        {"quotes": {"AAA": "not a quote"}},
        {},
        [],
        b"invalid JSON",
    ],
)
def test_empty_or_malformed_primary_success_does_not_stop_fallback(primary):
    now = instant("2026-09-24T07:00:00-04:00")
    read = QuoteResponses((200, primary), (200, {"quotes": {"AAA": quote(now)}}))
    result = prices.fetch(["AAA"], now, read, Clock())
    assert read.calls == [("sip", ("AAA",)), ("iex", ("AAA",))]
    assert result["quotes"]["AAA"]["price"] == 101
    assert result["quotes"]["AAA"]["feed"] == "iex"


# Timestamp conversion outside supported datetime bounds cannot poison the whole batch.
@pytest.mark.parametrize(
    "timestamp", ["0001-01-01T00:00:00Z", "9999-12-31T23:59:59-05:00"]
)
def test_unrepresentable_quote_instant_does_not_block_valid_fallback(timestamp):
    now = instant("2026-09-24T18:00:00-04:00")
    primary = {"quotes": {"AAA": quote(now, t=timestamp)}}
    fallback = {"quotes": {"AAA": quote(now)}}
    read = QuoteResponses((200, primary), (200, fallback))
    result = prices.fetch(["AAA"], now, read, Clock())
    assert read.calls == [("sip", ("AAA",)), ("iex", ("AAA",))]
    assert result["quotes"]["AAA"]["status"] == "fresh"
    assert result["quotes"]["AAA"]["feed"] == "iex"
    assert result["quotes"]["AAA"]["price"] == 101


# A failed primary consumes one attempt and cannot conceal an available fallback.
@pytest.mark.parametrize("failure", [401, 403, 429, 500, 503, "timeout"])
def test_primary_failure_is_bounded_and_falls_back_without_exposing_errors(failure):
    now = instant("2026-09-24T18:00:00-04:00")
    private_marker = "DO_NOT_EXPOSE_PROVIDER_BODY"
    first = (
        TimeoutError(private_marker)
        if failure == "timeout"
        else (failure, private_marker.encode())
    )
    read = QuoteResponses(first, (200, {"quotes": {"AAA": quote(now)}}))
    result = prices.fetch(["AAA"], now, read, Clock())
    assert read.calls == [("sip", ("AAA",)), ("iex", ("AAA",))]
    assert result["quotes"]["AAA"]["status"] == "fresh"
    assert result["quotes"]["AAA"]["feed"] == "iex"
    assert private_marker not in json.dumps(result, allow_nan=False)


# Denied or throttled feeds back off across symbols, then become retryable.
@pytest.mark.parametrize("status", [403, 429])
def test_backoff_applies_to_both_feeds_and_is_not_per_symbol(status):
    now = instant("2026-09-24T18:00:00-04:00")
    clock = Clock()
    read = QuoteResponses((status, {}), (status, {}))
    initial = prices.fetch(["AAA"], now, read, clock)
    assert read.calls == [("sip", ("AAA",)), ("iex", ("AAA",))]
    assert initial["quotes"]["AAA"]["price"] is None
    clock.tick += 11
    blocked = prices.fetch(["BBB"], now + timedelta(seconds=11), read, clock)
    assert len(read.calls) == 2
    assert blocked["quotes"]["BBB"]["price"] is None
    clock.tick += 350
    retry_at = now + timedelta(seconds=361)
    read.replies.extend([(status, {}), (200, {"quotes": {"BBB": quote(retry_at)}})])
    recovered = prices.fetch(["BBB"], retry_at, read, clock)
    assert read.calls[-2:] == [("sip", ("BBB",)), ("iex", ("BBB",))]
    assert recovered["quotes"]["BBB"]["status"] == "fresh"
    assert recovered["quotes"]["BBB"]["feed"] == "iex"


# Generic failures briefly back off both feeds and permit prompt recovery.
def test_generic_failure_backoff_has_a_bounded_recovery_window():
    now = instant("2026-09-24T18:00:00-04:00")
    clock = Clock()
    read = QuoteResponses((503, {}), TimeoutError("temporary failure"))
    initial = prices.fetch(["AAA"], now, read, clock)
    assert initial["quotes"]["AAA"]["price"] is None
    assert read.calls == [("sip", ("AAA",)), ("iex", ("AAA",))]
    clock.tick += 5
    blocked = prices.fetch(["BBB"], now + timedelta(seconds=5), read, clock)
    assert len(read.calls) == 2
    assert blocked["quotes"]["BBB"]["price"] is None
    clock.tick += 6
    retry_at = now + timedelta(seconds=11)
    read.replies.extend([(503, {}), (200, {"quotes": {"BBB": quote(retry_at)}})])
    recovered = prices.fetch(["BBB"], retry_at, read, clock)
    assert read.calls[-2:] == [("sip", ("BBB",)), ("iex", ("BBB",))]
    assert recovered["quotes"]["BBB"]["status"] == "fresh"


# A cached observation expires at its data deadline without becoming a new observation.
def test_cache_read_revalidates_age_and_does_not_refresh_quote_time():
    now = instant("2026-09-24T18:00:00-04:00")
    observed = now - timedelta(seconds=50)
    clock = Clock()
    read = QuoteResponses(
        (200, {"quotes": {"AAA": quote(observed)}}), (200, {"quotes": {}})
    )
    first = prices.fetch(["AAA"], now, read, clock)
    assert first["quotes"]["AAA"]["status"] == "fresh"
    clock.tick += 1
    expired = prices.fetch(["AAA"], now + timedelta(seconds=10), read, clock)
    row = expired["quotes"]["AAA"]
    assert read.calls == [("sip", ("AAA",)), ("iex", ("AAA",))]
    assert row["status"] == "stale"
    assert row["price"] is None
    assert instant(row["at"]) == observed
    assert row["feed"] == "sip"


# Cached primary expiry permits a new fallback without repeating the primary request.
def test_cached_primary_expiry_recovers_from_fresh_fallback():
    now = instant("2026-09-24T18:00:00-04:00")
    observed = now - timedelta(seconds=50)
    later = now + timedelta(seconds=10)
    clock = Clock()
    read = QuoteResponses(
        (200, {"quotes": {"AAA": quote(observed)}}),
        (200, {"quotes": {"AAA": quote(later, 201)}}),
    )
    first = prices.fetch(["AAA"], now, read, clock)
    assert first["quotes"]["AAA"]["feed"] == "sip"
    assert first["quotes"]["AAA"]["price"] == 101
    clock.tick += 1
    result = prices.fetch(["AAA"], later, read, clock)
    assert read.calls == [("sip", ("AAA",)), ("iex", ("AAA",))]
    row = result["quotes"]["AAA"]
    assert row["status"] == "fresh"
    assert row["price"] == 201
    assert row["feed"] == "iex"
    assert instant(row["at"]) == later


# When both feeds are old, retain the newest valid source/time without a current price.
@pytest.mark.parametrize(
    ("primary_age", "fallback_age", "selected"),
    [(61, 80, "boats"), (80, 61, "overnight")],
)
def test_stale_diagnostic_retains_the_newest_observation(
    primary_age, fallback_age, selected
):
    now = instant("2026-09-24T22:00:00-04:00")
    primary_at = now - timedelta(seconds=primary_age)
    fallback_at = now - timedelta(seconds=fallback_age)
    read = QuoteResponses(
        (200, {"quotes": {"AAA": quote(primary_at, 101)}}),
        (200, {"quotes": {"AAA": quote(fallback_at, 201)}}),
    )
    result = prices.fetch(["AAA"], now, read, Clock())
    assert read.calls == [("boats", ("AAA",)), ("overnight", ("AAA",))]
    row = result["quotes"]["AAA"]
    assert row["status"] == "stale"
    assert row["price"] is None
    assert row["feed"] == selected
    assert row["indicative"] is (selected == "overnight")
    assert instant(row["at"]) == max(primary_at, fallback_at)
    assert row["session"] == "overnight"


# A request crossing a phase boundary preserves evidence and updates only the envelope.
@pytest.mark.parametrize(
    ("before", "after", "previous", "current", "feed"),
    [
        (
            "2026-09-24T03:59:59-04:00",
            "2026-09-24T04:00:01-04:00",
            "overnight",
            "pre-market",
            "boats",
        ),
        (
            "2026-09-24T19:59:59-04:00",
            "2026-09-24T20:00:01-04:00",
            "post-market",
            "overnight",
            "sip",
        ),
    ],
)
def test_unsupplied_now_rollover_keeps_recent_original_session(
    monkeypatch, before, after, previous, current, feed
):
    observed, finished = instant(before), instant(after)
    wall = {"now": observed}
    scripted = QuoteResponses((200, {"quotes": {"AAA": quote(observed)}}))

    class WallDateTime(datetime):
        # Follow the mutable wall clock regardless of how often it is sampled.
        @classmethod
        def now(cls, tz=None):
            return (
                wall["now"].astimezone(tz) if tz else wall["now"].replace(tzinfo=None)
            )

    # Advance real-time observation while the synthetic request is in flight.
    def read(url, headers):
        response = scripted(url, headers)
        wall["now"] = finished
        return response

    monkeypatch.setattr(prices, "datetime", WallDateTime)
    result = prices.fetch(["AAA"], request=read, monotonic=Clock())
    assert scripted.calls == [(feed, ("AAA",))]
    assert result["session"] == current
    assert instant(result["as_of"]) == finished
    row = result["quotes"]["AAA"]
    assert row["status"] == "fresh"
    assert row["price"] == 101
    assert row["session"] == previous
    assert instant(row["at"]) == observed
    assert instant(row["valid_until"]) == observed + timedelta(seconds=60)


# New provider failure cannot resurrect a still-young price from an older fetch.
def test_failed_refresh_discards_prior_price_even_before_its_age_deadline():
    now = instant("2026-09-24T18:00:00-04:00")
    clock = Clock()
    read = QuoteResponses(
        (200, {"quotes": {"AAA": quote(now)}}),
        TimeoutError("first unavailable"),
        TimeoutError("second unavailable"),
    )
    assert prices.fetch(["AAA"], now, read, clock)["quotes"]["AAA"]["price"] == 101
    clock.tick += 11
    result = prices.fetch(["AAA"], now + timedelta(seconds=11), read, clock)
    assert read.calls == [("sip", ("AAA",)), ("sip", ("AAA",)), ("iex", ("AAA",))]
    assert result["quotes"]["AAA"]["price"] is None
    assert result["quotes"]["AAA"]["status"] != "fresh"


# A late failure cannot erase newer evidence or impose stale feed-wide backoff.
@pytest.mark.parametrize("newer_symbol", ["AAA", "BBB"])
@pytest.mark.parametrize("tick_advance", [0, 1])
def test_older_failure_cannot_replace_newer_success_or_deny_its_feed(
    newer_symbol, tick_advance
):
    now = instant("2026-09-24T18:00:00-04:00")
    clock = Clock()
    newer_at = now + timedelta(seconds=1)
    nested_results = []
    scripted = QuoteResponses(
        (500, {}),
        (200, {"quotes": {newer_symbol: quote(newer_at, 201)}}),
        (503, {}),
    )

    # Complete a newer request before letting the older primary report failure.
    def read(url, headers):
        response = scripted(url, headers)
        if len(scripted.calls) == 1:
            clock.tick += tick_advance
            nested_results.append(prices.fetch([newer_symbol], newer_at, read, clock))
        return response

    prices.fetch(["AAA"], now, read, clock)
    assert scripted.calls == [
        ("sip", ("AAA",)),
        ("sip", (newer_symbol,)),
        ("iex", ("AAA",)),
    ]
    assert nested_results[0]["quotes"][newer_symbol]["price"] == 201
    clock.tick += 1
    latest = prices.fetch([newer_symbol], now + timedelta(seconds=2), read, clock)
    assert len(scripted.calls) == 3
    row = latest["quotes"][newer_symbol]
    assert row["status"] == "fresh"
    assert row["price"] == 201
    assert row["feed"] == "sip"
    assert instant(row["at"]) == newer_at


# An older success completing last cannot replace a newer successful cache entry.
@pytest.mark.parametrize("tick_advance", [0, 1])
def test_older_success_cannot_overwrite_newer_successful_quote(tick_advance):
    now = instant("2026-09-24T18:00:00-04:00")
    clock = Clock()
    newer_at = now + timedelta(seconds=1)
    nested_results = []
    scripted = QuoteResponses(
        (200, {"quotes": {"AAA": quote(now, 101)}}),
        (200, {"quotes": {"AAA": quote(newer_at, 201)}}),
    )

    # Finish newer evidence while the earlier successful response is still held.
    def read(url, headers):
        response = scripted(url, headers)
        if len(scripted.calls) == 1:
            clock.tick += tick_advance
            nested_results.append(prices.fetch(["AAA"], newer_at, read, clock))
        return response

    prices.fetch(["AAA"], now, read, clock)
    assert nested_results[0]["quotes"]["AAA"]["price"] == 201
    clock.tick += 1
    latest = prices.fetch(["AAA"], now + timedelta(seconds=2), read, clock)
    assert scripted.calls == [("sip", ("AAA",)), ("sip", ("AAA",))]
    row = latest["quotes"]["AAA"]
    assert row["status"] == "fresh"
    assert row["price"] == 201
    assert row["feed"] == "sip"
    assert instant(row["at"]) == newer_at


# No combination of invalid primary and fallback evidence fabricates a current price.
@pytest.mark.parametrize(
    "change",
    [
        {"ap": 0},
        {"bp": 103},
        {"bs": 0},
        {"ap": float("nan")},
        {"t": "2026-09-24T18:00:01-04:00"},
        {"t": "2026-09-24T17:59:00-04:00"},
        {"t": "2026-09-24T18:00:00"},
    ],
)
def test_both_feeds_invalid_never_produce_a_fresh_midpoint(change):
    now = instant("2026-09-24T18:00:00-04:00")
    payload = {"quotes": {"AAA": quote(now, **change)}}
    read = QuoteResponses((200, payload), (200, payload))
    result = prices.fetch(["AAA"], now, read, Clock())
    assert read.calls == [("sip", ("AAA",)), ("iex", ("AAA",))]
    assert result["quotes"]["AAA"]["price"] is None
    assert result["quotes"]["AAA"]["status"] != "fresh"
    json.dumps(result, allow_nan=False)


# The real display transport's two timeouts fit inside the existing browser deadline.
def test_default_transport_has_a_bounded_two_feed_timeout_budget(monkeypatch):
    now = instant("2026-09-24T18:00:00-04:00")
    scripted = QuoteResponses((403, {}), (200, {"quotes": {"AAA": quote(now)}}))
    timeouts = []

    # Observe the actual curl request contract without opening a network connection.
    def get(url, *, headers, timeout):
        timeouts.append(timeout)
        status, body = scripted(url, headers)
        return SimpleNamespace(status_code=status, content=body)

    monkeypatch.setattr(requests, "get", get)
    result = prices.fetch(["AAA"], now=now, monotonic=Clock())
    assert scripted.calls == [("sip", ("AAA",)), ("iex", ("AAA",))]
    assert len(timeouts) == 2
    assert all(isinstance(timeout, (int, float)) for timeout in timeouts)
    assert all(0 < timeout <= 2 for timeout in timeouts), timeouts
    assert sum(timeouts) <= 4
    assert result["quotes"]["AAA"]["status"] == "fresh"


# Display evidence does not grant execution eligibility outside the supported session.
def test_overnight_midpoint_does_not_change_execution_eligibility():
    now = instant("2026-09-24T22:00:00-04:00")
    raw = quote(now)
    read = QuoteResponses((403, {}), (200, {"quotes": {"AAA": raw}}))
    result = prices.fetch(["AAA"], now, read, Clock())
    assert result["quotes"]["AAA"]["price"] == 101
    assert result["signal_scope"] == "regular-session"
    assert "eligible" not in result["quotes"]["AAA"]
    execution = execution_quotes.describe(raw, "overnight", market_open=False, now=now)
    assert execution["eligible"] is False


# An empty batch has no external work and retains the expected-session envelope.
def test_empty_batch_does_not_request_a_feed():
    result = prices.fetch([], instant("2026-09-24T18:00:00-04:00"), forbidden, Clock())
    assert result["quotes"] == {}
    assert result["signal_scope"] == "regular-session"


# An undated input is rejected before any data request can be issued.
def test_naive_now_fails_before_requesting_quotes():
    with pytest.raises(ValueError, match="dated instant"):
        prices.fetch(["AAA"], datetime(2026, 9, 24, 18), forbidden, Clock())
