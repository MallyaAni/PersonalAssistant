"""FOMC restorations sent on the decision session's last candle.

`event_execution` plans the restoration of an FOMC cut on the eve of the
decision, once the cut has filled, and the nightly writes it down with this
module's timing and the decision session as its `execute_on`. The balancer
sends it here, as a market order on the decision session's last candle
(3:45 PM ET on a 4:00 close, `entry_timing.FINAL_LEAD`), after the 2:00 PM
statement and the press conference: never earlier, never on a price level.
Since the June 2026 guidance change most of the post-decision rebound came
overnight, which a restoration at the next open missed
(`docs/research/fomc-lead-in-2026-10-22.md`).

It lives beside `intraday_orders` rather than inside it because the original
live-model history audit authenticates archived sessions against that
module's exact bytes; the sending itself is `intraday_orders._send_one`,
unchanged, under the same paper lock.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import entry_timing

DECISION_CLOSE = "decision_close"
NEW_YORK = intraday_orders.NEW_YORK


# The decision-close restorations executing on `today` that have not gone out.
def due(state: paper.PaperState, today: date) -> list[dict]:
    """Return the unsent decision-close rows executing on `today`."""
    return [
        row
        for row in state.pending
        if row.get("execution_timing") == DECISION_CLOSE
        and row.get("event_id")
        and row.get("execute_on") == today.isoformat()
        and not row.get("sent")
    ]


# Whether `now` is inside the decision session's last candle.
def in_window(now: datetime, today: date) -> bool:
    clock = entry_timing.session_clock(today)
    return clock["final"] <= now < clock["close"]


# Send every due restoration on the last candle, under the paper lock; return
# the log lines. Nothing is sent before the last candle, after the close, or
# while the broker's own clock says the market is closed.
def send_due(
    root: Path | str, now: datetime, client_factory: Callable[[], Any]
) -> list[str]:
    """Send the due decision-close restorations; return log lines."""
    from backend.market import alpaca_trading

    if now.tzinfo is None:
        raise ValueError("send_due requires a timezone-aware now")
    today = now.astimezone(NEW_YORK).date()
    root = Path(root)
    with paper.transaction(root):
        state = paper.load_state(root)
        rows = due(state, today)
        if not rows or not in_window(now, today):
            return []
        started = time.monotonic()
        try:
            client = client_factory()
            if not bool((client.clock() or {}).get("is_open")):
                return [
                    "FOMC restoration: the broker reports the market closed; "
                    "nothing sent"
                ]
            known = {
                str(o.get("client_order_id") or ""): o
                for o in client.orders_since(f"{today.isoformat()}T00:00:00Z") or []
            }
            held = {p.symbol: float(p.qty) for p in client.positions()}
        except (alpaca_trading.AlpacaTradingError, OSError, ValueError) as exc:
            return [f"FOMC restoration: broker unavailable ({exc}); nothing sent"]
        verdict = {
            "send": intraday_orders.MARKET,
            "timed": {"state": DECISION_CLOSE, "open": None, "level": None},
        }
        return [
            "FOMC restoration: "
            + intraday_orders._send_one(
                root, state, row, verdict, client, known, held, now, started
            )
            for row in rows
        ]


# The board's rows for decision-close restorations, in this timing's words: the
# shared board reads any FOMC order as one queued for the open.
def relabel(rows: list[dict], state: paper.PaperState, now: datetime) -> list[dict]:
    """Return `rows` with decision-close restorations described as such."""
    timed = {
        str(row.get("client_order_id")): row
        for row in state.pending
        if row.get("execution_timing") == DECISION_CLOSE
    }
    today = now.astimezone(NEW_YORK).date()
    out = []
    for shown in rows:
        row = timed.get(str(shown.get("client_order_id")))
        if row is None:
            out.append(shown)
            continue
        shown = dict(shown)
        execute_on = row.get("execute_on")
        day = (
            "Today"
            if execute_on == today.isoformat()
            else intraday_orders._day(execute_on)
        )
        shown["timing"] = DECISION_CLOSE
        shown["when"] = f"{day} · 3:45 PM, after the FOMC statement (FOMC risk rule)"
        queued = shown.get("status", "").startswith("Queued at the broker")
        if not row.get("sent") and queued:
            if not execute_on or execute_on > today.isoformat():
                shown["state"], shown["status"] = "planned", "Planned"
            elif execute_on < today.isoformat():
                shown["state"], shown["status"] = (
                    "missed",
                    "Not sent: its session ended before the order went out",
                )
            elif in_window(now, today):
                shown["state"], shown["status"] = (
                    "due",
                    "After the FOMC statement · market order due",
                )
            elif now < entry_timing.session_clock(today)["final"]:
                shown["state"], shown["status"] = (
                    "waiting",
                    "After the FOMC statement · market order at 3:45 PM ET",
                )
            else:
                shown["state"], shown["status"] = (
                    "missed",
                    "Not sent: the session closed before the order went out",
                )
        out.append(shown)
    return out
