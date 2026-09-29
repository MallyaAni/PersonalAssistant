"""Read the real paper account's recorded values, never simulated returns.

The nightly writer stores broker account equity, not a certified closing NAV.
No cash-flow ledger or per-record policy stamp exists in these records, so a
change in account value must not be labelled trading P&L or strategy return.
"""

import math
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import paper
from backend.market.calendar import reviewed_sessions


# Keep malformed values missing rather than creating invalid JSON or fake zeros.
def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


# A recording timestamp needs its timezone; a session date is not a quote time.
def _recorded_at(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if instant.tzinfo is not None else None


# Count absent exchange records without treating weekends/holidays as missing.
def _missing_sessions(previous: date, current: date) -> int | None:
    years, calendar = reviewed_sessions()
    if not set(range(previous.year, current.year + 1)).issubset(years):
        return None
    return int(
        np.busday_count(previous + timedelta(days=1), current, busdaycal=calendar)
    )


# Project saved broker observations without touching the account or its history.
def load(root: Path, *, limit: int = 90) -> dict:
    """Return dated observations and unadjusted changes, newest record last.

    Missing/invalid values stay missing. Never forward-fill them, append a live
    quote to a historical day, or infer zero deposits from an absent ledger.
    """
    state = paper.load_state(root)
    if not isinstance(state.history, list):
        raise ValueError("Invalid paper account history")
    by_session = {}
    ignored = 0
    for item in state.history:
        if not isinstance(item, dict):
            ignored += 1
            continue
        try:
            session = date.fromisoformat(item.get("session", ""))
        except (TypeError, ValueError):
            ignored += 1
            continue
        if session.isoformat() != item["session"]:
            ignored += 1
            continue
        # The writer replaces a session's record on re-run; last occurrence
        # also wins for legacy files containing repeated sessions.
        by_session[session] = item

    rows = []
    previous = None
    for session, item in sorted(by_session.items()):
        equity = _number(item.get("equity"))
        recorded_at = _recorded_at(item.get("written"))
        chronology = None
        if previous and previous["recorded_at"] and recorded_at:
            chronology = datetime.fromisoformat(recorded_at) > datetime.fromisoformat(
                previous["recorded_at"]
            )
        prior_equity = previous["equity"] if previous is not None else None
        change = (
            _number(equity - prior_equity)
            if equity is not None and prior_equity is not None and chronology is True
            else None
        )
        change_pct = (
            _number(change / prior_equity)
            if change is not None and prior_equity > 0
            else None
        )
        row = {
            "session": session.isoformat(),
            "recorded_at": recorded_at,
            "chronology_verified": chronology,
            "equity": equity,
            "cash": _number(item.get("cash")),
            "equity_change": change,
            "equity_change_pct": change_pct,
            "previous_session": previous["session"] if previous else None,
            "missing_sessions": (
                _missing_sessions(date.fromisoformat(previous["session"]), session)
                if previous
                else None
            ),
        }
        rows.append(row)
        previous = row

    return {
        "source": "paper_account_records",
        "valuation_basis": "recorded_broker_account_value",
        "cash_flow_adjusted": False,
        "closing_values_verified": False,
        "policy_attribution_available": False,
        "total_records": len(rows),
        "ignored_records": ignored,
        "first_session": rows[0]["session"] if rows else None,
        "last_session": rows[-1]["session"] if rows else None,
        "truncated": len(rows) > limit,
        "rows": rows[-limit:],
    }
