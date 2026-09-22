"""The two reproduced ledger fixes, tested on the real ledger, not mocks.

The funded path fills with `recycle_sells=False`, and `_Book._fill` used to
drop the day's sale proceeds from closing cash entirely when recycling was
off: the buy budget was limited to old cash but the ending cash was computed
from that same limited budget, so a no-recycle sale's proceeds vanished from
the ledger. The sale's net proceeds are now credited to closing cash
unconditionally; only their use as a buy budget is conditional on recycling.
Whole-share rounding used to sell one share against a 0.6-share holding,
silently shorting the name; rounded sells are now capped at the whole shares
actually held, with the unexecutable fractional residual reported as blocked.
"""

import numpy as np
import pytest

from backend.agents.trading.desk.allocation import AllocationDecision
from backend.agents.trading.desk.funded_execution import plan_funded
from backend.agents.trading.desk.simulate import _Book


def _decision(desired_weights: dict[str, float]) -> AllocationDecision:
    """Return a valid vol_trend decision wanting exactly `desired_weights`."""
    return AllocationDecision(
        version="portfolio-allocation/vol_trend/1",
        as_of="2026-09-01",
        desired_weights=desired_weights,
        cash=1.0,
        available=True,
        reasons=("no risk reduction required",),
        missing=(),
        volatility=None,
        binding="none",
    )


# The reproduced no-recycle failure: a pure sale with `recycle_sells=False`
# used to leave cash at zero, because the closing cash was computed from the
# buy budget that excluded the proceeds. The sale must still be credited.
def test_no_recycle_still_credits_sale_proceeds_to_closing_cash():
    book = _Book(2, 0, 10, None, None, None)
    book.shares = np.array([1.0, 0.0])
    book._fill(np.array([0.0, 0.0]), np.array([100.0, 100.0]), recycle_sells=False)
    np.testing.assert_array_equal(book.shares, [0.0, 0.0])
    assert book.cash == pytest.approx(99.9)


# The same-day sell cannot fund this basket's buy when recycling is off, so
# the buy is limited to the pre-existing cash, while the sale's proceeds still
# land in the closing cash rather than disappearing.
def test_no_recycle_limits_buys_to_preexisting_cash_but_keeps_proceeds():
    book = _Book(2, 10, 10, None, None, None)
    book.shares = np.array([1.0, 0.0])
    book._fill(np.array([0.0, 0.5]), np.array([100.0, 100.0]), recycle_sells=False)
    assert book.shares[0] == 0.0
    # The buy notional never exceeds the ten dollars that existed before.
    assert book.shares[1] * 100.0 == pytest.approx(50.0 * 10 / 50.05)
    # Closing cash = old cash + the 99.9 net proceeds - the 10 of buy spend.
    assert book.cash == pytest.approx(99.9)


# A fill with a missing price preserves the holding and contributes no sale
# proceeds, so it cannot fund anything else in the same basket.
def test_missing_fill_price_preserves_holding_and_yields_no_proceeds():
    book = _Book(2, 0, 10, None, None, None)
    book.shares = np.array([1.0, 0.0])
    book._fill(np.array([0.0, 1.0]), np.array([np.nan, 100.0]))
    assert book.shares[0] == 1.0
    assert book.shares[1] == 0.0
    assert book.cash == pytest.approx(0.0)
    assert book.traded == pytest.approx(0.0)


# The default recycle path is untouched: a sale's proceeds fund the same
# day's buy, so the account stays fully invested and pays the fee once.
def test_default_recycle_true_behavior_is_unchanged():
    book = _Book(2, 0, 10, None, None, None)
    book.shares = np.array([1.0, 0.0])
    book._fill(np.array([0.0, 1.0]), np.array([100.0, 100.0]))
    assert book.shares[0] == 0.0
    assert book.shares[1] == pytest.approx(99.9 / 100.1)
    assert book.cash == pytest.approx(0.0)
    assert book.traded == pytest.approx(100 + 100 * (99.9 / 100.1))


# The reproduced whole-share failure: a 0.6-share holding rounds to one share
# and used to sell into a 0.4 short. It is now blocked as unexecutable.
def test_whole_share_sell_never_creates_a_short_from_a_fractional_holding():
    plan = plan_funded(
        _decision({"A": 0.0}),
        held={"A": 0.6},
        prices={"A": 100.0},
        equity=100.0,
        cash=0.0,
        whole_shares=True,
    )
    assert not any(o.side == "sell" for o in plan.orders)
    assert any("A" in message for message in plan.blocked)
    # The whole 0.6-share holding is all the account is worth, so with the
    # post-fee NAV denominator the executable weight is 1.0, not 0.6.
    assert plan.executable.get("A", 0.0) == pytest.approx(1.0)


# A partial sell that fits in whole shares still executes, within holdings.
def test_whole_share_partial_sell_stays_within_holdings():
    plan = plan_funded(
        _decision({"A": 1.4}),
        held={"A": 2.0},
        prices={"A": 100.0},
        equity=100.0,
        cash=0.0,
        whole_shares=True,
    )
    sell = [o for o in plan.orders if o.side == "sell"]
    assert sell
    assert sell[0].qty == 1
    assert not plan.blocked
    # The remaining whole share is worth 100 against a post-fee NAV of the
    # final 100 of A plus the 99.9 net sale proceeds.
    assert plan.executable.get("A", 0.0) == pytest.approx(
        100.0 / (100.0 + 100.0 * (1.0 - 10.0 / 1e4))
    )


# A fractional residual that whole shares cannot sell is reported as blocked
# while the whole shares it can sell still go.
def test_whole_share_reports_the_fractional_residual_as_blocked():
    plan = plan_funded(
        _decision({"A": 0.0}),
        held={"A": 1.6},
        prices={"A": 100.0},
        equity=100.0,
        cash=0.0,
        whole_shares=True,
    )
    sell = [o for o in plan.orders if o.side == "sell"]
    assert sell
    assert sell[0].qty == 1
    assert any("A" in message and "residual" in message for message in plan.blocked)
    # The unsold 0.6 share is worth 60 against a post-fee NAV of 60 plus the
    # 99.9 net sale proceeds from the whole share that did sell.
    assert plan.executable.get("A", 0.0) == pytest.approx(
        0.6 * 100.0 / (0.6 * 100.0 + 1.0 * 100.0 * (1.0 - 10.0 / 1e4))
    )


# A nonfinite or negative held quantity is a caller error, not a row to
# silently drop (the positive filter would have let +inf through).
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, -0.5])
def test_plan_funded_rejects_nonfinite_or_negative_held_quantities(bad):
    with pytest.raises(ValueError, match="must be finite and nonnegative"):
        plan_funded(
            _decision({"A": 0.0}),
            held={"A": bad},
            prices={"A": 100.0},
            equity=100.0,
            cash=0.0,
            whole_shares=True,
        )
