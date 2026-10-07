"""Dated monthly heads and current stock risk for the private funded shadow path.

The caller authenticates original inputs and supplies the actual publication
clock. The August freeze, monthly window, features, estimator and volatility
transform remain unchanged. This module publishes evidence, not broker orders.
"""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_daily_arithmetic as direct
from backend.market import direct_error_band as errors
from backend.market import direct_feature_arithmetic as feature
from backend.market import learned_entry_models as base
from backend.market import learned_retention_models as context

POLICY = "forward-held-arithmetic/1-shadow"
PROTOCOL = "docs/research/forward-arithmetic-publication-2026-10-04.md"


# Keep non-executable model bytes separate from their dated publication receipt.
@dataclass(frozen=True)
class MonthlyPublication:
    bundle: dict | None
    receipt: dict


# Resolve a first-of-month exchange session without guessing uncovered years.
def _month_session(value):
    day = np.datetime64(value, "D")
    if np.isnat(day):
        raise ValueError("Known first monthly exchange session required")
    years, calendar = exchange.reviewed_sessions()
    if day.astype(object).year not in years:
        raise ValueError("Reviewed calendar year required")
    first = np.busday_offset(
        day.astype("datetime64[M]").astype("datetime64[D]"),
        0,
        roll="forward",
        busdaycal=calendar,
    )
    if day != first:
        raise ValueError("First monthly exchange session required")
    return day, calendar


# Fit only mature original rows and retain the real late-publication clock.
def fit_month(
    prepared,
    bridge,
    grades,
    eligible,
    *,
    fit_session,
    published_at,
    source_revision,
    input_identity,
):
    fit_date, calendar = _month_session(fit_session)
    published = reference._as_of(published_at)
    if (
        not isinstance(source_revision, str)
        or len(source_revision) != 40
        or any(c not in "0123456789abcdef" for c in source_revision)
        or not isinstance(input_identity, dict)
        or not input_identity
        or any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
            for key, value in input_identity.items()
        )
    ):
        raise ValueError(
            "Explicit source revision and original artifact hashes required"
        )
    close = datetime.combine(
        fit_date.astype(object),
        exchange.session_close(fit_date.astype(object)),
        exchange.NEW_YORK,
    )
    if published < close or np.datetime64(published.date(), "M") != fit_date.astype(
        "datetime64[M]"
    ):
        raise ValueError("Publication must follow fit-session close within its month")
    x, dates, names, mask, _ = feature.support(
        prepared, bridge, grades, eligible, hold_b=True
    )
    as_of = reference._as_of(bridge.manifest["data_as_of"])
    if as_of > published:
        raise ValueError("Inputs cannot arrive after model publication")
    years, _ = exchange.reviewed_sessions()
    complete = np.arange(dates[0], dates[-1] + np.timedelta64(1, "D"))
    if (
        any(day.astype(object).year not in years for day in dates)
        or not np.array_equal(
            dates, complete[np.is_busday(complete, busdaycal=calendar)]
        )
        or dates[-1] > np.datetime64(as_of.date())
        or datetime.combine(
            dates[-1].astype(object),
            exchange.session_close(dates[-1].astype(object)),
            exchange.NEW_YORK,
        )
        > as_of
    ):
        raise ValueError("Complete completed-close input calendar required")
    first = int(np.searchsorted(dates, fit_date))
    training_dates = dates
    if first == len(dates):
        next_session = np.busday_offset(dates[-1], 1, busdaycal=calendar)
        if fit_date != next_session:
            raise ValueError("Missing sessions before forward monthly fit")
        training_dates = np.append(dates, fit_date)
    elif dates[first] != fit_date:
        raise ValueError("Missing monthly fit session")
    actual, stocks, weights, training = feature.training(
        training_dates, names, x, bridge.labels, bridge.label_end_dates, mask, first
    )
    head = None
    status = "insufficient_training_days"
    if training["training_days"] >= reference.MIN_DAYS:
        with threadpool_limits(limits=2):
            head = direct._fit(
                x[actual, stocks], bridge.labels[actual, stocks], weights
            )
        status = "fitted" if head is not None else "no_observed_training_features"
    root = Path(__file__).resolve().parents[2]
    identity = {
        "policy": POLICY,
        "training_policy": feature.HELD_POLICY,
        "target": "adjusted_open[t+2]/adjusted_open[t+1]-1",
        "source_revision": source_revision,
        "input_identity": deepcopy(input_identity),
        "data_as_of": as_of.isoformat(),
        "fit_requested_at": published.isoformat(),
        "published_at": published.isoformat(),
        "feature_names": list(direct.FEATURE_NAMES),
        "symbols": list(names),
        "config": dict(base.MODEL_CONFIG["boosting"]),
        "freeze": str(reference.FREEZE),
        "minimum_days": reference.MIN_DAYS,
        "maximum_days": reference.MAX_DAYS,
        "source_sha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(__file__),
                Path(direct.__file__),
                Path(feature.__file__),
                Path(reference.__file__),
                Path(base.__file__),
                Path(exchange.__file__),
                root / PROTOCOL,
            )
        },
        "input_sha256": {
            name: reference._hash(np.asarray(value))
            for name, value in (
                ("dates", dates),
                ("features", x),
                ("grades", grades),
                ("eligible", eligible),
                ("mask", mask),
                ("labels", bridge.labels),
                ("endpoints", bridge.label_end_dates),
            )
        },
    }
    receipt = {
        "identity": identity,
        "identity_sha256": base._json_hash(identity),
        "training": training,
        "status": status,
        "model": direct.model_identity(head) if head is not None else None,
        "adoption_eligible": False,
    }
    return MonthlyPublication(
        direct.numeric_snapshot(head) if head is not None else None, receipt
    )


