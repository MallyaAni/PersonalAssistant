"""Actual timing fits, numeric inference and causal publication acceptance."""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import joblib
import numpy as np
import pytest

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as reference
from backend.market import forward_arithmetic as publication_source
from backend.market import forward_execution as forward
from backend.market import learned_entry_data as features
from backend.market import learned_entry_models as original
from backend.market import learned_intraday_moments as moments
from backend.market import probabilistic_execution as probability
from backend.market import probabilistic_execution_saved as saved_source


# Supply a complete session grid with real models and controlled synthetic labels.
def dataset(end="2026-10-02"):
    _, calendar = exchange.reviewed_sessions()
    dates = np.arange(
        "2023-01-03", np.datetime64(end) + np.timedelta64(1, "D"), dtype="datetime64[D]"
    )
    dates = dates[np.is_busday(dates, busdaycal=calendar)]
    rng = np.random.default_rng(721)
    x = rng.uniform(-1, 1, size=(len(dates), 25, 3, 21)).astype(np.float32)
    x[::5, :, 0, 7] = np.nan
    y = np.full((*x.shape[:3], 3), np.nan, dtype=np.float32)
    y[..., 2] = 0.002 * x[..., 0] + rng.normal(0, 0.0004, size=x.shape[:3])
    y[-10:, ..., 2] = np.nan
    valid = np.ones(x.shape[:3], dtype=bool)
    for day, value in enumerate(dates):
        close = exchange.session_close(value.astype(object))
        slots = ((close.hour - 9) * 60 + close.minute - 30) // 15
        valid[day, slots:] = False
    return {
        "X": x,
        "y": y,
        "valid": valid,
        "dates": dates,
        "feature_names": list(features.FEATURE_NAMES),
        "training_symbols": np.array([True, True, False]),
        "provenance": {"fixture": "synthetic"},
    }


# Request the original monthly fit with explicit supplied input and publication clocks.
def publish(data, session="2026-10-01", at="2026-10-02T17:00:00-04:00"):
    day = data["dates"][-1].astype(object)
    return forward.fit_month(
        data,
        fit_session=session,
        data_as_of=datetime.combine(
            day, exchange.session_close(day), exchange.NEW_YORK
        ),
        published_at=at,
        source_revision="a" * 40,
        input_identity={"original": "b" * 64, "cohort": "c" * 64},
    )


# Fit the two registered models once for the publication and corruption cases.
@pytest.fixture(scope="module")
def fitted():
    data = dataset()
    return data, publish(data)


# Use a historical synthetic clock only to verify recorded publication boundaries.
def write(path, publication, at=None):
    return forward.write_publication(
        path,
        publication,
        clock=lambda: at or publication.receipt["identity"]["published_at"],
    )


# Compare actual original estimator predictions with exported current-row inference.
def test_real_numeric_heads_match_original_timing_fit(fitted, tmp_path, monkeypatch):
    data, publication = fitted
    elapsed = moments.waiting_elapsed_minutes(data["dates"])
    mean, second = moments.targets(data, elapsed)
    first = int(np.searchsorted(data["dates"], np.datetime64("2026-10-01")))
    indices = moments.training_rows(
        data["dates"], data["valid"], mean, elapsed, first, data["training_symbols"]
    )[:3]
    captured = {}

    # Capture trusted fitted estimators before the original helper serializes them.
    def capture(output, month, name, model):
        captured[name] = model
        return {"name": name}

    monkeypatch.setattr(moments, "_save_model", capture)
    means = {m: np.full(data["y"].shape, np.nan) for m in ("boosting", "ridge")}
    risk = np.full(data["valid"].shape, np.nan)
    score = data["valid"].copy()
    score[:, 23:] = False
    months = np.flatnonzero(
        data["dates"].astype("datetime64[M]") == np.datetime64("2026-10", "M")
    )
    moments._fit_month(
        data["X"],
        mean,
        second,
        score,
        indices,
        months,
        "2026-10",
        tmp_path,
        means,
        risk,
    )
    folder = tmp_path / "numeric"
    digest = write(folder, publication)

    # Numeric readback must never deserialize a joblib estimator.
    def forbidden(*args, **kwargs):
        pytest.fail("Numeric timing inference deserialized an executable model")

    monkeypatch.setattr(joblib, "load", forbidden)
    heads, receipt = forward.load_publication(
        folder, receipt_sha256=digest, observed_at="2026-10-05T09:45:00-04:00"
    )
    values = data["X"][-1, :23].reshape(-1, 21)
    predictions = forward.predict_moments(heads, values)
    expected = np.asarray(
        [captured[name].predict(values.astype(np.float64)) for name in forward.HEADS],
        dtype=np.float32,
    )
    np.testing.assert_array_equal(predictions, expected)
    assert receipt["training"]["training_clocks"] == [0, 3, 9, 19]
    assert receipt["training"]["maximum_label_end"] < "2026-08-17"
    assert receipt["adoption_eligible"] is False
    assert not heads["risk"].baseline.flags.writeable
    with pytest.raises(FileExistsError):
        write(folder, publication)


