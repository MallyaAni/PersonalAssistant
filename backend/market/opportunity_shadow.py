"""Frozen neural inference and isolated prospective accounts; never broker orders."""

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from backend.market import calendar, desk_freshness, edgar, levels_pit
from backend.market import growth_pilot as gp
from backend.market import opportunity_learning as ol
from backend.market.panel import build_panel
from backend.market.store import MarketStore

BUNDLE = Path(__file__).parent / "data/opportunity_neural_v1.npz"
# Declared continuations of a ledger across revisions: (from, to, reason)
# rows. The identity hashes whole files so any drift is caught; a revision
# that touches a hashed file without touching what the shadow reads is
# continued by a declaration here, never by overwriting the fingerprint.
# The file sits outside the hash because the successor identity cannot be
# written into the code it hashes.
MIGRATIONS = Path(__file__).parent / "data/opportunity_shadow_migrations.json"
VERSION = "opportunity-shadow/1"
POLICIES = ("neural", "valuation_rule", "momentum20", "SPY", "USD")


# Run the exported small network with NumPy; production does not need PyTorch.
def predict(x, weights):
    values = np.asarray(x, dtype=np.float32)
    for layer in (0, 2, 4):
        values = values @ weights[f"{layer}.weight"].T + weights[f"{layer}.bias"]
        if layer != 4:
            values = np.tanh(values)
    return values.squeeze(-1)


# Pin the model and execution implementation so an existing experiment cannot drift.
def identity(bundle):
    code = b"".join(
        Path(module.__file__).read_text().replace("\r\n", "\n").encode()
        for module in (gp, ol, edgar, levels_pit, calendar)
    )
    code += Path(__file__).read_text().replace("\r\n", "\n").encode()
    return hashlib.sha256(bundle.read_bytes() + code).hexdigest()


# Commit one complete account transition without overwriting any prior sequence.
def append(folder, row):
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{row['sequence']:08d}.json"
    descriptor, name = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(row, stream, allow_nan=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, target)
    finally:
        os.unlink(name)
    return row


# Load only the last completed transition; malformed records never reset an account.
def latest(folder):
    paths = sorted(folder.glob("[0-9]*.json"))
    return json.loads(paths[-1].read_text()) if paths else None


# The declared continuation from `from_policy` to `to_policy`, or None.
def migration(from_policy, to_policy, path=None):
    """Return the declared migration row for the pair, or None."""
    path = path or MIGRATIONS
    if not path.exists():
        return None
    for row in json.loads(path.read_text(encoding="utf-8")):
        if row.get("from") == from_policy and row.get("to") == to_policy:
            return row
    return None


# Create explicitly separate cash accounts before any future return can be observed.
def initialize(folder, tickers, policy, now, migrations=None):
    prior = latest(folder)
    if prior:
        if prior["tickers"] != list(tickers):
            raise ValueError("Frozen experiment changed; use a separate run directory")
        if prior["policy"] != policy:
            declared = migration(prior["policy"], policy, migrations)
            if declared is None:
                raise ValueError(
                    "Frozen experiment changed; use a separate run directory"
                )
            # The ledger continues under the new identity, and every later
            # row carries where it came from and why.
            return {
                **prior,
                "policy": policy,
                "policy_from": prior["policy"],
                "migration": declared["reason"],
            }
        return prior
    accounts = {
        f"{name}@{bps}bps": {
            "cash": 100000.0,
            "holdings": [0.0] * len(tickers),
            "equity": 100000.0,
            "pending": None,
            "last_decision": None,
            "turnover": 0.0,
        }
        for name in POLICIES
        for bps in (10, 30)
    }
    return append(
        folder,
        {
            "version": VERSION,
            "sequence": 0,
            "policy": policy,
            "tickers": list(tickers),
            "started_at": now.isoformat(),
            "observed_at": now.isoformat(),
            "session": None,
            "accounts": accounts,
            "status": "Awaiting a fresh completed daily session",
        },
    )


