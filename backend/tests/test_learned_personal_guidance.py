"""Adopted personal guidance must share real learned timing without paper funding."""

import json
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.v1 import market
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app
from backend.market import (
    calendar,
    desk_freshness,
    event_status,
    execution_quotes,
    holdings,
    learned_live_holding,
    learned_live_timing,
)
from backend.market import learned_personal_guidance as guidance
from backend.market.joint_funded_policy import MARKET_TIMED_POLICY
from backend.tests.test_forward_execution import fitted as fitted
from backend.tests.test_forward_execution import residual_archive as residual_archive
from backend.tests.test_forward_market_evidence import NOW, capture_payloads
from backend.tests.test_learned_live_timing import context, install


# Install a synthetic explicit approval over authentic fixture timing publications.
def approve(root, timing_config):
    folder = (root / learned_live_holding.CONFIG).parent
    folder.mkdir(parents=True)
    evidence = b'{"fixture_only":true,"economic_adoption":false}'
    (folder / "evidence.json").write_bytes(evidence)
    release = {
        "schema": "learned-holding-release/1",
        "policy": MARKET_TIMED_POLICY,
        "approved_at": "2026-10-05T08:00:00-04:00",
        "source_sha256": learned_live_holding.source_identity(),
        "evidence_sha256": sha256(evidence).hexdigest(),
        "approved": True,
    }
    raw_release = json.dumps(release).encode()
    (folder / "release.json").write_bytes(raw_release)
    config = {
        "policy": MARKET_TIMED_POLICY,
        "risk_directory": "risk",
        "risk_receipt_sha256": "0" * 64,
        "model_directory": "models",
        "model_receipt_sha256": "1" * 64,
        "cost_bps": timing_config["cost_bps"],
        "timing_config_sha256": sha256(
            (root / learned_live_timing.CONFIG).read_bytes()
        ).hexdigest(),
        "release_receipt_sha256": sha256(raw_release).hexdigest(),
    }
    raw = json.dumps(config).encode()
    (root / learned_live_holding.CONFIG).write_bytes(raw)
    return sha256(raw).hexdigest()


# Supply identical current API quotes, genuine numeric inference and original pages.
@pytest.fixture
def personal(tmp_path, monkeypatch, fitted, residual_archive):
    digest = approve(tmp_path, install(tmp_path, fitted, residual_archive))
    grade = {
        "grade": "A+",
        "score": 4,
        "ranks": {"technical": 0.7, "value": 0.9},
        "stances": {"technical": 1, "value": 1, "fundamental": 1, "sentiment": 1},
    }
    targets = {"policy": MARKET_TIMED_POLICY, "weights": {"AAOI": 0.05, "QQQ": 0.0}}
    record = {
        "session": "2026-10-02",
        "written": "2026-10-02T20:00:00-04:00",
        "grades": {"AAOI": deepcopy(grade), "QQQ": deepcopy(grade)},
        "book": [{"ticker": "AAOI", "weight": 0.05}],
        "targets": targets,
        "paper": {
            "policy": MARKET_TIMED_POLICY,
            "selected_targets": deepcopy(targets),
            "learned_holding": {"config_sha256": digest},
        },
    }
    snapshot = {
        "as_of": NOW.isoformat(),
        "decision_session": record["session"],
        "quotes": {
            name: {"last": 99, "bar": "2026-10-05T13:30:00Z"}
            for name in ("AAOI", "SPY", "QQQ")
        },
        "technical": {"AAOI": {"now": 0.7, "close": 0.7, "stance": 1}},
        "value": {"AAOI": {"now": 0.9, "close": 0.9, "stance": 1}},
        "technical_detail": {
            "AAOI": {"short": {"support_distance": 0.04, "resistance_distance": 0.08}}
        },
    }
    quoted = {
        "feed": "iex",
        "market_open": True,
        "quotes": {
            name: {
                "bp": 98.995,
                "ap": 99.005,
                "bs": 100,
                "as": 100,
                "t": NOW.isoformat(),
            }
            for name in ("AAOI", "QQQ")
        },
    }
    seen = []
    monkeypatch.setattr(
        learned_live_timing.sequential_shadow_context,
        "load_context",
        lambda *args: context(),
    )
    monkeypatch.setattr(learned_live_timing.alpaca, "credentials", lambda: {})

    # Replay endpoint bytes and stock risk references at an explicit current clock.
    def run(
        *,
        held=(),
        cash=1000,
        price=99,
        pending=None,
        budget=None,
        now=NOW,
        extra_quotes=None,
        reference_risk=None,
    ):
        current_quoted = deepcopy(quoted)
        current_snapshot = deepcopy(snapshot)
        if reference_risk is not None:
            support, resistance = reference_risk
            current_snapshot["technical_detail"]["AAOI"]["short"].update(
                support_distance=support, resistance_distance=resistance
            )
        for quote in current_quoted["quotes"].values():
            quote.update(bp=price - 0.005, ap=price + 0.005, t=now.isoformat())
        current_quoted["quotes"].update(extra_quotes or {})
        for quote in current_snapshot["quotes"].values():
            quote["last"] = price
        bodies = capture_payloads(
            NOW, datetime(2026, 10, 2, 15, 45, tzinfo=calendar.NEW_YORK)
        )
        quote_page = json.loads(bodies[-1])
        for quote in quote_page["quotes"].values():
            quote.update(bp=price - 0.005, ap=price + 0.005)
        bodies[-1] = json.dumps(quote_page).encode()
        pages = iter(bodies)

        # Keep provider requests inspectable and prohibit any real HTTP transport.
        def transport(url, headers):
            seen.append(url)
            return 200, next(pages)

        return guidance.build(
            tmp_path,
            record,
            list(held),
            10000,
            current_snapshot,
            current_quoted,
            now,
            cash=cash,
            pending=pending,
            risk_budget_pct=budget,
            expected_account="owner",
            clock=lambda: now + timedelta(seconds=2),
            transport=transport,
        )[0]

    return run, record, seen, tmp_path


