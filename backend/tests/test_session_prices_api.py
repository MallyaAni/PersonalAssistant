"""Check authorized HTTP display data without changing strategy or account state."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.v1 import market
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app
from backend.market import session_prices


# A per-user read returns only covered symbols, and refuses the wrong account first.
@pytest.mark.asyncio
async def test_session_price_http_access(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    monkeypatch.setattr(
        market.deskrecord,
        "latest_pair",
        lambda root: ({"grades": {"AAOI": {}, "Q": {}}}, None),
    )
    requested = []

    # Capture the route's real covered universe without performing a provider call.
    def fetch(symbols):
        requested.append(symbols)
        return {
            "session": "overnight",
            "signal_scope": "regular-session",
            "quotes": {"AAOI": {"price": 101, "indicative": True}},
        }

    monkeypatch.setattr(session_prices, "fetch", fetch)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        path = "/api/v1/market/desk_user/desk/session-prices"
        assert (await client.get(path)).status_code == 401
        wrong = {"Authorization": "Bearer " + issue_user_token("other")}
        assert (await client.get(path, headers=wrong)).status_code == 403
        auth = {"Authorization": "Bearer " + issue_user_token("desk_user")}
        response = await client.get(path, headers=auth)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["quotes"]["AAOI"]["price"] == 101
    assert requested == [["AAOI", "Q"]]
