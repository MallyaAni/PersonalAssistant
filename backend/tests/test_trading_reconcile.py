"""Submitting is not filling.

The paper book printed "submitted", saved the rebalance as done, and never
looked again. An order can be accepted and then rejected at the open,
expire when the auction does not cross, or fill in part - so a rebalance
the broker never carried out counted as one that had, and the book sat
twenty sessions from its next attempt at targets it had never reached.

What has to hold: the outcome comes from the broker's own record of the
order, matched by an id chosen before the order was sent; a rebalance is
only done when its orders filled; one that did not fill puts the clock
back so the next session tries again; a partial or open order stays
pending with its outstanding quantity, unconcluded; a partial the broker
has now closed is a concluded partial, never stuck pending; every outcome
is kept in a durable journal, so a leg rejected in one round is seen
again when another leg fills in a later round; and the journal survives
the state's round-trip through its file.
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
# A *partial* is different and does not roll the clock back: it stays
# pending and the rebalance unconcluded, so the outstanding quantity is
# asked about again rather than planned over.
@pytest.mark.parametrize(
    ("status", "filled"),
    [("rejected", 0), ("expired", 0)],
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


# A partial fill is an order still carrying outstanding quantity: it stays
# pending, and the rebalance it belongs to is not concluded either way.
# Dropping the partial would silently forget the unfilled part, and marking
# the rebalance done would celebrate a book that never reached its targets.
def test_a_partial_fill_stays_pending_and_the_rebalance_is_not_concluded():
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
            _broker("2026-09-07", "BBB", "partially_filled", 3),
        ],
    )
    after = paper.apply_settlements(state, settled)
    assert [row["symbol"] for row in after.pending] == ["BBB"]
    assert after.unconfirmed_rebalance == "2026-09-07"
    assert after.last_rebalance == "2026-09-07"
    assert after.sessions_since_rebalance == 1


# A partial the broker has now CLOSED (canceled or expired) is a concluded
# partial, not an order still working: the outstanding quantity is not
# coming, so it leaves pending with its fill recorded and the rebalance is
# not confirmed - the clock goes back so the remainder is planned again.
def test_a_canceled_partial_is_concluded_and_the_clock_goes_back():
    state = paper.PaperState(
        last_rebalance="2026-09-07",
        previous_rebalance="2026-08-10",
        sessions_since_rebalance=1,
        unconfirmed_rebalance="2026-09-07",
        pending=_pending("2026-09-07", "AAA"),
    )
    settled = paper.settle(
        state.pending, [_broker("2026-09-07", "AAA", "canceled", 3)]
    )
    after = paper.apply_settlements(state, settled)
    # Concluded: not stuck pending, and its outcome is in the journal.
    assert after.pending == []
    assert after.unconfirmed_rebalance is None
    assert after.last_rebalance == "2026-08-10"
    assert after.sessions_since_rebalance == paper.REBALANCE_EVERY
    assert after.journal[0]["status"] == "partial"
    assert after.journal[0]["terminal"] is True
    assert after.journal[0]["filled_qty"] == 3


# A leg rejected in one round is seen again when another leg fills in a
# later round: the rebalance is concluded over every leg's latest recorded
# outcome, so a book that never reached its targets is never confirmed.
def test_a_rejected_leg_is_not_forgotten_when_another_fills_later():
    state = paper.PaperState(
        last_rebalance="2026-09-07",
        previous_rebalance="2026-08-10",
        sessions_since_rebalance=1,
        unconfirmed_rebalance="2026-09-07",
        pending=_pending("2026-09-07", "AAA", "BBB"),
    )
    round1 = paper.settle(
        state.pending,
        [
            _broker("2026-09-07", "AAA", "rejected", 0),
            _broker("2026-09-07", "BBB", "accepted", 0),
        ],
    )
    after1 = paper.apply_settlements(state, round1)
    assert [row["symbol"] for row in after1.pending] == ["BBB"]
    # BBB fills in a later round; AAA's rejection is still in the journal.
    round2 = paper.settle(
        after1.pending, [_broker("2026-09-07", "BBB", "filled", 10)]
    )
    after2 = paper.apply_settlements(after1, round2)
    assert after2.unconfirmed_rebalance is None
    assert after2.last_rebalance == "2026-08-10"
    assert after2.sessions_since_rebalance == paper.REBALANCE_EVERY
    by_id = {e["client_order_id"]: e for e in after2.journal}
    assert by_id[paper.order_id("2026-09-07", "AAA", "buy")]["status"] == "dead"
    assert by_id[paper.order_id("2026-09-07", "BBB", "buy")]["status"] == "filled"


# An order whose cancel or replacement is still in flight can still fill or
# change, so it must stay pending and keep the rebalance open: a partial
# reported as pending_cancel or pending_replace is not a concluded partial.
# Before the fix those two statuses were outside the working set, so a
# 3-of-10 partial was dropped and the clock rolled back while the original
# order was still live.
@pytest.mark.parametrize("raw", ["pending_cancel", "pending_replace"])
def test_an_in_flight_cancel_or_replace_keeps_the_partial_pending(raw):
    state = paper.PaperState(
        last_rebalance="2026-09-07",
        previous_rebalance="2026-08-10",
        sessions_since_rebalance=1,
        unconfirmed_rebalance="2026-09-07",
        pending=_pending("2026-09-07", "AAA"),
    )
    settled = paper.settle(
        state.pending, [_broker("2026-09-07", "AAA", raw, 3)]
    )
    assert not settled[0].terminal
    after = paper.apply_settlements(state, settled)
    # Still pending, still unconfirmed: the rebalance is not concluded.
    assert [row["symbol"] for row in after.pending] == ["AAA"]
    assert after.unconfirmed_rebalance == "2026-09-07"
    assert after.last_rebalance == "2026-09-07"


# The id is chosen before the order is sent and is stable, which is what
# makes a crash between sending and recording recoverable.
def test_the_order_id_is_stable_and_specific():
    first = paper.order_id("2026-09-07", "AAA", "buy")
    assert first == paper.order_id("2026-09-07", "AAA", "buy")
    assert first != paper.order_id("2026-09-07", "AAA", "sell")
    assert first != paper.order_id("2026-09-07", "AAA", "buy", 1)


# Every order gets an id unique to one submission, and a forced rebalance
# of a session already planned must produce fresh ids - a reused id makes
# the broker reject the replacement order, so the forced rebalance never
# reaches the market.
def test_a_forced_rebalance_uses_fresh_order_ids():
    def planned(session):
        state = paper.PaperState(
            last_rebalance="2026-09-01",
            sessions_since_rebalance=paper.REBALANCE_EVERY - 1,
        )
        orders, new, _what = paper.plan(
            session,
            state,
            equity=100_000.0,
            held={},
            prices={"AAA": 100.0, "BBB": 50.0},
            targets={"AAA": 0.1, "BBB": 0.1},
            grades={"AAA": "A+", "BBB": "A"},
        )
        return orders, new

    first, state_after = planned("2026-09-08")
    assert len({o.client_order_id for o in first}) == len(first)
    # Replanning the same session as a forced rebalance yields ids that do
    # not collide with the first round's.
    second, _state, _what = paper.plan(
        "2026-09-08",
        state_after,
        equity=100_000.0,
        held={},
        prices={"AAA": 100.0, "BBB": 50.0},
        targets={"AAA": 0.1, "BBB": 0.1},
        grades={"AAA": "A+", "BBB": "A"},
        force_rebalance=True,
    )
    assert not {o.client_order_id for o in first} & {o.client_order_id for o in second}
    assert state_after.order_seq == len(first)
    # The fallback for an id-less order still matches the first planned one.
    assert paper.order_id("2026-09-08", "AAA", "buy") in {
        o.client_order_id for o in first
    }
    assert first != paper.order_id("2026-09-07", "BBB", "buy")


# Nothing pending means nothing to settle, and the state is untouched.
def test_no_pending_orders_changes_nothing():
    state = paper.PaperState(last_rebalance="2026-09-07", sessions_since_rebalance=4)
    after = paper.apply_settlements(state, paper.settle([], []))
    assert after.last_rebalance == "2026-09-07"
    assert after.sessions_since_rebalance == 4


# The journal is durable: it survives the state's round-trip through its
# file, so a terminal outcome is never lost to a restart.
def test_the_journal_survives_the_state_file(tmp_path):
    state = paper.PaperState(
        last_rebalance="2026-09-07",
        previous_rebalance="2026-08-10",
        unconfirmed_rebalance="2026-09-07",
        pending=_pending("2026-09-07", "AAA"),
    )
    after = paper.apply_settlements(
        state,
        paper.settle(
            state.pending, [_broker("2026-09-07", "AAA", "canceled", 3)]
        ),
    )
    paper.save_state(tmp_path, after)
    loaded = paper.load_state(tmp_path)
    assert [e["status"] for e in loaded.journal] == ["partial"]
    assert loaded.journal[0]["terminal"] is True


# The fill price the broker reports is kept, and the closing auction's
# counterfactual is signed so that positive means the close would have
# been worse than the fill: a buy filled below the close, a sell above it.
def test_the_fill_price_is_kept_and_the_close_is_judged_against_it():
    pending = _pending("2026-09-07", "AAA")
    order = _broker("2026-09-07", "AAA", "filled", 10)
    order["filled_avg_price"] = "100.0"
    settled = paper.settle(pending, [order])
    assert settled[0].filled_price == 100.0
    assert paper.settle(pending, [])[0].filled_price == 0.0
    assert paper.close_shortfall_bps("buy", 100.0, 101.0) == 100.0
    assert paper.close_shortfall_bps("sell", 100.0, 101.0) == -100.0
    assert paper.close_shortfall_bps("sell", 100.0, 99.0) == 100.0
    assert paper.close_shortfall_bps("buy", 0.0, 99.0) is None
    assert paper.close_shortfall_bps("buy", 100.0, float("nan")) is None


# The record row takes the close of the session after the plan's, since
# that is when a market-on-open order fills.
def test_the_record_uses_the_close_of_the_fill_session():
    import numpy as np

    from backend.cli import market_daily
    from backend.market.panel import Panel

    dates = np.array(["2026-09-04", "2026-09-08", "2026-09-09"], dtype="datetime64[D]")
    close = np.array([[100.0, 1.0], [110.0, 1.0], [120.0, 1.0]])
    panel = Panel(
        dates=dates,
        tickers=("AAA", "SPY"),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.ones_like(close),
        themes={},
        benchmark="SPY",
    )
    settled = [
        paper.Settled("id", "AAA", "sell", 10, "2026-09-04", "filled", 10, 105.0),
        paper.Settled("id2", "ZZZ", "buy", 10, "2026-09-04", "filled", 10, 50.0),
    ]
    rows = market_daily._settled_rows(settled, panel)
    # Planned on the 4th, filled at the 8th's open; the 8th closed at 110,
    # above the 105 fill, so the close would have been better for a sell.
    assert rows[0]["filled_price"] == 105.0
    assert np.isclose(rows[0]["close_shortfall_bps"], -(110.0 - 105.0) / 105.0 * 1e4)
    assert rows[1]["close_shortfall_bps"] is None  # a name the panel lacks
