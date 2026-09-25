"""Independent accounting replay of immutable, synthetic-unit research journals.

This module deliberately imports no producer, planner, or execution implementation.
Successful replay proves internal integrity and accounting under the declared batch
funding model, not point-in-time availability, security identity, settlement, or
economic readiness. Comparisons allow only 1e-10 relative / 1e-12 absolute rounding.
Ill-conditioned buy scales must match their recorded funding formula, and both
their scale-induced and executed-spend discrepancies must be at most 1e-12
times max(1, account NAV).
The independently carried account is never reset to observed cash or quantities.
Optional phase states expose opening and post-fill balances only after complete
verification; they retain daily dates and execution phases, not intraday times.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

REL_TOL = 1e-10
ABS_TOL = 1e-12
_BASE = {"seq", "event_id", "type", "session", "session_index"}
_EVENT_FIELDS = {
    "open_account": {"cash", "positions"},
    "decision": {
        "decision_id",
        "submitted_units",
        "desired_weights",
        "reason",
        "metadata",
    },
    "adjustment": {"decision_id", "phase", "submitted_units", "reason"},
    "fill_batch": {
        "decision_id",
        "phase",
        "submitted_units",
        "prices",
        "positions_before",
        "cash_before",
        "positions_after",
        "cash_after",
        "buy_budget",
        "scale",
        "recycle_sells",
        "filled_units",
        "notional",
        "fees",
        "gross_buys",
        "gross_sells",
        "fee_total",
        "residual_units",
        "unfilled_reasons",
        "price_ref",
    },
    "mark": {
        "cash",
        "positions",
        "nav",
        "traded",
        "price_ref",
        "unavailable_held_symbols",
    },
    "finish": {"cash", "positions", "traded", "pending", "status"},
}


class JournalError(ValueError):
    """A journal failed an independently checked invariant."""


# Stop at the first unsupported or inconsistent boundary with a readable reason.
def _require(condition: bool, message: str) -> None:
    if not condition:
        raise JournalError(message)


# Encode the public archive convention without importing its producer.
def _canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


# Require an ordinary finite JSON number, never a Boolean masquerading as one.
def _number(value: Any, label: str, *, nonnegative: bool = False) -> float:
    _require(type(value) in (int, float), f"{label}: finite number required")
    _require(math.isfinite(value), f"{label}: finite number required")
    if nonnegative:
        _require(value >= -ABS_TOL, f"{label}: negative balance or quantity")
    return float(value)


# Compare numeric claims within the explicitly declared floating-point allowance.
def _equal(actual: Any, expected: Any, label: str) -> None:
    if isinstance(expected, list):
        _require(isinstance(actual, list), f"{label}: vector required")
        _require(len(actual) == len(expected), f"{label}: vector length mismatch")
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            _equal(left, right, f"{label}[{index}]")
    elif expected is None:
        _require(actual is None, f"{label}: expected null")
    else:
        left = _number(actual, label)
        _require(
            math.isclose(left, expected, rel_tol=REL_TOL, abs_tol=ABS_TOL),
            f"{label}: claimed {actual!r}, replayed {expected!r}",
        )


# Check a symbol-aligned vector, allowing missing observations only when declared.
def _vector(
    value: Any,
    size: int,
    label: str,
    *,
    nullable: bool = False,
    nonnegative: bool = False,
) -> list[float | None]:
    _require(isinstance(value, list) and len(value) == size, f"{label}: wrong shape")
    return [
        None
        if item is None and nullable
        else _number(item, f"{label}[{index}]", nonnegative=nonnegative)
        for index, item in enumerate(value)
    ]


# Reject missing and unsupported fields rather than silently skipping new semantics.
def _fields(value: Any, expected: set[str], label: str) -> None:
    _require(isinstance(value, dict), f"{label}: object required")
    _require(set(value) == expected, f"{label}: unsupported or missing fields")


# Validate the grid, model declarations, and narrow readiness claims.
def _manifest(manifest: Any) -> tuple[int, int]:
    _fields(
        manifest,
        {
            "schema",
            "run_id",
            "account_id",
            "policy_id",
            "sessions",
            "symbols",
            "cost_bps",
            "price_basis",
            "cash_yield",
            "cash_model",
            "provenance",
            "historical_availability_verified",
            "security_identity_verified",
            "settlement_verified",
            "adoption_eligible",
            "status",
            "files",
        },
        "manifest",
    )
    _require(manifest["schema"] == "research-journal/1", "unsupported schema")
    for key in ("run_id", "account_id", "policy_id"):
        _require(
            isinstance(manifest[key], str) and bool(manifest[key].strip()),
            f"manifest {key}: nonempty identity required",
        )
    sessions, symbols = manifest["sessions"], manifest["symbols"]
    _require(isinstance(sessions, list) and bool(sessions), "empty session grid")
    for session in sessions:
        _require(isinstance(session, str), "invalid session")
        _require(date.fromisoformat(session).isoformat() == session, "invalid session")
    _require(sessions == sorted(set(sessions)), "session grid must be sorted unique")
    _require(isinstance(symbols, list) and bool(symbols), "empty symbol grid")
    _require(
        all(isinstance(s, str) and s and s == s.strip() for s in symbols),
        "invalid symbol identity",
    )
    _require(len(set(symbols)) == len(symbols), "duplicate symbol identity")
    cost = _number(manifest["cost_bps"], "cost_bps", nonnegative=True)
    _require(0 <= cost < 10000, "cost_bps outside supported range")
    _require(
        manifest["price_basis"] == "adjusted_synthetic_units",
        "unsupported price basis",
    )
    _equal(manifest["cash_yield"], 0.0, "unsupported cash yield")
    _require(
        manifest["cash_model"] == "single_balance_batch_funding_not_actual_settlement",
        "unsupported cash model",
    )
    for key in (
        "historical_availability_verified",
        "security_identity_verified",
        "settlement_verified",
        "adoption_eligible",
    ):
        _require(manifest[key] is False, f"unsupported readiness assertion: {key}")
    _require(manifest["status"] in ("recording", "complete", "failed"), "bad status")
    _require(isinstance(manifest["provenance"], dict), "provenance object required")
    _canonical(manifest)
    return len(sessions), len(symbols)


# Check immutable source matrix shape and the declared raw-to-adjusted convention.
def _prices(prices: Any, rows: int, columns: int) -> None:
    _fields(prices, {"schema", "open", "close", "raw"}, "prices")
    _require(prices["schema"] == "research-journal-prices/1", "bad price schema")
    matrices = {name: prices[name] for name in ("open", "close")}
    raw = prices["raw"]
    if raw is not None:
        _require(isinstance(raw, dict) and bool(raw), "raw object must be nonempty")
        _require(set(raw) <= {"open", "close", "adjusted_close"}, "unknown raw field")
        matrices.update({f"raw.{key}": value for key, value in raw.items()})
    for name, matrix in matrices.items():
        _require(isinstance(matrix, list) and len(matrix) == rows, f"{name}: row count")
        for index, row in enumerate(matrix):
            _vector(row, columns, f"{name}[{index}]", nullable=True)
    if raw is None:
        return
    if "adjusted_close" in raw:
        for index in range(rows):
            _equal(
                raw["adjusted_close"][index],
                prices["close"][index],
                "raw adjusted close",
            )
    if not {"open", "close"} <= set(raw):
        return
    _adjusted_opens(prices, raw, rows, columns)


# Independently reconstruct each adjusted opening observation from its raw source.
def _adjusted_opens(prices: dict, raw: dict, rows: int, columns: int) -> None:
    for row in range(rows):
        for col in range(columns):
            opening, closing = raw["open"][row][col], raw["close"][row][col]
            adjusted = prices["close"][row][col]
            value = None
            if (
                opening is not None
                and closing is not None
                and closing > 0
                and adjusted is not None
            ):
                computed = opening * (adjusted / closing)
                value = computed if math.isfinite(computed) else None
            _equal(prices["open"][row][col], value, f"adjusted open[{row}][{col}]")


# Authenticate only the two explicitly supported immutable data files.
def _hashes(manifest: dict, events: Any, prices: Any) -> None:
    _fields(manifest["files"], {"prices.json", "events.json"}, "manifest files")
    for name, value in (("prices.json", prices), ("events.json", events)):
        entry = manifest["files"][name]
        _fields(entry, {"sha256", "bytes"}, f"{name} metadata")
        encoded = _canonical(value)
        _require(
            type(entry["bytes"]) is int and entry["bytes"] == len(encoded),
            f"{name}: byte count mismatch",
        )
        _require(
            entry["sha256"] == hashlib.sha256(encoded).hexdigest(),
            f"{name}: SHA256 mismatch",
        )


# Return an explicitly narrow result even when validation stops before replay.
def _result() -> dict:
    return {
        "schema": "research-journal-verification/1",
        "ok": False,
        "accounting_verified": False,
        "integrity_verified": False,
        "complete": False,
        "errors": [],
        "marks": [],
        "total_fees": 0.0,
        "total_traded": 0.0,
        "terminal": None,
        "historical_availability_verified": False,
        "security_identity_verified": False,
        "settlement_verified": False,
        "adoption_eligible": False,
        "tolerance": {"relative": REL_TOL, "absolute": ABS_TOL},
        "max_reconciliation_residual": {"cash": 0.0, "units": 0.0, "nav": 0.0},
        "small_notional_scale_checks": {
            "count": 0,
            "max_requested_spend": 0.0,
            "max_bound": 0.0,
        },
        "currency_scale_checks": {
            "count": 0,
            "max_requested_spend": 0.0,
            "max_currency_difference": 0.0,
            "max_bound": 0.0,
        },
        "pending_semantics_verified": False,
    }


# Explain only the observed batch remainder, never an inferred future order queue.
def _residual_reason(wanted: Any, held: float, price: Any, scale: float) -> Any:
    if wanted is None:
        return "submitted_units_unavailable"
    if wanted == held:
        return None
    if price is None or price <= 0:
        return "price_unavailable"
    if wanted > held and scale < 1:
        return "cash_budget_limited"
    return "not_filled_in_batch"


class _Replay:
    """A separate ledger reconstructed solely from authenticated observations."""

    # Start without an account so an opening endowment must be explicit.
    def __init__(self, manifest: dict, prices: dict, result: dict) -> None:
        self.manifest, self.prices, self.result = manifest, prices, result
        self.columns = len(manifest["symbols"])
        self.cash = 0.0
        self.positions: list[float] = []
        self.traded = 0.0
        self.fees = 0.0
        self.opening: int | None = None
        self.last_session = -1
        self.last_mark = -1
        self.phase = -1
        self.decisions: dict[str, dict] = {}
        self.adjustments: dict[tuple, list] = {}
        self.filled: set[tuple] = set()
        self.execution_session: dict[str, int] = {}
        self.finished = False

    # Resolve each event's immutable price row instead of trusting copied prices.
    def source(self, event: dict, field: str) -> list:
        reference = event["price_ref"]
        _fields(reference, {"file", "field", "session_index"}, "price_ref")
        _require(reference["file"] == "prices.json", "price_ref file mismatch")
        _require(reference["field"] == field, "price_ref field mismatch")
        _require(
            type(reference["session_index"]) is int
            and reference["session_index"] == event["session_index"],
            "price_ref session mismatch",
        )
        return self.prices[field][event["session_index"]]

    # Record tolerated residuals without replacing independently reconstructed state.
    def compare(self, actual: Any, expected: Any, label: str, category: str) -> None:
        _equal(actual, expected, label)
        residual = (
            max(
                (abs(a - b) for a, b in zip(actual, expected, strict=True)), default=0.0
            )
            if isinstance(expected, list)
            else abs(actual - expected)
        )
        measured = self.result["max_reconciliation_residual"]
        measured[category] = max(measured[category], residual)

    # Check that a claimed account state matches the independently carried ledger.
    def state(self, cash: Any, positions: Any, label: str) -> None:
        _number(cash, f"{label} cash", nonnegative=True)
        _vector(positions, self.columns, f"{label} positions", nonnegative=True)
        self.compare(cash, self.cash, f"{label} cash", "cash")
        self.compare(positions, self.positions, f"{label} positions", "units")

    # Bound unstable scale ratios by monetary effect without resetting carried balances.
    def check_scale(
        self, event: dict, expected: float, requested: float, source: list, rate: float
    ) -> None:
        actual = _number(event["scale"], "scale")
        _require(0 <= actual <= 1, "scale outside [0, 1]")
        if math.isclose(actual, expected, rel_tol=REL_TOL, abs_tol=ABS_TOL):
            return
        observed = math.fsum(
            max(target - held, 0.0) * price * (1 + rate)
            for target, held, price in zip(
                event["submitted_units"], event["positions_before"], source, strict=True
            )
            if target is not None and target >= 0 and price is not None and price > 0
        )
        observed_scale = (
            min(1.0, max(0.0, event["buy_budget"]) / observed) if observed else 0.0
        )
        _equal(actual, observed_scale, "scale versus recorded funding formula")
        account = abs(self.cash) + math.fsum(
            abs(held * price)
            for held, price in zip(self.positions, source, strict=True)
            if price is not None and price > 0
        )
        bound = ABS_TOL * max(1.0, account)
        replayed_spend = requested * (1 + rate)
        spend = max(observed, replayed_spend)
        difference = max(
            abs(actual - expected) * spend,
            abs(actual * observed - expected * replayed_spend),
        )
        _require(difference <= bound, "common buy scale: materially sized mismatch")
        measured = self.result["currency_scale_checks"]
        measured["count"] += 1
        measured["max_requested_spend"] = max(measured["max_requested_spend"], spend)
        measured["max_currency_difference"] = max(
            measured["max_currency_difference"], difference
        )
        measured["max_bound"] = max(measured["max_bound"], bound)
        if spend <= bound:
            small = self.result["small_notional_scale_checks"]
            small["count"] += 1
            small["max_requested_spend"] = max(small["max_requested_spend"], spend)
            small["max_bound"] = max(small["max_bound"], bound)

    # Bind execution or an adjustment to an earlier close-time decision and phase.
    def binding(self, event: dict) -> tuple:
        identifier, session, phase = (
            event["decision_id"],
            event["session_index"],
            event["phase"],
        )
        _require(
            isinstance(identifier, str) and identifier in self.decisions,
            "unknown decision binding",
        )
        _require(phase in ("open", "close"), "unsupported execution phase")
        _require(
            session > self.decisions[identifier]["session_index"],
            "execution does not follow decision session",
        )
        _require(session > self.last_mark, "execution after closing mark")
        rank = 0 if phase == "open" else 1
        _require(rank >= self.phase, "open execution reordered after close")
        self.phase = rank
        previous = self.execution_session.setdefault(identifier, session)
        _require(previous == session, "decision reused across execution sessions")
        return identifier, session, phase

    # Reconstruct a cash-limited basket with one proportional scale for all buys.
    def fill(self, event: dict) -> None:
        key = self.binding(event)
        _require(key not in self.filled, "duplicate execution phase")
        target = _vector(
            event["submitted_units"],
            self.columns,
            "submitted_units",
            nullable=True,
            nonnegative=True,
        )
        expected_target = self.adjustments.get(
            key, self.decisions[key[0]]["submitted_units"]
        )
        _equal(target, expected_target, "decision/adjustment submitted_units")
        source = self.source(event, event["phase"])
        _vector(event["prices"], self.columns, "fill prices", nullable=True)
        _require(
            event["prices"] == source, "fill source prices differ from immutable row"
        )
        self.state(event["cash_before"], event["positions_before"], "before fill")
        _require(type(event["recycle_sells"]) is bool, "recycle_sells must be Boolean")
        sells, buys = [], []
        for holding, wanted, price in zip(self.positions, target, source, strict=True):
            eligible = (
                price is not None and price > 0 and wanted is not None and wanted >= 0
            )
            change = wanted - holding if eligible else 0.0
            sells.append(max(-change, 0.0))
            buys.append(max(change, 0.0))
        sale_values = [
            qty * price if qty else 0.0
            for qty, price in zip(sells, source, strict=True)
        ]
        buy_values = [
            qty * price if qty else 0.0 for qty, price in zip(buys, source, strict=True)
        ]
        rate = self.manifest["cost_bps"] / 10000
        sold = math.fsum(sale_values)
        requested = math.fsum(buy_values)
        budget = self.cash + (sold * (1 - rate) if event["recycle_sells"] else 0.0)
        scale = (
            min(1.0, max(0.0, budget) / (requested * (1 + rate))) if requested else 0.0
        )
        _equal(event["buy_budget"], budget, "buy_budget")
        self.check_scale(event, scale, requested, source, rate)
        changes = [buy * scale - sale for buy, sale in zip(buys, sells, strict=True)]
        positions = [
            old + change for old, change in zip(self.positions, changes, strict=True)
        ]
        notionals = [
            sale + buy * scale
            for sale, buy in zip(sale_values, buy_values, strict=True)
        ]
        fees = [value * rate for value in notionals]
        fee_total = math.fsum(fees)
        bought = requested * scale
        cash = self.cash + sold - bought - fee_total
        _require(cash >= -ABS_TOL, "replayed borrowing")
        residual = [
            None if wanted is None else wanted - actual
            for wanted, actual in zip(target, positions, strict=True)
        ]
        for name, expected in (
            ("filled_units", changes),
            ("notional", notionals),
            ("fees", fees),
            ("fee_total", fee_total),
            ("gross_buys", bought),
            ("gross_sells", sold),
            ("residual_units", residual),
        ):
            _equal(event[name], expected, name)
        self.compare(event["cash_after"], cash, "cash_after", "cash")
        self.compare(event["positions_after"], positions, "positions_after", "units")
        reasons = [
            _residual_reason(wanted, held, price, event["scale"])
            for wanted, held, price in zip(
                target, event["positions_after"], source, strict=True
            )
        ]
        _require(event["unfilled_reasons"] == reasons, "unfilled_reasons mismatch")
        # Keep the mathematical state; tolerate, but never fabricate, roundoff cash.
        self.cash, self.positions = cash, positions
        self.traded += math.fsum(notionals)
        self.fees += fee_total
        self.filled.add(key)

    # Preserve explicitly declared queues without inventing an order-expiry policy.
    def pending(self, pending: Any) -> None:
        _require(isinstance(pending, dict), "pending object required")
        _require(
            set(pending)
            <= {
                "decision_id",
                "submitted_units",
                "deferred_units",
                "event_state",
                "retry",
            },
            "unsupported pending fields",
        )
        identifier = pending.get("decision_id")
        if identifier is not None:
            _require(
                isinstance(identifier, str) and identifier in self.decisions,
                "pending references unknown decision",
            )
        if pending.get("submitted_units") is not None:
            _vector(
                pending["submitted_units"],
                self.columns,
                "pending submitted_units",
                nullable=True,
                nonnegative=True,
            )
        if "retry" in pending:
            _require(type(pending["retry"]) is bool, "pending retry must be Boolean")
        if "deferred_units" in pending:
            deferred = pending["deferred_units"]
            _require(isinstance(deferred, dict), "deferred_units object required")
            _require(
                set(deferred) <= set(self.manifest["symbols"]),
                "unknown deferred symbol",
            )
            for value in deferred.values():
                _number(value, "deferred_units", nonnegative=True)
        if pending.get("event_state") is not None:
            state = pending["event_state"]
            _fields(state, {"baseline_units", "sold_units"}, "pending event_state")
            for name, value in state.items():
                _vector(value, self.columns, name, nonnegative=True)

    # Retain last-close intentions explicitly because they cannot yet have executed.
    def terminal_decisions(self, pending: dict, session: int) -> None:
        for identifier, decision in self.decisions.items():
            if decision["session_index"] != session:
                continue
            _require(
                pending.get("decision_id") == identifier
                and pending.get("submitted_units") is not None,
                "last-session decision missing from terminal pending state",
            )
            _equal(
                pending["submitted_units"],
                decision["submitted_units"],
                "terminal pending decision units",
            )

    # Dispatch a strictly ordered event while requiring every claimed daily mark.
    def event(self, event: Any, seq: int) -> None:
        _require(isinstance(event, dict), "event object required")
        kind = event.get("type")
        _require(
            isinstance(kind, str) and kind in _EVENT_FIELDS, "unsupported event type"
        )
        _fields(event, _BASE | _EVENT_FIELDS[kind], f"event {seq}")
        _require(
            type(event["seq"]) is int and event["seq"] == seq, "event sequence mismatch"
        )
        _require(event["event_id"] == f"event-{seq:06d}", "event identity mismatch")
        session = event["session_index"]
        _require(
            type(session) is int and 0 <= session < len(self.manifest["sessions"]),
            "event session index invalid",
        )
        _require(
            event["session"] == self.manifest["sessions"][session],
            "event session mismatch",
        )
        _require(
            session >= self.last_session and not self.finished,
            "reordered or post-finish event",
        )
        if session > self.last_session:
            self.phase = -1
        self.last_session = session
        if seq == 0:
            _require(kind == "open_account", "first event must open account")
            self.cash = _number(event["cash"], "opening cash", nonnegative=True)
            self.positions = _vector(
                event["positions"], self.columns, "opening positions", nonnegative=True
            )
            self.opening = session
            self.last_mark = session - 1
            return
        _require(kind != "open_account", "duplicate opening endowment")
        if kind == "decision":
            _require(self.last_mark == session, "decision must follow its closing mark")
            _require(
                event["decision_id"] == f"decision-{seq:06d}",
                "decision identity mismatch",
            )
            _vector(
                event["submitted_units"],
                self.columns,
                "decision units",
                nullable=True,
                nonnegative=True,
            )
            if event["desired_weights"] is not None:
                _vector(
                    event["desired_weights"],
                    self.columns,
                    "desired_weights",
                    nullable=True,
                    nonnegative=True,
                )
            _require(
                isinstance(event["reason"], str)
                and isinstance(event["metadata"], dict),
                "invalid decision explanation",
            )
            self.decisions[event["decision_id"]] = event
        elif kind == "adjustment":
            key = self.binding(event)
            _require(key not in self.filled, "adjustment after execution")
            _require(isinstance(event["reason"], str), "invalid adjustment reason")
            self.adjustments[key] = _vector(
                event["submitted_units"],
                self.columns,
                "adjusted units",
                nullable=True,
                nonnegative=True,
            )
        elif kind == "fill_batch":
            self.fill(event)
        elif kind == "mark":
            _require(session == self.last_mark + 1, "missing or duplicate daily mark")
            self.state(event["cash"], event["positions"], "mark")
            source = self.source(event, "close")
            for holding, observed, price in zip(
                self.positions, event["positions"], source, strict=True
            ):
                _require(
                    max(holding, observed) <= 0 or (price is not None and price > 0),
                    "held closing mark unavailable",
                )
            _require(
                event["unavailable_held_symbols"] == [],
                "unavailable held-symbol marker contradicts source",
            )
            nav = self.cash + math.fsum(
                holding * price
                for holding, price in zip(self.positions, source, strict=True)
                if holding > 0
            )
            self.compare(event["nav"], nav, "mark NAV", "nav")
            _equal(event["traded"], self.traded, "mark cumulative traded")
            self.result["marks"].append(
                {
                    "session": event["session"],
                    "session_index": session,
                    "nav": nav,
                    "cash": self.cash,
                    "positions": list(self.positions),
                    "traded": self.traded,
                }
            )
            self.last_mark = session
        elif kind == "finish":
            self.state(event["cash"], event["positions"], "finish")
            _equal(event["traded"], self.traded, "finish cumulative traded")
            self.pending(event["pending"])
            self.terminal_decisions(event["pending"], session)
            _require(
                event["status"] == self.manifest["status"], "finish status mismatch"
            )
            _require(event["status"] == "complete", "journal failed or incomplete")
            _require(
                self.last_mark == session == len(self.manifest["sessions"]) - 1,
                "finish missing complete daily marks",
            )
            self.result["terminal"] = {
                key: event[key]
                for key in ("cash", "positions", "traded", "pending", "status")
            }
            self.finished = True


# Replay every event, optionally exposing phase states only after full verification.
def verify_payload(
    manifest: Any, events: Any, prices: Any, *, include_phase_states: bool = False
) -> dict:
    result = _result()
    try:
        _require(
            type(include_phase_states) is bool, "include_phase_states must be Boolean"
        )
        rows, columns = _manifest(manifest)
        _prices(prices, rows, columns)
        _hashes(manifest, events, prices)
        result["integrity_verified"] = True
        _require(isinstance(events, list) and bool(events), "event history is empty")
        replay = _Replay(manifest, prices, result)
        phase_states = [] if include_phase_states else None
        for seq, event in enumerate(events):
            replay.event(event, seq)
            if phase_states is not None and event["type"] in (
                "open_account",
                "fill_batch",
            ):
                phase_states.append(
                    {
                        "seq": event["seq"],
                        "event_id": event["event_id"],
                        "session": event["session"],
                        "session_index": event["session_index"],
                        "type": event["type"],
                        "phase": event.get("phase"),
                        "cash": replay.cash,
                        "positions": list(replay.positions),
                        "fees": replay.fees,
                        "traded": replay.traded,
                    }
                )
        _require(replay.finished, "journal incomplete: finish event missing")
        result.update(
            ok=True,
            accounting_verified=True,
            complete=True,
            total_fees=replay.fees,
            total_traded=replay.traded,
        )
        if phase_states is not None:
            result["phase_states"] = phase_states
    except (JournalError, ValueError, TypeError, KeyError, OverflowError) as exc:
        result["errors"].append(str(exc))
    return result


# Verify a public snapshot and forward optional phase output without producer coupling.
def verify_snapshot(snapshot: Any, *, include_phase_states: bool = False) -> dict:
    try:
        _fields(snapshot, {"manifest", "events", "prices"}, "snapshot")
        return verify_payload(
            snapshot["manifest"],
            snapshot["events"],
            snapshot["prices"],
            include_phase_states=include_phase_states,
        )
    except JournalError as exc:
        result = _result()
        result["errors"].append(str(exc))
        return result


# Reject duplicate JSON keys so an ambiguous archive cannot choose its own meaning.
def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


# Verify local files and optional phase states without escapes or changed bytes.
def verify_archive(path: str | Path, *, include_phase_states: bool = False) -> dict:
    result = _result()
    try:
        requested = Path(path)
        _require(".." not in requested.parts, "archive parent traversal rejected")
        requested = requested.absolute()
        _require(
            not any(part.is_symlink() for part in (requested, *requested.parents)),
            "archive symlink path rejected",
        )
        folder = requested if requested.is_dir() else requested.parent
        _require(
            requested.is_dir() or requested.name == "manifest.json",
            "archive path must be directory or manifest.json",
        )
        data = {}
        for name in ("manifest.json", "prices.json", "events.json"):
            source = folder / name
            _require(
                source.is_file() and not source.is_symlink(),
                f"{name}: local regular file required",
            )
            content = source.read_bytes()
            parsed = json.loads(content, object_pairs_hook=_unique_pairs)
            _require(
                content == _canonical(parsed), f"{name}: noncanonical or changed bytes"
            )
            data[name] = parsed
        return verify_payload(
            data["manifest.json"],
            data["events.json"],
            data["prices.json"],
            include_phase_states=include_phase_states,
        )
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        result["errors"].append(str(exc))
        return result
