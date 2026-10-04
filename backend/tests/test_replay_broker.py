"""Private venue accounting and actual settlement semantics without network calls."""

import pytest

from backend.agents.trading.desk import paper
from backend.market.alpaca_trading import AlpacaTradingError
from backend.market.replay_broker import ReplayBroker

NOW = "2026-08-03T09:45:00-04:00"
LATER = "2026-08-03T10:00:00-04:00"
MERGER_BOUNDARY = "2026-08-03T09:30:00-04:00"


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


# Convert terminal shares into a known receivable while retaining spendable cash.
@pytest.mark.parametrize("quantity", [0, 1, 20, 100])
def test_cash_merger_retains_value_without_paid_cash_or_stale_holdings(quantity):
    broker = account(100, 0, holdings={"AAA": quantity})
    broker.observe(NOW, {"AAA": None, "BBB": 10}, True)
    broker.apply_cash_merger(
        "AAA",
        142.5,
        MERGER_BOUNDARY,
        old_security_id="old-common",
        election_policy="declared_no_election_default_cash",
    )
    before = broker.ledger()
    assert before["holdings"] == before["average_prices"] == {}
    assert before["cash"] == broker.account().buying_power == 100
    assert broker.account().equity == 100 + 142.5 * quantity
    assert broker.positions() == []
    receipt = before["cash_mergers"][0]
    assert receipt["amount"] == 142.5 * quantity
    assert receipt["prior_total_cost"] == quantity * 8
    assert receipt["completed_before"] == "2026-08-03T13:30:00+00:00"
    assert receipt["applied_at"] == "2026-08-03T13:45:00+00:00"
    assert receipt["legal_clock_precision"] == "completed_before_open_not_exact"
    assert receipt["paid"] is False
    assert "effective_at" not in receipt
    broker.apply_cash_merger(
        "AAA",
        142.5,
        MERGER_BOUNDARY,
        old_security_id="old-common",
        election_policy="declared_no_election_default_cash",
    )
    assert broker.ledger() == before
    with pytest.raises(AlpacaTradingError, match="insufficient_reserved_cash"):
        broker.submit_market("BBB", 11, "buy", "unpaid-cash")
    assert broker.open_orders() == []


# Unallocated acquisition cost never changes the known merger entitlement.
def test_cash_merger_keeps_unknown_prior_basis_without_fabricated_profit():
    broker = account(1000, 0, holdings={"AAA": 100})
    broker.apply_stock_distribution(
        "AAA",
        "BBB",
        1,
        5,
        MERGER_BOUNDARY,
        parent_basis_fraction=None,
        basis_policy="unallocated_at_effective_clock",
    )
    broker.observe(NOW, {"AAA": 10, "BBB": None}, True)
    broker.apply_cash_merger(
        "BBB",
        142.5,
        MERGER_BOUNDARY,
        old_security_id="old-child",
        election_policy="declared_no_election_default_cash",
    )
    assert broker.ledger()["holdings"] == {"AAA": 100}
    assert broker.ledger()["cash_mergers"][0]["prior_total_cost"] is None
    assert broker.ledger()["cash_mergers"][0]["amount"] == 2850
    assert broker.account().equity == 4850
    assert broker.positions()[0].unrealized_pl is None


# Only a matching observed payment changes cash, leaving total wealth unchanged.
def test_merger_payment_is_observed_once_without_double_counting_wealth():
    broker = account(100, 0, holdings={"AAA": 20})
    broker.apply_cash_merger(
        "AAA",
        142.5,
        MERGER_BOUNDARY,
        old_security_id="old-common",
        election_policy="declared_no_election_default_cash",
    )
    before = broker.ledger()
    for amount, at in ((2850, LATER), (2849, NOW), (2850, "2026-08-03T09:29:00-04:00")):
        with pytest.raises(ValueError, match="Observed matching merger payment"):
            broker.settle_merger_cash("AAA", MERGER_BOUNDARY, amount, at)
        assert broker.ledger() == before
    broker.observe(LATER, {"AAA": None, "BBB": 10}, True)
    broker.settle_merger_cash("AAA", MERGER_BOUNDARY, 2850, LATER)
    assert broker.account().equity == broker.account().cash == 2950
    assert broker.account().buying_power == 2950
    paid = broker.ledger()
    broker.settle_merger_cash("AAA", MERGER_BOUNDARY, 2850, LATER)
    assert broker.ledger() == paid
    with pytest.raises(ValueError, match="Conflicting merger payment"):
        broker.settle_merger_cash("AAA", MERGER_BOUNDARY, 2850, NOW)
    assert broker.ledger() == paid


