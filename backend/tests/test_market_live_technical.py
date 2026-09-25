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
from backend.market import calendar, live_technical
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
    assert "net_gamma" not in walls
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
        lambda store, quotes, today: {
            "panel": panel,
            "opinion": technical,
            "value": value,
        },
    )
    quote = SimpleNamespace(last=100.0, open=100.0, high=101.0, low=99.0, bar="x")
    out = live_technical.value_now(None, {"AAA": quote, "BBB": quote}, date(2026, 9, 9))
    assert out["AAA"]["stance"] == 1
    assert out["BBB"]["stance"] == -1
    assert out["AAA"]["now"] < out["AAA"]["close"]
    # A live read without the value analyst carries no value rankings.
    monkeypatch.setattr(
        live_technical,
        "_live_read",
        lambda store, quotes, today: {
            "panel": panel,
            "opinion": technical,
            "value": None,
        },
    )
    assert live_technical.value_now(None, {"AAA": quote}, date(2026, 9, 9)) == {}


# A log distance is said as its arithmetic percentage, never the log
# itself: a reading of -0.796 is a price 54.9% below its level, not 79.6%,
# and the two diverge the further price sits. A small log distance keeps
# its familiar reading because log and arithmetic percentage agree closely.
def test_a_log_distance_reads_as_its_arithmetic_percentage():
    assert live_technical._log_pct_word(-0.796) == "54.9% below"
    assert live_technical._log_pct_word(0.796) == "121.7% above"
    assert live_technical._log_pct_word(-0.05) == "4.9% below"
    assert live_technical._log_pct_word(0.0) == "at"
    assert live_technical._log_pct_word(float("nan")) is None
    assert live_technical._log_pct_word(None) is None


# Level distances describe the level relative to price, preserving the denominator.
def test_levels_describe_the_level_relative_to_price():
    above = live_technical._level_lines(
        {"resistance_distance": 0.15, "resistance_kind": 1}
    )
    assert above == ["nearest resistance is 15.0% above the price — a swing high"]
    below = live_technical._level_lines(
        {"resistance_distance": -0.15, "resistance_kind": 1}
    )
    assert below == ["nearest resistance is 15.0% below the price — a swing high"]
    support = live_technical._level_lines(
        {"support_distance": 0.125, "support_kind": 3}
    )
    assert support == ["nearest support is 12.5% below the price — the 200-day average"]


# A net count of one means two pairs agree and one disagrees, not one agreeing pair.
@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (1, "2 of the three EMA pairs stacked up"),
        (-1, "2 of the three EMA pairs stacked down"),
        (-3, "full bearish EMA stack (9 < 21 < 50 < 200)"),
    ],
)
def test_live_stack_counts_pairs_instead_of_the_net_score(score, expected):
    assert expected in live_technical._short_lines({"stack_order": score})


# A weekly support names weeks and a coincident level does not claim a direction.
def test_weekly_and_coincident_levels_keep_their_units():
    assert live_technical._level_lines(
        {"support_distance": 0.0, "support_kind": 4}
    ) == ["nearest support is at the price — the 21-week average"]


# The long horizon's yearly-range line states the arithmetic percentage
# below the 52-week high and above the 52-week low, and the 200-day lines
# the same way.
def test_the_long_horizon_lines_say_arithmetic_percentages():
    lines_out = live_technical._long_lines(
        {
            "high_52w_distance": -0.796,
            "low_52w_distance": 0.27,
            "ema200_distance": -0.05,
            "sma200_distance": -0.05,
        }
    )
    assert "54.9% below its 52-week high" in lines_out[0]
    assert "31.0% above its 52-week low" in lines_out[0]
    assert "4.9% below the 200-day EMA" in lines_out
    assert "4.9% below the 200-day simple average" in lines_out


