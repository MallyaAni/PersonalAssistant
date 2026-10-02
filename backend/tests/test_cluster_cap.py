"""The peer-cluster exposure cap (R1): clusters, cap, allocator, null test, CLI.

A synthetic book of six names and SPY: AAA, BBB and CCC share a strong
common factor beyond the market (they must cluster), DDD, EEE and FFF move
on their own. Every name is graded A+, so `/5` holds each at 1/6 and the
AAA-BBB-CCC cluster carries 50% - over a 35% cap, under a 50% one. The
plan is `docs/research/cluster-cap-plan-2026-10-02.md`.
"""

import json
import math
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from backend.agents.trading.desk import grading, point_in_time, regime, simulate
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_cluster_cap as cli
from backend.cli import market_pit_scorecard as sc
from backend.market import benchmarks
from backend.market import cluster_cap as cc
from backend.market import peer_groups as pg
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE

NAMES = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
T = 320
SPY = 6
CHECK = (
    Path(__file__).resolve().parents[2]
    / "docs/research/scorecards/cluster-cap/cluster_cap_check.py"
)


# Closes for the synthetic book: SPY a random walk, every name its beta
# on SPY plus noise; AAA-CCC also carry one shared factor three times the
# size of their own noise, so their SPY-residual correlation is about 0.9.
def _closes(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    market = rng.normal(0.0004, 0.01, size=T)
    factor = rng.normal(0.0, 0.015, size=T)
    out = np.empty((T, len(NAMES) + 1))
    for i in range(len(NAMES)):
        own = rng.normal(0.0003, 0.005 if i < 3 else 0.015, size=T)
        out[:, i] = market * 1.1 + (factor if i < 3 else 0.0) + own
    out[:, SPY] = market
    return 100.0 * np.exp(out.cumsum(axis=0))


# A desk report on given closes with every name graded A+.
def _report(close: np.ndarray | None = None) -> DeskReport:
    close = _closes() if close is None else close
    n = len(NAMES)
    days, d = [], date(2023, 1, 2)
    while len(days) < T:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    panel = Panel(
        dates=np.array(days, dtype="datetime64[D]"),
        tickers=NAMES + ("SPY",),
        open=close * 0.999,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: (AI_COMPUTE,) for t in NAMES},
        benchmark="SPY",
    )
    grades = np.full((T, n + 1), grading.ORDINAL["A+"], dtype=int)
    grades[:, n] = 0
    conviction = np.tile(np.array([0.8, 0.7, 0.6, 0.5, 1.0, 0.9, np.nan]), (T, 1))
    graded = grading.Graded(grades, conviction.copy(), {}, conviction)
    state = regime.RegimeState(
        0.0, 0.0, 0.5, 0.0, 0.0, 0.0, "ai", 0.1, 0.0, 1.0, 1.0, (), 0.0, False
    )
    view = regime.RegimeView(
        [state] * T, Opinion("rotation", np.full((T, n + 1), np.nan))
    )
    return DeskReport(
        panel, {t: "ai" for t in NAMES}, {}, view, graded, graded.as_scores(), []
    )


# A membership history with every name a member throughout.
@pytest.fixture
def history(tmp_path):
    path = tmp_path / "membership_history.csv"
    rows = ["ticker,entered,entry_announced,exited,exit_announced,source,rule"]
    for t in NAMES:
        rows.append(f"{t},2016-01-04,2016-01-04,,,test,member throughout")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# The residual correlations are peer_groups' own: the k best peers and