# Invalid or conflicting merger declarations leave every account field untouched.
@pytest.mark.parametrize(
    "defect",
    [
        "amount",
        "bool",
        "clock",
        "future",
        "identity",
        "policy",
        "fractional",
        "conflict",
        "different_identity",
    ],
)
def test_cash_merger_invalid_evidence_is_atomic(defect):
    broker = account(1000, 0, holdings={"AAA": 3})
    amount, clock, identity, policy = (
        142.5,
        MERGER_BOUNDARY,
        "old-common",
        "declared_no_election_default_cash",
    )
    if defect == "amount":
        amount = float("inf")
    elif defect == "bool":
        amount = True
    elif defect == "clock":
        clock = NOW
    elif defect == "future":
        clock = "2026-08-04T09:30:00-04:00"
    elif defect == "identity":
        identity = ""
    elif defect == "policy":
        policy = "stock_election"
    elif defect == "fractional":
        broker.apply_split("AAA", 1.5, MERGER_BOUNDARY)
    else:
        broker.apply_cash_merger(
            "AAA", amount, clock, old_security_id=identity, election_policy=policy
        )
        if defect == "conflict":
            amount = 142.48
        else:
            identity = "different-old-common"
    before = broker.ledger()
    expected = {
        "amount": "Finite",
        "bool": "Finite",
        "clock": "before-open cash default",
        "future": "Observed dated",
        "identity": "before-open cash default",
        "policy": "before-open cash default",
        "fractional": "Whole pre-merger",
        "conflict": "Conflicting corporate-action",
        "different_identity": "Conflicting terminal",
    }[defect]
    with pytest.raises(ValueError, match=expected):
        broker.apply_cash_merger(
            "AAA", amount, clock, old_security_id=identity, election_policy=policy
        )
    assert broker.ledger() == before


# Old accepted orders or already affected fills cannot be rewritten as a merger.
@pytest.mark.parametrize("filled", [False, True])
def test_cash_merger_refuses_old_orders_or_post_boundary_fills(filled):
    broker = account(1000, 0, holdings={"AAA": 20})
    broker.submit_market("AAA", 1, "sell", "old-security")
    if filled:
        broker.flush(LATER, {"AAA": 10})
        broker.observe(LATER, {"AAA": None}, True)
    before = broker.ledger()
    with pytest.raises(
        ValueError, match="affected fills" if filled else "Outstanding orders"
    ):
        broker.apply_cash_merger(
            "AAA",
            142.5,
            MERGER_BOUNDARY,
            old_security_id="old-common",
            election_policy="declared_no_election_default_cash",
        )
    assert broker.ledger() == before


# Stale positive quotes cannot resurrect a terminated security or a later share grant.
def test_terminal_security_cannot_be_bought_split_or_recredited():
    broker = account(1000, 0, holdings={"AAA": 20, "BBB": 100})
    broker.apply_cash_merger(
        "AAA",
        142.5,
        MERGER_BOUNDARY,
        old_security_id="old-common",
        election_policy="declared_no_election_default_cash",
    )
    broker.observe(LATER, {"AAA": 999, "BBB": 10}, True)
    before = broker.ledger()
    with pytest.raises(AlpacaTradingError, match="terminated_security"):
        broker.submit_market("AAA", 1, "buy", "stale-quote")
    assert broker.attempt_history[-1]["reason"] == "terminated_security"
    assert broker.attempt_history[-1]["observed_price"] is None
    with pytest.raises(ValueError, match="Terminated security"):
        broker.apply_split("AAA", 2, LATER)
    with pytest.raises(ValueError, match="Terminated child"):
        broker.apply_stock_distribution(
            "BBB", "AAA", 1, 5, LATER, parent_basis_fraction=0.75
        )
    assert broker.ledger() == before


