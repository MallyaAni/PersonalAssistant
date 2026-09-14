"""Observe grades and entry states prospectively, without inventing trade fills."""

import json
import math
import time
from collections import defaultdict
from datetime import timedelta

import numpy as np

from backend.market import (
    calendar,
    desk_freshness,
    forward_actions,
    intraday_evaluation,
)

HORIZONS = (5, 20)
MIN_COHORTS = 20
_cache = {}


# Keep missing and nonpositive valuation evidence out of arithmetic.
def price(row, name):
    value = (row.get("prices") or {}).get(name)
    return (
        float(value)
        if isinstance(value, (int, float)) and math.isfinite(value) and value > 0
        else None
    )


# Aggregate independently spaced decision dates before estimating uncertainty.
def summarize(samples, horizon):
    by_day = defaultdict(list)
    for day, value in samples:
        by_day[day].append(value)
    cohorts = []
    previous = None
    for day in sorted(by_day):
        if (
            previous is None
            or calendar._future_session_offset(
                np.datetime64(previous), np.datetime64(day)
            )
            >= horizon
        ):
            cohorts.append(float(np.mean(by_day[day])))
            previous = day
    mean = float(np.mean(cohorts)) if cohorts else None
    interval = None
    if len(cohorts) >= MIN_COHORTS:
        margin = 1.96 * float(np.std(cohorts, ddof=1)) / math.sqrt(len(cohorts))
        interval = [mean - margin, mean + margin]
    return {
        "observations": len(samples),
        "decision_days": len(by_day),
        "nonoverlapping_cohorts": len(cohorts),
        "mean_excess_return": mean,
        "approximate_95_interval": interval,
        "status": "descriptive_evidence"
        if interval
        else "insufficient_independent_cohorts",
    }


# Find the first recorded close at the matching time on the requested session.
def endpoint(later, local_entry, horizon):
    for row in later:
        close_at = (
            desk_freshness.timestamp(row["bar"]) + timedelta(minutes=15)
        ).astimezone(desk_freshness.NEW_YORK)
        distance = calendar._future_session_offset(
            np.datetime64(local_entry.date()), np.datetime64(close_at.date())
        )
        if distance == horizon and (close_at.hour, close_at.minute) >= (
            local_entry.hour,
            local_entry.minute,
        ):
            return row
    return None


