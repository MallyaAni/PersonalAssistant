"""Volatility sizing: the weights of every variant, the control's identity with policy_v4, no lookahead, the verdict, the command.

On hand-built inputs the inverse-volatility weights are proportional to
1 / sigma, sum to the control's total, respect the cap by water-filling
and leave a name without a sigma at the control's weight (counted); the
volatility target scales exposure to min(1, target / predicted) and never
above 1; the hybrid composes them. The control's allocator is `policy_v4`
element for element and its simulated curve is `simulate.run` with
`policy_v4.allocator` under the plain and the live options. The sizer at
decision t reads only row t of the aligned forecasts. The verdict applies
its floors on hand-built payloads (adopt; record for too few points; record
labelled inverse vol when the trailing twin matches; record for a worse
drawdown). The command runs end to end on the pit fixture with a synthetic
forecast file.
"""

import io
import json
import math

import numpy as np
import pytest

from backend.agents.trading.desk import paper, point_in_time, policy_v4, simulate
from backend.cli import market_pit_scorecard as sc
from backend.cli import market_vol_sizing as cli
from backend.market import vol_forecast as vf
from backend.market import vol_sizing as vs
from backend.tests.test_market_pit_scorecard import (  # noqa: F401 - fixture
    NAMES,
    _report,
    history,
)

FORECAST_VARIANTS = tuple(v for v in vs.VARIANTS if v.source == vs.FORECAST)
SIZED = tuple(v for v in vs.VARIANTS if v.scheme is not None)


# Synthetic forecasts for every (session, name) of the fixture's panel: log
# variance around a 2% session volatility with a persistent per-name level
# (so inverse volatility has something to tilt), the baseline a noisier
# version and the realized value the forecast plus noise. `skip_names` get
# no row at all (the fallback case); `first` is the first session with a
# forecast (NaN before, as before the first fit).
def _forecasts(
    panel, seed: int = 0, skip_names: tuple[str, ...] = (), first: int = 0
) -> vf.Forecasts:
    rng = np.random.default_rng(seed)
    names = [t for t in panel.tickers if t != panel.benchmark and t not in skip_names]
    level = {t: math.log(0.0004) + rng.normal(0, 0.5) for t in names}
    dates, tickers, forecast, baseline, realized = [], [], [], [], []
    for i, d in enumerate(panel.dates):
        for t in names:
            dates.append(d)
            tickers.append(t)
            f = level[t] + rng.normal(0, 0.2)
            forecast.append(f if i >= first else np.nan)
            baseline.append(level[t] + rng.normal(0, 0.4))
            realized.append(f + rng.normal(0, 0.3))
    return vf.Forecasts(
        np.array(dates, dtype="datetime64[D]"),
        np.array(tickers),
        np.array(forecast),
        np.array(baseline),
        np.array(realized),
        {"model": "synthetic"},
    )


# The fixture's restricted report, mask and aligned synthetic forecasts.
def _setup(history, **kwargs):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    aligned = vf.align(_forecasts(report.panel, **kwargs), report.panel.dates, report.panel.tickers)
    return report, restricted, mask, aligned


# The variant set is fixed and named: the control first, then each scheme
# fed the forecast and fed the trailing baseline, every forecast variant
# naming its trailing twin, six trials.
def test_variants_are_registered_and_named():
    names = [v.name for v in vs.VARIANTS]
    assert len(names) == len(set(names)) == 7
    assert names[0] == vs.CONTROL and vs.variant(vs.CONTROL).scheme is None
    assert [(v.scheme, v.source) for v in SIZED] == [
        (vs.INV_VOL, vs.FORECAST),
        (vs.INV_VOL, vs.TRAILING),
        (vs.VOL_TARGET, vs.FORECAST),
        (vs.VOL_TARGET, vs.TRAILING),
        (vs.HYBRID, vs.FORECAST),
        (vs.HYBRID, vs.TRAILING),
    ]
    for v in FORECAST_VARIANTS:
        twin = vs.variant(v.twin)
        assert twin.scheme == v.scheme and twin.source == vs.TRAILING and twin.twin is None
    with pytest.raises(KeyError):
        vs.variant("nothing")
    assert vs.CAP == policy_v4.HOLD_CAP == 0.20
    with pytest.raises(ValueError, match="unknown option set"):
        vs.options_for("fast", None)