# Whole reverse-split entitlements retain cost while cash fractions cannot fund trades.
@pytest.mark.parametrize("quantity", [0, 1, 24, 25, 100])
def test_consolidation_keeps_whole_shares_and_unknown_fractional_cash(quantity):
    broker = account(1000, 0, holdings={"AAA": quantity})
    broker.observe(NOW, {"AAA": 48}, True)
    broker.apply_share_consolidation(
        "AAA", 1, 6, NOW, fractional_policy="cash_in_lieu_unknown"
    )
    ledger = broker.ledger()
    whole = quantity // 6
    assert ledger["holdings"] == ({"AAA": whole} if whole else {})
    assert ledger["cash"] == 1000
    assert "security_exchanges" not in ledger
    row = ledger["share_consolidations"][0]
    assert row["fractional_qty"] == pytest.approx((quantity % 6) / 6)
    assert row["cash_in_lieu"] is None
    assert whole * ledger["average_prices"].get("AAA", 0) + row[
        "fractional_basis"
    ] == pytest.approx(quantity * 8)
    if quantity % 6:
        with pytest.raises(AlpacaTradingError, match="Unknown consolidation"):
            broker.account()
        with pytest.raises(AlpacaTradingError, match="Unknown consolidation"):
            broker.submit_market("AAA", 1, "buy", "unfunded")
        assert broker.open_orders() == []
    else:
        assert broker.account().equity == 1000 + whole * 48
    broker.apply_share_consolidation(
        "AAA", 1, 6, NOW, fractional_policy="cash_in_lieu_unknown"
    )
    assert broker.ledger() == ledger


# Payment evidence becomes cash once, with no amount inferred from prices or basis.
def test_consolidation_cash_is_observed_and_idempotent():
    broker = account(1000, 0, holdings={"AAA": 25})
    broker.apply_share_consolidation(
        "AAA", 1, 6, NOW, fractional_policy="cash_in_lieu_unknown"
    )
    before = broker.ledger()
    with pytest.raises(ValueError, match="Observed consolidation payment"):
        broker.settle_consolidation_cash("AAA", NOW, 3, LATER)
    assert broker.ledger() == before
    broker.observe(LATER, {"AAA": 48}, True)
    broker.settle_consolidation_cash("AAA", NOW, 3, LATER)
    assert broker.account().cash == broker.account().buying_power == 1003
    assert broker.account().equity == 1195
    paid = broker.ledger()
    assert (
        paid["share_consolidations"][0]["observed_payment_at"]
        == "2026-08-03T14:00:00+00:00"
    )
    broker.settle_consolidation_cash("AAA", NOW, 3, LATER)
    assert broker.ledger() == paid
    with pytest.raises(ValueError, match="Conflicting consolidation payment"):
        broker.settle_consolidation_cash("AAA", NOW, 4, LATER)
    assert broker.ledger() == paid


# Invalid consolidation terms or old fractional holdings leave the ledger untouched.
@pytest.mark.parametrize(
    "defect", ["zero", "bool", "forward", "policy", "future", "fractional", "conflict"]
)
def test_consolidation_invalid_terms_are_atomic(defect):
    broker = account(1000, 0, holdings={"AAA": 25})
    numerator, denominator, effective, policy = 1, 6, NOW, "cash_in_lieu_unknown"
    if defect == "zero":
        numerator = 0
    elif defect == "bool":
        denominator = True
    elif defect == "forward":
        numerator = 6
    elif defect == "policy":
        policy = "floor_no_compensation"
    elif defect == "future":
        effective = LATER
    elif defect == "fractional":
        broker.apply_split("AAA", 0.5, NOW)
    else:
        broker.apply_share_consolidation("AAA", 1, 6, NOW, fractional_policy=policy)
        denominator = 5
    before = broker.ledger()
    expected = {
        "zero": "Explicit reverse ratio",
        "bool": "Explicit reverse ratio",
        "forward": "Explicit reverse ratio",
        "policy": "Explicit reverse ratio",
        "future": "Observed dated corporate action",
        "fractional": "Whole pre-consolidation",
        "conflict": "Conflicting corporate-action evidence",
    }[defect]
    with pytest.raises(ValueError, match=expected):
        broker.apply_share_consolidation(
            "AAA", numerator, denominator, effective, fractional_policy=policy
        )
    assert broker.ledger() == before