# their correlations computed by `session_peers` are read back from the
# matrix, and the factor names correlate far above the others.
def test_residual_corr_is_peer_groups_matrix():
    close = _closes()
    t = 200
    corr = cc.residual_corr(close, SPY, range(len(NAMES)), t)
    returns, masked, mkt, ok = pg.prepare(close, SPY)
    members, peer_corr, has = pg.session_peers(
        masked[t - 59 : t + 1], mkt[t - 59 : t + 1], ok[t], k=3
    )
    for i in range(len(NAMES)):
        assert has[i]
        for j, c in zip(members[i], peer_corr[i], strict=True):
            assert corr[i, j] == pytest.approx(c, abs=1e-12)
    assert corr[0, 1] > 0.8
    assert corr[1, 2] > 0.8
    assert corr[0, 2] > 0.8
    assert abs(corr[3, 4]) < 0.4
    assert abs(corr[0, 5]) < 0.4
    # Too early for a 60-session window: nothing is defined.
    assert np.isnan(cc.residual_corr(close, SPY, [0, 1], 59)).all()
    assert np.isfinite(cc.residual_corr(close, SPY, [0, 1], 60)).all()


# A name with a missing close inside the window has no correlation and is
# its own cluster; a missing market return leaves everything undefined.
def test_missing_prices_leave_a_name_alone():
    close = _closes()
    close[180, 1] = np.nan
    corr = cc.residual_corr(close, SPY, [0, 1, 2], 200)
    assert np.isnan(corr[1]).all()
    assert np.isnan(corr[:, 1]).all()
    assert np.isfinite(corr[np.ix_([0, 2], [0, 2])]).all()
    assert cc.average_linkage(corr, 0.6) == [[0, 2], [1]]
    close[190, SPY] = np.nan
    assert np.isnan(cc.residual_corr(close, SPY, [0, 2], 200)).all()


# Point in time: changing every price after t leaves t's correlations,
# clusters and capped targets unchanged; changing a price inside the
# window changes them.
def test_clustering_is_point_in_time(history):
    t = 200
    close = _closes()
    weights = np.r_[np.full(6, 1 / 6), 0.0]
    before = cc.cap_session(close, SPY, weights, t, cc.REGISTERED[0])
    tampered = close.copy()
    rng = np.random.default_rng(9)
    tampered[t + 1 :] *= np.exp(rng.normal(0, 0.2, size=tampered[t + 1 :].shape))
    after = cc.cap_session(tampered, SPY, weights, t, cc.REGISTERED[0])
    assert np.array_equal(before[0], after[0])
    assert before[1] == after[1]
    assert np.array_equal(before[2], after[2], equal_nan=True)
    # Through the allocator, on the report the simulator would see.
    report, other = _report(close), _report(tampered)
    restricted, mask = point_in_time.point_in_time(report, history)
    restricted2, mask2 = point_in_time.point_in_time(other, history)
    arm = cc.capped_arm(cli.base_arm(), cc.REGISTERED[0])
    a = arm(restricted, mask)(restricted, restricted.panel, None, t)
    b = arm(restricted2, mask2)(restricted2, restricted2.panel, None, t)
    assert np.array_equal(a, b)
    # A change at t itself is inside the window and is read.
    moved = close.copy()
    moved[t, 0] *= 1.3
    changed = cc.cap_session(moved, SPY, weights, t, cc.REGISTERED[0])
    assert not np.array_equal(changed[2], before[2], equal_nan=True)