# Water-filling: proportional when nothing hits the cap; a name over the
# cap is fixed at it and the rest shared among the others; when every name
# is at the cap the sum falls short (cash); zeros stay zero.
def test_cap_and_renormalise():
    w = vs.cap_and_renormalise(np.array([1.0, 1.0, 2.0]), 0.4, 0.20)
    np.testing.assert_allclose(w, [0.1, 0.1, 0.2])
    w = vs.cap_and_renormalise(np.array([1.0, 1.0, 8.0]), 0.5, 0.20)
    assert w[2] == pytest.approx(0.20)
    np.testing.assert_allclose(w[:2], [0.15, 0.15])
    assert w.sum() == pytest.approx(0.5)
    w = vs.cap_and_renormalise(np.array([1.0, 1.0, 1.0, 0.0]), 1.0, 0.20)
    np.testing.assert_allclose(w, [0.2, 0.2, 0.2, 0.0])
    assert vs.cap_and_renormalise(np.array([1.0, 2.0]), 0.0, 0.2).tolist() == [0.0, 0.0]
    assert vs.cap_and_renormalise(np.array([np.nan, 0.0]), 1.0, 0.2).tolist() == [0.0, 0.0]


# Each scheme's weights on hand-built inputs: the sum, the cap, the fallback.
def test_size_weights_per_scheme():
    # Six names at 10% (the real book's shape: below the 20% cap, cash spare),
    # the benchmark last; the fifth name has no sigma.
    control = np.array([0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.0])
    sig = np.array([0.01, 0.02, 0.04, 0.04, 0.04, np.nan, 0.03])
    have = np.isfinite(sig) & (control > 0)
    # Inverse volatility: proportional to 1 / sigma over the names with one,
    # summing to their share of the control's total (0.5), the 1% name
    # capped at 0.20 and the rest shared 50:25:25:25; the name without a
    # sigma keeps 0.1 and counts as the one fallback; the benchmark stays 0.
    w, positions, fallbacks = vs.size_weights(vs.INV_VOL, control, sig, math.nan)
    assert (positions, fallbacks) == (6, 1)
    assert w[5] == 0.1 and w[6] == 0.0
    np.testing.assert_allclose(w[:5], [0.20, 0.12, 0.06, 0.06, 0.06])
    assert w[have].sum() == pytest.approx(0.5)
    assert w.sum() == pytest.approx(control.sum())
    assert w.max() <= vs.CAP + 1e-9
    # Uncapped: exact proportionality.
    w, _, _ = vs.size_weights(
        vs.INV_VOL, np.array([0.1, 0.1, 0.1, 0.0]), np.array([0.02, 0.04, 0.04, 0.03]), math.nan
    )
    np.testing.assert_allclose(w[:3], [0.15, 0.075, 0.075])
    # Volatility target: the control's weights scaled by min(1, target /
    # predicted); predicted is sum(w sigma) over the names with a sigma.
    predicted = 0.1 * (0.01 + 0.02 + 0.04 * 3)
    w, positions, fallbacks = vs.size_weights(vs.VOL_TARGET, control, sig, predicted / 2)
    assert (positions, fallbacks) == (6, 1)
    np.testing.assert_allclose(w[:5], [0.05] * 5)
    assert w[5] == 0.1  # the fallback name is not scaled
    assert vs.book_vol(np.where(have, w, 0.0), sig) == pytest.approx(predicted / 2)
    # No leverage: a target above the prediction leaves the control alone.
    w, _, _ = vs.size_weights(vs.VOL_TARGET, control, sig, predicted * 3)
    np.testing.assert_array_equal(w, control)
    # Hybrid: inverse volatility, then the scale on the sized book.
    inv, _, _ = vs.size_weights(vs.INV_VOL, control, sig, math.nan)
    inv_predicted = vs.book_vol(np.where(have, inv, 0.0), sig)
    assert inv_predicted == pytest.approx(0.2 * 0.01 + 0.12 * 0.02 + 0.18 * 0.04)
    w, _, _ = vs.size_weights(vs.HYBRID, control, sig, inv_predicted / 4)
    np.testing.assert_allclose(w[:5], inv[:5] / 4)
    assert w[5] == 0.1
    # No sigma anywhere: the control, every position a fallback.
    w, positions, fallbacks = vs.size_weights(vs.INV_VOL, control, np.full(7, np.nan), math.nan)
    np.testing.assert_array_equal(w, control)
    assert (positions, fallbacks) == (6, 6)
    # An empty control stays empty.
    w, positions, fallbacks = vs.size_weights(vs.HYBRID, np.zeros(7), sig, 0.01)
    assert w.sum() == 0 and (positions, fallbacks) == (0, 0)
    with pytest.raises(ValueError, match="unknown scheme"):
        vs.size_weights("equal", control, sig, 0.01)
    with pytest.raises(ValueError, match="volatility target"):
        vs.size_weights(vs.VOL_TARGET, control, sig, math.nan)
    assert math.isnan(vs.ratio(0.2, 0.0)) and vs.ratio(0.2, -0.4) == pytest.approx(0.5)


