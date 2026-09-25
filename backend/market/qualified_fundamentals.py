"""A declared USD quarterly profile built from authenticated source observations.

This profile reads customer-contract revenue excluding assessed tax, never an
automatic substitute for every issuer's revenue definition. It does not certify
principal/agent gross-versus-net treatment, accounting-policy comparability,
constant-currency growth, economic truth or historical source authenticity.

All arithmetic uses the existing unit/full-period source helpers. Original
reported quarter/YTD/year revenue ends form a rejection-only frontier, including
other tags and units. Every scored quarter must end there; older shared periods
cannot stand in for a missing current quarter. Reported quarters remain primary,
but disagreement with a finite same-interval derived path is refused explicitly.
No FX, inferred gross profit, share-valued ratio or productive-assets fallback is
performed. The legacy /2 and reporting-end-only /3 paths are not changed.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np

from backend.market import fundamental_features as ff
from backend.market import fundamental_period_sources as periods
from backend.market import fundamental_unit_sources as units
from backend.market import fundamentals_asof as fa
from backend.market.panel import Panel

PROFILE_ID = "customer-revenue-ex-tax-usd-quarter/1"
SELECTION_POLICY = "reported-quarter-precedence-refuse-derived-disagreement/1"
REVENUE_TAG = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
UNIT = "USD"
MARGINS = (
    ("gross_margin", "gross_profit", "us-gaap:GrossProfit"),
    ("net_margin", "net_income", "us-gaap:NetIncomeLoss"),
    (
        "ocf_to_revenue",
        "operating_cash_flow",
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    ),
    ("capex_to_revenue", "capex", "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"),
)


@dataclass(frozen=True, slots=True)
class QualifiedFeatures:
    """Aligned economic features and JSON-safe evidence at every (T, N) position."""

    features: ff.FundamentalFeatures
    observations: tuple[tuple[dict, ...], ...]
    tickers: tuple[str, ...]
    decision_dates: tuple[str, ...]
    profile_id: str = field(default=PROFILE_ID, init=False)


@dataclass(frozen=True, slots=True)
class _Operand:
    """Safe primary periods plus derivation alternatives hidden by precedence."""

    values: dict
    issues: tuple
    alternatives: dict
    disagreements: tuple


@dataclass(frozen=True, slots=True)
class _Selection:
    """Every candidate at the required end and the reason none may be chosen."""

    operand: _Operand
    candidates: tuple
    reason: str | None


# Serialize a full fiscal interval without silently changing its dimension.
def _period(value):
    return {"start": str(value.start), "end": str(value.end), "unit": value.unit}


# Preserve the original source pointer, unit, filing identity and availability.
def _fact(fact):
    version = fact.version
    return {
        "name": version.name,
        "tag": version.tag,
        "unit": fact.unit,
        "start": str(version.start) if version.start else None,
        "end": str(version.end),
        "value": version.value,
        "filed": str(version.filed),
        "accepted": version.accepted.isoformat() if version.accepted else None,
        "accession": version.accession,
        "form": version.form,
        "available": str(version.available),
        "source_path": fact.source_path,
        "row_index": fact.row_index,
        "duplicate_of": fact.duplicate_of,
    }


# Keep a source-bound reported or computed amount with each signed original term.
def _value(value):
    return {
        "period": _period(value.period),
        "value": value.value,
        "method": value.method,
        "available": str(value.available),
        "reason": value.reason,
        "components": [
            {
                **_fact(component.fact),
                "coefficient": component.coefficient,
                "available": str(component.available),
            }
            for component in value.components
        ],
    }


# Identify economic dependence after cancelling repeated signed source terms.
def _depends_on(value, disputed):
    weights = Counter()
    for component in value.components:
        weights[component.fact.source_path] += component.coefficient
    return any(
        component.coefficient != 0 and weights[component.fact.source_path] != 0
        for component in disputed.components
    )


# Expose competing paths and any disputed reported inputs inside a derived amount.
def _value_evidence(value, operand):
    return {
        **_value(value),
        "competing_derivations": [
            _value(alternative)
            for alternative in operand.alternatives.get(value.period, ())
        ],
        "dependency_disagreements": [
            {
                **_value(disputed),
                "competing_derivations": [
                    _value(alternative)
                    for alternative in operand.alternatives[disputed.period]
                ],
            }
            for disputed in operand.disagreements
            if disputed.period != value.period and _depends_on(value, disputed)
        ],
    }


# Reuse the safe period engine while retaining alternatives its precedence hides.
def _operand(source, name, tag, decision):
    declaration = periods.RatioDeclaration(
        name, tag, "revenue", REVENUE_TAG, UNIT, "quarter"
    )
    values, issues = periods._operand(source, name, tag, declaration, decision, name)
    reported = periods._reported(
        [
            fact
            for fact in source.facts
            if fact.version.name == name
            and fact.version.tag == tag
            and fact.unit == UNIT
            and fact.version.available <= decision
        ]
    )
    alternate = periods._ytd_quarters(reported)
    annual, _ = periods._annual_quarters(reported, values, name)
    for period, choices in annual.items():
        alternate.setdefault(period, []).extend(choices)
    alternatives = {
        period: tuple(choices)
        for period, choices in alternate.items()
        if period in values and values[period].method == "reported"
    }
    disagreements = tuple(
        values[period]
        for period, choices in alternatives.items()
        if values[period].value is not None
        and any(
            choice.value is not None and choice.value != values[period].value
            for choice in choices
        )
    )
    return _Operand(values, tuple(issues), alternatives, disagreements)


# Select exactly one interval at the required end without seeking an older substitute.
def _at_end(operand, end):
    candidates = tuple(
        value for period, value in sorted(operand.values.items()) if period.end == end
    )
    if not candidates:
        declared = next(
            (
                issue.reason
                for issue in operand.issues
                if issue.reason in ("no_declared_concept", "no_declared_unit")
            ),
            None,
        )
        return _Selection(
            operand, (), declared or "no_complete_quarter_at_required_end"
        )
    if len(candidates) != 1:
        return _Selection(operand, candidates, "ambiguous_period_at_required_end")
    value = candidates[0]
    reason = value.reason
    if reason is None and (value.value is None or not math.isfinite(value.value)):
        reason = "unavailable_period_value"
    if reason is None and value in operand.disagreements:
        reason = "reported_derived_disagreement"
    if reason is None and any(
        _depends_on(value, disputed) for disputed in operand.disagreements
    ):
        reason = "disputed_derivation_component"
    return _Selection(operand, candidates, reason)


# Choose the legacy nearest lag end, then refuse ambiguity or invalidity at that end.
def _lag(operand, end, quarters):
    try:
        target = end - timedelta(days=91 * quarters)
    except OverflowError:
        return _Selection(operand, (), "missing_lagged_quarter")
    candidates = {
        period.end for period in operand.values if abs((period.end - target).days) <= 20
    }
    if not candidates:
        return _Selection(operand, (), "missing_lagged_quarter")
    chosen = min(candidates, key=lambda day: (abs((day - target).days), day))
    return _at_end(operand, chosen)


# Keep explicit unavailable reasons and every selected or refused candidate's lineage.
def _feature(value, period, status, selections):
    issues = [
        {
            "operand": issue.operand,
            "reason": issue.reason,
            "period": _period(issue.period) if issue.period else None,
        }
        for selection in selections.values()
        for issue in selection.operand.issues
    ]
    issues.extend(
        {"operand": role, "reason": selection.reason, "period": None}
        for role, selection in selections.items()
        if selection.reason is not None
    )
    return {
        "status": status or "accepted",
        "value": value,
        "period": _period(period) if period is not None and value is not None else None,
        "inputs": {
            role: [
                _value_evidence(item, selection.operand)
                for item in selection.candidates
            ]
            for role, selection in selections.items()
        },
        "issues": issues,
    }


# Calculate same-concept log growth only from finite positive selected quarters.
def _growth(selections, period, acceleration=False):
    reason = next(
        (selection.reason for selection in selections.values() if selection.reason),
        None,
    )
    value = None
    if reason is None:
        amounts = [selection.candidates[0].value for selection in selections.values()]
        if any(amount <= 0 for amount in amounts):
            reason = "nonpositive_growth_input"
        else:
            logs = [math.log(amount) for amount in amounts]
            value = logs[0] - logs[1]
            if acceleration:
                value -= logs[2] - logs[3]
    return _feature(value, period, reason, selections)


# A ratio uses one identical full USD interval and a nonzero revenue denominator.
def _margin(numerator, denominator):
    selections = {"numerator": numerator, "denominator": denominator}
    reason = denominator.reason or numerator.reason
    value = period = None
    if reason is None:
        num, den = numerator.candidates[0], denominator.candidates[0]
        if num.period != den.period:
            reason = "period_mismatch"
        elif den.value == 0:
            reason = "zero_denominator"
        else:
            period = den.period
            value = num.value / den.value
            if not math.isfinite(value):
                value, reason = None, "nonfinite_ratio"
    return _feature(value, period, reason, selections)


# State missing-source evidence without manufacturing any dates, values or lineage.
def _observation_base(ticker, decision, source):
    return {
        "profile_id": PROFILE_ID,
        "selection_policy": SELECTION_POLICY,
        "ticker": ticker,
        "decision": str(decision),
        "source_sha256": source.sha256 if source else None,
        "cik": source.cik if source else None,
        "revenue_tag": REVENUE_TAG,
        "unit": UNIT,
        "period_kind": "quarter",
        "revenue_period_end": None,
        "canonical_latest_quarter_end": None,
        "historical_authenticity_verified": False,
        "source_exclusions": {
            "scope": "whole_source_not_point_in_time",
            "items": [
                {
                    "source_path": item.source_path,
                    "name": item.name,
                    "unit": item.unit,
                    "reason": item.reason,
                    "expected_unit": item.expected_unit,
                }
                for item in source.exclusions
            ]
            if source
            else [],
        },
        "frontier_facts": [],
        "features": {
            name: _feature(None, None, "missing_source", {})
            for name in ff.FEATURE_NAMES
        },
    }


# Bind each feature to the current reported frontier and its declared operands.
def _observation(ticker, decision, source):
    out = _observation_base(ticker, decision, source)
    revenue_facts = [
        fact
        for fact in source.facts
        if fact.version.name == "revenue"
        and fact.version.available <= decision
        and fact.version.end <= decision
    ]
    end = max((fact.version.end for fact in revenue_facts), default=None)
    out["revenue_period_end"] = str(end) if end else None
    out["frontier_facts"] = [
        _fact(fact) for fact in revenue_facts if fact.version.end == end
    ]
    revenue = _operand(source, "revenue", REVENUE_TAG, decision)
    latest = max((period.end for period in revenue.values), default=None)
    out["canonical_latest_quarter_end"] = str(latest) if latest else None
    if end is None:
        out["features"] = {
            name: _feature(None, None, "no_revenue_period", {})
            for name in ff.FEATURE_NAMES
        }
        return out
    q0 = _at_end(revenue, end)
    q1, q4, q5 = (_lag(revenue, end, lag) for lag in (1, 4, 5))
    period = q0.candidates[0].period if len(q0.candidates) == 1 else None
    out["features"] = {
        "revenue_yoy": _growth({"q0": q0, "q4": q4}, period),
        "revenue_qoq": _growth({"q0": q0, "q1": q1}, period),
        "revenue_acceleration": _growth(
            {"q0": q0, "q4": q4, "q1": q1, "q5": q5}, period, True
        ),
    }
    for feature, name, tag in MARGINS:
        out["features"][feature] = _margin(
            _at_end(_operand(source, name, tag, decision), end), q0
        )
    return out


# Reject malformed calendars without hidden reordering or intraday truncation.
def _calendar(panel):
    dates = np.asarray(panel.dates)
    if dates.ndim != 1 or dates.dtype.kind != "M" or len(dates) == 0:
        raise ValueError("a nonempty daily decision calendar is required")
    days = dates.astype("datetime64[D]")
    if (
        np.isnat(days).any()
        or (days[1:] <= days[:-1]).any()
        or not np.array_equal(days, dates)
    ):
        raise ValueError(
            "decision calendar must contain strictly increasing whole dates"
        )
    return days.astype(object)


# Require unique canonical column identities without inferring issuer equivalence.
def _tickers(panel):
    tickers = panel.tickers
    if type(tickers) is not tuple or not tickers:
        raise ValueError("panel tickers must be a nonempty tuple of unique symbols")
    if any(
        not (
            type(ticker) is str
            and 1 <= len(ticker) <= 32
            and ticker[0].isascii()
            and ticker[0].isalnum()
            and all(
                "A" <= char <= "Z" or "0" <= char <= "9" or char in ".-"
                for char in ticker
            )
        )
        for ticker in tickers
    ):
        raise ValueError("panel ticker must be an uppercase symbol, not a path")
    if len(set(tickers)) != len(tickers):
        raise ValueError("panel tickers must be unique")
    return tickers


# Rebuild one ticker's evidence only when new retained flow facts become available.
def _ticker_observations(ticker, source, calendar):
    events = (
        sorted(
            {
                fact.version.available
                for fact in source.facts
                if fact.version.name in fa.FLOW_NAMES
            }
        )
        if source
        else []
    )
    pointer, last_update, cached = 0, None, None
    for row, decision in enumerate(calendar):
        previous = pointer
        while pointer < len(events) and events[pointer] <= decision:
            pointer += 1
        if pointer != previous:
            last_update = row
        if cached is None or pointer != previous:
            cached = (
                _observation(ticker, decision, source)
                if source
                else _observation_base(ticker, decision, None)
            )
        yield (
            {**cached, "decision": str(decision)},
            pointer > 0,
            row - last_update if last_update is not None else np.nan,
        )


# Authenticate each source once and compute only at newly available filing boundaries.
def features(
    panel: Panel, sources_by_ticker: Mapping[str, units.UnitSource | None]
) -> QualifiedFeatures:
    """Return the declared quarterly profile with source evidence for every name.

    Missing sources remain explicit. Malformed or tampered present sources raise
    at the existing original-byte validation boundary. Availability and staleness
    describe retained flow-filing activity, not individual metric freshness.
    """
    calendar, tickers = _calendar(panel), _tickers(panel)
    shape = (len(calendar), len(tickers))
    values = np.full(shape + (len(ff.FEATURE_NAMES),), np.nan)
    ends = np.full(values.shape, np.datetime64("NaT", "D"))
    targets = np.full(shape, np.datetime64("NaT", "D"))
    reasons = np.full(values.shape, "no_revenue_period", dtype="U20")
    available = np.zeros(shape, dtype=bool)
    staleness = np.full(shape, np.nan)
    observations = [[None for _ in tickers] for _ in calendar]
    authenticated = {}
    for column, ticker in enumerate(tickers):
        source = sources_by_ticker.get(ticker)
        if source is not None:
            if id(source) not in authenticated:
                authenticated[id(source)] = units._validated(source)
            source = authenticated[id(source)]
        for row, (observation, seen, age) in enumerate(
            _ticker_observations(ticker, source, calendar)
        ):
            observations[row][column] = observation
            available[row, column] = seen
            staleness[row, column] = age
            if observation["revenue_period_end"] is not None:
                targets[row, column] = np.datetime64(
                    observation["revenue_period_end"], "D"
                )
                reasons[row, column, :] = "not_computable"
            for index, name in enumerate(ff.FEATURE_NAMES):
                item = observation["features"][name]
                if item["status"] == "accepted":
                    values[row, column, index] = item["value"]
                    ends[row, column, index] = np.datetime64(item["period"]["end"], "D")
                    reasons[row, column, index] = "accepted"
    payload = ff.FundamentalFeatures(
        values,
        ff.FEATURE_NAMES,
        available,
        staleness,
        ends,
        ff.PeriodEligibility(targets, ends.copy(), reasons),
    )
    return QualifiedFeatures(
        features=payload,
        observations=tuple(tuple(row) for row in observations),
        tickers=tickers,
        decision_dates=tuple(str(day) for day in calendar),
    )
