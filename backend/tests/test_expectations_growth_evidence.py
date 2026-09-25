"""Pin reporting-only growth computability without fitting or fetching anything.

Synthetic parsed facts exercise the real legacy EDGAR -> feature block ->
timestamp-bounded dataset path. Its zero-filled model arrays deliberately stay
unchanged: these tests qualify an attached reporting witness, not financial
units, original SEC provenance, historical prevalence or investment returns.
"""

import copy
import re
import socket
import warnings
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from backend.cli import market_expectations as mx
from backend.market import calendar, edgar, valuation
from backend.market.panel import Panel

SOURCE_TIME = datetime(2024, 6, 30, tzinfo=UTC)
FEATURE_DATE = date(2024, 5, 14)
CASES = (
    "true_zero",
    "missing_prior",
    "zero_denominator",
    "missing_current",
    "zero_current",
    "negative_pair",
)
REASONS = (
    "available",
    "missing_prior",
    "nonpositive_prior",
    "missing_current",
    "nonpositive_current",
    "nonpositive_current",
)


# Fail explicitly if a reporting check attempts networking or model training.
@pytest.fixture(autouse=True)
def forbid_network_and_learning(monkeypatch):
    guards = []
    for owner, name in (
        (socket.socket, "connect"),
        (socket, "getaddrinfo"),
        (mx, "_fit_predict"),
        (mx, "_expected"),
        (mx, "_carried"),
    ):
        guard = Mock(side_effect=AssertionError(f"Forbidden boundary: {name}"))
        monkeypatch.setattr(owner, name, guard)
        guards.append(guard)
    yield
    for guard in guards:
        guard.assert_not_called()


# Construct one parsed revenue fact without contacting or emulating a provider.
def revenue(start, end, value, filed):
    return edgar.QuarterFact("revenue", start, end, value, filed)


# Keep the target pair observed while varying the prior feature's information.
def source_record(kind):
    prior_filed = date(2024, 5, 15) if kind == "missing_current" else date(2023, 5, 15)
    facts = [
        revenue(date(2023, 1, 1), date(2023, 3, 31), 100.0, prior_filed),
        revenue(date(2024, 1, 1), date(2024, 3, 31), 110.0, date(2024, 5, 15)),
    ]
    if kind != "missing_current":
        current = {
            "zero_current": 0.0,
            "negative_pair": -100.0,
        }.get(kind, 100.0)
        facts.append(
            revenue(date(2023, 10, 1), date(2023, 12, 31), current, date(2024, 2, 15))
        )
    if kind not in ("missing_prior", "missing_current"):
        prior = (
            0.0
            if kind == "zero_denominator"
            else -100.0
            if kind == "negative_pair"
            else 100.0
        )
        facts.append(
            revenue(date(2022, 10, 1), date(2022, 12, 31), prior, date(2023, 2, 15))
        )
    event = edgar.EarningsEvent(
        datetime(2024, 5, 15, 12, tzinfo=UTC),
        date(2024, 5, 15),
        "synthetic-release",
        "2.02",
    )
    return edgar.CompanyRecord(kind, 1, (event,), tuple(facts), SOURCE_TIME)


# Build genuine feature and dataset arrays from synthetic immutable fact records.
def build_dataset(records=None):
    records = (
        records
        if records is not None
        else {kind: source_record(kind) for kind in CASES}
    )
    _, sessions = calendar.reviewed_sessions()
    dates = np.arange("2022-01-01", "2024-07-01", dtype="datetime64[D]")
    dates = dates[np.is_busday(dates, busdaycal=sessions)]
    tickers = (*records, "SPY")
    prices = np.full((len(dates), len(tickers)), 100.0)
    panel = Panel(
        dates, tickers, prices, prices, prices, prices, prices, prices, {}, "SPY"
    )
    fund = edgar.edgar_features(panel, records, strict_publication=True)
    fidx = {name: index for index, name in enumerate(edgar.FEATURE_NAMES)}
    zero = np.zeros_like(prices)
    multiples = valuation.Multiples(zero, zero, zero, zero, np.ones_like(prices))
    feats, _ = mx._block(
        panel,
        {ticker: "synthetic" for ticker in tickers},
        fund,
        fidx,
        None,
        {},
        {20: zero, 60: zero, 120: zero},
        multiples,
    )
    days = dates.astype(object).tolist()
    quarters = {
        ticker: [(fact.end, fact.value, fact.filed) for fact in record.facts]
        for ticker, record in records.items()
    }
    reactions = {
        ticker: mx._release_windows(days, record) for ticker, record in records.items()
    }
    x, y, meta = mx._dataset(panel, days, quarters, reactions, feats)
    return SimpleNamespace(
        panel=panel, records=records, fund=fund, feats=feats, x=x, y=y, meta=meta
    )


