"""Actual timing and execution must reject evidence unavailable at decision time."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from backend.agents.trading.desk import intraday_orders
from backend.market import entry_timing

SESSION = date(2026, 9, 28)
NY = ZoneInfo("America/New_York")


# Construct explicit regular-session timestamps without inferring a timezone.
def at(hour, minute=0):
    return datetime(2026, 9, 28, hour, minute, tzinfo=NY)


# Future, malformed and non-crossing latches cannot authorize a paper submission.
@pytest.mark.parametrize(
    "trigger",
    [
        {"bar": at(15).isoformat(), "seen_at": at(15, 15).isoformat(), "price": 98},
        {"bar": at(10).isoformat(), "seen_at": at(10, 15).isoformat(), "price": 98},
        {"bar": at(9, 30).isoformat(), "seen_at": at(11).isoformat(), "price": 98},
        {"bar": at(9, 30).isoformat(), "seen_at": at(9, 40).isoformat(), "price": 98},
        {
            "bar": "2026-09-25T09:30:00-04:00",
            "seen_at": at(9, 45).isoformat(),
            "price": 98,
        },
        {"bar": at(8).isoformat(), "seen_at": at(9, 45).isoformat(), "price": 98},
        {"bar": at(9, 31).isoformat(), "seen_at": at(9, 46).isoformat(), "price": 98},
        {"bar": at(9, 30).isoformat(), "price": 98},
        {"bar": "invalid", "seen_at": at(9, 45).isoformat(), "price": 98},
        {"bar": at(9, 30).isoformat(), "seen_at": at(9, 45).isoformat(), "price": 100},
    ],
)
def test_unobservable_latch_cannot_send(trigger):
    latch = {"open": 100, "buy_trigger": trigger}
    verdict = intraday_orders.decide({"side": "buy"}, latch, None, at(10), SESSION)
    assert verdict["send"] is None
    assert verdict["timed"]["trigger_bar"] is None


# A completed candle remains unavailable until its actual receipt timestamp.
def test_completed_but_future_published_quote_cannot_send():
    quote = {
        "open": 100,
        "last": 98,
        "bar": at(9, 30).isoformat(),
        "as_of": at(10, 1).isoformat(),
    }
    verdict = intraday_orders.decide({"side": "buy"}, None, quote, at(10), SESSION)
    assert verdict["send"] is None
    assert verdict["timed"]["open"] is None
    quote["as_of"] = at(9, 45).isoformat()
    assert (
        intraday_orders.decide({"side": "buy"}, None, quote, at(10), SESSION)["send"]
        == "market"
    )


# An unavailable snapshot cannot poison the opening price used by a later valid quote.
def test_future_snapshot_is_not_persisted(tmp_path):
    quote = {
        "open": 101,
        "last": 98,
        "bar": at(9, 30).isoformat(),
        "as_of": at(9, 45).isoformat(),
    }
    snapshot = {"as_of": at(10, 1).isoformat(), "quotes": {"AAA": quote}}
    assert entry_timing.update(tmp_path, snapshot, at(10)) == []
    assert entry_timing.load(tmp_path, SESSION) is None
    current = {**quote, "open": 100, "last": 99.9}
    assert (
        intraday_orders.decide({"side": "buy"}, None, current, at(10), SESSION)["send"]
        is None
    )
    snapshot["as_of"] = at(10).isoformat()
    assert entry_timing.update(tmp_path, snapshot, at(10))
    assert (
        entry_timing.load(tmp_path, SESSION)["symbols"]["AAA"]["buy_trigger"]["seen_at"]
        == at(10).isoformat()
    )


# A late earlier candle cannot erase a crossing available in a historical prefix.
def test_late_candle_keeps_observed_trigger_versions(tmp_path):
    for bar, seen in ((at(10), at(10, 15)), (at(9, 45), at(11))):
        quote = {
            "open": 100,
            "last": 98,
            "high": 100,
            "bar": bar.isoformat(),
            "as_of": seen.isoformat(),
        }
        entry_timing.update(
            tmp_path, {"as_of": seen.isoformat(), "quotes": {"AAA": quote}}, seen
        )
    row = entry_timing.load(tmp_path, SESSION)["symbols"]["AAA"]
    assert row["open_seen_at"] == at(10, 15).isoformat()
    assert len(row["buy_trigger_versions"]) == 2
    old = entry_timing.timing(row, None, "buy", at(10, 30), SESSION)
    assert old["state"] == "triggered"
    assert old["trigger_bar"] == at(10).isoformat()
    latest = entry_timing.timing(row, None, "buy", at(11), SESSION)
    assert latest["trigger_bar"] == at(9, 45).isoformat()


# A valid archived crossing is retained after recovery, preserving the incumbent policy.
def test_observed_latch_survives_recovery_without_future_prefix_leakage():
    past = {"bar": at(9, 30).isoformat(), "seen_at": at(9, 45).isoformat(), "price": 98}
    quote = {
        "open": 100,
        "last": 106,
        "bar": at(10).isoformat(),
        "as_of": at(10, 15).isoformat(),
    }
    latch = {"open": 100, "buy_trigger": past}
    before = entry_timing.timing(latch, quote, "buy", at(10, 15), SESSION)
    assert before["state"] == "triggered"
    future = {**past, "bar": at(15).isoformat(), "seen_at": at(15, 15).isoformat()}
    after = entry_timing.timing(
        {"open": 100, "buy_trigger": future}, quote, "buy", at(10, 15), SESSION
    )
    assert after["state"] == "waiting"


# Early-close afternoon bars cannot become regular-session triggers on a later replay.
def test_early_close_rejects_after_hours_evidence():
    session = date(2026, 11, 27)
    now = datetime(2026, 11, 27, 12, 15, tzinfo=NY)
    trigger = {
        "bar": "2026-11-27T13:00:00-05:00",
        "seen_at": "2026-11-27T13:15:00-05:00",
        "price": 98,
    }
    timed = entry_timing.timing(
        {"open": 100, "buy_trigger": trigger}, None, "buy", now, session
    )
    assert timed["state"] == "waiting"


# The actual personal board with funded cash must also refuse an unavailable trigger.
def test_personal_board_does_not_authorize_a_future_latch():
    from backend.tests.test_board_level_gate import at as board_at
    from backend.tests.test_board_level_gate import board, v4

    record, snapshot, quotes, now = v4(board_at(10, 31), move=-0.005)
    symbol = "S11"
    opened = snapshot["quotes"][symbol]["open"]
    trigger = {
        "bar": board_at(15).isoformat(),
        "price": opened * 0.98,
        "seen_at": board_at(15, 15).isoformat(),
    }
    latch = {
        "session": "2026-09-14",
        "symbols": {symbol: {"open": opened, "buy_trigger": trigger}},
    }
    row = board(record, snapshot, quotes, now, timing_latch=latch)[symbol]
    assert row["strategy_action"] == "Buy"
    assert row["action"] == "Hold"
    assert row["move_weight"] == 0
    assert row["timing"]["state"] == "waiting"
