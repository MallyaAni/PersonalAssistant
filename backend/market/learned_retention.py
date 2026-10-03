"""Pure, experimental held-B retention; no orders, fitting or cash credits.

Forecasts are conditional ten-session log returns relative to SPY. Exponentiating
their means gives a plug-in wealth comparison, not expected terminal wealth or
an optimal portfolio. Recipient weights describe the caller's actual proposed
destination per exiting name; unavailable recipients are never renormalized.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# Keep the retention verdict and its account-relative quantities together.
@dataclass(frozen=True)
class RetentionPlan:
    retained_shares: np.ndarray
    retain_mask: np.ndarray
    retained_weights: np.ndarray
    buy_eligible: np.ndarray
    edge: np.ndarray
    reasons: tuple[str, ...]


# Validate numeric vectors without silently accepting strings or booleans.
def _numbers(value, shape, label, *, missing=False):
    array = np.asarray(value)
    if array.shape != shape or array.dtype.kind not in "iuf":
        raise ValueError(f"{label} must be a numeric array with shape {shape}")
    array = array.astype(np.float64, copy=True)
    if not missing and not np.isfinite(array).all():
        raise ValueError(f"{label} must contain finite numbers")
    return array


# Require actual boolean evidence masks on the declared symbol grid.
def _mask(value, size, label, *, optional=False):
    if value is None and optional:
        return np.zeros(size, dtype=bool)
    array = np.asarray(value)
    if array.shape != (size,) or array.dtype.kind != "b":
        raise ValueError(f"{label} must be a boolean symbol mask")
    return array.copy()


# Bound one scalar control without accepting coerced text or boolean values.
def _scalar(value, label, lower, upper, *, lower_inclusive=True):
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, float, np.integer, np.floating)
    ):
        raise ValueError(f"{label} must be a finite numeric control")
    value = float(value)
    if (
        not np.isfinite(value)
        or value > upper
        or (value < lower if lower_inclusive else value <= lower)
    ):
        raise ValueError(f"{label} outside its declared bounds")
    return value


# Compare holding with the exact fee-bearing destination mixture in log units.
def _wealth_edge(own, forecasts, weights, cost, spy_forecast):
    invested = float(weights.sum())
    cash_weight = max(0.0, 1.0 - invested)
    if cash_weight > 1e-12:
        if spy_forecast is None or not np.isfinite(spy_forecast):
            return np.nan
        own = own + spy_forecast
        destination = forecasts + spy_forecast
    else:
        destination = forecasts
    positive = weights > 0
    # Compare relative excess wealth so equal forecasts and zero fees remain zero.
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        invested_ratio = invested + np.dot(
            weights[positive], np.expm1(destination[positive] - own)
        )
        cash_ratio = cash_weight * np.exp(-own) if cash_weight > 1e-12 else 0.0
        ratio = (1 - cost) * (invested_ratio / (1 + cost) + cash_ratio)
    if np.isfinite(ratio) and ratio > 0:
        return float(-np.log(ratio))
    # Extreme finite log forecasts need a log-domain mixture to avoid overflow.
    terms = destination[positive] + np.log(weights[positive]) - np.log1p(cost)
    if cash_weight > 1e-12:
        terms = np.append(terms, np.log(cash_weight))
    replacement = np.log1p(-cost) + np.logaddexp.reduce(terms)
    return float(own - replacement)


# Decide which existing B positions survive a causal, funded replacement proposal.
def plan_retention(  # noqa: C901 - preserve explicit validation and fallback reasons
    grades,
    eligible,
    prices,
    held,
    nav,
    forecasts,
    recipient_weights,
    *,
    hard_cap,
    cost_bps,
    blocked=None,
    event_exits=None,
    thesis_exits=None,
    spy_forecast=None,
    trim_to_cap=False,
    whole_shares=False,
):
    """Return retention only; all other positions keep their incumbent behavior.

    Grades use C=0/B=1/A=2/A+=3, with -1 unavailable. ``blocked`` prevents
    destination purchases but does not force sale of an existing position.
    Event/thesis masks force incumbent exits. Recipient rows sum to <=1; their
    residual is cash and requires a separate absolute SPY log-return forecast.
    Switching uses (1-sell_fee)/(1+buy_fee), with uninvested proceeds charged
    only the sell fee. No account cash or executable order is created here.
    """
    raw_grades = np.asarray(grades)
    if raw_grades.ndim != 1 or not len(raw_grades):
        raise ValueError("grades must be a nonempty symbol vector")
    size = len(raw_grades)
    shape = (size,)
    grades = _numbers(raw_grades, shape, "grades")
    if np.any(grades != np.floor(grades)) or np.any((grades < -1) | (grades > 3)):
        raise ValueError("grades must be ordinal -1 through3")
    eligible = _mask(eligible, size, "eligible")
    blocked = _mask(blocked, size, "blocked", optional=True)
    event = _mask(event_exits, size, "event_exits", optional=True)
    thesis = _mask(thesis_exits, size, "thesis_exits", optional=True)
    prices = _numbers(prices, shape, "prices", missing=True)
    held = _numbers(held, shape, "held")
    forecasts = _numbers(forecasts, shape, "forecasts", missing=True)
    if np.any(held < 0) or np.any((held > 0) & (~np.isfinite(prices) | (prices <= 0))):
        raise ValueError("nonnegative holdings require positive finite held prices")
    nav = _scalar(nav, "nav", 0, np.inf, lower_inclusive=False)
    hard_cap = _scalar(hard_cap, "hard_cap", 0, 1, lower_inclusive=False)
    cost_bps = _scalar(cost_bps, "cost_bps", 0, 10000)
    if cost_bps == 10000:
        raise ValueError("cost_bps must be below10000")
    if not isinstance(trim_to_cap, (bool, np.bool_)) or not isinstance(
        whole_shares, (bool, np.bool_)
    ):
        raise ValueError("trim_to_cap and whole_shares must be booleans")
    if whole_shares and np.any(held != np.floor(held)):
        raise ValueError("whole-share mode requires whole existing holdings")
    marked = np.where(held > 0, held * prices, 0)
    if marked.sum() > nav + 1e-10 * nav:
        raise ValueError("held marked value exceeds NAV")
    if spy_forecast is not None:
        spy_forecast = _scalar(spy_forecast, "spy_forecast", -np.inf, np.inf)
    raw_weights = np.asarray(recipient_weights)
    if raw_weights.shape == shape:
        raw_weights = np.broadcast_to(raw_weights, (size, size))
    weights = _numbers(raw_weights, (size, size), "recipient_weights")
    if np.any(weights < 0) or np.any(weights.sum(axis=1) > 1 + 1e-12):
        raise ValueError("recipient weights must be nonnegative and sum to <=1")
    buy_eligible = eligible & (grades >= 2) & ~blocked & ~event & ~thesis
    for stock in np.flatnonzero((held > 0) & (grades == 1)):
        required = weights[stock] > 0
        proposed = (
            marked
            + weights[stock]
            * marked[stock]
            * (1 - cost_bps / 1e4)
            / (1 + cost_bps / 1e4)
        ) / nav
        if np.any(required & (proposed > hard_cap + 1e-12)):
            raise ValueError("Replacement destination exceeds the existing hard cap")
    retained = np.zeros(size)
    mask = np.zeros(size, dtype=bool)
    edge = np.full(size, np.nan)
    reasons = []
    for stock in range(size):
        reason = "not_held_B"
        if held[stock] > 0 and grades[stock] == 1:
            required = weights[stock] > 0
            if event[stock] or thesis[stock]:
                reason = "mandatory_exit"
            elif not eligible[stock]:
                reason = "eligibility_unavailable"
            elif not np.isfinite(forecasts[stock]):
                reason = "forecast_unavailable"
            elif np.any(
                required
                & (
                    ~buy_eligible
                    | ~np.isfinite(forecasts)
                    | ~np.isfinite(prices)
                    | (prices <= 0)
                )
            ):
                reason = "destination_unavailable"
            elif marked[stock] / nav > hard_cap and not trim_to_cap:
                reason = "hard_cap_requires_trim"
            else:
                edge[stock] = _wealth_edge(
                    forecasts[stock],
                    forecasts,
                    weights[stock],
                    cost_bps / 1e4,
                    spy_forecast,
                )
                reason = "cash_forecast_unavailable"
                if np.isfinite(edge[stock]):
                    reason = "replacement_preferred"
                    if edge[stock] > 0:
                        retained[stock] = min(
                            held[stock], hard_cap * nav / prices[stock]
                        )
                        if whole_shares:
                            retained[stock] = np.floor(retained[stock])
                        mask[stock] = retained[stock] > 0
                        reason = "retain" if mask[stock] else "cap_below_one_share"
        reasons.append(reason)
    retained_weights = np.where(mask, retained * prices / nav, 0)
    return RetentionPlan(
        retained, mask, retained_weights, buy_eligible, edge, tuple(reasons)
    )


# Reserve held-B weight before distributing an explicit reset budget to the A basket.
def reset_targets(base_targets, retention, *, hard_cap, stock_budget=1.0):
    """Return desired weights, not orders or a credit of pending sale proceeds.

    Preserve A basket ratios until individual caps bind; excess stays cash rather
    than silently reallocating it. The shared funded planner must still enforce
    actual cash, prices and executable quantities. Retained shares are unchanged.
    """
    if not isinstance(retention, RetentionPlan):
        raise ValueError("retention must be a RetentionPlan")
    shape = retention.retained_weights.shape
    if len(shape) != 1:
        raise ValueError("retention must contain a symbol vector")
    buy_eligible = _mask(retention.buy_eligible, shape[0], "buy_eligible")
    retained_mask = _mask(retention.retain_mask, shape[0], "retain_mask")
    shares = _numbers(retention.retained_shares, shape, "retained_shares")
    base = _numbers(base_targets, shape, "base_targets")
    cap = _scalar(hard_cap, "hard_cap", 0, 1, lower_inclusive=False)
    budget = _scalar(stock_budget, "stock_budget", 0, 1)
    if np.any(base < 0) or base.sum() > 1 + 1e-12 or np.any((base > 0) & ~buy_eligible):
        raise ValueError("base targets must be a valid eligible A/A+ basket")
    reserved = _numbers(retention.retained_weights, shape, "retained_weights")
    if np.any(reserved < 0) or np.any(reserved > cap + 1e-12):
        raise ValueError("retained weights violate the declared cap")
    if (
        np.any(shares < 0)
        or not np.array_equal(reserved > 0, retained_mask)
        or not np.array_equal(shares > 0, retained_mask)
        or np.any(retained_mask & buy_eligible)
    ):
        raise ValueError("retained positions must be held and excluded from purchases")
    remaining = budget - float(reserved.sum())
    if remaining < -1e-12:
        raise ValueError("retained positions exceed the explicit stock budget")
    target = reserved.copy()
    if base.sum() > 0:
        target += np.minimum(base * max(0.0, remaining) / base.sum(), cap)
    return target