# Reconstruct the original six-case failure through the real source boundaries.
@pytest.fixture
def six_cases():
    dataset = build_dataset()
    assert len(dataset.y) == len(CASES)
    return dataset


# Load the new isolated witness only when its behavior is under examination.
def evidence(dataset, meta=None):
    from backend.market.expectations_reporting import growth_evidence

    return growth_evidence(
        dataset.panel, dataset.records, dataset.meta if meta is None else meta
    )


# Preserve values and read-only arrays around a reporting-only observation.
def freeze_dataset(dataset):
    before = copy.deepcopy(dataset)
    for values in (dataset.x, dataset.y, dataset.fund, dataset.feats):
        values.flags.writeable = False
    return before


# Verify the reporting observer has not changed source facts or model inputs.
def assert_dataset_unchanged(dataset, before):
    for name in ("x", "y", "fund", "feats"):
        np.testing.assert_array_equal(getattr(dataset, name), getattr(before, name))
    assert dataset.meta == before.meta
    assert dataset.records == before.records


# Missing pre-report growth does not imply a missing or zero target report.
def test_six_source_conditions_keep_the_frozen_model_dataset(six_cases):
    ds = six_cases
    np.testing.assert_array_equal(ds.x[:, mx.NAMES.index("revenue_yoy")], np.zeros(6))
    np.testing.assert_allclose(ds.y, np.full(6, 0.1), atol=1e-14, rtol=0)
    assert [ds.panel.tickers[row[0]] for row in ds.meta] == list(CASES)
    feature_dates = [ds.panel.dates[row[4]].astype(object) for row in ds.meta]
    assert feature_dates == [FEATURE_DATE] * 6
    has = edgar.FEATURE_NAMES.index("has_fundamentals")
    indicators = [float(ds.fund[row[4], row[0], has]) for row in ds.meta]
    assert indicators == [1, 1, 1, 0, 1, 1]
    assert "has_fundamentals" not in mx.NAMES
    np.testing.assert_array_equal(np.clip(np.expm1(ds.x[:, 0]), -0.9, 5.0), np.zeros(6))


# A separate aligned witness distinguishes genuine zero from all invalid pairs.
def test_evidence_separates_zero_and_uncomputable_growth_without_mutation(six_cases):
    before = freeze_dataset(six_cases)
    actual = evidence(six_cases)
    np.testing.assert_array_equal(
        actual.latest_revenue, [100, 100, 100, np.nan, 0, -100]
    )
    np.testing.assert_array_equal(
        actual.prior_revenue, [100, np.nan, 0, np.nan, 100, -100]
    )
    np.testing.assert_array_equal(
        actual.usable, [True, False, False, False, False, False]
    )
    assert actual.reason == REASONS
    assert actual.tickers == CASES
    assert actual.feature_dates == (FEATURE_DATE,) * 6
    assert actual.source_times == (SOURCE_TIME,) * 6
    assert_dataset_unchanged(six_cases, before)


# Reordered and repeated observations must keep their own exact source alignment.
def test_evidence_follows_dataset_rows_not_ticker_sort_order(six_cases):
    order = [4, 0, 3, 4, 1]
    meta = [six_cases.meta[index] for index in order]
    original_meta = copy.deepcopy(meta)
    actual = evidence(six_cases, meta)
    assert actual.tickers == tuple(CASES[index] for index in order)
    assert actual.reason == tuple(REASONS[index] for index in order)
    np.testing.assert_array_equal(actual.usable, [False, True, False, False, False])
    assert meta == original_meta


# Missing records have neither an invented operand nor an invented source time.
def test_missing_record_has_no_source_time_or_computable_pair(six_cases):
    del six_cases.records[CASES[0]]
    actual = evidence(six_cases, [six_cases.meta[0]])
    assert actual.reason == ("missing_current",)
    assert actual.source_times == (None,)
    np.testing.assert_array_equal(actual.usable, [False])
    assert np.isnan(actual.latest_revenue[0])
    assert np.isnan(actual.prior_revenue[0])


