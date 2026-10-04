"""Private deterministic broker semantics, never a network client or fill claim.

Submissions see current raw marks and reserve cash/shares. Supplied outcome
prices enter only flush, after the entire decision batch. FIFO whole-share
fills use pre-flush cash; proceeds of this batch's sales cannot fund its buys.
Partial attempts expire their remainder. Auctions require explicit phase and
prices, never a close substitution. This is a declared hypothetical venue.
"""

from __future__ import annotations

import math
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction

import numpy as np

from backend.market import calendar
from backend.market.alpaca_trading import Account, AlpacaTradingError


# Report private held value without fabricating unallocated acquisition cost or P&L.
@dataclass(frozen=True, slots=True)
class ReplayPosition:
    symbol: str
    qty: float
    market_value: float
    avg_entry_price: float | None
    current_price: float
    unrealized_pl: float | None


# Parse actual aware instants without silently assigning a timezone.
def _instant(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Explicit timezone-aware clock required")
    return value.astimezone(UTC)


# Parse finite numeric values without accepting booleans as financial evidence.
def _number(value, *, positive=False):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("Finite numeric evidence required")
    value = float(value)
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError("Finite positive or nonnegative numeric evidence required")
    return value


# Validate known allocations separately from explicit unallocated acquisition cost.
def _distribution_fraction(value, policy):
    if value is None:
        if policy != "unallocated_at_effective_clock":
            raise ValueError("Explicit unknown distribution basis policy required")
        return None
    if policy is not None:
        raise ValueError("Conflicting known and unknown distribution basis policy")
    fraction = _number(value, positive=True)
    if fraction >= 1:
        raise ValueError(
            "Explicit parent basis fraction strictly between zero and one required"
        )
    return fraction


# Validate explicitly supplied raw marks without replacing missing prices.
def _prices(values):
    if not isinstance(values, dict):
        raise ValueError("Explicit symbol/raw-price dictionary required")
    output = {}
    for symbol, value in values.items():
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("Nonempty symbol required")
        if value is None or (
            isinstance(value, (float, np.floating)) and np.isnan(value)
        ):
            output[symbol] = None
        else:
            output[symbol] = _number(value, positive=True)
    return output


# Check the complete reviewed historical calendar rather than live-only coverage.
def _session(now):
    local = now.astimezone(calendar.NEW_YORK)
    years, sessions = calendar.reviewed_sessions()
    if local.year not in years:
        raise ValueError("Reviewed observed calendar unavailable")
    is_session = bool(np.is_busday(np.datetime64(local.date()), busdaycal=sessions))
    is_open = is_session and (
        calendar.REGULAR_OPEN <= local.time() < calendar.session_close(local.date())
    )
    return is_session, is_open


# Simulate the broker surface used by nightly and intraday dispatch.
class ReplayBroker:
    # Initialize private cash and explicit whole-share holdings and acquisition bases.
    def __init__(
        self,
        initial_cash,
        cost_bps,
        *,
        initial_holdings=None,
        initial_average_prices=None,
    ):
        self._cash = _number(initial_cash)
        self.cost_bps = _number(cost_bps)
        if self.cost_bps >= 1e4:
            raise ValueError("Per-side cost below 10000 basis points required")
        self._held, self._average = {}, {}
        supplied = initial_average_prices or {}
        for symbol, value in (initial_holdings or {}).items():
            qty = _number(value)
            if not isinstance(symbol, str) or not symbol or qty != int(qty):
                raise ValueError("Explicit whole-share initial holdings required")
            if qty:
                self._held[symbol] = qty
                self._average[symbol] = _number(supplied[symbol], positive=True)
        self._orders, self._attempts, self._fills, self._actions = {}, [], [], {}
        self._dividends, self._marks, self._mark_times = [], {}, {}
        self._security_distributions = []
        self._security_exchanges = []
        self._share_consolidations = []
        self._now = self._observed_at = None
        self._market_open = self._batch_open = False
        self._last_equity = self._cash

    # Return detached attempt receipts so callers cannot alter historical evidence.
    @property
    def attempt_history(self):
        return tuple(deepcopy(self._attempts))

    # Return detached outcome receipts separately from submission evidence.
    @property
    def fill_history(self):
        return tuple(deepcopy(self._fills))

    # Expose raw ledger state for private verification without fabricating a NAV mark.
    def ledger(self):
        return deepcopy(
            {
                "cash": self._cash,
                "holdings": self._held,
                "average_prices": self._average,
                "dividends": self._dividends,
                **(
                    {"security_distributions": self._security_distributions}
                    if self._security_distributions
                    else {}
                ),
                **(
                    {"security_exchanges": self._security_exchanges}
                    if self._security_exchanges
                    else {}
                ),
                **(
                    {"share_consolidations": self._share_consolidations}
                    if self._share_consolidations
                    else {}
                ),
                "observed_at": self._observed_at.isoformat()
                if self._observed_at
                else None,
            }
        )

    # Advance only with explicit observed raw marks and a reviewed market clock.
    def observe(self, now, prices, market_open):
        now, prices = _instant(now), _prices(prices)
        if not isinstance(market_open, bool) or (
            self._now is not None and now < self._now
        ):
            raise ValueError(
                "Monotonic clock and explicit market-open boolean required"
            )
        _, is_open = _session(now)
        if market_open and not is_open:
            raise ValueError("Market-open flag disagrees with reviewed exchange clock")
        self._now = self._observed_at = now
        self._market_open, self._batch_open = market_open, True
        for symbol, price in prices.items():
            self._marks[symbol], self._mark_times[symbol] = price, now
        self._pay_dividends(now)
        local = now.astimezone(calendar.NEW_YORK)
        if local.time() >= calendar.session_close(local.date()):
            with suppress(AlpacaTradingError):
                self._last_equity = self.account().equity

    # Require an actual current observation before account valuation or submission.
    def _observed(self):
        if self._now is None or self._observed_at != self._now:
            raise AlpacaTradingError("Fresh observed account clock required")

    # Refuse missing current marks instead of carrying stale prices.
    def _mark(self, symbol):
        if (
            self._mark_times.get(symbol) != self._observed_at
            or self._marks.get(symbol) is None
        ):
            raise AlpacaTradingError(f"Fresh raw held mark unavailable for {symbol}")
        return self._marks[symbol]

    # Value actual cash, marked holdings and explicit unspendable dividend receivables.
    def account(self):
        self._observed()
        if any(
            row["fractional_qty"] > 0 and row["cash_in_lieu"] is None
            for row in self._security_distributions
        ):
            raise AlpacaTradingError(
                "Unknown distribution cash-in-lieu prevents full NAV"
            )
        if any(
            row["fractional_qty"] > 0 and row["cash_in_lieu"] is None
            for row in self._share_consolidations
        ):
            raise AlpacaTradingError(
                "Unknown consolidation cash-in-lieu prevents full NAV"
            )
        equity = self._cash + sum(
            qty * self._mark(symbol) for symbol, qty in self._held.items()
        )
        equity += sum(row["amount"] for row in self._dividends if not row["paid"])
        if not math.isfinite(equity):
            raise AlpacaTradingError("Finite marked equity unavailable")
        reserved = sum(
            row["reserved_cash"]
            for row in self._orders.values()
            if row["status"] == "accepted"
        )
        return Account(
            equity, self._cash, max(0.0, self._cash - reserved), self._last_equity
        )

    # Return actual held shares at current observed marks, never projected future fills.
    def positions(self):
        self._observed()
        return [
            ReplayPosition(
                symbol,
                qty,
                qty * self._mark(symbol),
                self._average[symbol],
                self._mark(symbol),
                qty * (self._mark(symbol) - self._average[symbol])
                if self._average[symbol] is not None
                else None,
            )
            for symbol, qty in sorted(self._held.items())
        ]

    # Expose only the current supplied market clock.
    def clock(self):
        self._observed()
        return {"is_open": self._market_open, "timestamp": self._now.isoformat()}

    # Return detached accepted orders without revealing any future outcome price.
    def open_orders(self):
        return deepcopy(
            [row for row in self._orders.values() if row["status"] == "accepted"]
        )

    # Return detached receipts from the requested aware submission clock.
    def orders_since(self, after, limit=500):
        after = _instant(after)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("Positive integer page limit required")
        return deepcopy(
            [
                row
                for row in self._orders.values()
                if _instant(row["submitted_at"]) >= after
            ]
        )

    # Cancel accepted IDs while preserving terminal receipts.
    def cancel_orders(self, ids):
        self._observed()
        if not isinstance(ids, (list, tuple)) or any(
            not isinstance(identifier, str) or not identifier for identifier in ids
        ):
            raise ValueError("Explicit nonempty order IDs required")
        result = {}
        for identifier in ids:
            row = self._orders.get(identifier)
            if row is None or row["status"] != "accepted":
                result[identifier] = "already_gone"
            else:
                row.update(
                    status="canceled",
                    canceled_at=self._now.isoformat(),
                    reserved_cash=0.0,
                )
                result[identifier] = "cancelled"
        return result

    # Choose the next scheduled session phase strictly after the submission timestamp.
    def _due(self, phase):
        local = self._now.astimezone(calendar.NEW_YORK)
        years, sessions = calendar.reviewed_sessions()
        if local.year not in years:
            raise AlpacaTradingError("Reviewed queue calendar unavailable")
        day = np.datetime64(local.date(), "D")
        opening = (
            calendar.REGULAR_OPEN
            if phase == "open"
            else calendar.session_close(local.date())
        )
        if np.is_busday(day, busdaycal=sessions) and local.time() < opening:
            selected = day
        else:
            selected = np.busday_offset(day, 1, roll="backward", busdaycal=sessions)
        if selected.astype(object).year not in years:
            raise AlpacaTradingError("Reviewed future queue session unavailable")
        return str(selected)

    # Submit a market request inside the observed regular session.
    def submit_market(self, symbol, qty, side, client_order_id=None):
        if not self._market_open:
            raise AlpacaTradingError("Ordinary market submission requires open session")
        return self._submit(symbol, qty, side, client_order_id, "day", "market")

    # Match the real API's day market order, queued only outside regular hours.
    def submit_market_on_open(self, symbol, qty, side, client_order_id=None):
        phase = "market" if self._market_open else "open"
        return self._submit(symbol, qty, side, client_order_id, "day", phase)

    # Queue an explicit closing auction without manufacturing an auction fill price.
    def submit_market_on_close(self, symbol, qty, side, client_order_id=None):
        return self._submit(symbol, qty, side, client_order_id, "cls", "close")

    # Accept or reject using only presently observed prices, cash and covered shares.
    def _submit(self, symbol, qty, side, identifier, tif, phase):
        self._observed()
        if not self._batch_open:
            raise AlpacaTradingError("Observe a new decision batch before submission")
        if (
            not isinstance(symbol, str)
            or not symbol
            or side not in ("buy", "sell")
            or not isinstance(identifier, str)
            or not identifier
            or isinstance(qty, (bool, np.bool_))
            or not isinstance(qty, (int, np.integer))
            or qty <= 0
        ):
            raise AlpacaTradingError(
                "Unique ID, symbol, side and positive whole quantity required"
            )
        existing = self._orders.get(identifier)
        if existing is not None:
            if any(
                existing[key] != value
                for key, value in (
                    ("symbol", symbol),
                    ("side", side),
                    ("qty", str(qty)),
                    ("time_in_force", tif),
                )
            ):
                raise AlpacaTradingError("Conflicting duplicate order identity")
            return deepcopy(existing)
        price = self._mark(symbol)
        cash = self.account().buying_power
        execute_on = (
            str(self._now.astimezone(calendar.NEW_YORK).date())
            if phase == "market"
            else self._due(phase)
        )
        reserved_shares = sum(
            int(row["qty"])
            for row in self._orders.values()
            if row["status"] == "accepted"
            and row["side"] == "sell"
            and row["symbol"] == symbol
        )
        needed = int(qty) * price * (1 + self.cost_bps / 1e4) if side == "buy" else 0.0
        if not math.isfinite(needed):
            raise AlpacaTradingError("Finite order notional required")
        reason = (
            "insufficient_reserved_cash"
            if needed > cash
            else "uncovered_sell"
            if side == "sell" and qty > self._held.get(symbol, 0) - reserved_shares
            else None
        )
        attempt = {
            "client_order_id": identifier,
            "symbol": symbol,
            "side": side,
            "qty": int(qty),
            "at": self._now.isoformat(),
            "observed_price": price,
            "available_cash": cash,
            "accepted": reason is None,
            "reason": reason,
        }
        self._attempts.append(deepcopy(attempt))
        if reason:
            raise AlpacaTradingError(reason)
        row = {
            "id": f"private-replay-{len(self._orders)}",
            "client_order_id": identifier,
            "symbol": symbol,
            "side": side,
            "qty": str(int(qty)),
            "type": "market",
            "time_in_force": tif,
            "status": "accepted",
            "filled_qty": "0",
            "filled_avg_price": None,
            "created_at": self._now.isoformat(),
            "submitted_at": self._now.isoformat(),
            "execution_phase": phase,
            "execute_on": execute_on,
            "reserved_cash": needed,
            "fee": 0.0,
        }
        self._orders[identifier] = row
        return deepcopy(row)

    # Apply one explicit post-batch outcome under pre-flush cash and whole-share bounds.
    def _fill(self, row, price, now, budget):
        requested = int(row["qty"])
        quantity = 0
        if price is not None:
            if row["side"] == "buy":
                quantity = min(
                    requested, math.floor(budget / (price * (1 + self.cost_bps / 1e4)))
                )
            else:
                quantity = min(requested, math.floor(self._held.get(row["symbol"], 0)))
        fee = quantity * (price or 0) * self.cost_bps / 1e4
        if quantity:
            symbol, held = row["symbol"], self._held.get(row["symbol"], 0)
            if row["side"] == "buy":
                spent = quantity * price + fee
                self._average[symbol] = (
                    None
                    if held and self._average[symbol] is None
                    else (held * self._average.get(symbol, 0) + quantity * price)
                    / (held + quantity)
                )
                self._held[symbol], self._cash, budget = (
                    held + quantity,
                    self._cash - spent,
                    budget - spent,
                )
            else:
                self._held[symbol], self._cash = (
                    held - quantity,
                    self._cash + quantity * price - fee,
                )
                if self._held[symbol] == 0:
                    self._held.pop(symbol)
                    self._average.pop(symbol)
        row.update(
            status="filled" if quantity == requested else "expired",
            filled_qty=str(quantity),
            filled_avg_price=str(price) if quantity else None,
            reserved_cash=0.0,
            fee=fee,
        )
        if quantity:
            row["filled_at"] = now.isoformat()
        if quantity != requested:
            row["expired_at"] = now.isoformat()
        self._fills.append(
            {
                "client_order_id": row["client_order_id"],
                "symbol": row["symbol"],
                "side": row["side"],
                "requested_qty": requested,
                "filled_qty": quantity,
                "price": price if quantity else None,
                "fee": fee,
                "at": now.isoformat(),
                "status": row["status"],
                "reason": "missing_execution_price"
                if price is None
                else "partial_cash_or_coverage"
                if quantity < requested
                else "filled",
            }
        )
        return budget

    # Consume explicit fill proxies only after all requests at an observation are fixed.
    def flush(self, now, fill_prices, *, phase="market"):
        now, prices = _instant(now), _prices(fill_prices)
        if (
            self._now is None
            or now < self._now
            or phase not in ("market", "open", "close")
        ):
            raise ValueError("Monotonic explicit execution clock and phase required")
        local = now.astimezone(calendar.NEW_YORK)
        is_session, _ = _session(now)
        if not is_session:
            raise ValueError("Execution requires a reviewed exchange session")
        if phase == "market" and not (
            calendar.REGULAR_OPEN
            <= local.time()
            <= calendar.session_close(local.date())
        ):
            raise ValueError("Ordinary outcome requires a regular-session clock")
        day = str(local.date())
        expected = (
            calendar.REGULAR_OPEN
            if phase == "open"
            else calendar.session_close(local.date())
        )
        if phase != "market" and local.time() != expected:
            raise ValueError(
                "Auction proxy requires its exact scheduled phase timestamp"
            )
        due = [
            row
            for row in self._orders.values()
            if row["status"] == "accepted"
            and row["execution_phase"] == phase
            and row["execute_on"] == day
        ]
        reserved = sum(
            row["reserved_cash"]
            for row in self._orders.values()
            if row["status"] == "accepted" and row not in due
        )
        budget = max(0.0, self._cash - reserved)
        before = len(self._fills)
        for row in due:
            budget = self._fill(row, prices.get(row["symbol"]), now, budget)
        self._now, self._batch_open = now, False
        return deepcopy(self._fills[before:])

    # Bind a dated corporate action and refuse conflicting duplicate evidence.
    def _action(self, symbol, kind, value, effective_at):
        effective = _instant(effective_at)
        if (
            self._now is None
            or effective > self._now
            or not isinstance(symbol, str)
            or not symbol
        ):
            raise ValueError("Observed dated corporate action required")
        value = _number(value, positive=True)
        key = (symbol, kind, effective.isoformat())
        if key in self._actions and self._actions[key] != value:
            raise ValueError("Conflicting corporate-action evidence")
        if key not in self._actions and any(
            row["symbol"] == symbol
            and row["filled_qty"] > 0
            and _instant(row["at"]) >= effective
            for row in self._fills
        ):
            raise ValueError("Corporate action must precede affected fills")
        return key, value, effective

    # Apply split entitlements and basis without rewriting pending quantities.
    def apply_split(self, symbol, ratio, effective_at):
        key, ratio, _ = self._action(symbol, "split", ratio, effective_at)
        if key in self._actions:
            return
        quantity = self._held.get(symbol, 0) * ratio
        if not math.isfinite(quantity):
            raise ValueError("Finite split entitlement required")
        if symbol in self._held:
            basis = self._average[symbol]
            basis = basis / ratio if basis is not None else None
            if basis is not None and (not math.isfinite(basis) or basis <= 0):
                raise ValueError("Finite split acquisition basis required")
            self._held[symbol] = quantity
            self._average[symbol] = basis
        self._actions[key] = ratio

    # Consolidate whole shares and keep fractional proceeds as an unknown cash claim.
    def apply_share_consolidation(
        self, symbol, numerator, denominator, effective_at, *, fractional_policy
    ):
        if (
            any(
                type(value) is not int or value <= 0
                for value in (numerator, denominator)
            )
            or numerator >= denominator
            or fractional_policy != "cash_in_lieu_unknown"
        ):
            raise ValueError(
                "Explicit reverse ratio and fractional cash policy required"
            )
        ratio = Fraction(numerator, denominator)
        key, value, effective = self._action(
            symbol, "share_consolidation", float(ratio), effective_at
        )
        if key in self._actions:
            prior = next(
                row for row in self._share_consolidations if row["action_key"] == key
            )
            if (prior["numerator"], prior["denominator"]) != (
                ratio.numerator,
                ratio.denominator,
            ):
                raise ValueError("Conflicting share consolidation evidence")
            return
        if any(
            row["symbol"] == symbol and row["status"] == "accepted"
            for row in self._orders.values()
        ):
            raise ValueError("Outstanding orders need explicit consolidation treatment")
        previous = self._held.get(symbol, 0)
        if previous != int(previous):
            raise ValueError("Whole pre-consolidation holdings required")
        entitlement = Fraction(int(previous)) * ratio
        quantity = int(entitlement)
        residual = float(entitlement - quantity)
        basis = self._average.get(symbol, 0)
        basis = basis / value if basis is not None else None
        fractional_basis = (
            residual * basis if basis is not None else None if residual else 0
        )
        if any(
            amount is not None and not math.isfinite(amount)
            for amount in (quantity, basis, fractional_basis)
        ):
            raise ValueError("Finite consolidated entitlements and basis required")
        record = {
            "action_key": key,
            "symbol": symbol,
            "numerator": ratio.numerator,
            "denominator": ratio.denominator,
            "quantity_before": previous,
            "whole_qty": quantity,
            "fractional_qty": residual,
            "fractional_basis": fractional_basis,
            "fractional_policy": fractional_policy,
            "cash_in_lieu": None,
            "effective_at": effective.isoformat(),
            "applied_at": self._now.isoformat(),
            "entitlement_scope": (
                "private_holder_aggregate_not_broker_street_name_allocation"
            ),
        }
        if quantity:
            self._held[symbol], self._average[symbol] = quantity, basis
        else:
            self._held.pop(symbol, None)
            self._average.pop(symbol, None)
        self._share_consolidations.append(record)
        self._actions[key] = value

    # Exchange a named security into a new issuer without inventing fractional cash.
    def apply_security_exchange(
        self,
        symbol,
        numerator,
        denominator,
        effective_at,
        *,
        old_security_id,
        new_security_id,
        fractional_policy,
    ):
        if (
            any(
                type(value) is not int or value <= 0
                for value in (numerator, denominator)
            )
            or any(
                not isinstance(value, str) or not value
                for value in (old_security_id, new_security_id)
            )
            or old_security_id == new_security_id
            or fractional_policy != "floor_no_compensation"
        ):
            raise ValueError(
                "Explicit security identities, ratio and fractional policy required"
            )
        ratio = Fraction(numerator, denominator)
        key, value, effective = self._action(
            symbol, "security_exchange", float(ratio), effective_at
        )
        if key in self._actions:
            prior = next(
                row for row in self._security_exchanges if row["action_key"] == key
            )
            if (
                prior["old_security_id"],
                prior["new_security_id"],
                prior["fractional_policy"],
            ) != (old_security_id, new_security_id, fractional_policy):
                raise ValueError("Conflicting security exchange evidence")
            return
        if any(
            row["symbol"] == symbol and row["status"] == "accepted"
            for row in self._orders.values()
        ):
            raise ValueError(
                "Outstanding orders need explicit security exchange treatment"
            )
        prior_exchanges = [
            row for row in self._security_exchanges if row["symbol"] == symbol
        ]
        if (
            prior_exchanges
            and prior_exchanges[-1]["new_security_id"] != old_security_id
        ):
            raise ValueError("Prior security identity differs from exchange evidence")
        previous = self._held.get(symbol, 0)
        if previous != int(previous):
            raise ValueError("Whole old-security holdings required")
        entitlement = Fraction(int(previous)) * ratio
        quantity, residual = int(entitlement), float(entitlement - int(entitlement))
        basis = self._average.get(symbol, 0)
        basis = basis / value if basis is not None else None
        forfeited_basis = (
            residual * basis if basis is not None else None if residual else 0
        )
        if any(
            amount is not None and not math.isfinite(amount)
            for amount in (quantity, basis, forfeited_basis)
        ):
            raise ValueError(
                "Finite exchanged entitlements and acquisition basis required"
            )
        record = {
            "action_key": key,
            "symbol": symbol,
            "old_security_id": old_security_id,
            "new_security_id": new_security_id,
            "numerator": ratio.numerator,
            "denominator": ratio.denominator,
            "quantity_before": previous,
            "quantity_after": quantity,
            "forfeited_fraction": residual,
            "forfeited_basis": forfeited_basis,
            "fractional_policy": fractional_policy,
            "cash_credit": 0,
            "effective_at": effective.isoformat(),
            "basis_policy": "ratio_basis_with_separate_forfeited_cost_not_tax_basis",
            "entitlement_scope": (
                "private_holder_aggregate_not_broker_street_name_allocation"
            ),
        }
        if quantity:
            self._held[symbol], self._average[symbol] = quantity, basis
        else:
            self._held.pop(symbol, None)
            self._average.pop(symbol, None)
        self._security_exchanges.append(record)
        self._actions[key] = value

    # Credit child shares without changing parent quantity or inventing fractional cash.
    def apply_stock_distribution(
        self,
        parent,
        child,
        numerator,
        denominator,
        effective_at,
        *,
        parent_basis_fraction,
        basis_policy=None,
    ):
        if (
            not isinstance(child, str)
            or not child
            or child == parent
            or any(
                isinstance(value, (bool, np.bool_))
                or not isinstance(value, (int, np.integer))
                or value <= 0
                for value in (numerator, denominator)
            )
        ):
            raise ValueError(
                "Distinct child symbol and positive integer share ratio required"
            )
        fraction = _distribution_fraction(parent_basis_fraction, basis_policy)
        ratio = Fraction(int(numerator), int(denominator))
        key, value, effective = self._action(
            parent, f"stock_distribution/{child}", float(ratio), effective_at
        )
        if key in self._actions:
            prior = next(
                row for row in self._security_distributions if row["action_key"] == key
            )
            if prior["parent_basis_fraction"] != fraction or (
                prior["numerator"],
                prior["denominator"],
            ) != (ratio.numerator, ratio.denominator):
                raise ValueError("Conflicting distribution basis evidence")
            return
        if any(
            row["symbol"] == child
            and row["filled_qty"] > 0
            and _instant(row["at"]) >= effective
            for row in self._fills
        ):
            raise ValueError("Corporate action must precede affected child fills")
        parent_qty = self._held.get(parent, 0)
        entitlement = Fraction(str(parent_qty)) * ratio
        whole = int(entitlement)
        residual = float(entitlement - whole)
        parent_basis = self._average.get(parent, 0)
        child_basis = (
            parent_basis * (1 - fraction) / value
            if parent_basis is not None and fraction is not None
            else None
        )
        allocated_parent_basis = (
            parent_basis * fraction
            if parent_basis is not None and fraction is not None
            else None
        )
        previous = self._held.get(child, 0)
        quantity = previous + whole
        prior_child_basis = self._average.get(child, 0)
        basis = (
            (
                None
                if child_basis is None or (previous and prior_child_basis is None)
                else (previous * prior_child_basis + whole * child_basis) / quantity
            )
            if quantity
            else 0
        )
        fractional_basis = (
            residual * child_basis
            if child_basis is not None
            else None
            if residual
            else 0
        )
        before_basis = {
            "parent_total": parent_qty * parent_basis
            if parent_basis is not None
            else None,
            "child_total": previous * prior_child_basis
            if prior_child_basis is not None
            else None,
        }
        amounts = (
            child_basis,
            quantity,
            basis,
            allocated_parent_basis,
            fractional_basis,
            *before_basis.values(),
        )
        if any(amount is not None and not math.isfinite(amount) for amount in amounts):
            raise ValueError(
                "Finite distribution entitlements and acquisition bases required"
            )
        if parent_qty:
            self._average[parent] = allocated_parent_basis
        if whole:
            self._held[child], self._average[child] = quantity, basis
        self._security_distributions.append(
            {
                "action_key": key,
                "parent": parent,
                "child": child,
                "parent_qty": parent_qty,
                "numerator": ratio.numerator,
                "denominator": ratio.denominator,
                "whole_qty": whole,
                "fractional_qty": residual,
                "fractional_basis": fractional_basis,
                "parent_basis_fraction": fraction,
                **(
                    {
                        "basis_policy": "unallocated_at_effective_clock",
                        "basis_before": before_basis,
                    }
                    if fraction is None
                    else {}
                ),
                "cash_in_lieu": None,
                "effective_at": effective.isoformat(),
                "applied_at": self._now.isoformat(),
            }
        )
        self._actions[key] = value

    # Post only observed cash-in-lieu evidence without inventing its amount or date.
    def settle_distribution_cash(self, parent, child, effective_at, amount, pay_at):
        self._settle_fractional_cash(
            self._security_distributions,
            parent,
            f"stock_distribution/{child}",
            effective_at,
            amount,
            pay_at,
            "distribution",
        )

    # Credit reverse-split fractions only from an explicitly observed payment receipt.
    def settle_consolidation_cash(self, symbol, effective_at, amount, pay_at):
        self._settle_fractional_cash(
            self._share_consolidations,
            symbol,
            "share_consolidation",
            effective_at,
            amount,
            pay_at,
            "consolidation",
        )

    # Validate a dated fractional payment fully before changing either cash or receipt.
    def _settle_fractional_cash(
        self, records, symbol, kind, effective_at, amount, pay_at, label
    ):
        self._observed()
        effective, payment = _instant(effective_at), _instant(pay_at)
        amount = _number(amount)
        if payment < effective or payment > self._now:
            raise ValueError(f"Observed {label} payment after entitlement required")
        key = (symbol, kind, effective.isoformat())
        matching = [row for row in records if row["action_key"] == key]
        if len(matching) != 1 or matching[0]["fractional_qty"] <= 0:
            raise ValueError(f"Existing fractional {label} entitlement required")
        row = matching[0]
        if row["cash_in_lieu"] is not None:
            if row["cash_in_lieu"] != amount or row["paid_at"] != payment.isoformat():
                raise ValueError(f"Conflicting {label} payment evidence")
            return
        if not math.isfinite(self._cash + amount):
            raise ValueError(f"Finite {label} payment required")
        self._cash += amount
        row.update(
            cash_in_lieu=amount,
            paid_at=payment.isoformat(),
            observed_payment_at=self._now.isoformat(),
        )

    # Accrue a dividend without spending an unknown payment-date entitlement.
    def accrue_dividend(self, symbol, per_share, effective_at, *, pay_at=None):
        key, amount, effective = self._action(
            symbol, "dividend", per_share, effective_at
        )
        payment = _instant(pay_at) if pay_at is not None else None
        if payment is not None and payment < effective:
            raise ValueError("Dividend payment cannot precede entitlement")
        if key in self._actions:
            prior = next(row for row in self._dividends if row["action_key"] == key)
            if prior["pay_at"] != (payment.isoformat() if payment else None):
                raise ValueError("Conflicting dividend payment evidence")
            return
        total = self._held.get(symbol, 0) * amount
        if not math.isfinite(total):
            raise ValueError("Finite dividend entitlement required")
        self._dividends.append(
            {
                "action_key": key,
                "symbol": symbol,
                "amount": total,
                "effective_at": effective.isoformat(),
                "pay_at": payment.isoformat() if payment else None,
                "paid": False,
            }
        )
        self._actions[key] = amount
        self._pay_dividends(self._now)

    # Move only explicitly dated payable receivables into actual cash.
    def _pay_dividends(self, now):
        for row in self._dividends:
            if (
                not row["paid"]
                and row["pay_at"] is not None
                and _instant(row["pay_at"]) <= now
            ):
                self._cash += row["amount"]
                row["paid"] = True
