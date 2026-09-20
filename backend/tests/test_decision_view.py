"""Exercise execution evidence and the adopted-plan decision gates."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from backend.market import decision_view, execution_quotes
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


# What the desk WANTS and what can be TRADED are different questions, and the
# gates split along that line.
#
# A strategy gate blocks: an FOMC pause really is a hold, a name rejecting its
# upper band is one the desk itself holds back, and a name whose reset is not
# due has no scheduled trade. An execution gate does not: a wide spread, a
# stale quote or a closed market say nothing about whether the desk wants the
# name, and treating them as a view turned all ninety-three rows into Hold
# whenever the market was shut - which is most of the time the page is read.
@pytest.mark.parametrize("block", [None, "band", "fomc", "schedule"])
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
    result = decision_view.build(record, [], 100000, snapshot, quoted, now)["rows"][
        "S11"
    ]
    assert (result["action"] == "Buy") is (block is None)
    assert result["target_weight"] == 0.1


# An execution gate leaves the action alone and says what is in the way, so the
# operator learns the desk wants the name AND that he cannot cross the spread
# for it right now.
@pytest.mark.parametrize("block", ["stale", "closed", "spread", "size", "future", "timing", "technical"])
def test_an_execution_gate_annotates_rather_than_blocking(block):
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
    result = decision_view.build(record, [], 100000, snapshot, quoted, now)["rows"]["S11"]
    assert result["action"] == "Buy", f"{block} should not suppress the desk's view"
    assert "(" in result["reason"], f"{block} should say what is in the way"


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
    result = decision_view.build(record, [], 100000, snapshot, quoted, now)["rows"][
        "S11"
    ]
    assert result["action"] == "Buy"
    assert result["quote"]["feed"] == "iex"
    assert result["quote"]["eligible"]


# A B grade the desk does not hold is simply a Hold - there is nothing to buy
# and nothing to sell. Held, the same grade is a Sell, because the desk rotates
# out of what it no longer rates and into what it does.
@pytest.mark.parametrize(("shares", "expected"), [(0, "Hold"), (10, "Sell")])
def test_a_b_grade_is_a_hold_unheld_and_a_sell_when_held(shares, expected):
    _, _, _, now = setup()
    row = {
        "in_book": True,
        "until_rebalance": 0,
        "rebalance_due": True,
        "rejecting_band": False,
        "grade_live": "B",
        "shares": shares,
    }
    action, move, reason = decision_view.action_for_row(
        row,
        {"eligible": True, "reason": "Quote checks passed"},
        now + timedelta(seconds=20),
        False,
        True,
        0.1,
        0,
        now,
    )
    assert action == expected
    assert move == (0.0 if shares == 0 else pytest.approx(-0.0))


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
    assert execution_quotes.describe({**raw, "ap": 0}, "iex", True, now)["eligible"] is False
    assert execution_quotes.describe({**raw, "t": "unknown"}, "iex", True, now)["eligible"] is False


# The book's mid-cycle entry is what the operator can act on today, so it is
# decided before the rebalance calendar, which is now 120 sessions wide. Without
# this the name the desk buys tonight read "Wait · not held", the opposite of
# what to do about it.
@pytest.mark.parametrize(
    "shares,weight,grade,band,expected",
    [
        (0, 0.0, "A+", 1.50, "Buy"),
        (0, 0.0, "A", 1.30, "Buy"),
        (10, 0.05, "A+", 1.50, "Buy"),
        # At the name cap the desk cannot add, so the row says so rather than
        # promising a buy that `_entry_orders` would decline to size.
        (10, 0.15, "A+", 1.50, "Hold"),
        # Below the threshold, below the grade floor, and the retired dip tail:
        # none of these is an entry, so the calendar answers instead.
        (0, 0.0, "A+", 0.90, None),
        (0, 0.0, "B", 1.50, None),
        (0, 0.0, "A+", -1.50, None),
    ],
)
def test_the_live_entry_answers_before_the_calendar(shares, weight, grade, band, expected):
    row = {"shares": shares, "current_weight": weight, "rejecting_band": False,
           "target_weight": 0.04}
    assert (decision_view.entry_action(row, band, grade) or (None,))[0] == expected


# The band gate the nightly applies is applied here too, so the page never
# advertises a buy the nightly is going to hold back.
def test_a_breakout_rejecting_its_band_is_not_offered_as_a_buy():
    row = {"shares": 0, "current_weight": 0.0, "rejecting_band": True,
           "target_weight": 0.04}
    action, _size, reason = decision_view.entry_action(row, 1.5, "A+")
    assert action == "Wait"
    assert "upper band" in reason


# A name with no live reading falls through to the calendar rather than
# inventing an entry from a missing price.
def test_a_missing_live_stretch_is_not_an_entry():
    row = {"shares": 0, "current_weight": 0.0, "rejecting_band": False,
           "target_weight": 0.04}
    assert decision_view.entry_action(row, None, "A+") is None
    assert decision_view.entry_action(row, float("nan"), "A+") is None


# A name the sizing engine did not pick has no target, so however far it has
# run it is not an entry. The row used to read "Buy tonight - not picked by
# the sizing engine", two statements that cannot both be true.
def test_a_name_with_no_target_is_never_an_entry():
    row = {"shares": 0, "current_weight": 0.0, "rejecting_band": False, "target_weight": 0.0}
    assert decision_view.entry_action(row, 2.0, "A+") is None


# The size is the weight to put on now, not the target it moves toward: a
# fresh buy takes ENTRY_ADD, and a held name takes only the room left under
# the name cap.
def test_the_entry_carries_the_weight_to_put_on_now():
    from backend.agents.trading.desk import paper

    fresh = {"shares": 0, "current_weight": 0.0, "rejecting_band": False, "target_weight": 0.06}
    assert decision_view.entry_action(fresh, 1.5, "A+")[1] == paper.ENTRY_ADD
    nearly = {"shares": 5, "current_weight": paper.ENTRY_NAME_CAP - 0.01,
              "rejecting_band": False, "target_weight": 0.06}
    assert decision_view.entry_action(nearly, 1.5, "A+")[1] == pytest.approx(0.01)


# A downgrade IS a sell, because the desk redeploys rather than going to cash.
#
# This test asserted the opposite for part of 2026-09-19, on the evidence that
# a downgraded name still beats the benchmark over the next twenty sessions.
# That evidence is real and it is why selling one to CASH costs 24 points of
# CAGR a year. It is not an argument for holding it: rotated into the names the
# desk still wants, the same signal earned the same return with a 7.3 point
# shallower drawdown. Both readings were right about the book they were
# measured against - the first against a 20-session rebalance, where the
# calendar already did this work.
def test_a_downgrade_is_a_sell_that_funds_the_rest_of_the_book():
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
