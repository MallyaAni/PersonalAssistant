"""Registered daily target behavior under actual, unchanged `/4` accounting."""

from dataclasses import replace

import numpy as np
import pytest

from backend.agents.trading.desk import policy_v4, simulate
from backend.market import daily_action_execution as execution
from backend.market import profit_taking
from backend.tests.funded_simulator_fixtures import _report


# Build a quiet single-quality-name account with known prices and ample cash.
def _book(rows=8, names=6):
    closes = np.full((rows, names), 100.0)
    grades = np.zeros_like(closes, dtype=int)
    grades[:, 0] = 3
    report = _report(close=closes, grades=grades)
    return report, np.ones_like(closes, dtype=bool)


# Run the wrapper with a synthetic forecast on the account's first decision date.
def _price(report, mask, forecast=None, **kwargs):
    return execution.price(
        report, mask, forecast, report.panel.dates[0].astype(object), 0.0, **kwargs
    )


# Read independently reconstructed held units on each closing date.
def _positions(priced):
    return np.asarray([mark["positions"] for mark in priced.verification["marks"]])


# Pin the mapping, exclusions, forecast fallback and gross normalization numerically.
def test_exact_registered_mapping():
    base = np.array([0.1] * 8 + [0.0])
    forecast = np.array([-0.02, -0.01, 0, 0.01, 4, np.nan, np.inf, -np.inf, 2])
    np.testing.assert_allclose(
        execution.mapped_targets(base, forecast),
        [0, 0.05, 0.1, 0.15, 0.15, 0.1, 0.1, 0.1, 0],
    )
    np.testing.assert_allclose(
        execution.mapped_targets(np.full(10, 0.1), np.full(10, 0.01)), 0.1
    )
    np.testing.assert_allclose(
        execution.mapped_targets(np.array([0.2, 0.2]), [0.01, -0.01]), [0.2, 0.1]
    )


# Refuse malformed baselines instead of silently turning invalid risk into exposure.
@pytest.mark.parametrize(
    ("base", "forecast"),
    [([0.3], [0]), ([-0.1], [0]), ([np.nan], [0]), ([0.1], [0, 0]), ([[0.1]], [[0]])],
)
def test_mapping_rejects_invalid_inputs(base, forecast):
    with pytest.raises(ValueError, match="baseline targets|aligned one-dimensional"):
        execution.mapped_targets(base, forecast)


# Missing predictions preserve the ordinary baseline without fabricating learned Holds.
def test_missing_forecasts_preserve_baseline_and_are_counted():
    report, mask = _book()
    baseline = _price(report, mask)
    missing = _price(report, mask, np.full_like(report.panel.close, np.nan))
    np.testing.assert_array_equal(baseline.result.equity, missing.result.equity)
    assert missing.diagnostics["missing_forecasts"] == len(report.panel.dates) - 1
    assert (
        sum(missing.diagnostics["action_counts"]["forecast_covered_desired"].values())
        == 0
    )
    assert missing.diagnostics["action_counts"]["fallback_desired"]["Hold"] > 0


# Both original and matched daily controls must equal direct simulator calls exactly.
@pytest.mark.parametrize("daily", [False, True])
def test_control_parity_and_independent_accounting(daily):
    report, mask = _book(rows=35)
    observed = _price(report, mask, daily=daily)
    options = profit_taking.control_options(report.panel)
    if daily:
        options["rebalance"] = 1
    plain = simulate.run(
        report, allocator=policy_v4.allocator(mask), cost_bps=0.0, **options
    )
    for key in ("equity", "returns", "invested", "top_weight"):
        np.testing.assert_array_equal(
            getattr(observed.result, key), getattr(plain, key)
        )
    assert observed.verification["ok"]
    assert observed.verification["accounting_verified"]
    assert not observed.verification["adoption_eligible"]


# A known target path must actually buy, add, hold, trim and sell without shorting.
def test_all_action_verbs_and_nonnegative_cash():
    report, mask = _book()
    forecast = np.zeros_like(report.panel.close)
    forecast[:, 0] = [-0.01, 0, 0, -0.01, -0.02, -0.02, -0.02, -0.02]
    priced = _price(report, mask, forecast)
    np.testing.assert_allclose(
        _positions(priced)[:, 0], [0, 0.001, 0.002, 0.002, 0.001, 0, 0, 0]
    )
    counts = priced.diagnostics["action_counts"]
    assert counts["desired"] == dict(Buy=1, Add=1, Hold=1, Trim=1, Sell=1)
    assert counts["executed"] == dict(Buy=1, Add=1, Hold=0, Trim=1, Sell=1)
    assert all(row["cash"] >= 0 for row in priced.diagnostics["daily"])
    assert (_positions(priced) >= 0).all()


