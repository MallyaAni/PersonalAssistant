"""Supplied OOS errors prove causal stock-specific monthly resolution bands."""

import hashlib
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as bridge_module
from backend.market import direct_daily_arithmetic as direct
from backend.market import direct_error_band as bands
from backend.market import learned_entry_models as base


# Supply genuine causal bridge receipts and a caller-authenticated numeric archive.
def fixture(count=660, start="2023-01-03"):
    _, actual = exchange.reviewed_sessions()
    first = np.datetime64(start)
    candidates = np.arange(first, first + np.timedelta64(count * 3, "D"))
    dates = candidates[np.is_busday(candidates, busdaycal=actual)][:count]
    names = ("AAA", "BBB", "SPY", "QQQ")
    opens = np.full((count, 4), 100.0)
    for day in range(count - 2):
        opens[day + 2] = opens[day + 1] * (1 + np.array([0.002, 0.004, 0.001, 0.001]))
    parent = bridge_module.walk_forward(
        dates,
        names,
        opens,
        np.full(opens.shape, 2),
        np.ones(opens.shape, bool),
        np.full(opens.shape, 0.02),
        dates,
        data_as_of=datetime.combine(
            dates[-1].astype(object),
            exchange.session_close(dates[-1].astype(object)),
            exchange.NEW_YORK,
        ),
    )
    forecasts = np.full(opens.shape, np.nan)
    months = dates.astype("datetime64[M]")
    for receipt in parent.manifest["months"]:
        if receipt["status"] == "fitted":
            scored = months == np.datetime64(receipt["month"], "M")
            forecasts[scored, 0] = 0.001
            forecasts[scored, 1] = -0.002
    return dates, names, forecasts, manifest(dates, names, forecasts, parent), parent


# Authenticate supplied synthetic forecast bytes exactly as the public archive does.
def manifest(dates, names, forecasts, parent):
    identity = {
        "policy": direct.POLICY,
        "symbols": list(names),
        "target": parent.manifest["target"],
        "config": dict(base.MODEL_CONFIG["boosting"]),
        "minimum_days": bridge_module.MIN_DAYS,
        "label_end": 2,
        "holdout_end_before": str(bridge_module.FREEZE),
        "maximum_days": bridge_module.MAX_DAYS,
        "bridge_manifest_sha256": base._json_hash(parent.manifest),
        "dates_sha256": bridge_module._hash(dates),
        "labels_sha256": bridge_module._hash(parent.labels),
        "label_end_dates_sha256": bridge_module._hash(parent.label_end_dates),
        "score_mask_sha256": bridge_module._hash(parent.score_mask),
        "source_sha256": {
            str(
                path.relative_to(Path(direct.__file__).resolve().parents[2])
            ): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                Path(direct.__file__).resolve(),
                Path(base.__file__).resolve(),
                Path(bridge_module.__file__).resolve(),
                Path(direct.__file__).resolve().parents[2] / direct.PROTOCOL,
            )
        },
    }
    months = dates.astype("datetime64[M]")
    receipts = deepcopy(parent.manifest["months"])
    for receipt in receipts:
        receipt["prediction_sha256"] = bridge_module._hash(
            forecasts[months == np.datetime64(receipt["month"], "M")]
        )
    return {
        "identity": identity,
        "identity_sha256": base._json_hash(identity),
        "forecasts_sha256": bridge_module._hash(forecasts),
        "score_mask_sha256": bridge_module._hash(parent.score_mask),
        "months": receipts,
    }


# Refresh an intentional synthetic source mutation without weakening hash checks.
def changed_labels(parent, labels):
    receipt = deepcopy(parent.manifest)
    receipt["label_sha256"] = bridge_module._hash(labels)
    return replace(parent, labels=labels, manifest=receipt)


# Find one named stock's receipt in the final month for readable assertions.
def stock_receipt(result, name="AAA", month=-1):
    return next(
        row
        for row in result.manifest["months"][month]["stocks"]
        if row["symbol"] == name
    )


# Constant stock errors yield distinct biases without fictitious sampling precision.
def test_constant_stock_errors_zero_standard_error_and_distinct_radii():
    args = fixture()
    result = bands.calibrate(*args)
    a, b = stock_receipt(result), stock_receipt(result, "BBB")
    assert a["radius"] == pytest.approx(0.001, abs=1e-14)
    assert b["radius"] == pytest.approx(0.006, abs=1e-14)
    assert a["standard_error"] < 1e-14
    assert b["standard_error"] < 1e-14
    assert np.isnan(result.radii[:, 2:]).all()
    assert stock_receipt(result, "SPY")["status"] == "excluded_benchmark"
    assert len(result.manifest["months"][-1]["stocks"]) == 4


