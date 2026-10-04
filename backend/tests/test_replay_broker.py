"""Private venue accounting and actual settlement semantics without network calls."""

import pytest

from backend.agents.trading.desk import paper
from backend.market.alpaca_trading import AlpacaTradingError
from backend.market.replay_broker import ReplayBroker

NOW = "2026-08-03T09:45:00-04:00"
LATER = "2026-08-03T10:00:00-04:00"


# Create a private observed account with explicit initial acquisition bases.
def account(cash=1000, cost=10, holdings=None):
    held = holdings or {}
    broker = ReplayBroker(
        cash,
        cost,
        initial_holdings=held,
        initial_average_prices={name: 8 for name in held},
    )
    broker.observe(NOW, {"AAA": 10, "BBB": 10}, True)
    return broker


# Future price differences affect fills without leaking into accepted decisions.
def test_future_prices_do_not_enter_submission_or_marked_account():
    cheap, expensive = account(), account()
    for broker in (cheap, expensive):
        broker.submit_market("AAA", 5, "buy", "intent")
        assert broker.account().cash == 1000
        assert broker.positions() == []
        assert broker.open_orders()[0]["filled_avg_price"] is None
    assert cheap.attempt_history == expensive.attempt_history
    cheap.flush(LATER, {"AAA": 9})
    expensive.flush(LATER, {"AAA": 12})
    assert cheap.ledger()["cash"] == pytest.approx(954.955)
    assert expensive.ledger()["cash"] == pytest.approx(939.94)
    with pytest.raises(AlpacaTradingError, match="Fresh observed"):
        cheap.account()
    cheap.observe(LATER, {"AAA": 11}, True)
    assert cheap.account().equity == pytest.approx(1009.955)


# Accepted requests reserve both cash and the explicit per-side fee.
def test_batch_reservations_reject_and_cancellation_releases_cash():
    broker = account(100)
    broker.submit_market("AAA", 9, "buy", "first")
    assert broker.account().buying_power == pytest.approx(9.91)
    with pytest.raises(AlpacaTradingError, match="insufficient_reserved_cash"):
        broker.submit_market("BBB", 1, "buy", "second")
    assert len(broker.orders_since(NOW)) == 1
    assert broker.attempt_history[-1]["accepted"] is False
    assert broker.cancel_orders(["first"]) == {"first": "cancelled"}
    broker.submit_market("BBB", 1, "buy", "second")
    broker.flush(LATER, {"BBB": 10})
    assert broker.ledger()["cash"] == pytest.approx(89.99)


# Confirmed sale proceeds fund only a later observed decision batch.
def test_same_batch_sales_cannot_finance_buys_but_later_cash_can():
    broker = account(0, holdings={"AAA": 10})
    broker.submit_market("AAA", 10, "sell", "sale")
    with pytest.raises(AlpacaTradingError, match="insufficient_reserved_cash"):
        broker.submit_market("BBB", 5, "buy", "purchase")
    broker.flush(LATER, {"AAA": 10})
    broker.observe(LATER, {"BBB": 10}, True)
    broker.submit_market("BBB", 5, "buy", "purchase")
    broker.flush("2026-08-03T10:15:00-04:00", {"BBB": 10})
    assert broker.ledger()["cash"] == pytest.approx(49.85)
    assert broker.ledger()["holdings"] == {"BBB": 5}


# Pending sells reserve existing whole shares and never short a holding.
def test_covered_share_reservations_and_cancellation():
    broker = account(0, holdings={"AAA": 10})
    broker.submit_market("AAA", 6, "sell", "first")
    with pytest.raises(AlpacaTradingError, match="uncovered_sell"):
        broker.submit_market("AAA", 5, "sell", "second")
    broker.cancel_orders(["first"])
    broker.submit_market("AAA", 5, "sell", "second")
    broker.flush(LATER, {"AAA": 10})
    assert broker.ledger()["holdings"] == {"AAA": 5}


