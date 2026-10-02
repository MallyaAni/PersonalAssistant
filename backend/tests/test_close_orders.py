"""The close-window order goes to the market on the balancer's last candle.

Until 2026-10-02 the paper account sent its close-window orders as
market-on-close orders at the 3:30 PM candle. The paper broker's own record
(GET /v2/orders, 2026-09-10 to 10-02) holds 18 market-on-close orders the desk
did not cancel (the nightly's queued sells from 09-22, the 3:30 PM orders from
09-30): 4 filled, 2 filled in part and 12 expired with nothing filled, every
expiry stamped 16:00:04-16:01:53, after the close. All 23 market orders the
desk sent inside a session (09-30 to 10-02) filled within three seconds. So
the order now goes to the market on the last candle before the close
(3:45 PM ET; 12:45 PM on a calendar early close), and the board says so.

What has to hold:

* nothing is sent in the close window before the last candle; the last
  candle sends a market order, buys and sells alike; a later run sends nothing
  more (no double order), and an order already at the broker is adopted;
* the half-day close comes from the calendar, not a hard-coded 4 PM;
* a market-on-close order the older code sent that the broker has ended with
  nothing filled is replaced at market once, under a derived id, and adopted
  rather than sent twice if an earlier run already placed it; one still
  working, one that filled in part, a held sell, or one ended after the close
  is left alone;
* rows with an explicit bounded-execution contract keep their own rule.
"""

from datetime import date

import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import bounded_execution, entry_timing
from backend.tests.test_bounded_execution import LimitBroker, candidate
from backend.tests.test_bounded_execution import snapshot as bounded_snapshot
from backend.tests.test_intraday_orders import TODAY, Broker, latch, ny, row, save

# The day after Thanksgiving 2026: a calendar early close at 1 PM.
HALF_DAY = date(2026, 11, 27)
CID = row()["client_order_id"]


# Load the one pending row back from the saved state.
def kept(root, symbol="AAA") -> dict:
    """Return the saved pending row for `symbol`."""
    return next(r for r in paper.load_state(root).pending if r["symbol"] == symbol)


# A buy and a sell with no level reached all day: nothing at 3:30, both at
# market on the 3:45 candle, nothing more at 3:50, and nothing after the close.
def test_the_last_candle_sends_buys_and_sells_at_market_once(tmp_path):
    save(
        tmp_path,
        row("AAA"),
        row("BBB", side="sell", qty=5, reason="leaves the book"),
    )
    latch(tmp_path, symbol="AAA")
    broker = Broker(held={"BBB": 5})
    assert intraday_orders.send_due(tmp_path, {}, ny(15, 30), lambda: broker) == []
    assert broker.sent == []
    lines = intraday_orders.send_due(tmp_path, {}, ny(15, 45), lambda: broker)
    assert lines == [
        "buy 10 AAA (market, close): sent",
        "sell 5 BBB (market, close): sent",
    ]
    assert [s[:4] for s in broker.sent] == [
        ("market", "buy", "AAA", 10),
        ("market", "sell", "BBB", 5),
    ]
    assert kept(tmp_path)["sent"]["how"] == intraday_orders.MARKET
    assert intraday_orders.send_due(tmp_path, {}, ny(15, 50), lambda: broker) == []
    closed = Broker(is_open=False)
    assert intraday_orders.send_due(tmp_path, {}, ny(16, 0), lambda: closed) == []
    assert len(broker.sent) == 2
    assert closed.sent == []


# A run that finds the order already at the broker under the row's id (one
# that died after sending) records it and sends nothing.
def test_a_last_candle_order_already_at_the_broker_is_adopted(tmp_path):
    save(tmp_path, row("AAA"))
    broker = Broker(
        existing=[{"client_order_id": CID, "status": "filled", "time_in_force": "day"}]
    )
    lines = intraday_orders.send_due(tmp_path, {}, ny(15, 50), lambda: broker)
    assert lines == ["buy 10 AAA (market, close): already at the broker, recorded"]
    assert broker.sent == []
    assert kept(tmp_path)["sent"]["adopted"] is True


