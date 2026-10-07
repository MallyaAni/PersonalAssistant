"""Decision-only bridge for a frozen continuation model, never order submission.

Supplied completed source prefixes and actual intended orders remain explicit.
IEX versus SIP and September carry-forward are domain/age differences, not
claims of a newly refitted October model or a proven production replacement.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import numpy as np

from backend.market import (
    calendar,
    entry_timing,
    learned_entry_data,
    sequential_execution_models,
    sequential_execution_replay,
)
from backend.market.sip_cube import SessionCube

MANIFEST_SHA = "21afa50d2d36c1f03c20fa50dd4c18b05538865559ee80f7bf7ea553373a4c00"
MODEL_MONTH = "2026-09"
POLICY = "frozen-2026-09-continuation-shadow/1"
PARAMETERS = ("imputer", "indicators", "center", "scale", "coef", "intercept")


# Carry causal input identity separately from any unobserved execution outcome.
@dataclass(frozen=True)
class Observation:
    session: str
    clock: int
    received_at: str
    feed: str
    symbol: str
    features: np.ndarray
    valid: bool
    raw_price: float | None
    supported: bool
    legacy_triggered: dict


# Retain authenticated fitted heads and their actual historical training cutoff.
@dataclass(frozen=True)
class FrozenModel:
    heads: dict
    max_label_end: str
    manifest_sha256: str
    archive_sha256: str


# Reject unaware or impossible publication clocks before accepting an observation.
def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Timezone-aware receipt/publication timestamps required")
    return value.astimezone(calendar.NEW_YORK)


# Reuse the frozen preparation on a cropped past and a masked completed prefix only.
def observe(panel, grades, eligible, cube, clock, received_at, *, published_at, feed):
    if (
        isinstance(clock, (bool, np.bool_))
        or not isinstance(clock, (int, np.integer))
        or not 0 <= clock <= 24
        or feed not in ("sip", "iex")
    ):
        raise ValueError("Completed-bar clock and explicit SIP/IEX feed required")
    received = _aware(received_at)
    if set(published_at) != {"history", "grades", "membership"} or any(
        _aware(t) > received for t in published_at.values()
    ):
        raise ValueError("Daily prices, grades and membership require publication")
    session = np.datetime64(received.date(), "D")
    supported = bool(sequential_execution_replay.supported_sessions([session])[0])
    finish = datetime.combine(received.date(), time(9, 45), calendar.NEW_YORK)
    finish += timedelta(minutes=15 * int(clock))
    if supported and not finish <= received < finish + timedelta(minutes=15):
        raise ValueError("Receipt cannot backdate a decision or use a forming bar")
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    hits = np.flatnonzero(dates == session)
    cube_hits = np.flatnonzero(np.asarray(cube.dates) == session)
    if len(hits) != 1 or len(cube_hits) != 1 or cube.ticker not in panel.tickers:
        raise ValueError("One explicit panel/cube session and matching symbol required")
    stop, row = int(hits[0]) + 1, int(cube_hits[0])
    prices = np.asarray(panel.adj_close[:stop], dtype=float).copy()
    prices[-1] = np.nan
    past = SimpleNamespace(dates=dates[:stop], tickers=panel.tickers, adj_close=prices)
    bars = {}
    for name in ("open", "high", "low", "close", "volume"):
        source = np.asarray(getattr(cube, name), dtype=float)
        if source.ndim != 2 or source.shape[1] != 26:
            raise ValueError("Explicit 26-slot raw-basis source required")
        value = np.full((1, 26), np.nan)
        value[0, : clock + 1] = source[row, : clock + 1]
        bars[name] = value
    prefix = SessionCube(
        cube.ticker,
        np.array([session]),
        **bars,
        prior_close=np.asarray([cube.prior_close[row]], dtype=float),
        excluded={},
        auction_open=np.array([np.nan]),
        auction_volume=np.array([np.nan]),
    )
    packet = learned_entry_data.prepare(
        past,
        np.asarray(grades)[:stop],
        np.asarray(eligible)[:stop],
        {cube.ticker: prefix},
    )
    stock = panel.tickers.index(cube.ticker)
    raw = float(bars["close"][0, clock])
    return Observation(
        str(session),
        int(clock),
        received.isoformat(),
        feed,
        cube.ticker,
        packet["X"][-1, clock, stock].copy(),
        bool(packet["valid"][-1, clock, stock]),
        raw if np.isfinite(raw) and raw > 0 else None,
        supported,
        {
            side: any(
                entry_timing.crosses(value, bars["open"][0, 0], side)
                for value in bars["close"][0, : clock + 1]
            )
            for side in ("buy", "sell")
        },
    )


# Read only the already verified September coefficients with exact archive identities.
def load_model(directory):
    model = sequential_execution_models
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    if model._file_hash(manifest_path) != MANIFEST_SHA:
        raise ValueError("Exact completed research manifest required")
    manifest = json.loads(manifest_path.read_text())
    if tuple(manifest["identity"]["feature_names"]) != learned_entry_data.FEATURE_NAMES:
        raise ValueError("Frozen causal feature contract differs")
    rows = [row for row in manifest["months"] if row["month"] == MODEL_MONTH]
    if len(rows) != 1 or rows[0]["status"] != "fitted":
        raise ValueError("One fitted September model required")
    month = rows[0]
    folder = directory / MODEL_MONTH
    if (
        json.loads((folder / "receipt.json").read_text()) != month
        or json.loads((folder / "fit.json").read_text()) != month["fit"]
        or not month["max_label_end"] < month["label_end_before"] <= month["fit_date"]
    ):
        raise ValueError("Frozen training receipt or maturity changed")
    arrays = model._read_npz(folder / "models.npz", month["fit"]["bundle"])
    model._verify_heads(arrays, "final", month["fit"]["heads"])
    heads = {
        key: {name: arrays[f"final_{key}_{name}"] for name in PARAMETERS}
        for key, receipt in month["fit"]["heads"].items()
        if receipt["status"] == "fitted"
    }
    for head in heads.values():
        for value in head.values():
            value.setflags(write=False)
    heads = MappingProxyType(
        {key: MappingProxyType(head) for key, head in heads.items()}
    )
    return FrozenModel(
        heads, month["max_label_end"], MANIFEST_SHA, month["fit"]["bundle"]["sha256"]
    )


# Score an observed prefix without looking at prices or labels after its receipt.
def decide(observation, model, side):
    if side not in ("buy", "sell"):
        raise ValueError("Buy/sell side required")
    if observation.session < f"{MODEL_MONTH}-01":
        raise ValueError("Frozen model cannot score before its actual fitting date")
    result = {
        "policy": POLICY,
        "state": "unavailable",
        "predicted_difference": None,
        "model_month": MODEL_MONTH,
        "max_training_label_end": model.max_label_end,
        "model_manifest_sha256": model.manifest_sha256,
        "model_archive_sha256": model.archive_sha256,
        "observation_received_at": observation.received_at,
        "feed_domain_matches_training": observation.feed == "sip",
        "frozen_model_carry_forward": observation.session[:7] != MODEL_MONTH,
        "order_submission": False,
    }
    if not observation.supported or observation.raw_price is None:
        return result
    if observation.clock == 24:
        result["state"] = "terminal_attempt"
        return result
    head = model.heads.get(f"{observation.clock}_{int(side == 'sell')}")
    if not observation.valid or head is None:
        return result
    predicted = sequential_execution_models._predict(head, observation.features[None])[
        0
    ]
    predicted = float(np.float32(predicted))
    result.update(
        state=sequential_execution_models.decision(predicted, side),
        predicted_difference=predicted if np.isfinite(predicted) else None,
    )
    return result


# Explain every excluded original order without interpreting its reason text.
def _exclusion(row, state, opened, session):
    from backend.agents.trading.desk import intraday_orders, live_policy

    if state.get("policy_version") != live_policy.ACTIVE:
        return "unsupported_policy"
    if opened:
        return "working_broker_orders"
    if row.get("sent") or row.get("sending"):
        return "sent_or_sending"
    if row.get("event_id") or row.get("priority") or "execution_policy" in row:
        return "nonordinary_policy"
    if row.get("execution_timing") != intraday_orders.INTRADAY_TIMING:
        return "nonordinary_timing"
    if row.get("execute_on") != str(session):
        return "different_execution_session"
    if (
        row.get("side") not in ("buy", "sell")
        or not isinstance(row.get("symbol"), str)
        or not row.get("symbol")
        or isinstance(row.get("qty"), bool)
        or not isinstance(row.get("qty"), int)
        or row["qty"] <= 0
    ):
        return "invalid_order"
    return None


# Read actual intents and stable broker funding without acquiring writer locks.
def freeze_intents(root, client, session, *, clock):
    from backend.agents.trading.desk import paper

    started = _aware(clock())
    if str(started.date()) != str(session):
        raise ValueError("Actual snapshot receipt must belong to the requested session")
    path = paper.state_path(Path(root))
    before = path.read_bytes()
    state = json.loads(before)
    account = client.account()
    positions = client.positions()
    opened = client.open_orders()
    after_account = client.account()
    after_positions = client.positions()
    after_opened = client.open_orders()
    received = _aware(clock())
    held = {row.symbol: float(row.qty) for row in positions}
    after_held = {row.symbol: float(row.qty) for row in after_positions}
    if (
        path.read_bytes() != before
        or account.cash != after_account.cash
        or held != after_held
        or opened != after_opened
        or received < started
        or str(received.date()) != str(session)
    ):
        raise ValueError("Concurrent plan/account changes prevent a stable snapshot")
    if (
        len(held) != len(positions)
        or not np.isfinite(account.cash)
        or account.cash < 0
        or any(not np.isfinite(q) or q < 0 or q != int(q) for q in held.values())
    ):
        raise ValueError("Nonnegative finite cash and whole-share holdings required")
    selected, excluded, identifiers = [], [], set()
    for row in state.get("pending", []):
        identifier = row.get("client_order_id")
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in identifiers
        ):
            raise ValueError("Unique original client order identifiers required")
        identifiers.add(identifier)
        reason = _exclusion(row, state, opened, session)
        if reason:
            excluded.append({"client_order_id": identifier, "reason": reason})
        else:
            selected.append(row)
    return {
        "policy": POLICY,
        "live_policy": state.get("policy_version"),
        "session": str(session),
        "started_at": started.isoformat(),
        "received_at": received.isoformat(),
        "paper_state_sha256": hashlib.sha256(before).hexdigest(),
        "cash": float(account.cash),
        "whole_share_holdings": held,
        "orders": selected,
        "excluded": excluded,
        "working_broker_orders": len(opened),
        "status": "frozen" if selected else "no_eligible_intents",
        "order_submission": False,
    }


# Inspect original quantities; quote-based capacity is conditional and never a fill.
def inspect_intents(snapshot, observations, model, *, attempted_ids=()):
    results = []
    cash = float(snapshot["cash"])
    held = dict(snapshot["whole_share_holdings"])
    for order in snapshot["orders"]:
        observation = observations.get(order["symbol"])
        if order["client_order_id"] in attempted_ids:
            state, forecast, capacity = "previously_attempted", None, 0
        elif observation is None:
            state, forecast, capacity = "missing_observation", None, 0
        else:
            if (
                observation.session != snapshot["session"]
                or observation.symbol != order["symbol"]
                or observation.received_at < snapshot["received_at"]
            ):
                raise ValueError("Observation must follow its frozen intent snapshot")
            forecast = decide(observation, model, order["side"])
            state = forecast["state"]
            price = observation.raw_price
            capacity = 0
            if state in ("execute", "terminal_attempt") and price is not None:
                if order["side"] == "buy":
                    capacity = min(order["qty"], int(cash // price))
                    cash = max(0.0, cash - capacity * price)
                else:
                    capacity = min(order["qty"], int(held.get(order["symbol"], 0)))
                    held[order["symbol"]] = held.get(order["symbol"], 0) - capacity
                    # Sales do not fabricate available cash for another pending buy.
                if capacity == 0:
                    state = "unfunded_or_uncovered"
        results.append(
            {
                "client_order_id": order["client_order_id"],
                "original_order": dict(order),
                "state": state,
                "forecast": forecast,
                "conditional_whole_share_capacity_at_observed_price": capacity,
                "current_gate_state": (
                    "unavailable"
                    if observation is None
                    or not observation.supported
                    or observation.raw_price is None
                    else "execute"
                    if observation.clock == 24
                    or observation.legacy_triggered[order["side"]]
                    else "wait"
                ),
                "first_available_state": (
                    "execute"
                    if observation is not None
                    and observation.supported
                    and observation.raw_price is not None
                    else "unavailable"
                ),
                "order_submission": False,
                "actual_fill": False,
            }
        )
    return results