# An empty dataset yields empty aligned evidence rather than an invented row.
def test_empty_observation_list_has_empty_evidence(six_cases):
    actual = evidence(six_cases, [])
    for values in (actual.latest_revenue, actual.prior_revenue, actual.usable):
        assert values.shape == (0,)
    assert actual.usable.dtype == np.dtype(bool)
    assert actual.reason == actual.tickers == actual.feature_dates == ()
    assert actual.source_times == ()


# The source pair is read at meta's feature close, never at reaction minus one.
def test_evidence_uses_explicit_feature_date_not_reaction_offset(six_cases):
    row = list(six_cases.meta[0])
    row[4] = int(np.searchsorted(six_cases.panel.dates, np.datetime64("2023-02-15")))
    actual = evidence(six_cases, [tuple(row)])
    assert actual.feature_dates == (date(2023, 2, 15),)
    assert actual.reason == ("missing_current",)
    np.testing.assert_array_equal(actual.usable, [False])
    assert np.isnan(actual.latest_revenue[0])
    assert np.isnan(actual.prior_revenue[0])


# A date-only filing is eligible strictly after its day, not on that close.
@pytest.mark.parametrize(
    ("filed", "reason"),
    [
        (date(2024, 5, 13), "available"),
        (date(2024, 5, 14), "missing_prior"),
        (date(2024, 5, 15), "missing_prior"),
    ],
)
def test_growth_witness_respects_strict_publication_day(filed, reason):
    base = source_record("missing_prior")
    earlier = revenue(date(2022, 10, 1), date(2022, 12, 31), 100.0, filed)
    ds = build_dataset({base.ticker: replace(base, facts=(*base.facts, earlier))})
    actual = evidence(ds)
    assert actual.feature_dates == (FEATURE_DATE,)
    assert actual.reason == (reason,)
    assert bool(actual.usable[0]) == (reason == "available")
    assert actual.latest_revenue[0] == 100.0
    if reason == "available":
        assert actual.prior_revenue[0] == 100.0
    else:
        assert np.isnan(actual.prior_revenue[0])


# A later source mutation changes later features but never the earlier witness.
def test_future_filing_cannot_repair_an_earlier_missing_growth():
    base = source_record("missing_prior")
    before = build_dataset({base.ticker: base})
    added = revenue(date(2022, 10, 1), date(2022, 12, 31), 50.0, date(2024, 5, 20))
    after = build_dataset({base.ticker: replace(base, facts=(*base.facts, added))})
    original = evidence(before)
    revised = evidence(after)
    assert original.reason == revised.reason == ("missing_prior",)
    np.testing.assert_array_equal(original.latest_revenue, revised.latest_revenue)
    np.testing.assert_array_equal(original.prior_revenue, revised.prior_revenue)
    np.testing.assert_array_equal(original.usable, revised.usable)
    np.testing.assert_array_equal(before.x, after.x)
    np.testing.assert_array_equal(before.y, after.y)
    assert before.meta == after.meta
    # This explicit later feature proves that the source mutation was effective.
    index = int(np.searchsorted(before.panel.dates, np.datetime64("2024-05-21")))
    feature = mx.NAMES.index("revenue_acceleration")
    assert before.feats[index, 0, feature] != after.feats[index, 0, feature]


# Positive finite operands are insufficient if the legacy quotient overflows.
@pytest.mark.parametrize(("current", "prior"), [(1e308, 1e-308), (1e-308, 1e308)])
def test_growth_evidence_reports_nonfinite_legacy_arithmetic(current, prior):
    base = source_record("true_zero")
    facts = tuple(
        replace(fact, value=current)
        if fact.end == date(2023, 12, 31)
        else replace(fact, value=prior)
        if fact.end == date(2022, 12, 31)
        else fact
        for fact in base.facts
    )
    with np.errstate(over="ignore", under="ignore"):
        ds = build_dataset({base.ticker: replace(base, facts=facts)})
        actual = evidence(ds)
    assert actual.reason == ("nonfinite_legacy_growth",)
    np.testing.assert_array_equal(actual.usable, [False])
    assert actual.latest_revenue[0] == current
    assert actual.prior_revenue[0] == prior
    assert ds.x[0, 0] == 0.0


