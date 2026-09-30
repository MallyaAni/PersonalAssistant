"""The paper account's intraday leg: it trades what the board says, when it says it.

What has to hold, because the operator reads the board and the paper account
side by side and they must never disagree:

* an order is sent exactly when the board's `entry_timing` says BUY/SELL/TRIM
  stands: a market order on the first 15-minute close through the 1% level,
  a market-on-close order in the close window before the cutoff, a market
  order late in the window after it, and nothing before the open, while
  waiting, or after the close;
* it is written down as being sent before the request leaves, sent once
  (a second candle, or an order an earlier run already placed, sends nothing),
  never while the broker says the market is closed, and a sell never for
  more shares than the account holds;
* the board's reading of each order says what (BUY/SELL/TRIM and its size),
  why (the plan leg in plain words), when (the rule for its session) and what
  has happened (planned, waiting, due, sent, filled, held, missed), and every
  reason the planner writes has plain words.
"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import entry_timing

NY = ZoneInfo("America/New_York")
# Wednesday 2026-09-30, a regular session; its orders were decided Tuesday.
TODAY = date(2026, 9, 30)
DECIDED = "2026-09-29"


# An aware New York instant on `day`.
def ny(hour: int, minute: int = 0, day: date = TODAY) -> datetime:
    """Return `day` at hour:minute in New York."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NY)


# One pending row as the nightly writes it for the intraday leg.
def row(symbol="AAA", side="buy", qty=10, reason="rebalance to 0.083", **extra):
    """Return a pending row planned on DECIDED for TODAY."""
    out = {
        "client_order_id": f"anios-{DECIDED}-{side}-{symbol.lower()}-1",
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "session": DECIDED,
        "reason": reason,
        "event_id": None,
        "priority": None,
        "execution_timing": intraday_orders.INTRADAY_TIMING,
        "execute_on": TODAY.isoformat(),
        "kind": None,
        "execution": {"reference_price": 100.0},
    }
    out.update(extra)
    return out


# A live.json quote: the session's open and the latest completed bar.
def quote(last: float, bar: datetime, opened: float = 100.0) -> dict:
    """Return the quote dict the balancer writes."""
    return {
        "last": last,
        "open": opened,
        "bar": bar.astimezone(UTC).isoformat(),
        "as_of": (bar + timedelta(minutes=15)).astimezone(UTC).isoformat(),
    }


# Save a state holding `rows` as pending.
def save(root: Path, *rows: dict) -> None:
    """Write a paper state whose pending rows are `rows`."""
    state = paper.PaperState()
    state.pending = [dict(r) for r in rows]
    paper.save_state(root, state)


# A broker that records what it was sent and answers with a clock.
class Broker:
    """The paper broker, faked: clock, positions, orders, submissions."""

    def __init__(self, is_open=True, held=None, existing=None, refuse=None):
        self.is_open = is_open
        self.held = held or {}
        self.existing = existing or []
        self.refuse = refuse
        self.sent: list[tuple] = []

    # The broker's clock.
    def clock(self):
        return {"is_open": self.is_open}

    # The account's positions.
    def positions(self):
        return [SimpleNamespace(symbol=s, qty=q) for s, q in self.held.items()]

    # Every order since a time: the ones placed earlier plus this run's.
    def orders_since(self, since):
        return list(self.existing)

    # Record a submission, or refuse it the way the broker would.
    def _take(self, how, symbol, qty, side, cid):
        from backend.market import alpaca_trading

        if self.refuse:
            raise alpaca_trading.AlpacaTradingError(self.refuse)
        self.sent.append((how, side, symbol, qty, cid))
        return {
            "submitted_at": "2026-09-30T14:16:01Z",
            "time_in_force": "day" if how == "market" else "cls",
        }

    # A market order now.
    def submit_market(self, symbol, qty, side, cid):
        return self._take("market", symbol, qty, side, cid)

    # A market-on-close order.
    def submit_market_on_close(self, symbol, qty, side, cid):
        return self._take("moc", symbol, qty, side, cid)


