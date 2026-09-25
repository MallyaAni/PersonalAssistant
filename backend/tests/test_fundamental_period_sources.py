"""Exact-period monetary ratios without changing the legacy feature path.

The legacy full-period mismatch was reproduced on 2026-09-25 at 6c035a1:
USD revenue 100 for Jan 1–Mar 31 and income 10 for Dec 22–Mar 31 produce
net_margin=0.1 after UnitSource.parse -> project -> features(real Panel).
The strict xfail preserves that unfixed consumer defect.
"""

import hashlib
import json
import math
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime

import numpy as np
import pytest

from backend.market import fundamental_features as ff
from backend.market import fundamental_period_sources as periods
from backend.market import fundamental_unit_sources as units
from backend.market import fundamentals_asof as fa
from backend.market.panel import Panel


# Give each fixture an explicit interval, filing clock, and source accession.
def _row(start, end, value, filed="2025-05-01", accession="filing", **extra):
    return dict(
        start=start,
        end=end,
        val=value,
        filed=filed,
        accn=accession,
        form="10-Q",
        **extra,
    )


# Put both declared concepts into caller-controlled unit groups.
def _payload(revenue, income, revenue_unit="USD", income_unit="USD"):
    return {
        "cik": 1,
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {revenue_unit: revenue}},
                "NetIncomeLoss": {"units": {income_unit: income}},
            }
        },
    }


# Bind fixture observations to exactly the bytes the evaluator must authenticate.
def _source(payload):
    body = json.dumps(payload, allow_nan=False).encode()
    return units.parse(
        body, expected_sha256=hashlib.sha256(body).hexdigest(), expected_cik=1
    )


# Build the actual public feature input rather than imitating the private formula.
def _panel():
    close = np.array([[1.0]])
    return Panel(
        dates=np.array(["2025-05-02"], dtype="datetime64[D]"),
        tickers=("EXAMPLE",),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=close,
        themes={},
        benchmark="EXAMPLE",
    )


# Preserve the public-path failure: equal period ends do not mean equal periods.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Reproduced 2026-09-25 at 6c035a1: UnitSource->project->features returns "
        "0.1 for Dec22-Mar31 income / Jan1-Mar31 revenue; full starts differ"
    ),
)
def test_legacy_same_end_different_start_does_not_become_a_margin():
    source = _source(
        _payload(
            [_row("2025-01-01", "2025-03-31", 100)],
            [_row("2024-12-22", "2025-03-31", 10)],
        )
    )
    result = ff.features(_panel(), {"EXAMPLE": units.project(source).versions})
    margin = result.values[0, 0, result.names.index("net_margin")]
    assert np.isnan(margin), f"Mismatched full periods produced {margin}"


# Retain the independent raw-parser reproduction of discarded currency dimensions.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "2026-09-25 independent legacy-baseline.xml d9c8e5cf: "
        "EUR income / USD revenue produces 0.1 in the unitless legacy feature path"
    ),
)
def test_legacy_mixed_currencies_do_not_become_a_margin():
    payload = _payload(
        [_row("2025-01-01", "2025-03-31", 100)],
        [_row("2025-01-01", "2025-03-31", 10)],
        income_unit="EUR",
    )
    result = ff.features(_panel(), {"EXAMPLE": fa.parse_versions(payload)})
    assert np.isnan(result.feature("net_margin")[0, 0])


# Preserve the legacy annual remainder that silently includes an uncovered week.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "2026-09-25 independent legacy-baseline.xml d9c8e5cf: "
        "gapped Q1/Q2/Q3 partition invents Q4=40"
    ),
)
def test_legacy_gapped_quarters_do_not_support_a_fourth_quarter():
    quarters = {
        (date(2025, 1, 1), date(2025, 3, 31)): 10,
        (date(2025, 4, 8), date(2025, 6, 30)): 20,
        (date(2025, 7, 1), date(2025, 9, 30)): 30,
    }
    assert (
        fa._fourth_quarters(quarters, {(date(2025, 1, 1), date(2025, 12, 31)): 100})
        == {}
    )


