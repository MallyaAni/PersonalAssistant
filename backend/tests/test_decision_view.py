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


# ---------------------------------------------------------------------------
# The active policy's targets are a standing order.
#
# Since 2026-09-27 the paper account runs `graded-equal-weight/4`: every A/A+
# name at equal weight, exits on a downgrade, idle cash redeployed toward the
# targets mid-cycle, trims at the reset. The nightly stamps the record with
# `targets = {"policy": live_policy.ACTIVE, "weights": {...}}`, and for such a
# record the board trades the gap between what the person holds and the
# policy's weight - the `/3`-era "targets are not a standing order" rule is a
# fact about `/3` records, which keep it
# (`test_the_distance_to_a_target_weight_is_not_a_trade`).
# ---------------------------------------------------------------------------

POLICY = "graded-equal-weight/4"


# A `/4` record: eleven of the twelve graded names at 1/11 each, S0 at zero.
def _v4(record, *, until_rebalance=10):
    record["targets"] = {
        "policy": POLICY,
        "weights": {n: (0.0 if n == "S0" else 1 / 11) for n in record["grades"]},
    }
    record["paper"] = {"until_rebalance": until_rebalance}
    return record


# Shares of S11 worth `weight` of a 100,000 account at the snapshot's price.
def _shares(snapshot, weight, symbol="S11"):
    return weight * 100000 / snapshot["quotes"][symbol]["last"]


# A test double of today's entry-timing latch in which every name's level
# triggered on the snapshot's bar, on both sides. Since 2026-09-28 the `/4`
# board says Buy or Sell only once the measured level has triggered (or in
# the close window); the tests below are about sizing, funding and
# precedence, so they read the board after a trigger, where it sizes
# exactly as it did before the timing existed. `test_board_level_gate`
# covers every timing state itself.
def _triggered(snapshot, now):
    from backend.market import entry_timing

    session = now.astimezone(entry_timing.NEW_YORK).date().isoformat()
    return {
        "session": session,
        "symbols": {
            name: {
                "open": quote["last"],
                "buy_trigger": {"bar": quote["bar"], "price": quote["last"]},
                "sell_trigger": {"bar": quote["bar"], "price": quote["last"]},
            }
            for name, quote in snapshot["quotes"].items()
        },
    }


# The policy the board sizes toward is the live one, read from one place.
def test_the_board_sizes_toward_the_active_policy():
    from backend.agents.trading.desk import live_policy

    assert live_policy.ACTIVE == POLICY


# Nothing held, targets present, market open with cash, the level triggered:
# Buy to the target, and the reason says the target and the policy.
def test_v4_targets_with_no_holdings_buy_to_the_target():
    record, snapshot, quoted, now = setup()
    _v4(record)
    row = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        cash=100000,
        timing_latch=_triggered(snapshot, now),
    )["rows"]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["strategy_move_weight"] == pytest.approx(1 / 11)
    assert row["action"] == "Buy"
    assert row["executable"] is True
    assert row["move_weight"] == pytest.approx(1 / 11, abs=1e-6)
    assert row["target_weight"] == pytest.approx(1 / 11)
    assert "Buy to 9.1% target (policy graded-equal-weight/4)" in row["reason"]
    # A name the policy sizes at zero is not a buy.
    zero = decision_view.build(record, [], 100000, snapshot, quoted, now, cash=100000)[
        "rows"
    ]["S0"]
    assert zero["strategy_action"] == "Hold"
    assert zero["reason"].startswith("Entry criteria not met")


# The operator's holdings file absent entirely and no cash figure: the intent
# is still a Buy to the target, but nothing is claimed executable, and the
# blocker says why.
def test_v4_targets_with_unknown_cash_keep_the_intent_and_name_the_blocker():
    record, snapshot, quoted, now = setup()
    _v4(record)
    row = decision_view.build(record, [], 100000, snapshot, quoted, now)["rows"]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["strategy_move_weight"] == pytest.approx(1 / 11)
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0.0
    assert row["executable"] is False
    assert row["blocker"] == "available cash is unknown"
    assert row["reason"].startswith("Buy to 9.1% target (policy graded-equal-weight/4)")
    assert "not executable: available cash is unknown" in row["reason"]