# Learned buy and profitable-position trim must traverse original numeric timing.
@pytest.mark.parametrize("side", ["buy", "sell"])
def test_actual_learned_personal_action_and_funding(personal, side):
    run, record, seen, root = personal
    held = [holdings.Holding("AAOI", 10, 40, "2026-10-01")] if side == "sell" else []
    before = deepcopy(record)
    result = run(held=held, price=150 if side == "sell" else 99)
    row = result["rows"]["AAOI"]
    assert row["action"] == ("Buy" if side == "buy" else "Sell"), row
    assert row["executable"] is True
    assert row["timing"]["level"] is None
    assert row["learned_timing"]["policy"] == learned_live_timing.POLICY
    assert row["learned_timing"]["state"] == "execute"
    assert row["learned_timing"]["buying_power_budget"] == 1000
    assert result["account_basis"] == "manual_personal_inputs_not_broker_verified"
    assert len(seen) == 3
    assert record == before
    assert not (root / "paper" / "state.json").exists()
    if side == "buy":
        assert row["move_weight"] * 10000 * 1.001 <= 1000
    else:
        assert row["planned_qty"] <= 10

    from backend.market import personal_history

    receipt = personal_history.project(result, record, {"quotes": {}}, {})
    assert receipt["policy_version"] == MARKET_TIMED_POLICY
    assert receipt["rows"]["AAOI"]["grade"] == "A+"
    assert receipt["rows"]["AAOI"]["grade_basis"] == "recorded_close"
    assert "planned_qty" not in receipt["rows"]["AAOI"]


# Paper fills and balances cannot alter a personal recommendation or its size.
def test_paper_cash_and_holdings_are_not_personal_funding(personal):
    run, record, _, _ = personal
    first = run()
    record["paper"].update(
        cash=1e9, equity=1e12, positions=[{"symbol": "AAOI", "qty": 9000}]
    )
    second = run()
    assert second == first


# Cash absence, zero and small balances cannot use sales or paper money to fund buys.
@pytest.mark.parametrize("cash", [None, 0, 20, 100])
def test_declared_cash_bounds_whole_share_buys(personal, cash):
    run, _, _, _ = personal
    result = run(cash=cash)
    row = result["rows"]["AAOI"]
    assert max(0, row["move_weight"]) * 10000 * 1.001 <= (cash or 0)
    if cash is None or cash < 99.1:
        assert row["action"] == "Hold"


# B-grade holdings at target cannot be liquidated by the old downgrade or profit rule.
def test_no_legacy_b_exit_or_fixed_profit_target(personal):
    run, record, seen, _ = personal
    record["grades"]["AAOI"]["grade"] = "B"
    record["targets"]["weights"]["AAOI"] = 0.198
    record["paper"]["selected_targets"] = deepcopy(record["targets"])
    result = run(held=[holdings.Holding("AAOI", 20, 40, "2026-10-01")])
    assert result["rows"]["AAOI"]["action"] == "Hold"
    assert result["rows"]["AAOI"]["move_weight"] == 0
    assert not seen


# A pending personal fill must suppress its addition without issuing provider requests.
def test_pending_buys_suppressed(personal):
    run, _, seen, _ = personal
    result = run(pending=["AAOI"])
    assert result["rows"]["AAOI"]["action"] == "Hold"
    assert not seen