# Unequal-sized clusters implement the registered sum-based standard error.
def test_cluster_formula_preserves_unequal_month_sizes():
    errors = np.array([0.01, 0.02, 0.03, -0.01, 0.04, 0.05])
    clusters = np.array(
        ["2025-01"] * 2 + ["2025-02"] + ["2025-03"] * 3, dtype="datetime64[M]"
    )
    actual = bands._statistics(errors, clusters)
    bias = errors.mean()
    sums = np.array(
        [(errors[clusters == month] - bias).sum() for month in np.unique(clusters)]
    )
    expected = np.sqrt(3 / 2 * np.sum(sums**2)) / len(errors)
    assert actual["bias"] == pytest.approx(bias)
    np.testing.assert_allclose(actual["cluster_sums"], sums, atol=1e-16)
    assert actual["standard_error"] == pytest.approx(expected)
    assert actual["radius"] == pytest.approx(abs(bias) + expected)


# Neither one observation nor many observations in one month supplies a radius.
@pytest.mark.parametrize(
    ("errors", "clusters", "status"),
    [
        ([0.1], ["2025-01"], "insufficient_observations"),
        ([0.1, 0.2], ["2025-01", "2025-01"], "insufficient_clusters"),
        ([], [], "insufficient_observations"),
    ],
)
def test_observation_and_cluster_minimum_are_distinct(errors, clusters, status):
    result = bands._statistics(
        np.array(errors), np.array(clusters, dtype="datetime64[M]")
    )
    assert result["status"] == status
    assert result["radius"] is None


# Zero observed errors produce exactly zero resolution with two real clusters.
def test_zero_errors_produce_exact_zero_not_unavailable():
    receipt = bands._statistics(
        np.zeros(5), np.array(["2025-01"] * 2 + ["2025-02"] * 3, dtype="datetime64[M]")
    )
    assert receipt["status"] == "available"
    assert receipt["radius"] == receipt["standard_error"] == receipt["bias"] == 0


# A scoring row with an unknown future outcome keeps its previously fitted radius.
def test_future_missing_labels_do_not_remove_causal_opportunities():
    args = fixture()
    result = bands.calibrate(*args)
    assert np.isnan(args[-1].labels[-2:, :2]).all()
    assert args[-1].score_mask[-2:, :2].all()
    assert np.isfinite(result.radii[-2:, :2]).all()
    assert result.manifest["counts"]["opportunities"] == int(args[-1].score_mask.sum())
    assert (
        result.manifest["counts"]["available"]
        + result.manifest["counts"]["unavailable"]
        == result.manifest["counts"]["opportunities"]
    )


# Calibration remains frozen within a month despite different daily forecast errors.
def test_monthly_radius_uses_only_strictly_mature_previous_rows():
    args = fixture()
    result = bands.calibrate(*args)
    dates, _, forecasts, _, parent = args
    for month in result.manifest["months"]:
        scored = dates.astype("datetime64[M]") == np.datetime64(month["month"], "M")
        for index, stock in enumerate(month["stocks"][:2]):
            available = result.radii[scored, index]
            finite = available[np.isfinite(available)]
            assert not len(finite) or np.all(finite == finite[0])
            if stock["observations"]:
                assert np.datetime64(stock["maximum_endpoint"]) < np.datetime64(
                    month["label_end_before"]
                )
                first = month["fit_index"]
                indices = np.arange(max(0, first - 756), first, dtype=np.int64)
                indices = indices[
                    (
                        parent.label_end_dates[indices]
                        < np.datetime64(month["label_end_before"])
                    )
                    & np.isfinite(forecasts[indices, index])
                    & np.isfinite(parent.labels[indices, index])
                ]
                assert stock["row_sha256"]["decision_indices"] == bridge_module._hash(
                    indices
                )


# A later scoring month's labels and forecasts cannot change earlier bands.
def test_future_suffix_mutation_preserves_prefix_calibration():
    dates, names, forecasts, direct_manifest, parent = fixture()
    original = bands.calibrate(dates, names, forecasts, direct_manifest, parent)
    future = dates.astype("datetime64[M]") == dates.astype("datetime64[M]")[-1]
    labels = parent.labels.copy()
    labels[future & np.isfinite(labels[:, 0]), 0] += 0.25
    changed = changed_labels(parent, labels)
    forecasts = forecasts.copy()
    forecasts[future, :2] += 0.05
    updated = manifest(dates, names, forecasts, changed)
    actual = bands.calibrate(dates, names, forecasts, updated, changed)
    np.testing.assert_array_equal(original.radii, actual.radii)
    assert original.manifest["months"] == actual.manifest["months"]


