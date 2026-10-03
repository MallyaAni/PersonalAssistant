"""Exercise purchases and covered cash exits in the actual carried-account loop."""

from dataclasses import replace

import numpy as np
import pytest

from backend.agents.trading.desk import simulate
from backend.market.learned_cash_selection import MODES, CashSelectionAdapter
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot
from backend.tests.test_learned_retention_simulator_hook import (
    KeepB,
    options,
    report_fixture,
)


# Bind synthetic causal forecasts to the real fixture's explicit session calendar.
def adapter(report, means=None, spy=None, **changes):
    panel = report.panel
    relative = np.full(panel.close.shape, np.nan) if means is None else means.copy()
    relative[:, -1] = np.nan
    values = dict(
        symbols=panel.tickers,
        dates=panel.dates,
        eligible=np.ones(panel.close.shape, dtype=bool),
        relative=relative,
        spy=np.zeros(len(panel.dates)) if spy is None else spy,
        cost_bps=10,
    )
    values["eligible"][:, -1] = False
    values.update(changes)
    return CashSelectionAdapter(**values)


# Record actual decisions, fills and carried balances under identical source identities.
def account(report, selection=None, **changes):
    common = {**options(report), **changes}
    journal = ResearchJournal(
        report.panel.dates,
        report.panel.tickers,
        simulate.adjusted_open(report.panel),
        report.panel.adj_close,
        run_id="cash-selection-fixture",
        account_id="carried",
        policy_id="test-only",
        cost_bps=common["cost_bps"],
        provenance={"fixture": "cash-selection"},
    )
    result = simulate.run(
        report,
        **common,
        cash_selection_adapter=selection,
        journal=journal,
    )
    snapshot = journal.snapshot()
    assert verify_snapshot(snapshot)["ok"]
    return result, snapshot


# Missing forecasts preserve full journal content with and without the B overlay.
@pytest.mark.parametrize("retention", [False, True])
@pytest.mark.parametrize("mode", MODES)
def test_unavailable_full_journal_is_bit_identical(retention, mode):
    report = report_fixture()
    kwargs = {"retention_adapter": KeepB()} if retention else {}
    baseline, original = account(report, **kwargs)
    kwargs = {"retention_adapter": KeepB()} if retention else {}
    result, evidence = account(report, adapter(report, mode=mode), **kwargs)
    assert evidence == original
    np.testing.assert_array_equal(result.equity, baseline.equity)


# Negative stock forecasts deny every new purchase without inventing funding or shares.
def test_denied_new_buys_leave_the_account_in_cash():
    report = report_fixture()
    means = np.full(report.panel.close.shape, -0.02)
    result, evidence = account(report, adapter(report, means))
    np.testing.assert_array_equal(result.equity, np.ones(len(result.dates)))
    fills = [e for e in evidence["events"] if e["type"] == "fill_batch"]
    assert all(sum(e["notional"]) == 0 for e in fills)
    assert all(not any(e["positions_after"]) for e in fills)


# A marginal purchase forecast stops additions while preserving already owned A shares.
def test_buy_block_is_not_a_liquidation_and_grade_c_still_exits():
    report = report_fixture()
    means = np.full(report.panel.close.shape, 0.02)
    means[25:] = 0.0
    _, evidence = account(report, adapter(report, means))
    decisions = [e for e in evidence["events"] if e["type"] == "decision"]
    blocked = [e for e in decisions if 25 <= e["session_index"] < 70]
    assert blocked
    assert all(
        "AAA" not in e["metadata"]["cash_selection"]["cash_exit"] for e in blocked
    )
    marks = [e for e in evidence["events"] if e["type"] == "mark"]
    owned = [e["positions"][0] for e in marks if 26 <= e["session_index"] < 70]
    assert min(owned) > 0
    assert max(owned) == pytest.approx(min(owned))
    assert next(e for e in marks if e["session_index"] == 71)["positions"][1] == 0