# Admission failures cannot reuse the old one-percent rule.
@pytest.mark.parametrize("defect", ["release", "target", "config", "source", "stale"])
def test_invalid_adopted_plan_fails_closed(personal, defect):
    run, record, seen, root = personal
    if defect == "release":
        (root / learned_live_holding.CONFIG).with_name("release.json").write_text("{}")
    elif defect == "target":
        record["targets"]["weights"]["AAOI"] = 0.1
    elif defect == "config":
        record["paper"]["learned_holding"]["config_sha256"] = "0" * 64
    elif defect == "source":
        path = (root / learned_live_holding.CONFIG).with_name("evidence.json")
        path.write_text("{}")
    else:
        record["session"] = "2026-09-29"
    row = run(price=90)["rows"]["AAOI"]
    assert row["action"] == "Hold"
    assert row["executable"] is False
    assert row["move_weight"] == 0
    assert "timing" not in row
    assert not seen


# Mandatory C exits preserve the immediate path and never wait for a forecast.
def test_company_exit_before_first_completed_bar(personal):
    run, record, seen, _ = personal
    record["grades"]["AAOI"]["grade"] = "C"
    row = run(
        held=[holdings.Holding("AAOI", 5, 40, "2026-10-01")], now=NOW.replace(minute=32)
    )["rows"]["AAOI"]
    assert row["action"] == "Sell", row
    assert row["planned_qty"] == 5
    assert not seen


# An uncovered or fractional personal holding must not become an invented liquidation.
@pytest.mark.parametrize(
    "holding",
    [
        holdings.Holding("OTHER", 2, 30, "2026-10-01"),
        holdings.Holding("AAOI", 1.5, 40, "2026-10-01"),
    ],
)
def test_unsupported_personal_account_remains_unavailable(personal, holding):
    run, _, seen, _ = personal
    rows = run(held=[holding])["rows"]
    assert all(row["action"] == "Hold" for row in rows.values())
    assert all(row["move_weight"] == 0 for row in rows.values())
    assert not seen


# An explicit risk budget caps an addition using dated stock-specific reference risk.
def test_personal_risk_preference_cannot_increase_model_weight(personal):
    run, _, _, _ = personal
    unrestricted = run()["rows"]["AAOI"]
    bounded = run(budget=0.1)["rows"]["AAOI"]
    assert 0 <= bounded["move_weight"] <= unrestricted["move_weight"]
    assert bounded["target_weight"] == unrestricted["target_weight"] == 0.05


# Explain zero-sized learned buys by their risk constraint without fetching timing.
@pytest.mark.parametrize("missing_reward", [False, True])
def test_risk_blocked_buy_preserves_actual_risk_reason(personal, missing_reward):
    run, record, seen, _ = personal
    before = deepcopy(record)
    held = [] if missing_reward else [holdings.Holding("AAOI", 3, 40, "2026-10-01")]
    result = run(
        held=held,
        budget=0.1,
        reference_risk=(0.04, None if missing_reward else 0.08),
    )
    row = result["rows"]["AAOI"]
    assert row["strategy_action"] == "Buy"
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0
    assert row["executable"] is False
    assert row["blocker"] == row["risk_plan"]["reason"]
    assert row["reason"] == row["risk_plan"]["reason"]
    assert row["target_weight"] == 0.05
    assert row["current_weight"] == pytest.approx(
        0 if missing_reward else 3 * 99 / 10000
    )
    assert not seen
    assert record == before


# A known uncovered holding stays at its actual shares rather than becoming a sale.
def test_marked_uncovered_holding_is_preserved(personal):
    run, _, _, _ = personal
    quote = {"bp": 98.995, "ap": 99.005, "bs": 100, "as": 100, "t": NOW.isoformat()}
    result = run(
        held=[holdings.Holding("OTHER", 20, 40, "2026-10-01")],
        extra_quotes={"OTHER": quote},
    )
    assert result["rows"]["AAOI"]["action"] == "Buy"
    assert result["rows"]["OTHER"]["action"] == "Hold"
    assert result["rows"]["OTHER"]["move_weight"] == 0


# Event pauses suppress additions without changing model weights or fetching forecasts.
def test_event_entry_pause_preserves_holdings(personal):
    run, record, seen, _ = personal
    record["event_risk"] = {"execution_pending": True}
    result = run()
    assert result["rows"]["AAOI"]["action"] == "Hold"
    assert result["rows"]["AAOI"]["reason"] == "FOMC pause"
    assert result["rows"]["AAOI"]["target_weight"] == 0.05
    assert not seen


# The existing final deadline remains explicit and does not load an expired model clock.
def test_final_session_completion_uses_funded_shares(personal):
    run, _, seen, _ = personal
    row = run(now=NOW.replace(hour=15, minute=59))["rows"]["AAOI"]
    assert row["action"] == "Buy"
    assert row["planned_qty"] == 5
    assert row["reason"] == "Session completion"
    assert row["learned_timing"] is None
    assert not seen


