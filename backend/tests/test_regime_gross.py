"""Regime gross (B2): the rule, the point-in-time probability, scorecard and verdict.

The rule is `regime_gross.regime_path` on the walk-forward day-type
probability read at the previous close; `market_pit_scorecard
--gross-regime` runs it through the same gross path as the volatility
target; the verdict pairs each pair's payload with the gross-1 control and
with B1's best registered target. Asserted here: the rule reads t−1 and
nothing later; the probability series never changes when the future does
and every refit is an expanding window; a threshold of 1.0 reproduces the
plain run to the bit, in the scorecard's payloads and through the CLI;
and the label needs both controls.
"""

import json
import math
from dataclasses import replace

import numpy as np
import pytest

from backend.cli import market_pit_scorecard as sc
from backend.cli import market_regime_gross as cli
from backend.cli import market_vol_target as vt_cli
from backend.market import day_type, regime_gross, vol_target
from backend.tests import test_day_type as day_type_tests
from backend.tests import test_market_pit_scorecard as scorecard_tests
from backend.tests import test_vol_target as vol_target_tests

T = scorecard_tests.T
_report = scorecard_tests._report
history = vol_target_tests.history
flat_benchmark = vol_target_tests.flat_benchmark


# A synthetic probability series on the scorecard book's calendar: NaN
# for the first `undefined` sessions, `low` elsewhere, `high` on
# [hot_start, hot_end).
def _series(dates, undefined=40, low=0.05, high=0.9, hot=(100, 120)):
    p = np.full(len(dates), low)
    p[:undefined] = np.nan
    p[hot[0] : hot[1]] = high
    return regime_gross.Probability(
        np.asarray(dates),
        p,
        np.full(len(dates), 0.1),
        np.full(len(dates), np.nan),
        1,
        "hgb",
        math.nan,
        int(np.isfinite(p).sum()),
    )


