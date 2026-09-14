"""Audit forward evidence before choosing an offline RL training experiment."""

import json
from collections import Counter

from backend.market import desk_freshness, forward_actions


# Count actual dates and state coverage without treating correlated tickers as episodes.
def report(root):
    rows = []
    invalid = 0
    for path in sorted((root / "desk/intraday-research").glob("decision-*.json")):
        try:
            row = json.loads(path.read_text())
            if desk_freshness.timestamp(row.get("bar")) is None:
                raise ValueError("Dated bar required")
            rows.append(row)
        except (OSError, ValueError, TypeError):
            invalid += 1
    dates = sorted({forward_actions.session(row["bar"]).isoformat() for row in rows})
    states = sum(
        row.get("learning_state", {}).get("schema") == "desk-state/1" for row in rows
    )
    feeds = Counter(
        (row.get("execution_quotes") or {}).get("feed") or "missing" for row in rows
    )
    policies = Counter(row.get("policy_sha256") or "missing" for row in rows)
    return {
        "status": "research_only_not_training_approved",
        "observations": len(rows),
        "distinct_market_sessions": len(dates),
        "first_session": dates[0] if dates else None,
        "last_session": dates[-1] if dates else None,
        "state_snapshots": states,
        "missing_state_snapshots": len(rows) - states,
        "quote_feeds": dict(feeds),
        "policy_groups": dict(policies),
        "invalid_records": invalid,
        "evaluation_requirements": [
            "Chronological train, validation and untouched test periods; "
            "no random candle split",
            "Separate post-guidance-change evaluation with adequate "
            "independent meetings",
            "Compare adopted strategy, cash, SPY and a simple allocation model "
            "after identical costs",
            "Validate overnight actions, executable quotes and delayed fills "
            "before training",
            "Stress higher costs, missing quotes, drawdowns and unseen market regimes",
            "Run the frozen challenger in paper only before any promotion",
        ],
        "first_experiment": "Bounded allocation and cash control using existing "
        "analyst states; no live exploration",
    }