# Closed sessions never produce an executable action or trigger market acquisition.
def test_closed_session_is_explicitly_unavailable(personal):
    run, _, seen, _ = personal
    row = run(now=NOW.replace(hour=16, minute=1))["rows"]["AAOI"]
    assert row["action"] == "Hold"
    assert row["blocker"] == "Regular session closed"
    assert row["move_weight"] == 0
    assert not seen


# Timing can wait on a funded stock rather than inventing a universal price level.
def test_current_forecast_can_wait(personal):
    run, _, seen, _ = personal
    row = run(price=150)["rows"]["AAOI"]
    assert row["action"] == "Hold"
    assert row["planned_qty"] > 0
    assert row["learned_timing"]["state"] == "wait"
    assert row["move_weight"] == 0
    assert row["timing"]["level"] is None
    assert len(seen) == 3


# Missing original model bytes block ordinary actions while a current C exit remains.
def test_missing_model_never_uses_dip_gate_or_blocks_company_exit(personal):
    run, record, seen, root = personal
    record["grades"]["AAOI"]["grade"] = "C"
    record["targets"]["weights"]["QQQ"] = 0.05
    record["paper"]["selected_targets"] = deepcopy(record["targets"])
    folder = (root / learned_live_timing.CONFIG).parent / "models"
    for path in folder.iterdir():
        if path.suffix == ".npz":
            path.write_bytes(b"changed fixture artifact")
    result = run(held=[holdings.Holding("AAOI", 5, 40, "2026-10-01")], price=90)
    assert result["rows"]["AAOI"]["action"] == "Sell"
    assert result["rows"]["QQQ"]["action"] == "Hold"
    assert not seen


# The authenticated body-only route exercises real numeric timing and personal cash.
@pytest.mark.asyncio
async def test_adopted_personal_post_uses_actual_learned_path(personal, monkeypatch):
    _, record, seen, root = personal
    snapshot = {
        "as_of": NOW.isoformat(),
        "decision_session": record["session"],
        "quotes": {
            name: {"last": 99, "bar": "2026-10-05T13:30:00Z"}
            for name in ("AAOI", "SPY", "QQQ")
        },
    }
    quoted = {
        "feed": "iex",
        "market_open": True,
        "quotes": {
            name: {
                "bp": 98.995,
                "ap": 99.005,
                "bs": 100,
                "as": 100,
                "t": NOW.isoformat(),
            }
            for name in record["grades"]
        },
    }

    class Clock(datetime):
        # Keep the actual API, market capture and model completion clocks aligned.
        @classmethod
        def now(cls, tz=None):
            return NOW + timedelta(seconds=2)

    bodies = capture_payloads(
        NOW, datetime(2026, 10, 2, 15, 45, tzinfo=calendar.NEW_YORK)
    )
    quotes = json.loads(bodies[-1])
    for quote in quotes["quotes"].values():
        quote.update(bp=98.995, ap=99.005)
    bodies[-1] = json.dumps(quotes).encode()
    pages = iter(bodies)

    # Exercise original acquisition through the route without a real provider request.
    def transport(url, headers):
        seen.append(url)
        return 200, next(pages)

    monkeypatch.setattr(market, "datetime", Clock)
    monkeypatch.setattr(desk_freshness, "datetime", Clock)
    monkeypatch.setattr(guidance, "datetime", Clock)
    monkeypatch.setattr(learned_live_timing, "datetime", Clock)
    monkeypatch.setattr(learned_live_timing, "market_transport", transport)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(root))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(market.deskrecord, "latest_pair", lambda root: (record, None))
    monkeypatch.setattr(market, "_live_snapshot", lambda: snapshot)
    monkeypatch.setattr(event_status, "for_planning", lambda record, root: record)
    monkeypatch.setattr(execution_quotes, "fetch", lambda names: quoted)
    monkeypatch.setattr(market.live_technical, "entry_now", lambda *args: {})
    token = issue_user_token("desk_user", scopes=["memory:read", "memory:write"])
    original = deepcopy(record)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.post(
            "/api/v1/market/desk_user/desk/mine",
            json={"equity": 10000, "available_cash": 1000},
        )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    result = response.json()["decisions"]
    assert result["policy"] == MARKET_TIMED_POLICY
    assert result["rows"]["AAOI"]["action"] == "Buy", result
    assert result["rows"]["AAOI"]["planned_qty"] == 5
    assert result["rows"]["AAOI"]["learned_timing"]["buying_power_budget"] == 1000
    assert len(seen) == 3
    assert record == original
    assert not holdings.holdings_path(root).exists()
