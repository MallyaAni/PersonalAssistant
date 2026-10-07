"""Real fitted numeric publications prove clocks, frozen training and reload parity."""

from copy import deepcopy

import numpy as np
import pytest

from backend.market import calendar as exchange
from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_daily_arithmetic as direct
from backend.market import direct_feature_arithmetic as feature
from backend.market import forward_arithmetic as forward
from backend.tests.test_direct_feature_arithmetic import fixture


# Build complete synthetic original evidence ending at a declared exchange close.
def inputs(end="2025-04-04"):
    _, calendar = exchange.reviewed_sessions()
    count = int(
        np.busday_count(
            "2023-01-03",
            np.datetime64(end) + np.timedelta64(1, "D"),
            busdaycal=calendar,
        )
    )
    return fixture(count=count)


# Exercise the real registered estimator with explicit original artifact identity.
def publish(data, *, session="2025-04-01", at="2025-04-04T17:00:00-04:00"):
    return forward.fit_month(
        *data,
        fit_session=session,
        published_at=at,
        source_revision="a" * 40,
        input_identity={"original": "b" * 64},
    )


# Inject an explicit historical clock only in synthetic publication tests.
def save(output, publication, at=None):
    return forward.write_publication(
        output,
        publication,
        clock=lambda: at or publication.receipt["identity"]["published_at"],
    )


# Fit shared fixed synthetic inputs once without replacing any production state.
@pytest.fixture(scope="module")
def publication():
    data = inputs()
    return data, publish(data)


# Published numeric forecasts and rows equal the actual historical monthly fit.
def test_monthly_head_matches_original_path(publication, tmp_path):
    data, actual = publication
    original = feature.walk_forward(*data, hold_b=True)
    month = next(
        row for row in original.manifest["months"] if row["month"] == "2025-04"
    )
    assert actual.receipt["training"] == {
        key: month[key] for key in actual.receipt["training"]
    }
    assert actual.receipt["model"] == month["model"]
    output = tmp_path / "publication"
    digest = save(output, actual)
    restored, receipt = forward.load_publication(
        output, receipt_sha256=digest, observed_at="2025-04-04T17:00:00-04:00"
    )
    original_head = original.models["2025-04"]
    values = data[0]["X"][-4:].reshape(-1, 13)
    np.testing.assert_allclose(
        restored.predict(values), original_head.predict(values), rtol=1e-14, atol=1e-15
    )
    assert receipt["adoption_eligible"] is False
    assert not restored.baseline.flags.writeable
    with pytest.raises(FileExistsError):
        save(output, actual)


# New-month fit may use the preceding complete close without inventing future rows.
def test_forward_month_does_not_need_future_features():
    data = inputs("2025-03-31")
    before = data[0]["X"].copy()
    actual = publish(data, at="2025-04-01T16:00:00-04:00")
    assert actual.receipt["training"]["fit_index"] == len(data[0]["dates"])
    assert actual.receipt["status"] == "fitted"
    np.testing.assert_array_equal(before, data[0]["X"])


# The registered August holdout never enters a forward October monthly model.
def test_forward_training_retains_frozen_holdout():
    actual = publish(
        inputs("2026-09-30"), session="2026-10-01", at="2026-10-04T18:00:00-04:00"
    )
    training = actual.receipt["training"]
    assert training["label_end_before"] == "2026-08-17"
    assert np.datetime64(training["maximum_label_end"]) < np.datetime64("2026-08-17")
    assert actual.receipt["identity"]["published_at"] == "2026-10-04T18:00:00-04:00"


# An original model can never serve a clock before publication or a later month.
@pytest.mark.parametrize(
    "at", ["2025-04-04T16:59:59-04:00", "2025-05-01T17:00:00-04:00"]
)
def test_late_or_expired_publication_refused(publication, tmp_path, at):
    _, actual = publication
    output = tmp_path / "publication"
    digest = save(output, actual)
    with pytest.raises(ValueError, match="Current causal"):
        forward.load_publication(output, receipt_sha256=digest, observed_at=at)


# Ambiguous clocks, unreviewed dates and nonmonthly sessions refuse before fitting.
@pytest.mark.parametrize(
    ("session", "at"),
    [
        ("2025-04-01", "2025-04-01T15:59:59-04:00"),
        ("2025-04-01", "2025-04-04T17:00:00"),
        ("2025-04-02", "2025-04-04T17:00:00-04:00"),
        ("2029-01-02", "2029-01-02T17:00:00-05:00"),
        ("2025-04-01", "2025-05-01T17:00:00-04:00"),
    ],
)
def test_invalid_fit_clock_refused(publication, monkeypatch, session, at):
    data, _ = publication

    # Every invalid publication must stop before spending estimator work.
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid publication reached a fit")

    monkeypatch.setattr(direct, "_fit", forbidden)
    with pytest.raises(ValueError, match="required|Publication"):
        publish(data, session=session, at=at)


