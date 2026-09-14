"""An isolated forward paper ledger following the dashboard's eligibility gates.

This is a local simulation, not an Alpaca account. Each observation contains its
complete resulting state, so a crash cannot separate a fill from its cash debit.
"""

import fcntl
import hashlib
import json
import math
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from backend.market import (
    decision_view,
    desk_freshness,
    event_status,
    forward_actions,
    holdings,
)

VERSION = "board-paper/2"
SLIPPAGE = 0.001  # Additional 10 bp per side beyond the observed bid/ask.


# Write one complete state atomically without overwriting an earlier observation.
def append(folder, row):
    content = json.dumps(row, sort_keys=True, allow_nan=False, indent=2)
    digest = hashlib.sha256(content.encode()).hexdigest()
    descriptor, name = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, folder / f"{row['sequence']:08d}-{digest}.json")
    finally:
        os.unlink(name)
    return row


# Read the last complete state; malformed evidence fails closed instead of resetting.
def latest(root):
    folder = root / "desk/board-paper"
    paths = sorted(folder.glob("*.json"))
    return json.loads(paths[-1].read_text()) if paths else None


# Start an explicitly requested new forward run without touching either real account.
def initialize(root, capital=100_000.0, now=None):
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("Positive finite paper capital required")
    folder = root / "desk/board-paper"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if latest(root) is not None:
            raise ValueError("A forward run already exists; archive it explicitly")
        stamp = (now or datetime.now(UTC)).isoformat()
        return append(
            folder,
            {
                "version": VERSION,
                "sequence": 0,
                "started_at": stamp,
                "as_of": stamp,
                "initial_capital": capital,
                "cash": capital,
                "equity": capital,
                "receivables": 0.0,
                "positions": {},
                "pending": {},
                "fills": [],
                "bar": None,
                "status": "Started in USD",
                "decisions": {},
            },
        )


# Apply only previously observed intents that remain eligible at a later quote.
def transition(state, decisions, research, now):
    positions = {ticker: dict(row) for ticker, row in state["positions"].items()}
    cash = state["cash"]
    fills = []
    targets = research.get("targets") or {}
    rows = decisions["rows"]
    deadline = desk_freshness.timestamp(research.get("valid_until"))
    valid = research.get("status") == "available" and deadline and now < deadline
    valid = valid and not research.get("event_paused")
    valid = valid and all(math.isfinite(w) and 0 <= w <= 1 for w in targets.values())
    valid = valid and sum(targets.values()) <= 1.000001
    eligible = {}
    for ticker, row in rows.items():
        until = desk_freshness.timestamp(row.get("valid_until"))
        if (
            valid
            and until
            and now < until
            and row["quote"].get("eligible")
            and row["action"] in ("Buy eligible", "Reduce")
            and ticker in targets
        ):
            eligible[ticker] = {"action": row["action"], "weight": targets[ticker]}
    equity = (
        cash
        + state["receivables"]
        + sum(p["shares"] * p["mark"] for p in positions.values())
    )
    buy_cash = cash
    # Sales cannot fund buys during the same observation.
    for ticker, intent in sorted(
        state["pending"].items(), key=lambda item: item[1]["action"] != "Reduce"
    ):
        current = eligible.get(ticker)
        if not current or current["action"] != intent["action"]:
            continue
        quote = rows[ticker]["quote"]
        at = desk_freshness.timestamp(quote.get("at"))
        if not at or at <= desk_freshness.timestamp(state["as_of"]):
            continue
        old = positions.get(
            ticker,
            {
                "shares": 0,
                "entry_price": quote["ask"],
                "entry_date": now.date().isoformat(),
            },
        )
        buying = intent["action"] == "Buy eligible"
        weight = (
            min(intent["weight"], current["weight"])
            if buying
            else max(intent["weight"], current["weight"])
        )
        price = (
            quote["ask"] * (1 + SLIPPAGE) if buying else quote["bid"] * (1 - SLIPPAGE)
        )
        desired = math.floor(equity * weight / price)
        quantity = (
            max(0, desired - old["shares"])
            if buying
            else max(0, old["shares"] - desired)
        )
        quantity = min(
            quantity, math.floor(quote["ask_size"] if buying else quote["bid_size"])
        )
        if buying:
            quantity = min(quantity, math.floor(buy_cash / price))
        if quantity <= 0:
            continue
        shares = old["shares"] + (quantity if buying else -quantity)
        cash += (-1 if buying else 1) * quantity * price
        if buying:
            buy_cash -= quantity * price
        if shares:
            entry = (
                (old["entry_price"] * old["shares"] + quantity * price) / shares
                if buying
                else old["entry_price"]
            )
            positions[ticker] = {
                **old,
                "shares": shares,
                "entry_price": entry,
                "mark": quote["bid"],
            }
        else:
            positions.pop(ticker, None)
        fills.append(
            {
                "ticker": ticker,
                "side": "buy" if buying else "sell",
                "shares": quantity,
                "price": price,
                "quote_at": quote["at"],
                "decision_at": state["as_of"],
            }
        )
    return {
        **state,
        "sequence": state["sequence"] + 1,
        "as_of": now.isoformat(),
        "bar": research.get("bar"),
        "cash": cash,
        "positions": positions,
        "equity": cash
        + state["receivables"]
        + sum(p["shares"] * p["mark"] for p in positions.values()),
        "pending": eligible,
        "fills": fills,
        "decisions": rows,
        "policy_sha256": research.get("policy_sha256"),
        "status": "Observed dashboard gates",
    }


