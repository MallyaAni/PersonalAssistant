"""Synthetic acceptance for what the reviewed intraday modules truly guarantee
about missed opportunities and overtrading, per TURNOVER_VALIDATION_TASK.md.

This is an independent suite over the already-reviewed modules (the comparison
adapter/event ledger, the causal replay/outcome accounting, and the personal
decision view). It makes no new strategy and fits no threshold. What it pins:

* many polls of the same completed-bar prefix keep one stable identity and one
  event per method/symbol/session in the EventLedger and in replay;
* incumbent-only sessions are the "missed while waiting" opportunities, carrying
  the incumbent's own non-zero outcomes with the common session denominator,
  while candidate-only sessions stay separate diagnostics;
* missing and immature labels stay explicit records and are never coerced to a
  zero return or a zero denominator;
* personal additions passed to the real decision view are bounded by the
  person's supplied cash, an uncovered holding is never liquidated, and sale
  proceeds are never assumed to fund a buy;
* after a simulated confirmed fill updates the supplied holdings and cash, a
  recomputation cannot spend the old balance, and zero/unknown cash blocks
  further buys while an explicit sell remains inspectable;
* paper holdings/cash never change personal recommendations on the same inputs.

A one-event-per-session ledger does NOT prove low portfolio turnover: the
dedupe key is (method, symbol, session), so a fresh entry is independently
eligible the next session, and after a fill an add-on is bounded only by the
remaining cash and the name cap. Those cross-session and add-on behaviours are
reported in the review document as unconstrained, not as verified turnover.
"""

from datetime import date, datetime, timedelta
from datetime import time as day_time

import pytest

from backend.agents.trading.desk import paper
from backend.market import decision_view
from backend.market.holdings import Holding
from backend.market.intraday_comparison import (
    CANDIDATE,
    INCUMBENT,
    Eligibility,
    EventLedger,
    compare,
    record_event,
)
from backend.market.intraday_entry import NEW_YORK, Bar, session_open_for
from backend.market.intraday_replay import (
    ENDPOINT_IMMATURE,
    ENDPOINT_MISSING,
    EXECUTION_UNKNOWN,
    PRIMARY_HORIZON,
    RECORDED_ELIGIBILITY,
    SECONDARY_HORIZON,
    replay_session,
    replay_session_outcome,
    session_after,
    summarize,
)
from backend.tests.test_decision_view import setup
from backend.tests.test_intraday_comparison import SESSION, _history
from backend.tests.test_intraday_replay import (
    _bars_through,
    _entry_bars,
    _full_day,
    _ready_outcome,
    _schedule,
)


# One regular-window bar on ``day`` at ``slot`` (0 = 09:30) with the given OHLC.
def _day_bar(day: date, slot: int, o: float, h: float, lo: float, c: float) -> Bar:
    """Return a 15-minute Bar at the given slot and OHLC on ``day``."""
    start = session_open_for(day) + timedelta(minutes=15 * slot)
    return Bar(start=start, open=o, high=h, low=lo, close=c, volume=100.0)


# The standard reclaim path on an arbitrary day: hold, pull back, reclaim.
def _day_reclaim(day: date, close2: float = 245.0) -> list[Bar]:
    """Return a path that breaks the level then reclaims with bar 2 closing close2."""
    return [
        _day_bar(day, 0, 260.0, 262.0, 258.0, 260.0),
        _day_bar(day, 1, 260.0, 260.0, 238.0, 240.0),
        _day_bar(day, 2, close2, close2 + 1.0, close2 - 1.0, close2),
    ]


# The instant a bar's 15-minute window has fully elapsed on ``day``.
def _day_completed(day: date, slot: int):
    """Return the New York instant the slot's window has elapsed on ``day``."""
    return session_open_for(day) + timedelta(minutes=15 * (slot + 1))


# Grade-A eligibility known at ``day``'s session open.
def _day_eligibility(day: date) -> Eligibility:
    """Return an Eligibility known by the session open of ``day``."""
    return Eligibility(
        grade="A",
        grade_available_at=session_open_for(day),
        rejecting_band=False,
        rejecting_band_available_at=session_open_for(day),
    )


