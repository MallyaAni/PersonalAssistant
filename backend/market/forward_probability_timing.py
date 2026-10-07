"""Actual-clock private sender adapter for supplied probabilistic forecasts.

The caller authenticates model, prefix, raw quote and opening-anchor sources.
This contract transports an opening-price forecast to a conditional current
midpoint proxy. It does not claim a midpoint fill or enable a production caller.
"""

import io
import json
import math
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.agents.trading.desk import paper
from backend.market import calendar, entry_timing, execution_quotes
from backend.market import forward_entry_features as observations
from backend.market import forward_execution as inference
from backend.market import live_probability_timing as original
from backend.market import probabilistic_execution as probability
from backend.market.alpaca_trading import AlpacaTradingError
from backend.market.daily_arithmetic_bridge import _as_of, _hash

CONTRACT = "forward-probability-timing/1-shadow"
RESIDUAL_FIELDS = ("residuals", "weights", "day_indices", "clock_indices")


# Keep inferred stock distributions attached to their actual observation receipt.
@dataclass(frozen=True)
class ObservedForecast:
    distributions: dict
    receipt: dict
    receipt_sha256: str


# Bind the complete explicit receipt without accepting non-JSON evidence.
def _digest(value):
    return sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


# Check original sample identities, support and clocks before storing or restoring them.
def _validate_residual_month(month, observed_at):
    if not isinstance(month, inference.ResidualMonth):
        raise ValueError("Original prepared residual month required")
    receipt, now = month.receipt, _as_of(observed_at)
    identity = receipt["identity"]
    first, exchange_calendar = inference._month_session(identity["fit_date"])
    published = _as_of(identity["published_at"])
    symbols, records = identity["symbols"], receipt["stocks"]
    if (
        month.receipt_sha256 != _digest(receipt)
        or receipt["identity_sha256"] != _digest(identity)
        or identity["policy"] != "forward-execution-residuals/1-shadow"
        or identity["sources"] != inference._sources()
        or identity["horizon"] != probability.HORIZON
        or identity["freeze"] != str(probability.FREEZE)
        or identity["minimum_days"] != probability.MIN_DAYS
        or identity["maximum_days"] != probability.MAX_DAYS
        or identity["cutoff_exclusive"] != str(min(first, probability.FREEZE))
        or identity["lookback_first_date"]
        != str(
            np.busday_offset(first, -probability.MAX_DAYS, busdaycal=exchange_calendar)
        )
        or not _as_of(identity["requested_at"]) <= published <= now
        or np.datetime64(published.date(), "M") != first.astype("datetime64[M]")
        or published.date() < first.astype(object)
        or np.datetime64(now.date(), "M") != first.astype("datetime64[M]")
        or receipt["adoption_eligible"] is not False
        or receipt["confidence_guarantee"] is not False
        or len(symbols) != len(set(symbols))
        or [row["symbol"] for row in records] != symbols
        or set(month.samples)
        != {row["symbol"] for row in records if row["status"] == "available"}
    ):
        raise ValueError("Original causal residual receipt and cohort required")
    for record in records:
        symbol, status = record["symbol"], record["status"]
        if status not in (
            "available",
            "excluded_benchmark",
            "insufficient_mature_sessions",
        ):
            raise ValueError("Original residual missingness status required")
        if (symbol in ("SPY", "QQQ")) != (status == "excluded_benchmark"):
            raise ValueError("Benchmarks cannot become stock residual samples")
        if status != "available":
            continue
        sample = month.samples[symbol]
        residuals, weights = probability._sample(sample.residuals, sample.weights)
        days, clocks = sample.day_indices, sample.clock_indices
        if (
            days.ndim != 1
            or clocks.shape != days.shape
            or days.dtype.kind not in "iu"
            or clocks.dtype.kind not in "iu"
            or residuals.shape != days.shape
            or weights.shape != days.shape
            or np.any(days < 0)
            or np.any(clocks < 0)
            or np.any(clocks > 22)
            or np.any(
                (days[1:] < days[:-1])
                | ((days[1:] == days[:-1]) & (clocks[1:] <= clocks[:-1]))
            )
            or record["training_rows"] != len(days)
            or record["maximum_endpoint"] is None
            or np.datetime64(record["maximum_endpoint"], "D")
            >= min(first, probability.FREEZE)
        ):
            raise ValueError("Original ordered residual observation rows required")
        unique, counts = np.unique(days, return_counts=True)
        if (
            record["training_days"] != len(unique)
            or len(unique) < probability.MIN_DAYS
            or not np.array_equal(weights, 1.0 / counts[np.searchsorted(unique, days)])
            or any(
                record["hashes"][name] != _hash(getattr(sample, name))
                for name in RESIDUAL_FIELDS
            )
        ):
            raise ValueError(
                "Original supported residual bytes and date weights required"
            )