# Both paired errors use identical finite rows; all-row learner skill is separate.
def test_accuracy_uses_common_rows_and_separate_all_row_learner(capsys):
    expected = np.array([0.0, 0.5, 1.0, np.nan, 4.0, 3.0])
    naive = np.array([0.0, np.nan, 1.0, 2.0, 4.0, np.nan])
    target = np.array([0.0, 0.0, 1.0, 2.0, np.nan, 1.0])
    original = tuple(values.copy() for values in (expected, naive, target))
    mx._accuracy(expected, naive, target, np.full(6, 2024), [2024], None)
    output = capsys.readouterr().out
    assert re.search(r"paired[^\n]*\b2 rows\b", output, re.IGNORECASE)
    assert output.count("MAE 0.000") == 2
    assert "MAE 0.625" in output
    assert "learner (all scorable pairs)" in output
    assert re.search(r"\b4 rows\b", output)
    for values, before in zip((expected, naive, target), original, strict=True):
        np.testing.assert_array_equal(values, before)


# Undefined small-cohort correlations must be reported without invalid reductions.
@pytest.mark.parametrize("size", [0, 1])
def test_accuracy_empty_or_singleton_cohorts_emit_no_runtime_warnings(size, capsys):
    expected = np.arange(size, dtype=float)
    naive = expected.copy()
    target = expected.copy()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mx._accuracy(expected, naive, target, np.full(size, 2024), [2024], None)
    runtime_warnings = [
        warning for warning in caught if issubclass(warning.category, RuntimeWarning)
    ]
    assert not runtime_warnings
    assert capsys.readouterr().out


# Yearly correlations and counts must use the same finite paired population.
def test_accuracy_year_breakdown_uses_common_finite_cohort(capsys):
    expected = np.arange(36, dtype=float)
    naive, target = expected.copy(), expected.copy()
    expected[0], naive[1], target[2] = np.nan, np.nan, np.nan
    expected[1] = 1e6
    before = tuple(values.copy() for values in (expected, naive, target))
    mx._accuracy(expected, naive, target, np.full(36, 2024), [2024], None)
    lines = capsys.readouterr().out.splitlines()
    year = next(line for line in lines if re.search(r"\b2024:", line))
    assert re.search(r"\bn\s+33\b", year)
    assert year.count("+1.000") == 2
    for values, original in zip((expected, naive, target), before, strict=True):
        np.testing.assert_array_equal(values, original)


# Surprise fifths share one mature finite cohort before either ranking is built.
def test_after_report_fifths_use_the_same_mature_finite_cohort(monkeypatch, six_cases):
    panel = six_cases.panel
    count = 34
    expected = np.zeros(count)
    naive = np.full(count, 0.01)
    target = np.arange(count) / 100.0
    expected[0], naive[1], target[2] = np.nan, np.nan, np.nan
    meta = []
    for index in range(count):
        reaction = 200 + index
        published = panel.dates[reaction + int(index == 3)].astype(object)
        meta.append((0, reaction, published.year, published))
    years = np.array([row[2] for row in meta])
    common = np.arange(count) >= 4
    seen = []
    actual_fifths = mx._fifths

    # Exercise the real chronological bucket construction while retaining its mask.
    def observe_fifths(values, mask, *args, **kwargs):
        result = actual_fifths(values, mask, *args, **kwargs)
        seen.append((mask.copy(), result.copy()))
        return result

    monkeypatch.setattr(mx, "_fifths", observe_fifths)
    monkeypatch.setattr(mx, "_spread", Mock(return_value=(0.0, 0.0, 0)))
    before = tuple(values.copy() for values in (expected, naive, target))
    meta_before = copy.deepcopy(meta)
    mx._after(panel, expected, naive, target, meta, years, sorted(set(years)))
    assert len(seen) == 2
    manual = np.zeros((*panel.adj_close.shape, 5), dtype=bool)
    for index in range(28, count):
        manual[meta[index][1] + 1, 0, 4] = True
    for mask, actual in seen:
        np.testing.assert_array_equal(mask, common)
        np.testing.assert_array_equal(actual, manual)
        assert actual.sum() == 6
    for values, previous in zip((expected, naive, target), before, strict=True):
        np.testing.assert_array_equal(values, previous)
    assert meta == meta_before
