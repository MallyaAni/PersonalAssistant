"""UNEXECUTED new admission module; copied source is not the original CLI identity.

No old effect module import, runtime projection, model loading or executor exists.
Calendar/package imports are deferred and still need separately admitted closure.
"""
import os
import socket
from pathlib import Path

from backend.market import live_model_history_input_auth as byte_auth
from backend.market.capacity_original_evidence_v1 import authenticate_file, pinned, require, strict_json
from backend.market.capacity_original_archive_adaptations_v1 import logical_digest as digest


IMAGE = "sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237"

FULL_REVISION = "27471b9c61b958f759e9f48b80acaf60cdf75f2e"

FULL_CONTAINER = "1e8f440a3b5b75dcabd299f5eaba58c7929fb6f96bc822fdb46b641ecf3e598d"

PRODUCER_IMAGE = (
    "sha256:136ebb46b7912f20472a375a6b29f6efec4cf2fdca13d56cbffb86a1be697db2"
)

FULL_ACCOUNT = (
    "/home/animallya96/scratch/live-model-history-full-20261013-v1/output/account"
)

SCHEMA = "original-history-audit-invocation/2"

FULL_PHYSICAL_SHA256 = (
    "f334e3a5c691fb4dbcc8ea4e7236f395eb5e26e34bae2f1fd4fac64fc5935130"
)

FULL_PHYSICAL_BYTES = 832110254

FULL_COMPLETION_BYTES = 373782589

FULL_COMPLETION_SHA256 = (
    "b9ad0b6c86b287f3557c635a5fca17703adc48a30a75470256084af911c8a3dd"
)

# Decode only the unchanged original externally pinned schema2 invocation.
def invocation(path, expected):
    value = strict_json(pinned(path, expected))
    fields = {
        "schema",
        "profile",
        "account",
        "market",
        "completion_sha256",
        "physical_sha256",
        "physical_bytes",
        "initial_sha256",
        "manifest",
        "manifest_sha256",
        "execution",
        "execution_sha256",
        "audit_source_sha256",
        "runtime",
        "runtime_sha256",
        "producer_runtime",
        "producer_runtime_sha256",
        "git_map",
        "git_map_sha256",
        "initial_receipts",
        "initial_receipts_sha256",
        "proof_parent",
    }
    require(
        type(value) is dict and set(value) == fields and value["schema"] == SCHEMA,
        "EXACT_AUDIT_INVOCATION_REQUIRED",
    )
    byte_auth.Pins(
        value["profile"],
        value["completion_sha256"],
        value["manifest_sha256"],
        value["execution_sha256"],
    )
    byte_auth.digest_value(value["physical_sha256"])
    require(
        type(value["physical_bytes"]) is int and value["physical_bytes"] >= 0,
        "EXTERNAL_PHYSICAL_SIZE_REQUIRED",
    )
    if value["profile"] == "original-full-27471":
        require(
            value["physical_sha256"] == FULL_PHYSICAL_SHA256
            and value["physical_bytes"] == FULL_PHYSICAL_BYTES,
            "EXACT_ORIGINAL_FULL_PHYSICAL_PIN_REQUIRED",
        )
        require(
            value["completion_sha256"] == FULL_COMPLETION_SHA256,
            "EXACT_ORIGINAL_FULL_COMPLETION_PIN_REQUIRED",
        )
    for name in (
        "account",
        "market",
        "manifest",
        "execution",
        "runtime",
        "proof_parent",
    ):
        byte_auth.canonical(value[name], absolute=True)
    require(
        type(value["audit_source_sha256"]) is dict
        and bool(value["audit_source_sha256"]),
        "COMPLETE_AUDIT_SOURCE_PIN_REQUIRED",
    )
    return value

