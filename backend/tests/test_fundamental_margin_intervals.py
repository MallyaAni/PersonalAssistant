"""Current desk margins match retained intervals without changing growth rules.

All sources, prices and stored frames are synthetic. Unit and annual-partition
defects are deliberately not treated as fixed by this interval-alignment change.
"""

import hashlib
import json
from datetime import date

import numpy as np
import pytest

from backend.agents.trading.desk import desk, fundamental
from backend.market import fundamental_features as ff
from backend.market import fundamental_unit_sources as units
from backend.market import fundamentals_asof as fa
from backend.market.panel import Panel
from backend.market.store import MarketStore

MARGINS = (
    ("gross_margin", "GrossProfit"),
    ("net_margin", "NetIncomeLoss"),
    ("ocf_to_revenue", "NetCashProvidedByUsedInOperatingActivities"),
    ("capex_to_revenue", "PaymentsToAcquirePropertyPlantAndEquipment"),
)


# Declare one synthetic filed flow with the complete interval retained in storage.
def _row(start, end, value, filed="2025-05-01", accession="synthetic"):
    return dict(
        start=start, end=end, val=value, filed=filed, accn=accession, form="10-Q"
    )


# Authenticate synthetic USD source bytes before projecting their stored Version values.
def _versions(revenues, numerators, tag="NetIncomeLoss", extra_tags=None):
    tags = {"Revenues": revenues, tag: numerators, **(extra_tags or {})}
    payload = {
        "cik": 1,
        "facts": {
            "us-gaap": {name: {"units": {"USD": rows}} for name, rows in tags.items()}
        },
    }
    body = json.dumps(payload, allow_nan=False).encode()
    source = units.parse(
        body, expected_sha256=hashlib.sha256(body).hexdigest(), expected_cik=1
    )
    return units.project(source).versions


# Build a real aligned panel without fetching prices or invoking a strategy simulation.
def _panel(days=("2025-05-02",), tickers=("TEST", "SPY")):
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


# Exercise the current feature adapter with original source intervals still available.
def _features(
    revenues, numerators, tag="NetIncomeLoss", days=("2025-05-02",), **kwargs
):
    return ff.features(
        _panel(days), {"TEST": _versions(revenues, numerators, tag)}, **kwargs
    )


# Exclude mismatched intervals for every margin, not only net income.
@pytest.mark.parametrize(("feature", "tag"), MARGINS)
def test_each_margin_rejects_same_end_with_different_starts(feature, tag):
    result = _features(
        [_row("2025-01-01", "2025-03-31", 100)],
        [_row("2024-12-22", "2025-03-31", 10)],
        tag,
    )
    assert np.isnan(result.feature(feature)[0, 0])
    assert np.isnat(result.feature_period(feature)[0, 0])
    assert result.available[0, 0]


# Keep compatible positive, negative and genuine zero margins as their actual ratios.
@pytest.mark.parametrize(("feature", "tag"), MARGINS)
@pytest.mark.parametrize("amount", [0.0, 10.0, -10.0])
def test_compatible_margins_preserve_real_values_and_periods(feature, tag, amount):
    result = _features(
        [_row("2025-01-01", "2025-03-31", 100)],
        [_row("2025-01-01", "2025-03-31", amount)],
        tag,
    )
    assert result.feature(feature)[0, 0] == amount / 100
    assert result.feature_period(feature)[0, 0] == np.datetime64("2025-03-31")


# An earlier valid ratio must not conceal mismatched evidence at the latest common end.
@pytest.mark.parametrize(("feature", "tag"), MARGINS)
def test_latest_common_end_mismatch_does_not_fall_back_to_older_match(feature, tag):
    result = _features(
        [_row("2024-10-01", "2024-12-31", 80), _row("2025-01-01", "2025-03-31", 100)],
        [_row("2024-10-01", "2024-12-31", 8), _row("2024-12-22", "2025-03-31", 10)],
        tag,
    )
    assert np.isnan(result.feature(feature)[0, 0])
    assert np.isnat(result.feature_period(feature)[0, 0])
    assert result.feature("revenue_qoq")[0, 0] == pytest.approx(np.log(100 / 80))


# A later period in only one operand retains the older common-period behavior.
@pytest.mark.parametrize(("feature", "tag"), MARGINS)
def test_older_common_end_remains_available_when_other_operand_has_no_new_end(
    feature, tag
):
    result = _features(
        [_row("2024-10-01", "2024-12-31", 80), _row("2025-01-01", "2025-03-31", 100)],
        [_row("2024-10-01", "2024-12-31", 8)],
        tag,
    )
    assert result.feature(feature)[0, 0] == 0.1
    assert result.feature_period(feature)[0, 0] == np.datetime64("2024-12-31")


