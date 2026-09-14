"""A single cash budget must bound all additions, including fractional holdings."""

import pytest

from backend.market.funding import preview


# Construct an existing target row without a second implementation of sizing.
def row(ticker, price, weight=0.15, held=0, **extra):
    return dict(
        ticker=ticker,
        last=price,
        target_weight=weight,
        shares=held,
        action="add",
        **extra,
    )


# Independent rows cannot each spend the same cash, or spend expected sale proceeds.
def test_one_budget_and_no_sale_proceeds():
    rows = [
        row("AAA", 10),
        row("BBB", 20),
        dict(ticker="SELL", action="sell", last=100, shares=100),
    ]
    result = preview(rows, 10000, 300)
    assert [r["additional_shares"] for r in result["rows"]] == [15, 7]
    assert result["estimated_cost"] == 290
    assert result["unallocated_cash"] == 10
    assert result["cash_limited"]
    assert preview(rows, 10000, 0)["estimated_cost"] == 0


# Fractional positions reduce the remaining whole-share addition without rounding up.
def test_holdings_prices_and_event_pause_change_preview():
    assert preview([row("AAA", 10, held=149.5)], 10000, 1000)["rows"] == []
    original = preview([row("AAA", 10, held=100)], 10000, 1000)["rows"][0]
    assert original["additional_shares"] == 50
    assert original["target_total_shares"] == 150
    assert preview([row("AAA", 15, held=100)], 10000, 1000)["rows"] == []
    assert preview([row("AAA", 10, event_paused=True)], 10000, 1000)["rows"] == []


# Non-finite values and impossible cash-only balances fail before JSON serialization.
@pytest.mark.parametrize("cash", [float("nan"), float("inf"), -1, 10001])
def test_invalid_cash_is_rejected(cash):
    with pytest.raises(ValueError, match="Available cash"):
        preview([row("AAA", 10)], 10000, cash)


# Whole-share rounding always leaves the jointly proposed cost within cash.
def test_rounding_stays_funded():
    for cash in (0, 0.01, 1, 17.13, 100, 523.79, 9999):
        result = preview([row("AAA", 17.13, held=1.5), row("BBB", 123.47)], 10000, cash)
        assert 0 <= result["estimated_cost"] <= cash
        assert result["unallocated_cash"] >= 0