# Many refreshes of one finished prefix: one event, one stable identity.
def test_many_polls_of_the_same_prefix_record_one_event_with_stable_identity():
    bars = _day_reclaim(SESSION, 245.0)
    as_of = _day_completed(SESSION, 2)
    ledger: EventLedger = EventLedger()
    first_identity = None
    recorded = 0
    for _ in range(40):
        cmp = compare(
            "AAA",
            SESSION,
            bars,
            _history(),
            _day_eligibility(SESSION),
            as_of,
            price_basis="raw",
        )
        identity = cmp.candidate.identity
        if first_identity is None:
            first_identity = identity
        assert identity == first_identity
        ledger, _event, new = record_event(ledger, cmp.candidate)
        if new:
            recorded += 1
    # 40 polls produced exactly one recorded event and one ledger row.
    assert recorded == 1
    assert len(ledger.events) == 1
    assert ledger.events[(CANDIDATE, "AAA", SESSION)].identity == first_identity
    # A fresh ledger reading the same prefix recognises the identical identity.
    fresh = compare(
        "AAA",
        SESSION,
        bars,
        _history(),
        _day_eligibility(SESSION),
        as_of,
        price_basis="raw",
    )
    assert fresh.candidate.identity == first_identity


# Replay also polls every bar-end and records one event per method per session,
# with identical events on a repeat run.
def test_replay_repeat_refreshes_record_one_event_per_method_per_session():
    bars = _day_reclaim(SESSION, 245.0)
    kwargs = dict(
        symbol="AAA",
        session=SESSION,
        bars=bars,
        history=_history(),
        price_basis="raw",
        eligibility_timeline=[_day_eligibility(SESSION)],
        schedule=_schedule(),
        mode=RECORDED_ELIGIBILITY,
    )
    first = replay_session(**kwargs)
    second = replay_session(**kwargs)
    # All 26 bar-end observations are polls; each method records exactly one
    # event across all of them.
    assert len(first.observations) == 26
    assert set(first.events) == {CANDIDATE, INCUMBENT}
    assert len(first.events) == 2
    assert first.events == second.events
    assert first.events[CANDIDATE].identity == second.events[CANDIDATE].identity
    assert first.events[INCUMBENT].identity == second.events[INCUMBENT].identity
    # Readiness is counted separately from events: each method was observed
    # ready once on this prefix, and that did not multiply into events.
    assert first.readiness_counts[CANDIDATE] == 1
    assert first.readiness_counts[INCUMBENT] == 1
    assert len(first.events) == 2


# The ledger dedupes within a session, never across sessions: a fresh session is
# a fresh key, so cross-session repeat entry is one event per session, not one
# event in total. This is the honest boundary the review reports.
def test_cross_session_repeat_entry_is_one_event_per_session_not_one_total():
    ledger: EventLedger = EventLedger()
    days = [SESSION, date(2026, 1, 7), date(2026, 1, 8)]
    for day in days:
        cmp = compare(
            "AAA",
            day,
            _day_reclaim(day, 245.0),
            _history(),
            _day_eligibility(day),
            _day_completed(day, 2),
            price_basis="raw",
        )
        ledger, event, new = record_event(ledger, cmp.candidate)
        assert new is True
        assert event.session == day
    assert len(ledger.events) == 3
    assert {e.session for e in ledger.events.values()} == set(days)


