"""Exercise actual funded continuation actions and the matched live timing gate."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.market.sequential_execution_replay import account, supported_sessions


# Construct a funded stock opportunity without future labels or learned features.
def fixture(stocks=("ONE", "SPY", "QQQ"), days=2):
    dates = np.busday_offset("2026-08-03", np.arange(days))
    prices = np.full((days, len(stocks)), 10.0)
    panel = SimpleNamespace(dates=dates, tickers=stocks, adj_close=prices)
    grades = np.full(prices.shape, 3)
    eligible = np.ones(prices.shape, dtype=bool)
    eligible[:, -2:] = False
    shape = (days, 25, len(stocks))
    dataset = {
        "dates": dates,
        "current_close": np.full(shape, 10.0),
        "next_open": np.full(shape, 10.0),
    }
    predictions = np.ones((*shape, 2)) * 0.001
    return panel, grades, eligible, dataset, predictions, prices.copy()


# A stock-conditioned forecast determines timing without a universal price distance.
def test_distinct_stock_clocks_and_funded_trace():
    args = fixture(stocks=("NOW", "LATER", "SPY", "QQQ"))
    args[4][1, 0, 0, 0] = -0.002
    args[4][1, 3, 1, 0] = -0.002
    args[3]["next_open"][1, 0, 0] = 12
    args[3]["next_open"][1, 3, 1] = 8
    result = account(*args, first=1, cost_bps=10, offset=0)
    traces = result["intent_trace"]
    assert [x["attempt_clock"] for x in traces] == [0, 3]
    assert [x["realized_price"] for x in traces] == [12, 8]
    assert result["counts"]["fills"] == 2
    assert result["nav"][-1] == pytest.approx(0.9995)
    assert sum(x["fee"] for x in traces) == pytest.approx(0.0005)


# Unavailable forecasts can defer, but a known terminal observation still acts.
def test_terminal_uses_1545_next_open_without_model_context():
    args = fixture()
    args[4][:] = np.nan
    args[3]["next_open"][1, 24, 0] = 8
    result = account(*args, first=1, cost_bps=0, offset=0)
    trace = result["intent_trace"][0]
    assert trace["attempt_clock"] == 24
    assert trace["terminal_action"] is True
    assert trace["realized_price"] == 8
    assert result["counts"]["forecast_unavailable"] == 24
    assert result["nav"][-1] == pytest.approx(1.05)


# Once a price-missing attempt is chosen, a later favorable price cannot rescue it.
def test_first_missing_execution_is_not_retried():
    args = fixture()
    args[4][1, 0, 0, 0] = -1
    args[3]["next_open"][1, 0, 0] = np.nan
    args[3]["next_open"][1, 24, 0] = 8
    result = account(*args, first=1, cost_bps=0, offset=0)
    trace = result["intent_trace"][0]
    assert trace["attempt_clock"] == 0
    assert trace["realized_price"] is None
    assert trace["outcome"] == "unfilled"
    assert result["counts"]["missing_execution"] == 1
    assert result["counts"]["fills"] == 0


# Changing future execution outcomes cannot alter the selected action clock.
def test_future_price_invariance():
    args = fixture()
    args[4][1, 7, 0, 0] = -0.01
    before = account(*args, first=1, cost_bps=0, offset=0)
    args[3]["next_open"][1] *= 1.4
    after = account(*args, first=1, cost_bps=0, offset=0)
    assert before["intent_trace"][0]["attempt_clock"] == 7
    assert after["intent_trace"][0]["attempt_clock"] == 7
    assert before["nav"][-1] != after["nav"][-1]


# The unchanged live crossing rule and new terminal deadline are both reproduced.
def test_control_crossing_and_terminal():
    args = fixture()
    args[3]["current_close"][1, 2, 0] = 9.9
    crossed = account(*args, first=1, cost_bps=0, offset=0, method="control")
    assert crossed["intent_trace"][0]["attempt_clock"] == 2
    args[3]["current_close"][:] = 10
    closed = account(*args, first=1, cost_bps=0, offset=0, method="control")
    assert closed["intent_trace"][0]["attempt_clock"] == 24


# Unsupported early sessions remain unfunded opportunities in both denominators.
@pytest.mark.parametrize("method", ["candidate", "control"])
def test_unsupported_session_retains_intent(method):
    args = fixture()
    result = account(
        *args,
        first=1,
        cost_bps=0,
        offset=0,
        method=method,
        supported_days=np.array([True, False]),
    )
    assert result["counts"]["unsupported_plan_sessions"] == 1
    assert result["counts"]["intents"] == 1
    assert result["counts"]["expired_unfilled"] == 1
    assert result["intent_trace"][0]["attempt_clock"] is None


# The actual exchange calendar rejects unknown sessions and retains early closes.
def test_calendar_contract():
    dates = np.array(["2026-11-25", "2026-11-27"], dtype="datetime64[D]")
    np.testing.assert_array_equal(supported_sessions(dates), [True, False])
    with pytest.raises(ValueError, match="exchange"):
        supported_sessions(np.array(["2026-11-26"], dtype="datetime64[D]"))


# Sells are limited to held shares and never supply the day's reserved buy budget.
def test_sell_and_buy_funding_remain_separate():
    args = fixture(stocks=("OLD", "NEW", "SPY", "QQQ"), days=22)
    args[2][:, 1] = False
    args[2][20:, 0] = False
    args[2][20:, 1] = True
    args[4][:] = 0
    result = account(*args, first=1, cost_bps=0, offset=0)
    traces = result["intent_trace"]
    assert len(traces) == 3
    assert traces[1]["side"] == "sell"
    assert traces[1]["filled_delta"] == pytest.approx(-0.025)
    assert traces[2]["side"] == "buy"
    assert traces[2]["morning_cash"] == pytest.approx(0.75)
    assert result["nav"][-1] == pytest.approx(1)
