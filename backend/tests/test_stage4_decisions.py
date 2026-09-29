"""Stage 4's decision engine on hand-made orders, fills, panels and cubes.

What has to hold (docs/research/stage4-plan-2026-09-29.md, "The candidates",
"The decision test", "Kill criteria, fixed now"):

- Each decider picks, per order, its own fill or the control's: D0 the
  level always; D1 the level only for a buy with the VIX under 25 at t and
  no earnings in t-2..t, and for a sell with no earnings in t-2..t; D2 and
  D3 their rule's fill (the control where inactive); D4-D6 the level where
  the family's forecast for the side is above zero, the control otherwise,
  a missing forecast counted.
- g is `stage4_labels.gain` in bp of the order, d the fill session - 1; an
  order without a price fills as the control (g = 0, d = 0) and is counted.
- The book's session gain is the sum of weight x g over the orders decided
  that session, zero elsewhere; windows go by decision date, the model
  window from the latest first-forecast date (2018-01-02 without files).
- The statistics are read at offset offsets // 2; the per-re-timed-order t
  is clustered by decision date; the drift-adjusted gain is g - s·μ·d.
- The next-bar run reads the next-bar fills; the seeds decide one at a
  time and are stable with fewer than two sign changes; the deflated Sharpe
  is taken at N = 14 over the priced candidates' Sharpe variance.
- Every verdict criterion passes at its edge and fails just past it; "real
  but immaterial" needs the floor to fail and 25 bp at t 3 per re-timed
  order; a model without its file is SKIPPED.
- The command runs end to end on stub loaders, records the inputs'
  sha256, and refuses bad inputs before the desk runs.
"""

from __future__ import annotations

import hashlib
import io as textio
import json
import math
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import candidate_stats, stage3_verdict
from backend.market import stage3_io as io
from backend.market import stage4_decisions as sd
from backend.market import stage4_labels as lab
from backend.market import stage4_orders as so
from backend.market.fill_timing import clustered_t
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube
from backend.tests.test_stage4_labels import _cube, _zigzag
from backend.tests.test_stage4_orders import _history, _report

SLOTS = FULL_SESSION_SLOTS


# `n` weekdays from `start`, as datetime64[D].
def _weekdays(start: date, n: int) -> np.ndarray:
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return np.array(out, dtype="datetime64[D]")


# A fill grid where every convention fills at `control` in session t + 1
# (days 1), no rule active; tests then set the cells they need.
def _grid(
    T: int, N: int, next_bar: bool = False, control: float = 100.0
) -> sd.FillGrid:
    return sd.FillGrid(
        next_bar=next_bar,
        price={
            (c, s): np.full((T, N), control) for c in lab.CONVENTIONS for s in sd.SIDES
        },
        days={
            (c, s): np.ones((T, N), dtype=np.int64)
            for c in lab.CONVENTIONS
            for s in sd.SIDES
        },
        active={
            (c, s): np.zeros((T, N), dtype=bool)
            for c in lab.CONVENTIONS
            for s in sd.SIDES
        },
    )


# A market over the dates and tickers: the given grids, no oracle unless
# given, the VIX (20 by default), the earnings sessions, grades A+ and flat
# closes unless given, and the forecasts.
def _market(
    dates,
    tickers,
    fills,
    next_bar=None,
    vix=None,
    earnings=None,
    forecasts=None,
    oracle=None,
    grades=None,
    closes=None,
) -> sd.Market:
    T, N = len(dates), len(tickers)
    return sd.Market(
        dates=np.asarray(dates, dtype="datetime64[D]"),
        tickers=tuple(tickers),
        fills=fills,
        next_bar=next_bar if next_bar is not None else _grid(T, N, next_bar=True),
        oracle=oracle
        if oracle is not None
        else {s: np.full((T, N), np.nan) for s in sd.SIDES},
        vix=np.full(T, 20.0) if vix is None else np.asarray(vix, dtype=float),
        recent=sd.recent_earnings(
            np.zeros((T, N), dtype=bool) if earnings is None else earnings
        ),
        grades=np.full((T, N), so.A_PLUS) if grades is None else np.asarray(grades),
        closes=np.full((T, N), 100.0)
        if closes is None
        else np.asarray(closes, dtype=float),
        forecasts=dict(forecasts or {}),
    )


# Orders from (session, column, side, weight[, kind, detail, grade]) rows,
# for a run over decision sessions [start, stop).
def _orders(rows, tickers, start=0, stop=None, basis=so.EXECUTED) -> so.Orders:
    full = [
        r + ("midcycle", "add", so.A_PLUS)[len(r) - 4 :] if len(r) < 7 else r
        for r in rows
    ]
    session = np.array([r[0] for r in full], dtype=np.int64)
    column = np.array([r[1] for r in full], dtype=np.int64)
    side = np.array([r[2] for r in full], dtype=str)
    weight = np.array([r[3] for r in full], dtype=float)
    units = np.where(side == "buy", 1.0, -1.0) * weight / 100.0
    return so.Orders(
        session=session,
        column=column,
        ticker=np.array([tickers[j] for j in column], dtype=str),
        side=side,
        units=units,
        submitted=units.copy(),
        executed=units.copy(),
        weight=weight,
        kind=np.array([r[4] for r in full], dtype=str),
        detail=np.array([r[5] for r in full], dtype=str),
        grade=np.array([r[6] for r in full], dtype=np.int64),
        held=np.zeros(len(full)),
        start=start,
        stop=stop if stop is not None else int(session.max()) + 2,
        basis=basis,
    )


# A model forecast placed directly on the grid: `cells` {(t, j): yhat},
# seeds equal to the ensemble unless `seeds` {(t, j): [five values]}.
def _forecast(
    family, side, T, N, cells, seeds=None, first=date(2018, 1, 2)
) -> sd.ModelForecast:
    grid = np.full((T, N), np.nan)
    seed_grid = np.full((T, N, 5), np.nan)
    for (t, j), v in cells.items():
        grid[t, j] = v
        seed_grid[t, j] = v
    for (t, j), values in (seeds or {}).items():
        seed_grid[t, j] = values
    return sd.ModelForecast(
        family, side, grid, seed_grid, first, {"family": family, "side": side}
    )


# The buy and sell gain of a candidate fill over the control, in bp.
def _g(control: float, fill: float, side: str) -> float:
    return (
        1e4 * math.log(control / fill)
        if side == "buy"
        else 1e4 * math.log(fill / control)
    )


