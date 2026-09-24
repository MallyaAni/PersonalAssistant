"""Record observed research-account state without deciding or executing trades.

Adjusted prices imply synthetic adjusted units, not broker share quantities.
The single cash balance records each batch's funding convention, not actual
settlement. Source hashes protect retained bytes, not historical availability.
Independent validation lives in research_journal_replay, never in this recorder.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date
from hashlib import sha256
from pathlib import Path

import numpy as np

SCHEMA = "research-journal/1"
RAW_KEYS = frozenset({"open", "close", "adjusted_close"})
PENDING_KEYS = frozenset(
    {"decision_id", "submitted_units", "deferred_units", "event_state", "retry"}
)


# Serialize deterministic JSON bytes without permitting nonstandard NaN literals.
def _encode(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


# Copy JSON-compatible provenance while refusing unsupported or nonfinite values.
def _json_value(value):
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    raise ValueError("Metadata must contain only finite JSON values")


# Require meaningful identities and reasons without guessing their semantics.
def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


# Retain exact numbers, allowing unavailable valuation only when explicitly requested.
def _number(value, label, *, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result) and nullable:
        return None
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


# Preserve daily date precision and reject implicit truncation of source timestamps.
def _day(value):
    stamp = str(value)
    try:
        parsed = date.fromisoformat(stamp)
    except ValueError as exc:
        raise ValueError("Sessions must be plain YYYY-MM-DD dates") from exc
    if parsed.isoformat() != stamp:
        raise ValueError("Sessions must be plain YYYY-MM-DD dates")
    return stamp


# Freeze a sorted unique source calendar without claiming exchange completeness.
def _sessions(values):
    array = np.asarray(values)
    if array.ndim != 1 or not len(array):
        raise ValueError("A nonempty one-dimensional session calendar is required")
    days = tuple(_day(value) for value in array)
    if any(right <= left for left, right in zip(days, days[1:], strict=False)):
        raise ValueError("Sessions must be sorted and unique")
    return days


# Own a numeric array so changes to the producer's input cannot rewrite source history.
def _array(values, shape, label):
    try:
        result = np.array(values, dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a numeric array") from exc
    if result.shape != shape:
        raise ValueError(f"{label} must have shape {shape}")
    result.setflags(write=False)
    return result


# Represent unavailable source cells explicitly while keeping JSON standards-compliant.
def _nullable(values):
    return [None if not np.isfinite(value) else float(value) for value in values]


# Encode one complete source matrix without dropping unavailable rows or columns.
def _matrix(values):
    return [_nullable(row) for row in values]


# Refuse an existing target or any symlink/traversal component before archiving.
def _new_directory(destination):
    path = Path(destination)
    if ".." in path.parts:
        raise ValueError("Archive paths cannot contain parent traversal")
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Archive paths cannot traverse symlinks")
    if not path.parent.is_dir():
        raise ValueError("Archive parent must already exist")
    path.mkdir(exist_ok=False)
    return path


class ResearchJournal:
    """An append-only observer with privately owned prices and JSON event copies."""

    # Freeze account identity, source arrays and the limitations every archive carries.
    def __init__(
        self,
        sessions,
        symbols,
        opens,
        closes,
        *,
        run_id,
        account_id,
        policy_id,
        cost_bps,
        provenance,
        raw_prices=None,
    ):
        self._sessions = _sessions(sessions)
        self._symbols = tuple(_text(value, "symbol") for value in symbols)
        if not self._symbols or len(set(self._symbols)) != len(self._symbols):
            raise ValueError("Symbols must be nonempty and unique")
        if any(value != value.strip() for value in self._symbols):
            raise ValueError("Symbols cannot contain surrounding whitespace")
        self._shape = (len(self._sessions), len(self._symbols))
        self._opens = _array(opens, self._shape, "opens")
        self._closes = _array(closes, self._shape, "closes")
        self._cost_bps = _number(cost_bps, "cost_bps")
        if not 0 <= self._cost_bps < 10000:
            raise ValueError("cost_bps must be in [0, 10000)")
        if not isinstance(provenance, Mapping):
            raise ValueError("provenance must be a JSON object")
        self._prices = _encode(
            {
                "schema": "research-journal-prices/1",
                "open": _matrix(self._opens),
                "close": _matrix(self._closes),
                "raw": self._raw_prices(raw_prices),
            }
        )
        self._manifest = {
            "schema": SCHEMA,
            "run_id": _text(run_id, "run_id"),
            "account_id": _text(account_id, "account_id"),
            "policy_id": _text(policy_id, "policy_id"),
            "sessions": list(self._sessions),
            "symbols": list(self._symbols),
            "cost_bps": self._cost_bps,
            "price_basis": "adjusted_synthetic_units",
            "cash_yield": 0.0,
            "cash_model": "single_balance_batch_funding_not_actual_settlement",
            "historical_availability_verified": False,
            "security_identity_verified": False,
            "settlement_verified": False,
            "adoption_eligible": False,
            "provenance": _json_value(provenance),
        }
        self._events = []
        self._decision_ids = set()
        self._status = "recording"
        self._opened = False

    # Retain only explicitly supplied raw source arrays, never reconstruct missing ones.
    def _raw_prices(self, raw):
        if raw is None:
            return None
        if not isinstance(raw, Mapping) or not raw or set(raw) - RAW_KEYS:
            raise ValueError("raw_prices requires open, close or adjusted_close arrays")
        return {
            key: _matrix(_array(value, self._shape, f"raw {key}"))
            for key, value in raw.items()
        }

    # Expose the recorded cost without giving callers mutable source state.
    @property
    def cost_bps(self):
        return self._cost_bps

    # Expose immutable security order for producer wiring and diagnostics.
    @property
    def symbols(self):
        return self._symbols

    # Expose an independent calendar copy so callers cannot revise its source dates.
    @property
    def sessions(self):
        return np.asarray(self._sessions, dtype="datetime64[D]")

    # Reject a recorder bound to different prices, dates, security order or costs.
    def assert_inputs(self, sessions, symbols, opens, closes, cost_bps):
        if _sessions(sessions) != self._sessions or tuple(symbols) != self._symbols:
            raise ValueError("Journal calendar or symbols differ from producer inputs")
        if _number(cost_bps, "cost_bps") != self._cost_bps:
            raise ValueError("Journal cost differs from producer inputs")
        for expected, supplied, label in (
            (self._opens, opens, "open"),
            (self._closes, closes, "close"),
        ):
            actual = _array(supplied, self._shape, label)
            if not np.array_equal(expected, actual, equal_nan=True):
                raise ValueError(f"Journal {label} prices differ from producer inputs")

    # Resolve an event to one retained source row without guessing a nearby session.
    def _index(self, session):
        if isinstance(session, (int, np.integer)) and not isinstance(
            session, (bool, np.bool_)
        ):
            index = int(session)
            if 0 <= index < len(self._sessions):
                return index
            raise ValueError("Event session index is outside the source calendar")
        try:
            return self._sessions.index(_day(session))
        except ValueError as exc:
            raise ValueError("Event session is outside the source calendar") from exc

    # Preserve every aligned vector cell, allowing null only for unavailable intentions.
    def _vector(self, values, label, *, nullable=False):
        array = _array(values, (self._shape[1],), label)
        if not nullable and not np.isfinite(array).all():
            raise ValueError(f"{label} must contain finite observed state")
        return _nullable(array)

    # Require the open/close phase whose retained price row a fill can reference.
    def _phase(self, phase):
        if phase not in ("open", "close"):
            raise ValueError("Execution phase must be open or close")
        return phase

    # Point a fill or mark to its immutable source field and calendar position.
    def _price_ref(self, session, phase):
        return {
            "file": "prices.json",
            "field": self._phase(phase),
            "session_index": self._index(session),
        }

    # Append an owned event only while the account is open and not terminal.
    def _append(self, kind, session, **fields):
        if self._status != "recording":
            raise ValueError("A finished journal cannot accept more events")
        if kind != "open_account" and not self._opened:
            raise ValueError("Open the research account before recording events")
        index = self._index(session)
        if self._events and index < self._events[-1]["session_index"]:
            raise ValueError("Event sessions cannot move backwards")
        sequence = len(self._events)
        event = {
            "seq": sequence,
            "event_id": f"event-{sequence:06d}",
            "type": kind,
            "session": self._sessions[index],
            "session_index": index,
            **fields,
        }
        self._events.append(_json_value(event))

    # Preserve the observed opening cash and units without inferring earlier fills.
    def open_account(self, session, cash, positions):
        if self._opened or self._events:
            raise ValueError("A journal can open only one research account")
        self._append(
            "open_account",
            session,
            cash=_number(cash, "opening cash"),
            positions=self._vector(positions, "opening positions"),
        )
        self._opened = True

    # Record a close-time intention separately from whatever later fills actually do.
    def decision(
        self,
        session,
        submitted_units,
        desired_weights=None,
        reason="unspecified",
        metadata=None,
    ):
        decision_id = f"decision-{len(self._events):06d}"
        if metadata is not None and not isinstance(metadata, Mapping):
            raise ValueError("Decision metadata must be a JSON object")
        self._append(
            "decision",
            session,
            decision_id=decision_id,
            submitted_units=self._vector(
                submitted_units, "submitted units", nullable=True
            ),
            desired_weights=(
                None
                if desired_weights is None
                else self._vector(desired_weights, "desired weights", nullable=True)
            ),
            reason=_text(reason, "decision reason"),
            metadata=_json_value(metadata or {}),
        )
        self._decision_ids.add(decision_id)
        return decision_id

    # Require an existing intention without treating its requested units as fills.
    def _decision(self, decision_id):
        if decision_id not in self._decision_ids:
            raise ValueError("Unknown research decision_id")
        return decision_id

    # Keep every changed execution instruction and its stated reason in the journal.
    def adjustment(self, decision_id, session, phase, submitted_units, reason):
        self._append(
            "adjustment",
            session,
            decision_id=self._decision(decision_id),
            phase=self._phase(phase),
            submitted_units=self._vector(
                submitted_units, "adjusted submitted units", nullable=True
            ),
            reason=_text(reason, "adjustment reason"),
        )

    # Explain a batch residual without claiming that it became a queued future order.
    def _residual(self, submitted, after, prices, scale):
        residual, reasons = [], []
        for wanted, held, price in zip(submitted, after, prices, strict=True):
            remaining = None if wanted is None else wanted - held
            residual.append(remaining)
            if wanted is None:
                reason = "submitted_units_unavailable"
            elif remaining == 0:
                reason = None
            elif price is None or price <= 0:
                reason = "price_unavailable"
            elif remaining > 0 and scale < 1:
                reason = "cash_budget_limited"
            else:
                reason = "not_filled_in_batch"
            reasons.append(reason)
        return residual, reasons

    # Derive actual fills and costs solely from the producer's observed state change.
    def fill_batch(
        self,
        decision_id,
        session,
        phase,
        submitted_units,
        prices,
        positions_before,
        cash_before,
        positions_after,
        cash_after,
        buy_budget,
        scale,
        recycle_sells,
    ):
        before = self._vector(positions_before, "positions before")
        after = self._vector(positions_after, "positions after")
        supplied = self._vector(submitted_units, "submitted units", nullable=True)
        prices = self._vector(prices, "fill prices", nullable=True)
        scale = _number(scale, "fill scale")
        if not isinstance(recycle_sells, (bool, np.bool_)):
            raise ValueError("recycle_sells must be boolean")
        filled = [right - left for left, right in zip(before, after, strict=True)]
        notional = []
        for units, price in zip(filled, prices, strict=True):
            if units and (price is None or price <= 0):
                raise ValueError("An observed fill requires a finite positive price")
            notional.append(abs(units) * price if units else 0.0)
        fees = [amount * self._cost_bps / 10000 for amount in notional]
        residual, reasons = self._residual(supplied, after, prices, scale)
        self._append(
            "fill_batch",
            session,
            decision_id=self._decision(decision_id),
            phase=self._phase(phase),
            submitted_units=supplied,
            prices=prices,
            positions_before=before,
            cash_before=_number(cash_before, "cash before"),
            positions_after=after,
            cash_after=_number(cash_after, "cash after"),
            buy_budget=_number(buy_budget, "buy budget"),
            scale=scale,
            recycle_sells=bool(recycle_sells),
            filled_units=filled,
            notional=notional,
            fees=fees,
            gross_buys=sum(
                amount
                for units, amount in zip(filled, notional, strict=True)
                if units > 0
            ),
            gross_sells=sum(
                amount
                for units, amount in zip(filled, notional, strict=True)
                if units < 0
            ),
            fee_total=sum(fees),
            residual_units=residual,
            unfilled_reasons=reasons,
            price_ref=self._price_ref(session, phase),
        )

    # Preserve observed close marks and explicitly retain unavailable held valuations.
    def mark(self, session, cash, positions, nav, traded):
        held = self._vector(positions, "marked positions")
        closes = self._closes[self._index(session)]
        self._append(
            "mark",
            session,
            cash=_number(cash, "marked cash"),
            positions=held,
            nav=_number(nav, "marked NAV", nullable=True),
            traded=_number(traded, "cumulative traded notional"),
            price_ref=self._price_ref(session, "close"),
            unavailable_held_symbols=[
                symbol
                for symbol, units, price in zip(
                    self._symbols, held, closes, strict=True
                )
                if units > 0 and (not np.isfinite(price) or price <= 0)
            ],
        )

    # Validate retained queue and event state without inventing pending partial fills.
    def _pending(self, pending):
        if not isinstance(pending, Mapping) or set(pending) - PENDING_KEYS:
            raise ValueError("pending must use the declared research queue fields")
        result = {
            key: (
                self._vector(value, "pending submitted units", nullable=True)
                if key == "submitted_units" and value is not None
                else _json_value(value)
            )
            for key, value in pending.items()
        }
        if result.get("decision_id") is not None:
            self._decision(result["decision_id"])
        if "retry" in result and not isinstance(result["retry"], bool):
            raise ValueError("pending retry must be boolean")
        self._pending_deferred(result.get("deferred_units", {}))
        if result.get("event_state") is not None:
            state = result["event_state"]
            if not isinstance(state, dict) or set(state) != {
                "baseline_units",
                "sold_units",
            }:
                raise ValueError("Pending event state requires baseline and sold units")
            result["event_state"] = {
                key: self._vector(value, f"pending {key}")
                for key, value in state.items()
            }
        return result

    # Keep unpaid quantities tied to declared symbols and nonnegative finite units.
    def _pending_deferred(self, deferred):
        if not isinstance(deferred, dict) or set(deferred) - set(self._symbols):
            raise ValueError("Deferred units must reference declared symbols")
        for value in deferred.values():
            if _number(value, "deferred units") < 0:
                raise ValueError("Deferred units cannot be negative")

    # Retain terminal open holdings and pending work without simulating liquidation.
    def finish(self, session, cash, positions, traded, pending, status="complete"):
        if status not in ("complete", "failed"):
            raise ValueError("Terminal status must be complete or failed")
        self._append(
            "finish",
            session,
            cash=_number(cash, "terminal cash"),
            positions=self._vector(positions, "terminal positions"),
            traded=_number(traded, "terminal traded notional"),
            pending=self._pending(pending),
            status=status,
        )
        self._status = status

    # Return independent JSON values with hashes binding the exact source/event bytes.
    def snapshot(self):
        events = _encode(self._events)
        manifest = {
            **self._manifest,
            "status": self._status,
            "files": {
                name: {"sha256": sha256(body).hexdigest(), "bytes": len(body)}
                for name, body in (
                    ("prices.json", self._prices),
                    ("events.json", events),
                )
            },
        }
        return {
            "manifest": json.loads(_encode(manifest)),
            "prices": json.loads(self._prices),
            "events": json.loads(events),
        }

    # Publish a new archive last and read back every file without overwriting history.
    def archive(self, fresh_path):
        snapshot = self.snapshot()
        bodies = {
            f"{name}.json": _encode(snapshot[name])
            for name in ("prices", "events", "manifest")
        }
        destination = _new_directory(fresh_path)
        for name, body in bodies.items():
            with (destination / name).open("xb") as stream:
                stream.write(body)
        for name, body in bodies.items():
            path = destination / name
            if path.is_symlink() or path.read_bytes() != body:
                raise ValueError(f"Archived {name} differs from the observed journal")
        return destination / "manifest.json"