# Advance accounts using only previously recorded intents and newly observed returns.
def advance(state, session, now, previous_prices, prices, targets):
    prior = state["session"]
    distance = (
        calendar._future_session_offset(np.datetime64(prior), np.datetime64(session))
        if prior
        else None
    )
    if prior and (not np.isfinite(distance) or distance <= 0):
        raise ValueError("A later known exchange session is required")
    accounts = {}
    for key, old in state["accounts"].items():
        name, fee = key.split("@")
        held = np.asarray(old["holdings"], dtype=float)
        cash, turnover = old["cash"], 0.0
        if prior:
            held = gp.mark(held, previous_prices, prices)
        # A missed daily run cannot manufacture a fill at an already observed price.
        if old["pending"] is not None and distance == 1:
            target = np.asarray(old["pending"])
            if np.any((target > 0) & (~np.isfinite(prices) | (prices <= 0))):
                raise ValueError("Missing execution price")
            held, cash, turnover = gp.rebalance(
                held, cash, target, int(fee[:-3]) / 10000
            )
        last = old["last_decision"]
        elapsed = (
            calendar._future_session_offset(np.datetime64(last), np.datetime64(session))
            if last
            else 20
        )
        due = elapsed >= 20 or (old["pending"] is not None and distance != 1)
        accounts[key] = {
            "cash": cash,
            "holdings": held.tolist(),
            "equity": float(cash + held.sum()),
            "turnover": turnover,
            "pending": targets[name].tolist() if due else None,
            "last_decision": session if due else last,
        }
    return {
        **state,
        "sequence": state["sequence"] + 1,
        "session": session,
        "observed_at": now.isoformat(),
        "accounts": accounts,
        "status": (
            "Observed; missed-session intents cancelled"
            if distance and distance > 1
            else "Observed frozen policies"
        ),
    }


# Observe the current close using the frozen universe, model and training normalizer.
def observe(root, now=None, bundle=BUNDLE, folder=None):
    now = now or datetime.now(UTC)
    local = now.astimezone(desk_freshness.NEW_YORK)
    folder = folder or root / "desk/ml-forward"
    with np.load(bundle, allow_pickle=False) as saved:
        weights = dict(saved)
    tickers = tuple(weights["tickers"].tolist())
    state = initialize(folder, tickers, identity(bundle), now)
    store = MarketStore(root)
    panel = build_panel(store, tickers, "SPY", {}, asof=local.date())
    if tuple(panel.tickers) != tickers:
        raise ValueError("Frozen universe coverage changed")
    session = str(panel.dates[-1])
    if session != local.date().isoformat() or local.hour < 16:
        return state
    if state["session"] == session:
        return state
    data, raw, names = ol.features(panel, store, local.date())
    if list(names) != weights["feature_names"].tolist():
        raise ValueError("Feature schema changed")
    x, _ = ol.normalize(raw[-1], None, (weights["medians"], weights["scale"]))
    forecast = predict(x, weights)
    eligible = data.eligible[-1]
    if not np.isfinite(forecast).all() or not eligible.any():
        raise ValueError("Finite current model evidence required")
    value = x[:, 8] + x[:, 9] + x[:, 12]
    benchmark = np.zeros(len(tickers))
    benchmark[data.benchmark] = 1
    targets = {
        "neural": gp.basket(forecast, eligible & (forecast > 0)),
        "valuation_rule": gp.basket(value, eligible & (value > 0)),
        "momentum20": gp.actions(data, len(data.dates) - 1)[1],
        "SPY": benchmark,
        "USD": np.zeros(len(tickers)),
    }
    prior_indices = (
        np.flatnonzero(data.dates == np.datetime64(state["session"]))
        if state["session"]
        else []
    )
    if state["session"] and not len(prior_indices):
        raise ValueError("Prior mark missing from current history")
    previous = data.prices[prior_indices[0]] if len(prior_indices) else data.prices[-1]
    row = advance(state, session, now, previous, data.prices[-1], targets)
    row["forecast_log_return_percent_20_sessions"] = dict(
        zip(tickers, forecast.tolist(), strict=True)
    )
    row["input_sha256"] = hashlib.sha256(
        x.tobytes() + data.prices[-1].tobytes() + previous.tobytes()
    ).hexdigest()
    row["normalized_inputs"] = x.tolist()
    # Missing unheld marks remain explicit in the journal instead of invalid JSON NaNs.
    row["prices"] = [float(v) if np.isfinite(v) else None for v in data.prices[-1]]
    row["previous_prices"] = [float(v) if np.isfinite(v) else None for v in previous]
    row["targets"] = {name: value.tolist() for name, value in targets.items()}
    return append(folder, row)


# Isolate unavailable research data from the ordinary nightly trading workflow.
def observe_if_current(root, enabled):
    if not enabled:
        return None
    try:
        row = observe(root)
        print(f"ML forward: {row['status']} (sequence {row['sequence']})")
        return row
    except (OSError, ValueError, KeyError, IndexError) as exc:
        print(f"ML forward unavailable ({type(exc).__name__}): {exc}")
        return None


# Expose dated performance without loading model parameters or altering the ledger.
def summary(root):
    try:
        state = latest(root / "desk/ml-forward")
        if state is None:
            return None
        return {
            "status": state["status"],
            "started_at": state["started_at"],
            "observed_at": state["observed_at"],
            "session": state["session"],
            "accounts": {
                name: {
                    "equity": account["equity"],
                    "total_return": account["equity"] / 100000 - 1,
                }
                for name, account in state["accounts"].items()
            },
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "unavailable", "accounts": {}}
