"""The point-in-time restriction and the scorecard behave on a book whose truth is known.

A synthetic desk report over 320 sessions holds six names and SPY. Two of the
names enter the membership history late, one leaves early. The restricted
report must not select an ineligible name, the equal-weight allocator must
hold exactly the eligible names, and the scorecard must price every line on
the same sessions and report the windows apart.
"""

import json
from datetime import date, timedelta
from types import SimpleNamespace

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
    assert payload["metrics_version"] == "pit-scorecard-metrics/2"
    assert "starting NAV" in payload["note"]
    assert "target weights, not fills" in payload["note"]
    assert "(lagged-simple/2)" in payload["note"]
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


# The first finite return is exposed capital, so its loss belongs in drawdown.
@pytest.mark.parametrize(
    ("daily", "expected"),
    [
        ([-0.5, 0.0], -0.5),
        ([np.nan, -0.5, 0.0], -0.5),
        ([-0.1, -0.2], -0.28),
        ([-0.5, 1.0, 0.0], -0.5),
        ([0.5, -0.2], -0.2),
        ([0.1, 0.2], 0.0),
        ([-1.0, 0.0], -1.0),
    ],
)
def test_window_drawdown_includes_starting_nav(daily, expected):
    stats = sc.window_stats(np.asarray(daily))
    assert stats["drawdown"] == pytest.approx(expected)
    assert stats["sessions"] == np.isfinite(daily).sum()
    assert set(stats) == {"cagr", "drawdown", "sharpe", "sessions"}


# Construct only the target-book inputs needed for isolated concentration
# checks; prices are flat at 100 unless `adj_close` is given.
def _target_concentration(target_weights, windows=None, adj_close=None):
    weights = np.atleast_2d(np.asarray(target_weights, dtype=float))
    panel = SimpleNamespace(
        dates=np.datetime64("2023-01-03") + np.arange(len(weights)),
        tickers=tuple(f"STOCK{i}" for i in range(weights.shape[1])),
        adj_close=(
            np.full(weights.shape, 100.0)
            if adj_close is None
            else np.asarray(adj_close, dtype=float)
        ),
    )
    report = SimpleNamespace(panel=panel)

    # Return the declared target for this session without deriving any holdings.
    def allocate(restricted, panel, unused, t):
        return weights[t]

    return sc.concentration(
        report,
        np.ones(weights.shape, dtype=bool),
        allocate,
        windows or {"all": (None, None)},
    )


# Invested-name count depends on relative stock weights, not the cash allocation.
@pytest.mark.parametrize("gross", [0.07, 0.35, 1.0])
@pytest.mark.parametrize(
    ("relative", "effective"),
    [([1.0], 1.0), ([1.0] * 7, 7.0), ([1.0, 2.0, 3.0], 36.0 / 14.0)],
)
def test_concentration_effective_names_normalizes_invested_weights(
    gross, relative, effective
):
    relative = np.asarray(relative)
    targets = gross * relative / relative.sum()
    stats = _target_concentration(targets)["all"]
    assert stats["effective_names_median"] == pytest.approx(effective)
    assert stats["effective_names_min"] == pytest.approx(effective)
    assert stats["largest_weight_max"] == pytest.approx(targets.max())
    assert stats["cash_max"] == pytest.approx(1.0 - gross)
    # One flat-priced session: no earlier decision, so no single-name loss.
    assert stats["worst_single_name_day"] == 0.0
    assert stats["worst_single_name_day_basis"] == "lagged-simple/2"


# All-cash sessions remain outside invested-only summaries and cannot add names.
def test_concentration_keeps_all_cash_and_partly_invested_windows_separate():
    windows = {
        "all": (None, None),
        "cash": (date(2023, 1, 4), date(2023, 1, 5)),
    }
    stats = _target_concentration([[0.1, 0.1], [0.0, 0.0], [0.2, 0.2]], windows)
    assert stats["cash"] == {"sessions": 0}
    assert stats["all"]["sessions"] == 3
    assert stats["all"]["invested_share"] == pytest.approx(2.0 / 3.0)
    assert stats["all"]["effective_names_min"] == pytest.approx(2.0)
    assert stats["all"]["cash_median"] == pytest.approx(0.7)
    assert stats["all"]["cash_max"] == pytest.approx(0.8)
    assert _target_concentration([[0.0, 0.0]])["all"] == {"sessions": 0}


