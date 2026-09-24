"""Research-only stock/SPY/QQQ/cash execution of explicit close-time instructions.

This adapter does not predict returns or alter the incumbent desk policy. Stock
composition is retained independently of exposure, including while entirely in
cash. Instructions size absolute ending units at the close; the existing ledger
fills at the next adjusted open without recycling that batch's sale proceeds.
Zero targets exit completely, without the incumbent planner's minimum-trade rule.

Information dates are caller declarations, not attested historical availability.
Adjusted units, zero cash yield and single-balance batch funding are research
conventions, not broker shares, historical settlement or adoption evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date

import numpy as np

from backend.agents.trading.desk import simulate
from backend.market.allocation_controls import adjusted_open

EXECUTION_POLICY = "stock-index-cash-adapter/1-research"
INDEXES = ("SPY", "QQQ")


@dataclass(frozen=True)
class AllocationInstruction:
    """One declared close-time allocation and optional stock-composition update."""

    session: str
    information_through: str
    evidence_id: str
    stock_scale: float
    spy_weight: float
    qqq_weight: float
    stock_weights: Mapping[str, float] | None = None
    rebalance: bool = False


# Reject timestamp truncation and preserve the supplied daily information boundary.
def _day(value, label):
    stamp = str(value)
    try:
        parsed = date.fromisoformat(stamp)
    except ValueError as exc:
        raise ValueError(f"{label} must be a plain YYYY-MM-DD date") from exc
    if parsed.isoformat() != stamp:
        raise ValueError(f"{label} must be a plain YYYY-MM-DD date")
    return stamp


# Require finite numeric fractions without accepting booleans or numeric strings.
def _number(value, label):
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, float, np.integer, np.floating)
    ):
        raise ValueError(f"{label} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return value


# Own one stock basket while preserving explicit empty baskets and residual cash.
def _composition(weights, symbols):
    if weights is None:
        return None
    if not isinstance(weights, Mapping):
        raise ValueError("stock_weights must be a mapping or None")
    result = {}
    for symbol, value in weights.items():
        if symbol not in symbols or symbol in INDEXES:
            raise ValueError("stock_weights must name declared non-index stocks")
        weight = _number(value, f"stock weight for {symbol}")
        if weight < 0:
            raise ValueError("stock weights must be nonnegative")
        result[symbol] = weight
    if math.fsum(result.values()) > 1.0 + 1e-12:
        raise ValueError("stock weights must sum to at most one")
    return result


# Freeze a complete instruction calendar without inferring missing signals as cash.
def _instructions(raw, sessions, symbols, first):
    if not isinstance(raw, Sequence) or len(raw) != len(sessions) - first - 1:
        raise ValueError("one instruction is required for every executable close")
    result = []
    for offset, row in enumerate(raw):
        if not isinstance(row, AllocationInstruction):
            raise ValueError("instructions must contain AllocationInstruction values")
        session = _day(row.session, "instruction session")
        known = _day(row.information_through, "information_through")
        if session != sessions[first + offset] or known > session:
            raise ValueError("instruction calendar or information boundary is invalid")
        if not isinstance(row.evidence_id, str) or not row.evidence_id.strip():
            raise ValueError("evidence_id must identify the supplied instruction")
        if not isinstance(row.rebalance, bool):
            raise ValueError("rebalance must be an explicit boolean")
        sleeves = tuple(
            _number(value, label)
            for value, label in (
                (row.stock_scale, "stock_scale"),
                (row.spy_weight, "spy_weight"),
                (row.qqq_weight, "qqq_weight"),
            )
        )
        if min(sleeves) < 0 or max(sleeves) > 1 or math.fsum(sleeves[1:]) > 1 + 1e-12:
            raise ValueError("sleeve fractions must be in [0,1] and indexes sum <= 1")
        result.append(
            AllocationInstruction(
                session,
                known,
                row.evidence_id,
                *sleeves,
                stock_weights=_composition(row.stock_weights, symbols),
                rebalance=row.rebalance,
            )
        )
    return tuple(result)


# Validate and copy the source grid before a funded account can be opened.
def _inputs(panel, instructions, first, cost_bps, start_equity):
    dates = np.asarray(panel.dates)
    if dates.ndim != 1 or len(dates) < 2:
        raise ValueError("a source calendar with at least two sessions is required")
    sessions = [_day(value, "source session") for value in dates]
    if any(b <= a for a, b in zip(sessions, sessions[1:], strict=False)):
        raise ValueError("source sessions must be strictly ascending")
    if isinstance(panel.tickers, (str, bytes)) or not isinstance(
        panel.tickers, Sequence
    ):
        raise ValueError("symbols must be an ordered non-string sequence")
    symbols = tuple(panel.tickers)
    if (
        not symbols
        or any(
            not isinstance(s, str) or not s.strip() or s != s.strip() for s in symbols
        )
        or len(set(symbols)) != len(symbols)
        or any(index not in symbols for index in INDEXES)
    ):
        raise ValueError("unique declared symbols including SPY and QQQ are required")
    if isinstance(first, (bool, np.bool_)) or not isinstance(first, (int, np.integer)):
        raise ValueError("first must be an executable source session index")
    if not 0 <= first < len(dates) - 1:
        raise ValueError("first must be an executable source session index")
    cost = _number(cost_bps, "cost_bps")
    initial = _number(start_equity, "start_equity")
    if not 0 <= cost < 10000 or initial <= 0:
        raise ValueError("cost_bps must be in [0,10000) and start_equity positive")
    shape = (len(dates), len(symbols))
    raw_open, raw_close, closes = (
        _price_array(values, shape)
        for values in (panel.open, panel.close, panel.adj_close)
    )
    opens = adjusted_open(raw_open, raw_close, closes)
    rows = _instructions(instructions, sessions, symbols, int(first))
    return sessions, symbols, opens, closes, rows, cost, initial


# Refuse lossy coercions while retaining real numeric missing-price cells explicitly.
def _price_array(values, shape):
    array = np.asarray(values)
    if array.shape != shape:
        raise ValueError("source prices must match the full calendar and symbol grid")
    if array.dtype.kind not in "iuf":
        raise ValueError(
            "source prices must be real numeric arrays, not coerced values"
        )
    return np.array(array, dtype=float, copy=True)


# Bind the full declared path while retaining every row for later research archives.
def _path(sessions, symbols, first, instructions):
    payload = {
        "schema": "allocation-instructions/1",
        "sessions": sessions,
        "symbols": list(symbols),
        "first": int(first),
        "instructions": [asdict(row) for row in instructions],
    }
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    return {"payload": payload, "sha256": hashlib.sha256(encoded).hexdigest()}


# Refuse an unavailable price only when this account needs it for sizing or execution.
def _require_prices(prices, selected, label):
    if np.any(selected & (~np.isfinite(prices) | (prices <= 0))):
        raise ValueError(f"missing required price: {label}")


# Keep explicit portfolio intent independent of holdings reduced by a defensive switch.
def _target(instruction, base, symbols):
    desired = base * instruction.stock_scale
    desired[symbols.index("SPY")] = instruction.spy_weight
    desired[symbols.index("QQQ")] = instruction.qqq_weight
    if math.fsum(desired) > 1.0 + 1e-12:
        raise ValueError("actual stock and index allocations must total at most one")
    return desired


# Reject nonfinite execution state before it can masquerade as a valid closing NAV.
def _equity(book, prices):
    if (
        not math.isfinite(book.cash)
        or book.cash < 0
        or not math.isfinite(book.traded)
        or book.traded < 0
        or not np.isfinite(book.shares).all()
        or np.any(book.shares < 0)
    ):
        raise ValueError("invalid funded account state")
    nav = book.equity(prices)
    if not math.isfinite(nav) or nav <= 0:
        raise ValueError("invalid closing account NAV")
    return nav


# Name only explicit rebalance events, allocation changes and observed funding retries.
def _triggers(instruction, previous, retry, initial):
    reasons = []
    if initial:
        reasons.append("initial allocation")
    if instruction.rebalance:
        reasons.append("explicit rebalance")
    if instruction.stock_weights is not None:
        reasons.append("stock composition update")
    sleeves = (instruction.stock_scale, instruction.spy_weight, instruction.qqq_weight)
    if previous is not None and sleeves != previous:
        reasons.append("sleeve change")
    if retry:
        reasons.append("funding follow-up")
    return reasons, sleeves


# Replay declared allocations while preserving cash periods and terminal holdings.
def replay(  # noqa: C901 - retain the explicit decision/fill/mark order
    panel,
    instructions,
    *,
    first=0,
    cost_bps=10.0,
    start_equity=1.0,
    journal=None,
):
    """Return a continuous research account, never a new live-policy decision.

    Cash is a balance, not a fraction; `cash_fraction` names the latter. Fees
    and turnover are per account session (initial row zero), with turnover's
    denominator the preceding decision close NAV. Each instruction produces a
    receipt, including holds with no submitted units. The earliest execution
    session is permission timing, never proof of a fill. Composition updates,
    explicit rebalances, sleeve
    changes and funding follow-ups trigger close-sized plans; there is no
    implicit daily rebalancing. A follow-up replans against the next close's
    current instruction and NAV, never resubmits stale share quantities.
    """
    sessions, symbols, opens, closes, rows, cost, initial = _inputs(
        panel, instructions, first, cost_bps, start_equity
    )
    first = int(first)
    path = _path(sessions, symbols, first, rows)
    if journal is not None:
        journal.assert_inputs(panel.dates, symbols, opens, closes, cost)
    book = simulate._Book(
        len(symbols), initial, cost, panel, None, None, journal=journal
    )
    count = len(sessions) - first
    nav = np.zeros(count)
    cash = np.zeros(count)
    positions = np.zeros((count, len(symbols)))
    fees = np.zeros(count)
    turnover = np.zeros(count)
    nav[0] = cash[0] = initial
    if journal is not None:
        journal.open_account(first, book.cash, book.shares)
        book.observe_mark(first, initial)
    base = np.zeros(len(symbols))
    composition_known = False
    composition_session = None
    previous = None
    retry = False
    decisions = []
    for offset, instruction in enumerate(rows):
        t = first + offset
        if instruction.stock_weights is not None:
            base = np.array([instruction.stock_weights.get(s, 0.0) for s in symbols])
            composition_known = True
            composition_session = instruction.session
        if instruction.stock_scale > 0 and not composition_known:
            raise ValueError("stock exposure requires an explicit stock composition")
        desired = _target(instruction, base, symbols)
        triggers, previous = _triggers(instruction, previous, retry, offset == 0)
        before_nav = _equity(book, closes[t])
        order = book.shares.copy()
        if triggers:
            _require_prices(closes[t], desired > 0, f"decision {sessions[t]}")
            order = np.zeros(len(symbols))
            positive = desired > 0
            order[positive] = desired[positive] * before_nav / closes[t, positive]
            if not np.isfinite(order).all():
                raise ValueError("ending-unit target is not finite")
        reason = (
            "; ".join(triggers)
            if triggers
            else "held without a new allocation instruction"
        )
        receipt = {
            "session": instruction.session,
            "earliest_execution_session": sessions[t + 1],
            "information_through": instruction.information_through,
            "evidence_id": instruction.evidence_id,
            "stock_scale": instruction.stock_scale,
            "spy_weight": instruction.spy_weight,
            "qqq_weight": instruction.qqq_weight,
            "stock_weights": base.tolist(),
            "stock_composition_session": composition_session,
            "desired_weights": desired.tolist(),
            "submitted_units": order.tolist() if triggers else None,
            "reason": reason,
            "triggers": triggers,
            "planned": bool(triggers),
        }
        book.observe_decision(
            t,
            order,
            desired,
            reason,
            {
                "execution_policy": EXECUTION_POLICY,
                "instruction_path_sha256": path["sha256"],
                "instruction": asdict(instruction),
                "effective_stock_composition": base.tolist(),
                "stock_composition_session": composition_session,
                "triggers": triggers,
                "no_order": not bool(triggers),
            },
        )
        before_units = book.shares.copy()
        before_traded = book.traded
        retry = False
        if triggers:
            _require_prices(
                opens[t + 1], order != before_units, f"open {sessions[t + 1]}"
            )
            book._fill(order, opens[t + 1], recycle_sells=False, session=t + 1)
            retry = bool(
                np.any(book.shares < before_units)
                and np.any(order > book.shares)
                and book.cash > 0
            )
        nav[offset + 1] = _equity(book, closes[t + 1])
        cash[offset + 1] = book.cash
        positions[offset + 1] = book.shares
        traded = book.traded - before_traded
        fees[offset + 1] = traded * book.cost
        turnover[offset + 1] = traded / before_nav
        book.observe_mark(t + 1, nav[offset + 1])
        decisions.append(receipt)
    pending = {"retry": True} if retry else {}
    if journal is not None:
        journal.finish(len(sessions) - 1, book.cash, book.shares, book.traded, pending)
    return {
        "execution_policy": EXECUTION_POLICY,
        "dates": np.array(sessions[first:], dtype="datetime64[D]"),
        "nav": nav,
        "cash": cash,
        "cash_fraction": cash / nav,
        "positions": positions,
        "fees": fees,
        "turnover": turnover,
        "decisions": decisions,
        "terminal_pending": pending,
        "instruction_path": path,
        "adoption_eligible": False,
        "historical_availability_verified": False,
        "settlement_verified": False,
    }