# Average linkage on a known matrix: two blocks merge inside themselves at
# 0.6, the weak bridge does not; at 0.3 the bridge's average decides.
def test_average_linkage_cuts_at_rho():
    corr = np.array(
        [
            [1.0, 0.9, 0.7, 0.1, 0.0],
            [0.9, 1.0, 0.65, 0.5, 0.0],
            [0.7, 0.65, 1.0, 0.2, 0.0],
            [0.1, 0.5, 0.2, 1.0, 0.8],
            [0.0, 0.0, 0.0, 0.8, 1.0],
        ]
    )
    assert cc.average_linkage(corr, 0.6) == [[0, 1, 2], [3, 4]]
    # {0,1,2} to {3,4}: mean of 0.1, 0.0, 0.5, 0.0, 0.2, 0.0 = 0.133.
    assert cc.average_linkage(corr, 0.14) == [[0, 1, 2], [3, 4]]
    assert cc.average_linkage(corr, 0.13) == [[0, 1, 2, 3, 4]]
    assert cc.average_linkage(corr, 0.95) == [[0], [1], [2], [3], [4]]
    # Average, not single, linkage: 2 joins {0,1} at the average 0.675, and
    # would not at 0.68 even though its best link (0.7) is above it.
    assert cc.average_linkage(corr, 0.68) == [[0, 1], [2], [3, 4]]
    # Ties go to the pair first in column order.
    tie = np.array([[1.0, 0.7, 0.0], [0.7, 1.0, 0.7], [0.0, 0.7, 1.0]])
    assert cc.average_linkage(tie, 0.6) == [[0, 1], [2]]
    assert math.isclose(cc.cluster_mean_corr(corr, [0, 1, 2]), (0.9 + 0.7 + 0.65) / 3)
    assert math.isnan(cc.cluster_mean_corr(corr, [4]))


# The plan's linkage written the slow way: every pair of clusters, the
# mean of their cross block, merge the best while it reaches rho.
def _reference_linkage(corr, rho):
    clusters = [[i] for i in range(corr.shape[0])]
    while len(clusters) > 1:
        best, pair = -math.inf, None
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                block = corr[np.ix_(clusters[a], clusters[b])]
                if np.isfinite(block).all() and block.mean() > best:
                    best, pair = float(block.mean()), (a, b)
        if pair is None or best < rho:
            break
        merged = sorted(clusters[pair[0]] + clusters[pair[1]])
        clusters = [g for i, g in enumerate(clusters) if i not in pair] + [merged]
        clusters.sort(key=lambda g: g[0])
    return clusters


# The vectorised linkage agrees with the slow reference on random
# correlation matrices of real shape, with missing names among them.
def test_linkage_matches_the_reference():
    rng = np.random.default_rng(4)
    for trial in range(40):
        k = int(rng.integers(2, 30))
        factors = rng.normal(size=(60, 3))
        loads = rng.normal(size=(3, k)) * rng.uniform(0, 2, size=k)
        x = factors @ loads + rng.normal(size=(60, k))
        corr = np.corrcoef(x, rowvar=False)
        if trial % 3 == 0:
            gone = rng.integers(0, k)
            corr[gone, :] = np.nan
            corr[:, gone] = np.nan
        for rho in (0.3, 0.5, 0.6):
            assert cc.average_linkage(corr, rho) == _reference_linkage(corr, rho)


# The cap's arithmetic on synthetic weights: the binding cluster is scaled
# to C pro rata, the excess goes pro rata to the names outside it, the
# total is kept when there is room, and nothing goes above the name cap.
def test_cap_redistributes_pro_rata_under_the_name_cap():
    w = np.r_[np.full(6, 1 / 6), 0.0]
    capped, record = cc.cap_weights(w, [[0, 1, 2], [3], [4], [5]], 0.35)
    assert record["binds"]
    assert record["passes"] == 1
    assert capped[:3].sum() == pytest.approx(0.35)
    assert capped[:3] == pytest.approx([0.35 / 3] * 3)
    assert capped[3:6] == pytest.approx([(1 - 0.35) / 3] * 3)
    assert capped.sum() == pytest.approx(1.0)
    assert record["moved"] == pytest.approx(0.5 - 0.35)
    assert record["cash"] == pytest.approx(0.0, abs=1e-12)
    assert capped[SPY] == 0.0
    # Pro rata to unequal weights outside the cluster.
    w2 = np.array([0.25, 0.25, 0.15, 0.1, 0.15, 0.1])
    out, _ = cc.cap_weights(w2, [[0, 1], [2], [3], [4], [5]], 0.35)
    gained = out[2:6] - w2[2:6]
    assert gained == pytest.approx(0.15 * w2[2:6] / 0.5)
    assert out.sum() == pytest.approx(w2.sum())
    # The name cap: outside names already near 25% fill to it, the rest is
    # shared among the others, and what cannot be placed is cash.
    w3 = np.array([0.2, 0.2, 0.2, 0.24, 0.16])
    out3, rec3 = cc.cap_weights(w3, [[0, 1, 2], [3], [4]], 0.35)
    assert out3.max() <= cc.NAME_CAP + 1e-12
    assert out3[3] == pytest.approx(0.25)
    assert out3[4] == pytest.approx(0.25)
    assert rec3["cash"] == pytest.approx(0.25 - 0.01 - 0.09)
    assert out3.sum() + rec3["cash"] == pytest.approx(w3.sum())


