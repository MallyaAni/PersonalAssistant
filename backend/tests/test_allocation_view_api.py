"""The funded-allocation preview over the real HTTP decision route.

The optional allocation metadata the paper account serializes into
`snapshot["allocation_plan"]` is the agreed `portfolio-allocation-view/1`
payload, and reaches the page through the incumbent `/desk/mine` decision
route beside the adopted strategy's own rows, never replacing them. Every case
here drives the actual route with repository auth fixtures and asserts on the
returned payload: a missing, malformed, stale, cross-account, non-finite or
inconsistent plan is an explicit `unavailable` preview with null weights, a
blocked one is `blocked`, and a valid one is `available` with `adopted`
defaulting to False so the page can only call it a preview. No eligibility is
fabricated: a symbol only appears in `capabilities` when the plan evidences it.
"""

import json
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app


# A complete, fresh, consistent portfolio-allocation-view/1 plan for the
# fixture decision session, with per-kind rows agreeing with the buckets.
def valid_plan(**overrides):
    plan = {
        "account": "desk_user",
        "as_of": "2026-09-11",
        "policy": "vol_trend",
        "status": "available",
        "adopted": False,
        "reason": "portfolio volatility scaled down to the SPY/QQQ budget",
        "missing": [],
        "blocked": [],
        "current": {"stocks": 0.08, "indexes": 0.0, "cash": 0.92},
        "target": {"stocks": 0.10, "indexes": 0.30, "cash": 0.60},
        "projected": {"stocks": 0.10, "indexes": 0.30, "cash": 0.60},
        "rows": {
            "S11": {
                "kind": "stock",
                "current_weight": 0.08,
                "target_weight": 0.10,
                "projected_weight": 0.10,
                "action": "BUY",
                "reason": "target above current",
            },
            "SPY": {
                "kind": "index",
                "current_weight": 0.0,
                "target_weight": 0.30,
                "projected_weight": 0.30,
                "action": "BUY",
                "reason": "residual index allocation",
            },
            "CASH": {
                "kind": "cash",
                "current_weight": 0.92,
                "target_weight": 0.60,
                "projected_weight": 0.60,
                "action": "HOLD",
                "reason": "display asset; never an order",
            },
        },
        "capabilities": [
            {
                "symbol": "S11",
                "kind": "stock",
                "eligible": True,
                "reason": "tradable stock",
            },
            {
                "symbol": "SPY",
                "kind": "index",
                "eligible": True,
                "reason": "index eligibility evidenced",
            },
            {
                "symbol": "QQQ",
                "kind": "index",
                "eligible": False,
                "reason": "risk benchmark only",
            },
            {
                "symbol": "CASH",
                "kind": "cash",
                "eligible": True,
                "reason": "display asset",
            },
        ],
    }
    plan.update(overrides)
    return plan


# Apply the fixture record, snapshot and auth so the real route can be hit.
def _setup_desk(tmp_path, monkeypatch, snapshot):
    from backend.api.v1 import market
    from backend.market import (
        desk_freshness,
        event_status,
        execution_quotes,
        holdings,
    )
    from backend.tests.test_decision_view import setup

    record, _, quoted, now = setup()
    record["written"] = record["session"]

    class Clock(datetime):
        # Freeze the request at the fresh completed bar.
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
    holdings.save(tmp_path, [holdings.Holding("S11", 60, 100, "2026-09-14")])


