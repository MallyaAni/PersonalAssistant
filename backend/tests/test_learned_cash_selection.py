"""Pin both cash opportunities without granting fills, funding or risk overrides."""

import numpy as np
import pytest

from backend.market.learned_cash_selection import (
    MODES,
    CashSelectionAdapter,
    select_cash_opportunities,
)


# Supply a covered A/A+ book with one unheld candidate and actual marked NAV.
def inputs():
    return dict(
        grades=np.array([2, 3, 2]),
        eligible=np.ones(3, dtype=bool),
        prices=np.array([10.0, 20.0, 30.0]),
        held=np.array([2.0, 1.0, 0.0]),
        nav=100.0,
        relative=np.array([-0.02, 0.01, -0.0005]),
        spy=0.0,
        cost_bps=10,
    )


# A weak held name exits, a stronger name permits adds, and a marginal buy waits.
def test_joint_purchase_and_exit_verdicts():
    plan = select_cash_opportunities(**inputs())
    np.testing.assert_array_equal(plan.no_buy, [True, False, True])
    np.testing.assert_array_equal(plan.cash_exit, [True, False, False])
    np.testing.assert_array_equal(plan.cash_exit_shares, [2, 0, 0])
    assert plan.reasons == ("forecast_cash_exit", "purchase_edge", "purchase_no_edge")


# Attribution changes only declared masks, preserving the frozen forecast comparisons.
@pytest.mark.parametrize(
    ("mode", "denied", "exits"),
    [
        ("quantity_control", [False, False, False], [False, False, False]),
        ("buy_only", [True, False, True], [False, False, False]),
        ("exit_only", [True, False, False], [True, False, False]),
    ],
)
def test_attribution_masks_preserve_forecast_values(mode, denied, exits):
    joint = select_cash_opportunities(**inputs())
    plan = select_cash_opportunities(**inputs(), mode=mode)
    np.testing.assert_array_equal(plan.no_buy, denied)
    np.testing.assert_array_equal(plan.cash_exit, exits)
    np.testing.assert_array_equal(plan.cash_exit_shares, np.where(exits, [2, 1, 0], 0))
    for key in ("absolute_mean", "buy_edge", "hold_edge"):
        np.testing.assert_array_equal(getattr(plan, key), getattr(joint, key))


# A diagnostic mode cannot be misspelled or inferred from truthiness.
@pytest.mark.parametrize("mode", [None, True, "sell_only", ["joint"]])
def test_invalid_attribution_mode_refuses(mode):
    with pytest.raises(ValueError, match="supported cash-selection mode"):
        select_cash_opportunities(**inputs(), mode=mode)


# Blocking an addition never liquidates a held position with a positive hold edge.
def test_no_buy_does_not_imply_liquidation():
    values = inputs()
    values["relative"] = np.zeros(3)
    plan = select_cash_opportunities(**values)
    assert plan.no_buy.all()
    assert not plan.cash_exit.any()
    assert not plan.cash_exit_shares.any()


# Fees, rather than a universal price-move percentage, define economic equality.
@pytest.mark.parametrize("cost_bps", [0, 10, 25])
def test_exact_cost_boundaries(cost_bps):
    values = inputs()
    cost = cost_bps / 10000
    values.update(
        cost_bps=cost_bps, relative=np.array([np.log1p(-cost), np.log1p(cost), 0.0])
    )
    plan = select_cash_opportunities(**values)
    assert plan.no_buy.all()
    assert not plan.cash_exit.any()


# The absolute market component changes cash decisions even with equal relative ranks.
def test_market_forecast_changes_cash_opportunity():
    values = inputs()
    values.update(relative=np.zeros(3), spy=0.02)
    positive = select_cash_opportunities(**values)
    values["spy"] = -0.02
    negative = select_cash_opportunities(**values)
    assert not positive.no_buy.any()
    assert not positive.cash_exit.any()
    np.testing.assert_array_equal(negative.cash_exit_shares, values["held"])


# Unknown forecasts preserve the incumbent independently for each affected stock.
@pytest.mark.parametrize("spy", [None, np.nan])
def test_unavailable_market_preserves_incumbent(spy):
    values = inputs()
    values["spy"] = spy
    plan = select_cash_opportunities(**values)
    assert not plan.no_buy.any()
    assert not plan.cash_exit.any()
    assert set(plan.reasons) == {"forecast_unavailable"}


# A missing own forecast does not change a different stock's valid decision.
def test_partial_own_unavailability_is_local():
    values = inputs()
    values["relative"][0] = np.nan
    plan = select_cash_opportunities(**values)
    assert plan.reasons[0] == "forecast_unavailable"
    assert not plan.no_buy[0]
    assert not plan.cash_exit[0]
    assert plan.no_buy[2]


# Event and thesis authority supersede discretionary mean-return comparisons.
def test_mandatory_has_priority():
    values = inputs()
    values["mandatory"] = np.ones(3, dtype=bool)
    plan = select_cash_opportunities(**values)
    assert not plan.no_buy.any()
    assert not plan.cash_exit.any()
    assert set(plan.reasons) == {"mandatory_incumbent"}


