"""Dated numeric timing heads for the private forward execution path.

This preserves the registered boosting mean/risk fits and their conservative
purge. Original input authentication belongs to the caller. Model publication
does not certify probabilities, quote latency, broker fills or adoption.
"""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import sklearn
from threadpoolctl import threadpool_limits

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_daily_arithmetic as numeric
from backend.market import forward_arithmetic as publication_source
from backend.market import learned_entry_data as features
from backend.market import learned_entry_models as original
from backend.market import learned_intraday_moments as moments
from backend.market.daily_arithmetic_bridge import _as_of, _hash
from backend.market.forward_arithmetic import _month_session

POLICY = "forward-execution-moments/1-shadow"
HEADS = ("boosting_mean", "risk")
PROTOCOL = "docs/research/joint-probability-timing-plan-2026-10-05.md"


# Keep numeric arrays separate from their actual dated publication evidence.
@dataclass(frozen=True)
class Publication:
    bundles: dict | None
    receipt: dict


# Score the original twenty-one feature columns without loading executable objects.
@dataclass(frozen=True)
class NumericHead:
    columns: np.ndarray
    baseline: np.ndarray
    trees: tuple

    # Follow the fitted thresholds and missing routes, preserving original sums.
    def predict(self, values):
        values = np.asarray(values, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != 21 or np.isinf(values).any():
            raise ValueError("Original twenty-one finite-or-missing features required")
        result = np.full(len(values), float(self.baseline[0, 0]))
        for nodes, _, _ in self.trees:
            positions = np.zeros(len(values), dtype=np.int64)
            active = ~nodes["is_leaf"][positions].astype(bool)
            while active.any():
                rows = np.flatnonzero(active)
                current = nodes[positions[rows]]
                value = values[rows, current["feature_idx"]]
                left = np.where(
                    np.isnan(value),
                    current["missing_go_to_left"].astype(bool),
                    value <= current["num_threshold"],
                )
                positions[rows] = np.where(left, current["left"], current["right"])
                active = ~nodes["is_leaf"][positions].astype(bool)
            result += nodes["value"][positions]
        return result


# Refuse executable, malformed or cyclic payloads before numerical inference.
def _head(bundle, expected=None):
    fields = {"baseline"} | {
        prefix + str(stage)
        for prefix in ("nodes_", "raw_categories_", "binned_categories_")
        for stage in range(64)
    }
    if set(bundle) != fields:
        raise ValueError("Exact registered timing tree arrays required")
    copied = {name: np.asarray(value).copy() for name, value in bundle.items()}
    baseline = copied["baseline"]
    if (
        baseline.shape != (1, 1)
        or baseline.dtype != np.dtype("float64")
        or not np.isfinite(baseline).all()
    ):
        raise ValueError("Finite original timing baseline required")
    trees = tuple(
        tuple(
            copied[prefix + str(stage)]
            for prefix in ("nodes_", "raw_categories_", "binned_categories_")
        )
        for stage in range(64)
    )
    for nodes, raw, binned in trees:
        numeric._numeric_tree(nodes, raw, binned, 21)
    columns = np.arange(21, dtype=np.int64)
    head = NumericHead(columns, baseline, trees)
    if expected is not None and numeric.numeric_identity(head) != expected:
        raise ValueError("Original fitted timing identity differs")
    for array in (*copied.values(), columns):
        array.flags.writeable = False
    return head


# Export only the trusted in-memory registered estimator into non-executable arrays.
def _snapshot(estimator):
    if (
        estimator.n_features_in_ != 21
        or estimator.n_iter_ != 64
        or len(estimator._predictors) != 64
        or any(
            estimator.get_params()[name] != value
            for name, value in original.MODEL_CONFIG["boosting"].items()
        )
    ):
        raise ValueError("Registered fixed timing estimator required")
    bundle = {"baseline": estimator._baseline_prediction.copy()}
    for stage, trees in enumerate(estimator._predictors):
        if len(trees) != 1:
            raise ValueError("Single-output timing regression required")
        tree = trees[0]
        for prefix, values in (
            ("nodes_", tree.nodes),
            ("raw_categories_", tree.raw_left_cat_bitsets),
            ("binned_categories_", tree.binned_left_cat_bitsets),
        ):
            bundle[prefix + str(stage)] = values.copy()
    return bundle, numeric.numeric_identity(_head(bundle))


# Bind the exact original algorithms without pretending an artifact proves provenance.
def _sources():
    root = Path(__file__).resolve().parents[2]
    paths = (
        Path(__file__),
        Path(original.__file__),
        Path(moments.__file__),
        Path(features.__file__),
        Path(numeric.__file__),
        Path(exchange.__file__),
        Path(reference.__file__),
        Path(publication_source.__file__),
        exchange.HISTORICAL_SESSIONS_PATH,
        exchange.HOLIDAYS_PATH,
        exchange.EARLY_CLOSES_PATH,
        root / PROTOCOL,
    )
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


# Fit the unchanged two boosting heads on only original mature duration-matched rows.
def fit_month(
    dataset, *, fit_session, data_as_of, published_at, source_revision, input_identity
):
    x, _, valid, dates, names = original._validate(dataset)
    day, calendar = _month_session(fit_session)
    supplied, requested = _as_of(data_as_of), _as_of(published_at)
    if (
        names != list(features.FEATURE_NAMES)
        or x.shape[-1] != 21
        or supplied > requested
        or requested.date() < day.astype(object)
        or np.datetime64(requested.date(), "M") != day.astype("datetime64[M]")
        or not isinstance(source_revision, str)
        or len(source_revision) != 40
        or any(c not in "0123456789abcdef" for c in source_revision)
        or not isinstance(input_identity, dict)
        or not input_identity
        or any(
            not isinstance(k, str)
            or not k
            or not isinstance(v, str)
            or len(v) != 64
            or any(c not in "0123456789abcdef" for c in v)
            for k, v in input_identity.items()
        )
    ):
        raise ValueError(
            "Original features, dated publication and input hashes required"
        )
    years, _ = exchange.reviewed_sessions()
    complete = np.arange(dates[0], dates[-1] + np.timedelta64(1, "D"))
    if (
        any(value.astype(object).year not in years for value in dates)
        or not np.array_equal(
            dates, complete[np.is_busday(complete, busdaycal=calendar)]
        )
        or datetime.combine(
            dates[-1].astype(object),
            exchange.session_close(dates[-1].astype(object)),
            exchange.NEW_YORK,
        )
        > supplied
    ):
        raise ValueError("Complete completed-session timing inputs required")
    first = int(np.searchsorted(dates, day))
    training_dates = dates
    if first == len(dates):
        if day != np.busday_offset(dates[-1], 1, busdaycal=calendar):
            raise ValueError("Missing exchange sessions before timing fit")
        training_dates = np.append(dates, day)
    elif dates[first] != day:
        raise ValueError("Missing first monthly timing session")
    elapsed = moments.waiting_elapsed_minutes(dates)
    mean, second = moments.targets(dataset, elapsed)
    rows, clocks, stocks, cutoff = moments.training_rows(
        training_dates,
        valid,
        mean,
        elapsed,
        first,
        original._training_symbols(dataset, x.shape[2]),
    )
    distinct = np.unique(rows)
    training = {
        "fit_date": str(day),
        "label_end_before": str(cutoff),
        "training_days": len(distinct),
        "training_rows": len(rows),
        "training_clocks": sorted(np.unique(clocks).tolist()),
        "maximum_label_end": str(training_dates[rows.max() + original.LABEL_SESSIONS])
        if len(rows)
        else None,
        "selected_sha256": {
            name: _hash(value)
            for name, value in (
                ("days", rows),
                ("clocks", clocks),
                ("stocks", stocks),
                ("features", x[rows, clocks, stocks]),
                ("mean", mean[rows, clocks, stocks]),
                ("second", second[rows, clocks, stocks]),
            )
        },
    }
    identity = {
        "policy": POLICY,
        "source_revision": source_revision,
        "input_identity": deepcopy(input_identity),
        "sources": _sources(),
        "data_as_of": supplied.isoformat(),
        "fit_requested_at": requested.isoformat(),
        "published_at": requested.isoformat(),
        "feature_names": names,
        "config": dict(original.MODEL_CONFIG["boosting"]),
        "runtime": {"numpy": np.__version__, "sklearn": sklearn.__version__},
        "minimum_days": original.MIN_TRAIN_DAYS,
        "maximum_days": original.MAX_TRAIN_DAYS,
        "freeze": str(original.HOLDOUT_START),
        "target_schema": moments.TARGET_SCHEMA,
    }
    bundles, models = None, None
    if len(distinct) >= original.MIN_TRAIN_DAYS:
        bundles, models = {}, {}
        with threadpool_limits(limits=2):
            for name, target in zip(HEADS, (mean, second), strict=True):
                estimator = original._estimator("boosting")
                estimator.fit(
                    x[rows, clocks, stocks].astype(np.float64),
                    target[rows, clocks, stocks],
                )
                bundles[name], models[name] = _snapshot(estimator)
    receipt = {
        "identity": identity,
        "identity_sha256": original._json_hash(identity),
        "training": training,
        "models": models,
        "status": "fitted" if bundles is not None else "insufficient_mature_history",
        "adoption_eligible": False,
    }
    return Publication(bundles, receipt)


# Refuse stale, backdated or mismatched publications before numerical inference.
def _admit(publication, observed_at):
    receipt, identity = publication.receipt, publication.receipt["identity"]
    observed = _as_of(observed_at)
    day, _ = _month_session(receipt["training"]["fit_date"])
    published = _as_of(identity["published_at"])
    if (
        receipt["identity_sha256"] != original._json_hash(identity)
        or identity["policy"] != POLICY
        or receipt["adoption_eligible"] is not False
        or identity["sources"] != _sources()
        or identity["config"] != original.MODEL_CONFIG["boosting"]
        or identity["feature_names"] != list(features.FEATURE_NAMES)
        or identity["target_schema"] != moments.TARGET_SCHEMA
        or identity["minimum_days"] != original.MIN_TRAIN_DAYS
        or identity["maximum_days"] != original.MAX_TRAIN_DAYS
        or identity["freeze"] != str(original.HOLDOUT_START)
        or _as_of(identity["data_as_of"]) > _as_of(identity["fit_requested_at"])
        or _as_of(identity["fit_requested_at"]) > published
        or published > observed
        or published.date() < day.astype(object)
        or np.datetime64(published.date(), "M") != day.astype("datetime64[M]")
        or np.datetime64(observed.date(), "M") != day.astype("datetime64[M]")
        or receipt["training"]["label_end_before"]
        != str(min(day, original.HOLDOUT_START))
    ):
        raise ValueError("Current causal timing publication required")
    if receipt["status"] != "fitted":
        if (
            receipt["status"] != "insufficient_mature_history"
            or publication.bundles is not None
            or receipt["models"] is not None
        ):
            raise ValueError("Unavailable timing publication cannot contain models")
        return None
    training = receipt["training"]
    if (
        training["training_days"] < original.MIN_TRAIN_DAYS
        or not training["training_clocks"]
        or not set(training["training_clocks"]).issubset((0, 3, 9, 19))
        or training["maximum_label_end"] is None
        or np.datetime64(training["maximum_label_end"], "D")
        >= min(day, original.HOLDOUT_START)
        or set(publication.bundles) != set(HEADS)
        or set(receipt["models"]) != set(HEADS)
    ):
        raise ValueError("Original mature timing fits required")
    return {
        name: _head(publication.bundles[name], receipt["models"][name])
        for name in HEADS
    }


# Publish numeric bytes once, recording the actual clock after their serialization.
def write_publication(output, publication, *, clock=None):
    receipt = deepcopy(publication.receipt)
    _admit(publication, receipt["identity"]["published_at"])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    receipt["model_file"] = None
    if publication.bundles is not None:
        target = output / "models.npz"
        np.savez_compressed(
            target,
            **{
                head + "__" + name: value
                for head, bundle in publication.bundles.items()
                for name, value in bundle.items()
            },
        )
        receipt["model_file"] = {
            "name": target.name,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
    published = _as_of(clock() if clock else datetime.now(exchange.NEW_YORK))
    if published < _as_of(receipt["identity"]["fit_requested_at"]):
        raise ValueError("Timing publication cannot precede its actual fit request")
    receipt["identity"]["published_at"] = published.isoformat()
    receipt["identity_sha256"] = original._json_hash(receipt["identity"])
    _admit(Publication(publication.bundles, receipt), published)
    raw = json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False).encode()
    (output / "publication.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


# Restore only hash-authenticated numeric arrays with no estimator deserialization.
def load_publication(output, *, receipt_sha256, observed_at):
    output = Path(output)
    raw = (output / "publication.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt_sha256:
        raise ValueError("Original timing publication bytes differ")
    receipt = json.loads(raw)
    bundles = None
    record = receipt["model_file"]
    if record is not None:
        if record["name"] != "models.npz":
            raise ValueError("Canonical numeric timing filename required")
        target = output / record["name"]
        if hashlib.sha256(target.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Original timing model bytes differ")
        with np.load(target, allow_pickle=False) as saved:
            bundles = {head: {} for head in HEADS}
            for name in saved.files:
                head, separator, key = name.partition("__")
                if head not in HEADS or separator != "__":
                    raise ValueError("Registered numeric timing head names required")
                bundles[head][key] = saved[name]
    return _admit(Publication(bundles, receipt), observed_at), receipt


# Retain the original float32 predictions and missing/invalid moments without clipping.
def predict_moments(heads, values):
    rows = np.asarray(values)
    if rows.ndim != 2 or rows.shape[1] != 21 or np.isinf(rows).any():
        raise ValueError("Original twenty-one finite-or-missing features required")
    if heads is None:
        return np.full((2, len(rows)), np.nan, dtype=np.float32)
    if set(heads) != set(HEADS):
        raise ValueError("Both original timing moment heads required")
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.asarray(
            [heads[name].predict(rows) for name in HEADS], dtype=np.float32
        )
    result[~np.isfinite(result)] = np.nan
    return result
