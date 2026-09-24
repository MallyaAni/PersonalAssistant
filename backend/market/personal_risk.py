"""Describe a dated support/resistance scenario and an optional personal risk cap.

Distances are fractions of the same snapshot's price. Dollar level fields are
deliberately not accepted: those fields use adjusted prices, while a live quote
uses the raw price. Neither a reference level nor its ratio predicts a fill.
"""

import math
from datetime import datetime

BASIS = (
    "Approximate references derived from same-snapshot price distances; "
    "not a return forecast or guaranteed stop execution"
)


# Accept finite numeric inputs without silently interpreting flags as numbers.
def _finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


# Require comparable, aware timestamps before accepting a dated market reading.
def _aware(value):
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


# Bound an additional position by the person's explicit account risk budget.
def build(
    *,
    entry_price,
    support_distance,
    resistance_distance,
    current_weight,
    policy_max_add_weight,
    observed_at,
    valid_until,
    now,
    fresh,
    risk_budget_pct=None,
):
    """Return percentage risk/reward and a fractional additional-weight ceiling.

    The caller must supply distances and entry price from one snapshot, its actual
    observation/deadline, and the result of that snapshot's existing freshness gate.
    `policy_max_add_weight` is the existing strategy/name-cap limit for this entry.
    No budget means information only: `max_add_weight` is None, never a new limit.
    """
    result = {
        "status": "unavailable",
        "basis": BASIS,
        "entry": None,
        "reference_support": None,
        "reference_resistance": None,
        "risk_pct": None,
        "reward_pct": None,
        "reward_risk_ratio": None,
        "risk_budget_pct": risk_budget_pct if _finite(risk_budget_pct) else None,
        "max_add_weight": 0.0 if risk_budget_pct is not None else None,
        "reason": "Current risk references are unavailable",
    }
    if risk_budget_pct is not None and (
        not _finite(risk_budget_pct) or not 0 < risk_budget_pct <= 100
    ):
        return {
            **result,
            "reason": "Risk budget must be greater than zero and at most 100%",
        }
    if not _finite(current_weight) or not 0 <= current_weight <= 1:
        return {**result, "reason": "Current position weight is invalid"}
    if not _finite(policy_max_add_weight) or not 0 <= policy_max_add_weight <= 1:
        return {**result, "reason": "Strategy addition limit is invalid"}
    if (
        fresh is not True
        or not all(_aware(value) for value in (observed_at, valid_until, now))
        or not observed_at <= now < valid_until
    ):
        return {
            **result,
            "reason": "Risk references are stale, future-dated or undated",
        }
    if not _finite(entry_price) or entry_price <= 0:
        return {**result, "reason": "Current entry price is unavailable"}
    result["entry"] = float(entry_price)
    if not _finite(support_distance) or not 0 < support_distance < 1:
        return {
            **result,
            "reason": "No supported downside reference below the entry price",
        }
    if not _finite(resistance_distance) or resistance_distance <= 0:
        return {
            **result,
            "reason": "No supported overhead resistance; reward is unknown",
        }
    support = entry_price * (1 - support_distance)
    resistance = entry_price * (1 + resistance_distance)
    ratio = resistance_distance / support_distance
    risk_pct = support_distance * 100
    reward_pct = resistance_distance * 100
    if not all(
        math.isfinite(value)
        for value in (support, resistance, ratio, risk_pct, reward_pct)
    ):
        return {**result, "reason": "Risk reference calculation is not finite"}
    result.update(
        reference_support=float(support),
        reference_resistance=float(resistance),
        risk_pct=float(risk_pct),
        reward_pct=float(reward_pct),
        reward_risk_ratio=float(ratio),
    )
    if risk_budget_pct is None:
        return {
            **result,
            "status": "budget_required",
            "reason": "Reference scenario only; choose a risk budget to cap size",
        }
    room = max(0.0, (risk_budget_pct / 100) / support_distance - current_weight)
    result.update(
        status="available",
        max_add_weight=float(min(room, policy_max_add_weight, 1 - current_weight)),
        reason="Risk to reference support limits size; gaps can exceed the budget",
    )
    return result
