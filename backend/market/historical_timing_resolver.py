"""Private AAPL-pilot conditional venue, never a sender or actual fill claim.

Only already accepted native submissions at the fixed assumed submission clock
are consumed. The same immutable authenticated packet supplies all references.
Native arithmetic runs transactionally on an exact ReplayBroker copy. Auctions,
multi-symbol packets, sender clock transport and a complete runner are absent.
"""

import json
import math
from copy import deepcopy
from datetime import date

from backend.market import historical_timing_packet as packets
from backend.market import replay_broker as native
from backend.market.labels import OrderSide


# Reject corrupt financial evidence while preserving native fractional holdings.
def _number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Finite native numeric evidence required")
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError("Finite positive or nonnegative native evidence required")
    return value


# Bind original receipt values without equating booleans with numeric amounts.
def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


# Check a native accepted order before using its reservation or original identity.
def _order(identifier, row, index):
    if (
        not isinstance(identifier, str)
        or not identifier
        or row.get("client_order_id") != identifier
        or row.get("id") != f"private-replay-{index}"
        or row.get("status") != "accepted"
        or row.get("side") not in OrderSide
        or not isinstance(row.get("symbol"), str)
        or not row["symbol"]
        or row.get("type") != "market"
        or row.get("execution_phase") not in ("market", "open", "close")
        or row.get("time_in_force")
        != ("cls" if row["execution_phase"] == "close" else "day")
        or row.get("filled_qty") != "0"
        or row.get("filled_avg_price") is not None
        or _number(row.get("fee")) != 0.0
        or row.get("created_at") != row.get("submitted_at")
    ):
        raise ValueError("Original accepted native order identity required")
    quantity = row.get("qty")
    if (
        not isinstance(quantity, str)
        or not quantity.isascii()
        or not quantity.isdecimal()
        or int(quantity) <= 0
        or str(int(quantity)) != quantity
    ):
        raise ValueError("Original positive whole submitted quantity required")
    packets.nanos(row["submitted_at"])
    if date.fromisoformat(row["execute_on"]).isoformat() != row["execute_on"]:
        raise ValueError("Original execution session required")
    reserved = _number(row.get("reserved_cash"))
    if row["side"] == OrderSide.SELL and reserved != 0:
        raise ValueError("Native sell cannot reserve cash")
    return int(quantity), reserved


# Bind reservations to a unique successful native attempt with exact whole quantity.
def _attempt(broker, identifier, row, quantity, reserved):
    attempts = [
        item
        for item in broker._attempts
        if item.get("client_order_id") == identifier and item.get("accepted") is True
    ]
    if len(attempts) != 1:
        raise ValueError("Original unique accepted submission attempt required")
    attempt = attempts[0]
    if type(attempt.get("qty")) is not int or attempt.get("reason") is not None:
        raise ValueError("Original successful whole-quantity attempt required")
    if any(
        attempt.get(key) != value
        for key, value in (
            ("symbol", row["symbol"]),
            ("side", row["side"]),
            ("qty", quantity),
            ("at", row["submitted_at"]),
        )
    ):
        raise ValueError("Original accepted attempt binding differs")
    price = _number(attempt.get("observed_price"), positive=True)
    expected = (
        quantity * price * (1 + broker.cost_bps / 1e4)
        if row["side"] == OrderSide.BUY
        else 0.0
    )
    if not math.isfinite(expected) or reserved != expected:
        raise ValueError("Original observed-price cash reservation differs")
    if _number(attempt.get("available_cash")) < reserved:
        raise ValueError("Original accepted attempt exceeded its available cash")


# Validate every accepted reservation and the complete native market due set.
def _orders(broker, session):
    due, total_reserved, nondue_reserved, sell_reserved = [], 0.0, 0.0, {}
    for index, (identifier, row) in enumerate(broker._orders.items()):
        if row.get("status") != "accepted":
            continue
        quantity, reserved = _order(identifier, row, index)
        _market_session(broker, row, session)
        _attempt(broker, identifier, row, quantity, reserved)
        total_reserved += reserved
        if row["side"] == OrderSide.SELL:
            name = row["symbol"]
            sell_reserved[name] = sell_reserved.get(name, 0) + quantity
        if row["execution_phase"] == "market" and row["execute_on"] == session:
            due.append((index, row))
        else:
            nondue_reserved += reserved
    if not math.isfinite(total_reserved) or total_reserved > broker._cash:
        raise ValueError("Original aggregate cash reservations exceed cash")
    if any(
        quantity > broker._held.get(name, 0) for name, quantity in sell_reserved.items()
    ):
        raise ValueError("Original aggregate sell reservations exceed held shares")
    return due, nondue_reserved


# Reject stale or misdated market requests without expiring unrelated auction queues.
def _market_session(broker, row, session):
    submitted = native._instant(row["submitted_at"])
    if submitted > broker._now:
        raise ValueError("Original accepted submission exceeds current broker clock")
    if row["execution_phase"] != "market":
        return
    original_day = submitted.astimezone(native.calendar.NEW_YORK).date().isoformat()
    if row["execute_on"] != original_day or not native._session(submitted)[1]:
        raise ValueError("Market execution session differs from native submission")
    if row["execute_on"] != session:
        raise ValueError(
            "Stale accepted market request requires explicit prior outcome"
        )


# Preserve finite native cash, fractional shares and nullable acquisition bases.
def _ledger(broker):
    _number(broker._cash)
    if set(broker._held) != set(broker._average):
        raise ValueError("Native held shares and acquisition bases differ")
    for symbol, quantity in broker._held.items():
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("Original held symbol required")
        _number(quantity, positive=True)
        if broker._average[symbol] is not None:
            _number(broker._average[symbol])


