"""Private venue conservation from explicit fixtures, without data/model/sender I/O."""

import base64
import hashlib
import json
from copy import deepcopy
from decimal import Decimal

import pytest

from backend.market import historical_timing_packet as packets
from backend.market import replay_broker as native
from backend.market.historical_timing_resolver import PilotResolver

WINDOW = packets.schedule("2019-03-01T14:45:00Z")
SUBMITTED = WINDOW["assumed_submission_at"]
DEADLINE = WINDOW["quote_end"]


# Supply only labelled synthetic authenticated packet bytes, never a provider GET.
def source(*, bid=10, ask=10.01, missing=False, late=False, events=None):
    rows = (
        events
        if events is not None
        else (
            []
            if missing
            else [
                {
                    "t": "2019-03-01T14:45:32Z" if late else "2019-03-01T14:45:31.332Z",
                    "bp": bid,
                    "ap": ask,
                    "bs": 1,
                    "as": 1,
                }
            ]
        )
    )
    body = json.dumps({"quotes": {"AAPL": rows}, "next_page_token": None}).encode()
    raw = json.dumps(
        {
            "complete": True,
            "failure": None,
            "pages": [
                {
                    "url": packets.quote_request(WINDOW),
                    "status": 200,
                    "requested_at": "2026-10-17T12:30:00Z",
                    "received_at": "2026-10-17T12:30:01Z",
                    "body_base64": base64.b64encode(body).decode(),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            ],
        }
    ).encode()
    return packets.source_packet(
        WINDOW,
        raw,
        hashlib.sha256(raw).hexdigest(),
        "2026-10-17T12:31:00Z",
        kind="quotes",
    )


# Construct an exact native broker at a declared conditional submission clock.
def broker(cash=1000, held=None, averages=None, marks=None):
    held = held or {}
    client = native.ReplayBroker(
        cash,
        10,
        initial_holdings=held,
        initial_average_prices=averages or {name: 8 for name in held},
    )
    client.observe(SUBMITTED, marks or {"AAPL": 10, "BBB": 10}, True)
    return client


# Resolve native accepted receipts while keeping all input declarations explicit.
def resolve(client, orders, packet=None, resolver=None, **changes):
    arguments = {
        "window": WINDOW,
        "submitted": orders,
        "packet": packet if packet is not None else source(),
        "at": DEADLINE,
    }
    arguments.update(changes)
    return (resolver or PilotResolver(client)).resolve(**arguments)


# Compare against independent decimal cash or fee calculations at a strict tolerance.
def amount(actual, expected):
    assert actual == pytest.approx(float(Decimal(str(expected))), rel=1e-13, abs=1e-12)


# Keep side-specific prices, FIFO ties and pre-batch cash independent of sale proceeds.
def test_same_symbol_opposite_sides_cannot_reuse_sale_proceeds():
    client = broker(cash=100, held={"AAPL": 3})
    sell = client.submit_market("AAPL", 3, "sell", "sell-first")
    buy = client.submit_market("AAPL", 9, "buy", "buy-second")
    original = deepcopy([buy, sell])
    receipt = resolve(client, [buy, sell], source(bid=20, ask=20.01))
    outcomes = receipt["outcomes"]
    assert [row["client_order_id"] for row in outcomes] == ["sell-first", "buy-second"]
    assert [row["price"] for row in outcomes] == [20, 20.01]
    assert [row["filled_qty"] for row in outcomes] == [3, 4]
    assert outcomes[1]["requested_qty"] == 9
    assert outcomes[1]["status"] == "expired"
    amount(outcomes[0]["fee"], ".06")
    amount(outcomes[1]["fee"], ".08004")
    amount(client.ledger()["cash"], "79.81996")
    amount(receipt["initial_budget"], "100")
    amount(receipt["remaining_budget"], "19.87996")
    assert client.ledger()["holdings"] == {"AAPL": 4}
    amount(client.ledger()["average_prices"]["AAPL"], "20.01")
    assert [buy, sell] == original
    assert client._orders["buy-second"]["qty"] == "9"
    assert client._orders["buy-second"]["submitted_at"] == buy["submitted_at"]
    assert all(row["at"] == "2019-03-01T14:45:31.333000+00:00" for row in outcomes)
    assert receipt["actual_fills_proven"] is False


# Retain unrelated queued reservations while a price gap reduces a whole-share fill.
def test_nondue_reservation_survives_and_partial_basis_ignores_fees():
    client = broker()
    other = client.submit_market_on_close("BBB", 50, "buy", "closing-reservation")
    original_other = deepcopy(other)
    buy = client.submit_market("AAPL", 40, "buy", "gap")
    receipt = resolve(client, [buy], source(bid=199.99, ask=200))
    amount(receipt["nondue_reserved_cash"], "500.5")
    amount(receipt["initial_budget"], "499.5")
    amount(receipt["remaining_budget"], "99.1")
    amount(client.ledger()["cash"], "599.6")
    assert client.ledger()["holdings"] == {"AAPL": 2}
    assert client.ledger()["average_prices"] == {"AAPL": 200}
    assert receipt["outcomes"][0]["filled_qty"] == 2
    amount(receipt["outcomes"][0]["fee"], ".4")
    assert client._orders["closing-reservation"] == original_other
    assert client.open_orders() == [original_other]
    client.observe(DEADLINE, {"AAPL": 200}, True)
    amount(client.account().buying_power, "99.1")


# Blend original acquisition cost with fill notional while fees only reduce cash.
def test_native_weighted_acquisition_basis_is_preserved():
    client = broker(held={"AAPL": 2}, averages={"AAPL": 50})
    buy = client.submit_market("AAPL", 2, "buy", "add")
    receipt = resolve(client, [buy], source(bid=119.99, ask=120))
    amount(client.ledger()["cash"], "759.76")
    amount(client.ledger()["average_prices"]["AAPL"], "85")
    amount(receipt["outcomes"][0]["fee"], ".24")
    assert client.ledger()["holdings"] == {"AAPL": 4}


# A split residue remains fractional even though the submitted and filled sale is whole.
def test_fractional_native_holding_is_not_rounded_or_refused():
    client = broker(held={"AAPL": 10})
    client.apply_split("AAPL", 0.25, "2019-03-01T14:30:00Z")
    client.observe(SUBMITTED, {"AAPL": 10}, True)
    sell = client.submit_market("AAPL", 2, "sell", "covered-whole")
    receipt = resolve(client, [sell])
    assert receipt["outcomes"][0]["filled_qty"] == 2
    assert client.ledger()["holdings"] == {"AAPL": 0.5}
    assert client.ledger()["average_prices"] == {"AAPL": 32}
    amount(client.ledger()["cash"], "1019.98")
    client.observe(DEADLINE, {"AAPL": 10}, True)
    amount(client.account().equity, "1024.98")


# Unknown allocated acquisition cost stays unknown without hiding held marked value.
def test_unknown_basis_and_unrelated_corporate_claims_are_preserved():
    client = broker(held={"BBB": 10})
    client.apply_stock_distribution(
        "BBB",
        "AAPL",
        1,
        1,
        "2019-03-01T14:30:00Z",
        parent_basis_fraction=None,
        basis_policy="unallocated_at_effective_clock",
    )
    client.observe(SUBMITTED, {"AAPL": 10, "BBB": 10}, True)
    client.accrue_dividend("BBB", 1, "2019-03-01T00:00:00Z")
    before = client.ledger()
    buy = client.submit_market("AAPL", 2, "buy", "unknown-cost-add")
    receipt = resolve(client, [buy], source(bid=10.99, ask=11))
    after = client.ledger()
    assert after["holdings"] == {"BBB": 10, "AAPL": 12}
    assert after["average_prices"] == {"BBB": None, "AAPL": None}
    assert after["dividends"] == before["dividends"]
    assert after["security_distributions"] == before["security_distributions"]
    amount(after["cash"], "977.978")
    amount(receipt["initial_budget"], "1000")
    client.observe(DEADLINE, {"AAPL": 11, "BBB": 10}, True)
    amount(client.account().equity, "1219.978")


# Native zero acquisition cost remains zero through a covered partial disposal.
def test_native_zero_basis_is_preserved_without_requiring_positive_cost():
    client = broker(held={"AAPL": 2}, averages={"AAPL": 5e-324})
    client.apply_stock_distribution(
        "AAPL", "BBB", 1, 1, "2019-03-01T14:30:00Z", parent_basis_fraction=0.5
    )
    assert client.ledger()["average_prices"] == {"AAPL": 0, "BBB": 0}
    client.observe(SUBMITTED, {"AAPL": 10, "BBB": 10}, True)
    order = client.submit_market("AAPL", 1, "sell", "zero-basis")
    resolve(client, [order])
    assert client.ledger()["average_prices"] == {"AAPL": 0, "BBB": 0}
    assert client.ledger()["holdings"] == {"AAPL": 1, "BBB": 2}
    amount(client.ledger()["cash"], "1009.99")


# Keep unpaid receivables out of the spendable budget even when they increase NAV.
def test_receivables_do_not_fund_conditional_buys():
    client = broker(cash=100, held={"BBB": 100})
    client.accrue_dividend("BBB", 10, "2019-03-01T00:00:00Z")
    buy = client.submit_market("AAPL", 9, "buy", "cash-only")
    receipt = resolve(client, [buy], source(bid=19.99, ask=20))
    assert receipt["outcomes"][0]["filled_qty"] == 4
    amount(receipt["initial_budget"], "100")
    amount(client.ledger()["cash"], "19.92")
    assert client.ledger()["dividends"][0]["paid"] is False


# A complete empty packet expires only this batch at its declared deadline.
def test_complete_missing_reference_expires_without_a_price_or_fabricated_fill():
    client = broker()
    buy = client.submit_market("AAPL", 2, "buy", "missing")
    before = client.ledger()
    receipt = resolve(client, [buy], source(missing=True))
    assert receipt["outcomes"][0] == {
        "client_order_id": "missing",
        "symbol": "AAPL",
        "side": "buy",
        "requested_qty": 2,
        "filled_qty": 0,
        "price": None,
        "fee": 0,
        "at": "2019-03-01T14:45:33+00:00",
        "status": "expired",
        "reason": "missing_execution_price",
    }
    assert client.ledger() == before
    assert client._orders["missing"]["filled_qty"] == "0"
    assert "filled_at" not in client._orders["missing"]
    assert client._orders["missing"]["reserved_cash"] == 0
    assert receipt["references"][0]["reference"]["status"] == "unavailable"


# A cheaper later event cannot replace the first conservatively qualified reference.
def test_resolver_derives_first_reference_instead_of_choosing_a_later_price():
    client = broker()
    order = client.submit_market("AAPL", 2, "buy", "first-reference")
    events = [
        {"t": "2019-03-01T14:45:31.332Z", "bp": 10, "ap": 10.01, "bs": 1, "as": 1},
        {"t": "2019-03-01T14:45:32Z", "bp": 1, "ap": 1.001, "bs": 1, "as": 1},
    ]
    receipt = resolve(client, [order], source(events=events))
    assert receipt["outcomes"][0]["price"] == 10.01
    assert receipt["references"][0]["reference"]["event_at"] == events[0]["t"]


# Earlier current clocks cannot consume later packet events or future expirations.
@pytest.mark.parametrize("at", ["2019-03-01T14:45:31Z", "2019-03-01T14:45:34Z"])
def test_current_conditional_deadline_is_required_before_any_mutation(at):
    client = broker()
    order = client.submit_market("AAPL", 1, "buy", "deadline")
    before = deepcopy(client.__dict__)
    with pytest.raises(ValueError, match="fixed deadline"):
        resolve(client, [order], source(missing=True), at=at)
    assert client.__dict__ == before


# An exact retry returns detached evidence without applying native arithmetic twice.
def test_second_resolution_is_idempotent_and_input_drift_is_rejected():
    client = broker()
    order = client.submit_market("AAPL", 2, "buy", "once")
    resolver, packet = PilotResolver(client), source()
    first = resolve(client, [order], packet, resolver)
    state = deepcopy(client.__dict__)
    second = resolve(client, [order], packet, resolver)
    assert second == first
    assert client.__dict__ == state
    second["outcomes"][0]["filled_qty"] = 999
    assert resolve(client, [order], packet, resolver) == first
    changed = deepcopy(order)
    changed["qty"] = "3"
    with pytest.raises(ValueError, match="Completed pilot"):
        resolve(client, [changed], packet, resolver)
    assert client.__dict__ == state


# A new observed account batch cannot be silently treated as an unchanged retry.
def test_second_resolution_rejects_changed_broker_state():
    client = broker()
    order = client.submit_market("AAPL", 2, "buy", "changed-state")
    resolver, packet = PilotResolver(client), source()
    resolve(client, [order], packet, resolver)
    client.observe(DEADLINE, {"AAPL": 10}, True)
    before = deepcopy(client.__dict__)
    with pytest.raises(ValueError, match="Completed pilot"):
        resolve(client, [order], packet, resolver)
    assert client.__dict__ == before


# Accepted decision-clock receipts are never relabelled as delayed submissions.
def test_native_submission_clock_must_already_match_declared_submission():
    client = native.ReplayBroker(1000, 10)
    client.observe("2019-03-01T14:45:31.1Z", {"AAPL": 10}, True)
    order = client.submit_market("AAPL", 1, "buy", "not-delayed")
    before = deepcopy(client.__dict__)
    with pytest.raises(ValueError, match="fixed-clock"):
        resolve(client, [order])
    assert client.__dict__ == before


# A previous session's accepted market request cannot hide as a nondue reservation.
def test_stale_accepted_market_request_rejects_before_any_mutation():
    client = native.ReplayBroker(1000, 10)
    client.observe("2019-02-28T20:45:31.2Z", {"AAPL": 10}, True)
    client.submit_market("AAPL", 1, "buy", "old-unresolved")
    client.observe(SUBMITTED, {"AAPL": 10}, True)
    current = client.submit_market("AAPL", 1, "buy", "current")
    before = deepcopy(client.__dict__)
    with pytest.raises(ValueError, match="Stale accepted market"):
        resolve(client, [current])
    assert client.__dict__ == before


# A mutated market session cannot conceal an accepted current request as nondue.
@pytest.mark.parametrize("day", ["2019-02-28", "2019-03-04"])
def test_market_execute_on_must_match_original_local_submission_date(day):
    client = broker()
    client.submit_market("AAPL", 1, "buy", "mutated-session")
    client._orders["mutated-session"]["execute_on"] = day
    before = deepcopy(client.__dict__)
    with pytest.raises(ValueError, match="Market execution session"):
        resolve(client, [])
    assert client.__dict__ == before


# Every held symbol must receive a new mark before valuation can resume.
def test_execution_marks_never_become_fresh_nav_observations():
    client = broker(held={"BBB": 1})
    order = client.submit_market("AAPL", 2, "buy", "marks")
    receipt = resolve(client, [order])
    assert receipt["nav"] is None
    with pytest.raises(native.AlpacaTradingError, match="Fresh observed account"):
        client.account()
    client.observe(DEADLINE, {"AAPL": 10}, True)
    with pytest.raises(native.AlpacaTradingError, match="BBB"):
        client.account()
    client.observe(DEADLINE, {"AAPL": 10, "BBB": 10}, True)
    amount(client.account().equity, "1009.95998")


# Bad final bindings cannot leave earlier valid orders partially resolved.
@pytest.mark.parametrize(
    "defect", ["omit", "duplicate", "side", "qty", "phase", "clock", "unbound"]
)
def test_entire_due_set_and_original_binding_are_atomic(defect):
    client = broker()
    orders = [client.submit_market("AAPL", 1, "buy", str(index)) for index in range(2)]
    altered = deepcopy(orders)
    if defect == "omit":
        altered.pop()
    elif defect == "duplicate":
        altered[1] = deepcopy(altered[0])
    elif defect == "unbound":
        altered[1]["client_order_id"] = "other"
    else:
        key, value = {
            "side": ("side", "sell"),
            "qty": ("qty", "2"),
            "phase": ("execution_phase", "open"),
            "clock": ("submitted_at", WINDOW["assumed_decision_at"]),
        }[defect]
        altered[1][key] = value
    before = deepcopy(client.__dict__)
    with pytest.raises(ValueError, match="due CID|binding differs"):
        resolve(client, altered)
    assert client.__dict__ == before


# Float or boolean equality cannot reinterpret a native whole submitted quantity.
@pytest.mark.parametrize(
    "defect", ["float", "bool", "reason", "accepted", "reservation"]
)
def test_native_attempt_corruption_is_atomic(defect):
    client = broker()
    order = client.submit_market("AAPL", 1, "buy", "attempt")
    if defect in ("float", "bool"):
        client._attempts[0]["qty"] = 1.0 if defect == "float" else True
    elif defect == "reason":
        client._attempts[0]["reason"] = "insufficient_reserved_cash"
    elif defect == "accepted":
        client._attempts[0]["accepted"] = 1
    else:
        client._orders["attempt"]["reserved_cash"] = 0.0
        order["reserved_cash"] = 0.0
    before = deepcopy(client.__dict__)
    with pytest.raises(ValueError, match="Original"):
        resolve(client, [order])
    assert client.__dict__ == before


# Detached references and other symbols cannot bypass pilot authentication.
def test_detached_reference_and_unsupported_due_symbol_are_refused():
    client = broker()
    order = client.submit_market("BBB", 1, "buy", "unsupported")
    before = deepcopy(client.__dict__)
    with pytest.raises(ValueError, match="immutable"):
        resolve(client, [order], {"price": 1})
    with pytest.raises(ValueError, match="AAPL pilot"):
        resolve(client, [order])
    assert client.__dict__ == before


# Native submit already enforces covered reservations, which resolution must preserve.
def test_nondue_share_reservation_is_not_sold_by_the_pilot():
    client = broker(held={"AAPL": 5})
    close = client.submit_market_on_close("AAPL", 3, "sell", "reserved-close")
    sell = client.submit_market("AAPL", 2, "sell", "covered-due")
    with pytest.raises(native.AlpacaTradingError, match="uncovered_sell"):
        client.submit_market("AAPL", 1, "sell", "uncovered")
    resolve(client, [sell])
    assert client.ledger()["holdings"] == {"AAPL": 3}
    assert client.open_orders() == [close]


# A post-submission action cannot let this batch consume unrelated covered shares.
def test_post_action_overreserved_shares_reject_entire_batch():
    client = broker(held={"AAPL": 10})
    client.submit_market_on_close("AAPL", 6, "sell", "close-cover")
    order = client.submit_market("AAPL", 4, "sell", "due-cover")
    client.apply_split("AAPL", 0.5, "2019-03-01T14:30:00Z")
    before = deepcopy(client.__dict__)
    with pytest.raises(ValueError, match="sell reservations exceed"):
        resolve(client, [order])
    assert client.__dict__ == before


# Unknown fractional cash blocks native NAV even for an otherwise covered exit.
def test_unrelated_unknown_fractional_cash_claim_is_not_bypassed():
    client = broker(held={"AAPL": 2, "BBB": 1})
    order = client.submit_market("AAPL", 1, "sell", "exit-no-exemption")
    client.apply_stock_distribution(
        "BBB", "CCC", 1, 2, "2019-03-01T14:30:00Z", parent_basis_fraction=0.5
    )
    before = deepcopy(client.__dict__)
    with pytest.raises(native.AlpacaTradingError, match="cash-in-lieu"):
        resolve(client, [order])
    assert client.__dict__ == before


# Unexpected late native arithmetic failures leave the entire original broker unchanged.
def test_native_failure_after_first_preview_fill_is_atomic(monkeypatch):
    client = broker()
    orders = [client.submit_market("AAPL", 1, "buy", str(index)) for index in range(2)]
    original = native.ReplayBroker._fill

    # Fail on the second preview leg after the first has changed only the private copy.
    def failed_fill(self, row, price, now, budget):
        if row["client_order_id"] == "1":
            raise OverflowError("synthetic bounded failure")
        return original(self, row, price, now, budget)

    monkeypatch.setattr(native.ReplayBroker, "_fill", failed_fill)
    before = deepcopy(client.__dict__)
    with pytest.raises(ValueError, match="refused entire batch"):
        resolve(client, orders)
    assert client.__dict__ == before


# A subclass cannot widen the exact private broker admission used by the policy.
def test_exact_native_type_is_required():
    # Supply an unsupported subclass without changing native production code.
    class Other(native.ReplayBroker):
        pass

    with pytest.raises(ValueError, match="Exact ReplayBroker"):
        PilotResolver(Other(1000, 10))