# Write today's latch for one name with an optional buy or sell trigger.
def latch(root: Path, symbol="AAA", opened=100.0, buy=None, sell=None):
    """Write the entry-timing latch for TODAY."""
    path = entry_timing.latch_path(root, TODAY)
    path.parent.mkdir(parents=True, exist_ok=True)
    symbols = {
        symbol: {
            "open": opened,
            "buy_level": opened * 0.99,
            "sell_level": opened * 1.01,
            "buy_trigger": buy,
            "sell_trigger": sell,
        }
    }
    path.write_text(
        json.dumps({"session": TODAY.isoformat(), "symbols": symbols}), encoding="utf-8"
    )


# The next session skips weekends and holidays and fails closed off the calendar.
def test_the_next_session_is_the_reviewed_calendars():
    assert intraday_orders.next_session(date(2026, 9, 29)) == date(2026, 9, 30)
    assert intraday_orders.next_session(date(2026, 10, 2)) == date(2026, 10, 5)
    # Thanksgiving 2026-11-26 is closed.
    assert intraday_orders.next_session(date(2026, 11, 25)) == date(2026, 11, 27)
    assert intraday_orders.next_session(date(1990, 1, 2)) is None


# Only unsent ordinary rows for today are due; event rows, other days and
# rows already sent are not.
def test_only_todays_unsent_ordinary_rows_are_due():
    state = paper.PaperState()
    state.pending = [
        row("AAA"),
        row("BBB", execute_on="2026-10-01"),
        row("CCC", sent={"at": "x"}),
        row("DDD", event_id="fomc-1"),
        row("EEE", execution_timing="next_open"),
    ]
    assert [r["symbol"] for r in intraday_orders.due(state, TODAY)] == ["AAA"]


# The decision follows the board's clock exactly.
@pytest.mark.parametrize(
    ("at", "trigger", "expected"),
    [
        (ny(9, 20), None, None),  # before the open
        (ny(10, 16), None, None),  # waiting for the level
        (ny(10, 16), "buy", intraday_orders.MARKET),  # level reached
        (ny(15, 35), None, intraday_orders.MOC),  # close window
        (ny(15, 52), None, intraday_orders.MARKET),  # past the MOC cutoff
        (ny(16, 5), None, None),  # the session has closed
    ],
)
def test_the_decision_is_the_boards_clock(at, trigger, expected):
    latch_row = {"open": 100.0, "buy_trigger": None, "sell_trigger": None}
    if trigger:
        latch_row["buy_trigger"] = {"bar": ny(10, 0).isoformat(), "price": 98.9}
    verdict = intraday_orders.decide(row(), latch_row, None, at, TODAY)
    assert verdict["send"] == expected


# A buy whose level is reached is sent to the market once: written down as
# sending first, recorded as sent with the level after, and a second candle
# sends nothing.
def test_a_triggered_buy_is_sent_once(tmp_path):
    save(tmp_path, row("AAA"))
    latch(tmp_path, buy={"bar": ny(10, 0).isoformat(), "price": 98.9})
    broker = Broker()
    lines = intraday_orders.send_due(tmp_path, {}, ny(10, 16), lambda: broker)
    assert lines == ["buy 10 AAA (market, triggered): sent"]
    assert broker.sent == [("market", "buy", "AAA", 10, row()["client_order_id"])]
    kept = paper.load_state(tmp_path).pending[0]
    assert kept["sending"]
    assert kept["sent"]["how"] == intraday_orders.MARKET
    assert kept["sent"]["level"] == pytest.approx(99.0)
    assert kept["sent"]["trigger_price"] == 98.9
    assert kept["execution"]["time_in_force"] == "day"
    again = intraday_orders.send_due(tmp_path, {}, ny(10, 31), lambda: broker)
    assert again == []
    assert len(broker.sent) == 1