# Apply newly observed ex-date actions once before marking an overnight account.
def roll_overnight(root, state, now):
    start = forward_actions.session(state["as_of"])
    end = forward_actions.session(now.isoformat())
    if not state["positions"] or start == end:
        return
    actions, _ = forward_actions.current(root, state["positions"], start, now)
    shares = {ticker: p["shares"] for ticker, p in state["positions"].items()}
    state["receivables"] += forward_actions.apply(shares, start, end, actions)
    for ticker, quantity in shares.items():
        state["positions"][ticker]["entry_price"] *= (
            state["positions"][ticker]["shares"] / quantity
        )
        state["positions"][ticker]["shares"] = quantity


# Observe one fresh candle using the same planner as the personal dashboard.
def observe(root, record, snapshot, research, now=None):
    folder = root / "desk/board-paper"
    if not folder.exists():
        return None
    live_clock = now is None
    now = now or datetime.now(UTC)
    with (folder / "state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = latest(root)
        if state is None or state["bar"] == research.get("bar"):
            return state
        if (
            research.get("status") != "available"
            or desk_freshness.describe(snapshot, now)["stale"]
        ):
            return state
        previous = hashlib.sha256(
            json.dumps(state, sort_keys=True).encode()
        ).hexdigest()
        policy = hashlib.sha256(
            (str(research.get("policy_sha256")) + VERSION).encode()
            + Path(__file__).read_bytes()
            + Path(decision_view.__file__).read_bytes()
        ).hexdigest()
        if state.get("execution_policy") != policy:
            state["pending"] = {}
        roll_overnight(root, state, now)
        # Network collection can outlive quote eligibility; recheck before trading.
        now = datetime.now(UTC) if live_clock else now
        if desk_freshness.describe(snapshot, now)["stale"]:
            return latest(root)
        for ticker, position in state["positions"].items():
            quote = (snapshot.get("quotes") or {}).get(ticker)
            if not quote:
                return state
            position["mark"] = quote["last"]
        held = [
            holdings.Holding(ticker, p["shares"], p["entry_price"], p["entry_date"])
            for ticker, p in state["positions"].items()
        ]
        equity = (
            state["cash"]
            + state["receivables"]
            + sum(p["shares"] * p["mark"] for p in state["positions"].values())
        )
        planned = event_status.for_planning(record, root)
        decisions = decision_view.build(
            planned,
            held,
            equity,
            snapshot,
            research.get("execution_quotes") or {},
            now,
            targets=research.get("targets"),
        )
        result = transition(state, decisions, research, now)
        result["previous_sha256"] = previous
        result["execution_policy"] = policy
        return append(folder, result)


# Expose a bounded summary rather than copying the full per-stock execution journal.
def summary(root):
    try:
        row = latest(root)
    except (OSError, ValueError):
        return {"status": "unavailable"}
    if not row:
        return None
    return {
        key: row[key]
        for key in (
            "version",
            "started_at",
            "as_of",
            "initial_capital",
            "cash",
            "equity",
            "sequence",
            "status",
        )
    }
