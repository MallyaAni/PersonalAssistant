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
import pytest

from backend.agents.trading.desk.opinions import Opinion
from backend.market import live_technical
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


def test_technical_detail_splits_the_features_by_horizon(monkeypatch):
    # A fake live read: one name, one session, every feature present, so the
    # split and the buckets are what the test checks, not the analyst run.
    panel = Panel(
        dates=np.array(["2026-09-08"], dtype="datetime64[D]"),
        tickers=("AAA",),
        open=np.array([[100.0]]),
        high=np.array([[101.0]]),
        low=np.array([[99.0]]),
        close=np.array([[100.0]]),
        adj_close=np.array([[100.0]]),
        volume=np.array([[1000.0]]),
        themes={},
        benchmark="AAA",
    )
    evidence = {
        name: np.full((1, 1), 0.4)
        for name in live_technical.SHORT + live_technical.MEDIUM + live_technical.LONG
    }
    opinion = Opinion("technical", np.full((1, 1), 0.8), evidence)
    monkeypatch.setattr(
        live_technical,
        "_live_read",
        lambda store, quotes, today: {"panel": panel, "opinion": opinion},
    )
    quote = SimpleNamespace(last=100.0, open=100.0, high=101.0, low=99.0, bar="x")
    out = live_technical.technical_detail(None, {"AAA": quote}, date(2026, 9, 8))
    assert "AAA" in out
    d = out["AAA"]
    # Every horizon has at least one cited feature, each filed under its own
    # list and nowhere else.
    assert d["short"]
    assert d["medium"]
    assert d["long"]
    assert all(name in live_technical.SHORT for name in d["short"])
    assert all(name in live_technical.MEDIUM for name in d["medium"])
    assert all(name in live_technical.LONG for name in d["long"])
    assert "now" in d
    assert d["now"] is not None


# The long horizon names both the 200-day EMA and the 200-day simple
# average: the SMA is the standing trend line a person watches, and a read
# that omits it hides the figure that matters to them.
def test_long_lines_name_the_200_day_ema_and_sma():
    features = {
        "high_52w_distance": -0.79,
        "low_52w_distance": 0.27,
        "ema200_distance": -0.116,
        "sma200_distance": -0.106,
        "residual_momentum_120": -6.9,
    }
    lines_out = live_technical._long_lines(features)
    assert any("200-day EMA" in line for line in lines_out)
    assert any("200-day simple average" in line for line in lines_out)


# A bearish engulfing on the last daily bar is surfaced as today's candle
# in the short horizon, with how much of the prior body it takes; a name
# whose last bar is an ordinary candle carries none.
def test_todays_bearish_engulfing_is_a_short_horizon_line():
    panel = _panel()
    candles = {
        "bearish_engulfing": np.array([[0.0, 0.0], [0.0, 1.0]], dtype=float),
        "bullish_engulfing": np.zeros((2, 3)),
        "shooting_star": np.zeros((2, 3)),
        "hammer": np.zeros((2, 3)),
    }
    candle = live_technical._today_candle(candles, panel, 1, 1)
    assert candle is not None
    assert candle["name"] == "bearish engulfing"
    line = live_technical._candle_line(candle)
    assert "today's daily candle is a bearish engulfing" in line
    detail = {"short": {}, "medium": {}, "long": {}, "candle": candle}
    rendered = live_technical.lines(detail)
    assert any("bearish engulfing" in line for line in rendered["short"])
    # The name with no candle on its last bar carries none.
    assert live_technical._today_candle(candles, panel, 1, 0) is None


# When a chain is on file the drill-down carries the option walls read at
# the live price, with the put and call walls as distances from it; when
# the store has no chain the block is simply absent.
def test_technical_detail_carries_the_option_walls_when_stored(tmp_path, monkeypatch):
    from datetime import timedelta

    from backend.market import options
    from backend.market.store import MarketStore

    today = date(2026, 9, 8)
    expiry = today + timedelta(days=30)
    rows = [
        options.ChainRow(expiry, "put", 90.0, 3000, 1, 0.5, 0.018),
        options.ChainRow(expiry, "call", 110.0, 2000, 1, 0.4, 0.015),
    ]
    store = MarketStore(tmp_path)
    store.write_frame(options.KIND, today, "AAA", options.frame(rows))
    panel = Panel(
        dates=np.array(["2026-09-08"], dtype="datetime64[D]"),
        tickers=("AAA",),
        open=np.array([[100.0]]),
        high=np.array([[101.0]]),
        low=np.array([[99.0]]),
        close=np.array([[100.0]]),
        adj_close=np.array([[100.0]]),
        volume=np.array([[1000.0]]),
        themes={},
        benchmark="AAA",
    )
    evidence = {
        name: np.full((1, 1), 0.4)
        for name in live_technical.SHORT + live_technical.MEDIUM + live_technical.LONG
    }
    opinion = Opinion("technical", np.full((1, 1), 0.8), evidence)
    monkeypatch.setattr(
        live_technical,
        "_live_read",
        lambda store, quotes, today: {"panel": panel, "opinion": opinion},
    )
    quote = SimpleNamespace(last=100.0, open=100.0, high=101.0, low=99.0, bar="x")
    out = live_technical.technical_detail(store, {"AAA": quote}, today)
    walls = out["AAA"]["walls"]
    assert walls["put_wall"] == 90.0
    assert walls["call_wall"] == 110.0
    assert walls["put_wall_distance"] == pytest.approx(-0.10)
    assert walls["call_wall_distance"] == pytest.approx(0.10)
    assert "net_gamma" in walls
    # Without a chain (no store) the block is absent, not empty.
    bare = live_technical.technical_detail(None, {"AAA": quote}, today)
    assert "walls" not in bare["AAA"]