# Missing sessions between the supplied prefix and a forward fit are not compacted.
def test_missing_forward_sessions_refused(publication):
    data, _ = publication
    with pytest.raises(ValueError, match="Missing sessions"):
        publish(data, session="2025-05-01", at="2025-05-01T17:00:00-04:00")


# Future input publication cannot be used to create an earlier fitted artifact.
def test_input_publication_precedes_model(publication):
    data, _ = publication
    with pytest.raises(ValueError, match="Inputs cannot arrive"):
        publish(data, at="2025-04-01T17:00:00-04:00")


# No numeric model is fabricated from an insufficient original training prefix.
def test_insufficient_history_saved_as_unavailable(tmp_path):
    actual = publish(
        inputs("2023-03-31"), session="2023-04-03", at="2023-04-03T17:00:00-04:00"
    )
    assert actual.bundle is None
    assert actual.receipt["status"] == "insufficient_training_days"
    output = tmp_path / "unavailable"
    digest = save(output, actual)
    head, _ = forward.load_publication(
        output, receipt_sha256=digest, observed_at="2023-04-03T17:00:00-04:00"
    )
    assert head is None
    assert not (output / "model.npz").exists()


# Both receipt bytes and model bytes are authenticated before any numeric inference.
@pytest.mark.parametrize("filename", ["publication.json", "model.npz"])
def test_changed_artifact_refused(publication, tmp_path, filename):
    _, actual = publication
    output = tmp_path / "publication"
    digest = save(output, actual)
    path = output / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="bytes mismatch"):
        forward.load_publication(
            output, receipt_sha256=digest, observed_at="2025-04-04T17:00:00-04:00"
        )


# A receipt cannot relabel an immature or changed tree as the original model.
@pytest.mark.parametrize("change", ["immature", "tree", "clock"])
def test_mutated_in_memory_publication_refused(publication, tmp_path, change):
    _, original = publication
    actual = deepcopy(original)
    if change == "immature":
        actual.receipt["training"]["maximum_label_end"] = "2025-04-01"
    elif change == "tree":
        actual.bundle["baseline"][0, 0] += 0.001
    else:
        actual.receipt["identity"]["published_at"] = "2025-04-01T15:00:00-04:00"
        actual.receipt["identity_sha256"] = feature.base._json_hash(
            actual.receipt["identity"]
        )
    with pytest.raises(ValueError, match="Mature|identity mismatch|Current causal"):
        save(tmp_path / "refused", actual)
    assert not (tmp_path / "refused").exists()


# Serialized model availability follows the writer clock, including delayed writes.
def test_writer_clock_sets_actual_availability(publication, tmp_path):
    _, actual = publication
    output = tmp_path / "delayed"
    digest = save(output, actual, "2025-04-07T18:00:00-04:00")
    with pytest.raises(ValueError, match="Current causal"):
        forward.load_publication(
            output, receipt_sha256=digest, observed_at="2025-04-04T18:00:00-04:00"
        )
    _, receipt = forward.load_publication(
        output, receipt_sha256=digest, observed_at="2025-04-07T18:00:00-04:00"
    )
    assert receipt["identity"]["published_at"] == "2025-04-07T18:00:00-04:00"
    assert receipt["identity"]["fit_requested_at"] == "2025-04-04T17:00:00-04:00"


# A partial numeric write cannot commit a backdated publication receipt.
def test_writer_cannot_backdate(publication, tmp_path):
    _, actual = publication
    output = tmp_path / "backdated"
    with pytest.raises(ValueError, match="cannot precede"):
        save(output, actual, "2025-04-04T16:00:00-04:00")
    assert not (output / "publication.json").exists()


# A coherently rehashed compacted grid is still refused by the exchange calendar.
def test_interior_calendar_gap_refused(publication):
    data = deepcopy(publication[0])
    prepared, _, grades, eligible = data
    for field in ("dates", "X", "valid", "absolute_forecasts"):
        prepared[field] = np.delete(prepared[field], 10, axis=0)
    grades, eligible = np.delete(grades, 10, axis=0), np.delete(eligible, 10, axis=0)
    dates = prepared["dates"]
    bridge = reference.walk_forward(
        dates,
        prepared["symbols"],
        np.full(grades.shape, 100.0),
        grades,
        eligible,
        prepared["absolute_forecasts"],
        dates,
        data_as_of=data[1].manifest["data_as_of"],
    )
    with pytest.raises(ValueError, match="Complete completed-close"):
        publish((prepared, bridge, grades, eligible))


# Unobserved training columns cannot be manufactured into a trained model.
def test_unobserved_features_remain_unavailable(publication):
    data = deepcopy(publication[0])
    data[0]["X"][:] = np.nan
    actual = publish(data)
    assert actual.receipt["training"]["training_days"] >= 504
    assert actual.receipt["status"] == "no_observed_training_features"
    assert actual.bundle is None