# Duplicate IDs adopt original accepted receipts while conflicts fail closed.
def test_duplicate_identity_and_detached_histories():
    broker = account()
    first = broker.submit_market("AAA", 2, "buy", "id")
    first["qty"] = "99"
    assert broker.submit_market("AAA", 2, "buy", "id")["qty"] == "2"
    assert len(broker.attempt_history) == 1
    with pytest.raises(AlpacaTradingError, match="Conflicting"):
        broker.submit_market("AAA", 3, "buy", "id")
    with pytest.raises(AlpacaTradingError, match="Conflicting"):
        broker.submit_market_on_close("AAA", 2, "buy", "id")
    attempts = broker.attempt_history
    attempts[0]["accepted"] = False
    assert broker.attempt_history[0]["accepted"] is True
    broker.flush(LATER, {"AAA": 10})
    fills = broker.fill_history
    fills[0]["filled_qty"] = 99
    assert broker.fill_history[0]["filled_qty"] == 2
    broker.observe(LATER, {"AAA": 10}, True)
    assert broker.submit_market("AAA", 2, "buy", "id")["status"] == "filled"
    assert len(broker.fill_history) == 1


# A price gap causes a terminal whole-share partial, preserving desired quantity.
def test_partial_fill_is_terminal_in_actual_paper_settlement():
    broker = account(100)
    order = broker.submit_market("AAA", 9, "buy", "partial")
    broker.flush(LATER, {"AAA": 20})
    receipt = broker.orders_since(NOW)[0]
    assert receipt["qty"] == "9"
    assert receipt["filled_qty"] == "4"
    assert receipt["status"] == "expired"
    assert broker.ledger()["cash"] == pytest.approx(19.92)
    assert broker.fill_history[0]["fee"] == pytest.approx(0.08)
    settled = paper.settle([order], [receipt])[0]
    assert settled.status == "partial"
    assert settled.terminal
    assert settled.qty == 9
    assert settled.filled_qty == 4
    assert broker.flush("2026-08-03T10:15:00-04:00", {"AAA": 1}) == []


# Missing selected prices expire without inventing a later better execution.
def test_missing_selected_price_locks_expired_attempt():
    broker = account()
    broker.submit_market("AAA", 5, "buy", "missing")
    broker.flush(LATER, {})
    assert broker.fill_history[0]["reason"] == "missing_execution_price"
    assert broker.ledger()["holdings"] == {}
    broker.observe(LATER, {"AAA": 10}, True)
    adopted = broker.submit_market("AAA", 5, "buy", "missing")
    assert adopted["status"] == "expired"
    assert adopted["filled_qty"] == "0"
    assert broker.flush("2026-08-03T10:15:00-04:00", {"AAA": 1}) == []


# Outside-hours day orders wait for the correct future opening phase.
def test_open_queue_weekend_day_tif_and_idempotent_adoption():
    broker = ReplayBroker(1000, 0)
    broker.observe("2026-08-07T17:00:00-04:00", {"AAA": 10}, False)
    row = broker.submit_market_on_open("AAA", 2, "buy", "event")
    assert row["time_in_force"] == "day"
    assert row["execute_on"] == "2026-08-10"
    with pytest.raises(ValueError, match="regular-session"):
        broker.flush("2026-08-07T17:00:00-04:00", {"AAA": 1})
    assert broker.ledger()["holdings"] == {}
    broker.observe("2026-08-10T09:30:00-04:00", {"AAA": 11}, True)
    assert broker.submit_market_on_open("AAA", 2, "buy", "event") == row
    assert broker.flush("2026-08-10T09:30:00-04:00", {"AAA": 1}) == []
    broker.flush("2026-08-10T09:30:00-04:00", {"AAA": 11}, phase="open")
    assert broker.ledger()["cash"] == 978


# Opening API calls during trading remain immediate day market requests.
def test_open_api_during_regular_session_uses_market_phase():
    broker = account()
    row = broker.submit_market_on_open("AAA", 2, "buy", "catchup")
    assert row["execution_phase"] == "market"
    broker.flush(LATER, {"AAA": 10})
    assert broker.ledger()["holdings"] == {"AAA": 2}


# Closing auctions use their reviewed early close and explicit auction evidence.
def test_early_close_auction_requires_exact_phase_and_price():
    broker = ReplayBroker(
        0, 0, initial_holdings={"AAA": 3}, initial_average_prices={"AAA": 10}
    )
    broker.observe("2026-11-27T12:45:00-05:00", {"AAA": 10}, True)
    row = broker.submit_market_on_close("AAA", 3, "sell", "close")
    assert row["time_in_force"] == "cls"
    assert broker.flush("2026-11-27T13:00:00-05:00", {"AAA": 10}) == []
    with pytest.raises(ValueError, match="exact scheduled"):
        broker.flush("2026-11-27T16:00:00-05:00", {"AAA": 10}, phase="close")
    broker.flush("2026-11-27T13:00:00-05:00", {}, phase="close")
    assert broker.ledger()["holdings"] == {"AAA": 3}
    assert broker.orders_since("2026-11-27T00:00:00-05:00")[0]["status"] == "expired"


