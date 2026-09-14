"""Current event execution evidence, separate from immutable nightly decisions."""

import json
from datetime import UTC, datetime

from backend.agents.trading.desk import event_risk, paper
from backend.market import desk_freshness


# Read current durable intent and date the intraday policy observation separately.
def load(root):
    state = paper.load_state(root)
    try:
        result = json.loads((root / "desk" / "event-live.json").read_text())
    except (OSError, ValueError):
        result = {}
    stamp = desk_freshness.timestamp(result.get("as_of"))
    stale = stamp is None or not 0 <= (datetime.now(UTC) - stamp).total_seconds() < 900
    policy = result.get("policy") or {}
    paused = bool(state.event_cycle) or (
        not stale
        and (
            policy.get("factor") == event_risk.REDUCED
            or policy.get("calendar_known") is False
        )
    )
    return {
        **result,
        "stale": stale,
        "active": bool(state.event_cycle),
        "planning_paused": paused,
        "pending_orders": sum(bool(row.get("event_id")) for row in state.pending),
    }


# Pause current planning for durable event intent without changing archived records.
def for_planning(record, root):
    status = load(root)
    if not status["planning_paused"]:
        return record
    return {
        **record,
        "event_risk": {**(record.get("event_risk") or {}), "execution_pending": True},
    }
