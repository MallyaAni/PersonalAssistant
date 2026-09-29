"""Stage 3's networks: images, windows, scaling, causality and the walk-forward.

Everything runs on the CPU with tiny synthetic data, small widths and a few
epochs, through the same code the registered run uses.
"""

import math

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from backend.cli import market_stage3_nn as cli  # noqa: E402
from backend.market import stage3_io as io  # noqa: E402
from backend.market import stage3_nn as nn3  # noqa: E402

CHANNELS = len(io.SEQ_CHANNELS)
STEPS = io.STEPS_PER_SESSION
SLOTS = io.TI_SLOTS
# The small T-I walk-forward: first test block at session 30 (fit 0..15,
# validation 18..27), refit every 20 sessions.
SMALL_TI = {"min_train": 30, "validation": 10, "gap": 2, "refit": 20}
ONE = ({"lr": 3e-3, "dropout": 0.0, "width": 8},)
TWO = (
    {"lr": 3e-3, "dropout": 0.0, "width": 8},
    {"lr": 1e-3, "dropout": 0.1, "width": 8},
)


# Consecutive calendar dates from `start`.
def _dates(n, start="2021-01-04"):
    return np.datetime64(start, "D") + np.arange(n)


# Names that sort in the order given.
def _names(n, prefix="N"):
    return np.array([f"{prefix}{i:02d}" for i in range(n)])


# A random sequence tensor: N(0, 1) channels in float16, the gap-step flag on
# each session's gap step, and the listed (name, session) cells invalid.
def _tensor(names, sessions, seed=0, invalid=()):
    rng = np.random.default_rng(seed)
    shape = (len(names), len(sessions), STEPS, CHANNELS)
    seq = rng.normal(size=shape).astype(np.float16)
    seq[..., -1] = 0
    seq[:, :, 0, -1] = 1
    valid = np.ones(shape[:2], dtype=bool)
    for n, s in invalid:
        valid[n, s] = False
        seq[n, s] = 0
    return io.SeqTensor(np.asarray(names), np.asarray(sessions), seq, valid)


# A T-I dataset with a row for every (session, name, slot); `labels` is
# (sessions, names, 24) in bp. Two daily columns constant per name-session
# (the second with gaps) and one intraday column the sequence model ignores.
def _ti_data(dates, names, labels, seed=1):
    rng = np.random.default_rng(seed)
    d_n, n_n = len(dates), len(names)
    daily = rng.normal(size=(d_n * n_n, 2))
    daily[rng.random(d_n * n_n) < 0.1, 1] = np.nan
    x = np.concatenate(
        [np.repeat(daily, SLOTS, axis=0), rng.normal(size=(d_n * n_n * SLOTS, 1))],
        axis=1,
    )
    return io.Stage3Data(
        kind=io.TI,
        dates=np.repeat(np.asarray(dates), n_n * SLOTS),
        tickers=np.tile(np.repeat(np.asarray(names), SLOTS), d_n),
        slot=np.tile(np.arange(SLOTS, dtype=np.int8), d_n * n_n),
        x=x.astype(np.float32),
        feature_names=("d_a", "d_b", "i_c"),
        y=np.asarray(labels, dtype=np.float32).reshape(-1),
    )


# A T-S1 dataset with a row for every (date, name): `signal` is a daily
# column, the label the per-date rank-Gauss of weight * signal + noise, and
# extra["r"] that raw relative return (or the one given).
def _s1_data(dates, names, weight=0.0, seed=2, r=None):
    rng = np.random.default_rng(seed)
    count = len(dates) * len(names)
    signal = rng.normal(size=count)
    raw = weight * signal + rng.normal(size=count) if r is None else r.reshape(-1)
    date_col = np.repeat(np.asarray(dates), len(names))
    x = np.stack([signal, rng.normal(size=count), rng.normal(size=count)], axis=1)
    return io.Stage3Data(
        kind=io.S1,
        dates=date_col,
        tickers=np.tile(np.asarray(names), len(dates)),
        slot=np.zeros(count, dtype=np.int8),
        x=x.astype(np.float32),
        feature_names=("d_signal", "d_noise", "i_other"),
        y=io.rank_gauss(raw, date_col).astype(np.float32),
        extra={"r": raw.astype(np.float32)},
    )


# Random-walk daily bars for the names; `volume` replaces the random volume.
def _bars(dates, names, seed=3, volume=None):
    rng = np.random.default_rng(seed)
    shape = (len(dates), len(names))
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, size=shape), axis=0))
    open_ = close * np.exp(rng.normal(0, 0.01, size=shape))
    high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.01, size=shape)))
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.01, size=shape)))
    if volume is None:
        volume = rng.uniform(0.8, 1.2, size=shape) * 1e6
    return io.DailyOHLCV(
        np.asarray(names), np.asarray(dates), open_, high, low, close, volume
    )


# Settings for a small CPU run.
def _settings(**overrides):
    base = {"seeds": (0,), "max_epochs": 3, "patience": 2, "batch": 16, "device": "cpu"}
    return nn3.Settings(**{**base, **overrides})


# The rows of a dataset whose session index is in [lo, hi).
def _in_sessions(data, lo, hi):
    _, index = io.session_index(data.dates)
    return (index >= lo) & (index < hi)


# ---------------------------------------------------------------------------
# The chart CNN's images and network
# ---------------------------------------------------------------------------


