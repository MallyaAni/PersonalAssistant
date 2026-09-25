"""A reporting-end safeguard withholds obsolete inputs without replacing them.

These synthetic cases exercise the real legacy calculation and its explicit
current-period wrapper. Equal dates do not qualify erased currencies, economic
tag equivalence, annual arithmetic or historical source authenticity.
"""

from dataclasses import replace
from datetime import UTC, date, datetime

import numpy as np
import pytest

from backend.market import fundamental_features as ff
from backend.market import fundamentals_asof as fa
from backend.market.panel import Panel

REVENUE = "us-gaap:Revenues"
ALTERNATIVE = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
TAGS = {
    "revenue": REVENUE,
    "gross_profit": "us-gaap:GrossProfit",
    "net_income": "us-gaap:NetIncomeLoss",
    "operating_cash_flow": "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    "capex": "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
}
GROWTH = ("revenue_yoy", "revenue_qoq", "revenue_acceleration")
MARGINS = ("gross_margin", "net_margin", "ocf_to_revenue", "capex_to_revenue")


# Declare one stored observation without fetching or inferring additional context.
def _version(name, start, end, value, filed="2026-02-16", tag=None, accepted=None):
    return fa.Version(
        name=name,
        tag=tag or TAGS[name],
        start=date.fromisoformat(start) if start else None,
        end=date.fromisoformat(end),
        value=value,
        filed=date.fromisoformat(filed),
        accepted=accepted,
        accession=f"synthetic-{name}-{end}",
        form="10-Q",
    )


# Supply eight old revenue quarters and all four old matched margin operands.
def _history():
    periods = (
        ("2024-01-01", "2024-03-31", 80.0),
        ("2024-04-01", "2024-06-30", 90.0),
        ("2024-07-01", "2024-09-30", 100.0),
        ("2024-10-01", "2024-12-31", 110.0),
        ("2025-01-01", "2025-03-31", 100.0),
        ("2025-04-01", "2025-06-30", 110.0),
        ("2025-07-01", "2025-09-30", 120.0),
        ("2025-10-01", "2025-12-31", 130.0),
    )
    versions = [_version("revenue", *period) for period in periods]
    versions += [
        _version(name, "2025-10-01", "2025-12-31", value)
        for name, value in (
            ("gross_profit", 39.0),
            ("net_income", 13.0),
            ("operating_cash_flow", 26.0),
            ("capex", 6.5),
        )
    ]
    return versions


# Build a real panel whose prices are irrelevant to the fundamental calculation.
def _panel(days=("2026-05-04",), tickers=("TEST", "SPY")):
    prices = np.ones((len(days), len(tickers)))
    return Panel(
        dates=np.array(days, dtype="datetime64[D]"),
        tickers=tickers,
        open=prices,
        high=prices,
        low=prices,
        close=prices,
        adj_close=prices,
        volume=prices,
        themes={},
        benchmark="SPY",
    )


# Read a named metric's recorded eligibility without changing its values.
def _reason(result, feature, row=0, column=0):
    return result.eligibility.reasons[row, column, result.names.index(feature)]


# Compare every pre-existing tensor exactly, including NaN and NaT bit patterns.
def _assert_same_legacy_fields(left, right):
    assert left.names == right.names
    for name in ("values", "period_ends", "available", "staleness"):
        actual, expected = getattr(left, name), getattr(right, name)
        assert actual.dtype == expected.dtype
        assert actual.shape == expected.shape
        assert actual.tobytes() == expected.tobytes()


