"""Economic unit invariance and causal publication for separate neural inputs."""

from dataclasses import replace
from datetime import UTC, date, datetime

import numpy as np
import pytest

from backend.market import fundamentals_asof as fa
from backend.market import neural_price_basis as nb
from backend.market.panel import Panel
from backend.market.yahoo import CorporateAction, DailyBar, TickerHistory


# Construct dated filing versions without fetching or mutating the production store.
def _version(name, end, value, filed, start=None, accepted=None, accession="original"):
    tag = (
        "us-gaap:CommonStockSharesOutstanding"
        if name == "shares"
        else "us-gaap:Revenues"
    )
    return fa.Version(
        name,
        tag,
        date.fromisoformat(start) if start else None,
        date.fromisoformat(end),
        value,
        date.fromisoformat(filed),
        accepted,
        accession,
        "10-Q",
    )


# Supply four known quarters and a dated share count on their original reported basis.
def _versions():
    spans = (
        ("2025-01-01", "2025-03-31", "2025-05-01"),
        ("2025-04-01", "2025-06-30", "2025-08-01"),
        ("2025-07-01", "2025-09-30", "2025-11-01"),
        ("2025-10-01", "2025-12-31", "2026-02-01"),
    )
    return [
        _version("revenue", end, 100, filed, start=start) for start, end, filed in spans
    ] + [_version("shares", "2025-12-31", 10, "2026-02-01")]


# Build two-column prices and an explicit source/coverage manifest for the stock.
def _inputs(price=100.0, vintage="2026-03-06", actions=(), days=None):
    dates = np.asarray(
        days or ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"],
        dtype="datetime64[D]",
    )
    close = np.column_stack((np.full(len(dates), price), np.full(len(dates), 500.0)))
    panel = Panel(
        dates,
        ("AAA", "SPY"),
        close.copy(),
        close.copy(),
        close.copy(),
        close.copy(),
        close.copy(),
        np.full(close.shape, 1000.0),
        {},
        "SPY",
    )
    source_time = datetime.fromisoformat(vintage + "T23:00:00+00:00")
    bars = tuple(
        DailyBar(day, price, price, price, price, price, 1000)
        for day in [date(2025, 1, 1), *dates.astype(object)]
    )
    history = TickerHistory(
        "AAA", bars, tuple(actions), dates[-1].astype(object), source_time
    )
    basis = nb.PriceBasis(
        "yahoo", source_time, date(2025, 1, 1), date.fromisoformat(vintage), True, True
    )
    return panel, history, basis


# Exercise the public feature builder and return its financial inputs plus receipt.
def _features(inputs, versions=None):
    panel, history, basis = inputs
    audit = {}
    _, values, names = nb.features(
        panel,
        {"AAA": _versions() if versions is None else versions},
        {"AAA": history},
        basis_by_ticker={"AAA": basis},
        audit=audit,
    )
    return values, names, audit


# Later splits must not turn unchanged market capitalization into cheapness.
def test_actual_features_are_invariant_to_a_later_split_price_vintage():
    calendar = np.arange("2025-09-01", "2026-03-07", dtype="datetime64[D]")
    days = calendar[np.is_busday(calendar)].astype(str).tolist()
    before, names, _ = _features(_inputs(days=days))
    after, after_names, audit = _features(
        _inputs(
            price=10,
            vintage="2026-04-01",
            days=days,
            actions=(CorporateAction(date(2026, 3, 20), "split", 10),),
        )
    )
    assert names == after_names
    np.testing.assert_allclose(before, after, equal_nan=True)
    np.testing.assert_allclose(
        np.exp(after[-5:, 0, names.index("log_sales_yield")]), 0.4
    )
    assert np.isfinite(before[-1, 0, :8]).all()
    assert audit["AAA"]["status"] == "aligned"