# Both JKX networks flatten to the published fully connected inputs (15,360
# and 46,080), carry the published parameter counts, stride and dilate only
# I20's first convolution, and start from Xavier weights with zero biases.
def test_jkx_networks_flatten_to_the_published_sizes():
    assert nn3.jkx_flattened_size(io.CNN_I5) == 15_360
    assert nn3.jkx_flattened_size(io.CNN_I20) == 46_080
    counts = {io.CNN_I5: 155_138, io.CNN_I20: 708_866}
    for family in (io.CNN_I5, io.CNN_I20):
        _, height, width = io.CNN_IMAGES[family]
        model = nn3.JKXNet(family).eval()
        images = torch.zeros(2, 1, height, width)
        features = model.features(images)
        assert features.flatten(1).shape[1] == nn3.JKX_FLATTENED[family]
        assert tuple(model(images).shape) == (2, 2)
        assert nn3.parameter_count(model) == counts[family]
        convs = [m for m in model.modules() if isinstance(m, torch.nn.Conv2d)]
        assert len(convs) == len(nn3.JKX_CHANNELS[family])
        for i, conv in enumerate(convs):
            strided = family == io.CNN_I20 and i == 0
            assert conv.stride == ((3, 1) if strided else (1, 1))
            assert conv.dilation == ((2, 1) if strided else (1, 1))
            assert conv.kernel_size == (5, 3)
            assert float(conv.bias.detach().abs().sum()) == 0.0
        assert isinstance(model.classify[1], torch.nn.Dropout)
        assert model.classify[1].p == 0.5


# A hand-drawn I5 image: every open tick, high-low bar, close tick,
# moving-average pixel and volume bar lands where the prices say, with the
# window's high at row 0, its low at row 24, row 25 empty, volume below.
def test_i5_image_places_every_pixel():
    o = np.array([[110, 104, 118, 120, 101.0]])
    h = np.array([[114, 108, 124, 122, 106.0]])
    lo = np.array([[100, 102, 112, 115, 100.0]])
    c = np.array([[112, 106, 120, 116, 103.0]])
    v = np.array([[100, 300, 50, 0, 250.0]])
    ma = np.array([[110, 111, 112, np.nan, 109.0]])
    images, kept = nn3.render_charts(o, h, lo, c, v, ma, io.CNN_I5)
    assert kept.tolist() == [True]
    assert images.shape == (1, 32, 15)
    assert images.dtype == np.uint8
    expected = np.zeros((32, 15), dtype=np.uint8)
    # Price rows: row = 124 - price (the top is 124, the bottom 100, 25 rows).
    for day in range(5):
        x = 3 * day
        expected[int(124 - o[0, day]), x] = 255
        expected[int(124 - h[0, day]) : int(124 - lo[0, day]) + 1, x + 1] = 255
        expected[int(124 - c[0, day]), x + 2] = 255
        if np.isfinite(ma[0, day]):
            expected[int(124 - ma[0, day]), x + 1] = 255
    # Volume: 6 rows scaled to the largest (300): heights 2, 6, 1, 0, 5.
    for day, tall in enumerate((2, 6, 1, 0, 5)):
        if tall:
            expected[32 - tall :, 3 * day + 1] = 255
    np.testing.assert_array_equal(images[0], expected)
    assert not images[0, 25].any()


# The I20 layout: 51 price rows whose top and bottom rows are reached, an
# empty gap row, 12 volume rows holding only middle-column bars (the
# window's biggest volume full height, a fifth of it 2 rows). The row's
# image is the 20 bars ending at its date, and each day's moving average
# is the mean of the 20 closes ending that day - so it reads closes from
# before the window, and moving one of those moves the image.
def test_i20_image_is_the_window_ending_at_the_row_with_its_moving_average():
    dates = _dates(45)
    bars = _bars(dates, np.array(["AAA"]))
    volume = np.full((45, 1), 1e6)
    volume[40] = 5e6
    bars = io.DailyOHLCV(
        bars.tickers, bars.dates, bars.open, bars.high, bars.low, bars.close, volume
    )
    row_dates, row_tickers = dates[[44]], np.array(["AAA"])
    images, has, counts = nn3.chart_images(bars, row_dates, row_tickers, io.CNN_I20)
    assert has.tolist() == [True]
    assert counts["images"] == 1
    assert counts["partial_moving_average"] == 0
    image = images[0]
    assert image.shape == (64, 60)
    assert image[0].any()
    assert image[50].any()
    assert not image[51].any()
    assert not np.delete(image[52:], np.arange(1, 60, 3), axis=1).any()
    heights = (image[52:, 1::3] > 0).sum(axis=0)
    assert heights[15] == 12  # day 40 is the window's day 15
    assert (heights[np.arange(20) != 15] == 2).all()  # rint(12 / 5)
    window = slice(25, 45)
    average = np.array([bars.close[j - 19 : j + 1, 0].mean() for j in range(25, 45)])
    expected, _ = nn3.render_charts(
        bars.open[window, 0],
        bars.high[window, 0],
        bars.low[window, 0],
        bars.close[window, 0],
        volume[window, 0],
        average,
        io.CNN_I20,
    )
    np.testing.assert_array_equal(image, expected[0])
    shifted = bars.close.copy()
    shifted[10, 0] *= 1.3  # before the window, inside days 25..29's averages
    moved = io.DailyOHLCV(
        bars.tickers, bars.dates, bars.open, bars.high, bars.low, shifted, volume
    )
    again, _, _ = nn3.chart_images(moved, row_dates, row_tickers, io.CNN_I20)
    assert (again[0] != image).any()
    average = np.array([shifted[j - 19 : j + 1, 0].mean() for j in range(25, 45)])
    redrawn, _ = nn3.render_charts(
        bars.open[window, 0],
        bars.high[window, 0],
        bars.low[window, 0],
        shifted[window, 0],
        volume[window, 0],
        average,
        io.CNN_I20,
    )
    np.testing.assert_array_equal(again[0], redrawn[0])


# Rows without a complete window get no image and are counted by reason: a
# ticker the bars lack, a date they lack, too little history, a missing
# price inside the window; a missing close before the window only drops
# the moving average's pixel.
def test_chart_images_skip_rows_without_complete_bars():
    dates = _dates(20)
    bars = _bars(dates, np.array(["AAA", "BBB"]))
    opens = bars.open.copy()
    opens[15, 1] = np.nan  # inside BBB's window for dates 15..19
    bars = io.DailyOHLCV(
        bars.tickers, bars.dates, opens, bars.high, bars.low, bars.close, bars.volume
    )
    row_dates = np.array(
        [dates[19], dates[19], dates[2], dates[19], np.datetime64("2030-01-01")],
        dtype="datetime64[D]",
    )
    row_tickers = np.array(["AAA", "BBB", "AAA", "ZZZ", "AAA"])
    images, has, counts = nn3.chart_images(bars, row_dates, row_tickers, io.CNN_I5)
    assert has.tolist() == [True, False, False, False, False]
    assert counts["missing_ohlc"] == 1
    assert counts["short_history"] == 1
    assert counts["no_ticker"] == 1
    assert counts["no_date"] == 1
    assert counts["images"] == 1
    assert not images[1:].any()
    # A missing close before the window leaves the image, minus some averages.
    closes = bars.close.copy()
    closes[12, 0] = np.nan
    gapped = io.DailyOHLCV(
        bars.tickers, bars.dates, bars.open, bars.high, bars.low, closes, bars.volume
    )
    _, has2, counts2 = nn3.chart_images(
        gapped, row_dates[:1], row_tickers[:1], io.CNN_I5
    )
    assert has2.tolist() == [True]
    assert counts2["partial_moving_average"] == 1