# A newer candidate refuses stale selected metrics without borrowing its value.
def test_newer_revenue_candidate_withholds_all_obsolete_selected_metrics():
    panel = _panel()
    versions = _history() + [
        _version(
            "revenue",
            "2026-01-01",
            "2026-03-31",
            99999.0,
            filed="2026-05-01",
            tag=ALTERNATIVE,
        )
    ]
    legacy = ff.features(panel, {"TEST": versions})
    assert np.isfinite(legacy.values[0, 0]).all()
    assert legacy.feature("gross_margin")[0, 0] == 0.3
    current = ff.current_features(panel, {"TEST": versions})
    assert np.isnan(current.values[0, 0]).all()
    assert np.isnat(current.period_ends[0, 0]).all()
    assert (current.eligibility.reasons[0, 0] == "older_revenue_period").all()
    assert current.eligibility.target_period_ends[0, 0] == np.datetime64("2026-03-31")
    np.testing.assert_array_equal(
        current.eligibility.input_period_ends, legacy.period_ends
    )
    np.testing.assert_array_equal(current.available, legacy.available)
    np.testing.assert_array_equal(current.staleness, legacy.staleness)
    _assert_same_legacy_fields(ff.features(panel, {"TEST": versions}), legacy)


# Moving revenue forward must not carry an older shared margin into the new score.
def test_current_growth_survives_while_older_shared_margins_are_withheld():
    versions = _history() + [
        _version("revenue", "2026-01-01", "2026-03-31", 150.0, filed="2026-05-01")
    ]
    panel = _panel()
    legacy = ff.features(panel, {"TEST": versions})
    current = ff.current_features(panel, {"TEST": versions})
    for name in MARGINS:
        assert np.isfinite(legacy.feature(name)[0, 0])
        assert np.isnan(current.feature(name)[0, 0])
        assert _reason(current, name) == "older_revenue_period"
    for name in GROWTH:
        assert current.feature(name)[0, 0] == legacy.feature(name)[0, 0]
        assert current.feature_period(name)[0, 0] == np.datetime64("2026-03-31")
        assert _reason(current, name) == "accepted"


# An incomplete annual report establishes its end without reviving a Q3 ratio.
def test_incomplete_annual_frontier_does_not_reuse_the_latest_computable_quarter():
    versions = [
        _version("revenue", "2025-04-01", "2025-06-30", 100.0),
        _version("revenue", "2025-07-01", "2025-09-30", 120.0),
        _version("revenue", "2025-01-01", "2025-12-31", 500.0),
        _version("gross_profit", "2025-07-01", "2025-09-30", 36.0),
    ]
    legacy = ff.features(_panel(), {"TEST": versions})
    assert legacy.feature("gross_margin")[0, 0] == 0.3
    assert legacy.feature_period("revenue_qoq")[0, 0] == np.datetime64("2025-09-30")
    current = ff.current_features(_panel(), {"TEST": versions})
    assert np.isnan(current.values[0, 0]).all()
    assert current.eligibility.target_period_ends[0, 0] == np.datetime64("2025-12-31")
    assert _reason(current, "gross_margin") == "older_revenue_period"
    assert _reason(current, "revenue_qoq") == "older_revenue_period"
    assert _reason(current, "revenue_yoy") == "not_computable"


# A filing changes eligibility only from the existing availability rule onward.
@pytest.mark.parametrize(
    ("accepted", "first_available"),
    [
        (None, "2026-05-02"),
        (datetime(2026, 5, 1, 19, 59, tzinfo=UTC), "2026-05-01"),
        (datetime(2026, 5, 1, 20, 0, tzinfo=UTC), "2026-05-02"),
    ],
)
def test_late_revenue_evidence_never_changes_earlier_sessions(
    accepted, first_available
):
    panel = _panel(("2026-04-30", "2026-05-01", "2026-05-02", "2026-05-04"))
    original = _history()
    later = _version(
        "revenue",
        "2026-01-01",
        "2026-03-31",
        500.0,
        filed="2026-05-01",
        tag=ALTERNATIVE,
        accepted=accepted,
    )
    before = ff.current_features(panel, {"TEST": original})
    after = ff.current_features(panel, {"TEST": original + [later]})
    earlier = panel.dates < np.datetime64(first_available)
    assert np.isfinite(after.values[earlier, 0]).all()
    assert np.isnan(after.values[~earlier, 0]).all()
    for name in ("values", "period_ends", "available", "staleness"):
        assert (
            getattr(after, name)[earlier].tobytes()
            == getattr(before, name)[earlier].tobytes()
        )
    for name in ("target_period_ends", "input_period_ends", "reasons"):
        np.testing.assert_array_equal(
            getattr(after.eligibility, name)[earlier],
            getattr(before.eligibility, name)[earlier],
        )