# The single-name day charges the weight set at the previous close: a name
# first bought at the close of its crash day does not count, a name held
# from the close before does (at the simple return, not the log return),
# and so does one sold at the close of the crash day.
@pytest.mark.parametrize(
    ("targets", "expected"),
    [
        ([[0.0, 0.1], [0.5, 0.1], [0.5, 0.1]], 0.0),
        ([[0.5, 0.1], [0.5, 0.1], [0.5, 0.1]], -0.25),
        ([[0.5, 0.1], [0.0, 0.1], [0.0, 0.1]], -0.25),
    ],
    ids=["bought-at-crash-close", "held-from-prior-close", "sold-at-crash-close"],
)
def test_worst_single_name_day_uses_the_previous_close_weight(targets, expected):
    # STOCK0 halves between close 0 and close 1; STOCK1 is flat.
    prices = [[100.0, 100.0], [50.0, 100.0], [50.0, 100.0]]
    stats = _target_concentration(targets, adj_close=prices)["all"]
    assert stats["worst_single_name_day"] == pytest.approx(expected, abs=1e-15)
    assert stats["worst_single_name_day_basis"] == "lagged-simple/2"


# A price missing on either close contributes nothing rather than a loss.
def test_worst_single_name_day_ignores_missing_prices():
    weights = np.array([[0.5, 0.5], [0.5, 0.5]])
    prices = np.array([[100.0, np.nan], [90.0, 50.0]])
    np.testing.assert_allclose(sc.worst_name_day(weights, prices), [0.0, -0.05])


# The real CLI persists a versioned target-book risk report on a synthetic
# book, with the single-name day on its lagged basis in every window.
def test_scorecard_cli_versions_target_book_risk_output(history, monkeypatch, tmp_path):
    from backend.agents.trading.desk import desk

    report = _report()
    real_restriction = point_in_time.point_in_time
    monkeypatch.setattr(desk, "run", lambda *args, **kwargs: report)
    monkeypatch.setattr(
        point_in_time,
        "point_in_time",
        lambda report, *args, **kwargs: real_restriction(report, history),
    )
    monkeypatch.setattr(
        benchmarks,
        "load_benchmark",
        lambda store, symbol, sessions, **kwargs: benchmarks.BenchmarkSeries(
            symbol,
            True,
            np.zeros(len(sessions)),
            np.ones(len(sessions)),
            np.asarray(sessions),
        ),
    )
    arguments = ["--root", str(tmp_path), "--graded-cap", "0.10", "--offsets", "1"]
    assert sc.main([*arguments, "--costs", "10"]) == 0
    target = tmp_path / "desk" / "pit_scorecard_ew_graded_cap10.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["metrics_version"] == "pit-scorecard-metrics/2"
    assert "(lagged-simple/2)" in payload["note"]
    assert payload["concentration"]["all"]["effective_names_min"] == pytest.approx(5.0)
    assert set(payload["concentration"]) == set(sc.WINDOWS)
    for window in payload["concentration"].values():
        assert window["worst_single_name_day"] <= 0.0
        assert window["worst_single_name_day_basis"] == "lagged-simple/2"


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


