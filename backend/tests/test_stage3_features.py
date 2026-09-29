"""Stage 3's inputs: formulas, the moment each is known, and the export's rows."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from backend.market import stage3_export as export
from backend.market import stage3_features as features
from backend.market import stage3_intraday as intraday
from backend.market import stage3_io as io
from backend.market.panel import Panel
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

BOOK = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
ETFS = ("SMH", "IGV", "QQQ")
SIDES = {"AAA": "ai", "BBB": "ai", "CCC": "ai", "DDD": "software", "EEE": "software", "FFF": "software"}


def _business_days(start: str, count: int) -> np.ndarray:
    first = np.busday_offset(np.datetime64(start, "D"), 0, roll="forward")
    return np.busday_offset(first, np.arange(count)).astype("datetime64[D]")


def _world(sessions: int = 420, seed: int = 7, cube_start: int = 90):
    """A panel of six names plus SPY, and SIP cubes for the names and four ETFs."""
    rng = np.random.default_rng(seed)
    dates = _business_days("2015-01-02", sessions)
    tickers = (*BOOK, "SPY")
    n = len(tickers)
    close = np.empty((sessions, n))
    opens = np.empty((sessions, n))
    high = np.empty((sessions, n))
    low = np.empty((sessions, n))
    volume = rng.uniform(1e6, 3e6, size=(sessions, n))
    level = rng.uniform(20, 400, size=n)
    cubes: dict[str, SessionCube] = {}
    bars: dict[str, dict[str, np.ndarray]] = {}
    for j, ticker in enumerate((*tickers, *ETFS)):
        prior = level[j] if j < n else rng.uniform(50, 300)
        o = np.empty((sessions, FULL_SESSION_SLOTS))
        h = np.empty_like(o)
        lo_ = np.empty_like(o)
        c = np.empty_like(o)
        v = rng.uniform(1e4, 1e5, size=o.shape)
        priors = np.empty(sessions)
        for s in range(sessions):
            priors[s] = prior
            start = prior * math.exp(rng.normal(0, 0.01))
            path = start * np.exp(np.cumsum(rng.normal(0, 0.004, FULL_SESSION_SLOTS)))
            o[s] = np.concatenate([[start], path[:-1]])
            c[s] = path
            h[s] = np.maximum(o[s], c[s]) * (1 + rng.uniform(0, 0.003, FULL_SESSION_SLOTS))
            lo_[s] = np.minimum(o[s], c[s]) * (1 - rng.uniform(0, 0.003, FULL_SESSION_SLOTS))
            prior = c[s, -1]
        bars[ticker] = {"open": o, "high": h, "low": lo_, "close": c, "volume": v, "prior": priors}
        if j < n:
            close[:, j] = c[:, -1]
            opens[:, j] = o[:, 0]
            high[:, j] = h.max(axis=1)
            low[:, j] = lo_.min(axis=1)
        keep = np.arange(sessions) >= cube_start
        cubes[ticker] = SessionCube(
            ticker=ticker,
            dates=dates[keep],
            open=o[keep],
            high=h[keep],
            low=lo_[keep],
            close=c[keep],
            volume=v[keep],
            prior_close=priors[keep],
            excluded={},
            auction_open=c[keep, -1].copy(),
            auction_volume=np.full(int(keep.sum()), 1e5),
        )
    panel = Panel(
        dates=dates,
        tickers=tickers,
        open=opens,
        high=high,
        low=low,
        close=close,
        adj_close=close.copy(),
        volume=volume,
        themes={t: ("semis" if SIDES.get(t) == "ai" else "software",) for t in BOOK},
        benchmark="SPY",
    )
    grades = rng.integers(-1, 4, size=(sessions, n))
    grades[:, -1] = -1
    inputs = export.Inputs(
        panel=panel,
        cubes=cubes,
        grades=grades,
        stances={"fund": rng.normal(size=(sessions, n)), "tech": rng.normal(size=(sessions, n))},
        regime=rng.normal(size=(sessions, 6)),
        sides=SIDES,
        member=np.ones((sessions, n), dtype=bool),
        earnings_day=rng.random((sessions, n)) < 0.02,
        shares=np.full((sessions, n), 5e7),
        vol_forecast=rng.normal(size=(sessions, n)),
        dd_forecast=rng.normal(size=(sessions, n)),
    )
    return inputs


def _tamper_after(inputs: export.Inputs, t0: int, seed: int = 99) -> export.Inputs:
    """Change every input dated after row t0 (panel rows, cube sessions, desk state)."""
    rng = np.random.default_rng(seed)
    panel = inputs.panel
    dates = np.asarray(panel.dates)
    cut = dates[t0]

    def scramble(grid):
        out = np.array(grid, dtype=float, copy=True)
        out[t0 + 1 :] = out[t0 + 1 :] * rng.uniform(0.5, 1.5, size=out[t0 + 1 :].shape)
        return out

    close = scramble(panel.close)
    new_panel = replace(
        panel,
        open=scramble(panel.open),
        high=np.maximum(scramble(panel.high), close),
        low=np.minimum(scramble(panel.low), close),
        close=close,
        adj_close=close.copy(),
        volume=scramble(panel.volume),
    )
    cubes = {}
    for ticker, cube in inputs.cubes.items():
        later = cube.dates > cut
        fields = {}
        for name in ("open", "high", "low", "close", "volume"):
            values = np.array(getattr(cube, name), copy=True)
            values[later] = values[later] * rng.uniform(0.5, 1.5, size=values[later].shape)
            fields[name] = values
        auction = np.array(cube.auction_open, copy=True)
        auction[later] *= 1.3
        prior = np.array(cube.prior_close, copy=True)
        prior[later] *= 0.7
        cubes[ticker] = replace(cube, **fields, auction_open=auction, prior_close=prior)
    grades = np.array(inputs.grades, copy=True)
    grades[t0 + 1 :] = rng.integers(-1, 4, size=grades[t0 + 1 :].shape)
    regime = np.array(inputs.regime, copy=True)
    regime[t0 + 1 :] = rng.normal(size=regime[t0 + 1 :].shape)
    stances = {k: scramble(v) for k, v in inputs.stances.items()}
    earnings = np.array(inputs.earnings_day, copy=True)
    earnings[t0 + 1 :] = rng.random(earnings[t0 + 1 :].shape) < 0.3
    return replace(
        inputs,
        panel=new_panel,
        cubes=cubes,
        grades=grades,
        regime=regime,
        stances=stances,
        earnings_day=earnings,
        vol_forecast=scramble(inputs.vol_forecast),
        dd_forecast=scramble(inputs.dd_forecast),
    )


@pytest.fixture(scope="module")
def world():
    inputs = _world()
    block, internals = export.build_daily(inputs)
    return inputs, block, internals


def test_every_daily_column_is_named_with_the_daily_prefix(world):
    _, block, _ = world
    assert all(name.startswith(io.DAILY_PREFIX) for name in block.names)
    assert len(set(block.names)) == len(block.names)
    assert block.values.shape[2] == len(block.names)
    # Date-level columns are the same for every name on a date.
    level = block.values[:, :, block.date_level]
    finite = np.isfinite(level).all(axis=1)
    spread = np.nanmax(level, axis=1) - np.nanmin(level, axis=1)
    assert np.all(spread[finite] == 0)
    # The families the plan names are present.
    for name in ("d_ema21_dist", "d_mad", "d_sma400_dist", "d_bb_z", "d_keltner", "d_atr14", "d_donchian252",
                 "d_high52_dist", "d_rsi14", "d_macd_hist", "d_adx14", "d_lvl_support_distance",
                 "d_w_ema21_dist", "d_m_sma10_dist", "d_trend_align", "d_resid_mom12_1", "d_sr_support_dist",
                 "d_ret60_vs_side", "d_theme_ret120", "d_linked_mom21", "d_tug21", "d_max21", "d_abvol50",
                 "d_rev5_no_news", "d_beta60_side", "d_log_rv", "d_rskew5", "d_poc_dist", "d_round_fine",
                 "d_attention", "d_avwap_earnings", "d_cgo", "d_grade_a", "d_stance_fund", "d_grade_age",
                 "d_regime_exposure", "d_breadth", "d_weekday_0", "d_hammer"):
        assert name in block.names, name


def test_the_daily_block_never_reads_after_its_row(world):
    inputs, block, _ = world
    t0 = 300
    tampered = _tamper_after(inputs, t0)
    other, _ = export.build_daily(tampered)
    before = block.values[: t0 + 1]
    after = other.values[: t0 + 1]
    same = (before == after) | (np.isnan(before) & np.isnan(after))
    bad = [block.names[f] for f in range(len(block.names)) if not same[:, :, f].all()]
    assert not bad, f"columns reading the future: {bad}"
    # And the tampering did reach later rows.
    assert not np.array_equal(np.nan_to_num(block.values[t0 + 5 :]), np.nan_to_num(other.values[t0 + 5 :]))


def test_daily_formulas_on_known_values(world):
    inputs, block, internals = world
    panel = inputs.panel
    close = panel.adj_close
    t, j = 250, 1
    # RSI and stochastics stay in range; ADX in 0..100.
    for name in ("d_rsi14", "d_rsi2", "d_stoch_k14", "d_adx14"):
        v = block.values[:, :, block.column(name)]
        v = v[np.isfinite(v)]
        assert v.min() >= -1e-6 and v.max() <= 100 + 1e-6, name
    # The 20-session momentum is the log ratio of closes.
    assert block.values[t, j, block.column("d_ret20")] == pytest.approx(math.log(close[t, j] / close[t - 20, j]), rel=1e-5)
    # Donchian position is 1 exactly when the close is the window's top.
    pos = block.values[:, :, block.column("d_donchian20")]
    assert np.nanmax(pos) <= 1 + 1e-6 and np.nanmin(pos) >= -1e-6
    # The weekly EMA distance uses completed weeks only: mid-week rows repeat
    # the last Friday's EMA, so ln(C/wEMA) * sigma changes only through C.
    sigma = internals["sigma20"]
    w = block.values[:, :, block.column("d_w_ema21_dist")] * sigma
    implied = close / np.exp(w)
    days = np.asarray(panel.dates)
    ends = features.period_ends(days, "week")
    checked = 0
    for row in range(260, 300):
        if not ends[row] and np.isfinite(implied[row, j]) and np.isfinite(implied[row - 1, j]):
            checked += 1
            assert implied[row, j] == pytest.approx(implied[row - 1, j], rel=1e-4)
    assert checked > 20


def test_period_ends_mark_fridays_and_month_ends():
    days = _business_days("2024-01-01", 45)
    week = features.period_ends(days, "week")
    friday = (days.astype(np.int64) + 3) % 7 == 4
    assert np.array_equal(week, friday | np.concatenate([((days[1:].astype(np.int64) + 3) // 7) != ((days[:-1].astype(np.int64) + 3) // 7), [friday[-1]]]))
    month = features.period_ends(days, "month")
    assert days[month].tolist() == [np.datetime64("2024-01-31"), np.datetime64("2024-02-29")]


def test_intraday_rows_use_bars_before_k_and_only_the_close_of_k(world):
    inputs, block, internals = world
    ticker = "BBB"
    j = inputs.panel.index(ticker)
    cube = inputs.cubes[ticker]
    _, _, daily = export._daily_at_t(inputs, block, internals, j, cube)
    spy, qqq, side = inputs.cubes["SPY"], inputs.cubes["QQQ"], inputs.cubes["SMH"]
    from backend.market import sr_levels

    levels = sr_levels.daily_levels(inputs.panel)
    pos = np.searchsorted(np.asarray(inputs.panel.dates), cube.dates)
    level_block = (levels.levels[pos, j], levels.width[pos, j])
    eligible = {t: np.ones(len(inputs.cubes[t]), dtype=bool) for t in BOOK}
    market = intraday.breadth({t: inputs.cubes[t] for t in BOOK}, eligible)
    base = intraday.name_block(cube, daily, spy, qqq, side, market, level_block)
    assert np.isfinite(base.values[200:, :, base.names.index("i_is_support_dist")]).any()
    s = 200
    for k in (0, 1, 5, 23):
        high, low, volume = cube.high.copy(), cube.low.copy(), cube.volume.copy()
        o, c, auction = cube.open.copy(), cube.close.copy(), cube.auction_open.copy()
        high[s, k] *= 1.05
        low[s, k] *= 0.95
        volume[s, k] *= 7.0
        for arr in (o, high, low, c, volume):
            arr[s, k + 1 :] *= 1.2
        auction[s] *= 1.2
        altered = replace(cube, open=o, high=high, low=low, close=c, volume=volume, auction_open=auction)
        cubes = {t: inputs.cubes[t] for t in BOOK}
        cubes[ticker] = altered
        moved = intraday.name_block(altered, daily, spy, qqq, side, intraday.breadth(cubes, eligible), level_block)
        a, b = base.values[s, k], moved.values[s, k]
        same = (a == b) | (np.isnan(a) & np.isnan(b))
        bad = [base.names[f] for f in np.flatnonzero(~same)]
        assert not bad, f"slot {k} reads bar {k}'s high/low/volume or a later bar: {bad}"
        earlier = (base.values[:s] == moved.values[:s]) | (np.isnan(base.values[:s]) & np.isnan(moved.values[:s]))
        assert earlier.all()


def test_intraday_formulas_on_known_values(world):
    inputs, block, internals = world
    ticker = "DDD"
    j = inputs.panel.index(ticker)
    cube = inputs.cubes[ticker]
    _, _, daily = export._daily_at_t(inputs, block, internals, j, cube)
    name = intraday.name_block(cube, daily, inputs.cubes["SPY"], inputs.cubes["QQQ"], inputs.cubes["IGV"], None, None)
    col = {n: i for i, n in enumerate(name.names)}
    s, k = 150, 6
    c = cube.close[s]
    assert name.values[s, k, col["i_since_open"]] == pytest.approx(math.log(c[k] / cube.open[s, 0]), rel=1e-5)
    assert name.values[s, k, col["i_gap"]] == pytest.approx(math.log(cube.open[s, 0] / cube.prior_close[s]), rel=1e-5)
    # The prior close is exactly the session's prior close on its basis.
    expected = math.log(c[k] / cube.prior_close[s]) / daily["atr"][s]
    assert name.values[s, k, col["i_pdc_dist"]] == pytest.approx(expected, rel=1e-4)
    # VWAP through bar k-1, typical price weighted by volume.
    tp = (cube.high[s, :k] + cube.low[s, :k] + cube.close[s, :k]) / 3
    vwap = float((tp * cube.volume[s, :k]).sum() / cube.volume[s, :k].sum())
    sigma = np.std([math.log(cube.close[q, k] / cube.open[q, 0]) for q in range(s - 60, s)], ddof=1)
    assert name.values[s, k, col["i_vwap_dist"]] == pytest.approx(math.log(c[k] / vwap) / sigma, rel=1e-4)
    # Opening range over two bars, formed from slot 2.
    assert math.isnan(name.values[s, 1, col["i_or2_position"]])
    hi, lo = cube.high[s, :2].max(), cube.low[s, :2].min()
    assert name.values[s, k, col["i_or2_position"]] == pytest.approx((c[k] - lo) / (hi - lo), rel=1e-4)
    # SPY's 12th half hour only at 15:30.
    assert math.isnan(name.values[s, 22, col["i_spy_r12"]]) and np.isfinite(name.values[s, 23, col["i_spy_r12"]])


def test_the_s1_dataset_labels_and_ranks(world):
    inputs, block, _ = world
    data = export.s1_data(inputs, block)
    io.validate(data)
    assert data.kind == io.S1
    first = min(c.dates[0] for t, c in inputs.cubes.items() if t in BOOK)
    assert data.dates.min() >= first
    panel = inputs.panel
    opens = panel.open
    dates = np.asarray(panel.dates)
    t = int(np.searchsorted(dates, data.dates[len(data) // 2]))
    rows = np.flatnonzero(data.dates == dates[t])
    raw = []
    for i in rows:
        j = panel.index(data.tickers[i])
        raw.append(math.log(opens[t + 21, j] / opens[t + 1, j]))
    raw = np.array(raw)
    np.testing.assert_allclose(data.extra["r"][rows], raw - raw.mean(), rtol=1e-4, atol=1e-6)
    # Name-level features are rank-Gauss per date; date-level ones raw.
    col = data.feature_names.index("d_ret20")
    assert abs(np.nanmean(data.x[rows, col])) < 1e-6
    level = data.feature_names.index("d_regime_exposure")
    assert np.allclose(data.x[rows, level], inputs.regime[t, 0])
    # Labels past the panel's end are NaN, not dropped.
    assert np.isnan(data.y[data.dates == dates[-1]]).all()


def test_the_ti_dataset_rows_labels_and_joined_daily_block(world):
    inputs, block, internals = world
    data = export.ti_data(inputs, block, internals)
    io.validate(data)
    assert len(data) % io.TI_SLOTS == 0
    assert data.feature_names[-2:] == export.FORECAST_COLUMNS
    i = len(data) // 2
    ticker, day, k = data.tickers[i], data.dates[i], int(data.slot[i])
    cube = inputs.cubes[ticker]
    s = int(np.searchsorted(cube.dates, day))
    assert data.y[i] == pytest.approx(1e4 * math.log(cube.auction_open[s] / cube.close[s, k]), rel=1e-4)
    panel_dates = np.asarray(inputs.panel.dates)
    t = int(np.searchsorted(panel_dates, day)) - 1
    j = inputs.panel.index(ticker)
    col = data.feature_names.index("d_rsi14")
    assert data.x[i, col] == pytest.approx(block.values[t, j, block.column("d_rsi14")], rel=1e-5, abs=1e-6)
    assert data.x[i, data.feature_names.index("d_volfc")] == pytest.approx(inputs.vol_forecast[t, j], rel=1e-5)
    # Every row's name was eligible at t.
    eligible = inputs.eligible()
    for r in range(0, len(data), 997):
        t = int(np.searchsorted(panel_dates, data.dates[r])) - 1
        assert eligible[t, inputs.panel.index(data.tickers[r])]


def test_the_sequence_tensor_channels(world):
    inputs, block, internals = world
    tensor = export.seq_tensor(inputs, block, internals)
    assert tensor.seq.shape[2:] == (io.STEPS_PER_SESSION, len(io.SEQ_CHANNELS))
    n = list(tensor.tickers).index("CCC")
    cube = inputs.cubes["CCC"]
    s = 120
    where = int(np.searchsorted(tensor.sessions, cube.dates[s]))
    assert tensor.valid[n, where]
    gap_flag = io.SEQ_CHANNELS.index("gap_step")
    assert tensor.seq[n, where, 0, gap_flag] == 1 and tensor.seq[n, where, 5, gap_flag] == 0
    j = inputs.panel.index("CCC")
    _, _, daily = export._daily_at_t(inputs, block, internals, j, cube)
    k = 10
    expected = math.log(cube.close[s, k] / cube.prior_close[s]) / daily["atr"][s]
    got = float(tensor.seq[n, where, k + 1, io.SEQ_CHANNELS.index("prior_close_distance")])
    assert got == pytest.approx(expected, rel=2e-3, abs=2e-3)


def test_the_export_command_writes_every_file_and_a_summary(tmp_path):
    import io as stdio
    import json

    from backend.cli import market_stage3_export as cli

    inputs = _world(sessions=380)
    out_dir = tmp_path / "out"
    args = cli.build_parser().parse_args(["--root", str(tmp_path), "--out-dir", str(out_dir), "--workers", "1"])
    printed = stdio.StringIO()
    code = cli.run(args, out=printed, loader=lambda *a, **k: inputs, desk_run=lambda store: None)
    assert code == 0, printed.getvalue()
    for name in ("stage3_s1.npz", "stage3_ti.npz", "stage3_seq.npz", "stage3_ohlcv.npz", "stage3_export.json"):
        assert (out_dir / name).exists(), name
    summary = json.loads((out_dir / "stage3_export.json").read_text())
    assert summary["plan"] == io.PLAN
    assert summary["files"]["ti"]["rows"] % io.TI_SLOTS == 0
    ti = io.load_data(out_dir / "stage3_ti.npz")
    assert ti.kind == io.TI and summary["files"]["ti"]["sha256"] == cli.sha256(out_dir / "stage3_ti.npz")
    seq = io.load_seq(out_dir / "stage3_seq.npz")
    assert seq.seq.shape[1] == len(seq.sessions)