# The control's allocator is policy_v4 element for element on every
# session of the fixture, and its curve is `simulate.run` with
# `policy_v4.allocator` under the plain and under the live options.
def test_control_is_policy_v4(history):
    report, restricted, mask, aligned = _setup(history)
    panel = restricted.panel
    sizer = vs.Sizer(vs.variant(vs.CONTROL), mask, aligned, math.nan)
    base = policy_v4.allocator(mask)
    for t in range(len(panel.dates)):
        np.testing.assert_array_equal(
            sizer.allocate(restricted, panel, None, t), base(restricted, panel, None, t)
        )
    assert (sizer.fallbacks[np.isfinite(sizer.fallbacks)] == 0).all()
    since = sc._since(panel, 1)
    for option_set in vs.OPTION_SETS:
        run = vs.price(restricted, mask, vs.variant(vs.CONTROL), option_set, since, 10.0, aligned, math.nan)
        direct = simulate.run(
            restricted,
            since=since,
            cost_bps=10.0,
            allocator=base,
            **vs.options_for(option_set, panel),
        )
        np.testing.assert_array_equal(run.curve.dates, direct.dates)
        np.testing.assert_array_equal(run.curve.daily, direct.returns)
        assert run.option_set == option_set
    assert vs.options_for(vs.PLAIN, panel) == dict(use_exits=False, rebalance=paper.REBALANCE_EVERY)
    assert vs.options_for(vs.LIVE, panel)["exit_at_close"] is True


