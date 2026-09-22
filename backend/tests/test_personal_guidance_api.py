"""Exercise personal account isolation through the authenticated HTTP route."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.v1 import market
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app
from backend.market import desk_freshness, event_status, execution_quotes, holdings
from backend.tests.test_decision_view import setup


# Supply dated market evidence and isolated personal holdings without provider calls.
@pytest.fixture
def personal_context(tmp_path, monkeypatch):
    record, snapshot, quoted, now = setup()
    record["written"] = record["session"]
    snapshot["quotes"]["S11"]["last"] = 100.0
    record["paper"] = {
        "equity": 100000.0,
        "cash": 100000.0,
        "positions": [],
        "until_rebalance": 0,
    }

    class Clock(datetime):
        # Keep signal, bar and quote evidence at the same decision instant.
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(market, "datetime", Clock)
    monkeypatch.setattr(desk_freshness, "datetime", Clock)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(market.deskrecord, "latest_pair", lambda root: (record, None))
    monkeypatch.setattr(market, "_live_snapshot", lambda: snapshot)
    monkeypatch.setattr(event_status, "for_planning", lambda record, root: record)
    monkeypatch.setattr(execution_quotes, "fetch", lambda names: quoted)
    monkeypatch.setattr(
        market.live_technical,
        "entry_now",
        lambda *args: {"S11": {"band_z": 1.5}},
    )
    holdings.save(tmp_path, [holdings.Holding("S11", 60, 100, record["session"])])
    token = issue_user_token("desk_user", scopes=["memory:read"])
    return record, quoted, now, tmp_path, {"Authorization": f"Bearer {token}"}


# Paper fills, cash and rebalance timing cannot change personal recommendation rows.
@pytest.mark.asyncio
async def test_personal_http_decisions_ignore_paper_account_changes(personal_context):
    record, _, _, root, auth = personal_context
    before_holdings = holdings.holdings_path(root).read_bytes()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=auth
    ) as client:
        first = await client.get(
            "/api/v1/market/desk_user/desk/mine", params={"equity": 100000}
        )
        record["paper"] = {
            "equity": 100000.0,
            "cash": 50000.0,
            "positions": [{"symbol": "S11", "qty": 500.0, "market_value": 50000.0}],
            "until_rebalance": 40,
        }
        second = await client.get(
            "/api/v1/market/desk_user/desk/mine", params={"equity": 100000}
        )
    assert first.status_code == second.status_code == 200
    first_rows = first.json()["decisions"]["rows"]
    second_rows = second.json()["decisions"]["rows"]
    assert first_rows["S11"]["current_weight"] == pytest.approx(0.06)
    assert second_rows == first_rows
    assert holdings.holdings_path(root).read_bytes() == before_holdings


# Explicit personal cash is forwarded as one budget and never persisted by a read.
@pytest.mark.asyncio
@pytest.mark.parametrize("cash", [0.0, 1000.0])
async def test_personal_http_uses_explicit_cash_budget(personal_context, cash):
    record, _, _, root, auth = personal_context
    before_record = deepcopy(record)
    before_holdings = holdings.holdings_path(root).read_bytes()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=auth
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/mine",
            params={"equity": 100000, "available_cash": cash},
        )
    assert response.status_code == 200, response.text
    rows = response.json()["decisions"]["rows"]
    total_buys = sum(
        row["move_weight"] * 100000 for row in rows.values() if row["action"] == "Buy"
    )
    assert total_buys == pytest.approx(cash)
    assert rows["S11"]["action"] == ("Buy" if cash else "Hold")
    assert record == before_record
    assert holdings.holdings_path(root).read_bytes() == before_holdings


# Unknown personal cash cannot become a funded buy from the paper account's cash.
@pytest.mark.asyncio
async def test_personal_http_unknown_cash_does_not_claim_a_funded_buy(personal_context):
    _, _, _, _, auth = personal_context
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=auth
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/mine", params={"equity": 100000}
        )
    assert response.status_code == 200
    row = response.json()["decisions"]["rows"]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["action"] == "Hold"
    assert not row["move_weight"]
    assert row["executable"] is False


# Invalid account input is rejected before collecting any market evidence.
@pytest.mark.asyncio
@pytest.mark.parametrize("cash", ["nan", "inf", "-inf", "-1", "100001"])
async def test_personal_http_rejects_invalid_cash(personal_context, monkeypatch, cash):
    _, _, _, root, auth = personal_context
    before_holdings = holdings.holdings_path(root).read_bytes()

    # Invalid request inputs must never cross the external quote boundary.
    def unexpected_fetch(*args, **kwargs):
        pytest.fail("Invalid cash reached market evidence collection")

    monkeypatch.setattr(execution_quotes, "fetch", unexpected_fetch)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=auth
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/mine",
            params={"equity": 100000, "available_cash": cash},
        )
    assert response.status_code == 422
    assert holdings.holdings_path(root).read_bytes() == before_holdings


# A stale executable quote cannot advertise an immediate personal buy.
@pytest.mark.asyncio
async def test_stale_quote_blocks_personal_http_buy(personal_context):
    record, quoted, now, _, auth = personal_context
    before_record = deepcopy(record)
    quoted["quotes"]["S11"]["t"] = (now - timedelta(seconds=31)).isoformat()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=auth
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/mine",
            params={"equity": 100000, "available_cash": 1000},
        )
    assert response.status_code == 200
    row = response.json()["decisions"]["rows"]["S11"]
    assert row["quote"]["eligible"] is False
    assert row["action"] == "Hold"
    assert not row["move_weight"]
    assert record == before_record


# The personal route continues to enforce operator ownership.
@pytest.mark.asyncio
async def test_personal_http_rejects_another_account(personal_context):
    _, _, _, root, _ = personal_context
    before_holdings = holdings.holdings_path(root).read_bytes()
    token = issue_user_token("someone_else", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/mine", params={"equity": 100000}
        )
    assert response.status_code == 403
    assert holdings.holdings_path(root).read_bytes() == before_holdings