# August and September calibrations cannot see endpoints on or beyond August17.
def test_august_september_frozen_outcomes_are_never_used():
    dates, names, forecasts, direct_manifest, parent = fixture(
        count=700, start="2024-01-02"
    )
    original = bands.calibrate(dates, names, forecasts, direct_manifest, parent)
    labels = parent.labels.copy()
    forbidden = parent.label_end_dates >= np.datetime64("2026-08-17")
    labels[forbidden & np.isfinite(labels[:, 0]), 0] += 0.5
    updated_parent = changed_labels(parent, labels)
    actual = bands.calibrate(
        dates,
        names,
        forecasts,
        manifest(dates, names, forecasts, updated_parent),
        updated_parent,
    )
    holdout = dates >= np.datetime64("2026-08-01")
    np.testing.assert_array_equal(original.radii[holdout], actual.radii[holdout])
    for receipt in actual.manifest["months"]:
        if receipt["month"] >= "2026-08":
            assert receipt["label_end_before"] <= "2026-08-17"
            for stock in receipt["stocks"]:
                if stock["observations"]:
                    assert stock["maximum_endpoint"] < "2026-08-17"


# Original numeric and parent-manifest mutations fail before calibration.
@pytest.mark.parametrize(
    "field", ["forecast", "labels", "identity", "monthly", "score_mask", "dates"]
)
def test_typed_lineage_tampering_is_rejected(field):
    dates, names, forecasts, direct_manifest, parent = fixture()
    if field == "forecast":
        forecasts[-1, 0] += 0.1
    elif field == "labels":
        parent.labels[0, 0] += 0.1
    elif field == "identity":
        direct_manifest["identity"]["target"] = "wrong"
    elif field == "monthly":
        direct_manifest["months"][-1]["fit_date"] = "2026-01-01"
    elif field == "score_mask":
        parent.score_mask[-1, 0] = False
    else:
        dates = dates.astype("datetime64[ns]")
    with pytest.raises(ValueError, match="mismatch|required|disagree"):
        bands.calibrate(dates, names, forecasts, direct_manifest, parent)


# Extreme finite errors remain representable without overflow in squared cluster sums.
def test_scaled_formula_avoids_intermediate_overflow_and_reports_true_overflow():
    months = np.array(
        ["2025-01", "2025-01", "2025-02", "2025-02"], dtype="datetime64[M]"
    )
    huge = bands._statistics(np.array([1e200, 1e200, -1e200, -1e200]), months)
    assert huge["status"] == "available"
    assert huge["radius"] == pytest.approx(1e200)
    invalid = bands._statistics(np.array([np.inf, 1.0, 2.0, 3.0]), months)
    assert invalid["status"] == "nonfinite_residual"
    assert invalid["radius"] is None
    assert invalid["nonfinite_residuals"] == 1


# Repeated calibration is deterministic and never changes caller-owned arrays.
def test_inputs_remain_unchanged_and_receipts_repeat_exactly():
    args = fixture()
    snapshots = [
        value.copy()
        for value in (args[0], args[2], args[-1].labels, args[-1].score_mask)
    ]
    first, second = bands.calibrate(*args), bands.calibrate(*args)
    assert first.manifest == second.manifest
    np.testing.assert_array_equal(first.radii, second.radii)
    for actual, expected in zip(
        (args[0], args[2], args[-1].labels, args[-1].score_mask), snapshots, strict=True
    ):
        np.testing.assert_array_equal(actual, expected)


# A stock with no past forecasts keeps its current opportunities but no error radius.
def test_missing_stock_history_is_not_pooled_or_given_zero():
    dates, names, forecasts, _, parent = fixture()
    months = dates.astype("datetime64[M]")
    forecasts[months < months[-1], 1] = np.nan
    result = bands.calibrate(
        dates, names, forecasts, manifest(dates, names, forecasts, parent), parent
    )
    missing = stock_receipt(result, "BBB")
    assert missing["observations"] == missing["clusters"] == 0
    assert missing["status"] == "insufficient_observations"
    assert np.isnan(result.radii[:, 1]).all()
    assert np.isfinite(result.radii[-1, 0])
    assert parent.score_mask[-1, 1]


# A source digest must be explicit even when the parent JSON itself is self-consistent.
def test_missing_direct_source_identity_is_rejected():
    dates, names, forecasts, receipt, parent = fixture()
    del receipt["identity"]["source_sha256"]
    receipt["identity_sha256"] = base._json_hash(receipt["identity"])
    with pytest.raises(ValueError, match="source hashes required"):
        bands.calibrate(dates, names, forecasts, receipt, parent)