# Multiple/reverse ratios multiply; identical duplicates do not double-count.
def test_multiple_reverse_and_duplicate_splits():
    actions = (
        CorporateAction(date(2026, 3, 10), "split", 10),
        CorporateAction(date(2026, 3, 10), "split", 10),
        CorporateAction(date(2026, 3, 20), "split", 0.2),
        CorporateAction(date(2026, 3, 25), "dividend", 9),
    )
    raw, names, audit = _features(
        _inputs(price=50, vintage="2026-04-01", actions=actions)
    )
    np.testing.assert_allclose(np.exp(raw[:, 0, names.index("log_sales_yield")]), 0.4)
    assert audit["AAA"]["duplicate_splits_deduplicated"] == 1


# An announced event after the source vintage cannot change that vintage's share units.
def test_future_action_is_excluded_and_reported():
    raw, _, audit = _features(
        _inputs(actions=(CorporateAction(date(2026, 3, 20), "split", 10),))
    )
    baseline, _, _ = _features(_inputs())
    np.testing.assert_allclose(raw, baseline, equal_nan=True)
    assert audit["AAA"]["future_splits_excluded"] == 1


# A later report with the same number can have a different basis date.
def test_reported_end_not_numeric_first_appearance_controls_share_basis():
    inputs = _inputs(
        price=10,
        vintage="2026-03-30",
        days=["2026-03-23", "2026-03-24"],
        actions=(CorporateAction(date(2026, 3, 20), "split", 10),),
    )
    versions = _versions() + [
        _version("shares", "2026-03-21", 10, "2026-03-23", accession="new")
    ]
    raw, names, _ = _features(inputs, versions)
    np.testing.assert_allclose(
        np.exp(raw[:, 0, names.index("log_sales_yield")]), [0.4, 4.0]
    )


# Restated share counts affect only observations after their real publication boundary.
@pytest.mark.parametrize(
    ("accepted", "first_changed"),
    [
        (None, 3),
        (datetime(2026, 3, 4, 20, 59, tzinfo=UTC), 2),
        (datetime(2026, 3, 4, 21, 0, tzinfo=UTC), 3),
    ],
)
def test_causal_restatement_and_timezone_aware_acceptance(accepted, first_changed):
    restated = _version(
        "shares",
        "2025-12-31",
        20,
        "2026-03-04",
        accepted=accepted,
        accession="restatement",
    )
    raw, names, _ = _features(_inputs(), _versions() + [restated])
    yields = np.exp(raw[:, 0, names.index("log_sales_yield")])
    np.testing.assert_allclose(yields[:first_changed], 0.4)
    np.testing.assert_allclose(yields[first_changed:], 0.2)


# A later financial revision must not change the earlier neural feature prefix.
def test_later_revenue_restatement_keeps_earlier_features_identical():
    original, names, _ = _features(_inputs())
    later = _version(
        "revenue",
        "2025-12-31",
        200,
        "2026-03-04",
        start="2025-10-01",
        accession="restated",
    )
    changed, _, _ = _features(_inputs(), _versions() + [later])
    np.testing.assert_allclose(original[:3], changed[:3], equal_nan=True)
    np.testing.assert_allclose(
        np.exp(changed[3:, 0, names.index("log_sales_yield")]), 0.5
    )


# Counts before source coverage cannot assume that no earlier split occurred.
def test_share_period_before_source_coverage_stays_missing():
    versions = _versions()
    versions[-1] = replace(versions[-1], end=date(2024, 12, 31))
    raw, names, audit = _features(_inputs(), versions)
    assert np.isnan(raw[:, 0, names.index("log_sales_yield")]).all()
    assert audit["AAA"]["share_versions_unavailable"] == 1
    assert audit["AAA"]["share_sessions_available"] == 0


# Unknown corporate-action completeness and ADR/currency units mask features explicitly.
@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("actions_complete", "corporate-action coverage unverified"),
        (
            "fundamental_units_verified",
            "fundamental currency/share/ADR units unverified",
        ),
    ],
)
def test_unverified_coverage_or_units_are_not_silently_assumed(field, reason):
    panel, history, basis = _inputs()
    raw, _, audit = _features((panel, history, replace(basis, **{field: False})))
    assert np.isnan(raw[:, 0, 8:]).all()
    assert audit["AAA"]["reason"] == reason