# A future forecast cannot change earlier targets, and caller mutation is isolated.
def test_forecast_future_tampering_and_copy_boundary():
    report, mask = _book()
    initial = np.zeros_like(report.panel.close)
    changed = initial.copy()
    changed[4:, 0] = -0.02
    original = _price(report, mask, initial)
    altered = _price(report, mask, changed)
    np.testing.assert_array_equal(original.result.equity[:5], altered.result.equity[:5])
    np.testing.assert_array_equal(_positions(original)[:5], _positions(altered)[:5])
    decide = execution.allocator(mask, initial)
    initial[:] = -0.02
    mask[:] = False
    assert decide(report, report.panel, None, 0)[0] == 0.2


# A cash-blocked purchase is superseded by tomorrow's zero target, not retried.
def test_daily_target_supersedes_unfunded_retry():
    report, mask = _book(rows=5, names=7)
    report.graded.grades[:, :5] = 3
    report.graded.grades[1:, 5] = 3
    forecast = np.zeros_like(report.panel.close)
    forecast[1:, 0] = -0.02
    forecast[1, 5] = 0.01
    forecast[2:, 5] = -0.02
    priced = _price(report, mask, forecast)
    decisions = [
        e for e in priced.journal.snapshot()["events"] if e["type"] == "decision"
    ]
    assert decisions[1]["metadata"]["deferred_units"]["N5"] > 0
    assert _positions(priced)[2, 5] == 0
    assert (_positions(priced)[3:, 5] == 0).all()
    assert priced.diagnostics["daily"][2]["cash"] > 0


# A green-open cancelled sale remains Sell intent, not an executed Sell or Hold.
def test_green_open_cancellation_is_not_hold():
    report, mask = _book(rows=5)
    opens = report.panel.open.copy()
    opens[2, 0] = 110
    report.panel = replace(report.panel, open=opens)
    forecast = np.zeros_like(report.panel.close)
    forecast[1:, 0] = -0.02
    priced = _price(report, mask, forecast)
    assert _positions(priced)[2, 0] > 0
    assert _positions(priced)[3, 0] == 0
    assert priced.diagnostics["cancelled_sell_intents"] == 1
    assert priced.diagnostics["daily"][1]["desired"]["Sell"] == 1
    assert sum(priced.diagnostics["daily"][2]["executed"].values()) == 0


# Sub-floor positions retain a visible intent difference rather than fake exits.
def test_minimum_trade_residual_is_explicit():
    report, mask = _book(rows=4)
    closes = report.panel.close.copy()
    closes[1:, 0] = 0.1
    report.panel = replace(report.panel, close=closes, adj_close=closes)
    forecast = np.zeros_like(closes)
    forecast[1:, 0] = -0.02
    priced = _price(report, mask, forecast)
    assert (_positions(priced)[1:, 0] > 0).all()
    assert priced.diagnostics["desired_submission_differences"] >= 2
    assert priced.diagnostics["action_counts"]["desired"]["Sell"] >= 2
    assert priced.diagnostics["action_counts"]["executed"]["Sell"] == 0


# The event lifecycle restores its actual cut before ordinary model targets resume.
def test_fomc_owns_event_decisions(monkeypatch):
    report, mask = _book(rows=7)
    original_options = profit_taking.control_options

    # Supply a synthetic risk window while preserving all other live execution flags.
    def options(panel):
        out = original_options(panel)
        out["event_exposure"] = np.array([1, 0.5, 0.5, 1, 1, 1, 1])
        return out

    monkeypatch.setattr(profit_taking, "control_options", options)
    forecast = np.zeros_like(report.panel.close)
    forecast[1:, 0] = -0.02
    priced = _price(report, mask, forecast)
    np.testing.assert_allclose(
        _positions(priced)[:, 0], [0, 0.002, 0.001, 0.001, 0.002, 0, 0]
    )
    assert sum(row["event_owned_decisions"] for row in priced.diagnostics["daily"]) == 3


# The registered experiment cannot silently run learned positions on another cadence.
def test_learned_non_daily_and_bad_shapes_are_refused():
    report, mask = _book()
    with pytest.raises(ValueError, match="daily cadence"):
        _price(report, mask, np.zeros_like(mask, dtype=float), daily=False)
    with pytest.raises(ValueError, match="align"):
        _price(report, mask, np.zeros((1, 1)))


# Gap-up buys remain cash-bounded including each registered one-way fee level.
@pytest.mark.parametrize("cost", [10.0, 25.0])
def test_gapped_full_investment_accounts_respect_costs_and_cash(cost):
    report, mask = _book(rows=5)
    report.graded.grades[:, :5] = 3
    opens = report.panel.open.copy()
    opens[1, :5] *= 2
    report.panel = replace(report.panel, open=opens)
    priced = execution.price(
        report, mask, np.zeros_like(opens), report.panel.dates[0].astype(object), cost
    )
    assert priced.verification["total_fees"] == pytest.approx(
        priced.result.traded * cost / 10000
    )
    assert all(row["cash"] >= 0 for row in priced.diagnostics["daily"])
    assert (_positions(priced) >= 0).all()
    first_buy = next(
        event
        for event in priced.journal.snapshot()["events"]
        if event["type"] == "fill_batch" and event["gross_buys"] > 0
    )
    assert first_buy["scale"] < 1
    assert first_buy["gross_buys"] + first_buy["fee_total"] <= 1 + 1e-12