# B/C/unknown grades and unavailable membership never receive new learned exits.
def test_other_grades_and_missing_eligibility_preserve_incumbent():
    values = inputs()
    values.update(grades=np.array([-1, 0, 1]), relative=np.full(3, -0.5))
    plan = select_cash_opportunities(**values)
    assert not plan.no_buy.any()
    assert not plan.cash_exit.any()
    values.update(grades=np.full(3, 3), eligible=np.zeros(3, dtype=bool))
    plan = select_cash_opportunities(**values)
    assert not plan.no_buy.any()
    assert not plan.cash_exit.any()


# A forecast never creates sale quantity in a stock the account does not own.
def test_unheld_stock_has_no_exit_quantity():
    values = inputs()
    values["relative"] = np.full(3, -0.5)
    plan = select_cash_opportunities(**values)
    assert plan.cash_exit_shares[2] == 0
    assert np.all(plan.cash_exit_shares <= values["held"])


# Invalid financial evidence is refused instead of converted into a hold fallback.
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("relative", np.array([np.inf, 0, 0]), "Finite-or-missing prices/forecasts"),
        ("spy", np.inf, "numeric SPY forecast"),
        ("spy", True, "numeric SPY forecast"),
        ("cost_bps", True, "cost_bps must be a finite numeric control"),
        ("cost_bps", 10000, "Cost must be below10000bp"),
        ("held", np.array([-1, 0, 0]), "nonnegative holdings"),
        ("prices", np.array([np.nan, 20, 30]), "Positive finite prices"),
        ("nav", 10, "holdings cannot exceed NAV"),
        ("grades", np.array([2, 2.5, 3]), "Ordinal grades"),
        ("eligible", np.ones(3), "eligible must be a boolean symbol mask"),
    ],
)
def test_invalid_evidence_refuses(field, value, message):
    values = inputs()
    values[field] = value
    with pytest.raises(ValueError, match=message):
        select_cash_opportunities(**values)


# Discretionary output arrays cannot be mutated into a different account decision.
def test_verdict_arrays_are_read_only():
    plan = select_cash_opportunities(**inputs())
    for value in (
        plan.no_buy,
        plan.cash_exit,
        plan.cash_exit_shares,
        plan.absolute_mean,
        plan.buy_edge,
        plan.hold_edge,
    ):
        with pytest.raises(ValueError, match="read-only"):
            value[0] = 0


# Future model rows cannot change the same earlier stock/account verdict.
@pytest.mark.parametrize("mode", MODES)
def test_adapter_prefix_invariance(mode):
    values = inputs()
    arrays = np.tile(values["relative"], (4, 1))
    eligible = np.ones((4, 3), dtype=bool)
    first = CashSelectionAdapter(
        ("AAA", "BBB", "CCC"),
        eligible,
        arrays,
        np.zeros(4),
        10,
        dates=np.arange("2026-01-05", "2026-01-09", dtype="datetime64[D]"),
        mode=mode,
    )
    arrays[1:] = 100
    eligible[1:] = False
    second = CashSelectionAdapter(
        ("AAA", "BBB", "CCC"),
        eligible,
        arrays,
        np.zeros(4),
        10,
        dates=np.arange("2026-01-05", "2026-01-09", dtype="datetime64[D]"),
        mode=mode,
    )
    args = (0, values["grades"], values["prices"], values["held"], values["nav"])
    one, two = first.decide(*args), second.decide(*args)
    np.testing.assert_array_equal(one.no_buy, two.no_buy)
    np.testing.assert_array_equal(one.cash_exit_shares, two.cash_exit_shares)
    assert first.events == second.events
    assert all(e.get("mode", "joint") == mode for e in first.events)


# Fitted stock heads never supply benchmark forecasts as purchase/exit evidence.
def test_adapter_refuses_benchmark_stock_forecasts():
    with pytest.raises(ValueError, match="benchmark"):
        CashSelectionAdapter(
            ("AAA", "SPY"),
            np.ones((4, 2), dtype=bool),
            np.zeros((4, 2)),
            np.zeros(4),
            10,
            dates=np.arange("2026-01-05", "2026-01-09", dtype="datetime64[D]"),
        )


# Same-length shifted or nonchronological dates cannot silently label a forecast row.
@pytest.mark.parametrize(
    "dates",
    [
        np.array(["2026-01-05", "2026-01-05"], dtype="datetime64[D]"),
        np.array(["2026-01-06", "2026-01-05"], dtype="datetime64[D]"),
        np.array(["NaT", "2026-01-05"], dtype="datetime64[D]"),
        np.array(["2026-01-05", "2026-01-06"]),
    ],
)
def test_adapter_refuses_invalid_forecast_calendar(dates):
    with pytest.raises(ValueError, match="calendar|datetime64"):
        CashSelectionAdapter(
            ("AAA",),
            np.ones((2, 1), dtype=bool),
            np.zeros((2, 1)),
            np.zeros(2),
            10,
            dates=dates,
        )
