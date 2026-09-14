"""Order-level execution evidence; missing broker times stay unknown.

The broker's filled_at is order completion, not the timestamp of every partial
fill. Comparisons use the aggregate fill price and explicitly name that basis.
"""

import math
from datetime import datetime
from zoneinfo import ZoneInfo

TIMESTAMPS = (
    "created_at",
    "submitted_at",
    "filled_at",
    "canceled_at",
    "expired_at",
    "failed_at",
)


# Accept only explicit timezone-aware timestamps while retaining broker precision.
def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.utcoffset() is not None else None


# Keep a small allowlist of broker evidence, never credentials or account identifiers.
def broker_evidence(order):
    order = order or {}
    evidence = {key: timestamp(order.get(key)) for key in TIMESTAMPS}
    evidence = {key: value for key, value in evidence.items() if value is not None}
    if order.get("time_in_force") in ("day", "cls", "opg", "gtc", "ioc", "fok"):
        evidence["time_in_force"] = order["time_in_force"]
    return evidence


# Resolve the order's completion date in the exchange timezone, never from its plan.
def completion_session(execution):
    value = timestamp(execution.get("filled_at"))
    if value is None:
        return None
    return (
        datetime.fromisoformat(value)
        .astimezone(ZoneInfo("America/New_York"))
        .date()
        .isoformat()
    )


# Measure aggregate fill drift from the recorded decision price; positive is adverse.
def decision_shortfall_bps(side, filled_price, reference):
    if side not in ("buy", "sell"):
        return None
    try:
        fill, price = float(filled_price), float(reference)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(p) and p > 0 for p in (fill, price)):
        return None
    return (1 if side == "buy" else -1) * (fill / price - 1) * 1e4
