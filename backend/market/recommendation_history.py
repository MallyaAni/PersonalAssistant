"""Expose original recorded recommendations without replaying today's policy."""

import json
import math
import time
from datetime import timedelta

from backend.market import desk_freshness, forward_actions

MAX_SCAN = 1000
DISPLAY_LIMIT = 200
_cache = {}


# Project only public decision evidence, preserving pauses and original model weights.
def observation(record, ticker, identity):
    grade = (record.get("grades") or {}).get(ticker)
    if grade is None:
        return None
    weight = float(record["targets"][ticker])
    price = float(record["prices"][ticker])
    if not math.isfinite(weight) or not 0 <= weight <= 1:
        raise ValueError("Invalid recorded allocation")
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Invalid recorded price")
    stamp = desk_freshness.timestamp(record["as_of"])
    bar = desk_freshness.timestamp(record["bar"])
    if stamp is None or bar is None:
        raise ValueError("Recorded timestamps required")
    paused = record.get("event_paused") is True
    return {
        "id": identity,
        "recorded_at": stamp.isoformat(),
        "bar": bar.isoformat(),
        "grade": grade["grade_live"],
        "allocation": None if paused else weight,
        "model_weight": weight,
        "event_paused": paused,
        "entry_state": (record.get("entry_states") or {}).get(ticker),
        "price": price,
        "version": record.get("version", "unversioned"),
        "policy_sha256": record.get("policy_sha256"),
        "allocation_change": None,
        "stock_total_return": None,
    }


# Compare recorded marks only when daily corporate-action validation covers them.
def mark_outcomes(root, ticker, rows):
    try:
        actions, through = forward_actions.load(root, [ticker])
    except (ValueError, KeyError, OSError):
        return {"status": "daily_validation_unavailable"}
    valid = [
        row
        for row in rows
        if forward_actions.session(row["bar"]).isoformat() <= through
    ]
    if not valid:
        return {"status": "awaiting_daily_validation", "through": through}
    last = valid[-1]
    for row in valid[:-1]:
        if desk_freshness.timestamp(row["bar"]) >= desk_freshness.timestamp(
            last["bar"]
        ):
            continue
        row["stock_total_return"] = forward_actions.total_return(
            ticker,
            row["price"],
            last["price"],
            forward_actions.session(row["bar"]),
            forward_actions.session(last["bar"]),
            actions,
        )
    return {
        "status": "observed_marks",
        "through": through,
        "mark_price": last["price"],
        "mark_at": (
            desk_freshness.timestamp(last["bar"]) + timedelta(minutes=15)
        ).isoformat(),
    }


# Read a bounded recent timeline and keep original policy groups distinct.
def load(root, ticker):
    folder = root / "desk/intraday-research"
    signature = folder.stat().st_mtime_ns if folder.exists() else 0
    key = (str(root), ticker)
    cached = _cache.get(key)
    if cached and cached[0] == signature and time.monotonic() - cached[1] < 60:
        return cached[2]
    paths = sorted(
        folder.glob("decision-*.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    rows = []
    invalid = 0
    for path in paths[-MAX_SCAN:]:
        try:
            row = observation(json.loads(path.read_text()), ticker, path.stem)
            if row:
                rows.append(row)
        except (ValueError, TypeError, KeyError, OSError):
            invalid += 1
    rows.sort(key=lambda row: (row["recorded_at"], row["id"]))
    previous = {}
    for row in rows:
        policy = (row["version"], row["policy_sha256"])
        prior = previous.get(policy)
        if prior is not None and row["allocation"] is not None:
            row["allocation_change"] = row["allocation"] - prior
        previous[policy] = row["allocation"]
    try:
        outcomes = mark_outcomes(root, ticker, rows) if rows else None
    except (ValueError, TypeError, KeyError, OSError):
        for row in rows:
            row["stock_total_return"] = None
        outcomes = {"status": "daily_validation_unavailable"}
    result = {
        "status": "available" if rows else "no_recorded_recommendations",
        "outcomes": outcomes,
        "observations": list(reversed(rows[-DISPLAY_LIMIT:])),
        "invalid_archives": invalid,
        "older_records_not_shown": len(paths) > MAX_SCAN or len(rows) > DISPLAY_LIMIT,
        "method": "Original model observations; paused allocations are withheld. "
        "Stock total return runs from the recorded bar to the latest validated "
        "archived mark, including recorded splits and dividends. It is gross of "
        "costs and is not a trade fill or strategy profit.",
    }
    if len(_cache) >= 128:
        _cache.clear()
    _cache[key] = (signature, time.monotonic(), result)
    return result
