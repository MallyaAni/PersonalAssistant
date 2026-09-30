"""The chart's decision history: the live policy replayed, and the real fills.

A synthetic report over twenty sessions holds three names and SPY. One
name crosses into A at session 5 and out at session 12, so its series
must read buy, hold..., sell on exactly those sessions; the equal-weight
reshuffles that happen when another name joins or leaves must read as
holds, and a shift above ADD_TRIM_MIN as an add or a trim. The targets are
asserted equal to `policy_v4.targets` on the point-in-time mask, a name
outside the membership history gets no decision at all, and the fills are
read out of a record tree written to a tmp path with the shape the nightly
writes.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from backend.agents.trading.desk import (
    decision_history,
    grading,
    point_in_time,
    policy_v4,
    regime,
)
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE

NAMES = ("AAA", "BBB", "CCC")
T = 20
A = grading.ORDINAL[grading.A]
B = grading.ORDINAL[grading.B]
C = grading.ORDINAL[grading.C]


# Twenty weekday sessions from a Monday, as the panel indexes them.
def _dates() -> np.ndarray:
    days = []
    d = date(2026, 8, 3)
    while len(days) < T:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return np.array(days, dtype="datetime64[D]")


# A report whose grades are given as a (T, N) matrix, prices flat at 100.
def _report(grades: np.ndarray) -> DeskReport:
    n = len(NAMES)
    close = np.full((T, n + 1), 100.0)
    panel = Panel(
        dates=_dates(),
        tickers=NAMES + ("SPY",),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: (AI_COMPUTE,) for t in NAMES},
        benchmark="SPY",
    )
    conviction = grades.astype(float)
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


# A membership history admitting AAA and BBB for the whole span and CCC
# never: a name the book did not hold cannot have been decided on.
@pytest.fixture
def membership(tmp_path: Path) -> Path:
    path = tmp_path / "membership_history.csv"
    path.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        "AAA,2020-01-02,2020-01-02,,,test,test\n"
        "BBB,2020-01-02,2020-01-02,,,test,test\n",
        encoding="utf-8",
    )
    return path


# AAA is graded A from session 5 through 11 and C otherwise; BBB is always
# A, so the book is BBB alone except while AAA qualifies.
def _crossing() -> np.ndarray:
    grades = np.full((T, len(NAMES) + 1), C, dtype=int)
    grades[:, 1] = A
    grades[5:12, 0] = A
    return grades


# The constants come from the policy module and the threshold is stated.
def test_the_policy_is_the_live_one():
    assert decision_history.POLICY == policy_v4.POLICY_VERSION
    assert decision_history.ADD_TRIM_MIN == 0.025
    # The note describes the signals, not a fill convention: since 2026-09-30
    # the paper account trades them on the board's intraday rule, and its own
    # fills (not a projected open) say when each trade happened.
    assert decision_history.DECISION_NOTE.startswith("signals at each close")
    assert "next open" not in decision_history.DECISION_NOTE


# Crossing into A is a buy on that session, leaving it a sell, and every
# session between is a hold; nothing before or after says anything.
def test_a_grade_crossing_reads_buy_hold_sell(membership):
    report = _report(_crossing())
    rows = decision_history.series(report, "AAA", history_path=membership)
    assert len(rows) == T
    actions = [r["action"] for r in rows]
    assert actions[5] == "buy"
    assert actions[6:12] == ["hold"] * 6
    assert actions[12] == "sell"
    assert set(actions[:5]) == {"hold"}
    assert set(actions[13:]) == {"hold"}
    assert rows[5]["date"] == str(report.panel.dates[5])
    assert rows[5]["previous_weight"] == 0
    assert rows[5]["target_weight"] == pytest.approx(policy_v4.HOLD_CAP)
    assert rows[5]["delta_weight"] == pytest.approx(policy_v4.HOLD_CAP)
    assert rows[12]["target_weight"] == 0
    assert rows[12]["delta_weight"] == pytest.approx(-policy_v4.HOLD_CAP)


# `since` keeps the rows from that date on, with the earlier weight still
# known, so the first row after a buy is a hold and not a second buy.
def test_since_trims_the_rows_without_forgetting_the_position(membership):
    report = _report(_crossing())
    since = report.panel.dates[7].astype(object)
    rows = decision_history.series(report, "AAA", since=since, history_path=membership)
    assert rows[0]["date"] == str(report.panel.dates[7])
    assert rows[0]["action"] == "hold"
    assert rows[0]["previous_weight"] == pytest.approx(policy_v4.HOLD_CAP)


# An equal-weight reshuffle smaller than ADD_TRIM_MIN is a hold; one above
# it is an add or a trim. Below the cap (which is 1/5) the weights are
# 1/count, so 1/6 -> 1/7 (2.4 points) is a hold while 1/6 -> 1/9 (5.6
# points) is a trim and back is an add.
def test_equal_weight_shifts_under_the_threshold_are_holds():
    assert decision_history.classify(1 / 6, 1 / 7) == "hold"
    assert decision_history.classify(1 / 7, 1 / 6) == "hold"
    assert decision_history.classify(1 / 6, 1 / 9) == "trim"
    assert decision_history.classify(1 / 9, 1 / 6) == "add"
    assert decision_history.classify(0.0, 0.1) == "buy"
    assert decision_history.classify(0.1, 0.0) == "sell"
    assert decision_history.classify(0.0, 0.0) == "hold"
    # The threshold is inclusive on both sides.
    step = decision_history.ADD_TRIM_MIN
    assert decision_history.classify(0.10, 0.10 + step) == "add"
    assert decision_history.classify(0.10, 0.10 - step) == "trim"


# The matrix is `policy_v4.targets` session by session on the point-in-time
# mask; the benchmark column is always zero.
def test_targets_equal_the_policy_on_the_point_in_time_mask(membership):
    report = _report(_crossing())
    targets = decision_history.target_matrix(report, membership)
    panel = report.panel
    mask = point_in_time.eligibility(panel.dates, tuple(panel.tickers), membership)
    bench = panel.index("SPY")
    for t in range(T):
        expected = policy_v4.targets(
            report.graded.grades[t], panel.close[t], mask[t], bench
        )
        assert np.array_equal(targets[t], expected)
    assert (targets[:, bench] == 0).all()
    # Session 5: AAA and BBB both A, two names -> the cap each.
    assert targets[5, 0] == targets[5, 1] == pytest.approx(policy_v4.HOLD_CAP)
    # Session 0: BBB alone -> the cap, not 100%.
    assert targets[0, 1] == pytest.approx(policy_v4.HOLD_CAP)
    assert targets[0, 0] == 0


# A name the membership history never admits has no decision on any
# session, however it is graded: all zeros, every action a hold.
def test_a_name_outside_the_membership_history_has_no_decisions(membership):
    grades = _crossing()
    grades[:, 2] = A  # CCC graded A throughout, but never a member
    report = _report(grades)
    targets = decision_history.target_matrix(report, membership)
    assert (targets[:, 2] == 0).all()
    rows = decision_history.series(report, "CCC", targets=targets)
    assert {r["action"] for r in rows} == {"hold"}
    assert all(r["target_weight"] == 0 for r in rows)


# A precomputed matrix gives the same series as computing it inside.
def test_series_accepts_a_precomputed_matrix(membership):
    report = _report(_crossing())
    targets = decision_history.target_matrix(report, membership)
    assert decision_history.series(
        report, "AAA", targets=targets
    ) == decision_history.series(report, "AAA", history_path=membership)


# A record tree with the nightly's shape; returns the root.
def _records(root: Path) -> Path:
    def write(session: str, paper):
        folder = root / "desk" / f"asof={session}"
        folder.mkdir(parents=True)
        record = {"session": session, "grades": {}, "book": []}
        if paper is not None:
            record["paper"] = paper
        (folder / "desk.json").write_text(json.dumps(record), encoding="utf-8")

    write("2026-09-10", None)  # a night without a paper block
    write(
        "2026-09-11",
        {
            "settled": [
                {
                    "symbol": "AAA",
                    "side": "buy",
                    "qty": 63,
                    "status": "filled",
                    "filled": 63,
                    "filled_price": 224.81,
                    "client_order_id": "anios-2026-09-10-buy-aaa-0",
                },
                {
                    "symbol": "BBB",
                    "side": "buy",
                    "qty": 10,
                    "status": "filled",
                    "filled": 10,
                    "filled_price": 50.0,
                    "client_order_id": "anios-2026-09-10-buy-bbb-0",
                },
                {
                    "symbol": "AAA",
                    "side": "sell",
                    "qty": 20,
                    "status": "dead",
                    "filled": 0,
                    "filled_price": 0.0,
                    "client_order_id": "anios-2026-09-10-sell-aaa-0",
                },
            ]
        },
    )
    write(
        "2026-09-14",
        {
            "settled": [
                # A partial reported again after concluding: the later
                # reading, with a completion session, replaces the earlier.
                {
                    "symbol": "AAA",
                    "side": "sell",
                    "qty": 63,
                    "status": "partial",
                    "filled": 40,
                    "filled_price": 230.5,
                    "completion_session": "2026-09-14",
                    "client_order_id": "anios-2026-09-11-sell-aaa-0",
                },
                # Fields absent: skipped, not fatal.
                {"symbol": "AAA"},
                "not a row",
            ],
            "label": "paper",
        },
    )
    write("2026-09-15", {"settled": "nothing"})
    return root


# The fills come out of the records dated, sided and priced, dead orders
# and malformed rows left out, other names left out.
def test_fills_read_from_the_record_tree(tmp_path):
    root = _records(tmp_path)
    got = decision_history.fills(root, "AAA")
    assert got == [
        {"date": "2026-09-11", "side": "buy", "qty": 63, "price": 224.81},
        {"date": "2026-09-14", "side": "sell", "qty": 40, "price": 230.5},
    ]
    assert decision_history.fills(root, "BBB") == [
        {"date": "2026-09-11", "side": "buy", "qty": 10, "price": 50.0}
    ]
    assert decision_history.fills(root, "CCC") == []
    assert decision_history.fills(tmp_path / "nowhere", "AAA") == []


# An unreadable record is skipped, not fatal.
def test_fills_skip_an_unreadable_record(tmp_path):
    root = _records(tmp_path)
    (root / "desk" / "asof=2026-09-11" / "desk.json").write_text("{", encoding="utf-8")
    assert decision_history.fills(root, "AAA") == [
        {"date": "2026-09-14", "side": "sell", "qty": 40, "price": 230.5},
    ]


# A settled row that names its plan leg (`kind`, "redeploy" since the
# executor's /4) carries it into the fill; a row without one, or with a
# malformed one, reads exactly as before.
def test_fills_carry_the_plan_leg_when_the_record_names_one(tmp_path):
    root = tmp_path
    folder = root / "desk" / "asof=2026-09-29"
    folder.mkdir(parents=True)
    (folder / "desk.json").write_text(
        json.dumps(
            {
                "session": "2026-09-29",
                "paper": {
                    "settled": [
                        {
                            "symbol": "AAA",
                            "side": "buy",
                            "qty": 7,
                            "status": "filled",
                            "filled": 7,
                            "filled_price": 91.0,
                            "kind": "redeploy",
                            "client_order_id": "anios-2026-09-28-buy-aaa-2",
                        },
                        {
                            "symbol": "AAA",
                            "side": "buy",
                            "qty": 3,
                            "status": "filled",
                            "filled": 3,
                            "filled_price": 90.0,
                            "kind": 7,
                            "client_order_id": "anios-2026-09-28-buy-aaa-1",
                        },
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    assert decision_history.fills(root, "AAA") == [
        {"date": "2026-09-29", "side": "buy", "qty": 3, "price": 90.0},
        {
            "date": "2026-09-29",
            "side": "buy",
            "qty": 7,
            "price": 91.0,
            "kind": "redeploy",
        },
    ]


# The /4 reading, on hand-built moves. Entering and leaving the book are a
# buy and a sell on any session; a held name's move is a hold on a
# non-reset session however large (the executor does not follow the
# denominator), and on a reset session it is the add or trim the
# rebalance places when it reaches ADD_TRIM_MIN, else a hold.
def test_classify_under_the_reset_schedule():
    classify = decision_history.classify
    # Membership changes trade on any session.
    assert classify(0.0, 1 / 11, reset=False) == "buy"
    assert classify(1 / 11, 0.0, reset=False) == "sell"
    assert classify(0.0, 1 / 11, reset=True) == "buy"
    # Drift between resets is a hold, whatever its size (AAOI's 10 -> 12.5).
    assert classify(0.10, 0.125, reset=False) == "hold"
    assert classify(0.125, 0.10, reset=False) == "hold"
    assert classify(1 / 6, 1 / 9, reset=False) == "hold"
    # The reset trades a move at or above the threshold, and not one below it.
    assert classify(0.10, 0.125, reset=True) == "add"
    assert classify(0.125, 0.10, reset=True) == "trim"
    assert classify(1 / 6, 1 / 7, reset=True) == "hold"
    assert classify(0.0, 0.0, reset=True) == "hold"


# A /3-style call (no schedule) reads exactly as it did: the same rows,
# no `rebalance` key, so a history written for a sizing policy is unchanged.
def test_series_without_a_schedule_is_the_weight_move_reading(membership):
    report = _report(_crossing())
    rows = decision_history.series(report, "AAA", history_path=membership)
    assert all("rebalance" not in r for r in rows)
    assert set(rows[0]) == {
        "date",
        "target_weight",
        "previous_weight",
        "delta_weight",
        "action",
    }
    assert [r["action"] for r in rows] == [
        decision_history.classify(r["previous_weight"], r["target_weight"])
        for r in rows
    ]


# A report of eight member names whose count of A/A+ names changes while
# one of them stays A+, so that name's equal-weight target drifts without
# it ever leaving the book (the cap binds below five names, so the drift
# needs six or more). Returns (report, membership history path).
def _drifting(tmp_path: Path):
    names = tuple(f"N{i}" for i in range(8))
    path = tmp_path / "membership_history.csv"
    path.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        + "".join(f"{n},2020-01-02,2020-01-02,,,test,test\n" for n in names),
        encoding="utf-8",
    )
    n = len(names)
    close = np.full((T, n + 1), 100.0)
    panel = Panel(
        dates=_dates(),
        tickers=names + ("SPY",),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: (AI_COMPUTE,) for t in names},
        benchmark="SPY",
    )
    grades = np.full((T, n + 1), C, dtype=int)
    # N0 is A+ throughout; N1..N5 are A throughout (six names, 1/6 each);
    # N6 joins on sessions 4-9 (seven names, 1/7) and N7 joins on 6-7
    # (eight, 1/8), so N0's target drifts 1/6 -> 1/7 -> 1/8 -> 1/7 -> 1/6
    # without N0 ever leaving the book. N0 is downgraded on session 15.
    grades[:, 0:6] = A
    grades[4:10, 6] = A
    grades[6:8, 7] = A
    grades[15:, 0] = C
    conviction = grades.astype(float)
    graded = grading.Graded(grades, conviction.copy(), {}, conviction)
    state = regime.RegimeState(
        0.0, 0.0, 0.5, 0.0, 0.0, 0.0, "ai", 0.1, 0.0, 1.0, 1.0, (), 0.0, False
    )
    view = regime.RegimeView(
        [state] * T, Opinion("rotation", np.full((T, n + 1), np.nan))
    )
    report = DeskReport(
        panel, {t: "ai" for t in names}, {}, view, graded, graded.as_scores(), []
    )
    return report, path


# A name A+ every session with a drifting target reads buy on its entry,
# hold through every drift on a non-reset session, add/trim only on the
# reset session where the move reaches the threshold, and sell on the
# session it leaves the book; every row says whether it was a reset.
def test_series_under_the_schedule_marks_entries_exits_and_resets(tmp_path):
    report, membership = _drifting(tmp_path)
    dates = [str(d) for d in report.panel.dates]
    targets = decision_history.target_matrix(report, membership)
    # Every drift here is under the threshold (1/6 -> 1/7 is 2.4 points,
    # 1/7 -> 1/8 is 1.8), so a reset on session 6 is a hold too: the
    # rebalance would not bother. The resets on sessions 0 and 15 show
    # the flag beside an entry and an exit.
    resets = {dates[0], dates[6], dates[15]}
    rows = decision_history.series(report, "N0", targets=targets, resets=resets)
    actions = [r["action"] for r in rows]
    assert actions[0] == "buy"
    assert rows[0]["rebalance"] is True
    assert rows[0]["target_weight"] == pytest.approx(1 / 6, abs=1e-6)
    # Drift on sessions 4 (1/6 -> 1/7), 8 (1/8 -> 1/7), 10 (1/7 -> 1/6): holds.
    assert rows[4]["target_weight"] == pytest.approx(1 / 7, abs=1e-6)
    assert rows[6]["target_weight"] == pytest.approx(1 / 8, abs=1e-6)
    assert rows[10]["target_weight"] == pytest.approx(1 / 6, abs=1e-6)
    assert actions[1:15] == ["hold"] * 14
    assert [r["rebalance"] for r in rows[1:15]] == [d in resets for d in dates[1:15]]
    assert actions[15] == "sell"
    assert rows[15]["rebalance"] is True
    assert set(actions[16:]) == {"hold"}


# The same drift with a large move on a reset session is the add or trim
# the rebalance places. Built by hand on the classify boundary through
# `series`: a two-column matrix whose second column drifts by 5 points.
def test_series_on_a_reset_session_reads_the_rebalance_as_add_or_trim(membership):
    report = _report(_crossing())
    dates = [str(d) for d in report.panel.dates]
    targets = np.zeros((T, len(NAMES) + 1))
    targets[:, 0] = 0.15
    targets[5:10, 0] = 0.20  # +5 points on session 5, -5 on session 10
    rows = decision_history.series(
        report, "AAA", targets=targets, resets={dates[5], dates[10]}
    )
    actions = [r["action"] for r in rows]
    assert actions[0] == "buy"
    assert actions[5] == "add"
    assert actions[10] == "trim"
    assert set(actions[1:5] + actions[6:10] + actions[11:]) == {"hold"}
    # The same moves off the schedule are holds.
    off = decision_history.series(report, "AAA", targets=targets, resets=set())
    assert [r["action"] for r in off][1:] == ["hold"] * (T - 1)
    assert all(r["rebalance"] is False for r in off)


# The paper state's json, written the way `paper.save_state` does.
def _state(root: Path, **fields):
    from backend.agents.trading.desk import paper

    paper.save_state(root, paper.PaperState(**fields))


# A record with a paper block, written the way the nightly does.
def _record(root: Path, session: str, paper_block: dict | None):
    folder = root / "desk" / f"asof={session}"
    folder.mkdir(parents=True, exist_ok=True)
    record = {"session": session, "grades": {}, "book": []}
    if paper_block is not None:
        record["paper"] = paper_block
    (folder / "desk.json").write_text(json.dumps(record), encoding="utf-8")


# The reset sessions are the state's last and previous rebalance plus
# every record whose plan was a rebalance the clock accepted; a refused
# rebalance (clock not restarted) and a mid-cycle plan are not resets.
def test_reset_sessions_come_from_the_state_and_the_records(tmp_path):
    from backend.agents.trading.desk import paper

    _state(
        tmp_path,
        last_rebalance="2026-09-27",
        previous_rebalance="2026-08-28",
        sessions_since_rebalance=0,
    )
    _record(tmp_path, "2026-08-28", {"plan": "rebalance", "until_rebalance": 20})
    _record(tmp_path, "2026-09-10", {"plan": "hold", "until_rebalance": 11})
    # A refused rebalance: the clock stayed where it was.
    _record(tmp_path, "2026-09-15", {"plan": "rebalance", "until_rebalance": 8})
    _record(
        tmp_path,
        "2026-07-30",
        {"plan": "rebalance", "until_rebalance": paper.REBALANCE_EVERY},
    )
    _record(tmp_path, "2026-09-16", None)
    found, note = decision_history.reset_sessions(tmp_path)
    assert found == {"2026-07-30", "2026-08-28", "2026-09-27"}
    assert note == decision_history.RESETS_FROM_CLOCK


# No state, or a state that never rebalanced, is no clock: nothing is a
# reset and the note says so, so the chart shows entries and exits only.
def test_reset_sessions_without_a_clock_are_none_and_say_so(tmp_path):
    assert decision_history.reset_sessions(tmp_path) == (
        set(),
        decision_history.RESETS_UNKNOWN,
    )
    _state(tmp_path, last_rebalance=None)
    _record(tmp_path, "2026-08-28", {"plan": "rebalance", "until_rebalance": 20})
    assert decision_history.reset_sessions(tmp_path) == (
        set(),
        decision_history.RESETS_UNKNOWN,
    )
