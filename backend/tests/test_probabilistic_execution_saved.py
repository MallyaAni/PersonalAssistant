"""Synthetic restoration accepts original samples and refuses corrupted evidence."""

from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from backend.market import calendar
from backend.market import probabilistic_execution as model
from backend.market import probabilistic_execution_saved as saved
from backend.market.daily_arithmetic_bridge import _hash


# Produce synthetic original receipts once without any estimator or account fitting.
@pytest.fixture(scope="module")
def original():
    _, sessions = calendar.reviewed_sessions()
    dates = np.arange(np.datetime64("2023-01-03"), np.datetime64("2026-10-01"))
    dates = dates[np.is_busday(dates, busdaycal=sessions)]
    shape = (len(dates), 2, 3)
    means = np.zeros(shape, dtype=np.float32)
    second = np.full(shape, 0.01, dtype=np.float32)
    labels = np.broadcast_to(np.array([-0.1, 0.1])[None, :, None], shape).copy()
    valid = np.ones(shape, dtype=bool)
    missing = np.flatnonzero(dates == np.datetime64("2026-09-30"))[0]
    means[missing, 1, 0] = np.nan
    inputs = dict(
        dates=dates,
        symbols=("AAOI", "SPY", "QQQ"),
        means=means,
        second_moments=second,
        labels=labels,
        valid=valid,
        outcome_end_dates=dates.copy(),
        data_as_of="2026-09-30T20:00:00+00:00",
        horizon=model.HORIZON,
    )
    result = model.calibrate(**inputs)
    return inputs, result


# Restore a fresh isolated fixture using only saved arrays and sample receipts.
def restore(original, **changes):
    inputs, result = original
    args = {
        key: value.copy() if isinstance(value, np.ndarray) else value
        for key, value in inputs.items()
    }
    args.update(
        manifest=deepcopy(result.manifest),
        saved_probability=result.probability_positive.copy(),
        saved_quantiles=result.quantiles.copy(),
    )
    args.update(changes)
    return saved.load_saved(**args)


# Prove restored distributions exactly match the original without recalibration.
def test_valid_restoration_and_original_sample_identity(original, monkeypatch):
    inputs, result = original

    # Make accidental regeneration fail before it could manufacture another sample.
    def forbid(*args, **kwargs):
        raise AssertionError("Restoration must not call calibrate")

    monkeypatch.setattr(model, "calibrate", forbid)
    restored = restore(original)
    for month, stocks in result.samples.items():
        if "AAOI" not in stocks:
            continue
        day = int(
            np.flatnonzero(
                inputs["dates"].astype("datetime64[M]") == np.datetime64(month, "M")
            )[0]
        )
        actual = restored.provider(day, 0, 0)
        expected = result.distribution(day, 0, 0)
        assert actual.mean == expected.mean
        assert actual.scale == expected.scale
        np.testing.assert_array_equal(actual.residuals, expected.residuals)
        np.testing.assert_array_equal(actual.weights, expected.weights)
    np.testing.assert_array_equal(restored.score_mask, result.score_mask)
    assert restored.verification["no_refit_or_recalibration"] is True
    assert restored.verification["sample_cache"] == "one_month_only"
    assert restored.provider(len(inputs["dates"]) - 1, 1, 0) is None
    assert restored.provider(len(inputs["dates"]) - 1, 0, 1) is None


# Every original sample array hash remains mandatory, including unavailable months.
@pytest.mark.parametrize(
    "key", ["day_indices", "clock_indices", "residuals", "weights"]
)
def test_corrupt_original_sample_hash_refused(original, key):
    manifest = deepcopy(original[1].manifest)
    manifest["months"][-1]["stocks"][0]["hashes"][key] = "0" * 64
    with pytest.raises(ValueError, match="sample hash"):
        restore(original, manifest=manifest)


# Reject a changed sample calendar, endpoint or cutoff before supplying any decision.
@pytest.mark.parametrize(
    "key",
    ["month", "cutoff_exclusive", "maximum_endpoint", "stock_order", "training_rows"],
)
def test_corrupt_month_or_maturity_refused(original, key):
    manifest = deepcopy(original[1].manifest)
    row = manifest["months"][-1]
    if key == "month":
        row[key] = "2026-08"
    elif key == "cutoff_exclusive":
        row[key] = "2026-09-01"
    elif key == "stock_order":
        row["stocks"].reverse()
    elif key == "training_rows":
        row["stocks"][0][key] += 1
    else:
        row["stocks"][0][key] = "2026-08-17"
    with pytest.raises(ValueError, match="receipt|maturity|sample"):
        restore(original, manifest=manifest)


# Bind original support and quantile bytes rather than silently accepting new forecasts.
@pytest.mark.parametrize(
    "key", ["probability_positive", "quantiles", "score_mask", "causal_mask"]
)
def test_saved_output_hash_corruption_refused(original, key):
    manifest = deepcopy(original[1].manifest)
    manifest["arrays"][key] = "0" * 64
    with pytest.raises(ValueError, match="array hash"):
        restore(original, manifest=manifest)


# Refuse numerical equality with a changed archived dtype or shape.
@pytest.mark.parametrize("kind", ["dtype", "shape"])
def test_saved_representation_refused(original, kind):
    probability = original[1].probability_positive
    probability = (
        probability.astype(np.float32) if kind == "dtype" else probability[:, :1]
    )
    with pytest.raises(ValueError, match="float64"):
        restore(original, saved_probability=probability)