# The chart label splits each date at its own median; a missing return stays
# unlabelled.
def test_above_median_splits_each_date_and_keeps_missing_returns_unlabelled():
    dates = np.repeat(_dates(2), 4)
    r = np.array([0.1, 0.4, 0.2, 0.3, 5.0, np.nan, 1.0, 3.0])
    labels = nn3.above_median(r, dates)
    assert labels[:4].tolist() == [0.0, 1.0, 0.0, 1.0]
    assert labels[[4, 6, 7]].tolist() == [1.0, 0.0, 0.0]
    assert math.isnan(labels[5])


# ---------------------------------------------------------------------------
# Windows, units and scaling
# ---------------------------------------------------------------------------


# A window is the sessions ending at the unit's session, earliest first;
# sessions before the tensor starts and invalid sessions are marked.
def test_window_arrays_left_pad_and_mark_invalid_sessions():
    seq = np.zeros((2, 5, STEPS, CHANNELS), dtype=np.float16)
    for n in range(2):
        for s in range(5):
            seq[n, s] = 10 * n + s
    valid = np.ones((2, 5), dtype=bool)
    valid[1, 2] = False
    windows, ok = nn3.window_arrays(
        seq, valid, np.array([0, 1, 1]), np.array([1, 4, 2]), 3
    )
    assert windows.shape == (3, 3, STEPS, CHANNELS)
    assert ok.tolist() == [
        [False, True, True],
        [False, True, True],
        [True, True, False],
    ]
    assert windows[0, 1, 0, 0] == 0 and windows[0, 2, 0, 0] == 1  # noqa: PT018
    assert windows[1, 1, 5, 3] == 13 and windows[1, 2, 26, 11] == 14  # noqa: PT018
    assert windows[2, 0, 0, 0] == 10


# T-I rows group into (ticker, session) units whose outputs are their slots;
# a slot without a row has no output, and a repeated slot is refused.
def test_ti_units_group_slots_by_name_session_and_refuse_repeats():
    labels = np.arange(2 * 2 * SLOTS, dtype=float).reshape(2, 2, SLOTS)
    data = _ti_data(_dates(2), np.array(["AAA", "BBB"]), labels)
    keep = np.flatnonzero(~((data.tickers == "BBB") & (data.slot == 5)))
    sub = io.Stage3Data(
        io.TI,
        data.dates[keep],
        data.tickers[keep],
        data.slot[keep],
        data.x[keep],
        data.feature_names,
        data.y[keep],
    )
    units = nn3.ti_units(sub)
    assert len(units.first) == 4
    assert units.rows.shape == (4, SLOTS)
    assert (units.rows[[1, 3], 5] == -1).all()
    assert (units.rows[[0, 2], 5] >= 0).all()
    assert np.array_equal(sub.y[units.rows[2, :5]], units.targets[2, :5])
    assert np.array_equal(units.of_row[units.rows[3, 7]], 3)
    doubled = io.Stage3Data(
        io.TI,
        np.r_[sub.dates[:1], sub.dates],
        np.r_[sub.tickers[:1], sub.tickers],
        np.r_[sub.slot[:1], sub.slot],
        np.r_[sub.x[:1], sub.x],
        sub.feature_names,
        np.r_[sub.y[:1], sub.y],
    )
    with pytest.raises(ValueError, match="repeat"):
        nn3.ti_units(doubled)


# The daily branch's robust z: median/IQR from the given rows, clipped to
# +-5, missing values 0 with an indicator; a flag column (IQR 0) keeps scale
# 1 and an all-missing column centres on 0.
def test_robust_scaling_clips_fills_and_flags_missing_values():
    x = np.array(
        [
            [1.0, 0.0, np.nan],
            [2.0, 0.0, np.nan],
            [3.0, 1.0, np.nan],
            [4.0, 0.0, np.nan],
            [5.0, 0.0, np.nan],
        ]
    )
    median, scale = nn3.robust_stats(x)
    assert median.tolist() == [3.0, 0.0, 0.0]
    assert scale.tolist() == [2.0, 1.0, 1.0]
    wide = np.array([[100.0, 1.0, np.nan], [-100.0, 0.0, 2.0]])
    out = nn3.daily_inputs(wide, median, scale)
    assert out.shape == (2, 6)
    assert out.dtype == np.float32
    assert out[0, 0] == 5.0 and out[1, 0] == -5.0  # noqa: PT018
    assert out[0, 1] == 1.0
    assert out[0, 2] == 0.0 and out[1, 2] == 2.0  # noqa: PT018
    assert out[:, 3:].tolist() == [[0.0, 0.0, 1.0], [0.0, 0.0, 0.0]]


# Channel statistics read only valid cells dated on or before the cutoff.
def test_channel_stats_read_only_valid_cells_up_to_the_cutoff():
    sessions = _dates(6)
    tensor = _tensor(_names(3), sessions, invalid=[(1, 1)])
    cutoff = sessions[3]
    median, scale = nn3.channel_stats(tensor.seq, tensor.valid, sessions, cutoff)
    later = tensor.seq.copy()
    later[:, 4:] = 50
    later[1, 1] = -50  # invalid, so never read
    same = nn3.channel_stats(later, tensor.valid, sessions, cutoff)
    np.testing.assert_array_equal(same[0], median)
    np.testing.assert_array_equal(same[1], scale)
    assert scale[-1] == 1.0  # the gap-step flag has IQR 0
    earlier = tensor.seq.copy()
    earlier[0, 0, :, 0] = 50
    moved = nn3.channel_stats(earlier, tensor.valid, sessions, cutoff)
    assert moved[0][0] != median[0] or moved[1][0] != scale[0]