# Old-share orders and fills need explicit treatment before a consolidation can apply.
@pytest.mark.parametrize("filled", [False, True])
def test_consolidation_cannot_rewrite_outstanding_orders_or_affected_fills(filled):
    broker = account(1000, 0, holdings={"AAA": 25})
    broker.submit_market("AAA", 1, "sell", "old-shares")
    if filled:
        broker.flush(LATER, {"AAA": 10})
        broker.observe(LATER, {"AAA": 10}, True)
    before = broker.ledger()
    with pytest.raises(
        ValueError, match="affected fills" if filled else "Outstanding orders"
    ):
        broker.apply_share_consolidation(
            "AAA", 1, 6, NOW, fractional_policy="cash_in_lieu_unknown"
        )
    assert broker.ledger() == before


# Whole entitlements cannot acquire cash merely because a receipt is supplied.
def test_consolidation_cash_requires_an_existing_fractional_claim():
    broker = account(1000, 0, holdings={"AAA": 24})
    broker.apply_share_consolidation(
        "AAA", 1, 6, NOW, fractional_policy="cash_in_lieu_unknown"
    )
    before = broker.ledger()
    with pytest.raises(ValueError, match="Existing fractional consolidation"):
        broker.settle_consolidation_cash("AAA", NOW, 3, NOW)
    assert broker.ledger() == before


# Apply the declared holder-level rounding without cash or a tradable fraction.
@pytest.mark.parametrize("quantity", [0, 1, 24, 25, 100])
def test_named_security_exchange_floors_shares_and_records_forfeited_basis(quantity):
    broker = account(1000, 0, holdings={"AAA": quantity})
    broker.apply_security_exchange(
        "AAA",
        1,
        5,
        NOW,
        old_security_id="old-issuer-common",
        new_security_id="new-issuer-common",
        fractional_policy="floor_no_compensation",
    )
    whole = quantity // 5
    assert broker.ledger()["holdings"] == ({"AAA": whole} if whole else {})
    assert broker.ledger()["cash"] == 1000
    assert "security_distributions" not in broker.ledger()
    event = broker.ledger()["security_exchanges"][0]
    assert event["old_security_id"] != event["new_security_id"]
    assert event["quantity_before"] == quantity
    assert event["quantity_after"] == whole
    assert event["forfeited_fraction"] == pytest.approx((quantity % 5) / 5)
    assert event["cash_credit"] == 0
    basis = broker.ledger()["average_prices"].get("AAA", 0)
    assert whole * basis + event["forfeited_basis"] == pytest.approx(quantity * 8)
    assert broker.account().equity == 1000 + whole * 10
    broker.apply_security_exchange(
        "AAA",
        1,
        5,
        NOW,
        old_security_id="old-issuer-common",
        new_security_id="new-issuer-common",
        fractional_policy="floor_no_compensation",
    )
    assert len(broker.ledger()["security_exchanges"]) == 1


# Invalid or conflicting security terms leave both holdings and cash unchanged.
@pytest.mark.parametrize(
    "change",
    [
        "zero_ratio",
        "bool_ratio",
        "same_id",
        "empty_id",
        "cash_policy",
        "future",
        "conflict",
    ],
)
def test_security_exchange_rejects_unsupported_or_changed_terms_atomically(change):
    broker = account(1000, 0, holdings={"AAA": 24})
    args = dict(
        old_security_id="old-issuer-common",
        new_security_id="new-issuer-common",
        fractional_policy="floor_no_compensation",
    )
    numerator, denominator, effective = 1, 5, NOW
    if change == "zero_ratio":
        numerator = 0
    elif change == "bool_ratio":
        denominator = True
    elif change == "same_id":
        args["new_security_id"] = args["old_security_id"]
    elif change == "empty_id":
        args["old_security_id"] = ""
    elif change == "cash_policy":
        args["fractional_policy"] = "cash_in_lieu_unknown"
    elif change == "future":
        effective = LATER
    else:
        broker.apply_security_exchange("AAA", 1, 5, NOW, **args)
        args["new_security_id"] = "different-new-issuer"
    before = broker.ledger()
    message = (
        "Observed dated corporate action required"
        if change == "future"
        else "Conflicting security exchange evidence"
        if change == "conflict"
        else "Explicit security identities, ratio and fractional policy required"
    )
    with pytest.raises(ValueError, match=message):
        broker.apply_security_exchange("AAA", numerator, denominator, effective, **args)
    assert broker.ledger() == before


