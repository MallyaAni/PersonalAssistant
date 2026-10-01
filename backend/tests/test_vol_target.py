"""Volatility targeting of the book (B1): gross path, simulator, scorecard, verdict.

The rule is `vol_target.gross_path` on the book's own gross-1 returns;
`simulate.run(gross_path=...)` applies it; `market_pit_scorecard
--gross-target` runs the two rule lines at gross 1 and then scaled; the
verdict pairs a target's payload with the control's. The null test - an
infinite target reproduces the plain run to the bit - is asserted here on
the synthetic book, in the simulator and through the scorecard's payloads.
"""

import json
import math

import numpy as np
import pytest

from backend.agents.trading.desk import point_in_time, simulate
from backend.cli import market_pit_scorecard as sc
from backend.cli import market_vol_target as cli
from backend.market import benchmarks, vol_target
from backend.tests import test_market_pit_scorecard as scorecard_tests

PLAIN = dict(use_exits=False, rebalance=20, cost_bps=10.0)
T = scorecard_tests.T
_report = scorecard_tests._report


# The scorecard tests' membership history: AAA-DDD throughout, EEE from
# mid-2023, FFF until mid-2023.
@pytest.fixture
def history(tmp_path):
    return scorecard_tests.history.__wrapped__(tmp_path)


# A flat benchmark so the scorecard needs no store.
@pytest.fixture
def flat_benchmark(monkeypatch):
    monkeypatch.setattr(
        benchmarks,
        "load_benchmark",
        lambda store, symbol, sessions, cost_bps=10.0, **kw: benchmarks.BenchmarkSeries(
            symbol,
            True,
            np.zeros(len(sessions)),
            np.ones(len(sessions)),
            np.asarray(sessions),
        ),
    )


# σ̂ at t reads exactly returns[t-window .. t-1], annualised with the
# sample standard deviation, and is undefined until the window is full
# or when any return inside it is missing.
def test_sigma_hat_reads_the_window_before_t():
    r = np.array([np.nan, 0.01, -0.02, 0.03, 0.0, 0.01, np.nan, 0.02, 0.01, -0.01])
    sigma = vol_target.sigma_hat(r, window=3)
    assert np.isnan(sigma[:4]).all()  # r[1..3] is the first full window, read at t=4
    expected = float(np.std(r[1:4], ddof=1)) * math.sqrt(252)
    assert sigma[4] == pytest.approx(expected)
    assert sigma[5] == pytest.approx(float(np.std(r[2:5], ddof=1)) * math.sqrt(252))
    # The NaN at index 6 poisons the windows that contain it.
    assert np.isnan(sigma[7:10]).all()
    with pytest.raises(ValueError, match="two sessions"):
        vol_target.sigma_hat(r, window=1)


# gross = min(1, σ*/σ̂): 1 where σ̂ is undefined, 1 when σ̂ is under the
# target, σ*/σ̂ when over; an infinite target is 1 everywhere (the null).
def test_gross_path_scales_by_the_target():
    rng = np.random.default_rng(1)
    r = rng.normal(0.0, 0.03, size=100)  # about 48% a year
    gross, sigma = vol_target.gross_path(r, vol_target.Spec(0.20, window=20))
    assert (gross[:20] == 1.0).all()
    assert (gross[20:] < 1.0).all()
    assert gross[50] == pytest.approx(min(1.0, 0.20 / sigma[50]))
    calm, _ = vol_target.gross_path(r, vol_target.Spec(5.0, window=20))
    assert (calm == 1.0).all()
    null, _ = vol_target.gross_path(r, vol_target.Spec(math.inf, window=20))
    assert (null == 1.0).all()
    with pytest.raises(ValueError, match="positive"):
        vol_target.gross_path(r, vol_target.Spec(0.0))