# Missed-waiting attribution: incumbent-only sessions are the missed
# opportunities and carry the incumbent's own non-zero outcomes; candidate-only
# sessions are a separate diagnostic and the denominator is shared.
def test_missed_waiting_attribution_shares_denominators_and_keeps_outcomes():
    schedule = _schedule()
    both_day = SESSION
    incumbent_only_day = date(2026, 1, 7)
    candidate_only_day = date(2026, 1, 9)
    neither_day = date(2026, 1, 8)
    both_sec = session_after(schedule, both_day, SECONDARY_HORIZON)[0]
    both_pri = session_after(schedule, both_day, PRIMARY_HORIZON)[0]
    inc_sec = session_after(schedule, incumbent_only_day, SECONDARY_HORIZON)[0]
    inc_pri = session_after(schedule, incumbent_only_day, PRIMARY_HORIZON)[0]
    cand_sec = session_after(schedule, candidate_only_day, SECONDARY_HORIZON)[0]
    cand_pri = session_after(schedule, candidate_only_day, PRIMARY_HORIZON)[0]

    both = _ready_outcome(
        both_day, 250.0, invalidate=True, closes={both_sec: 260.0, both_pri: 280.0}
    )
    incumbent_only = replay_session_outcome(
        symbol="AAA",
        session=incumbent_only_day,
        bars=_full_day(incumbent_only_day, 260.0),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=[_day_eligibility(incumbent_only_day)],
        schedule=schedule,
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=_bars_through(
            incumbent_only_day, schedule, closes={inc_sec: 270.0, inc_pri: 280.0}
        ),
    )
    candidate_only = _ready_outcome(
        candidate_only_day,
        245.0,
        invalidate=True,
        closes={cand_sec: 250.0, cand_pri: 255.0},
    )
    neither = replay_session_outcome(
        symbol="AAA",
        session=neither_day,
        bars=_full_day(neither_day, 230.0),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=[_day_eligibility(neither_day)],
        schedule=schedule,
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=_bars_through(neither_day, schedule),
    )
    assert incumbent_only.incumbent.event is not None
    assert incumbent_only.candidate.event is None
    summary = summarize(
        [both, incumbent_only, candidate_only, neither],
        mode=RECORDED_ELIGIBILITY,
        price_basis="raw",
    )
    # Common opportunity denominator: all four sessions count once.
    assert summary.session_count == 4
    assert (
        summary.both_entries,
        summary.incumbent_only,
        summary.candidate_only,
        summary.neither_entries,
    ) == (1, 1, 1, 1)
    assert (
        summary.both_entries
        + summary.incumbent_only
        + summary.candidate_only
        + summary.neither_entries
        == summary.session_count
    )
    # Only the incumbent-only session is a missed-waiting opportunity, carrying
    # the incumbent's own actual (non-zero) primary and secondary outcomes.
    assert summary.missed_opportunity_count == 1
    assert summary.missed_opportunity_incumbent_primary.count == 1
    assert summary.missed_opportunity_incumbent_primary.mean == pytest.approx(
        280.0 / 260.0 - 1.0
    )
    assert summary.missed_opportunity_incumbent_secondary.count == 1
    assert summary.missed_opportunity_incumbent_secondary.mean == pytest.approx(
        270.0 / 260.0 - 1.0
    )
    # The candidate-only session is reported as its own diagnostic in the
    # candidate's missed-opportunity fields, never as what waiting missed: the
    # incumbent had no entry there, so waiting missed nothing.
    assert summary.missed_opportunity_candidate_primary.count == 1
    assert summary.missed_opportunity_candidate_primary.mean == pytest.approx(
        255.0 / 246.0 - 1.0
    )
    assert summary.candidate_primary.count == 2
    assert summary.candidate_secondary.count == 2
    assert summary.paired_entry_count == 1


