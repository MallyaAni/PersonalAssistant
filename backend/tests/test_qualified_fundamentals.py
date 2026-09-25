"""Declared USD concepts reach qualified features without losing source evidence."""

import hashlib
import json
import math
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta

import numpy as np
import pytest

from backend.market import fundamental_period_sources as periods
from backend.market import fundamental_unit_sources as units
from backend.market import qualified_fundamentals as qualified
from backend.market.panel import Panel

REVENUE = "RevenueFromContractWithCustomerExcludingAssessedTax"
PERIODS = (
    ("2024-01-01", "2024-03-31", 80.0),
    ("2024-04-01", "2024-06-30", 90.0),
    ("2024-07-01", "2024-09-30", 100.0),
    ("2024-10-01", "2024-12-31", 110.0),
    ("2025-01-01", "2025-03-31", 100.0),
    ("2025-04-01", "2025-06-30", 110.0),
    ("2025-07-01", "2025-09-30", 120.0),
    ("2025-10-01", "2025-12-31", 130.0),
)
MARGINS = (
    ("gross_margin", "GrossProfit"),
    ("net_margin", "NetIncomeLoss"),
    ("ocf_to_revenue", "NetCashProvidedByUsedInOperatingActivities"),
    ("capex_to_revenue", "PaymentsToAcquirePropertyPlantAndEquipment"),
)


# Give every synthetic fact explicit source dates, accession and full fiscal interval.
def _row(start, end, value, filed="2026-02-01", accession="original", **extra):
    return dict(
        start=start,
        end=end,
        val=value,
        filed=filed,
        accn=accession,
        form="10-Q",
        **extra,
    )


# Authenticate precisely the public-source bytes supplied by a test.
def _source(
    revenues, numerators=None, *, revenue_tag=REVENUE, revenue_unit="USD", extra=None
):
    tags = {revenue_tag: {"units": {revenue_unit: revenues}}}
    tags.update(
        {tag: {"units": {"USD": rows}} for tag, rows in (numerators or {}).items()}
    )
    tags.update(extra or {})
    body = json.dumps({"cik": 1, "facts": {"us-gaap": tags}}, allow_nan=False).encode()
    return units.parse(
        body, expected_sha256=hashlib.sha256(body).hexdigest(), expected_cik=1
    )


# Supply ordinary complete quarters without switching the declared revenue concept.
def _revenues():
    return [
        _row(*period, accession=f"quarter-{index}")
        for index, period in enumerate(PERIODS)
    ]


# Construct a real calendar and ticker alignment without reading or using prices.
def _panel(days=("2026-02-02",), tickers=("TEST", "SPY")):
    prices = np.full((len(days), len(tickers)), np.nan)
    return Panel(
        np.array(days, dtype="datetime64[D]"),
        tickers,
        prices,
        prices,
        prices,
        prices,
        prices,
        prices,
        {},
        "SPY",
    )


# Read one feature's complete trace at an explicit panel position.
def _trace(result, feature, row=0, column=0):
    return result.observations[row][column]["features"][feature]


# Supply hand-checkable cumulative observations requiring safe quarterly subtraction.
def _cumulative(scale=1):
    return [
        _row("2025-01-01", "2025-03-31", 10 * scale, accession="q1"),
        _row("2025-01-01", "2025-06-30", 30 * scale, accession="half"),
        _row("2025-01-01", "2025-09-30", 60 * scale, accession="nine"),
        _row("2025-01-01", "2025-12-31", 100 * scale, accession="year"),
    ]