# Historical session coverage is taken from reviewed bytes rather than live years.
def test_historical_observation_and_holiday_clocks():
    broker = ReplayBroker(100, 0)
    broker.observe("2018-02-01T09:45:00-05:00", {"AAA": 10}, True)
    assert broker.clock()["is_open"] is True
    with pytest.raises(ValueError, match="disagrees"):
        broker.observe("2018-12-25T09:45:00-05:00", {"AAA": 10}, True)


# NAV refuses missing or stale held marks instead of carrying previous prices.
def test_held_marks_must_be_current_for_account_and_positions():
    broker = account(100, holdings={"AAA": 2})
    broker.observe(LATER, {"BBB": 10}, True)
    with pytest.raises(AlpacaTradingError, match="Fresh raw held mark"):
        broker.account()
    with pytest.raises(AlpacaTradingError, match="Fresh raw held mark"):
        broker.positions()
    broker.observe(LATER, {"AAA": 11}, True)
    assert broker.account().equity == 122
    assert broker.positions()[0].unrealized_pl == 6


# Explicit splits change shares and basis while leaving pending intent quantity alone.
def test_split_entitlement_basis_and_pending_quantity():
    broker = account(0, holdings={"AAA": 10})
    broker.submit_market("AAA", 5, "sell", "pending")
    broker.apply_split("AAA", 2, "2026-08-03T00:00:00-04:00")
    assert broker.ledger()["holdings"] == {"AAA": 20}
    assert broker.ledger()["average_prices"] == {"AAA": 4}
    assert broker.open_orders()[0]["qty"] == "5"
    broker.apply_split("AAA", 2, "2026-08-03T00:00:00-04:00")
    with pytest.raises(ValueError, match="Conflicting"):
        broker.apply_split("AAA", 3, "2026-08-03T00:00:00-04:00")
    assert broker.ledger()["holdings"] == {"AAA": 20}


# A child-stock distribution preserves parent shares and total acquisition basis.
def test_stock_distribution_is_not_a_parent_split():
    broker = ReplayBroker(
        50,
        0,
        initial_holdings={"AAA": 99, "BBB": 2},
        initial_average_prices={"AAA": 60, "BBB": 40},
    )
    broker.observe(NOW, {"AAA": 45, "BBB": 45}, True)
    broker.apply_stock_distribution("AAA", "BBB", 1, 3, NOW, parent_basis_fraction=0.75)
    ledger = broker.ledger()
    assert ledger["holdings"] == {"AAA": 99, "BBB": 35}
    assert ledger["average_prices"] == {"AAA": 45, "BBB": pytest.approx(1565 / 35)}
    assert ledger["cash"] == 50
    assert broker.account().equity == 6080
    assert sum(
        ledger["holdings"][s] * ledger["average_prices"][s] for s in ledger["holdings"]
    ) == pytest.approx(6020)
    broker.apply_stock_distribution("AAA", "BBB", 1, 3, NOW, parent_basis_fraction=0.75)
    assert broker.ledger() == ledger
    with pytest.raises(ValueError, match="Conflicting"):
        broker.apply_stock_distribution(
            "AAA", "BBB", 1, 3, NOW, parent_basis_fraction=0.70
        )
    assert broker.ledger() == ledger


# Unknown cash-in-lieu stays an unpriced claim and cannot become shares or cash.
def test_distribution_fraction_is_not_fabricated_funding_or_a_tradable_share():
    broker = ReplayBroker(
        0, 0, initial_holdings={"AAA": 100}, initial_average_prices={"AAA": 60}
    )
    broker.observe(NOW, {"AAA": 45, "BBB": 45}, True)
    broker.apply_stock_distribution("AAA", "BBB", 1, 3, NOW, parent_basis_fraction=0.75)
    ledger = broker.ledger()
    assert ledger["holdings"] == {"AAA": 100, "BBB": 33}
    claim = ledger["security_distributions"][0]
    assert claim["fractional_qty"] == pytest.approx(1 / 3)
    assert claim["fractional_basis"] == pytest.approx(15)
    assert claim["cash_in_lieu"] is None
    assert ledger["cash"] == 0
    assert broker.positions()[0].qty == 100
    assert broker.positions()[1].qty == 33
    with pytest.raises(AlpacaTradingError, match="cash-in-lieu"):
        broker.account()
    with pytest.raises(AlpacaTradingError, match="cash-in-lieu"):
        broker.submit_market("BBB", 34, "sell", "excess")
    assert broker.ledger() == ledger