# Hidden labels, late features and overnight outcomes cannot revise monthly heads.
def test_freeze_and_future_prefix_invariance(fitted):
    data, before = fitted
    changed = deepcopy(data)
    endpoint = np.full(len(data["dates"]), np.datetime64("NaT", "D"))
    endpoint[:-10] = data["dates"][10:]
    changed["y"][endpoint >= original.HOLDOUT_START, ..., 2] = -100.0
    changed["y"][:, 24, :, 2] = 1000.0
    changed["X"][data["dates"] >= np.datetime64("2026-10-01")] = 20.0
    after = publish(changed)
    assert after.receipt["models"] == before.receipt["models"]
    assert after.receipt["training"] == before.receipt["training"]


# Clock semantics and calendar bytes must remain attributable to the published fit.
def test_publication_binds_actual_clock_helpers_and_calendar(fitted):
    recorded = fitted[1].receipt["identity"]["sources"]
    root = Path(forward.__file__).resolve().parents[2]
    for path in (
        Path(reference.__file__),
        Path(publication_source.__file__),
        exchange.HISTORICAL_SESSIONS_PATH,
        exchange.HOLIDAYS_PATH,
        exchange.EARLY_CLOSES_PATH,
    ):
        assert (
            recorded[str(path.relative_to(root))]
            == sha256(path.read_bytes()).hexdigest()
        )


# A returned receipt must not alias or revise the registered execution target.
def test_returned_receipt_detaches_registered_target(monkeypatch):
    declared = deepcopy(moments.TARGET_SCHEMA)
    monkeypatch.setattr(moments, "TARGET_SCHEMA", deepcopy(declared))
    publication = publish(
        dataset("2024-01-31"), session="2024-02-01", at="2024-02-01T08:00:00-05:00"
    )
    publication.receipt["identity"]["target_schema"]["prediction_clocks"].append(24)
    publication.receipt["identity"]["target_schema"]["maturity_sessions"] = 1
    assert declared == moments.TARGET_SCHEMA


# New-month fitting needs only the previous completed session, not future prices.
def test_forward_fit_without_any_current_month_features():
    data = dataset("2026-09-30")
    publication = publish(data, at="2026-10-01T08:00:00-04:00")
    assert publication.receipt["status"] == "fitted"
    assert publication.receipt["training"]["fit_date"] == "2026-10-01"
    assert publication.receipt["training"]["maximum_label_end"] < "2026-08-17"


# Missing training stays unavailable and never turns into a synthetic forecast.
def test_insufficient_training_persists_unavailable(tmp_path):
    data = dataset("2024-01-31")
    publication = publish(data, session="2024-02-01", at="2024-02-01T08:00:00-05:00")
    assert publication.receipt["status"] == "insufficient_mature_history"
    folder = tmp_path / "unavailable"
    digest = write(folder, publication)
    heads, _ = forward.load_publication(
        folder, receipt_sha256=digest, observed_at="2024-02-01T09:45:00-05:00"
    )
    assert heads is None
    assert np.isnan(forward.predict_moments(heads, data["X"][-1, 0])).all()


# Receipt and model availability must follow real publication and monthly boundaries.
@pytest.mark.parametrize(
    "at",
    ["2026-10-02T16:59:59-04:00", "2026-11-02T09:45:00-05:00", "2026-10-05T09:45:00"],
)
def test_stale_or_unpublished_model_refused(fitted, tmp_path, at):
    folder = tmp_path / "clock"
    digest = write(folder, fitted[1])
    with pytest.raises(ValueError, match="causal timing|Timezone-aware"):
        forward.load_publication(folder, receipt_sha256=digest, observed_at=at)


# Partial or reversed-clock serialization leaves no valid publication receipt.
def test_writer_cannot_backdate_after_serialization(fitted, tmp_path):
    folder = tmp_path / "backdated"
    with pytest.raises(ValueError, match="cannot precede"):
        write(folder, fitted[1], "2026-10-02T16:59:59-04:00")
    assert not (folder / "publication.json").exists()


