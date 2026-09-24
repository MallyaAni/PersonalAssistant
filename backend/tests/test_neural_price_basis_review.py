"""Independent supplied-data reproduction; does not change frozen model or stores."""

from datetime import UTC, date, datetime

import numpy as np
import pytest

from backend.market import edgar, opportunity_learning
from backend.market.panel import Panel
from backend.market.store import MarketStore


# A later provider split normalization must not change an earlier economic valuation.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Frozen opportunity_learning mixes price and filed share units: "
        "same economic history gives sales yield 0.4 versus 4.0; "
        "see neural-comparison-readiness-2026-09-24.md. Frozen ledger unchanged."
    ),
)
def test_future_price_vintage_does_not_change_historical_yield(tmp_path):
    dates = np.busday_offset('2024-01-01', np.arange(150))
    original = np.full((len(dates), 2), 100.0)
    adjusted = np.full_like(original, 10.0)
    volume = np.full_like(original, 1000.0)
    # These are equivalent historical prices before and after a later 10-for-1
    # split changes the provider's historical close units. The same dated filing
    # correctly reports ten original shares; future fetches do not rewrite it.
    old = Panel(dates, ('ABC', 'SPY'), original, original, original,
                original, original, volume, {}, 'SPY')
    normalized = Panel(dates, ('ABC', 'SPY'), adjusted, adjusted, adjusted,
                       adjusted, adjusted, volume, {}, 'SPY')
    ends = [date(2023, 3, 31), date(2023, 6, 30),
            date(2023, 9, 30), date(2023, 12, 31)]
    filed = date(2024, 1, 2)
    facts = [edgar.QuarterFact('revenue', end, end, 100.0, filed) for end in ends]
    facts.append(edgar.QuarterFact('shares', ends[-1], ends[-1], 10.0, filed))
    stamp = datetime(2025, 1, 1, tzinfo=UTC)
    store = MarketStore(tmp_path)
    events, values = edgar.record_frames(
        edgar.CompanyRecord('ABC', 1, (), tuple(facts), stamp)
    )
    store.write_frame('edgar_events', stamp.date(), 'ABC', events)
    store.write_frame('edgar_facts', stamp.date(), 'ABC', values)
    _, before, names = opportunity_learning.features(old, store, stamp.date())
    _, after, _ = opportunity_learning.features(normalized, store, stamp.date())
    feature = names.index('log_sales_yield')
    row = -1
    print({'original_sales_yield': float(np.exp(before[row, 0, feature])),
           'later_vintage_sales_yield': float(np.exp(after[row, 0, feature])),
           'expected_economic_sales_yield': 400 / (100 * 10)})
    np.testing.assert_allclose(before[row, 0, :8], after[row, 0, :8], equal_nan=True)
    np.testing.assert_allclose(before[row, 0, feature], after[row, 0, feature])