# Every recognized reported fiscal span is evidence even when YTD derivation is off.
@pytest.mark.parametrize(
    "end", ["2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31"]
)
@pytest.mark.parametrize("ytd_names", [fa.ALL_YTD_NAMES, frozenset()])
def test_reported_span_frontier_is_independent_of_quarter_derivation(end, ytd_names):
    versions = _history() + [
        _version(
            "revenue", "2026-01-01", end, 500.0, filed="2027-02-01", tag=ALTERNATIVE
        )
    ]
    panel = _panel(("2027-02-02",))
    legacy = ff.features(panel, {"TEST": versions}, ytd_names)
    current = ff.current_features(panel, {"TEST": versions}, ytd_names)
    assert np.isfinite(legacy.values[0, 0]).all()
    assert np.isnan(current.values[0, 0]).all()
    assert current.eligibility.target_period_ends[0, 0] == np.datetime64(end)
    np.testing.assert_array_equal(
        current.eligibility.input_period_ends, legacy.period_ends
    )


# Malformed, nonfinite and non-revenue evidence cannot move the reporting end.
@pytest.mark.parametrize(
    "changes",
    [
        {"start": None},
        {"start": date(2026, 3, 1)},
        {"start": date(2026, 4, 1)},
        {"filed": date(2026, 3, 1)},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": -float("inf")},
        {"accepted": datetime(2026, 5, 1, 15, 0)},
        {"tag": "us-gaap:UnrecognizedRevenue"},
        {"name": "net_income", "tag": "us-gaap:NetIncomeLoss"},
    ],
)
def test_invalid_reported_observations_do_not_establish_a_new_frontier(changes):
    extra = replace(
        _version(
            "revenue",
            "2026-01-01",
            "2026-03-31",
            500.0,
            filed="2026-05-01",
            tag=ALTERNATIVE,
        ),
        **changes,
    )
    versions = _history() + [extra]
    legacy = ff.features(_panel(), {"TEST": versions})
    current = ff.current_features(_panel(), {"TEST": versions})
    assert current.eligibility.target_period_ends[0, 0] == np.datetime64("2025-12-31")
    _assert_same_legacy_fields(current, legacy)


# An impossible early acceptance never becomes valid merely because time passes.
def test_acceptance_before_period_end_stays_rejected_after_filing_and_period_dates():
    extra = _version(
        "revenue",
        "2026-04-01",
        "2026-06-30",
        500.0,
        filed="2026-07-01",
        tag=ALTERNATIVE,
        accepted=datetime(2026, 5, 1, 15, 0, tzinfo=UTC),
    )
    panel = _panel(("2026-05-04", "2026-06-30", "2026-07-02"))
    current = ff.current_features(panel, {"TEST": _history() + [extra]})
    assert np.isfinite(current.values[:, 0]).all()
    np.testing.assert_array_equal(
        current.eligibility.target_period_ends[:, 0],
        np.array(["2025-12-31"] * 3, dtype="datetime64[D]"),
    )


# Compare acceptance against the New York calendar day, not its UTC date label.
@pytest.mark.parametrize(
    ("accepted", "valid"),
    [
        (datetime(2026, 3, 31, 0, 0, tzinfo=UTC), False),
        (datetime(2026, 4, 1, 0, 0, tzinfo=UTC), True),
    ],
)
def test_acceptance_period_guard_uses_new_york_dates(accepted, valid):
    extra = _version(
        "revenue",
        "2026-01-01",
        "2026-03-31",
        500.0,
        filed="2026-04-01",
        tag=ALTERNATIVE,
        accepted=accepted,
    )
    current = ff.current_features(
        _panel(("2026-03-31", "2026-04-01", "2026-05-04")),
        {"TEST": _history() + [extra]},
    )
    assert np.isfinite(current.values[0, 0]).all()
    if valid:
        assert np.isnan(current.values[1:, 0]).all()
        assert (current.eligibility.reasons[1:, 0] == "older_revenue_period").all()
    else:
        assert np.isfinite(current.values[:, 0]).all()
        assert (current.eligibility.reasons[:, 0] == "accepted").all()


