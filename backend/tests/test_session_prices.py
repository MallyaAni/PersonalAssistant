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


# Invalid or old-session data never yields a current price.
@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"ap": 0}, "unavailable"),
        ({"bp": 103}, "unavailable"),
        ({"bs": 0}, "unavailable"),
        ({"ap": float("nan")}, "unavailable"),
        ({"t": "2026-09-25T04:00:00Z"}, "unavailable"),
        ({"t": "2026-09-24T20:00:00Z"}, "unavailable"),
        ({"t": "2026-09-25T02:58:59Z"}, "stale"),
    ],
)
def test_invalid_quotes(overrides, status):
    now = instant("2026-09-25T03:00:00+00:00")
    _, start, end = prices.session_window(now)
    row = prices.describe(quote(now, **overrides), "overnight", now, start, end)
    assert row["status"] == status
    assert row["price"] is None
    json.dumps(row, allow_nan=False)


# A fresh quote expires exactly when its session ends.
def test_midpoint_has_source_and_session_bounded_expiry():
    now = instant("2026-09-25T03:59:40-04:00")
    _, start, end = prices.session_window(now)
    row = prices.describe(quote(now), "overnight", now, start, end)
    assert row["price"] == 101
    assert row["indicative"] is True
    assert row["valid_until"] == end.isoformat()
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


# Inactive sessions do not request quotes or alter regular bars.
@pytest.mark.parametrize(
    "stamp", ["2026-09-24T12:00:00-04:00", "2026-09-26T12:00:00-04:00"]
)
def test_inactive_session_makes_no_request(stamp):
    # Any unexpected external read makes the boundary test fail.
    def forbidden(*args):
        pytest.fail("unexpected quote request")

    assert prices.fetch(["AAOI"], instant(stamp), forbidden)["quotes"] == {}
