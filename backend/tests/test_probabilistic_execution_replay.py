"""Exercise probability timing through the actual shared funded-account engine."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import policy_v5
from backend.market import learned_execution_timing as ledger
from backend.market import probabilistic_execution as probability
from backend.market import probabilistic_execution_replay as candidate


# Supply simple causal quotes and the ordinary unchanged periodic target book.
def fixture(stocks=("ONE", "SPY", "QQQ"), days=2):
    dates = np.busday_offset("2026-08-03", np.arange(days)).astype("datetime64[D]")
    prices = np.full((days, len(stocks)), 10.0)
    panel = SimpleNamespace(dates=dates, tickers=stocks, adj_close=prices)
    grades = np.full(prices.shape, 3)
    eligible = np.ones(prices.shape, dtype=bool)
    eligible[:, -2:] = False
    shape = (days, 25, len(stocks))
    data = {
        "dates": dates,
        "current_close": np.full(shape, 10.0),
        "next_open": np.full(shape, 10.0),
    }
    return panel, grades, eligible, data


# Return a transparent deterministic waiting-price advantage for selector tests.
def distribution(mean, horizon=probability.HORIZON):
    return probability.Distribution(
        mean, 0.0, np.array([0.0]), np.array([1.0]), horizon
    )


# Run a synthetic account with frozen supplied forecasts and no model fitting.
def run(args, provider, **options):
    return candidate.account(
        *args,
        provider,
        first=1,
        cost_bps=options.pop("cost_bps", 0),
        offset=0,
        **options,
    )


# Keep grade-equal quantities while stock-specific forecasts choose clocks.
def test_stock_specific_clocks_share_original_allocator(monkeypatch):
    args = fixture(stocks=("NOW", "LATER", "SPY", "QQQ"))
    original = policy_v5.targets
    calls = []

    # Observe actual target creation without replacing its arithmetic.
    def targets(*values):
        targets = original(*values)
        calls.append(targets.copy())
        return targets

    monkeypatch.setattr(policy_v5, "targets", targets)

    # Defer the second stock to its fourth completed observation.
    def provider(day, clock, stock):
        return distribution(-0.01 if stock == 0 or clock >= 3 else 0.01)

    result = run(args, provider, cost_bps=10)
    assert candidate.replay_account is ledger.replay_account
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0], [0.25, 0.25, 0, 0])
    assert [row["attempt_clock"] for row in result["intent_trace"]] == [0, 3]
    assert [row["desired_shares"] for row in result["intent_trace"]] == [0.025, 0.025]
    assert result["counts"]["fills"] == 2


# Future labels and execution prices cannot alter the first selected request clock.
def test_unknown_future_prices_and_labels_do_not_select_clock():
    args = fixture()

    # Select only from the predeclared frozen clock-conditioned distribution.
    def provider(day, clock, stock):
        return distribution(-0.01 if clock >= 4 else 0.01)

    args[3]["labels"] = np.zeros_like(args[3]["next_open"])
    before = run(args, provider)
    args[3]["labels"][:] = np.nan
    args[3]["next_open"][1] *= 2
    after = run(args, provider)
    assert before["decision_trace"] == after["decision_trace"]
    assert (
        before["intent_trace"][0]["attempt_clock"]
        == after["intent_trace"][0]["attempt_clock"]
        == 4
    )
    assert before["nav"][-1] != after["nav"][-1]


# Missing or partial first attempts stay locked even if later prices improve.
@pytest.mark.parametrize("price", [np.nan, 100.0])
def test_first_attempt_missing_or_partial_is_never_retried(price):
    args = fixture()
    args[3]["next_open"][1, 0, 0] = price
    args[3]["next_open"][1, 1:, 0] = 8
    result = run(args, lambda day, clock, stock: distribution(-0.01))
    trace = result["intent_trace"][0]
    assert trace["attempt_clock"] == 0
    assert trace["outcome"] == ("unfilled" if np.isnan(price) else "partial")
    assert result["counts"]["fills"] == int(np.isfinite(price))
    assert len(result["decision_trace"]) == 1


# Defer unavailable distributions to the existing terminal deadline.
def test_terminal_is_authoritative_and_provider_not_called_at_deadline():
    calls = []

    # Record requests and deliberately refuse all ordinary learned evidence.
    def provider(day, clock, stock):
        calls.append(clock)
        assert clock < 24
        return None

    result = run(fixture(), provider)
    assert calls == list(range(24))
    assert result["counts"]["distribution_unavailable"] == 24
    assert result["intent_trace"][0]["attempt_clock"] == 24
    assert result["decision_trace"][-1]["reason"] == "shared_terminal_deadline"
    assert result["counts"]["closing_fills"] == 1


# All pending buys enter the ex-ante funding denominator even if one will wait.
def test_ex_ante_fraction_uses_all_pending_buy_requests():
    args = fixture(stocks=("A", "B", "C", "D", "E", "SPY", "QQQ"))

    # Defer one request while the four peers execute from the same morning cash.
    def provider(day, clock, stock):
        return distribution(0.01 if stock == 0 and clock == 0 else -0.01)

    result = run(args, provider, cost_bps=25)
    first = [row for row in result["decision_trace"] if row["clock"] == 0]
    assert len(first) == 5
    assert all(
        row["buy_funding_fraction"] == pytest.approx(1 / 1.0025) for row in first
    )
    assert all(row["trade_fraction"] == pytest.approx(0.2 / 1.0025) for row in first)
    assert all(row["all_pending_buy_spend"] == pytest.approx(1.0025) for row in first)
    for row in first:
        expected = probability.decision(
            provider(1, 0, row["stock"]),
            "buy",
            row["trade_fraction"],
            25,
            horizon=probability.HORIZON,
        )
        assert row["expected_log_utility"] == expected.expected_log_utility


# Covered sales cannot fund new buys at the same or a later observation that session.
def test_zero_cash_and_covered_sells_preserve_shared_budget():
    args = fixture(
        stocks=("OLD0", "OLD1", "OLD2", "OLD3", "NEW", "SPY", "QQQ"), days=22
    )
    args[2][:, 4] = False
    args[2][20:, :4] = False
    args[2][20:, 4] = True
    result = run(args, lambda day, clock, stock: distribution(0))
    traces = [
        row for row in result["intent_trace"] if row["date"] == str(args[0].dates[21])
    ]
    sells = [row for row in traces if row["side"] == "sell"]
    buy = [row for row in traces if row["side"] == "buy"][0]
    assert len(sells) == 4
    assert all(row["filled_delta"] == -row["initial_shares"] for row in sells)
    assert buy["morning_cash"] == 0
    assert buy["filled_delta"] == 0
    assert buy["outcome"] == "unfilled"
    assert result["counts"]["unfunded_decisions"] == 24
    requests = [
        row
        for row in result["decision_trace"]
        if row["date"] == buy["date"] and row["side"] == "buy"
    ]
    assert all(row["trade_fraction"] == 0 for row in requests)
    assert all(row["reserved_cash"] == 0 for row in requests)


# Unsupported sessions retain the planned denominator without invoking a distribution.
def test_unsupported_early_close_retains_intent():
    args = fixture()
    args[0].dates[:] = np.array(["2026-11-25", "2026-11-27"], dtype="datetime64[D]")

    # Fail if an unsupported early-close session reaches the learned selector.
    def provider(day, clock, stock):
        raise AssertionError("Unsupported session must not call the provider")

    result = run(args, provider)
    assert result["counts"]["unsupported_plan_sessions"] == 1
    assert result["counts"]["expired_unfilled"] == 1
    assert result["decision_trace"] == []


# Apply pro-rata cash only to buys while retaining covered sale risk and costs.
def test_buy_pro_rata_does_not_reduce_covered_sell_fraction():
    counts = dict.fromkeys(
        (
            "waiting_decisions",
            "distribution_unavailable",
            "unfunded_decisions",
            "cash_limited_decisions",
        ),
        0,
    )
    trace = []
    acting = candidate.select(
        lambda day, clock, stock: distribution(0.01),
        1,
        0,
        np.array([5.0, -2.0, 5.0]),
        np.ones(3, dtype=bool),
        np.ones(3, dtype=bool),
        np.array([10.0, 10.0, 10.0]),
        100.0,
        20.0,
        25.0,
        False,
        counts,
        trace,
        ("BUY0", "SELL", "BUY1"),
        np.datetime64("2026-08-04"),
        0,
    )
    np.testing.assert_array_equal(acting, [False, True, False])
    assert [row["trade_fraction"] for row in trace] == pytest.approx(
        [0.5 * 20 / 100.25, 0.2, 0.5 * 20 / 100.25]
    )
    assert counts["waiting_decisions"] == 2
    assert counts["cash_limited_decisions"] == 2
    for row in trace:
        expected = probability.decision(
            distribution(0.01),
            row["side"],
            row["trade_fraction"],
            25,
            horizon=probability.HORIZON,
        )
        assert row["expected_log_utility"] == expected.expected_log_utility
        assert row["cost_bps"] == 25


# Validate the shared calendar start before computing any session support slice.
@pytest.mark.parametrize("first", [True, -1, 1.5, 2])
def test_invalid_start_uses_shared_validation(first):
    args = fixture()
    with pytest.raises(ValueError, match="first session"):
        candidate.account(
            *args,
            lambda day, clock, stock: distribution(0),
            first=first,
            cost_bps=0,
            offset=0,
        )


# Malformed supplied forecasts or quote grids fail at their original boundary.
@pytest.mark.parametrize("case", ["not_callable", "wrong_type", "horizon", "grid"])
def test_strict_provider_and_grid_contract(case):
    args = fixture()

    # Supply the requested malformed value at the actual provider boundary.
    def provider(day, clock, stock):
        if case == "wrong_type":
            return {"mean": 0}
        return distribution(
            0, "holding_return" if case == "horizon" else probability.HORIZON
        )

    if case == "not_callable":
        provider = None
    elif case == "grid":
        args[3]["current_close"] = args[3]["current_close"][:, :24]
    with pytest.raises(ValueError, match="required|Provider|horizon"):
        run(args, provider)
