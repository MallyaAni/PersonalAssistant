"""Extended-hours display evidence never substitutes for execution quotes."""

import json
from datetime import datetime, timedelta

import pytest

from backend.market import session_prices as prices


# Use explicit offsets to exercise real exchange-session boundaries and DST.
def instant(value):
    return datetime.fromisoformat(value)


# Keep each transport test independent of prior entitlements and cached symbols.
@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    prices._cache.clear()
    prices._denied_until.clear()
    monkeypatch.setattr(prices.alpaca, "credentials", lambda: {})


# Calendar closure and overnight trade dates follow the next eligible session.
@pytest.mark.parametrize(
    ("stamp", "phase"),
    [
        ("2026-09-24T03:59:59-04:00", "overnight"),
        ("2026-09-24T04:00:00-04:00", "pre-market"),
        ("2026-09-24T09:30:00-04:00", "regular"),
        ("2026-09-24T16:00:00-04:00", "post-market"),
        ("2026-09-24T20:00:00-04:00", "overnight"),
        ("2026-09-25T20:00:00-04:00", "closed"),
        ("2026-09-27T19:59:59-04:00", "closed"),
        ("2026-09-27T20:00:00-04:00", "overnight"),
        ("2026-09-06T20:00:00-04:00", "closed"),
        ("2026-09-07T20:00:00-04:00", "overnight"),
        ("2026-11-27T13:00:00-05:00", "post-market"),
        ("2026-11-01T20:00:00-05:00", "overnight"),
        ("2039-01-03T21:00:00-05:00", "unknown"),
    ],
)
def test_session_boundaries(stamp, phase):
    assert prices.session_window(instant(stamp))[0] == phase


# Keep raw provider evidence separate from the display midpoint.
def quote(now, **overrides):
    return {"bp": 100, "ap": 102, "bs": 10, "as": 20, "t": now.isoformat(), **overrides}


# Invalid or future data never yields a price; expired data is never fresh.
@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"ap": 0}, "unavailable"),
        ({"bp": 103}, "unavailable"),
        ({"bs": 0}, "unavailable"),
        ({"ap": float("nan")}, "unavailable"),
        ({"t": "2026-09-25T04:00:00Z"}, "unavailable"),
        ({"t": "2026-09-24T20:00:00Z"}, "stale"),
        ({"t": "2026-09-25T02:58:59Z"}, "stale"),
    ],
)
def test_invalid_quotes(overrides, status):
    now = instant("2026-09-25T03:00:00+00:00")
    row = prices.describe(quote(now, **overrides), "overnight", now)
    assert row["status"] == status
    assert row["price"] == (101 if status == "stale" else None)
    json.dumps(row, allow_nan=False)


# An expired quote keeps its last midpoint, dated by its own observation time.
def test_expired_quote_keeps_last_observed_price_and_time():
    observed = instant("2026-09-25T16:59:58-04:00")
    now = instant("2026-09-26T11:00:00-04:00")
    row = prices.describe(quote(observed), "iex", now)
    assert row["status"] == "stale"
    assert row["reason"] == "Quote expired"
    assert (row["price"], row["bid"], row["ask"]) == (101, 100, 102)
    assert instant(row["at"]) == observed
    assert instant(row["valid_until"]) == observed + timedelta(seconds=60)
    assert row["session"] == "post-market"
    assert row["feed"] == "iex"


# Keep the original phase and full age deadline across a schedule boundary.
def test_midpoint_has_source_and_age_bounded_expiry():
    now = instant("2026-09-25T03:59:40-04:00")
    row = prices.describe(quote(now), "overnight", now)
    assert row["price"] == 101
    assert row["indicative"] is True
    assert instant(row["valid_until"]) == now + timedelta(seconds=60)
    assert row["session"] == "overnight"
    assert row["status"] == "fresh"
    assert "eligible" not in row


