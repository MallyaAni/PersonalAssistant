"""Audit an immutable completed original account; never publish or replay it."""

import argparse
import json
import os
import socket
from dataclasses import fields
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import numpy as np
import sklearn

from backend.agents.trading.desk import paper
from backend.market import calendar
from backend.market import live_model_history_audit_inputs as loader
from backend.market import live_model_history_input_auth as byte_auth
from backend.market.live_model_history_receipts import require
from backend.market.live_model_history_stream_audit import (
    MAX_STATE_BYTES,
    InitialReceipts,
    OriginalArchives,
    StreamAudit,
    authenticate_file,
    digest,
    pinned,
    strict_json,
)
from backend.market.live_policy_replay import plain

IMAGE = "sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237"
FULL_REVISION = "27471b9c61b958f759e9f48b80acaf60cdf75f2e"
FULL_CONTAINER = "1e8f440a3b5b75dcabd299f5eaba58c7929fb6f96bc822fdb46b641ecf3e598d"
PRODUCER_IMAGE = (
    "sha256:136ebb46b7912f20472a375a6b29f6efec4cf2fdca13d56cbffb86a1be697db2"
)
FULL_ACCOUNT = (
    "/home/animallya96/scratch/live-model-history-full-20261013-v1/output/account"
)
SCHEMA = "original-history-audit-invocation/1"


