"""Non-executable original risk history for the installed learned holding policy.

Restore the existing reader through its full lineage checks. This stores no
estimator, fits nothing and does not grant permission to trade a live account.
"""

import io
import json
import os
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import numpy as np

from backend.market import calendar
from backend.market import daily_arithmetic_bridge as reference
from backend.market import direct_error_band as errors
from backend.market import direct_feature_arithmetic as feature
from backend.market import learned_entry_models as base

SCHEMA = "holding-risk-bank/1"
RISK_ARRAYS = ("forecasts", "score_mask", "features", "valid", "prices")
PARENT_ARRAYS = ("forecasts", "score_mask")
BRIDGE_ARRAYS = ("calibrated", "past_mean", "labels", "label_end_dates", "score_mask")


# Bind every consumer and calendar file that decides lineage or outcome maturity.
def _sources():
    root = Path(__file__).resolve().parents[2]
    paths = [
        Path(__file__),
        Path(errors.__file__),
        Path(feature.__file__),
        Path(reference.__file__),
        Path(feature.direct.__file__),
        Path(base.__file__),
        Path(calendar.__file__),
        calendar.HOLIDAYS_PATH,
        calendar.HISTORICAL_SESSIONS_PATH,
        calendar.EARLY_CLOSES_PATH,
    ]
    return {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


# Detach the original numeric buffers and discard any executable parent estimators.
def _copy(risk, bridge):
    if not isinstance(risk, feature.HoldingRiskForecasts) or not isinstance(
        bridge, reference.BridgeForecasts
    ):
        raise ValueError("Original holding risk and bridge artifacts required")
    parent = feature._copy_feature(risk.parent)
    copied = feature.HoldingRiskForecasts(
        risk.forecasts.copy(),
        risk.score_mask.copy(),
        deepcopy(risk.manifest),
        risk.dates.copy(),
        tuple(risk.symbols),
        parent,
        risk.features.copy(),
        risk.valid.copy(),
        risk.prices.copy(),
    )
    copied_bridge = reference.BridgeForecasts(
        *(getattr(bridge, key).copy() for key in BRIDGE_ARRAYS),
        deepcopy(bridge.manifest),
    )
    return copied, copied_bridge


# Preserve typed original arrays instead of pickling a reader or executable model.
def _arrays(risk, bridge):
    arrays = {"dates": risk.dates, "symbols": np.asarray(risk.symbols)}
    for prefix, obj, names in (
        ("risk", risk, RISK_ARRAYS),
        ("parent", risk.parent, PARENT_ARRAYS),
        ("bridge", bridge, BRIDGE_ARRAYS),
    ):
        arrays.update({f"{prefix}__{name}": getattr(obj, name) for name in names})
    if any(value.dtype.hasobject for value in arrays.values()):
        raise ValueError("Risk bank cannot contain executable object arrays")
    return arrays


# Publish an exclusive private snapshot after full original-reader validation.
def write_bank(
    output,
    risk,
    bridge,
    *,
    source_revision,
    input_identity,
    published_at,
    allow_saved_origin=False,
    clock=None,
):
    risk, bridge = _copy(risk, bridge)
    reader = errors.VolatilityHoldingReader(
        risk,
        bridge,
        allow_saved_origin=allow_saved_origin,
    )
    requested = reference._as_of(published_at)
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
        or not isinstance(allow_saved_origin, bool)
        or requested < reader.as_of
    ):
        raise ValueError(
            "Actual original input identities and publication clock required"
        )
    arrays = _arrays(risk, bridge)
    folder = Path(output)
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    with (folder / "bank.npz").open("xb") as stream:
        os.chmod(folder / "bank.npz", 0o600)
        np.savez_compressed(stream, **arrays)
        stream.flush()
        os.fsync(stream.fileno())
    available = reference._as_of(clock() if clock else datetime.now(calendar.NEW_YORK))
    if available < requested:
        raise ValueError(
            "Risk-bank availability cannot precede its publication request"
        )
    identity = {
        "schema": SCHEMA,
        "source_revision": source_revision,
        "input_identity": deepcopy(input_identity),
        "sources": _sources(),
        "data_as_of": reader.as_of.isoformat(),
        "requested_at": requested.isoformat(),
        "published_at": available.isoformat(),
        "allow_saved_origin": allow_saved_origin,
        "array_sha256": {key: reference._hash(value) for key, value in arrays.items()},
    }
    receipt = {
        "identity": identity,
        "identity_sha256": base._json_hash(identity),
        "risk_manifest": risk.manifest,
        "feature_manifest": risk.parent.manifest,
        "bridge_manifest": bridge.manifest,
        "reader_identity": reader.identity,
        "arrays_sha256": sha256((folder / "bank.npz").read_bytes()).hexdigest(),
        "adoption_eligible": False,
        "confidence_guarantee": False,
    }
    encoded = json.dumps(receipt, sort_keys=True, allow_nan=False).encode()
    with (folder / "bank.json").open("xb") as stream:
        os.chmod(folder / "bank.json", 0o600)
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return sha256(encoded).hexdigest()


