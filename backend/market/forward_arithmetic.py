"""Dated monthly continuation of the fixed held-B arithmetic learner.

The caller authenticates original inputs and supplies the actual publication
clock. This publishes models, not orders or current forecasts. The August freeze,
monthly window, features and estimator remain unchanged. Live adoption is absent.
"""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from threadpoolctl import threadpool_limits

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_daily_arithmetic as direct
from backend.market import direct_feature_arithmetic as feature
from backend.market import learned_entry_models as base

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
def _admit(publication, observed_at):
    receipt, identity = publication.receipt, publication.receipt["identity"]
    observed = reference._as_of(observed_at)
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
        or np.datetime64(observed.date(), "M") != fit_date.astype("datetime64[M]")
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
def load_publication(output, *, receipt_sha256, observed_at):
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
    return _admit(MonthlyPublication(bundle, receipt), observed_at), receipt