# The return switch is 0 while the trailing book return is negative; the
# intercept switch is 1 while the trailing risk-return intercept is
# negative; the return switch wins when both fire.
def test_switches():
    r = np.full(200, 0.02)
    r[100:] = -0.01
    on = vol_target.return_switch(r, window=50)
    # The 50-session product turns negative once fewer than 17 of the +2%
    # sessions remain in the window, from t = 134 on.
    assert not on[:134].any()
    assert on[134:].all()
    # A book whose return falls as its variance rises has a positive
    # intercept; one whose return rises with variance from a negative base
    # has a negative one.
    rng = np.random.default_rng(2)
    noise = rng.normal(0.0, 0.001, size=300)
    sigma = np.linspace(0.1, 0.5, 300)
    daily_var = (sigma / math.sqrt(252)) ** 2
    positive = 0.001 - 0.5 * daily_var + noise
    negative = -0.001 + 50.0 * daily_var + noise
    assert not vol_target.intercept_switch(positive, sigma, window=120)[120:].any()
    assert vol_target.intercept_switch(negative, sigma, window=120)[120:].all()
    spec = vol_target.Spec(0.20, window=20, switch_return=True, switch_intercept=True)
    # A losing book with a negative intercept: both switches fire, and the
    # return switch (cash) wins over the intercept switch (no scaling).
    losing = -0.001 + daily_var + noise
    assert vol_target.intercept_switch(losing, sigma, window=120)[130:].all()
    assert vol_target.return_switch(losing, window=120)[130:].all()
    gross, _ = vol_target.gross_path(losing, spec)
    assert (gross[130:] == 0.0).all()
    alone = vol_target.Spec(0.20, window=20, switch_intercept=True)
    assert (vol_target.gross_path(losing, alone)[0][130:] == 1.0).all()
    assert vol_target.Spec(0.25).tag == "vt25"
    assert spec.tag == "vt20_sr_si"
    assert vol_target.Spec(0.25, window=60).tag == "vt25_w60"
    assert vol_target.Spec(math.inf).tag == "vtinf"
    assert vol_target.Spec(0.25).record()["registered"]
    assert not vol_target.Spec(0.15).record()["registered"]


