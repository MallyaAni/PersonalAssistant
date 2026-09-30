"""Produce the paper account's orders for the board's browser tests, worded by the backend.

Run from the repository root with the backend test dependencies available:
``PYTHONPATH=. python frontend/e2e/fixtures/paper_plan.py --check`` (fails when
the committed JSON differs), or without --check to print the regenerated JSON.
The orders pass through the real `intraday_orders.board_orders`, so the browser
tests assert the exact sentences `/desk/paper` sends; no broker, network or
persistence boundary is used.

The scenario is the live paper account of 2026-09-29 carried to Thursday
2026-10-01 at 10:20 AM ET, under the board's intraday rule: the exits and
the reinvest/deferred buys planned on Wednesday night are at every stage of
their life (waiting for the level, level reached, sent, filled), and the
same account read on Wednesday evening, when all of them are only planned.
"""

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from backend.agents.trading.desk import intraday_orders, paper, plainly

DECIDED = "2026-09-30"
TODAY = date(2026, 10, 1)
OUT = Path(__file__).with_name("paper_plan.json")

# The account as the broker reported it (symbol, shares, price).
POSITIONS = [
    ("AAOI", 89, 101.25),
    ("ANET", 32, 202.86),
    ("COHR", 13, 294.12),
    ("HPE", 61, 61.70),
    ("LITE", 4, 980.00),
    ("MDB", 23, 336.50),
    ("MU", 3, 1071.31),
    ("NTAP", 78, 212.00),
    ("NVDA", 67, 228.23),
    ("SMCI", 350, 41.20),
    ("SNDK", 3, 1725.01),
    ("STX", 4, 916.35),
    ("SWKS", 44, 88.44),
]
EQUITY = 100_018.26
CASH = 3_076.26
REASONS = {
    "exit": "graded B; the desk wants the money elsewhere",
    "reinvest": "redeploying a downgraded name",
    "deferred": "deferred buy: the remainder cash could not pay for last session",
}
# (symbol, side, qty, leg, seq)
ORDERS = [
    ("NVDA", "sell", 67, "exit", 1),
    ("ANET", "sell", 32, "exit", 2),
    ("AAOI", "buy", 4, "reinvest", 3),
    ("HPE", "buy", 6, "deferred", 4),
    ("HPE", "buy", 3, "reinvest", 5),
    ("SMCI", "buy", 2, "reinvest", 6),
    ("SWKS", "buy", 4, "deferred", 7),
    ("SWKS", "buy", 2, "reinvest", 8),
    ("COHR", "buy", 1, "deferred", 9),
    ("MDB", "buy", 1, "deferred", 10),
]


# An aware instant from a New York wall-clock time on TODAY.
def ny(hour: int, minute: int, day: date = TODAY) -> datetime:
    """Return day at hour:minute New York time."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=intraday_orders.NEW_YORK)


# The pending rows the Wednesday nightly writes down.
def pending() -> list[dict]:
    """Return the paper state's pending rows for the scenario."""
    prices = {s: p for s, _, p in POSITIONS}
    return [
        {
            "client_order_id": paper.order_id(DECIDED, symbol, side, seq),
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "session": DECIDED,
            "reason": REASONS[leg],
            "event_id": None,
            "priority": None,
            "execution_timing": intraday_orders.INTRADAY_TIMING,
            "execute_on": TODAY.isoformat(),
            "kind": None,
            "execution": {"reference_price": prices[symbol]},
        }
        for symbol, side, qty, leg, seq in ORDERS
    ]


