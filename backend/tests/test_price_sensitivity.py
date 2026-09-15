"""The sensitivity diagnostic's own pieces.

What has to hold: the bounded magnitude keeps the size of a discount (a
halving moves every name by the same log distance, however cheap it
already ranks) and stays inside [-1, 1]; the implied stance follows the
rank's lines; a repriced panel touches only the asked sessions and column.
"""

import numpy as np

from backend.cli import market_price_sensitivity as ps


def test_magnitude_keeps_the_size_of_the_discount_and_is_bounded():
    cheap = np.array([2.0, 0.5, 0.0, -0.5, -2.0])
    eligible = np.ones(5, dtype=bool)
    m = ps.magnitude(cheap, eligible)
    assert (np.abs(m) <= 1.0).all()
    assert (np.diff(m) < 0).all()  # monotone in cheapness
    # Halving every price adds log 2 to every distance; at the same scale the
    # cheapest name, already saturated in rank terms, still moves.
    scale = float(np.median(np.abs(cheap)))
    same = ps.magnitude(cheap, eligible, scale)
    halved = ps.magnitude(cheap + np.log(2.0), eligible, scale)
    assert (halved > same).all()
    assert m[2] == 0.0  # at the side's median: neutral
    # Ineligible names do not set the scale and read as neutral when NaN.
    withnan = ps.magnitude(np.array([np.nan, 0.5, -0.5]), np.array([False, True, True]))
    assert withnan[0] == 0.0


def test_implied_stance_follows_the_rank_lines():
    assert ps.raw_stance(0.95) == 1
    assert ps.raw_stance(0.70) == 1
    assert ps.raw_stance(0.69) == 0
    assert ps.raw_stance(0.30) == -1
    assert ps.raw_stance(float("nan")) == 0


def test_repricing_touches_only_the_asked_sessions_and_column():
    from backend.market.panel import Panel

    close = np.array([[10.0, 20.0, 30.0]] * 5)
    panel = Panel(
        dates=np.datetime64("2026-09-01") + np.arange(5).astype("timedelta64[D]"),
        tickers=("A", "B", "SPY"),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.ones_like(close),
        themes={},
        benchmark="SPY",
    )
    one = ps.repriced(panel, 2.0, 1, 0)
    assert one.close[-1, 0] == 20.0
    assert one.close[-2, 0] == 10.0
    assert one.close[-1, 1] == 20.0
    three = ps.repriced(panel, 2.0, 3, 0)
    assert (three.close[-3:, 0] == 20.0).all()
    assert three.close[-4, 0] == 10.0
    book = ps.repriced(panel, 1.5, 1, None)
    assert book.close[-1].tolist() == [15.0, 30.0, 45.0]
    assert book.close[-2].tolist() == [10.0, 20.0, 30.0]