# Derive every conservative reference from the sealed packet before native arithmetic.
def _references(window, packet, due, at):
    selected = []
    for index, row in due:
        reference = packets.execution_reference(window, packet, row["side"])
        available = reference["status"] == "available"
        instant = (
            packets.nanos(reference["event_at"])
            + packets.FIXED["event_timestamp_uncertainty_ns"]
            if available
            else packets.nanos(at)
        )
        if not packets.nanos(row["submitted_at"]) < instant <= packets.nanos(at):
            raise ValueError("Conditional reference exceeds current batch clock")
        selected.append((instant, index, row["client_order_id"], reference))
    return sorted(selected, key=lambda item: item[:2])


# Consume only the fixed pilot batch without changing the broker's native class.
class PilotResolver:
    # Retain one exact private broker and a detached completed-batch receipt.
    def __init__(self, broker):
        if type(broker) is not native.ReplayBroker:
            raise ValueError("Exact ReplayBroker required; no subclass or live client")
        self._broker = broker
        self._completed = None

    # Resolve the complete accepted pilot batch only at its fixed conditional deadline.
    def resolve(self, *, window, submitted, packet, at):
        packets._window(window)
        if type(packet) is not packets.ArchivedPacket or packet.kind != "quotes":
            raise ValueError("Exact immutable authenticated quote packet required")
        # Revalidate source bytes even when there are no due orders or a retry.
        packets._rows(window, packet, "quotes")
        if packets.nanos(at) != packets.nanos(window["quote_end"]):
            raise ValueError("Current conditional clock must equal the fixed deadline")
        if not isinstance(submitted, (list, tuple)) or any(
            not isinstance(row, dict) for row in submitted
        ):
            raise ValueError("Original submitted receipt list required")
        signature = _json(
            {
                "window": window,
                "submitted": submitted,
                "at": at,
                "source_sha256": packet.source_sha256,
                "verified_at": packet.verified_at,
            }
        )
        broker = self._broker
        if self._completed is not None:
            if (
                self._completed["signature"] != signature
                or self._completed["after"] != broker.__dict__
            ):
                raise ValueError("Completed pilot inputs or broker state changed")
            return deepcopy(self._completed["receipt"])
        due, reserved, before = self._validate(window, submitted)
        frozen_budget = max(0.0, broker._cash - reserved)
        selected = _references(window, packet, due, at)
        preview, budget = deepcopy(broker), frozen_budget
        first_fill = len(preview._fills)
        try:
            for instant, _, identifier, reference in selected:
                row = preview._orders[identifier]
                price = (
                    reference["price"] if reference["status"] == "available" else None
                )
                budget = preview._fill(
                    row, price, native._instant(packets.stamp(instant)), budget
                )
                _number(budget)
                _ledger(preview)
        except (OverflowError, ZeroDivisionError, TypeError, ValueError) as error:
            raise ValueError(
                "Conditional native arithmetic refused entire batch"
            ) from error
        preview._now, preview._batch_open = native._instant(at), False
        receipt = {
            "status": "PILOT_ONLY_CONDITIONAL_RESOLUTION",
            "contract": packets.CONTRACT,
            "symbol_scope": ["AAPL"],
            "conditional_window": deepcopy(window),
            "resolved_at": at,
            "source_sha256": packet.source_sha256,
            "original_submitted": deepcopy(list(submitted)),
            "initial_budget": frozen_budget,
            "nondue_reserved_cash": reserved,
            "remaining_budget": budget,
            "before_ledger": broker.ledger(),
            "after_ledger": preview.ledger(),
            "outcomes": deepcopy(preview._fills[first_fill:]),
            "references": [
                {
                    "client_order_id": identifier,
                    "assumed_outcome_at": packets.stamp(instant),
                    "reference": deepcopy(reference),
                }
                for instant, _, identifier, reference in selected
            ],
            "nav": None,
            "nav_reason": "Fresh observation of every held mark required",
            "actual_fills_proven": False,
            "sender_clock_transport_proven": False,
            "multi_symbol_or_auction_acceptance": False,
        }
        if broker.__dict__ != before:
            raise ValueError("Original broker changed during conditional resolution")
        broker.__dict__ = deepcopy(preview.__dict__)
        self._completed = {
            "signature": signature,
            "after": deepcopy(broker.__dict__),
            "receipt": deepcopy(receipt),
        }
        return receipt

    # Admit original native submissions and all-held marks before selecting outcomes.
    def _validate(self, window, submitted):
        broker = self._broker
        if (
            broker.cost_bps != 10
            or not broker._batch_open
            or not broker._market_open
            or broker._now is None
            or packets.nanos(broker._now.isoformat())
            != packets.nanos(window["assumed_submission_at"])
        ):
            raise ValueError(
                "Original fixed-clock10bp native submission batch required"
            )
        at = native._instant(window["quote_end"])
        local = at.astimezone(native.calendar.NEW_YORK)
        if not native._session(at)[1]:
            raise ValueError("Pilot deadline requires a reviewed regular session")
        broker.account()
        _ledger(broker)
        due, reserved = _orders(broker, local.date().isoformat())
        ids = [row.get("client_order_id") for row in submitted]
        if (
            any(not isinstance(value, str) or not value for value in ids)
            or len(set(ids)) != len(ids)
            or set(ids) != {row["client_order_id"] for _, row in due}
        ):
            raise ValueError("Entire original native market due CID set required")
        bindings = dict(zip(ids, submitted, strict=True))
        for _, row in due:
            if (
                row["symbol"] != "AAPL"
                or packets.nanos(row["submitted_at"])
                != packets.nanos(window["assumed_submission_at"])
                or _json(bindings[row["client_order_id"]]) != _json(row)
            ):
                raise ValueError("Original AAPL pilot submission binding differs")
        return due, reserved, deepcopy(broker.__dict__)