# No lookahead: the sizer at decision t reads only row t of the aligned
# forecasts - changing every other row leaves its weights unchanged, and
# changing row t changes them. Every sized variant keeps the control's
# names, its cap and (inverse volatility) its total.
def test_sizer_reads_only_row_t_and_keeps_the_book(history):
    report, restricted, mask, aligned = _setup(history)
    panel = restricted.panel
    weights = vs.control_weights(restricted, mask)
    target = vs.measure_vol_target(weights, aligned)
    assert np.isfinite(target["target"]) and target["source"] == "realized"
    assert target["sessions"] > 0 and target["window"] == vs.CHOOSING
    t = 100
    control = policy_v4.allocator(mask)(restricted, panel, None, t)
    assert (control > 0).sum() >= 3
    for v in SIZED:
        sizer = vs.Sizer(v, mask, aligned, target["target"])
        w = sizer.allocate(restricted, panel, None, t)
        assert ((w > 0) == (control > 0)).all()
        assert w.max() <= vs.CAP + 1e-9
        assert w.sum() <= control.sum() + 1e-9
        if v.scheme == vs.INV_VOL:
            # The fixture's five names sit at the cap already, so inverse
            # volatility has no room to tilt: the sum and the book are the
            # control's (the tilt itself is tested on hand-built inputs).
            assert w.sum() == pytest.approx(control.sum())
            np.testing.assert_allclose(w, control)
        assert sizer.fallbacks[t] == 0 and sizer.positions[t] == (control > 0).sum()
        assert sizer.exposure[t] == pytest.approx(w.sum())
        # Every other row tampered: the same weights.
        tampered = np.array(aligned.forecast)
        tampered_b = np.array(aligned.baseline)
        others = np.arange(len(panel.dates)) != t
        tampered[others] += 3.0
        tampered_b[others] += 3.0
        other = vf.Aligned(aligned.dates, aligned.tickers, tampered, tampered_b, aligned.realized)
        w2 = vs.Sizer(v, mask, other, target["target"]).allocate(restricted, panel, None, t)
        np.testing.assert_array_equal(w2, w)
        # Row t tampered (a higher volatility everywhere): different weights
        # for the target schemes, and the tilt moved for inverse volatility.
        tampered = np.array(aligned.forecast)
        tampered_b = np.array(aligned.baseline)
        tampered[t] += np.linspace(0.0, 2.0, tampered.shape[1])
        tampered_b[t] += np.linspace(0.0, 2.0, tampered.shape[1])
        own = vf.Aligned(aligned.dates, aligned.tickers, tampered, tampered_b, aligned.realized)
        w3 = vs.Sizer(v, mask, own, target["target"]).allocate(restricted, panel, None, t)
        if v.scheme != vs.INV_VOL:
            assert not np.array_equal(w3, w)
    # A name with no forecast keeps the control's weight and is counted.
    _, restricted2, mask2, partial = _setup(history, skip_names=("AAA",))
    sizer = vs.Sizer(vs.variant("inv-vol-forecast"), mask2, partial, math.nan)
    w = sizer.allocate(restricted2, panel, None, t)
    a = panel.index("AAA")
    assert control[a] > 0 and w[a] == control[a]
    assert sizer.fallbacks[t] == 1
    # Before the first fit every position falls back and the book is the control.
    _, restricted3, mask3, late = _setup(history, first=200)
    sizer = vs.Sizer(vs.variant("inv-vol-forecast"), mask3, late, math.nan)
    np.testing.assert_array_equal(sizer.allocate(restricted3, panel, None, 50), control)
    assert sizer.fallbacks[50] == sizer.positions[50] == (control > 0).sum()
    with pytest.raises(ValueError, match="volatility target"):
        vs.Sizer(vs.variant("vol-target-forecast"), mask, aligned, math.nan)
    with pytest.raises(ValueError, match="sigma source"):
        vs.Sizer(vs.Variant("odd", vs.INV_VOL, "guess"), mask, aligned, 0.01)


# The volatility target is measured on the control's book from the
# realized column over the choosing window's complete sessions, and falls
# back to the baseline when the file carries no realized values.
def test_measure_vol_target(history):
    report, restricted, mask, aligned = _setup(history)
    weights = vs.control_weights(restricted, mask)
    sig = vf.sigma(aligned.realized)
    keep = point_in_time.window(aligned.dates, *sc.WINDOWS[vs.CHOOSING])
    expected = [
        vs.book_vol(weights[t], sig[t])
        for t in np.flatnonzero(keep)
        if (weights[t] > 0).any() and np.isfinite(sig[t][weights[t] > 0]).all()
    ]
    info = vs.measure_vol_target(weights, aligned)
    assert info["target"] == pytest.approx(float(np.median(expected)))
    assert info["sessions"] == len(expected) and info["sessions_in_window"] == int(keep.sum())
    without = vf.Aligned(aligned.dates, aligned.tickers, aligned.forecast, aligned.baseline, None)
    info = vs.measure_vol_target(weights, without)
    assert info["source"] == "baseline" and np.isfinite(info["target"])
    # No realized values anywhere: NaN, and the target variants are refused.
    empty = vf.Aligned(aligned.dates, aligned.tickers, aligned.forecast, aligned.baseline, np.full_like(aligned.forecast, np.nan))
    info = vs.measure_vol_target(weights, empty)
    assert math.isnan(info["target"]) and info["sessions"] == 0