# A held A proposes an exact exit; buys use pre-sale cash, not the proposed sale.
def test_covered_cash_exit_fills_and_reconciles():
    report = report_fixture()
    means = np.full(report.panel.close.shape, 0.02)
    means[25:, 0] = -0.02
    hook = adapter(report, means)
    _, evidence = account(report, hook, retention_adapter=KeepB())
    proposals = [e for e in hook.events if e["symbol"] == "AAA" and e["day"] == 25]
    assert proposals[0]["cash_exit_shares"] > 0
    fills = [e for e in evidence["events"] if e["type"] == "fill_batch"]
    first = next(
        e
        for e in fills
        if e["session_index"] == 26
        and e["positions_before"][0] > e["positions_after"][0]
    )
    assert first["positions_after"][0] == 0
    for event in fills:
        if event["gross_buys"] > 0:
            assert event["buy_budget"] <= event["cash_before"] + 1e-12
            assert event["phase"] == "open"
        assert np.min(event["positions_after"]) >= -1e-12
    assert any(e["reason"] == "forecast_cash_exit" for e in hook.events)


# Purchase veto alone blocks additions but does not create a discretionary A exit.
def test_buy_only_keeps_held_a_while_joint_cash_exit_removes_it():
    report = report_fixture()
    means = np.full(report.panel.close.shape, 0.02)
    means[25:, 0] = -0.02
    hook = adapter(report, means, mode="buy_only")
    _, evidence = account(report, hook)
    marks = {e["session_index"]: e for e in evidence["events"] if e["type"] == "mark"}
    assert marks[25]["positions"][0] > 0
    assert marks[26]["positions"][0] == marks[25]["positions"][0]
    assert all(e["cash_exit_shares"] == 0 for e in hook.events)
    assert any(e["symbol"] == "AAA" and e["no_buy"] for e in hook.events)


# Exit-only can buy an unheld candidate but cannot repurchase its own exit.
def test_exit_only_cannot_rebuy_its_covered_exit_same_decision():
    report = report_fixture()
    means = np.full(report.panel.close.shape, -0.02)
    hook = adapter(report, means, mode="exit_only")
    _, evidence = account(report, hook)
    fills = [e for e in evidence["events"] if e["type"] == "fill_batch"]
    assert any(e["gross_buys"] > 0 for e in fills)
    proposals = {(e["day"], e["symbol"]): e for e in hook.events}
    decisions = [e for e in evidence["events"] if e["type"] == "decision"]
    covered = 0
    for event in decisions:
        for column, name in enumerate(report.panel.tickers):
            row = proposals.get((event["session_index"], name))
            if row and row["cash_exit_shares"] > 0:
                covered += 1
                assert row["no_buy"] is True
                assert event["submitted_units"][column] == 0
        assert set(
            event["metadata"].get("cash_selection", {}).get("no_buy", [])
        ) == set(event["metadata"].get("cash_selection", {}).get("cash_exit", []))
    assert covered > 0
    for event in fills:
        if event["gross_buys"] > 0:
            assert event["buy_budget"] <= event["cash_before"] + 1e-12
    assert any(e["reason"] == "forecast_cash_exit" for e in hook.events)


# Quantity control preserves purchase permission even for a negative mean forecast.
def test_quantity_control_never_creates_discretionary_masks():
    report = report_fixture()
    means = np.full(report.panel.close.shape, -0.02)
    hook = adapter(report, means, mode="quantity_control")
    _, evidence = account(report, hook)
    assert any(
        e["type"] == "fill_batch" and e["gross_buys"] > 0 for e in evidence["events"]
    )
    assert all(not e["no_buy"] and e["cash_exit_shares"] == 0 for e in hook.events)
    assert all(
        "cash_selection" not in e["metadata"]
        for e in evidence["events"]
        if e["type"] == "decision"
    )


