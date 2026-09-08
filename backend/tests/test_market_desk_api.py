"""The desk endpoint: the day's record and its changes reach the page, and
only for the user whose token asks."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app


def _write(root, session, grades, book, flags):
    path = root / "desk" / f"asof={session}" / "desk.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "session": session,
                "regime": {
                    "flags": flags,
                    "selection_confidence": 0.5,
                    "exposure": 1.0,
                },
                "grades": {t: {"grade": g} for t, g in grades.items()},
                "book": [{"ticker": t, "weight": w} for t, w in book],
                "briefs": {},
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_the_endpoint_returns_the_record_and_the_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(tmp_path, "2026-09-03", {"SNDK": "A", "MU": "A+"}, [("MU", 0.07)], [])
    _write(tmp_path, "2026-09-04", {"SNDK": "A+", "MU": "B"}, [("SNDK", 0.08)], ["x"])
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
        earlier = await client.get(
            "/api/v1/market/desk_user/desk/2026-09-03",
            headers={"Authorization": f"Bearer {token}"},
        )
        missing = await client.get(
            "/api/v1/market/desk_user/desk/2020-01-01",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["latest"]["session"] == "2026-09-04"
    assert payload["summary"]["counts"] == {"A+": 1, "A": 0, "B": 1, "C": 0}
    assert payload["changes"]["since"] == "2026-09-03"
    assert payload["changes"]["upgrades"] == [
        {"ticker": "SNDK", "from": "A", "to": "A+"}
    ]
    assert {o["ticker"]: o["action"] for o in payload["changes"]["orders"]} == {
        "MU": "sell",
        "SNDK": "buy",
    }
    assert payload["changes"]["flags_raised"] == ["x"]
    assert payload["sessions"] == ["2026-09-03", "2026-09-04"]
    assert earlier.status_code == 200
    assert earlier.json()["record"]["session"] == "2026-09-03"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_no_record_is_an_empty_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json() == {"user_id": "desk_user", "latest": None, "sessions": []}


@pytest.mark.asyncio
async def test_another_users_token_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    token = issue_user_token("someone_else", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code in (401, 403), response.text


@pytest.mark.asyncio
async def test_a_user_who_is_not_the_operator_is_refused_with_their_own_token(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
    _write(tmp_path, "2026-09-04", {"SNDK": "A+"}, [("SNDK", 0.08)], [])
    token = issue_user_token("someone_else", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/someone_else/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403, response.text


# The person's own positions round-trip through the API, a bad row is
# refused whole, and the board against them says what to do with each
# name held or targeted, the name the desk does not rate included.
@pytest.mark.asyncio
async def test_holdings_are_saved_and_the_board_is_computed_against_them(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(tmp_path, "2026-09-04", {"SNDK": "A+", "MU": "B"}, [("SNDK", 0.08)], [])
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    auth = {"Authorization": f"Bearer {token}"}
    rows = [
        {
            "ticker": "mu",
            "shares": 10,
            "entry_price": 100.0,
            "entry_date": "2026-09-01",
        },
        {
            "ticker": "IREN",
            "shares": 100,
            "entry_price": 35.0,
            "entry_date": "2026-08-28",
        },
    ]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        before = await client.get(
            "/api/v1/market/desk_user/desk/holdings", headers=auth
        )
        saved = await client.put(
            "/api/v1/market/desk_user/desk/holdings", json=rows, headers=auth
        )
        bad = await client.put(
            "/api/v1/market/desk_user/desk/holdings",
            json=[{"ticker": "MU", "shares": 0, "entry_price": 1, "entry_date": "x"}],
            headers=auth,
        )
        mine = await client.get(
            "/api/v1/market/desk_user/desk/mine", params={"equity": 10000}, headers=auth
        )
    assert before.json()["holdings"] == []
    assert [h["ticker"] for h in saved.json()["holdings"]] == ["MU", "IREN"]
    assert bad.status_code == 422
    assert "positive" in bad.json()["detail"]
    board = {r["ticker"]: r for r in mine.json()["rows"]}
    assert mine.json()["session"] == "2026-09-04"
    assert board["SNDK"]["action"] == "buy"
    assert board["MU"]["action"] == "sell"
    assert board["MU"]["grade"] == "B"
    assert board["IREN"]["action"] == "sell"
    assert not board["IREN"]["in_book"]
    assert board["IREN"]["shares"] == 100


# The practice account's live state comes from the broker, and a missing
# key is an answer with a reason, not an error.
@pytest.mark.asyncio
async def test_the_paper_account_is_read_live(tmp_path, monkeypatch):
    from backend.market import alpaca_trading

    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")

    class Fake:
        def account(self):
            return alpaca_trading.Account(101000.0, 5000.0, 5000.0, 100000.0)

        def positions(self):
            return [alpaca_trading.Position("ADBE", 42.0, 12600.0, 290.0, 300.0, 420.0)]

        def open_orders(self):
            return [{"symbol": "HPE", "side": "buy", "qty": "201", "status": "new"}]

    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: Fake())
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    auth = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        live = await client.get("/api/v1/market/desk_user/desk/paper", headers=auth)
        monkeypatch.setattr(
            alpaca_trading,
            "client_from_env",
            lambda: (_ for _ in ()).throw(alpaca_trading.AlpacaTradingError("no key")),
        )
        missing = await client.get("/api/v1/market/desk_user/desk/paper", headers=auth)
    body = live.json()
    assert body["equity"] == 101000.0
    assert body["day_pl"] == 1000.0
    assert body["positions"][0]["symbol"] == "ADBE"
    assert body["orders"] == [
        {"symbol": "HPE", "side": "buy", "qty": 201.0, "status": "new"}
    ]
    assert missing.json()["reason"] == "no key"
