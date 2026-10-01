"""Funded resets honor policy targets, not the unrelated mid-cycle entry cap."""

import numpy as np
import pytest

from backend.agents.trading.desk import grading, live_policy, paper, planner


# Build the active policy's targets with equal-priced eligible names and SPY.
def _targets(count):
    names = [f"NAME{i}" for i in range(count)]
    weights = live_policy.POLICY.targets(
        np.full(count + 1, grading.ORDINAL[grading.A]),
        np.full(count + 1, 100.0),
        np.ones(count + 1, dtype=bool),
        count,
    )
    return dict(zip(names, weights[:-1], strict=True))


# The real funded paper reset matches the shared planner after whole-share funding.
@pytest.mark.parametrize("count", [1, 4, 5, 6, 7])
@pytest.mark.parametrize("cash", [100_000.0, 20_000.0])
def test_funded_reset_preserves_the_active_policys_buy_sizes(count, cash):
    targets = _targets(count)
    prices = dict.fromkeys(targets, 100.0)
    grades = dict.fromkeys(targets, "A")
    moves = planner.plan(targets, {}, 100_000.0, prices)
    rounded = {o.symbol: round(o.qty) for o in moves}
    requested = sum(rounded.values()) * 100.0
    scale = min(1.0, cash / requested)
    expected = {s: int(np.floor(q * scale + 1e-10)) for s, q in rounded.items()}
    orders, state, what = paper.plan(
        "2026-09-30",
        paper.PaperState(),
        100_000.0,
        {},
        prices,
        targets,
        grades,
        cash=cash,
    )
    assert what == "rebalance"
    assert {o.symbol: o.qty for o in orders} == expected
    assert state.deferred_buys == {
        s: rounded[s] - q for s, q in expected.items() if rounded[s] > q
    }
    assert sum(o.qty * prices[o.symbol] for o in orders) <= cash
    assert all(o.qty == int(o.qty) for o in orders)


# Reset additions above 15% remain permitted, but unfunded sells buy nothing now.
def test_reset_additions_use_targets_and_only_existing_cash():
    orders, state, _ = paper.plan(
        "2026-09-30",
        paper.PaperState(),
        100_000.0,
        {"AAA": 200.0, "OLD": 700.0},
        {"AAA": 100.0, "OLD": 100.0},
        {"AAA": 0.25},
        {"AAA": "A", "OLD": "C"},
        cash=10_000.0,
    )
    assert {(o.symbol, o.side, o.qty) for o in orders} == {
        ("AAA", "buy", 50),
        ("OLD", "sell", 700),
    }
    assert state.deferred_buys == {}
    unfunded, state, _ = paper.plan(
        "2026-09-30",
        paper.PaperState(),
        100_000.0,
        {"OLD": 1000.0},
        {"AAA": 100.0, "OLD": 100.0},
        {"AAA": 0.25},
        {"AAA": "A", "OLD": "C"},
        cash=0.0,
    )
    assert [(o.symbol, o.side, o.qty) for o in unfunded] == [("OLD", "sell", 1000)]
    assert state.deferred_buys == {"AAA": 250.0}


# Blocking a reset buy is still a deliberate gate, not a deferred cash shortfall.
def test_target_sizing_does_not_bypass_the_reset_band_gate():
    orders, state, _ = paper.plan(
        "2026-09-30",
        paper.PaperState(),
        100_000.0,
        {},
        {"AAA": 100.0, "BBB": 100.0},
        {"AAA": 0.25, "BBB": 0.25},
        {"AAA": "A", "BBB": "A"},
        cash=100_000.0,
        entry_blocked={"AAA"},
    )
    assert [(o.symbol, o.qty) for o in orders] == [("BBB", 250)]
    assert state.deferred_buys == {}


# Default entry bounding keeps its 15% ceiling even when a reset can target 25%.
def test_midcycle_entry_cap_is_unchanged():
    order = paper.PaperOrder("AAA", "buy", 250, "price entry")
    actual = paper.bound_orders([order], {}, {"AAA": 100.0}, 100_000.0, 100_000.0)
    assert actual[0].qty == 150


# A funded reset keeps nearest-share rounding for a deliberately smaller target.
def test_funded_reset_keeps_existing_nearest_share_rounding():
    orders, _, _ = paper.plan(
        "2026-09-30",
        paper.PaperState(),
        100_000.0,
        {},
        {"AAA": 1740.0},
        {"AAA": 0.049},
        {"AAA": "A"},
        cash=100_000.0,
    )
    assert orders[0].qty == 3