# Retain exact original runtime and read-only input/proof mount checks.
def runtime_admission(value, *, hostname=None, uid=None):
    rows = strict_json(pinned(value["runtime"], value["runtime_sha256"]))
    require(
        type(rows) is list and len(rows) == 1, "ONE_ACTUAL_AUDIT_CONTAINER_REQUIRED"
    )
    row = rows[0]
    config, host = row["Config"], row["HostConfig"]
    require(
        row["Image"] == IMAGE
        and config["Hostname"]
        == (socket.gethostname() if hostname is None else hostname)
        and row["Id"].startswith(config["Hostname"])
        and config["User"] in ("1000", "1000:1000")
        and (os.getuid() if uid is None else uid) == 1000
        and host["NetworkMode"] == "none"
        and host["ReadonlyRootfs"] is True
        and host["NanoCpus"] == 1_000_000_000
        and host["Memory"] == 2 * 1024**3
        and host["MemorySwap"] == 2 * 1024**3
        and host.get("Privileged", False) is False,
        "EXACT_ISOLATED_NATIVE_AUDIT_RUNTIME_REQUIRED",
    )
    require(
        host.get("Tmpfs") == {"/tmp": "rw,size=64m"},
        "BOUNDED_AUDIT_TMPFS_REQUIRED",
    )
    mounts = row["Mounts"]
    require(type(mounts) is list and bool(mounts), "ACTUAL_AUDIT_MOUNTS_REQUIRED")
    writable = [item for item in mounts if item["RW"]]
    require(
        len(writable) == 1
        and writable[0]["Destination"] == value["proof_parent"]
        and writable[0]["Type"] == "bind",
        "SOLE_FRESH_PROOF_BIND_REQUIRED",
    )
    proof_source = Path(writable[0]["Source"])
    for item in mounts:
        if item["RW"]:
            continue
        source = Path(item["Source"])
        require(
            not proof_source.is_relative_to(source)
            and not source.is_relative_to(proof_source),
            "PROOF_HOST_PATH_OVERLAPS_ORIGINAL_INPUT",
        )
    require(
        not host.get("CapAdd") and not host.get("Devices"),
        "NO_AUDIT_DEVICE_OR_CAPABILITY_ADDITIONS",
    )
    required = (
        Path(value["account"]),
        Path(value["market"]),
        Path(__file__).resolve().parents[2],
    )
    for path in required:
        covering = [
            item
            for item in mounts
            if path == Path(item["Destination"])
            or Path(item["Destination"]) in path.parents
        ]
        require(bool(covering), "READONLY_AUDIT_INPUT_MOUNT_REQUIRED")
        selected = max(covering, key=lambda item: len(Path(item["Destination"]).parts))
        require(selected["RW"] is False, "ORIGINAL_AUDIT_INPUT_IS_WRITABLE")
        if value.get("profile") == "original-full-27471" and path == Path(
            value["account"]
        ):
            actual_path = Path(selected["Source"]) / path.relative_to(
                selected["Destination"]
            )
            require(
                str(actual_path) == FULL_ACCOUNT,
                "AUDITOR_ORIGINAL_ACCOUNT_HOST_MAPPING_DIFFERS",
            )
    return {
        "container": row["Id"],
        "image": row["Image"],
        "runtime_sha256": value["runtime_sha256"],
        "uid": 1000,
    }

# Authenticate the legacy audit-source/Git map separately from new executor bytes.
def source_admission(value, archives):
    root = Path(__file__).resolve().parents[2]
    files = value["audit_source_sha256"]
    required = {
        "backend/cli/audit_original_live_model_history.py",
        "backend/cli/verify_actual_policy_timing.py",
        "backend/cli/verify_live_model_history.py",
        "backend/market/live_model_history_audit_inputs.py",
        "backend/market/live_model_history_stream_audit.py",
        "backend/market/live_model_history_pending_audit.py",
        "backend/market/live_model_history_observation_context.py",
        "backend/market/live_model_history_nightly_model.py",
        "backend/market/live_model_history_nightly_audit.py",
        "backend/market/live_model_history_receipts.py",
        "backend/market/live_model_history_input_auth.py",
        "backend/market/original_history_json.py",
        "backend/market/live_model_history_binding.py",
        "backend/market/live_policy_replay.py",
        "backend/agents/trading/desk/paper.py",
    }
    require(required <= set(files), "ALL_AUDIT_COMPONENT_SOURCE_PINS_REQUIRED")
    for name, expected in files.items():
        byte_auth.canonical(name, absolute=False)
        authenticate_file(root / name, expected)
    if value["profile"] == "complete-private-v10":
        require(
            value["git_map"] is None and value["git_map_sha256"] is None,
            "TEST_PROFILE_IS_NOT_FULL_GIT_AUTHENTICATION",
        )
        return "UNVERIFIED_TEST_PROFILE_ONLY"
    require(value["git_map"] is not None, "EXTERNAL_COMPLETE_GIT_BLOB_MAP_REQUIRED")
    record = strict_json(pinned(value["git_map"], value["git_map_sha256"]))
    require(
        set(record) == {"revision", "files"}
        and record["revision"] == FULL_REVISION
        and len(record["files"]) == 2431
        and record["files"] == archives.sources,
        "ORIGINAL_FULL_GIT_BLOB_PROFILE_DIFFERS",
    )
    return {
        "revision": FULL_REVISION,
        "files": 2431,
        "external_git_blob_map_sha256": value["git_map_sha256"],
    }