# The fast picture: a name that ran up and then slipped for three sessions
# reads as the 9-day EMA having turned down over the last three sessions,
# with the 9/21 gap narrowing, while the analyst's five-session slope would
# still call it rising.
def test_the_short_read_sees_the_nine_day_ema_turn(monkeypatch):
    rows = 40
    path = np.concatenate([np.linspace(100, 130, rows - 3), [128.0, 126.0, 124.0]])
    dates = np.datetime64("2026-07-01") + np.arange(rows).astype("timedelta64[D]")
    col = path[:, None]
    panel = Panel(
        dates=dates,
        tickers=("AAA",),
        open=col,
        high=col * 1.01,
        low=col * 0.99,
        close=col,
        adj_close=col,
        volume=np.full((rows, 1), 1000.0),
        themes={},
        benchmark="AAA",
    )
    opinion = Opinion("technical", np.full((rows, 1), 0.5), {})
    monkeypatch.setattr(
        live_technical,
        "_live_read",
        lambda store, quotes, today: {"panel": panel, "opinion": opinion},
    )
    quote = SimpleNamespace(last=124.0, open=126.0, high=126.5, low=123.5, bar="x")
    detail = live_technical.technical_detail(None, {"AAA": quote}, date(2026, 8, 9))[
        "AAA"
    ]
    assert detail["short"]["ema9_turn_3"] < 0
    assert detail["short"]["spread_9_21_turn_3"] < 0
    short = live_technical.lines(detail)["short"]
    assert "the 9-day EMA has turned down over the last three sessions" in short
    assert any(
        line.startswith("the 9-day EMA is") and "narrowing" in line for line in short
    )


# The entry read: is this a moment to start, at the live price.
#
# `entry.py` has measured two triggers on this book since it was written and
# was called by nothing but the backtest, so the board could say a name was
# A+ without ever saying whether now was a time to buy it. These tests pin
# the wiring and the classification, not the thresholds, which belong to
# the analyst. Keep those prices on real sessions ending at the evaluation date.
def _long_panel(paths: dict[str, np.ndarray]) -> Panel:
    names = tuple(paths) + ("SPY",)
    rows = len(next(iter(paths.values())))
    close = np.column_stack([*paths.values(), np.full(rows, 400.0)])
    _, sessions = calendar.reviewed_sessions()
    dates = np.busday_offset(
        np.datetime64("2026-09-18"), np.arange(1 - rows, 1), busdaycal=sessions
    )
    return Panel(
        dates=dates,
        tickers=names,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1000.0),
        themes={n: () for n in names},
        benchmark="SPY",
    )


# Read the supplied numerical fixture at its declared current exchange session.
def _entry_read(monkeypatch, panel, ai_trend=None):
    trend = ai_trend if ai_trend is not None else np.zeros(panel.dates.shape[0])
    monkeypatch.setattr(
        live_technical,
        "_live_read",
        lambda store, quotes, today: {"panel": panel, "ai_trend": trend},
    )
    quotes = {n: SimpleNamespace(last=1.0, bar="x") for n in panel.tickers}
    return live_technical.entry_now(None, quotes, date(2026, 9, 18))


# A name that has run up and then dropped hard under its 21-day average is
# a dip, and the dip edge was measured over five sessions.
def test_a_sharp_drop_below_the_21_day_average_is_a_dip(monkeypatch):
    climb = np.linspace(100.0, 200.0, 290)
    drop = np.linspace(200.0, 150.0, 10)  # ~25% under the 21 EMA by the end
    out = _entry_read(monkeypatch, _long_panel({"AAA": np.concatenate([climb, drop])}))
    assert out["AAA"]["trigger"] == "dip"
    assert out["AAA"]["horizon_sessions"] == 5
    assert out["AAA"]["stretch_21"] < -0.08
    assert out["AAA"]["band_z"] < -1.0


# A name at the top of its 60-session range with both trends up is a
# breakout, and that edge was measured over twenty sessions.
def test_a_name_at_the_top_of_its_range_in_an_agreed_trend_is_a_breakout(monkeypatch):
    out = _entry_read(monkeypatch, _long_panel({"AAA": np.linspace(100.0, 300.0, 300)}))
    assert out["AAA"]["trigger"] == "breakout"
    assert out["AAA"]["horizon_sessions"] == 20


