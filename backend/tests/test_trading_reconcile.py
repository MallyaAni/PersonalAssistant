"""Submitting is not filling.

The paper book printed "submitted", saved the rebalance as done, and never
looked again. An order can be accepted and then rejected at the open,
expire when the auction does not cross, or fill in part - so a rebalance
the broker never carried out counted as one that had, and the book sat
twenty sessions from its next attempt at targets it had never reached.

What has to hold: the outcome comes from the broker's own record of the
order, matched by an id chosen before the order was sent; a rebalance is
only done when its orders filled; and one that did not fill puts the clock
back so the next session tries again.
"""

import pytest

from backend.agents.trading.desk import paper


def _pending(session: str, *symbols: str) -> list[dict]:
    return [
        {
            "client_order_id": paper.order_id(session, symbol, "buy"),
            "symbol": symbol,
            "side": "buy",
            "qty": 10,
            "session": session,
            "reason": "rebalance",
        }
        for symbol in symbols
    ]


def _broker(session: str, symbol: str, status: str, filled: int) -> dict:
    return {
        "client_order_id": paper.order_id(session, symbol, "buy"),
        "symbol": symbol,
        "status": status,
        "filled_qty": str(filled),
    }


# Each of the ways an order ends, read from the broker rather than guessed.
@pytest.mark.parametrize(
    ("status", "filled", "expected"),
    [
        ("filled", 10, "filled"),
        ("partially_filled", 4, "partial"),
        ("filled", 4, "partial"),  # says filled, is not: the count decides
        ("rejected", 0, "dead"),
        ("expired", 0, "dead"),
        ("canceled", 0, "dead"),
        ("accepted", 0, "open"),
        ("new", 0, "open"),
    ],
)
def test_every_ending_is_read_from_the_broker(status, filled, expected):
    pending = _pending("2026-09-07", "AAA")
    settled = paper.settle(pending, [_broker("2026-09-07", "AAA", status, filled)])
    assert [s.status for s in settled] == [expected]
    assert settled[0].filled_qty == filled


# An order the broker has never heard of is not a trade this desk made.
# That is the crash case: written down, and the submission never landed.
def test_an_order_the_broker_does_not_know_is_not_a_trade():
    pending = _pending("2026-09-07", "AAA")
    settled = paper.settle(pending, [])
    assert settled[0].status == "missing"
    assert settled[0].filled_qty == 0
    # And an unrelated order of someone else's does not match it either.
    other = {"client_order_id": "someone-else", "status": "filled", "filled_qty": "10"}
    assert paper.settle(pending, [other])[0].status == "missing"


# A rebalance whose orders all filled is done, and the clock stands.
def test_a_filled_rebalance_is_confirmed():
    state = paper.PaperState(
        last_rebalance="2026-09-07",
        previous_rebalance="2026-08-10",
        sessions_since_rebalance=1,
        unconfirmed_rebalance="2026-09-07",
        pending=_pending("2026-09-07", "AAA", "BBB"),
    )
    settled = paper.settle(
        state.pending,
        [
            _broker("2026-09-07", "AAA", "filled", 10),
            _broker("2026-09-07", "BBB", "filled", 10),
        ],
    )
    after = paper.apply_settlements(state, settled)
    assert after.unconfirmed_rebalance is None
    assert after.last_rebalance == "2026-09-07"
    assert after.sessions_since_rebalance == 1
    assert after.pending == []


# A rebalance the broker did not carry out is not one. The clock goes back
# to the rebalance before it, so the next session plans it again rather
# than waiting out twenty sessions on a book that never reached target.
@pytest.mark.parametrize(
    ("status", "filled"),
    [("rejected", 0), ("expired", 0), ("partially_filled", 3)],
)
def test_an_unfilled_rebalance_puts_the_clock_back(status, filled):
    state = paper.PaperState(
        last_rebalance="2026-09-07",
        previous_rebalance="2026-08-10",
        sessions_since_rebalance=1,
        unconfirmed_rebalance="2026-09-07",
        pending=_pending("2026-09-07", "AAA", "BBB"),
    )
    settled = paper.settle(
        state.pending,
        [
            _broker("2026-09-07", "AAA", "filled", 10),
            _broker("2026-09-07", "BBB", status, filled),
        ],
    )
    after = paper.apply_settlements(state, settled)
    assert after.last_rebalance == "2026-08-10"
    assert after.sessions_since_rebalance == paper.REBALANCE_EVERY
    assert after.unconfirmed_rebalance is None
    # Which means the very next session plans a rebalance.
    orders, _new, what = paper.plan(
        "2026-09-08",
        after,
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 50.0},
        targets={"AAA": 0.1, "BBB": 0.1},
        grades={"AAA": "A+", "BBB": "A"},
    )
    assert what == "rebalance"
    assert orders


# An order still working is not concluded either way: it stays pending and
# the rebalance stays unconfirmed, so nothing is decided on a guess.
def test_an_open_order_is_left_to_settle():
    state = paper.PaperState(
        last_rebalance="2026-09-07",
        previous_rebalance="2026-08-10",
        unconfirmed_rebalance="2026-09-07",
        pending=_pending("2026-09-07", "AAA", "BBB"),
    )
    settled = paper.settle(
        state.pending,
        [
            _broker("2026-09-07", "AAA", "filled", 10),
            _broker("2026-09-07", "BBB", "accepted", 0),
        ],
    )
    after = paper.apply_settlements(state, settled)
    assert after.unconfirmed_rebalance == "2026-09-07"
    assert after.last_rebalance == "2026-09-07"
    assert [row["symbol"] for row in after.pending] == ["BBB"]


# The id is chosen before the order is sent and is stable, which is what
# makes a crash between sending and recording recoverable.
def test_the_order_id_is_stable_and_specific():
    first = paper.order_id("2026-09-07", "AAA", "buy")
    assert first == paper.order_id("2026-09-07", "AAA", "buy")
    assert first != paper.order_id("2026-09-07", "AAA", "sell")
    assert first != paper.order_id("2026-09-08", "AAA", "buy")
    assert first != paper.order_id("2026-09-07", "BBB", "buy")


# Nothing pending means nothing to settle, and the state is untouched.
def test_no_pending_orders_changes_nothing():
    state = paper.PaperState(last_rebalance="2026-09-07", sessions_since_rebalance=4)
    after = paper.apply_settlements(state, paper.settle([], []))
    assert after.last_rebalance == "2026-09-07"
    assert after.sessions_since_rebalance == 4