# A buy still waiting sends nothing; in the close window it goes in as a
# market-on-close order, and a sell with a pop goes to the market.
def test_waiting_close_window_and_a_sell_pop(tmp_path):
    save(tmp_path, row("AAA"), row("BBB", side="sell", qty=5, reason="leaves the book"))
    latch(tmp_path, symbol="AAA")
    broker = Broker(held={"BBB": 5})
    assert intraday_orders.send_due(tmp_path, {}, ny(11, 1), lambda: broker) == []
    snapshot = {"quotes": {"BBB": quote(101.2, ny(11, 0))}}
    lines = intraday_orders.send_due(tmp_path, snapshot, ny(11, 16), lambda: broker)
    assert lines == ["sell 5 BBB (market, triggered): sent"]
    lines = intraday_orders.send_due(tmp_path, {}, ny(15, 31), lambda: broker)
    assert lines == ["buy 10 AAA (moc, close): sent"]
    assert [s[:4] for s in broker.sent] == [
        ("market", "sell", "BBB", 5),
        ("moc", "buy", "AAA", 10),
    ]


# Nothing is sent while the broker reports the market closed, whatever the
# calendar says: a market-on-close order then would queue for the next close.
def test_nothing_is_sent_while_the_broker_is_closed(tmp_path):
    save(tmp_path, row("AAA"))
    broker = Broker(is_open=False)
    lines = intraday_orders.send_due(tmp_path, {}, ny(15, 31), lambda: broker)
    assert "market closed" in lines[0]
    assert broker.sent == []
    assert "sent" not in paper.load_state(tmp_path).pending[0]


# An order the broker already holds under the row's id (a run that died after
# sending) is adopted, not sent twice.
def test_an_order_already_at_the_broker_is_adopted(tmp_path):
    save(tmp_path, row("AAA"))
    existing = [
        {
            "client_order_id": row()["client_order_id"],
            "status": "accepted",
            "time_in_force": "cls",
            "submitted_at": "2026-09-30T19:31:00Z",
        }
    ]
    broker = Broker(existing=existing)
    lines = intraday_orders.send_due(tmp_path, {}, ny(15, 35), lambda: broker)
    assert lines == ["buy 10 AAA (moc, close): already at the broker, recorded"]
    assert broker.sent == []
    assert paper.load_state(tmp_path).pending[0]["sent"]["adopted"] is True


# A sell is capped at the shares held, and with none held it is not sent.
def test_a_sell_never_exceeds_the_position(tmp_path):
    save(
        tmp_path,
        row("AAA", side="sell", qty=10, reason="leaves the book"),
        row("BBB", side="sell", qty=4, reason="leaves the book"),
    )
    broker = Broker(held={"AAA": 6})
    lines = intraday_orders.send_due(tmp_path, {}, ny(15, 35), lambda: broker)
    assert broker.sent == [
        ("moc", "sell", "AAA", 6, row("AAA", side="sell")["client_order_id"])
    ]
    assert "sell 4 BBB (moc, close): not sent (no shares to sell)" in lines
    kept = {r["symbol"]: r for r in paper.load_state(tmp_path).pending}
    assert kept["AAA"]["sent"]["qty"] == 6
    assert kept["BBB"]["send_error"] == "no shares to sell"


# A refused order is recorded and tried again on the next candle.
def test_a_refused_order_is_retried(tmp_path):
    save(tmp_path, row("AAA"))
    refusing = Broker(refuse="insufficient buying power")
    lines = intraday_orders.send_due(tmp_path, {}, ny(15, 31), lambda: refusing)
    assert lines == ["buy 10 AAA (moc, close): REFUSED insufficient buying power"]
    kept = paper.load_state(tmp_path).pending[0]
    assert kept["send_error"] == "insufficient buying power"
    assert "sent" not in kept
    broker = Broker()
    assert intraday_orders.send_due(tmp_path, {}, ny(15, 46), lambda: broker) == [
        "buy 10 AAA (moc, close): sent"
    ]
    assert "send_error" not in paper.load_state(tmp_path).pending[0]