# Thursday 10:20 AM: what the balancer has done so far and what the broker says.
def thursday() -> list[dict]:
    """Return board_orders for the in-session read."""
    state = paper.PaperState(last_rebalance="2026-09-28", sessions_since_rebalance=2)
    rows = pending()
    by = {(r["symbol"], r["qty"]): r for r in rows}
    sent = {
        ("ANET", 32): ny(9, 46),
        ("HPE", 6): ny(10, 16),
        ("HPE", 3): ny(10, 16),
        ("SWKS", 4): ny(9, 46),
        ("SWKS", 2): ny(9, 46),
    }
    for key, at in sent.items():
        by[key]["sent"] = {"at": at.isoformat(), "how": "market", "qty": key[1]}
    state.pending = rows
    filled = {
        ("ANET", 32): ("205.10", "2026-10-01T13:46:04Z"),
        ("SWKS", 4): ("86.90", "2026-10-01T13:46:02Z"),
        ("SWKS", 2): ("86.91", "2026-10-01T13:46:03Z"),
    }
    broker = [
        {
            "client_order_id": by[key]["client_order_id"],
            "status": "filled",
            "filled_qty": str(key[1]),
            "filled_avg_price": price,
            "filled_at": at,
        }
        for key, (price, at) in filled.items()
    ] + [
        {"client_order_id": by[key]["client_order_id"], "status": "accepted", "filled_qty": "0"}
        for key in (("HPE", 6), ("HPE", 3))
    ]
    opens = {"NVDA": 230.00, "AAOI": 100.80, "SMCI": 41.60, "COHR": 296.00, "MDB": 338.00}
    latch = {
        "session": TODAY.isoformat(),
        "symbols": {s: {"open": o, "buy_trigger": None, "sell_trigger": None} for s, o in opens.items()},
    }
    latch["symbols"]["AAOI"]["buy_trigger"] = {"bar": ny(10, 0).isoformat(), "price": 99.60}
    held = {s: float(q) for s, q, _ in POSITIONS}
    held["ANET"] = 0.0
    held["SWKS"] = 50.0
    prices = {s: p for s, _, p in POSITIONS}
    prices.update({"NVDA": 229.10, "AAOI": 99.70, "SMCI": 41.35, "HPE": 61.05})
    return intraday_orders.board_orders(
        state, broker_orders=broker, latch=latch, quotes={}, held=held,
        prices=prices, equity=EQUITY, now=ny(10, 20),
    )


# Wednesday 8:15 PM: the same orders as the nightly wrote them, all planned.
def wednesday() -> list[dict]:
    """Return board_orders for the evening read after the nightly."""
    state = paper.PaperState(last_rebalance="2026-09-28", sessions_since_rebalance=2)
    state.pending = pending()
    return intraday_orders.board_orders(
        state, broker_orders=[], latch=None, quotes={},
        held={s: float(q) for s, q, _ in POSITIONS},
        prices={s: p for s, _, p in POSITIONS}, equity=EQUITY,
        now=ny(20, 15, date(2026, 9, 30)),
    )


# Everything the spec needs, in one JSON document.
def produce() -> dict:
    """Return the fixture document."""
    plan = {
        "rule": intraday_orders.INTRADAY_TIMING,
        "rule_text": {"buy": intraday_orders.rule_text("buy"), "sell": intraday_orders.rule_text("sell")},
        "until_rebalance": 18,
        "last_rebalance": "2026-09-28",
        "reason": None,
    }
    return {
        "tone_wording": [
            plainly._figure("sentiment", field, value, None)
            for field, value in (
                ("tone_guidance", 0.2),
                ("tone_demand", 0.0),
                ("tone_guidance_change", 0.1),
                ("tone_supply_constrained", 0.0),
            )
        ],
        "equity": EQUITY,
        "cash": CASH,
        "positions": [
            {"symbol": s, "qty": q, "market_value": round(q * p, 2), "avg_entry_price": p,
             "current_price": p, "unrealized_pl": 0.0}
            for s, q, p in POSITIONS
        ],
        "thursday": {**plan, "orders": thursday()},
        "wednesday": {**plan, "orders": wednesday()},
    }


if __name__ == "__main__":
    text = json.dumps(produce(), indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        if OUT.read_text(encoding="utf-8") != text:
            sys.exit("paper_plan.json is stale: regenerate it with this script")
        print("paper_plan.json is current")
    else:
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT}")