# The payload holds every variant under both option sets on every window
# at every cost, pairs every sized variant against the control under the
# same options and every forecast variant against its twin, and records
# the target and the coverage.
def test_run_variants_payload(history):
    report, restricted, mask, aligned = _setup(history, first=30)
    payload = vs.run_variants(report, restricted, mask, None, 2, (10.0, 25.0), aligned)
    names = {v.name for v in vs.VARIANTS}
    assert payload["study"] == "vol_sizing" and payload["trials"] == 6
    assert payload["policy"] == policy_v4.POLICY_VERSION
    assert payload["refused"] == {}
    assert payload["ran"] == [vs.key(v.name, o) for o in vs.OPTION_SETS for v in vs.VARIANTS]
    assert np.isfinite(payload["vol_target"]["target"])
    assert payload["forecast_coverage"]["first_session_with_forecast"] == str(report.panel.dates[30])
    assert 0 < payload["forecast_coverage"]["held_cells"] < 1
    assert len(payload["rows"]) == 7 * 2 * len(sc.WINDOWS) * 2
    for row in payload["rows"]:
        assert row["offsets"] == 2 and row["options"] in vs.OPTION_SETS
        assert {
            "median_cagr",
            "median_drawdown",
            "ratio",
            "median_exposure",
            "fallback_share",
            "offsets_above_control",
            "sessions",
        } <= set(row)
    control_rows = [r for r in payload["rows"] if r["line"] == vs.CONTROL]
    assert all(r["offsets_above_control"] == 0 for r in control_rows)
    assert all(r["fallback_share"] == 0 or r["fallback_share"] != r["fallback_share"] for r in control_rows)
    assert all(r["median_exposure"] <= 1.0 + 1e-9 for r in payload["rows"] if np.isfinite(r["median_exposure"]))
    # Fallback share on the "all" window under plain options is positive
    # for the forecast variants (the first 30 sessions have no forecast)
    # and zero for the trailing ones (the baseline covers every session).
    for v in SIZED:
        row = next(r for r in payload["rows"] if r["line"] == v.name and r["window"] == "all" and r["options"] == vs.PLAIN and r["cost_bps"] == 10.0)
        if v.source == vs.FORECAST:
            assert row["fallback_share"] > 0
        else:
            assert row["fallback_share"] == 0
    pairs = {(p["line"], p["against"], p["options"]) for p in payload["paired"]}
    expected = {(n, vs.CONTROL, o) for n in names - {vs.CONTROL} for o in vs.OPTION_SETS}
    expected |= {(v.name, v.twin, o) for v in FORECAST_VARIANTS for o in vs.OPTION_SETS}
    assert pairs == expected
    for p in payload["paired"]:
        assert {"mean_daily_bp", "hac_t", "psr", "sessions"} <= set(p)
    verdict = vs.verdict(payload)
    assert set(verdict["variants"]) == {v.name for v in SIZED}
    assert all(
        info["decision"] in (vs.ADOPT, vs.RECORD, vs.INVERSE_VOL)
        for info in verdict["variants"].values()
    )
    assert all(info["decision"] == vs.RECORD for n, info in verdict["variants"].items() if vs.variant(n).source == vs.TRAILING)
    assert verdict["options"] == vs.LIVE and verdict["cost_bps"] == 25.0
    # A NaN target refuses the target variants, records them, and the rest run.
    empty = vf.Aligned(aligned.dates, aligned.tickers, aligned.forecast, aligned.baseline, np.full_like(aligned.forecast, np.nan))
    payload = vs.run_variants(report, restricted, mask, None, 1, (25.0,), empty)
    refused = set(payload["refused"])
    assert refused == {vs.key(v.name, o) for v in SIZED if v.scheme in (vs.VOL_TARGET, vs.HYBRID) for o in vs.OPTION_SETS}
    assert {r["line"] for r in payload["rows"]} == {vs.CONTROL, "inv-vol-forecast", "inv-vol-trailing"}
    verdict = vs.verdict(payload)
    assert verdict["variants"]["vol-target-forecast"]["refused"].startswith("refused")
    assert verdict["variants"]["vol-target-forecast"]["decision"] == vs.RECORD


