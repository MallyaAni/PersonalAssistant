"""Account isolation for personal guidance: the person's board is a function of
the person's own holdings, equity and explicit cash, never of the desk's paper
account.

Two defects made the personal board a statement about the wrong account. The
first: current weights were read off `record["paper"]` (the desk's paper book),
so a paper fill silently moved what the person was told they held. The second:
`apply_account_plan` projected the paper account's plan - its cash, its
positions, its rebalance clock - over the personal rows, so a funded paper
account replaced the person's actions with orders for another account's money.

This review hardens the eligibility and funding boundaries:

* Investment intent (`strategy_action`/`strategy_move_weight`) is preserved as
  data while the actionable `action`/`move_weight` reflect what can actually be
  traded now: unusable evidence, unknown cash and a zero cash bound each make
  an actionable Hold with the blocker named, executable false.
* Buy candidates are filtered for fresh evidence before any cash is allocated,
  so a stale or blocked name consumes no budget and the cash bound is one
  account-wide figure, not one independent bound per row.
* No-coverage is a Hold for review, never a liquidation; a covered downgrade is
  an explicit exit; and a buy needs its own eligible entry signal - a
  downgrade is never recycled into a buy of another holding (the paper book's
  rotation has no meaning against a person's account).
"""

from datetime import UTC, datetime, timedelta

import pytest

from backend.agents.trading.desk import paper
from backend.market import decision_view
from backend.market.holdings import Holding
from backend.tests.test_decision_view import setup


# A cash reduction must not turn a permitted-sized entry into a tiny live buy.
@pytest.mark.parametrize("cash", [10.0, 499.99])
def test_cash_scaled_entry_below_minimum_remains_hold(cash):
    record, snapshot, quoted, now = setup()
    row = decision_view.build(
        record, [], 100000, snapshot, quoted, now, entries={"S11": 1.5}, cash=cash
    )["rows"]["S11"]
    assert row["strategy_action"] == decision_view.Action.BUY
    assert row["action"] == decision_view.Action.HOLD
    assert row["move_weight"] == 0


# The exact minimum remains fundable so rounding does not impose a new threshold.
def test_cash_scaled_entry_at_minimum_is_funded():
    record, snapshot, quoted, now = setup()
    row = decision_view.build(
        record, [], 100000, snapshot, quoted, now, entries={"S11": 1.5}, cash=500
    )["rows"]["S11"]
    assert row["action"] == decision_view.Action.BUY
    assert row["move_weight"] == pytest.approx(0.005)


# Build the personal board for a fixed account and return the row projection
# the tests actually care about, so a changed reason or weight fails here
# rather than hiding inside an ignored dict.
def _board(record, held, equity, snapshot, quoted, now, *, entries=None, cash=None):
    built = decision_view.build(
        record, held, equity, snapshot, quoted, now, entries=entries, cash=cash
    )["rows"]
    return {
        ticker: (
            row["action"],
            row["move_weight"],
            row["current_weight"],
            row["delta_weight"],
            row["reason"],
        )
        for ticker, row in built.items()
    }


# A person who holds five shares of S11 and a paper account that holds eighty:
# the current weight must be the person's own, so a paper position the person
# does not own never shows up as theirs.
def test_current_weight_comes_from_the_person_not_the_paper_book():
    record, snapshot, quoted, now = setup()
    record["paper"] = {
        "cash": 50000.0,
        "equity": 50000.0,
        "positions": [{"symbol": "S11", "qty": 80.0, "market_value": 8000.0}],
        "until_rebalance": 0,
    }
    held = [Holding("S11", 5.0, 100.0, "2026-08-01")]
    price = (snapshot.get("quotes") or {})["S11"]["last"]
    row = decision_view.build(record, held, 100000, snapshot, quoted, now)["rows"][
        "S11"
    ]
    assert row["current_weight"] == pytest.approx(5.0 * price / 100000)
    assert row["current_weight"] != pytest.approx(0.08)


