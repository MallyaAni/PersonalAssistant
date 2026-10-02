"""Current chart candles retain real timing, source, gaps and early closes."""

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from backend.market import calendar as exchange_calendar
from backend.market import live_chart, ticker_chart_intraday
from backend.market.alpaca import IntradayBar
from backend.market.store import MarketStore


# A printed regular-session grid with a distinct current price and raw basis.
def _bars(day="2026-10-02", count=8):
    opening = datetime.fromisoformat(day + "T09:30:00-04:00")
    return [
        IntradayBar(opening + timedelta(minutes=15 * i), 100, 102, 99, 101, 10)
        for i in range(count)
    ]


# Keep provider cache state independent across clock and malformed-input cases.
@pytest.fixture(autouse=True)
def _clear_cache():
    live_chart._cache.clear()
    yield
    live_chart._cache.clear()


# Forming bars are chart evidence, while future and extended-hours bars are excluded.
def test_current_session_filters_future_and_extended_bars():
    now = datetime.fromisoformat("2026-10-02T11:16:00-04:00")
    bars = _bars(count=10)
    before = replace(bars[0], start=bars[0].start - timedelta(minutes=15))
    out = live_chart.qualify(
        [before, *bars], now, exchange_calendar.exchange_status(now)
    )
    assert len(out) == 8
    assert out[-1].start.hour == 11
    assert out[-1].start.minute == 15
    assert out[-1].close == 101


# Invalid, ambiguous or missing slots must not become synthetic chart continuity.
@pytest.mark.parametrize(
    "defect",
    [
        "duplicate",
        "gap",
        "missing_open",
        "stale",
        "nan",
        "range",
        "negative_volume",
        "naive",
    ],
)
def test_current_session_rejects_invalid_evidence(defect):
    now = datetime.fromisoformat("2026-10-02T11:16:00-04:00")
    bars = _bars()
    if defect == "duplicate":
        bars.append(bars[-1])
    elif defect == "gap":
        bars.pop(2)
    elif defect == "missing_open":
        bars.pop(0)
    elif defect == "stale":
        bars = bars[:4]
    elif defect == "nan":
        bars[-1] = replace(bars[-1], close=float("nan"))
    elif defect == "range":
        bars[-1] = replace(bars[-1], high=100)
    elif defect == "negative_volume":
        bars[-1] = replace(bars[-1], volume=-1)
    else:
        bars[-1] = replace(bars[-1], start=bars[-1].start.replace(tzinfo=None))
    with pytest.raises(ValueError, match="(?i)live chart"):
        live_chart.qualify(bars, now, exchange_calendar.exchange_status(now))


# Cache expiry and the 15-minute boundary fetch new raw IEX observations.
def test_cache_refresh_source_and_boundary(monkeypatch):
    calls = []

    # Return the available prefix appropriate to each supplied test clock.
    def fetch(ticker, start, end, **kwargs):
        calls.append((ticker, start, end, kwargs))
        return _bars(count=3)

    monkeypatch.setattr(live_chart.alpaca, "fetch_bars", fetch)
    at = datetime.fromisoformat("2026-10-02T09:59:50-04:00")
    first = live_chart.read("aapl", at)
    assert len(first["bars"]) == 2
    assert not first["complete"]
    assert live_chart.read("AAPL", at + timedelta(seconds=5)) is first
    second = live_chart.read("AAPL", at + timedelta(seconds=10))
    assert len(second["bars"]) == 3
    live_chart.read("AAPL", at + timedelta(seconds=31))
    assert len(calls) == 3
    assert calls[0][:3] == ("AAPL", date(2026, 10, 2), date(2026, 10, 2))
    assert calls[0][3]["feed"] == "iex"
    assert calls[0][3]["adjustment"] == "raw"