# Missing and immature labels stay explicit records: they are counted as
# coverage, never coerced into a zero return or a zero mean.
def test_missing_and_immature_labels_stay_explicit_never_zeroed():
    schedule = _schedule()
    missing_exec_day = SESSION
    immature_day = date(2026, 1, 7)
    missing_endpoint_day = date(2026, 1, 9)

    # A missing next bar after the signal leaves execution unknown.
    bars = _entry_bars(missing_exec_day, 245.0)
    missing_third = [bars[0], bars[1], bars[2], bars[4], *bars[5:]]
    no_exec = replay_session_outcome(
        symbol="AAA",
        session=missing_exec_day,
        bars=missing_third,
        history=_history(),
        price_basis="raw",
        eligibility_timeline=[_day_eligibility(missing_exec_day)],
        schedule=schedule,
        mode=RECORDED_ELIGIBILITY,
        outcome_bars={},
    )
    # Outcome bars that stop before the horizon make the label immature.
    secondary = session_after(schedule, immature_day, SECONDARY_HORIZON)[0]
    truncated = {}
    day = immature_day
    while day < secondary:
        if schedule.is_session(day):
            truncated[day] = _full_day(day, 260.0)
        day += timedelta(days=1)
    immature = replay_session_outcome(
        symbol="AAA",
        session=immature_day,
        bars=_entry_bars(immature_day, 245.0),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=[_day_eligibility(immature_day)],
        schedule=schedule,
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=truncated,
    )
    # The primary endpoint session is present in the data but its bars were
    # removed: the label is missing, not immature.
    primary = session_after(schedule, missing_endpoint_day, PRIMARY_HORIZON)[0]
    endpoint_bars = _bars_through(missing_endpoint_day, schedule)
    del endpoint_bars[primary]
    after_close = datetime.combine(primary, day_time(16, 1), NEW_YORK)
    missing = replay_session_outcome(
        symbol="AAA",
        session=missing_endpoint_day,
        bars=_entry_bars(missing_endpoint_day, 245.0),
        history=_history(),
        price_basis="raw",
        eligibility_timeline=[_day_eligibility(missing_endpoint_day)],
        schedule=schedule,
        mode=RECORDED_ELIGIBILITY,
        outcome_bars=endpoint_bars,
        data_as_of=after_close,
    )
    assert no_exec.candidate.execution.status == EXECUTION_UNKNOWN
    assert no_exec.candidate.primary.status == ENDPOINT_MISSING
    assert no_exec.candidate.primary.forward_return is None
    assert immature.candidate.primary.status == ENDPOINT_IMMATURE
    assert immature.candidate.primary.forward_return is None
    assert missing.candidate.primary.status == ENDPOINT_MISSING
    assert missing.candidate.primary.forward_return is None

    summary = summarize(
        [no_exec, immature, missing],
        mode=RECORDED_ELIGIBILITY,
        price_basis="raw",
    )
    assert summary.missing_execution_count == 1
    assert summary.missing_outcome_count == 1
    assert summary.immature_outcome_count == 1
    # None of the three could produce a complete primary label: the conditional
    # mean is empty (None), never a coerced 0.0 with a fabricated count. The
    # secondary stays complete on the missing-endpoint session, whose endpoint
    # bars survived, so its conditional mean is a real number over a counted set.
    assert summary.candidate_primary.count == 0
    assert summary.candidate_primary.mean is None
    assert summary.candidate_secondary.count == 1
    assert summary.candidate_secondary.mean == pytest.approx(260.0 / 246.0 - 1.0)


# Personal additions are one account-wide cash bound, not a per-row claim.
def test_personal_proposed_additions_stay_within_supplied_cash():
    record, snapshot, quoted, now = setup()
    held = [Holding("S11", 60.0, 100.0, "2026-08-01")]
    equity = 100000.0
    rows = decision_view.build(
        record,
        held,
        equity,
        snapshot,
        quoted,
        now,
        entries={"S10": 1.5, "S11": 1.5},
        cash=3000.0,
    )["rows"]
    total_buys = sum(
        row["move_weight"] * equity
        for row in rows.values()
        if row["action"] == decision_view.Action.BUY
    )
    assert total_buys == pytest.approx(3000.0)
    assert rows["S10"]["strategy_action"] == decision_view.Action.BUY
    assert rows["S11"]["strategy_action"] == decision_view.Action.BUY
    for row in rows.values():
        if row["action"] == decision_view.Action.BUY:
            assert row["move_weight"] <= paper.ENTRY_NAME_CAP


# A name the person holds but the desk does not cover is review, never a sale.
def test_uncovered_personal_holding_is_review_never_a_liquidation():
    record, snapshot, quoted, now = setup()
    rows = decision_view.build(
        record,
        [Holding("ZZZ", 100.0, 100.0, "2026-08-01")],
        100000,
        snapshot,
        quoted,
        now,
        cash=1000.0,
    )["rows"]
    assert rows["ZZZ"]["action"] == decision_view.Action.HOLD
    assert rows["ZZZ"]["move_weight"] == 0.0
    assert rows["ZZZ"]["strategy_action"] == decision_view.Action.HOLD


# A covered downgrade is an explicit sell, but its proceeds are never assumed:
# zero cash blocks the buy of another name even though a sale would raise money.
def test_zero_cash_blocks_buys_while_explicit_exit_remains_inspectable():
    record, snapshot, quoted, now = setup()
    grade = record["grades"]["S11"]
    grade.update(
        grade="C",
        stances={
            "technical": -1,
            "value": -1,
            "fundamental": -1,
            "sentiment": -1,
        },
        ranks={"technical": 0.2, "value": 0.1},
    )
    held = [Holding("S11", 100.0, 100.0, "2026-08-01")]
    rows = decision_view.build(
        record,
        held,
        100000,
        snapshot,
        quoted,
        now,
        entries={"S10": 1.5},
        cash=0.0,
    )["rows"]
    assert rows["S11"]["strategy_action"] == decision_view.Action.SELL
    assert rows["S11"]["action"] == decision_view.Action.SELL
    assert rows["S11"]["move_weight"] == pytest.approx(-rows["S11"]["current_weight"])
    assert rows["S11"]["executable"] is True
    # No assumed proceeds: the S10 buy is not funded by the S11 sale.
    assert rows["S10"]["strategy_action"] == decision_view.Action.BUY
    assert rows["S10"]["action"] == decision_view.Action.HOLD
    assert rows["S10"]["move_weight"] == 0.0
    assert rows["S10"]["executable"] is False
    assert "no available cash" in rows["S10"]["reason"]