# Declare concepts and horizon independently of the number of available source rows.
def _declaration(unit="USD", period_kind="quarter"):
    return periods.RatioDeclaration(
        numerator_name="net_income",
        numerator_tag="us-gaap:NetIncomeLoss",
        denominator_name="revenue",
        denominator_tag="us-gaap:Revenues",
        unit=unit,
        period_kind=period_kind,
    )


# Run the public evaluator at an explicit sequence of close-date decisions.
def _evaluate(payload, *days, declaration=None):
    return periods.evaluate(
        _source(payload),
        declaration or _declaration(),
        decision_dates=tuple(date.fromisoformat(day) for day in days),
    )


# Keep hand-calculated numerator and denominator values on exactly the same interval.
@pytest.mark.parametrize("unit", ["USD", "EUR", "JPY"])
def test_same_currency_full_period_ratio_preserves_original_evidence(unit):
    payload = _payload(
        [_row("2025-01-01", "2025-03-31", 100)],
        [_row("2025-01-01", "2025-03-31", 10)],
        unit,
        unit,
    )
    result = _evaluate(payload, "2025-05-02", declaration=_declaration(unit))
    row = result.observations[0]
    assert row.value == 0.1
    assert row.reason is None
    assert row.period == periods.Period(date(2025, 1, 1), date(2025, 3, 31), unit)
    assert row.numerator_latest_end == row.denominator_latest_end == row.period.end
    assert row.numerator.value == 10
    assert row.denominator.value == 100
    source = _source(payload)
    assert result.source_sha256 == source.sha256
    assert result.cik == 1
    for operand in (row.numerator, row.denominator):
        assert operand.method == "reported"
        assert operand.available == date(2025, 5, 2)
        assert all(item.fact in source.facts for item in operand.components)
        assert all(item.available <= row.decision for item in operand.components)
    assert not result.historical_authenticity_verified
    assert not result.strategy_adopted
    with pytest.raises(FrozenInstanceError):
        row.value = 99


# An equal end date no longer makes unequal starts into a valid monetary ratio.
def test_full_period_mismatch_is_explicitly_unavailable():
    result = _evaluate(
        _payload(
            [_row("2025-01-01", "2025-03-31", 100)],
            [_row("2024-12-22", "2025-03-31", 10)],
        ),
        "2025-05-02",
    ).observations[0]
    assert result.value is None
    assert result.period is None
    assert result.reason == "no_shared_complete_interval"


# Literal unit matching rejects mixed currencies without inventing exchange rates.
@pytest.mark.parametrize("declared", ["USD", "EUR"])
def test_mixed_currency_ratio_is_unavailable(declared):
    result = _evaluate(
        _payload(
            [_row("2025-01-01", "2025-03-31", 100)],
            [_row("2025-01-01", "2025-03-31", 10)],
            income_unit="EUR",
        ),
        "2025-05-02",
        declaration=_declaration(declared),
    ).observations[0]
    assert result.value is None
    assert any(issue.reason == "no_declared_unit" for issue in result.issues)


# Later matching periods expose stale common evidence without pretending it is latest.
def test_older_common_period_exposes_both_latest_operand_ends():
    result = _evaluate(
        _payload(
            [
                _row("2025-01-01", "2025-03-31", 100),
                _row("2025-04-01", "2025-06-30", 200, "2025-08-01"),
            ],
            [_row("2025-01-01", "2025-03-31", 10)],
        ),
        "2025-08-02",
    ).observations[0]
    assert result.value == 0.1
    assert result.period.end == date(2025, 3, 31)
    assert result.numerator_latest_end == date(2025, 3, 31)
    assert result.denominator_latest_end == date(2025, 6, 30)