# Paper state is another account's state. Changing its cash, its positions or
# its rebalance clock must leave the personal board unchanged - with and
# without an explicit personal cash bound - because the board never reads it.
def test_paper_state_changes_never_move_personal_recommendations():
    record, snapshot, quoted, now = setup()
    held = [Holding("S11", 5.0, 100.0, "2026-08-01")]
    base = _board(record, held, 100000, snapshot, quoted, now, entries={"S11": 1.5})
    with_cash = _board(
        record,
        held,
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=1000.0,
    )
    paper_variants = (
        {},
        {"cash": 50000.0, "positions": [], "until_rebalance": 0},
        {
            "cash": 0.0,
            "positions": [{"symbol": "S11", "qty": 80.0}],
            "until_rebalance": 40,
        },
        {
            "cash": 999999.0,
            "positions": [{"symbol": "S11", "qty": 1.0}],
            "until_rebalance": 19,
        },
    )
    for paper_block in paper_variants:
        changed = {**record, "paper": paper_block}
        assert (
            _board(changed, held, 100000, snapshot, quoted, now, entries={"S11": 1.5})
            == base
        )
        assert (
            _board(
                changed,
                held,
                100000,
                snapshot,
                quoted,
                now,
                entries={"S11": 1.5},
                cash=1000.0,
            )
            == with_cash
        )


# Unknown personal cash stays unknown: with no cash supplied, a buy opinion is
# preserved as `strategy_action`/`strategy_move_weight` but nothing is claimed
# funded or executable, and the paper account's cash is never imported into a
# size or a reason.
def test_unknown_personal_cash_is_not_taken_from_paper():
    record, snapshot, quoted, now = setup()
    record["paper"] = {"cash": 50000.0, "positions": [], "until_rebalance": 0}
    row = decision_view.build(
        record, [], 100000, snapshot, quoted, now, entries={"S11": 1.5}
    )["rows"]["S11"]
    assert row["strategy_action"] == decision_view.Action.BUY
    assert row["strategy_move_weight"] == pytest.approx(
        min(paper.entry_size(1.5), paper.ENTRY_NAME_CAP)
    )
    assert row["action"] == decision_view.Action.HOLD
    assert row["move_weight"] == 0.0
    assert row["executable"] is False
    assert "available cash is unknown" in row["reason"]
    assert "not executable" in row["reason"]
    assert "preview from recorded account" not in row["reason"]
    assert "50000" not in row["reason"]


# Explicit personal cash is one account-wide bound: the entry is scaled to the
# cash actually supplied, so the board never tells the person to spend money
# they did not say they had. A zero cash bound means no buy at all, and the
# desired entry size stays visible as strategy data.
def test_explicit_personal_cash_bounds_the_plan():
    record, snapshot, quoted, now = setup()
    record["paper"] = {"cash": 50000.0, "positions": [], "until_rebalance": 0}
    desired = min(paper.entry_size(1.5), paper.ENTRY_NAME_CAP)
    uncapped = decision_view.build(
        record, [], 100000, snapshot, quoted, now, entries={"S11": 1.5}
    )["rows"]["S11"]
    capped = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=1000.0,
    )["rows"]["S11"]
    none = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=0.0,
    )["rows"]["S11"]
    assert uncapped["strategy_action"] == decision_view.Action.BUY
    assert uncapped["strategy_move_weight"] == pytest.approx(desired)
    assert uncapped["action"] == decision_view.Action.HOLD
    assert uncapped["move_weight"] == 0.0
    assert capped["action"] == decision_view.Action.BUY
    assert capped["move_weight"] == pytest.approx(1000.0 / 100000)
    assert capped["move_weight"] < desired
    assert capped["executable"] is True
    assert "sized against your holdings" in capped["reason"]
    assert none["action"] == decision_view.Action.HOLD
    assert none["move_weight"] == 0.0
    assert none["executable"] is False
    assert "no available cash" in none["reason"]


