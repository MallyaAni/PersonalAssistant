"""Prior-close daily plans, covered cash execution and fee-inclusive books."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import policy_v5
from backend.market import daily_bridge_replay as m


# Build a supplied daily stock-and-benchmark grid without providers or model fits.
def inputs(rows=5):
    prices = np.full((rows, 4), 10.0)
    panel = SimpleNamespace(
        dates=np.busday_offset(np.datetime64("2026-01-02"), np.arange(rows)),
        tickers=("X", "Y", "SPY", "QQQ"),
        open=prices.copy(),
        close=prices.copy(),
        adj_close=prices.copy(),
    )
    grades = np.full(prices.shape, 2)
    return panel, grades, np.ones(prices.shape, bool), np.full(prices.shape, np.nan)


# Run the unmodified equal target rule at the separately declared daily clock.
def run(values, *, cost=0, first=0, method="equal"):
    return m.run_account(*values, first=first, cost_bps=cost, method=method)


# The initial anchor is cash NAV1, and no final-close plan is fictitiously filled.
def test_common_anchor_and_pending_last_close_plan():
    result = run(inputs())
    assert result["nav"][0] == result["cash"][0] == 1
    assert not result["shares"][0].any()
    np.testing.assert_allclose(result["shares"][1:, :2], 0.025)
    np.testing.assert_allclose(result["cash"][1:], 0.5)
    assert result["counts"]["plans"] == len(result["dates"])
    assert result["pending_plan"]["decision_session"] == str(result["dates"][-1])
    assert all(
        row["execution_session"] > row["decision_session"]
        for row in result["intent_trace"]
    )
    assert not result["shares"][:, 2:].any()


# A gap alters the realized cost, never the submitted prior-close share quantity.
def test_share_quantities_are_frozen_before_opening_gap():
    values = inputs(3)
    values[0].open[1, 0] = 20
    result = run(values)
    intent = next(row for row in result["intent_trace"] if row["symbol"] == "X")
    assert intent["requested_delta"] == pytest.approx(0.025)
    assert intent["filled_delta"] == pytest.approx(0.025)
    assert result["allocation_trace"][0]["prices"][0] == 10
    assert result["shares"][1, 0] == pytest.approx(0.025)
    assert result["cost_basis"][1, 0] == pytest.approx(0.5)


# Opening sales are credited to carried cash but unavailable to that plan's buys.
def test_same_plan_sale_proceeds_do_not_fund_buys():
    plan = {
        "submitted_delta": np.array([-1.0, 1.0]),
        "cash_budget": 0.0,
        "decision_session": "2026-01-02",
    }
    shares, basis, realized, cashflows = (
        np.array([1.0, 0.0]),
        np.array([10.0, 0.0]),
        np.zeros(2),
        np.zeros(2),
    )
    cash, fees, _, intents = m._execute(
        plan,
        np.array([20.0, 10.0]),
        shares,
        0.0,
        basis,
        realized,
        cashflows,
        0.001,
        ("X", "Y"),
        "2026-01-05",
    )
    assert cash == pytest.approx(19.98)
    assert fees == pytest.approx(0.02)
    np.testing.assert_array_equal(shares, [0, 0])
    assert realized[0] == pytest.approx(9.98)
    assert intents[1]["status"] == "cash_limited"
    assert intents[1]["filled_delta"] == 0


# Missing openings preserve exact missed intents and expire without an intra-plan retry.
def test_missing_open_is_unfilled_and_next_day_has_new_identity():
    values = inputs(4)
    values[0].open[1, 0] = np.nan
    result = run(values)
    rows = [row for row in result["intent_trace"] if row["symbol"] == "X"]
    assert rows[0]["status"] == "missing_open"
    assert rows[0]["price"] is None
    assert rows[0]["filled_delta"] == 0
    assert rows[0]["expires_after_open"]
    assert rows[1]["id"] != rows[0]["id"]
    assert rows[1]["execution_session"] == str(values[0].dates[2])
    assert result["counts"]["missing_open"] == 1


# Fee-inclusive average basis survives a partial exit and reconciles realized profit.
def test_average_basis_and_profit_reconcile_after_partial_exit():
    names = ("X",)
    shares, basis, realized, cashflows = (np.zeros(1) for _ in range(4))
    cash = 100.0
    for requested, price in ((2.0, 10.0), (1.0, 20.0), (-1.5, 30.0)):
        plan = {
            "submitted_delta": np.array([requested]),
            "cash_budget": cash,
            "decision_session": "2026-01-02",
        }
        cash, _, _, _ = m._execute(
            plan,
            np.array([price]),
            shares,
            cash,
            basis,
            realized,
            cashflows,
            0.01,
            names,
            "2026-01-05",
        )
    assert shares[0] == 1.5
    assert basis[0] == pytest.approx(20.2)
    assert realized[0] == pytest.approx(45 * 0.99 - 20.2)
    assert cash + shares[0] * 30 - 100 == pytest.approx(realized[0] + 45 - basis[0])


# Buy funding scales known quantities to original cash including all per-side fees.
def test_joint_known_purchases_are_cash_scaled_after_fees():
    plan = {
        "submitted_delta": np.array([1.0, 2.0]),
        "cash_budget": 10.0,
        "decision_session": "2026-01-02",
    }
    shares, basis, realized, cashflows = (np.zeros(2) for _ in range(4))
    cash, fees, _, rows = m._execute(
        plan,
        np.array([10.0, 10.0]),
        shares,
        10.0,
        basis,
        realized,
        cashflows,
        0.01,
        ("X", "Y"),
        "2026-01-05",
    )
    assert cash == pytest.approx(0, abs=1e-12)
    np.testing.assert_allclose(shares, [1 / 3.03, 2 / 3.03])
    assert fees == pytest.approx(10 / 1.01 * 0.01)
    assert sum(basis) == pytest.approx(10)
    assert all(row["status"] == "cash_limited" for row in rows)


# An unavailable held close must fail instead of inventing an end mark or NAV.
@pytest.mark.parametrize("day", [1, 3])
def test_missing_held_marks_refuse_account(day):
    values = inputs(4)
    values[0].adj_close[day, 0] = np.nan
    if day == 1:
        # Keep the open available so a held missing close is genuinely exercised.
        values[0].close[day, 0] = np.nan
        with pytest.raises(ValueError, match="Held close"):
            m._nav(
                0.5,
                np.array([0.025, 0, 0, 0]),
                values[0].adj_close[day],
                values[0].tickers,
            )
    else:
        with pytest.raises(ValueError, match="Held close"):
            run(values)


# Full-account future prices and grades cannot change already observed plans or states.
def test_future_prefix_invariance():
    values = inputs(6)
    before = run(values, cost=10)
    values[0].open[4:, :2] *= 3
    values[0].close[4:, :2] *= 3
    values[0].adj_close[4:, :2] *= 3
    values[1][4:, :2] = 0
    after = run(values, cost=10)
    for key in ("nav", "cash", "shares", "cost_basis", "realized_profit", "fees"):
        np.testing.assert_array_equal(before[key][:4], after[key][:4])
    for day in range(4):
        np.testing.assert_array_equal(
            before["allocation_trace"][day]["submitted_delta"],
            after["allocation_trace"][day]["submitted_delta"],
        )


# Risk allocation sees a causal prefix and one-session arithmetic units.
def test_risk_wrapper_units_prefix_and_unavailable_no_adds(monkeypatch):
    values = inputs(255)
    calls = []

    # Capture only supplied arrays and preserve the carried account as unavailable.
    def unavailable(
        history, grades, eligible, means, current, cash, cost, benchmark, **kwargs
    ):
        calls.append((history.copy(), grades.copy(), means.copy(), kwargs))
        return current.copy(), {"status": "unavailable"}

    monkeypatch.setattr(m.adaptive_growth_policy, "allocate", unavailable)
    result = run(values, first=252, method="calibrated")
    assert [len(call[0]) for call in calls] == [253, 254, 255]
    assert all(
        call[3] == {"mean_units": "arithmetic", "horizon_sessions": 1} for call in calls
    )
    np.testing.assert_array_equal(result["nav"], 1)
    assert not result["shares"].any()
    assert result["counts"]["allocator_unavailable"] == 3


# Existing targets are reused exactly while benchmarks remain excluded from stocks.
def test_equal_rule_targets_match_existing_policy():
    values = inputs()
    values[1][0, 1] = 1
    result = run(values)
    mask = values[2][0].copy()
    mask[2:] = False
    expected = policy_v5.targets(values[1][0], values[0].adj_close[0], mask, 2)
    np.testing.assert_array_equal(result["allocation_trace"][0]["targets"], expected)


# Benchmark references share the anchor, opening cost and terminal closing mark.
def test_benchmark_matched_clock_cost_and_profit():
    values = inputs(4)
    values[0].adj_close[1:, 2] = [10, 11, 12]
    values[0].close[1:, 2] = [10, 11, 12]
    reference = m.benchmark_account(values[0], ticker="SPY", cost_bps=25, first=0)
    assert reference["nav"][0] == reference["cash"][0] == 1
    assert reference["nav"][-1] == pytest.approx(1.2 / 1.0025)
    assert reference["fees"][1] == pytest.approx(0.0025 / 1.0025)
    assert reference["stocks"]["SPY"]["unrealized_profit"] == pytest.approx(
        reference["nav"][-1] - 1
    )
    assert not reference["realized_profit"].any()


# Full records reconcile compounded NAV with every name's realized and unrealized gain.
def test_fee_inclusive_full_account_stock_reconciliation():
    values = inputs(5)
    values[0].open[2:, :2] = 12
    values[0].close[2:, :2] = 12
    values[0].adj_close[2:, :2] = 12
    values[1][3:, 0] = 0
    result = run(values, cost=25)
    contribution = sum(
        stock["net_gain_initial_nav_units"] for stock in result["stocks"].values()
    )
    assert contribution == pytest.approx(result["nav"][-1] - 1)
    for day in range(len(result["dates"])):
        mark = values[0].adj_close[day]
        assert result["nav"][day] == pytest.approx(
            result["cash"][day] + result["shares"][day] @ mark
        )
    assert result["realized_profit"][-1, 0] != 0
    assert result["cost_basis"][-1, 0] == 0


# Ambiguous anchors and missing risk history fail before any account is evaluated.
@pytest.mark.parametrize("first", [True, -1, 4])
def test_invalid_anchor_rejected(first):
    with pytest.raises(ValueError, match="anchor"):
        run(inputs(), first=first)


# Refuse missing risk history without switching an arm to equal targets.
def test_risk_requires_prior_context():
    with pytest.raises(ValueError, match="253 completed"):
        run(inputs(), method="mean")


# Both risk arms exercise the real certified allocator without retraining forecasts.
def test_actual_arithmetic_allocator_carried_accounts():
    values = inputs(255)
    day = np.arange(255)[:, None]
    price = 10 * np.exp(
        0.0005 * day + np.sin(day / 13) * np.array([[0.01, 0.02, 0.03, 0.04]])
    )
    for field in ("open", "close", "adj_close"):
        setattr(values[0], field, price.copy())
    values[3][:] = 0.002
    calibrated = run(values, method="calibrated", first=252, cost=10)
    mean = run(values, method="mean", first=252, cost=10)
    assert calibrated["allocation_trace"][0]["receipt"]["mean_units"] == "arithmetic"
    assert calibrated["allocation_trace"][0]["receipt"]["horizon_sessions"] == 1
    assert calibrated["shares"][1, :2].sum() > 0
    np.testing.assert_array_equal(calibrated["nav"], mean["nav"])
    np.testing.assert_array_equal(calibrated["shares"], mean["shares"])


# An unavailable solve must preserve exact owned quantities without rounding trades.
def test_unavailable_held_forecast_preserves_exact_share_quantities():
    values = inputs(253)
    panel, grades, eligible, means = values
    means[:] = 0
    means[:, 0] = np.nan
    rng = np.random.default_rng(5)
    for _ in range(20):
        prices = rng.uniform(10, 200, 4)
        panel.adj_close[:] = prices
        held = np.r_[rng.uniform(0.001, 0.2, 2), 0.0, 0.0]
        plan = m._plan(
            panel, grades, eligible, means, "calibrated", 252, 1000.0, held, 10
        )
        assert plan["receipt"]["status"] == "unavailable"
        np.testing.assert_array_equal(plan["desired_shares"], held)
        assert not plan["submitted_delta"].any()
