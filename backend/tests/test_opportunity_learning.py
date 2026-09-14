"""Pin price sensitivity, label timing and training-only transformations."""

from datetime import UTC, date, datetime

import numpy as np

from backend.market import edgar
from backend.market import opportunity_learning as ol
from backend.market.panel import Panel
from backend.market.store import MarketStore


# A cheaper price raises yields while retaining negative earnings as a loss.
def test_price_sensitivity_and_negative_earnings():
    levels = {
        name: np.array([[100.0]])
        for name in (
            "shares",
            "revenue",
            "earnings",
            "equity",
            "operating_cash_flow",
            "revenue_growth",
            "gross_profit",
            "cash",
            "debt",
        )
    }
    levels["earnings"] *= -1
    expensive = ol.ratios(np.array([[100.0]]), levels)
    cheaper = ol.ratios(np.array([[50.0]]), levels)
    assert cheaper[0, 0, 0] > expensive[0, 0, 0]
    assert cheaper[0, 0, 1] == 2 * expensive[0, 0, 1] < 0
    assert cheaper[0, 0, 5] == expensive[0, 0, 5]


# Validation corruption cannot change fitted imputations, scales or training values.
def test_normalizer_ignores_validation_and_preserves_missing_rows():
    values = np.array([[1.0, np.nan], [3.0, 2.0], [5.0, 4.0]])
    before, fitted = ol.normalize(values, values[:2])
    changed = values.copy()
    changed[2] = 1e10
    after, other = ol.normalize(changed, changed[:2])
    np.testing.assert_array_equal(before[:2], after[:2])
    np.testing.assert_array_equal(fitted, other)
    assert before.shape == (3, 4)
    assert before[0, 3] == 1
    assert np.isfinite(before).all()


# Labels exclude the entry gap and include the final delayed exit-day return.
def test_twenty_session_execution_label():
    prices = np.ones((25, 1)) * 100
    prices[1:] = 120
    prices[21:] = 132
    result = ol.labels(prices)
    np.testing.assert_allclose(result[0], 100 * np.log(1.1))
    assert np.isnan(result[-21:]).all()


# A future quarterly filing cannot alter any feature on or before its filing date.
def test_future_filings_do_not_rewrite_features(tmp_path):
    dates = np.busday_offset("2024-01-01", np.arange(310))
    prices = np.ones((310, 2)) * 100
    panel = Panel(
        dates, ("ABC", "SPY"), prices, prices, prices, prices, prices, prices, {}, "SPY"
    )
    quarters = [
        date(2023, 12, 31),
        date(2024, 3, 31),
        date(2024, 6, 30),
        date(2024, 9, 30),
    ]
    facts = [
        edgar.QuarterFact("revenue", end, end, 100, date(2024, 11, 1))
        for end in quarters
    ]
    facts += [
        edgar.QuarterFact("shares", quarters[-1], quarters[-1], 10, date(2024, 11, 1))
    ]
    stamp = datetime(2025, 3, 1, tzinfo=UTC)
    old = MarketStore(tmp_path / "old")
    new = MarketStore(tmp_path / "new")
    future = edgar.QuarterFact(
        "revenue", date(2024, 10, 1), date(2024, 12, 31), 1000, date(2025, 1, 15)
    )
    for store, rows in ((old, facts), (new, facts + [future])):
        events, frame = edgar.record_frames(
            edgar.CompanyRecord("ABC", 1, (), tuple(rows), stamp)
        )
        store.write_frame("edgar_events", stamp.date(), "ABC", events)
        store.write_frame("edgar_facts", stamp.date(), "ABC", frame)
    _, before, _ = ol.features(panel, old, stamp.date())
    _, after, _ = ol.features(panel, new, stamp.date())
    past = dates <= np.datetime64("2025-01-15")
    np.testing.assert_allclose(before[past], after[past], equal_nan=True)
    first = np.flatnonzero(dates == np.datetime64("2025-01-16"))[0]
    assert after[first, 0, 8] > before[first, 0, 8]