# Publish once into a new directory and never replace an earlier model's evidence.
def write_publication(output, publication, *, clock=None):
    output = Path(output)
    receipt = deepcopy(publication.receipt)
    _admit(publication, receipt["identity"]["published_at"])
    output.mkdir(parents=True, exist_ok=False)
    receipt["model_file"] = None
    if publication.bundle is not None:
        path = output / "model.npz"
        np.savez_compressed(path, **publication.bundle)
        receipt["model_file"] = {
            "name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    # The default clock runs after numeric serialization, never before fitting.
    published = reference._as_of(clock() if clock else datetime.now(exchange.NEW_YORK))
    if published < reference._as_of(receipt["identity"]["fit_requested_at"]):
        raise ValueError("Publication cannot precede the requested fit clock")
    receipt["identity"]["published_at"] = published.isoformat()
    receipt["identity_sha256"] = base._json_hash(receipt["identity"])
    _admit(MonthlyPublication(publication.bundle, receipt), published)
    encoded = json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False).encode()
    (output / "publication.json").write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


# Admit a current published numeric head without fitting or backdating availability.
def _admit(publication, observed_at, decision_session=None):
    receipt, identity = publication.receipt, publication.receipt["identity"]
    observed = reference._as_of(observed_at)
    decision_date = np.datetime64(observed.date(), "D")
    if decision_session is not None:
        decision_date = np.datetime64(decision_session, "D")
        _close_window(decision_date, observed)
    fit_date, _ = _month_session(receipt["training"]["fit_date"])
    published = reference._as_of(identity["published_at"])
    fit_close = datetime.combine(
        fit_date.astype(object),
        exchange.session_close(fit_date.astype(object)),
        exchange.NEW_YORK,
    )
    if (
        receipt["identity_sha256"] != base._json_hash(identity)
        or identity["policy"] != POLICY
        or receipt["adoption_eligible"] is not False
        or published > observed
        or reference._as_of(identity["fit_requested_at"]) > published
        or reference._as_of(identity["data_as_of"]) > published
        or published < fit_close
        or np.datetime64(published.date(), "M") != fit_date.astype("datetime64[M]")
        or decision_date.astype("datetime64[M]") != fit_date.astype("datetime64[M]")
        or receipt["training"]["label_end_before"]
        != str(min(fit_date, reference.FREEZE))
        or receipt["training"]["month"] != str(fit_date.astype("datetime64[M]"))
        or identity["config"] != base.MODEL_CONFIG["boosting"]
        or identity["freeze"] != str(reference.FREEZE)
        or identity["minimum_days"] != reference.MIN_DAYS
        or identity["maximum_days"] != reference.MAX_DAYS
        or identity["feature_names"] != list(direct.FEATURE_NAMES)
        or identity["training_policy"] != feature.HELD_POLICY
        or identity["target"] != "adjusted_open[t+2]/adjusted_open[t+1]-1"
    ):
        raise ValueError("Current causal model publication required")
    if receipt["status"] != "fitted":
        if (
            receipt["status"]
            not in ("insufficient_training_days", "no_observed_training_features")
            or publication.bundle is not None
            or receipt["model"] is not None
        ):
            raise ValueError("Unavailable publication cannot contain a model")
        return None
    training = receipt["training"]
    if (
        training["training_days"] < reference.MIN_DAYS
        or training["maximum_label_end"] is None
        or np.datetime64(training["maximum_label_end"], "D")
        >= min(fit_date, reference.FREEZE)
    ):
        raise ValueError("Mature sufficient training required for published model")
    return direct.numeric_head(publication.bundle, receipt["model"])