# Alternative same-end spans cannot be chosen by insertion order or apparent match.
@pytest.mark.parametrize("reverse", [False, True])
def test_same_end_alternative_spans_are_explicitly_ambiguous(reverse):
    revenue = [
        _row("2025-01-01", "2025-03-31", 100),
        _row("2024-12-22", "2025-03-31", 150),
    ]
    result = _evaluate(
        _payload(
            revenue[::-1] if reverse else revenue,
            [_row("2025-01-01", "2025-03-31", 10)],
        ),
        "2025-05-02",
    ).observations[0]
    assert result.value is None
    assert result.period is None
    assert result.reason == "ambiguous_period_at_selected_end"


# Revisions become usable only at their own clock and do not change earlier operands.
def test_future_revisions_preserve_the_earlier_decision_prefix():
    original = _row("2025-01-01", "2025-03-31", 10)
    revenue = [_row("2025-01-01", "2025-03-31", 100)]
    days = ("2025-05-01", "2025-05-02", "2025-05-05", "2025-05-06")
    before = _evaluate(_payload(revenue, [original]), *days)
    after = _evaluate(
        _payload(
            revenue,
            [original, dict(original, val=20, filed="2025-05-05", accn="amended")],
        ),
        *days,
    )
    assert after.observations[:3] == before.observations[:3]
    assert [row.value for row in after.observations] == [None, 0.1, 0.1, 0.2]
    assert (
        after.observations[-1].numerator.components[0].fact.version.accession
        == "amended"
    )


# Future-only concepts cannot change an earlier missingness reason or observation.
def test_future_only_concept_preserves_the_full_earlier_observation():
    income = [_row("2025-01-01", "2025-03-31", 10)]
    future = _row("2025-01-01", "2025-03-31", 100, "2025-06-01")
    before = _evaluate(_payload([], income), "2025-05-02")
    after = _evaluate(_payload([future], income), "2025-05-02")
    assert before.observations == after.observations


# Future compatible units cannot rewrite an earlier unit-mismatch explanation.
def test_future_only_unit_preserves_the_full_earlier_observation():
    payload = _payload(
        [_row("2025-01-01", "2025-03-31", 90)],
        [_row("2025-01-01", "2025-03-31", 10)],
        revenue_unit="EUR",
    )
    before = _evaluate(payload, "2025-05-02")
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"] = [
        _row("2025-01-01", "2025-03-31", 100, "2025-06-01")
    ]
    after = _evaluate(payload, "2025-05-02")
    assert before.observations == after.observations


# Before-close and at-close acceptance boundaries retain their distinct usable dates.
@pytest.mark.parametrize(
    ("accepted", "values"),
    [("2025-05-01T19:59:00Z", [0.1, 0.1]), ("2025-05-01T20:00:00Z", [None, 0.1])],
)
def test_exact_acceptance_boundary_is_not_an_invented_intraday_clock(accepted, values):
    result = _evaluate(
        _payload(
            [_row("2025-01-01", "2025-03-31", 100, accepted=accepted)],
            [_row("2025-01-01", "2025-03-31", 10, accepted=accepted)],
        ),
        "2025-05-01",
        "2025-05-02",
    )
    assert [row.value for row in result.observations] == values


# Source ambiguity at the same vintage does not become an arbitrary accession choice.
def test_conflicting_latest_filings_remain_unavailable():
    original = _row("2025-01-01", "2025-03-31", 10)
    result = _evaluate(
        _payload(
            [dict(original, val=100)], [original, dict(original, val=20, accn="other")]
        ),
        "2025-05-02",
    ).observations[0]
    assert result.value is None
    assert result.reason == "conflicting_latest_vintage"
    assert len(result.numerator.components) == 2


# Repeated equal rows corroborate a value without doubling its economic amount.
def test_duplicate_source_rows_are_zero_weight_corroboration():
    original = _row("2025-01-01", "2025-03-31", 10)
    result = _evaluate(
        _payload([dict(original, val=100)], [original, original]), "2025-05-02"
    ).observations[0]
    assert result.value == 0.1
    assert [term.coefficient for term in result.numerator.components] == [1, 0]
    assert (
        sum(
            term.coefficient * term.fact.version.value
            for term in result.numerator.components
        )
        == 10
    )


