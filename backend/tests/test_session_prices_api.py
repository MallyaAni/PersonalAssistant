"""Check authorized HTTP display data without changing strategy or account state."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from curl_cffi import requests
from httpx import ASGITransport, AsyncClient

from backend.api.v1 import market
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app
from backend.market import session_price_snapshot, session_prices


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

    # Capture the route's read-only snapshot request without performing collection.
    def read(root, symbols):
        requested.append(symbols)
        return {
            "session": "overnight",
            "signal_scope": "regular-session",
            "quotes": {"AAOI": {"price": 101, "indicative": True}},
        }

    monkeypatch.setattr(session_price_snapshot, "read", read)
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


# Collect once, then serve the real persisted selection over HTTP without provider work.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stamp", "phase", "primary", "fallback"),
    [
        ("2026-09-24T07:00:00-04:00", "pre-market", "sip", "iex"),
        ("2026-09-24T12:00:00-04:00", "regular", "sip", "iex"),
        ("2026-09-24T18:00:00-04:00", "post-market", "sip", "iex"),
        ("2026-09-24T22:00:00-04:00", "overnight", "boats", "overnight"),
        ("2026-09-25T22:00:00-04:00", "closed", "boats", "overnight"),
        ("2039-01-03T22:00:00-05:00", "unknown", "boats", "overnight"),
    ],
)
async def test_session_prices_http_keeps_per_symbol_source_evidence(
    monkeypatch, tmp_path, stamp, phase, primary, fallback
):
    now = datetime.fromisoformat(stamp)
    session_prices._cache.clear()
    session_prices._denied_until.clear()
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        market.deskrecord,
        "latest_pair",
        lambda root: ({"grades": {"AAA": {}, "BBB": {}}}, None),
    )
    monkeypatch.setattr(session_prices.alpaca, "credentials", lambda: {})

    class DatedClock:
        # Give each response the same deterministic aware completion timestamp.
        @staticmethod
        def now(tz):
            return now.astimezone(tz)

        combine = staticmethod(datetime.combine)

    monkeypatch.setattr(session_prices, "datetime", DatedClock)
    monkeypatch.setattr(session_price_snapshot, "utc_now", lambda: now)
    calls = []

    # Supply only synthetic quotes while recording the real transport contract.
    def get(url, *, headers, timeout):
        address = urlsplit(url)
        assert address.netloc == "data.alpaca.markets"
        assert address.path == "/v2/stocks/quotes/latest"
        assert headers == {}
        assert timeout == 2
        query = parse_qs(address.query)
        feed = query["feed"][0]
        symbols = query["symbols"][0].split(",")
        calls.append((feed, symbols))
        quotes = {}
        for symbol in symbols:
            observed = (
                now - timedelta(seconds=61)
                if feed == primary and symbol == "BBB"
                else now - timedelta(seconds=1)
            )
            quotes[symbol] = {
                "t": observed.isoformat(),
                "bp": 100,
                "ap": 102,
                "bs": 10,
                "as": 20,
            }
        return SimpleNamespace(
            status_code=200, content=json.dumps({"quotes": quotes}).encode()
        )

    monkeypatch.setattr(requests, "get", get)
    outcome = session_price_snapshot.collect(
        tmp_path, ["AAA", "BBB"], clock=lambda: now
    )
    assert outcome["status"] == "collected"
    path = tmp_path / "desk/session-prices/latest.json"
    before = path.read_bytes()
    original = json.loads(before)["snapshot"]
    modified = path.stat().st_mtime_ns

    # Fail if any HTTP read attempts to fetch instead of reading collected evidence.
    def forbidden(*args, **kwargs):
        pytest.fail("HTTP snapshot reads must not call a provider")

    monkeypatch.setattr(requests, "get", forbidden)
    auth = {"Authorization": "Bearer " + issue_user_token("desk_user")}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/session-prices", headers=auth
        )
        repeated = await client.get(
            "/api/v1/market/desk_user/desk/session-prices", headers=auth
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    payload = response.json()
    assert repeated.json() == payload
    assert payload["as_of"] == original["as_of"]
    assert datetime.fromisoformat(payload["as_of"]) == now
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == modified
    assert payload["session"] == phase
    assert payload["signal_scope"] == "regular-session"
    assert calls == [(primary, ["AAA", "BBB"]), (fallback, ["BBB"])]
    for symbol, feed in (("AAA", primary), ("BBB", fallback)):
        row = payload["quotes"][symbol]
        assert row["feed"] == feed
        assert row["session"] == phase
        assert row["status"] == "fresh"
        assert row["price"] == 101
        assert row["indicative"] is (feed == "overnight")
        assert datetime.fromisoformat(row["at"]) == now - timedelta(seconds=1)
        assert "eligible" not in row


# Missing or corrupt evidence stays unavailable without provider calls or writes.
@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", [False, True])
async def test_unavailable_http_snapshot_never_fetches(tmp_path, monkeypatch, corrupt):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        market.deskrecord,
        "latest_pair",
        lambda root: ({"grades": {"AAA": {}}}, None),
    )
    path = tmp_path / "desk/session-prices/latest.json"
    if corrupt:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"invalid snapshot")
    before = sorted(str(item.relative_to(tmp_path)) for item in tmp_path.rglob("*"))

    # Any provider or writer attempt is a failure even when evidence cannot be read.
    def forbidden(*args, **kwargs):
        pytest.fail("GET must not collect or publish")

    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(session_price_snapshot, "collect", forbidden)
    auth = {"Authorization": "Bearer " + issue_user_token("desk_user")}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for _ in range(2):
            response = await client.get(
                "/api/v1/market/desk_user/desk/session-prices", headers=auth
            )
            assert response.status_code == 200
            assert response.json()["as_of"] is None
            assert response.json()["quotes"]["AAA"]["price"] is None
            assert response.json()["quotes"]["AAA"]["status"] == "unavailable"
    assert (
        sorted(str(item.relative_to(tmp_path)) for item in tmp_path.rglob("*"))
        == before
    )
    if corrupt:
        assert path.read_bytes() == b"invalid snapshot"
