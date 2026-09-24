"""Exercise optional personal risk limits through funded decisions and HTTP."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.v1 import market
from backend.main import app
from backend.market import decision_view, holdings
from backend.tests.test_decision_view import setup
from backend.tests.test_personal_guidance_api import (
    personal_context as personal_context,
)
from backend.tests.test_personal_guidance_api import (
    post_auth,
)


# Supply dated levels as price fractions, never mix adjusted levels with raw quotes.
def scenario():
    record, snapshot, quoted, now = setup()
    snapshot["technical_detail"]["S11"] = {
        "short": {"support_distance": 0.1, "resistance_distance": 0.2},
    }
    return record, snapshot, quoted, now


# An explicit risk budget caps the actual funded move rather than only its tooltip.
def test_risk_budget_caps_funded_buy_and_preserves_signal():
    record, snapshot, quoted, now = scenario()
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 2},
        cash=100000,
        risk_budget_pct=0.5,
    )["rows"]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["action"] == "Buy"
    assert row["move_weight"] == pytest.approx(0.05)
    assert row["risk_plan"]["reward_risk_ratio"] == pytest.approx(2)
    assert row["move_weight"] * row["risk_plan"]["risk_pct"] <= 0.5


# Existing shares already consume the selected per-position loss budget.
def test_existing_exposure_consumes_risk_budget():
    record, snapshot, quoted, now = scenario()
    price = snapshot["quotes"]["S11"]["last"]
    held = [holdings.Holding("S11", 4000 / price, price, "2026-09-01")]
    row = decision_view.build(
        record,
        held,
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 2},
        cash=100000,
        risk_budget_pct=0.5,
    )["rows"]["S11"]
    assert row["action"] == "Buy"
    assert row["move_weight"] == pytest.approx(0.01)


# No target is invented when the current chart has no overhead reference.
def test_unknown_reward_blocks_opted_in_risk_sizing_without_hiding_intent():
    record, snapshot, quoted, now = scenario()
    snapshot["technical_detail"]["S11"]["short"].pop("resistance_distance")
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 2},
        cash=100000,
        risk_budget_pct=0.5,
    )["rows"]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0
    assert not row["executable"]
    assert row["risk_plan"]["reward_risk_ratio"] is None
    assert "reward is unknown" in row["reason"]


# New risk constraints cannot manufacture tiny buys below the existing floor.
def test_risk_cap_below_minimum_is_not_an_action():
    record, snapshot, quoted, now = scenario()
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 2},
        cash=100000,
        risk_budget_pct=0.01,
    )["rows"]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0


# The real authenticated POST applies the budget and leaves personal holdings intact.
@pytest.mark.asyncio
async def test_http_risk_budget_changes_only_returned_sizing(personal_context):
    _, _, _, root, auth = personal_context
    holdings.save(root, [])
    before = holdings.holdings_path(root).read_bytes()
    snapshot = market._live_snapshot()
    snapshot["technical_detail"]["S11"] = {
        "short": {"support_distance": 0.1, "resistance_distance": 0.2},
    }
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=post_auth(),
    ) as client:
        response = await client.post(
            "/api/v1/market/desk_user/desk/mine",
            json={
                "equity": 100000,
                "available_cash": 100000,
                "risk_budget_pct": 0.1,
            },
        )
    assert response.status_code == 200
    row = response.json()["decisions"]["rows"]["S11"]
    assert row["action"] == "Buy"
    assert row["move_weight"] == pytest.approx(0.01)
    assert row["risk_plan"]["risk_budget_pct"] == 0.1
    assert holdings.holdings_path(root).read_bytes() == before


# Invalid percentages cannot reach account or market computations.
@pytest.mark.parametrize(
    "value", [True, False, 0, -0.5, 101, float("nan"), float("inf"), {}, [], [0.5]]
)
def test_risk_budget_input_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="Risk budget"):
        market.DeskMineInput(equity=100000, risk_budget_pct=value)


# Malformed JSON values produce a client error, not a server error or account write.
@pytest.mark.asyncio
@pytest.mark.parametrize("value", [{}, [], [0.5]])
async def test_http_malformed_budget_is_422(personal_context, value):
    _, _, _, root, _ = personal_context
    holdings.save(root, [])
    before = holdings.holdings_path(root).read_bytes()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=post_auth()
    ) as client:
        response = await client.post(
            "/api/v1/market/desk_user/desk/mine",
            json={"equity": 100000, "risk_budget_pct": value},
        )
    assert response.status_code == 422
    assert holdings.holdings_path(root).read_bytes() == before


# A missing daily observation remains an explicit data failure through final funding.
def test_missing_entry_evidence_survives_account_plan():
    record, snapshot, quoted, now = scenario()
    reason = "Entry data unavailable: missing daily close for 2026-09-22"
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={},
        cash=100000,
        entry_readings={
            "S11": {
                "entry_status": "unavailable",
                "entry_reason": reason,
                "missing_sessions": ["2026-09-22"],
            }
        },
    )["rows"]["S11"]
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0
    assert row["entry_status"] == "unavailable"
    assert row["entry_reason"] == reason
    assert row["reason"] == reason
    assert row["missing_sessions"] == ["2026-09-22"]