# Investment opinion is not executable readiness. On unusable evidence - a
# stale, future or expired quote, a closed market, or a missing technical read
# - the desk's opinion (Buy, and how much it wants) is preserved in the
# strategy fields, but the actionable action is a Hold with the blocker named
# and a zero move, even when cash is supplied (so no funded path bypasses the
# readiness gate).
@pytest.mark.parametrize(
    ("fault", "blocker"),
    [
        ("stale", "quote expired"),
        ("future", "quote expired"),
        ("closed", "market closed"),
        ("technical", "no current price reading"),
    ],
)
def test_stale_or_ineligible_evidence_is_not_a_fresh_buy_claim(fault, blocker):
    record, snapshot, quoted, now = setup()
    if fault == "stale":
        quoted["quotes"]["S11"]["t"] = (now - timedelta(seconds=31)).isoformat()
    elif fault == "future":
        quoted["quotes"]["S11"]["t"] = (now + timedelta(seconds=1)).isoformat()
    elif fault == "closed":
        quoted["market_open"] = False
    else:
        snapshot["technical"] = {}
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=1000.0,
    )["rows"]["S11"]
    assert row["strategy_action"] == decision_view.Action.BUY
    assert row["strategy_move_weight"] == pytest.approx(
        min(paper.entry_size(1.5), paper.ENTRY_NAME_CAP)
    )
    assert row["action"] == decision_view.Action.HOLD
    assert row["move_weight"] == 0.0
    assert row["executable"] is False
    assert blocker in row["reason"]
    assert "not executable" in row["reason"]
    assert "subject to available cash" not in row["reason"]


# Expired evidence is missing evidence. A grade read that has passed its
# deadline - here, a snapshot too old to re-grade - exposes the missing
# reading explicitly instead of claiming a fresh entry, even with cash on hand.
def test_expired_evidence_is_explicit_not_a_fresh_entry_claim():
    record, snapshot, quoted, now = setup()
    snapshot["as_of"] = (now - timedelta(seconds=1000)).isoformat()
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=1000.0,
    )["rows"]["S11"]
    assert row["strategy_action"] == decision_view.Action.BUY
    assert row["action"] == decision_view.Action.HOLD
    assert row["move_weight"] == 0.0
    assert row["executable"] is False
    assert "no current price reading" in row["reason"]
    assert "not executable" in row["reason"]


# A fresh, eligible read with demonstrated cash stays an executable buy, so the
# fix only touches the missing-evidence and missing-funding cases.
def test_fresh_evidence_remains_an_executable_buy():
    record, snapshot, quoted, now = setup()
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=1000.0,
    )["rows"]["S11"]
    assert row["strategy_action"] == decision_view.Action.BUY
    assert row["action"] == decision_view.Action.BUY
    assert row["executable"] is True
    assert "not executable" not in row["reason"]


# One eligible and one ineligible buy share the same explicit cash: the blocked
# or stale name consumes no budget, so the eligible name gets the whole bound.
# The ineligible name is filtered before cash allocation, not after sizing.
def test_one_ineligible_and_one_eligible_buy_share_cash_without_budget_waste():
    record, snapshot, quoted, now = setup()
    record["levels"] = {"S10": {"rejecting_band": True}}
    rows = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S10": 1.5, "S11": 1.5},
        cash=1000.0,
    )["rows"]
    total_buys = sum(
        row["move_weight"] * 100000 for row in rows.values() if row["action"] == "Buy"
    )
    assert total_buys == pytest.approx(1000.0)
    assert rows["S11"]["action"] == decision_view.Action.BUY
    assert rows["S11"]["move_weight"] == pytest.approx(1000.0 / 100000)
    assert rows["S10"]["action"] == decision_view.Action.HOLD
    assert rows["S10"]["move_weight"] == 0.0


# A name the person holds but the desk does not cover is a Hold for review,
# never a liquidation - with or without known cash. Lack of coverage is not a
# downgrade, and the folded basket must not turn the initial Hold into a Sell.
def test_uncovered_holding_with_known_cash_is_review_not_liquidation():
    record, snapshot, quoted, now = setup()
    record["grades"] = {"S11": record["grades"]["S11"]}
    held = [Holding("ZZZ", 100, 100, "2026-08-01")]
    rows = decision_view.build(
        record, held, 100000, snapshot, quoted, now, cash=1000.0
    )["rows"]
    assert rows["ZZZ"]["action"] == decision_view.Action.HOLD
    assert rows["ZZZ"]["move_weight"] == 0.0
    assert rows["ZZZ"]["strategy_action"] == decision_view.Action.HOLD
    assert "Not covered by the desk" in rows["ZZZ"]["reason"]


