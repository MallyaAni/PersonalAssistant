"""Event windows use past evidence and the real simulator's costs and fills."""

from datetime import date

import numpy as np
import pytest

from backend.agents.trading.desk import event_risk, simulate
from backend.cli.market_fomc import ResearchStore
from backend.market.store import MarketStore
from backend.tests.test_trading_simulate import _report


# Protect the chosen pre-meeting days plus the meeting; release at the next open.
def test_event_window_is_a_close_decision_for_the_next_session():
    report = _report(np.full((20, 6), 100.0))
    decision = report.panel.dates[12].astype(object)
    path = event_risk.exposure_path(report.panel, [decision], 3)
    np.testing.assert_array_equal(np.flatnonzero(path < 1), [8, 9, 10, 11])


# Future prices cannot affect earlier decisions; weakness latches through the event.
def test_weakness_gate_is_causal_and_does_not_churn_on_a_rebound():
    prices = np.full((20, 6), 100.0)
    prices[9, -1] = 99
    prices[10:, -1] = 101
    report = _report(prices)
    decision = report.panel.dates[12].astype(object)
    path = event_risk.exposure_path(report.panel, [decision], 3, require_weakness=True)
    np.testing.assert_array_equal(np.flatnonzero(path < 1), [9, 10, 11])
    prices[11:] = 1
    changed = event_risk.exposure_path(
        _report(prices).panel, [decision], 3, require_weakness=True
    )
    np.testing.assert_array_equal(path[:11], changed[:11])


# A half-exposure window cuts once, restores once and pays the actual fill costs.
def test_simulator_reduces_once_and_restores_after_the_window():
    report = _report(np.full((20, 6), 100.0))
    scale = np.ones(20)
    scale[5:10] = 0.5

    # A fixed full allocation isolates exposure from grading and volatility estimates.
    def allocation(report, panel, config, t):
        return np.asarray([0.5, 0, 0, 0, 0, 0])

    base = simulate.run(
        report, allocator=allocation, rebalance=20, use_exits=False, cost_bps=10
    )
    cut = simulate.run(
        report,
        allocator=allocation,
        rebalance=20,
        use_exits=False,
        cost_bps=10,
        event_exposure=scale,
    )
    np.testing.assert_allclose(cut.invested[6:11], cut.invested[6], atol=1e-9)
    assert 0.24 < cut.invested[6] < 0.26
    assert 0.49 < cut.invested[11] < 0.51
    assert cut.traded > base.traded
    assert cut.equity[-1] < base.equity[-1]
    np.testing.assert_array_equal(cut.equity[:6], base.equity[:6])


# Invalid scales cannot silently introduce leverage or an unknown order.
def test_event_overlay_rejects_invalid_inputs():
    report = _report(np.full((20, 6), 100.0))
    with pytest.raises(ValueError, match="predeclared"):
        event_risk.exposure_path(report.panel, [date(2026, 9, 16)], 2)
    with pytest.raises(ValueError, match="Event exposure"):
        simulate.run(report, use_exits=False, event_exposure=np.full(20, np.nan))


# A disabled event overlay is identical to the live policy, including its fill timing.
def test_disabled_overlay_preserves_the_live_policy_exactly():
    report = _report()
    base = simulate.run(report, use_exits=False, **simulate.LIVE_POLICY)
    disabled = simulate.run(
        report,
        use_exits=False,
        event_exposure=np.ones(len(report.panel.dates)),
        **simulate.LIVE_POLICY,
    )
    np.testing.assert_array_equal(base.equity, disabled.equity)
    np.testing.assert_array_equal(base.invested, disabled.invested)
    assert base.traded == disabled.traded


# A nested loader that forgets asof still cannot read a later extraction partition.
def test_research_snapshot_bounds_nested_readers(tmp_path):
    store = MarketStore(tmp_path)
    before, later = date(2026, 9, 11), date(2026, 9, 13)
    store.write_frame("edgar_tone", before, "AAA", {"value": [1]}, {})
    store.write_frame("edgar_tone", later, "AAA", {"value": [9]}, {})
    pinned = ResearchStore(tmp_path, before)
    assert pinned.read_frame("edgar_tone", "AAA")[0]["value"] == [1]
    assert pinned.read_frame("edgar_tone", "AAA", later)[0]["value"] == [1]


# The adopted lifecycle postpones a due rebalance until the event's shares are restored.
def test_event_lifecycle_defers_rebalance_without_repeated_scaling():
    report = _report(np.full((24, 6), 100.0))
    scale = np.ones(24)
    scale[4:9] = 0.5
    decisions = []

    # Record the actual rebalance sessions alongside a constant allocation.
    def allocation(report, panel, config, t):
        decisions.append(t)
        return np.asarray([0.5, 0, 0, 0, 0, 0])

    result = simulate.run(
        report,
        allocator=allocation,
        rebalance=5,
        use_exits=False,
        cost_bps=10,
        event_exposure=scale,
        event_lifecycle=True,
    )
    assert decisions == [0, 10, 15, 20]
    np.testing.assert_allclose(result.invested[5:10], result.invested[5], atol=1e-9)
    assert 0.49 < result.invested[10] < 0.51


# Era reporting slices one equity path and does not manufacture a new cash account.
def test_evaluation_eras_preserve_the_boundary_equity():
    from types import SimpleNamespace

    result = SimpleNamespace(
        dates=np.asarray(
            ["2026-06-16", "2026-06-17", "2026-06-18", "2026-06-22", "2026-07-29"],
            dtype="datetime64[D]",
        ),
        equity=np.asarray([100, 105, 110, 99, 121]),
    )
    before, after = event_risk.evaluation_slices(result)
    assert before["total_return"] == pytest.approx(0.05)
    assert after["total_return"] == pytest.approx(121 / 105 - 1)
    assert after["since"] == "2026-06-18"
    assert after["base_session"] == "2026-06-17"
    assert after["drawdown"] == pytest.approx(0.1)
    assert after["completed_meetings"] == ["2026-07-29"]