# On a calendar early close the window is 12:30-1:00 PM and the market order
# goes in on the 12:45 candle; the 4 PM clock plays no part.
def test_a_half_day_sends_on_its_own_last_candle(tmp_path):
    save(tmp_path, row("AAA", execute_on=HALF_DAY.isoformat()))
    broker = Broker()
    send = intraday_orders.send_due
    assert send(tmp_path, {}, ny(12, 30, HALF_DAY), lambda: broker) == []
    assert send(tmp_path, {}, ny(12, 45, HALF_DAY), lambda: broker) == [
        "buy 10 AAA (market, close): sent"
    ]
    assert send(tmp_path, {}, ny(12, 50, HALF_DAY), lambda: broker) == []
    assert send(tmp_path, {}, ny(15, 45, HALF_DAY), lambda: broker) == []
    assert len(broker.sent) == 1
    clock = entry_timing.session_clock(HALF_DAY)
    assert clock["market"] == ny(12, 45, HALF_DAY)
    assert clock["close"] == ny(13, 0, HALF_DAY)


# The board's sentences for the rule name the last candle, never a
# market-on-close order, on a regular and a half day.
def test_the_board_names_the_market_order_and_its_time():
    assert intraday_orders.rule_text("buy") == (
        "15-min close 1% under the open, else at market in the last 15 minutes"
    )
    assert "market-on-close" not in intraday_orders.rule_text("sell", 100.0, 101.0)
    for day, at in ((TODAY, "3:45 PM"), (HALF_DAY, "12:45 PM")):
        timed = entry_timing.timing(
            {"open": 100.0}, None, "buy", entry_timing.session_clock(day)["cutoff"], day
        )
        assert timed["state"] == entry_timing.CLOSE
        assert f"a market order at {at} ET, in the last 15 minutes" in timed["reason"]
        assert entry_timing.acting("Buy", timed).startswith("Buy near the close: ")


# The 10-02 case: an older market-on-close order the broker ended with nothing
# filled is replaced at market on the next run before the close, under a
# derived id, once; the board says what replaced what.
@pytest.mark.parametrize("status", ["canceled", "expired", "done_for_day"])
def test_an_ended_unfilled_market_on_close_is_replaced_once(tmp_path, status):
    moc = {"at": ny(15, 30).isoformat(), "how": intraday_orders.MOC, "qty": 10}
    save(tmp_path, row("AAA", sent=moc))
    ended = {
        "client_order_id": CID,
        "status": status,
        "filled_qty": "0",
        "qty": "10",
        "time_in_force": "cls",
    }
    broker = Broker(existing=[ended])
    lines = intraday_orders.send_due(tmp_path, {}, ny(15, 46), lambda: broker)
    assert lines == ["buy 10 AAA (market, close): sent"]
    assert broker.sent == [("market", "buy", "AAA", 10, CID + "-m")]
    saved = kept(tmp_path)
    assert saved["client_order_id"] == CID + "-m"
    assert saved["replaced"]["client_order_id"] == CID
    assert saved["replaced"]["status"] == status
    assert saved["replaced"]["sent"] == moc
    assert saved["sent"]["how"] == intraday_orders.MARKET
    # The next run sends nothing more.
    assert intraday_orders.send_due(tmp_path, {}, ny(15, 50), lambda: broker) == []
    assert len(broker.sent) == 1
    shown = intraday_orders.board_row(
        saved,
        broker={"client_order_id": CID + "-m", "status": "accepted", "qty": "10"},
        latch=None,
        quote=None,
        held=0,
        price=100,
        equity=100_000,
        now=ny(15, 47),
    )
    assert shown["status"] == (
        "Sent 3:46 PM · market order, replacing an unfilled market-on-close"
    )