# All seven features use the declared quarter and expose real signed source lineage.
def test_declared_quarters_produce_exact_features_and_json_safe_lineage():
    numerators = {
        tag: [_row("2025-10-01", "2025-12-31", value)]
        for (_, tag), value in zip(MARGINS, (39, 13, 26, 6.5), strict=True)
    }
    source = _source(_revenues(), numerators)
    result = qualified.features(_panel(), {"TEST": source})
    expected = {
        "revenue_yoy": math.log(130) - math.log(110),
        "revenue_qoq": math.log(130) - math.log(120),
        "revenue_acceleration": math.log(130)
        - math.log(110)
        - (math.log(120) - math.log(100)),
        "gross_margin": 0.3,
        "net_margin": 0.1,
        "ocf_to_revenue": 0.2,
        "capex_to_revenue": 0.05,
    }
    for name, value in expected.items():
        assert result.features.feature(name)[0, 0] == pytest.approx(value)
        trace = _trace(result, name)
        assert trace["status"] == "accepted"
        assert trace["period"] == {
            "start": "2025-10-01",
            "end": "2025-12-31",
            "unit": "USD",
        }
        assert result.features.feature_period(name)[0, 0] == np.datetime64("2025-12-31")
        for candidates in trace["inputs"].values():
            for candidate in candidates:
                assert candidate["available"] <= "2026-02-02"
                assert (
                    math.fsum(
                        c["coefficient"] * c["value"] for c in candidate["components"]
                    )
                    == candidate["value"]
                )
                for component in candidate["components"]:
                    assert component["source_path"].startswith("/facts/us-gaap/")
                    assert component["accession"]
                    assert component["unit"] == "USD"
                    assert component["available"] <= "2026-02-02"
    observation = result.observations[0][0]
    assert observation["profile_id"] == result.profile_id == qualified.PROFILE_ID
    assert observation["source_sha256"] == source.sha256
    assert observation["cik"] == 1
    assert observation["historical_authenticity_verified"] is False
    assert (
        json.loads(json.dumps(result.observations, allow_nan=False))[0][0]
        == observation
    )