# The simulator with no path and with a path of all ones are the same to
# the bit; a path that halves the book on a rebalance halves what it holds,
# and a zero holds cash; the path is validated.
def test_simulator_gross_path(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    allocate = point_in_time.equal_weight_allocator(mask)
    plain = simulate.run(restricted, allocator=allocate, **PLAIN)
    ones = simulate.run(restricted, allocator=allocate, gross_path=np.ones(T), **PLAIN)
    assert np.array_equal(plain.returns, ones.returns, equal_nan=True)
    assert np.array_equal(plain.equity, ones.equity, equal_nan=True)
    assert plain.traded == ones.traded
    half = simulate.run(
        restricted, allocator=allocate, gross_path=np.full(T, 0.5), **PLAIN
    )
    assert half.invested[1:].max() < 0.55
    assert half.invested[5] == pytest.approx(0.5, abs=0.03)
    # Scaling down between rebalances is traded once, when the gross moves.
    path = np.ones(T)
    path[30:] = 0.5
    cut = simulate.run(restricted, allocator=allocate, gross_path=path, **PLAIN)
    assert cut.invested[29] > 0.9
    assert cut.invested[31] == pytest.approx(0.5, abs=0.03)
    # The cut is one trade; what follows is a half-size book, so the run's
    # whole notional is lower, not higher.
    assert cut.traded < plain.traded
    # Gross 0 is cash; the session the gross returns re-enters.
    path = np.ones(T)
    path[30:45] = 0.0
    out = simulate.run(restricted, allocator=allocate, gross_path=path, **PLAIN)
    assert out.invested[31:45].max() == 0.0
    assert out.invested[46] > 0.9
    # The exit to cash is logged under the overlay's own reason.
    assert "volatility target risk reduction" in {tr.reason for tr in out.trades}
    for bad in (np.full(T - 1, 1.0), np.full(T, 1.5), np.full(T, -0.1)):
        with pytest.raises(ValueError, match="gross path"):
            simulate.run(restricted, allocator=allocate, gross_path=bad, **PLAIN)
    with pytest.raises(ValueError, match="funded_allocation"):
        simulate.run(restricted, funded_allocation=True, gross_path=np.ones(T), **PLAIN)


# The scorecard's target run: the control inside it is the plain build to
# the bit, an infinite target reproduces the control on every line and
# curve, and a tight target holds less, carries its gross record and is
# named by its tag.
def test_scorecard_targets_and_null(history, flat_benchmark):
    report = _report()
    arm = sc.ARMS["ew_graded_full"]
    specs = (vol_target.Spec(math.inf), vol_target.Spec(0.05))
    payloads = sc.build_targets(
        report, object(), 2, (10.0,), history_path=history, arm=arm, specs=specs
    )
    control = sc.build(report, object(), 2, (10.0,), history_path=history, arm=arm)
    assert json.dumps(payloads[sc.CONTROL], allow_nan=True) == json.dumps(
        control, allow_nan=True
    )
    null = payloads["vtinf"]
    assert null["rows"] == control["rows"]
    assert null["paired"] == control["paired"]
    assert json.dumps(null["curves"], allow_nan=True) == json.dumps(
        control["curves"], allow_nan=True
    )
    assert null["vol_target"]["target"] == math.inf
    assert all(g == 1.0 for g in null["vol_target"]["10"]["median_offset"]["gross"])
    tight = payloads["vt05"]
    assert tight["vol_target"]["tag"] == "vt05"
    assert tight["vol_target"]["window"] == 20
    record = tight["vol_target"]["10"]["windows"]["all"]
    assert 0 < record["mean_gross"] < 1
    assert record["share_below_one"] > 0.5
    assert record["traded_over_gross_one"] > 1.0
    assert len(tight["vol_target"]["10"]["median_offset"]["gross"]) == len(
        tight["curves"]["10"]["dates"]
    )
    row = vol_target._row(tight, "all", 10.0)
    base = vol_target._row(control, "all", 10.0)
    assert len(row["cagrs"]) == 2
    assert "worst_drawdown" in row
    # Scaled to 5% a year, the book is much calmer than at gross 1.
    assert abs(row["median_drawdown"]) < abs(base["median_drawdown"])
    # The other lines are shared with the base.
    for label in (sc.EW_PIT, sc.EW_TODAY, "SPY"):
        assert np.array_equal(
            np.asarray(tight["curves"]["10"]["lines"][label], dtype=float),
            np.asarray(control["curves"]["10"]["lines"][label], dtype=float),
            equal_nan=True,
        )
    text = sc.render(tight)
    assert "volatility target vt05" in text
    assert "gross on rule / point-in-time" in text


# The CLI's null test passes on the synthetic book, a target run writes
# the control and each target by tag, and the options are checked.
def test_scorecard_cli_null_test_and_outputs(
    history, flat_benchmark, monkeypatch, tmp_path
):  # noqa: F811
    from backend.agents.trading.desk import desk

    report = _report()
    monkeypatch.setattr(desk, "run", lambda *args, **kwargs: report)
    common = [
        "--root",
        str(tmp_path),
        "--graded-cap",
        "0.5",
        "--membership",
        str(history),
    ]
    assert (
        sc.main([*common, "--gross-target", "inf", "--null-test", "--costs", "10"]) == 0
    )
    out = tmp_path / "vt.json"
    assert (
        sc.main(
            [
                *common,
                "--gross-target",
                "20",
                "30",
                "--offsets",
                "1",
                "--costs",
                "10",
                "--output",
                str(out),
            ]
        )
        == 0
    )
    assert {p.name for p in tmp_path.glob("vt_*.json")} == {
        "vt_control.json",
        "vt_vt20.json",
        "vt_vt30.json",
    }
    written = json.loads((tmp_path / "vt_vt20.json").read_text(encoding="utf-8"))
    assert written["arm"] == "ew_graded_cap50 + vt20"
    assert written["vol_target"]["target"] == pytest.approx(0.20)
    assert "concentration" in written
    control = json.loads((tmp_path / "vt_control.json").read_text(encoding="utf-8"))
    assert control["arm"] == "ew_graded_cap50"
    assert "vol_target" not in control
    one = tmp_path / "one.json"
    assert (
        sc.main(
            [
                *common,
                "--gross-target",
                "25",
                "--gross-window",
                "60",
                "--offsets",
                "1",
                "--costs",
                "10",
                "--output",
                str(one),
            ]
        )
        == 0
    )
    assert one.exists()
    assert (tmp_path / "one_control.json").exists()
    assert (
        json.loads(one.read_text(encoding="utf-8"))["vol_target"]["tag"] == "vt25_w60"
    )
    with pytest.raises(SystemExit):
        sc.main(["--root", str(tmp_path), "--gross-target", "20"])  # no arm
    with pytest.raises(SystemExit):
        sc.main([*common, "--gross-target", "20", "--null-test"])  # not inf


# Two synthetic payloads on which the verdict is known: the paired
# statistics match a direct computation, the drawdown trade and the
# Sharpe trade are read per the plan, a negative paired t blocks REPLACES,
# and the lines carry the numbers.
def test_verdict_on_known_payloads():
    rng = np.random.default_rng(3)
    dates = [
        str(d) for d in np.arange("2016-01-04", "2026-01-01", dtype="datetime64[D]")
    ]
    dates = [
        d
        for d in dates
        if np.datetime64(d).astype("datetime64[D]").astype(object).weekday() < 5
    ]
    n = len(dates)
    control_daily = rng.normal(0.0005, 0.02, size=n)
    candidate_daily = control_daily * 0.6 + 0.0002

    def payload(daily, rows):
        return {
            "windows": {
                "2016-2023": ["2016-01-01", "2024-01-01"],
                "2024-2026": ["2024-01-01", None],
                "all": [None, None],
            },
            "curves": {
                "25": {
                    "offset": 10,
                    "dates": dates,
                    "lines": {vol_target.RULE_LINE: list(daily)},
                }
            },
            "rows": rows,
            "arm": "x",
        }

    def rows(dd, cagr, sharpe, cagrs):
        return [
            {
                "line": vol_target.RULE_LINE,
                "window": w,
                "cost_bps": 25.0,
                "median_drawdown": dd[w],
                "median_cagr": cagr[w],
                "median_sharpe": sharpe[w],
                "cagrs": cagrs[w],
            }
            for w in ("2016-2023", "2024-2026")
        ]

    control = payload(
        control_daily,
        rows(
            {"2016-2023": -0.40, "2024-2026": -0.25},
            {"2016-2023": 0.28, "2024-2026": 0.45},
            {"2016-2023": 0.9, "2024-2026": 1.2},
            {"2016-2023": [0.28] * 20, "2024-2026": [0.45] * 20},
        ),
    )
    good = payload(
        candidate_daily,
        rows(
            {"2016-2023": -0.30, "2024-2026": -0.19},
            {"2016-2023": 0.26, "2024-2026": 0.43},
            {"2016-2023": 1.0, "2024-2026": 1.3},
            {"2016-2023": [0.29] * 16 + [0.27] * 4, "2024-2026": [0.45] * 20},
        ),
    )
    good["vol_target"] = vol_target.Spec(0.25).record()
    reading = vol_target.verdict(good, control, trial_variance=0.01)
    a, b = vol_target.paired_daily(good, control, "2016-2023")
    diff = a - b
    assert reading["paired"]["2016-2023"]["sessions"] == len(diff) > 1500
    assert reading["paired"]["2016-2023"]["mean_daily_bp"] == pytest.approx(
        diff.mean() * 1e4
    )
    assert reading["drawdown_trade"]
    assert not reading["sharpe_trade"]
    assert reading["label"] == "REPLACES"
    assert reading["replaces_on"] == ["drawdown"]
    assert reading["offsets_above"] == 16
    assert reading["offsets"] == 20
    assert math.isfinite(reading["dsr"])
    assert reading["lines"][0].startswith("σ* = 25%: paired 2016-2023")
    assert "REPLACES gross 1.0 (on drawdown)" in reading["lines"][-1]
    assert "-30.0% against -40.0% (+10.0 points)" in reading["lines"][1]
    # The Sharpe trade: +0.15 on both windows, drawdown not worse.
    sharpe_only = payload(
        candidate_daily,
        rows(
            {"2016-2023": -0.40, "2024-2026": -0.25},
            {"2016-2023": 0.28, "2024-2026": 0.45},
            {"2016-2023": 1.1, "2024-2026": 1.4},
            {"2016-2023": [0.28] * 20, "2024-2026": [0.45] * 20},
        ),
    )
    sharpe_only["vol_target"] = vol_target.Spec(0.30).record()
    reading = vol_target.verdict(sharpe_only, control)
    assert reading["sharpe_trade"]
    assert reading["label"] == "REPLACES"
    assert reading["replaces_on"] == ["sharpe"]
    assert math.isnan(reading["dsr"])
    # Three points of drawdown is not five; a point of CAGR too many fails.
    weak = payload(
        candidate_daily,
        rows(
            {"2016-2023": -0.37, "2024-2026": -0.19},
            {"2016-2023": 0.26, "2024-2026": 0.43},
            {"2016-2023": 0.9, "2024-2026": 1.2},
            {"2016-2023": [0.2] * 20, "2024-2026": [0.45] * 20},
        ),
    )
    weak["vol_target"] = vol_target.Spec(0.20).record()
    reading = vol_target.verdict(weak, control)
    assert reading["label"] == "RECORD"
    assert "drawdown trade" in reading["lines"][-1]
    greedy = payload(
        candidate_daily,
        rows(
            {"2016-2023": -0.30, "2024-2026": -0.19},
            {"2016-2023": 0.24, "2024-2026": 0.43},
            {"2016-2023": 0.9, "2024-2026": 1.2},
            {"2016-2023": [0.2] * 20, "2024-2026": [0.45] * 20},
        ),
    )
    greedy["vol_target"] = vol_target.Spec(0.20).record()
    assert vol_target.verdict(greedy, control)["label"] == "RECORD"
    # A clearly negative paired difference blocks the drawdown trade.
    losing = payload(control_daily - 0.0015, good["rows"])
    losing["vol_target"] = vol_target.Spec(0.25).record()
    reading = vol_target.verdict(losing, control)
    assert reading["paired"]["2016-2023"]["hac_t"] < -2
    assert reading["drawdown_trade"]
    assert not reading["not_negative"]
    assert reading["label"] == "RECORD"
    assert "negative at t <= -2" in reading["lines"][-1]
    # The trial variance across the registered targets.
    assert math.isfinite(
        vol_target.trial_variance({"a": good, "b": sharpe_only}, control)
    )
    assert math.isnan(vol_target.trial_variance({"a": good}, control))


# The verdict command pairs every target payload with the control, writes
# the verdict file with the registered lines, and prints them.
def test_verdict_cli(history, flat_benchmark, tmp_path, capsys):
    report = _report()
    arm = sc.ARMS["ew_graded_full"]
    specs = (vol_target.Spec(0.05), vol_target.Spec(0.08))
    payloads = sc.build_targets(
        report, object(), 2, (10.0, 25.0), history_path=history, arm=arm, specs=specs
    )
    payloads[sc.CONTROL]["arm"] = "ew_graded_full"
    control = tmp_path / "control.json"
    control.write_text(
        json.dumps(payloads[sc.CONTROL], allow_nan=True), encoding="utf-8"
    )
    targets = []
    for tag in ("vt05", "vt08"):
        path = tmp_path / f"{tag}.json"
        path.write_text(json.dumps(payloads[tag], allow_nan=True), encoding="utf-8")
        targets.append(str(path))
    out = tmp_path / "verdict.json"
    assert (
        cli.main(
            ["--control", str(control), "--targets", *targets, "--output", str(out)]
        )
        == 0
    )
    written = json.loads(out.read_text(encoding="utf-8"))
    assert set(written["targets"]) == {"vt05", "vt08"}
    assert written["targets"]["vt05"]["label"] in {"REPLACES", "RECORD"}
    assert written["trials"] == vol_target.TRIALS
    assert written["control"]["arm"] == payloads[sc.CONTROL]["arm"]
    printed = capsys.readouterr().out
    assert "σ* = 5%" in printed
    assert "σ* = 8%" in printed
    for line in written["targets"]["vt05"]["lines"]:
        assert line in printed
