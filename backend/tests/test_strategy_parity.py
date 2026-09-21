"""Behavioral checks of the shared live and historical order boundary."""

import numpy as np
import pytest

from backend.agents.trading.desk import paper, simulate
from backend.tests.test_trading_simulate import _report


# A rotation and breakout reserve the same name capacity, even at awkward prices.
@pytest.mark.parametrize("price", [100.0, 103.7])
def test_combined_orders_respect_name_cap(price):
    held = {"OLD": 100, "KEEP": 14000 / price}
    orders = paper.midcycle_orders(
        "2026-09-04",
        paper.PaperState(),
        100000,
        held,
        {"OLD": 100, "KEEP": price},
        {"OLD": "B", "KEEP": "A"},
        {"OLD": "downgrade"},
        {"KEEP": 1.5},
        cash=76000,
    )
    bought = sum(o.qty for o in orders if o.symbol == "KEEP" and o.side == "buy")
    assert (held["KEEP"] + bought) * price <= 15000 + 1e-8
    assert bought > 0


# Opening buys cannot spend the proceeds of a sale due at the later close.
def test_no_cash_means_no_opening_buys():
    orders = paper.midcycle_orders(
        "2026-09-04",
        paper.PaperState(),
        100000,
        {"OLD": 100, "KEEP": 100},
        {"OLD": 100, "KEEP": 100},
        {"OLD": "B", "KEEP": "A"},
        {"OLD": "downgrade"},
        {"KEEP": 2},
        cash=0,
    )
    assert [(o.symbol, o.side) for o in orders] == [("OLD", "sell")]


# Multiple candidates share a finite budget without assuming borrowing.
def test_cash_budget_and_grade_gate_apply_together():
    orders = paper.midcycle_orders(
        "2026-09-04",
        paper.PaperState(),
        100000,
        {},
        {"A": 100, "B": 100, "C": 100},
        {"A": "A", "B": "A+", "C": "B"},
        {},
        {"A": 2, "B": 2, "C": 2},
        cash=1000,
    )
    assert {o.symbol for o in orders} == {"A", "B"}
    assert sum(o.qty * 100 for o in orders) <= 1000


# Fractional historical decisions match paper decisions before whole-share rounding.
def test_historical_midcycle_matches_shared_planner():
    report = _report(close=np.full((30, 6), 100.0))
    book = simulate._Book(
        6, 100000, 10, report.panel, report, list(map(str, report.panel.dates))
    )
    book.shares[:3] = [140, 0, 100]
    book.cash = 76000
    bands = np.full((30, 6), 1.5)
    wanted = simulate._live_midcycle(book, report, 25, bands, None)
    orders = paper.midcycle_orders(
        str(report.panel.dates[25]),
        paper.PaperState(),
        100000,
        {"N0": 140, "N2": 100},
        dict.fromkeys(report.panel.tickers, 100),
        {"N0": "A+", "N1": "A", "N2": "B"},
        {"N2": "downgrade"},
        {"N0": 1.5, "N1": 1.5},
        cash=76000,
        whole_shares=False,
    )
    expected = book.shares.copy()
    for order in orders:
        expected[report.panel.index(order.symbol)] += order.qty * (
            1 if order.side == "buy" else -1
        )
    np.testing.assert_allclose(wanted, expected)
    assert wanted[0] <= 150
    assert wanted[1] > 0
    assert wanted[2] == 0


# Enabling live policy really changes holdings after the next fill, never beforehand.
def test_full_simulator_executes_midcycle_entries(monkeypatch):
    from backend.agents.trading.desk import entry

    close = np.full((30, 6), 100.0)
    close[25:, 1] = 110
    report = _report(close=close)
    bands = np.zeros_like(close)
    bands[23, 1] = 1.5
    monkeypatch.setattr(entry, "bollinger_z", lambda values: bands)
    baseline = simulate.run(
        report, allocator=lambda *args: np.zeros(6), use_exits=False
    )
    actual = simulate.run(
        report, allocator=lambda *args: np.zeros(6), use_exits=False, live_midcycle=True
    )
    np.testing.assert_allclose(actual.equity[:24], baseline.equity[:24])
    assert actual.invested[24] > 0
    assert actual.equity[-1] > baseline.equity[-1]


# The displayed plan uses the same funded order basket rather than independent buys.
def test_dashboard_projects_the_shared_account_plan():
    from datetime import UTC, datetime

    from backend.market import decision_view

    record = {
        "session": "2026-09-04",
        "grades": {"OLD": {"grade": "B"}, "KEEP": {"grade": "A"}},
        "book": [],
        "paper": {
            "cash": 76000,
            "until_rebalance": 10,
            "positions": [
                {"symbol": "OLD", "qty": 100, "current_price": 100},
                {"symbol": "KEEP", "qty": 140, "current_price": 100},
            ],
        },
    }
    rows = {s: {"target_weight": 0} for s in record["grades"]}
    decision_view.apply_account_plan(
        rows, record, {}, {"KEEP": 1.5}, False, datetime(2026, 9, 4, tzinfo=UTC)
    )
    assert rows["OLD"]["action"] == "Sell"
    assert rows["KEEP"]["action"] == "Buy"
    assert rows["KEEP"]["move_weight"] == pytest.approx(0.01)
    assert rows["KEEP"]["current_weight"] == pytest.approx(0.14)
    record["paper"]["cash"] = 0
    decision_view.apply_account_plan(
        rows, record, {}, {"KEEP": 1.5}, False, datetime(2026, 9, 4, tzinfo=UTC)
    )
    assert rows["KEEP"]["action"] == "Hold"


# All reporting paths include an initial loss and use arithmetic excess-return Sharpe.
def test_summary_statistics_share_the_same_definition():
    from backend.market import strategy_bench

    returns = np.array([-0.1, 0.01, 0.02, 0.01, -0.01])
    bench = strategy_bench.stats(returns)
    sim = simulate.SimResult(np.arange(5), returns, np.ones(5)).stats()
    assert bench["drawdown"] == pytest.approx(-0.1)
    assert bench["sharpe"] == pytest.approx(sim["sharpe"])
    assert bench["drawdown"] == pytest.approx(sim["drawdown"])


# A reset cannot bypass the funding and whole-share cap used between resets.
def test_rebalance_is_cash_and_cap_bounded():
    orders, _, _ = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        100000,
        {},
        {"A": 103.7, "B": 100},
        {"A": 0.8, "B": 0.2},
        {"A": "A", "B": "A"},
        cash=1000,
    )
    assert sum(o.qty * {"A": 103.7, "B": 100}[o.symbol] for o in orders) <= 1000
    assert all(o.side == "buy" for o in orders)
    orders, _, _ = paper.plan(
        "2026-09-04",
        paper.PaperState(),
        100000,
        {},
        {"A": 103.7},
        {"A": 0.8},
        {"A": "A"},
        cash=100000,
    )
    assert orders[0].qty * 103.7 <= 15000
