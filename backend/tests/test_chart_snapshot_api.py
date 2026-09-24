"""The authenticated chart route must retain its indicator source observation."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.v1 import market
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app
from backend.tests.test_market_ticker_chart import _store


# Exercise the route and chart builder with one quote and no provider calls.
@pytest.mark.asyncio
@pytest.mark.parametrize("timeframe", ["daily", "weekly"])
async def test_chart_http_preserves_coherent_quote_snapshot(monkeypatch, timeframe):
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "chart_user")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(market, "MarketStore", lambda root: _store([100.0] * 320))
    monkeypatch.setattr(market, "_live_snapshot", lambda: {"quotes": {"AAA": {
        "last": 150.0, "open": 100.0, "high": 151.0, "low": 99.0,
        "bar": "2026-09-24T14:00:00+00:00",
    }}})
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
    assert chart["quote_bar"] == "2026-09-24T14:00:00+00:00"
    assert chart["bars"][-1]["close"] == 150.0
    assert chart["overlays"]["ema9"][-1] == pytest.approx(110.0)
    assert chart["last_bar_complete"] is False
    assert all(len(line) == len(chart["bars"]) for line in chart["levels"].values())