# Changed numeric bytes are rejected before the consumer can score them.
def test_changed_model_bytes_refused(fitted, tmp_path):
    folder = tmp_path / "changed"
    digest = write(folder, fitted[1])
    path = folder / "models.npz"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="model bytes"):
        forward.load_publication(
            folder, receipt_sha256=digest, observed_at="2026-10-05T09:45:00-04:00"
        )


# Even newly hash-addressed tree payloads cannot contain cycles or invalid baselines.
def test_malformed_numeric_tree_refused(fitted):
    bundle = deepcopy(fitted[1].bundles["boosting_mean"])
    assert len(bundle["nodes_0"]) > 1
    bundle["nodes_0"]["left"][0] = 0
    with pytest.raises(ValueError, match="forward-child"):
        forward._head(bundle)
    bundle = deepcopy(fitted[1].bundles["risk"])
    bundle["baseline"][0, 0] = np.nan
    with pytest.raises(ValueError, match="baseline"):
        forward._head(bundle)


# Gaps and unfinished input sessions cannot masquerade as mature training evidence.
def test_input_calendar_and_completion_refused(fitted):
    data = deepcopy(fitted[0])
    for name in ("X", "y", "valid", "dates"):
        data[name] = np.delete(data[name], 40, axis=0)
    with pytest.raises(ValueError, match="completed-session"):
        publish(data)
    with pytest.raises(ValueError, match="completed-session"):
        forward.fit_month(
            fitted[0],
            fit_session="2026-10-01",
            data_as_of="2026-10-02T15:59:59-04:00",
            published_at="2026-10-02T17:00:00-04:00",
            source_revision="a" * 40,
            input_identity={"original": "b" * 64},
        )


# Preserve synthetic original OOS calibration bytes for forward-month acceptance only.
@pytest.fixture(scope="module")
def residual_archive():
    dates = dataset("2026-09-30")["dates"]
    shape = (len(dates), 2, 3)
    inputs = {
        "dates": dates,
        "symbols": ("AAOI", "SPY", "QQQ"),
        "means": np.zeros(shape, dtype=np.float32),
        "second_moments": np.full(shape, 0.01, dtype=np.float32),
        "labels": np.broadcast_to(np.array([-0.1, 0.1])[None, :, None], shape).copy(),
        "valid": np.ones(shape, dtype=bool),
        "outcome_end_dates": dates.copy(),
        "data_as_of": "2026-09-30T16:00:00-04:00",
        "horizon": probability.HORIZON,
    }
    calibrated = probability.calibrate(**inputs)
    saved = saved_source.load_saved(
        **inputs,
        manifest=calibrated.manifest,
        saved_probability=calibrated.probability_positive,
        saved_quantiles=calibrated.quantiles,
    )
    return inputs, saved


# Prepare one forward sample with an explicitly synthetic post-preparation clock.
def residual_month(saved, **changes):
    arguments = {
        "fit_session": "2026-10-01",
        "published_at": "2026-10-01T08:00:00-04:00",
        "archive_identity": {"cohort": "c" * 64, "archive": "d" * 64},
        "clock": lambda: "2026-10-01T08:00:00-04:00",
    }
    arguments.update(changes)
    return forward.prepare_residuals(saved, **arguments)


# Original calibration with an unavailable new row pins the forward sample formula.
def test_forward_residuals_match_original_next_month_without_rescoring(
    residual_archive, monkeypatch
):
    inputs, saved = residual_archive
    expected_inputs = deepcopy(inputs)
    expected_inputs["dates"] = np.append(inputs["dates"], np.datetime64("2026-10-01"))
    for name in ("means", "second_moments", "labels", "valid"):
        values = inputs[name]
        extra = (
            np.zeros((1, 2, 3), dtype=bool)
            if name == "valid"
            else np.full((1, 2, 3), np.nan)
        )
        expected_inputs[name] = np.concatenate((values, extra.astype(values.dtype)))
    expected_inputs["outcome_end_dates"] = np.append(
        inputs["outcome_end_dates"], np.datetime64("NaT", "D")
    )
    expected_inputs["data_as_of"] = "2026-10-01T16:00:00-04:00"
    expected = probability.calibrate(**expected_inputs).samples["2026-10"]["AAOI"]

    # Forward continuation must not recalibrate old probability diagnostics.
    def forbidden(*args, **kwargs):
        pytest.fail("Forward residual preparation rescored the archive")

    monkeypatch.setattr(probability, "calibrate", forbidden)
    actual = residual_month(saved)
    for name in ("residuals", "weights", "day_indices", "clock_indices"):
        np.testing.assert_array_equal(
            getattr(actual.samples["AAOI"], name), getattr(expected, name)
        )
    assert set(actual.samples) == {"AAOI"}
    assert actual.receipt["stocks"][0]["maximum_endpoint"] < "2026-08-17"
    assert not actual.samples["AAOI"].residuals.flags.writeable