# Valid after-hours acceptance can precede the separately assigned filing date.
def test_after_hours_acceptance_keeps_the_existing_next_day_availability():
    extra = _version(
        "revenue",
        "2026-01-01",
        "2026-03-31",
        500.0,
        filed="2026-05-02",
        tag=ALTERNATIVE,
        accepted=datetime(2026, 5, 1, 22, 0, tzinfo=UTC),
    )
    current = ff.current_features(
        _panel(("2026-05-01", "2026-05-02")), {"TEST": _history() + [extra]}
    )
    assert np.isfinite(current.values[0, 0]).all()
    assert np.isnan(current.values[1, 0]).all()
    assert extra.available == date(2026, 5, 2)


# Invalid timestamp objects retain the legacy explicit error rather than gaining a date.
def test_unprocessable_acceptance_does_not_get_a_synthetic_availability():
    extra = _version(
        "revenue",
        "2026-01-01",
        "2026-03-31",
        500.0,
        filed="2026-05-01",
        tag=ALTERNATIVE,
        accepted="not-a-timestamp",
    )
    for calculate in (ff.features, ff.current_features):
        with pytest.raises(AttributeError, match="astimezone"):
            calculate(_panel(), {"TEST": _history() + [extra]})


# A legacy feature pointing beyond the valid reporting end is not accepted either.
def test_future_selected_feature_period_is_explicitly_mismatched():
    future = [
        _version("revenue", "2026-04-01", "2026-06-30", 500.0, filed="2026-05-01"),
        _version("gross_profit", "2026-04-01", "2026-06-30", 100.0, filed="2026-05-01"),
    ]
    versions = _history() + future
    legacy = ff.features(_panel(), {"TEST": versions})
    assert legacy.feature("gross_margin")[0, 0] == 0.2
    current = ff.current_features(_panel(), {"TEST": versions})
    assert np.isnan(current.feature("gross_margin")[0, 0])
    assert np.isnat(current.feature_period("gross_margin")[0, 0])
    assert _reason(current, "gross_margin") == "period_mismatch"
    assert _reason(current, "revenue_yoy") == "period_mismatch"
    assert current.eligibility.input_period_ends[
        0, 0, current.names.index("gross_margin")
    ] == np.datetime64("2026-06-30")
    assert current.eligibility.target_period_ends[0, 0] == np.datetime64("2025-12-31")


# A missing valid reporting end is unknown even when legacy arithmetic is finite.
def test_no_valid_revenue_frontier_withholds_values_and_preserves_input_periods():
    versions = [replace(v, filed=date(2023, 1, 1)) for v in _history()]
    legacy = ff.features(_panel(), {"TEST": versions})
    assert np.isfinite(legacy.values[0, 0]).all()
    current = ff.current_features(_panel(), {"TEST": versions})
    assert np.isnan(current.values[0, 0]).all()
    assert np.isnat(current.eligibility.target_period_ends).all()
    assert (current.eligibility.reasons == "no_revenue_period").all()
    np.testing.assert_array_equal(
        current.eligibility.input_period_ends, legacy.period_ends
    )
    np.testing.assert_array_equal(current.available, legacy.available)


