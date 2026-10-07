"""Exercise causal sizing through the actual carried funded execution ledger."""

import numpy as np
import pytest

from backend.market import adaptive_growth_policy as growth
from backend.market.sequential_execution_replay import account
from backend.tests.test_sequential_execution_replay import fixture


# Return a dated stock-specific plan while retaining the exact causal inputs.
def provider(records, weights):
    # Capture an independent prefix so later source mutations cannot change proof.
    def allocate(**context):
        records.append(context)
        return np.asarray(weights, dtype=float), {
            "as_of": str(context["as_of"]),
            "status": "optimized",
        }

    return allocate


# Different desired sizes survive distinct clocks and one partial locked fill.
def test_frozen_sizes_partial_and_missing_attempts():
    args = fixture(stocks=("NOW", "LATER", "MISSING", "SPY", "QQQ"))
    records = []
    plan = provider(records, [0.2, 0.1, 0.05, 0, 0])
    args[4][1, 0, 0, 0] = -1
    args[4][1, 3, 1, 0] = -1
    args[4][1, 0, 2, 0] = -1
    args[3]["next_open"][1, 0, 0] = 1000
    args[3]["next_open"][1, 0, 2] = np.nan
    args[3]["next_open"][1, 1:, 0] = 1
    result = account(*args, first=1, cost_bps=25, offset=0, target_provider=plan)
    assert len(records) == 1
    traces = result["intent_trace"]
    assert [r["desired_shares"] for r in traces] == pytest.approx([0.02, 0.01, 0.005])
    assert [r["attempt_clock"] for r in traces] == [0, 3, 0]
    assert traces[0]["outcome"] == "partial"
    assert traces[1]["outcome"] == "unfilled"
    assert traces[2]["outcome"] == "unfilled"
    assert result["counts"]["fills"] == 1
    assert result["counts"]["missing_execution"] == 1
    assert result["cash"][-1] == pytest.approx(0)
    assert result["fees"].sum() == pytest.approx(1 - 1 / 1.0025)


# Allocation receives prior history/grade/membership rather than the entry day's rows.
def test_completed_prefix_and_future_price_invariance():
    args = fixture()
    records = []
    plan = provider(records, [0.12, 0, 0])
    args[4][1, 2, 0, 0] = -1
    first = account(*args, first=1, cost_bps=10, offset=0, target_provider=plan)
    args[0].adj_close[1] *= 3
    args[1][1] = 0
    args[2][1] = False
    args[3]["next_open"][1] *= 2
    second = account(*args, first=1, cost_bps=10, offset=0, target_provider=plan)
    assert len(records) == 2
    for key in ("history", "grades", "eligible", "current_weights"):
        np.testing.assert_array_equal(records[0][key], records[1][key])
    assert records[0]["history"].shape == (1, 3)
    assert records[0]["as_of"] == args[0].dates[0]
    assert first["allocation_trace"] == second["allocation_trace"]
    assert first["intent_trace"][0]["attempt_clock"] == 2
    assert second["intent_trace"][0]["attempt_clock"] == 2


# Reject a malformed or unfunded provider before reading any execution outcome.
@pytest.mark.parametrize("weights", [[0.3, 0, 0], [0.25, 0.25, 0.6], [-0.1, 0, 0]])
def test_invalid_provider_plan_rejected(weights):
    with pytest.raises(ValueError, match="target|funded"):
        account(
            *fixture(),
            first=1,
            cost_bps=25,
            offset=0,
            target_provider=provider([], weights),
        )


# New sizing cannot spend closing sale proceeds after cash was consumed earlier.
def test_sale_proceeds_cannot_fund_provider_targets():
    args = fixture(stocks=("OLD", "B", "C", "D", "NEW", "SPY", "QQQ"), days=22)
    args[4][:] = 0
    calls = []

    # Freeze the initial fully funded plan and then deliberately propose a bad rotation.
    def bad_rotation(**context):
        calls.append(context)
        w = np.zeros(7)
        if len(calls) == 1:
            w[:4] = 0.25 / 1.0025
        else:
            assert context["cash_weight"] == pytest.approx(0, abs=1e-12)
            w[1:5] = 0.25
        return w, {"status": "optimized", "as_of": str(context["as_of"])}

    with pytest.raises(ValueError, match="cash before sales"):
        account(*args, first=1, cost_bps=25, offset=0, target_provider=bad_rotation)
    assert len(calls) == 2


# Missing held valuation prevents sizing from inventing a liquidatable dollar value.
def test_missing_held_price_rejects_account_without_fabricating_value():
    args = fixture(days=22)
    args[4][:] = 0
    args[0].adj_close[20, 0] = np.nan
    records = []
    with pytest.raises(ValueError, match="held valuation unavailable"):
        account(
            *args,
            first=1,
            cost_bps=0,
            offset=0,
            target_provider=provider(records, [0.2, 0, 0]),
        )
    assert len(records) == 1


# Use the actual covariance optimizer and distinct learned buy/sell action clocks.
def test_actual_growth_policy_sizes_buys_and_reduces_position_on_new_forecast():
    args = fixture(stocks=("LOW", "HIGH", "SPY", "QQQ"), days=275)
    rng = np.random.default_rng(17)
    returns = rng.normal(size=(274, 4)) * [0.025, 0.15, 0.01, 0.01]
    args[0].adj_close[:] = 10 * np.exp(
        np.vstack((np.zeros(4), np.cumsum(returns, axis=0)))
    )
    args[3]["current_close"][1:] = args[0].adj_close[:-1, None, :]
    args[3]["next_open"][1:] = args[0].adj_close[:-1, None, :]
    args[4][:] = 0
    args[4][273, :5, 0, 1] = -1
    records = []

    # Construct dated means with a negative held-stock update at the second reset.
    def actual_provider(**context):
        history = context.pop("history")
        as_of = context.pop("as_of")
        cov = growth.covariance(history[:, :2])
        means = np.zeros(4)
        means[:2] = 0.002 - 0.5 * np.diag(cov)
        if as_of == args[0].dates[272]:
            means[0] = -0.2
        target, receipt = growth.allocate(
            history=history, means=means, benchmark_indices=[2, 3], **context
        )
        receipt["as_of"] = str(as_of)
        records.append(receipt)
        return target, receipt

    result = account(
        *args,
        first=253,
        cost_bps=0,
        offset=0,
        target_provider=actual_provider,
        supported_days=np.ones(275, bool),
    )
    assert len(records) == 2
    assert all(r["status"] == "optimized" for r in records)
    assert 0 < records[0]["targets"][1] < records[0]["targets"][0] < 0.25
    assert records[1]["targets"][0] == pytest.approx(0, abs=1e-10)
    sells = [
        r
        for r in result["intent_trace"]
        if r["symbol"] == "LOW" and r["side"] == "sell"
    ]
    assert len(sells) == 1
    assert sells[0]["attempt_clock"] == 5
    assert sells[0]["filled_delta"] == pytest.approx(-sells[0]["initial_shares"])
    assert result["cash"].min() >= 0
    assert sum(
        r["net_gain_initial_nav_units"] for r in result["stocks"].values()
    ) == pytest.approx(result["nav"][-1] - 1)