# What the network is fed, exactly: each valid session of the window as the
# channel's robust z (median and IQR of the valid cells up to the last fit
# session) clipped to +-5, padded and invalid sessions as zeros, the step
# mask attention reads, the daily block's robust z (fit units only) with its
# missing indicators, and the T-I targets winsorized at the fit rows'
# quantiles and divided by their standard deviation.
def test_a_batch_is_the_fold_scaled_window_with_empty_sessions_zeroed():
    rng = np.random.default_rng(26)
    dates, names = _dates(40), _names(3)
    tensor = _tensor(names, dates, seed=27, invalid=[(1, 30)])
    seq = tensor.seq.copy()
    seq[0, 31, 3, 2] = 1e4  # clipped to +5
    tensor = io.SeqTensor(tensor.tickers, tensor.sessions, seq, tensor.valid)
    labels = 40 * rng.standard_t(3, size=(40, 3, SLOTS))
    data = _ti_data(dates, names, labels)
    settings = _settings(grid=ONE, **SMALL_TI)
    task = nn3._SeqTask(data, tensor, settings)
    sessions, index = io.session_index(data.dates)
    fold = io.folds(40, 20, 2, min_train=30, validation=10)[0]
    unit_session = index[task.units.first]
    fit = np.flatnonzero(unit_session < fold.fit_end)
    state = task.prepare(fold, sessions, fit, "cpu")
    median, scale = nn3.channel_stats(seq, tensor.valid, dates, dates[fold.fit_end - 1])
    np.testing.assert_allclose(state.median.numpy(), median, rtol=1e-6)
    units = np.array(
        [3 * 31 + 0, 3 * 33 + 1, 3 * 2 + 2]
    )  # (N00, 31), (N01, 33), (N02, 2)
    (x, daily, steps), targets = task.batch(state, units, "cpu")
    assert tuple(x.shape) == (3, 6 * STEPS, CHANNELS)
    window = x.numpy().reshape(3, 6, STEPS, CHANNELS)
    expected = np.clip((seq[0, 26:32].astype(np.float64) - median) / scale, -5, 5)
    np.testing.assert_allclose(window[0], expected, rtol=1e-5, atol=1e-5)
    assert window[0, 5, 3, 2] == 5.0
    assert not window[1, 2].any()  # N01's session 30 is invalid
    assert window[1, 3].any()
    assert not window[2, :3].any()  # sessions before the tensor's first
    np.testing.assert_array_equal(
        steps.numpy().reshape(3, 6, STEPS)[:, :, 0],
        [[True] * 6, [True, True, False, True, True, True], [False] * 3 + [True] * 3],
    )
    columns = io.daily_columns(data.feature_names)
    raw = data.x[task.units.first][:, columns]
    d_median, d_scale = nn3.robust_stats(raw[fit])
    np.testing.assert_allclose(
        daily.numpy(), nn3.daily_inputs(raw[units], d_median, d_scale), rtol=1e-6
    )
    y = data.y.astype(np.float64).reshape(40, 3, SLOTS)
    fit_labels = y[: fold.fit_end].reshape(-1)
    low, high = np.quantile(fit_labels, io.WINSOR)
    y_scale = np.clip(fit_labels, low, high).std()
    assert state.y_scale == pytest.approx(y_scale, rel=1e-12)
    assert state.record["winsor_bp"] == pytest.approx([low, high], rel=1e-12)
    expected_y = np.clip(y[[31, 33, 2], [0, 1, 2]], low, high) / y_scale
    np.testing.assert_allclose(targets.numpy(), expected_y, rtol=1e-6)
    assert (targets.numpy() * y_scale).max() <= high + 1e-3


# The schedule rises linearly over the warm-up, peaks at 1 and follows a
# cosine to 0 at the planned last step.
def test_lr_factor_warms_up_then_follows_a_cosine():
    assert nn3.lr_factor(0, 10, 200) == pytest.approx(0.1)
    assert nn3.lr_factor(4, 10, 200) == pytest.approx(0.5)
    assert nn3.lr_factor(9, 10, 200) == pytest.approx(1.0)
    assert nn3.lr_factor(10, 10, 200) == pytest.approx(1.0)
    assert nn3.lr_factor(105, 10, 200) == pytest.approx(0.5)
    assert nn3.lr_factor(200, 10, 200) == pytest.approx(0.0)
    values = [nn3.lr_factor(s, 10, 200) for s in range(10, 200)]
    assert all(a >= b for a, b in zip(values, values[1:], strict=False))


# ---------------------------------------------------------------------------
# The sequence model
# ---------------------------------------------------------------------------


