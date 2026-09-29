"""An offline entry-eligibility ablation; no paper or default policy change."""
# ruff: noqa: F811 - imported pytest fixture intentionally names test arguments

import numpy as np
import pytest

from backend.agents.trading.desk import point_in_time, simulate
from backend.market import profit_taking, stage3_overlay
from backend.market.midcycle_ew import Ledger
from backend.tests.test_market_pit_scorecard import _report, history  # noqa: F401


def _orders(targets, gate):
    return simulate._variant_midcycle_orders(
        "2026-09-28",
        10000.0,
        {"EXIT": 5.0},
        {"KEEP": 100.0, "DROP": 100.0, "EXIT": 100.0},
        {"KEEP": "A+", "DROP": "A+", "EXIT": "C"},
        {"EXIT": "downgrade"},
        {"KEEP": 3.0, "DROP": 3.0},
        set(),
        9500.0,
        "breakout",
        False,
        targets,
        {},
        target_gate=gate,
    )


@pytest.mark.parametrize("weight", [0.0, -0.1, np.nan, np.inf, -np.inf, None])
def test_only_positive_finite_targets_allow_a_breakout(weight):
    targets = {"KEEP": 0.2}
    if weight is not None:
        targets["DROP"] = weight
    base = _orders(targets, False)
    gated = _orders(targets, True)
    assert any(o.symbol == "DROP" and o.side == "buy" for o in base)
    assert not any(o.symbol == "DROP" and o.side == "buy" for o in gated)
    # Eligibility does not resize the surviving buy or withhold the exit.
    for symbol in ("KEEP", "EXIT"):
        original = [(o.side, o.qty, o.reason) for o in base if o.symbol == symbol]
        changed = [(o.side, o.qty, o.reason) for o in gated if o.symbol == symbol]
        assert original == changed
        assert original


def test_gate_is_not_a_target_sizing_rule():
    small = _orders({"KEEP": 0.001, "DROP": 0.2}, True)
    large = _orders({"KEEP": 0.2, "DROP": 0.2}, True)
    assert [(o.symbol, o.qty) for o in small] == [(o.symbol, o.qty) for o in large]


def test_real_simulator_stops_excluded_name_reentry_and_preserves_default(history):
    report, mask = point_in_time.point_in_time(_report(), history)
    panel = report.panel
    grid = np.tile(np.arange(len(panel.tickers), dtype=float), (len(panel.dates), 1))
    options = profit_taking.control_options(panel)
    runs = []
    for explicit in (None, False, True):
        ledger = Ledger()
        overlay = stage3_overlay.Overlay(mask, grid)
        extra = {} if explicit is None else {"midcycle_target_gate": explicit}
        result = simulate.run(
            report,
            since=panel.dates[1].astype(object),
            cost_bps=25,
            allocator=overlay.allocator,
            journal=ledger,
            **options,
            **extra,
        )
        runs.append((result, ledger))
    assert runs[0][0].returns.tobytes() == runs[1][0].returns.tobytes()
    # AAA is always the lowest forecast and never gets a reset target.
    # On the old path it is nevertheless bought by the breakout planner.
    old_shares = [mark[1][0] for mark in runs[0][1].marks.values()]
    new_shares = [mark[1][0] for mark in runs[2][1].marks.values()]
    assert max(old_shares) > 0
    assert max(new_shares) == 0
    assert np.isfinite(runs[2][0].returns[1:]).all()


def test_future_allocator_rows_do_not_change_past_gated_results(history):
    report, mask = point_in_time.point_in_time(_report(), history)
    n = len(report.panel.dates)
    grid = np.tile(np.arange(mask.shape[1], dtype=float), (n, 1))
    changed = grid.copy()
    changed[200:] *= -1
    results = []
    for forecasts in (grid, changed):
        results.append(
            simulate.run(
                report,
                allocator=stage3_overlay.Overlay(mask, forecasts).allocator,
                midcycle_target_gate=True,
                **profit_taking.control_options(report.panel),
            )
        )
    np.testing.assert_array_equal(results[0].returns[:201], results[1].returns[:201])


def test_gate_requires_the_live_breakout_path():
    with pytest.raises(ValueError, match="require live_midcycle"):
        simulate.run(_report(), midcycle_target_gate=True)
    with pytest.raises(ValueError, match="breakout"):
        simulate.run(
            _report(),
            live_midcycle=True,
            midcycle_entries="target",
            midcycle_target_gate=True,
        )
