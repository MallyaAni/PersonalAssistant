"""Present the adopted plan's eligibility without promoting research allocations."""

import math
from datetime import UTC, datetime

import numpy as np

from backend.agents.trading.desk.actions import action_for
from backend.market import (
    calendar,
    desk_freshness,
    execution_quotes,
    holdings,
    opportunity,
)

VERSION = "desk-decision-view/1"


# Select the first blocking fact before interpreting the scheduled weight change.
def action_for_row(
    row, quote, deadline, paused, current_decision, target, current, now
):
    checks = (
        (paused, "FOMC cycle takes priority"),
        (not row, "No allocation in the adopted plan"),
        (row and not row["in_book"], "Outside desk coverage; review manually"),
        (not current_decision, "Nightly decision outdated or calendar unavailable"),
        (not quote["eligible"], quote["reason"]),
        (not deadline or deadline <= now, "Current technical evidence unavailable"),
        (row and row["until_rebalance"] is None, "Rebalance timing unavailable"),
    )
    reason = next((message for blocked, message in checks if blocked), None)
    if reason:
        return "Wait", reason
    if not row["rebalance_due"]:
        return ("Hold" if row["shares"] > 0 else "Wait"), "Next rebalance not due"
    direction = action_for(target, current)
    if row["rejecting_band"] and direction in ("buy", "add"):
        return "Wait", "Upper-band rejection blocks additions"
    if direction in ("buy", "add") and row["grade_live"] in ("A", "A+"):
        return "Buy eligible", "Scheduled addition; confirm cash and broker price"
    if direction in ("trim", "sell"):
        return "Reduce", "Scheduled target below recorded position"
    return ("Hold" if row["shares"] > 0 else "Wait"), "No eligible addition"


# Combine existing strategy gates and quote evidence into one dated, reviewable row.
def build(record, held, equity, snapshot, quoted, now=None, targets=None):
    now = now or datetime.now(UTC)
    if targets is not None:
        if (
            set(targets) != set(record.get("grades") or {})
            or not all(math.isfinite(w) and 0 <= w <= 1 for w in targets.values())
            or sum(targets.values()) > 1.000001
        ):
            raise ValueError("Complete funded allocation required")
        record = {
            **record,
            "book": [
                {"ticker": name, "weight": weight} for name, weight in targets.items()
            ],
        }
    technical, value = desk_freshness.grade_inputs(snapshot, record, now)
    rows = {
        r["ticker"]: r
        for r in holdings.board(
            record, held, equity, snapshot.get("quotes") or {}, technical, value
        )
    }
    expiries = desk_freshness.grade_expiries(snapshot, technical)
    readings = holdings.live_grades(record, technical, value)
    event = record.get("event_risk") or {}
    paused = (
        event.get("factor") == 0.5
        or event.get("execution_pending")
        or event.get("calendar_known") is False
    )
    result = {}
    current_decision = (
        calendar._future_session_offset(
            np.datetime64(record["session"]),
            np.datetime64(now.astimezone(desk_freshness.NEW_YORK).date()),
        )
        == 1
    )
    for symbol in sorted(set(record.get("grades") or {}) | set(rows)):
        row = rows.get(symbol)
        quote = execution_quotes.describe(
            (quoted.get("quotes") or {}).get(symbol, {}),
            quoted.get("feed"),
            quoted.get("market_open", False),
            now,
        )
        target = row["target_weight"] if row else 0.0
        current = row["current_weight"] if row else 0.0
        # Compare percentages at the quoted midpoint when valid prices exist.
        if row and "bid" in quote and math.isfinite(equity) and equity > 0:
            current = row["shares"] * (quote["bid"] + quote["ask"]) / (2 * equity)
        action, reason = action_for_row(
            row,
            quote,
            desk_freshness.timestamp(expiries.get(symbol)),
            paused,
            current_decision,
            target,
            current,
            now,
        )
        deadlines = [
            desk_freshness.timestamp(v)
            for v in (expiries.get(symbol), quote.get("valid_until"))
            if desk_freshness.timestamp(v)
        ]
        result[symbol] = {
            "opportunity": opportunity.explain(
                (record.get("grades") or {}).get(symbol, {}),
                readings.get(symbol),
                (snapshot.get("quotes") or {}).get(symbol, {}),
                expiries.get(symbol),
                now,
                record["session"],
            ),
            "action": action,
            "reason": reason,
            "target_weight": target,
            "current_weight": current,
            "delta_weight": target - current,
            "valid_until": min(deadlines).isoformat() if deadlines else None,
            "quote": quote,
            "session": record["session"],
        }
    return {
        "version": VERSION,
        "as_of": now.isoformat(),
        "session": record["session"],
        "written": record.get("written"),
        "equity": equity,
        "holdings": {h.ticker: h.shares for h in held},
        "policy": "Experimental targets; adopted gates; manual execution"
        if targets is not None
        else "Scheduled next-open strategy; personal execution is manual",
        "rows": result,
    }
