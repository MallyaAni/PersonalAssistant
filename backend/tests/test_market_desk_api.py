"""The desk endpoint: the day's record and its changes reach the page, and
only for the user whose token asks."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app


def _write(root, session, grades, book, flags, curve=None):
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
                "curve": curve,
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


# An account named in MARKET_DESK_USERS opens the desk like the primary
# operator; a user outside both still cannot.
@pytest.mark.asyncio
async def test_a_named_extra_user_opens_the_desk(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
    monkeypatch.setattr(settings, "MARKET_DESK_USERS", "vjmallya, guest")
    _write(tmp_path, "2026-09-04", {"SNDK": "A+"}, [("SNDK", 0.08)], [])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        allowed = await client.get(
            "/api/v1/market/vjmallya/desk",
            headers={
                "Authorization": f"Bearer {issue_user_token('vjmallya', ttl_seconds=60)}"
            },
        )
        refused = await client.get(
            "/api/v1/market/stranger/desk",
            headers={
                "Authorization": f"Bearer {issue_user_token('stranger', ttl_seconds=60)}"
            },
        )
    assert allowed.status_code == 200, allowed.text
    assert refused.status_code == 403, refused.text


def test_market_desk_operators_parse_the_allowlist(monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
    monkeypatch.setattr(settings, "MARKET_DESK_USERS", " vjmallya, ,guest")
    assert settings.market_desk_operators == frozenset(
        {"ani.mallya", "vjmallya", "guest"}
    )


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


# The record's track-record curve reaches the desk endpoint, and a record
# written before the curve existed answers without one.
@pytest.mark.asyncio
async def test_the_desk_returns_the_track_record_curve(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(
        tmp_path,
        "2026-09-04",
        {"SNDK": "A+"},
        [("SNDK", 0.08)],
        [],
        curve={"backtest": {"dates": ["2026-09-03"], "rules": [0.0]}, "paper": None},
    )
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json()["curve"]["backtest"]["rules"] == [0.0]
    assert response.json()["latest"]["curve"]["backtest"]["dates"] == ["2026-09-03"]


# The drill-down reads the nightly history file for one name, and refuses a
# stranger the same way every other desk route does.
@pytest.mark.asyncio
async def test_the_history_endpoint_reads_the_nightly_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "SNDK.json").write_text(
        json.dumps(
            {
                "ticker": "SNDK",
                "asof": "2026-09-04",
                "horizon": 20,
                "rows": [{"date": "2026-09-03", "grade": "A+", "votes": 2.0}],
                "backtest": {"rule_return": 0.05},
            }
        ),
        encoding="utf-8",
    )
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    auth = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        found = await client.get(
            "/api/v1/market/desk_user/desk/history/SNDK", headers=auth
        )
        lower = await client.get(
            "/api/v1/market/desk_user/desk/history/sndk", headers=auth
        )
        missing = await client.get(
            "/api/v1/market/desk_user/desk/history/NVDA", headers=auth
        )
    assert found.status_code == 200
    assert found.json()["ticker"] == "SNDK"
    assert found.json()["rows"][0]["grade"] == "A+"
    assert lower.json()["ticker"] == "SNDK"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_the_history_endpoint_refuses_a_stranger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
    token = issue_user_token("someone_else", ttl_seconds=60, scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/someone_else/desk/history/SNDK",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403, response.text


# The persisted intraday plan reaches the page as the balancer wrote it, and
# a desk with no plan yet answers 404 rather than inventing one.
@pytest.mark.asyncio
async def test_the_intraday_plan_is_read_back(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    plan = tmp_path / "desk" / "intraday.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        json.dumps(
            {
                "as_of": "2026-09-09T13:32:29+00:00",
                "session": "2026-09-08",
                "top_buys": [
                    {
                        "ticker": "SNDK",
                        "grade_live": "A+",
                        "target_weight": 0.04,
                        "leaves_if": "a buy only while it holds an A grade",
                    }
                ],
                "changed": ["first plan of the session"],
            }
        ),
        encoding="utf-8",
    )
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    auth = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        found = await client.get("/api/v1/market/desk_user/desk/intraday", headers=auth)
        # A desk with no plan: the root has no intraday.json yet.
        (plan.parent / "intraday.json").unlink()
        missing = await client.get(
            "/api/v1/market/desk_user/desk/intraday", headers=auth
        )
        # A stranger is refused before the file is read.
        monkeypatch.setattr(settings, "MARKET_DESK_USER", "ani.mallya")
        stranger_token = issue_user_token(
            "someone_else", ttl_seconds=60, scopes=["memory:read"]
        )
        refused = await client.get(
            "/api/v1/market/someone_else/desk/intraday",
            headers={"Authorization": f"Bearer {stranger_token}"},
        )
    body = found.json()
    assert found.status_code == 200
    assert body["session"] == "2026-09-08"
    assert body["top_buys"][0]["ticker"] == "SNDK"
    assert body["top_buys"][0]["leaves_if"].startswith("a buy only")
    assert missing.status_code == 404
    assert refused.status_code == 403


# The autopsy reads the caller's own trading passages and returns the model's
# three sections, and answers with a plain reason when there is nothing to read.
@pytest.mark.asyncio
async def test_the_autopsy_reads_the_persons_own_documents(tmp_path, monkeypatch):
    from backend.api.v1 import market as market_api
    from backend.core.dependencies import get_agent_memory_manager

    payload = {
        "patterns": [{"behaviour": "cut winners early", "evidence": "twice"}],
        "costs": [
            {
                "what": "left on the table",
                "amount": "not stated",
                "source": "journal",
            }
        ],
        "plan": {"stop": ["hold winners"], "start": [], "keep": ["journaled"]},
        "unknowns": [],
    }

    class FakeWriter:
        def chat(
            self, messages, max_tokens=1024, response_schema=None, temperature=None
        ):
            return {"content": json.dumps(payload)}

    class FakeManager:
        async def search(self, user_id, query, top_k):
            return [
                {
                    "content": "bought at 40, sold at 32",
                    "document": {"title": "journal"},
                }
            ]

    app.dependency_overrides[get_agent_memory_manager] = lambda: FakeManager()
    monkeypatch.setattr(market_api, "get_structured_llm_client", lambda: FakeWriter())
    try:
        token = issue_user_token("trader", ttl_seconds=60, scopes=["memory:read"])
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/market/trader/trading/autopsy",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_agent_memory_manager, None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["patterns"][0]["behaviour"] == "cut winners early"
    assert body["result"]["costs"][0]["amount"] == "not stated"
    assert body["sources"] == ["journal"]
    assert body["passages_used"] == 1


@pytest.mark.asyncio
async def test_the_autopsy_without_documents_explains_why(tmp_path, monkeypatch):
    from backend.core.dependencies import get_agent_memory_manager

    class EmptyManager:
        async def search(self, user_id, query, top_k):
            return []

    app.dependency_overrides[get_agent_memory_manager] = lambda: EmptyManager()
    try:
        token = issue_user_token("trader", ttl_seconds=60, scopes=["memory:read"])
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/api/v1/market/trader/trading/autopsy",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_agent_memory_manager, None)
    assert response.status_code == 200
    body = response.json()
    assert body["result"] is None
    assert "No trading documents" in body["reason"]


# The live endpoints serve the candle the balancer persisted, without a quote
# fetch or an analyst run of their own: /desk/live returns the snapshot, and
# /desk/mine builds its board from the snapshot's quotes and technical read.
@pytest.mark.asyncio
async def test_the_live_endpoints_serve_the_persisted_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    _write(tmp_path, "2026-09-04", {"SNDK": "A+", "MU": "B"}, [("SNDK", 0.08)], [])
    # The live grade re-read needs a technical stance on each name.
    record_path = tmp_path / "desk" / "asof=2026-09-04" / "desk.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    for grade in record["grades"].values():
        grade["stances"] = {"technical": 1}
    record_path.write_text(json.dumps(record), encoding="utf-8")
    desk = tmp_path / "desk"
    desk.mkdir(parents=True, exist_ok=True)
    (desk / "live.json").write_text(
        json.dumps(
            {
                "as_of": "2026-09-04T12:00:00+00:00",
                "quotes": {"SNDK": {"last": 120.0}, "MU": {"last": 45.0}},
                "technical": {"SNDK": {"now": 0.81, "close": 0.7}},
                "technical_detail": {"SNDK": {"now": 0.81}},
            }
        ),
        encoding="utf-8",
    )
    token = issue_user_token("desk_user", ttl_seconds=60, scopes=["memory:read"])
    auth = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        live = await client.get("/api/v1/market/desk_user/desk/live", headers=auth)
        mine = await client.get(
            "/api/v1/market/desk_user/desk/mine", params={"equity": 10000}, headers=auth
        )
    assert live.status_code == 200
    body = live.json()
    assert body["as_of"] == "2026-09-04T12:00:00+00:00"
    assert body["quotes"] == {"SNDK": {"last": 120.0}, "MU": {"last": 45.0}}
    assert body["technical"]["SNDK"]["now"] == 0.81
    assert body["technical_detail"] == {"SNDK": {"now": 0.81}}
    board = {r["ticker"]: r for r in mine.json()["rows"]}
    assert board["SNDK"]["technical_now"] == 0.81
    assert board["SNDK"]["last"] == 120.0
