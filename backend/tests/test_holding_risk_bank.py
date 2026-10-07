"""Installed risk history preserves original numeric scenarios and lineage."""

import json
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256

import numpy as np
import pytest

from backend.market import direct_error_band as errors
from backend.market import holding_risk_bank as storage
from backend.tests.test_direct_feature_arithmetic import risk_example_factory


# Fit original synthetic evidence once; no publication or restoration may train again.
@pytest.fixture(scope="module")
def original(tmp_path_factory):
    _, bridge, _, _, risk = risk_example_factory(
        tmp_path_factory,
        with_volatility=True,
        with_market=True,
    )
    reader = errors.VolatilityHoldingReader(risk, bridge)
    return risk, bridge, reader, reader.as_of + timedelta(minutes=1)


# Store the supplied original inputs at an explicit synthetic availability clock.
def publish(folder, original):
    risk, bridge, _, now = original
    return storage.write_bank(
        folder,
        risk,
        bridge,
        source_revision="a" * 40,
        input_identity={"original_arrays": "b" * 64},
        published_at=now,
        clock=lambda: now + timedelta(seconds=1),
    )


# Every restored array and joint scenario must equal the authentic original reader.
def test_original_reader_roundtrip_without_fitting(original, tmp_path, monkeypatch):
    risk, _, reader, now = original

    # Any estimator creation would violate the installed-artifact contract.
    def forbidden(*args, **kwargs):
        pytest.fail("Risk-bank storage attempted a model fit")

    monkeypatch.setattr(storage.base, "_estimator", forbidden)
    monkeypatch.setattr(storage.feature.direct, "_fit", forbidden)
    folder = tmp_path / "bank"
    digest = publish(folder, original)
    restored, receipt = storage.load_bank(
        folder,
        receipt_sha256=digest,
        observed_at=now + timedelta(seconds=2),
    )
    assert restored.identity == reader.identity == receipt["reader_identity"]
    assert restored.symbols == reader.symbols
    assert restored.as_of == reader.as_of
    for key in (
        "dates",
        "features",
        "forecasts",
        "labels",
        "support",
        "endpoints",
        "volatility",
    ):
        np.testing.assert_array_equal(getattr(restored, key), getattr(reader, key))
        assert not getattr(restored, key).flags.writeable
    day = len(reader.dates) - 1
    actual, expected = (
        restored.distribution(day, ("AAA", "BBB")),
        reader.distribution(day, ("AAA", "BBB")),
    )
    assert actual.receipt == expected.receipt
    np.testing.assert_array_equal(actual.scenarios, expected.scenarios)
    np.testing.assert_array_equal(actual.probabilities, expected.probabilities)
    assert folder.stat().st_mode & 0o777 == 0o700
    assert (folder / "bank.json").stat().st_mode & 0o777 == 0o600
    assert (folder / "bank.npz").stat().st_mode & 0o777 == 0o600
    with np.load(folder / "bank.npz", allow_pickle=False) as arrays:
        assert len(arrays.files) == 14
        assert all(not arrays[key].dtype.hasobject for key in arrays.files)
        assert "models" not in arrays.files
    # Neither a caller edit nor a second publication may rewrite the original bank.
    altered = deepcopy(risk)
    altered.features[-1, 0, 4] *= 2
    assert restored.features[-1, 0, 4] == reader.features[-1, 0, 4]
    with pytest.raises(FileExistsError):
        publish(folder, original)
    assert sha256((folder / "bank.json").read_bytes()).hexdigest() == digest


# A future publication cannot be admitted as evidence known before serialization.
def test_publication_availability_is_not_backdated(original, tmp_path):
    now = original[-1]
    folder = tmp_path / "bank"
    digest = publish(folder, original)
    with pytest.raises(ValueError, match="available risk-bank"):
        storage.load_bank(folder, receipt_sha256=digest, observed_at=now)
    risk, bridge, _, _ = original
    with pytest.raises(ValueError, match="availability"):
        storage.write_bank(
            tmp_path / "early",
            risk,
            bridge,
            source_revision="a" * 40,
            input_identity={"original": "b" * 64},
            published_at=now,
            clock=lambda: now - timedelta(seconds=1),
        )
    assert not (tmp_path / "early/bank.json").exists()