# Everything in one cluster: the cluster is held at C and the rest is cash.
def test_unplaced_weight_goes_to_cash():
    w = np.array([0.25, 0.25, 0.25, 0.25])
    out, record = cc.cap_weights(w, [[0, 1, 2, 3]], 0.35)
    assert out.sum() == pytest.approx(0.35)
    assert record["cash"] == pytest.approx(0.65)


# Passes: weight moved out of one cluster pushes a second over C, which is
# then capped; its excess goes to the names still free; no cluster ends
# above C and no name above the name cap.
def test_cap_runs_in_passes():
    w = np.full(8, 0.125)
    clusters = [[0, 1, 2, 3], [4, 5], [6], [7]]
    out, record = cc.cap_weights(w, clusters, 0.30, name_cap=0.25)
    # Pass 1: [0..3] 50% -> 30%, 20% to the four free names (5% each),
    # [4, 5] becomes 35% > 30%; pass 2: [4, 5] -> 30%, 5% to names 6 and 7.
    assert record["passes"] == 2
    assert sorted(map(tuple, record["capped"])) == [(0, 1, 2, 3), (4, 5)]
    for g in clusters:
        assert out[g].sum() <= 0.30 + 1e-12
    assert out[6] == pytest.approx(0.2)
    assert out[7] == pytest.approx(0.2)
    assert out.sum() == pytest.approx(1.0)
    assert out.max() <= 0.25 + 1e-12


# A book on which nothing binds is returned as the very same array, and
# C = 100% never binds: the null.
def test_nothing_binds_returns_the_same_array():
    w = np.r_[np.full(6, 1 / 6), 0.0]
    out, record = cc.cap_weights(w, [[0, 1, 2], [3], [4], [5]], 0.50)
    assert out is w
    assert not record["binds"]
    out, record = cc.cap_weights(w, [[0, 1, 2, 3, 4, 5]], cc.NULL.cap)
    assert out is w
    assert not record["binds"]
    full = np.full(3, 1 / 3)
    assert cc.cap_weights(full, [[0, 1, 2]], 1.0)[0] is full


