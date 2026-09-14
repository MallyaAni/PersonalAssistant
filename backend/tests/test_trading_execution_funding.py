"""Keep the observed funding limitation visible before new timing rules are scored."""

import numpy as np
import pytest

from backend.agents.trading.desk.simulate import _Book, _settle_event


# A cash-only fill cannot borrow silently when the execution price gaps above sizing.
def test_opening_gap_does_not_create_unmodeled_borrowing():
    book = _Book(1, 100, 10, None, None, None)
    book._fill(np.array([1.0]), np.array([120.0]))
    assert book.cash >= 0
    assert book.shares[0] == pytest.approx(100 / 120.12)
    assert book.equity(np.array([120.0])) == pytest.approx(100 - book.traded * 0.001)


# A closing sale is not spendable at the opening purchase boundary.
def test_opening_buys_cannot_spend_future_closing_proceeds():
    book = _Book(2, 0, 10, None, None, None)
    book.shares = np.array([1.0, 0.0])
    book._fill_split(
        np.array([0.0, 1.0]), np.array([100.0, 100.0]), np.array([120.0, 100.0])
    )
    np.testing.assert_array_equal(book.shares, [0.0, 0.0])
    assert book.cash == pytest.approx(119.88)
    assert book.traded == pytest.approx(120)


# A same-time sale may fund buys, but fees must fit and allocation ratios must hold.
def test_same_time_fills_preserve_cash_and_scale_competing_buys():
    book = _Book(3, 0, 10, None, None, None)
    book.shares = np.array([1.0, 0.0, 0.0])
    book._fill(np.array([0.0, 1.0, 2.0]), np.array([100.0, 100.0, 100.0]))
    assert book.cash >= 0
    assert book.shares[1] < 1
    assert book.shares[2] == pytest.approx(2 * book.shares[1])
    assert book.equity(np.full(3, 100.0)) == pytest.approx(100 - book.traded * 0.001)


# An unavailable sale cannot provide cash or erase its untraded holding.
def test_missing_prices_preserve_shares_and_cannot_fund_other_names():
    book = _Book(2, 10, 10, None, None, None)
    book.shares = np.array([1.0, 0.0])
    book._fill(np.array([0.0, 1.0]), np.array([np.nan, 100.0]))
    assert book.shares[0] == 1
    assert book.shares[1] == pytest.approx(10 / 100.1)
    assert book.cash >= 0


# Costs can make the last restored fraction unaffordable; it must not freeze rebalances.
def test_cash_limited_event_restoration_releases_the_completed_cycle():
    book = _Book(1, 0, 10, None, None, None)
    book.shares = np.array([1.0])
    baseline, sold = _settle_event(book, None, None, 0.5, np.array([100.0]), 0)
    baseline, sold = _settle_event(book, baseline, sold, 1, np.array([100.0]), 1)
    assert 0.99 < book.shares[0] < 1
    assert book.cash >= 0
    assert baseline is None
