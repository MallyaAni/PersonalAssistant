"""Fold original pre-observation account facts without executing any request."""

import math
from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime

from backend.cli import verify_actual_policy_timing as economic
from backend.market.live_model_history_receipts import (
    instant,
    require,
    same_number,
    whole,
)


# Validate a fresh raw mark without converting booleans into prices.
def price(value):
    return (
        value
        if type(value) in (int, float) and math.isfinite(value) and value > 0
        else None
    )


# Reproduce only native account completeness, never a model or a broker call.
def account_problem(held, marks, records):
    for name, message in (
        (
            "security_distributions",
            "Unknown distribution cash-in-lieu prevents full NAV",
        ),
        (
            "share_consolidations",
            "Unknown consolidation cash-in-lieu prevents full NAV",
        ),
        ("security_exchanges", "Unknown exchange cash-in-lieu prevents full NAV"),
    ):
        if any(
            row.get("fractional_qty", 0) > 0 and row["cash_in_lieu"] is None
            for row in records[name]
        ):
            return message
    return next(
        (
            f"Fresh raw held mark unavailable for {name}"
            for name in held
            if price(marks.get(name)) is None
        ),
        None,
    )


# Detach original read-only metadata without changing tuples or economic clock types.
def detached(value):
    if isinstance(value, Mapping):
        return {detached(key): detached(item) for key, item in value.items()}
    if type(value) is tuple:
        return tuple(detached(item) for item in value)
    if type(value) is list:
        return [detached(item) for item in value]
    require(
        type(value) in (str, int, bool, type(None), date, datetime)
        or (type(value) is float and math.isfinite(value)),
        "Explicit primitive original economic metadata required",
    )
    return value