# Each decider's choice per order, on a hand-made grid. Buys o0-o3, sells
# o4-o5; the level fills at 98 (buy, day 3) and 103 (sell, day 2); the turn
# acts at (2, X) and (4, Y) for buys (97, day 4) and (2, Y) for sells (104,
# day 2); the squeeze at (3, X) for buys (99, day 5). X has earnings on
# sessions 0 and 5; the VIX is 30 at t = 4 and unknown at t = 5.
def test_each_decider_chooses_its_fill_per_order():
    T, tickers = 10, ("X", "Y")
    X, Y = 0, 1
    dates = np.datetime64("2023-06-01", "D") + np.arange(T)
    grid = _grid(T, 2)
    grid.price[(lab.LEVEL, "buy")][:] = 98.0
    grid.days[(lab.LEVEL, "buy")][:] = 3
    grid.price[(lab.LEVEL, "sell")][:] = 103.0
    grid.days[(lab.LEVEL, "sell")][:] = 2
    for t, j in ((2, X), (4, Y)):
        grid.price[(lab.TURN, "buy")][t, j] = 97.0
        grid.days[(lab.TURN, "buy")][t, j] = 4
        grid.active[(lab.TURN, "buy")][t, j] = True
    grid.price[(lab.TURN, "sell")][2, Y] = 104.0
    grid.days[(lab.TURN, "sell")][2, Y] = 2
    grid.active[(lab.TURN, "sell")][2, Y] = True
    grid.price[(lab.SQUEEZE, "buy")][3, X] = 99.0
    grid.days[(lab.SQUEEZE, "buy")][3, X] = 5
    grid.active[(lab.SQUEEZE, "buy")][3, X] = True
    vix = np.full(T, 20.0)
    vix[4], vix[5] = 30.0, np.nan
    earnings = np.zeros((T, 2), dtype=bool)
    earnings[0, X] = earnings[5, X] = True
    lgbm = _forecast(io.LGBM, "buy", T, 2, {(2, X): 0.5, (3, X): -0.1, (5, Y): 0.0})
    cnn = _forecast(
        io.CNN_I20,
        "buy",
        T,
        2,
        {(5, Y): -1.0},
        seeds={(5, Y): [-1.0, -1.0, 2.0, -1.0, -1.0]},
    )
    market = _market(
        dates,
        tickers,
        grid,
        vix=vix,
        earnings=earnings,
        forecasts={(io.LGBM, "buy"): lgbm, (io.CNN_I20, "buy"): cnn},
    )
    orders = _orders(
        [
            (2, X, "buy", 0.1),
            (3, X, "buy", 0.1),
            (4, Y, "buy", 0.1),
            (5, Y, "buy", 0.1),
            (2, Y, "sell", 0.1),
            (6, X, "sell", 0.1),
        ],
        tickers,
    )
    lvl_b, lvl_s = _g(100, 98, "buy"), _g(100, 103, "sell")

    # The gains and waits a candidate's book holds, in order.
    def gains(candidate, **kwargs):
        book = sd.price_book(orders, market, candidate, **kwargs)
        return book.gain.tolist(), book.wait.tolist(), book

    g, d, book = gains("D0_buy")
    assert (
        g == pytest.approx([lvl_b] * 4)
        and d == [2, 2, 2, 2]
        and book.rows.tolist() == [0, 1, 2, 3]
    )
    g, d, _ = gains("D0_sell")
    assert g == pytest.approx([lvl_s] * 2) and d == [1, 1]
    # D1 buys: o0 has earnings at t-2 (control), o1 at t-3 (acts), o2 in
    # stress and o3 without a VIX act at once.
    g, d, book = gains("D1_buy")
    assert g == pytest.approx([0.0, lvl_b, 0.0, 0.0]) and d == [0, 2, 0, 0]
    assert book.acted.tolist() == [False, True, False, False]
    # D1 sells ignore the VIX: o4 waits; o5 has earnings at t-1.
    g, d, _ = gains("D1_sell")
    assert g == pytest.approx([lvl_s, 0.0]) and d == [1, 0]
    g, d, book = gains("D2_buy")
    assert g == pytest.approx(
        [_g(100, 97, "buy"), 0.0, _g(100, 97, "buy"), 0.0]
    ) and d == [3, 0, 3, 0]
    assert book.acted.tolist() == [True, False, True, False]
    g, d, _ = gains("D2_sell")
    assert g == pytest.approx([_g(100, 104, "sell"), 0.0]) and d == [1, 0]
    g, d, _ = gains("D3_buy")
    assert g == pytest.approx([0.0, _g(100, 99, "buy"), 0.0, 0.0]) and d == [0, 4, 0, 0]
    g, d, _ = gains("D3_sell")
    assert g == [0.0, 0.0]
    # D4 buys: +0.5 waits, -0.1 and 0.0 act at once, no forecast at (4, Y).
    g, d, book = gains("D4_buy")
    assert g == pytest.approx([lvl_b, 0.0, 0.0, 0.0]) and d == [2, 0, 0, 0]
    assert book.no_forecast.tolist() == [False, False, True, False]
    # D4 sells have no file: every order fills as the control, counted.
    g, d, book = gains("D4_sell")
    assert g == [0.0, 0.0] and book.no_forecast.all()
    # D5 reads its own family; seed 2 waits where the ensemble does not.
    g, _, _ = gains("D5_buy")
    assert g == [0.0, 0.0, 0.0, 0.0]
    g, d, _ = gains("D5_buy", seed=2)
    assert g == pytest.approx([0.0, 0.0, 0.0, lvl_b]) and d == [0, 0, 0, 2]
    with pytest.raises(ValueError, match="unknown candidate"):
        sd.price_book(orders, market, "D7_buy")
    # The stress edge: a VIX of exactly 25 is stress (the buy acts at once),
    # just under 25 is calm (it waits).
    edge_vix = np.full(T, 20.0)
    edge_vix[7], edge_vix[8] = 25.0, np.nextafter(25.0, 0.0)
    edge = _market(dates, tickers, grid, vix=edge_vix)
    two = _orders([(7, Y, "buy", 0.1), (8, Y, "buy", 0.1)], tickers)
    assert sd.price_book(two, edge, "D1_buy").gain.tolist() == pytest.approx(
        [0.0, lvl_b]
    )
    # Sells never read the VIX: in stress or without one they still wait.
    stressed = _orders(
        [(4, Y, "sell", 0.1), (5, Y, "sell", 0.1), (7, Y, "sell", 0.1)], tickers
    )
    assert sd.price_book(stressed, edge, "D1_sell").gain.tolist() == pytest.approx(
        [lvl_s] * 3
    )
    assert sd.price_book(stressed, market, "D1_sell").gain.tolist() == pytest.approx(
        [lvl_s] * 3
    )


