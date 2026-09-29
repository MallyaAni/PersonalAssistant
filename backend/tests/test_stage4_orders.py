"""Stage 4's orders: the live executor's own orders, read off its journal.

What has to hold (docs/research/stage4-plan-2026-09-29.md, "The decision"
and "The decision test"):

- The journal is passive: the control run with it attached returns stage
  3's T-S1 control to the bit.
- Per decision session t the journal keeps the submitted units, the
  Ledger's kind (reset, mid-cycle, top-up, event) and the closing marks.
- An order is one changed position: on the executed basis the change from
  the mark at t to the mark at t + 1, on the submitted basis the submitted
  units less the shares held at t. Its side, weight (|units| x close_t /
  NAV_t), kind and grade at t are the run's own.
- The finer detail: a sell of a name graded A/A+ is a trim, one graded
  below A a rotation exit (mid-cycle) or a reset exit; a buy is an entry
  (not held), an add (held) or a retry (the previous decision deferred it);
  every order of an event decision is an event order.
- A retried remainder is one order at the retry on the executed basis and
  two on the submitted basis; a sell held back on a green open is no order
  until it trades.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import grading, point_in_time, regime
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_pit_scorecard as sc
from backend.market import stage3_overlay
from backend.market import stage4_orders as so
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE

NAMES = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
T = 320
A_PLUS = grading.ORDINAL["A+"]
A = grading.ORDINAL["A"]
B = grading.ORDINAL["B"]
C = grading.ORDINAL["C"]


# A desk report over T weekdays from 2023-01-02: six names and SPY on a
# random walk. Every name is graded A+ except DDD (A throughout), BBB
# (B on sessions 90-129) and CCC (C on sessions 200-239), so the rotation
# has names to sell mid-cycle.
def _report(seed: int = 0) -> DeskReport:
    rng = np.random.default_rng(seed)
    n = len(NAMES)
    days, day = [], date(2023, 1, 2)
    while len(days) < T:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    dates = np.array(days, dtype="datetime64[D]")
    close = 100.0 * np.exp(rng.normal(0.0004, 0.02, size=(T, n + 1)).cumsum(axis=0))
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
    grades = np.full((T, n + 1), A_PLUS, dtype=int)
    grades[:, NAMES.index("DDD")] = A
    grades[90:130, NAMES.index("BBB")] = B
    grades[200:240, NAMES.index("CCC")] = C
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


# A membership history holding every name throughout.
def _history(tmp_path):
    path = tmp_path / "membership_history.csv"
    rows = ["ticker,entered,entry_announced,exited,exit_announced,source,rule"]
    rows += [f"{t},2016-01-04,2016-01-04,,,test,member throughout" for t in NAMES]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# A journal fed by hand the calls the simulator makes, on three names
# (AAA, BBB, SPY) and seven sessions with the given closes:
#   t0 a reset buys AAA in full and BBB in part (its rest deferred);
#   t1 a mid-cycle decision retries BBB's rest;
#   t2 an FOMC event sells half of AAA;
#   t3 a mid-cycle rotation sells BBB (graded B) but it is held back;
#   t4 it sells BBB again and it trades;
#   t5 a reset top-up session (the Ledger's topup) buys AAA back.
def _fed_journal(closes: np.ndarray) -> so.OrderJournal:
    journal = so.OrderJournal()
    sessions = np.datetime64("2023-03-01", "D") + np.arange(7)
    journal.assert_inputs(sessions, ("AAA", "BBB", "SPY"), closes, closes, 25.0)
    journal.open_account(0, 1.0, np.zeros(3))
    marks = [
        [0.0, 0.0, 0.0],
        [0.004, 0.001, 0.0],
        [0.004, 0.002, 0.0],
        [0.002, 0.002, 0.0],
        [0.002, 0.002, 0.0],
        [0.002, 0.0, 0.0],
        [0.003, 0.0, 0.0],
    ]
    navs = [1.0, 1.01, 1.02, 1.03, 1.04, 1.05, 1.06]
    decisions = [
        (
            [0.004, 0.002, 0.0],
            {
                "scheduled": True,
                "topup": False,
                "event_changed": False,
                "deferred_units": {"BBB": 0.001},
            },
        ),
        (
            [0.004, 0.002, 0.0],
            {
                "scheduled": False,
                "topup": False,
                "event_changed": False,
                "deferred_units": {},
            },
        ),
        ([0.002, 0.002, 0.0], {"event_scale": 0.5}),
        (
            [0.002, 0.0, 0.0],
            {
                "scheduled": False,
                "topup": False,
                "event_changed": False,
                "deferred_units": {},
            },
        ),
        (
            [0.002, 0.0, 0.0],
            {
                "scheduled": False,
                "topup": False,
                "event_changed": False,
                "deferred_units": {},
            },
        ),
        (
            [0.003, 0.0, 0.0],
            {
                "scheduled": False,
                "topup": True,
                "event_changed": False,
                "deferred_units": {},
            },
        ),
    ]
    for t, (units, meta) in enumerate(decisions):
        journal.mark(t, 0.0, np.array(marks[t]), navs[t], 0.0)
        journal.decision(t, np.array(units), None, "test", meta)
    journal.mark(6, 0.0, np.array(marks[6]), navs[6], 0.0)
    return journal


# The journal's record and the orders on both bases, on the hand-fed run:
# kinds as the Ledger classifies them, units, weights, details, the retry,
# the held-back sell and the event; a second decision on a session and a
# decision without its closing mark are refused.
def test_journal_orders_on_a_hand_fed_run():
    closes = np.array([[100.0, 50.0, 400.0]] * 7) * (1 + 0.01 * np.arange(7))[:, None]
    grades = np.full((7, 3), A_PLUS)
    grades[3:, 1] = B
    journal = _fed_journal(closes)
    assert journal.kinds == {
        0: "rebalance",
        1: "midcycle",
        2: "event",
        3: "midcycle",
        4: "midcycle",
        5: "topup",
    }
    assert (
        journal.deferred[0] == frozenset({"BBB"}) and journal.deferred[1] == frozenset()
    )
    np.testing.assert_array_equal(journal.submitted[3], [0.002, 0.0, 0.0])
    executed = so.extract_orders(journal, grades)
    rows = list(
        zip(
            executed.session.tolist(),
            executed.ticker.tolist(),
            executed.side.tolist(),
            executed.kind.tolist(),
            executed.detail.tolist(),
            strict=True,
        )
    )
    assert rows == [
        (0, "AAA", "buy", "rebalance", "entry"),
        (0, "BBB", "buy", "rebalance", "entry"),
        (1, "BBB", "buy", "midcycle", "retry"),
        (2, "AAA", "sell", "event", "event_sell"),
        (4, "BBB", "sell", "midcycle", "rotation_exit"),
        (5, "AAA", "buy", "topup", "add"),
    ]
    np.testing.assert_allclose(
        executed.units, [0.004, 0.001, 0.001, -0.002, -0.002, 0.001]
    )
    np.testing.assert_allclose(
        executed.submitted, [0.004, 0.002, 0.001, -0.002, -0.002, 0.001]
    )
    navs = np.array([1.0, 1.0, 1.01, 1.02, 1.04, 1.05])
    prices = closes[executed.session, executed.column]
    np.testing.assert_allclose(
        executed.weight, np.abs(executed.units) * prices / navs, rtol=1e-15
    )
    assert executed.grade.tolist() == [A_PLUS, A_PLUS, A_PLUS, A_PLUS, B, A_PLUS]
    assert (executed.start, executed.stop, executed.basis) == (0, 6, so.EXECUTED)
    assert executed.meta["status"] == {
        "executed_in_full": 5,
        "executed_in_part": 1,
        "submitted_not_executed": 1,
    }
    # The submitted basis: BBB's reset buy at its full size, and the sell
    # held back at t3 is an order too.
    submitted = so.extract_orders(journal, grades, so.SUBMITTED)
    assert len(submitted) == 7
    held_back = (submitted.session == 3) & (submitted.ticker == "BBB")
    assert held_back.sum() == 1 and submitted.detail[held_back][0] == "rotation_exit"
    assert submitted.executed[held_back][0] == 0.0 and submitted.units[held_back][
        0
    ] == pytest.approx(-0.002)
    reset_bbb = (submitted.session == 0) & (submitted.ticker == "BBB")
    assert submitted.units[reset_bbb][0] == pytest.approx(0.002)
    assert submitted.weight[reset_bbb][0] == pytest.approx(0.002 * 50.0 / 1.0)
    with pytest.raises(ValueError, match="two decisions"):
        journal.decision(2, np.zeros(3), None, "again", {"scheduled": False})
    with pytest.raises(ValueError, match="basis"):
        so.extract_orders(journal, grades, "intended")
    journal.decision(6, np.array([0.0, 0.0, 0.0]), None, "last", {"scheduled": True})
    with pytest.raises(ValueError, match="closing mark"):
        so.extract_orders(journal, grades)
    with pytest.raises(ValueError, match="no run"):
        so.extract_orders(so.OrderJournal(), grades)


# Every branch of the finer classification.
def test_classify_every_branch():
    assert so.classify("sell", "midcycle", A_PLUS, True, False) == so.TRIM
    assert so.classify("sell", "rebalance", A, True, False) == so.TRIM
    assert so.classify("sell", "midcycle", B, True, False) == so.ROTATION_EXIT
    assert so.classify("sell", "topup", C, True, False) == so.ROTATION_EXIT
    assert so.classify("sell", "rebalance", B, True, False) == so.RESET_EXIT
    assert so.classify("sell", "rebalance", -1, True, False) == so.RESET_EXIT
    assert so.classify("buy", "rebalance", A_PLUS, False, False) == so.ENTRY
    assert so.classify("buy", "rebalance", A_PLUS, True, True) == so.ADD
    assert so.classify("buy", "midcycle", A, True, True) == so.RETRY
    assert so.classify("buy", "midcycle", A, False, False) == so.ENTRY
    assert so.classify("buy", "midcycle", A, True, False) == so.ADD
    assert so.classify("buy", "event", A, True, True) == so.EVENT_BUY
    assert so.classify("sell", "event", B, True, False) == so.EVENT_SELL


# The control executor on a synthetic book with downgrades: the journal
# changes nothing (stage 3's control to the bit); every order is exactly
# the run's executed change, with its submitted change, weight, grade and
# kind; every executed change is an order; the downgraded names leave
# through mid-cycle rotation exits at a grade below A, and every trim is
# a sell of an A/A+ name; the submitted basis holds at least as many
# orders, each at its submitted change.
def test_control_run_orders_are_the_executors_own(tmp_path):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, _history(tmp_path))
    since = sc._since(report.panel, 1)
    run = so.run_control(restricted, mask, since)
    reference = stage3_overlay.price(
        restricted,
        mask,
        stage3_overlay.CONTROL,
        since,
        so.COST_BPS,
        None,
        stage3_overlay.windows(None),
    )
    assert run.returns.tobytes() == reference.curve.daily.tobytes()
    orders, journal = run.orders, run.journal
    closes = np.asarray(restricted.panel.adj_close, dtype=float)
    assert len(orders) > 40 and orders.start == 1 and orders.stop == T - 1
    for i in range(len(orders)):
        t, j = int(orders.session[i]), int(orders.column[i])
        _, before, nav, _ = journal.marks[t]
        _, after, _, _ = journal.marks[t + 1]
        assert orders.executed[i] == after[j] - before[j] == orders.units[i]
        assert orders.submitted[i] == journal.submitted[t][j] - before[j]
        assert orders.weight[i] == pytest.approx(
            abs(orders.units[i]) * closes[t, j] / nav, rel=1e-12
        )
        assert orders.grade[i] == restricted.graded.grades[t, j]
        assert orders.kind[i] == journal.kinds[t]
        assert orders.side[i] == ("buy" if orders.units[i] > 0 else "sell")
        assert orders.held[i] == before[j]
    for t in journal.submitted:
        change = journal.marks[t + 1][1] - journal.marks[t][1]
        mine = orders.session == t
        got = np.zeros(len(change))
        got[orders.column[mine]] = orders.units[mine]
        np.testing.assert_array_equal(got, change)
    assert set(orders.kind.tolist()) == {"rebalance", "midcycle"}
    exits = orders.detail == so.ROTATION_EXIT
    assert set(orders.ticker[exits].tolist()) == {"BBB", "CCC"}
    assert (orders.grade[exits] < A).all() and (orders.kind[exits] == "midcycle").all()
    bbb = orders.session[exits & (orders.ticker == "BBB")]
    ccc = orders.session[exits & (orders.ticker == "CCC")]
    assert 90 <= bbb.min() < 130 and 200 <= ccc.min() < 240
    trims = orders.detail == so.TRIM
    assert (
        trims.any()
        and (orders.grade[trims] >= A).all()
        and (orders.side[trims] == "sell").all()
    )
    retries = orders.detail == so.RETRY
    assert (
        retries.any()
        and (orders.kind[retries] == "midcycle").all()
        and orders.buy[retries].all()
    )
    for i in np.flatnonzero(retries):
        assert orders.ticker[i] in journal.deferred[int(orders.session[i]) - 1]
    assert orders.meta["status"]["executed_in_part"] > 0
    submitted = so.extract_orders(journal, restricted.graded.grades, so.SUBMITTED)
    assert len(submitted) >= len(orders)
    np.testing.assert_array_equal(submitted.units, submitted.submitted)
    assert submitted.weight.sum() > orders.weight.sum()


# The offsets start on the scorecard's phases, and the counts add up.
def test_run_offsets_and_counts(tmp_path):
    report = _report()
    restricted, mask = point_in_time.point_in_time(report, _history(tmp_path))
    lines: list[str] = []
    runs = so.run_offsets(restricted, mask, 2, log=lines.append)
    assert [r.start for r in runs] == [0, 1] and len(lines) == 2
    counts = so.order_counts(runs[1])
    assert counts["orders"] == len(runs[1]) == counts["buys"] + counts["sells"]
    assert (
        sum(counts["by_kind"].values())
        == sum(counts["by_detail"].values())
        == counts["orders"]
    )
    assert counts["decision_sessions"] == T - 2
    assert counts["weight_per_session"] == pytest.approx(runs[1].weight.sum() / (T - 2))
    assert counts["min_weight"] > so.DUST and math.isfinite(counts["mean_weight"])
    assert counts["decision_kinds"] == {"rebalance": 16, "midcycle": 302}
    assert sum(counts["submitted_status"].values()) >= counts["orders"]
    subset = runs[1].subset(runs[1].buy)
    assert (
        len(subset) == counts["buys"]
        and subset.buy.all()
        and subset.start == runs[1].start
    )
    # A subset's counts cannot recount the run's submitted changes.
    partial = so.order_counts(subset, sessions=100)
    assert partial["submitted_status"] is None and partial["decision_kinds"] is None
    assert partial["orders_per_session"] == pytest.approx(len(subset) / 100)
    with pytest.raises(ValueError, match="offsets"):
        so.run_offsets(restricted, mask, 0)