# A run that dies between placing the replacement and recording it leaves the
# row unsent under the derived id; the next run adopts the broker's order.
def test_a_replacement_already_at_the_broker_is_adopted(tmp_path):
    moc = {"at": ny(15, 30).isoformat(), "how": intraday_orders.MOC}
    save(tmp_path, row("AAA", sent=moc))
    ended = {"client_order_id": CID, "status": "canceled", "filled_qty": "0"}
    placed = {"client_order_id": CID + "-m", "status": "filled", "filled_qty": "10"}
    broker = Broker(existing=[ended, placed])
    lines = intraday_orders.send_due(tmp_path, {}, ny(15, 46), lambda: broker)
    assert lines == ["buy 10 AAA (market, close): already at the broker, recorded"]
    assert broker.sent == []
    assert kept(tmp_path)["sent"]["adopted"] is True


# A replacement sell is capped at the shares the account holds.
def test_a_replacement_sell_never_exceeds_the_position(tmp_path):
    sell = row("BBB", side="sell", qty=8, reason="leaves the book")
    moc = {"at": ny(15, 30).isoformat(), "how": intraday_orders.MOC}
    save(tmp_path, {**sell, "sent": moc})
    ended = {
        "client_order_id": sell["client_order_id"],
        "status": "expired",
        "filled_qty": "0",
    }
    broker = Broker(held={"BBB": 6}, existing=[ended])
    intraday_orders.send_due(tmp_path, {}, ny(15, 46), lambda: broker)
    assert broker.sent == [("market", "sell", "BBB", 6, sell["client_order_id"] + "-m")]


# Left alone: a market-on-close order still working (it may fill at the
# close), one that filled in part (the settlement must keep that fill under
# its id), a sell the green-day rule held, one ended before the last candle
# (the rule's market order waits for it), and one found ended after the close.
@pytest.mark.parametrize(
    ("order", "extra", "at", "is_open"),
    [
        ({"status": "accepted", "filled_qty": "0"}, {}, ny(15, 46), True),
        ({"status": "expired", "filled_qty": "4"}, {}, ny(15, 46), True),
        (
            {"status": "canceled", "filled_qty": "0"},
            {"hold_requested": True},
            ny(15, 46),
            True,
        ),
        ({"status": "canceled", "filled_qty": "0"}, {}, ny(15, 35), True),
        ({"status": "expired", "filled_qty": "0"}, {}, ny(16, 2), False),
    ],
)
def test_a_market_on_close_that_may_fill_or_filled_is_not_replaced(
    tmp_path, order, extra, at, is_open
):
    moc = {"at": ny(15, 30).isoformat(), "how": intraday_orders.MOC}
    save(tmp_path, row("AAA", sent=moc, **extra))
    broker = Broker(is_open=is_open, existing=[{"client_order_id": CID, **order}])
    intraday_orders.send_due(tmp_path, {}, at, lambda: broker)
    assert broker.sent == []
    saved = kept(tmp_path)
    assert saved["client_order_id"] == CID
    assert saved["sent"] == moc
    assert "replaced" not in saved


# A row with an explicit bounded-execution contract keeps its own decision in
# the close window: the same verdict `bounded_execution.evaluate` gives, and
# never the legacy market order.
def test_bounded_rows_keep_their_own_rule_in_the_close_window(tmp_path):
    now = ny(15, 46)
    order = candidate()
    snap = bounded_snapshot(now)
    bar = snap["quotes"]["AAA"]
    verdict = intraday_orders.decide(order, {"open": 100.0}, bar, now, TODAY)
    timed = entry_timing.timing({"open": 100.0}, bar, "buy", now, TODAY)
    guard = bounded_execution.evaluate(order, timed, bar["execution_quote"], now, TODAY)
    assert verdict["guard"] == guard
    assert verdict["send"] == guard["send"]
    assert verdict["send"] != intraday_orders.MARKET
    save(tmp_path, order)
    broker = LimitBroker()
    intraday_orders.send_due(tmp_path, snap, now, lambda: broker)
    assert all(how != "market" for how, *_ in broker.sent)
