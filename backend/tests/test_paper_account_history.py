"""Paper account history reports observed balances without invented returns."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from backend.agents.trading.desk import paper
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app
from backend.market import paper_history


# Use the production state's shape without creating any orders.
def _save(root, rows):
    paper.save_state(root, paper.PaperState(history=rows, start_equity=100000))


# Deliberately misleading legacy P&L fields must never drive the projection.
def _row(session, equity, *, written=None):
    return {
        "session": session,
        "written": written or f"{session}T23:30:00+00:00",
        "equity": equity,
        "cash": 1500,
        # These legacy fields are deliberately wrong: never serialize them
        # as authenticated P&L or use them to calculate balance changes.
        "pl": 1234567,
        "pl_pct": 900,
    }


# Only observed account values and their explicitly unadjusted changes are shown.
def test_history_is_actual_recorded_value_not_return_or_backtest(tmp_path):
    _save(tmp_path, [_row("2026-09-28", 100000), _row("2026-09-29", 99000)])
    path = paper.state_path(tmp_path)
    original = path.read_bytes()
    result = paper_history.load(tmp_path)
    assert path.read_bytes() == original  # read-only
    assert result["source"] == "paper_account_records"
    assert result["cash_flow_adjusted"] is False
    assert result["closing_values_verified"] is False
    assert result["policy_attribution_available"] is False
    first, second = result["rows"]
    assert first["equity_change"] is None
    assert first["equity_change_pct"] is None
    assert first["previous_session"] is None
    assert second == {
        "session": "2026-09-29",
        "recorded_at": "2026-09-29T23:30:00+00:00",
        "chronology_verified": True,
        "equity": 99000,
        "cash": 1500,
        "equity_change": -1000,
        "equity_change_pct": -0.01,
        "previous_session": "2026-09-28",
        "missing_sessions": 0,
    }


# A skipped trading session is a gap; a market holiday is not a missing record.
def test_holiday_weekend_is_not_missing_but_unrecorded_session_is(tmp_path):
    _save(
        tmp_path,
        [
            _row("2026-09-04", 100000),  # Friday before Labor Day
            _row("2026-09-08", 101000),  # Tuesday, next exchange session
            _row("2026-09-10", 103000),  # Wednesday record absent
        ],
    )
    rows = paper_history.load(tmp_path)["rows"]
    assert [row["session"] for row in rows] == [
        "2026-09-04",
        "2026-09-08",
        "2026-09-10",
    ]
    assert rows[1]["missing_sessions"] == 0
    assert rows[2]["missing_sessions"] == 1
    assert rows[2]["previous_session"] == "2026-09-08"
    assert rows[2]["equity_change"] == 2000  # interval change, not daily P&L


# Invalid marks neither become zero nor allow a later value to bridge the gap.
@pytest.mark.parametrize(
    "bad", [None, "100000", True, float("nan"), float("inf"), 10**400]
)
def test_invalid_mark_is_null_and_never_bridged(tmp_path, bad):
    _save(
        tmp_path,
        [
            _row("2026-09-25", 100000),
            _row("2026-09-28", bad),
            _row("2026-09-29", 101000),
        ],
    )
    rows = paper_history.load(tmp_path)["rows"]
    assert rows[1]["equity"] is None
    assert rows[1]["equity_change"] is None
    assert rows[2]["equity_change"] is None
    assert rows[2]["equity_change_pct"] is None
    json.dumps(rows, allow_nan=False)


# Percentage changes require a positive prior balance.
@pytest.mark.parametrize("base", [0, -100])
def test_nonpositive_base_has_no_percentage_return(tmp_path, base):
    _save(tmp_path, [_row("2026-09-28", base), _row("2026-09-29", 100)])
    row = paper_history.load(tmp_path)["rows"][1]
    assert row["equity_change"] == 100 - base
    assert row["equity_change_pct"] is None


# Pagination retains the real predecessor rather than re-basing a partial window.
def test_duplicate_order_and_limit_keep_actual_prior_comparison(tmp_path):
    _save(
        tmp_path,
        [
            _row("2026-09-29", 200000),
            _row("2026-09-28", 100000),
            _row("2026-09-29", 101000),
            {"session": "not-a-date", "equity": 999999},
            {"session": "20260930", "equity": 999999},
            None,
        ],
    )
    result = paper_history.load(tmp_path, limit=1)
    assert result["total_records"] == 2
    assert result["ignored_records"] == 3
    assert result["truncated"] is True
    assert result["first_session"] == "2026-09-28"
    assert result["last_session"] == "2026-09-29"
    assert len(result["rows"]) == 1
    assert result["rows"][0]["equity"] == 101000
    assert result["rows"][0]["equity_change"] == 1000


# Never assume a timezone or fabricate a recording time from a strategy session.
@pytest.mark.parametrize("written", ["invalid", "2026-09-29", "2026-09-29T19:30:00"])
def test_missing_timestamp_is_not_invented_from_session(tmp_path, written):
    _save(tmp_path, [_row("2026-09-29", 100000, written=written)])
    assert paper_history.load(tmp_path)["rows"][0]["recorded_at"] is None


# Empty history is absence of evidence, not a zero-return account.
def test_no_records_is_empty_not_flat_performance(tmp_path):
    result = paper_history.load(tmp_path)
    assert result["rows"] == []
    assert result["total_records"] == 0
    assert result["first_session"] is None
    assert result["last_session"] is None


# Unknown calendar coverage cannot certify a consecutive-session change.
def test_unreviewed_calendar_does_not_claim_contiguous_daily_values(tmp_path):
    _save(tmp_path, [_row("2100-01-04", 100000), _row("2100-01-05", 101000)])
    assert paper_history.load(tmp_path)["rows"][1]["missing_sessions"] is None


# Account history is private and cannot submit orders or depend on live keys.
@pytest.mark.asyncio
async def test_history_endpoint_is_private_read_only_and_requires_no_broker(
    tmp_path, monkeypatch
):
    from backend.market import alpaca_trading

    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")

    def forbidden_broker_call():
        pytest.fail("History must not place orders or require a broker refresh")

    monkeypatch.setattr(alpaca_trading, "client_from_env", forbidden_broker_call)
    _save(tmp_path, [_row("2026-09-28", 100000), _row("2026-09-29", 101000)])
    owner = issue_user_token("desk_user", scopes=["memory:read"])
    outsider = issue_user_token("outsider", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/paper/history?limit=1",
            headers={"Authorization": f"Bearer {owner}"},
        )
        refused = await client.get(
            "/api/v1/market/outsider/desk/paper/history",
            headers={"Authorization": f"Bearer {outsider}"},
        )
        bad_limit = await client.get(
            "/api/v1/market/desk_user/desk/paper/history?limit=0",
            headers={"Authorization": f"Bearer {owner}"},
        )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["rows"][0]["equity"] == 101000
    assert refused.status_code == 403
    assert bad_limit.status_code == 422


# Corruption is reported without regenerating records or mutating the source.
@pytest.mark.asyncio
async def test_corrupt_state_has_no_fabricated_history(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    path = paper.state_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{broken")
    token = issue_user_token("desk_user", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/market/desk_user/desk/paper/history",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json()["rows"] == []
    assert response.json()["reason"] == "Account history unavailable"
    assert path.read_text() == "{broken"


# Late reruns can reorder recording times without changing their session labels.
@pytest.mark.parametrize(
    ("written", "verified"),
    [
        ("2026-09-29T09:00:00+00:00", False),
        ("2026-09-29T10:00:00+00:00", False),
        ("invalid", None),
    ],
)
def test_nonchronological_recordings_do_not_create_period_changes(
    tmp_path, written, verified
):
    _save(
        tmp_path,
        [
            _row("2026-09-28", 100000, written="2026-09-29T10:00:00+00:00"),
            _row("2026-09-29", 101000, written=written),
        ],
    )
    row = paper_history.load(tmp_path)["rows"][1]
    assert row["equity"] == 101000
    assert row["chronology_verified"] is verified
    assert row["equity_change"] is None
    assert row["equity_change_pct"] is None