# Future labels cannot select a distribution after their typed input identity is bound.
def test_future_labels_do_not_change_restored_decision(original):
    inputs, result = original
    labels = inputs["labels"].copy()
    labels[inputs["dates"] >= model.FREEZE] = np.nan
    manifest = deepcopy(result.manifest)
    # The pure relationship fixture updates its supplied array identity; real callers
    # separately authenticate original immutable artifact bytes before restoration.
    manifest["identity"]["inputs"]["labels"] = _hash(labels)
    changed = restore(original, labels=labels, manifest=manifest)
    ordinary = restore(original)
    day = len(inputs["dates"]) - 1
    before, after = ordinary.provider(day, 0, 0), changed.provider(day, 0, 0)
    assert before.mean == after.mean
    assert before.scale == after.scale
    np.testing.assert_array_equal(before.residuals, after.residuals)
    np.testing.assert_array_equal(before.weights, after.weights)
    assert model.decision(
        before, "buy", 0.2, 10, horizon=model.HORIZON
    ) == model.decision(after, "buy", 0.2, 10, horizon=model.HORIZON)


# Caller mutations cannot overwrite the verified internal grid or frozen sample arrays.
def test_provider_owns_immutable_inputs_and_single_month_cache(original):
    restored = restore(original)
    dates = restored.dates.astype("datetime64[M]")
    for month in ("2026-08", "2026-09", "2026-08"):
        day = int(np.flatnonzero(dates == np.datetime64(month, "M"))[0])
        distribution = restored.provider(day, 0, 0)
        assert restored._cache_month == month
        assert set(restored._cache) == {"AAOI"}
        assert not distribution.residuals.flags.writeable
        assert not distribution.weights.flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        restored.means[-1, 0, 0] = 10


# Refuse forged original input identities and malformed provider indices.
def test_input_identity_and_provider_indices_refused(original):
    labels = original[0]["labels"].copy()
    labels[-1, 0, 0] += 0.1
    with pytest.raises(ValueError, match="identity"):
        restore(original, labels=labels)
    restored = restore(original)
    for indices in ((-1, 0, 0), (0, 2, 0), (0, 0, 3), (True, 0, 0)):
        with pytest.raises(ValueError, match="indices"):
            restored.provider(*indices)


# Require explicit admission before restoring the exact old calendar producer.
def test_archived_calendar_requires_explicit_admission(original, monkeypatch):
    manifest = deepcopy(original[1].manifest)
    manifest["identity"]["sources"]["backend/market/calendar.py"] = (
        "5f36c265d979d13370d0535a135e528198136572bc067efeaaad292433ffe0a9"
    )
    with pytest.raises(ValueError, match="identity differs: sources"):
        restore(original, manifest=manifest)

    # Reject any attempt to regenerate diagnostics during compatibility restoration.
    def forbid(*args, **kwargs):
        raise AssertionError("Saved restoration cannot calibrate")

    monkeypatch.setattr(model, "calibrate", forbid)
    old = restore(original, manifest=manifest, allow_calendar_correction=True)
    current = restore(original)
    day = len(original[0]["dates"]) - 1
    actual, expected = old.provider(day, 0, 0), current.provider(day, 0, 0)
    assert actual.mean == expected.mean
    assert actual.scale == expected.scale
    np.testing.assert_array_equal(actual.residuals, expected.residuals)
    np.testing.assert_array_equal(actual.weights, expected.weights)
    proof = old.verification["source_compatibility"]
    assert proof["original_sources"] == manifest["identity"]["sources"]
    assert proof["consumer_sources"] == original[1].manifest["identity"]["sources"]
    assert proof["calendar_correction_admitted"] is True


# The admitted pair never allows another source, calendar version or input to change.
@pytest.mark.parametrize("changed", ["calendar", "producer", "table", "labels"])
def test_calendar_admission_refuses_other_identity_changes(original, changed):
    manifest = deepcopy(original[1].manifest)
    sources = manifest["identity"]["sources"]
    sources["backend/market/calendar.py"] = (
        "5f36c265d979d13370d0535a135e528198136572bc067efeaaad292433ffe0a9"
    )
    if changed == "labels":
        manifest["identity"]["inputs"]["labels"] = "0" * 64
    elif changed == "calendar":
        sources["backend/market/calendar.py"] = "0" * 64
    else:
        key = (
            "backend/market/probabilistic_execution.py"
            if changed == "producer"
            else str(
                calendar.HISTORICAL_SESSIONS_PATH.relative_to(
                    Path(__file__).resolve().parents[2]
                )
            )
        )
        sources[key] = "0" * 64
    with pytest.raises(ValueError, match="identity differs"):
        restore(original, manifest=manifest, allow_calendar_correction=True)


# A future consumer calendar or truthy non-boolean flag cannot reuse this exception.
@pytest.mark.parametrize("changed", ["consumer", "flag"])
def test_calendar_admission_refuses_unregistered_consumer(original, changed):
    consumer = deepcopy(original[1].manifest["identity"]["sources"])
    archived = dict(consumer)
    archived["backend/market/calendar.py"] = saved.ARCHIVED_CALENDAR_SHA
    if changed == "consumer":
        consumer["backend/market/calendar.py"] = "1" * 64
    with pytest.raises(ValueError, match="identity differs: sources"):
        saved._source_compatibility(
            archived, consumer, 1 if changed == "flag" else True
        )
