"""Paper orders sent on the board's rule: a 1% dip or pop, else the close.

Since 2026-09-30 the paper account trades exactly what the Stock rankings
board shows, on the board's clock. The operator asked for that in so many
words ("the live paper trading account consistent with the realtime stock
suggestions"), and chose the board's timing over the old next-open one.

* WHAT is traded is unchanged: `paper.plan` still makes the night's basket
  (the reset, the rotation, the entries, the deferred buys, the redeploy).
* WHEN it trades is the board's `dip_or_close` rule, read through the same
  `entry_timing.timing` function the board reads, so the two cannot disagree:
  - a buy goes to the market on the first completed 15-minute bar of the
    session whose close is at or under the session's open less 1%, and a
    sell or trim on the first one at or over the open plus 1%;
  - with no such bar, the order goes to the market from the last 15-minute
    candle before the close (3:45 PM ET on a 4:00 close; `entry_timing.
    FINAL_LEAD`), the last balancer run inside the session. Until 2026-10-02
    it went in market-on-close at 3:30 PM, but the Alpaca paper venue expired
    8 of the 9 such buys unfilled at 4:00 PM while every market order filled,
    leaving 4-5% of the account idle for a session each time
    (`docs/research/paper-moc-fills-2026-10-02.md`). A plain market order
    fifteen minutes before the close is the nearest order the paper venue
    reliably fills.

Measured on the `/4` policy's own orders the rule earned -0.1 bp a session
(t -0.2) on 2016-2023 and +1.0 bp (t 2.2) on 2024-2026 against the next open
(`docs/research/execution-timing-2026-09-27.md`): the timing is neutral, and
it was adopted for consistency, not for an edge.

The nightly (`market_daily`) writes each ordinary order down with
`execution_timing = INTRADAY_TIMING` and the session it executes on, and sends
nothing. The balancer calls `send_due` on every 15-minute candle, right after
it latches the candle. FOMC event orders keep their own next-open treatment
(`event_execution.py`) and never pass through here.

`board_orders` is the same state read back for the dashboard: every order
with its size, why, when, and what has happened to it, worded once here so
the board, the ticker panel and the chart say the same thing.

An explicitly tagged `bounded-execution/1` candidate instead uses a qualified
raw bid/ask quote and an IOC limit. The active nightly does not tag orders;
its existing behavior remains unchanged. Candidate budgets must be supplied
before evaluation; only candidate rows request the existing bid/ask reader.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from backend.agents.trading.desk import execution_evidence, paper
from backend.market import bounded_execution, calendar, entry_timing, execution_quotes

# The off switch. True: the nightly writes its ordinary orders down for the
# balancer to send on the board's rule. False: the nightly queues them itself
# for the next open (buys) and the next close (sells), as before 2026-09-30,
# and the board shows them that way.
INTRADAY_EXECUTION = True
# The execution timing written on every ordinary order the nightly plans.
INTRADAY_TIMING = "dip_or_close"
# The way an order is sent from here: a day market order. MOC is kept only
# to read back rows sent market-on-close before 2026-10-05.
MARKET = "market"
MOC = "moc"
NEW_YORK = calendar.NEW_YORK

# The broker statuses of an order that has been accepted and may still fill.
_WORKING = ("new", "accepted", "pending_new", "accepted_for_bidding", "held", "open")
_CANCELLED = ("canceled", "cancelled", "expired", "done_for_day", "replaced")
_REJECTED = ("rejected", "suspended", "stopped")


# The next regular XNYS session strictly after `day`, on the reviewed
# calendar, or None when the calendar does not cover it (fail closed).
def next_session(day: date) -> date | None:
    """Return the first reviewed session after `day`, else None."""
    years, sessions = calendar.reviewed_sessions()
    if day.year not in years:
        return None
    following = np.busday_offset(
        np.datetime64(day, "D"), 1, roll="backward", busdaycal=sessions
    ).astype(object)
    return following if following.year in years else None


# The ordinary orders planned for `today` that have not been sent yet.
def due(state: paper.PaperState, today: date) -> list[dict]:
    """Return the pending intraday rows that execute on `today`, unsent."""
    return [
        row
        for row in state.pending
        if row.get("execution_timing") == INTRADAY_TIMING
        and not row.get("event_id")
        and row.get("execute_on") == today.isoformat()
        and not row.get("sent")
    ]


# What one row should do at `now`: send a market order (its level was
# reached, or the close window's last candle has come), or nothing yet.
# Explicit candidate contracts use bounded execution instead; malformed
# contracts never fall back to the legacy rule.
def decide(
    row: dict, latch_row: dict | None, quote: dict | None, now: datetime, today: date
) -> dict[str, Any]:
    """Return legacy timing or an opt-in IOC decision with its execution guard."""
    if "execution_policy" in row and row.get("side") not in ("buy", "sell"):
        return {
            "send": None,
            "timed": {},
            "guard": {"state": "invalid_contract", "reason": "Invalid order side"},
        }
    timed = entry_timing.timing(latch_row, quote, str(row.get("side")), now, today)
    if "execution_policy" in row:
        guard = bounded_execution.evaluate(
            row, timed, (quote or {}).get("execution_quote"), now, today
        )
        return {"send": guard["send"], "timed": timed, "guard": guard}
    state = timed["state"]
    send: str | None = None
    if state == entry_timing.TRIGGERED:
        send = MARKET
    elif state == entry_timing.CLOSE:
        clock = entry_timing.session_clock(today)
        if clock["final"] <= now < clock["close"]:
            send = MARKET
    return {"send": send, "timed": timed}


# Submit the decided order type, preserving an explicit candidate's price bound.
def _submit(client, row: dict, how: str, qty: int, verdict: dict) -> dict:
    """Submit `row` as a day market order (or a candidate's IOC limit)."""
    symbol = str(row["symbol"])
    side = str(row["side"])
    cid = str(row["client_order_id"])
    if how == bounded_execution.LIMIT_IOC:
        return client.submit_limit_ioc(
            symbol, qty, side, verdict["guard"]["limit_price"], cid
        )
    return client.submit_market(symbol, qty, side, cid)


# The part of a timing the row keeps as the record of why it was sent.
def _why_sent(timed: dict[str, Any], how: str, now: datetime) -> dict[str, Any]:
    """Return the sent block written onto a row: when, how, and the level."""
    return {
        "at": now.isoformat(timespec="seconds"),
        "how": how,
        "state": timed.get("state"),
        "open": timed.get("open"),
        "level": timed.get("level"),
        "trigger_bar": timed.get("trigger_bar"),
        "trigger_price": timed.get("trigger_price"),
    }


# Send every order that is due on this candle, under the paper lock.
#
# For each unsent row executing today, `decide` reads the latch and the
# candle's quote. A row that is due is written down as being sent before the
# request leaves (so a crash in between is visible), then sent, then its
# broker acknowledgement is recorded. An order the broker already holds under
# the row's id (an earlier run that died before recording) is adopted, not
# sent twice. Nothing is sent unless the broker's own clock says the market is
# open: an order sent after the close would queue for the NEXT session. A sell
# is never sent for more shares than the account holds.
# An explicit timing reader can replace ordinary pre-deadline timing in a
# private replay; the default, bounded IOC contracts and final clock are retained.
# Returns the log lines.
def send_due(
    root: Path | str,
    snapshot: dict | None,
    now: datetime,
    client_factory: Callable[[], Any],
    *,
    quote_reader: Callable | None = None,
    timing_reader: Callable | None = None,
) -> list[str]:
    """Send the orders the board's timing makes due now; return log lines."""
    if now.tzinfo is None:
        raise ValueError("send_due requires a timezone-aware now")
    today = now.astimezone(NEW_YORK).date()
    root = Path(root)
    with paper.transaction(root):
        return _send_due_locked(
            root, snapshot, now, today, client_factory, quote_reader, timing_reader
        )


# The due rows that `decide` says to send on this candle, with its verdict.
def _ready(
    rows: list[dict],
    root: Path,
    snapshot: dict | None,
    now: datetime,
    today: date,
    timing_reader: Callable | None = None,
) -> list[tuple[dict, dict[str, Any]]]:
    """Return [(row, verdict)] for the rows to send now."""
    latch = entry_timing.load(root, today)
    quotes = (snapshot or {}).get("quotes") or {}
    ready = []
    for row in rows:
        symbol = str(row.get("symbol"))
        custom = False
        if timing_reader is not None and "execution_policy" not in row:
            clock = entry_timing.session_clock(today)
            custom = clock["open"] <= now < clock["final"]
        reader = timing_reader if custom else decide
        args = (
            row,
            entry_timing.row_for(latch, symbol, today),
            quotes.get(symbol),
            now,
            today,
        )
        verdict = reader(*(deepcopy(args) if custom else args))
        if custom and (
            not isinstance(verdict, dict)
            or "send" not in verdict
            or verdict["send"] not in (None, MARKET)
            or not isinstance(verdict.get("timed"), dict)
            or not isinstance(verdict["timed"].get("state"), str)
            or not verdict["timed"]["state"]
        ):
            raise ValueError("Timing reader requires an explicit ordinary verdict")
        if verdict["send"]:
            ready.append((row, verdict))
    return ready


# The body of `send_due`, run while the paper state is locked.
def _send_due_locked(
    root: Path,
    snapshot: dict | None,
    now: datetime,
    today: date,
    client_factory: Callable[[], Any],
    quote_reader: Callable | None,
    timing_reader: Callable | None = None,
) -> list[str]:
    """Send due rows with the paper lock held; return log lines."""
    from backend.market import alpaca_trading

    state = paper.load_state(root)
    rows = due(state, today)
    snapshot, now = qualify_snapshot(rows, snapshot, now, quote_reader)
    started = time.monotonic()
    _observe_bounded(root, state, rows, snapshot, now, today)
    ready = _ready(rows, root, snapshot, now, today, timing_reader)
    recovering = [r for r in rows if "execution_policy" in r and r.get("sending")]
    if not ready and not recovering:
        return []
    try:
        client = client_factory()
        market_open = bool((client.clock() or {}).get("is_open"))
        if not market_open and not recovering:
            return [
                "intraday orders: the broker reports the market closed; nothing sent"
            ]
        known = {
            str(o.get("client_order_id") or ""): o
            for o in client.orders_since(f"{today.isoformat()}T00:00:00Z") or []
        }
        held = {p.symbol: float(p.qty) for p in client.positions()}
    except (alpaca_trading.AlpacaTradingError, OSError, ValueError) as exc:
        return [f"intraday orders: broker unavailable ({exc}); nothing sent"]
    # Recover accepted attempts even if their price permission has since expired.
    recovered = []
    for row in recovering:
        cid = str(row["client_order_id"])
        if cid in known and not any(r is row for r, _ in ready):
            conflict = _adoption_error(row, known[cid])
            if conflict:
                row["send_error"] = conflict
                paper.save_state(root, state)
                recovered.append(f"{row['symbol']}: {conflict}")
                continue
            row["sent"] = {
                "at": row["sending"],
                "how": bounded_execution.LIMIT_IOC,
                "adopted": True,
            }
            row["execution"] = {
                **(row.get("execution") or {}),
                **execution_evidence.broker_evidence(known[cid]),
            }
            paper.save_state(root, state)
            recovered.append(f"{row['symbol']}: accepted IOC attempt recovered")
    if not market_open:
        return recovered + [
            "intraday orders: the broker reports the market closed; nothing sent"
        ]
    return recovered + [
        _send_one(root, state, row, verdict, client, known, held, now, started)
        for row, verdict in ready
    ]


# Fetch only missing candidate quotes; legacy orders make no additional data requests.
def qualify_snapshot(rows, snapshot, now, quote_reader=None):
    quotes = (snapshot or {}).get("quotes") or {}
    today = now.astimezone(NEW_YORK).date()
    symbols = set()
    for row in rows:
        if "execution_policy" not in row or row.get("sent"):
            continue
        symbol = str(row.get("symbol"))
        bar = quotes.get(symbol) or {}
        verdict = decide(row, None, bar, now, today)
        if "execution_quote" not in bar and verdict["guard"]["state"] in (
            "quote_unavailable",
            "waiting",
        ):
            symbols.add(symbol)
    if not symbols:
        return snapshot or {}, now
    started = time.monotonic()
    try:
        evidence = (quote_reader or execution_quotes.fetch)(sorted(symbols))
    except Exception:  # noqa: BLE001 - unavailable evidence must not expose credentials
        evidence = None
    result = bounded_execution.with_quotes(snapshot, evidence)
    return result, now + timedelta(seconds=max(0.0, time.monotonic() - started))


# Preserve every candidate opportunity, including blocked attempts, once per candle.
def _observe_bounded(root, state, rows, snapshot, now, today):
    latch = entry_timing.load(root, today)
    quotes = (snapshot or {}).get("quotes") or {}
    bucket = (
        now.astimezone(NEW_YORK)
        .replace(
            minute=now.astimezone(NEW_YORK).minute // 15 * 15,
            second=0,
            microsecond=0,
        )
        .isoformat()
    )
    changed = False
    for row in rows:
        if "execution_policy" not in row:
            continue
        execution = row.setdefault("execution", {})
        observations = execution.setdefault("bounded_observations", [])
        if any(o["bucket"] == bucket for o in observations):
            continue
        symbol = str(row.get("symbol"))
        verdict = decide(
            row,
            entry_timing.row_for(latch, symbol, today),
            quotes.get(symbol),
            now,
            today,
        )
        observations.append(
            {
                "bucket": bucket,
                "observed_at": now.isoformat(),
                "guard": verdict["guard"],
            }
        )
        execution["execution_policy"] = row["execution_policy"]
        changed = True
    if changed:
        paper.save_state(root, state)


# Send one due row, or adopt the order an earlier run already placed for it,
# saving the state around the request; return its log line.
def _send_one(
    root: Path,
    state: paper.PaperState,
    row: dict,
    verdict: dict[str, Any],
    client: Any,
    known: dict[str, dict],
    held: dict[str, float],
    now: datetime,
    started: float,
) -> str:
    """Send `row` as `verdict` says and record it on `state`; return a log line."""
    from backend.market import alpaca_trading

    cid = str(row["client_order_id"])
    how = verdict["send"]
    timed = verdict["timed"]
    line = f"{row['side']} {row['qty']} {row['symbol']} ({how}, {timed['state']})"
    if cid in known:
        # An earlier run sent it and stopped before writing that down.
        if conflict := _adoption_error(row, known[cid]):
            row["send_error"] = conflict
            paper.save_state(root, state)
            return f"{line}: not sent ({conflict})"
        # Record what the broker holds: a market-on-close order an older
        # build sent earlier in the session stays market-on-close on the board.
        held_how = MOC if known[cid].get("time_in_force") == "cls" else how
        row["sent"] = {**_why_sent(timed, held_how, now), "adopted": True}
        row["execution"] = {
            **(row.get("execution") or {}),
            **execution_evidence.broker_evidence(known[cid]),
        }
        paper.save_state(root, state)
        return f"{line}: already at the broker, recorded"
    qty = int(row.get("qty") or 0)
    if how == bounded_execution.LIMIT_IOC:
        try:
            qty, verdict, now = _prepare_bounded(
                row, verdict, client, known, held, now, started
            )
        except (alpaca_trading.AlpacaTradingError, OSError, ValueError) as exc:
            row["send_error"] = str(exc)
            paper.save_state(root, state)
            return f"{line}: not sent ({exc})"
    elif row.get("side") == "sell":
        qty = min(qty, int(math.floor(held.get(str(row["symbol"]), 0.0))))
    if qty <= 0:
        row["send_error"] = (
            "no shares to sell"
            if row.get("side") == "sell"
            else "no funded quantity"
            if how == bounded_execution.LIMIT_IOC
            else "no quantity"
        )
        paper.save_state(root, state)
        return f"{line}: not sent ({row['send_error']})"
    row["sending"] = now.isoformat(timespec="seconds")
    paper.save_state(root, state)
    try:
        response = _submit(client, row, how, qty, verdict)
    except alpaca_trading.AlpacaTradingError as exc:
        row["send_error"] = str(exc)
        # A failed response need not prove that the broker refused the request.
        known[cid] = {
            "symbol": row["symbol"],
            "side": row["side"],
            "qty": qty,
            "filled_qty": 0,
            "status": "pending_new",
            "limit_price": (verdict.get("guard") or {}).get("limit_price"),
            "_uncertain": True,
        }
        paper.save_state(root, state)
        status = (
            f"submission unconfirmed ({exc})"
            if how == bounded_execution.LIMIT_IOC
            else f"REFUSED {exc}"
        )
        return f"{line}: {status}"
    row["sent"] = {**_why_sent(timed, how, now), "qty": qty}
    row.pop("send_error", None)
    row["execution"] = {
        **(row.get("execution") or {}),
        **execution_evidence.broker_evidence(response),
    }
    if how == bounded_execution.LIMIT_IOC:
        # Reserve the maximum attempted cash/shares until the broker reconciles.
        known[cid] = {
            **response,
            "symbol": row["symbol"],
            "side": row["side"],
            "qty": qty,
            "filled_qty": 0,
            "limit_price": verdict["guard"]["limit_price"],
            "status": "pending_new",
        }
    else:
        # Later bounded rows must also reserve attempts made by the legacy policy.
        known[cid] = {
            **response,
            "symbol": row["symbol"],
            "side": row["side"],
            "qty": qty,
            "filled_qty": 0,
            "status": "pending_new",
        }
    paper.save_state(root, state)
    return f"{line}: sent"


# Adopt confirmed legacy orders or an IOC matching its bounded execution permission.
def _adoption_error(row, order):
    if order.get("_uncertain"):
        return "Submission remains unconfirmed"
    if "execution_policy" not in row:
        return None
    error = bounded_execution.contract_error(row, row.get("execution_policy"))
    if error:
        return error
    expected = {
        "symbol": row["symbol"],
        "side": row["side"],
        "type": "limit",
        "time_in_force": "ioc",
    }
    qty = bounded_execution.positive(order.get("qty"))
    price = bounded_execution.positive(order.get("limit_price"))
    cap = float(
        bounded_execution.limit_text(
            row["execution_policy"]["limit_price"], row["side"]
        )
    )
    protected = price is not None and (
        price <= cap if row["side"] == "buy" else price >= cap
    )
    if (
        any(order.get(k) != v for k, v in expected.items())
        or qty is None
        or qty > row["qty"]
        or not protected
    ):
        return "Broker order does not confirm this bounded attempt"
    return None


# Revalidate funds, reservations, price and expiry immediately before an IOC attempt.
def _prepare_bounded(row, verdict, client, known, held, now, started):
    row["execution"] = {
        **(row.get("execution") or {}),
        "execution_policy": row["execution_policy"],
    }
    qty = int(row["qty"])
    if row["side"] == "buy":
        try:
            cash = _bounded_cash(client, known)
        except (ValueError, OSError) as exc:
            raise ValueError(f"Cash unavailable: {exc}") from exc
        qty = min(qty, int(math.floor(cash / float(verdict["guard"]["limit_price"]))))
    else:
        qty = min(
            qty, int(math.floor(_bounded_shares(str(row["symbol"]), held, known)))
        )
    attempted_at = now + timedelta(seconds=max(0.0, time.monotonic() - started))
    guard = bounded_execution.evaluate(
        row,
        verdict["timed"],
        verdict["guard"].get("quote"),
        attempted_at,
        now.astimezone(NEW_YORK).date(),
    )
    row["execution"]["bounded_attempt"] = {
        **guard,
        "approved_at": attempted_at.isoformat(),
    }
    if not guard["send"]:
        raise ValueError(guard["reason"])
    return qty, {**verdict, "guard": guard}, attempted_at


# Reserve other working buys against actual cash, never promised sale proceeds.
def _bounded_cash(client, known: dict) -> float:
    account = client.account()
    cash, buying_power = float(account.cash), float(account.buying_power)
    if not math.isfinite(cash) or not math.isfinite(buying_power):
        raise ValueError("Non-finite account funds")
    reserved = 0.0
    for order in known.values():
        status = str(order.get("status") or "").lower()
        if order.get("side") != "buy" or status in _CANCELLED + _REJECTED + ("filled",):
            continue
        qty = _remaining(order)
        price = bounded_execution.positive(order.get("limit_price"))
        if not math.isfinite(qty) or qty < 0 or (qty > 0 and price is None):
            raise ValueError("Working buy reservation is unknown")
        reserved += max(0, qty) * (price or 0)
    return max(0.0, min(cash - reserved, buying_power))


# Reserve working sells so another row cannot sell the same long shares twice.
def _bounded_shares(symbol, held, known):
    shares = float(held.get(symbol, 0))
    if not math.isfinite(shares) or shares < 0:
        raise ValueError("Held shares are unknown")
    for order in known.values():
        status = str(order.get("status") or "").lower()
        if (
            order.get("symbol") != symbol
            or order.get("side") != "sell"
            or status in _CANCELLED + _REJECTED + ("filled",)
        ):
            continue
        remaining = _remaining(order)
        if not math.isfinite(remaining) or remaining < 0:
            raise ValueError("Working sell reservation is unknown")
        shares -= remaining
    return max(0.0, shares)


# Read a working order's remaining quantity without treating missing data as zero.
def _remaining(order):
    qty = bounded_execution.positive(order.get("qty"))
    try:
        filled = float(order.get("filled_qty", 0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Working order quantity is unknown") from exc
    if qty is None or not math.isfinite(filled) or not 0 <= filled <= qty:
        raise ValueError("Working order quantity is unknown")
    return qty - filled


# ----------------------------------------------------------------------------
# The same orders read back for the dashboard.
# ----------------------------------------------------------------------------

# Each leg of the nightly plan by the reason text `paper.plan` writes on it,
# in the words a trader uses. The reasons are this repository's own strings;
# `test_every_plan_leg_has_a_plain_reason` pins them, so a reworded reason
# fails a test instead of falling through to the raw text.
_LEGS: tuple[tuple[str, str, str], ...] = (
    ("rebalance to ", "reset", "Reset to the {target} target"),
    ("leaves the book", "reset-exit", "Reset: no longer in the book"),
    ("graded ", "exit", "Exit: the grade fell below A"),
    ("redeploying a downgraded name", "reinvest", "Reinvest an exit's proceeds"),
    ("price entry", "entry", "Breakout entry (20-day band)"),
    ("deferred buy", "deferred", "Finish last session's buy (cash was short)"),
    ("redeploy:", "redeploy", "Put idle cash to work, toward the target"),
)


# The leg a row belongs to and one plain sentence for why it trades.
def why(row: dict) -> tuple[str, str]:
    """Return (leg, plain reason) for a pending or journal row."""
    reason = str(row.get("reason") or "")
    if row.get("event_id"):
        return "event", "FOMC risk rule"
    for prefix, leg, words in _LEGS:
        if reason.startswith(prefix):
            if leg == "reset":
                try:
                    target = float(reason[len(prefix) :])
                    return leg, words.format(target=f"{target:.1%}")
                except ValueError:
                    return leg, "Reset to the target weight"
            if leg == "exit":
                # "graded B; the desk wants the money elsewhere"
                letter = reason[len(prefix) :].split(";")[0].strip()
                return leg, f"Exit: the grade fell to {letter}" if letter else words
            return leg, words
    return "plan", reason or "Nightly plan"


# How a row is executed: the board's intraday rule, or one of the older
# conventions an order planned before the switch still carries.
def timing_of(row: dict) -> str:
    """Return "dip_or_close", "event", "next_open" or "close" for a row."""
    if row.get("execution_timing") == INTRADAY_TIMING:
        return INTRADAY_TIMING
    if row.get("event_id") or row.get("priority"):
        return "event"
    if row.get("execution_timing") == "next_open" or row.get("side") == "buy":
        return "next_open"
    return "close"


# A New York wall-clock time as the board writes it: 10:15 AM.
def _clock(value: object) -> str | None:
    """Return h:mm AM/PM in New York for an ISO instant, else None."""
    try:
        instant = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if instant.tzinfo is None:
        return None
    local = instant.astimezone(NEW_YORK)
    meridiem = "AM" if local.hour < 12 else "PM"
    return f"{local.hour % 12 or 12}:{local.minute:02d} {meridiem}"


# A session date as the board writes it: Wed Sep 30.
def _day(value: str | None) -> str:
    """Return e.g. "Wed Sep 30" for an ISO date, else the input."""
    try:
        return date.fromisoformat(str(value)).strftime("%a %b %-d")
    except (TypeError, ValueError):
        return str(value or "")


# Dollars as a trader reads them.
def _money(value: float) -> str:
    """Return $1,234.56."""
    return f"${value:,.2f}"


# The price a buy waits for, floored to the cent, or a sell's, ceiled: the
# same rounding the board's timing sentence uses, so "at or under $X" is true.
def _level_text(level: float | None, side: str) -> str | None:
    """Return the level in dollars, or None without one."""
    if level is None or not math.isfinite(level):
        return None
    cents = level * 100.0
    cents = math.floor(cents + 1e-6) if side == "buy" else math.ceil(cents - 1e-6)
    return _money(cents / 100.0)


# What the rule waits for, in one line: the level once the open is known,
# otherwise the rule itself.
def rule_text(
    side: str, opened: float | None = None, level: float | None = None
) -> str:
    """Return the rule's sentence, with the level once the open is known.

    "15-min close ≤ $40.55 (1% under the $40.96 open), else at the close" for
    a buy with its open; "15-min close 1% under the open, else at the close"
    before the open is known. A sell reads ≥ and over.
    """
    way = "under" if side == "buy" else "over"
    sign = "≤" if side == "buy" else "≥"
    pct = f"{entry_timing.LEVEL:.0%}"
    shown = _level_text(level, side)
    if opened is not None and shown is not None:
        return (
            f"15-min close {sign} {shown} ({pct} {way} the {_money(opened)} open), "
            "else at the close"
        )
    return f"15-min close {pct} {way} the open, else at the close"


# Parse nonnegative share quantities without treating missing evidence as zero.
def _quantity(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


# The broker's view of one order, reduced to what the board says about it.
def _broker_state(order: dict | None) -> dict[str, Any] | None:
    """Return {status, filled_qty, filled_price, filled_at, tif} or None."""
    if not order:
        return None
    status = str(order.get("status") or "").lower()
    try:
        filled_qty = float(order.get("filled_qty") or 0)
    except (TypeError, ValueError):
        filled_qty = 0.0
    try:
        filled_price = float(order.get("filled_avg_price") or 0)
    except (TypeError, ValueError):
        filled_price = 0.0
    return {
        "status": status,
        "qty": _quantity(order.get("qty")),
        "filled_qty": filled_qty,
        "filled_price": filled_price if filled_price > 0 else None,
        "filled_at": order.get("filled_at"),
        "tif": order.get("time_in_force"),
    }


# The state and the sentence for a row the broker has an answer about.
def _from_broker(row: dict, broker: dict, qty: int) -> tuple[str, str] | None:
    """Return (state, status sentence) from the broker's order, or None."""
    side = str(row.get("side"))
    verb = "Bought" if side == "buy" else "Sold"
    status = broker["status"]
    filled = broker["filled_qty"]
    price = broker["filled_price"]
    at = _clock(broker.get("filled_at"))
    fill = f" @ {_money(price)}" if price else ""
    when = f" · {at}" if at else ""
    if status == "filled" or (filled >= qty > 0):
        return "filled", f"{verb} {filled:,.6f}".rstrip("0").rstrip(
            "."
        ) + f"{fill}{when}"
    if filled > 0:
        if status in _CANCELLED + _REJECTED:
            return (
                "cancelled" if status in _CANCELLED else "rejected",
                f"{verb} {filled:g} of {qty:g}{fill}{when}; the rest did not fill",
            )
        return "partial", f"{verb} {filled:g} of {qty:g}{fill} so far"
    if status in _REJECTED:
        return "rejected", "Not filled: the broker rejected the order"
    if status in _CANCELLED:
        if row.get("hold_requested"):
            return "held", "Held: it opened above the last close"
        if status == "expired" and broker.get("tif") == "cls":
            # The paper venue's failure mode for market-on-close orders.
            return "cancelled", (
                "Not filled: the broker expired the market-on-close order at the close"
            )
        return "cancelled", f"Not filled: the order was {status.replace('_', ' ')}"
    if status in _WORKING or status.startswith("pending"):
        return None
    return None


# The one word for an order: BUY, SELL (the position goes: an exit or a
# name leaving the book) or TRIM (a reduction that keeps the name: a reset
# trim, an FOMC cut). An unrecognised sell is read against the position it
# started from, which is the shares held now plus any already sold by it.
def _action(side: str, leg: str, qty: int, held: float, broker: dict | None) -> str:
    """Return "BUY", "SELL" or "TRIM"."""
    if side == "buy":
        return "BUY"
    if leg in ("exit", "reset-exit"):
        return "SELL"
    if leg in ("reset", "event"):
        return "TRIM"
    sold = (_broker_state(broker) or {}).get("filled_qty") or 0.0
    return "TRIM" if 0 < qty < held + sold else "SELL"


# One pending row as the board shows it.
#
# `broker` is the broker's order under the row's id (None when unknown),
# `latch` today's entry-timing latch, `quote` the candle's quote for the name,
# `held` the shares the account holds, `price` the name's latest price and
# `equity` the account's. The row says what (BUY, SELL or TRIM, and its
# size in shares, dollars and percent of the account), why (the plan leg in
# plain words), when (the execution rule for its session) and what has
# happened (planned, waiting, sent, filled, ...). Every sentence the board,
# the ticker panel and the chart print about an order comes from here.
def board_row(
    row: dict,
    *,
    broker: dict | None,
    latch: dict | None,
    quote: dict | None,
    held: float,
    price: float | None,
    equity: float | None,
    now: datetime,
) -> dict[str, Any]:
    """Return the dashboard's view of one planned or working order."""
    side = str(row.get("side") or "")
    symbol = str(row.get("symbol") or "")
    qty = int(row.get("qty") or 0)
    known = _broker_state(broker)
    submitted = known["qty"] if known else None
    if submitted is None:
        submitted = _quantity((row.get("sent") or {}).get("qty"))
    leg, reason = why(row)
    timing = timing_of(row)
    today = now.astimezone(NEW_YORK).date()
    execute_on = row.get("execute_on")
    if not execute_on:
        # Planned before execute_on existed: the next session after its decision.
        try:
            decided = date.fromisoformat(str(row.get("session")))
            upcoming = next_session(decided)
            execute_on = upcoming.isoformat() if upcoming else None
        except ValueError:
            execute_on = None
    reference = (row.get("execution") or {}).get("reference_price")
    shown_price = price if price and price > 0 else reference
    notional = qty * float(shown_price) if shown_price else None
    action = _action(side, leg, qty, held, broker)
    out: dict[str, Any] = {
        "client_order_id": row.get("client_order_id"),
        "symbol": symbol,
        "side": side,
        "action": action,
        "qty": qty,
        "planned_qty": qty,
        "submitted_qty": submitted,
        "remaining_qty": None,
        "quantity_basis": "planned",
        "terminal": None,
        "price": float(shown_price) if shown_price else None,
        "notional": notional,
        "weight": (notional / equity) if notional and equity else None,
        "leg": leg,
        "why": reason,
        "reason": row.get("reason"),
        "timing": timing,
        "decided": row.get("session"),
        "execute_on": execute_on,
        "open": None,
        "level": None,
        "sent_at": (row.get("sent") or {}).get("at"),
        "sent_how": (row.get("sent") or {}).get("how"),
        "filled_qty": None,
        "filled_price": None,
        "filled_at": None,
    }
    sent = row.get("sent") or {}
    if sent.get("open") is not None and sent.get("level") is not None:
        out["open"] = sent["open"]
        out["level"] = sent["level"]
    state_word, sentence = _status(
        row,
        out,
        broker,
        latch,
        quote,
        submitted if submitted is not None else qty,
        timing,
        execute_on,
        today,
        now,
    )
    out["state"] = state_word
    out["status"] = sentence
    # A fill is historical execution value; an unfilled order is only an
    # estimate at the displayed quote. Never price an old fill at today's quote.
    terminal = state_word in ("filled", "cancelled", "rejected", "held", "missed")
    out["terminal"] = terminal if terminal or known or not row.get("sent") else None
    if terminal:
        out["remaining_qty"] = 0.0
    elif known and submitted is not None:
        out["remaining_qty"] = max(0.0, submitted - known["filled_qty"])
    if terminal and known and known["filled_qty"] > 0:
        out["qty"] = known["filled_qty"]
        out["quantity_basis"] = "filled"
        out["price"] = known["filled_price"]
    elif submitted is not None:
        out["qty"] = submitted
        out["quantity_basis"] = "submitted"
    out["notional"] = out["qty"] * out["price"] if out["price"] else None
    out["weight"] = (
        out["notional"] / equity if out["notional"] is not None and equity else None
    )
    out["when"] = _when(side, timing, execute_on, today, out)
    if "execution_policy" in row:
        out["execution_policy"] = (
            row["execution_policy"]
            if bounded_execution.contract_error(row, row["execution_policy"]) is None
            else {"version": bounded_execution.VERSION, "valid": False}
        )
        out["when"] = "Bounded IOC limit; no market fallback"
    return out


# The rule an order executes under, for its session, in one line.
def _when(
    side: str, timing: str, execute_on: str | None, today: date, out: dict
) -> str:
    """Return the session and the rule, e.g. "Wed Sep 30 · on a 15-min close ..."."""
    day = (
        "Today"
        if execute_on == today.isoformat()
        else _day(execute_on)
        if execute_on
        else "Next session"
    )
    if timing == INTRADAY_TIMING:
        return f"{day} · {rule_text(side, out.get('open'), out.get('level'))}"
    if timing == "event":
        return f"{day} · at the open (FOMC risk rule)"
    if timing == "next_open":
        return f"{day} · at the open"
    return f"{day} · at the close, held instead if it opens above the last close"


# The state word and sentence for one row: what its own record and the
# broker say first, then what the clock and the latch say for its session.
def _status(
    row: dict,
    out: dict,
    broker: dict | None,
    latch: dict | None,
    quote: dict | None,
    qty: int,
    timing: str,
    execute_on: str | None,
    today: date,
    now: datetime,
) -> tuple[str, str]:
    """Return (state, sentence) for one row and fill `out`'s price fields."""
    recorded = _recorded_status(row, out, broker, qty, timing)
    if recorded:
        return recorded
    if not execute_on or execute_on > today.isoformat():
        day = _day(execute_on) if execute_on else "the next session"
        return "planned", f"Planned for {day}" if not execute_on else "Planned"
    if execute_on < today.isoformat():
        return "missed", "Not sent: its session ended before the order went out"
    return _clock_status(row, out, latch, quote, today, now)


# What a row's record and the broker's answer say about it, or None when the
# row has not reached the broker yet: held by the green-open rule, filled or
# not by the broker, refused, queued by the nightly (older conventions), or
# sent by the intraday leg and still working.
def _recorded_status(
    row: dict, out: dict, broker: dict | None, qty: int, timing: str
) -> tuple[str, str] | None:
    """Return (state, sentence) from the record and the broker, else None."""
    if row.get("status") == paper.SKIPPED:
        # The green-open rule cancelled an older closing sell and held the name.
        return "held", "Held instead: it opened above the last close"
    sent = row.get("sent") or {}
    known = _broker_state(broker)
    if known:
        out["filled_qty"] = known["filled_qty"]
        out["filled_price"] = known["filled_price"]
        out["filled_at"] = known["filled_at"]
        answered = _from_broker(row, known, qty)
        if answered:
            return answered
    if row.get("send_error") and not sent:
        return "problem", f"Not sent: {row['send_error']}"
    if timing == "close":
        # Orders planned before the switch were queued by the nightly itself.
        return "queued", (
            "Queued at the broker · sells at the close, held instead if it opens "
            "above the last close"
        )
    if timing == "event":
        return "queued", "Queued at the broker · FOMC order, fills at the open"
    if timing == "next_open":
        return "queued", "Queued at the broker · fills at the open"
    if not (sent or known):
        return None
    at = _clock(sent.get("at")) if sent else None
    stamp = f" {at}" if at else ""
    how = sent.get("how") or (MOC if known and known.get("tif") == "cls" else MARKET)
    label = {
        bounded_execution.LIMIT_IOC: "IOC limit; fill unconfirmed",
        MOC: "market-on-close",
    }.get(how, "market order")
    words = f"Sent{stamp} · {label}"
    return "sent", words if known else f"{words} · broker status unavailable"


# What the board's clock says about an unsent row executing today, from the
# same `entry_timing.timing` the balancer sends on.
def _clock_status(
    row: dict,
    out: dict,
    latch: dict | None,
    quote: dict | None,
    today: date,
    now: datetime,
) -> tuple[str, str]:
    """Return (state, sentence) for an unsent row on its own session."""
    side = str(row.get("side") or "")
    symbol = str(row.get("symbol") or "")
    verdict = decide(row, entry_timing.row_for(latch, symbol, today), quote, now, today)
    timed = verdict["timed"]
    if "guard" in verdict:
        guard = verdict["guard"]
        out["execution_guard"] = guard
        state = (
            "due"
            if verdict["send"]
            else "missed"
            if guard["state"] in ("expired", "closed")
            else "waiting"
        )
        return state, guard["reason"]
    out["open"] = timed.get("open")
    out["level"] = timed.get("level")
    state = timed["state"]
    clock = entry_timing.session_clock(today)
    if state == entry_timing.PRE_OPEN:
        if now >= clock["open"] + entry_timing.BAR:
            return "planned", "Waiting for today's opening price"
        return "planned", "Waiting for the 9:30-9:45 AM bar to set the open"
    if state == entry_timing.WAITING:
        shown = _level_text(timed.get("level"), side)
        cutoff = entry_timing._clock(clock["cutoff"])
        return "waiting", f"Waiting for {shown} or the close ({cutoff} window)"
    if state == entry_timing.TRIGGERED:
        return "due", f"Level hit: {_trigger(timed)} · order due"
    if state == entry_timing.CLOSE:
        if now < clock["final"]:
            final = entry_timing._clock(clock["final"])
            return "waiting", f"Close window · market order at {final} ET"
        return "due", "Close window · market order due"
    return "missed", "Not sent: the session closed before the order went out"


# "the 10:15 AM 15-min close $98.90": the bar that reached the level, named by
# the time it closed, as entry_timing's own sentence names it.
def _trigger(timed: dict[str, Any]) -> str:
    """Return the trigger bar's close time and price, as the board says it."""
    try:
        started = datetime.fromisoformat(str(timed.get("trigger_bar")))
        ended = _clock((started + entry_timing.BAR).isoformat())
    except (TypeError, ValueError):
        ended = None
    price = timed.get("trigger_price")
    shown = f" ({_money(float(price))})" if price else ""
    return f"the {ended} close{shown}" if ended else f"a 15-min close{shown}"


# The rows the board lists: every pending row, and the closing sells of the
# same decision the green-open rule held instead (those leave `pending` for the
# journal the moment they are held, and a SELL vanishing without a word is
# exactly the confusion the board exists to remove).
def _shown_rows(state: paper.PaperState) -> list[dict]:
    """Return the pending rows plus the same decision's held sells."""
    sessions = {str(r.get("session") or "") for r in state.pending}
    latest = (
        max(sessions)
        if sessions
        else max((str(e.get("session") or "") for e in state.journal), default="")
    )
    held = [
        e
        for e in state.journal
        if e.get("status") == paper.SKIPPED and str(e.get("session") or "") == latest
    ]
    return list(state.pending) + held


# Every order the dashboard should show, in the order a trader reads them:
# the ones still to happen first, then the finished ones, largest first.
def board_orders(
    state: paper.PaperState,
    *,
    broker_orders: list[dict] | None,
    latch: dict | None,
    quotes: dict | None,
    held: dict[str, float],
    prices: dict[str, float],
    equity: float | None,
    now: datetime,
) -> list[dict[str, Any]]:
    """Return `board_row` for every order of the paper state the board lists."""
    by_id = {
        str(o.get("client_order_id") or ""): o
        for o in broker_orders or []
        if o.get("client_order_id")
    }
    rows = [
        board_row(
            row,
            broker=by_id.get(str(row.get("client_order_id") or "")),
            latch=latch,
            quote=(quotes or {}).get(str(row.get("symbol"))),
            held=float(held.get(str(row.get("symbol")), 0.0)),
            price=prices.get(str(row.get("symbol"))),
            equity=equity,
            now=now,
        )
        for row in _shown_rows(state)
    ]
    finished = (
        "filled",
        "partial",
        "cancelled",
        "rejected",
        "held",
        "missed",
        "problem",
    )
    return sorted(
        rows,
        key=lambda r: (r["state"] in finished, -(r["notional"] or 0.0), r["symbol"]),
    )