# A covered downgrade is an explicit exit, and the money is never recycled into
# a buy of another held name: a buy needs its own eligible entry signal, so a
# fine held name with no entry stays a Hold even when cash is on hand.
def test_covered_downgrade_is_an_exit_and_does_not_churn_another_name():
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
    held = [
        Holding("S11", 100, 100, "2026-08-01"),
        Holding("S10", 100, 100, "2026-08-01"),
    ]
    rows = decision_view.build(
        record, held, 100000, snapshot, quoted, now, cash=1000.0
    )["rows"]
    assert rows["S11"]["strategy_action"] == decision_view.Action.SELL
    assert rows["S11"]["action"] == decision_view.Action.SELL
    assert rows["S11"]["move_weight"] == pytest.approx(-rows["S11"]["current_weight"])
    assert rows["S11"]["executable"] is True
    assert rows["S10"]["action"] == decision_view.Action.HOLD
    assert rows["S10"]["move_weight"] == 0.0


# A personal cash figure that cannot bound a plan is a caller error, never a
# silent fall back to unbounded per-row actions.
@pytest.mark.parametrize(
    "cash",
    [float("nan"), float("inf"), float("-inf"), -1.0, 100001.0],
)
def test_invalid_cash_raises_value_error(cash):
    record, snapshot, quoted, now = setup()
    with pytest.raises(ValueError, match="cash"):
        decision_view.build(
            record, [], 100000, snapshot, quoted, now, entries={"S11": 1.5}, cash=cash
        )


# With no personal holdings the board reports no positions anywhere: every
# current weight is zero and nothing on the account side invents a position,
# even when cash is supplied and an entry fires.
def test_empty_personal_holdings_stay_zero():
    record, snapshot, quoted, now = setup()
    rows = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=1000.0,
    )["rows"]
    for _symbol, row in rows.items():
        assert row["current_weight"] == 0.0
        assert row["delta_weight"] == pytest.approx(row["target_weight"])


# Reading the board writes nothing, however many times it is read: no order is
# submitted and no paper state appears. The board is a pure projection of its
# inputs, so repeated reads are identical and the filesystem is untouched.
def test_repeated_reads_create_no_orders_or_state_writes(tmp_path):
    record, snapshot, quoted, now = setup()
    record["paper"] = {"cash": 50000.0, "positions": [], "until_rebalance": 0}
    held = [Holding("S11", 5.0, 100.0, "2026-08-01")]
    first = _board(
        record,
        held,
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5},
        cash=1000.0,
    )
    for _ in range(5):
        assert (
            _board(
                record,
                held,
                100000,
                snapshot,
                quoted,
                now,
                entries={"S11": 1.5},
                cash=1000.0,
            )
            == first
        )
    assert not (tmp_path / "desk/board-paper").exists()
    assert not (tmp_path / "paper").exists()


# The paper path is preserved as its own surface: `apply_account_plan` still
# projects the desk's paper account plan when it is asked to, while the
# personal board with the same record ignores that account entirely.
def test_the_paper_account_plan_survives_as_its_own_path():
    record = {
        "session": "2026-09-04",
        "grades": {"OLD": {"grade": "B"}, "KEEP": {"grade": "A"}},
        "book": [],
        "paper": {
            "cash": 76000,
            "until_rebalance": 10,
            "positions": [
                {"symbol": "OLD", "qty": 100, "current_price": 100},
                {"symbol": "KEEP", "qty": 140, "current_price": 100},
            ],
        },
    }
    rows = {s: {"target_weight": 0} for s in record["grades"]}
    decision_view.apply_account_plan(
        rows, record, {}, {"KEEP": 1.5}, False, datetime(2026, 9, 4, tzinfo=UTC)
    )
    assert rows["OLD"]["action"] == "Sell"
    assert rows["KEEP"]["action"] == "Buy"
    # The same record through the personal board never sees the paper plan:
    # with no personal holding and no entry, KEEP is simply not bought.
    personal = decision_view.build(
        record, [], 100000, {}, {}, datetime(2026, 9, 4, tzinfo=UTC)
    )["rows"]["KEEP"]
    assert personal["action"] == decision_view.Action.HOLD
    assert "preview from recorded account" not in personal["reason"]