# A payload with the given live choosing-window CAGR and drawdown per
# variant, the paired t against the control, and the reported paired bp,
# at 25 bp; plain rows carry the same numbers.
def _payload(
    cagr: dict[str, float],
    drawdown: dict[str, float] | None = None,
    t: dict[str, float] | None = None,
    reported_bp: dict[str, float] | None = None,
) -> dict:
    drawdown = drawdown or {}
    t = t or {}
    reported_bp = reported_bp or {}
    rows, paired = [], []
    for option_set in vs.OPTION_SETS:
        for name, c in cagr.items():
            dd = drawdown.get(name, -0.30)
            for window in (vs.CHOOSING, vs.REPORTED, "all"):
                rows.append(
                    {
                        "line": name,
                        "options": option_set,
                        "cost_bps": 25.0,
                        "window": window,
                        "median_cagr": c,
                        "median_drawdown": dd,
                        "ratio": vs.ratio(c, dd),
                        "fallback_share": 0.1,
                        "median_exposure": 1.0,
                    }
                )
            if name != vs.CONTROL:
                paired.append(
                    {"line": name, "against": vs.CONTROL, "options": option_set, "cost_bps": 25.0, "window": vs.CHOOSING, "mean_daily_bp": 1.0, "hac_t": t.get(name, 3.0)}
                )
                paired.append(
                    {"line": name, "against": vs.CONTROL, "options": option_set, "cost_bps": 25.0, "window": vs.REPORTED, "mean_daily_bp": reported_bp.get(name, 0.5), "hac_t": 1.0}
                )
    return {"costs_bps": [10.0, 25.0], "rows": rows, "paired": paired, "refused": {}, "vol_target": {"target": 0.02}}


# The verdict's floors on hand-built payloads: adopt when every floor is
# cleared; record when the points are short; record labelled inverse vol
# when the trailing twin is within half a point; record when the drawdown
# is worse or the reported window is worse; not measured without a control.
def test_verdict_rules_on_hand_built_payloads():
    base = {v.name: 0.25 for v in vs.VARIANTS}
    # Adopt: inv-vol-forecast +2 points, twin +0.5 only, t 3, drawdown equal.
    v = vs.verdict(_payload({**base, "inv-vol-forecast": 0.27, "inv-vol-trailing": 0.255}))
    assert v["variants"]["inv-vol-forecast"]["decision"] == vs.ADOPT
    assert v["adopt"] == ["inv-vol-forecast"] and v["inverse_vol"] == []
    assert v["variants"]["inv-vol-forecast"]["live"]["choosing_points"] == pytest.approx(2.0)
    assert v["variants"]["inv-vol-forecast"]["live"]["twin_points"] == pytest.approx(1.5)
    assert v["variants"]["inv-vol-trailing"]["decision"] == vs.RECORD
    assert v["text"].startswith("2016-2023 at 25 bp under live options") and vs.ADOPT in v["text"]
    assert v["control_cagr"] == 0.25 and v["vol_target"] == 0.02
    # Record for cost: +0.9 points is under the floor.
    v = vs.verdict(_payload({**base, "inv-vol-forecast": 0.259}))
    assert v["variants"]["inv-vol-forecast"]["decision"] == vs.RECORD
    assert not v["variants"]["inv-vol-forecast"]["live"]["passes_points"]
    assert "every variant is RECORD" in v["text"]
    # Record because the trailing twin matches: +2 points, twin +1.7.
    v = vs.verdict(_payload({**base, "hybrid-forecast": 0.27, "hybrid-trailing": 0.267}))
    assert v["variants"]["hybrid-forecast"]["decision"] == vs.INVERSE_VOL
    assert v["variants"]["hybrid-forecast"]["passes_floors_live"] is True
    assert v["inverse_vol"] == ["hybrid-forecast"] and v["adopt"] == []
    assert "inverse vol, not the forecast" in v["text"]
    # Exactly half a point over the twin is enough.
    v = vs.verdict(_payload({**base, "hybrid-forecast": 0.27, "hybrid-trailing": 0.265}))
    assert v["variants"]["hybrid-forecast"]["decision"] == vs.ADOPT
    # Record for t under 2.
    v = vs.verdict(_payload({**base, "inv-vol-forecast": 0.27}, t={"inv-vol-forecast": 1.5}))
    assert v["variants"]["inv-vol-forecast"]["decision"] == vs.RECORD
    # Record for a worse drawdown.
    v = vs.verdict(_payload({**base, "inv-vol-forecast": 0.27}, drawdown={"inv-vol-forecast": -0.35}))
    assert v["variants"]["inv-vol-forecast"]["decision"] == vs.RECORD
    assert not v["variants"]["inv-vol-forecast"]["live"]["drawdown_not_worse"]
    # A shallower drawdown is not worse.
    v = vs.verdict(_payload({**base, "inv-vol-forecast": 0.27}, drawdown={"inv-vol-forecast": -0.25}))
    assert v["variants"]["inv-vol-forecast"]["decision"] == vs.ADOPT
    # Record for a worse reported window.
    v = vs.verdict(_payload({**base, "inv-vol-forecast": 0.27}, reported_bp={"inv-vol-forecast": -0.2}))
    assert v["variants"]["inv-vol-forecast"]["decision"] == vs.RECORD
    # Not measured without a control row.
    v = vs.verdict({"costs_bps": [25.0], "rows": [], "paired": [], "refused": {}})
    assert v["text"].startswith("not measured") and v["adopt"] == []
    # Without 25 bp the verdict reads the highest cost.
    p = _payload({**base, "inv-vol-forecast": 0.27})
    for r in p["rows"]:
        r["cost_bps"] = 10.0
    for r in p["paired"]:
        r["cost_bps"] = 10.0
    p["costs_bps"] = [5.0, 10.0]
    assert vs.verdict(p)["cost_bps"] == 10.0