# A closed market blocks execution and nothing else: the strategy fields carry
# the sized Buy, the reason keeps the target sentence and names the blocker.
def test_v4_targets_survive_a_closed_market_as_strategy_intent():
    record, snapshot, quoted, now = setup()
    _v4(record)
    quoted["market_open"] = False
    row = decision_view.build(record, [], 100000, snapshot, quoted, now, cash=100000)[
        "rows"
    ]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["strategy_move_weight"] == pytest.approx(1 / 11)
    assert row["action"] == "Hold"
    assert row["executable"] is False
    assert row["blocker"] == "market closed or clock unavailable"
    assert row["reason"] == (
        "Buy to 9.1% target (policy graded-equal-weight/4); "
        "buy not executable: market closed or clock unavailable"
    )


# A non-session entry read ("2026-09-27 is not an exchange session") must not
# replace a target-sized Buy's reason: `_apply_entry_reason` only speaks for a
# Hold, so the row keeps its target sentence and its entry fields say what
# the reader lacks.
def test_a_non_session_entry_read_does_not_overwrite_a_target_buy():
    record, snapshot, quoted, now = setup()
    _v4(record)
    quoted["market_open"] = False
    readings = {
        n: {
            "band_z": None,
            "entry_status": "unavailable",
            "entry_reason": (
                "Entry data unavailable: 2026-09-27 is not an exchange session"
            ),
        }
        for n in record["grades"]
    }
    rows = decision_view.build(
        record, [], 100000, snapshot, quoted, now, entry_readings=readings
    )["rows"]
    assert rows["S11"]["strategy_action"] == "Buy"
    assert rows["S11"]["entry_status"] == "unavailable"
    assert rows["S11"]["reason"].startswith("Buy to 9.1% target")
    # A Hold still surfaces the missing reading, as before.
    assert rows["S0"]["strategy_action"] == "Hold"
    assert rows["S0"]["reason"] == readings["S0"]["entry_reason"]


# Held at the target: a Hold that names the position, no move.
def test_v4_held_at_target_is_a_hold():
    record, snapshot, quoted, now = setup()
    _v4(record)
    held = [Holding("S11", _shares(snapshot, 1 / 11), 100.0, "2026-08-01")]
    row = decision_view.build(record, held, 100000, snapshot, quoted, now, cash=50000)[
        "rows"
    ]["S11"]
    assert row["strategy_action"] == "Hold"
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0.0
    assert row["reason"].startswith("Maintain position (9.1% of account)")


# Held well under the target: an add, sized to the gap, classified as the
# charts classify it (ADD_TRIM_MIN).
def test_v4_held_under_target_adds_the_gap():
    from backend.agents.trading.desk import decision_history

    record, snapshot, quoted, now = setup()
    _v4(record)
    held = [Holding("S11", _shares(snapshot, 0.04), 100.0, "2026-08-01")]
    # Cash for every target buy on the board, so the add is not scaled.
    row = decision_view.build(
        record,
        held,
        100000,
        snapshot,
        quoted,
        now,
        cash=100000,
        timing_latch=_triggered(snapshot, now),
    )["rows"]["S11"]
    assert row["strategy_action"] == "Buy"
    assert row["strategy_move_weight"] == pytest.approx(1 / 11 - 0.04)
    assert row["action"] == "Buy"
    assert row["move_weight"] == pytest.approx(1 / 11 - 0.04, abs=1e-6)
    assert (
        "Add to 9.1% target (policy graded-equal-weight/4); holding 4.0%"
        in row["reason"]
    )
    # A shortfall under the threshold is a reshuffle, not an order.
    close = 1 / 11 - decision_history.ADD_TRIM_MIN / 2
    held = [Holding("S11", _shares(snapshot, close), 100.0, "2026-08-01")]
    row = decision_view.build(record, held, 100000, snapshot, quoted, now, cash=50000)[
        "rows"
    ]["S11"]
    assert row["strategy_action"] == "Hold"