# Mature lookback uses actual exchange dates even beyond the last archived month.
def test_forward_residual_calendar_lookback_and_missing_sessions(residual_archive):
    _, saved = residual_archive
    result = residual_month(
        saved,
        fit_session="2026-11-02",
        published_at="2026-11-02T08:00:00-05:00",
        clock=lambda: "2026-11-02T08:00:00-05:00",
    )
    lower = result.receipt["identity"]["lookback_first_date"]
    assert (
        saved.dates[result.samples["AAOI"].day_indices] >= np.datetime64(lower)
    ).all()
    assert result.receipt["identity"]["unrepresented_archive_sessions"] > 0


# Mutating a restored context cannot create an unauthenticated future sample.
def test_changed_verified_context_refused(residual_archive):
    saved = deepcopy(residual_archive[1])
    saved._context[4].flags.writeable = True
    saved._context[4][0, 0, 0] = 99
    with pytest.raises(ValueError, match="Verified original OOS"):
        residual_month(saved)


# A forward request cannot predate its actual input or preparation completion.
@pytest.mark.parametrize(
    "change",
    [
        {"published_at": "2026-09-30T08:00:00-04:00"},
        {"clock": lambda: "2026-10-01T07:59:59-04:00"},
        {"archive_identity": {"cohort": "invalid"}},
    ],
)
def test_residual_availability_and_identity_refused(residual_archive, change):
    with pytest.raises(ValueError, match="dated forward|preparation"):
        residual_month(residual_archive[1], **change)


# Real numeric head readback and original residuals supply only the admitted stock.
def test_current_model_and_residual_distribution_path(
    fitted, residual_archive, tmp_path
):
    folder = tmp_path / "forward-cdf"
    digest = write(folder, fitted[1])
    month = residual_month(residual_archive[1])
    values = np.zeros((3, 21), dtype=np.float32)
    result = forward.current_distributions(
        folder,
        digest,
        month,
        symbols=residual_archive[0]["symbols"],
        values=values,
        valid=np.ones(3, dtype=bool),
        observed_at="2026-10-05T10:00:03-04:00",
        timing_supported=True,
    )
    heads, _ = forward.load_publication(
        folder, receipt_sha256=digest, observed_at="2026-10-05T10:00:03-04:00"
    )
    predicted = forward.predict_moments(heads, values).astype(np.float64)
    assert result["AAOI"].mean == predicted[0, 0]
    assert result["AAOI"].scale == np.sqrt(predicted[1, 0] - predicted[0, 0] ** 2)
    assert result["SPY"] is None
    assert result["QQQ"] is None
    assert result["AAOI"].horizon == probability.HORIZON
    assert month.receipt["confidence_guarantee"] is False


# Unavailable observations and unsupported clocks retain every name without forecasts.
def test_current_missing_inputs_and_timing_retained(fitted, residual_archive, tmp_path):
    folder = tmp_path / "missing-cdf"
    digest = write(folder, fitted[1])
    arguments = {
        "symbols": residual_archive[0]["symbols"],
        "values": np.zeros((3, 21)),
        "valid": np.zeros(3, dtype=bool),
        "observed_at": "2026-10-05T10:00:03-04:00",
        "timing_supported": True,
    }
    month = residual_month(residual_archive[1])
    arguments["values"][0] = np.inf
    result = forward.current_distributions(folder, digest, month, **arguments)
    assert all(value is None for value in result.values())
    arguments.update(
        values=np.zeros((3, 21)), valid=np.ones(3, dtype=bool), timing_supported=False
    )
    result = forward.current_distributions(folder, digest, month, **arguments)
    assert all(value is None for value in result.values())


# Changed cohort metadata cannot substitute residual evidence at the current decision.
def test_changed_residual_receipt_refused(fitted, residual_archive, tmp_path):
    folder = tmp_path / "changed-cdf"
    digest = write(folder, fitted[1])
    month = residual_month(residual_archive[1])
    month.receipt["stocks"][0]["training_days"] = 1
    with pytest.raises(ValueError, match="Matching current"):
        forward.current_distributions(
            folder,
            digest,
            month,
            symbols=residual_archive[0]["symbols"],
            values=np.zeros((3, 21)),
            valid=np.ones(3, dtype=bool),
            observed_at="2026-10-05T10:00:03-04:00",
            timing_supported=True,
        )