# Early-close sessions finish at 13:00, without fabricating afternoon candles.
def test_early_close_completion_and_missing_last_slot(monkeypatch):
    now = datetime.fromisoformat("2026-11-27T13:01:00-05:00")
    opening = datetime.fromisoformat("2026-11-27T09:30:00-05:00")
    bars = [
        replace(bar, start=opening + timedelta(minutes=15 * i))
        for i, bar in enumerate(_bars(count=14))
    ]
    monkeypatch.setattr(live_chart.alpaca, "fetch_bars", lambda *a, **k: bars)
    out = live_chart.read("AAPL", now)
    assert len(out["bars"]) == 14
    assert out["complete"]
    with pytest.raises(ValueError, match="incomplete"):
        live_chart.qualify(bars[:-1], now, exchange_calendar.exchange_status(now))


# Disclose read failure without secrets or writes to frozen partitions.
def test_unavailable_read_and_chart_only_current_session(monkeypatch, tmp_path):
    now = datetime.fromisoformat("2026-10-02T11:16:00-04:00")

    # A provider's exception body must never become displayed dashboard text.
    def fail(*args, **kwargs):
        raise RuntimeError("private provider credentials")

    monkeypatch.setattr(live_chart.alpaca, "fetch_bars", fail)
    out = live_chart.read("AAPL", now)
    assert out["bars"] == []
    assert "private" not in out["reason"]
    assert "unavailable" in out["reason"]
    source = {
        "bars": _bars(),
        "session": "2026-10-02",
        "as_of": now.isoformat(),
        "complete": False,
        "reason": None,
    }
    chart = ticker_chart_intraday.payload(
        MarketStore(tmp_path), tmp_path, "AAPL", 10, {}, source
    )
    assert chart["sessions"] == 1
    assert len(chart["bars"]) == 8
    assert chart["live_feed"] == "iex"
    assert not chart["last_bar_complete"]
    assert "raw IEX" in chart["basis"]
    assert chart["quote_bar"] == source["bars"][-1].start.isoformat()
    assert not list(tmp_path.rglob("*.parquet"))


# Non-session and pre-open reads do not call a provider or claim a live regular candle.
@pytest.mark.parametrize(
    "instant", ["2026-10-03T15:00:00+00:00", "2026-10-02T12:00:00+00:00"]
)
def test_no_session_provider_read(monkeypatch, instant):
    # Fail if a prohibited read reaches the provider.
    def forbidden(*args, **kwargs):
        pytest.fail("Provider called outside an opened exchange session")

    monkeypatch.setattr(live_chart.alpaca, "fetch_bars", forbidden)
    assert live_chart.read("AAPL", datetime.fromisoformat(instant))["bars"] == []


# Stop provider failures promptly instead of entering historical-fetch retries.
@pytest.mark.parametrize("failure", ["rate_limit", "network"])
def test_transport_failure_is_bounded_and_redacted(monkeypatch, failure):
    from types import SimpleNamespace

    from curl_cffi import requests

    # Exercise the actual transport with a deterministic provider refusal.
    def fetch(*args, **kwargs):
        assert kwargs["timeout"] == 10
        if failure == "network":
            raise requests.exceptions.RequestException("secret provider response")
        return SimpleNamespace(status_code=429, content=b"secret provider response")

    monkeypatch.setattr(requests, "get", fetch)
    with pytest.raises(RuntimeError, match="unavailable") as found:
        live_chart._transport("https://example.invalid", {})
    assert "secret" not in str(found.value)


# Malformed provider pagination cannot keep a chart request running indefinitely.
def test_provider_pagination_has_a_fixed_bound(monkeypatch):
    import json

    calls = []

    # Simulate a provider returning the same nonterminal token forever.
    def transport(*args):
        calls.append(1)
        return 200, json.dumps(
            {"bars": {"AAPL": []}, "next_page_token": "repeat"}
        ).encode()

    monkeypatch.setattr(live_chart, "_transport", transport)
    monkeypatch.setattr(live_chart.alpaca, "credentials", lambda: {"test": "test"})
    out = live_chart.read("AAPL", datetime.fromisoformat("2026-10-02T11:16:00-04:00"))
    assert len(calls) == 2
    assert out["bars"] == []
    assert "unavailable" in out["reason"]
