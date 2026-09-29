"""Stage 4's fills and timing target on hand-made cubes and panels.

What has to hold (docs/research/stage4-plan-2026-09-29.md):

- The indicators read rows through t only:
  - sigma is the ddof-1 sd of the last 20 log returns;
  - EMA10 is `technical.ema`;
  - the bands are SMA20 ± 2 sd (ddof 0);
  - the squeeze is the bandwidth at or below the 10% quantile of its last
    126 values.
- The control is `fill_timing`'s dip_or_close in session t+1, on the
  adjusted basis.
- D0 rests at C_t·exp(∓σ) through t+1..t+5. It fills at the first bar close
  at or past the level (all 26 bars), else at the official close of t+5.
  With `next_bar`, a bar fill moves to the next bar's open.
- A split inside the window does not fake a fill: every price is compared
  on the adjusted basis.
- D2 and D3 act only when their condition holds at t, and fill at the first
  session close past their trigger or at t+5. Inactive orders fill as the
  control.
- A missing cube session in t+1..t+5 leaves D0 (and an active D2/D3)
  unpriced, while the control needs only t+1.
- The labels are 1e4·ln(control/level) for buys and 1e4·ln(level/control)
  for sells, per T-S1 row. A name without a cube is NaN and counted.
- The command writes the labels in the export's row order with a JSON
  summary, and `load` reads them back.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import fill_timing, technical
from backend.market import stage3_io as io
from backend.market import stage4_labels as lab
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

SLOTS = FULL_SESSION_SLOTS


# Consecutive calendar dates.
def _dates(n, start="2024-01-01"):
    return np.datetime64(start, "D") + np.arange(n)


# A cube whose every bar is flat at the session's price (open = close =
# high = low = price), with an auction print at the price; `paths` can
# replace a session's 26 bar closes.
def _cube(dates, prices, paths=None, drop=()):
    keep = [i for i in range(len(dates)) if i not in set(drop)]
    n = len(keep)
    closes = np.repeat(np.asarray(prices, dtype=float)[keep][:, None], SLOTS, axis=1)
    for i, path in (paths or {}).items():
        if i in keep:
            closes[keep.index(i)] = np.asarray(path, dtype=float)
    opens = closes.copy()
    auction = closes[:, -1].copy()
    return SessionCube(
        ticker="T", dates=np.asarray(dates)[keep], open=opens, high=closes.copy(), low=closes.copy(),
        close=closes, volume=np.ones((n, SLOTS)), prior_close=np.r_[np.nan, auction[:-1]], excluded={},
        auction_open=auction, auction_volume=np.ones(n),
    )


# A one-name panel view: flat daily bars at the given closes (raw), with
# an optional adjustment factor per session.
def _series(dates, closes, factor=None, high=None, low=None):
    closes = np.asarray(closes, dtype=float)
    factor = np.ones(len(closes)) if factor is None else np.asarray(factor, dtype=float)
    high = closes if high is None else np.asarray(high, dtype=float)
    low = closes if low is None else np.asarray(low, dtype=float)
    return lab.name_series(dates, closes, closes * factor, high, low)


# A price path with alternating +-1% returns (sigma well defined), T long.
def _zigzag(T, base=100.0):
    r = np.where(np.arange(T) % 2 == 0, 0.01, -0.01)
    return base * np.exp(np.cumsum(r))


# The indicators against their definitions.
def test_name_series_indicators():
    T = 160
    dates = _dates(T)
    closes = _zigzag(T) * np.linspace(1.0, 1.3, T)
    s = _series(dates, closes)
    lr = np.diff(np.log(closes))
    assert s.sigma[20] == pytest.approx(np.std(lr[:20], ddof=1))
    assert math.isnan(s.sigma[19])
    np.testing.assert_allclose(s.ema10, technical.ema(closes[:, None], 10)[:, 0], equal_nan=True)
    window = closes[40:60]
    assert s.upper[59] == pytest.approx(window.mean() + 2 * window.std(ddof=0))
    assert s.lower[59] == pytest.approx(window.mean() - 2 * window.std(ddof=0))
    # A squeeze: bands that were wide go flat for a while.
    wide = _zigzag(200) * np.exp(np.where(np.arange(200) % 2 == 0, 0.03, -0.03).cumsum())
    flat = wide.copy()
    flat[170:] = flat[169]
    sq = _series(_dates(200), flat).squeeze
    assert not sq[:125].any() and sq[195]


# The control is fill_timing's dip_or_close in session t+1.
def test_control_is_the_boards_dip_or_close():
    T = 30
    dates = _dates(T)
    closes = np.full(T, 100.0)
    path = np.full(SLOTS, 100.0)
    path[4] = 98.9  # below open * 0.99 at bar 4
    cube = _cube(dates, closes, paths={11: path})
    fills = lab.name_fills(_series(dates, closes), cube)
    ctrl = fills[(lab.CONTROL, "buy")]
    raw, hit = fill_timing._dip_or_close_fill(cube, "buy")
    assert ctrl.price[10] == pytest.approx(raw[11]) and ctrl.price[10] == pytest.approx(98.9)
    assert ctrl.reached[10] and ctrl.days[10] == 1
    assert ctrl.price[9] == pytest.approx(100.0) and not ctrl.reached[9]
    assert math.isnan(ctrl.price[T - 1])


# D0: the first bar close past the level within five sessions, else the
# official close of t+5; next_bar moves a bar fill to the next bar's open.
def test_level_fills_at_the_first_touch_or_the_fifth_close():
    T = 60
    dates = _dates(T)
    closes = _zigzag(T)
    t = 40
    sigma = lab.name_series(dates, closes, closes, closes, closes).sigma[t]
    level = closes[t] * math.exp(-sigma)
    paths = {}
    for j in range(1, 6):
        paths[t + j] = np.full(SLOTS, closes[t] * 1.001)
    touch = np.full(SLOTS, closes[t] * 1.001)
    touch[7] = level * 0.999
    touch[8] = level * 0.995
    paths[t + 3] = touch
    cube = _cube(dates, closes, paths=paths)
    series = _series(dates, closes)
    fills = lab.name_fills(series, cube)
    lv = fills[(lab.LEVEL, "buy")]
    assert lv.price[t] == pytest.approx(level * 0.999) and lv.days[t] == 3 and lv.reached[t]
    nb = lab.name_fills(series, cube, next_bar=True)[(lab.LEVEL, "buy")]
    assert nb.price[t] == pytest.approx(touch[8])  # the next bar's open (= its flat close)
    # No touch: the fifth session's official close.
    cube2 = _cube(dates, closes, paths={t + j: np.full(SLOTS, closes[t] * 1.002) for j in range(1, 6)})
    lv2 = lab.name_fills(series, cube2)[(lab.LEVEL, "buy")]
    assert lv2.price[t] == pytest.approx(closes[t] * 1.002) and lv2.days[t] == 5 and not lv2.reached[t]
    # Sells mirror above the close.
    up = np.full(SLOTS, closes[t])
    up[2] = closes[t] * math.exp(sigma) * 1.0005
    cube3 = _cube(dates, closes, paths={t + 2: up})
    sl = lab.name_fills(series, cube3)[(lab.LEVEL, "sell")]
    assert sl.price[t] == pytest.approx(up[2]) and sl.days[t] == 2


# A 2-for-1 split between t+1 and t+2: raw prices halve, the panel factor
# halves the other way, and nothing fills on the split itself.
def test_split_inside_the_window_does_not_fake_a_fill():
    T = 60
    dates = _dates(T)
    closes = _zigzag(T)
    t = 40
    raw = closes.copy()
    raw[t + 2 :] = raw[t + 2 :] / 2.0
    factor = np.ones(T)
    factor[t + 2 :] = 2.0
    flat = {t + j: np.full(SLOTS, raw[t + 1] if j == 1 else closes[t] / 2.0) for j in range(1, 6)}
    flat[t + 1] = np.full(SLOTS, closes[t])
    cube = _cube(dates, raw, paths=flat)
    series = lab.name_series(dates, raw, raw * factor, raw, raw)
    lv = lab.name_fills(series, cube)[(lab.LEVEL, "buy")]
    assert not lv.reached[t] and lv.days[t] == 5
    assert lv.price[t] == pytest.approx(closes[t])  # the fifth close, back on the adjusted basis


# D2: a buy of a name under its EMA10 fills at the first close above the
# prior session's high; a name above its EMA10 fills as the control.
def test_turn_rule_waits_for_a_close_above_the_prior_high():
    T = 60
    dates = _dates(T)
    closes = np.linspace(120.0, 100.0, T)  # a steady decline: close < EMA10
    t = 40
    closes = closes.copy()
    highs = closes * 1.01
    after = closes.copy()
    after[t + 1] = closes[t] * 0.99
    after[t + 2] = closes[t] * 0.985
    after[t + 3] = highs[t + 2] * 1.02  # closes above t+2's high
    for j in (4, 5):
        after[t + j] = after[t + 3]
    highs = after * 1.01
    highs[t + 3] = after[t + 3] * 1.001
    cube = _cube(dates, after)
    series = lab.name_series(dates, after, after, highs, after * 0.99)
    assert series.close[t] < series.ema10[t]
    turn = lab.name_fills(series, cube)[(lab.TURN, "buy")]
    assert turn.active[t] and turn.reached[t] and turn.days[t] == 3
    assert turn.price[t] == pytest.approx(after[t + 3])
    # A rising name is inactive for buys: it fills as the control.
    rising = np.linspace(100.0, 130.0, T)
    s2 = lab.name_series(dates, rising, rising, rising * 1.01, rising * 0.99)
    f2 = lab.name_fills(s2, _cube(dates, rising))
    assert not f2[(lab.TURN, "buy")].active[t]
    assert f2[(lab.TURN, "buy")].price[t] == pytest.approx(f2[(lab.CONTROL, "buy")].price[t])
    # And active for sells, which wait for a close below the prior low.
    assert f2[(lab.TURN, "sell")].active[t]


# D3: a squeezed name's buy fills at the first close above the upper band;
# an unsqueezed one fills as the control.
def test_squeeze_rule_waits_for_the_breakout():
    T = 200
    dates = _dates(T)
    wide = 100 * np.exp(np.where(np.arange(T) % 2 == 0, 0.03, -0.03).cumsum())
    path = wide.copy()
    path[150:] = path[149]
    t = 180
    path[t + 2] = path[t] * 1.05  # a breakout above the flat band
    path[t + 3 :] = path[t + 2]
    cube = _cube(dates, path)
    series = lab.name_series(dates, path, path, path, path)
    assert series.squeeze[t]
    sq = lab.name_fills(series, cube)[(lab.SQUEEZE, "buy")]
    assert sq.active[t] and sq.reached[t] and sq.days[t] == 2 and sq.price[t] == pytest.approx(path[t + 2])
    assert not series.squeeze[100]
    f = lab.name_fills(series, cube)
    assert f[(lab.SQUEEZE, "buy")].price[100] == pytest.approx(f[(lab.CONTROL, "buy")].price[100])


# A missing cube session in the window leaves D0 unpriced; the control
# needs only t+1.
def test_missing_session_leaves_the_level_unpriced():
    T = 60
    dates = _dates(T)
    closes = _zigzag(T)
    t = 40
    cube = _cube(dates, closes, drop=(t + 3,))
    fills = lab.name_fills(_series(dates, closes), cube)
    assert math.isnan(fills[(lab.LEVEL, "buy")].price[t])
    assert np.isfinite(fills[(lab.CONTROL, "buy")].price[t])
    assert np.isfinite(fills[(lab.LEVEL, "buy")].price[t - 10])
    empty = _cube(dates[:0], closes[:0])
    assert np.isnan(lab.name_fills(_series(dates, closes), empty)[(lab.LEVEL, "sell")].price).all()


# The gain signs: a buy gains paying less, a sell receiving more.
def test_gain_signs():
    assert lab.gain(100.0, 98.0, "buy") == pytest.approx(1e4 * math.log(100 / 98))
    assert lab.gain(100.0, 102.0, "sell") == pytest.approx(1e4 * math.log(102 / 100))
    assert lab.gain(100.0, 102.0, "buy") < 0 and lab.gain(100.0, 98.0, "sell") < 0


# The labels of a T-S1 dataset's rows, in its order; a name without a cube
# is NaN and counted.
def test_label_rows_follow_the_dataset():
    T = 60
    dates = _dates(T)
    closes = _zigzag(T)
    panel = SimpleNamespace(
        dates=dates, tickers=["AAA", "BBB"], close=np.column_stack([closes, closes]),
        adj_close=np.column_stack([closes, closes]), high=np.column_stack([closes, closes]),
        low=np.column_stack([closes, closes]),
    )
    cube = _cube(dates, closes)
    rows_t = [30, 31, 40]
    ds_dates = np.repeat(dates[rows_t], 2)
    tickers = np.tile(["AAA", "BBB"], 3)
    data = io.Stage3Data(
        kind=io.S1, dates=ds_dates, tickers=tickers, slot=np.zeros(6, dtype=np.int8),
        x=np.zeros((6, 1), dtype=np.float32), feature_names=("d_zero",), y=np.zeros(6, dtype=np.float32),
        extra={"r": np.zeros(6, dtype=np.float32), "grade": np.zeros(6, dtype=np.int8)},
    )
    labels = lab.label_rows(data, panel, {"AAA": cube})
    fills = lab.name_fills(lab.name_series(dates, closes, closes, closes, closes), cube)
    for k, t in enumerate(rows_t):
        expected_buy = lab.gain(fills[(lab.CONTROL, "buy")].price[t], fills[(lab.LEVEL, "buy")].price[t], "buy")
        expected_sell = lab.gain(fills[(lab.CONTROL, "sell")].price[t], fills[(lab.LEVEL, "sell")].price[t], "sell")
        assert labels.g_buy[2 * k] == pytest.approx(expected_buy)
        assert labels.g_sell[2 * k] == pytest.approx(expected_sell)
        assert math.isnan(labels.g_buy[2 * k + 1])
    assert labels.meta["counts"]["no_cube"] == 3
    import dataclasses

    with pytest.raises(ValueError, match="T-S1"):
        lab.label_rows(dataclasses.replace(data, kind=io.TI), panel, {"AAA": cube})


# The command end to end with a stand-in loader: the labels file, its
# summary, and the reader.
def test_command_writes_and_reads_the_labels(tmp_path):
    import io as textio
    import json

    from backend.cli import market_stage4_labels as cli

    T = 60
    dates = _dates(T)
    closes = _zigzag(T)
    panel = SimpleNamespace(
        dates=dates, tickers=["AAA"], close=closes[:, None], adj_close=closes[:, None],
        high=closes[:, None], low=closes[:, None],
    )
    cube = _cube(dates, closes)
    data = io.Stage3Data(
        kind=io.S1, dates=dates[25:45], tickers=np.array(["AAA"] * 20), slot=np.zeros(20, dtype=np.int8),
        x=np.zeros((20, 1), dtype=np.float32), feature_names=("d_zero",), y=np.zeros(20, dtype=np.float32),
        extra={"r": np.zeros(20, dtype=np.float32), "grade": np.zeros(20, dtype=np.int8)},
    )
    s1 = io.save_data(tmp_path / "s1.npz", data)
    out = tmp_path / "lab" / "labels.npz"
    args = cli.build_parser().parse_args(["--s1", str(s1), "--out", str(out)])
    text = textio.StringIO()
    assert cli.run(args, out=text, loader=lambda store, tickers, workers, log: (panel, {"AAA": cube})) == 0
    d, t, gb, gs, meta = cli.load(out)
    assert len(d) == 20 and (t == "AAA").all()
    direct = lab.label_rows(data, panel, {"AAA": cube})
    np.testing.assert_allclose(gb, direct.g_buy.astype(np.float32), equal_nan=True)
    np.testing.assert_allclose(gs, direct.g_sell.astype(np.float32), equal_nan=True)
    summary = json.loads(out.with_suffix(".json").read_text())
    assert summary["s1_sha256"] == meta["s1_sha256"] and "positive_share" in summary
    assert "labels:" in text.getvalue()