# The cap sweep's arm at a cap is the registered arm at that cap, weight
# for weight, and the concentration statistics read the target book: a
# 10% cap on four names is 40% invested with the largest weight 10% and
# 60% cash; no cap on the same names is 25% each, four effective names,
# no cash.
def test_graded_arm_and_concentration(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    grades = restricted.graded.grades.copy()
    grades[:, 1] = grading.ORDINAL["C"]
    from dataclasses import replace

    demoted = replace(restricted, graded=replace(restricted.graded, grades=grades))
    capped = sc.graded_arm(0.10)(demoted, mask)
    registered = sc.ARMS["ew_graded"](demoted, mask)
    for t in (10, T - 1):
        np.testing.assert_array_equal(capped(demoted, report.panel, None, t), registered(demoted, report.panel, None, t))
    windows = {"all": (None, None)}
    tight = sc.concentration(demoted, mask, capped, windows)["all"]
    assert tight["sessions"] == T and 0 < tight["invested_share"] <= 1
    assert tight["largest_weight_max"] == pytest.approx(0.10)
    assert tight["cash_max"] >= 0.5
    assert tight["effective_names_min"] == pytest.approx(4.0)
    loose = sc.concentration(demoted, mask, sc.graded_arm(1.0)(demoted, mask), windows)["all"]
    assert loose["cash_max"] == pytest.approx(0.0)
    assert loose["largest_weight_max"] >= tight["largest_weight_max"]
    assert loose["effective_names_min"] >= 1.0
    assert loose["worst_single_name_day"] <= 0.0
    assert loose["worst_single_name_day_basis"] == "lagged-simple/2"
    # The CLI tag for a cap names the percent.
    assert sc.main.__doc__  # entry point exists; the tag rule is pinned below
    assert f"ew_graded_cap{round(0.15 * 100):02d}" == "ew_graded_cap15"


# The fake benchmark the scorecard tests price the indexes with.
def _fake_benchmark(report):
    def fake_benchmark(store, symbol, sessions, cost_bps=10.0, **kw):
        idx = np.searchsorted(report.panel.dates, np.asarray(sessions, dtype="datetime64[D]"))
        prices = report.panel.adj_close[idx, 6]
        equity = np.full(len(sessions), np.nan)
        equity[0] = 1.0
        equity[1:] = prices[1:] / prices[1] / (1 + cost_bps / 1e4)
        daily = np.full(len(sessions), np.nan)
        daily[1:] = equity[1:] / np.where(np.isfinite(equity[:-1]), equity[:-1], 1.0) - 1
        return benchmarks.BenchmarkSeries(symbol, True, daily, equity, np.asarray(sessions))

    return fake_benchmark


# The null test passes for two identical reports on every line at every
# offset and cost, and fails as soon as one grade differs.
def test_null_test_compares_every_line_to_the_bit(history, monkeypatch):
    report = _report()
    monkeypatch.setattr(benchmarks, "load_benchmark", _fake_benchmark(report))
    arm = sc.graded_arm(0.25)
    verdict = sc.null_test(report, _report(), object(), history, 2, (10.0, 25.0), arm)
    assert verdict["ok"] and verdict["grades_and_scores_equal"]
    assert len(verdict["lines"]) == 2 * 2 * 6
    assert {r["line"] for r in verdict["lines"]} == {
        sc.RULE_TODAY, sc.RULE_PIT, sc.EW_PIT, sc.EW_TODAY, "SPY", "QQQ"
    }
    assert "PASS" in sc.render_null_test(verdict)
    # One name graded B on the second half: the rule lines move, the
    # equal-weight lines and the indexes do not.
    from dataclasses import replace

    grades = report.graded.grades.copy()
    grades[T // 2 :, 0] = grading.ORDINAL["B"]
    other = replace(report, graded=replace(report.graded, grades=grades))
    verdict = sc.null_test(report, other, object(), history, 2, (10.0,), arm)
    assert not verdict["ok"] and not verdict["grades_and_scores_equal"]
    moved = {r["line"] for r in verdict["lines"] if not r["returns_equal"]}
    assert moved == {sc.RULE_TODAY, sc.RULE_PIT}
    assert all(r["dates_equal"] for r in verdict["lines"])
    assert "MISMATCH" in sc.render_null_test(verdict) and "FAIL" in sc.render_null_test(verdict)


# The candidate block counts eligible A/A+ names per session: every
# eligible name is A+ here, so the count is the eligible count, and the
# share below five follows the membership.
def test_candidate_counts_follow_eligibility(history):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, history)
    counts = sc.candidate_counts(restricted, mask, windows={"all": (None, None)}, few=6)
    assert counts["all"]["median"] == 5.0 and counts["all"]["p10"] == 5.0
    assert counts["all"]["share_below"] == 1.0 and counts["all"]["below"] == 6
    # Downgrade one name to B: it is no longer a candidate.
    from dataclasses import replace

    grades = restricted.graded.grades.copy()
    grades[:, 0] = grading.ORDINAL["B"]
    fewer = replace(restricted, graded=replace(restricted.graded, grades=grades))
    assert sc.candidate_counts(fewer, mask, windows={"all": (None, None)})["all"]["median"] == 4.0
    empty = sc.candidate_counts(restricted, mask, windows={"none": (date(2030, 1, 1), None)})
    assert empty["none"] == {"sessions": 0}


# `build` carries the membership file and the candidate block in the payload.
def test_build_records_membership_and_candidates(history, monkeypatch):
    report = _report()
    monkeypatch.setattr(benchmarks, "load_benchmark", _fake_benchmark(report))
    payload = sc.build(report, object(), offsets=2, costs=(10.0,), history_path=history)
    assert payload["membership"] == str(history)
    assert set(payload["candidates"]) == set(sc.WINDOWS)
    assert payload["candidates"]["all"]["median"] == 5.0


# The CLI's --null-test runs the desk twice, once through the book cohort,
# and exits 0 when the lines match and 1 when they do not; --universe and
# --membership reach the desk and the mask.
def test_cli_null_test_and_universe_wiring(history, monkeypatch, tmp_path, capsys):
    from backend.agents.trading.desk import cohort as cohort_module
    from backend.agents.trading.desk import desk

    report = _report()
    monkeypatch.setattr(benchmarks, "load_benchmark", _fake_benchmark(report))
    runs = []

    def fake_run(store, asof, inputs=(), fundamentals=None, *, signed_rotation=False, cohort=None):
        runs.append(cohort)
        return report

    monkeypatch.setattr(desk, "run", fake_run)
    monkeypatch.setattr("backend.market.store.MarketStore", lambda root: object())
    code = sc.main(["--graded-cap", "0.25", "--null-test", "--membership", str(history), "--root", str(tmp_path)])
    assert code == 0
    assert runs[0] is None and runs[1].label == cohort_module.BOOK
    assert "PASS" in capsys.readouterr().out
    # A desk that answers differently on the second call fails the null test.
    from dataclasses import replace

    grades = report.graded.grades.copy()
    grades[:, 0] = grading.ORDINAL["B"]
    other = replace(report, graded=replace(report.graded, grades=grades))
    answers = iter([report, other])
    monkeypatch.setattr(desk, "run", lambda *a, **k: next(answers))
    assert sc.main(["--graded-cap", "0.25", "--null-test", "--membership", str(history), "--root", str(tmp_path)]) == 1
    # --universe builds the cohort, reads the universe file by default, and
    # writes where --output says with the arm named.
    runs.clear()
    monkeypatch.setattr(desk, "run", fake_run)
    fake = cohort_module.Cohort("sector", ("AAA",), {"AAA": "X"}, True)
    monkeypatch.setattr(cohort_module, "universe_cohort", lambda arm, store=None, asof=None, universe=None: fake)
    out = tmp_path / "universe_sector.json"
    code = sc.main(["--graded-cap", "0.25", "--universe", "sector", "--membership", str(history), "--offsets", "2", "--costs", "10", "--output", str(out), "--root", str(tmp_path)])
    assert code == 0 and runs == [fake]
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["universe"] == {"arm": "sector", "names": 1, "rank_within_peers": True, "groups": 1}
    assert payload["arm"] == "ew_graded_cap25 + universe_sector"
    assert payload["membership"] == str(history)
    assert "candidates" in payload and "concentration" in payload
    # --null-test with --universe is refused.
    with pytest.raises(SystemExit):
        sc.main(["--null-test", "--universe", "sector"])


# The payload carries the median-offset daily curves of every line and
# each row's per-offset CAGRs and worst drawdown, so two runs can be paired.
def test_build_carries_curves_and_per_offset_cagrs(history, monkeypatch):
    report = _report()
    monkeypatch.setattr(benchmarks, "load_benchmark", _fake_benchmark(report))
    payload = sc.build(report, object(), offsets=3, costs=(10.0,), history_path=history)
    curves = payload["curves"]["10"]
    assert curves["offset"] == 1
    assert len(curves["dates"]) == len(curves["lines"][sc.RULE_PIT])
    assert set(curves["lines"]) == {sc.RULE_TODAY, sc.RULE_PIT, sc.EW_PIT, sc.EW_TODAY, "SPY", "QQQ"}
    daily = np.asarray(curves["lines"][sc.EW_PIT], dtype=float)
    assert np.isfinite(daily).sum() > T // 2
    for row in payload["rows"]:
        assert len(row["cagrs"]) == 3
        finite = [c for c in row["cagrs"] if c == c]
        if finite:
            assert row["median_cagr"] == pytest.approx(float(np.median(finite)))
            assert row["worst_drawdown"] <= row["median_drawdown"] + 1e-12