# T-I causality, with the session-position embedding in place (and made
# large, so it matters): the forecast for slot k is the output at session
# s's bar k, and perturbing every later step leaves slots 0..k unchanged,
# while perturbing bar k itself does move slot k.
def test_ti_forecast_at_bar_k_never_reads_a_later_step():
    torch.manual_seed(0)
    model = nn3.SeqNet(io.TI, CHANNELS, daily=4, width=16, dropout=0.1).eval()
    assert tuple(model.session_position.weight.shape) == (io.SEQ_SESSIONS[io.TI], 16)
    torch.nn.init.normal_(model.session_position.weight, std=1.0)
    steps = io.SEQ_SESSIONS[io.TI] * STEPS
    assert nn3.TI_FIRST_OUTPUT == 5 * 27 + 1
    seq = torch.randn(3, steps, CHANNELS)
    daily = torch.randn(3, 4)
    with torch.no_grad():
        base = model(seq, daily)
        # The embedding is wired in: the row's own session's row moves the
        # forecasts; sessions s-5 and s-4 are outside every forecast's
        # receptive field, so their rows move nothing. (Random directions:
        # a shift equal in every dimension is removed by the LayerNorms.)
        table = model.session_position.weight
        saved = table.clone()
        table[-1] += torch.randn(16)
        assert (model(seq, daily) - base).abs().max() > 1e-3
        table.copy_(saved)
        table[:2] += 10.0 * torch.randn(2, 16)
        torch.testing.assert_close(model(seq, daily), base, rtol=0, atol=1e-5)
        table.copy_(saved)
        assert tuple(base.shape) == (3, SLOTS)
        for k in (0, 1, 7, 22, 23):
            step = nn3.TI_FIRST_OUTPUT + k
            later = seq.clone()
            later[:, step + 1 :] += 100 * torch.randn_like(later[:, step + 1 :])
            out = model(later, daily)
            torch.testing.assert_close(
                out[:, : k + 1], base[:, : k + 1], rtol=0, atol=1e-5
            )
            if k < SLOTS - 1:
                assert (out[:, k + 1 :] - base[:, k + 1 :]).abs().max() > 1e-3
            now = seq.clone()
            now[:, step] += 10.0
            assert (model(now, daily)[:, k] - base[:, k]).abs().max() > 1e-3
        # The encoder alone: step t never reads a step after t.
        h = model.encode(seq)
        for t in (0, 40, 100, steps - 2):
            later = seq.clone()
            later[:, t + 1 :] = 50.0
            torch.testing.assert_close(
                model.encode(later)[:, : t + 1], h[:, : t + 1], rtol=0, atol=1e-5
            )


# The TCN's receptive field is the registered 63 steps: step t's output
# reads step t - 62 and nothing before it. (So a T-I forecast at bar k of
# session s reads from step 74 + k on: sessions s-5 and s-4 of its
# six-session window never reach any forecast.)
def test_tcn_receptive_field_is_63_steps():
    torch.manual_seed(2)
    model = nn3.SeqNet(io.TI, CHANNELS, daily=4, width=8, dropout=0.0).eval()
    seq = torch.randn(1, io.SEQ_SESSIONS[io.TI] * STEPS, CHANNELS)
    t = 150
    with torch.no_grad():
        base = model.encode(seq)[0, t]
        edge = seq.clone()
        edge[:, t - 62] += 10.0
        assert (model.encode(edge)[0, t] - base).abs().max() > 1e-4
        before = seq.clone()
        before[:, : t - 62] += 100.0 * torch.randn_like(before[:, : t - 62])
        torch.testing.assert_close(model.encode(before)[0, t], base, rtol=0, atol=1e-5)
        early = seq.clone()
        early[:, : 2 * STEPS] = 1e3  # sessions s-5 and s-4
        torch.testing.assert_close(
            model(early, torch.zeros(1, 4)),
            model(seq, torch.zeros(1, 4)),
            rtol=0,
            atol=1e-5,
        )


# The sequence model's parameters, counted layer by layer, include the
# (K, W) session-position embedding: K = 6 sessions for T-I, 60 for T-S1.
def test_seqnet_parameter_count_includes_the_session_position_embedding():
    daily = 300
    for width in (32, 64):
        shared = (
            13 * width  # Linear(12 -> W)
            + 27 * width  # step-type embedding
            + 5 * (3 * width * width + width + 2 * width)  # conv + LayerNorm, x5
            + 2 * width  # final LayerNorm
            + (daily * width + width)
            + (width * width + width)  # daily branch
        )
        ti_head = (2 * width * width + width) + (width + 1)
        s1_head = width + width * width + (3 * width * width + width) + (width + 1)
        for kind, head in ((io.TI, ti_head), (io.S1, s1_head)):
            model = nn3.SeqNet(kind, CHANNELS, daily, width, 0.1)
            sessions = io.SEQ_SESSIONS[kind]
            assert tuple(model.session_position.weight.shape) == (sessions, width)
            assert nn3.parameter_count(model) == shared + sessions * width + head
    assert nn3.parameter_count(nn3.SeqNet(io.TI, CHANNELS, daily, 64, 0.1)) == 97_217
    assert nn3.parameter_count(nn3.SeqNet(io.S1, CHANNELS, daily, 64, 0.1)) == 108_929


# T-S1: attention reads only the steps marked valid, and a row with none
# valid still gets a finite forecast.
def test_s1_head_pools_valid_steps_and_survives_a_row_with_none():
    torch.manual_seed(1)
    model = nn3.SeqNet(io.S1, CHANNELS, daily=4, width=8, dropout=0.0).eval()
    steps = io.SEQ_SESSIONS[io.S1] * STEPS
    seq = torch.randn(2, steps, CHANNELS)
    daily = torch.randn(2, 4)
    valid = torch.ones(2, steps, dtype=torch.bool)
    valid[1] = False
    with torch.no_grad():
        out = model(seq, daily, valid)
    assert tuple(out.shape) == (2, 1)
    assert torch.isfinite(out).all()


