"""Source-bound, full-period monetary ratios for isolated offline research.

The caller fixes the concepts, unit, horizon and decision calendar. Currency
codes are checked for shape only; matching labels prove neither currency truth
nor comparable accounting policies. No FX, prices, share counts, persistence,
live consumer, model fit or automatic horizon fallback is involved.

Availability uses the source helper's conservative close-date convention, not
an intraday clock or proof that today's snapshot existed historically. The
latest shared complete interval may be older than either operand's latest
period; both latest ends and the used full interval remain explicit.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from backend.market import fundamental_unit_sources as units
from backend.market import fundamentals_asof as fa

SCHEMA = "fundamental-period-sources/1"
POLICY = "latest_shared_complete_interval"


@dataclass(frozen=True, slots=True)
class RatioDeclaration:
    """Predeclared money/money operands, literal unit and reported horizon."""

    numerator_name: str
    numerator_tag: str
    denominator_name: str
    denominator_tag: str
    unit: str
    period_kind: str
    selection_policy: str = POLICY

    # Reject undeclared dimensions and unsupported horizons before reading observations.
    def __post_init__(self):
        candidates = {
            (name, f"{taxonomy}:{tag}")
            for name, taxonomy, tag, instant in fa._candidates()
            if not instant and name in fa.FLOW_NAMES
        }
        for name, tag in (
            (self.numerator_name, self.numerator_tag),
            (self.denominator_name, self.denominator_tag),
        ):
            if (name, tag) not in candidates:
                raise ValueError("a recognized monetary flow name/tag is required")
        if not (
            isinstance(self.unit, str)
            and len(self.unit) == 3
            and all("A" <= char <= "Z" for char in self.unit)
        ):
            raise ValueError("unit must have a three-uppercase-letter currency shape")
        if self.period_kind not in ("quarter", "year"):
            raise ValueError("period_kind must explicitly be quarter or year")
        if self.selection_policy != POLICY:
            raise ValueError("unsupported period-selection policy")


@dataclass(frozen=True, slots=True, order=True)
class Period:
    """An inclusive fiscal interval whose original monetary unit is retained."""

    start: date
    end: date
    unit: str


@dataclass(frozen=True, slots=True)
class Component:
    """A signed source term; zero marks corroborating duplicate evidence."""

    fact: units.UnitFact
    coefficient: int
    available: date


@dataclass(frozen=True, slots=True)
class PeriodValue:
    """Reported or derived money with its complete source lineage or failure."""

    period: Period
    value: float | None
    method: str
    components: tuple[Component, ...]
    available: date
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Issue:
    """An excluded derivation or operand without an invented quarterly value."""

    operand: str
    reason: str
    period: Period | None = None


@dataclass(frozen=True, slots=True)
class RatioObservation:
    """One dated ratio, both latest horizons, and the exact operands actually used."""

    decision: date
    value: float | None
    period: Period | None
    numerator: PeriodValue | None
    denominator: PeriodValue | None
    numerator_latest_end: date | None
    denominator_latest_end: date | None
    reason: str | None
    issues: tuple[Issue, ...]


@dataclass(frozen=True, slots=True)
class RatioSeries:
    """An immutable result whose source identity does not claim historical truth."""

    source_sha256: str
    cik: int
    declaration: RatioDeclaration
    observations: tuple[RatioObservation, ...]
    schema: str = field(default=SCHEMA, init=False)
    historical_authenticity_verified: bool = field(default=False, init=False)
    strategy_adopted: bool = field(default=False, init=False)


# Order eligible vintages by availability, filed date and known acceptance time.
def _vintage(fact):
    version = fact.version
    accepted = (
        version.accepted.astimezone(UTC)
        if version.accepted is not None
        else datetime.min.replace(tzinfo=UTC)
    )
    return version.available, version.filed, accepted


# Preserve every tied latest filing when the available source cannot choose its value.
def _reported(facts):
    grouped = defaultdict(list)
    for fact in facts:
        version = fact.version
        grouped[Period(version.start, version.end, fact.unit)].append(fact)
    result = {}
    for period, rows in sorted(grouped.items()):
        latest = max(map(_vintage, rows))
        selected = sorted(
            (row for row in rows if _vintage(row) == latest),
            key=lambda row: row.source_path,
        )
        values = {row.version.value for row in selected}
        # Exact source duplicates are evidence, not additional economic amounts.
        components = tuple(
            Component(row, 1 if index == 0 else 0, row.version.available)
            for index, row in enumerate(selected)
        )
        result[period] = PeriodValue(
            period,
            selected[0].version.value if len(values) == 1 else None,
            "reported",
            components,
            latest[0],
            None if len(values) == 1 else "conflicting_latest_vintage",
        )
    return result


# Expand signed evidence, including zero-weight corroborating source observations.
def _terms(value, coefficient):
    return tuple(
        Component(item.fact, coefficient * item.coefficient, item.available)
        for item in value.components
    )


# Calculate from original signed terms so nested rounding cannot change the lineage.
def _derive(period, method, signed_values):
    components = tuple(
        item
        for coefficient, value in signed_values
        for item in _terms(value, coefficient)
    )
    reason = None
    result = None
    if any(value.value is None for _, value in signed_values):
        reason = "unavailable_derivation_component"
    elif any(value.period.unit != period.unit for _, value in signed_values):
        reason = "incompatible_derivation_unit"
    else:
        try:
            result = math.fsum(
                item.coefficient * item.fact.version.value for item in components
            )
        except OverflowError:
            reason = "nonfinite_derivation"
        if result is not None and not math.isfinite(result):
            result, reason = None, "nonfinite_derivation"
    return PeriodValue(
        period,
        result,
        method,
        components,
        max(value.available for _, value in signed_values),
        reason,
    )


# Retain every eligible same-start residual, including competing quarter boundaries.
def _ytd_quarters(reported):
    grouped = defaultdict(list)
    for period, value in reported.items():
        if fa.span_kind(period.start, period.end) in ("quarter", "ytd"):
            grouped[period.start].append(value)
    result = {}
    for spans in grouped.values():
        spans.sort(key=lambda value: value.period.end)
        for index, later in enumerate(spans):
            if fa.span_kind(later.period.start, later.period.end) != "ytd":
                continue
            for earlier in spans[:index]:
                period = Period(
                    earlier.period.end + timedelta(days=1),
                    later.period.end,
                    later.period.unit,
                )
                if fa.span_kind(period.start, period.end) == "quarter":
                    result.setdefault(period, []).append(
                        _derive(period, "ytd_difference", ((1, later), (-1, earlier)))
                    )
    return result


# Keep conflicting derivation routes explicit instead of choosing an arbitrary value.
def _merge_derived(quarters, candidates):
    for period, choices in candidates.items():
        if period in quarters:
            continue
        if len(choices) == 1:
            quarters[period] = choices[0]
        else:
            quarters[period] = PeriodValue(
                period,
                None,
                choices[0].method,
                tuple(item for value in choices for item in value.components),
                max(value.available for value in choices),
                "ambiguous_derivation",
            )


# Require three unambiguous contiguous quarters to partition the annual prefix exactly.
def _annual_quarters(reported, quarters, operand):
    result, issues = {}, []
    for year, annual in reported.items():
        if fa.span_kind(year.start, year.end) != "year":
            continue
        inside = sorted(
            (
                value
                for period, value in quarters.items()
                if year.start <= period.start and period.end < year.end
            ),
            key=lambda value: value.period,
        )
        candidates = []
        for third in inside:
            period = Period(third.period.end + timedelta(days=1), year.end, year.unit)
            if fa.span_kind(period.start, period.end) != "quarter":
                continue
            prefix = [
                value for value in inside if value.period.start <= third.period.end
            ]
            if len(prefix) != 3 or prefix[0].period.start != year.start:
                continue
            if any(
                before.period.end + timedelta(days=1) != after.period.start
                for before, after in zip(prefix, prefix[1:], strict=False)
            ):
                continue
            candidates.append(
                _derive(
                    period,
                    "annual_less_three_quarters",
                    ((1, annual), *((-1, value) for value in prefix)),
                )
            )
        for value in candidates:
            result.setdefault(value.period, []).append(value)
        if not candidates:
            issues.append(
                Issue(operand, "incomplete_or_ambiguous_annual_partition", year)
            )
    return result, issues


# Build the declared horizon and missingness reasons from decision-eligible facts only.
def _operand(source, name, tag, declaration, decision, operand):
    matching = [
        fact
        for fact in source.facts
        if fact.version.available <= decision
        and fact.version.name == name
        and fact.version.tag == tag
    ]
    available = [fact for fact in matching if fact.unit == declaration.unit]
    if not available:
        reason = "no_declared_concept" if not matching else "no_declared_unit"
        return {}, [Issue(operand, reason)]
    reported = _reported(available)
    values = {
        period: value
        for period, value in reported.items()
        if fa.span_kind(period.start, period.end) == declaration.period_kind
    }
    issues = []
    if declaration.period_kind == "quarter":
        _merge_derived(values, _ytd_quarters(reported))
        fourth, issues = _annual_quarters(reported, values, operand)
        _merge_derived(values, fourth)
    if not values:
        issues.append(Issue(operand, f"no_complete_{declaration.period_kind}"))
    return values, issues


# Select the latest shared full interval without hiding alternative spans at that end.
def _observation(source, declaration, decision):
    num, num_issues = _operand(
        source,
        declaration.numerator_name,
        declaration.numerator_tag,
        declaration,
        decision,
        "numerator",
    )
    den, den_issues = _operand(
        source,
        declaration.denominator_name,
        declaration.denominator_tag,
        declaration,
        decision,
        "denominator",
    )
    latest_num = max((period.end for period in num), default=None)
    latest_den = max((period.end for period in den), default=None)
    issues = tuple(num_issues + den_issues)
    common = num.keys() & den.keys()
    period = numerator = denominator = value = None
    reason = "no_shared_complete_interval"
    if common:
        end = max(period.end for period in common)
        selected = [period for period in common if period.end == end]
        num_at_end = [period for period in num if period.end == end]
        den_at_end = [period for period in den if period.end == end]
        if len(selected) != 1 or len(num_at_end) != 1 or len(den_at_end) != 1:
            reason = "ambiguous_period_at_selected_end"
        else:
            period = selected[0]
            numerator, denominator = num[period], den[period]
            reason = numerator.reason or denominator.reason
            if reason is None:
                if denominator.value == 0:
                    reason = "zero_denominator"
                else:
                    value = numerator.value / denominator.value
                    if not math.isfinite(value):
                        value, reason = None, "nonfinite_ratio"
    return RatioObservation(
        decision,
        value,
        period,
        numerator,
        denominator,
        latest_num,
        latest_den,
        reason,
        issues,
    )


# Authenticate the raw source and evaluate the caller's ordered close-date calendar.
def evaluate(
    source: units.UnitSource,
    declaration: RatioDeclaration,
    *,
    decision_dates: tuple[date, ...],
) -> RatioSeries:
    if not isinstance(declaration, RatioDeclaration):
        raise ValueError("RatioDeclaration is required")
    declaration.__post_init__()
    if (
        not isinstance(decision_dates, tuple)
        or not decision_dates
        or any(type(day) is not date for day in decision_dates)
        or any(
            left >= right
            for left, right in zip(decision_dates, decision_dates[1:], strict=False)
        )
    ):
        raise ValueError(
            "decision_dates must be a nonempty strictly increasing date tuple"
        )
    # This public source boundary re-extracts and checks all original bytes and types.
    units.frame(source)
    observations = tuple(
        _observation(source, declaration, day) for day in decision_dates
    )
    return RatioSeries(source.sha256, source.cik, declaration, observations)