# Construct cumulative evidence whose residuals and annual remainder are hand-checkable.
def _cumulative(value_scale=1):
    return [
        _row("2025-01-01", "2025-03-31", 10 * value_scale),
        _row("2025-01-01", "2025-06-30", 30 * value_scale, "2025-08-01", "half"),
        _row("2025-01-01", "2025-09-30", 60 * value_scale, "2025-11-01", "nine"),
        _row("2025-01-01", "2025-12-31", 100 * value_scale, "2026-02-01", "year"),
    ]


# Cumulative subtraction preserves exact residual intervals and every source dependency.
def test_derived_quarters_have_exact_intervals_availability_and_lineage():
    result = _evaluate(
        _payload(_cumulative(10), _cumulative()),
        "2025-08-02",
        "2025-11-02",
        "2026-02-02",
    )
    assert [row.value for row in result.observations] == [0.1, 0.1, 0.1]
    assert [row.numerator.value for row in result.observations] == [20, 30, 40]
    assert [row.period.start for row in result.observations] == [
        date(2025, 4, 1),
        date(2025, 7, 1),
        date(2025, 10, 1),
    ]
    assert [row.numerator.method for row in result.observations] == [
        "ytd_difference",
        "ytd_difference",
        "annual_less_three_quarters",
    ]
    source = _source(_payload(_cumulative(10), _cumulative()))
    for row in result.observations:
        for operand in (row.numerator, row.denominator):
            assert operand.available == max(
                term.available for term in operand.components
            )
            assert all(term.available <= row.decision for term in operand.components)
            assert all(term.fact in source.facts for term in operand.components)
            assert (
                sum(
                    term.coefficient * term.fact.version.value
                    for term in operand.components
                )
                == operand.value
            )


# A late cumulative component cannot leak into an earlier derived quarter.
def test_derived_quarter_waits_for_every_component_and_retains_older_evidence():
    income = _cumulative()[:2]
    income[0] = dict(income[0], filed="2025-08-05")
    result = _evaluate(
        _payload(_cumulative(10)[:2], income), "2025-08-02", "2025-08-06"
    )
    assert result.observations[0].value is None
    assert result.observations[1].value == 0.1
    assert result.observations[1].numerator.available == date(2025, 8, 6)


# Subtraction requires the same fiscal start, not just a roughly six-month total.
def test_different_fiscal_starts_cannot_derive_a_second_quarter():
    income = _cumulative()[:2]
    income[1] = dict(income[1], start="2024-12-29")
    result = _evaluate(
        _payload(_cumulative(10)[:2], income), "2025-08-02"
    ).observations[0]
    assert result.value == 0.1
    assert result.period.end == date(2025, 3, 31)
    assert result.denominator_latest_end == date(2025, 6, 30)
    assert result.numerator_latest_end == date(2025, 3, 31)


# Competing cumulative prefixes must expose both possible residual quarter starts.
def test_competing_cumulative_prefixes_are_not_chosen_by_adjacency():
    revenue = [
        _row("2025-01-01", "2025-03-31", 100),
        _row("2025-01-01", "2025-04-01", 110, accession="alternate"),
        _row("2025-01-01", "2025-06-30", 250, "2025-08-01", "half"),
    ]
    income = [_row("2025-04-02", "2025-06-30", 14, "2025-08-01")]
    result = _evaluate(_payload(revenue, income), "2025-08-02").observations[0]
    assert result.value is None
    assert result.reason == "ambiguous_period_at_selected_end"


# Nested subtraction must reproduce the signed original terms despite cancellation.
def test_nested_derivation_equals_its_independent_scalar_source_lineage():
    income = _cumulative()
    for row, value in zip(income, (1e16, 1, 1, 2), strict=True):
        row["val"] = value
    revenue = [_row("2025-10-01", "2025-12-31", 1, "2026-02-01")]
    result = _evaluate(_payload(revenue, income), "2026-02-02").observations[0]
    scalar = math.fsum(
        term.coefficient * term.fact.version.value
        for term in result.numerator.components
    )
    assert scalar == result.numerator.value == 1
    assert result.value == 1