# Denied feeds fall back to existing free data without orders or subscriptions.
def test_fetch_fallback_cache_expiry_and_failure(monkeypatch):
    now = instant("2026-09-25T03:00:00+00:00")
    calls = []
    failure = False

    # Model only data GETs, preserving quote time even when the request is later.
    def request(url, headers):
        calls.append(url)
        if failure:
            raise TimeoutError("provider unavailable")
        if "feed=boats" in url:
            return 403, b"{}"
        return 200, json.dumps({"quotes": {"AAOI": quote(now)}}).encode()

    result = prices.fetch(["AAOI", "Q", "AAOI"], now, request, lambda: 1)
    assert result["quotes"]["AAOI"]["price"] == 101
    assert result["quotes"]["Q"]["status"] == "unavailable"
    assert result["signal_scope"] == "regular-session"
    assert len(calls) == 2
    cached = prices.fetch(
        ["AAOI", "Q"], now + timedelta(seconds=61), request, lambda: 2
    )
    assert cached["quotes"]["AAOI"]["status"] == "stale"
    assert len(calls) == 2
    failure = True
    failed = prices.fetch(
        ["AAOI", "Q"], now + timedelta(seconds=62), request, lambda: 12
    )
    assert failed["quotes"]["AAOI"]["status"] == "unavailable"
    assert failed["quotes"]["AAOI"]["price"] is None
    assert "feed=overnight" in calls[-1]


# Every expected schedule still probes display feeds without changing signal scope.
@pytest.mark.parametrize(
    "stamp", ["2026-09-24T12:00:00-04:00", "2026-09-26T12:00:00-04:00"]
)
def test_regular_and_weekend_schedules_still_request_quotes(stamp):
    calls = []
    now = instant(stamp)

    # Return a dated synthetic observation and track the existing provider boundary.
    def request(url, headers):
        calls.append(url)
        return 200, json.dumps({"quotes": {"AAOI": quote(now)}}).encode()

    result = prices.fetch(["AAOI"], now, request)
    assert len(calls) == 1
    assert result["quotes"]["AAOI"]["price"] == 101
    assert result["signal_scope"] == "regular-session"


# The pair follows the calendar, not the clock alone: on a Saturday at
# 03:00 New York no overnight session is running and IEX holds the newest
# print (Friday 16:59), so the day pair is asked; on a Monday at 05:00 the
# overnight venue's 03:59 print is the newest, so the night pair is; from
# 08:00 IEX prints again and the day pair returns.
@pytest.mark.parametrize(
    ("stamp", "pair"),
    [
        ("2026-09-26T07:00:00+00:00", ["sip", "iex"]),  # Saturday 03:00
        ("2026-09-27T01:00:00+00:00", ["sip", "iex"]),  # Saturday 21:00
        ("2026-09-28T01:00:00+00:00", ["boats", "overnight"]),  # Sunday 21:00
        ("2026-09-28T09:00:00+00:00", ["boats", "overnight"]),  # Monday 05:00
        ("2026-09-28T12:30:00+00:00", ["sip", "iex"]),  # Monday 08:30
        ("2026-09-25T03:00:00+00:00", ["boats", "overnight"]),  # Thursday 23:00
    ],
)
def test_feed_pair_follows_the_exchange_calendar(stamp, pair):
    now = instant(stamp)
    friday_close = instant("2026-09-25T20:59:58+00:00")
    calls = []

    def request(url, headers):
        calls.append(url.split("feed=")[1])
        if "feed=iex" in url:
            return 200, json.dumps({"quotes": {"AAOI": quote(friday_close, bp=200, ap=202)}}).encode()
        return 403, b"{}"

    result = prices.fetch(["AAOI"], now, request, lambda: 1)
    assert calls == pair
    row = result["quotes"]["AAOI"]
    if pair == ["sip", "iex"]:
        assert row["status"] == "stale" and row["feed"] == "iex" and row["price"] == 201
        assert row["at"] == friday_close.isoformat() and row["session"] == "post-market"
