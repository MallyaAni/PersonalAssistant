"""Keep the observed funding limitation visible before new timing rules are scored."""

import numpy as np
import pytest

from backend.agents.trading.desk.simulate import _Book


# A cash-only fill cannot borrow silently when the execution price gaps above sizing.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "2026-09-13 live 84d07faf: $100 cash buys $120 plus costs, "
        "leaving -$20.12; borrowing is not modeled"
    ),
)
def test_opening_gap_does_not_create_unmodeled_borrowing():
    book = _Book(1, 100, 10, None, None, None)
    book._fill(np.array([1.0]), np.array([120.0]))
    assert book.cash >= 0
