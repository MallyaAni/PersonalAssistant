"""Exercise execution evidence and the adopted-plan decision gates."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from backend.market import decision_view, execution_quotes
from backend.market.holdings import Holding
from backend.tests.test_intraday_candidate import inputs


# Construct fresh quotes and a strategy due for its scheduled rebalance.
def setup():
    record, snapshot, _, _, now = inputs()
    record["paper"] = {"until_rebalance": 0}
    quoted = {
        "feed": "sip",
        "market_open": True,
        "quotes": {
            n: {"bp": 99.99, "ap": 100.01, "bs": 10, "as": 10, "t": now.isoformat()}
            for n in record["grades"]
        },
    }
    return record, snapshot, quoted, now


# A live band reading through the desk's threshold, which is the only thing
# that makes a row read Buy between resets. The board used to manufacture one
# by comparing a position to its target weight; it does not any more, so a
# test that wants a Buy has to supply the signal that causes one.
FIRING = {"S11": 1.5}


# What the desk WANTS and what can be TRADED are different questions, and the
# gates split along that line.
#
# A strategy gate blocks: an FOMC pause really is a hold, a name rejecting its
# upper band is one the desk itself holds back, and a name whose reset is not
# due has no scheduled trade. An execution gate does not: a wide spread, a
# stale quote or a closed market say nothing about whether the desk wants the
# name, and treating them as a view turned all ninety-three rows into Hold
# whenever the market was shut - which is most of the time the page is read.
@pytest.mark.parametrize("block", [None, "band", "fomc"])
def test_a_strategy_gate_blocks_the_buy(block):
    record, snapshot, quoted, now = setup()
    quote = quoted["quotes"]["S11"]
    changes = {
        "stale": (quote, {"t": (now - timedelta(seconds=31)).isoformat()}),
        "future": (quote, {"t": (now + timedelta(seconds=1)).isoformat()}),
        "closed": (quoted, {"market_open": False}),
        "spread": (quote, {"ap": 102}),
        "size": (quote, {"bs": 0}),
        "band": (record, {"levels": {"S11": {"rejecting_band": True}}}),
        "fomc": (record, {"event_risk": {"execution_pending": True}}),
        "schedule": (record, {"paper": {"until_rebalance": 10}}),
        "timing": (record, {"paper": {}}),
        "technical": (snapshot, {"technical": {}}),
    }
    if block:
        target, replacement = changes[block]
        target.update(replacement)
    result = decision_view.build(
        record, [], 100000, snapshot, quoted, now, entries=FIRING, cash=100000
    )["rows"]["S11"]
    assert (result["action"] == "Buy") is (block is None)
    assert result["target_weight"] == 0.1


# Unusable evidence blocks personal action while preserving investment intent;
# the unrelated paper rebalance clock does not block a funded personal entry.
@pytest.mark.parametrize(
    "block", ["stale", "closed", "spread", "size", "future", "timing", "technical"]
)
def test_execution_evidence_blocks_actions_without_erasing_intent(block):
    record, snapshot, quoted, now = setup()
    quote = quoted["quotes"]["S11"]
    changes = {
        "stale": (quote, {"t": (now - timedelta(seconds=31)).isoformat()}),
        "future": (quote, {"t": (now + timedelta(seconds=1)).isoformat()}),
        "closed": (quoted, {"market_open": False}),
        "spread": (quote, {"ap": 102}),
        "size": (quote, {"bs": 0}),
        "timing": (record, {"paper": {}}),
        "technical": (snapshot, {"technical": {}}),
    }
    target, replacement = changes[block]
    target.update(replacement)
    result = decision_view.build(
        record, [], 100000, snapshot, quoted, now, entries=FIRING, cash=100000
    )["rows"]["S11"]
    assert result["strategy_action"] == "Buy"
    assert result["action"] == ("Buy" if block == "timing" else "Hold")
    assert result["executable"] is (block == "timing")
    if block != "timing":
        assert result["move_weight"] == 0


# The gap between a position and its target weight is not an instruction.
#
# The board briefly read it as one, so a name sized below its target printed
# Buy on any session. The targets are a fresh sizing computed every night, not
# a standing order: on the live record the book held 43% of its equity against
# targets summing to 22%, and reading the difference as an instruction printed
# Sell on eight names the desk had no intention of selling. Nothing is traded
# toward those weights until a reset, and no backtest supports doing so.
def test_the_distance_to_a_target_weight_is_not_a_trade():
    record, snapshot, quoted, now = setup()
    record["paper"] = {"until_rebalance": 40}  # the reset is months away
    result = decision_view.build(record, [], 100000, snapshot, quoted, now)["rows"][
        "S11"
    ]
    assert result["action"] == "Hold"
    assert result["move_weight"] == 0.0
    # And it still says what the desk wants, so the row is not merely silent.
    assert "10%" in result["reason"]


# A personal Hold names the person's marked weight, independent of paper holdings.
def test_a_hold_on_a_personal_position_names_the_weight():
    record, snapshot, quoted, now = setup()
    record["paper"] = {
        "until_rebalance": 40,
        "equity": 100000.0,
        "positions": [{"symbol": "S11", "qty": 80.0, "market_value": 8000.0}],
    }
    held = [Holding("S11", 5.0, 100.0, "2026-08-01")]
    result = decision_view.build(record, held, 100000, snapshot, quoted, now)["rows"][
        "S11"
    ]
    expected = 5.0 * snapshot["quotes"]["S11"]["last"] / 100000
    assert result["action"] == "Hold"
    assert result["move_weight"] == 0.0
    assert result["current_weight"] == pytest.approx(expected)
    assert f"{expected:.1%}" in result["reason"]


# Personal holdings must change personal weights and expose uncovered holdings.
def test_the_board_reflects_the_operator_records():
    record, snapshot, quoted, now = setup()
    record["paper"] = {
        "until_rebalance": 40,
        "equity": 100000.0,
        "positions": [{"symbol": "S11", "qty": 80.0, "market_value": 8000.0}],
    }

    # Project the action and sizing fields for each supplied personal portfolio.
    def board(held):
        rows = decision_view.build(
            record, held, 100000, snapshot, quoted, now, entries=FIRING
        )["rows"]
        return {
            t: (r["action"], r["move_weight"], r["current_weight"], r["reason"])
            for t, r in rows.items()
        }

    nothing = board([])
    small = board([Holding("S11", 5.0, 100.0, "2026-08-01")])
    large = board([Holding("S11", 80.0, 100.0, "2026-08-01")])
    assert nothing["S11"][2] == 0
    assert 0 < small["S11"][2] < large["S11"][2]
    uncovered = board([Holding("S99", 999.0, 12.0, "2026-01-02")])
    assert set(uncovered) == set(nothing) | {"S99"}
    assert uncovered["S99"][0] == "Hold"
    assert not uncovered["S99"][1]


# A decision written on the evening of its own session is current, not
# "outdated" until the next session: the nightly record carries today's date.
def test_just_written_decision_is_current():
    record, snapshot, quoted, now = setup()
    record["session"] = "2026-09-14"
    result = decision_view.build(record, [], 100000, snapshot, quoted, now)["rows"][
        "S11"
    ]
    assert "Nightly decision outdated" not in result.get("reason", "")


# IEX is the only feed the account can read; its quotes pass the gate, labelled.
def test_iex_quote_passes_the_gate():
    record, snapshot, quoted, now = setup()
    quoted["feed"] = "iex"
    result = decision_view.build(
        record, [], 100000, snapshot, quoted, now, entries=FIRING, cash=100000
    )["rows"]["S11"]
    assert result["action"] == "Buy"
    assert result["quote"]["feed"] == "iex"
    assert result["quote"]["eligible"]


# A B grade on a name the DESK does not hold is simply a Hold - there is
# nothing to sell. A B grade on one it does hold is a Sell, because the desk
# rotates out of what it no longer rates and into what it does.
#
# The position is the desk's own weight, not the operator's share count. The
# same rotation runs in the nightly off `client.positions()`, so sourcing it
# from a holdings file here made the page a second, wrong answer to a question
# the book had already settled.
@pytest.mark.parametrize(("weight", "expected"), [(0.0, "Hold"), (0.08, "Sell")])
def test_a_b_grade_is_a_hold_unheld_and_a_sell_when_the_desk_holds_it(weight, expected):
    _, _, _, now = setup()
    row = {
        "in_book": True,
        "until_rebalance": 0,
        "rebalance_due": True,
        "rejecting_band": False,
        "grade_live": "B",
    }
    action, move, reason = decision_view.action_for_row(
        row,
        {"eligible": True, "reason": "Quote checks passed"},
        now + timedelta(seconds=20),
        False,
        True,
        0.1,
        weight,
        now,
    )
    assert action == expected
    assert move == (0.0 if weight == 0 else pytest.approx(-weight))


# Expired provider caches are checked by their quote time, not their fetch time.
def test_invalid_quotes_never_gain_eligibility():
    _, _, quoted, now = setup()
    raw = quoted["quotes"]["S11"]
    for replacement in ({"bp": float("nan")}, {"ap": 0}, {"ap": 90}, {"t": "unknown"}):
        assert not execution_quotes.describe({**raw, **replacement}, "sip", True, now)[
            "eligible"
        ]


# Feed fallback is explicit, cached and read-only; provider text is never returned.
def test_quote_access_falls_back_without_hiding_feed(monkeypatch):
    execution_quotes._cache.clear()
    monkeypatch.setattr(execution_quotes, "_sip_retry_at", 0)
    monkeypatch.setattr(execution_quotes.alpaca, "credentials", lambda: {})
    monkeypatch.setattr(
        execution_quotes.alpaca_trading,
        "client_from_env",
        lambda: SimpleNamespace(clock=lambda: {"is_open": True}),
    )
    calls = []

    # Return a forbidden consolidated feed and an available single-exchange quote.
    def request(url, headers):
        calls.append(url)
        return (
            (403, b"private provider text")
            if "feed=sip" in url
            else (200, json.dumps({"quotes": {"AAPL": {"bp": 1}}}).encode())
        )

    result = execution_quotes.fetch(["AAPL"], request, lambda: 100)
    assert result["feed"] == "iex"
    assert result["market_open"]
    assert len(calls) == 2
    assert execution_quotes.fetch(["AAPL"], request, lambda: 101) == result
    assert len(calls) == 2
    assert "private" not in json.dumps(result)
    execution_quotes._cache.clear()


# A single venue's book is not the market.
#
# This account has no consolidated feed, so quotes come from IEX, which
# carries a few percent of US volume. When IEX has nothing resting near the
# touch, its book reads absurdly wide while the national best bid and offer
# is tight. Measured on the live book at 13:49 on 2026-09-18: ALAB showed
# 1021 bp, AAOI 536, BE 439, LITE 178, in the same second that NVDA showed
# 0.5 and ORCL 2.0 on the same feed. Six of twelve plan names were refused
# on that artefact, and the board told the operator "Spread exceeds 25 bp",
# asserting a fact about the market that had not been established.
#
# The asymmetry is the whole point: the NBBO is at least as tight as any one
# venue, so a TIGHT single-venue spread proves the market is tight, while a
# wide one proves nothing at all.
def _wide(feed: str):
    _, _, quoted, now = setup()
    raw = quoted["quotes"]["S11"]
    mid = (float(raw["bp"]) + float(raw["ap"])) / 2
    blown = {**raw, "bp": mid * 0.95, "ap": mid * 1.05}  # about 1000 bp
    return execution_quotes.describe(blown, feed, True, now)


def test_a_wide_spread_on_the_consolidated_feed_still_disqualifies():
    read = _wide("sip")
    assert read["spread_bps"] > execution_quotes.MAX_SPREAD_BPS
    assert read["eligible"] is False
    assert read["reason"] == "Spread exceeds 25 bp"


def test_a_wide_spread_on_one_venue_is_unverified_rather_than_wide():
    read = _wide("iex")
    assert read["spread_bps"] > execution_quotes.MAX_SPREAD_BPS
    # It is reported, so a trader can see it, but it does not refuse the row
    # and it never claims the market is wide.
    assert read["eligible"] is True
    assert read["spread_verified"] is False
    assert "unverified" in read["reason"]
    assert "exceeds" not in read["reason"]


def test_a_tight_single_venue_spread_still_proves_the_market_is_tight():
    _, _, quoted, now = setup()
    read = execution_quotes.describe(quoted["quotes"]["S11"], "iex", True, now)
    assert read["spread_bps"] <= execution_quotes.MAX_SPREAD_BPS
    assert read["eligible"] is True
    assert read["spread_verified"] is True


# The relaxation is about the spread and nothing else: a stale, closed or
# malformed quote is refused on either feed exactly as before.
def test_the_other_guards_are_untouched_on_a_single_venue_feed():
    _, _, quoted, now = setup()
    raw = quoted["quotes"]["S11"]
    assert execution_quotes.describe(raw, "iex", False, now)["eligible"] is False
    assert (
        execution_quotes.describe({**raw, "ap": 0}, "iex", True, now)["eligible"]
        is False
    )
    assert (
        execution_quotes.describe({**raw, "t": "unknown"}, "iex", True, now)["eligible"]
        is False
    )


# The book's mid-cycle entry is what the operator can act on today, so it is
# decided before the rebalance calendar, which is now 120 sessions wide. Without
# this the name the desk buys tonight read "Wait · not held", the opposite of
# what to do about it.
@pytest.mark.parametrize(
    ("weight", "grade", "band", "expected"),
    [
        (0.0, "A+", 1.50, "Buy"),
        (0.0, "A", 1.30, "Buy"),
        (0.05, "A+", 1.50, "Buy"),
        # At the name cap the desk cannot add, so the row says so rather than
        # promising a buy that `_entry_orders` would decline to size.
        (0.15, "A+", 1.50, "Hold"),
        # Below the threshold, below the grade floor, and the retired dip tail:
        # none of these is an entry, so the calendar answers instead.
        (0.0, "A+", 0.90, None),
        (0.0, "B", 1.50, None),
        (0.0, "A+", -1.50, None),
    ],
)
def test_the_live_entry_answers_before_the_calendar(weight, grade, band, expected):
    # `weight` is the desk's own position in the name: the cap the nightly
    # checks is the cap on the book, so the room left under it is the book's.
    row = {"rejecting_band": False, "target_weight": 0.04}
    assert (decision_view.entry_action(row, band, grade, weight) or (None,))[
        0
    ] == expected


# The band gate the nightly applies is applied here too, so the page never
# advertises a buy the nightly is going to hold back.
def test_a_breakout_rejecting_its_band_is_not_offered_as_a_buy():
    row = {"rejecting_band": True, "target_weight": 0.04}
    action, _size, reason = decision_view.entry_action(row, 1.5, "A+")
    # One of the three actions, not a fourth word. This branch returned "Wait"
    # for as long as nothing reached it.
    assert action == decision_view.Action.HOLD
    assert "upper band" in reason


# A name with no live reading falls through to the calendar rather than
# inventing an entry from a missing price.
def test_a_missing_live_stretch_is_not_an_entry():
    row = {"rejecting_band": False, "target_weight": 0.04}
    assert decision_view.entry_action(row, None, "A+") is None
    assert decision_view.entry_action(row, float("nan"), "A+") is None


# A reset target does not veto a graded mid-cycle breakout in either planner.
def test_a_graded_breakout_can_enter_without_a_reset_target():
    row = {"rejecting_band": False, "target_weight": 0.0}
    assert decision_view.entry_action(row, 2.0, "A+")[0] == decision_view.Action.BUY


# The size is the weight to put on now, not the target it moves toward: a
# fresh buy takes ENTRY_ADD, and a held name takes only the room left under
# the name cap.
def test_the_entry_carries_the_weight_to_put_on_now():
    from backend.agents.trading.desk import paper

    row = {"rejecting_band": False, "target_weight": 0.06}
    # The size is the book's own function of the band reading, not a flat
    # increment and not a copy of a constant: a board quoting ENTRY_ADD
    # directly would name a size the nightly would not trade.
    assert decision_view.entry_action(row, 1.5, "A+", 0.0)[1] == paper.entry_size(1.5)
    # Further through the band is a stronger reading at that price, so it is
    # a bigger position. This is the property the flat increment lacked.
    weak = decision_view.entry_action(row, paper.ENTRY_BAND_Z, "A+", 0.0)[1]
    strong = decision_view.entry_action(row, 2.0, "A+", 0.0)[1]
    assert strong > weak > 0
    # A name the DESK already holds close to its cap takes only the room left.
    nearly = paper.ENTRY_NAME_CAP - 0.01
    assert decision_view.entry_action(row, 1.5, "A+", nearly)[1] == pytest.approx(0.01)


# One entry increment per name per session. The board is re-read every candle
# and used to size the same breakout again on each read. A displayed Buy
# remains advice until a fill or working order proves the person acted.
@pytest.mark.parametrize("evidence", ["filled", "pending"])
def test_an_entry_already_taken_this_session_is_not_issued_again(evidence):
    record, snapshot, quoted, now = setup()
    held = []
    extra = {}
    if evidence == "filled":
        # The person recorded today's fill: a holding dated this session.
        held = [Holding("S11", 10, 100.0, "2026-09-11", "2026-09-14")]
    else:
        extra["pending"] = ["S11"]
    rows = decision_view.build(
        record,
        held,
        100000,
        snapshot,
        quoted,
        now,
        entries={"S11": 1.5, "S10": 1.5},
        cash=100000,
        **extra,
    )["rows"]
    assert rows["S11"]["action"] == "Hold"
    assert rows["S11"]["move_weight"] == 0.0
    assert "one entry per name per session" in rows["S11"]["reason"]
    # The other firing name is untouched, and the plan did not fold S11 back in.
    assert rows["S10"]["action"] == "Buy"
    assert rows["S10"]["move_weight"] > 0


# A fill from an earlier session is not this session's increment: the board
# may size the name again when its signal fires on a later day.
def test_a_fill_on_an_earlier_session_does_not_block_todays_entry():
    record, snapshot, quoted, now = setup()
    held = [Holding("S11", 10, 100.0, "2026-09-11")]
    rows = decision_view.build(
        record, held, 100000, snapshot, quoted, now, entries=FIRING, cash=100000
    )["rows"]
    assert rows["S11"]["action"] == "Buy"


# A covered downgrade preserves the exit opinion without assuming a future buy.
def test_a_covered_downgrade_has_an_exit_opinion():
    _, _, _, now = setup()
    row = {
        "in_book": True,
        "until_rebalance": 40,
        "rebalance_due": False,
        "rejecting_band": False,
        "grade_live": "C",
        "shares": 25,
        "target_weight": 0.0,
        "current_weight": 0.04,
    }
    action, move, _reason = decision_view.action_for_row(
        row,
        {"eligible": True, "reason": "Quote checks passed"},
        now + timedelta(seconds=20),
        False,
        True,
        0.0,
        0.04,
        now,
    )
    assert action == decision_view.Action.SELL
    assert move == pytest.approx(-0.04)


# The column can print three words and no others.
#
# This is a guard, not a feature test. The vocabulary has drifted four times:
# "Buy eligible", "Reduce", "Wait" and "entry" all reached a surface a trader
# reads, and the enum was introduced precisely to stop it. It kept happening
# anyway, because the drift was never in `action_for_row` - it was a bare
# string written somewhere else and never checked against this list. Two of
# them ("Wait · FOMC" on the board, "entry" on the chart) survived months.
#
# So every path through the builder is driven here at once: paused and not,
# quoted and unquoted, held and unheld, entry firing and not, every grade.
def test_the_board_can_only_ever_say_one_of_three_things():
    record, snapshot, quoted, now = setup()
    record["paper"] = {
        "until_rebalance": 40,
        "equity": 100000.0,
        "positions": [{"symbol": "S11", "qty": 80.0, "market_value": 8000.0}],
    }
    said = set()
    for paused in (False, True):
        event = {"execution_pending": True} if paused else {}
        for band in (None, 0.5, 1.5, 9.9, float("nan")):
            for allowed in ({}, {"S11": 1.5}):
                built = decision_view.build(
                    {**record, "event_risk": event},
                    [],
                    100000,
                    snapshot,
                    quoted,
                    now,
                    entries={**allowed, **({"S11": band} if band is not None else {})},
                    cash=100000,
                )
                for row in built["rows"].values():
                    said.add(row["action"])
                    # A word is not enough on its own: a Hold must not carry a
                    # move, and a Buy or Sell must.
                    if row["action"] == "Hold":
                        assert row["move_weight"] == 0.0, row
                    else:
                        assert row["move_weight"] != 0.0, row
                    assert row["reason"], row
    assert said <= {a.value for a in decision_view.Action}, said
    assert said <= {"Buy", "Sell", "Hold"}, said