# Decode only an externally pinned invocation; it cannot select another model image.
def invocation(path, expected):
    value = strict_json(pinned(path, expected))
    fields = {
        "schema",
        "profile",
        "account",
        "market",
        "completion_sha256",
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


# Check the independently captured actual runtime before reading any model arrays.
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


# Authenticate every loaded audit module and all original Git source bytes separately.
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


# Bind the original producer's actual immutable image and output mount after completion.
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


# Compare the completed calendar with the independent reviewed exchange closures.
def calendar_admission(archives, profile):
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


# Hash every saved session and the actual final state outside model comparison.
def preserved_archives(archives):
    result = {}
    for row in archives.completion["sessions"]:
        path = archives.root / "sessions" / (row["session"] + ".json.gz")
        result[str(path)] = authenticate_file(path, row["sha256"])
    physical = paper.state_path(archives.root / "state")
    # The pinned completion authenticates the physical final state's JSON content.
    before = physical.stat()
    require(before.st_size <= MAX_STATE_BYTES, "FINAL_PHYSICAL_STATE_BOUND_REQUIRED")
    raw_sha256 = byte_auth.stream_file(physical, file_sha256(physical))["sha256"]
    raw = pinned(physical, raw_sha256, max_bytes=MAX_STATE_BYTES)
    require(
        digest(physical_state(raw)) == archives.ending_state,
        "FINAL_PHYSICAL_STATE_DIFFERS_FROM_COMPLETION",
    )
    result[str(physical)] = raw_sha256
    return result


# Decode only the original physical writer's nonfinite literals, not metadata JSON.
def physical_constant(value):
    return {"NaN": float("nan"), "Infinity": float("inf"), "-Infinity": -float("inf")}[
        value
    ]


# Apply the exact original export normalization after strict duplicate/schema checks.
def physical_state(raw):
    value = json.loads(
        raw,
        object_pairs_hook=byte_auth.unique,
        parse_float=byte_auth.finite,
        parse_constant=physical_constant,
    )
    require(
        type(value) is dict
        and set(value) == {field.name for field in fields(paper.PaperState)},
        "EXACT_ORIGINAL_PHYSICAL_STATE_SCHEMA_REQUIRED",
    )
    return plain(value)


# Obtain a bounded-memory first digest before binding final physical-state JSON content.
def file_sha256(path):
    result = sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(byte_auth.CHUNK_BYTES):
            result.update(block)
    return result.hexdigest()


# Run only the new streaming composition under explicit external identities and limits.
def audit(value):
    runtime = runtime_admission(value)
    parent = byte_auth.physical(value["proof_parent"])
    require(
        parent.is_dir() and parent.stat().st_uid == 1000 and not list(parent.iterdir()),
        "NEW_EMPTY_OWNED_PROOF_ROOT_REQUIRED",
    )
    destination = parent / "original-audit"
    destination.mkdir(mode=0o700, exist_ok=False)
    started = datetime.now(UTC)
    try:
        require(
            np.__version__ == "2.5.3" and sklearn.__version__ == "1.9.1",
            "EXACT_NATIVE_NUMERIC_PACKAGES_REQUIRED",
        )
        archives = OriginalArchives(
            value["account"],
            value["completion_sha256"],
            value["initial_sha256"],
            value["manifest"],
            value["manifest_sha256"],
        )
        git = source_admission(value, archives)
        producer = producer_admission(value)
        calendar_proof = calendar_admission(archives, value["profile"])
        preserved = preserved_archives(archives)
        pins = byte_auth.Pins(
            value["profile"],
            value["completion_sha256"],
            value["manifest_sha256"],
            value["execution_sha256"],
        )
        bytes_before = byte_auth.authenticate(
            Path(value["account"]) / "completion.json",
            value["manifest"],
            value["execution"],
            pins,
        )
        loaded = loader.load(archives, value["market"], observed_at=started)
        stream = StreamAudit(
            archives,
            value["market"],
            loaded.panel,
            loaded.raw,
            loaded.reader,
            loaded.holding,
            loaded.overlay,
            verified_at=started,
        )
        initial = None
        if value["initial_receipts"] is not None:
            initial = InitialReceipts(
                value["initial_receipts"], value["initial_receipts_sha256"]
            )
        else:
            require(
                value["initial_receipts_sha256"] is None,
                "NO_FABRICATED_INITIAL_RECEIPT_SELECTOR",
            )
        numerical = stream.verify(initial_receipts=initial)
        require(
            preserved_archives(archives) == preserved,
            "ORIGINAL_SESSION_OR_FINAL_STATE_CHANGED",
        )
        bytes_after = byte_auth.authenticate(
            Path(value["account"]) / "completion.json",
            value["manifest"],
            value["execution"],
            pins,
        )
        require(
            bytes_before == bytes_after, "COMPLETE_INPUT_BYTES_CHANGED_DURING_AUDIT"
        )
        for name, expected in value["audit_source_sha256"].items():
            authenticate_file(Path(__file__).resolve().parents[2] / name, expected)
        result = {
            "status": "VERIFIED_ORIGINAL_STREAM_AND_INPUT_BYTES_ONLY",
            "profile": value["profile"],
            "test_profile": value["profile"] != "original-full-27471",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "runtime": runtime,
            "producer_runtime": producer,
            "source_git_authentication": git,
            "completion_sha256": value["completion_sha256"],
            "initial_sha256": value["initial_sha256"],
            "source_manifest_sha256": value["manifest_sha256"],
            "execution_receipt_sha256": value["execution_sha256"],
            "audit_source_sha256": value["audit_source_sha256"],
            "calendar": calendar_proof,
            "input_bytes": bytes_before,
            "stream": numerical,
            "preserved_archives": preserved,
            "numpy": np.__version__,
            "sklearn": sklearn.__version__,
            "full_fixed_calibration_dates": len(loaded.reader._parent._frozen_dates),
            "risk_bank_rows": len(loaded.reader._parent._bank["dates"]),
            "original_config_sha256": loader.ORIGINAL_CONFIG_SHA256,
            "current_live_timing_parity": "FAILED_SEPARATE_ORIGINAL_PATH_CONTRACT",
            "publication_barrier": "CLOSED",
            "historical_publication_authorized": False,
            "new_account_or_orders": False,
            "base_models_fitted": 0,
        }
        (destination / "proof.json").write_text(
            json.dumps(result, indent=2, allow_nan=False) + "\n"
        )
        return result
    except Exception as exc:
        (destination / "failure.json").write_text(
            json.dumps(
                {
                    "status": "FAILED_ORIGINAL_AUDIT",
                    "error": str(exc),
                    "started_at": started.isoformat(),
                    "publication_barrier": "CLOSED",
                },
                indent=2,
            )
            + "\n"
        )
        raise


# Require an explicit independently reviewed invocation digest, with no default account.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--invocation", type=Path, required=True)
    parser.add_argument("--invocation-sha256", required=True)
    args = parser.parse_args()
    result = audit(invocation(args.invocation, args.invocation_sha256))
    print(
        json.dumps(
            {
                "status": result["status"],
                "profile": result["profile"],
                "publication_barrier": result["publication_barrier"],
            }
        )
    )


if __name__ == "__main__":
    main()