# Restore typed artifacts through the same maturity and source checks as the original.
def load_bank(output, *, receipt_sha256, observed_at):
    folder = Path(output)
    raw = (folder / "bank.json").read_bytes()
    if sha256(raw).hexdigest() != receipt_sha256:
        raise ValueError("Original risk-bank receipt bytes differ")
    receipt = json.loads(raw)
    identity = receipt["identity"]
    observed = reference._as_of(observed_at)
    if (
        set(receipt)
        != {
            "identity",
            "identity_sha256",
            "risk_manifest",
            "feature_manifest",
            "bridge_manifest",
            "reader_identity",
            "arrays_sha256",
            "adoption_eligible",
            "confidence_guarantee",
        }
        or identity["schema"] != SCHEMA
        or base._json_hash(identity) != receipt["identity_sha256"]
        or identity["sources"] != _sources()
        or not isinstance(identity["allow_saved_origin"], bool)
        or not reference._as_of(identity["data_as_of"])
        <= reference._as_of(identity["requested_at"])
        <= reference._as_of(identity["published_at"])
        <= observed
        or receipt["adoption_eligible"] is not False
        or receipt["confidence_guarantee"] is not False
    ):
        raise ValueError("Original available risk-bank lineage required")
    content = (folder / "bank.npz").read_bytes()
    if sha256(content).hexdigest() != receipt["arrays_sha256"]:
        raise ValueError("Original risk-bank array bytes differ")
    with np.load(io.BytesIO(content), allow_pickle=False) as archive:
        expected = {"dates", "symbols"} | {
            f"{prefix}__{name}"
            for prefix, fields in (
                ("risk", RISK_ARRAYS),
                ("parent", PARENT_ARRAYS),
                ("bridge", BRIDGE_ARRAYS),
            )
            for name in fields
        }
        if set(archive.files) != expected or set(identity["array_sha256"]) != expected:
            raise ValueError("Exact original risk-bank array fields required")
        arrays = {key: archive[key] for key in expected}
    if any(
        reference._hash(value) != identity["array_sha256"][key]
        for key, value in arrays.items()
    ):
        raise ValueError("Original typed risk-bank arrays differ")
    parent = feature.FeatureForecasts(
        arrays["parent__forecasts"],
        arrays["parent__score_mask"],
        receipt["feature_manifest"],
        {},
        arrays["dates"],
        tuple(arrays["symbols"]),
    )
    risk = feature.HoldingRiskForecasts(
        arrays["risk__forecasts"],
        arrays["risk__score_mask"],
        receipt["risk_manifest"],
        arrays["dates"],
        tuple(arrays["symbols"]),
        parent,
        arrays["risk__features"],
        arrays["risk__valid"],
        arrays["risk__prices"],
    )
    bridge = reference.BridgeForecasts(
        *(arrays[f"bridge__{key}"] for key in BRIDGE_ARRAYS),
        receipt["bridge_manifest"],
    )
    reader = errors.VolatilityHoldingReader(
        risk,
        bridge,
        allow_saved_origin=identity["allow_saved_origin"],
    )
    if reader.identity != receipt[
        "reader_identity"
    ] or reader.as_of != reference._as_of(identity["data_as_of"]):
        raise ValueError("Restored risk reader differs from original numeric identity")
    # Bind the parsed archive to the same original bytes throughout restoration.
    if (folder / "bank.npz").read_bytes() != content or (
        folder / "bank.json"
    ).read_bytes() != raw:
        raise ValueError("Concurrent risk-bank changes prevent stable restoration")
    return reader, receipt
