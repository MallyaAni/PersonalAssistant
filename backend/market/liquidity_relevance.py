"""Read-only paper-order capacity diagnostics, never simulated execution savings."""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np

from backend.agents.trading.desk import execution_evidence
from backend.market.daily_risk_liquidity import Dataset


# Parse positive monetary quantities without treating missing data as zero.
def positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if np.isfinite(number) and number > 0 else None


# Summarize a nonempty finite sample in its original units.
def distribution(values: list[float] | np.ndarray) -> dict[str, Any]:
    a = np.asarray(values, dtype=float)
    a = a[np.isfinite(a)]
    if not len(a):
        return {"n": 0, "median": None, "p95": None, "max": None}
    return {
        "n": len(a),
        "median": float(np.median(a)),
        "p95": float(np.quantile(a, 0.95)),
        "max": float(a.max()),
    }


# Compare recorded sizes with turnover only when actual completion dates are known.
def evaluate(
    state: dict[str, Any], ds: Dataset, forecasts: dict[str, Any]
) -> dict[str, Any]:
    lookup = {
        (str(day), str(ticker)): i
        for i, (day, ticker) in enumerate(zip(ds.dates, ds.tickers, strict=True))
    }
    skipped: Counter[str] = Counter()
    notionals, participation, matched_notional = [], [], []
    reference_dates = []
    for order in state.get("journal", []):
        qty, price = (
            positive(order.get("filled_qty")),
            positive(order.get("filled_price")),
        )
        if qty is None or price is None:
            skipped["no_positive_recorded_fill"] += 1
            continue
        notional = qty * price
        notionals.append(notional)
        execution = order.get("execution") or {}
        complete = execution_evidence.completion_session(execution)
        if complete is None:
            skipped["missing_completion_timestamp"] += 1
            continue
        # An order-completion timestamp is not every partial fill's timestamp.
        if order.get("status") != "filled":
            skipped["partial_or_nonfilled_status"] += 1
            continue
        end = int(np.searchsorted(ds.sessions, np.datetime64(complete)))
        if end == 0 or end >= len(ds.sessions) or str(ds.sessions[end]) != complete:
            skipped["completion_session_outside_dataset"] += 1
            continue
        prior = str(ds.sessions[end - 1])
        i = lookup.get((prior, str(order.get("symbol"))))
        if i is None or not np.isfinite(forecasts["point"][i, 2, 2]):
            skipped["no_previous_session_forecast"] += 1
            continue
        participation.append(notional / forecasts["point"][i, 2, 2])
        matched_notional.append(notional)
        reference_dates.append(complete)
    history = state.get("history", [])
    latest = max(history, key=lambda r: str(r.get("session", ""))) if history else {}
    equity = positive(latest.get("equity"))
    total = float(sum(notionals))
    scenarios = [
        {
            "saved_bps_per_filled_notional": bp,
            "hypothetical_dollars": total * bp / 1e4,
            "hypothetical_fraction_of_latest_equity": (
                total * bp / 1e4 / equity if equity else None
            ),
        }
        for bp in (1, 5, 10)
    ]
    # Fixed current-equity scenarios are not a compounded historical account.
    recent = (ds.dates >= np.datetime64("2024-01-01")) & np.isfinite(
        forecasts["point"][:, 2, 2]
    )
    max_order = 0.25 * equity if equity else None
    capacity = max_order / forecasts["point"][recent, 2, 2] if max_order else []
    return {
        "journal_policy_version": state.get("policy_version"),
        "per_order_policy_provenance": "not recorded; do not infer from current state",
        "journal_rows": len(state.get("journal", [])),
        "positive_fill_notional": distribution(notionals),
        "total_recorded_filled_notional": total,
        "latest_equity": equity,
        "latest_equity_session": latest.get("session"),
        "excluded_from_forecast_matching": dict(skipped),
        "completion_date_matched_orders": len(participation),
        "predicted_daily_turnover_participation": distribution(participation),
        "notional_weighted_participation": (
            float(np.average(participation, weights=matched_notional))
            if participation
            else None
        ),
        "matched_completion_dates": sorted(set(reference_dates)),
        "saving_sensitivity": scenarios,
        "v5_size_scenario": {
            "policy_cap": 0.25,
            "fixed_equity": equity,
            "order_dollars": max_order,
            "window": "2024 onward",
            "all_eligible_names_not_actual_v5_orders": True,
            "daily_turnover_participation": distribution(capacity),
        },
        "measured_savings": None,
        "fill_probability_model_qualified": False,
        "limitations": [
            "Paper fills are not real broker execution quality.",
            "Daily turnover is not available depth at the execution instant.",
            "Completion date applies to aggregate order price, not all partial fills.",
            "No annualization of the short live journal or fabricated execution dates.",
            "Saving scenarios are not alpha, an achievable saving, or an upper bound.",
        ],
    }