# Observed cash-in-lieu closes the unpriced claim exactly once without future funding.
def test_distribution_cash_requires_observed_receipt_and_is_idempotent():
    broker = account(100, cost=0, holdings={"AAA": 10})
    broker.apply_stock_distribution("AAA", "BBB", 1, 3, NOW, parent_basis_fraction=0.75)
    before = broker.ledger()
    with pytest.raises(ValueError, match="Observed distribution payment"):
        broker.settle_distribution_cash("AAA", "BBB", NOW, 3, LATER)
    assert broker.ledger() == before
    broker.observe(LATER, {"AAA": 10, "BBB": 10}, True)
    broker.settle_distribution_cash("AAA", "BBB", NOW, 3, LATER)
    assert broker.account().cash == 103
    assert broker.account().equity == 233
    paid = broker.ledger()
    broker.settle_distribution_cash("AAA", "BBB", NOW, 3, LATER)
    assert broker.ledger() == paid
    with pytest.raises(ValueError, match="Conflicting"):
        broker.settle_distribution_cash("AAA", "BBB", NOW, 4, LATER)
    assert broker.ledger() == paid


# Invalid or late distribution facts must not partially change the account.
@pytest.mark.parametrize(
    "change", ["same_symbol", "zero", "boolean", "basis", "future"]
)
def test_invalid_stock_distribution_is_atomic(change):
    broker = account(100, holdings={"AAA": 9})
    child, numerator, fraction, when = "BBB", 1, 0.75, NOW
    if change == "same_symbol":
        child = "AAA"
    elif change == "zero":
        numerator = 0
    elif change == "boolean":
        numerator = True
    elif change == "basis":
        fraction = 1.1
    else:
        when = "2026-08-04T09:45:00-04:00"
    before = broker.ledger()
    with pytest.raises(ValueError, match="required"):
        broker.apply_stock_distribution(
            "AAA", child, numerator, 3, when, parent_basis_fraction=fraction
        )
    assert broker.ledger() == before


# Fractional entitlements remain shares; invalid action clocks preserve the ledger.
def test_fractional_split_and_invalid_action_clocks():
    broker = account(0, holdings={"AAA": 3})
    broker.apply_split("AAA", 0.5, "2026-08-03T00:00:00-04:00")
    assert broker.ledger()["holdings"] == {"AAA": 1.5}
    assert broker.ledger()["average_prices"] == {"AAA": 16}
    assert broker.ledger()["cash"] == 0
    before = broker.ledger()
    with pytest.raises(ValueError, match="Observed dated"):
        broker.apply_split("AAA", 2, "2026-08-04T00:00:00-04:00")
    assert broker.ledger() == before
    broker.submit_market("AAA", 1, "sell", "sell")
    broker.flush(LATER, {"AAA": 10})
    with pytest.raises(ValueError, match="precede affected fills"):
        broker.apply_split("AAA", 2, "2026-08-03T09:30:00-04:00")


# Odd-lot forward splits preserve value and leave fractional shares after whole sells.
def test_odd_lot_split_preserves_fractional_residual_without_cash_in_lieu():
    broker = ReplayBroker(
        0, 10, initial_holdings={"AAA": 3}, initial_average_prices={"AAA": 15}
    )
    broker.observe(NOW, {"AAA": 10}, True)
    broker.apply_split("AAA", 1.5, "2026-08-03T00:00:00-04:00")
    assert broker.positions()[0].qty == 4.5
    assert broker.positions()[0].avg_entry_price == 10
    assert broker.account().equity == 45
    assert broker.account().cash == 0
    with pytest.raises(AlpacaTradingError, match="uncovered_sell"):
        broker.submit_market("AAA", 5, "sell", "too_many")
    broker.submit_market("AAA", 4, "sell", "whole_sale")
    broker.flush(LATER, {"AAA": 10})
    assert broker.ledger()["holdings"] == {"AAA": 0.5}
    assert broker.ledger()["cash"] == pytest.approx(39.96)
    broker.observe(LATER, {"AAA": 10}, True)
    assert broker.positions()[0].qty == 0.5
    assert broker.positions()[0].market_value == 5
    assert broker.account().equity == pytest.approx(44.96)
    with pytest.raises(AlpacaTradingError, match="uncovered_sell"):
        broker.submit_market("AAA", 1, "sell", "residual")