# The book's gain: weight x g summed over the orders decided on a session,
# zero on the others; the windows by decision date (an order decided on
# 2023-12-29 belongs to the model window); the mean and Newey-West t over
# each window's decision sessions; the re-timed orders' mean with its
# date-clustered t; the model window from the latest first-forecast date.
def test_book_series_weights_and_windows():
    dates = _weekdays(date(2023, 12, 18), 20)
    T, tickers = len(dates), ("X", "Y")
    grid = _grid(T, 2)
    grid.price[(lab.LEVEL, "buy")][3, 0] = 98.0
    grid.price[(lab.LEVEL, "buy")][3, 1] = 99.0
    grid.price[(lab.LEVEL, "buy")][9, 1] = 99.5
    grid.price[(lab.LEVEL, "buy")][12, 0] = 101.0
    grid.price[(lab.LEVEL, "buy")][13, 0] = 97.0
    oracle = {side: np.full((T, 2), np.nan) for side in sd.SIDES}
    oracle["buy"][3, 0], oracle["buy"][3, 1], oracle["buy"][9, 1] = 96.0, 97.0, 99.0
    market = _market(dates, tickers, grid, oracle=oracle)
    orders = _orders(
        [
            (3, 0, "buy", 0.1),
            (3, 1, "buy", 0.05),
            (9, 1, "buy", 0.02),
            (12, 0, "buy", 0.2),
            (13, 0, "buy", 0.1),
        ],
        tickers,
        stop=T - 1,
    )
    book = sd.price_book(orders, market, "D0_buy")
    g = [
        _g(100, 98, "buy"),
        _g(100, 99, "buy"),
        _g(100, 99.5, "buy"),
        _g(100, 101, "buy"),
        _g(100, 97, "buy"),
    ]
    series = sd.session_series(book, book.gain)
    expected = np.zeros(T - 1)
    expected[3] = 0.1 * g[0] + 0.05 * g[1]
    expected[9] = 0.02 * g[2]
    expected[12] = 0.2 * g[3]
    expected[13] = 0.1 * g[4]
    np.testing.assert_allclose(series, expected, rtol=1e-12)
    first = _forecast(io.LGBM, "buy", T, 2, {(0, 0): 1.0}, first=date(2023, 12, 19))
    later = _forecast(io.SEQ, "sell", T, 2, {(0, 0): 1.0}, first=date(2023, 12, 20))
    start, source, files = sd.model_start(
        {(io.LGBM, "buy"): first, (io.SEQ, "sell"): later}
    )
    assert (start, source) == (date(2023, 12, 20), "forecasts")
    assert files == {"lgbm_buy": "2023-12-19", "seq_sell": "2023-12-20"}
    assert sd.model_start({}) == (date(2018, 1, 2), "default", {})
    spans = sd.windows(start)
    assert spans == {
        "model": (date(2023, 12, 20), date(2024, 1, 1)),
        "2024-2026": (date(2024, 1, 1), None),
    }
    model = sd.summarize(book, dates, *spans["model"], mu_bp=0.0)
    # Sessions 2..9 (2023-12-20 .. 2023-12-29) are the model window.
    assert model["sessions"] == 8 and model["orders"] == 3
    assert model["mean_bp"] == pytest.approx(expected[2:10].mean(), rel=1e-12)
    assert model["hac_t"] == pytest.approx(
        candidate_stats.hac_t(expected[2:10], 20), rel=1e-12
    )
    assert model["retimed"] == 3 and model["retimed_bp"] == pytest.approx(
        np.mean(g[:3])
    )
    assert model["retimed_t"] == pytest.approx(
        clustered_t(np.array(g[:3]), np.array([3, 3, 9]))
    )
    assert model["retimed_sessions"] == 2 and model["sessions_with_orders"] == 2
    assert model["waited"] == 0 and model["mean_wait"] != model["mean_wait"]
    assert model["excess"]["length"] == 8
    # The oracle's capture: sums of gains over sums of oracle gains, plain
    # and weighted by the orders' weights.
    best = [_g(100, 96, "buy"), _g(100, 97, "buy"), _g(100, 99, "buy")]
    weights = [0.1, 0.05, 0.02]
    assert model["oracle_orders"] == 3 and model["oracle_bp"] == pytest.approx(
        np.mean(best)
    )
    assert model["capture"] == pytest.approx(sum(g[:3]) / sum(best))
    assert model["capture_weighted"] == pytest.approx(
        sum(w * x for w, x in zip(weights, g[:3], strict=True))
        / sum(w * b for w, b in zip(weights, best, strict=True))
    )
    assert model["capture"] != pytest.approx(model["capture_weighted"])
    later_window = sd.summarize(book, dates, *spans["2024-2026"], mu_bp=0.0)
    # Sessions 10..18: the run's last decision session is 18.
    assert later_window["sessions"] == 9 and later_window["orders"] == 2
    assert later_window["mean_bp"] == pytest.approx(
        (0.2 * g[3] + 0.1 * g[4]) / 9, rel=1e-12
    )
    assert later_window["oracle_orders"] == 0 and math.isnan(later_window["capture"])
    assert sd.window_mean(book, dates, *spans["2024-2026"]) == pytest.approx(
        later_window["mean_bp"]
    )
    # A subset reads only its orders.
    only_y = sd.summarize(
        book, dates, *spans["model"], mu_bp=0.0, subset=orders.column[book.rows] == 1
    )
    assert only_y["orders"] == 2
    assert only_y["mean_bp"] == pytest.approx(
        (0.05 * g[1] + 0.02 * g[2]) / 8, rel=1e-12
    )
    bad = _orders([(3, 0, "buy", 0.1)], tickers, start=4, stop=10)
    with pytest.raises(ValueError, match="outside"):
        sd.session_series(sd.price_book(bad, market, "D0_buy"), np.ones(1))


# An order whose chosen fill or control has no price fills as the control:
# g = 0, d = 0, counted as unpriced - an order before the cubes start too;
# an order a decider leaves to a priced control is not unpriced.
def test_unpriced_orders_fill_as_the_control_and_are_counted():
    T, tickers = 12, ("X", "Y")
    dates = np.datetime64("2023-06-01", "D") + np.arange(T)
    grid = _grid(T, 2)
    grid.price[(lab.LEVEL, "buy")][:] = 98.0
    grid.days[(lab.LEVEL, "buy")][:] = 3
    grid.price[(lab.CONTROL, "buy")][:2, :] = np.nan  # before the cubes start
    grid.price[(lab.LEVEL, "buy")][:2, :] = np.nan
    grid.days[(lab.CONTROL, "buy")][:2, :] = 0
    grid.price[(lab.LEVEL, "buy")][6, 0] = np.nan  # a window with a missing session
    vix = np.full(T, 20.0)
    vix[6] = 40.0
    market = _market(dates, tickers, grid, vix=vix)
    orders = _orders(
        [(1, 0, "buy", 0.1), (4, 1, "buy", 0.1), (6, 0, "buy", 0.1)],
        tickers,
        stop=T - 1,
    )
    d0 = sd.price_book(orders, market, "D0_buy")
    assert d0.unpriced.tolist() == [True, False, True]
    assert d0.gain.tolist() == pytest.approx(
        [0.0, _g(100, 98, "buy"), 0.0]
    ) and d0.wait.tolist() == [0, 2, 0]
    stats = sd.summarize(d0, dates, None, None, 0.0)
    assert (stats["orders"], stats["unpriced"], stats["retimed"], stats["waited"]) == (
        3,
        2,
        1,
        1,
    )
    # D1 leaves the third order (VIX 40) to its priced control: not unpriced.
    d1 = sd.price_book(orders, market, "D1_buy")
    assert d1.unpriced.tolist() == [True, False, False] and d1.gain[2] == 0.0


# The next-bar run reads the next-bar grid, for candidate and control alike.
def test_next_bar_reads_the_next_bar_fills():
    T, tickers = 8, ("X",)
    dates = np.datetime64("2023-06-01", "D") + np.arange(T)
    grid = _grid(T, 1)
    grid.price[(lab.LEVEL, "buy")][:] = 98.0
    nb = _grid(T, 1, next_bar=True, control=100.5)
    nb.price[(lab.LEVEL, "buy")][:] = 99.0
    market = _market(dates, tickers, grid, next_bar=nb)
    orders = _orders([(2, 0, "buy", 0.1)], tickers)
    assert sd.price_book(orders, market, "D0_buy").gain[0] == pytest.approx(
        _g(100, 98, "buy")
    )
    assert sd.price_book(orders, market, "D0_buy", next_bar=True).gain[
        0
    ] == pytest.approx(_g(100.5, 99, "buy"))
    with pytest.raises(ValueError, match="bar-close grid"):
        sd.build_market(
            SimpleNamespace(dates=dates, tickers=tickers, adj_close=np.ones((T, 1))),
            np.zeros((T, 1)),
            nb,
            grid,
            market.oracle,
            np.zeros(T),
            np.zeros((T, 1)),
        )


# The grids are `stage4_labels.name_fills` of each name with a cube, in
# both fill modes; a name without a cube is unpriced; the oracle is the
# lowest (buy) or highest (sell) adjusted bar close over t+1..t+5, NaN when
# a session of the window is missing.
def test_fill_grids_are_the_labels_fills_and_the_oracle():
    T = 60
    dates = np.datetime64("2024-01-01", "D") + np.arange(T)
    closes = _zigzag(T)
    t = 40
    paths = {t + 2: np.full(SLOTS, closes[t + 2]), t + 4: np.full(SLOTS, closes[t + 4])}
    paths[t + 2][5] = closes[t] * 0.9
    paths[t + 4][7] = closes[t] * 1.2
    cube = _cube(dates, closes, paths=paths, drop=(10,))
    panel = SimpleNamespace(
        dates=dates,
        tickers=("X", "Y"),
        benchmark="Y",
        close=np.column_stack([closes, closes]),
        adj_close=np.column_stack([closes, closes]),
        high=np.column_stack([closes, closes]),
        low=np.column_stack([closes, closes]),
    )
    fills, nb, oracle, coverage = sd.fill_grids(panel, {"X": cube})
    assert coverage["names_with_cube"] == 1 and coverage["names_without_cube"] == ["Y"]
    series = lab.name_series(dates, closes, closes, closes, closes)
    for mode, grid in ((False, fills), (True, nb)):
        assert grid.next_bar is mode
        for key, f in lab.name_fills(series, cube, next_bar=mode).items():
            np.testing.assert_array_equal(grid.price[key][:, 0], f.price)
            np.testing.assert_array_equal(grid.days[key][:, 0], f.days)
            np.testing.assert_array_equal(grid.active[key][:, 0], f.active)
            assert np.isnan(grid.price[key][:, 1]).all()
    assert oracle["buy"][t, 0] == pytest.approx(closes[t] * 0.9)
    assert oracle["sell"][t, 0] == pytest.approx(closes[t] * 1.2)
    window = [closes[t + j] for j in range(1, 6)]
    assert oracle["buy"][t - 3, 0] == pytest.approx(
        min(min(window[:2]), closes[t] * 0.9, min(closes[t - 2 : t + 1]))
    )
    assert np.isnan(oracle["buy"][7, 0]) and np.isfinite(
        oracle["buy"][10, 0]
    )  # session 10 is missing
    assert np.isnan(oracle["buy"][T - 3, 0]) and np.isnan(oracle["sell"][:, 1]).all()


