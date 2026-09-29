"""Research-only daily desired positions through the unchanged `/4` executor.

The registered mapping changes target positions, not order funding or fills.
Daily resets supersede ordinary entry/retry paths; FOMC execution still owns
event sessions. A target is not a fill, and this module records both separately.
No broker, live account, dashboard or production policy consumes this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.agents.trading.desk import policy_v4, simulate
from backend.market import profit_taking
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot

POLICY = "daily-learned-positions/1"
ACTIONS = ("Buy", "Add", "Hold", "Trim", "Sell")
EPSILON = 1e-12


@dataclass
class PricedExecution:
    """A continuous account, independently checked journal and action diagnostics."""

    result: simulate.SimResult
    journal: ResearchJournal
    verification: dict[str, Any]
    diagnostics: dict[str, Any]


# Convert economic forecasts into the exact registered long-only target mapping.
def mapped_targets(base, forecast) -> np.ndarray:
    base = np.asarray(base, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    if base.ndim != 1 or forecast.shape != base.shape:
        raise ValueError("base and forecast must be aligned one-dimensional arrays")
    if (
        not np.isfinite(base).all()
        or np.any(base < 0)
        or np.any(base > policy_v4.HOLD_CAP + EPSILON)
        or base.sum() > 1.0 + EPSILON
    ):
        raise ValueError("baseline targets must be finite, long-only and /4 capped")
    finite = np.isfinite(forecast)
    multiplier = np.ones_like(base)
    # Clipping the forecast first is algebraically identical and avoids overflow.
    multiplier[finite] = 1.0 + np.clip(forecast[finite], -0.02, 0.01) / 0.02
    target = np.minimum(base * multiplier, policy_v4.HOLD_CAP)
    total = float(target.sum())
    if total > 1.0:
        target = target / total
    return target


# Freeze the supplied paths and expose only the current row to the target mapping.
def allocator(mask, forecast=None):
    membership = np.array(mask, dtype=bool, copy=True)
    if membership.ndim != 2:
        raise ValueError("membership must have shape (sessions, symbols)")
    predictions = (
        None if forecast is None else np.array(forecast, dtype=float, copy=True)
    )
    if predictions is not None and predictions.shape != membership.shape:
        raise ValueError("forecast must align with membership")
    membership.setflags(write=False)
    if predictions is not None:
        predictions.setflags(write=False)
    baseline = policy_v4.allocator(membership)

    # Decide from the same session's incumbent targets and already-causal forecast.
    def allocate(report, panel, config, t):
        if panel.adj_close.shape != membership.shape:
            raise ValueError("membership and forecast must align with the panel")
        target = baseline(report, panel, config, t)
        return target if predictions is None else mapped_targets(target, predictions[t])

    return allocate


# Give each action its own counter so zero activity cannot disappear from reports.
def _counts() -> dict[str, int]:
    return dict.fromkeys(ACTIONS, 0)


# Classify actual or intended unit changes without calling an unowned position Hold.
def _actions(before, after, *, holds=True) -> dict[int, str]:
    before, after = np.asarray(before, dtype=float), np.asarray(after, dtype=float)
    out = {}
    for j in range(len(before)):
        left, right = float(before[j]), float(after[j])
        if not (np.isfinite(left) and np.isfinite(right)):
            continue
        tolerance = EPSILON * max(1.0, abs(left), abs(right))
        if right > left + tolerance:
            out[j] = "Buy" if left <= tolerance else "Add"
        elif right < left - tolerance:
            out[j] = "Sell" if right <= tolerance else "Trim"
        elif holds and left > tolerance:
            out[j] = "Hold"
    return out


# Add a collection of symbol actions to aggregate counters.
def _accumulate(counts, actions) -> None:
    for action in actions.values():
        counts[action] += 1


# Summarize intent, actual fills and end-of-session cash from the recorded account.
def _diagnostics(  # noqa: C901 - one chronological pass over distinct journal events
    snapshot, restricted, membership, forecast
) -> dict[str, Any]:
    panel = restricted.panel
    totals = {
        key: _counts()
        for key in (
            "desired",
            "submitted",
            "executed",
            "learned_desired",
            "fallback_desired",
        )
    }
    daily = {}
    for event in snapshot["events"]:
        if event["type"] != "mark":
            continue
        daily[event["session_index"]] = {
            "session": event["session"],
            "cash": event["cash"],
            "nav": event["nav"],
            "cash_share": event["cash"] / event["nav"] if event["nav"] > 0 else None,
            "traded": event["traded"],
            "desired": _counts(),
            "submitted": _counts(),
            "executed": _counts(),
            "missing_forecasts": 0,
            "eligible_forecasts": 0,
            "cancelled_sell_intents": 0,
            "desired_submission_differences": 0,
            "batch_residuals": 0,
            "event_owned_decisions": 0,
        }
    positions = np.zeros(len(panel.tickers))
    decisions = {}
    baseline = policy_v4.allocator(membership)
    residual_reasons: dict[str, int] = {}
    for event in snapshot["events"]:
        kind, t = event["type"], event["session_index"]
        if kind in ("open_account", "mark"):
            positions = np.asarray(event["positions"], dtype=float)
            continue
        row = daily[t]
        if kind == "decision":
            submitted = np.asarray(event["submitted_units"], dtype=float)
            submitted_actions = _actions(positions, submitted)
            _accumulate(totals["submitted"], submitted_actions)
            _accumulate(row["submitted"], submitted_actions)
            decisions[event["decision_id"]] = (positions.copy(), submitted.copy())
            weights = event["desired_weights"]
            if weights is None:
                row["event_owned_decisions"] += int("event_scale" in event["metadata"])
                continue
            prices = panel.adj_close[t]
            nav = row["nav"]
            wanted = positions.copy()
            priced = np.isfinite(prices) & (prices > 0)
            wanted[priced] = (
                np.asarray(weights, dtype=float)[priced] * nav / prices[priced]
            )
            desired_actions = _actions(positions, wanted)
            _accumulate(totals["desired"], desired_actions)
            _accumulate(row["desired"], desired_actions)
            row["desired_submission_differences"] += len(
                _actions(wanted, submitted, holds=False)
            )
            if forecast is not None:
                eligible = baseline(restricted, panel, None, t) > 0
                finite = np.isfinite(forecast[t])
                row["eligible_forecasts"] += int(eligible.sum())
                row["missing_forecasts"] += int((eligible & ~finite).sum())
                learned = {
                    j: a
                    for j, a in desired_actions.items()
                    if eligible[j] and finite[j]
                }
                fallback = {
                    j: a
                    for j, a in desired_actions.items()
                    if eligible[j] and not finite[j]
                }
                _accumulate(totals["learned_desired"], learned)
                _accumulate(totals["fallback_desired"], fallback)
        elif kind == "adjustment" and event["reason"] == "green-open sell suppression":
            before, submitted = decisions[event["decision_id"]]
            adjusted = np.asarray(event["submitted_units"], dtype=float)
            row["cancelled_sell_intents"] += int(
                ((submitted < before - EPSILON) & (adjusted >= before - EPSILON)).sum()
            )
        elif kind == "fill_batch":
            executed = _actions(
                event["positions_before"], event["positions_after"], holds=False
            )
            _accumulate(totals["executed"], executed)
            _accumulate(row["executed"], executed)
            positions = np.asarray(event["positions_after"], dtype=float)
            for residual, reason in zip(
                event["residual_units"], event["unfilled_reasons"], strict=True
            ):
                if residual is None or abs(residual) > EPSILON:
                    row["batch_residuals"] += 1
                    key = reason or "unclassified"
                    residual_reasons[key] = residual_reasons.get(key, 0) + 1
    previous_traded = 0.0
    previous_nav = None
    for row in daily.values():
        row["notional_traded"] = row["traded"] - previous_traded
        row["turnover"] = row["notional_traded"] / previous_nav if previous_nav else 0.0
        previous_traded, previous_nav = row["traded"], row["nav"]
    rows = list(daily.values())
    return {
        "action_counts": totals,
        "daily": rows,
        "turnover": sum(row["turnover"] for row in rows),
        "mean_cash_share": float(np.mean([row["cash_share"] for row in rows])),
        "missing_forecasts": sum(row["missing_forecasts"] for row in rows),
        "eligible_forecasts": sum(row["eligible_forecasts"] for row in rows),
        "cancelled_sell_intents": sum(row["cancelled_sell_intents"] for row in rows),
        "desired_submission_differences": sum(
            row["desired_submission_differences"] for row in rows
        ),
        "batch_residual_reasons": residual_reasons,
        "executed_hold_count_note": "No fill is never counted as an executed Hold.",
        "residual_note": (
            "Batch residuals are phase-specific observations, not pending-order counts."
        ),
    }


# Run one continuous research account and reject any independently unreconciled result.
def price(
    restricted, mask, forecast, since, cost_bps, *, daily=True, name=POLICY
) -> PricedExecution:
    if forecast is not None and not daily:
        raise ValueError("learned forecasts require the registered daily cadence")
    panel = restricted.panel
    membership = np.array(mask, dtype=bool, copy=True)
    predictions = (
        None if forecast is None else np.array(forecast, dtype=float, copy=True)
    )
    decide = allocator(membership, predictions)
    if membership.shape != panel.adj_close.shape:
        raise ValueError("membership must align with the panel")
    options = profit_taking.control_options(panel)
    if daily:
        options["rebalance"] = 1
    journal = ResearchJournal(
        panel.dates,
        panel.tickers,
        simulate.adjusted_open(panel),
        panel.adj_close,
        run_id=f"{name}:{since}:{cost_bps}",
        account_id=f"research:{name}",
        policy_id=name,
        cost_bps=cost_bps,
        provenance={
            "study": POLICY,
            "daily": bool(daily),
            "rebalance": options["rebalance"],
            "forecast_supplied": predictions is not None,
            "specification": "docs/research/daily-actions-plan-2026-09-29.md",
            "event_lifecycle_owns_event_sessions": True,
            "historical_availability_verified": False,
        },
    )
    result = simulate.run(
        restricted,
        since=since,
        allocator=decide,
        cost_bps=cost_bps,
        journal=journal,
        **options,
    )
    snapshot = journal.snapshot()
    verification = verify_snapshot(snapshot)
    if not verification["ok"]:
        raise ValueError(
            f"research account failed independent replay: {verification['errors']}"
        )
    marks = verification["marks"]
    if [m["session"] for m in marks] != [str(d) for d in result.dates]:
        raise ValueError("journal and simulator calendars differ")
    np.testing.assert_allclose(
        [m["nav"] for m in marks], result.equity, rtol=1e-10, atol=1e-12
    )
    np.testing.assert_allclose(
        verification["total_traded"], result.traded, rtol=1e-10, atol=1e-12
    )
    diagnostics = _diagnostics(snapshot, restricted, membership, predictions)
    return PricedExecution(result, journal, verification, diagnostics)