# Dividend receivables count as equity but cannot fund buys before explicit payment.
def test_dividend_receivable_requires_known_pay_date_for_cash():
    broker = account(0, cost=0, holdings={"AAA": 10})
    broker.accrue_dividend(
        "AAA", 1, "2026-08-03T00:00:00-04:00", pay_at="2026-08-04T00:00:00-04:00"
    )
    assert broker.account().equity == 110
    assert broker.account().cash == broker.account().buying_power == 0
    with pytest.raises(AlpacaTradingError, match="insufficient_reserved_cash"):
        broker.submit_market("BBB", 1, "buy", "buy")
    broker.observe("2026-08-04T09:45:00-04:00", {"AAA": 10, "BBB": 10}, True)
    assert broker.account().cash == 10
    broker.submit_market("BBB", 1, "buy", "buy")
    broker.flush("2026-08-04T10:00:00-04:00", {"BBB": 10})
    assert broker.ledger()["cash"] == 0


# An unknown dividend payment date never becomes cash through elapsed time.
def test_unknown_payment_and_duplicate_entitlements():
    broker = account(0, cost=0, holdings={"AAA": 10})
    broker.accrue_dividend("AAA", 1, "2026-08-03T00:00:00-04:00")
    broker.accrue_dividend("AAA", 1, "2026-08-03T00:00:00-04:00")
    broker.observe("2026-08-10T09:45:00-04:00", {"AAA": 10}, True)
    assert broker.account().cash == 0
    assert broker.account().equity == 110
    assert len(broker.ledger()["dividends"]) == 1
    with pytest.raises(ValueError, match="cannot precede"):
        broker.accrue_dividend(
            "AAA", 1, "2026-08-10T00:00:00-04:00", pay_at="2026-08-03T00:00:00-04:00"
        )


# Reject ambiguous order quantities and IDs before any order is accepted.
@pytest.mark.parametrize(
    ("qty", "identifier"), [(1.5, "id"), (True, "id"), (0, "id"), (1, None)]
)
def test_malformed_order_identity(qty, identifier):
    broker = account()
    with pytest.raises(AlpacaTradingError):
        broker.submit_market("AAA", qty, "buy", identifier)
    assert broker.open_orders() == []


# Reject naive, regressing, unknown and false market-open clocks.
@pytest.mark.parametrize(
    ("clock", "opened"),
    [
        ("2026-08-03T10:00:00", True),
        ("2026-08-03T09:30:00-04:00", True),
        ("2026-08-08T10:00:00-04:00", True),
        ("2035-08-03T10:00:00-04:00", True),
    ],
)
def test_ambiguous_observation_clocks(clock, opened):
    broker = account()
    with pytest.raises(ValueError, match="clock|timezone|calendar"):
        broker.observe(clock, {"AAA": 10}, opened)


# A completed batch requires another observation before a fresh submission.
def test_flush_closes_batch_and_cancellation_rejects_malformed_ids():
    broker = account()
    broker.flush(NOW, {})
    with pytest.raises(AlpacaTradingError, match="new decision batch"):
        broker.submit_market("AAA", 1, "buy", "late")
    with pytest.raises(ValueError, match="order IDs"):
        broker.cancel_orders("late")


# Initial whole-share accounts require actual finite bases and cash evidence.
@pytest.mark.parametrize(
    ("cash", "cost", "qty"), [(-1, 0, 1), (100, 10000, 1), (100, 0, 1.5)]
)
def test_invalid_initial_financial_values(cash, cost, qty):
    with pytest.raises(ValueError, match="numeric|cost|whole-share"):
        ReplayBroker(
            cash,
            cost,
            initial_holdings={"AAA": qty},
            initial_average_prices={"AAA": 10},
        )