# The T-I walk-forward: forecasts exist exactly on the test blocks, each
# fold's forecast is the mean of its seeds, the chosen configuration's first
# seed is its column of yhat_configs, the meta records every choice, the file
# round-trips, and a second run gives the same numbers bit for bit.
def test_seq_ti_walk_forward_forecasts_test_rows_only_and_repeats_exactly(tmp_path):
    rng = np.random.default_rng(5)
    dates, names = _dates(60), _names(6)
    tensor = _tensor(names, dates, seed=4)
    data = _ti_data(dates, names, 40 * rng.normal(size=(60, 6, SLOTS)))
    settings = _settings(grid=TWO, seeds=(0, 1), **SMALL_TI)
    first = nn3.run_seq(data, tensor, settings)
    second = nn3.run_seq(data, tensor, settings)
    for name in ("yhat", "yhat_seeds", "yhat_configs", "fold"):
        np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
    tested = _in_sessions(data, 30, 60)
    assert np.isfinite(first.yhat[tested]).all()
    assert np.isnan(first.yhat[~tested]).all()
    assert (first.fold[~tested] == -1).all()
    assert (first.fold[_in_sessions(data, 30, 50)] == 0).all()
    assert (first.fold[_in_sessions(data, 50, 60)] == 1).all()
    assert first.yhat_seeds.shape == (len(data), 2)
    assert first.yhat_configs.shape == (len(data), 2)
    np.testing.assert_allclose(first.yhat, first.yhat_seeds.mean(axis=1), rtol=1e-6)
    meta = first.meta
    assert meta["registered"] is False
    assert meta["family"] == io.SEQ
    assert meta["kind"] == io.TI
    assert len(meta["folds"]) == 2
    for number, record in enumerate(meta["folds"]):
        assert record["sessions"]["fit"] == [0, [16, 36][number]]
        assert len(record["configs"]) == 2
        for run in record["configs"]:
            assert 1 <= run["best_epoch"] <= run["epochs"] <= 3
            assert run["seconds"] >= 0
            assert "score" in run
        chosen = record["chosen"]
        rows = first.fold == number
        np.testing.assert_array_equal(
            first.yhat_configs[rows, chosen], first.yhat_seeds[rows, 0]
        )
        assert [s["seed"] for s in record["seeds"]] == [0, 1]
        assert record["scaling"]["y_scale"] > 0
    back = io.load_forecast(io.save_forecast(tmp_path / "f.npz", first))
    np.testing.assert_array_equal(back.yhat, first.yhat)
    assert back.meta["folds"][0]["chosen_config"] == meta["folds"][0]["chosen_config"]


# The slot mapping, end to end: a label planted in session s's bar k is
# learned (the forecast at slot k reads bar k), while a label that is bar
# k+1's value is not (the model cannot see bar k+1 at slot k).
def test_seq_ti_learns_the_current_bar_but_not_the_next():
    rng = np.random.default_rng(8)
    dates, names = _dates(70), _names(10)
    tensor = _tensor(names, dates, seed=9)
    # Channel 0 of every step as (sessions, names, 27).
    z = tensor.seq[..., 0].astype(np.float64).transpose(1, 0, 2)
    noise = 3 * rng.normal(size=(70, 10, SLOTS))
    settings = _settings(
        grid=({"lr": 3e-3, "dropout": 0.0, "width": 16},),
        max_epochs=30,
        patience=5,
        batch=32,
        max_folds=1,
        min_train=40,
        validation=12,
        gap=2,
        refit=30,
    )
    scores, spread = {}, {}
    for name, offset in (("current", 1), ("next", 2)):
        labels = 30 * z[:, :, offset : offset + SLOTS] + noise
        data = _ti_data(dates, names, labels)
        forecast = nn3.run_seq(data, tensor, settings)
        test = np.isfinite(forecast.yhat)
        scores[name] = io.selection_score(
            io.TI, forecast.yhat[test], data.y[test], data.dates[test]
        )
        spread[name] = forecast.yhat[test].std() / data.y[test].std()
    assert scores["current"] > 0.5, scores
    assert abs(scores["next"]) < 0.1, scores
    # Forecasts come back in bp: the learned one spans the labels' own range.
    assert 0.7 < spread["current"] < 1.3, spread


# T-S1: a label that depends on a daily column is learned out of sample
# through the daily branch, with the sixty-session windows in place.
def test_seq_s1_learns_a_planted_daily_signal():
    dates, names = _dates(90), _names(16)
    tensor = _tensor(names, dates, seed=11)
    data = _s1_data(dates, names, weight=2.0, seed=12)
    settings = _settings(
        grid=({"lr": 3e-3, "dropout": 0.0, "width": 8},),
        max_epochs=25,
        patience=5,
        batch=64,
        max_folds=1,
        min_train=50,
        validation=16,
        gap=2,
        refit=40,
    )
    forecast = nn3.run_seq(data, tensor, settings)
    test = np.isfinite(forecast.yhat)
    assert test.sum() == 40 * 16
    ic = io.selection_score(io.S1, forecast.yhat[test], data.y[test], data.dates[test])
    assert ic > 0.3, ic
    assert forecast.yhat_configs.shape == (len(data), 1)


# A T-S1 dataset whose label is WHICH session of the window holds a spike.
# Each name's rows are sixty sessions apart, so no two windows share a
# session, and every window's sequence is zero but for one spike session
# (the return channel at +4 on all its steps) at position 10 or 50 - both
# far from the window's first and last 63 steps. The label is 1 for
# position 10; the daily columns are noise. Five names per date. (A zero
# background, because the robust z would scale any noise back to unit size,
# and a noisy background lets 530 rows be memorized instead of learned.)
def _position_data(seed=40):
    rng = np.random.default_rng(seed)
    names_n, sessions_n = 300, 300
    names = np.array([f"P{i:03d}" for i in range(names_n)])
    dates = _dates(sessions_n)
    seq = np.zeros((names_n, sessions_n, STEPS, CHANNELS), dtype=np.float16)
    seq[:, :, 0, -1] = 1
    pairs = sorted(
        (s, n) for n in range(names_n) for s in range(59 + n % 60, sessions_n, 60)
    )
    at = np.array([s for s, _ in pairs])
    who = np.array([n for _, n in pairs])
    early = rng.random(len(pairs)) < 0.5
    seq[who, at - 59 + np.where(early, 10, 50), :, 0] = 4.0
    valid = np.ones((names_n, sessions_n), dtype=bool)
    r = early + 0.01 * rng.normal(size=len(pairs))
    data = io.Stage3Data(
        kind=io.S1,
        dates=dates[at],
        tickers=names[who],
        slot=np.zeros(len(pairs), dtype=np.int8),
        x=rng.normal(size=(len(pairs), 3)).astype(np.float32),
        feature_names=("d_a", "d_b", "i_c"),
        y=io.rank_gauss(r, dates[at]).astype(np.float32),
        extra={"r": r.astype(np.float32)},
    )
    return data, io.SeqTensor(names, dates, seq, valid)


class _NoSessionPosition(nn3.SeqNet):
    """The sequence model with its session-position embedding zeroed and frozen."""

    # Build the network, then zero and freeze its session-position table.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        torch.nn.init.zeros_(self.session_position.weight)
        self.session_position.weight.requires_grad_(False)


