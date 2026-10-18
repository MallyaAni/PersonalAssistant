"""Versioned opaque native paper components; never financial/JSON admission.

The caller supplies storage explicitly. A descriptor never selects a filesystem
path, completes a native operation or adopts an account. Historical descriptors
verify content independently of the checkpoint's latest-capture marker. Restore
consumes the primitive's one reserved restore inode; it is not replayable.
"""

from pathlib import Path

from backend.market import historical_physical_checkpoint as physical

SCHEMA = "physical-paper-component/1"
SCOPE = "OPAQUE_NATIVE_PAPER_NOT_SEMANTIC_ADMISSION"
KEYS = {
    "schema", "scope", "identity_sha256", "primitive_sha256", "limits_sha256",
    "adapter_sha256",
    "checkpoint", "raw_sha256", "raw_bytes", "history_rows",
    "native_operation_committed", "durable_simulator_adoption",
}


# Refuse storage substitutions before reading or capturing an account component.
def _checkpoint(checkpoint, expected_identity):
    physical._digest(expected_identity)
    physical._require(
        type(checkpoint) is physical.PhysicalCheckpoint
        and checkpoint.header["identity_sha256"] == expected_identity,
        "Exact same-account component checkpoint required",
    )


# Build finite metadata from authenticated raw content without parsing its values.
def _descriptor(reference, root):
    return {
        "schema": SCHEMA,
        "scope": SCOPE,
        "identity_sha256": root["identity_sha256"],
        "primitive_sha256": root["primitive_sha256"],
        "adapter_sha256": physical._sha(Path(__file__).read_bytes()),
        "limits_sha256": root["limits_sha256"],
        "checkpoint": dict(reference),
        "raw_sha256": root["raw_sha256"],
        "raw_bytes": root["raw_bytes"],
        "history_rows": root["history_rows"],
        "native_operation_committed": False,
        "durable_simulator_adoption": False,
    }


# Publish a descriptor only after an actual completed local capture of native bytes.
def capture(checkpoint, path, *, expected_identity):
    _checkpoint(checkpoint, expected_identity)
    reference = checkpoint.capture(path)
    completed = checkpoint.completed(reference)
    return _descriptor(reference, completed["root"])


# Authenticate every descriptor field, including older captures, without adoption.
def verify(component, checkpoint, *, expected_identity):
    _checkpoint(checkpoint, expected_identity)
    physical._require(
        type(component) is dict and len(component) == len(KEYS)
        and set(component) == KEYS,
        "Exact versioned raw paper component required",
    )
    physical._require(
        component["schema"] == SCHEMA and component["scope"] == SCOPE
        and component["identity_sha256"] == expected_identity
        and type(component["raw_bytes"]) is int
        and 0 < component["raw_bytes"] <= checkpoint.limits["raw_bytes"]
        and type(component["history_rows"]) is int
        and 0 <= component["history_rows"] <= checkpoint.limits["history_rows"]
        and component["native_operation_committed"] is False
        and component["durable_simulator_adoption"] is False,
        "Raw paper component identity, scope or bounds differ",
    )
    for name in ("primitive_sha256", "adapter_sha256", "limits_sha256", "raw_sha256"):
        physical._digest(component[name])
    root = checkpoint.verify(component["checkpoint"])
    physical._require(
        physical._encoded(component) == physical._encoded(
            _descriptor(component["checkpoint"], root)
        ),
        "Raw paper component content differs",
    )
    return root


# Restore exact opaque bytes once through the already reserved same-filesystem inode.
def restore(component, checkpoint, destination, *, expected_identity):
    root = verify(component, checkpoint, expected_identity=expected_identity)
    control = physical._control(
        physical._fixed_read(checkpoint.root / "control"), checkpoint.limits
    )
    physical._require(
        control["operation"] is None and control["restored"] is False,
        "Component restore reservation unavailable or already consumed",
    )
    restored = checkpoint.restore(component["checkpoint"], destination)
    physical._require(restored == root, "Restored raw paper component differs")
    return restored