# One matching interval cannot hide another span at the selected end in either operand.
@pytest.mark.parametrize("operand", ["numerator", "denominator", "both"])
@pytest.mark.parametrize("reverse", [False, True])
def test_ambiguous_same_end_is_unavailable_independent_of_source_order(
    operand, reverse
):
    revenues = [_row("2025-01-01", "2025-03-31", 100)]
    numerators = [_row("2025-01-01", "2025-03-31", 10)]
    if operand in ("denominator", "both"):
        revenues.append(_row("2024-12-22", "2025-03-31", 200))
    if operand in ("numerator", "both"):
        numerators.append(_row("2024-12-22", "2025-03-31", 30))
    if reverse:
        revenues.reverse()
        numerators.reverse()
    result = _features(revenues, numerators)
    assert np.isnan(result.feature("net_margin")[0, 0])
    assert np.isnat(result.feature_period("net_margin")[0, 0])


# A newly available conflicting interval affects only its publication boundary onward.
def test_future_interval_cannot_change_earlier_features_or_missingness():
    revenue = [_row("2025-01-01", "2025-03-31", 100)]
    income = [_row("2025-01-01", "2025-03-31", 10)]
    days = ("2025-05-02", "2025-05-30", "2025-06-02")
    before = _features(revenue, income, days=days)
    after = _features(
        revenue,
        income + [_row("2024-12-22", "2025-03-31", 30, "2025-06-01", "future")],
        days=days,
    )
    assert np.array_equal(before.values[:2], after.values[:2], equal_nan=True)
    assert np.array_equal(
        before.period_ends[:2].view("i8"), after.period_ends[:2].view("i8")
    )
    assert np.array_equal(before.available, after.available)
    assert np.array_equal(before.staleness[:2], after.staleness[:2], equal_nan=True)
    assert np.isnan(after.feature("net_margin")[2, 0])
    assert after.staleness[2, 0] == 0


# Same-start cumulative filings produce the exact residual interval used by the ratio.
@pytest.mark.parametrize(("feature", "tag"), MARGINS)
def test_compatible_ytd_differences_keep_their_existing_values(feature, tag):
    result = _features(
        [
            _row("2025-01-01", "2025-03-31", 100),
            _row("2025-01-01", "2025-06-30", 300, "2025-08-01"),
        ],
        [
            _row("2025-01-01", "2025-03-31", 10),
            _row("2025-01-01", "2025-06-30", 50, "2025-08-01"),
        ],
        tag,
        days=("2025-08-02",),
    )
    assert result.feature(feature)[0, 0] == 0.2
    assert result.feature_period(feature)[0, 0] == np.datetime64("2025-06-30")
    assert result.feature("revenue_qoq")[0, 0] == pytest.approx(np.log(2))


# A reported span and a different derived span at one end are ambiguous for margins.
def test_reported_priority_for_growth_does_not_hide_derived_margin_ambiguity():
    result = _features(
        [
            _row("2025-01-01", "2025-03-31", 100),
            _row("2025-01-01", "2025-06-30", 300, "2025-08-01"),
            _row("2025-04-02", "2025-06-30", 250, "2025-08-01"),
        ],
        [_row("2025-04-02", "2025-06-30", 50, "2025-08-01")],
        days=("2025-08-02",),
    )
    assert np.isnan(result.feature("net_margin")[0, 0])
    assert result.feature("revenue_qoq")[0, 0] == pytest.approx(np.log(250 / 100))


# A zero denominator stays missing and cannot expose an older matching ratio.
def test_zero_current_denominator_stays_missing_without_older_fallback():
    result = _features(
        [_row("2024-10-01", "2024-12-31", 100), _row("2025-01-01", "2025-03-31", 0)],
        [_row("2024-10-01", "2024-12-31", 10), _row("2025-01-01", "2025-03-31", 0)],
    )
    assert np.isnan(result.feature("net_margin")[0, 0])
    assert np.isnat(result.feature_period("net_margin")[0, 0])


# Preserve the existing table-order and available-quarter-count revenue tag choice.
def test_margin_interval_matching_does_not_change_tag_selection_or_growth():
    revenue = [
        _row("2024-10-01", "2024-12-31", 80),
        _row("2025-01-01", "2025-03-31", 100),
    ]
    alternate = [
        _row("2024-07-01", "2024-09-30", 80),
        _row("2024-10-01", "2024-12-31", 90),
        _row("2025-01-01", "2025-03-31", 110),
    ]
    versions = _versions(
        revenue,
        [_row("2025-01-01", "2025-03-31", 11)],
        extra_tags={"RevenueFromContractWithCustomerExcludingAssessedTax": alternate},
    )
    result = ff.features(_panel(), {"TEST": versions})
    assert result.feature("net_margin")[0, 0] == 0.1
    assert result.feature("revenue_qoq")[0, 0] == pytest.approx(np.log(110 / 90))
    assert (
        fa.snapshot_tag("revenue", versions)
        == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    )