# The capped allocator caps the factor cluster at 35% on the synthetic
# book, leaves it at 50% under a 50% cap, and at C = 100% is the base
# allocator to the bit on every session; so is the simulator's book.
def test_null_identity_through_the_allocator_and_simulator(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    base = cli.base_arm()
    t = 200
    plain = base(restricted, mask)(restricted, restricted.panel, None, t)
    r1a = cc.capped_arm(base, cc.REGISTERED[0])(restricted, mask)
    capped = r1a(restricted, restricted.panel, None, t)
    assert capped[:3].sum() == pytest.approx(0.35)
    assert capped[3:6] == pytest.approx([0.65 / 3] * 3)
    r1b = cc.capped_arm(base, cc.REGISTERED[1])(restricted, mask)
    assert np.array_equal(r1b(restricted, restricted.panel, None, t), plain)
    null = cc.capped_arm(base, cc.NULL)(restricted, mask)
    allocate = base(restricted, mask)
    for s in range(T):
        assert np.array_equal(
            null(restricted, restricted.panel, None, s),
            allocate(restricted, restricted.panel, None, s),
        )
    options = dict(use_exits=False, rebalance=20, cost_bps=25.0)
    a = simulate.run(restricted, allocator=allocate, **options)
    b = simulate.run(restricted, allocator=null, **options)
    assert np.array_equal(a.returns, b.returns, equal_nan=True)
    assert np.array_equal(a.equity, b.equity, equal_nan=True)
    c = simulate.run(restricted, allocator=r1a, **options)
    assert not np.array_equal(a.returns, c.returns, equal_nan=True)


# The binding record counts the sessions the cap binds on and keeps each
# binding session's weights and clusters.
def test_binding_record(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    record = cc.binding_record(
        restricted,
        mask,
        cli.base_arm(),
        cc.REGISTERED[0],
        sc.WINDOWS,
        point_in_time.window,
    )
    whole = record["windows"]["all"]
    assert whole["sessions_with_targets"] == T
    # From the first full 60-session window the factor names cluster.
    assert whole["sessions_binding"] >= T - 70
    assert whole["median_largest_cluster_before"] == pytest.approx(0.5)
    assert whole["median_largest_cluster_after"] == pytest.approx(0.35)
    first = record["sessions"][0]
    assert ["AAA", "BBB", "CCC"] in first["clusters"]
    assert sum(first["after"]) == pytest.approx(1.0)
    assert record["spec"]["tag"] == "cc35_r60"
    none = cc.binding_record(
        restricted, mask, cli.base_arm(), cc.NULL, sc.WINDOWS, point_in_time.window
    )
    assert none["windows"]["all"]["sessions_binding"] == 0
    assert not none["sessions"]


# Tags, parsing and the registered set.
def test_specs():
    assert [s.tag for s in cc.REGISTERED] == ["cc35_r60", "cc50_r60", "cc35_r50"]
    assert cc.NULL.tag == "cc100_r60"
    assert not cc.NULL.registered
    assert cc.parse_spec("35:0.6") == cc.REGISTERED[0]
    assert all(s.registered for s in cc.REGISTERED)
    with pytest.raises(ValueError, match="cap must be"):
        cc.parse_spec("0:0.6")
    assert cc.TRIALS == {"registered": 3, "cumulative": 488}


# The verdict's labels from the plan's criteria on hand-made readings.
def test_labels():
    # One window's reading with the three numbers the label reads.
    def reading(gain, cagr, shallower):
        return {
            "drawdown_gain": gain,
            "cagr_difference": cagr,
            "offsets_shallower": shallower,
        }

    both = lambda r: {cc.DECIDING: r, cc.RECENT: r}  # noqa: E731
    assert cc.label(both(reading(0.03, -0.01, 0))) == cc.REPLACES
    assert cc.label(both(reading(0.05, 0.02, 0))) == cc.REPLACES
    assert cc.label(both(reading(0.05, -0.011, 20))) == cc.RECORD
    assert cc.label(both(reading(0.02, 0.0, 15))) == cc.IMMATERIAL
    assert cc.label(both(reading(0.02, 0.0, 14))) == cc.RECORD
    mixed = {cc.DECIDING: reading(0.10, 0.0, 20), cc.RECENT: reading(0.0, 0.0, 10)}
    assert cc.label(mixed) == cc.RECORD


# A flat benchmark and the synthetic desk in place of the store's.
@pytest.fixture
def synthetic_desk(history, monkeypatch):
    from backend.agents.trading.desk import desk

    report = _report()
    real = point_in_time.point_in_time
    monkeypatch.setattr(desk, "run", lambda *args, **kwargs: report)
    monkeypatch.setattr(
        point_in_time,
        "point_in_time",
        lambda report, *args, **kwargs: real(report, history),
    )
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
    monkeypatch.setattr(desk, "book_panel", lambda store, asof=None: (report.panel, {}))
    return report


# The CLI end to end on the tiny panel: the null test passes; score writes
# the control, the three arms and the null; the null payload is the
# control's; the verdict reads them; the independent check agrees; the
# session report shows the factor cluster and each arm's capped targets.
def test_cli_end_to_end(synthetic_desk, tmp_path, capsys):
    root = tmp_path / "market"
    out = tmp_path / "scorecards"
    assert cli.main(["null-test", "--root", str(root), "--offsets", "1"]) == 0
    assert "PASS, reproduced to the bit" in capsys.readouterr().out
    args = ["score", "--root", str(root), "--offsets", "3", "--null"]
    assert cli.main([*args, "--output-dir", str(out)]) == 0
    written = sorted(p.name for p in out.glob("*.json"))
    assert written == sorted(
        [
            "control.json",
            "cc35_r60.json",
            "cc50_r60.json",
            "cc35_r50.json",
            "cc100_r60.json",
        ]
    )
    control = json.loads((out / "control.json").read_text())
    null = json.loads((out / "cc100_r60.json").read_text())
    r1a = json.loads((out / "cc35_r60.json").read_text())
    assert control["arm"] == "ew_graded_cap25"
    assert control["costs_bps"] == [10.0, 25.0]
    assert json.dumps(null["rows"]) == json.dumps(control["rows"])
    assert json.dumps(null["curves"]) == json.dumps(control["curves"])
    assert all(len(r["drawdowns"]) == 3 for r in control["rows"])
    assert r1a["cluster_cap"]["binding"]["windows"]["all"]["sessions_binding"] > 0
    assert json.dumps(r1a["rows"]) != json.dumps(control["rows"])
    verdict_path = out / "cluster_cap_verdict.json"
    arms = [str(out / f"{s.tag}.json") for s in cc.REGISTERED]
    assert (
        cli.main(
            ["verdict", "--control", str(out / "control.json"), "--arms", *arms]
            + ["--output", str(verdict_path)]
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "C = 35% at rho* = 0.6 (cc35_r60)" in text
    assert "SPY" in text
    record = json.loads(verdict_path.read_text())
    assert set(record["arms"]) == {"cc35_r60", "cc50_r60", "cc35_r50"}
    for reading in record["arms"].values():
        assert reading["label"] in (cc.REPLACES, cc.IMMATERIAL, cc.RECORD)
        assert reading["trials"] == 488
    check = subprocess.run(
        [sys.executable, str(CHECK), str(verdict_path), str(out / "cc100_r60.json")],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    assert "independent check: OK" in check.stdout
    # The session report from a desk record.
    session = str(synthetic_desk.panel.dates[-1])
    folder = root / "desk" / f"asof={session}"
    folder.mkdir(parents=True)
    weights = {t: 1 / 6 for t in NAMES}
    (folder / "desk.json").write_text(
        json.dumps({"targets": {"policy": "graded-equal-weight/5", "weights": weights}})
    )
    report_path = tmp_path / "clusters.json"
    assert (
        cli.main(
            ["clusters", "--root", str(root), "--session", session]
            + ["--output", str(report_path)]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "AAA BBB CCC (50.0%" in printed
    clusters = json.loads(report_path.read_text())
    assert clusters["by_rho"]["0.6"][0]["names"] == ["AAA", "BBB", "CCC"]
    assert clusters["arms"]["cc35_r60"]["binds"]
    assert not clusters["arms"]["cc50_r60"]["binds"]
    assert sum(clusters["arms"]["cc35_r60"]["weights"].values()) == pytest.approx(1.0)
    early = root / "desk" / "asof=2023-01-03"
    early.mkdir(parents=True)
    (early / "desk.json").write_text(json.dumps({"targets": {"weights": weights}}))
    with pytest.raises(ValueError, match="ends on"):
        cli.session_clusters(root, "2023-01-03", cc.REGISTERED)
