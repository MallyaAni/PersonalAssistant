"""Personal intent and funding must consume the same current grade."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.v1 import market
from backend.main import app
from backend.market import decision_view, holdings
from backend.tests.test_decision_view import setup
from backend.tests.test_personal_guidance_api import (
    personal_context as personal_context,
)
from backend.tests.test_personal_guidance_api import post_auth


# A live downgrade must not be hidden by a Buy opinion taken from last night's grade.
@pytest.mark.parametrize("cash", [None, 0.0, 1000.0])
def test_current_downgrade_preserves_the_covered_exit(cash):
    record, snapshot, quoted, now = setup()
    record["grades"]["S11"]["grade"] = "A+"
    record["grades"]["S11"]["stances"] = {
        "fundamental": 1,
        "technical": 1,
        "sentiment": 1,
        "value": 0,
    }
    snapshot["technical"]["S11"]["stance"] = -1
    assert (
        holdings.live_grades(record, snapshot["technical"])["S11"]["grade_live"] == "B"
    )
    row = decision_view.build(
        record,
        [holdings.Holding("S11", 50, 100, "2026-08-01")],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=cash,
    )["rows"]["S11"]
    assert row["strategy_action"] == "Sell"
    assert row["action"] == "Sell"
    assert row["move_weight"] == pytest.approx(-row["current_weight"])
    assert row["executable"] is True


# An upgraded breakout remains a Buy opinion even when personal funding is unknown.
@pytest.mark.parametrize("cash", [None, 0.0, 1000.0])
def test_current_upgrade_drives_intent_and_cash_gate(cash):
    record, snapshot, quoted, now = setup()
    record["grades"]["S11"]["grade"] = "B"
    record["grades"]["S11"]["stances"] = {
        "fundamental": 1,
        "technical": -1,
        "sentiment": 1,
        "value": 0,
    }
    snapshot["technical"]["S11"]["stance"] = 1
    assert (
        holdings.live_grades(record, snapshot["technical"])["S11"]["grade_live"] == "A+"
    )
    row = decision_view.build(
        record, [], 100000, snapshot, quoted, now, entries={"S11": 1.5}, cash=cash
    )["rows"]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["action"] == ("Buy" if cash else "Hold")
    assert row["executable"] is bool(cash)
    assert row["move_weight"] * 100000 <= (cash or 0) + 1e-8


# Preserve a live grade transition over HTTP without writing account state.
@pytest.mark.asyncio
@pytest.mark.parametrize("upgraded", [False, True])
async def test_live_grade_transition_over_personal_http(personal_context, upgraded):
    record, _, _, root, _ = personal_context
    snapshot = market._live_snapshot()
    record["grades"]["S11"]["grade"] = "B" if upgraded else "A+"
    record["grades"]["S11"]["stances"] = {
        "fundamental": 1,
        "technical": -1 if upgraded else 1,
        "sentiment": 1,
        "value": 0,
    }
    snapshot["technical"]["S11"]["stance"] = 1 if upgraded else -1
    before = holdings.holdings_path(root).read_bytes()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=post_auth()
    ) as client:
        response = await client.post(
            "/api/v1/market/desk_user/desk/mine",
            json={"equity": 100000, "available_cash": 1000},
        )
    assert response.status_code == 200
    row = response.json()["decisions"]["rows"]["S11"]
    expected = "Buy" if upgraded else "Sell"
    assert row["strategy_action"] == row["action"] == expected
    assert row["executable"] is True
    assert holdings.holdings_path(root).read_bytes() == before