# The strongest measured dip edge is a name below its band *while the
# basket is falling*, so that condition is reported rather than left for
# the reader to remember.
def test_a_dip_while_the_basket_falls_is_marked(monkeypatch):
    path = np.concatenate(
        [np.linspace(100.0, 200.0, 290), np.linspace(200.0, 150.0, 10)]
    )
    panel = _long_panel({"AAA": path})
    rows = panel.dates.shape[0]
    calm = _entry_read(monkeypatch, panel, ai_trend=np.full(rows, 0.1))
    assert calm["AAA"]["with_the_basket_falling"] is False
    falling = _entry_read(monkeypatch, panel, ai_trend=np.full(rows, -0.1))
    assert falling["AAA"]["with_the_basket_falling"] is True


# A name doing neither has no trigger and no horizon, and still reports
# where it sits, because "nothing yet" is an answer a trader can act on.
def test_a_name_with_no_trigger_still_reports_where_it_sits(monkeypatch):
    rng = np.random.default_rng(3)
    flat = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.002, 300)))
    out = _entry_read(monkeypatch, _long_panel({"AAA": flat}))
    assert out["AAA"]["trigger"] is None
    assert out["AAA"]["horizon_sessions"] is None
    assert out["AAA"]["band_z"] is not None


# A lost historical close must not masquerade as a neutral entry opinion.
def test_entry_read_retains_missing_daily_close_reason(monkeypatch):
    panel = _long_panel({"AAA": np.linspace(100.0, 200.0, 300)})
    panel.adj_close[-3, 0] = np.nan
    row = _entry_read(monkeypatch, panel)["AAA"]
    assert row["entry_status"] == "unavailable"
    assert row["missing_sessions"] == [str(panel.dates[-3])]
    assert str(panel.dates[-3]) in row["entry_reason"]
    assert row["trigger"] is None
    assert row["band_z"] is None
    assert row["horizon_sessions"] is None


# A genuine complete no-trigger reading remains distinct from unavailable data.
def test_complete_entry_read_has_explicit_available_status(monkeypatch):
    row = _entry_read(
        monkeypatch, _long_panel({"AAA": np.linspace(100.0, 200.0, 300)})
    )["AAA"]
    assert row["entry_status"] == "available"
    assert row["entry_reason"] is None
    assert row["missing_sessions"] == []
    assert row["band_z"] is not None


# Insufficient observations are not expanded into an invented twenty-day window.
def test_short_history_is_explicitly_unavailable(monkeypatch):
    row = _entry_read(monkeypatch, _long_panel({"AAA": np.linspace(100.0, 110.0, 10)}))[
        "AAA"
    ]
    assert row["entry_status"] == "unavailable"
    assert "fewer than 20" in row["entry_reason"]
    assert row["band_z"] is None


# A constant price has no standardized band and must not create infinite strength.
def test_zero_width_band_is_explicitly_unavailable(monkeypatch):
    row = _entry_read(monkeypatch, _long_panel({"AAA": np.full(300, 100.0)}))["AAA"]
    assert row["entry_status"] == "unavailable"
    assert "undefined" in row["entry_reason"]
    assert row["band_z"] is None


# A quoted name absent from cached history still gets an explanatory row.
def test_quoted_name_without_history_is_retained(monkeypatch):
    panel = _long_panel({"AAA": np.linspace(100.0, 200.0, 300)})
    monkeypatch.setattr(live_technical, "_live_read", lambda *args: {"panel": panel})
    row = live_technical.entry_now(
        None, {"MISSING": SimpleNamespace(last=10, bar="x")}, date(2026, 9, 18)
    )["MISSING"]
    assert row["entry_status"] == "unavailable"
    assert "no daily history" in row["entry_reason"]
    assert row["trigger"] is None