# Direct disclosures win over conflicting derived values only on the exact same span.
def test_reported_quarter_precedence_is_fixed_even_with_later_cumulative_values():
    income = _cumulative()[:2] + [
        _row("2025-04-01", "2025-06-30", 99, "2025-07-01", "direct")
    ]
    result = _evaluate(
        _payload(_cumulative(10)[:2], income), "2025-08-02"
    ).observations[0]
    assert result.value == 99 / 200
    assert result.numerator.method == "reported"
    assert result.numerator.components[0].fact.version.accession == "direct"


# An annual remainder needs a complete, nonoverlapping three-quarter prefix.
@pytest.mark.parametrize("second_start", ["2025-04-08", "2025-03-29"])
def test_gap_or_overlap_prevents_a_fourth_quarter(second_start):
    income = [
        _row("2025-01-01", "2025-03-31", 10),
        _row(second_start, "2025-06-30", 20, "2025-08-01", "second"),
        _row("2025-07-01", "2025-09-30", 30, "2025-11-01", "third"),
        _cumulative()[-1],
    ]
    result = _evaluate(_payload(_cumulative(10), income), "2026-02-02").observations[0]
    assert result.value == 0.1
    assert result.period.end == date(2025, 9, 30)
    assert result.numerator_latest_end == date(2025, 9, 30)
    assert result.denominator_latest_end == date(2025, 12, 31)
    assert any(
        issue.reason == "incomplete_or_ambiguous_annual_partition"
        for issue in result.issues
    )


# A missing first or middle quarter cannot silently create a full annual partition.
@pytest.mark.parametrize("missing", [0, 1, 2])
def test_missing_quarter_prevents_an_annual_remainder(missing):
    income = [
        _row("2025-01-01", "2025-03-31", 10),
        _row("2025-04-01", "2025-06-30", 20, "2025-08-01", "second"),
        _row("2025-07-01", "2025-09-30", 30, "2025-11-01", "third"),
    ]
    income.pop(missing)
    result = _evaluate(
        _payload(_cumulative(10), income + [_cumulative()[-1]]), "2026-02-02"
    ).observations[0]
    assert result.numerator_latest_end != date(2025, 12, 31)


# The same bytes support a declared annual ratio but no fabricated quarterly ratio.
def test_annual_only_source_requires_an_explicit_annual_horizon():
    payload = _payload([_cumulative(10)[-1]], [_cumulative()[-1]], "EUR", "EUR")
    year = _evaluate(
        payload, "2026-02-02", declaration=_declaration("EUR", "year")
    ).observations[0]
    quarter = _evaluate(
        payload, "2026-02-02", declaration=_declaration("EUR", "quarter")
    ).observations[0]
    assert year.value == 0.1
    assert year.numerator.method == "reported"
    assert year.period == periods.Period(date(2025, 1, 1), date(2025, 12, 31), "EUR")
    assert quarter.value is None
    assert quarter.period is None
    assert any(issue.reason == "no_complete_quarter" for issue in quarter.issues)


# Annual declarations cannot consume reported quarter values or annualize them by four.
def test_quarter_only_source_cannot_satisfy_an_annual_declaration():
    payload = _payload([_cumulative(10)[0]], [_cumulative()[0]])
    result = _evaluate(
        payload, "2025-05-02", declaration=_declaration(period_kind="year")
    ).observations[0]
    assert result.value is None
    assert any(issue.reason == "no_complete_year" for issue in result.issues)


# Genuine zero and signed amounts remain valid while division by zero stays missing.
@pytest.mark.parametrize(
    ("num", "den", "expected", "reason"),
    [
        (0, 100, 0, None),
        (-10, 100, -0.1, None),
        (10, -100, -0.1, None),
        (10, 0, None, "zero_denominator"),
        (1e308, 1e-308, None, "nonfinite_ratio"),
    ],
)
def test_ratio_arithmetic_retains_zero_and_rejects_nonfinite_results(
    num, den, expected, reason
):
    result = _evaluate(
        _payload(
            [_row("2025-01-01", "2025-03-31", den)],
            [_row("2025-01-01", "2025-03-31", num)],
        ),
        "2025-05-02",
    ).observations[0]
    assert result.value == expected
    assert result.reason == reason
    assert result.period is not None
    assert result.numerator is not None