# Restore only hash-linked non-executable arrays at an explicitly supplied clock.
def load_publication(output, *, receipt_sha256, observed_at, decision_session=None):
    output = Path(output)
    raw = (output / "publication.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt_sha256:
        raise ValueError("Original publication bytes mismatch")
    receipt = json.loads(raw)
    bundle = None
    record = receipt["model_file"]
    if record is not None:
        if record["name"] != "model.npz":
            raise ValueError("Canonical numeric model filename required")
        path = output / record["name"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Original numeric model bytes mismatch")
        with np.load(path, allow_pickle=False) as values:
            bundle = dict(values)
    return _admit(
        MonthlyPublication(bundle, receipt), observed_at, decision_session
    ), receipt


# Keep one completed-close observation and its authenticated numeric head together.
@dataclass(frozen=True)
class CloseObservation:
    dates: np.ndarray
    symbols: tuple
    features: np.ndarray
    prices: np.ndarray
    forecasts: np.ndarray
    support: np.ndarray
    history_prices: np.ndarray
    history_grades: np.ndarray
    head: direct.NumericHead | None
    receipt: dict


# Refuse unfinished or expired daily observations at the real next-open boundary.
def _close_window(day, observed_at):
    observed = reference._as_of(observed_at)
    years, calendar = exchange.reviewed_sessions()
    if day.astype(object).year not in years or not np.is_busday(
        day, busdaycal=calendar
    ):
        raise ValueError("Reviewed exchange close required")
    next_day = np.busday_offset(day, 1, busdaycal=calendar)
    if next_day.astype(object).year not in years:
        raise ValueError("Reviewed following exchange session required")
    close = datetime.combine(
        day.astype(object),
        exchange.session_close(day.astype(object)),
        exchange.NEW_YORK,
    )
    opening = datetime.combine(next_day.astype(object), time(9, 30), exchange.NEW_YORK)
    if not close <= observed < opening:
        raise ValueError("Completed close before its following opening required")
    return close, opening


# Score the original full-prefix features without fitting or needing future labels.
def observe_close(
    panel,
    grades,
    eligible,
    provenance,
    model_directory,
    *,
    model_receipt_sha256,
    observed_at,
):
    observed = reference._as_of(observed_at)
    head, model = load_publication(
        model_directory,
        receipt_sha256=model_receipt_sha256,
        observed_at=observed,
        decision_session=str(panel.dates[-1]),
    )
    if not isinstance(provenance, dict) or "data_as_of" not in provenance:
        raise ValueError("Actual completed input publication required")
    data_as_of = reference._as_of(provenance["data_as_of"])
    if data_as_of > observed:
        raise ValueError("Input publication cannot follow observation")
    prepared = context.completed_features(
        panel, grades, eligible, panel.dates, provenance
    )
    dates, names = prepared["dates"], prepared["symbols"]
    close, opening = _close_window(dates[-1], observed)
    if data_as_of < close or names != tuple(model["identity"]["symbols"]):
        raise ValueError(
            "Published current close and original stock identities required"
        )
    years, calendar = exchange.reviewed_sessions()
    complete = np.arange(dates[0], dates[-1] + np.timedelta64(1, "D"))
    if any(day.astype(object).year not in years for day in dates) or not np.array_equal(
        dates, complete[np.is_busday(complete, busdaycal=calendar)]
    ):
        raise ValueError("Complete original feature calendar required")
    mask = prepared["risk_valid"][-1:]
    values, diagnostics = direct.predict(head, prepared["X"][-1:], mask)
    identity = {
        "policy": "forward-holding-close/1-shadow",
        "model_publication_sha256": model_receipt_sha256,
        "model": model["model"],
        "model_training_policy": model["identity"]["training_policy"],
        "model_fit_date": model["training"]["fit_date"],
        "model_published_at": model["identity"]["published_at"],
        "freeze": model["identity"]["freeze"],
        "data_as_of": data_as_of.isoformat(),
        "observed_at": observed.isoformat(),
        "published_at": observed.isoformat(),
        "expires_at": opening.isoformat(),
        "symbols": list(names),
        "provenance": deepcopy(provenance),
        "prefix_sha256": {
            name: reference._hash(np.asarray(value))
            for name, value in (
                ("dates", dates),
                ("prices", panel.adj_close),
                ("grades", grades),
                ("eligible", eligible),
            )
        },
        "source_sha256": {
            str(
                Path(module.__file__).relative_to(Path(__file__).resolve().parents[2])
            ): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (context, context.learned_entry_data, direct, exchange)
        },
        "array_sha256": {
            name: reference._hash(np.asarray(value))
            for name, value in (
                ("dates", dates),
                ("symbols", np.asarray(names)),
                ("features", prepared["X"][-1]),
                ("prices", prepared["prices"][-1]),
                ("forecasts", values[0]),
                ("support", mask[0]),
                ("history_prices", panel.adj_close),
                ("history_grades", grades),
            )
        },
    }
    identity["source_sha256"]["backend/market/forward_arithmetic.py"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    return CloseObservation(
        dates.copy(),
        names,
        prepared["X"][-1].copy(),
        prepared["prices"][-1].copy(),
        values[0].copy(),
        mask[0].copy(),
        np.asarray(panel.adj_close).copy(),
        np.asarray(grades).copy(),
        head,
        {
            "identity": identity,
            "identity_sha256": base._json_hash(identity),
            "status": "predicted" if head is not None else "model_unavailable",
            "prediction_counts": diagnostics,
            "adoption_eligible": False,
        },
    )


# Verify current inference against the exact numeric head and immutable row hashes.
def _admit_close(observation, observed_at):
    receipt, identity = observation.receipt, observation.receipt["identity"]
    observed = reference._as_of(observed_at)
    _, opening = _close_window(observation.dates[-1], observed)
    _close_window(observation.dates[-1], identity["observed_at"])
    fit_date, _ = _month_session(identity["model_fit_date"])
    if (
        receipt["identity_sha256"] != base._json_hash(identity)
        or identity["policy"] != "forward-holding-close/1-shadow"
        or identity["symbols"] != list(observation.symbols)
        or identity["model_training_policy"] != feature.HELD_POLICY
        or identity["freeze"] != str(reference.FREEZE)
        or observation.dates[-1].astype("datetime64[M]")
        != fit_date.astype("datetime64[M]")
        or identity["expires_at"] != opening.isoformat()
        or receipt["adoption_eligible"] is not False
        or not reference._as_of(identity["data_as_of"])
        <= reference._as_of(identity["observed_at"])
        <= reference._as_of(identity["published_at"])
        <= observed
        or reference._as_of(identity["model_published_at"])
        > reference._as_of(identity["observed_at"])
    ):
        raise ValueError("Current causal close publication required")
    shape = (len(observation.symbols),)
    if (
        observation.features.shape != (*shape, 13)
        or observation.prices.shape != shape
        or observation.forecasts.shape != shape
        or observation.support.shape != shape
        or observation.support.dtype.kind != "b"
        or observation.history_prices.shape != (len(observation.dates), *shape)
        or observation.history_grades.shape != observation.history_prices.shape
    ):
        raise ValueError("Aligned original close inference required")
    for name in (
        "dates",
        "features",
        "prices",
        "forecasts",
        "support",
        "history_prices",
        "history_grades",
    ):
        if (
            reference._hash(getattr(observation, name))
            != identity["array_sha256"][name]
        ):
            raise ValueError("Original close row bytes mismatch: " + name)
    if (observation.head is None) != (identity["model"] is None) or (
        observation.head is not None
        and direct.numeric_identity(observation.head) != identity["model"]
    ):
        raise ValueError("Original monthly numeric head required")
    expected, counts = direct.predict(
        observation.head, observation.features[None], observation.support[None]
    )
    if (
        not np.array_equal(expected[0], observation.forecasts, equal_nan=True)
        or counts != receipt["prediction_counts"]
    ):
        raise ValueError("Published forecasts differ from original numeric inference")
    return observation


# Commit current numeric rows once with the actual post-serialization write clock.
def write_close(output, observation, *, clock=None):
    _admit_close(observation, observation.receipt["identity"]["published_at"])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    path = output / "close.npz"
    np.savez_compressed(
        path,
        symbols=np.asarray(observation.symbols),
        **{
            name: getattr(observation, name)
            for name in (
                "dates",
                "features",
                "prices",
                "forecasts",
                "support",
                "history_prices",
                "history_grades",
            )
        },
    )
    receipt = deepcopy(observation.receipt)
    published = reference._as_of(clock() if clock else datetime.now(exchange.NEW_YORK))
    receipt["identity"]["published_at"] = published.isoformat()
    receipt["identity_sha256"] = base._json_hash(receipt["identity"])
    _admit_close(
        CloseObservation(
            observation.dates,
            observation.symbols,
            observation.features,
            observation.prices,
            observation.forecasts,
            observation.support,
            observation.history_prices,
            observation.history_grades,
            observation.head,
            receipt,
        ),
        published,
    )
    receipt["arrays_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    encoded = json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False).encode()
    (output / "close.json").write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


# Reopen hash-linked current rows only with their original dated numeric model.
def load_close(output, model_directory, *, receipt_sha256, observed_at):
    output = Path(output)
    raw = (output / "close.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt_sha256:
        raise ValueError("Original close receipt bytes mismatch")
    receipt = json.loads(raw)
    path = output / "close.npz"
    if hashlib.sha256(path.read_bytes()).hexdigest() != receipt["arrays_sha256"]:
        raise ValueError("Original close array bytes mismatch")
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != {
            "dates",
            "symbols",
            "features",
            "prices",
            "forecasts",
            "support",
            "history_prices",
            "history_grades",
        }:
            raise ValueError("Exact close observation fields required")
        arrays = {name: archive[name] for name in archive.files}
    head, model = load_publication(
        model_directory,
        receipt_sha256=receipt["identity"]["model_publication_sha256"],
        observed_at=observed_at,
        decision_session=str(arrays["dates"][-1]),
    )
    if model["identity"]["published_at"] != receipt["identity"]["model_published_at"]:
        raise ValueError("Original model publication clock required")
    observation = CloseObservation(
        arrays["dates"],
        tuple(arrays["symbols"]),
        arrays["features"],
        arrays["prices"],
        arrays["forecasts"],
        arrays["support"],
        arrays["history_prices"],
        arrays["history_grades"],
        head,
        receipt,
    )
    _admit_close(observation, observed_at)
    for value in arrays.values():
        value.flags.writeable = False
    return observation


# Use the original OOS bank with current means and the same stock-volatility transform.
class ForwardVolatilityHoldingReader:
    # Copy old evidence and current inference without extending frozen forecasts.
    def __init__(self, original, observation):
        if not isinstance(original, errors.VolatilityHoldingReader) or not isinstance(
            observation, CloseObservation
        ):
            raise ValueError("Authenticated original reader and current close required")
        if (
            reference._hash(original.features) != original.identity["features_sha256"]
            or reference._hash(original.volatility)
            != original.identity["volatility_sha256"]
        ) or any(
            reference._hash(getattr(original, name))
            != reference._hash(getattr(original._reader, name))
            for name in ("dates", "forecasts", "labels", "endpoints", "support")
        ):
            raise ValueError("Original reader numeric binding differs")
        current = deepcopy(observation)
        _admit_close(current, current.receipt["identity"]["published_at"])
        if (
            tuple(original.symbols) != current.symbols
            or current.dates[0] != original.dates[0]
        ):
            raise ValueError("Original stock order and feature history anchor required")
        common = min(len(original.dates), len(current.dates))
        if not np.array_equal(original.dates[:common], current.dates[:common]):
            raise ValueError("Original and current complete calendars required")
        self.current = current
        self.dates, self.symbols = current.dates, current.symbols
        for name in (
            "dates",
            "features",
            "prices",
            "forecasts",
            "support",
            "history_prices",
            "history_grades",
        ):
            getattr(current, name).flags.writeable = False
        self._bank = {
            name: getattr(original, name).copy()
            for name in (
                "dates",
                "forecasts",
                "labels",
                "endpoints",
                "support",
                "volatility",
                "features",
            )
        }
        for value in self._bank.values():
            value.flags.writeable = False
        self.identity = {
            "policy": "forward-joint-holding-volatility/1-shadow",
            "horizon": "next_open_to_following_open_arithmetic_return",
            "original_reader_identity_sha256": base._json_hash(original.identity),
            "close_receipt_sha256": base._json_hash(current.receipt),
            "confidence_guarantee": False,
            "adoption_eligible": False,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "volatility_transform_sha256": hashlib.sha256(
                Path(errors.__file__).read_bytes()
            ).hexdigest(),
        }

    # Refuse an expired cached observation at the actual funded decision instant.
    def validate_clock(self, instant):
        _admit_close(self.current, instant)

    # Bind funded planning to the same grades, prices and complete feature prefix.
    def validate_report(self, report):
        prefix = self.current.receipt["identity"]["prefix_sha256"]
        if reference._hash(np.asarray(report.panel.dates)) != prefix["dates"]:
            raise ValueError(
                "Funded report differs from published current close: dates"
            )
        metadata = getattr(report, "provenance", {})
        converted = (
            metadata.get("price_basis")
            == "entire_prefix_in_current_session_raw_share_dollars"
        )
        if (
            converted
            and metadata.get("raw_source_arrays", {}).get("adj_close")
            != prefix["prices"]
        ):
            raise ValueError(
                "Funded report differs from published current close: source prices"
            )
        for column, name in enumerate(report.panel.tickers):
            if name not in self.symbols:
                raise ValueError("Funded report has an uncovered stock")
            source = self.symbols.index(name)
            factor = metadata.get("split_factors", {}).get(name) if converted else 1.0
            if (
                not isinstance(factor, (int, float, np.number))
                or isinstance(factor, (bool, np.bool_))
                or not np.isfinite(factor)
                or factor <= 0
            ):
                raise ValueError("Explicit mechanical report share conversion required")
            if not np.array_equal(
                report.panel.adj_close[:, column],
                self.current.history_prices[:, source] * factor,
                equal_nan=True,
            ):
                raise ValueError(
                    "Funded report differs from published current close: prices"
                )
            if name not in ("SPY", "QQQ") and not np.array_equal(
                report.graded.grades[:, column], self.current.history_grades[:, source]
            ):
                raise ValueError(
                    "Funded report differs from published current close: grades"
                )

    # Select mature simultaneous OOS errors; no current outcome can enter the bank.
    def distribution(self, day, symbols):
        if (
            isinstance(day, (bool, np.bool_))
            or not isinstance(day, (int, np.integer))
            or day != len(self.dates) - 1
            or not isinstance(symbols, (list, tuple))
            or not symbols
            or any(not isinstance(s, str) or not s for s in symbols)
            or len(set(symbols)) != len(symbols)
        ):
            raise ValueError("Current close index and unique required stocks required")
        names = tuple(symbols)
        receipt = {
            **deepcopy(self.identity),
            "decision_date": str(self.dates[-1]),
            "symbols": list(names),
            "status": "unavailable",
        }
        if any(name not in self.symbols or name in ("SPY", "QQQ") for name in names):
            receipt["reason"] = "uncovered_required_stock"
            return feature.HoldingScenarios(None, None, names, receipt)
        indices = np.asarray([self.symbols.index(name) for name in names])
        month_date, _ = _month_session(
            self.current.receipt["identity"]["model_fit_date"]
        )
        first = int(np.searchsorted(self.dates, month_date))
        cutoff = min(month_date, reference.FREEZE)
        candidates = self.dates[max(0, first - reference.MAX_DAYS) : first]
        bank = self._bank
        positions = np.searchsorted(bank["dates"], candidates)
        matched = positions < len(bank["dates"])
        matched[matched] &= bank["dates"][positions[matched]] == candidates[matched]
        available = positions[matched]
        mature = available[
            ~np.isnat(bank["endpoints"][available])
            & (bank["endpoints"][available] < cutoff)
        ]
        mask = (
            bank["support"][np.ix_(mature, indices)]
            & np.isfinite(bank["forecasts"][np.ix_(mature, indices)])
            & np.isfinite(bank["labels"][np.ix_(mature, indices)])
        )
        chosen = mature[mask.all(axis=1)]
        receipt.update(
            fit_date=str(month_date),
            label_end_before=str(cutoff),
            candidate_dates=len(candidates),
            missing_bank_dates=int((~matched).sum()),
            mature_dates=len(mature),
            joint_dates=len(chosen),
            unavailable_joint_dates=len(mature) - len(chosen),
            decision_indices=chosen.tolist(),
            maximum_endpoint=str(bank["endpoints"][chosen].max())
            if len(chosen)
            else None,
        )
        if (
            not self.current.support[indices].all()
            or not np.isfinite(self.current.forecasts[indices]).all()
        ):
            receipt["reason"] = "missing_current_forecast"
        elif len(chosen) < 252:
            receipt["reason"] = "insufficient_joint_history"
        else:
            past, labels, volatility = (
                bank[key][np.ix_(chosen, indices)]
                for key in ("forecasts", "labels", "volatility")
            )
            try:
                scenarios = errors.scale_holding_volatility(
                    self.current.forecasts[indices],
                    past,
                    labels,
                    self.current.features[indices, 4],
                    volatility,
                )
            except ValueError as exc:
                receipt.update(
                    reason="unsupported_volatility_arithmetic",
                    arithmetic_reason=str(exc),
                )
            else:
                probabilities = np.full(len(chosen), 1 / len(chosen))
                probabilities.flags.writeable = False
                receipt.update(
                    status="available",
                    scenarios_sha256=reference._hash(scenarios),
                    probabilities_sha256=reference._hash(probabilities),
                    bank_forecasts_sha256=reference._hash(past),
                    bank_labels_sha256=reference._hash(labels),
                    bank_volatility_sha256=reference._hash(volatility),
                )
                return feature.HoldingScenarios(
                    scenarios, probabilities, names, receipt
                )
        return feature.HoldingScenarios(None, None, names, receipt)