# The drift: μ is the mean daily log return of the name-days graded A/A+
# in the window; a sell's gain is lowered by μ·d, a buy's raised, and the
# drift-adjusted series is aggregated like the gain.
def test_drift_adjustment():
    T, tickers = 30, ("X", "Y", "Z")
    dates = np.datetime64("2023-03-01", "D") + np.arange(T)
    steps = np.arange(T)[:, None]
    closes = 100.0 * np.exp(steps * np.array([[0.001, 0.005, 0.001]]))
    grades = np.tile(np.array([so.A_PLUS, so.B, so.A]), (T, 1))
    grid = _grid(T, 3)
    grid.price[(lab.LEVEL, "buy")][5, 0] = 99.0
    grid.days[(lab.LEVEL, "buy")][5, 0] = 4
    grid.price[(lab.LEVEL, "sell")][8, 1] = 101.0
    grid.days[(lab.LEVEL, "sell")][8, 1] = 3
    market = _market(dates, tickers, grid, grades=grades, closes=closes)
    reading = sd.drift(market, None, None)
    # X and Z are A/A+: 2 names x 29 sessions with a next close.
    assert reading["name_days"] == 58
    assert reading["mu"] == pytest.approx(0.001, rel=1e-9) and reading[
        "mu_bp"
    ] == pytest.approx(10.0, rel=1e-9)
    orders = _orders([(5, 0, "buy", 0.1), (8, 1, "sell", 0.2)], tickers, stop=T - 1)
    buy = sd.price_book(orders, market, "D0_buy")
    sell = sd.price_book(orders, market, "D0_sell")
    mu = reading["mu_bp"]
    assert sd.drift_adjusted(buy, mu)[0] == pytest.approx(_g(100, 99, "buy") + mu * 3)
    assert sd.drift_adjusted(sell, mu)[0] == pytest.approx(
        _g(100, 101, "sell") - mu * 2
    )
    stats = sd.summarize(sell, dates, None, None, mu)
    assert stats["drift_mean_bp"] == pytest.approx(
        0.2 * (_g(100, 101, "sell") - mu * 2) / (T - 1)
    )
    assert stats["mean_bp"] == pytest.approx(0.2 * _g(100, 101, "sell") / (T - 1))
    assert (
        sd.summarize(sell, dates, None, None, math.nan)["drift_mean_bp"]
        != stats["drift_mean_bp"]
    )
    window = sd.drift(market, date(2023, 3, 10), date(2023, 3, 12))
    assert window["name_days"] == 4


