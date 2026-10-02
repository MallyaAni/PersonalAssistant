"""The authenticated chart route must retain its indicator source observation."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.v1 import market
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app
from backend.tests.test_market_ticker_chart import _Store, _store


# Freeze the route's evidence clock without changing token or database clocks.
def _freeze_clock(monkeypatch, now):
    # Return the supplied aware instant when the market route asks for its clock.
    class Clock(datetime):
        # Keep timestamp comparisons deterministic for chart evidence.
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(market, "datetime", Clock)


# Retain the flat-price control while moving its sessions into the live calendar.
def _current_store(factor=1.0, include_current=False):
    store = _store([100.0] * (321 if include_current else 320), factor=factor)
    shift = date(2026, 9, 18) - date(2025, 3, 21)
    return _Store(
        tuple(
            replace(bar, session_date=bar.session_date + shift) for bar in store._bars
        )
    )


# Exercise the route and chart builder with one quote and no provider calls.
@pytest.mark.asyncio
@pytest.mark.parametrize("timeframe", ["daily", "weekly"])
async def test_chart_http_preserves_coherent_quote_snapshot(monkeypatch, timeframe):
    now = datetime(2026, 9, 21, 14, 16, tzinfo=UTC)
    _freeze_clock(monkeypatch, now)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "chart_user")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(market, "MarketStore", lambda root: _current_store())
    monkeypatch.setattr(
        market,
        "_live_snapshot",
        lambda: {
            "as_of": now.isoformat(),
            "quotes": {
                "AAA": {
                    "last": 150.0,
                    "open": 100.0,
                    "high": 151.0,
                    "low": 99.0,
                    "bar": "2026-09-21T14:00:00+00:00",
                }
            },
        },
    )
    auth = {"Authorization": f"Bearer {issue_user_token('chart_user')}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=auth
    ) as client:
        response = await client.get(
            "/api/v1/market/chart_user/desk/chart/AAA",
            params={"timeframe": timeframe},
        )
    assert response.status_code == 200, response.text
    chart = response.json()
    assert chart["quote_bar"] == "2026-09-21T14:00:00+00:00"
    assert chart["bars"][-1]["close"] == 150.0
    assert chart["overlays"]["ema9"][-1] == pytest.approx(110.0)
    assert chart["last_bar_complete"] is False
    assert all(len(line) == len(chart["bars"]) for line in chart["levels"].values())


# Invalid retained snapshots cannot replace stored prices or append a new session.
@pytest.mark.asyncio
@pytest.mark.parametrize("timeframe", ["daily", "weekly"])
@pytest.mark.parametrize(
    ("clock", "snapshot_change", "quote_change"),
    [
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {"as_of": "2026-09-21T14:00:00+00:00"},
            {},
            id="stale_snapshot",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {"as_of": "2026-09-21T14:16:01+00:00"},
            {},
            id="future_snapshot",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {"as_of": "2026-09-21T14:16:00"},
            {},
            id="naive_snapshot",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00", {"as_of": None}, {}, id="missing_snapshot"
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {},
            {"bar": "2026-09-21T13:45:00+00:00"},
            id="stale_quote",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {},
            {"bar": "2026-09-21T14:30:00+00:00"},
            id="future_quote",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {},
            {"bar": "2026-09-21T14:00:00"},
            id="naive_quote",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00", {}, {"bar": "unknown"}, id="malformed_quote"
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {},
            {"bar": "2026-09-18T19:45:00+00:00"},
            id="wrong_session",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {},
            {"bar": "2026-09-21T14:15:00+00:00"},
            id="incomplete_quote",
        ),
        pytest.param(
            "2026-09-21T13:31:00+00:00",
            {},
            {"bar": "2026-09-21T13:15:00+00:00"},
            id="before_open",
        ),
        pytest.param(
            "2026-11-27T18:16:00+00:00",
            {},
            {"bar": "2026-11-27T18:00:00+00:00"},
            id="after_early_close",
        ),
        pytest.param(
            "2026-09-20T14:16:00+00:00",
            {},
            {"bar": "2026-09-20T14:00:00+00:00"},
            id="closed_session",
        ),
        pytest.param(
            "2030-09-23T14:16:00+00:00",
            {},
            {"bar": "2030-09-23T14:00:00+00:00"},
            id="unknown_calendar",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00", {}, {"last": "unknown"}, id="invalid_price"
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00", {}, {"low": None}, id="missing_price"
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00", {}, {"high": 120.0}, id="invalid_ohlc"
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {},
            {"bar": "2026-09-21T14:00:01+00:00"},
            id="misaligned_quote",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {"as_of": "2026-09-21T14:14:00+00:00"},
            {},
            id="snapshot_before_completed_bar",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {},
            {"as_of": "2026-09-21T14:17:00+00:00"},
            id="receipt_after_snapshot",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {},
            {"as_of": "2026-09-21T14:14:00+00:00"},
            id="receipt_before_completion",
        ),
        pytest.param(
            "2026-09-21T14:16:00+00:00",
            {},
            {"as_of": "2026-09-21T14:16:00"},
            id="naive_receipt",
        ),
    ],
)
async def test_chart_http_rejects_unusable_quote_evidence(
    monkeypatch, timeframe, clock, snapshot_change, quote_change
):
    now = datetime.fromisoformat(clock)
    quote = {
        "last": 150.0,
        "open": 100.0,
        "high": 151.0,
        "low": 99.0,
        "bar": "2026-09-21T14:00:00+00:00",
    }
    quote.update(quote_change)
    snapshot = {"as_of": now.isoformat(), "quotes": {"AAA": quote}, **snapshot_change}
    _freeze_clock(monkeypatch, now)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "chart_user")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    store = _current_store()
    monkeypatch.setattr(market, "MarketStore", lambda root: store)
    monkeypatch.setattr(market, "_live_snapshot", lambda: snapshot)
    auth = {"Authorization": f"Bearer {issue_user_token('chart_user')}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=auth
    ) as client:
        response = await client.get(
            "/api/v1/market/chart_user/desk/chart/AAA", params={"timeframe": timeframe}
        )
    assert response.status_code == 200, response.text
    chart = response.json()
    assert chart["quote_bar"] is None
    assert chart["bars"][-1]["date"] == store.read("AAA").complete_through.isoformat()
    assert chart["bars"][-1]["close"] == 100.0
    assert chart["overlays"]["ema9"][-1] == pytest.approx(100.0)


# Even a valid fresh same-day quote cannot overwrite the store's completed candle.
@pytest.mark.asyncio
@pytest.mark.parametrize("timeframe", ["daily", "weekly"])
async def test_chart_http_preserves_completed_store_candle(monkeypatch, timeframe):
    now = datetime(2026, 9, 21, 14, 16, tzinfo=UTC)
    _freeze_clock(monkeypatch, now)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "chart_user")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    store = _current_store(factor=0.5, include_current=True)
    monkeypatch.setattr(market, "MarketStore", lambda root: store)
    snapshot = {
        "as_of": now.isoformat(),
        "quotes": {
            "AAA": {
                "last": 150.0,
                "open": 100.0,
                "high": 151.0,
                "low": 99.0,
                "bar": "2026-09-21T14:00:00+00:00",
            }
        },
    }
    monkeypatch.setattr(market, "_live_snapshot", lambda: snapshot)
    auth = {"Authorization": f"Bearer {issue_user_token('chart_user')}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=auth
    ) as client:
        response = await client.get(
            "/api/v1/market/chart_user/desk/chart/AAA", params={"timeframe": timeframe}
        )
    assert response.status_code == 200, response.text
    from backend.market import ticker_chart

    expected = ticker_chart.payload(store, "AAA", timeframe=timeframe)
    chart = response.json()
    chart.pop("user_id")
    assert chart == expected