# The accepted safeguard path preserves every original scalar and constructor default.
def test_equal_periods_preserve_legacy_scalars_and_positional_constructor():
    versions = _history()
    original = tuple(versions)
    panel = _panel(("2026-02-17", "2026-05-04", "2036-05-04"))
    legacy = ff.features(panel, {"TEST": versions})
    current = ff.current_features(panel, {"TEST": versions})
    _assert_same_legacy_fields(current, legacy)
    assert tuple(versions) == original
    assert legacy.eligibility is None
    rebuilt = ff.FundamentalFeatures(
        legacy.values,
        legacy.names,
        legacy.available,
        legacy.staleness,
        legacy.period_ends,
    )
    assert rebuilt.eligibility is None
    assert rebuilt.values is legacy.values
    assert rebuilt.period_ends is legacy.period_ends
    assert (current.eligibility.reasons[:, 0] == "accepted").all()
    assert (current.eligibility.reasons[:, 1] == "no_revenue_period").all()
    assert current.feature("gross_margin")[0, 0] == 0.3
    assert current.feature("net_margin")[0, 0] == 0.1
    assert current.feature("ocf_to_revenue")[0, 0] == 0.2
    assert current.feature("capex_to_revenue")[0, 0] == 0.05
    assert current.feature("revenue_yoy")[0, 0] == np.log(130.0) - np.log(110.0)


# Missing evidence remains distinct from a finite zero in each economic column.
@pytest.mark.parametrize("amount", [0.0, -10.0, 10.0])
def test_real_zero_and_negative_margins_are_not_confused_with_missingness(amount):
    versions = [
        _version("revenue", "2025-10-01", "2025-12-31", 100.0),
        _version("gross_profit", "2025-10-01", "2025-12-31", amount),
    ]
    current = ff.current_features(_panel(), {"TEST": versions})
    assert current.feature("gross_margin")[0, 0] == amount / 100.0
    assert _reason(current, "gross_margin") == "accepted"
    for name in ("net_margin", "revenue_yoy", "revenue_qoq"):
        assert np.isnan(current.feature(name)[0, 0])
        assert np.isnat(current.feature_period(name)[0, 0])
        assert _reason(current, name) == "not_computable"


# Erased unit differences remain a documented limitation, not a claimed repair.
def test_same_end_acceptance_does_not_authenticate_legacy_currency_compatibility():
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2025-10-01",
                                "end": "2025-12-31",
                                "val": 100,
                                "filed": "2026-02-16",
                            }
                        ]
                    }
                },
                "GrossProfit": {
                    "units": {
                        "EUR": [
                            {
                                "start": "2025-10-01",
                                "end": "2025-12-31",
                                "val": 20,
                                "filed": "2026-02-16",
                            }
                        ]
                    }
                },
            }
        }
    }
    versions = fa.parse_versions(payload)
    assert all(not hasattr(version, "unit") for version in versions)
    legacy = ff.features(_panel(), {"TEST": versions})
    current = ff.current_features(_panel(), {"TEST": versions})
    _assert_same_legacy_fields(current, legacy)
    assert current.feature("gross_margin")[0, 0] == 0.2
    assert _reason(current, "gross_margin") == "accepted"


# Eligibility aligns all named columns and is independent of observation order.
def test_frontier_alignment_and_results_do_not_depend_on_observation_order():
    stale = _history() + [
        _version(
            "revenue",
            "2026-01-01",
            "2026-03-31",
            500.0,
            filed="2026-05-01",
            tag=ALTERNATIVE,
        )
    ]
    panel = _panel(tickers=("EMPTY", "STALE", "CURRENT", "SPY"))
    one = ff.current_features(panel, {"STALE": stale, "CURRENT": _history()})
    two = ff.current_features(
        panel, {"CURRENT": list(reversed(_history())), "STALE": list(reversed(stale))}
    )
    _assert_same_legacy_fields(one, two)
    for name in ("target_period_ends", "input_period_ends", "reasons"):
        np.testing.assert_array_equal(
            getattr(one.eligibility, name), getattr(two.eligibility, name)
        )
    assert one.eligibility.target_period_ends.shape == (1, 4)
    assert one.eligibility.input_period_ends.shape == (1, 4, len(ff.FEATURE_NAMES))
    assert one.eligibility.reasons.shape == one.values.shape
    assert np.isnat(one.eligibility.target_period_ends[0, [0, 3]]).all()
    assert (one.eligibility.reasons[0, 1] == "older_revenue_period").all()
    assert (one.eligibility.reasons[0, 2] == "accepted").all()