# Hit the real /desk/mine route as the operator with the fixture in place.
async def _request_desk(tmp_path):
    token = issue_user_token("desk_user", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        return await client.get("/api/v1/market/desk_user/desk/mine?equity=100000")


# The route serves an explicit unavailable preview when the snapshot carries no
# allocation metadata, and the adopted decision rows are untouched.
@pytest.mark.asyncio
async def test_missing_allocation_plan_is_explicit_unavailable_over_http(
    tmp_path, monkeypatch
):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    _setup_desk(tmp_path, monkeypatch, snapshot)
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "unavailable"
    assert preview["adopted"] is False
    assert preview["reason"] == "no allocation metadata recorded"
    assert preview["version"] == "portfolio-allocation-view/1"
    assert preview["as_of"] is None
    assert preview["policy"] is None
    assert preview["current"] == {"stocks": None, "indexes": None, "cash": None}
    assert preview["target"] == {"stocks": None, "indexes": None, "cash": None}
    assert preview["projected"] == {"stocks": None, "indexes": None, "cash": None}
    assert preview["rows"] == {}
    assert preview["capabilities"] == []
    # The adopted plan's rows still render as the incumbent board.
    assert response.json()["decisions"]["rows"]["S11"]["action"] in (
        "Buy",
        "Sell",
        "Hold",
    )


# A malformed allocation_plan is an explicit unavailable preview, never a crash.
@pytest.mark.asyncio
async def test_malformed_allocation_plan_is_unavailable_over_http(
    tmp_path, monkeypatch
):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    snapshot["allocation_plan"] = ["not", "a", "map"]
    _setup_desk(tmp_path, monkeypatch, snapshot)
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "unavailable"
    assert preview["reason"] == "allocation metadata malformed"


# A valid plan serves an available preview labelled unadopted, with finite
# bucket fractions, explicit capabilities and the incumbent rows unchanged.
@pytest.mark.asyncio
async def test_valid_unadopted_allocation_plan_serves_preview_over_http(
    tmp_path, monkeypatch
):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    snapshot["allocation_plan"] = valid_plan()
    _setup_desk(tmp_path, monkeypatch, snapshot)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")}
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    body = response.json()["decisions"]
    preview = body["portfolio_allocation"]
    assert preview["status"] == "available"
    assert preview["adopted"] is False
    assert preview["as_of"] == "2026-09-11"
    assert preview["policy"] == "vol_trend"
    assert preview["missing"] == []
    assert preview["blocked"] == []
    assert preview["current"] == {"stocks": 0.08, "indexes": 0.0, "cash": 0.92}
    assert preview["target"] == {"stocks": 0.10, "indexes": 0.30, "cash": 0.60}
    assert preview["projected"] == {"stocks": 0.10, "indexes": 0.30, "cash": 0.60}
    row = preview["rows"]["S11"]
    assert row["kind"] == "stock"
    assert row["current_weight"] == 0.08
    assert row["target_weight"] == 0.10
    assert row["projected_weight"] == 0.10
    assert row["action"] == "BUY"
    spy = preview["rows"]["SPY"]
    assert spy["kind"] == "index"
    assert spy["projected_weight"] == 0.30
    cash = preview["rows"]["CASH"]
    assert cash["kind"] == "cash"
    assert cash["action"] == "HOLD"
    assert "never an order" in cash["reason"]
    caps = {c["symbol"]: c for c in preview["capabilities"]}
    assert caps["SPY"]["eligible"] is True
    assert caps["SPY"]["kind"] == "index"
    assert caps["QQQ"]["eligible"] is False
    assert caps["CASH"]["eligible"] is True
    assert caps["S11"]["eligible"] is True
    # The experimental metadata must never change the incumbent decision rows.
    assert body["rows"]["S11"]["action"] in ("Buy", "Sell", "Hold")
    assert body["rows"]["S11"]["target_weight"] == 0.1
    # The preview writes no state.
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*.json")} == before


# A valid plan whose symbols could not all be traded is blocked, not available,
# and still carries its weights so the page can label the preview.
@pytest.mark.asyncio
async def test_blocked_allocation_plan_is_blocked_over_http(tmp_path, monkeypatch):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    snapshot["allocation_plan"] = valid_plan(
        status="blocked", blocked=["held valuation unavailable for S99"]
    )
    _setup_desk(tmp_path, monkeypatch, snapshot)
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "blocked"
    assert preview["blocked"] == ["held valuation unavailable for S99"]
    assert preview["target"] == {"stocks": 0.10, "indexes": 0.30, "cash": 0.60}


# A plan whose evidence was incomplete is unavailable, never a made-up target.
@pytest.mark.asyncio
async def test_unavailable_allocation_plan_is_unavailable_over_http(
    tmp_path, monkeypatch
):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    snapshot["allocation_plan"] = valid_plan(
        status="unavailable",
        missing=["trend ceiling (< 200 prices)"],
        reason="insufficient policy evidence; holdings retained",
    )
    _setup_desk(tmp_path, monkeypatch, snapshot)
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "unavailable"
    assert preview["as_of"] == "2026-09-11"
    assert preview["missing"] == ["trend ceiling (< 200 prices)"]
    assert preview["current"]["stocks"] is None
    assert preview["rows"] == {}


# A non-finite weight anywhere in a bucket rejects the whole preview.
@pytest.mark.asyncio
async def test_nonfinite_weight_rejects_allocation_over_http(tmp_path, monkeypatch):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    snapshot["allocation_plan"] = valid_plan(
        current={"stocks": float("nan"), "indexes": 0.0, "cash": 1.0}
    )
    _setup_desk(tmp_path, monkeypatch, snapshot)
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "unavailable"
    assert "not a finite" in preview["reason"]


# A bucket that does not total one is inconsistent, never clamped to one.
@pytest.mark.asyncio
async def test_overallocated_bucket_is_unavailable_over_http(tmp_path, monkeypatch):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    snapshot["allocation_plan"] = valid_plan(
        current={"stocks": 0.8, "indexes": 0.8, "cash": 0.2}
    )
    _setup_desk(tmp_path, monkeypatch, snapshot)
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "unavailable"
    assert "does not total one" in preview["reason"]


# A per-symbol map in a bucket (the wrong raw-map protocol) is rejected.
@pytest.mark.asyncio
async def test_per_symbol_bucket_shape_is_unavailable_over_http(tmp_path, monkeypatch):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    snapshot["allocation_plan"] = valid_plan(current={"A": 0.8, "B": 0.8})
    _setup_desk(tmp_path, monkeypatch, snapshot)
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "unavailable"


# A plan dated before the current decision session is stale, not a preview.
@pytest.mark.asyncio
async def test_stale_allocation_plan_rejected_over_http(tmp_path, monkeypatch):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    snapshot["allocation_plan"] = valid_plan(as_of="2026-09-10")
    _setup_desk(tmp_path, monkeypatch, snapshot)
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "unavailable"
    assert "stale" in preview["reason"]


# A plan dated after the current decision session is inconsistent, not a preview.
@pytest.mark.asyncio
async def test_future_allocation_plan_rejected_over_http(tmp_path, monkeypatch):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    snapshot["allocation_plan"] = valid_plan(as_of="2026-09-15")
    _setup_desk(tmp_path, monkeypatch, snapshot)
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "unavailable"
    assert "inconsistent" in preview["reason"]


# A plan naming another account is an unavailable preview through the real
# route, which passes the viewing account as the expected provenance.
@pytest.mark.asyncio
async def test_cross_account_allocation_plan_rejected_over_http(tmp_path, monkeypatch):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    snapshot["allocation_plan"] = valid_plan(account="another-account")
    _setup_desk(tmp_path, monkeypatch, snapshot)
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "unavailable"
    assert "another account" in preview["reason"]


# SPY eligibility comes only from explicit capability evidence, not guessing.
@pytest.mark.asyncio
async def test_index_eligibility_is_reported_explicitly_over_http(
    tmp_path, monkeypatch
):
    from backend.tests.test_decision_view import setup

    _record, snapshot, _quoted, _now = setup()
    snapshot["allocation_plan"] = valid_plan(
        target={"stocks": 0.10, "indexes": 0.0, "cash": 0.90},
        projected={"stocks": 0.10, "indexes": 0.0, "cash": 0.90},
        capabilities=[
            {"symbol": "S11", "kind": "stock", "eligible": True, "reason": "tradable"},
            {
                "symbol": "SPY",
                "kind": "index",
                "eligible": False,
                "reason": "index access not confirmed",
            },
        ],
        rows={
            "S11": {
                "kind": "stock",
                "current_weight": 0.08,
                "target_weight": 0.10,
                "projected_weight": 0.10,
                "action": "BUY",
                "reason": "target above current",
            },
            "CASH": {
                "kind": "cash",
                "current_weight": 0.92,
                "target_weight": 0.90,
                "projected_weight": 0.90,
                "action": "HOLD",
                "reason": "display asset; never an order",
            },
        },
    )
    _setup_desk(tmp_path, monkeypatch, snapshot)
    response = await _request_desk(tmp_path)
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "available"
    caps = {c["symbol"]: c for c in preview["capabilities"]}
    assert caps["SPY"]["eligible"] is False
    assert "not confirmed" in caps["SPY"]["reason"]


# A plan carried in the actual live.json file reaches the route the same way.
@pytest.mark.asyncio
async def test_allocation_plan_read_from_live_json_file(tmp_path, monkeypatch):
    from backend.api.v1 import market
    from backend.market import event_status, execution_quotes
    from backend.tests.test_decision_view import setup

    record, snapshot, quoted, now = setup()
    record["written"] = record["session"]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(market, "datetime", Clock)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(market.deskrecord, "latest_pair", lambda root: (record, None))
    monkeypatch.setattr(event_status, "for_planning", lambda record, root: record)
    monkeypatch.setattr(execution_quotes, "fetch", lambda names: quoted)
    (tmp_path / "desk").mkdir(parents=True, exist_ok=True)
    snapshot["allocation_plan"] = valid_plan()
    (tmp_path / "desk" / "live.json").write_text(json.dumps(snapshot))
    token = issue_user_token("desk_user", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.get("/api/v1/market/desk_user/desk/mine?equity=100000")
    assert response.status_code == 200, response.text
    preview = response.json()["decisions"]["portfolio_allocation"]
    assert preview["status"] == "available"
    assert preview["rows"]["S11"]["projected_weight"] == 0.10


# A plan with no decision date cannot be judged current, so it is unavailable.
def test_undated_allocation_plan_is_unavailable():
    from backend.market import allocation_view

    plan = valid_plan(as_of=None)
    plan["as_of"] = None
    preview = allocation_view.serialize(plan, session="2026-09-11")
    assert preview["status"] == "unavailable"
    assert "undated" in preview["reason"]


# A malformed missing list is inconsistent metadata, not an empty one.
def test_malformed_missing_list_rejects_the_plan():
    from backend.market import allocation_view

    plan = valid_plan(missing="not-a-list")
    preview = allocation_view.serialize(plan, session="2026-09-11")
    assert preview["status"] == "unavailable"


# A blocked status without a blocked reason is inconsistent metadata.
def test_blocked_without_reasons_is_unavailable():
    from backend.market import allocation_view

    plan = valid_plan(status="blocked", blocked=[])
    preview = allocation_view.serialize(plan, session="2026-09-11")
    assert preview["status"] == "unavailable"
    assert "blocked status" in preview["reason"]


# An available status listing blocked symbols is inconsistent metadata.
def test_available_with_blocked_is_unavailable():
    from backend.market import allocation_view

    plan = valid_plan(status="available", blocked=["something"])
    preview = allocation_view.serialize(plan, session="2026-09-11")
    assert preview["status"] == "unavailable"
    assert "inconsistent" in preview["reason"]


# Rows that contradict their buckets are inconsistent, not silently trusted.
def test_rows_contradicting_buckets_are_unavailable():
    from backend.market import allocation_view

    plan = valid_plan()
    plan["rows"]["S11"]["projected_weight"] = 0.5
    preview = allocation_view.serialize(plan, session="2026-09-11")
    assert preview["status"] == "unavailable"
    assert "sum to" in preview["reason"]


# A money-market asset is never given fabricated stock/fund eligibility.
def test_money_market_asset_gets_no_fabricated_eligibility():
    from backend.market import allocation_view

    preview = allocation_view.serialize(valid_plan(), session="2026-09-11")
    assert preview["status"] == "available"
    assert "SWVXX" not in preview["rows"]
    assert all(c["symbol"] != "SWVXX" for c in preview["capabilities"])
    # And a row that tries to name a money-market kind is rejected outright.
    plan = valid_plan(rows={"SWVXX": {"kind": "money_market"}})
    rejected = allocation_view.serialize(plan, session="2026-09-11")
    assert rejected["status"] == "unavailable"
    assert "unknown kind" in rejected["reason"]


# A malformed capability entry is inconsistent metadata, not a silent pass.
def test_malformed_capabilities_reject_the_plan():
    from backend.market import allocation_view

    plan = valid_plan(capabilities=[{"symbol": "S11"}])
    preview = allocation_view.serialize(plan, session="2026-09-11")
    assert preview["status"] == "unavailable"
    assert "capability" in preview["reason"]


# A non-boolean adopted flag is malformed metadata, not a silent default.
def test_non_boolean_adopted_rejects_the_plan():
    from backend.market import allocation_view

    plan = valid_plan(adopted="yes")
    preview = allocation_view.serialize(plan, session="2026-09-11")
    assert preview["status"] == "unavailable"
    assert "adopted" in preview["reason"]


# A boolean is not a weight; it is rejected rather than read as 0 or 1.
def test_boolean_is_not_a_weight():
    from backend.market import allocation_view

    plan = valid_plan(target={"stocks": True, "indexes": 0.3, "cash": 0.7})
    preview = allocation_view.serialize(plan, session="2026-09-11")
    assert preview["status"] == "unavailable"
    assert "boolean" in preview["reason"]


# The contract's canonical payload passes through exactly as agreed.
def test_canonical_contract_payload_passes_through():
    from backend.market import allocation_view

    plan = {
        "version": "portfolio-allocation-view/1",
        "as_of": "2026-09-18",
        "policy": "vol",
        "status": "available",
        "adopted": False,
        "reason": "known composition",
        "missing": [],
        "blocked": [],
        "current": {"stocks": 0.6, "indexes": 0.2, "cash": 0.2},
        "target": {"stocks": 0.4, "indexes": 0.3, "cash": 0.3},
        "projected": {"stocks": 0.4, "indexes": 0.3, "cash": 0.3},
        "rows": {},
        "capabilities": [],
    }
    preview = allocation_view.serialize(plan, session="2026-09-18")
    assert preview["status"] == "available"
    assert preview["adopted"] is False
    assert preview["current"] == {"stocks": 0.6, "indexes": 0.2, "cash": 0.2}
    assert preview["target"] == {"stocks": 0.4, "indexes": 0.3, "cash": 0.3}
    assert preview["projected"] == {"stocks": 0.4, "indexes": 0.3, "cash": 0.3}
    assert preview["rows"] == {}
    assert preview["capabilities"] == []
