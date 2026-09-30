"""The one-time move of queued paper orders onto the board's intraday rule.

What has to hold, because it cancels orders on the paper broker: a dry run
touches nothing; only an order whose cancel the broker confirms with nothing
filled is moved, keeping its symbol, side, shares, reason and leg under a
fresh id on the intraday rule for the next session; an unconfirmed or already
gone order is left exactly as it was; FOMC event orders are never touched; and
nothing moves once the execution session has opened.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from backend.agents.trading.desk import intraday_orders, paper
from backend.cli import market_paper_retime

NY = ZoneInfo("America/New_York")
EVENING = datetime(2026, 9, 29, 21, 0, tzinfo=NY)


# A queued row as the 2026-09-29 nightly wrote it.
def queued(symbol, side, qty, seq, **extra):
    """Return a pending row queued the old way."""
    row = {
        "client_order_id": paper.order_id("2026-09-29", symbol, side, seq),
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "session": "2026-09-29",
        "reason": (
            "redeploying a downgraded name"
            if side == "buy"
            else "graded B; the desk wants the money elsewhere"
        ),
        "event_id": None,
        "priority": None,
        "execution_timing": None,
        "kind": None,
        "execution": {"reference_price": 100.0},
    }
    row.update(extra)
    return row


# A broker whose cancel answers per id.
class Broker:
    """Records cancel requests and answers with the given outcomes."""

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.cancelled: list[str] = []

    # Cancel by client order id.
    def cancel_orders(self, ids):
        self.cancelled.extend(ids)
        return {i: self.outcomes.get(i, "cancelled") for i in ids}


# Save a state with these pending rows and an order sequence past them.
def save(root, *rows):
    """Write the paper state."""
    state = paper.PaperState(order_seq=40)
    state.pending = [dict(r) for r in rows]
    paper.save_state(root, state)


# The dry run prints the plan and changes nothing, at the broker or on disk.
def test_the_dry_run_touches_nothing(tmp_path):
    save(tmp_path, queued("SMCI", "buy", 2, 30), queued("NVDA", "sell", 67, 31))
    before = paper.state_path(tmp_path).read_text()
    broker = Broker({})
    lines = market_paper_retime.retime(tmp_path, EVENING, lambda: broker, apply=False)
    assert lines[0] == "would move 2 orders onto the board's rule for 2026-09-30:"
    assert "Reinvest an exit's proceeds" in lines[1]
    assert "Exit: the grade fell to B" in lines[2]
    assert lines[-1].startswith("dry run")
    assert broker.cancelled == []
    assert paper.state_path(tmp_path).read_text() == before


# Applied: confirmed cancels move, the rest stay queued, events are untouched.
def test_only_confirmed_cancels_move(tmp_path):
    smci = queued("SMCI", "buy", 2, 30)
    hpe = queued("HPE", "buy", 6, 31, kind=None)
    nvda = queued("NVDA", "sell", 67, 32)
    fomc = queued("MU", "sell", 1, 33, event_id="fomc-2026-10-28")
    save(tmp_path, smci, hpe, nvda, fomc)
    broker = Broker({hpe["client_order_id"]: "unconfirmed"})
    lines = market_paper_retime.retime(tmp_path, EVENING, lambda: broker, apply=True)
    assert broker.cancelled == [
        smci["client_order_id"],
        hpe["client_order_id"],
        nvda["client_order_id"],
    ]
    assert "  kept HPE as queued: the cancel was unconfirmed" in lines
    state = paper.load_state(tmp_path)
    rows = {r["symbol"]: r for r in state.pending}
    assert rows["HPE"] == hpe
    assert rows["MU"] == fomc
    for symbol, old in (("SMCI", smci), ("NVDA", nvda)):
        row = rows[symbol]
        assert row["execution_timing"] == intraday_orders.INTRADAY_TIMING
        assert row["execute_on"] == "2026-09-30"
        assert row["replaced"] == old["client_order_id"]
        assert row["client_order_id"] != old["client_order_id"]
        assert (row["side"], row["qty"], row["reason"]) == (
            old["side"],
            old["qty"],
            old["reason"],
        )
    assert rows["SMCI"]["client_order_id"] == "anios-2026-09-29-buy-smci-40"
    assert state.order_seq == 42
    # The moved rows are now due on the board's rule, and only them.
    due = intraday_orders.due(state, datetime(2026, 9, 30).date())
    assert sorted(r["symbol"] for r in due) == ["NVDA", "SMCI"]
    assert lines[-1].startswith("done: 2 moved, 1 kept as queued")


# Nothing moves once the session the orders execute on has opened, and a
# second run finds nothing left to move.
def test_nothing_moves_after_the_open_or_twice(tmp_path):
    save(tmp_path, queued("SMCI", "buy", 2, 30))
    broker = Broker({})
    opened = datetime(2026, 9, 30, 9, 31, tzinfo=NY)
    lines = market_paper_retime.retime(tmp_path, opened, lambda: broker, apply=True)
    assert lines[0].startswith("refused: the 2026-09-30 session opened")
    assert broker.cancelled == []
    market_paper_retime.retime(tmp_path, EVENING, lambda: broker, apply=True)
    again = market_paper_retime.retime(tmp_path, EVENING, lambda: broker, apply=True)
    assert again == ["nothing to move: no queued ordinary orders are pending"]