# Known original bytes cannot be replaced by edited JSON or a different numeric archive.
@pytest.mark.parametrize("file", ["bank.json", "bank.npz"])
def test_tampered_original_bytes_are_rejected(original, tmp_path, file):
    folder = tmp_path / "bank"
    digest = publish(folder, original)
    target = folder / file
    target.write_bytes(target.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="bytes differ"):
        storage.load_bank(
            folder,
            receipt_sha256=digest,
            observed_at=original[-1] + timedelta(seconds=2),
        )


# Even hash-consistent outer metadata must retain the constructor's original lineage.
def test_rehashed_forecast_cannot_fabricate_original_risk(original, tmp_path):
    folder = tmp_path / "bank"
    publish(folder, original)
    receipt = json.loads((folder / "bank.json").read_bytes())
    with np.load(folder / "bank.npz", allow_pickle=False) as archive:
        arrays = dict(archive)
    arrays["risk__forecasts"][-1, 0] += 0.01
    np.savez_compressed(folder / "bank.npz", **arrays)
    receipt["arrays_sha256"] = sha256((folder / "bank.npz").read_bytes()).hexdigest()
    receipt["identity"]["array_sha256"]["risk__forecasts"] = storage.reference._hash(
        arrays["risk__forecasts"]
    )
    receipt["identity_sha256"] = storage.base._json_hash(receipt["identity"])
    raw = json.dumps(receipt, sort_keys=True, allow_nan=False).encode()
    (folder / "bank.json").write_bytes(raw)
    with pytest.raises(ValueError, match="lineage"):
        storage.load_bank(
            folder,
            receipt_sha256=sha256(raw).hexdigest(),
            observed_at=original[-1] + timedelta(seconds=2),
        )


# The narrowly registered old source is supported without admitting arbitrary drift.
def test_registered_saved_origin_is_explicit(original, tmp_path):
    risk, bridge, _, now = deepcopy(original)
    risk.manifest["identity"]["source_sha256"] = dict(storage.feature.SAVED_RISK_SOURCE)
    risk.manifest["identity_sha256"] = storage.base._json_hash(
        risk.manifest["identity"]
    )
    with pytest.raises(ValueError, match="lineage"):
        storage.write_bank(
            tmp_path / "refused",
            risk,
            bridge,
            source_revision="a" * 40,
            input_identity={"old": "b" * 64},
            published_at=now,
            clock=lambda: now,
        )
    digest = storage.write_bank(
        tmp_path / "accepted",
        risk,
        bridge,
        source_revision="a" * 40,
        input_identity={"old": "b" * 64},
        published_at=now,
        allow_saved_origin=True,
        clock=lambda: now,
    )
    restored, receipt = storage.load_bank(
        tmp_path / "accepted",
        receipt_sha256=digest,
        observed_at=now,
    )
    assert receipt["identity"]["allow_saved_origin"] is True
    assert (
        restored._reader.identity["original_risk_source_sha256"]
        == storage.feature.SAVED_RISK_SOURCE
    )


# Pickled objects in a hash-linked archive cannot become installed model inputs.
def test_object_arrays_never_deserialized(original, tmp_path):
    folder = tmp_path / "bank"
    publish(folder, original)
    receipt = json.loads((folder / "bank.json").read_bytes())
    with np.load(folder / "bank.npz", allow_pickle=False) as archive:
        arrays = dict(archive)
    arrays["symbols"] = np.asarray(arrays["symbols"], dtype=object)
    np.savez_compressed(folder / "bank.npz", **arrays)
    receipt["arrays_sha256"] = sha256((folder / "bank.npz").read_bytes()).hexdigest()
    raw = json.dumps(receipt, sort_keys=True, allow_nan=False).encode()
    (folder / "bank.json").write_bytes(raw)
    with pytest.raises(ValueError, match="Object arrays cannot be loaded"):
        storage.load_bank(
            folder,
            receipt_sha256=sha256(raw).hexdigest(),
            observed_at=original[-1] + timedelta(seconds=2),
        )