# Every reason the planner writes has plain words and a leg; the literals are
# checked against the planner's own source so a reworded reason fails here.
def test_every_plan_leg_has_a_plain_reason():
    source = "\n".join(
        (Path(__file__).parents[1] / p).read_text(encoding="utf-8")
        for p in (
            "agents/trading/desk/paper.py",
            "agents/trading/desk/planner.py",
            "cli/market_daily.py",
        )
    )
    cases = {
        "rebalance to 0.083": ("reset", "Reset to the 8.3% target"),
        "leaves the book": ("reset-exit", "Reset: no longer in the book"),
        "graded B; the desk wants the money elsewhere": (
            "exit",
            "Exit: the grade fell to B",
        ),
        "redeploying a downgraded name": ("reinvest", "Reinvest an exit's proceeds"),
        "price entry: breakout through its own 20-day band": (
            "entry",
            "Breakout entry (20-day band)",
        ),
        "deferred buy: the remainder cash could not pay for last session": (
            "deferred",
            "Finish last session's buy (cash was short)",
        ),
        "redeploy: cash beyond the buffer put back to its target weights": (
            "redeploy",
            "Put idle cash to work, toward the target",
        ),
    }
    for reason, expected in cases.items():
        assert intraday_orders.why({"reason": reason}) == expected
    for literal in (
        'f"rebalance to {target:.3f}"',
        '"leaves the book"',
        'f"graded {letter}; the desk wants the money elsewhere"',
        '"redeploying a downgraded name"',
        '"price entry: breakout through its own 20-day band"',
        '"deferred buy: the remainder cash could not pay for last session"',
        '"redeploy: cash beyond the buffer put back to its target weights"',
    ):
        assert literal in source, literal
    assert intraday_orders.why({"reason": "x", "event_id": "fomc"}) == (
        "event",
        "FOMC risk rule",
    )


# The board's reading of each order across its life, in one vocabulary.
def test_the_board_reads_each_order_in_one_vocabulary(tmp_path):
    common = dict(latch=None, quote=None, held=0.0, price=40.0, equity=100_000.0)
    # Planned tonight for tomorrow.
    planned = intraday_orders.board_row(
        row(), broker=None, now=ny(20, 0, date(2026, 9, 29)), **common
    )
    assert planned["action"] == "BUY"
    assert planned["state"] == "planned"
    assert planned["status"] == "Planned"
    assert planned["when"] == (
        "Wed Sep 30 · 15-min close 1% under the open, else at the close"
    )
    assert planned["notional"] == pytest.approx(400.0)
    assert planned["weight"] == pytest.approx(0.004)
    assert planned["why"] == "Reset to the 8.3% target"
    # In the session, waiting for its level.
    latch_doc = {"session": TODAY.isoformat(), "symbols": {"AAA": {"open": 41.0}}}
    waiting = intraday_orders.board_row(
        row(),
        broker=None,
        latch=latch_doc,
        quote=None,
        held=0.0,
        price=40.9,
        equity=100_000.0,
        now=ny(10, 20),
    )
    assert waiting["state"] == "waiting"
    assert waiting["status"] == "Waiting for $40.59 or the close (3:30 PM window)"
    assert waiting["when"] == (
        "Today · 15-min close ≤ $40.59 (1% under the $41.00 open), else at the close"
    )
    # Sent at the trigger, then filled.
    sent_row = row(sent={"at": ny(10, 16).isoformat(), "how": "market", "qty": 10})
    sent = intraday_orders.board_row(sent_row, broker=None, now=ny(10, 17), **common)
    assert (sent["state"], sent["status"]) == (
        "sent",
        "Sent 10:16 AM · market order · broker status unavailable",
    )
    filled = intraday_orders.board_row(
        sent_row,
        broker={
            "status": "filled",
            "filled_qty": "10",
            "filled_avg_price": "40.51",
            "filled_at": "2026-09-30T14:16:03Z",
        },
        now=ny(10, 30),
        **common,
    )
    assert (filled["state"], filled["status"]) == (
        "filled",
        "Bought 10 @ $40.51 · 10:16 AM",
    )
    # Missed: its session ended with nothing sent.
    missed = intraday_orders.board_row(
        row(), broker=None, now=ny(9, 0, date(2026, 10, 1)), **common
    )
    assert missed["state"] == "missed"