# Alternative tag definitions never substitute for missing canonical revenue or capex.
@pytest.mark.parametrize(
    "tag",
    [
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
)
def test_noncanonical_revenue_is_frontier_evidence_not_a_monetary_fallback(tag):
    result = qualified.features(
        _panel(), {"TEST": _source(_revenues(), revenue_tag=tag)}
    )
    assert np.isnan(result.features.values[0, 0]).all()
    assert _trace(result, "revenue_qoq")["status"] == "no_declared_concept"
    assert result.observations[0][0]["revenue_period_end"] == "2025-12-31"


# A newer different revenue measure refuses old metrics without replacing them.
def test_newer_other_tag_frontier_prevents_an_old_canonical_quarter_fallback():
    source = _source(
        _revenues()[:-1],
        {"GrossProfit": [_row("2025-07-01", "2025-09-30", 36)]},
        extra={
            "Revenues": {"units": {"USD": [_row("2025-10-01", "2025-12-31", 9999)]}}
        },
    )
    result = qualified.features(_panel(), {"TEST": source})
    assert np.isnan(result.features.values[0, 0]).all()
    assert result.observations[0][0]["canonical_latest_quarter_end"] == "2025-09-30"
    assert (
        _trace(result, "gross_margin")["status"]
        == "no_complete_quarter_at_required_end"
    )


# A missing or mismatched current numerator never revives an older shared ratio.
@pytest.mark.parametrize("kind", ["older", "different_start", "ambiguous"])
@pytest.mark.parametrize(("feature", "tag"), MARGINS)
def test_current_margin_requires_one_identical_full_interval(feature, tag, kind):
    rows = [_row("2025-07-01", "2025-09-30", 12)]
    if kind == "different_start":
        rows.append(_row("2025-09-22", "2025-12-31", 13))
    if kind == "ambiguous":
        rows.extend(
            [_row("2025-10-01", "2025-12-31", 13), _row("2025-09-22", "2025-12-31", 13)]
        )
    result = qualified.features(_panel(), {"TEST": _source(_revenues(), {tag: rows})})
    assert np.isnan(result.features.feature(feature)[0, 0])
    assert (
        _trace(result, feature)["status"]
        == {
            "older": "no_complete_quarter_at_required_end",
            "different_start": "period_mismatch",
            "ambiguous": "ambiguous_period_at_required_end",
        }[kind]
    )
    assert np.isnat(result.features.feature_period(feature)[0, 0])
    assert np.isfinite(result.features.feature("revenue_yoy")[0, 0])


# Literal USD is required even when another dimension has the same dates.
@pytest.mark.parametrize("wrong_unit", ["EUR", "shares", "USD/shares"])
@pytest.mark.parametrize("operand", ["revenue", "numerator"])
def test_wrong_dimensions_cannot_become_qualified_margin_values(wrong_unit, operand):
    kwargs = (
        {"revenue_unit": wrong_unit}
        if operand == "revenue"
        else {
            "extra": {
                "GrossProfit": {
                    "units": {wrong_unit: [_row("2025-10-01", "2025-12-31", 13)]}
                }
            }
        }
    )
    source = _source(
        _revenues(), {"GrossProfit": [_row("2025-10-01", "2025-12-31", 13)]}, **kwargs
    )
    result = qualified.features(_panel(), {"TEST": source})
    assert np.isnan(result.features.feature("gross_margin")[0, 0])
    assert _trace(result, "gross_margin")["status"] == "no_declared_unit"


# Productive-assets spending is not silently relabelled as physical-PPE capex.
def test_productive_assets_are_not_a_capex_fallback():
    source = _source(
        _revenues(),
        {"PaymentsToAcquireProductiveAssets": [_row("2025-10-01", "2025-12-31", 50)]},
    )
    result = qualified.features(_panel(), {"TEST": source})
    assert np.isnan(result.features.feature("capex_to_revenue")[0, 0])
    assert _trace(result, "capex_to_revenue")["status"] == "no_declared_concept"


# Same-end ambiguity is retained in every affected growth lag.
@pytest.mark.parametrize(
    ("index", "affected", "unaffected"),
    [
        (7, ("revenue_yoy", "revenue_qoq", "revenue_acceleration"), ()),
        (6, ("revenue_qoq", "revenue_acceleration"), ("revenue_yoy",)),
        (3, ("revenue_yoy", "revenue_acceleration"), ("revenue_qoq",)),
        (2, ("revenue_acceleration",), ("revenue_yoy", "revenue_qoq")),
    ],
)
def test_growth_refuses_ambiguous_q0_q1_q4_and_q5_intervals(
    index, affected, unaffected
):
    rows = _revenues()
    duplicate = dict(
        rows[index], start=rows[index]["start"][:-2] + "02", accn="different-period"
    )
    result = qualified.features(_panel(), {"TEST": _source(rows + [duplicate])})
    for feature in affected:
        assert np.isnan(result.features.feature(feature)[0, 0])
        assert _trace(result, feature)["status"] == "ambiguous_period_at_required_end"
    for feature in unaffected:
        assert np.isfinite(result.features.feature(feature)[0, 0])


# A missing lag stays missing and cannot be supplied by another revenue concept.
def test_growth_never_stitches_lagged_quarters_from_a_different_tag():
    rows = _revenues()
    old_lag = rows.pop(3)
    source = _source(rows, extra={"Revenues": {"units": {"USD": [old_lag]}}})
    result = qualified.features(_panel(), {"TEST": source})
    assert np.isnan(result.features.feature("revenue_yoy")[0, 0])
    assert _trace(result, "revenue_yoy")["status"] == "missing_lagged_quarter"
    assert np.isfinite(result.features.feature("revenue_qoq")[0, 0])


# A nearer ambiguous lag cannot be replaced by a slightly more distant valid period.
def test_nearest_invalid_lag_never_falls_back_to_another_end_in_the_window():
    rows = _revenues() + [
        _row("2025-07-02", "2025-09-30", 121, accession="ambiguous"),
        _row("2025-06-22", "2025-09-20", 120, accession="nearby"),
    ]
    result = qualified.features(_panel(), {"TEST": _source(rows)})
    trace = _trace(result, "revenue_qoq")
    assert trace["status"] == "ambiguous_period_at_required_end"
    assert len(trace["inputs"]["q1"]) == 2
    assert {item["period"]["end"] for item in trace["inputs"]["q1"]} == {"2025-09-30"}


# The inherited lag convention accepts exactly twenty days, never twenty-one.
@pytest.mark.parametrize("distance", [20, 21])
def test_lag_window_boundary_is_explicit(distance):
    rows = _revenues()
    rows.pop(3)
    end = date(2025, 12, 31) - timedelta(days=91 * 4 + distance)
    rows.append(_row(str(end - timedelta(days=90)), str(end), 110, accession="edge"))
    result = qualified.features(_panel(), {"TEST": _source(rows)})
    trace = _trace(result, "revenue_yoy")
    assert trace["status"] == (
        "accepted" if distance == 20 else "missing_lagged_quarter"
    )


# Safe annual and YTD construction retains all signed original monetary components.
def test_safe_cumulative_derivation_keeps_full_source_terms():
    source = _source(_cumulative(10), {"GrossProfit": _cumulative()})
    result = qualified.features(_panel(), {"TEST": source})
    assert result.features.feature("gross_margin")[0, 0] == 0.1
    denominator = _trace(result, "gross_margin")["inputs"]["denominator"][0]
    assert denominator["method"] == "annual_less_three_quarters"
    assert denominator["value"] == 400
    assert any(item["coefficient"] < 0 for item in denominator["components"])
    assert {item["accession"] for item in denominator["components"]} == {
        "q1",
        "half",
        "nine",
        "year",
    }


# Incomplete or overlapping annual partitions cannot revive an old Q3 ratio.
@pytest.mark.parametrize("kind", ["gap", "overlap", "missing"])
def test_incomplete_annual_partition_does_not_invent_q4_or_fall_back(kind):
    quarters = [
        _row("2025-01-01", "2025-03-31", 100),
        _row("2025-04-01", "2025-06-30", 100),
        _row("2025-07-01", "2025-09-30", 100),
    ]
    if kind == "gap":
        quarters[1]["start"] = "2025-04-08"
    elif kind == "overlap":
        quarters[1]["start"] = "2025-03-25"
    else:
        quarters.pop(0)
    source = _source(
        quarters + [_row("2025-01-01", "2025-12-31", 400)],
        {"GrossProfit": [_row("2025-07-01", "2025-09-30", 30)]},
    )
    result = qualified.features(_panel(), {"TEST": source})
    assert np.isnan(result.features.values[0, 0]).all()
    assert result.observations[0][0]["revenue_period_end"] == "2025-12-31"
    assert any(
        issue["reason"] == "incomplete_or_ambiguous_annual_partition"
        for issue in _trace(result, "revenue_qoq")["issues"]
    )


# Reported quarter precedence never hides a contradictory computed amount.
@pytest.mark.parametrize("route", ["ytd", "annual"])
def test_reported_and_derived_disagreement_is_refused_with_both_paths(route):
    rows = _cumulative(10)
    if route == "ytd":
        rows = rows[:2] + [_row("2025-04-01", "2025-06-30", 999, accession="direct")]
    else:
        rows += [_row("2025-10-01", "2025-12-31", 999, accession="direct")]
    result = qualified.features(_panel(), {"TEST": _source(rows)})
    assert np.isnan(result.features.feature("revenue_qoq")[0, 0])
    trace = _trace(result, "revenue_qoq")
    assert trace["status"] == "reported_derived_disagreement"
    primary = trace["inputs"]["q0"][0]
    assert primary["method"] == "reported"
    assert primary["value"] == 999
    assert primary["competing_derivations"][0]["value"] in (200, 400)
    assert primary["competing_derivations"][0]["components"]


# A derived Q4 cannot use a disputed reported Q2 as though its amount were qualified.
def test_disputed_reported_component_also_refuses_dependent_annual_derivation():
    rows = _cumulative(10) + [
        _row("2025-04-01", "2025-06-30", 999, accession="disputed-q2")
    ]
    result = qualified.features(_panel(), {"TEST": _source(rows)})
    trace = _trace(result, "revenue_qoq")
    assert trace["status"] == "disputed_derivation_component"
    q0 = trace["inputs"]["q0"][0]
    assert q0["method"] == "annual_less_three_quarters"
    disputed = q0["dependency_disagreements"]
    assert len(disputed) == 1
    assert disputed[0]["value"] == 999
    assert disputed[0]["competing_derivations"][0]["value"] == 200


# A signed source term that cancels exactly cannot contaminate an independent value.
def test_disputed_dependency_is_decided_after_signed_source_cancellation():
    source = _source(
        _cumulative(10)
        + [_row("2025-04-01", "2025-06-30", 999, accession="disputed-q2")]
    )
    operand = qualified._operand(
        source, "revenue", qualified.REVENUE_TAG, date(2026, 2, 2)
    )
    disputed = operand.disagreements[0]
    independent = operand.values[
        periods.Period(date(2025, 7, 1), date(2025, 9, 30), "USD")
    ]
    term = disputed.components[0]
    cancelled = replace(
        independent,
        components=independent.components + (term, replace(term, coefficient=-1)),
    )
    assert not qualified._depends_on(cancelled, disputed)
    assert (
        qualified._value_evidence(cancelled, operand)["dependency_disagreements"] == []
    )
    assert qualified._depends_on(
        replace(independent, components=independent.components + (term,)), disputed
    )


# A later contradiction changes eligibility only once its own facts are available.
def test_later_derived_disagreement_preserves_all_earlier_decisions():
    reported = [
        _row("2025-01-01", "2025-03-31", 100, accession="q1"),
        _row("2025-04-01", "2025-06-30", 200, accession="q2"),
    ]
    later = reported + [
        _row("2025-01-01", "2025-06-30", 999, filed="2026-02-05", accession="later")
    ]
    panel = _panel(("2026-02-02", "2026-02-05", "2026-02-06"))
    before, after = [
        qualified.features(panel, {"TEST": _source(rows)}) for rows in (reported, later)
    ]
    np.testing.assert_array_equal(before.features.values[:2], after.features.values[:2])
    for row in (0, 1):
        assert (
            before.observations[row][0]["features"]
            == after.observations[row][0]["features"]
        )
    trace = _trace(after, "revenue_qoq", row=2)
    assert trace["status"] == "reported_derived_disagreement"
    assert trace["inputs"]["q0"][0]["value"] == 200
    alternative = trace["inputs"]["q0"][0]["competing_derivations"][0]
    assert alternative["value"] == 899
    assert alternative["available"] == "2026-02-06"
    assert np.isnan(after.features.feature("revenue_qoq")[2, 0])


# Annual-only revenue remains annual and is never divided into invented quarters.
def test_annual_only_revenue_cannot_become_a_quarter():
    source = _source([_row("2025-01-01", "2025-12-31", 400)])
    result = qualified.features(_panel(), {"TEST": source})
    assert np.isnan(result.features.values[0, 0]).all()
    assert result.observations[0][0]["revenue_period_end"] == "2025-12-31"
    assert result.observations[0][0]["canonical_latest_quarter_end"] is None
    assert (
        _trace(result, "revenue_yoy")["status"] == "no_complete_quarter_at_required_end"
    )


# An agreeing computed route is exposed as a route, not certified corroboration.
def test_agreeing_reported_and_derived_paths_remain_explicit():
    rows = _cumulative(10)[:2] + [
        _row("2025-04-01", "2025-06-30", 200, accession="direct")
    ]
    result = qualified.features(_panel(), {"TEST": _source(rows)})
    trace = _trace(result, "revenue_qoq")
    assert trace["status"] == "accepted"
    assert trace["inputs"]["q0"][0]["method"] == "reported"
    assert trace["inputs"]["q0"][0]["competing_derivations"][0]["value"] == 200
    assert "corroborated" not in json.dumps(result.observations)


# Exact duplicate rows carry zero-weight evidence without doubling their value.
def test_duplicate_source_facts_keep_zero_weight_components():
    row = _row("2025-10-01", "2025-12-31", 13)
    result = qualified.features(
        _panel(), {"TEST": _source(_revenues(), {"GrossProfit": [row, row]})}
    )
    numerator = _trace(result, "gross_margin")["inputs"]["numerator"][0]
    assert result.features.feature("gross_margin")[0, 0] == 0.1
    assert [item["coefficient"] for item in numerator["components"]] == [1, 0]


# Same-vintage conflicting source values cannot be resolved by accession ordering.
def test_conflicting_latest_vintage_stays_unavailable():
    row = _row("2025-10-01", "2025-12-31", 13)
    source = _source(
        _revenues(), {"GrossProfit": [row, dict(row, val=26, accn="other")]}
    )
    result = qualified.features(_panel(), {"TEST": source})
    assert np.isnan(result.features.feature("gross_margin")[0, 0])
    assert _trace(result, "gross_margin")["status"] == "conflicting_latest_vintage"


# Zero and negative valid numerator amounts differ from missing or zero denominators.
@pytest.mark.parametrize("value", [0.0, -13.0, 13.0])
def test_real_zero_and_negative_margins_are_preserved(value):
    result = qualified.features(
        _panel(),
        {
            "TEST": _source(
                _revenues(), {"GrossProfit": [_row("2025-10-01", "2025-12-31", value)]}
            )
        },
    )
    assert result.features.feature("gross_margin")[0, 0] == value / 130
    assert _trace(result, "gross_margin")["status"] == "accepted"


# Growth needs positive inputs, and a zero denominator cannot produce a ratio.
def test_zero_revenue_is_not_a_growth_or_margin_value():
    rows = _revenues()
    rows[-1]["val"] = 0
    result = qualified.features(
        _panel(),
        {"TEST": _source(rows, {"GrossProfit": [_row("2025-10-01", "2025-12-31", 1)]})},
    )
    assert _trace(result, "revenue_yoy")["status"] == "nonpositive_growth_input"
    assert _trace(result, "gross_margin")["status"] == "zero_denominator"
    assert np.isnan(result.features.values[0, 0]).all()


# Nonfinite arithmetic is explicitly unavailable, not serialized as Infinity.
def test_ratio_overflow_is_unavailable_with_original_finite_inputs():
    source = _source(
        [_row("2025-10-01", "2025-12-31", 1e-308)],
        {"GrossProfit": [_row("2025-10-01", "2025-12-31", 1e308)]},
    )
    result = qualified.features(_panel(), {"TEST": source})
    assert _trace(result, "gross_margin")["status"] == "nonfinite_ratio"
    assert np.isnan(result.features.feature("gross_margin")[0, 0])
    json.dumps(result.observations, allow_nan=False)


# Accepted timestamps retain the existing before-close and at-close availability rule.
@pytest.mark.parametrize(
    ("accepted", "visible"),
    [("2025-05-01T19:59:00Z", [True, True]), ("2025-05-01T20:00:00Z", [False, True])],
)
def test_exact_acceptance_boundary_prevents_premature_use(accepted, visible):
    source = _source(
        [_row("2025-01-01", "2025-03-31", 100, filed="2025-05-01", accepted=accepted)],
        {
            "GrossProfit": [
                _row(
                    "2025-01-01",
                    "2025-03-31",
                    10,
                    filed="2025-05-01",
                    accepted=accepted,
                )
            ]
        },
    )
    result = qualified.features(_panel(("2025-05-01", "2025-05-02")), {"TEST": source})
    assert (
        np.isfinite(result.features.feature("gross_margin")[:, 0]).tolist() == visible
    )


# New filings and larger future currency groups cannot alter an earlier economic result.
def test_late_revision_and_future_units_preserve_prior_decisions():
    original = _row("2025-01-01", "2025-03-31", 100, filed="2025-05-01")
    numerator = _row("2025-01-01", "2025-03-31", 10, filed="2025-05-01")
    early = _source([original], {"GrossProfit": [numerator]})
    later = _source(
        [original, dict(original, val=200, filed="2025-05-05", accn="later")],
        {"GrossProfit": [numerator]},
    )
    payload = json.loads(later.body)
    payload["facts"]["us-gaap"][REVENUE]["units"]["EUR"] = [
        dict(original, val=value, filed="2025-06-01", accn=f"eur-{value}")
        for value in range(20)
    ]
    body = json.dumps(payload).encode()
    later = units.parse(
        body, expected_sha256=hashlib.sha256(body).hexdigest(), expected_cik=1
    )
    panel = _panel(("2025-05-01", "2025-05-02", "2025-05-05", "2025-05-06"))
    before, after = [
        qualified.features(panel, {"TEST": source}) for source in (early, later)
    ]
    np.testing.assert_array_equal(before.features.values[:3], after.features.values[:3])
    for old, new in zip(before.observations[:3], after.observations[:3], strict=True):
        assert {k: v for k, v in old[0].items() if k != "source_sha256"} == {
            k: v for k, v in new[0].items() if k != "source_sha256"
        }
    assert after.features.feature("gross_margin")[-1, 0] == 0.05


# Missing sources remain aligned, and original-byte authentication is mandatory.
def test_missing_source_is_explicit_and_tampered_source_is_refused():
    source = _source(_revenues())
    result = qualified.features(
        _panel(tickers=("EMPTY", "TEST", "SPY")), {"TEST": source}
    )
    assert len(result.observations[0]) == 3
    assert _trace(result, "revenue_yoy", column=0)["status"] == "missing_source"
    assert result.observations[0][0]["source_sha256"] is None
    assert np.isnan(result.features.values[0, 0]).all()
    bad = replace(source, facts=source.facts[:-1])
    with pytest.raises(ValueError, match="original bytes"):
        qualified.features(_panel(), {"TEST": bad})


# Each original source is authenticated once, not once per metric and session.
def test_source_validation_is_once_per_source_not_once_per_session(monkeypatch):
    source = _source(_revenues())
    calls = []
    original = units._validated

    # Record actual validations while preserving the real original-byte check.
    def validate(candidate):
        calls.append(candidate)
        return original(candidate)

    monkeypatch.setattr(units, "_validated", validate)
    result = qualified.features(
        _panel(("2026-02-02", "2026-02-03", "2026-02-04")), {"TEST": source}
    )
    assert len(calls) == 1
    np.testing.assert_array_equal(result.features.staleness[:, 0], [0, 1, 2])


# A malformed decision calendar is an explicit caller error, not an implicit reorder.
@pytest.mark.parametrize(
    "days", [("2026-02-02", "2026-02-02"), ("2026-02-03", "2026-02-02"), ("NaT",)]
)
def test_invalid_decision_calendar_is_refused(days):
    with pytest.raises(ValueError, match="calendar"):
        qualified.features(_panel(days), {"TEST": _source(_revenues())})


# Immutable identity anchors cannot follow later edits to mutable evidence dictionaries.
def test_alignment_anchors_preserve_validated_panel_identity():
    result = qualified.features(
        _panel(("2026-02-02", "2026-02-03"), ("BRK.B", "TEST", "SPY")), {}
    )
    assert result.tickers == ("BRK.B", "TEST", "SPY")
    assert result.decision_dates == ("2026-02-02", "2026-02-03")
    result.observations[0][0]["ticker"] = "CHANGED"
    result.observations[0][0]["decision"] = "2026-02-04"
    assert result.tickers[0] == "BRK.B"
    assert result.decision_dates[0] == "2026-02-02"
    with pytest.raises(FrozenInstanceError):
        result.tickers = ("CHANGED",)
    with pytest.raises(FrozenInstanceError):
        result.decision_dates = ("2026-02-04",)


# A qualified column requires a unique canonical symbol, not a coerced or unsafe key.
@pytest.mark.parametrize(
    "tickers",
    [
        (),
        ("TEST", "TEST"),
        ("test",),
        (" TEST",),
        ("TEST ",),
        ("",),
        ("A" * 33,),
        ("../TEST",),
        ("TEST/OTHER",),
        ("TEST\\OTHER",),
        ("ＴＥＳＴ",),
        (".TEST",),
        ("TEST_OTHER",),
        (1,),
        (None,),
        ["TEST"],
    ],
)
def test_invalid_or_duplicate_ticker_identity_is_refused(tickers):
    with pytest.raises(ValueError, match="ticker"):
        qualified.features(_panel(tickers=tickers), {})


# Parser exclusions explain the whole source without becoming dated financial facts.
def test_source_exclusions_are_scoped_and_cannot_advance_the_frontier():
    rows = _revenues()
    invalid = _row("2026-01-01", "2026-03-31", "not-numeric", filed="2026-05-01")
    plain = qualified.features(_panel(), {"TEST": _source(rows)})
    excluded = qualified.features(_panel(), {"TEST": _source(rows + [invalid])})
    np.testing.assert_array_equal(plain.features.values, excluded.features.values)
    observation = excluded.observations[0][0]
    assert observation["revenue_period_end"] == "2025-12-31"
    assert observation["source_exclusions"] == {
        "scope": "whole_source_not_point_in_time",
        "items": [
            {
                "source_path": f"/facts/us-gaap/{REVENUE}/units/USD/8",
                "name": "revenue",
                "unit": "USD",
                "reason": "value_not_numeric",
                "expected_unit": None,
            }
        ],
    }
    assert excluded.observations[0][1]["source_exclusions"] == {
        "scope": "whole_source_not_point_in_time",
        "items": [],
    }
    json.dumps(excluded.observations, allow_nan=False)