# gross(t) is g_low exactly when p(t−1) is finite and at or above the
# threshold: the first session, a session after an undefined p, and every
# session under a threshold of 1.0 are the control; the combination is
# the per-session minimum with the volatility target's gross.
def test_regime_path_reads_the_previous_close():
    p = np.array([np.nan, 0.2, 0.5, 0.49, np.nan, 0.9, 0.3, 0.5])
    gross, read = regime_gross.regime_path(p, regime_gross.Spec(0.5, 0.25))
    assert np.isnan(read[0])
    assert np.array_equal(read[1:], p[:-1], equal_nan=True)
    # t=3 reads p[2]=0.5 (fires), t=4 reads 0.49 (no), t=5 reads NaN (no),
    # t=6 reads 0.9 (fires), t=7 reads 0.3 (no).
    assert gross.tolist() == [1.0, 1.0, 1.0, 0.25, 1.0, 1.0, 0.25, 1.0]
    cash, _ = regime_gross.regime_path(p, regime_gross.Spec(0.3, 0.0))
    assert cash.tolist() == [1.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    null, _ = regime_gross.regime_path(np.full(8, 0.999), regime_gross.Spec(1.0, 0.0))
    assert (null == 1.0).all()
    # The combination: min of the regime gross and min(1, σ*/σ̂).
    rng = np.random.default_rng(0)
    r = rng.normal(0.0, 0.03, size=60)
    prob = np.full(60, 0.05)
    prob[40:45] = 0.9
    spec = regime_gross.Spec(0.5, 0.5, combine_target=0.20)
    gross, read, sigma = regime_gross.gross_path(prob, spec, r)
    target, expect_sigma = vol_target.gross_path(r, vol_target.Spec(0.20))
    regime, _ = regime_gross.regime_path(prob, regime_gross.Spec(0.5, 0.5))
    assert np.array_equal(gross, np.minimum(regime, target))
    assert np.array_equal(sigma, expect_sigma, equal_nan=True)
    assert (gross[41:46] <= 0.5).all()
    with pytest.raises(ValueError, match="returns"):
        regime_gross.gross_path(prob, spec)
    with pytest.raises(ValueError, match="calendars"):
        regime_gross.gross_path(prob, spec, r[:-1])
    plain, _, none = regime_gross.gross_path(prob, regime_gross.Spec(0.5, 0.5))
    assert none is None
    assert np.array_equal(plain, regime)


# Tags, the registered set, the null, and the option parser.
def test_spec_tags_registered_and_parse():
    assert regime_gross.Spec(0.3, 0.5).tag == "rg30_g50"
    assert regime_gross.Spec(0.5, 0.0).tag == "rg50_g00"
    assert regime_gross.Spec(1.0, 0.5).tag == "rg100_g50"
    assert regime_gross.Spec(0.5, 0.5, 0.25).tag == "rg50_g50_vt25"
    assert regime_gross.Spec(0.5, 0.5, horizon=5).tag == "rg50_g50_h5_hgb"
    for pair in regime_gross.REGISTERED:
        assert regime_gross.Spec(*pair).registered
    assert not regime_gross.Spec(0.5, 0.5, 0.25).registered
    assert not regime_gross.Spec(0.4, 0.5).registered
    assert not regime_gross.Spec(0.5, 0.5, model="logistic").registered
    assert regime_gross.Spec(1.0, 0.5).is_null
    assert not regime_gross.Spec(0.5, 0.5).is_null
    assert regime_gross.Spec(0.5, 0.5).record()["registered"]
    assert regime_gross.parse_pair("0.3:0.5") == regime_gross.Spec(0.3, 0.5)
    assert regime_gross.parse_pair("0.5:0.0", 0.25).combine_target == 0.25
    for bad, why in (
        ("0.5", "THRESH:GLOW"),
        ("a:b", "THRESH:GLOW"),
        ("1.5:0.5", "lie in"),
        ("0.5:-0.1", "lie in"),
    ):
        with pytest.raises(ValueError, match=why):
            regime_gross.parse_pair(bad)


# The probability series is point in time: changing every price after a
# session changes no probability at or before it (and does change later
# ones), it is undefined before the first fit, and every refit trains on
# an expanding window of rows ending before the block it scores.
def test_tail_probability_never_reads_the_future(monkeypatch):
    from sklearn.ensemble import HistGradientBoostingClassifier

    report = day_type_tests._report(clustered=True, seed=3)
    mask = day_type_tests._mask()
    n = day_type_tests.T
    sizes = []
    real_fit = HistGradientBoostingClassifier.fit

    def spy(self, x, y, *args, **kwargs):
        sizes.append(len(x))
        return real_fit(self, x, y, *args, **kwargs)

    monkeypatch.setattr(HistGradientBoostingClassifier, "fit", spy)
    series = regime_gross.tail_probability(report, mask)
    p = series.probability
    assert len(p) == n
    assert np.isnan(p[: day_type.MIN_TRAIN]).all()
    assert np.isfinite(p[day_type.MIN_TRAIN + 70 :]).mean() > 0.95
    assert (p[np.isfinite(p)] >= 0).all()
    assert (p[np.isfinite(p)] <= 1).all()
    # Every refit is an expanding window, one per block from MIN_TRAIN.
    blocks = len(range(day_type.MIN_TRAIN, n, day_type.REFIT))
    assert len(sizes) == blocks
    assert all(a <= b for a, b in zip(sizes, sizes[1:], strict=False))
    # The rows a block's model trained on end before the block, less the
    # purge: at most start - purge rows exist to train on.
    for k, size in enumerate(sizes):
        start = day_type.MIN_TRAIN + k * day_type.REFIT
        assert size <= start - (series.horizon + 22)
    record = series.record()
    assert record["first_session"] == str(series.dates[day_type.MIN_TRAIN])
    assert record["refit_every"] == day_type.REFIT
    assert record["purge"] == 23
    assert set(record["share_at_or_above"]) == {"0.3", "0.5"}
    # Tamper with the future.
    s = 1500
    panel = report.panel
    scale = np.ones(n)[:, None]
    scale[s + 1 :] = 3.0
    tampered = replace(
        panel,
        open=panel.open * scale,
        high=panel.high * scale,
        low=panel.low * scale,
        close=panel.close * scale,
        adj_close=panel.adj_close * scale,
    )
    other = regime_gross.tail_probability(replace(report, panel=tampered), mask)
    q = other.probability
    np.testing.assert_array_equal(p[: s + 1], q[: s + 1])
    assert np.isfinite(p[s])
    later = np.isfinite(p[s + 1 :]) & np.isfinite(q[s + 1 :])
    assert later.any()
    assert not np.array_equal(p[s + 1 :][later], q[s + 1 :][later])
    # And the rule itself reads t−1: the first gross the series can move
    # is the session after the first defined probability.
    gross, _ = regime_gross.regime_path(p, regime_gross.Spec(0.0, 0.5))
    assert (gross[: day_type.MIN_TRAIN + 1] == 1.0).all()
    assert gross[day_type.MIN_TRAIN + 1] == 0.5
    # The scorecard produces the same series once per (horizon, model) and
    # keeps one it is handed.
    produced = sc.probability_series(report, mask, (regime_gross.Spec(0.5, 0.5),))
    assert set(produced) == {(1, "hgb")}
    np.testing.assert_array_equal(produced[(1, "hgb")].probability, p)
    kept = sc.probability_series(
        report, mask, (regime_gross.Spec(0.5, 0.5),), {(1, "hgb"): series}
    )
    assert kept[(1, "hgb")] is series


# The scorecard's regime run on a synthetic series: the null (threshold
# 1.0) reproduces the control on every row, pair and curve; a firing pair
# holds cash on the sessions after the hot ones, carries its record and
# the probability it read; the combination carries σ̂ beside it.
def test_scorecard_regime_specs_and_null(history, flat_benchmark):
    report = _report()
    arm = sc.ARMS["ew_graded_full"]
    series = {(1, "hgb"): _series(report.panel.dates)}
    specs = (
        regime_gross.Spec(1.0, 0.5),
        regime_gross.Spec(0.5, 0.0),
        regime_gross.Spec(0.5, 0.5, combine_target=0.05),
        vol_target.Spec(0.05),
    )
    payloads = sc.build_targets(
        report,
        object(),
        2,
        (10.0,),
        history_path=history,
        arm=arm,
        specs=specs,
        probabilities=series,
    )
    control = payloads[sc.CONTROL]
    null = payloads["rg100_g50"]
    assert null["rows"] == control["rows"]
    assert null["paired"] == control["paired"]
    assert json.dumps(null["curves"], allow_nan=True) == json.dumps(
        control["curves"], allow_nan=True
    )
    assert null["regime_gross"]["null"]
    assert "vol_target" not in null
    assert all(g == 1.0 for g in null["regime_gross"]["10"]["median_offset"]["gross"])
    assert null["probability"]["first_session"] == str(report.panel.dates[40])
    cash = payloads["rg50_g00"]
    record = cash["regime_gross"]["10"]
    at = record["median_offset"]
    dates = np.asarray(at["dates"], dtype="datetime64[D]")
    gross = np.asarray(at["gross"], dtype=float)
    read = np.asarray(at["probability"], dtype=float)
    assert "sigma_hat" not in at
    # The rule fired on the sessions after the hot ones, read at t−1.
    hot = (dates >= report.panel.dates[101]) & (dates <= report.panel.dates[120])
    assert (gross[hot] == 0.0).all()
    assert (gross[~hot] == 1.0).all()
    assert (read[hot] == 0.9).all()
    assert record["windows"]["all"]["share_in_cash"] > 0
    # The window statistic is the median across offsets (whose calendars
    # differ by a session or two), so it sits beside the median offset's own share.
    assert record["windows"]["all"]["share_below_one"] == pytest.approx(
        hot.mean(), abs=0.005
    )
    curve = cash["curves"]["10"]["lines"][sc.RULE_PIT]
    base = control["curves"]["10"]["lines"][sc.RULE_PIT]
    # In cash the book earns nothing; the control does not sit still.
    inside = [i for i, d in enumerate(cash["curves"]["10"]["dates"]) if hot[i]]
    assert all(curve[i] == 0.0 for i in inside[2:])
    assert any(base[i] != 0.0 for i in inside[2:])
    combined = payloads["rg50_g50_vt05"]
    at = combined["regime_gross"]["10"]["median_offset"]
    assert "sigma_hat" in at
    assert "probability" in at
    assert combined["regime_gross"]["combine_target"] == 0.05
    assert min(at["gross"]) < 0.5
    # A volatility target in the same run is untouched by the series.
    assert payloads["vt05"]["vol_target"]["tag"] == "vt05"
    assert "probability" not in payloads["vt05"]["vol_target"]["10"]["median_offset"]
    text = sc.render(cash)
    assert "regime gross rg50_g00" in text
    assert "gross on rule / point-in-time" in text
    with pytest.raises(ValueError, match="tail probability"):
        sc.gross_for(regime_gross.Spec(0.5, 0.5), np.zeros(T), None)


# The CLI: the regime null test passes, a pair run writes the control and
# each pair by tag with the reported combination tagged, and the options
# are checked.
def test_scorecard_cli_regime_options(history, flat_benchmark, monkeypatch, tmp_path):
    from backend.agents.trading.desk import desk

    report = _report()
    monkeypatch.setattr(desk, "run", lambda *args, **kwargs: report)
    monkeypatch.setattr(
        regime_gross,
        "tail_probability",
        lambda restricted, mask, horizon=1, model="hgb", study=None: _series(
            restricted.panel.dates
        ),
    )
    common = [
        "--root",
        str(tmp_path),
        "--graded-cap",
        "0.5",
        "--membership",
        str(history),
        "--costs",
        "10",
    ]
    assert sc.main([*common, "--gross-regime", "1.0:0.5", "--null-test"]) == 0
    out = tmp_path / "rg.json"
    assert (
        sc.main(
            [
                *common,
                "--gross-regime",
                "0.3:0.5",
                "0.5:0.0",
                "--offsets",
                "1",
                "--output",
                str(out),
            ]
        )
        == 0
    )
    assert {p.name for p in tmp_path.glob("rg_*.json")} == {
        "rg_control.json",
        "rg_rg30_g50.json",
        "rg_rg50_g00.json",
    }
    written = json.loads((tmp_path / "rg_rg30_g50.json").read_text(encoding="utf-8"))
    assert written["arm"] == "ew_graded_cap50 + rg30_g50"
    assert written["regime_gross"]["threshold"] == pytest.approx(0.3)
    assert written["regime_gross"]["registered"]
    assert written["probability"]["horizon"] == 1
    combined = tmp_path / "combo.json"
    assert (
        sc.main(
            [
                *common,
                "--gross-regime",
                "0.5:0.5",
                "--gross-regime-with-target",
                "25",
                "--offsets",
                "1",
                "--output",
                str(combined),
            ]
        )
        == 0
    )
    payload = json.loads(combined.read_text(encoding="utf-8"))
    assert payload["regime_gross"]["tag"] == "rg50_g50_vt25"
    assert not payload["regime_gross"]["registered"]
    for bad in (
        ["--gross-regime", "0.5"],
        ["--gross-regime", "1.5:0.5"],
        ["--gross-regime", "0.5:0.5", "--null-test"],
        ["--gross-regime", "0.5:0.5", "--gross-regime-with-target", "0"],
    ):
        with pytest.raises(SystemExit):
            sc.main([*common, *bad])
    with pytest.raises(SystemExit):
        sc.main(["--root", str(tmp_path), "--gross-regime", "0.5:0.5"])  # no arm


# Two synthetic controls and candidates on which the verdict is known: a
# pair that clears the gross-1 control and the vol target REPLACES; one
# that clears the control alone is RECORD (does not beat the vol target);
# one that clears neither is RECORD; the combination is REPORTED; and
# the best registered B1 target is chosen as the plan says.
def test_verdict_needs_both_controls():
    rng = np.random.default_rng(4)
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

    def payload(daily, dd, cagr, sharpe, arm):
        return {
            "arm": arm,
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
            "rows": [
                {
                    "line": vol_target.RULE_LINE,
                    "window": w,
                    "cost_bps": 25.0,
                    "median_drawdown": dd[w],
                    "median_cagr": cagr[w],
                    "median_sharpe": sharpe[w],
                    "cagrs": [cagr[w]] * 20,
                }
                for w in ("2016-2023", "2024-2026")
            ],
        }

    control = payload(
        control_daily,
        {"2016-2023": -0.40, "2024-2026": -0.25},
        {"2016-2023": 0.28, "2024-2026": 0.45},
        {"2016-2023": 0.9, "2024-2026": 1.2},
        "cap25",
    )
    vt = payload(
        control_daily * 0.7 + 0.0005,
        {"2016-2023": -0.33, "2024-2026": -0.19},
        {"2016-2023": 0.27, "2024-2026": 0.43},
        {"2016-2023": 1.0, "2024-2026": 1.3},
        "cap25 + vt25",
    )
    vt["vol_target"] = vol_target.Spec(0.25).record()

    def candidate(dd, cagr, spec, daily=None):
        out = payload(
            control_daily * 0.5 + 0.0008 if daily is None else daily,
            dd,
            cagr,
            {"2016-2023": 1.0, "2024-2026": 1.3},
            f"cap25 + {spec.tag}",
        )
        out["regime_gross"] = spec.record()
        out["regime_gross"]["25"] = {
            "windows": {
                w: {"share_below_one": 0.1} for w in ("2016-2023", "2024-2026", "all")
            }
        }
        return out

    both = candidate(
        {"2016-2023": -0.26, "2024-2026": -0.13},
        {"2016-2023": 0.27, "2024-2026": 0.43},
        regime_gross.Spec(0.5, 0.0),
    )
    reading = regime_gross.verdict(both, control, vt, trial_variance=0.01)
    assert reading["clears_control"]
    assert reading["clears_vol_target"]
    assert reading["label"] == "REPLACES"
    assert reading["against_control"]["windows"]["2016-2023"]["drawdown_gain"] == (
        pytest.approx(0.14)
    )
    assert reading["against_vol_target"]["windows"]["2016-2023"]["drawdown_gain"] == (
        pytest.approx(0.07)
    )
    assert reading["fired"] == {"2016-2023": 0.1, "2024-2026": 0.1}
    assert reading["lines"][0].startswith(
        "θ = 0.5 / g_low = 0: gross below 1 on 2016-2023 10%"
    )
    assert reading["against_control"]["trials"] == 477
    assert "cap25 + rg50_g00: paired 2016-2023" in reading["lines"][2]
    assert reading["lines"][-1].endswith("REPLACES gross 1.0 and the vol target")
    assert math.isfinite(reading["against_control"]["dsr"])
    control_only = candidate(
        {"2016-2023": -0.33, "2024-2026": -0.19},
        {"2016-2023": 0.27, "2024-2026": 0.43},
        regime_gross.Spec(0.3, 0.5),
    )
    reading = regime_gross.verdict(control_only, control, vt)
    assert reading["clears_control"]
    assert not reading["clears_vol_target"]
    assert reading["label"] == regime_gross.RECORD_VOL_TARGET
    assert reading["lines"][-1].strip() == regime_gross.RECORD_VOL_TARGET
    neither = candidate(
        {"2016-2023": -0.38, "2024-2026": -0.24},
        {"2016-2023": 0.27, "2024-2026": 0.43},
        regime_gross.Spec(0.5, 0.5),
    )
    assert regime_gross.verdict(neither, control, vt)["label"] == "RECORD"
    # A clearly negative paired difference against the vol target alone
    # (not against the control) blocks REPLACES even when the rows clear
    # both.
    losing = candidate(
        {"2016-2023": -0.26, "2024-2026": -0.13},
        {"2016-2023": 0.27, "2024-2026": 0.43},
        regime_gross.Spec(0.5, 0.0),
        daily=control_daily * 0.7 + 0.0002 + rng.normal(0.0, 0.002, size=n),
    )
    reading = regime_gross.verdict(losing, control, vt)
    assert reading["against_control"]["not_negative"]
    assert not reading["against_vol_target"]["not_negative"]
    assert reading["against_vol_target"]["drawdown_trade"]
    assert reading["label"] == regime_gross.RECORD_VOL_TARGET
    combined = candidate(
        {"2016-2023": -0.26, "2024-2026": -0.13},
        {"2016-2023": 0.27, "2024-2026": 0.43},
        regime_gross.Spec(0.5, 0.5, combine_target=0.25),
    )
    reading = regime_gross.verdict(combined, control, vt)
    assert reading["label"] == "REPORTED"
    assert "∧ σ* = 25% (reported)" in reading["lines"][0]
    # The trial variance across the registered pairs only.
    three = {"a": both, "b": control_only, "c": combined}
    assert math.isfinite(regime_gross.trial_variance(three, control))
    assert math.isnan(regime_gross.trial_variance({"a": both, "c": combined}, control))

    # The best registered B1 target: the REPLACES one with the largest
    # deciding-window drawdown gain, else the largest gain of all.
    def vt_reading(tag, label, gain, registered=True):
        return {
            "label": label,
            "vol_target": {"tag": tag, "registered": registered},
            "windows": {"2016-2023": {"drawdown_gain": gain}},
        }

    record = {
        "targets": {
            "vt20": vt_reading("vt20", "REPLACES", 0.08),
            "vt25": vt_reading("vt25", "REPLACES", 0.06),
            "vt30": vt_reading("vt30", "RECORD", 0.12),
            "vt15": vt_reading("vt15", "REPLACES", 0.20, registered=False),
        }
    }
    assert regime_gross.best_registered(record) == "vt20"
    for tag in ("vt20", "vt25"):
        record["targets"][tag]["label"] = "RECORD"
    assert regime_gross.best_registered(record) == "vt30"
    record["targets"]["vt30"]["windows"]["2016-2023"]["drawdown_gain"] = None
    assert regime_gross.best_registered(record) == "vt20"
    with pytest.raises(KeyError):
        regime_gross.best_registered({"targets": {"vt15": record["targets"]["vt15"]}})


# The verdict command: B1's verdict file names the best target, every
# candidate is paired with both controls, the verdict file carries the
# lines, and a candidate from another session is refused.
def test_verdict_cli(history, flat_benchmark, tmp_path, capsys):
    report = _report()
    arm = sc.ARMS["ew_graded_full"]
    series = {(1, "hgb"): _series(report.panel.dates)}
    specs = (
        vol_target.Spec(0.05),
        vol_target.Spec(0.08),
        regime_gross.Spec(0.5, 0.0),
        regime_gross.Spec(0.5, 0.5, combine_target=0.05),
    )
    payloads = sc.build_targets(
        report,
        object(),
        2,
        (10.0, 25.0),
        history_path=history,
        arm=arm,
        specs=specs,
        probabilities=series,
    )
    payloads[sc.CONTROL]["arm"] = "ew_graded_full"
    paths = {}
    for tag, payload in payloads.items():
        # The synthetic 5% and 8% targets stand in for the registered ones.
        if tag in ("vt05", "vt08"):
            payload["vol_target"]["registered"] = True
        paths[tag] = tmp_path / f"{tag}.json"
        paths[tag].write_text(json.dumps(payload, allow_nan=True), encoding="utf-8")
    vt_verdict = tmp_path / "vol_target_verdict.json"
    assert (
        vt_cli.main(
            [
                "--control",
                str(paths[sc.CONTROL]),
                "--targets",
                str(paths["vt05"]),
                str(paths["vt08"]),
                "--output",
                str(vt_verdict),
            ]
        )
        == 0
    )
    best = regime_gross.best_registered(json.loads(vt_verdict.read_text()))
    assert best in {"vt05", "vt08"}
    out = tmp_path / "verdict.json"
    assert (
        cli.main(
            [
                "--control",
                str(paths[sc.CONTROL]),
                "--vol-target-verdict",
                str(vt_verdict),
                "--candidates",
                str(paths["rg50_g00"]),
                str(paths["rg50_g50_vt05"]),
                "--output",
                str(out),
            ]
        )
        == 0
    )
    written = json.loads(out.read_text(encoding="utf-8"))
    assert set(written["candidates"]) == {"rg50_g00", "rg50_g50_vt05"}
    assert written["vol_target"]["tag"] == best
    assert written["sources"]["vol_target"] == str(paths[best])
    assert written["candidates"]["rg50_g00"]["label"] in {
        "REPLACES",
        "RECORD",
        regime_gross.RECORD_VOL_TARGET,
    }
    assert written["candidates"]["rg50_g50_vt05"]["label"] == "REPORTED"
    assert written["trials"] == regime_gross.TRIALS
    printed = capsys.readouterr().out
    assert f"regime gross (B2) against ew_graded_full and {best}" in printed
    for line in written["candidates"]["rg50_g00"]["lines"]:
        assert line in printed
    # Naming the target outright works too; a non-registered one is refused.
    assert (
        cli.main(
            [
                "--control",
                str(paths[sc.CONTROL]),
                "--vol-target",
                str(paths[best]),
                "--candidates",
                str(paths["rg50_g00"]),
                "--output",
                str(tmp_path / "v2.json"),
            ]
        )
        == 0
    )
    with pytest.raises(SystemExit):
        cli.main(
            [
                "--control",
                str(paths[sc.CONTROL]),
                "--vol-target",
                str(paths["rg50_g00"]),
                "--candidates",
                str(paths["rg50_g00"]),
            ]
        )
    stale = json.loads(paths["rg50_g00"].read_text(encoding="utf-8"))
    stale["asof"] = "2000-01-01"
    (tmp_path / "stale.json").write_text(json.dumps(stale, allow_nan=True))
    with pytest.raises(SystemExit):
        cli.main(
            [
                "--control",
                str(paths[sc.CONTROL]),
                "--vol-target",
                str(paths[best]),
                "--candidates",
                str(tmp_path / "stale.json"),
            ]
        )