# Store non-executable residual arrays once and date availability after serialization.
def write_residual_month(output, month, *, clock=None):
    if not isinstance(month, inference.ResidualMonth):
        raise ValueError("Original prepared residual month required")
    receipt = deepcopy(month.receipt)
    if "prepared_at" in receipt["identity"]:
        raise ValueError("Already stored residual month cannot be republished")
    samples = {
        symbol: probability.ResidualSample(
            *(getattr(sample, name).copy() for name in RESIDUAL_FIELDS)
        )
        for symbol, sample in month.samples.items()
    }
    frozen = inference.ResidualMonth(samples, receipt, month.receipt_sha256)
    _validate_residual_month(frozen, receipt["identity"]["published_at"])
    output = Path(output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    arrays = {
        f"s{index}_{name}": getattr(samples[record["symbol"]], name)
        for index, record in enumerate(receipt["stocks"])
        if record["status"] == "available"
        for name in RESIDUAL_FIELDS
    }
    descriptor = os.open(
        output / "residuals.npz", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    with os.fdopen(descriptor, "wb") as target:
        np.savez_compressed(target, **arrays)
        target.flush()
        os.fsync(target.fileno())
    available = _as_of(clock() if clock else datetime.now(calendar.NEW_YORK))
    _validate_residual_month(frozen, available)
    identity = receipt["identity"]
    identity["prepared_at"] = identity["published_at"]
    identity["published_at"] = available.isoformat()
    identity["residual_artifact"] = {
        "name": "residuals.npz",
        "sha256": sha256((output / "residuals.npz").read_bytes()).hexdigest(),
    }
    identity["storage_sources"] = _inference_sources()
    receipt["preparation_receipt_sha256"] = month.receipt_sha256
    receipt["identity_sha256"] = _digest(identity)
    raw = json.dumps(receipt, sort_keys=True, allow_nan=False).encode()
    descriptor = os.open(
        output / "residuals.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    with os.fdopen(descriptor, "wb") as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())
    return sha256(raw).hexdigest()


# Restore only original hash-bound arrays and retain their actual later availability.
def load_residual_month(output, *, receipt_sha256, observed_at):
    output = Path(output)
    if output.is_symlink() or any(
        (output / name).is_symlink() for name in ("residuals.json", "residuals.npz")
    ):
        raise ValueError("Regular original residual artifacts required")
    raw = (output / "residuals.json").read_bytes()
    if sha256(raw).hexdigest() != receipt_sha256:
        raise ValueError("Original residual publication bytes differ")
    receipt = json.loads(raw)
    identity = receipt["identity"]
    artifact = identity["residual_artifact"]
    if (
        artifact["name"] != "residuals.npz"
        or identity["storage_sources"] != _inference_sources()
    ):
        raise ValueError("Original residual artifact and storage helpers required")
    encoded = (output / "residuals.npz").read_bytes()
    if sha256(encoded).hexdigest() != artifact["sha256"]:
        raise ValueError("Original residual array file bytes differ")
    samples = {}
    with np.load(io.BytesIO(encoded), allow_pickle=False) as saved:
        expected = {
            f"s{index}_{name}"
            for index, record in enumerate(receipt["stocks"])
            if record["status"] == "available"
            for name in RESIDUAL_FIELDS
        }
        if len(saved.files) != len(expected) or set(saved.files) != expected:
            raise ValueError("Exact original residual archive fields required")
        for index, record in enumerate(receipt["stocks"]):
            if record["status"] == "available":
                arrays = [saved[f"s{index}_{name}"] for name in RESIDUAL_FIELDS]
                for array in arrays:
                    array.flags.writeable = False
                samples[record["symbol"]] = probability.ResidualSample(*arrays)
    restored = inference.ResidualMonth(samples, receipt, receipt_sha256)
    _validate_residual_month(restored, observed_at)
    preparation = deepcopy(receipt)
    original_identity = preparation["identity"]
    original_identity["published_at"] = original_identity.pop("prepared_at")
    original_identity.pop("residual_artifact")
    original_identity.pop("storage_sources")
    original_sha = preparation.pop("preparation_receipt_sha256")
    preparation["identity_sha256"] = _digest(original_identity)
    _validate_residual_month(
        inference.ResidualMonth(samples, preparation, original_sha),
        identity["published_at"],
    )
    return restored


# Bind the actual inference, feature and sender modules used by this observation.
def _inference_sources():
    root = Path(__file__).resolve().parents[2]
    return {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in (
            Path(__file__),
            Path(observations.__file__),
            Path(inference.__file__),
            Path(original.__file__),
            Path(probability.__file__),
        )
    }


# Describe every inferred distribution, retaining missing risk and original arrays.
def _forecast_identity(distributions):
    identity = {}
    for symbol, value in distributions.items():
        if value is None:
            identity[symbol] = None
            continue
        if (
            not isinstance(value, probability.Distribution)
            or value.horizon != probability.HORIZON
            or not math.isfinite(value.mean)
            or original._positive(value.scale) is None
        ):
            raise ValueError("Original positive-risk inferred distribution required")
        probability._sample(value.residuals, value.weights)
        identity[symbol] = {
            "mean": float(value.mean),
            "scale": float(value.scale),
            "residuals": _hash(value.residuals),
            "weights": _hash(value.weights),
            "horizon": value.horizon,
        }
    return identity


# Derive current features and authenticate numeric heads before recording availability.
def prepare_forecast(
    panel,
    grades,
    eligible,
    prefixes,
    *,
    observed_at,
    daily_as_of,
    model_folder,
    model_receipt_sha256,
    residual_month,
    clock=None,
):
    observed = _as_of(observed_at)
    # Freeze caller arrays once so later edits cannot alter this feature observation.
    prior = SimpleNamespace(
        dates=np.asarray(panel.dates).copy(),
        tickers=tuple(panel.tickers),
        adj_close=np.asarray(panel.adj_close).copy(),
    )
    prefixes = deepcopy(prefixes)
    frame = observations.observe(
        prior,
        np.asarray(grades).copy(),
        np.asarray(eligible).copy(),
        prefixes,
        observed_at=observed,
        daily_as_of=daily_as_of,
    )
    distributions = inference.current_distributions(
        model_folder,
        model_receipt_sha256,
        residual_month,
        symbols=frame["symbols"],
        values=frame["features"],
        valid=frame["valid"],
        observed_at=observed,
        timing_supported=frame["timing_supported"],
    )
    available = _as_of(clock() if clock else datetime.now(calendar.NEW_YORK))
    completed = _as_of(frame["completed_at"])
    if not observed <= available < completed + entry_timing.BAR:
        raise ValueError(
            "Actual forecast completion must follow observation before expiry"
        )
    raw_openings = {}
    for symbol, values in prefixes.items():
        opening = np.asarray(values["open"])[0]
        raw_openings[symbol] = original._positive(opening)
    receipt = {
        "contract": CONTRACT,
        "sources": _inference_sources(),
        "model_receipt": model_receipt_sha256,
        "residual_receipt": residual_month.receipt_sha256,
        "observation": {
            key: deepcopy(frame[key])
            for key in (
                "session",
                "clock",
                "completed_at",
                "observed_at",
                "daily_as_of",
                "timing_supported",
                "identity",
            )
        },
        "symbols": list(frame["symbols"]),
        "feature_names": list(frame["feature_names"]),
        "features_sha256": _hash(frame["features"]),
        "valid_sha256": _hash(frame["valid"]),
        "raw_session_openings": raw_openings,
        "forecast_available_at": available.isoformat(),
        "distributions": _forecast_identity(distributions),
        "confidence_guarantee": False,
        "adoption_eligible": False,
    }
    # Prevent ordinary accidental edits while retaining independent receipt checks.
    for value in distributions.values():
        if value is not None:
            value.residuals.flags.writeable = False
            value.weights.flags.writeable = False
    return ObservedForecast(distributions, receipt, _digest(receipt))


# Bind actual inferred evidence to the sender without accepting substituted forecasts.
def build_forecast_reader(
    forecast,
    now,
    snapshot,
    pending,
    observed_account,
    cost_bps,
    trace,
    *,
    evidence_root,
):
    if (
        not isinstance(forecast, ObservedForecast)
        or _digest(forecast.receipt) != forecast.receipt_sha256
        or forecast.receipt["sources"] != _inference_sources()
        or forecast.receipt["contract"] != CONTRACT
        or forecast.receipt["adoption_eligible"] is not False
        or forecast.receipt["confidence_guarantee"] is not False
        or forecast.receipt["distributions"]
        != _forecast_identity(forecast.distributions)
        or tuple(forecast.distributions) != tuple(forecast.receipt["symbols"])
    ):
        raise ValueError(
            "Original inferred forecast receipt and distributions required"
        )
    receipt, trace_before = deepcopy(forecast.receipt), len(trace)
    stored = _store_inference(evidence_root, receipt, forecast.receipt_sha256)
    observation = receipt["observation"]
    snapshot = deepcopy(snapshot)
    for symbol, quote in snapshot["quotes"].items():
        if isinstance(quote, dict) and (
            symbol not in receipt["raw_session_openings"]
            or quote.get("open") != receipt["raw_session_openings"][symbol]
        ):
            quote["basis"] = "incompatible_prefix_opening"
    reader = build_reader(
        forecast.distributions,
        receipt["symbols"],
        observation["clock"],
        _as_of(observation["completed_at"]).date(),
        now,
        snapshot,
        pending,
        observed_account,
        cost_bps,
        trace,
        forecast_available_at=_as_of(receipt["forecast_available_at"]),
        source_identity={
            "model_receipt": receipt["model_receipt"],
            "residual_receipt": receipt["residual_receipt"],
            "observation": forecast.receipt_sha256,
        },
    )

    # Retain the complete inferred receipt when the real sender persists its verdict.
    def inferred_reader(row, latch, quote, observation_at, today):
        actual = deepcopy(quote)
        expected = snapshot["quotes"].get(row["symbol"])
        if (
            isinstance(actual, dict)
            and isinstance(expected, dict)
            and actual.get("open") != receipt["raw_session_openings"].get(row["symbol"])
        ):
            actual["basis"] = "incompatible_prefix_opening"
        verdict = reader(row, latch, actual, observation_at, today)
        evidence = verdict["timed"]["forward_receipt"]
        evidence["inference"] = deepcopy(stored)
        verdict["timed"]["forward_receipt_sha256"] = _digest(evidence)
        if len(trace) > trace_before:
            trace[-1]["forward_receipt"] = deepcopy(evidence)
            trace[-1]["forward_receipt_sha256"] = _digest(evidence)
        return verdict

    return inferred_reader


# Retain one immutable inference receipt outside the repeatedly serialized account.
def _store_inference(root, receipt, expected):
    root = Path(root)
    raw = json.dumps(receipt, sort_keys=True, allow_nan=False).encode()
    if sha256(raw).hexdigest() != expected:
        raise ValueError("Original inference receipt bytes required")
    folder = root / paper.PAPER_KIND / "forecast-evidence"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / (expected + ".json")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError("Existing immutable inference evidence differs") from None
    else:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return {"path": str(path.relative_to(root)), "sha256": expected}


# Read only actual observed balances and quantities, never promised sale proceeds.
def capture_account(broker, completed, *, clock=None):
    completed = original._aware(completed)
    now = None
    receipt = {"reason": "", "nav": None, "budget": None, "held": {}}
    try:
        before = broker.clock()
        first, positions = broker.account(), broker.positions()
        second, repeated = broker.account(), broker.positions()
        after = broker.clock()
        now = original._aware(clock() if clock else datetime.now(calendar.NEW_YORK))
        clocks = [
            entry_timing._instant(value.get("timestamp")) for value in (before, after)
        ]
        if (
            any(value.get("is_open") is not True for value in (before, after))
            or any(value is None for value in clocks)
            or not completed <= clocks[0] <= clocks[1] <= now
            or (now - clocks[0]).total_seconds() >= execution_quotes.MAX_AGE_SECONDS
        ):
            raise ValueError("Current observed open broker clocks required")
        amounts = []
        for account in (first, second):
            nav = original._positive(account.equity)
            cash = original._positive(account.cash, zero=True)
            power = original._positive(account.buying_power, zero=True)
            if nav is None or cash is None or power is None:
                raise ValueError(
                    "Finite observed equity and nonnegative funds required"
                )
            amounts.append((nav, cash, power))
        holdings = []
        for batch in (positions, repeated):
            held = {}
            for position in batch:
                quantity = original._positive(position.qty, zero=True)
                if (
                    not isinstance(position.symbol, str)
                    or not position.symbol
                    or position.symbol in held
                    or quantity is None
                    or quantity != math.floor(quantity)
                    or original._positive(position.current_price) is None
                ):
                    raise ValueError("Unique marked whole-share holdings required")
                held[position.symbol] = int(quantity)
            holdings.append(held)
        if amounts[0][1:] != amounts[1][1:] or holdings[0] != holdings[1]:
            raise ValueError("Account changed during the observed funding snapshot")
        # Independent feeds may mark equity differently; neither is a future fill.
        receipt.update(
            nav=amounts[1][0],
            budget=min(amounts[1][1:]),
            held=holdings[1],
            source_timestamps=[value.isoformat() for value in clocks],
        )
    except (AlpacaTradingError, OSError, ValueError, TypeError, AttributeError) as exc:
        receipt["reason"] = str(exc)
    if now is None:
        now = original._aware(clock() if clock else datetime.now(calendar.NEW_YORK))
    receipt.update(captured_at=now.isoformat(), completed_at=completed.isoformat())
    return {"receipt": receipt, "receipt_sha256": _digest(receipt)}


# Validate known current prices and the already published first next-bar opening.
def _quote(quote, start, completed, now):
    if not isinstance(quote, dict):
        return None
    stamps = [
        entry_timing._instant(quote.get(key))
        for key in ("as_of", "received_at", "next_open_at", "next_open_published_at")
    ]
    at, received, anchor_at, anchor_published = stamps
    values = [
        original._positive(quote.get(key))
        for key in ("bid", "ask", "bid_size", "ask_size", "next_open", "open", "last")
    ]
    bid, ask, _, _, anchor, _, last = values
    if (
        any(value is None for value in (*stamps, *values))
        or quote.get("basis") != "raw_current_shares"
        or quote.get("feed") not in ("iex", "sip")
        or entry_timing._instant(quote.get("bar")) != start
        or not completed <= at <= received <= now
        or not completed == anchor_at <= anchor_published <= now
        or (now - at).total_seconds() >= execution_quotes.MAX_AGE_SECONDS
        or ask < bid
    ):
        return None
    midpoint = bid / 2 + ask / 2
    if (
        not math.isfinite(midpoint)
        or last != midpoint
        or (ask - bid) / midpoint * 1e4 > execution_quotes.MAX_SPREAD_BPS
    ):
        return None
    return midpoint, anchor


# Freeze actual availability, current price transport and shared funded sender checks.
def build_reader(
    distributions,
    symbols,
    clock,
    session,
    now,
    snapshot,
    pending,
    observed_account,
    cost_bps,
    trace,
    *,
    forecast_available_at,
    source_identity,
):
    now, available = original._aware(now), original._aware(forecast_available_at)
    symbols = tuple(symbols)
    start = datetime.combine(session, calendar.REGULAR_OPEN, calendar.NEW_YORK)
    start += timedelta(minutes=15 * int(clock))
    completed = start + entry_timing.BAR
    # Use the original reviewed session/symbol/intent checks at their own boundary.
    _, session, symbols, start = original._contract(
        None, symbols, 0, clock, session, completed, snapshot, pending, cost_bps, trace
    )
    if (
        not completed <= available <= now < completed + entry_timing.BAR
        or not isinstance(distributions, dict)
        or set(distributions) != set(symbols)
        or not isinstance(source_identity, dict)
        or not {"model_receipt", "residual_receipt", "observation"}
        <= set(source_identity)
        or any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            or len(value) != 64
            or any(letter not in "0123456789abcdef" for letter in value)
            for key, value in source_identity.items()
        )
    ):
        raise ValueError(
            "Actual forecast publication and fixed source identities required"
        )
    account = deepcopy(observed_account["receipt"])
    captured = entry_timing._instant(account.get("captured_at"))
    if (
        _digest(account) != observed_account["receipt_sha256"]
        or account.get("completed_at") != completed.isoformat()
        or captured is None
        or not completed <= captured <= now
        or (now - captured).total_seconds() >= execution_quotes.MAX_AGE_SECONDS
    ):
        raise ValueError("Original current observed account receipt required")
    closing = datetime.combine(
        session, calendar.session_close(session), calendar.NEW_YORK
    )
    supported = completed + entry_timing.BAR < closing and clock <= 22
    distributions = deepcopy(distributions)
    quotes = deepcopy(snapshot["quotes"])
    price_pairs = {
        symbol: _quote(quote, start, completed, now) for symbol, quote in quotes.items()
    }
    transported, identities = {}, {}
    for symbol, distribution in distributions.items():
        pair = price_pairs.get(symbol)
        transported[symbol] = None
        if distribution is None:
            identities[symbol] = None
            continue
        if (
            not isinstance(distribution, probability.Distribution)
            or distribution.horizon != probability.HORIZON
            or original._positive(distribution.scale) is None
            or not math.isfinite(distribution.mean)
        ):
            raise ValueError(
                "Original finite positive-risk probability forecast required"
            )
        residuals, weights = probability._sample(
            distribution.residuals, distribution.weights
        )
        identities[symbol] = {
            "mean": float(distribution.mean),
            "scale": float(distribution.scale),
            "residuals": sha256(residuals.tobytes()).hexdigest(),
            "weights": sha256(weights.tobytes()).hexdigest(),
        }
        if pair is not None and supported and symbol not in ("SPY", "QQQ"):
            midpoint, anchor = pair
            shift = math.log(midpoint) - math.log(anchor)
            transported[symbol] = probability.Distribution(
                distribution.mean + shift,
                distribution.scale,
                residuals,
                weights,
            )
    receipt = {
        "contract": CONTRACT,
        "session": session.isoformat(),
        "clock": int(clock),
        "completed_at": completed.isoformat(),
        "forecast_available_at": available.isoformat(),
        "decided_at": now.isoformat(),
        "source_identity": deepcopy(source_identity),
        "forecast_identity": identities,
        "quotes": quotes,
        "account": deepcopy(observed_account),
        "transport": "log(current_midpoint/original_next_bar_open)",
        "conditional_midpoint_proxy": True,
        "midpoint_fill_proven": False,
    }

    # Resolve only a frozen transported distribution for the original named stock.
    def provider(day, observed_clock, stock):
        return transported[symbols[stock]]

    # Price batch funding only from validated current quotes, never later bars.
    def quote_reader(quote):
        pair = _quote(quote, start, completed, now)
        return pair[0] if pair is not None else None

    # Freeze two stable GET observations before the sender submits any request.
    def account_reader(marks):
        return account["reason"], account["nav"], account["budget"], account["held"]

    return original._frozen_reader(
        provider,
        symbols,
        0,
        clock,
        session,
        now,
        quotes,
        pending,
        cost_bps,
        trace,
        quote_reader,
        account_reader,
        start,
        extra={"forward_receipt": receipt, "forward_receipt_sha256": _digest(receipt)},
    )