# Pin the original by-end projection with explicit raw-span compatibility cases.
@pytest.mark.parametrize(
    "kind", ["reported", "ytd", "disabled_ytd", "priority", "annual", "gapped_annual"]
)
def test_extracted_intervals_preserve_legacy_quarter_projection(kind):
    rows = [_row("2025-01-01", "2025-03-31", 10)]
    expected = {date(2025, 3, 31): 10}
    if kind in ("ytd", "disabled_ytd", "priority"):
        rows.append(_row("2025-01-01", "2025-06-30", 30, "2025-08-01"))
        if kind != "disabled_ytd":
            expected[date(2025, 6, 30)] = 20
        if kind == "priority":
            rows.append(_row("2025-04-02", "2025-06-30", 99, "2025-08-01"))
            expected[date(2025, 6, 30)] = 99
    if kind in ("annual", "gapped_annual"):
        rows += [
            _row(
                "2025-04-08" if kind == "gapped_annual" else "2025-04-01",
                "2025-06-30",
                20,
                "2025-08-01",
            ),
            _row("2025-07-01", "2025-09-30", 30, "2025-11-01"),
            _row("2025-01-01", "2025-12-31", 100, "2026-02-01"),
        ]
        # Pin the old gapped-Q4 bug as unchanged arithmetic, not correct accounting.
        expected.update(
            {date(2025, 6, 30): 20, date(2025, 9, 30): 30, date(2025, 12, 31): 40}
        )
    versions = _versions(rows, [])
    spans = {(version.start, version.end): version for version in versions}
    use_ytd = kind != "disabled_ytd"
    assert fa._quarters(spans, use_ytd) == expected
    intervals, derived = fa._quarter_intervals(spans, use_ytd)
    assert all(start is not None and start < end for start, end in intervals)
    assert intervals[(date(2025, 1, 1), date(2025, 3, 31))] == 10
    if kind in ("ytd", "priority"):
        assert intervals[(date(2025, 4, 1), date(2025, 6, 30))] == 20
        assert (date(2025, 4, 1), date(2025, 6, 30)) in derived
    if kind == "priority":
        assert intervals[(date(2025, 4, 2), date(2025, 6, 30))] == 99


# Prove stored intervals reach the desk, where an invalid margin supplies no leg.
def test_stored_frames_change_actual_fundamental_scoring_without_touching_other_inputs(
    tmp_path,
):
    names = ("INVALID", "VALID_A", "VALID_B", "SPY")
    panel = _panel(tickers=names)
    store = MarketStore(tmp_path / "market")
    asof = date(2025, 5, 2)
    for ticker, previous, current, margin, start in (
        ("INVALID", 50, 100, 40, "2024-12-22"),
        ("VALID_A", 80, 100, 20, "2025-01-01"),
        ("VALID_B", 100, 110, 11, "2025-01-01"),
    ):
        versions = _versions(
            [
                _row("2024-10-01", "2024-12-31", previous),
                _row("2025-01-01", "2025-03-31", current),
            ],
            [_row(start, "2025-03-31", margin)],
            "GrossProfit",
        )
        frame = fa.frame(versions)
        assert fa.versions_from_frame(frame) == list(versions)
        store.write_frame(
            fa.KIND, asof, ticker, frame, {"source": "synthetic interval test"}
        )
    originals = {
        str(path.relative_to(store.root)): path.read_bytes()
        for path in store.root.rglob("*.parquet")
    }
    opinion = desk._fundamental_opinion(store, panel, asof, desk.FUNDAMENTALS_CORRECTED)
    assert np.isnan(opinion.evidence["gross_margin"][0, 0])
    assert np.isnan(opinion.scores[0, 0])
    assert opinion.evidence["revenue_qoq"][0, 0] == pytest.approx(np.log(2))
    assert opinion.scores[0, 1] == pytest.approx(0.75)
    assert opinion.scores[0, 2] == pytest.approx(0.0)
    assert np.isnat(opinion.meta["period_ends"]["gross_margin"][0, 0])
    assert (
        opinion.meta["source"]
        == fundamental.CORRECTED_SOURCE
        == "fundamentals-features/2"
    )
    assert {
        str(path.relative_to(store.root)): path.read_bytes()
        for path in store.root.rglob("*.parquet")
    } == originals
