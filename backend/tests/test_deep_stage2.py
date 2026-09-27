"""Stage 2 of the deep sequence plan builds the rows the plan describes,
sees nothing after the close of t, keeps a 20-session purge, defines the
horizon targets as written, and reaches the plan's verdict from the
decision test alone.

Synthetic cubes and a synthetic desk report only. The cubes come from the
stage-1 fixtures (`test_deep_intraday._book`, weekday calendar); the
report is built here with prices equal to the cubes' session closes so the
20-session targets can be checked against the bars. The torch parts are
skipped where torch is absent.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from backend.market import deep_intraday as stage1
from backend.market import deep_stage2 as s2
from backend.market.deep_intraday import Forecast
from backend.market.session_anatomy import bar_returns
from backend.market.sip_cube import SessionCube
from backend.tests.test_deep_intraday import (
    BAR_SD,
    CAL,
    SLOTS,
    _book,
    _cube_from_returns,
    _dates,
)

# The short bar window the tests use where the plan's sixty would only
# cost time (the row rule and the models are constant-agnostic).
K = 8
A_PLUS, A, B, C = 3, 2, 1, 0


# A synthetic desk report over the cubes' sessions: adjusted close equal
# to each name's session close (the benchmark's too when its cube exists),
# the given (T, names) grades, two analysts' stances, a regime whose
# exposure alternates so the regime scalars vary.
def _report(
    cubes: dict[str, SessionCube],
    names: tuple[str, ...],
    grades: np.ndarray,
    stances: dict[str, np.ndarray] | None = None,
    benchmark: str = "SPY",
):
    from backend.agents.trading.desk import grading, regime
    from backend.agents.trading.desk.desk import DeskReport
    from backend.agents.trading.desk.opinions import Opinion
    from backend.market.panel import Panel
    from backend.market.universe import AI_COMPUTE

    dates = cubes[names[0]].dates
    tickers = (*names, benchmark)
    t, n = len(dates), len(tickers)
    close = np.column_stack(
        [cubes[k].close[:, -1] if k in cubes else np.full(t, 100.0) for k in tickers]
    )
    panel = Panel(
        dates=dates,
        tickers=tickers,
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=close,
        themes={k: (AI_COMPUTE,) for k in names},
        benchmark=benchmark,
    )
    full = np.full((t, n), A, dtype=int)
    full[:, : len(names)] = grades
    if stances is None:
        rng = np.random.default_rng(len(names))
        stances = {
            "fundamental": rng.integers(-1, 2, size=(t, n)).astype(float),
            "technical": rng.integers(-1, 2, size=(t, n)).astype(float),
        }
    graded = grading.Graded(full, full.astype(float), stances, full.astype(float))
    states = [
        regime.RegimeState(
            0,
            0,
            0.5,
            0,
            0,
            0,
            "ai" if i % 3 else "software",
            0.1,
            -0.05,
            1.0,
            1.0 if i % 2 else 0.75,
            (),
            0.0,
            bool(i % 5 == 0),
        )
        for i in range(t)
    ]
    view = regime.RegimeView(states, Opinion("rotation", np.full((t, n), np.nan)))
    return DeskReport(
        panel, {k: "ai" for k in names}, {}, view, graded, graded.as_scores(), []
    )


# A book of `names` names plus the given benchmarks (independent bars),
# the mask, and a report with every name graded A except where `grades`
# says otherwise.
def _world(
    kind: str = "noise",
    names: int = 3,
    n: int = 120,
    seed: int = 0,
    benchmarks: tuple[str, ...] = ("SPY", "QQQ"),
    grades: np.ndarray | None = None,
):
    cubes, mask = _book(kind, names=names, n=n, seed=seed)
    rng = np.random.default_rng(seed + 1000)
    dates = cubes["N00"].dates
    for b in benchmarks:
        cubes[b] = _cube_from_returns(
            b, dates, rng.normal(0.0, BAR_SD, size=(n, SLOTS)), rng
        )
    book = tuple(sorted(t for t in cubes if t not in benchmarks))
    if grades is None:
        grades = np.full((n, len(book)), A, dtype=int)
    mask = {t: dates for t in book}
    return cubes, mask, _report(cubes, book, grades), book


# The dataset's rows follow the plan's rule and carry what the plan says:
# one row per graded member (name, t) with K sessions of bars behind it
# and a complete next session; the market channels are the benchmarks'
# bar returns on the same sessions, in order, and a benchmark the store
# lacks is left out; the scalars are the fixed ones then the stances; the
# grade one-hot, the band z, the breadth and the horizon targets equal
# the hand computation from the report; the last HORIZON sessions have no
# horizon targets.
def test_dataset_shape_and_inputs():
    from backend.agents.trading.desk import entry

    grades = np.full((120, 3), A, dtype=int)
    grades[:, 1] = B
    grades[::2, 1] = A_PLUS
    grades[50:60, 0] = C
    cubes, mask, report, book = _world(n=120, grades=grades)
    ds = s2.dataset(cubes, mask, report, ("SPY", "QQQ", "SMH"), CAL, k=K)
    first_row = stage1.TRAILING - 1
    per_name = 120 - first_row - 1
    assert len(ds) == 3 * per_name
    assert ds.benchmarks == ("SPY", "QQQ")  # SMH has no cube here
    assert ds.x_seq.shape == (len(ds), K * SLOTS, 5)
    assert ds.x_seq.dtype == np.float32
    assert ds.channels == (*stage1.CHANNELS, "SPY_bar_return", "QQQ_bar_return")
    assert ds.scalar_names == (
        *s2.FIXED_SCALARS,
        "stance_fundamental",
        "stance_technical",
    )
    assert ds.x_scalar.shape == (len(ds), len(ds.scalar_names))
    assert ds.flat().shape == (len(ds), K * SLOTS * 5 + len(ds.scalar_names))
    assert np.isfinite(ds.flat()).all()
    assert ds.benchmark_fill == 0
    assert ds.k == K
    assert ds.seq_len == K * SLOTS
    dates = cubes["N00"].dates
    for name in book:
        rows = ds.tickers == name
        assert ds.dates[rows][0] == dates[first_row]
        assert ds.dates[rows][-1] == dates[-2]
    # The name's own channels are stage 1's; the market channels are the
    # benchmarks' bar returns on the same sessions.
    t = 40
    row = np.nonzero((ds.tickers == "N01") & (ds.dates == dates[t]))[0][0]
    np.testing.assert_allclose(
        ds.x_seq[row, -SLOTS:, 0], bar_returns(cubes["N01"])[t], rtol=1e-5, atol=1e-7
    )
    np.testing.assert_allclose(
        ds.x_seq[row, :, 3],
        bar_returns(cubes["SPY"])[t - K + 1 : t + 1].reshape(-1),
        rtol=1e-5,
        atol=1e-7,
    )
    np.testing.assert_allclose(
        ds.x_seq[row, :SLOTS, 4],
        bar_returns(cubes["QQQ"])[t - K + 1],
        rtol=1e-5,
        atol=1e-7,
    )
    # The scalars: grade one-hot, band z as the live rule computes it,
    # breadth by hand, the regime, the stances.
    col = {name: i for i, name in enumerate(ds.scalar_names)}
    assert ds.grade[row] == A_PLUS  # N01 is A+ on even sessions
    assert ds.x_scalar[row, col["grade_a_plus"]] == 1.0
    assert ds.x_scalar[row, [col["grade_a"], col["grade_b"], col["grade_c"]]].sum() == 0
    z = entry.bollinger_z(report.panel.adj_close)
    assert ds.x_scalar[row, col["band_z"]] == pytest.approx(z[t, 1], abs=1e-9)
    close = report.panel.adj_close
    up = (close[t, :3] > close[t - 1, :3]).mean()
    assert ds.x_scalar[row, col["breadth"]] == pytest.approx(up)
    assert ds.x_scalar[row, col["regime_exposure"]] == (1.0 if t % 2 else 0.75)
    assert ds.x_scalar[row, col["regime_leader_ai"]] == (1.0 if t % 3 else 0.0)
    assert ds.x_scalar[row, col["regime_tightening"]] == (1.0 if t % 5 == 0 else 0.0)
    assert (
        ds.x_scalar[row, col["stance_fundamental"]]
        == report.graded.stances["fundamental"][t, 1]
    )
    # The horizon targets, by hand from the panel.
    h = s2.HORIZON
    path = close[t : t + h + 1, 1]
    assert ds.fwd20[row] == pytest.approx(math.log(path[-1] / path[0]))
    assert ds.y_drawdown20[row] == pytest.approx((path[1:] / path[0]).min() - 1.0)
    r = np.diff(np.log(path))
    assert ds.y_vol20[row] == pytest.approx(math.log((r**2).sum()))
    back = np.diff(np.log(close[t - h : t + 1, 1]))
    assert ds.trailing_vol20[row] == pytest.approx(math.log((back**2).sum()))
    # N01 is B on odd sessions, so from an A+ session it is always
    # downgraded within 20; N00 is A and drops to C at 50..59.
    assert ds.y_downgrade20[row] == 1.0
    odd = np.nonzero((ds.tickers == "N01") & (ds.dates == dates[t + 1]))[0][0]
    assert math.isnan(ds.y_downgrade20[odd])  # below A on t: undefined
    n00 = ds.tickers == "N00"
    n00_dates = ds.dates[n00]
    y = ds.y_downgrade20[n00]
    assert y[n00_dates == dates[29]] == 0.0  # 30..49 all A
    assert y[n00_dates == dates[30]] == 1.0  # session 50 is C
    assert y[n00_dates == dates[49]] == 1.0
    assert np.isnan(y[n00_dates == dates[55]])  # C itself
    assert y[n00_dates == dates[60]] == 0.0
    # The horizon runs past the panel on the last HORIZON sessions.
    late = ds.dates > dates[120 - h - 1]
    assert late.any()
    assert np.isnan(ds.fwd20[late]).all()
    assert np.isnan(ds.y_drawdown20[late]).all()
    assert np.isnan(ds.y_downgrade20[late]).all()
    assert np.isfinite(ds.fwd20[~late]).all()
    # Rank: stage 1's within-date rank of the next session's return.
    np.testing.assert_allclose(
        ds.y_rank, stage1.rank_within(ds.y_return, ds.session_index)
    )
    # The plan's default window: sixty sessions, 1,560 steps, six channels
    # when every benchmark is present.
    cubes["SMH"] = cubes["QQQ"]
    full = s2.dataset(cubes, mask, report, ("SPY", "QQQ", "SMH"), CAL)
    assert full.x_seq.shape[1:] == (60 * SLOTS, 6)
    assert full.k == s2.K_SESSIONS == 60
    assert len(full) == 3 * (120 - 60)


# The window tolerates a hole the size of the slack (early closes are not
# in the cubes) and refuses one beyond it; a name the desk did not grade
# contributes no row; a benchmark session the store lacks is a zero row
# and is counted.
def test_window_slack_desk_join_and_benchmark_fill():
    cubes, mask, report, book = _world(names=2, n=80)
    full = s2.dataset(cubes, mask, report, ("SPY",), CAL, k=K)

    # The cube without the sessions at `holes`.
    def without(cube: SessionCube, holes: list[int]) -> SessionCube:
        keep = ~np.isin(np.arange(len(cube)), holes)
        fields = {
            name: getattr(cube, name)[keep]
            for name in (
                "dates",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "prior_close",
                "auction_open",
                "auction_volume",
            )
        }
        return replace(cube, **fields)

    hole = 50
    holed = dict(cubes)
    holed["N00"] = without(cubes["N00"], [hole])
    ds = s2.dataset(holed, mask, report, ("SPY",), CAL, k=K)
    lost = set(full.dates[full.tickers == "N00"].astype(str)) - set(
        ds.dates[ds.tickers == "N00"].astype(str)
    )
    dates = cubes["N00"].dates
    # Only the hole and the session before it (its next session is gone);
    # the windows spanning the hole are kept, unlike stage 1's.
    assert lost == {str(dates[hole - 1]), str(dates[hole])}
    wide = without(cubes["N00"], list(range(hole, hole + s2.WINDOW_SLACK + 1)))
    holed["N00"] = wide
    ds = s2.dataset(holed, mask, report, ("SPY",), CAL, k=K)
    kept = ds.dates[ds.tickers == "N00"]
    # The first row after the gap needs a window that spans at most
    # k - 1 + slack sessions: k - 1 rows after the gap's end.
    after = wide.dates[wide.dates > dates[hole - 1]]
    assert kept[kept > dates[hole - 1]][0] == after[K - 1]
    # The benchmark with a hole: the missing session is a zero row.
    holed = dict(cubes)
    holed["SPY"] = without(cubes["SPY"], [hole])
    ds = s2.dataset(holed, mask, report, ("SPY",), CAL, k=K)
    assert ds.benchmark_fill == 2  # one session, two names
    row = np.nonzero((ds.tickers == "N01") & (ds.dates == dates[hole]))[0][0]
    assert (ds.x_seq[row, -SLOTS:, 3] == 0).all()
    assert (ds.x_seq[row, -2 * SLOTS : -SLOTS, 3] != 0).any()
    # A name the desk has no column for is dropped.
    extra = dict(cubes)
    extra["ZZZ"] = cubes["N01"]
    ds = s2.dataset(extra, {**mask, "ZZZ": dates}, report, ("SPY",), CAL, k=K)
    assert set(ds.tickers) == set(book)
    # No rows at all.
    empty = s2.dataset({}, {}, report, ("SPY",), CAL, k=K)
    assert len(empty) == 0
    assert empty.x_seq.shape == (0, K * SLOTS, 3)


# Nothing in X looks past the close of t: tampering the bars of every
# session from t + 1 on, the benchmark's bars, the grades, the stances and
# the prices from t + 1 on leaves row t's inputs unchanged and changes its
# targets; a grade path shifted by one session changes the downgrade
# target of exactly the rows the shift touches.
def test_no_lookahead():
    grades = np.full((100, 4), A, dtype=int)
    grades[70:75, 2] = B
    cubes, mask, report, book = _world(names=4, n=100, grades=grades)
    base = s2.dataset(cubes, mask, report, ("SPY", "QQQ"), CAL, k=K)
    t = 50
    dates = cubes["N00"].dates
    rng = np.random.default_rng(7)

    # The cube with every session at index >= `start` replaced by noise.
    def tampered(cube: SessionCube, start: int) -> SessionCube:
        fields = {}
        for name in ("open", "high", "low", "close", "volume", "prior_close"):
            values = getattr(cube, name).copy()
            values[start:] *= np.exp(rng.normal(0.0, 0.3, size=values[start:].shape))
            fields[name] = values
        return replace(cube, **fields)

    later = {k: tampered(c, t + 1) for k, c in cubes.items()}
    new_grades = grades.copy()
    new_grades[t + 1 :] = rng.integers(0, 4, size=new_grades[t + 1 :].shape)
    stances = {k: v.copy() for k, v in report.graded.stances.items()}
    for v in stances.values():
        v[t + 1 :] = rng.integers(-1, 2, size=v[t + 1 :].shape)
    tampered_report = _report(later, book, new_grades, stances)
    after = s2.dataset(later, mask, tampered_report, ("SPY", "QQQ"), CAL, k=K)
    upto = base.dates <= dates[t]
    assert upto.sum() > 0
    np.testing.assert_array_equal(base.tickers[upto], after.tickers[upto])
    np.testing.assert_array_equal(base.x_seq[upto], after.x_seq[upto])
    np.testing.assert_array_equal(base.x_scalar[upto], after.x_scalar[upto])
    np.testing.assert_array_equal(base.grade[upto], after.grade[upto])
    row = upto & (base.dates == dates[t])
    assert not np.array_equal(base.y_return[row], after.y_return[row])
    assert not np.array_equal(base.fwd20[row], after.fwd20[row])
    assert not np.array_equal(base.y_drawdown20[row], after.y_drawdown20[row])
    assert not np.array_equal(base.y_vol20[row], after.y_vol20[row])
    # Row t's downgrade target depends on the grades after t.
    assert np.isnan(after.y_downgrade20[row]).sum() < row.sum() or not np.array_equal(
        base.y_downgrade20[row], after.y_downgrade20[row]
    )
    # Rows after t saw the tampering.
    assert not np.array_equal(base.x_seq[~upto], after.x_seq[~upto])
    # A grade path shifted one session later moves the downgrade target
    # of N02 by one session and nothing else.
    shifted = np.full((100, 4), A, dtype=int)
    shifted[71:76, 2] = B
    moved = s2.dataset(
        cubes, mask, _report(cubes, book, shifted), ("SPY", "QQQ"), CAL, k=K
    )
    n02 = base.tickers == "N02"
    changed = np.nonzero(
        (base.y_downgrade20 != moved.y_downgrade20)
        & ~(np.isnan(base.y_downgrade20) & np.isnan(moved.y_downgrade20))
    )[0]
    assert set(base.tickers[changed]) == {"N02"}
    # Rows that lose the target: 70 (A in both, now sees a B at 71), the
    # first eligible session 50 (its horizon 51..70 held the B at 70 and
    # no longer does), and the ones at the shifted edges.
    changed_dates = set(base.dates[changed].astype(str))
    assert str(dates[50]) in changed_dates
    assert str(dates[70]) in changed_dates
    assert str(dates[75]) in changed_dates
    others = n02 & ~np.isin(np.arange(len(base)), changed)
    np.testing.assert_array_equal(
        base.y_downgrade20[others & (base.dates < dates[49])],
        moved.y_downgrade20[others & (base.dates < dates[49])],
    )


# The horizon targets and the downgrade target on hand-built paths.
def test_targets_on_hand_built_paths():
    h = s2.HORIZON
    close = np.array([100.0 * (1.02**i) for i in range(h + 5)])
    close[3] = 90.0  # a dip in the first horizon
    features = s2.horizon_features(close[:, None], h)
    assert features["fwd"][0, 0] == pytest.approx(math.log(close[h] / close[0]))
    assert features["drawdown"][0, 0] == pytest.approx(90.0 / 100.0 - 1.0)
    assert features["drawdown"][4, 0] == pytest.approx(
        0.02
    )  # never dips: the first step
    r = np.diff(np.log(close))
    assert features["vol"][0, 0] == pytest.approx(math.log((r[:h] ** 2).sum()))
    # Twenty trailing returns need the price twenty sessions back.
    assert features["trailing_vol"][h, 0] == pytest.approx(math.log((r[:h] ** 2).sum()))
    assert np.isnan(features["trailing_vol"][:h, 0]).all()
    assert np.isnan(features["fwd"][-h:, 0]).all()
    assert np.isnan(features["drawdown"][-h:, 0]).all()
    assert np.isnan(features["vol"][-h:, 0]).all()
    assert np.isfinite(features["fwd"][:-h, 0]).all()
    # A missing price inside the horizon makes that horizon's variance NaN
    # and leaves the rest alone.
    holed = np.array([100.0 * (1.01**i) for i in range(h + 15)])
    holed[10] = np.nan
    f2 = s2.horizon_features(holed[:, None], h)
    # The returns of sessions 10 and 11 are missing: every horizon holding
    # either (rows 0..10) is NaN, row 11's (12..31) is not.
    assert np.isnan(f2["vol"][:11, 0]).all()
    assert np.isfinite(f2["vol"][11, 0])
    assert np.isnan(f2["trailing_vol"][h : h + 11, 0]).all()
    assert np.isfinite(f2["trailing_vol"][h + 11, 0])
    assert np.isnan(f2["fwd"][10, 0])
    assert np.isfinite(f2["fwd"][11, 0])
    # A drop to a ratio below one in the forward path is the drawdown even
    # when the endpoint is up.
    path = np.array([100.0] * (h - 1) + [50.0, 120.0] + [120.0] * 4)  # 50 at h - 1
    f3 = s2.horizon_features(path[:, None], h)
    assert f3["drawdown"][0, 0] == pytest.approx(-0.5)
    assert f3["fwd"][0, 0] == pytest.approx(math.log(1.2))
    # The downgrade target: A/A+ rows with a sub-A grade in the next h.
    g = np.full(h + 10, A, dtype=int)
    g[5] = B
    g[8] = A_PLUS
    g[h + 3] = C
    y = s2.downgrade_target(g[:, None], h)[:, 0]
    assert y[0] == 1.0  # 5 is B
    assert y[4] == 1.0
    assert math.isnan(y[5])  # B itself
    assert y[6] == 1.0  # h + 3 is within 7..26
    assert y[8] == 1.0
    assert np.isnan(y[-h:]).all()
    g2 = np.full(h + 10, A_PLUS, dtype=int)
    y2 = s2.downgrade_target(g2[:, None], h)[:, 0]
    assert (y2[:-h] == 0.0).all()
    assert np.isnan(s2.downgrade_target(np.full((h, 1), A), h)).all()


# Walk-forward keeps stage 1's schedule with the stage-2 purge: nothing
# before MIN_TRAIN sessions, a refit every REFIT sessions, the last
# training session PURGE + 1 sessions before the block, every head
# predicted from the same fits, the horizon-less rows still predicted.
def test_walk_forward_schedule_and_purge_20():
    cubes, mask, report, _ = _world(names=3, n=600, seed=3, benchmarks=("SPY",))
    ds = s2.dataset(cubes, mask, report, ("SPY",), CAL, k=K)
    s = len(ds.sessions)
    assert s > stage1.MIN_TRAIN + stage1.REFIT
    assert s2.PURGE == 20 == s2.HORIZON
    forecasts = s2.walk_forward(ds, "ridge")
    assert set(forecasts) == set(s2.TARGETS)
    starts = list(range(stage1.MIN_TRAIN, s, stage1.REFIT))
    for target, forecast in forecasts.items():
        assert forecast.model == "ridge"
        assert forecast.target == target
        before = ds.session_index < stage1.MIN_TRAIN
        assert np.isnan(forecast.values[before]).all()
        assert np.isfinite(forecast.values[~before]).all()
        assert len(forecast.fits) == len(starts)
        for fit, start in zip(forecast.fits, starts, strict=True):
            assert fit["test_start"] == str(ds.sessions[start])
            assert fit["train_through"] == str(ds.sessions[start - s2.PURGE - 1])
            assert fit["n_train"] == int((ds.session_index < start - s2.PURGE).sum())
        first = np.datetime64(forecast.fits[0]["train_through"], "D")
        gap = int(np.busday_count(first, ds.sessions[stage1.MIN_TRAIN], busdaycal=CAL))
        assert gap == s2.PURGE + 1
    # The downgrade head is a probability-like score from a ridge on 0/1;
    # the rows with an undefined target are still scored.
    assert np.isfinite(forecasts["downgrade20"].values[~before]).all()
    with pytest.raises(ValueError, match="unknown model"):
        s2.walk_forward(ds, "forest")
    with pytest.raises(ValueError, match="unknown target"):
        s2.walk_forward(ds, "ridge", ("price",))
    with pytest.raises(ValueError, match="unknown target"):
        s2.target_array(ds, "vol")


# A hand-built dataset for the decision test: dates x names with known
# forward returns and grades; the x arrays are placeholders.
def _hand_dataset(
    fwd: np.ndarray, grades: np.ndarray, start: date = date(2020, 1, 6)
) -> s2.Dataset2:
    t, n = fwd.shape
    sessions = _dates(t, start)
    names = np.array([f"N{j:02d}" for j in range(n)])
    m = t * n
    return s2.Dataset2(
        dates=np.repeat(sessions, n),
        tickers=np.tile(names, t),
        x_seq=np.zeros((m, SLOTS, 3), np.float32),
        x_scalar=np.zeros((m, 1)),
        scalar_names=("gap",),
        y_return=np.zeros(m),
        y_rank=np.full(m, 0.5),
        y_downgrade20=np.zeros(m),
        y_drawdown20=np.zeros(m),
        y_vol20=np.zeros(m),
        trailing_vol20=np.zeros(m),
        fwd20=fwd.reshape(-1),
        grade=grades.reshape(-1),
        sessions=sessions,
        session_index=np.repeat(np.arange(t), n),
        k=1,
        benchmarks=(),
        benchmark_fill=0,
    )


# The decision test on hand-built forecasts: the book is equal weight of
# the A/A+ names, the modified book drops the worst decile (at least one)
# by forecast, both earn the 20-session forward return, the difference is
# per session net of the cost on the extra turnover; the sign convention
# follows `higher_is_worse`; names below A and rows without a forward
# return are not in the book; a date with too few names is skipped.
def test_decision_test_hand_built():
    fwd = np.array(
        [
            [0.10, 0.20, -0.30, 0.00, 0.05],
            [0.10, 0.20, -0.30, 0.00, 0.05],
            [0.02, 0.02, 0.02, 0.02, -0.40],
        ]
    )
    grades = np.full(fwd.shape, A, dtype=int)
    grades[2, 0] = B  # not in the book on the third date
    ds = _hand_dataset(fwd, grades)
    # The oracle: a downgrade probability highest for the worst return.
    score = -fwd.reshape(-1)
    decision = s2.decision_test(ds, score, higher_is_worse=True, cost_bps=10.0)
    assert len(decision.dates) == 3
    np.testing.assert_allclose(decision.names, [5, 5, 4])
    np.testing.assert_allclose(decision.dropped, [1, 1, 1])
    np.testing.assert_allclose(decision.book, [0.01, 0.01, (0.02 * 3 - 0.40) / 4])
    np.testing.assert_allclose(decision.modified, [0.35 / 4, 0.35 / 4, 0.02])
    # Turnover: the first date is all entries for both books (1.0 each,
    # so no extra); the second date repeats both; the third date the book
    # loses N00 (0.2 -> 0.25 x 4: 0.2 + 4 x 0.05 = 0.4) and the modified
    # book goes from {N00, N01, N03, N04} at 0.25 to {N01, N02, N03} at
    # 1/3: N00 out 0.25, N04 out 0.25, N02 in 1/3, N01 and N03 up 1/12
    # each, 1.0 in all; the extra is 0.6.
    expected_extra = (0.25 + 0.25 + 1 / 3 + 2 * (1 / 3 - 0.25)) - 0.4
    np.testing.assert_allclose(decision.extra_turnover, [0.0, 0.0, expected_extra])
    gross = decision.gross()
    np.testing.assert_allclose(
        gross.values, (decision.modified - decision.book) / s2.HORIZON
    )
    net = decision.net()
    np.testing.assert_allclose(
        net.values, gross.values - 10.0 / s2.BP * decision.extra_turnover
    )
    summary = decision.summary()
    assert summary["dates"] == 3
    assert summary["mean_bp"] == pytest.approx(net.mean * s2.BP)
    assert summary["gross_bp"] == pytest.approx(gross.mean * s2.BP)
    assert summary["mean_bp"] < summary["gross_bp"]
    assert summary["book_bp"] == pytest.approx(
        decision.book.mean() / s2.HORIZON * s2.BP
    )
    # A drawdown forecast: the most negative is dropped.
    drawdown_score = fwd.reshape(-1)  # predicted drawdown ~ the return itself
    by_drawdown = s2.decision_test(ds, drawdown_score, higher_is_worse=False)
    np.testing.assert_allclose(by_drawdown.modified, decision.modified)
    # The wrong sign drops the best name instead.
    wrong = s2.decision_test(ds, drawdown_score, higher_is_worse=True)
    assert wrong.modified[0] == pytest.approx((0.10 - 0.30 + 0.0 + 0.05) / 4)
    # A window restricts the dates; a NaN forecast on a date skips it.
    window = ds.dates >= ds.sessions[1]
    assert len(s2.decision_test(ds, score, window=window).dates) == 2
    partial = score.copy()
    partial[:5] = np.nan
    assert len(s2.decision_test(ds, partial).dates) == 2
    # Fewer than MIN_NAMES A/A+ names: the date is skipped.
    few = grades.copy()
    few[0, :3] = C
    assert len(s2.decision_test(_hand_dataset(fwd, few), score).dates) == 2
    # Ties in the forecast break by ticker, so the result is deterministic.
    tied = s2.decision_test(ds, np.zeros(len(ds)))
    assert tied.modified[0] == pytest.approx((0.20 - 0.30 + 0.0 + 0.05) / 4)


# The AUC is the Mann-Whitney probability: one when the positives all
# score higher, zero when lower, one half for a constant score, NaN with
# one class.
def test_auc_and_downgrade_auc():
    label = np.array([0, 0, 1, 1, 0, 1], dtype=float)
    assert s2.auc(label, np.array([0.1, 0.2, 0.8, 0.9, 0.3, 0.7])) == 1.0
    assert s2.auc(label, -np.array([0.1, 0.2, 0.8, 0.9, 0.3, 0.7])) == 0.0
    assert s2.auc(label, np.zeros(6)) == 0.5
    assert s2.auc(label, np.array([0.1, 0.2, 0.15, 0.9, 0.3, 0.7])) == pytest.approx(
        7 / 9
    )
    assert math.isnan(s2.auc(np.zeros(4), np.arange(4.0)))
    assert s2.auc(np.array([0, 1, np.nan]), np.array([0.0, 1.0, 0.5])) == 1.0
    fwd = np.zeros((2, 4))
    ds = _hand_dataset(fwd, np.full((2, 4), A))
    ds = replace(ds, y_downgrade20=np.array([0, 1, 1, 0, np.nan, 1, 0, 0.0]))
    out = s2.downgrade_auc(ds, np.array([0.1, 0.9, 0.8, 0.2, 0.5, 0.7, 0.1, 0.4]))
    assert out == {"auc": 1.0, "n": 7, "positives": 3}


# The ridge end to end on a book with stage 1's planted late-day signal:
# the rank head finds it with the new inputs, the payload carries every
# target on both windows with the metrics the plan names, and the verdict
# is INSUFFICIENT EVIDENCE because no decision test clears the floors
# (the downgrades here are unrelated to the bars). Strict JSON.
def test_ridge_end_to_end_and_insufficient_evidence():
    grades = np.full((620, 6), A, dtype=int)
    rng = np.random.default_rng(5)
    for j in range(6):
        for start in rng.choice(np.arange(30, 600), size=6, replace=False):
            grades[start : start + 5, j] = B
    cubes, mask, report, _ = _world(
        "late_signal", names=6, n=620, seed=7, grades=grades
    )
    ds = s2.dataset(cubes, mask, report, ("SPY", "QQQ"), CAL, k=K)
    forecasts = s2.walk_forward(ds, "ridge")
    ic = stage1.daily_ic(ds, forecasts["rank"])
    assert ic.n > 80
    assert ic.mean > 0.1
    assert ic.t > 3.0
    payload = s2.study(ds, {("ridge", t): f for t, f in forecasts.items()})
    assert payload["study"] == "deep_stage2"
    assert payload["stage"] == 2
    assert payload["plan"] == s2.PLAN
    assert payload["trials"] == 4
    assert payload["trials_total"] == s2.TRIALS == 16
    assert payload["models"] == ["ridge"]
    assert payload["targets"] == list(s2.TARGETS)
    assert payload["constants"]["purge"] == 20
    assert payload["constants"]["k_sessions"] == K
    assert payload["constants"]["channels"] == list(ds.channels)
    assert payload["dataset"]["benchmarks"] == ["SPY", "QQQ"]
    assert payload["dataset"]["downgrade_rows"] > 0
    assert payload["dataset"]["horizon_rows"] == int(np.isfinite(ds.fwd20).sum())
    assert len(payload["results"]) == 2 * 4
    choosing = {
        r["target"]: r for r in payload["results"] if r["window"] == "2016-2023"
    }
    assert choosing["rank"]["ic"]["dates"] == ic.n
    assert choosing["rank"]["portfolio"]["dates"] > 0
    assert choosing["rank"]["portfolio_a"]["dates"] > 0
    assert choosing["rank"]["decision"] is None
    assert 0.0 <= choosing["downgrade20"]["auc"]["auc"] <= 1.0
    assert choosing["downgrade20"]["decision"]["dates"] > 0
    assert choosing["downgrade20"]["ic"] is None
    assert choosing["drawdown20"]["ic"]["dates"] > 0
    assert choosing["drawdown20"]["decision"]["dates"] > 0
    assert choosing["vol20"]["vol_r2"]["n"] > 0
    assert choosing["vol20"]["decision"] is None
    later = [r for r in payload["results"] if r["window"] == "2024-2026"]
    assert all(r["rows"] == 0 for r in later)
    assert payload["verdict"] == stage1.INSUFFICIENT
    detail = "\n".join(payload["verdict_detail"])
    assert "ridge/downgrade20 on 2016-2023: AUC" in detail
    assert "fails the kill criteria" in detail
    assert "ridge/rank on 2016-2023" in detail
    assert "recorded, no decision test" in detail
    assert "trials counted: 4 run of 16 pre-registered" in detail
    json.dumps(payload, allow_nan=False)


# The verdict from hand-built forecasts: an oracle drawdown forecast on a
# book that runs into the later window clears both floors and PASSES,
# naming the pair and not a trade; the same oracle with the later window
# negative, or absent, does not; AUC alone never does.
def test_verdict_from_the_decision_test_alone():
    cubes, mask, report, _ = _world(names=8, n=900, seed=11, benchmarks=("SPY",))
    # Move the sessions so the last year falls in 2024-2026.
    shifted = _dates(900, date(2021, 1, 4))
    cubes = {k: replace(c, dates=shifted) for k, c in cubes.items()}
    mask = {k: shifted for k in mask}
    report = _report(cubes, tuple(sorted(mask)), np.full((900, 8), A, dtype=int))
    ds = s2.dataset(cubes, mask, report, ("SPY",), CAL, k=K)
    assert (ds.dates >= np.datetime64("2024-01-01")).sum() > 0
    scored = ds.session_index >= stage1.MIN_TRAIN
    oracle = np.where(scored, ds.y_drawdown20, np.nan)
    forecast = Forecast("cnn", "drawdown20", oracle)
    payload = s2.study(ds, {("cnn", "drawdown20"): forecast})
    first = next(r for r in payload["results"] if r["window"] == "2016-2023")
    second = next(r for r in payload["results"] if r["window"] == "2024-2026")
    assert first["decision"]["mean_bp"] > s2.DECISION_BP_FLOOR
    assert first["decision"]["t"] > s2.DECISION_T_FLOOR
    assert second["decision"]["mean_bp"] > 0
    assert first["ic"]["mean"] > 0.99
    assert payload["verdict"].startswith(s2.PASSED)
    assert "cnn/drawdown20" in payload["verdict"]
    assert "not a trading verdict" in payload["verdict"]
    assert "passes the kill criteria" in "\n".join(payload["verdict_detail"])
    # The anti-oracle fails; a perfect AUC with a useless decision fails.
    payload = s2.study(
        ds, {("cnn", "drawdown20"): Forecast("cnn", "drawdown20", -oracle)}
    )
    assert payload["verdict"] == stage1.INSUFFICIENT
    # Worse on the later window: the choosing window passes, the verdict
    # does not.
    mixed = oracle.copy()
    late = ds.dates >= np.datetime64("2024-01-01")
    mixed[late] = -oracle[late]
    payload = s2.study(
        ds, {("cnn", "drawdown20"): Forecast("cnn", "drawdown20", mixed)}
    )
    assert payload["verdict"] == stage1.INSUFFICIENT
    first = next(r for r in payload["results"] if r["window"] == "2016-2023")
    assert first["decision"]["t"] > s2.DECISION_T_FLOOR
    # No later window at all: cannot pass.
    payload = s2.study(
        ds,
        {("cnn", "drawdown20"): forecast},
        windows={"2016-2023": (date(2016, 1, 1), date(2024, 1, 1))},
    )
    assert payload["later_window"] is None
    assert payload["verdict"] == stage1.INSUFFICIENT
    # The downgrade oracle with the same sign convention.
    down = np.where(scored & np.isfinite(ds.y_downgrade20), -ds.fwd20, np.nan)
    payload = s2.study(
        ds, {("ridge", "downgrade20"): Forecast("ridge", "downgrade20", down)}
    )
    assert payload["verdict"].startswith(s2.PASSED)
    assert "ridge/downgrade20" in payload["verdict"]
    with pytest.raises(ValueError, match="choosing window"):
        s2.study(ds, {}, choosing="never")


# The dataset round-trips through the export: the sequence as float16
# (within its precision), everything else exactly, the names and the
# constants with it.
def test_export_round_trip(tmp_path):
    cubes, mask, report, _ = _world(names=2, n=60)
    ds = s2.dataset(cubes, mask, report, ("SPY", "QQQ"), CAL, k=K)
    path = s2.save_dataset(tmp_path / "out" / "stage2.npz", ds)
    assert path.exists()
    with np.load(path) as data:
        assert data["x_seq"].dtype == np.float16
    back = s2.load_dataset(path)
    assert back.x_seq.dtype == np.float32
    np.testing.assert_allclose(back.x_seq, ds.x_seq, rtol=1e-3, atol=1e-6)
    for name in s2.DATASET_ARRAYS:
        if name == "x_seq":
            continue
        np.testing.assert_array_equal(getattr(back, name), getattr(ds, name))
    assert back.scalar_names == ds.scalar_names
    assert back.benchmarks == ds.benchmarks
    assert back.k == ds.k
    assert back.benchmark_fill == ds.benchmark_fill
    assert back.dates.dtype == np.dtype("datetime64[D]")
    assert back.tickers.dtype.kind == "U"
    assert back.channels == ds.channels


# The command end to end on a store with synthetic names and a benchmark:
# the export from the store with the desk hook, then training from the
# file elsewhere with no store, the payload under <root>/desk/, the table
# and the verdict in the text; the option validation.
def test_cli_end_to_end(tmp_path, monkeypatch):
    from backend.cli import market_deep_stage2 as cli
    from backend.market.store import MarketStore
    from backend.tests.test_deep_intraday import _exchange_sessions, _write

    monkeypatch.setattr(stage1, "_ANNOUNCED", set())
    store = MarketStore(tmp_path)
    sessions = _exchange_sessions(stage1.MIN_TRAIN + 45)
    names = ("AAA", "BBB", "CCC")
    for i, ticker in enumerate((*names, "SPY")):
        _write(store, ticker, sessions, 30 + i)
    membership = tmp_path / "membership.csv"
    membership.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        + "".join(f"{t},2015-01-02,2015-01-02,,,test,test\n" for t in names),
        encoding="utf-8",
    )
    grades = np.full((len(sessions), 3), A, dtype=int)
    grades[100:110, 1] = B
    calls: list[str] = []

    # The desk hook: a report over the store's cubes.
    def fake_desk(store_):
        from backend.market import sip_cube

        calls.append(str(store_.root))
        cubes = {t: sip_cube.load(store_, t) for t in (*names, "SPY")}
        return _report(cubes, names, grades)

    export = tmp_path / "export" / "stage2.npz"
    common = [
        "--root",
        str(tmp_path),
        "--tickers",
        "AAA,BBB,CCC",
        "--membership",
        str(membership),
        "--device",
        "cpu",
        "--workers",
        "1",
        "--k",
        str(K),
    ]
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            *common,
            "--models",
            "none",
            "--export",
            str(export),
            "--benchmarks",
            "SPY,QQQ",
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    text = out.getvalue()
    assert calls == [str(tmp_path)]
    assert export.exists()
    assert "wrote dataset" in text
    assert "benchmarks without a cube in the store: QQQ" in text
    assert "desk run:" in text
    assert not (tmp_path / "desk" / "deep_stage2.json").exists()
    ds = s2.load_dataset(export)
    assert set(ds.tickers) == set(names)
    assert ds.benchmarks == ("SPY",)
    assert ds.x_seq.shape[1:] == (K * SLOTS, 4)
    # Training from the file, in a directory with no store at all.
    elsewhere = tmp_path / "desktop"
    elsewhere.mkdir()
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(elsewhere),
            "--dataset",
            str(export),
            "--models",
            "ridge",
            "--targets",
            "rank,downgrade20",
            "--device",
            "cpu",
            "--out",
            "from_file.json",
        ]
    )
    assert cli.run(args, out) == 0
    text = out.getvalue()
    target = elsewhere / "desk" / "from_file.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["study"] == "deep_stage2"
    assert payload["models"] == ["ridge"]
    assert payload["targets"] == ["rank", "downgrade20"]
    assert payload["requested"] == {
        "models": ["ridge"],
        "targets": ["rank", "downgrade20"],
        "benchmarks": ["SPY", "QQQ", "SMH"],
    }
    assert payload["dataset"]["benchmarks"] == ["SPY"]  # what the file carries
    assert payload["trials"] == 2
    assert payload["trials_total"] == 16
    assert payload["device"] == "cpu"
    assert payload["dataset_file"] == str(export)
    assert payload["dataset"]["names"] == 3
    assert list(payload["fits"]) == ["ridge/rank", "ridge/downgrade20"]
    assert len(payload["fits"]["ridge/rank"]) == 1
    assert payload["verdict"] in (stage1.INSUFFICIENT,) or payload[
        "verdict"
    ].startswith(s2.PASSED)
    assert "NaN" not in target.read_text(encoding="utf-8")
    assert "dataset from" in text
    assert "ridge fit 1: train through" in text
    assert "dec bp/s" in text
    assert "verdict:" in text
    assert f"wrote {target}" in text
    # --json prints the payload only.
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(elsewhere),
            "--dataset",
            str(export),
            "--models",
            "ridge",
            "--targets",
            "vol20",
            "--device",
            "cpu",
            "--json",
        ]
    )
    assert cli.run(args, out) == 0
    printed = json.loads(out.getvalue())
    assert printed["targets"] == ["vol20"]
    # Option validation.
    assert cli.parse_models("none") == ()
    assert cli.parse_models("ridge,patchtst-pretrained") == (
        "ridge",
        "patchtst-pretrained",
    )
    assert cli.parse_benchmarks("spy, qqq,spy") == ("SPY", "QQQ")
    with pytest.raises(SystemExit, match="--models"):
        cli.parse_models("ridge,forest")
    with pytest.raises(SystemExit, match="--targets"):
        cli.parse_targets("vol")
    # An empty store exits 1.
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path / "empty"),
            "--tickers",
            "AAA",
            "--membership",
            str(membership),
            "--models",
            "ridge",
            "--workers",
            "1",
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 1


# The dispatch names the four families and refuses others; the torch
# families fail at their lazy import where torch is absent, never with
# "unknown model".
def test_dispatch_names():
    assert s2.MODELS == ("ridge", "cnn", "patchtst", "patchtst-pretrained")
    assert s2.TORCH_MODELS == ("cnn", "patchtst", "patchtst-pretrained")
    assert s2.TARGETS == ("rank", "downgrade20", "drawdown20", "vol20")
    assert s2.DECISION_TARGETS == ("downgrade20", "drawdown20")
    assert s2.TRIALS == 16
    assert s2.TARGET_KIND["downgrade20"] == "bce"
    cubes, mask, report, _ = _world(names=2, n=40)
    ds = s2.dataset(cubes, mask, report, ("SPY",), CAL, k=K)
    for name in ("forest", "chronos", "", "Ridge"):
        with pytest.raises(ValueError, match="unknown model"):
            s2.walk_forward(ds, name)
    for name in s2.TORCH_MODELS:
        with contextlib.suppress(ImportError):
            s2.walk_forward(ds, name, device="cpu")


# The multi-head CNN and PatchTST train and predict on a tiny book with
# one epoch, the bce head a probability, the parameter count the network's
# with a four-way head (skipped where torch is absent).
def test_torch_multihead_smoke():
    pytest.importorskip("torch")
    from backend.market import deep_stage2_nn as nn2

    cubes, mask, report, _ = _world(names=3, n=80, seed=21)
    ds = s2.dataset(cubes, mask, report, ("SPY", "QQQ"), CAL, k=K)
    y = np.column_stack([s2.target_array(ds, t) for t in s2.TARGETS])
    kinds = tuple(s2.TARGET_KIND[t] for t in s2.TARGETS)
    for family, config in (
        ("cnn", stage1.CNN_CONFIG),
        ("patchtst", stage1.PATCHTST_CONFIG),
    ):
        predicted, parameters = nn2.fit_predict(
            family,
            ds.x_seq[:120],
            ds.x_scalar[:120],
            y[:120],
            kinds,
            ds.x_seq[120:140],
            ds.x_scalar[120:140],
            {**config, "epochs": 1, "batch": 32},
            device="cpu",
        )
        assert predicted.shape == (20, 4)
        assert np.isfinite(predicted).all()
        assert ((predicted[:, 1] >= 0) & (predicted[:, 1] <= 1)).all()
        model = nn2.build_network(
            family, 5, ds.x_scalar.shape[1], ds.seq_len, config, 4
        )
        assert parameters == nn2.parameter_count(model)
        assert model.heads.out_features == 4
    with pytest.raises(ValueError, match="loss kind"):
        nn2.fit_predict(
            "cnn",
            ds.x_seq[:10],
            ds.x_scalar[:10],
            y[:10, :1],
            ("huber",),
            ds.x_seq[:2],
            ds.x_scalar[:2],
            stage1.CNN_CONFIG,
            device="cpu",
        )
    with pytest.raises(ValueError, match="unknown family"):
        nn2.build_network("lstm", 5, 3, ds.seq_len, stage1.CNN_CONFIG, 4)


# Masked-patch pretraining runs on the training rows alone and the frozen
# encoder embeds train and test rows to d_model; the stage-2 walk-forward
# of the pretrained arm is the ridge on that embedding (skipped where
# torch is absent).
def test_pretrain_embed_smoke(monkeypatch):
    pytest.importorskip("torch")
    from backend.market import deep_stage2_nn as nn2

    cubes, mask, report, _ = _world(names=2, n=70, seed=22)
    ds = s2.dataset(cubes, mask, report, ("SPY",), CAL, k=K)
    config = {**stage1.PATCHTST_CONFIG, "batch": 16}
    pre = {**s2.PRETRAIN_CONFIG, "epochs": 1}
    emb_train, emb_test, parameters = nn2.pretrain_embed(
        ds.x_seq[:60],
        ds.x_scalar[:60],
        ds.x_seq[60:70],
        ds.x_scalar[60:70],
        config,
        pre,
        device="cpu",
    )
    assert emb_train.shape == (60, config["d_model"])
    assert emb_test.shape == (10, config["d_model"])
    assert np.isfinite(emb_train).all()
    assert np.isfinite(emb_test).all()
    assert parameters > 60_000
    # The walk-forward dispatch reaches it: shrink the schedule.
    monkeypatch.setattr(s2, "MIN_TRAIN", 40)
    monkeypatch.setattr(s2, "REFIT", 10)
    monkeypatch.setattr(s2, "PRETRAIN_CONFIG", pre)
    monkeypatch.setattr(stage1, "PATCHTST_CONFIG", config)
    monkeypatch.setattr(
        stage1, "CNN_CONFIG", {**stage1.CNN_CONFIG, "epochs": 1, "batch": 16}
    )
    for model in ("patchtst-pretrained", "cnn"):
        forecasts = s2.walk_forward(ds, model, device="cpu")
        scored = ds.session_index >= 40
        for forecast in forecasts.values():
            assert np.isfinite(forecast.values[scored]).all()
            assert np.isnan(forecast.values[~scored]).all()
            assert forecast.parameters
            assert forecast.parameters > 1000
