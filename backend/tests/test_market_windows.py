"""Window tensors: no look-ahead in, no leaked labels out.

The properties that make the tensor builder a safe input to a model: a
window ending at session t contains nothing after t; a future label is only
the ticker's own forward return and is marked invalid where the future is
not fully known; a missing session drops windows over the gap instead of
inventing a price.
"""

from datetime import date, timedelta

import numpy as np

from backend.market.yahoo import DailyBar
from backend.market.windows import CHANNELS, LOG_VOLUME, MARKET_RELATIVE, OWN_RETURN, WindowSet, build_windows


def _session_dates(start: date, count: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(count)]


# One ticker's bars from a list of adjusted closes (close == adjusted).
def _bars(closes: list[float], start: date = date(2026, 1, 5)) -> list[DailyBar]:
    return [
        DailyBar(day, c, c, c, c, c, 1_000)
        for day, c in zip(_session_dates(start, len(closes)), closes)
    ]


def _closes(returns: list[float], base: float = 100.0) -> list[float]:
    prices = [base]
    for r in returns:
        prices.append(prices[-1] * (1.0 + r))
    return prices


def test_windows_have_expected_shape_and_channels():
    ticker = _bars(_closes([0.01] * 30), start=date(2026, 1, 5))
    benchmark = _bars(_closes([0.005] * 30), start=date(2026, 1, 5))
    result = build_windows({"ZZZZA": ticker}, benchmark, window_size=10, horizon=5)
    assert result.inputs.shape == (len(result.tickers), 10, CHANNELS)
    assert result.inputs.dtype == np.float32
    # Every window ends within the supplied history, and the last channel is
    # the market-relative return of the benchmark's own day.
    assert result.end_dates[0] == np.datetime64("2026-01-05", "D") + np.timedelta64(10, "D")


def test_windows_do_not_contain_future_returns():
    # A single huge return at one session; no window that ends before it may
    # contain it, and a window that ends on it must end with it. The jump
    # return (day 15 -> 16) is realized on the session whose bar closes at the
    # jumped price, i.e. start + 16 days.
    returns = [0.01] * 20
    returns[15] = 0.9  # the one big day
    prices = _closes(returns, base=100.0)
    start = date(2026, 1, 5)
    ticker = _bars(prices, start=start)
    benchmark = _bars(_closes([0.01] * 20), start=start)
    jump_date = start + timedelta(days=16)

    result = build_windows({"ZZZZA": ticker}, benchmark, window_size=10, horizon=1)

    for end, window in zip(result.end_dates, result.inputs):
        own = window[:, OWN_RETURN]
        if end < np.datetime64(jump_date, "D"):
            assert not np.any(np.abs(own - _log(1.9)) < 1e-9), "future return leaked in"
        if end == np.datetime64(jump_date, "D"):
            assert np.isclose(own[-1], _log(1.9), atol=1e-9)


def test_future_label_uses_only_future_data_and_is_nan_when_incomplete():
    prices = _closes([0.01] * 30, base=100.0)
    start = date(2026, 1, 5)
    ticker = _bars(prices, start=start)
    benchmark = _bars(_closes([0.005] * 30), start=start)
    result = build_windows({"ZZZZA": ticker}, benchmark, window_size=5, horizon=5)

    # A window ending at t predicts only the ticker's own return over [t, t+5].
    for end, label, valid in zip(result.end_dates, result.future_returns, result.valid):
        t = (end - np.datetime64(start, "D")) // np.timedelta64(1, "D")
        expected = _log(prices[t + 5] / prices[t]) if t + 5 < len(prices) else np.nan
        if valid:
            assert np.isclose(label, expected, atol=1e-9)
        else:
            assert np.isnan(label)


def test_a_missing_session_drops_windows_over_the_gap():
    # The ticker skips a session in the middle; the benchmark does not, so the
    # shared calendar has the day. No window may span it.
    all_dates = _session_dates(date(2026, 1, 5), 40)
    gap_date = date(2026, 1, 20)
    ticker_dates = [d for d in all_dates if d != gap_date]
    ticker = [
        DailyBar(d, 100 + i, 100 + i, 100 + i, 100 + i, 100 + i, 1_000)
        for i, d in enumerate(ticker_dates)
    ]
    benchmark = [
        DailyBar(d, 100, 100, 100, 100, 100, 1_000) for d in all_dates
    ]
    result = build_windows({"ZZZZA": ticker}, benchmark, window_size=5, horizon=1)
    assert len(result.tickers) > 0
    for end in result.end_dates:
        window_start = end - np.timedelta64(4, "D")
        assert not (window_start <= np.datetime64(gap_date, "D") <= end), "window spans the gap"


def test_empty_inputs_produce_an_empty_window_set():
    benchmark = _bars(_closes([0.01] * 10), start=date(2026, 1, 5))
    result = build_windows({}, benchmark, window_size=5, horizon=2)
    assert result.inputs.shape == (0, 5, CHANNELS)


def _log(value: float) -> float:
    import math

    return math.log(value)