# Held above the target mid-cycle: the executor trims only at the reset, so
# the row is a Hold that says so - never a Sell the book will not place.
def test_v4_over_target_mid_cycle_is_a_hold_with_the_trim_note():
    record, snapshot, quoted, now = setup()
    _v4(record, until_rebalance=10)
    held = [Holding("S11", _shares(snapshot, 0.14), 100.0, "2026-08-01")]
    row = decision_view.build(record, held, 100000, snapshot, quoted, now, cash=50000)[
        "rows"
    ]["S11"]
    assert row["strategy_action"] == "Hold"
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0.0
    assert row["reason"].startswith(
        "Above target (9.1%; holding 14.0%); trimmed at the next reset"
    )


# On the reset session the same excess is a trim to the target.
def test_v4_over_target_at_the_reset_trims_to_the_target():
    record, snapshot, quoted, now = setup()
    _v4(record, until_rebalance=0)
    held = [Holding("S11", _shares(snapshot, 0.14), 100.0, "2026-08-01")]
    row = decision_view.build(record, held, 100000, snapshot, quoted, now, cash=50000)[
        "rows"
    ]["S11"]
    assert row["strategy_action"] == "Sell"
    assert row["strategy_move_weight"] == pytest.approx(1 / 11 - 0.14)
    assert (
        "Trim to 9.1% target (policy graded-equal-weight/4); holding 14.0%"
        in row["reason"]
    )


# A record with targets but no rebalance clock at all never prints a trim.
def test_v4_without_a_clock_never_prints_a_trim():
    record, snapshot, quoted, now = setup()
    _v4(record)
    record["paper"] = {}
    held = [Holding("S11", _shares(snapshot, 0.14), 100.0, "2026-08-01")]
    row = decision_view.build(record, held, 100000, snapshot, quoted, now, cash=50000)[
        "rows"
    ]["S11"]
    assert row["strategy_action"] == "Hold"
    assert "trimmed at the next reset" in row["reason"]


# A held name the desk has downgraded is the whole-position exit, before any
# target sizing: the target branch never reaches a name the desk no longer rates.
# The downgrade is the record's close grade (the one the executor rotates
# on, and whose policy target is then zero); an intraday re-grade alone is
# not a `/4` exit (`test_board_level_gate`).
def test_v4_held_and_downgraded_is_the_exit():
    record, snapshot, quoted, now = setup()
    _v4(record)
    record["grades"]["S11"]["grade"] = "B"
    record["targets"]["weights"]["S11"] = 0.0
    held = [Holding("S11", _shares(snapshot, 0.05), 100.0, "2026-08-01")]
    row = decision_view.build(
        record,
        held,
        100000,
        snapshot,
        quoted,
        now,
        cash=50000,
        timing_latch=_triggered(snapshot, now),
    )["rows"]["S11"]
    assert row["strategy_action"] == "Sell"
    assert row["strategy_move_weight"] == pytest.approx(-0.05)
    assert row["action"] == "Sell"
    assert row["move_weight"] == pytest.approx(-0.05)
    # The funded personal plan words the exit as before; no target sentence.
    assert "grade below A; close position" in row["reason"]
    assert "target" not in row["reason"]


# Target buys share one cash bound: with cash for a third of the wants, every
# funded buy is scaled to a third while the intent keeps the full gap.
def test_v4_target_buys_share_the_cash_bound():
    record, snapshot, quoted, now = setup()
    _v4(record)
    wanted = sum(record["targets"]["weights"].values()) * 100000
    rows = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        cash=wanted / 3,
        timing_latch=_triggered(snapshot, now),
    )["rows"]
    funded = {s: r for s, r in rows.items() if r["action"] == "Buy"}
    assert set(funded) == {n for n in record["grades"] if n != "S0"}
    for row in funded.values():
        assert row["strategy_move_weight"] == pytest.approx(1 / 11)
        assert row["move_weight"] == pytest.approx(1 / 33, abs=1e-6)
        assert "Buy to 9.1% target" in row["reason"]
    assert sum(r["move_weight"] for r in funded.values()) * 100000 == pytest.approx(
        wanted / 3, rel=1e-6
    )


# A firing band entry still answers first, sized as the executor's entry leg
# sizes it; the target branch takes the names without a signal.
def test_v4_a_firing_entry_still_answers_before_the_target():
    record, snapshot, quoted, now = setup()
    _v4(record)
    rows = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries=FIRING,
        cash=100000,
        timing_latch=_triggered(snapshot, now),
    )["rows"]
    assert rows["S11"]["strategy_action"] == "Buy"
    assert "breakout" in rows["S11"]["reason"].lower()
    assert "target" not in rows["S11"]["reason"]
    assert "Buy to 9.1% target" in rows["S10"]["reason"]