# technical_now carries the persisted stance the rule would hold with the
# live bar as today's session, not a threshold on the live rank alone.
def test_technical_now_carries_the_persisted_stance(monkeypatch):
    dates = np.array(
        ["2026-09-04", "2026-09-05", "2026-09-08", "2026-09-09"], dtype="datetime64[D]"
    )
    ones = np.ones((4, 3))
    panel = Panel(
        dates=dates,
        tickers=("AAA", "BBB", "CCC"),
        open=ones * 100,
        high=ones * 101,
        low=ones * 99,
        close=ones * 100,
        adj_close=ones * 100,
        volume=ones * 1000,
        themes={},
        benchmark="CCC",
    )
    # AAA is top-ranked for three sessions and slips to the middle on the
    # live bar; BBB the reverse. The rule keeps AAA bullish (one session
    # under the line is not a run) and BBB bearish.
    scores = np.array(
        [[0.9, 0.1, 0.5], [0.9, 0.1, 0.5], [0.9, 0.1, 0.5], [0.5, 0.6, 0.4]]
    )
    opinion = Opinion("technical", scores, {})
    monkeypatch.setattr(
        live_technical,
        "_live_read",
        lambda store, quotes, today: {"panel": panel, "opinion": opinion},
    )
    quote = SimpleNamespace(last=100.0, open=100.0, high=101.0, low=99.0, bar="x")
    out = live_technical.technical_now(
        None, {"AAA": quote, "BBB": quote}, date(2026, 9, 9)
    )
    assert out["AAA"]["stance"] == 1
    assert out["BBB"]["stance"] == -1
    assert out["AAA"]["now"] < out["AAA"]["close"]


# value_now reads the value analyst from the same live read and returns the
# same shape as technical_now - rank now and at the close, and the persisted
# stance - so the live re-grade can move the value stance exactly as it
# moves the technical one.
def test_value_now_reads_the_value_analyst_and_reports_the_stance(monkeypatch):
    dates = np.array(
        ["2026-09-04", "2026-09-05", "2026-09-08", "2026-09-09"], dtype="datetime64[D]"
    )
    ones = np.ones((4, 2))
    panel = Panel(
        dates=dates,
        tickers=("AAA", "BBB"),
        open=ones * 100,
        high=ones * 101,
        low=ones * 99,
        close=ones * 100,
        adj_close=ones * 100,
        volume=ones * 1000,
        themes={},
        benchmark="BBB",
    )
    technical = Opinion("technical", np.full((4, 2), 0.5), {})
    # AAA is cheap for three sessions and expensive on the live bar; BBB the
    # reverse. The persisted stance keeps AAA bullish and BBB bearish.
    value = Opinion(
        "value",
        np.array([[0.9, 0.1], [0.9, 0.1], [0.9, 0.1], [0.5, 0.6]]),
        {},
    )
    monkeypatch.setattr(
        live_technical,
        "_live_read",
        lambda store, quotes, today: {"panel": panel, "opinion": technical, "value": value},
    )
    quote = SimpleNamespace(last=100.0, open=100.0, high=101.0, low=99.0, bar="x")
    out = live_technical.value_now(
        None, {"AAA": quote, "BBB": quote}, date(2026, 9, 9)
    )
    assert out["AAA"]["stance"] == 1
    assert out["BBB"]["stance"] == -1
    assert out["AAA"]["now"] < out["AAA"]["close"]
    # A live read without the value analyst carries no value rankings.
    monkeypatch.setattr(
        live_technical,
        "_live_read",
        lambda store, quotes, today: {"panel": panel, "opinion": technical, "value": None},
    )
    assert live_technical.value_now(None, {"AAA": quote}, date(2026, 9, 9)) == {}
