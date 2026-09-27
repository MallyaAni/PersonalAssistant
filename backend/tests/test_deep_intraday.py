"""Stage 1 of the deep-intraday plan finds a signal exactly where one is
planted, sees nothing of the future, keeps the walk-forward schedule the
plan fixes, and reaches the plan's verdict on noise.

Synthetic cubes only. Each test builds a small book of names whose bars
are independent draws unless the test plants something: a next-session
return that depends on the last session's late-day bars (the ridge must
find it, and the top-quintile portfolio must beat the hurdle), clustered
volatility (the volatility head must beat trailing volatility), and a
return whose size but not sign is predictable (the volatility control must
remove the IC it creates). The CNN and PatchTST smoke tests are skipped
where torch is absent, the Chronos one where chronos is; the device
resolution, the embedding cache fingerprint and the chronos feature join
are tested without either.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from backend.market import deep_intraday as di
from backend.market.sip_cube import SessionCube

# Weekdays only: the synthetic calendar has no holidays, so every row of a
# cube is the next session after the one before.
CAL = np.busdaycalendar()
SLOTS = di.SLOTS
BAR_SD = 0.004


# `n` consecutive weekday sessions from `start`.
def _dates(n: int, start: date = date(2016, 1, 4)) -> np.ndarray:
    first = np.datetime64(start, "D")
    return np.busday_offset(first, np.arange(n), roll="forward", busdaycal=CAL)


# A cube from per-session, per-bar log returns (n, 26): prices walk the
# bars from an open that gaps a little on the prior close; the high and
# low bracket each bar; volume is lognormal. `volume_shape` (26,) tilts the
# volume profile when given.
def _cube_from_returns(
    ticker: str,
    dates: np.ndarray,
    returns: np.ndarray,
    rng: np.random.Generator,
    gap_sd: float = 0.002,
) -> SessionCube:
    n = len(dates)
    opens = np.empty((n, SLOTS))
    closes = np.empty((n, SLOTS))
    prior = np.empty(n)
    price = 100.0
    for i in range(n):
        prior[i] = price
        open0 = price * math.exp(rng.normal(0.0, gap_sd))
        path = open0 * np.exp(np.cumsum(returns[i]))
        opens[i] = np.concatenate([[open0], path[:-1]])
        closes[i] = path
        price = path[-1]
    wick = np.abs(rng.normal(0.0, 0.0005, size=(n, SLOTS)))
    high = np.maximum(opens, closes) * (1.0 + wick)
    low = np.minimum(opens, closes) * (1.0 - wick)
    volume = rng.lognormal(10.0, 0.5, size=(n, SLOTS))
    return SessionCube(
        ticker=ticker,
        dates=dates,
        open=opens,
        high=high,
        low=low,
        close=closes,
        volume=volume,
        prior_close=prior,
        excluded={"early_close": 0, "incomplete": 0, "no_prior_close": 0},
        auction_open=closes[:, -1].copy(),
        auction_volume=np.full(n, 1e5),
    )


# A book of `names` names over `n` sessions. `kind` plants the structure:
# "noise" - independent bars; "late_signal" - the next session's return
# carries `coef` times the sum of the last four bars of the session before;
# "vol_cluster" - each name's bar volatility follows a persistent log-AR(1);
# "vol_drift" - a persistent per-name volatility level and a per-bar drift
# proportional to it, so the return's size and mean are predictable but its
# sign, given the volatility, is not.
def _book(
    kind: str, names: int = 12, n: int = 950, seed: int = 0, coef: float = 1.0
) -> tuple[dict[str, SessionCube], dict[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    dates = _dates(n)
    cubes = {}
    for j in range(names):
        ticker = f"N{j:02d}"
        if kind == "vol_cluster":
            log_sigma = np.empty(n)
            log_sigma[0] = math.log(BAR_SD)
            for i in range(1, n):
                log_sigma[i] = (
                    math.log(BAR_SD) * 0.1
                    + 0.9 * log_sigma[i - 1]
                    + rng.normal(0.0, 0.25)
                )
            sigma = np.exp(log_sigma)
            returns = rng.normal(0.0, 1.0, size=(n, SLOTS)) * sigma[:, None]
        elif kind == "vol_drift":
            level = BAR_SD * (0.5 + 1.5 * j / max(1, names - 1))
            sigma = level * np.exp(rng.normal(0.0, 0.1, size=n))
            returns = rng.normal(0.0, 1.0, size=(n, SLOTS)) * sigma[:, None]
            returns += 0.15 * sigma[:, None]
        else:
            returns = rng.normal(0.0, BAR_SD, size=(n, SLOTS))
            if kind == "late_signal":
                late = returns[:-1, -4:].sum(axis=1)
                returns[1:] += (coef * late / SLOTS)[:, None]
        cubes[ticker] = _cube_from_returns(ticker, dates, returns, rng)
    mask = {t: dates for t in cubes}
    return cubes, mask


# The dataset's rows follow the plan's rule: one per member (name, t) with
# K consecutive complete sessions ending at t, full trailing scalars and a
# complete next session; shapes as declared; the last row of each name is
# the session before the cube's last.
def test_dataset_shape_and_row_rule():
    cubes, mask = _book("noise", names=3, n=60, seed=1)
    ds = di.dataset(cubes, mask, CAL)
    first_row = di.TRAILING - 1
    per_name = 60 - first_row - 1
    assert len(ds) == 3 * per_name
    assert ds.x_seq.shape == (len(ds), di.SEQ_LEN, len(di.CHANNELS))
    assert ds.x_scalar.shape == (len(ds), len(di.SCALARS))
    assert ds.x_seq.dtype == np.float32
    dates = cubes["N00"].dates
    for name in cubes:
        rows = ds.tickers == name
        assert ds.dates[rows][0] == dates[first_row]
        assert ds.dates[rows][-1] == dates[-2]
    assert np.isfinite(ds.flat()).all()
    assert ds.flat().shape == (len(ds), di.SEQ_LEN * len(di.CHANNELS) + len(di.SCALARS))
    # Sorted by session then ticker; the bounds slice sessions.
    assert (np.diff(ds.session_index) >= 0).all()
    bounds = ds.bounds()
    assert bounds[0] == 0
    assert bounds[-1] == len(ds)
    assert all(bounds[s + 1] - bounds[s] == 3 for s in range(len(ds.sessions)))
    # The last session's volume shares sum to one; the sequence ends at t.
    cube = cubes["N00"]
    row = np.nonzero((ds.tickers == "N00") & (ds.dates == dates[30]))[0][0]
    shares = ds.x_seq[row, -SLOTS:, 1]
    assert abs(shares.sum() - 1.0) < 1e-5
    np.testing.assert_allclose(
        ds.x_seq[row, -SLOTS:, 0],
        np.log(
            cube.close[30] / np.concatenate([[cube.open[30, 0]], cube.close[30, :-1]])
        ),
        rtol=1e-5,
        atol=1e-7,
    )
    # The targets are the next session's.
    assert ds.y_return[row] == pytest.approx(
        math.log(cube.close[31, -1] / cube.open[31, 0])
    )
    # A non-member session contributes no row; a name outside the mask none.
    partial = {"N00": dates[:40], "N01": dates}
    ds2 = di.dataset(cubes, partial, CAL)
    assert set(ds2.tickers) == {"N00", "N01"}
    assert (ds.dates[ds.tickers == "N00"] < dates[40]).sum() == (
        ds2.tickers == "N00"
    ).sum()


# A gap in the cube (a missing session) drops the rows whose K-window or
# next session spans it, and nothing else.
def test_dataset_requires_consecutive_sessions():
    cubes, mask = _book("noise", names=1, n=60, seed=2)
    cube = cubes["N00"]
    full = di.dataset(cubes, mask, CAL)
    hole = 40
    keep = np.arange(60) != hole
    holed = replace(
        cube,
        dates=cube.dates[keep],
        open=cube.open[keep],
        high=cube.high[keep],
        low=cube.low[keep],
        close=cube.close[keep],
        volume=cube.volume[keep],
        prior_close=cube.prior_close[keep],
        auction_open=cube.auction_open[keep],
        auction_volume=cube.auction_volume[keep],
    )
    ds = di.dataset({"N00": holed}, mask, CAL)
    lost = set(full.dates.astype(str)) - set(ds.dates.astype(str))
    # Row hole-1 loses its next session; rows hole+1 .. hole+K-1 lack a
    # consecutive window; the hole itself is gone.
    expected = {str(cube.dates[hole - 1]), str(cube.dates[hole])} | {
        str(cube.dates[hole + j]) for j in range(1, di.K_SESSIONS)
    }
    assert lost == expected


# Nothing in X looks past the close of t: tampering every session after
# t + 1 leaves X and y at t unchanged, and tampering t + 1 changes only y.
def test_causality_tamper():
    cubes, mask = _book("noise", names=4, n=80, seed=3)
    base = di.dataset(cubes, mask, CAL)
    cube = cubes["N01"]
    t = 50
    rng = np.random.default_rng(99)

    # The cube with every session at index >= `start` replaced by noise.
    def tampered(start: int) -> SessionCube:
        fields = {}
        for name in (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "prior_close",
            "auction_open",
        ):
            values = getattr(cube, name).copy()
            values[start:] *= np.exp(rng.normal(0.0, 0.3, size=values[start:].shape))
            fields[name] = values
        return replace(cube, **fields)

    later = dict(cubes)
    later["N01"] = tampered(t + 2)
    after = di.dataset(later, mask, CAL)
    upto = base.dates <= cube.dates[t]
    assert upto.sum() > 0
    for field in ("x_seq", "x_scalar", "y_return", "y_rank", "y_vol", "trailing_vol"):
        np.testing.assert_array_equal(
            getattr(base, field)[upto], getattr(after, field)[upto]
        )
    np.testing.assert_array_equal(base.tickers[upto], after.tickers[upto])
    # Rows after t differ for N01 (the future was changed).
    changed = (after.tickers == "N01") & (after.dates > cube.dates[t + 1])
    assert not np.array_equal(base.x_seq[changed], after.x_seq[changed])

    nxt = dict(cubes)
    nxt["N01"] = tampered(t + 1)
    after = di.dataset(nxt, mask, CAL)
    row = (base.tickers == "N01") & (base.dates == cube.dates[t])
    np.testing.assert_array_equal(base.x_seq[row], after.x_seq[row])
    np.testing.assert_array_equal(base.x_scalar[row], after.x_scalar[row])
    assert base.y_return[row] != after.y_return[row]
    assert base.y_vol[row] != after.y_vol[row]


# Within each date the rank target is the return's rank scaled to [0, 1],
# ties averaged, a lone name at 0.5.
def test_rank_normalization_within_date():
    cubes, mask = _book("noise", names=6, n=70, seed=4)
    ds = di.dataset(cubes, mask, CAL)
    bounds = ds.bounds()
    for s in range(len(ds.sessions)):
        rows = slice(bounds[s], bounds[s + 1])
        y = ds.y_return[rows]
        r = ds.y_rank[rows]
        assert r.min() == 0.0
        assert r.max() == 1.0
        assert np.array_equal(np.argsort(y), np.argsort(r))
        np.testing.assert_allclose(np.sort(r), np.arange(6) / 5.0)
    ranked = di.rank_within(
        np.array([3.0, 1.0, 1.0, 7.0, 5.0]), np.array([0, 0, 0, 0, 1])
    )
    np.testing.assert_allclose(ranked, [2 / 3, 0.5 / 3, 0.5 / 3, 1.0, 0.5])


# The ridge is the closed form: with no penalty it is least squares, and
# the penalty shrinks the coefficients toward zero on standardized inputs.
def test_ridge_closed_form():
    rng = np.random.default_rng(5)
    x = rng.normal(size=(400, 6)) * np.array([1, 10, 0.1, 1, 1, 1])
    beta = np.array([1.0, -0.5, 2.0, 0.0, 0.3, 0.0])
    y = 0.7 + x @ beta + rng.normal(0, 0.01, size=400)
    tiny = di.ridge_fit(x, y, alpha=1e-9)
    design = np.column_stack([np.ones(400), x])
    ols = np.linalg.lstsq(design, y, rcond=None)[0]
    np.testing.assert_allclose(di.ridge_predict(tiny, x), design @ ols, atol=1e-6)
    heavy = di.ridge_fit(x, y, alpha=1e6)
    assert np.abs(heavy.coef).max() < 1e-2
    assert heavy.intercept == pytest.approx(y.mean())
    # A constant column does not divide by zero.
    x[:, 5] = 3.0
    fitted = di.ridge_fit(x, y)
    assert np.isfinite(fitted.coef).all()


# Walk-forward keeps the plan's schedule: nothing before MIN_TRAIN sessions,
# a refit every REFIT sessions on rows more than PURGE sessions before the
# block, every later session predicted exactly once.
def test_walk_forward_schedule_and_purge():
    cubes, mask = _book("noise", names=4, n=720, seed=6)
    ds = di.dataset(cubes, mask, CAL)
    s = len(ds.sessions)
    assert s > di.MIN_TRAIN + di.REFIT
    forecast = di.walk_forward(ds, "ridge", "rank")
    before = ds.session_index < di.MIN_TRAIN
    assert np.isnan(forecast.values[before]).all()
    assert np.isfinite(forecast.values[~before]).all()
    starts = list(range(di.MIN_TRAIN, s, di.REFIT))
    assert len(forecast.fits) == len(starts)
    for fit, start in zip(forecast.fits, starts, strict=True):
        assert fit["test_start"] == str(ds.sessions[start])
        assert fit["test_end"] == str(ds.sessions[min(start + di.REFIT, s) - 1])
        assert fit["train_through"] == str(ds.sessions[start - di.PURGE - 1])
        assert fit["n_train"] == int((ds.session_index < start - di.PURGE).sum())
        assert fit["n_test"] == int(
            ((ds.session_index >= start) & (ds.session_index < start + di.REFIT)).sum()
        )
        assert fit["seconds"] >= 0
    # The purge: the last training session is PURGE + 1 sessions before the
    # first test session, so its target (t + 1) closes before the block.
    first = np.datetime64(forecast.fits[0]["train_through"], "D")
    gap = int(np.busday_count(first, ds.sessions[di.MIN_TRAIN], busdaycal=CAL))
    assert gap == di.PURGE + 1
    with pytest.raises(ValueError, match="unknown model"):
        di.walk_forward(ds, "forest", "rank")
    with pytest.raises(ValueError, match="unknown target"):
        di.walk_forward(ds, "ridge", "price")


# A planted late-day signal: the ridge's daily IC is large and stable, and
# the top-quintile portfolio beats equal weight after the 10 bp cost.
def test_ridge_finds_a_planted_late_day_signal():
    cubes, mask = _book("late_signal", names=12, n=950, seed=7)
    ds = di.dataset(cubes, mask, CAL)
    forecast = di.walk_forward(ds, "ridge", "rank")
    ic = di.daily_ic(ds, forecast)
    assert ic.n > 300
    assert ic.mean > 0.15
    assert ic.t > 3.0
    portfolio = di.top_quantile_portfolio(ds, forecast, di.COST_BPS)
    summary = portfolio.summary()
    assert summary["dates"] == ic.n
    assert summary["mean_bp"] > 0
    assert summary["t"] > 3.0
    # The cost is charged: net is below gross by the turnover times 10 bp.
    assert summary["portfolio_bp"] < summary["portfolio_gross_bp"]
    expected_cost = summary["turnover"] * di.COST_BPS
    assert summary["portfolio_gross_bp"] - summary["portfolio_bp"] == pytest.approx(
        expected_cost
    )
    # Twelve names: the top quintile is three of them.
    assert summary["names"] == 12
    # The study's verdict passes on this signal, restricted to A names too.
    keep = np.ones(len(ds), dtype=bool)
    payload = di.study(ds, {("ridge", "rank"): forecast}, keep_a=keep)
    row = next(r for r in payload["results"] if r["window"] == "2016-2023")
    assert row["portfolio_a"]["t"] == row["portfolio"]["t"]
    assert payload["verdict"].startswith(di.PASSED)
    assert "ridge" in payload["verdict"]


# Independent bars: the IC is noise, the portfolio does not beat the hurdle
# and the verdict is the plan's INSUFFICIENT EVIDENCE.
def test_noise_gives_insufficient_evidence():
    cubes, mask = _book("noise", names=12, n=950, seed=8)
    ds = di.dataset(cubes, mask, CAL)
    rank = di.walk_forward(ds, "ridge", "rank")
    vol = di.walk_forward(ds, "ridge", "vol")
    ic = di.daily_ic(ds, rank)
    assert abs(ic.t) < 3.0
    payload = di.study(ds, {("ridge", "rank"): rank, ("ridge", "vol"): vol})
    assert payload["verdict"] == di.INSUFFICIENT
    # The pairs run against the family total: the plan's four plus the two
    # families added on 2026-09-27 on both targets.
    assert payload["trials"] == 2
    assert payload["trials_total"] == di.TRIALS == 8
    assert payload["plan_trials"] == di.PLAN_TRIALS == 4
    assert payload["models"] == ["ridge"]
    assert payload["targets"] == ["rank", "vol"]
    assert {r["window"] for r in payload["results"]} == {"2016-2023", "2024-2026"}
    assert len(payload["results"]) == 4
    later = next(r for r in payload["results"] if r["window"] == "2024-2026")
    assert later["rows"] == 0
    # The detail names both floors and the trial count.
    detail = "\n".join(payload["verdict_detail"])
    assert "fails the kill criteria" in detail
    assert "trials counted: 2 run of 8 pre-registered" in detail
    # Strict JSON round-trips.
    json.dumps(payload, allow_nan=False)


# The volatility head: positive R² against trailing volatility when
# volatility clusters, about zero on independent bars.
def test_vol_r2_positive_when_volatility_clusters():
    cubes, mask = _book("vol_cluster", names=8, n=800, seed=9)
    ds = di.dataset(cubes, mask, CAL)
    forecast = di.walk_forward(ds, "ridge", "vol")
    clustered = di.vol_r2(ds, forecast)
    assert clustered["n"] > 1000
    assert clustered["r2"] > 0.05
    assert clustered["mse_model"] < clustered["mse_baseline"]

    cubes, mask = _book("noise", names=8, n=800, seed=10)
    ds = di.dataset(cubes, mask, CAL)
    forecast = di.walk_forward(ds, "ridge", "vol")
    flat = di.vol_r2(ds, forecast)
    assert -0.2 < flat["r2"] < 0.05


# A return whose mean scales with a predictable volatility gives the return
# head an IC that is really the volatility's; regressing the return forecast
# on the volatility forecast within each date removes it.
def test_volatility_control_removes_a_volatility_driven_ic():
    cubes, mask = _book("vol_drift", names=12, n=950, seed=11)
    ds = di.dataset(cubes, mask, CAL)
    rank = di.walk_forward(ds, "ridge", "rank")
    vol = di.walk_forward(ds, "ridge", "vol")
    raw = di.daily_ic(ds, rank)
    assert raw.t > 3.0
    controlled = di.volatility_control(ds, rank, vol)
    assert controlled.n == raw.n
    assert abs(controlled.t) < 3.0
    assert abs(controlled.mean) < raw.mean / 3.0
    payload = di.study(ds, {("ridge", "rank"): rank, ("ridge", "vol"): vol})
    row = next(
        r
        for r in payload["results"]
        if r["window"] == "2016-2023" and r["target"] == "rank"
    )
    assert row["control"]["dates"] == controlled.n
    # The return head clears both floors here, and the plan says what that is.
    assert row["ic"]["t"] >= di.IC_T_FLOOR
    assert row["portfolio"]["t"] >= di.PORTFOLIO_T_FLOOR
    assert payload["verdict"].startswith("VOLATILITY RESULT")
    assert any("a volatility result" in line for line in payload["verdict_detail"])


# The verdict applies the floors exactly as the plan states them.
def test_verdict_rules():
    # A payload with the fields the verdict reads.
    def payload(ic_t, port_t, control_t=None, r2=None):
        rank = {
            "window": "2016-2023",
            "model": "ridge",
            "target": "rank",
            "ic": {"mean": 0.02, "t": ic_t, "dates": 1000},
            "portfolio": {"mean_bp": 3.0, "t": port_t, "dates": 1000},
            "portfolio_a": None,
            "control": None
            if control_t is None
            else {"mean": 0.001, "t": control_t, "dates": 1000},
            "vol_r2": None,
        }
        rows = [rank]
        if r2 is not None:
            rows.append(
                {
                    "window": "2016-2023",
                    "model": "ridge",
                    "target": "vol",
                    "ic": None,
                    "portfolio": None,
                    "portfolio_a": None,
                    "control": None,
                    "vol_r2": {"r2": r2, "n": 5000},
                }
            )
        return {"choosing_window": "2016-2023", "results": rows, "trials": 4}

    assert di.verdict(payload(1.99, 5.0)) == di.INSUFFICIENT
    assert di.verdict(payload(5.0, 1.99)) == di.INSUFFICIENT
    assert di.verdict(payload(None, None)) == di.INSUFFICIENT
    assert di.verdict(payload(2.0, 2.0)).startswith(di.PASSED)
    assert di.verdict(payload(2.0, 2.0, control_t=2.0)).startswith(di.PASSED)
    assert di.verdict(payload(2.0, 2.0, control_t=1.9)).startswith("VOLATILITY RESULT")
    detail = di.verdict_detail(payload(2.5, 2.5, control_t=1.0, r2=-0.01))
    assert any("vanishes" in line for line in detail)
    assert any("fails (a failure of the model" in line for line in detail)
    assert any("passes the kill criteria" in line for line in detail)
    assert di.verdict_detail(payload(0.5, 0.5))[0].endswith("fails the kill criteria")


# The Spearman helper and the daily series agree with a direct computation.
def test_spearman_and_daily_series():
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert di.spearman(a, a) == pytest.approx(1.0)
    assert di.spearman(a, -a) == pytest.approx(-1.0)
    assert math.isnan(di.spearman(a, np.ones(5)))
    assert di.spearman(
        np.array([1.0, 2.0, 2.0, 3.0]), np.array([1.0, 3.0, 2.0, 4.0])
    ) == pytest.approx(0.9486832980505138)
    series = di.DailySeries(np.zeros(0, dtype="datetime64[D]"), np.zeros(0))
    assert series.n == 0
    assert math.isnan(series.mean)
    assert math.isnan(series.t)
    assert series.summary() == {"mean": series.mean, "t": series.t, "dates": 0}


# The CNN trains and predicts on a tiny book with the fixed configuration
# (skipped where torch is absent).
def test_cnn_smoke():
    pytest.importorskip("torch")
    from backend.market import deep_intraday_cnn as cnn

    cubes, mask = _book("late_signal", names=3, n=530, seed=12)
    ds = di.dataset(cubes, mask, CAL)
    forecast = di.walk_forward(ds, "cnn", "rank")
    assert forecast.parameters is not None
    assert forecast.parameters > 1000
    scored = ds.session_index >= di.MIN_TRAIN
    assert np.isfinite(forecast.values[scored]).all()
    assert np.isnan(forecast.values[~scored]).all()
    assert len(forecast.fits) == 1
    model = cnn.TemporalCNN(len(di.CHANNELS), len(di.SCALARS))
    assert cnn.parameter_count(model) == forecast.parameters
    predicted, _ = cnn.fit_predict(
        ds.x_seq[:200],
        ds.x_scalar[:200],
        ds.y_vol[:200],
        ds.x_seq[200:210],
        ds.x_scalar[200:210],
        "vol",
        {**di.CNN_CONFIG, "epochs": 1},
    )
    assert predicted.shape == (10,)
    assert np.isfinite(predicted).all()


# The dispatch knows the four families and no other; the torch and chronos
# families fail at their lazy import where the package is absent, never
# with "unknown model".
def test_dispatch_names():
    assert di.MODELS == ("ridge", "cnn", "patchtst", "chronos")
    assert di.TORCH_MODELS == ("cnn", "patchtst")
    cubes, mask = _book("noise", names=3, n=40, seed=13)
    ds = di.dataset(cubes, mask, CAL)
    for name in ("forest", "lstm", "", "Ridge"):
        with pytest.raises(ValueError, match="unknown model"):
            di.walk_forward(ds, name, "rank")
    for name in ("cnn", "patchtst", "chronos"):
        # The package may be absent here; the name itself is accepted.
        with contextlib.suppress(ImportError):
            di.walk_forward(ds, name, "rank", device="cpu")


# `resolve_device` is pure: auto follows CUDA availability, cpu is cpu,
# cuda needs a device, anything else is refused. The announcement prints
# once per process per device.
def test_resolve_device_and_announce(monkeypatch):
    assert di.resolve_device("auto", True) == "cuda"
    assert di.resolve_device("auto", False) == "cpu"
    assert di.resolve_device("AUTO", False) == "cpu"
    assert di.resolve_device("cpu", True) == "cpu"
    assert di.resolve_device("cpu", False) == "cpu"
    assert di.resolve_device("cuda", True) == "cuda"
    with pytest.raises(ValueError, match="no CUDA device"):
        di.resolve_device("cuda", False)
    with pytest.raises(ValueError, match="unknown device"):
        di.resolve_device("tpu", True)
    assert di.cuda_available() in (True, False)
    monkeypatch.setattr(di, "_ANNOUNCED", set())
    said: list[str] = []
    assert di.announce_device("cpu", said.append) is True
    assert di.announce_device("cpu", said.append) is False
    assert di.announce_device("cuda", said.append) is True
    assert said == ["device: cpu", "device: cuda"]


# The ridge is untouched by the device option and the new dispatch: the
# planted-signal IC is the value the pre-extension code produced
# (recorded from main at 3945c06 on 2026-09-27), and the forecast is
# byte-identical whatever device is named.
def test_ridge_results_unchanged_by_the_extension():
    cubes, mask = _book("late_signal", names=12, n=950, seed=7)
    ds = di.dataset(cubes, mask, CAL)
    forecast = di.walk_forward(ds, "ridge", "rank")
    ic = di.daily_ic(ds, forecast)
    assert ic.n == 430
    assert ic.mean == pytest.approx(0.2675394373068791, abs=1e-9)
    assert ic.t == pytest.approx(19.832886693475825, abs=1e-6)
    on_cuda_name = di.walk_forward(ds, "ridge", "rank", device="cuda")
    np.testing.assert_array_equal(forecast.values, on_cuda_name.values)
    assert forecast.parameters is None


# The chronos model is the ridge on [embedding, scalars]: with the encoder
# replaced by a fake (the package need not be present), it walks forward
# on the ridge's schedule, reports the encoder's parameter count, and with
# an embedding equal to the flattened bar returns it reproduces the ridge
# on those features exactly.
def test_chronos_is_ridge_on_the_embedding(monkeypatch):
    from backend.market import deep_intraday_pretrained as pretrained

    cubes, mask = _book("late_signal", names=6, n=620, seed=14)
    ds = di.dataset(cubes, mask, CAL)
    returns = ds.x_seq[:, :, 0].astype(np.float32)
    calls: list[dict] = []

    def fake_embedding(
        ds_, device="auto", cache_dir=None, model_id="", batch_size=0, log=None
    ):
        calls.append({"device": device, "cache_dir": cache_dir, "model_id": model_id})
        return returns, {"parameters": 1234, "cached": False}

    monkeypatch.setattr(pretrained, "dataset_embedding", fake_embedding)
    forecast = di.walk_forward(ds, "chronos", "rank", device="cpu", cache_dir=None)
    assert len(calls) == 1
    assert calls[0]["model_id"] == di.CHRONOS_CONFIG["model_id"]
    assert forecast.model == "chronos"
    assert forecast.parameters == 1234
    ridge = di.walk_forward(ds, "ridge", "rank")
    assert [f["test_start"] for f in forecast.fits] == [
        f["test_start"] for f in ridge.fits
    ]
    # The same ridge by hand on the same features, fit by fit.
    features = pretrained.features(returns, ds.x_scalar)
    assert features.shape == (len(ds), di.SEQ_LEN + len(di.SCALARS))
    s = ds.session_index
    start = di.MIN_TRAIN
    train = s < start - di.PURGE
    test = (s >= start) & (s < start + di.REFIT)
    fitted = di.ridge_fit(features[train], ds.y_rank[train])
    np.testing.assert_array_equal(
        forecast.values[test], di.ridge_predict(fitted, features[test])
    )
    with pytest.raises(ValueError, match="does not match"):
        pretrained.features(returns[:-1], ds.x_scalar)


# The embedding cache is keyed on the dataset: the fingerprint is a pure
# function of dates, tickers and the sequence shape, stable across calls,
# different for a different membership, order, window or shape; the path
# carries the model slug and the fingerprint.
def test_embedding_cache_fingerprint(tmp_path):
    from backend.market import deep_intraday_pretrained as pretrained

    cubes, mask = _book("noise", names=3, n=40, seed=15)
    ds = di.dataset(cubes, mask, CAL)
    key = pretrained.dataset_fingerprint(ds.dates, ds.tickers, ds.x_seq.shape)
    assert key == pretrained.dataset_fingerprint(ds.dates, ds.tickers, ds.x_seq.shape)
    assert len(key) == pretrained.FINGERPRINT_DIGITS
    assert all(c in "0123456789abcdef" for c in key)
    # A different dataset gives a different key.
    smaller = di.dataset(
        cubes, {"N00": cubes["N00"].dates, "N01": cubes["N01"].dates}, CAL
    )
    assert (
        pretrained.dataset_fingerprint(
            smaller.dates, smaller.tickers, smaller.x_seq.shape
        )
        != key
    )
    other = ds.tickers.copy()
    other[0] = "ZZZ"
    assert pretrained.dataset_fingerprint(ds.dates, other, ds.x_seq.shape) != key
    assert (
        pretrained.dataset_fingerprint(
            ds.dates + np.timedelta64(1, "D"), ds.tickers, ds.x_seq.shape
        )
        != key
    )
    assert (
        pretrained.dataset_fingerprint(ds.dates, ds.tickers, (len(ds), di.SEQ_LEN, 2))
        != key
    )
    # The path: <cache_dir>/embeddings_<slug>_<fingerprint>.npy.
    assert (
        pretrained.model_slug("amazon/chronos-bolt-small")
        == "amazon_chronos-bolt-small"
    )
    path = pretrained.cache_path(tmp_path, "amazon/chronos-bolt-small", key)
    assert path == tmp_path / f"embeddings_amazon_chronos-bolt-small_{key}.npy"
    assert pretrained.cache_path(tmp_path, "amazon/chronos-bolt-base", key) != path


# A cached embedding is read back without loading the pipeline; a file for
# another dataset (a different fingerprint, or the wrong row count) is not.
def test_embedding_cache_round_trip(tmp_path, monkeypatch):
    from backend.market import deep_intraday_pretrained as pretrained

    cubes, mask = _book("noise", names=3, n=40, seed=16)
    ds = di.dataset(cubes, mask, CAL)
    model_id = "fake/encoder"
    fake = np.arange(len(ds) * 4, dtype=np.float32).reshape(len(ds), 4)
    loads: list[str] = []

    class Pipeline:
        # A fake pipeline: an "encoder" with no parameters, and an embed()
        # the test never lets run (the embedding itself is faked below).
        class Model:
            # The fake encoder's (empty) parameter list.
            @staticmethod
            def parameters():
                return iter(())

        model = Model()

        @staticmethod
        def embed(context):
            raise AssertionError("embed must not run in this test")

    def fake_load(model_id_, device):
        loads.append(model_id_)
        return Pipeline()

    monkeypatch.setattr(pretrained, "load_pipeline", fake_load)
    monkeypatch.setattr(pretrained, "embed", lambda *a, **k: fake)
    lines: list[str] = []
    first, info = pretrained.dataset_embedding(
        ds, "cpu", tmp_path, model_id=model_id, log=lines.append
    )
    np.testing.assert_array_equal(first, fake)
    assert info["cached"] is False
    assert info["parameters"] == 0
    assert info["dim"] == 4
    assert loads == [model_id]
    path = Path(info["path"])
    assert path.exists()
    assert path.with_suffix(".json").exists()
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["rows"] == len(ds)
    assert meta["dim"] == 4
    assert meta["parameters"] == 0
    # Second call: read from the cache, the pipeline not loaded again.
    second, info2 = pretrained.dataset_embedding(ds, "cpu", tmp_path, model_id=model_id)
    np.testing.assert_array_equal(second, fake)
    assert info2["cached"] is True
    assert info2["parameters"] == 0
    assert loads == [model_id]
    assert any("written to" in line for line in lines)
    # A different dataset does not read this file.
    other = di.dataset({"N00": cubes["N00"]}, mask, CAL)
    _, info3 = pretrained.dataset_embedding(other, "cpu", tmp_path, model_id=model_id)
    assert info3["cached"] is False
    assert loads == [model_id, model_id]
    # No cache dir: computed, nothing written.
    _, info4 = pretrained.dataset_embedding(ds, "cpu", None, model_id=model_id)
    assert info4["cached"] is False
    assert info4["path"] is None


# The PatchTST trains and predicts on a tiny book with the fixed
# configuration (skipped where torch is absent), on the CPU explicitly.
def test_patchtst_smoke():
    pytest.importorskip("torch")
    import torch

    from backend.market import deep_intraday_patchtst as patchtst

    cubes, mask = _book("late_signal", names=3, n=530, seed=17)
    ds = di.dataset(cubes, mask, CAL)
    forecast = di.walk_forward(ds, "patchtst", "rank", device="cpu")
    assert forecast.parameters is not None
    assert forecast.parameters > 10_000
    scored = ds.session_index >= di.MIN_TRAIN
    assert np.isfinite(forecast.values[scored]).all()
    assert np.isnan(forecast.values[~scored]).all()
    assert len(forecast.fits) == 1
    model = patchtst.build(
        len(di.CHANNELS), len(di.SCALARS), di.SEQ_LEN, di.PATCHTST_CONFIG
    )
    assert model.n_patches == di.SEQ_LEN // di.PATCHTST_CONFIG["patch"] == 10
    from backend.market.deep_intraday_cnn import parameter_count

    assert parameter_count(model) == forecast.parameters
    out = model(
        torch.zeros(4, di.SEQ_LEN, len(di.CHANNELS)), torch.zeros(4, len(di.SCALARS))
    )
    assert tuple(out.shape) == (4, 2)
    with pytest.raises(ValueError, match="not a multiple"):
        patchtst.PatchTST(3, 3, seq_len=131, patch=13)
    predicted, _ = patchtst.fit_predict(
        ds.x_seq[:200],
        ds.x_scalar[:200],
        ds.y_vol[:200],
        ds.x_seq[200:210],
        ds.x_scalar[200:210],
        "vol",
        {**di.PATCHTST_CONFIG, "epochs": 1},
        device="cpu",
    )
    assert predicted.shape == (10,)
    assert np.isfinite(predicted).all()


# The Chronos-Bolt encoder embeds a few rows (skipped where torch or
# chronos is absent; downloads the checkpoint on first use) and the
# walk-forward on the embedding runs through the cache.
def test_chronos_smoke(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("chronos")
    from backend.market import deep_intraday_pretrained as pretrained

    cubes, mask = _book("noise", names=2, n=40, seed=18)
    ds = di.dataset(cubes, mask, CAL)
    embedding = pretrained.embed(ds.x_seq[:5], "cpu", batch_size=2)
    assert embedding.shape[0] == 5
    assert embedding.shape[1] > 8
    assert np.isfinite(embedding).all()
    full, info = pretrained.dataset_embedding(ds, "cpu", tmp_path, batch_size=16)
    assert full.shape == (len(ds), embedding.shape[1])
    assert info["parameters"] is not None
    assert info["parameters"] > 1_000_000
    again, info2 = pretrained.dataset_embedding(ds, "cpu", tmp_path)
    assert info2["cached"] is True
    np.testing.assert_array_equal(full, again)


# ---- the command on a temporary store ----------------------------------------

from backend.market import intraday_sip as sip  # noqa: E402
from backend.market.alpaca import IntradayBar, bars_expected  # noqa: E402
from backend.market.calendar import reviewed_sessions  # noqa: E402
from backend.market.store import MarketStore  # noqa: E402
from backend.market.yahoo import DailyBar, TickerHistory  # noqa: E402

PROVENANCE = sip.Provenance(
    fetched_at="2026-09-26T01:00:00+00:00", source_revision="abc"
)


# `n` full exchange sessions from `start` on the reviewed calendar, early
# closes skipped (the cube excludes them anyway).
def _exchange_sessions(n: int, start: date = date(2016, 1, 4)) -> list[date]:
    calendar = reviewed_sessions()[1]
    out: list[date] = []
    day = np.datetime64(start, "D")
    while len(out) < n:
        if np.is_busday(day, busdaycal=calendar):
            d = day.astype(object)
            if bars_expected(d) == di.SLOTS:
                out.append(d)
        day += np.timedelta64(1, "D")
    return out


# One session's 26 bars from `open0` with the given per-bar log returns.
def _bars(day: date, open0: float, returns: np.ndarray) -> list[IntradayBar]:
    # 13:30 UTC is 09:30 New York in summer, 14:30 UTC in winter; the store
    # groups by New York session date, so use the local clock.
    from zoneinfo import ZoneInfo

    start = datetime(
        day.year, day.month, day.day, 9, 30, tzinfo=ZoneInfo("America/New_York")
    )
    out = []
    price = open0
    for i, r in enumerate(returns):
        close = price * float(np.exp(r))
        out.append(
            IntradayBar(
                (start + timedelta(minutes=15 * i)).astimezone(UTC),
                price,
                max(price, close) * 1.0005,
                min(price, close) * 0.9995,
                close,
                1000.0 + 100.0 * i,
            )
        )
        price = close
    return out


# Write one name's sessions to the SIP store and its daily bars to the
# daily store.
def _write(store: MarketStore, ticker: str, sessions: list[date], seed: int) -> None:
    rng = np.random.default_rng(seed)
    closes: dict[date, float] = {}
    open0 = 100.0
    closes[sessions[0] - timedelta(days=3)] = open0
    for day in sessions:
        bars = _bars(day, open0, rng.normal(0.0, BAR_SD, size=di.SLOTS))
        assert sip.write_session(store, ticker, day, bars, PROVENANCE)
        closes[day] = bars[-1].close
        open0 = bars[-1].close
    store.write(
        date(2026, 9, 26),
        TickerHistory(
            ticker=ticker,
            bars=tuple(
                DailyBar(d, c, c, c, c, c, 26000) for d, c in sorted(closes.items())
            ),
            actions=(),
            complete_through=max(closes),
            source_time=datetime(2026, 9, 26, tzinfo=UTC),
        ),
    )


# A fake desk report over `dates` and `tickers` with the given (T, N) grades.
def _report(dates: np.ndarray, tickers: tuple[str, ...], grades: np.ndarray):
    from backend.agents.trading.desk import grading, regime
    from backend.agents.trading.desk.desk import DeskReport
    from backend.agents.trading.desk.opinions import Opinion
    from backend.market.panel import Panel
    from backend.market.universe import AI_COMPUTE

    t, n = grades.shape
    prices = np.full((t, n), 100.0)
    panel = Panel(
        dates=dates,
        tickers=tickers,
        open=prices,
        high=prices,
        low=prices,
        close=prices,
        adj_close=prices,
        volume=prices,
        themes={k: (AI_COMPUTE,) for k in tickers[:-1]},
        benchmark=tickers[-1],
    )
    graded = grading.Graded(grades, grades.astype(float), {}, grades.astype(float))
    state = regime.RegimeState(
        0, 0, 0.5, 0, 0, 0, "ai", 0.1, 0, 1.0, 1.0, (), 0.0, False
    )
    view = regime.RegimeView([state] * t, Opinion("rotation", np.full((t, n), np.nan)))
    return DeskReport(
        panel, {k: "ai" for k in tickers[:-1]}, {}, view, graded, graded.as_scores(), []
    )


# The command end to end on a store with three synthetic names: cubes from
# the SIP store, the mask from the membership file, grades from the desk
# hook, the payload at <root>/desk/deep_intraday.json with every row and a
# verdict, the table and the verdict in the text.
def test_cli_end_to_end(tmp_path):
    from backend.agents.trading.desk import grading
    from backend.cli import market_deep_intraday as cli

    store = MarketStore(tmp_path)
    sessions = _exchange_sessions(di.MIN_TRAIN + 45)
    names = ("AAA", "BBB", "CCC")
    for i, ticker in enumerate(names):
        _write(store, ticker, sessions, i)
    membership = tmp_path / "membership.csv"
    membership.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        + "".join(f"{t},2015-01-02,2015-01-02,,,test,test\n" for t in names),
        encoding="utf-8",
    )
    dates = np.array(sessions, dtype="datetime64[D]")
    grades = np.full((len(dates), 4), grading.ORDINAL[grading.A], dtype=int)
    grades[:, 2] = grading.ORDINAL[grading.B]
    grades[::2, 2] = grading.ORDINAL[grading.A_PLUS]
    grades[:, 3] = grading.ORDINAL[grading.C]
    calls: list[str] = []

    def fake_desk(store_):
        calls.append(str(store_.root))
        return _report(dates, (*names, "SPY"), grades)

    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--tickers",
            "AAA,BBB,CCC,SPY",
            "--membership",
            str(membership),
            "--models",
            "ridge",
            "--workers",
            "1",
        ]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    text = out.getvalue()
    assert calls == [str(tmp_path)]

    target = tmp_path / "desk" / "deep_intraday.json"
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["study"] == "deep_intraday"
    assert payload["stage"] == 1
    assert payload["plan"] == di.PLAN
    assert payload["models"] == ["ridge"]
    assert payload["targets"] == ["rank", "vol"]
    assert payload["requested"] == {"models": ["ridge"], "targets": ["rank", "vol"]}
    assert payload["trials"] == 2
    assert payload["trials_total"] == 8
    assert payload["device"] == "cpu"
    assert set(payload["sessions_per_ticker"]) == set(names)  # SPY was dropped
    assert payload["dataset"]["names"] == 3
    assert payload["dataset"]["rows"] > 3 * di.MIN_TRAIN
    assert payload["dataset"]["graded_rows"] > 0
    assert len(payload["results"]) == 2 * 2  # two windows x (rank, vol)
    rank = next(
        r
        for r in payload["results"]
        if r["window"] == "2016-2023" and r["target"] == "rank"
    )
    assert rank["rows"] > 0
    assert rank["ic"]["dates"] == rank["portfolio"]["dates"] > 0
    # The A/A+ line: CCC is A+ on alternate sessions, so fewer dates qualify.
    assert 0 < rank["portfolio_a"]["dates"] <= rank["portfolio"]["dates"]
    assert rank["control"]["dates"] == rank["ic"]["dates"]
    vol = next(
        r
        for r in payload["results"]
        if r["window"] == "2016-2023" and r["target"] == "vol"
    )
    assert vol["vol_r2"]["n"] > 0
    assert len(payload["fits"]["ridge/rank"]) == 1
    assert payload["verdict"] in (di.INSUFFICIENT,) or payload["verdict"].startswith(
        (di.PASSED, "VOLATILITY RESULT")
    )
    assert "NaN" not in target.read_text(encoding="utf-8")

    assert "dataset:" in text
    assert "ridge/rank fit 1: train through" in text
    assert "desk grades:" in text
    assert "verdict:" in text
    assert "top bp/d" in text
    assert f"wrote {target}" in text


# `--json` prints the payload only; an empty store exits 1; the model list
# is validated; a desk that fails leaves the A-only line unscored and says so.
def test_cli_json_empty_store_and_model_validation(tmp_path):
    from backend.cli import market_deep_intraday as cli

    out = io.StringIO()
    args = cli.build_parser().parse_args(["--root", str(tmp_path), "--tickers", "AAA"])
    assert cli.run(args, out) == 1
    assert "nothing to study" in out.getvalue()
    with pytest.raises(SystemExit):
        cli.parse_models("ridge,forest")
    assert cli.parse_models("cnn, ridge") == ("cnn", "ridge")
    assert cli.parse_models("patchtst,chronos") == ("patchtst", "chronos")
    with pytest.raises(SystemExit):
        cli.parse_targets("rank,price")
    assert cli.parse_targets("VOL") == ("vol",)
    with pytest.raises(SystemExit):
        cli.parse_out("sub/dir.json")
    with pytest.raises(SystemExit):
        cli.parse_out("")
    assert cli.parse_out("cnn.json") == "cnn.json"
    defaults = cli.build_parser().parse_args([])
    assert defaults.models == "ridge,cnn,patchtst,chronos"
    assert defaults.targets == "rank,vol"
    assert defaults.device == "auto"
    assert defaults.out == "deep_intraday.json"
    assert defaults.root == "data/market"
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--device", "tpu"])

    store = MarketStore(tmp_path)
    sessions = _exchange_sessions(di.MIN_TRAIN + 30)
    _write(store, "AAA", sessions, 1)
    _write(store, "BBB", sessions, 2)
    _write(store, "CCC", sessions, 3)
    membership = tmp_path / "membership.csv"
    membership.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        + "".join(
            f"{t},2015-01-02,2015-01-02,,,test,test\n" for t in ("AAA", "BBB", "CCC")
        ),
        encoding="utf-8",
    )

    def broken_desk(store_):
        raise RuntimeError("no fundamentals here")

    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--tickers",
            "AAA,BBB,CCC",
            "--membership",
            str(membership),
            "--models",
            "ridge",
            "--json",
        ]
    )
    assert cli.run(args, out, desk_run=broken_desk) == 0
    payload = json.loads(out.getvalue())
    assert payload["grade_note"].startswith("desk not run (RuntimeError")
    assert payload["dataset"]["graded_rows"] is None
    rank = next(r for r in payload["results"] if r["target"] == "rank")
    assert rank["portfolio_a"] is None


# `--out` names the payload file under <root>/desk/ and the default file is
# left alone; `--targets vol` runs only the volatility rows and the payload
# says so; `--device cpu` is recorded.
def test_cli_out_and_targets(tmp_path, monkeypatch):
    from backend.cli import market_deep_intraday as cli

    # The device is announced once per process; start this one fresh.
    monkeypatch.setattr(di, "_ANNOUNCED", set())
    store = MarketStore(tmp_path)
    sessions = _exchange_sessions(di.MIN_TRAIN + 45)
    for i, ticker in enumerate(("AAA", "BBB", "CCC")):
        _write(store, ticker, sessions, 20 + i)
    membership = tmp_path / "membership.csv"
    membership.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        + "".join(
            f"{t},2015-01-02,2015-01-02,,,test,test\n" for t in ("AAA", "BBB", "CCC")
        ),
        encoding="utf-8",
    )

    def broken_desk(store_):
        raise RuntimeError("no fundamentals here")

    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--tickers",
            "AAA,BBB,CCC",
            "--membership",
            str(membership),
            "--models",
            "ridge",
            "--targets",
            "vol",
            "--device",
            "cpu",
            "--out",
            "deep_intraday_ridge.json",
            "--workers",
            "1",
        ]
    )
    assert cli.run(args, out, desk_run=broken_desk) == 0
    text = out.getvalue()
    named = tmp_path / "desk" / "deep_intraday_ridge.json"
    assert named.exists()
    assert not (tmp_path / "desk" / "deep_intraday.json").exists()
    assert f"wrote {named}" in text
    assert "device: cpu" in text
    payload = json.loads(named.read_text(encoding="utf-8"))
    assert payload["device"] == "cpu"
    assert payload["targets"] == ["vol"]
    assert payload["requested"] == {"models": ["ridge"], "targets": ["vol"]}
    assert payload["trials"] == 1
    assert payload["trials_total"] == 8
    assert {r["target"] for r in payload["results"]} == {"vol"}
    assert list(payload["fits"]) == ["ridge/vol"]
    assert payload["verdict"] == di.INSUFFICIENT
    assert "ridge/vol fit 1: train through" in text
    assert "ridge/rank" not in text
    assert "trials 1 run of 8; device cpu" in text


# The dataset round-trips through the export file with every array intact,
# and the CLI can build-and-export on one machine and train from the file
# on another (no store, no cubes, no desk) with the same result.
def test_dataset_export_and_training_from_the_file(tmp_path, monkeypatch):
    from backend.cli import market_deep_intraday as cli

    monkeypatch.setattr(di, "_ANNOUNCED", set())
    store = MarketStore(tmp_path)
    sessions = _exchange_sessions(di.MIN_TRAIN + 45)
    for i, ticker in enumerate(("AAA", "BBB", "CCC")):
        _write(store, ticker, sessions, 20 + i)
    membership = tmp_path / "membership.csv"
    membership.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        + "".join(
            f"{t},2015-01-02,2015-01-02,,,test,test\n" for t in ("AAA", "BBB", "CCC")
        ),
        encoding="utf-8",
    )
    export = tmp_path / "export" / "stage1.npz"
    common = ["--root", str(tmp_path), "--tickers", "AAA,BBB,CCC", "--membership", str(membership), "--device", "cpu", "--workers", "1"]
    out = io.StringIO()
    args = cli.build_parser().parse_args([*common, "--models", "none", "--export", str(export)])
    assert cli.run(args, out, desk_run=lambda s_: (_ for _ in ()).throw(RuntimeError("no desk"))) == 0
    assert export.exists() and "wrote dataset" in out.getvalue()
    assert not (tmp_path / "desk" / "deep_intraday.json").exists()
    ds, keep = di.load_dataset(export)
    assert len(ds) > 0 and keep is None  # the desk failed, so no A/A+ rows
    assert ds.dates.dtype == np.dtype("datetime64[D]") and ds.tickers.dtype.kind in "U"
    # Training from the file, in a directory with no store at all.
    elsewhere = tmp_path / "desktop"
    elsewhere.mkdir()
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        ["--root", str(elsewhere), "--dataset", str(export), "--models", "ridge", "--targets", "vol", "--device", "cpu", "--out", "from_file.json"]
    )
    assert cli.run(args, out) == 0
    payload = json.loads((elsewhere / "desk" / "from_file.json").read_text(encoding="utf-8"))
    assert payload["targets"] == ["vol"] and list(payload["fits"]) == ["ridge/vol"]
    assert "dataset from" in out.getvalue()
    # Round trip with a mask keeps it.
    keep_a = np.zeros(len(ds), dtype=bool)
    keep_a[::3] = True
    di.save_dataset(export, ds, keep_a)
    ds2, keep2 = di.load_dataset(export)
    np.testing.assert_array_equal(keep2, keep_a)
    np.testing.assert_array_equal(ds2.x_seq, ds.x_seq)
    np.testing.assert_array_equal(ds2.dates, ds.dates)
    assert cli.parse_models("none") == ()