# T-S1: a label that depends on which session of the window a spike fell in
# (position 10 or 50, far outside the last 63 steps) is learned out of
# sample with the session-position embedding, and not at all without it.
def test_seq_s1_learns_which_session_a_spike_fell_in_only_with_the_embedding(
    monkeypatch,
):
    data, tensor = _position_data()
    settings = _settings(
        grid=({"lr": 1e-2, "dropout": 0.0, "width": 8},),
        max_epochs=20,
        patience=6,
        batch=32,
        max_folds=1,
        min_train=150,
        validation=40,
        gap=2,
        refit=91,
    )
    scores = {}
    for name, model in (("with", nn3.SeqNet), ("without", _NoSessionPosition)):
        monkeypatch.setattr(nn3, "SeqNet", model)
        forecast = nn3.run_seq(data, tensor, settings)
        test = np.isfinite(forecast.yhat)
        assert test.sum() == 91 * 5
        scores[name] = io.selection_score(
            io.S1, forecast.yhat[test], data.y[test], data.dates[test]
        )
    assert scores["with"] > 0.3, scores
    assert abs(scores["without"]) < 0.15, scores


# No label outside a fold's fit part and validation block reaches its
# forecasts: changing every label in the gaps and from the test block on
# leaves the fold's forecasts identical (sequence model and chart CNN).
def test_labels_outside_fit_and_validation_never_move_a_forecast():
    rng = np.random.default_rng(13)
    dates, names = _dates(50), _names(6)
    tensor = _tensor(names, dates, seed=14)
    labels = 40 * rng.normal(size=(50, 6, SLOTS))
    settings = _settings(grid=ONE, max_folds=1, **SMALL_TI)
    data = _ti_data(dates, names, labels)
    base = nn3.run_seq(data, tensor, settings)
    hidden = _in_sessions(data, 16, 18) | _in_sessions(data, 28, 50)
    y = data.y.copy()
    y[hidden] = 1e4 * rng.normal(size=int(hidden.sum()))
    changed = io.Stage3Data(
        data.kind, data.dates, data.tickers, data.slot, data.x, data.feature_names, y
    )
    np.testing.assert_array_equal(
        nn3.run_seq(changed, tensor, settings).yhat, base.yhat
    )

    bar_dates = _dates(60, start="2020-12-25")
    bars = _bars(bar_dates, names, seed=15)
    s1 = _s1_data(dates, names, seed=16)
    cnn = _settings(grid=({"lr": 1e-3},), max_folds=1, max_epochs=2, **SMALL_TI)
    before = nn3.run_cnn(s1, bars, io.CNN_I5, cnn)
    r = s1.extra["r"].copy()
    far = _in_sessions(s1, 16, 18) | _in_sessions(s1, 28, 50)
    r[far] = rng.normal(size=int(far.sum()))
    moved = io.Stage3Data(
        s1.kind,
        s1.dates,
        s1.tickers,
        s1.slot,
        s1.x,
        s1.feature_names,
        s1.y,
        extra={"r": r},
    )
    np.testing.assert_array_equal(
        nn3.run_cnn(moved, bars, io.CNN_I5, cnn).yhat, before.yhat
    )


# A row whose ticker or date the tensor lacks is never trained on, gets no
# forecast and is counted; invalid cells are zeros whatever the tensor holds.
def test_rows_off_the_tensor_get_no_forecast_and_invalid_cells_are_ignored():
    rng = np.random.default_rng(17)
    dates = _dates(45)
    names = np.array(["AAA", "BBB", "CCC", "ZZZ"])
    tensor_dates = np.delete(dates, 40)
    invalid = [(0, 35), (1, 36)]
    tensor = _tensor(names[:3], tensor_dates, seed=18, invalid=invalid)
    data = _ti_data(dates, names, 40 * rng.normal(size=(45, 4, SLOTS)))
    settings = _settings(grid=ONE, max_folds=1, **SMALL_TI)
    forecast = nn3.run_seq(data, tensor, settings)
    counts = forecast.meta["inputs"]
    assert counts["rows_no_ticker"] == 45 * SLOTS
    assert counts["rows_no_session"] == 3 * SLOTS
    assert counts["rows_without_window"] == 45 * SLOTS + 3 * SLOTS
    assert counts["rows_own_session_invalid"] == 2 * SLOTS
    off = (data.tickers == "ZZZ") | (data.dates == dates[40])
    assert np.isnan(forecast.yhat[off]).all()
    assert (forecast.fold[off] == -1).all()
    assert np.isfinite(forecast.yhat[~off & _in_sessions(data, 30, 45)]).all()
    garbage = tensor.seq.copy()
    for n, s in invalid:
        garbage[n, s] = rng.normal(size=(STEPS, CHANNELS)) * 100
    noisy = io.SeqTensor(tensor.tickers, tensor.sessions, garbage, tensor.valid)
    np.testing.assert_array_equal(
        nn3.run_seq(data, noisy, settings).yhat, forecast.yhat
    )


# ---------------------------------------------------------------------------
# The chart CNN's walk-forward
# ---------------------------------------------------------------------------


