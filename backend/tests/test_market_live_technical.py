"""The live technical read's row logic.

What has to hold: when the store ends before today a row is appended
with every name carried at its last close and the quoted names set from
their live bar, the adjusted close moving with the raw close; when the
store already has today the row is overwritten; a quote for a name not
in the panel is ignored.
"""

from datetime import date
from types import SimpleNamespace

import numpy as np

from backend.market.live_technical import with_live_row
from backend.market.panel import Panel


def _panel():
    dates = np.array(["2026-09-03", "2026-09-04"], dtype="datetime64[D]")
    close = np.array([[100.0, 50.0, 400.0], [110.0, 52.0, 404.0]])
    return Panel(
        dates=dates,
        tickers=("AAA", "BBB", "SPY"),
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        adj_close=close * 0.5,  # a 2:1 adjustment sits in the history
        volume=np.full((2, 3), 1000.0),
        themes={},
        benchmark="SPY",
    )


def test_a_live_row_is_appended_when_the_store_ends_before_today():
    quotes = {
        "AAA": SimpleNamespace(last=99.0, open=111.0, high=112.0, low=98.0, bar="x"),
        "ZZZ": SimpleNamespace(last=1.0, open=1.0, high=1.0, low=1.0, bar="x"),
    }
    live = with_live_row(_panel(), quotes, date(2026, 9, 8))
    assert live.dates.shape == (3,)
    assert str(live.dates[-1]) == "2026-09-08"
    assert live.close[-1].tolist() == [99.0, 52.0, 404.0]  # BBB and SPY carried
    assert live.high[-1].tolist() == [112.0, 52.0, 404.0]  # carried names: flat bar
    assert live.low[-1, 0] == 98.0
    assert live.open[-1, 0] == 111.0
    assert live.adj_close[-1, 0] == 99.0 * 0.5  # moves with the raw close
    assert live.adj_close[-1, 1] == 52.0 * 0.5
    assert np.isnan(live.volume[-1]).all()
    assert live.close.shape[0] == 3


def test_todays_row_is_overwritten_when_the_store_has_it():
    quotes = {
        "BBB": SimpleNamespace(last=60.0, open=52.0, high=61.0, low=51.0, bar="x")
    }
    live = with_live_row(_panel(), quotes, date(2026, 9, 4))
    assert live.dates.shape == (2,)
    assert live.close[-1].tolist() == [110.0, 60.0, 404.0]
    assert live.high[-1, 1] == 61.0
    assert live.adj_close[-1, 1] == 60.0 * 0.5
    # Nothing before today changed.
    assert live.close[0].tolist() == [100.0, 50.0, 400.0]