# Orders the nightly sent itself before the switch read as queued, a held
# closing sell reads as held, and exits and trims have their own words.
def test_older_orders_and_the_three_sell_words():
    now = ny(20, 0, date(2026, 9, 29))
    common = dict(latch=None, quote=None, price=None, equity=100_000.0, now=now)
    legacy_buy = row(execution_timing=None, execute_on=None)
    queued = intraday_orders.board_row(
        legacy_buy, broker={"status": "accepted"}, held=0.0, **common
    )
    assert (queued["state"], queued["status"]) == (
        "queued",
        "Queued at the broker · fills at the open",
    )
    assert queued["when"] == "Wed Sep 30 · at the open"
    exit_sell = row(
        "NVDA",
        side="sell",
        qty=67,
        execution_timing=None,
        execute_on=None,
        reason="graded B; the desk wants the money elsewhere",
    )
    exited = intraday_orders.board_row(
        exit_sell,
        broker={"status": "accepted", "time_in_force": "cls"},
        held=67.0,
        **common,
    )
    assert exited["action"] == "SELL"
    assert exited["why"] == "Exit: the grade fell to B"
    assert (
        exited["when"]
        == "Wed Sep 30 · at the close, held instead if it opens above the last close"
    )
    trim = intraday_orders.board_row(
        row("SMCI", side="sell", qty=100, reason="rebalance to 0.091"),
        broker=None,
        held=350.0,
        **common,
    )
    assert trim["action"] == "TRIM"
    held = intraday_orders.board_row(
        {**exit_sell, "status": paper.SKIPPED}, broker=None, held=67.0, **common
    )
    assert (held["state"], held["status"]) == (
        "held",
        "Held instead: it opened above the last close",
    )


# The board lists the pending rows and the same decision's held sells, the
# ones still to happen first.
def test_board_orders_lists_pending_then_finished():
    state = paper.PaperState()
    state.pending = [
        row("AAA", qty=1, sent={"at": ny(10, 16).isoformat(), "how": "market"}),
        row("BBB", qty=50),
    ]
    state.journal = [
        {
            **row("CCC", side="sell", qty=5, reason="leaves the book"),
            "status": paper.SKIPPED,
        },
        {
            **row("OLD", side="sell", qty=5),
            "session": "2026-09-01",
            "status": paper.SKIPPED,
        },
    ]
    shown = intraday_orders.board_orders(
        state,
        broker_orders=[
            {
                "client_order_id": row("AAA")["client_order_id"],
                "status": "filled",
                "filled_qty": 1,
                "filled_avg_price": 100.0,
            }
        ],
        latch=None,
        quotes=None,
        held={"CCC": 5},
        prices={},
        equity=100_000.0,
        now=ny(10, 30),
    )
    # BBB is still to happen (no opening price latched yet); the finished
    # ones follow, largest first; the older decision's held sell is not shown.
    assert [(r["symbol"], r["state"]) for r in shown] == [
        ("BBB", "planned"),
        ("CCC", "held"),
        ("AAA", "filled"),
    ]
    assert shown[0]["status"] == "Waiting for today's opening price"