# Carry independent balances and native request facts across observation clocks.
class ObservationContext:
    # Seed only previously conserved balances, requests and source economic events.
    def __init__(
        self,
        *,
        cash,
        held,
        basis,
        dividends,
        records,
        accepted,
        outcomes,
        cancellations,
        fills,
        opening,
        cost_bps=10,
        events=None,
        seen=None,
        entitlement_comparison=None,
    ):
        require(
            type(cash) in (int, float) and math.isfinite(cash) and cash >= 0,
            "Independent context cash required",
        )
        require(
            all(
                type(qty) in (int, float) and math.isfinite(qty) and qty > 0
                for qty in held.values()
            ),
            "Independent context holdings required",
        )
        require(
            set(records)
            == {
                "security_distributions",
                "share_consolidations",
                "security_exchanges",
                "cash_mergers",
            },
            "Independent context economic records required",
        )
        self.cash, self.held, self.basis = float(cash), deepcopy(held), deepcopy(basis)
        self.dividends, self.records = deepcopy(dividends), deepcopy(records)
        self.requests, self.outcomes = deepcopy(accepted), deepcopy(outcomes)
        self.cancellations, self.fills = deepcopy(cancellations), deepcopy(fills)
        self.events, self.seen = detached(events or {}), deepcopy(seen or set())
        self.opening, self.now, self.cost_bps = opening, None, cost_bps
        self.processed_fills = set()
        self.terminal = set(outcomes)
        self.marks = {}
        if self.events:
            require(
                entitlement_comparison is not None,
                "Original entitlement comparison required",
            )
            economic.fold_actions(
                self.events,
                opening,
                self.held,
                self.basis,
                self.dividends,
                self.records,
                self.seen,
                entitlement_comparison,
            )

    # Fold strictly earlier flushes before freezing this clock's native decision batch.
    def advance(self, now, marks):
        require(
            now > self.opening and (self.now is None or now > self.now),
            "Independent observation clock must advance",
        )
        for index, fill in enumerate(self.fills):
            if index in self.processed_fills or instant(fill["at"]) >= now:
                continue
            require(
                fill["client_order_id"] in self.requests,
                "Prior flush lacks conserved accepted request",
            )
            self.cash = economic.fold_fills([fill], self.cash, self.held, self.basis)
            self.terminal.add(fill["client_order_id"])
            self.processed_fills.add(index)
        for cid, at in self.cancellations.items():
            if instant(at) < now:
                self.terminal.add(cid)
        self.now, self.marks = now, deepcopy(marks)
        self.sender_error = next(
            (
                f"Fresh raw held mark unavailable for {name}"
                for name in sorted(self.held)
                if price(marks.get(name)) is None
            ),
            None,
        )
        self.timing_error = account_problem(self.held, marks, self.records)
        self.timing_held = {} if self.timing_error else deepcopy(self.held)
        self.nav = (
            None
            if self.timing_error
            else self.cash
            + sum(qty * marks[name] for name, qty in self.held.items())
            + sum(row["amount"] for row in self.dividends if not row["paid"])
            + sum(
                row["amount"] for row in self.records["cash_mergers"] if not row["paid"]
            )
        )
        if self.timing_error is None and (not math.isfinite(self.nav) or self.nav <= 0):
            self.timing_error, self.nav, self.timing_held = (
                "Finite positive equity and nonnegative cash required",
                None,
                {},
            )
        self.budget = None if self.timing_error else self.available()

    # Retain reservations from accepted, not-yet-terminal original requests.
    def available(self):
        reserved = sum(
            row["qty"] * row["observed_price"] * (1 + self.cost_bps / 10000)
            for cid, row in self.requests.items()
            if cid not in self.terminal and row["side"] == "buy"
        )
        return max(0.0, self.cash - reserved)

    # Derive the literal legacy reader's account fields separately from sender holdings.
    def trace_fields(self, row, quotes, due):
        missing_buy = any(
            price((quotes.get(r["symbol"]) or {}).get("last")) is None
            for r in due
            if r["side"] == "buy"
        )
        spend = (
            None
            if missing_buy
            else sum(
                r["qty"] * quotes[r["symbol"]]["last"]
                for r in due
                if r["side"] == "buy"
            )
            * (1 + self.cost_bps / 10000)
        )
        fraction = (
            min(1.0, self.budget / spend)
            if not self.timing_error and spend and self.budget is not None
            else 1.0
        )
        mark = price((quotes.get(row["symbol"]) or {}).get("last"))
        qty = (
            min(row["qty"], math.floor(self.timing_held.get(row["symbol"], 0)))
            if row["side"] == "sell"
            else row["qty"]
        )
        clock = int((self.now - self.opening).total_seconds() // 900) - 1
        reason = self.timing_error or (
            "unsupported learned clock"
            if clock > 22
            else "missing or stale completed raw quote"
            if mark is None
            else "unknown pending buy price"
            if row["side"] == "buy" and missing_buy
            else ""
        )
        weight = (
            0.0
            if reason
            else qty * mark / self.nav * (fraction if row["side"] == "buy" else 1.0)
        )
        return {
            "observed_qty": qty,
            "nav": self.nav,
            "buying_power_budget": self.budget,
            "all_pending_buy_spend": spend,
            "buy_funding_fraction": fraction,
            "trade_fraction": weight,
        }

    # Compare derived timing account fields without judging model probabilities.
    def compare_trace(self, row, trace, quotes, due):
        expected = self.trace_fields(row, quotes, due)
        require(
            type(trace.get("observed_qty")) is int
            and trace["observed_qty"] == expected["observed_qty"],
            "Independent legacy observed quantity differs",
        )
        for name, value in expected.items():
            if name == "observed_qty":
                continue
            require(name in trace, "Original legacy account field missing: " + name)
            if value is None:
                require(
                    trace[name] is None,
                    "Independent legacy account missing state differs",
                )
            else:
                same_number(
                    trace[name],
                    value,
                    "Independent legacy account " + name + " differs",
                )
        missing_buy = any(
            price((quotes.get(r["symbol"]) or {}).get("last")) is None
            for r in due
            if r["side"] == "buy"
        )
        reason = self.timing_error or (
            "unsupported learned clock"
            if trace["clock"] > 22
            else "missing or stale completed raw quote"
            if price((quotes.get(row["symbol"]) or {}).get("last")) is None
            else "unknown pending buy price"
            if row["side"] == "buy" and missing_buy
            else ""
        )
        if reason:
            require(
                trace["state"] == "unavailable" and trace.get("reason") == reason,
                "Independent legacy unavailable reason differs",
            )
        elif expected["trade_fraction"] == 0:
            require(
                trace["state"] == "no_trade"
                and trace.get("reason") == "no funded quantity",
                "Independent legacy zero-quantity verdict differs",
            )

    # Derive the original sender's quantity or exact pre-receipt failure branch.
    def result(self, row):
        require(self.now is not None, "Independent sender context required")
        cid, symbol, side = row["client_order_id"], row["symbol"], row["side"]
        require(
            cid not in self.requests, "Original sequential adoption invariant violated"
        )
        if self.sender_error:
            return {"kind": "batch_unavailable", "error": self.sender_error}
        qty = whole(row["qty"])
        if side == "sell":
            qty = min(qty, math.floor(self.held.get(symbol, 0)))
        if qty <= 0:
            return {"kind": "no_quantity", "error": "no shares to sell"}
        if any(
            r["symbol"] == symbol and instant(r["completed_before"]) <= self.now
            for r in self.records["cash_mergers"]
        ):
            return {
                "kind": "attempt",
                "qty": qty,
                "reason": "terminated_security",
                "observed_price": None,
                "available_cash": None,
            }
        mark = price(self.marks.get(symbol))
        error = (
            f"Fresh raw held mark unavailable for {symbol}"
            if mark is None
            else account_problem(self.held, self.marks, self.records)
        )
        if error:
            return {"kind": "pre_attempt_error", "error": error}
        cash = self.available()
        reserved_shares = sum(
            r["qty"]
            for key, r in self.requests.items()
            if key not in self.terminal
            and r["side"] == "sell"
            and r["symbol"] == symbol
        )
        needed = qty * mark * (1 + self.cost_bps / 10000) if side == "buy" else 0.0
        reason = (
            "insufficient_reserved_cash"
            if needed > cash
            else "uncovered_sell"
            if side == "sell" and qty > self.held.get(symbol, 0) - reserved_shares
            else None
        )
        return {
            "kind": "attempt",
            "qty": qty,
            "reason": reason,
            "observed_price": mark,
            "available_cash": cash,
        }

    # Admit only independently derived request quantities, prices, cash and refusals.
    def admit(self, row, attempt):
        expected = self.result(row)
        require(expected["kind"] == "attempt", "Unexpected original sender attempt")
        require(
            attempt["client_order_id"] == row["client_order_id"]
            and attempt["symbol"] == row["symbol"]
            and attempt["side"] == row["side"]
            and instant(attempt["at"]) == self.now,
            "Independent sender attempt identity or clock differs",
        )
        require(
            type(attempt["qty"]) is int and attempt["qty"] == expected["qty"],
            "Independent sender submitted quantity differs",
        )
        require(
            attempt["accepted"] is (expected["reason"] is None)
            and attempt["reason"] == expected["reason"],
            "Independent sender refusal differs",
        )
        for name in ("observed_price", "available_cash"):
            if expected[name] is None:
                require(
                    attempt[name] is None, "Terminated request missing state differs"
                )
            else:
                same_number(
                    attempt[name],
                    expected[name],
                    "Independent sender " + name + " differs",
                )
        if attempt["accepted"]:
            self.requests[row["client_order_id"]] = deepcopy(attempt)
