"""Sender quantities come from independent pre-clock balances, not saved requests."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import MappingProxyType, SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.market import entry_timing
from backend.market import live_model_history_pending_audit as pending
from backend.market.live_model_history_nightly_model import serialized
from backend.market.live_model_history_observation_context import (
    ObservationContext,
    detached,
)
from backend.market.live_model_history_pending_audit import apply_attempt
from backend.tests.test_live_model_history_pending_audit import evidence

OPEN = datetime.fromisoformat("2019-03-01T09:30:00-05:00")
NOW = OPEN + timedelta(minutes=15)


# Provide complete empty entitlement collections without any saved control state.
def records():
    return {
        name: []
        for name in (
            "security_distributions",
            "share_consolidations",
            "security_exchanges",
            "cash_mergers",
        )
    }


# Build independent economic facts for one controlled decision clock.
def context(*, cash=1000, held=None, economic=None, accepted=None, fills=None):
    held = {} if held is None else held
    value = ObservationContext(
        cash=cash,
        held=held,
        basis={name: 100 for name in held},
        dividends=[],
        records=records() if economic is None else economic,
        accepted=accepted or {},
        outcomes={},
        cancellations={},
        fills=fills or [],
        opening=OPEN,
    )
    value.advance(NOW, {"AAA": 100})
    return value


# Define a previously independently funded intent with immutable desired shares.
def row(side="buy"):
    return {
        "client_order_id": "funded-five",
        "symbol": "AAA",
        "side": side,
        "qty": 5,
        "execution": {"decision_at": "2019-02-28T16:01:00-05:00"},
    }


# Supply native receipt fields independently of the desired funded quantity.
def attempt(*, side="buy", qty=5, accepted=True, reason=None, cash=1000, at=None):
    return {
        "client_order_id": "funded-five",
        "symbol": "AAA",
        "side": side,
        "qty": qty,
        "at": (at or NOW).isoformat(),
        "accepted": accepted,
        "reason": reason,
        "observed_price": 100.0,
        "available_cash": cash,
    }


# Missing independent context can no longer admit arbitrary three-of-five requests.
def test_quantity_context_gap_is_closed():
    receipt = attempt(qty=3)
    with pytest.raises(ValueError, match="Independent sender context"):
        apply_attempt(
            row(), receipt, {"funded-five": receipt}, {"state": "execute"}, NOW
        )


# Buys cannot use a smaller saved request as their submitted quantity oracle.
@pytest.mark.parametrize("qty", [2, 3, 4, 5.0, True])
def test_corrupt_buy_quantity_rejected(qty):
    with pytest.raises(ValueError, match="submitted quantity"):
        context().admit(row(), attempt(qty=qty))


# A real partially covered sale preserves funded-five separately from submitted-three.
def test_exact_sell_clamp_and_integral_float_holdings():
    economic = context(held={"AAA": 3.0})
    funded, receipt = row("sell"), attempt(side="sell", qty=3)
    apply_attempt(
        funded,
        receipt,
        {"funded-five": receipt},
        {"state": "execute"},
        NOW,
        context=economic,
    )
    assert funded["qty"] == 5
    assert funded["sent"]["qty"] == 3
    assert economic.held == {"AAA": 3.0}


# Neither under-submission nor an uncovered fourth share can seed the sender output.
@pytest.mark.parametrize("qty", [2, 4])
def test_corrupt_sell_clamp_rejected(qty):
    with pytest.raises(ValueError, match="submitted quantity"):
        context(held={"AAA": 3}).admit(row("sell"), attempt(side="sell", qty=qty))


# Preserve fractional entitlements and floor only at the sender boundary.
def test_fractional_zero_sale_has_no_attempt():
    value = context(held={"AAA": 0.5})
    assert value.held["AAA"] == 0.5
    assert value.result(row("sell")) == {
        "kind": "no_quantity",
        "error": "no shares to sell",
    }
    with pytest.raises(ValueError, match="Unexpected original sender attempt"):
        value.admit(row("sell"), attempt(side="sell", qty=1))


# Prior accepted identities cannot become an invented crash-recovery adoption path.
def test_sequential_adoption_invariant():
    accepted = attempt(at=OPEN - timedelta(days=1))
    with pytest.raises(ValueError, match="adoption invariant"):
        context(accepted={"funded-five": accepted}).result(row())


# Current-clock outcome prices and shares remain unavailable until after the decision.
def test_same_clock_fill_is_excluded_and_prior_flush_is_included():
    accepted = attempt(at=OPEN - timedelta(days=1))
    fill = {
        "client_order_id": "funded-five",
        "symbol": "AAA",
        "side": "buy",
        "filled_qty": 5,
        "price": 100,
        "fee": 0.5,
        "at": NOW.isoformat(),
    }
    value = context(accepted={"funded-five": accepted}, fills=[fill])
    assert value.held == {}
    assert value.cash == 1000
    assert value.available() == 1000 - 500 * (1 + 10 / 10000)
    value.advance(NOW + timedelta(minutes=15), {"AAA": 100})
    assert value.held == {"AAA": 5}
    assert value.cash == 499.5
    assert value.available() == 499.5


# Unknown NAV empties only the old reader's staged holdings, not the sender's positions.
@pytest.mark.parametrize(
    "kind", ["security_distributions", "share_consolidations", "security_exchanges"]
)
def test_legacy_timing_held_differs_from_sender_held(kind):
    grants = records()
    grants[kind] = [{"fractional_qty": 0.5, "cash_in_lieu": None}]
    value = context(held={"AAA": 3}, economic=grants)
    assert value.timing_held == {}
    assert value.held == {"AAA": 3}
    fields = value.trace_fields(row("sell"), {"AAA": {"last": 100}}, [row("sell")])
    assert fields["observed_qty"] == 0
    assert fields["nav"] is None
    assert value.result(row("sell"))["kind"] == "pre_attempt_error"
    assert "cash-in-lieu" in value.result(row("sell"))["error"]


# Missing held marks stop the whole ready batch before any sending metadata is written.
def test_missing_held_mark_is_batch_failure():
    value = context(held={"BBB": 2})
    assert value.result(row()) == {
        "kind": "batch_unavailable",
        "error": "Fresh raw held mark unavailable for BBB",
    }


# A missing buy mark can fail after positions but before a native receipt exists.
def test_missing_buy_mark_is_pre_attempt_failure():
    value = context()
    value.advance(NOW + timedelta(minutes=15), {})
    assert value.result(row()) == {
        "kind": "pre_attempt_error",
        "error": "Fresh raw held mark unavailable for AAA",
    }


# Termination is independently sourced and precedes price and account requirements.
def test_termination_receipt_has_explicit_missing_price_and_cash():
    grants = records()
    grants["cash_mergers"] = [
        {
            "symbol": "AAA",
            "completed_before": OPEN.isoformat(),
            "amount": 0,
            "paid": False,
        }
    ]
    value = context(economic=grants)
    receipt = attempt(accepted=False, reason="terminated_security")
    receipt.update(observed_price=None, available_cash=None)
    value.admit(row(), receipt)
    assert value.requests == {}
    for key in ("observed_price", "available_cash"):
        corrupt = deepcopy(receipt)
        corrupt[key] = 100
        with pytest.raises(ValueError, match="missing state"):
            context(economic=grants).admit(row(), corrupt)


# A future or wrong-security action cannot authenticate a terminated refusal.
@pytest.mark.parametrize("mutation", ["future", "wrong", "absent"])
def test_false_termination_rejected(mutation):
    grants = records()
    if mutation != "absent":
        grants["cash_mergers"] = [
            {
                "symbol": "BBB" if mutation == "wrong" else "AAA",
                "completed_before": (
                    NOW + timedelta(minutes=15) if mutation == "future" else OPEN
                ).isoformat(),
                "amount": 0,
                "paid": False,
            }
        ]
    receipt = attempt(accepted=False, reason="terminated_security")
    receipt.update(observed_price=None, available_cash=None)
    with pytest.raises(ValueError, match="refusal differs"):
        context(economic=grants).admit(row(), receipt)


# Rejected requests can retry later without reserving imaginary cash.
def test_refusal_then_later_acceptance():
    value = context(cash=100)
    rejected = attempt(accepted=False, reason="insufficient_reserved_cash", cash=100)
    value.admit(row(), rejected)
    assert not value.requests
    value.advance(NOW + timedelta(minutes=15), {"AAA": 10})
    accepted = attempt(at=NOW + timedelta(minutes=15), cash=100)
    accepted["observed_price"] = 10
    value.admit(row(), accepted)
    assert value.requests["funded-five"] == accepted


# Submitted cash cannot be altered to justify a refusal or release a real reservation.
@pytest.mark.parametrize("mutation", ["cash", "reason", "accepted"])
def test_false_refusal_or_cash_rejected(mutation):
    receipt = attempt()
    if mutation == "cash":
        receipt["available_cash"] = 2000
    elif mutation == "reason":
        receipt.update(accepted=False, reason="insufficient_reserved_cash")
    else:
        receipt["accepted"] = False
    with pytest.raises(ValueError, match="differs"):
        context().admit(row(), receipt)


# Construction and observation do not mutate caller-owned account or receipt maps.
def test_context_detaches_all_input_maps():
    held, grants = {"AAA": 3.0}, records()
    value = context(held=held, economic=grants)
    held["AAA"] = 99
    grants["cash_mergers"].append({"untrusted": True})
    assert value.held == {"AAA": 3.0}
    assert value.records == records()


# Original nested MappingProxyType action sources retain values and exact clock types.
def test_original_readonly_source_metadata_detaches():
    mutable = {"sha256": "original", "nested": [1, (2, OPEN)]}
    actions = {
        "2019-03-01": [
            (
                OPEN,
                0,
                "AAA",
                {"kind": "archive_adjustment", "source": MappingProxyType(mutable)},
            )
        ]
    }
    value = ObservationContext(
        cash=1000,
        held={},
        basis={},
        dividends=[],
        records=records(),
        accepted={},
        outcomes={},
        cancellations={},
        fills=[],
        opening=OPEN,
        events=actions,
        entitlement_comparison={},
    )
    copied = value.events["2019-03-01"][0]
    assert type(copied) is tuple
    assert copied[0] is OPEN
    assert copied[3]["source"] == mutable
    mutable["nested"][0] = 99
    actions["2019-03-01"].clear()
    assert copied[3]["source"]["nested"][0] == 1
    copied[3]["source"]["sha256"] = "private copy"
    assert mutable["sha256"] == "original"


# A metadata object's custom copy protocol cannot execute during evidence admission.
def test_arbitrary_metadata_object_rejected():
    # Any custom copying would mean the primitive-only evidence boundary was bypassed.
    class Arbitrary:
        # Reject invocation so the test cannot pass through an object's copy hook.
        def __deepcopy__(self, memo):
            raise AssertionError("Arbitrary copy protocol invoked")

    with pytest.raises(ValueError, match="primitive"):
        detached({"source": Arbitrary()})


# Drive complete archived observations through the real pending fold's failure branches.
@pytest.mark.parametrize(
    "kind",
    [
        "zero_sell",
        "missing_buy",
        "missing_held",
        "unknown_nav",
        "terminated",
        "cash_refusal",
    ],
)
def test_complete_pending_failure_branch(kind):
    cash = 100 if kind == "cash_refusal" else 1000
    held = (
        {"AAA": 0.5}
        if kind == "zero_sell"
        else {"BBB": 1}
        if kind == "missing_held"
        else {"AAA": 3}
        if kind == "unknown_nav"
        else {}
    )
    grants = records()
    if kind == "unknown_nav":
        grants["security_distributions"] = [
            {"fractional_qty": 0.5, "cash_in_lieu": None}
        ]
    if kind == "terminated":
        grants["cash_mergers"] = [
            {
                "symbol": "AAA",
                "completed_before": OPEN.isoformat(),
                "amount": 0,
                "paid": False,
            }
        ]

    # Each execution gets a fresh independent seed, not the generated expected snapshot.
    def seed():
        return ObservationContext(
            cash=cash,
            held=held,
            basis={name: 100 for name in held},
            dividends=[],
            records=grants,
            accepted={},
            outcomes={},
            cancellations={},
            fills=[],
            opening=OPEN,
        )

    funded = {
        **row("sell" if kind == "zero_sell" else "buy"),
        "session": "2019-02-28",
        "execute_on": "2019-03-01",
        "execution_timing": "dip_or_close",
        "timing_policy": pending.POLICY,
        "sending": "2019-02-28T12:00:00-05:00",
    }
    previous = paper.PaperState(
        pending=[deepcopy(funded)],
        journal=[{"preserved": True}],
        history=[{"preserved": True}],
    )
    expected = deepcopy(previous)
    raw = SimpleNamespace(
        dates=np.array(["2019-03-01"], dtype="datetime64[D]"),
        tickers=("AAA",),
        session_open=np.full((1, 1), np.nan if kind == "missing_buy" else 100.0),
        observation_close=np.full(
            (1, 25, 1), np.nan if kind == "missing_buy" else 100.0
        ),
    )
    saved = {
        "session": "2019-03-01",
        "forecast_decisions": [],
        "observations": [],
        "attempts": [],
    }
    independent = seed()
    for slot in range(25):
        now = OPEN + (slot + 1) * entry_timing.BAR
        quotes = {} if kind == "missing_buy" else {"AAA": {"last": 100, "open": 100}}
        independent.advance(
            now, {name: quote["last"] for name, quote in quotes.items()}
        )
        saved["observations"].append(
            {"at": now.isoformat(), "due": serialized([funded]), "sender_logs": []}
        )
        if slot < 24:
            reason = independent.timing_error or (
                "unsupported learned clock"
                if slot > 22
                else "missing or stale completed raw quote"
                if kind == "missing_buy"
                else "no funded quantity"
                if kind == "zero_sell"
                else ""
            )
            fields = independent.trace_fields(funded, quotes, [funded])
            saved["forecast_decisions"].append(
                {
                    "policy": pending.POLICY,
                    "intent_id": funded["client_order_id"],
                    "symbol": "AAA",
                    "side": funded["side"],
                    "desired_qty": 5,
                    "observed_price": None if kind == "missing_buy" else 100,
                    "day": 0,
                    "clock": slot,
                    "at": now.isoformat(),
                    "state": "no_trade"
                    if reason == "no funded quantity"
                    else "unavailable"
                    if reason
                    else "wait",
                    "reason": reason,
                    **fields,
                }
            )
    last = saved["observations"][-1]
    final = OPEN + 25 * entry_timing.BAR
    error = (
        "no shares to sell"
        if kind == "zero_sell"
        else "Fresh raw held mark unavailable for AAA"
        if kind == "missing_buy"
        else "Fresh raw held mark unavailable for BBB"
        if kind == "missing_held"
        else "Unknown distribution cash-in-lieu prevents full NAV"
        if kind == "unknown_nav"
        else "terminated_security"
        if kind == "terminated"
        else "insufficient_reserved_cash"
    )
    if kind == "missing_held":
        last["sender_logs"] = [
            f"intraday orders: broker unavailable ({error}); nothing sent"
        ]
    else:
        expected.pending[0]["send_error"] = error
        if kind != "zero_sell":
            expected.pending[0]["sending"] = final.isoformat(timespec="seconds")
        prefix = f"{funded['side']} 5 AAA (market, close)"
        last["sender_logs"] = [
            prefix
            + (f": not sent ({error})" if kind == "zero_sell" else f": REFUSED {error}")
        ]
    if kind in ("terminated", "cash_refusal"):
        rejected = attempt(at=final, accepted=False, reason=error, cash=cash)
        if kind == "terminated":
            rejected.update(observed_price=None, available_cash=None)
        saved["attempts"] = [rejected]
    actual, scope = pending.fold_pending(
        previous,
        evidence(saved),
        {},
        {},
        raw,
        0,
        "2019-03-01",
        conserved_attempts=saved["attempts"],
        observation_context=seed(),
    )
    assert actual == expected
    assert scope["sender_quantity_context"] == "independently_folded_pre_clock"
    assert actual.journal == previous.journal
    assert actual.history == previous.history
