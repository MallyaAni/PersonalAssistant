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
    row, quote, deadline, paused, current_decision, target, current, now, entry=None
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
    # The book's own mid-cycle entry, read at the live price. This has to be
    # decided before the rebalance branch below, because that branch answers
    # only the calendar's question and the calendar is now six months wide.
    # Without this the row that the desk is about to buy tonight reads "Wait",
    # which is the opposite of what the operator has to do about it.
    if entry is not None:
        return entry
    if not row["rebalance_due"]:
        # A name already held is genuinely waiting for the rebalance, since
        # that is when its weight is reset. A name NOT held is not waiting
        # for a date at all: nothing about starting a position depends on
        # the schedule, and saying so made every unheld row read as blocked
        # by a calendar. An account with no recorded positions saw that on
        # all ninety-three.
        if row["shares"] > 0:
            return "Hold", "Weight is reset at the next scheduled reset"
        return "Wait", "Not held; bought when it breaks out or at the reset"
    direction = action_for(target, current)
    if row["rejecting_band"] and direction in ("buy", "add"):
        return "Wait", "Upper-band rejection blocks additions"
    if direction in ("buy", "add") and row["grade_live"] in ("A", "A+"):
        return "Buy eligible", "Scheduled addition; confirm cash and broker price"
    if direction in ("trim", "sell"):
        return "Reduce", "Scheduled target below recorded position"
    return ("Hold" if row["shares"] > 0 else "Wait"), "No eligible addition"


# The book's mid-cycle entry, decided at the live price rather than at the
# close, so the row says what the desk will do tonight instead of what the
# calendar says months from now. The threshold, the grade floor and the name
# cap are read from `paper` rather than restated, because a copy of a trading
# rule in the presentation layer is a copy that drifts.
def entry_action(row, stretch, grade_live):
    """Return (action, reason) when tonight's entry fires on this name, else None."""
    from backend.agents.trading.desk import paper

    if stretch is None or not math.isfinite(stretch) or stretch < paper.ENTRY_TAIL:
        return None
    if grade_live not in paper.ENTRY_MIN_GRADE:
        return None
    # The nightly only enters a name the book wants to hold, so a name with no
    # target is not a candidate however far it has run. Without this the row
    # read "Buy tonight - not picked by the sizing engine", which is two
    # statements that cannot both be true.
    if not row or not row.get("target_weight"):
        return None
    # The same two gates the nightly applies before it sizes anything.
    if row and row.get("rejecting_band"):
        return "Wait", "Breaking out, but the daily is rejecting its upper band"
    above = f"{stretch * 100:.0f}% above its 21-day"
    if row and row["shares"] > 0:
        if row["current_weight"] >= paper.ENTRY_NAME_CAP:
            return "Hold", f"{above}; already at the {paper.ENTRY_NAME_CAP:.0%} name cap"
        return "Add tonight", f"{above}; funded by trimming the rest"
    return "Buy tonight", f"{above}; funded by trimming the rest"


# Combine existing strategy gates and quote evidence into one dated, reviewable row.
def build(record, held, equity, snapshot, quoted, now=None, targets=None, entries=None):
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
    # The plan is current the session it names and the one after (the nightly
    # record is written on the evening of its own session, so requiring
    # strictly the next session labelled a just-written plan "outdated").
    offset = calendar._future_session_offset(
        np.datetime64(record["session"]),
        np.datetime64(now.astimezone(desk_freshness.NEW_YORK).date()),
    )
    current_decision = offset in (0, 1)
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
            entry_action(
                row,
                (entries or {}).get(symbol),
                (readings.get(symbol) or {}).get("grade")
                or (record.get("grades") or {}).get(symbol, {}).get("grade"),
            ),
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
