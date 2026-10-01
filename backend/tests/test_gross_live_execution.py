"""Research gross changes take precedence over ordinary mid-cycle execution."""

from dataclasses import asdict, replace

import numpy as np
import pytest

from backend.agents.trading.desk import simulate
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot
from backend.tests.test_trading_simulate import _report


# Hold two equal positions; the other half of capital remains cash.
def _allocate(*args):
    return np.array([0.25, 0.25, 0.0, 0.0, 0.0, 0.0])


# Drive the real simulator with the legacy live flags and idle-cash redeployment.
def _run(path=None, *, green=False, cost_bps=0.0, **overrides):
    report = _report(np.full((60, 6), 100.0))
    if green:
        opens = report.panel.open.copy()
        opens[11, :2] = 101.0
        report.panel = replace(report.panel, open=opens)
    options = {**simulate.LIVE_POLICY, "midcycle_redeploy": True, **overrides}
    return simulate.run(
        report,
        allocator=_allocate,
        use_exits=False,
        rebalance=20,
        cost_bps=cost_bps,
        gross_path=path,
        **options,
    )


# Fill a risk cut next open, even on a green open, without waiting for reset.
@pytest.mark.parametrize("gross", [0.0, 0.5])
@pytest.mark.parametrize("green", [False, True])
def test_midcycle_risk_cut_is_not_overwritten_or_green_skipped(gross, green):
    path = np.ones(60)
    path[10:] = gross
    result = _run(path, green=green)
    assert result.invested[10] == pytest.approx(0.5)
    equity = 1.0 + (0.5 * (1.0 - gross) * 0.01 if green else 0.0)
    assert result.equity[11] == pytest.approx(equity)
    assert result.invested[11] == pytest.approx(0.5 * gross / equity)
    np.testing.assert_allclose(result.invested[11:20], result.invested[11])


# Successive cuts are relative; cash and re-entry need not wait for reset.
def test_repeated_cuts_and_reentry_preserve_the_requested_gross():
    path = np.ones(60)
    path[10:12] = 0.5
    path[12:14] = 0.25
    path[14:16] = 0.0
    path[16:] = 0.5
    result = _run(path)
    assert result.invested[11] == pytest.approx(0.25)
    assert result.invested[13] == pytest.approx(0.125)
    assert result.invested[15] == 0.0
    assert result.invested[17] == pytest.approx(0.25)
    assert result.invested[21] == pytest.approx(0.25)


# An inert path leaves all existing live-flag research returns and trades unchanged.
def test_all_ones_preserves_the_legacy_control():
    control, inert = _run(), _run(np.ones(60))
    np.testing.assert_array_equal(control.returns, inert.returns)
    np.testing.assert_array_equal(control.equity, inert.equity)
    assert len(control.trades) == len(inert.trades)
    for original, repeated in zip(control.trades, inert.trades, strict=True):
        a, b = asdict(original), asdict(repeated)
        np.testing.assert_equal(a.pop("weight"), b.pop("weight"))
        assert a == b


# A future risk-path change cannot alter earlier holdings or returns.
def test_gross_changes_are_chronological():
    original = np.ones(60)
    changed = original.copy()
    changed[30:] = 0.0
    before, after = _run(original), _run(changed)
    np.testing.assert_array_equal(before.returns[:31], after.returns[:31])
    np.testing.assert_array_equal(before.invested[:31], after.invested[:31])
    assert after.invested[31] == 0.0


# The early-return FOMC lifecycle cannot silently swallow a second risk controller.
def test_uncoordinated_event_lifecycle_is_refused():
    path = np.ones(60)
    path[10:] = 0.5
    with pytest.raises(ValueError, match="gross_path.*event_lifecycle"):
        _run(path, event_lifecycle=True, event_exposure=np.full(60, 0.5))


# Reconcile every closing value and fee independently across cuts and recovery.
@pytest.mark.parametrize("cost_bps", [25.0, 100.0])
def test_risk_changes_reconcile_fees_and_cash_through_the_journal(cost_bps):
    report = _report(np.full((60, 6), 100.0))
    panel = report.panel
    journal = ResearchJournal(
        panel.dates,
        panel.tickers,
        simulate.adjusted_open(panel),
        panel.adj_close,
        run_id="gross-execution-regression",
        account_id="synthetic",
        policy_id="synthetic-gross/1",
        cost_bps=cost_bps,
        provenance={"evidence_basis": "synthetic-accounting-test"},
    )
    path = np.ones(60)
    path[10:12] = 0.5
    path[12:14] = 0.0
    result = _run(path, cost_bps=cost_bps, journal=journal)
    replayed = verify_snapshot(journal.snapshot(), include_phase_states=True)
    assert replayed["ok"], replayed["errors"]
    assert replayed["accounting_verified"]
    assert replayed["adoption_eligible"] is False
    np.testing.assert_allclose(
        [mark["nav"] for mark in replayed["marks"]], result.equity,
        rtol=1e-12, atol=1e-12,
    )
    assert replayed["total_fees"] > 0
    assert replayed["total_fees"] == pytest.approx(
        replayed["total_traded"] * cost_bps / 1e4
    )
    assert result.equity[-1] == pytest.approx(1.0 - replayed["total_fees"])
    assert all(mark["cash"] >= -1e-12 for mark in replayed["marks"])
    fills = [s for s in replayed["phase_states"] if s["type"] == "fill_batch"]
    for session in (11, 13, 15):
        active = [s for s in fills if s["session_index"] == session and s["traded"] > 0]
        assert active
        assert all(s["phase"] == "open" for s in active)


# An intervening cash cut cancels an unfunded reset basket before a new recovery.
def test_cash_cut_discards_old_unfunded_buys_before_recovery():
    report = _report(np.full((60, 6), 100.0), grades=np.full((60, 6), 2))
    panel = report.panel

    # Rotate into a different pair, then change the desired pair before recovery.
    def allocate(report, panel, config, t):
        if 20 <= t < 23:
            return np.array([0.0, 0.0, 0.5, 0.5, 0.0, 0.0])
        return np.array([0.5, 0.5, 0.0, 0.0, 0.0, 0.0])

    journal = ResearchJournal(
        panel.dates, panel.tickers, simulate.adjusted_open(panel), panel.adj_close,
        run_id="gross-deferred-regression", account_id="synthetic",
        policy_id="synthetic-gross/1", cost_bps=0.0,
        provenance={"evidence_basis": "synthetic-accounting-test"},
    )
    path = np.ones(60)
    path[21:23] = 0.0
    result = simulate.run(
        report, allocator=allocate, use_exits=False, rebalance=20, cost_bps=0.0,
        gross_path=path, journal=journal, midcycle_redeploy=True,
        **simulate.LIVE_POLICY,
    )
    decisions = {
        e["session_index"]: e for e in journal.snapshot()["events"]
        if e["type"] == "decision"
    }
    assert decisions[20]["metadata"]["deferred_units"]
    assert decisions[21]["metadata"]["deferred_units"] == {}
    assert decisions[23]["metadata"]["deferred_units"] == {}
    replayed = verify_snapshot(journal.snapshot())
    assert replayed["ok"], replayed["errors"]
    assert result.invested[22] == 0.0
    assert result.invested[24] == pytest.approx(1.0)
    for mark in replayed["marks"][24:40]:
        assert mark["positions"][2:4] == [0.0, 0.0]
        assert mark["cash"] >= -1e-12