# A holdings-clipped order must display the broker quantity and actual fill value.
def test_clipped_order_displays_five_filled_not_twenty_planned():
    planned = row(side="sell", qty=20, sent={"qty": 5, "how": "market"})
    shown = intraday_orders.board_row(
        planned,
        broker={
            "status": "filled",
            "qty": "5",
            "filled_qty": "5",
            "filled_avg_price": "100",
        },
        latch=None,
        quote=None,
        held=0,
        price=80,
        equity=100_000,
        now=ny(15, 55),
    )
    assert (shown["planned_qty"], shown["submitted_qty"], shown["qty"]) == (20, 5, 5)
    assert (shown["notional"], shown["price"], shown["quantity_basis"]) == (
        500,
        100,
        "filled",
    )
    assert shown["terminal"] is True
    assert shown["remaining_qty"] == 0
    assert planned["qty"] == 20  # Display must not mutate the execution plan.


# A cancelled partial fill has no working remainder; an open partial fill does.
@pytest.mark.parametrize(
    ("status", "terminal", "state", "remaining", "qty"),
    [
        ("partially_filled", False, "partial", 3, 5),
        ("canceled", True, "cancelled", 0, 2),
        ("rejected", True, "rejected", 0, 2),
    ],
)
def test_partial_fill_preserves_terminal_evidence(
    status, terminal, state, remaining, qty
):
    shown = intraday_orders.board_row(
        row(qty=20, sent={"qty": 5}),
        broker={
            "status": status,
            "qty": "5",
            "filled_qty": "2",
            "filled_avg_price": "100",
        },
        latch=None,
        quote=None,
        held=2,
        price=80,
        equity=100_000,
        now=ny(15, 55),
    )
    assert (
        shown["terminal"],
        shown["state"],
        shown["remaining_qty"],
        shown["qty"],
    ) == (terminal, state, remaining, qty)
    assert shown["filled_qty"] == 2
    assert "of 5" in shown["status"]


# A missing broker answer cannot establish fills or a working remainder.
def test_submitted_order_without_broker_has_unknown_remainder():
    shown = intraday_orders.board_row(
        row(qty=20, sent={"qty": 5}),
        broker=None,
        latch=None,
        quote=None,
        held=0,
        price=100,
        equity=100_000,
        now=ny(15, 55),
    )
    assert (shown["qty"], shown["quantity_basis"]) == (5, "submitted")
    assert shown["remaining_qty"] is None
    assert shown["terminal"] is None
    assert shown["filled_qty"] is None
    assert "broker status unavailable" in shown["status"]


# Adopted broker orders may be smaller than the plan even without a saved sent quantity.
def test_adopted_broker_quantity_overrides_plan():
    shown = intraday_orders.board_row(
        row(qty=20, sent={"adopted": True}),
        broker={"status": "accepted", "qty": "5", "filled_qty": "0"},
        latch=None,
        quote=None,
        held=0,
        price=100,
        equity=100_000,
        now=ny(15, 55),
    )
    assert (shown["qty"], shown["remaining_qty"], shown["submitted_qty"]) == (5, 5, 5)


# The dashboard uses the same MOC cutoff as execution, including early closes.
@pytest.mark.parametrize(
    ("day", "hour", "minute", "how"),
    [
        (TODAY, 15, 30, "moc"),
        (TODAY, 15, 50, "market"),
        (TODAY, 15, 55, "market"),
        (date(2026, 11, 27), 12, 30, "moc"),
        (date(2026, 11, 27), 12, 50, "market"),
    ],
)
def test_close_window_words_match_actual_order_type(day, hour, minute, how):
    now = ny(hour, minute, day)
    pending = row(execute_on=day.isoformat())
    latch_row = {"open": 100.0}
    verdict = intraday_orders.decide(pending, latch_row, None, now, day)
    shown = intraday_orders.board_row(
        pending,
        broker=None,
        latch={"session": day.isoformat(), "symbols": {"AAA": latch_row}},
        quote=None,
        held=0,
        price=100,
        equity=100_000,
        now=now,
    )
    assert verdict["send"] == how
    order_type = "market-on-close" if how == "moc" else "market order"
    assert shown["status"] == f"Close window · {order_type} due"
