"""The point-in-time restriction and the scorecard behave on a book whose truth is known.

A synthetic desk report over 320 sessions holds six names and SPY. Two of the
names enter the membership history late, one leaves early. The restricted
report must not select an ineligible name, the equal-weight allocator must
hold exactly the eligible names, and the scorecard must price every line on
the same sessions and report the windows apart.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import grading, point_in_time, regime, simulate
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.agents.trading.desk.risk import RiskBudget
from backend.cli import market_pit_scorecard as sc
from backend.market import benchmarks
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE

NAMES = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
T = 320


# A report whose every name is graded A+ with a fixed ranking, so selection
# is decided by eligibility alone.
def _report(seed: int = 0) -> DeskReport:
    rng = np.random.default_rng(seed)
    n = len(NAMES)
    start = date(2023, 1, 2)
    days = []
    d = start
    while len(days) < T:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    dates = np.array(days, dtype="datetime64[D]")
    log = rng.normal(0.0004, 0.02, size=(T, n + 1)).cumsum(axis=0)
    close = 100.0 * np.exp(log)
    panel = Panel(
        dates=dates,
        tickers=NAMES + ("SPY",),
        open=close * (1 + rng.normal(0, 0.002, size=close.shape)),
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
    # EEE ranks first and FFF second, so the top-decile rule (one name on a
    # six-name book) wants EEE whenever it may, else FFF, else AAA.
    conviction = np.tile(np.array([0.8, 0.7, 0.6, 0.5, 1.0, 0.9, np.nan]), (T, 1))
    graded = grading.Graded(grades, conviction.copy(), {}, conviction)
    state = regime.RegimeState(
        0.0, 0.0, 0.5, 0.0, 0.0, 0.0, "ai", 0.1, 0.0, 1.0, 1.0, (), 0.0, False
    )
    view = regime.RegimeView([state] * T, Opinion("rotation", np.full((T, n + 1), np.nan)))
    return DeskReport(
        panel, {t: "ai" for t in NAMES}, {}, view, graded, graded.as_scores(), []
    )


# A history: AAA-DDD members throughout, EEE from mid-2023, FFF until mid-2023.
@pytest.fixture
def history(tmp_path):
    path = tmp_path / "membership_history.csv"
    rows = ["ticker,entered,entry_announced,exited,exit_announced,source,rule"]
    for t in ("AAA", "BBB", "CCC", "DDD"):
        rows.append(f"{t},2016-01-04,2016-01-04,,,test,member throughout")
    rows.append("EEE,2023-07-03,2023-07-03,,,test,enters mid-2023")
    rows.append("FFF,2016-01-04,2016-01-04,2023-07-03,2023-07-03,test,leaves mid-2023")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# The mask follows the intervals; the restriction grades non-members C with
# no score and leaves prices alone.
def test_restriction_masks_by_interval(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    dates = report.panel.dates
    switch = int(np.searchsorted(dates, np.datetime64("2023-07-03")))
    eee, fff, spy = 4, 5, 6
    assert not mask[: switch, eee].any() and mask[switch:, eee].all()
    assert mask[: switch, fff].all() and not mask[switch:, fff].any()
    assert mask[:, :4].all() and not mask[:, spy].any()
    assert (restricted.graded.grades[: switch, eee] == grading.ORDINAL["C"]).all()
    assert np.isnan(restricted.scores[: switch, eee]).all()
    assert np.isfinite(restricted.scores[switch:, eee]).all()
    assert restricted.panel is report.panel
    # The unrestricted report is untouched.
    assert (report.graded.grades[:, eee] == grading.ORDINAL["A+"]).all()


# Run the live rule on both reports: the restricted one never holds a name
# outside its interval, the unrestricted one does.
def test_simulation_never_holds_an_ineligible_name(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    options = dict(use_exits=False, rebalance=20, cost_bps=10.0)
    free = simulate.run(report, **options)
    pit = simulate.run(restricted, **options)
    switch = np.datetime64("2023-07-03")
    for trade in pit.trades:
        opened = np.datetime64(trade.opened)
        closed = np.datetime64(trade.closed) if trade.closed else None
        if trade.ticker == "EEE":
            assert opened >= switch
        if trade.ticker == "FFF":
            assert opened < switch
            # Once ineligible, the rule rotates it out on its next clock.
            assert closed is not None and closed <= switch + np.timedelta64(40, "D")
    assert {tr.ticker for tr in pit.trades} == {"FFF", "EEE"}
    assert {tr.ticker for tr in free.trades} == {"EEE"}
    assert len(free.returns) == len(pit.returns)


# The equal-weight allocator holds exactly the eligible names at 1/count and
# reads only the decision session.
def test_equal_weight_allocator_uses_only_the_mask(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    allocate = point_in_time.equal_weight_allocator(mask)
    early = allocate(restricted, report.panel, None, 10)
    late = allocate(restricted, report.panel, None, T - 1)
    assert early[6] == 0 and late[6] == 0
    assert early[4] == 0 and early[5] == pytest.approx(0.2)
    assert late[4] == pytest.approx(0.2) and late[5] == 0
    assert early.sum() == pytest.approx(1.0) and late.sum() == pytest.approx(1.0)
    # Future rows of the panel cannot change today's answer.
    tampered = report.panel.adj_close.copy()
    tampered[11:] = np.nan
    from dataclasses import replace

    same = allocate(restricted, replace(report.panel, adj_close=tampered), None, 10)
    assert np.array_equal(same, early)


# The scorecard prices every line on identical sessions, keeps the windows
# apart, and reports the equal-weight hurdle and both indexes beside the rule.
def test_scorecard_reports_every_line_per_window(history, monkeypatch):
    report = _report()

    def fake_benchmark(store, symbol, sessions, cost_bps=10.0, **kw):
        idx = np.searchsorted(report.panel.dates, np.asarray(sessions, dtype="datetime64[D]"))
        prices = report.panel.adj_close[idx, 6]
        equity = np.full(len(sessions), np.nan)
        equity[0] = 1.0
        equity[1:] = prices[1:] / prices[1] / (1 + cost_bps / 1e4)
        daily = np.full(len(sessions), np.nan)
        daily[1:] = equity[1:] / np.where(np.isfinite(equity[:-1]), equity[:-1], 1.0) - 1
        return benchmarks.BenchmarkSeries(symbol, True, daily, equity, np.asarray(sessions))

    monkeypatch.setattr(benchmarks, "load_benchmark", fake_benchmark)
    payload = sc.build(report, object(), offsets=3, costs=(10.0,), history_path=history)
    lines = {sc.RULE_TODAY, sc.RULE_PIT, sc.EW_PIT, sc.EW_TODAY, "SPY", "QQQ"}
    assert {r["line"] for r in payload["rows"]} == lines
    assert {r["window"] for r in payload["rows"]} == set(sc.WINDOWS)
    for row in payload["rows"]:
        assert row["offsets"] == 3
        if row["window"] == "2024-2026":
            assert row["sessions"] > 0
    # The 2016-2023 window here is 2023 only; every line has the same session count.
    counts = {r["line"]: r["sessions"] for r in payload["rows"] if r["window"] == "2023" or r["window"] == "2016-2023"}
    assert len(set(counts.values())) == 1
    assert payload["book"]["names_today"] == 6
    assert payload["book"]["eligible_first_session"] == 5
    assert payload["book"]["eligible_last_session"] == 5
    pairs = {(p["line"], p["against"]) for p in payload["paired"]}
    assert (sc.RULE_PIT, sc.EW_PIT) in pairs and (sc.RULE_PIT, "QQQ") in pairs
    text = sc.render(payload)
    assert "equal weight / point-in-time" in text and "QQQ" in text


# Window statistics: a flat series has zero CAGR and drawdown; a series that
# halves shows it.
def test_window_stats():
    flat = sc.window_stats(np.zeros(252))
    assert flat["cagr"] == pytest.approx(0.0) and flat["drawdown"] == pytest.approx(0.0)
    halved = sc.window_stats(np.array([0.0] * 10 + [-0.5] + [0.0] * 10))
    assert halved["drawdown"] == pytest.approx(-0.5)
    assert sc.window_stats(np.array([np.nan, 0.01]))["sessions"] == 1


# The graded equal-weight arm holds every eligible A-or-better name at
# min(1/count, cap), leaves the rest in cash, and ignores C names.
def test_graded_equal_weight_allocator(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    grades = restricted.graded.grades.copy()
    grades[:, 1] = grading.ORDINAL["C"]  # BBB never qualifies
    from dataclasses import replace

    demoted = replace(restricted, graded=replace(restricted.graded, grades=grades))
    allocate = point_in_time.graded_equal_weight_allocator(
        mask, min_grade=grading.ORDINAL["A"], cap=0.10
    )
    early = allocate(demoted, report.panel, None, 10)
    # Eligible early: AAA, CCC, DDD, FFF (4 names) -> capped at 10% each, 60% cash.
    assert early[1] == 0 and early[4] == 0 and early[6] == 0
    assert early[0] == pytest.approx(0.10) and early[5] == pytest.approx(0.10)
    assert early.sum() == pytest.approx(0.40)
    wide = point_in_time.graded_equal_weight_allocator(mask, min_grade=0, cap=0.5)
    late = wide(demoted, report.panel, None, T - 1)
    assert late.sum() == pytest.approx(1.0) and late[5] == 0 and late[4] == pytest.approx(0.2)
    with pytest.raises(ValueError):
        point_in_time.graded_equal_weight_allocator(mask, 0, cap=0.0)


# An arm replaces the rule lines and is named in the payload and the file.
def test_scorecard_arm_replaces_the_rule_lines(history, monkeypatch, tmp_path):
    report = _report()
    monkeypatch.setattr(
        benchmarks,
        "load_benchmark",
        lambda store, symbol, sessions, cost_bps=10.0, **kw: benchmarks.BenchmarkSeries(
            symbol, True, np.zeros(len(sessions)), np.ones(len(sessions)), np.asarray(sessions)
        ),
    )
    seen = []
    real = sc.simulate.run

    def spy(report_, **kw):
        seen.append(kw.get("allocator"))
        return real(report_, **kw)

    monkeypatch.setattr(sc.simulate, "run", spy)
    payload = sc.build(report, object(), offsets=1, costs=(10.0,), history_path=history, arm=sc.ARMS["ew_graded"])
    # Four simulator runs per offset: two arm lines and two equal-weight controls, all with allocators.
    assert len(seen) == 4 and all(a is not None for a in seen)
    assert {r["line"] for r in payload["rows"]} >= {sc.RULE_TODAY, sc.RULE_PIT}
    assert "ew_graded" in sc.ARMS