# Retain exact completed producer image, command, mounts and original output mapping.
def producer_admission(value):
    if value["profile"] == "complete-private-v10":
        require(
            value["producer_runtime"] is None
            and value["producer_runtime_sha256"] is None,
            "TEST_PROFILE_PRODUCER_LIMIT_MUST_BE_EXPLICIT",
        )
        return "UNAVAILABLE_PRIVATE_TEST_PROFILE_ONLY"
    rows = strict_json(
        pinned(value["producer_runtime"], value["producer_runtime_sha256"])
    )
    require(type(rows) is list and len(rows) == 1, "ORIGINAL_PRODUCER_INSPECT_REQUIRED")
    row = rows[0]
    host, config = row["HostConfig"], row["Config"]
    require(
        row["Id"] == FULL_CONTAINER
        and row["State"]["Running"] is False
        and row["State"]["ExitCode"] == 0
        and row["State"]["OOMKilled"] is False
        and row["Image"] == PRODUCER_IMAGE
        and host["NetworkMode"] == "none"
        and host["ReadonlyRootfs"] is True
        and host["NanoCpus"] == 1_000_000_000
        and host["Memory"] == 4 * 1024**3
        and host.get("Privileged", False) is False
        and config["User"] in ("1000", "1000:1000"),
        "GENUINE_SUCCESSFUL_ORIGINAL_PRODUCER_REQUIRED",
    )
    execution = strict_json(pinned(value["execution"], value["execution_sha256"]))
    original_command = [
        "python",
        "-m",
        "backend.cli.market_live_model_history",
        "--market",
        "/private",
        "--output",
        "/results/account",
    ]
    require(
        execution["command"][-len(original_command) :] == original_command
        and config.get("Cmd") == original_command
        and "Entrypoint" in config
        and config["Entrypoint"] is None,
        "EXACT_ORIGINAL_PRODUCER_COMMAND_REQUIRED",
    )
    expected = byte_auth.mounts_from_receipt(execution)
    actual = {
        item["Destination"]: (item["Source"], "rw" if item["RW"] else "ro")
        for item in row["Mounts"]
        if item["Type"] == "bind"
    }
    require(
        len(actual) == len(row["Mounts"]) and actual == expected,
        "EXACT_ORIGINAL_PRODUCER_MOUNTS_REQUIRED",
    )
    writable = [
        (target, source) for target, (source, mode) in actual.items() if mode == "rw"
    ]
    command = execution["command"]
    require(
        command.count("--output") == 1 and len(writable) == 1,
        "SOLE_ORIGINAL_OUTPUT_REQUIRED",
    )
    target, source = writable[0]
    output = command[command.index("--output") + 1]
    require(
        output.startswith(target + "/")
        and source + output[len(target) :] == FULL_ACCOUNT,
        "EXACT_ORIGINAL_OUTPUT_MAPPING_REQUIRED",
    )
    return {
        "container": row["Id"],
        "image": row["Image"],
        "inspect_sha256": value["producer_runtime_sha256"],
    }

# Apply original calendar checks through an explicit new reviewed-session module.
def calendar_admission(archives, profile):
    import numpy as np
    from backend.market import capacity_original_calendar_v1 as calendar
    require(Path(calendar.__file__).resolve().parents[2] == archives.source_root, "CAPACITY_CALENDAR_IMPORT_ROOT_REQUIRED")
    completion = archives.completion
    first, through = completion["first"], completion["through"]
    require(
        (first, through)
        == (
            ("2019-03-01", "2026-10-12")
            if profile == "original-full-27471"
            else ("2019-03-01", "2019-03-04")
        ),
        "EXACT_ORIGINAL_PROFILE_CALENDAR_REQUIRED",
    )
    years, days = calendar.reviewed_sessions()
    dates = np.arange(
        np.datetime64(first), np.datetime64(through) + np.timedelta64(1, "D")
    )
    require(
        all(day.astype(object).year in years for day in dates),
        "REVIEWED_CALENDAR_COVERAGE_REQUIRED",
    )
    expected = list(map(str, dates[np.is_busday(dates, busdaycal=days)]))
    require(
        [row["session"] for row in completion["sessions"]] == expected,
        "COMPLETE_EXCHANGE_SESSION_SEQUENCE_REQUIRED",
    )
    for path in (
        calendar.HOLIDAYS_PATH,
        calendar.HISTORICAL_SESSIONS_PATH,
        calendar.EARLY_CLOSES_PATH,
    ):
        relative = str(path.relative_to(archives.source_root))
        authenticate_file(path, archives.sources[relative])
    return {
        "sessions": len(expected),
        "first": first,
        "through": through,
        "sha256": digest(expected),
    }

# Check the unchanged exact native package versions without fitting or loading a model.
def native_packages():
    import numpy as np
    import sklearn
    require(np.__version__ == '2.5.3' and sklearn.__version__ == '1.9.1', 'EXACT_NATIVE_NUMERIC_PACKAGES_REQUIRED')
    return {'numpy': np.__version__, 'sklearn': sklearn.__version__, 'model_or_fit': False}