# The I5 CNN learns a pattern drawn on the row's own last day (a volume
# spike on day t decides the label), forecasts probabilities only on test
# rows, averages its seeds, and repeats exactly.
def test_cnn_i5_learns_the_last_day_and_repeats_exactly():
    rng = np.random.default_rng(19)
    bar_dates, names = _dates(90), _names(12)
    spike = rng.random(size=(90, 12)) < 0.5
    volume = rng.uniform(0.8, 1.2, size=(90, 12)) * 1e6 * np.where(spike, 3.0, 1.0)
    bars = _bars(bar_dates, names, seed=20, volume=volume)
    dates = bar_dates[10:]
    r = spike[10:].astype(float) + 0.1 * rng.normal(size=(80, 12))
    data = _s1_data(dates, names, r=r)
    settings = _settings(
        grid=({"lr": 1e-3},),
        seeds=(0, 1),
        max_epochs=12,
        patience=3,
        batch=32,
        max_folds=1,
        min_train=40,
        validation=10,
        gap=2,
        refit=40,
    )
    forecast = nn3.run_cnn(data, bars, io.CNN_I5, settings)
    test = _in_sessions(data, 40, 80)
    assert np.isfinite(forecast.yhat[test]).all()
    assert np.isnan(forecast.yhat[~test]).all()
    assert ((forecast.yhat_seeds[test] > 0) & (forecast.yhat_seeds[test] < 1)).all()
    np.testing.assert_allclose(
        forecast.yhat, forecast.yhat_seeds.mean(axis=1), rtol=1e-6
    )
    assert forecast.yhat_configs is None
    ic = io.selection_score(io.S1, forecast.yhat[test], data.y[test], data.dates[test])
    assert ic > 0.3, ic
    assert forecast.meta["inputs"]["images"] == len(data)
    small = _settings(
        grid=({"lr": 1e-3},),
        seeds=(0, 1),
        max_epochs=2,
        max_folds=1,
        min_train=40,
        validation=10,
        gap=2,
        refit=40,
    )
    once = nn3.run_cnn(data, bars, io.CNN_I5, small)
    twice = nn3.run_cnn(data, bars, io.CNN_I5, small)
    np.testing.assert_array_equal(once.yhat_seeds, twice.yhat_seeds)


# The I20 CNN runs the walk-forward end to end on 64 x 60 images.
def test_cnn_i20_walk_forward_runs_end_to_end():
    bar_dates, names = _dates(80), _names(4)
    bars = _bars(bar_dates, names, seed=21)
    dates = bar_dates[40:]
    data = _s1_data(dates, names, seed=22)
    settings = _settings(
        grid=({"lr": 1e-3},), max_epochs=1, max_folds=1, batch=32, **SMALL_TI
    )
    forecast = nn3.run_cnn(data, bars, io.CNN_I20, settings)
    test = _in_sessions(data, 30, 40)
    assert np.isfinite(forecast.yhat[test]).all()
    assert np.isnan(forecast.yhat[~test]).all()
    assert forecast.meta["architecture"]["flattened"] == 46_080


# A CPU run never touches a GPU, even where one exists: torch's Adam asks for
# the current CUDA stream on every step when an accelerator is present,
# which creates a CUDA context (on the Spark, on the GPU the LLM server
# uses). The machine is simulated - the accelerator query reports cuda and
# the stream query fails the test - so no GPU is touched here either.
def test_cpu_training_never_asks_the_gpu_for_a_stream(monkeypatch):
    # Report a CUDA accelerator, as torch does on the Spark and the RTX box.
    def cuda_present(check_available=False):
        return torch.device("cuda")

    # Fail the test if anything asks for a CUDA stream.
    def refuse(*args, **kwargs):
        raise AssertionError("a CPU run asked for the current CUDA stream")

    monkeypatch.setattr(torch.accelerator, "current_accelerator", cuda_present)
    monkeypatch.setattr(torch.accelerator, "current_stream", refuse)
    rng = np.random.default_rng(25)
    dates, names = _dates(40), _names(3)
    data = _ti_data(dates, names, 40 * rng.normal(size=(40, 3, SLOTS)))
    nn3.run_seq(
        data, _tensor(names, dates), _settings(grid=ONE, max_folds=1, **SMALL_TI)
    )
    bars = _bars(_dates(50, start="2020-12-25"), names)
    cnn = _settings(grid=({"lr": 1e-3},), max_epochs=1, max_folds=1, **SMALL_TI)
    nn3.run_cnn(_s1_data(dates, names), bars, io.CNN_I5, cnn)
    assert not torch.cuda.is_initialized()


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


# The command line trains the registered grid and seeds (cut to one fold and
# one epoch) and writes a forecast whose meta names the inputs and the cut.
def test_cli_trains_the_registered_grid_and_writes_the_forecast(tmp_path, capsys):
    rng = np.random.default_rng(23)
    dates, names = _dates(505), np.array(["AAA", "BBB"])
    tensor = _tensor(names, dates, seed=24)
    data = _ti_data(dates, names, 40 * rng.normal(size=(505, 2, SLOTS)))
    data_path = io.save_data(tmp_path / "ti.npz", data)
    seq_path = io.save_seq(tmp_path / "seq.npz", tensor)
    out = tmp_path / "forecast.npz"
    argv = [
        "--family",
        "seq",
        "--kind",
        "ti",
        "--data",
        str(data_path),
        "--seq",
        str(seq_path),
        "--out",
        str(out),
        "--device",
        "cpu",
        "--max-folds",
        "1",
        "--max-epochs",
        "1",
    ]
    assert cli.main(argv) == 0
    printed = capsys.readouterr().out
    assert "fold 1/1" in printed
    forecast = io.load_forecast(out)
    assert forecast.family == io.SEQ
    assert forecast.kind == io.TI
    assert forecast.yhat_seeds.shape == (len(data), len(io.SEEDS))
    assert forecast.yhat_configs.shape == (len(data), len(io.SEQ_GRID))
    assert np.isfinite(forecast.yhat).sum() == 5 * 2 * SLOTS
    meta = forecast.meta
    assert meta["registered"] is False
    assert meta["settings"]["max_epochs"] == 1
    assert meta["settings"]["folds_run"] == 1
    assert meta["command"] == argv
    assert [f["path"] for f in meta["input_files"]] == [str(data_path), str(seq_path)]
    assert all(len(f["sha256"]) == 64 for f in meta["input_files"])
    assert len(meta["folds"][0]["configs"]) == len(io.SEQ_GRID)


# The command line refuses a family that does not answer the question and a
# run missing its inputs.
def test_cli_refuses_a_run_it_cannot_describe(tmp_path):
    common = ["--data", str(tmp_path / "d.npz"), "--out", str(tmp_path / "f.npz")]
    with pytest.raises(SystemExit):
        cli.main(["--family", "cnn_i5", "--kind", "ti", "--ohlcv", "o.npz", *common])
    with pytest.raises(SystemExit):
        cli.main(["--family", "seq", "--kind", "ti", *common])
    with pytest.raises(SystemExit):
        cli.main(["--family", "cnn_i20", "--kind", "s1", *common])