# Even finite raw operands may have an overflowing cumulative difference.
def test_nonfinite_derivation_remains_missing_with_source_lineage():
    income = _cumulative()[:2]
    income[0] = dict(income[0], val=-1e308)
    income[1] = dict(income[1], val=1e308)
    result = _evaluate(
        _payload(_cumulative(10)[:2], income), "2025-08-02"
    ).observations[0]
    assert result.value is None
    assert result.reason == "nonfinite_derivation"
    assert result.numerator.value is None
    assert len(result.numerator.components) == 2


# Larger alternate groups cannot change the caller's fixed concept and unit.
def test_large_alternate_groups_do_not_select_another_tag_or_currency():
    payload = _payload(_cumulative(10)[:1], _cumulative()[:1])
    before = _evaluate(payload, "2025-05-02")
    payload["facts"]["us-gaap"]["Revenues"]["units"]["EUR"] = _cumulative(100)
    payload["facts"]["us-gaap"]["SalesRevenueNet"] = {
        "units": {"USD": _cumulative(999)}
    }
    after = _evaluate(payload, "2025-05-02")
    assert before.observations == after.observations


# Caller edits to values, units, paths or raw bytes fail source binding.
@pytest.mark.parametrize("change", ["value", "unit", "path", "body", "boolean"])
def test_source_tampering_is_rejected_at_evaluation(change):
    source = _source(_payload(_cumulative(10)[:1], _cumulative()[:1]))
    first = source.facts[0]
    if change == "value":
        source = replace(
            source,
            facts=(
                replace(first, version=replace(first.version, value=999)),
                *source.facts[1:],
            ),
        )
    elif change == "unit":
        source = replace(source, facts=(replace(first, unit="EUR"), *source.facts[1:]))
    elif change == "path":
        source = replace(
            source, facts=(replace(first, source_path="/elsewhere"), *source.facts[1:])
        )
    elif change == "boolean":
        source = replace(
            source, facts=(replace(first, row_index=False), *source.facts[1:])
        )
    else:
        source = replace(source, body=source.body + b" ")
    with pytest.raises(ValueError, match="original bytes|source byte hash mismatch"):
        periods.evaluate(source, _declaration(), decision_dates=(date(2025, 5, 2),))


# A monetary-flow declaration cannot be repurposed into EPS, shares or a tag mismatch.
@pytest.mark.parametrize(
    "change",
    [
        dict(numerator_name="eps", numerator_tag="us-gaap:EarningsPerShareDiluted"),
        dict(
            numerator_name="shares",
            numerator_tag="us-gaap:CommonStockSharesOutstanding",
        ),
        dict(numerator_tag="us-gaap:Revenues"),
        dict(unit="USD/shares"),
        dict(unit="eur"),
        dict(unit=" EU"),
        dict(period_kind="ttm"),
        dict(selection_policy="pick_largest"),
    ],
)
def test_declaration_rejects_undeclared_dimensions_and_policies(change):
    with pytest.raises(
        ValueError, match="monetary flow|currency shape|period_kind|policy"
    ):
        replace(_declaration(), **change)


# Decision calendars reject timestamps, unordered dates and duplicate decision rows.
@pytest.mark.parametrize(
    "days",
    [
        [],
        (),
        (datetime(2025, 5, 2, tzinfo=UTC),),
        (date(2025, 5, 2), date(2025, 5, 2)),
        (date(2025, 5, 3), date(2025, 5, 2)),
        ("2025-05-02",),
    ],
)
def test_decision_calendar_requires_explicit_increasing_dates(days):
    source = _source(_payload(_cumulative(10)[:1], _cumulative()[:1]))
    with pytest.raises(ValueError, match="decision_dates"):
        periods.evaluate(source, _declaration(), decision_dates=days)