# Ordinary tiny exit proposals survive the trade floor but green-open deferral remains.
def test_cash_exit_respects_actual_execution_green_open_gate():
    report = report_fixture()
    means = np.full(report.panel.close.shape, 0.02)
    means[25:, 0] = -0.02
    prices = report.panel.open.copy()
    prices[26, 0] = 101.0
    report = replace(report, panel=replace(report.panel, open=prices))
    _, evidence = account(report, adapter(report, means), green_day_skip=True)
    marks = {e["session_index"]: e for e in evidence["events"] if e["type"] == "mark"}
    assert marks[26]["positions"][0] > 0
    assert marks[27]["positions"][0] == 0


# Model permission cannot cancel a scheduled concentration reduction below the floor.
@pytest.mark.parametrize("forecast", [0.0, 0.02])
@pytest.mark.parametrize("mode", MODES)
def test_blocked_add_preserves_small_scheduled_reduction(monkeypatch, forecast, mode):
    report = report_fixture()
    recorded = []
    observe = simulate._Book.observe_decision

    # Supply a small incumbent trim after acquiring a fully covered A holding.
    def allocator(_report, panel, config, t):
        target = np.zeros(len(panel.tickers))
        target[0] = 0.25 if t < 40 else 0.2495
        return target

    # Retain the real submitted quantities before execution rather than mocking fills.
    def capture(book, t, order, *args, **kwargs):
        if t == 40:
            recorded.append(
                (book.shares[0], order[0], book.equity(report.panel.adj_close[t]))
            )
        return observe(book, t, order, *args, **kwargs)

    monkeypatch.setattr(simulate._Book, "observe_decision", capture)
    means = np.full(report.panel.close.shape, 0.02)
    means[40:] = forecast
    account(report, adapter(report, means, mode=mode), allocator=allocator)
    held, wanted, nav = recorded[0]
    assert wanted < held
    assert wanted <= 0.2495 * nav / 100


# FOMC owns its cut/restore cycle and bypasses favorable or unfavorable model rows.
@pytest.mark.parametrize("mode", MODES)
def test_event_cycle_bypasses_discretionary_selection(mode):
    report = report_fixture()
    exposure = np.ones(len(report.panel.dates))
    exposure[24:43] = 0.5
    means = np.full(report.panel.close.shape, 0.02)
    means[24:44] = -0.2
    hook = adapter(report, means, mode=mode)
    account(report, hook, event_lifecycle=True, event_exposure=exposure)
    assert not any(24 <= e["day"] <= 43 for e in hook.events)


# Altering future predictions cannot change preceding decisions or fills.
@pytest.mark.parametrize("mode", MODES)
def test_account_prefix_invariance(mode):
    report = report_fixture()
    means = np.full(report.panel.close.shape, 0.02)
    _, first = account(report, adapter(report, means, mode=mode))
    means[31:] = -0.2
    _, second = account(report, adapter(report, means, mode=mode))
    old = [e for e in first["events"] if e.get("session_index", 999) <= 30]
    new = [e for e in second["events"] if e.get("session_index", 999) <= 30]
    assert old == new


# Same-sized forecasts on a different clock or cost cannot be used by the account.
@pytest.mark.parametrize("field", ["dates", "cost_bps", "symbols"])
def test_forecast_identity_mismatch_refuses(field):
    report = report_fixture()
    changes = {
        "dates": report.panel.dates + np.timedelta64(1, "D"),
        "cost_bps": 25,
        "symbols": tuple(reversed(report.panel.tickers)),
    }
    with pytest.raises(ValueError, match="identity"):
        account(report, adapter(report, **{field: changes[field]}))


# Unsupported research overlays must not silently bypass the new selection hook.
@pytest.mark.parametrize(
    "changes",
    [
        {"midcycle_sweep": True},
        {"trend_brake": True},
        {"use_exits": True},
        {"live_midcycle": False},
        {"midcycle_entries": "target"},
        {"exit_at_close": False, "deferred_buys": False},
        {"event_exposure": np.ones(320) * 0.5, "event_lifecycle": False},
    ],
)
def test_unsupported_purchase_paths_refuse(changes):
    report = report_fixture()
    with pytest.raises(ValueError, match="ordinary tested"):
        account(report, adapter(report), **changes)
