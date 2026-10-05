"""Actual timing fits, numeric inference and causal publication acceptance."""

from copy import deepcopy
from datetime import datetime

import joblib
import numpy as np
import pytest

from backend.market import calendar as exchange
from backend.market import forward_execution as forward
from backend.market import learned_entry_data as features
from backend.market import learned_entry_models as original
from backend.market import learned_intraday_moments as moments


# Supply a complete session grid with real models and controlled synthetic labels.
def dataset(end="2026-10-02"):
    _, calendar = exchange.reviewed_sessions()
    dates = np.arange("2023-01-03", np.datetime64(end) + 1, dtype="datetime64[D]")
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
        input_identity={"original": "b" * 64},
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