# Use the first daily signal and later observed bars, including wait signals.
def outcomes(decisions, cost_bps=10, corporate_actions=None):
    if not math.isfinite(cost_bps) or not 0 <= cost_bps <= 100:
        raise ValueError("Invalid cost assumption")
    if len({(r.get("version"), r.get("policy_sha256")) for r in decisions}) > 1:
        raise ValueError("Policy versions must be evaluated separately")
    decisions = sorted(decisions, key=lambda r: r["bar"])
    first = {}
    for i, row in enumerate(decisions):
        stamp = desk_freshness.timestamp(row.get("as_of"))
        if stamp:
            first.setdefault(
                stamp.astimezone(desk_freshness.NEW_YORK).date().isoformat(), i
            )
    buckets = defaultdict(list)
    states = defaultdict(list)
    missing = defaultdict(int)
    signals = sum(len(decisions[i].get("grades") or {}) for i in first.values())
    for day, index in first.items():
        signal = decisions[index]
        observed = desk_freshness.timestamp(signal["as_of"])
        deadline = desk_freshness.timestamp(signal.get("valid_until"))
        later = decisions[index + 1 :]
        entry = (
            next(
                (
                    r
                    for r in later
                    if observed
                    < desk_freshness.timestamp(r["bar"]) + timedelta(minutes=15)
                    <= deadline
                ),
                None,
            )
            if deadline
            else None
        )
        for horizon in HORIZONS:
            if entry is None:
                missing[horizon] += len(signal.get("grades") or {})
                continue
            entered_at = desk_freshness.timestamp(entry["bar"]) + timedelta(minutes=15)
            local_entry = entered_at.astimezone(desk_freshness.NEW_YORK)
            exit_row = endpoint(later, local_entry, horizon)
            for name, grade in (signal.get("grades") or {}).items():
                numbers = [
                    price(entry, name),
                    price(exit_row or {}, name),
                    price(entry, "SPY"),
                    price(exit_row or {}, "SPY"),
                ]
                if any(value is None for value in numbers):
                    missing[horizon] += 1
                    continue
                start, end, bench_start, bench_end = numbers
                end_day = forward_actions.session(exit_row["bar"])
                stock_return = forward_actions.total_return(
                    name,
                    start,
                    end,
                    local_entry.date(),
                    end_day,
                    corporate_actions or {},
                )
                benchmark_return = forward_actions.total_return(
                    "SPY",
                    bench_start,
                    bench_end,
                    local_entry.date(),
                    end_day,
                    corporate_actions or {},
                )
                excess = stock_return - benchmark_return - 2 * cost_bps / 10000
                buckets[(grade.get("grade_live", "unknown"), horizon)].append(
                    (day, excess)
                )
                states[
                    (
                        (signal.get("entry_states") or {}).get(name, "unrecorded"),
                        horizon,
                    )
                ].append((day, excess))
    return {
        "signal_count": signals,
        "decision_days": len(first),
        "cost_bps_per_side": cost_bps,
        "missing_or_immature": dict(missing),
        "grades": [
            {"grade": grade, "horizon_sessions": horizon, **summarize(values, horizon)}
            for (grade, horizon), values in sorted(buckets.items())
        ],
        "entry_states": [
            {"state": state, "horizon_sessions": horizon, **summarize(values, horizon)}
            for (state, horizon), values in sorted(states.items())
        ],
        "method": (
            "First daily signal; later observed entry close and first observed "
            "close at or after the same time 5/20 sessions later. Stock total "
            "return less SPY and an additive round-trip cost allowance. Wait "
            "signals included. No actual execution or calibrated profit "
            "probability. Approximate intervals use nonoverlapping date cohorts."
        ),
    }


# Build separate cost-stressed reports for each immutable research-policy version.
def report(root, require_actions=True):
    folder = root / "desk" / "intraday-research"
    signature = folder.stat().st_mtime_ns if folder.exists() else 0
    key = (str(root), require_actions)
    if (
        key in _cache
        and _cache[key][0] == signature
        and time.monotonic() - _cache[key][1] < 60
    ):
        return _cache[key][2]
    groups = defaultdict(list)
    paths = sorted((root / "desk" / "intraday-research").glob("decision-*.json"))
    if len(paths) > 10000:
        return {
            "status": "unavailable",
            "reason": "Archive exceeds the 10,000-record evaluation limit",
        }
    try:
        for path in paths:
            row = json.loads(path.read_text())
            groups[
                (
                    row.get("version", "unversioned"),
                    row.get("policy_sha256", "unidentified"),
                )
            ].append(row)
        versions = []
        for (version, fingerprint), rows in sorted(groups.items()):
            actions, through = {}, None
            eligible = rows
            if require_actions:
                symbols = set().union(*(row["prices"] for row in rows))
                actions, through = forward_actions.load(root, symbols)
                eligible = [
                    row
                    for row in rows
                    if forward_actions.session(row["bar"]).isoformat() <= through
                ]
            versions.append(
                {
                    "version": f"{version} · {fingerprint[:8]}",
                    "decision_count": len(rows),
                    "corporate_actions_through": through,
                    "pending_daily_validation": len(rows) - len(eligible),
                    "outcomes": [
                        outcomes(eligible, cost, actions) for cost in (10, 25)
                    ],
                    "portfolios": [
                        intraday_evaluation.evaluate(eligible, cost, actions)
                        for cost in (10, 25)
                    ],
                }
            )
        result = {
            "status": "collecting_forward_evidence"
            if versions
            else "no_forward_records",
            "versions": versions,
            "promotion": "Research only; no automatic promotion",
            "minimum_cohorts_for_interval": MIN_COHORTS,
        }
        _cache[key] = (signature, time.monotonic(), result)
        return result
    except (ValueError, TypeError, KeyError, OSError):
        return {
            "status": "unavailable",
            "reason": "Invalid or incomplete forward archive",
        }