# The command end to end on the synthetic book with a synthetic forecast
# file: the file written, the payload shape, both option sets, the target,
# the verdict and the tables; `--json` prints the payload; a missing
# forecast file is exit 1.
def test_cli_end_to_end(history, tmp_path):
    report = _report()
    forecasts = tmp_path / "vol_forecasts.npz"
    vf.save_forecasts(forecasts, _forecasts(report.panel, first=40))
    calls = []

    def fake_desk(store):
        calls.append(str(store.root))
        return report

    out = io.StringIO()
    args = cli.build_parser().parse_args(
        ["--root", str(tmp_path), "--membership", str(history), "--forecasts", str(forecasts), "--offsets", "2", "--costs", "25"]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    assert calls == [str(tmp_path)]
    target = tmp_path / "desk" / "vol_sizing.json"
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["study"] == "vol_sizing" and payload["policy"] == policy_v4.POLICY_VERSION
    assert payload["trials"] == 6 and len(payload["variants"]) == 7
    assert payload["offsets"] == 2 and payload["costs_bps"] == [25.0]
    assert payload["option_sets"] == ["plain", "live"]
    assert len(payload["rows"]) == 7 * 2 * 3
    assert payload["membership_history"] == str(history)
    assert payload["forecast_file"] == str(forecasts)
    assert payload["forecast_meta"] == {"model": "synthetic"}
    assert payload["vol_target"]["target"] is not None
    verdict = payload["verdict"]
    assert verdict["cost_bps"] == 25.0 and verdict["options"] == "live"
    assert set(verdict["variants"]) == {v.name for v in SIZED}
    text = out.getvalue()
    assert "volatility sizing for graded-equal-weight/4" in text
    assert "6 registered variants" in text and "volatility target" in text
    assert "plain options, 25 bp, 2016-2023" in text and "live options, 25 bp, 2016-2023" in text
    assert "inv-vol-forecast" in text and "hybrid-trailing" in text and "verdict:" in text
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        ["--root", str(tmp_path), "--membership", str(history), "--forecasts", str(forecasts), "--offsets", "1", "--costs", "10", "--json"]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 0
    printed = json.loads(out.getvalue())
    assert printed["offsets"] == 1 and printed["verdict"]["cost_bps"] == 10.0
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        ["--root", str(tmp_path), "--forecasts", str(tmp_path / "missing.npz")]
    )
    assert cli.run(args, out, desk_run=fake_desk) == 1 and "not found" in out.getvalue()