# After a confirmed fill updates the supplied holdings and cash, recomputation
# is bounded by the remaining cash: it cannot spend the old balance again.
def test_after_a_confirmed_fill_recomputation_cannot_spend_the_old_balance():
    record, snapshot, quoted, now = setup()
    equity = 100000.0
    price = snapshot["quotes"]["S11"]["last"]
    entries = {"S10": 1.5, "S11": 1.5}
    first = decision_view.build(
        record,
        [Holding("S11", 60.0, price, "2026-08-01")],
        equity,
        snapshot,
        quoted,
        now,
        entries=entries,
        cash=7000.0,
    )["rows"]
    first_buys = sum(
        row["move_weight"] * equity
        for row in first.values()
        if row["action"] == decision_view.Action.BUY
    )
    assert first_buys > 0
    # Simulated confirmed fill: add the bought shares and deduct the spent cash.
    filled_shares = {"S11": 60.0}
    for symbol, row in first.items():
        if row["action"] == decision_view.Action.BUY:
            fill_price = snapshot["quotes"][symbol]["last"]
            filled_shares[symbol] = (
                filled_shares.get(symbol, 0.0)
                + row["move_weight"] * equity / fill_price
            )
    new_held = [
        Holding(symbol, shares, snapshot["quotes"][symbol]["last"], "2026-08-01")
        for symbol, shares in filled_shares.items()
    ]
    new_cash = 7000.0 - first_buys
    second = decision_view.build(
        record,
        new_held,
        equity,
        snapshot,
        quoted,
        now,
        entries=entries,
        cash=new_cash,
    )["rows"]
    second_buys = sum(
        row["move_weight"] * equity
        for row in second.values()
        if row["action"] == decision_view.Action.BUY
    )
    # The repeated computation is bounded by the remaining cash, never the old
    # balance, and any add-on is bounded by the name cap.
    assert second_buys <= new_cash + 1e-6
    assert second_buys < first_buys
    for row in second.values():
        if row["action"] == decision_view.Action.BUY:
            assert row["move_weight"] <= paper.ENTRY_NAME_CAP


# Unknown cash cannot claim a funded buy either: no personal cash means no
# executable purchase, and the paper account's cash never becomes personal.
def test_unknown_personal_cash_never_borrows_paper_cash():
    record, snapshot, quoted, now = setup()
    record["paper"] = {"cash": 50000.0, "positions": [], "until_rebalance": 0}
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
    )["rows"]["S11"]
    assert row["strategy_action"] == decision_view.Action.BUY
    assert row["action"] == decision_view.Action.HOLD
    assert row["move_weight"] == 0.0
    assert row["executable"] is False
    assert "available cash is unknown" in row["reason"]


# Paper holdings and cash never change personal recommendations on the same
# inputs: the personal board is a pure function of the person's own state.
def test_paper_holdings_and_cash_never_alter_personal_recommendations():
    record, snapshot, quoted, now = setup()
    held = [Holding("S11", 5.0, 100.0, "2026-08-01")]
    base = decision_view.build(
        record,
        held,
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=1000.0,
    )["rows"]
    paper_variants = (
        {
            "cash": 999999.0,
            "equity": 1e9,
            "positions": [{"symbol": "S99", "qty": 5000.0, "market_value": 5e8}],
            "until_rebalance": 0,
        },
        {"cash": 0.0, "equity": 0.0, "positions": [], "until_rebalance": 40},
    )
    for block in paper_variants:
        changed = {**record, "paper": block}
        rows = decision_view.build(
            changed,
            held,
            100000,
            snapshot,
            quoted,
            now,
            entries={"S11": 1.5},
            cash=1000.0,
        )["rows"]
        assert rows == base
        assert "S99" not in rows