# Missing manifests remain an observable absence of financial evidence.
def test_missing_manifest_masks_fundamentals():
    panel, history, _ = _inputs()
    audit = {}
    _, raw, _ = nb.features(
        panel, {"AAA": _versions()}, {"AAA": history}, basis_by_ticker={}, audit=audit
    )
    assert np.isnan(raw[:, :, 8:]).all()
    assert audit["AAA"]["reason"] == "missing price-basis evidence"


# Supplied source identity, dates and price values must agree before reconciliation.
@pytest.mark.parametrize(
    ("defect", "match"),
    [
        ("symbol", "source/symbol"),
        ("source", "source/symbol"),
        ("vintage", "vintage mismatch"),
        ("close", "panel close differs"),
        ("duplicate_bar", "duplicate source price"),
        ("coverage_start", "first source bar"),
        ("coverage_end", "end at price vintage"),
        ("basis", "unsupported price basis"),
    ],
)
def test_inconsistent_provenance_is_rejected(defect, match):
    panel, history, basis = _inputs()
    if defect == "symbol":
        history = replace(history, ticker="OTHER")
    elif defect == "source":
        basis = replace(basis, source="other")
    elif defect == "vintage":
        basis = replace(basis, source_time=datetime(2026, 3, 7, tzinfo=UTC))
    elif defect == "close":
        changed = panel.close.copy()
        changed[0, 0] = 99
        panel = replace(panel, close=changed)
    elif defect == "duplicate_bar":
        history = replace(history, bars=history.bars + (history.bars[-1],))
    elif defect == "coverage_start":
        basis = replace(basis, action_coverage_start=date(2024, 1, 1))
    elif defect == "coverage_end":
        basis = replace(basis, action_coverage_end=date(2026, 3, 7))
    else:
        basis = replace(basis, price_basis="unadjusted")
    with pytest.raises(ValueError, match=match):
        _features((panel, history, basis))


# Conflicting, invalid or uncovered actions cannot become an estimated split factor.
@pytest.mark.parametrize(
    ("actions", "match"),
    [
        (
            (
                CorporateAction(date(2026, 3, 1), "split", 2),
                CorporateAction(date(2026, 3, 1), "split", 3),
            ),
            "conflicting",
        ),
        ((CorporateAction(date(2026, 3, 1), "split", 0),), "finite and positive"),
        ((CorporateAction(date(2026, 3, 1), "split", np.nan),), "finite and positive"),
        ((CorporateAction(date(2024, 3, 1), "split", 2),), "outside declared"),
    ],
)
def test_invalid_actions_fail_closed(actions, match):
    with pytest.raises(ValueError, match=match):
        _features(_inputs(actions=actions))


# A naive acceptance time cannot inherit an arbitrary host timezone.
def test_naive_acceptance_timestamp_is_rejected():
    versions = _versions()
    versions[-1] = replace(versions[-1], accepted=datetime(2026, 2, 1, 12))
    with pytest.raises(ValueError, match="filing acceptance must be timezone aware"):
        _features(_inputs(), versions)


# Duration facts cannot be silently treated as outstanding shares at period end.
def test_share_duration_is_rejected():
    versions = _versions()
    versions[-1] = replace(versions[-1], start=date(2025, 10, 1))
    with pytest.raises(ValueError, match="Share facts must describe an instant"):
        _features(_inputs(), versions)


# The snapshot's own completion marker must cover every supplied price bar.
def test_incomplete_source_price_session_is_rejected():
    panel, history, basis = _inputs()
    history = replace(history, complete_through=date(2026, 3, 5))
    with pytest.raises(ValueError, match="incomplete price session"):
        _features((panel, history, basis))


