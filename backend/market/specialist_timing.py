"""Frozen Kronos candle-path timing research, with no live or broker integration.

Raw completed prefixes establish one bounded permission. Future candles are
kept separate and support only a conservative open-price execution proxy.
Neither a forecast nor an OHLC touch proves an executable bid/ask fill.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from datetime import date, datetime, time, timedelta

import numpy as np

from backend.market import calendar
from backend.market.bounded_execution import limit_text
from backend.market.open_source_forecasts import CHECKPOINTS, Forecaster

VERSION = "kronos-path-timing/1-research"
CONTEXT = 252
SEEDS = tuple(range(8))
BAR = timedelta(minutes=15)
NY = calendar.NEW_YORK
COLUMNS = ("open", "high", "low", "close", "volume")


# Bind a research artifact to exact finite JSON inputs without reading future prices.
def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


# Require an aware timestamp so local and UTC event clocks cannot be confused.
def aware(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("timezone_required")
    return result.astimezone(NY)


# Reject undeclared source identities rather than treat arbitrary text as a hash.
def source_hash(value):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("source_sha256_required")
    if any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError("source_sha256_required")
    return value


# Enumerate only reviewed exchange sessions, including their actual early closes.
def slots(session):
    day = date.fromisoformat(session)
    years, holidays = calendar.reviewed_sessions()
    if day.year not in years or not np.is_busday(str(day), busdaycal=holidays):
        raise ValueError("unreviewed_or_closed_session")
    at = datetime.combine(day, time(9, 30), NY)
    close = datetime.combine(day, calendar.session_close(day), NY)
    out = []
    while at < close:
        out.append(at)
        at += BAR
    return out


# Construct the fixed causal regular-bar grid ending at today's first completed bar.
def expected_prefix(session):
    day = date.fromisoformat(session)
    expected = [slots(session)[0]]
    years, holidays = calendar.reviewed_sessions()
    while len(expected) < CONTEXT:
        day -= timedelta(days=1)
        if day.year not in years:
            raise ValueError("prefix_calendar_unavailable")
        if np.is_busday(str(day), busdaycal=holidays):
            expected = slots(str(day)) + expected
    return expected[-CONTEXT:]


# Validate one observed raw candle without fixing malformed model or provider prices.
def values(row):
    result = []
    for key in COLUMNS:
        value = row[key]
        if isinstance(value, bool):
            raise ValueError("invalid_ohlcv")
        number = float(value)
        if not math.isfinite(number) or number < 0 or (key != "volume" and number == 0):
            raise ValueError("invalid_ohlcv")
        result.append(number)
    opening, high, low, close, _ = result
    if high < max(opening, low, close) or low > min(opening, high, close):
        raise ValueError("inconsistent_ohlc")
    return result


# Require the complete causal prefix without considering later session completeness.
def prefix_rows(payload, grid, observed):
    wanted = set(grid)
    selected = {}
    for row in payload["bars"]:
        start = aware(row["start"])
        if start not in wanted:
            continue
        if start in selected:
            raise ValueError("duplicate_prefix_bar")
        available = aware(row["available_at"])
        if available < start + BAR or available > observed:
            raise ValueError("prefix_bar_not_available")
        selected[start] = {
            "start": start.isoformat(),
            "available_at": available.isoformat(),
            **dict(zip(COLUMNS, values(row), strict=True)),
        }
    if set(selected) != wanted:
        raise ValueError("incomplete_causal_prefix")
    return [selected[start] for start in grid]


# Require dated split coverage and reject discontinuities without ratio fitting.
def split_evidence(payload, grid, observed):
    audit = payload.get("split_audit")
    if not isinstance(audit, dict) or audit.get("basis") != "dated-actions":
        raise ValueError("dated_split_audit_required")
    source_hash(audit.get("source_sha256"))
    if audit.get("availability_mode") not in ("recorded", "assumed_research"):
        raise ValueError("split_availability_mode_required")
    if aware(audit["available_at"]) > observed:
        raise ValueError("split_audit_not_available")
    if date.fromisoformat(audit["coverage_start"]) > grid[0].date():
        raise ValueError("split_audit_prefix_coverage_missing")
    if date.fromisoformat(audit["coverage_end"]) < observed.date():
        raise ValueError("split_audit_session_coverage_missing")
    relevant_events = []
    for event in audit["events"]:
        effective = date.fromisoformat(event["effective_session"])
        if grid[0].date() <= effective <= observed.date():
            ratio = float(event["ratio"])
            if not math.isfinite(ratio) or ratio <= 0:
                raise ValueError("invalid_split_event")
            if ratio != 1:
                raise ValueError("split_discontinuous_raw_prefix")
            relevant_events.append(event)
    return {**audit, "events": relevant_events}


# Select exactly 252 already available bars while ignoring all appended future candles.
def prepare(payload):
    if payload.get("price_basis") != "raw":
        raise ValueError("raw_price_basis_required")
    symbol, session = payload["symbol"], payload["session"]
    if session < CHECKPOINTS["kronos"].available_on:
        raise ValueError("checkpoint_not_available_at_decision")
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol_required")
    observed = aware(payload["observed_at"])
    today = slots(session)
    if not today[0] + BAR <= observed < today[0] + 2 * BAR:
        raise ValueError("first_completed_bar_permission_only")
    mode = payload.get("availability_mode")
    if mode not in ("recorded", "bar_close_assumed"):
        raise ValueError("availability_mode_required")
    grid = expected_prefix(session)
    rows = prefix_rows(payload, grid, observed)
    audit = split_evidence(payload, grid, observed)
    evidence = {
        "version": VERSION,
        "symbol": symbol,
        "session": session,
        "observed_at": observed.isoformat(),
        "price_basis": "raw",
        "source_sha256": source_hash(payload.get("source_sha256")),
        "availability_mode": mode,
        "split_audit": audit,
        "bars": rows,
        "seeds": list(SEEDS),
        "temperature": 1.0,
        "top_k": 0,
        "top_p": 0.9,
        "buy_quantile": 0.25,
        "sell_quantile": 0.75,
    }
    return {
        **evidence,
        "context_sha256": digest(evidence),
        "future_starts": [at.isoformat() for at in today[1:]],
        "expires_at": (today[-1] + BAR).isoformat(),
    }


# Reject altered prepared contexts or calendar horizons before using native inference.
def prepared_check(prepared):
    evidence = {
        key: value
        for key, value in prepared.items()
        if key not in ("context_sha256", "future_starts", "expires_at")
    }
    if digest(evidence) != prepared["context_sha256"]:
        raise ValueError("prepared_context_hash_mismatch")
    today = slots(prepared["session"])
    if (
        prepared["future_starts"] != [at.isoformat() for at in today[1:]]
        or prepared["expires_at"] != (today[-1] + BAR).isoformat()
    ):
        raise ValueError("prepared_calendar_horizon_mismatch")
    if prepare(prepared) != prepared:
        raise ValueError("prepared_context_not_canonical")


class KronosPaths:
    """Use the pinned public predictor eight times without its sample averaging."""

    # Load through the reviewed checkpoint/code guard and keep one in-process cache.
    def __init__(self):
        self.loader = Forecaster("kronos")
        self.cache = {}

    # Run each frozen seed once on CPU and preserve every path without redraws.
    def predict(self, prepared):
        prepared_check(prepared)
        key = prepared["context_sha256"]
        if key in self.cache:
            return self.cache[key].copy()
        if self.loader.model is None:
            self.loader.load()
        import pandas as pd
        import torch

        frame = pd.DataFrame(prepared["bars"], columns=COLUMNS)
        x = pd.Series(
            pd.to_datetime(
                [row["start"] for row in prepared["bars"]], utc=True
            ).tz_convert(NY)
        )
        y = pd.Series(
            pd.to_datetime(prepared["future_starts"], utc=True).tz_convert(NY)
        )
        paths = []
        deterministic = torch.are_deterministic_algorithms_enabled()
        try:
            torch.use_deterministic_algorithms(True)
            for seed in SEEDS:
                with torch.random.fork_rng(devices=[]):
                    torch.manual_seed(seed)
                    result = self.loader.model.predict(
                        frame,
                        x,
                        y,
                        pred_len=len(y),
                        T=1.0,
                        top_k=0,
                        top_p=0.9,
                        sample_count=1,
                        verbose=False,
                    )
                paths.append(result.loc[:, COLUMNS].to_numpy(dtype=float))
        finally:
            torch.use_deterministic_algorithms(deterministic)
        result = np.asarray(paths)
        self.cache[key] = result.copy()
        return result

    # Bind captured native paths to exact weights, source, seed and input identities.
    def provenance(self):
        return {
            "checkpoint": asdict(self.loader.spec),
            "runtime": self.loader.runtime,
            "device": "cpu",
            "target": "remaining_regular_ohlcv_path",
            "price_basis": "raw",
            "sample_count_per_call": 1,
            "seeds": list(SEEDS),
            "amount": "official predictor derives volume times mean OHLC",
        }


# Establish a price bound only for an existing original prior-night allocation intent.
def permission(prepared, intent, paths):
    prepared_check(prepared)
    if intent.get("side") not in ("buy", "sell"):
        raise ValueError("allocation_buy_or_sell_required")
    qty = intent.get("qty")
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        raise ValueError("positive_whole_share_intent_required")
    if (
        not isinstance(intent.get("client_order_id"), str)
        or not intent["client_order_id"]
    ):
        raise ValueError("original_intent_identity_required")
    if (
        intent.get("symbol") != prepared["symbol"]
        or intent.get("session") != prepared["session"]
    ):
        raise ValueError("intent_identity_mismatch")
    if aware(intent["created_at"]) >= slots(prepared["session"])[0]:
        raise ValueError("prior_night_intent_required")
    array = np.asarray(paths, dtype=float)
    if array.shape != (8, len(prepared["future_starts"]), 5):
        raise ValueError("eight_complete_paths_required")
    for path in array:
        for candle in path:
            values(dict(zip(COLUMNS, candle, strict=True)))
    minima = array[:, :, 2].min(axis=1)
    maxima = array[:, :, 1].max(axis=1)
    side = intent["side"]
    level = np.quantile(minima, 0.25) if side == "buy" else np.quantile(maxima, 0.75)
    bound = float(limit_text(float(level), side))
    last_close = prepared["bars"][-1]["close"]
    valid = bound <= last_close if side == "buy" else bound >= last_close
    result = {
        "version": VERSION,
        "status": "resting" if valid else "unavailable",
        "reason": None if valid else "forecast_bound_not_favorable",
        "symbol": prepared["symbol"],
        "session": prepared["session"],
        "observed_at": prepared["observed_at"],
        "expires_at": prepared["expires_at"],
        "context_sha256": prepared["context_sha256"],
        "intent_sha256": digest(intent),
        "client_order_id": intent["client_order_id"],
        "side": side,
        "qty": qty,
        "limit_price": bound,
        "price_basis": "raw",
        "path_sha256": digest(array.tolist()),
        "path_minima": minima.tolist(),
        "path_maxima": maxima.tolist(),
        "future_starts": prepared["future_starts"],
        "fill_proof": False,
        "exact_live_parity": False,
    }
    return {**result, "permission_sha256": digest(result)}


# Require explicit funding without borrowing or fractional holdings.
def funding_check(available_cash, held_qty, cost_bps):
    for number in (available_cash, held_qty, cost_bps):
        if isinstance(number, bool) or not math.isfinite(float(number)) or number < 0:
            raise ValueError("explicit_nonnegative_funding_required")
    if int(held_qty) != held_qty:
        raise ValueError("whole_share_holdings_required")


# Index separate future candles without silently collapsing duplicate evidence.
def execution_rows(future_bars, grid):
    indexed = {}
    wanted = set(grid)
    for row in future_bars:
        start = aware(row["start"])
        if start not in wanted:
            continue
        indexed.setdefault(start, []).append(row)
    return indexed


# Cap a single proxy execution to real cash or existing whole-share holdings.
def funded_proxy(result, order, start, opening, cash, held, cost_bps):
    side = order["side"]
    max_qty = (
        math.floor(cash / (opening * (1 + cost_bps / 10_000)))
        if side == "buy"
        else int(held)
    )
    qty = min(order["qty"], max_qty)
    if qty <= 0:
        return {**result, "status": "unfunded", "proxy_at": start.isoformat()}
    fees = qty * opening * cost_bps / 10_000
    return {
        **result,
        "status": "filled" if qty == order["qty"] else "partial",
        "filled_qty": qty,
        "proxy_at": start.isoformat(),
        "proxy_price": opening,
        "fees": fees,
        "cash_delta": (-1 if side == "buy" else 1) * qty * opening - fees,
        "shares_delta": (1 if side == "buy" else -1) * qty,
    }


# Count an intrabar touch only as ambiguity when the candle open is unfavorable.
def touched(side, low, high, bound):
    return low <= bound if side == "buy" else high >= bound


# Verify that original permission identity, price bound and quantity remain unchanged.
def permission_check(order):
    if order.get("permission_sha256") != digest(
        {key: value for key, value in order.items() if key != "permission_sha256"}
    ):
        raise ValueError("timing_permission_hash_mismatch")
    if order["version"] != VERSION or order["price_basis"] != "raw":
        raise ValueError("invalid_timing_permission")


# Find a later favorable open without making any funding, quantity or fill claim.
def price_opportunity(order, future_bars, *, data_as_of):
    permission_check(order)
    result = {
        "client_order_id": order["client_order_id"],
        "status": "unavailable",
        "touches_not_fills": 0,
        "fill_proof": False,
        "convention": "strictly-later-consecutive-bar-open",
    }
    if order["status"] != "resting":
        return {**result, "reason": order["reason"]}
    observed = aware(order["observed_at"])
    expires = aware(order["expires_at"])
    cutoff = aware(data_as_of)
    grid = [aware(start) for start in order["future_starts"]]
    indexed = execution_rows(future_bars, grid)
    for start in grid:
        if start + BAR > cutoff:
            return {**result, "status": "immature", "reason": "future_bar_not_closed"}
        matches = indexed.get(start)
        if matches is None:
            return {**result, "reason": "missing_consecutive_execution_bar"}
        if len(matches) != 1:
            raise ValueError("duplicate_execution_bar")
        row = matches[0]
        if (
            aware(row["available_at"]) < start + BAR
            or aware(row["available_at"]) > cutoff
        ):
            return {**result, "reason": "execution_bar_not_available"}
        opening, high, low, _, _ = values(row)
        if start <= observed or start >= expires:
            continue
        side, bound = order["side"], order["limit_price"]
        favorable = opening <= bound if side == "buy" else opening >= bound
        if not favorable:
            result["touches_not_fills"] += int(touched(side, low, high, bound))
            continue
        return {
            **result,
            "status": "opportunity",
            "proxy_at": start.isoformat(),
            "proxy_price": opening,
        }
    return {**result, "status": "expired" if cutoff >= expires else "immature"}


# Apply actual cash and existing whole-share limits to the shared price-only probe.
def proxy_fill(
    order, future_bars, *, data_as_of, available_cash, held_qty, cost_bps, completed_ids
):
    permission_check(order)
    funding_check(available_cash, held_qty, cost_bps)
    empty = {
        "client_order_id": order["client_order_id"],
        "filled_qty": 0,
        "requested_qty": order["qty"],
        "touches_not_fills": 0,
        "fill_proof": False,
        "convention": "strictly-later-consecutive-bar-open",
    }
    if order["client_order_id"] in completed_ids:
        return {**empty, "status": "repeat_suppressed"}
    price = price_opportunity(order, future_bars, data_as_of=data_as_of)
    result = {**empty, **price}
    if price["status"] != "opportunity":
        return result
    return funded_proxy(
        result,
        order,
        aware(price["proxy_at"]),
        price["proxy_price"],
        available_cash,
        held_qty,
        cost_bps,
    )