# Old-security orders cannot silently become orders for a different issuer.
def test_security_exchange_requires_explicit_outstanding_order_treatment():
    broker = account(1000, 0, holdings={"AAA": 24})
    broker.submit_market("AAA", 1, "buy", "old-security-intent")
    before = broker.ledger()
    with pytest.raises(ValueError, match="Outstanding orders"):
        broker.apply_security_exchange(
            "AAA",
            1,
            5,
            NOW,
            old_security_id="old",
            new_security_id="new",
            fractional_policy="floor_no_compensation",
        )
    assert broker.ledger() == before
    assert broker.open_orders()[0]["qty"] == "1"


# A subsequent issuer exchange must start with the actual prior recorded issuer.
def test_security_exchange_cannot_relabel_an_unrelated_old_issuer():
    broker = account(1000, 0, holdings={"AAA": 100})
    broker.apply_security_exchange(
        "AAA",
        1,
        5,
        NOW,
        old_security_id="old",
        new_security_id="new",
        fractional_policy="floor_no_compensation",
    )
    broker.observe(LATER, {"AAA": 50, "BBB": 10}, True)
    before = broker.ledger()
    with pytest.raises(ValueError, match="Prior security identity"):
        broker.apply_security_exchange(
            "AAA",
            1,
            2,
            LATER,
            old_security_id="unrelated",
            new_security_id="latest",
            fractional_policy="floor_no_compensation",
        )
    assert broker.ledger() == before


# Fractional old positions need their own evidence instead of another inferred rounding.
def test_security_exchange_refuses_fractional_old_holdings_without_mutation():
    broker = account(1000, 0, holdings={"AAA": 25})
    broker.apply_split("AAA", 0.5, NOW)
    before = broker.ledger()
    with pytest.raises(ValueError, match="Whole old-security holdings"):
        broker.apply_security_exchange(
            "AAA",
            1,
            5,
            NOW,
            old_security_id="old",
            new_security_id="new",
            fractional_policy="floor_no_compensation",
        )
    assert broker.ledger() == before


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


# Known physical entitlements retain valued shares without a made-up tax allocation.
def test_unallocated_distribution_reports_unknown_basis_without_blocking_wealth():
    broker = ReplayBroker(
        50,
        0,
        initial_holdings={"AAA": 99, "BBB": 2},
        initial_average_prices={"AAA": 60, "BBB": 40},
    )
    broker.observe(NOW, {"AAA": 45, "BBB": 45}, True)
    broker.apply_stock_distribution(
        "AAA",
        "BBB",
        1,
        3,
        NOW,
        parent_basis_fraction=None,
        basis_policy="unallocated_at_effective_clock",
    )
    ledger = broker.ledger()
    assert ledger["holdings"] == {"AAA": 99, "BBB": 35}
    assert ledger["average_prices"] == {"AAA": None, "BBB": None}
    assert ledger["security_distributions"][0]["basis_before"] == {
        "parent_total": 5940,
        "child_total": 80,
    }
    assert ledger["security_distributions"][0]["fractional_basis"] == 0
    assert broker.account().equity == 6080
    assert broker.account().cash == broker.account().buying_power == 50
    assert all(
        p.avg_entry_price is None and p.unrealized_pl is None
        for p in broker.positions()
    )
    broker.apply_stock_distribution(
        "AAA",
        "BBB",
        1,
        3,
        NOW,
        parent_basis_fraction=None,
        basis_policy="unallocated_at_effective_clock",
    )
    assert broker.ledger() == ledger
    with pytest.raises(ValueError, match="Conflicting distribution basis"):
        broker.apply_stock_distribution(
            "AAA", "BBB", 1, 3, NOW, parent_basis_fraction=0.75
        )
    assert broker.ledger() == ledger