# On a session every name carries a band reading, most of them below the
# trigger. A reading that does not fire is not an entry and must not consume
# the name's target buy: the row stays a funded Buy to the target. (The
# first cut excluded any name with a reading from the target legs, which on
# a weekday would have knocked every target buy on the board to "no funded
# entry under account limits".)
def test_v4_a_band_reading_below_the_trigger_does_not_starve_the_target_buy():
    from backend.agents.trading.desk import paper

    record, snapshot, quoted, now = setup()
    _v4(record)
    quiet = {n: paper.ENTRY_BAND_Z / 2 for n in record["grades"]}
    rows = decision_view.build(
        record,
        [],
        100000,
        snapshot,
        quoted,
        now,
        entries=quiet,
        cash=100000,
        timing_latch=_triggered(snapshot, now),
    )["rows"]
    for name in record["grades"]:
        if name == "S0":
            continue
        assert rows[name]["action"] == "Buy", rows[name]
        assert rows[name]["executable"] is True
        assert rows[name]["move_weight"] == pytest.approx(1 / 11, abs=1e-6)
        assert "Buy to 9.1% target" in rows[name]["reason"]


# Targets stamped with another policy, or none, change nothing: the `/3`
# rules produce the same rows byte for byte.
@pytest.mark.parametrize("stamp", [None, "some-other-policy/9"])
def test_records_without_the_active_policy_are_unchanged(stamp):
    record, snapshot, quoted, now = setup()
    record["paper"] = {"until_rebalance": 10}
    before = decision_view.build(record, [], 100000, snapshot, quoted, now, cash=100000)
    if stamp is not None:
        record["targets"] = {
            "policy": stamp,
            "weights": {n: 1 / 12 for n in record["grades"]},
        }
    after = decision_view.build(record, [], 100000, snapshot, quoted, now, cash=100000)
    assert json.dumps(before["rows"], sort_keys=True, default=str) == json.dumps(
        after["rows"], sort_keys=True, default=str
    )
    assert after["rows"]["S11"]["action"] == "Hold"
    assert "reset target 10%" in after["rows"]["S11"]["reason"]


# The board with the API's swap already applied (`_with_active_targets`) is
# the same board: the swap is idempotent.
def test_the_api_swap_is_idempotent_with_the_boards_own():
    pytest.importorskip("fastapi")
    from backend.api.v1 import market

    record, snapshot, quoted, now = setup()
    _v4(record)
    plain = decision_view.build(record, [], 100000, snapshot, quoted, now, cash=100000)
    swapped = decision_view.build(
        market._with_active_targets(record),
        [],
        100000,
        snapshot,
        quoted,
        now,
        cash=100000,
    )
    assert json.dumps(plain["rows"], sort_keys=True, default=str) == json.dumps(
        swapped["rows"], sort_keys=True, default=str
    )


# The three-word guard holds for `/4` records too, across every path.
def test_the_v4_board_can_only_ever_say_one_of_three_things():
    record, snapshot, quoted, now = setup()
    _v4(record)
    said = set()
    for held in ([], [Holding("S11", _shares(snapshot, 0.14), 100.0, "2026-08-01")]):
        for until in (0, 10, None):
            record["paper"] = {"until_rebalance": until} if until is not None else {}
            for open_ in (True, False):
                quoted["market_open"] = open_
                for cash in (None, 0, 100000):
                    built = decision_view.build(
                        record, held, 100000, snapshot, quoted, now, cash=cash
                    )
                    for row in built["rows"].values():
                        said.add(row["action"])
                        said.add(row["strategy_action"])
                        if row["action"] == "Hold":
                            assert row["move_weight"] == 0.0, row
                        else:
                            assert row["move_weight"] != 0.0, row
                        if row["strategy_action"] == "Hold":
                            assert row["strategy_move_weight"] == 0.0, row
                        else:
                            assert row["strategy_move_weight"] != 0.0, row
                        assert row["reason"], row
    assert said <= {"Buy", "Sell", "Hold"}, said