# The 13:00 early close controls acceptance without changing the frozen selector.
@pytest.mark.parametrize(
    ("accepted", "first_yield"),
    [
        (datetime(2026, 11, 27, 17, 59, tzinfo=UTC), 0.2),
        (datetime(2026, 11, 27, 18, 0, tzinfo=UTC), 0.4),
        (datetime(2026, 11, 27, 19, 0, tzinfo=UTC), 0.4),
    ],
)
def test_early_close_publication_boundary_preserves_original_timestamp(
    accepted, first_yield
):
    inputs = _inputs(vintage="2026-11-30", days=["2026-11-27", "2026-11-30"])
    revision = _version(
        "shares", "2025-12-31", 20, "2026-11-27", accepted=accepted, accession="late"
    )
    raw, names, audit = _features(inputs, _versions() + [revision])
    np.testing.assert_allclose(
        np.exp(raw[:, 0, names.index("log_sales_yield")]), [first_yield, 0.2]
    )
    assert revision.accepted == accepted
    assert audit["AAA"]["availability"] == "reviewed-exchange-close-or-next-day"


# Learned adjusted prices and volume must match their source, including the benchmark.
@pytest.mark.parametrize("field", ["adj_close", "volume"])
@pytest.mark.parametrize("symbol", ["AAA", "SPY"])
def test_consumed_model_fields_match_source_for_stock_and_benchmark(field, symbol):
    panel, history, basis = _inputs()
    histories = {"AAA": history}
    manifests = {"AAA": basis}
    if symbol == "SPY":
        histories["SPY"] = replace(
            history,
            ticker="SPY",
            bars=tuple(
                replace(bar, open=500, high=500, low=500, close=500, adjusted_close=500)
                for bar in history.bars
            ),
        )
        manifests["SPY"] = basis
    changed = getattr(panel, field).copy()
    changed[-1, panel.index(symbol)] *= 2
    panel = replace(panel, **{field: changed})
    with pytest.raises(ValueError, match=f"{symbol}: panel {field} differs"):
        nb.features(panel, {"AAA": _versions()}, histories, basis_by_ticker=manifests)


# A historical count republished after a split lacks evidence of its share-unit basis.
@pytest.mark.parametrize("value", [10, 100])
@pytest.mark.parametrize("filed", ["2026-03-20", "2026-03-23"])
def test_postsplit_historical_share_facts_are_masked_without_inferred_basis(
    value, filed
):
    inputs = _inputs(
        price=10,
        vintage="2026-03-30",
        days=["2026-03-19", "2026-03-20", "2026-03-23", "2026-03-24"],
        actions=(CorporateAction(date(2026, 3, 20), "split", 10),),
    )
    revision = _version(
        "shares", "2025-12-31", value, filed, accession="ambiguous-revision"
    )
    raw, names, audit = _features(inputs, _versions() + [revision])
    yield_ = raw[:, 0, names.index("log_sales_yield")]
    available = inputs[0].dates > np.datetime64(filed)
    np.testing.assert_allclose(np.exp(yield_[~available]), 0.4)
    assert np.isnan(yield_[available]).all()
    assert audit["AAA"]["share_versions_ambiguous_basis"] == 1
    assert audit["AAA"]["share_versions_unavailable"] == 1


# Acceptance after the split is ambiguous even if another source field is earlier.
def test_share_acceptance_after_split_cannot_bypass_ambiguity_mask():
    inputs = _inputs(
        price=10,
        vintage="2026-03-30",
        days=["2026-03-23", "2026-03-24"],
        actions=(CorporateAction(date(2026, 3, 20), "split", 10),),
    )
    revision = _version(
        "shares", "2025-12-31", 100, "2026-03-19",
        accepted=datetime(2026, 3, 23, 12, tzinfo=UTC), accession="late-acceptance",
    )
    raw, names, audit = _features(inputs, _versions() + [revision])
    assert np.isnan(raw[:, 0, names.index("log_sales_yield")]).all()
    assert audit["AAA"]["share_versions_ambiguous_basis"] == 1