# Adding or partly selling an unknown-basis lot cannot turn its cost into zero.
def test_unallocated_basis_survives_trades_until_the_position_is_fully_closed():
    broker = account(1000, 0, holdings={"AAA": 6})
    broker.apply_stock_distribution(
        "AAA",
        "BBB",
        1,
        3,
        NOW,
        parent_basis_fraction=None,
        basis_policy="unallocated_at_effective_clock",
    )
    broker.submit_market("BBB", 1, "buy", "add")
    broker.flush(LATER, {"BBB": 10})
    broker.observe(LATER, {"AAA": 10, "BBB": 10}, True)
    assert broker.ledger()["average_prices"]["BBB"] is None
    broker.submit_market("BBB", 1, "sell", "partial")
    broker.flush("2026-08-03T10:15:00-04:00", {"BBB": 10})
    broker.observe("2026-08-03T10:15:00-04:00", {"AAA": 10, "BBB": 10}, True)
    assert broker.ledger()["holdings"]["BBB"] == 2
    assert broker.ledger()["average_prices"]["BBB"] is None
    broker.submit_market("BBB", 2, "sell", "close")
    broker.flush("2026-08-03T10:30:00-04:00", {"BBB": 10})
    broker.observe("2026-08-03T10:30:00-04:00", {"AAA": 10, "BBB": 11}, True)
    assert "BBB" not in broker.ledger()["average_prices"]
    broker.submit_market("BBB", 1, "buy", "new-lot")
    broker.flush("2026-08-03T10:45:00-04:00", {"BBB": 11})
    broker.observe("2026-08-03T10:45:00-04:00", {"AAA": 10, "BBB": 12}, True)
    assert broker.ledger()["average_prices"]["BBB"] == 11
    assert broker.positions()[1].unrealized_pl == 1


# Corporate actions propagate unknown cost while still changing physical quantities.
@pytest.mark.parametrize("kind", ["split", "consolidation", "exchange", "distribution"])
def test_subsequent_share_actions_preserve_unallocated_basis(kind):
    broker = account(1000, 0, holdings={"AAA": 99})
    broker.apply_stock_distribution(
        "AAA",
        "BBB",
        1,
        3,
        NOW,
        parent_basis_fraction=None,
        basis_policy="unallocated_at_effective_clock",
    )
    broker.observe(LATER, {"AAA": 10, "BBB": 10, "CCC": 10}, True)
    if kind == "split":
        broker.apply_split("BBB", 2, LATER)
    elif kind == "consolidation":
        broker.apply_share_consolidation(
            "BBB", 1, 3, LATER, fractional_policy="cash_in_lieu_unknown"
        )
    elif kind == "exchange":
        broker.apply_security_exchange(
            "BBB",
            1,
            5,
            LATER,
            old_security_id="old",
            new_security_id="new",
            fractional_policy="floor_no_compensation",
        )
    else:
        broker.apply_stock_distribution(
            "BBB", "CCC", 1, 3, LATER, parent_basis_fraction=0.75
        )
    assert broker.ledger()["average_prices"]["BBB"] is None


# Fractional cash remains unavailable independently of acquisition cost.
def test_unallocated_fractional_distribution_still_requires_observed_cash():
    broker = account(1000, 0, holdings={"AAA": 100})
    broker.apply_stock_distribution(
        "AAA",
        "BBB",
        1,
        3,
        NOW,
        parent_basis_fraction=None,
        basis_policy="unallocated_at_effective_clock",
    )
    assert broker.ledger()["security_distributions"][0]["fractional_basis"] is None
    with pytest.raises(AlpacaTradingError, match="Unknown distribution"):
        broker.account()
    broker.settle_distribution_cash("AAA", "BBB", NOW, 3, NOW)
    assert broker.account().equity == 2333
    assert broker.ledger()["average_prices"] == {"AAA": None, "BBB": None}


# Explicit uncertainty is required; invalid policy or a numerical guess changes nothing.
@pytest.mark.parametrize(
    ("fraction", "policy"),
    [(None, None), (None, "guess"), (0.75, "unallocated_at_effective_clock")],
)
def test_unknown_distribution_basis_cannot_be_implicit_or_guessed(fraction, policy):
    broker = account(1000, 0, holdings={"AAA": 99})
    before = broker.ledger()
    with pytest.raises(ValueError, match="distribution basis policy"):
        broker.apply_stock_distribution(
            "AAA", "BBB", 1, 3, NOW, parent_basis_fraction=fraction, basis_policy=policy
        )
    assert broker.ledger() == before


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