# The whole engine over three offsets of hand-made orders: the statistics
# are those of offset 3 // 2 = 1; the per-offset means of every offset; the
# next-bar run; the seeds (one flips sign, one is missing: two changes, not
# stable; the sell model has one change, stable); the deflated Sharpe at
# N = 14 over the priced candidates' variance; the splits; the payload's
# windows from the forecasts' first date.
def test_evaluate_median_offset_seeds_and_deflated_sharpe():
    dates = _weekdays(date(2023, 1, 2), 330)
    T, tickers = len(dates), ("X", "Y")
    rng = np.random.default_rng(7)
    grid = _grid(T, 2)
    grid.price[(lab.LEVEL, "buy")][:] = 100.0 * np.exp(
        -rng.normal(0.004, 0.01, size=(T, 2))
    )
    grid.days[(lab.LEVEL, "buy")][:] = rng.integers(1, 6, size=(T, 2))
    grid.price[(lab.LEVEL, "sell")][:] = 100.0 * np.exp(
        rng.normal(0.002, 0.01, size=(T, 2))
    )
    grid.days[(lab.LEVEL, "sell")][:] = rng.integers(1, 6, size=(T, 2))
    nb = _grid(T, 2, next_bar=True)
    nb.price[(lab.LEVEL, "buy")][:] = grid.price[(lab.LEVEL, "buy")] * 1.001
    oracle = {"buy": np.full((T, 2), 95.0), "sell": np.full((T, 2), 105.0)}
    buy_cells = {(t, j): 1.0 for t in range(T) for j in range(2)}
    seeds = {cell: [1.0, -1.0, 1.0, 1.0, np.nan] for cell in buy_cells}
    lgbm_buy = _forecast(
        io.LGBM, "buy", T, 2, buy_cells, seeds=seeds, first=date(2023, 2, 1)
    )
    sell_cells = {(t, j): 1.0 for t in range(T) for j in range(2)}
    sell_seeds = {cell: [1.0, 1.0, -1.0, 1.0, 1.0] for cell in sell_cells}
    lgbm_sell = _forecast(
        io.LGBM, "sell", T, 2, sell_cells, seeds=sell_seeds, first=date(2023, 1, 20)
    )
    market = _market(
        dates,
        tickers,
        grid,
        next_bar=nb,
        oracle=oracle,
        forecasts={(io.LGBM, "buy"): lgbm_buy, (io.LGBM, "sell"): lgbm_sell},
    )
    runs = []
    for k in range(3):
        rows = [
            (
                t,
                t % 2,
                "buy" if (t // 7) % 2 == 0 else "sell",
                0.05 + 0.01 * k,
                "rebalance" if t % 20 == k else "midcycle",
                "entry" if t % 3 else "add",
                so.A_PLUS if t % 2 else so.A,
            )
            for t in range(k, T - 1, 3)
        ]
        runs.append(_orders(rows, tickers, start=k, stop=T - 1))
    payload = sd.evaluate(runs, market, registered=3)
    assert payload["offsets"] == {
        "registered": 3,
        "priced": 3,
        "median": 1,
        "smoke": False,
        "starts": [0, 1, 2],
    }
    assert payload["model_start"] == {
        "date": "2023-02-01",
        "source": "forecasts",
        "files": {"lgbm_buy": "2023-02-01", "lgbm_sell": "2023-01-20"},
    }
    assert payload["windows"]["model"] == ["2023-02-01", "2024-01-01"]
    spans = sd.windows(date(2023, 2, 1))
    mus = {w: sd.drift(market, lo, hi)["mu_bp"] for w, (lo, hi) in spans.items()}
    for c in sd.CANDIDATES:
        means = [
            sd.window_mean(sd.price_book(o, market, c), dates, *spans["model"])
            for o in runs
        ]
        assert payload["per_offset"][c]["model_bp"] == pytest.approx(means)
        assert len(payload["per_offset"][c]["next_bar_model_bp"]) == 3
        at = sd.summarize(
            sd.price_book(runs[1], market, c), dates, *spans["model"], mus["model"]
        )
        got = payload["results"][c]["default"]["model"]
        assert (
            got["mean_bp"] == pytest.approx(at["mean_bp"])
            and got["orders"] == at["orders"]
        )
        nb_at = sd.summarize(
            sd.price_book(runs[1], market, c, next_bar=True),
            dates,
            *spans["model"],
            mus["model"],
        )
        assert payload["results"][c]["next_bar"]["model"]["mean_bp"] == pytest.approx(
            nb_at["mean_bp"]
        )
    assert payload["results"]["D0_buy"]["default"]["model"]["mean_bp"] > 0
    means = payload["per_offset"]["D0_buy"]["model_bp"]
    across = payload["results"]["D0_buy"]["across_offsets"]
    assert across["offsets"] == 3 and across["median"] == pytest.approx(
        float(np.median(means))
    )
    assert across["offset_at_lower_median_mean"] == int(
        np.argsort(means, kind="stable")[1]
    )
    # The median offset's orders per window, over that window's decision sessions.
    model_orders = payload["orders"]["median_by_window"]["model"]
    in_model = sd.session_window(
        sd.price_book(runs[1], market, "D0_buy"), dates, *spans["model"]
    )
    assert model_orders["decision_sessions"] == int(in_model.sum())
    assert model_orders["orders"] == sum(
        payload["results"][c]["default"]["model"]["orders"]
        for c in ("D0_buy", "D0_sell")
    )
    assert model_orders["orders_per_session"] == pytest.approx(
        model_orders["orders"] / in_model.sum()
    )
    # D4 buy waits wherever the ensemble does; seed 1 never waits (zero)
    # and seed 4 is missing: two changes. D4 sell: seed 2 alone changes.
    seeds_buy = payload["results"]["D4_buy"]["seeds"]["model_bp"]
    reference = payload["results"]["D4_buy"]["default"]["model"]["mean_bp"]
    assert (
        seeds_buy[0] == pytest.approx(reference)
        and seeds_buy[1] == 0.0
        and seeds_buy[4] == 0.0
    )
    seed_stats = payload["results"]["D4_buy"]["seeds"]["stats"]
    assert payload["results"]["D4_buy"]["seeds"]["columns"] == [0, 1, 2, 3, 4]
    assert [s["model"]["mean_bp"] for s in seed_stats] == seeds_buy and seed_stats[4][
        "model"
    ]["no_forecast"] > 0
    assert seed_stats[1]["model"]["retimed"] == 0 and set(seed_stats[0]) == {
        "model",
        "2024-2026",
    }
    stability = payload["seed_stability"]["D4_buy"]
    assert stability == stage3_verdict.seed_stability(reference, seeds_buy)
    assert stability["sign_changes"] == 2 and not stability["stable"]
    assert (
        payload["seed_stability"]["D4_sell"]["sign_changes"] == 1
        and payload["seed_stability"]["D4_sell"]["stable"]
    )
    assert set(payload["seed_stability"]) == {
        "D4_buy",
        "D4_sell",
        "D5_buy",
        "D5_sell",
        "D6_buy",
        "D6_sell",
    }
    # The deflated Sharpe at N = 14 over the priced candidates' Sharpe variance.
    priced = [c for c in sd.CANDIDATES if payload["candidates"][c]["priced"]]
    assert priced == [c for c in sd.CANDIDATES if not c.startswith(("D5", "D6"))]
    sharpes = np.array(
        [payload["results"][c]["default"]["model"]["excess"]["sharpe"] for c in priced]
    )
    variance = float(sharpes[np.isfinite(sharpes)].var(ddof=1))
    for c in ("D0_buy", "D4_sell"):
        e = payload["results"][c]["default"]["model"]["excess"]
        record = payload["deflated"][c]
        assert record["trial_variance"] == pytest.approx(variance)
        assert record["dsr"] == pytest.approx(
            candidate_stats.deflated_sharpe(
                e["sharpe"], e["length"], e["skew"], e["kurtosis"], 14, variance
            )
        )
        assert record["dsr_cumulative"] == pytest.approx(
            candidate_stats.deflated_sharpe(
                e["sharpe"], e["length"], e["skew"], e["kurtosis"], 451, variance
            )
        )
        assert record["passes"] == (record["dsr"] >= 0.95)
    assert (
        math.isnan(payload["deflated"]["D5_buy"]["dsr"])
        and not payload["deflated"]["D5_buy"]["passes"]
    )
    assert payload["constants"]["expected_best_null_t"]["cumulative"] == pytest.approx(
        3.02, abs=0.01
    )
    # The splits partition the side's orders.
    split = payload["results"]["D0_buy"]["splits"]
    total = payload["results"]["D0_buy"]["default"]["model"]["orders"]
    for group, labels in sd.group_values("buy").items():
        assert (
            sum(split[group][label]["model"]["orders"] for label in labels) == total
        ), group
    assert (
        split["grade"]["a"]["model"]["orders"] > 0
        and split["grade"]["a_plus"]["model"]["orders"] > 0
    )
    assert split["kind"]["rebalance"]["model"]["orders"] > 0
    # The oracle: every order's best close is 95 / 105 against a control of 100.
    model = payload["results"]["D0_buy"]["default"]["model"]
    assert model["oracle_bp"] == pytest.approx(_g(100, 95, "buy"))
    assert model["capture"] == pytest.approx(model["per_order_bp"] / _g(100, 95, "buy"))
    assert payload["verdict"]["candidates"]["D5_buy"]["label"] == sd.SKIPPED
    assert len(payload["verdict"]["lines"]) == 14
    json.dumps(io.clean_json(payload), allow_nan=False)
    with pytest.raises(ValueError, match="no offsets"):
        sd.evaluate([], market)
    with pytest.raises(ValueError, match="bases"):
        sd.evaluate(
            [runs[0], _orders([(3, 0, "buy", 0.1)], tickers, basis=so.SUBMITTED)],
            market,
        )


# A payload skeleton whose every candidate clears every criterion exactly
# at its edge, for the verdict tests to move one number at a time. Its
# per-re-timed-order reading (20 bp) is below the immaterial floor, so a
# failed floor reads RECORD unless a test raises it.
def _passing_payload() -> dict:
    stats = {
        "mean_bp": 2.0,
        "hac_t": 2.0,
        "drift_mean_bp": 1.0,
        "drift_hac_t": 2.0,
        "retimed_bp": 20.0,
        "retimed_t": 4.0,
        "orders": 100,
        "retimed": 60,
        "waited_share": 0.5,
        "mean_wait": 2.0,
    }
    later = dict(stats, mean_bp=0.0)
    candidates, results, dsr, seeds = {}, {}, {}, {}
    for c in sd.CANDIDATES:
        decider, side = c.split("_")
        family = sd.MODEL_FAMILIES.get(decider)
        candidates[c] = {
            "decider": decider,
            "rule": sd.DECIDERS[decider],
            "side": side,
            "family": family,
            "priced": True,
        }
        results[c] = {
            "default": {"model": dict(stats), "2024-2026": dict(later)},
            "next_bar": {"model": dict(stats), "2024-2026": dict(later)},
        }
        dsr[c] = {"dsr": 0.95, "passes": True}
        if family is not None:
            seeds[c] = stage3_verdict.seed_stability(2.0, [1.0, 1.0, 1.0, 1.0, -1.0])
    return {
        "candidates": candidates,
        "results": results,
        "deflated": dsr,
        "seed_stability": seeds,
        "offsets": {"registered": 20, "priced": 20, "median": 10, "smoke": False},
    }


# Every criterion at its edge: the passing skeleton REPLACES; each number
# moved just past its floor makes a RECORD; "real but immaterial" needs the
# floor to fail and 25 bp at t 3 per re-timed order, and never overrides a
# passing floor; seeds bind only the models; a model without its file is
# SKIPPED; a smoke run says so.
def test_verdict_criteria_at_their_edges():
    base = _passing_payload()
    record = sd.verdict(base)
    assert record["replaces"] == list(sd.CANDIDATES) and record["immaterial"] == []
    assert all(v["label"] == sd.REPLACES for v in record["candidates"].values())
    assert record["text"].startswith("REPLACES: D0_buy")

    # The label of `candidate` after `change` edits a fresh skeleton.
    def label(candidate, change) -> str:
        payload = _passing_payload()
        change(payload, payload["results"][candidate])
        return sd.verdict(payload)["candidates"][candidate]["label"]

    eps = 1e-9
    moves = {
        "floor bp": lambda p, r: r["default"]["model"].update(mean_bp=2.0 - eps),
        "floor t": lambda p, r: r["default"]["model"].update(hac_t=2.0 - eps),
        "next-bar bp": lambda p, r: r["next_bar"]["model"].update(mean_bp=2.0 - eps),
        "next-bar t": lambda p, r: r["next_bar"]["model"].update(hac_t=2.0 - eps),
        "2024-2026": lambda p, r: r["default"]["2024-2026"].update(mean_bp=-eps),
        "2024-2026 missing": lambda p, r: r["default"]["2024-2026"].update(
            mean_bp=None
        ),
        "drift bp": lambda p, r: r["default"]["model"].update(drift_mean_bp=1.0 - eps),
        "drift t": lambda p, r: r["default"]["model"].update(drift_hac_t=2.0 - eps),
        "floor missing": lambda p, r: r["default"]["model"].update(hac_t=None),
    }
    for name, move in moves.items():
        for c in ("D0_sell", "D6_buy"):
            assert label(c, move) == sd.RECORD, (name, c)
    for c in ("D2_buy", "D4_sell"):
        assert (
            label(
                c,
                lambda p, r, c=c: p["deflated"][c].update(dsr=0.95 - eps, passes=False),
            )
            == sd.RECORD
        )
    # The gate itself: the shortest record whose deflated Sharpe reaches
    # 0.95 passes, one session shorter fails.
    excess = {
        "D0_buy": {"sharpe": 0.3, "skew": 0.0, "kurtosis": 3.0, "length": 0},
        "D0_sell": {"sharpe": 0.1, "skew": 0.0, "kurtosis": 3.0, "length": 500},
    }
    lengths = range(10, 20000)

    # The deflated Sharpe of D0_buy with `n` sessions.
    def at(n):
        return sd.deflated(
            {**excess, "D0_buy": {**excess["D0_buy"], "length": n}}, "D0_buy"
        )

    edge = next(n for n in lengths if at(n)["dsr"] >= 0.95)
    assert at(edge)["passes"] and at(edge)["dsr"] >= 0.95
    assert not at(edge - 1)["passes"] and at(edge - 1)["dsr"] < 0.95
    assert at(edge)["trials"] == 14 and at(edge)["candidates"] == 2
    assert at(edge)["trial_variance"] == pytest.approx(np.var([0.3, 0.1], ddof=1))
    assert 100 < edge < 20000
    assert not sd.deflated({"D0_buy": excess["D0_buy"]}, "D0_buy")[
        "passes"
    ]  # one Sharpe: no variance
    # Seeds: two changes fail a model; a rule has no seeds to fail.
    two = stage3_verdict.seed_stability(2.0, [1.0, 1.0, 1.0, -1.0, 0.0])
    assert not two["stable"]
    assert (
        label("D5_buy", lambda p, r: p["seed_stability"].update(D5_buy=two))
        == sd.RECORD
    )
    assert label("D5_buy", lambda p, r: p["seed_stability"].pop("D5_buy")) == sd.RECORD
    assert (
        label("D1_buy", lambda p, r: p["seed_stability"].update(D1_buy=two))
        == sd.REPLACES
    )
    # Real but immaterial: the floor fails and 25 bp at t 3 per re-timed order.

    # A failing floor with the given per-re-timed-order reading.
    def immaterial(bp, t):
        return lambda p, r: r["default"]["model"].update(
            mean_bp=1.0, retimed_bp=bp, retimed_t=t
        )

    assert label("D3_sell", immaterial(25.0, 3.0)) == sd.IMMATERIAL
    assert label("D3_sell", immaterial(25.0 - eps, 3.0)) == sd.RECORD
    assert label("D3_sell", immaterial(25.0, 3.0 - eps)) == sd.RECORD
    assert label("D3_sell", immaterial(None, 3.0)) == sd.RECORD
    assert label("D6_sell", immaterial(40.0, 5.0)) == sd.IMMATERIAL

    # A passing floor with a failing next-bar run and a strong per-order reading.
    def next_bar_fails(p, r):
        r["next_bar"]["model"].update(mean_bp=1.0)
        r["default"]["model"].update(retimed_bp=30.0, retimed_t=4.0)

    assert label("D3_sell", next_bar_fails) == sd.RECORD
    assert (
        label("D4_buy", lambda p, r: p["candidates"]["D4_buy"].update(priced=False))
        == sd.SKIPPED
    )
    payload = _passing_payload()
    payload["results"]["D0_buy"]["default"]["model"].update(
        mean_bp=1.0, retimed_bp=26.0, retimed_t=3.5
    )
    payload["results"]["D1_sell"]["default"]["model"].update(mean_bp=1.5)
    payload["candidates"]["D6_sell"]["priced"] = False
    payload["offsets"]["smoke"] = True
    payload["offsets"]["priced"] = 2
    record = sd.verdict(payload)
    assert record["immaterial"] == ["D0_buy"] and "D1_sell" not in record["replaces"]
    assert record["text"].startswith(
        "SMOKE RUN (2 of 20 offsets): not the registered test. REPLACES: D0_sell"
    )
    assert record["text"].endswith("RECORD: real but immaterial: D0_buy")
    lines = dict(zip(sd.CANDIDATES, record["lines"], strict=True))
    assert (
        lines["D6_sell"]
        == "D6_sell (m3_seq): not priced - no seq_sell forecast file - SKIPPED"
    )
    assert lines["D0_buy"].startswith(
        "D0_buy (always): model window +1.0 bp/session (t +2.00)"
    )
    assert lines["D0_buy"].endswith("- RECORD: real but immaterial")
    assert (
        "seeds n/a (a rule)" in lines["D2_sell"]
        and "seeds stable (1 sign changes of 5)" in lines["D4_buy"]
    )
    # A JSON round trip (NaN written as null) reads the same.
    again = sd.verdict(json.loads(json.dumps(io.clean_json(payload))))
    assert io.clean_json(again["candidates"]) == io.clean_json(record["candidates"])
    assert again["text"] == record["text"] and again["lines"] == record["lines"]


# The VIX from the export: exp of the date-level ln VIX at each session,
# NaN where the export has no value; a close of exactly 25 reads as stress
# through float32; rows of one date that disagree, an unsorted export and a
# missing column are refused. Earnings count over t-2..t.
def test_vix_from_export_and_recent_earnings():
    panel_dates = np.datetime64("2023-05-01", "D") + np.arange(6)
    rows = [(1, 25.0), (1, 25.0), (2, 24.99), (4, np.nan), (5, 31.0)]
    x = np.array(
        [[np.log(v) if v == v else np.nan, 0.0] for _, v in rows], dtype=np.float32
    )
    data = io.Stage3Data(
        kind=io.S1,
        dates=panel_dates[[r[0] for r in rows]],
        tickers=np.array(["A", "B", "A", "A", "A"]),
        slot=np.zeros(5, dtype=np.int8),
        x=x,
        feature_names=("d_vix_level", "d_other"),
        y=np.zeros(5, dtype=np.float32),
    )
    vix = sd.vix_from_export(data, panel_dates)
    assert np.isnan(vix[[0, 3, 4]]).all()
    assert (
        vix[1] >= sd.VIX_STRESS
        and vix[1] == pytest.approx(25.0)
        and vix[2] < sd.VIX_STRESS
    )
    assert vix[5] == pytest.approx(31.0, rel=1e-6)
    bad = x.copy()
    bad[1, 0] = np.float32(np.log(26.0))
    with pytest.raises(ValueError, match="date-level"):
        sd.vix_from_export(io.Stage3Data(**{**data.__dict__, "x": bad}), panel_dates)
    with pytest.raises(ValueError, match="sorted"):
        sd.vix_from_export(
            io.Stage3Data(**{**data.__dict__, "dates": data.dates[::-1]}), panel_dates
        )
    with pytest.raises(ValueError, match="no 'd_vix_level'"):
        sd.vix_from_export(
            io.Stage3Data(**{**data.__dict__, "feature_names": ("d_a", "d_b")}),
            panel_dates,
        )
    earnings = np.zeros((8, 2), dtype=bool)
    earnings[2, 0] = True
    recent = sd.recent_earnings(earnings)
    assert recent[:, 0].tolist() == [
        False,
        False,
        True,
        True,
        True,
        False,
        False,
        False,
    ]
    assert not recent[:, 1].any()


# Placing a forecast file: rows at (t, ticker), off-panel rows counted, the
# first finite date; refused - another family, another side, a slot, a
# seed count, rows other than the export's, a duplicate, nothing finite.
def test_place_forecast_checks_and_placement():
    dates = np.datetime64("2023-05-01", "D") + np.arange(5)
    keys_d = np.array(
        ["2023-05-02", "2023-05-02", "2023-05-03", "2023-05-09"], dtype="datetime64[D]"
    )
    keys_t = np.array(["A", "B", "Z", "A"])
    yhat = np.array([np.nan, 1.5, 2.0, 3.0], dtype=np.float32)
    forecast = io.Stage3Forecast(
        kind=io.S1,
        family=io.SEQ,
        dates=keys_d,
        tickers=keys_t,
        slot=np.zeros(4, dtype=np.int8),
        yhat=yhat,
        yhat_seeds=np.stack([yhat + k for k in range(5)], axis=1),
        yhat_configs=None,
        fold=np.zeros(4, dtype=np.int32),
        meta={"side": "sell"},
    )
    placed = sd.place_forecast(
        forecast, dates, ("A", "B"), io.SEQ, "sell", (keys_d, keys_t), {"file": "f"}
    )
    assert (
        placed.grid[1, 1] == 1.5
        and np.isnan(placed.grid[1, 0])
        and np.isfinite(placed.grid).sum() == 1
    )
    assert placed.seeds[1, 1].tolist() == [1.5, 2.5, 3.5, 4.5, 5.5]
    assert placed.first == date(2023, 5, 2)
    assert (
        placed.identity["placed"],
        placed.identity["off_panel"],
        placed.identity["file"],
    ) == (2, 2, "f")
    for change, message in (
        ({"family": io.LGBM}, "family"),
        ({"meta": {"side": "buy"}}, "side"),
        ({"slot": np.array([0, 3, 0, 0], dtype=np.int8)}, "slot 0"),
        ({"yhat_seeds": np.zeros((4, 3), dtype=np.float32)}, "5 seeds"),
        ({"yhat": np.full(4, np.nan, dtype=np.float32)}, "no finite"),
    ):
        with pytest.raises(ValueError, match=message):
            sd.place_forecast(
                io.Stage3Forecast(**{**forecast.__dict__, **change}),
                dates,
                ("A", "B"),
                io.SEQ,
                "sell",
            )
    with pytest.raises(ValueError, match="export's rows"):
        sd.place_forecast(
            forecast, dates, ("A", "B"), io.SEQ, "sell", (keys_d, keys_t[::-1])
        )
    twice = io.Stage3Forecast(
        **{
            **forecast.__dict__,
            "tickers": np.array(["A", "A", "Z", "A"]),
            "dates": np.array(
                ["2023-05-02"] * 2 + ["2023-05-03", "2023-05-09"], dtype="datetime64[D]"
            ),
        }
    )
    with pytest.raises(ValueError, match="more than once"):
        sd.place_forecast(twice, dates, ("A", "B"), io.SEQ, "sell")


# Population skill: the pooled Spearman and the decision's hit rate per
# window and grade.
def test_population_skill():
    row_dates = np.array(["2023-06-01"] * 6 + ["2024-02-01"] * 4, dtype="datetime64[D]")
    yhat = np.array([1.0, 2.0, 3.0, -1.0, -2.0, 0.5, 1.0, -1.0, 2.0, np.nan])
    label = np.array([10.0, 20.0, 30.0, -5.0, -10.0, -1.0, 5.0, 3.0, -2.0, 1.0])
    grades = np.array([3, 3, 3, 2, 2, 2, 3, 2, 3, 3])
    skill = sd.population_skill(
        yhat, label, grades, row_dates, sd.windows(date(2023, 1, 2))
    )
    model = skill["model"]
    assert model["all"]["rows"] == 6 and model["all"]["spearman"] == pytest.approx(
        io.spearman(yhat[:6], label[:6])
    )
    assert (
        model["A+"]["spearman"] == pytest.approx(1.0) and model["A+"]["hit_rate"] == 1.0
    )
    assert (
        model["A"]["wait_share"] == pytest.approx(1 / 3)
        and model["A"]["hit_rate"] == 0.0
    )
    assert model["all"]["hit_rate"] == pytest.approx(3 / 4) and model["all"][
        "base_rate"
    ] == pytest.approx(0.5)
    later = skill["2024-2026"]
    assert (
        later["all"]["rows"] == 3
        and later["A+"]["rows"] == 2
        and math.isnan(later["B"]["hit_rate"])
    )


# A cube for one name of a panel: 26 bars wandering around the session's
# close and ending on it, the official close at the close.
def _session_cube(ticker, dates, closes, rng) -> SessionCube:
    n = len(dates)
    path = closes[:, None] * np.exp(
        rng.normal(0, 0.004, size=(n, SLOTS)).cumsum(axis=1)
    )
    path[:, -1] = closes
    opens = np.empty_like(path)
    opens[:, 0] = np.r_[closes[0], closes[:-1]]
    opens[:, 1:] = path[:, :-1]
    return SessionCube(
        ticker=ticker,
        dates=np.asarray(dates),
        open=opens,
        high=np.maximum(opens, path),
        low=np.minimum(opens, path),
        close=path,
        volume=np.ones((n, SLOTS)),
        prior_close=np.r_[np.nan, closes[:-1]],
        excluded={},
        auction_open=closes.copy(),
        auction_volume=np.ones(n),
    )


# The command end to end on stub loaders: the synthetic book of the orders
# tests, cubes for its names, a T-S1 export with the VIX, two model files
# and the labels, two of twenty offsets. The payload names the plan, the
# revision and the inputs' sha256, starts the model window at the first
# forecast date, reads an EDGAR release into D1, prices the files' models
# and skips the others, adds the population skill, and prints a verdict
# line per candidate; the submitted basis and --json work; bad inputs are
# refused before the desk runs.
def test_command_end_to_end(tmp_path):
    from backend.cli import market_stage4_decisions as cli

    report = _report()
    panel = report.panel
    rng = np.random.default_rng(11)
    cubes = {
        t: _session_cube(t, panel.dates, panel.close[:, j], rng)
        for j, t in enumerate(panel.tickers)
        if t != panel.benchmark
    }
    names = [t for t in panel.tickers if t != panel.benchmark]
    keys = [(d, t) for d in panel.dates[30:] for t in sorted(names)]
    row_dates = np.array([k[0] for k in keys], dtype="datetime64[D]")
    row_tickers = np.array([k[1] for k in keys])
    vix_by_row = np.where(row_dates < np.datetime64("2023-06-01"), 18.0, 27.0)
    data = io.Stage3Data(
        kind=io.S1,
        dates=row_dates,
        tickers=row_tickers,
        slot=np.zeros(len(keys), dtype=np.int8),
        x=np.column_stack([np.log(vix_by_row), np.zeros(len(keys))]).astype(np.float32),
        feature_names=("d_vix_level", "d_zero"),
        y=np.zeros(len(keys), dtype=np.float32),
        extra={
            "r": np.zeros(len(keys), dtype=np.float32),
            "grade": np.full(len(keys), 3, dtype=np.int8),
        },
    )
    s1 = io.save_data(tmp_path / "s1.npz", data)
    paths = {}
    for side, scale in (("buy", 1.0), ("sell", -1.0)):
        yhat = (scale * rng.normal(size=len(keys))).astype(np.float32)
        yhat[:40] = np.nan
        forecast = io.Stage3Forecast(
            kind=io.S1,
            family=io.LGBM,
            dates=row_dates,
            tickers=row_tickers,
            slot=np.zeros(len(keys), dtype=np.int8),
            yhat=yhat,
            yhat_seeds=np.stack([yhat] * 5, axis=1),
            yhat_configs=None,
            fold=np.zeros(len(keys), dtype=np.int32),
            meta={"side": side},
        )
        paths[side] = io.save_forecast(tmp_path / f"lgbm_{side}.npz", forecast)
    labels = tmp_path / "labels.npz"
    with labels.open("wb") as handle:
        np.savez(
            handle,
            dates=row_dates,
            tickers=row_tickers,
            g_buy=rng.normal(size=len(keys)).astype(np.float32),
            g_sell=rng.normal(size=len(keys)).astype(np.float32),
            meta=np.asarray(json.dumps({"plan": sd.PLAN})),
        )
    history = _history(tmp_path)
    release = datetime(
        2023, 3, 1, 21, 30, tzinfo=UTC
    )  # after the close: the reaction session is 2023-03-02
    records = {"AAA": SimpleNamespace(events=[SimpleNamespace(accepted=release)])}
    calls = []

    # The stub loader: the synthetic report, its cubes and one EDGAR record.
    def loader(store, workers, log):
        calls.append(str(store.root))
        return report, cubes, records

    out_path = tmp_path / "out" / "decisions.json"
    common = [
        "--root",
        str(tmp_path),
        "--s1",
        str(s1),
        "--membership",
        str(history),
        "--forecast",
        f"lgbm_buy={paths['buy']}",
        "--forecast",
        f"lgbm_sell={paths['sell']}",
        "--offsets",
        "20",
        "--max-offsets",
        "2",
    ]
    text = textio.StringIO()
    args = cli.build_parser().parse_args(
        [*common, "--labels", str(labels), "--out", str(out_path)]
    )
    assert cli.run(args, out=text, loader=loader) == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["plan"] == sd.PLAN and payload["study"] == sd.STUDY
    assert payload["offsets"] == {
        "registered": 20,
        "priced": 2,
        "median": 1,
        "smoke": True,
        "starts": [0, 1],
    }
    first = str(row_dates[40])
    assert payload["model_start"]["date"] == first and payload["windows"]["model"] == [
        first,
        "2024-01-01",
    ]
    inputs = payload["run"]["inputs"]
    assert inputs["s1"]["sha256"] == hashlib.sha256(s1.read_bytes()).hexdigest()
    assert (
        inputs["forecasts"]["lgbm_buy"]["sha256"]
        == hashlib.sha256(paths["buy"].read_bytes()).hexdigest()
    )
    assert (
        inputs["membership"]["sha256"]
        == hashlib.sha256(history.read_bytes()).hexdigest()
    )
    assert (
        payload["labels"]["sha256"] == hashlib.sha256(labels.read_bytes()).hexdigest()
    )
    revision = payload["run"]["revision"]
    assert revision is None or (
        set(revision) == {"commit", "dirty"} and len(revision["commit"]) == 40
    )
    assert payload["run"]["edgar"] == {
        "names": 1,
        "names_without_record": ["BBB", "CCC", "DDD", "EEE", "FFF"],
        "earnings_sessions": 1,
    }
    assert payload["run"]["cubes"]["names_with_cube"] == 6
    assert payload["conditions"]["model"]["vix_stress"] > 0
    assert payload["forecasts"]["lgbm_buy"]["placed"] == len(keys)
    assert set(payload["population_skill"]) == {"lgbm_buy", "lgbm_sell"}
    assert payload["population_skill"]["lgbm_buy"]["model"]["A+"]["rows"] > 0
    labels_of = {c: v["label"] for c, v in payload["verdict"]["candidates"].items()}
    assert {c for c, v in labels_of.items() if v == sd.SKIPPED} == {
        "D5_buy",
        "D5_sell",
        "D6_buy",
        "D6_sell",
    }
    assert payload["results"]["D4_buy"]["default"]["model"]["orders"] > 0
    assert (
        payload["control"]["basis"] == so.EXECUTED
        and payload["run"]["cost_bps"] == so.COST_BPS
    )
    printed = text.getvalue()
    assert "SMOKE RUN (2 of 20 offsets)" in printed and printed.count("\n  D") == 14
    assert f"wrote {out_path}" in printed and calls == [str(tmp_path)]
    # The submitted basis and --json.
    text = textio.StringIO()
    args = cli.build_parser().parse_args(
        [*common, "--basis", "submitted", "--json", "--out", str(tmp_path / "s.json")]
    )
    assert cli.run(args, out=text, loader=loader) == 0
    body = text.getvalue()
    printed_payload = json.loads(body[body.index("{") : body.rindex("}") + 1])
    assert printed_payload["control"]["basis"] == so.SUBMITTED
    assert (
        printed_payload["orders"]["per_offset"][1]["orders"]
        >= payload["orders"]["per_offset"][1]["orders"]
    )
    # Refusals, all before the desk runs.
    wrong_family = io.save_forecast(
        tmp_path / "wrong.npz",
        io.Stage3Forecast(
            **{**io.load_forecast(paths["buy"]).__dict__, "family": io.SEQ}
        ),
    )
    short = io.load_forecast(paths["buy"])
    short_path = io.save_forecast(
        tmp_path / "short.npz",
        io.Stage3Forecast(
            **{
                **short.__dict__,
                **{
                    k: getattr(short, k)[1:]
                    for k in ("dates", "tickers", "slot", "yhat", "yhat_seeds", "fold")
                },
            }
        ),
    )
    ti = io.save_data(
        tmp_path / "ti.npz", io.Stage3Data(**{**data.__dict__, "kind": io.TI})
    )
    shuffled = tmp_path / "shuffled_labels.npz"
    with shuffled.open("wb") as handle:
        np.savez(
            handle,
            dates=row_dates[::-1],
            tickers=row_tickers[::-1],
            g_buy=np.zeros(len(keys), dtype=np.float32),
            g_sell=np.zeros(len(keys), dtype=np.float32),
            meta=np.asarray(json.dumps({})),
        )
    before = len(calls)
    base = [
        "--root",
        str(tmp_path),
        "--membership",
        str(history),
        "--out",
        str(tmp_path / "x.json"),
    ]
    for extra, code, message in (
        (
            ["--s1", str(s1), "--forecast", f"xgb_buy={paths['buy']}"],
            2,
            "expected <family>_<side>",
        ),
        (
            [
                "--s1",
                str(s1),
                "--forecast",
                f"lgbm_buy={paths['buy']}",
                "--forecast",
                f"lgbm_buy={paths['buy']}",
            ],
            2,
            "twice",
        ),
        (["--s1", str(tmp_path / "none.npz")], 1, "file not found"),
        (["--s1", str(s1), "--forecast", f"lgbm_buy={wrong_family}"], 2, "family"),
        (["--s1", str(s1), "--forecast", f"lgbm_buy={short_path}"], 2, "export's rows"),
        (["--s1", str(ti)], 2, "T-S1"),
        (["--s1", str(s1), "--max-offsets", "0"], 2, "at least 1"),
        (["--s1", str(s1), "--labels", str(shuffled)], 2, "not the export's rows"),
    ):
        text = textio.StringIO()
        assert (
            cli.run(
                cli.build_parser().parse_args([*base, *extra]), out=text, loader=loader
            )
            == code
        ), extra
        assert message in text.getvalue(), (extra, text.getvalue())
    assert len(calls) == before
