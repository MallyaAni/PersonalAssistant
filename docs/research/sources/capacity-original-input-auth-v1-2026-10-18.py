# SOURCE ONLY: separately versioned capacity data interface; all bodies UNRUN.
# This is a new module/type identity, not the original verified reader or receipt.
"""Authenticate original input bytes without interpreting or approving a model."""

import json
import math
import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

from backend.market import capacity_original_history_json_v1 as streamed

CHUNK_BYTES = 1024 * 1024
METADATA_BYTES = 16 * 1024 * 1024
COMPLETION_BYTES = 256 * 1024 * 1024
PROFILES = {
    "original-full-27471": (
        "27471b9c61b958f759e9f48b80acaf60cdf75f2e",
        2431,
    ),
    "complete-private-v10": (
        "6792cd1e9dc076ec0be485cf749fe251f738ff4e",
        2428,
    ),
}


# Reject evidence that cannot support exact byte authentication.
def require(condition, reason):
    if not condition:
        raise ValueError(reason)


# Admit only an explicit lower-case SHA256 identity.
def digest_value(value):
    require(
        type(value) is str
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value),
        "EXACT_EXTERNAL_SHA256_REQUIRED",
    )
    return value


# Reject ambiguous metadata instead of retaining the last repeated member.
def unique(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, "DUPLICATE_JSON_MEMBER")
        result[name] = value
    return result


# Reject nonfinite JSON constants before they can become admitted metadata.
def constant(value):
    raise ValueError("NONFINITE_JSON_CONSTANT")


# Reject exponent overflow as well as explicit nonfinite constants.
def finite(value):
    number = float(value)
    require(math.isfinite(number), "NONFINITE_JSON_NUMBER")
    return number


# Parse externally authenticated immutable metadata bytes strictly.
def decode(raw):
    require(type(raw) is bytes, "IMMUTABLE_METADATA_BYTES_REQUIRED")
    return json.loads(
        raw, object_pairs_hook=unique, parse_constant=constant, parse_float=finite
    )


# Require canonical paths with no traversal or alternate textual alias.
def canonical(value, *, absolute):
    require(type(value) is str and bool(value), "EXACT_PATH_REQUIRED")
    path = PurePosixPath(value)
    require(
        path.is_absolute() == absolute
        and str(path) == value
        and ".." not in path.parts
        and value != "/"
        and value != ".",
        "NONCANONICAL_OR_TRAVERSING_PATH",
    )
    return path


# Refuse symlinked ancestors and missing paths rather than resolving aliases.
def physical(path):
    path = Path(path)
    canonical(str(path), absolute=True)
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError as exc:
            raise ValueError("MISSING_ORIGINAL_INPUT: " + str(path)) from exc
        require(not stat.S_ISLNK(info.st_mode), "SYMLINK_ORIGINAL_INPUT")
    return path


# Identify a regular file so concurrent replacement cannot masquerade as a read.
def identity(info):
    require(stat.S_ISREG(info.st_mode), "REGULAR_ORIGINAL_FILE_REQUIRED")
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


# Check unchanged descriptors and all path components after streaming bytes.
def unchanged(stream, path, before):
    require(
        identity(os.fstat(stream.fileno())) == before
        and identity(physical(path).stat()) == before,
        "ORIGINAL_INPUT_CHANGED_DURING_READ",
    )


# Hash a regular file in bounded chunks without importing array/model libraries.
def stream_file(path, expected):
    digest_value(expected)
    path = physical(path)
    before = identity(path.stat())
    result = sha256()
    with path.open("rb") as stream:
        require(identity(os.fstat(stream.fileno())) == before, "INPUT_REPLACED")
        while block := stream.read(CHUNK_BYTES):
            result.update(block)
        unchanged(stream, path, before)
    require(result.hexdigest() == expected, "ORIGINAL_INPUT_DIGEST_MISMATCH")
    return {"sha256": expected, "bytes": before[2], "identity": list(before)}


# Bound metadata before allocation and reject growth or replacement while reading.
def metadata(path, expected, *, limit=METADATA_BYTES):
    digest_value(expected)
    path = physical(path)
    before = identity(path.stat())
    require(before[2] <= limit, "ORIGINAL_METADATA_TOO_LARGE")
    with path.open("rb") as stream:
        require(identity(os.fstat(stream.fileno())) == before, "INPUT_REPLACED")
        raw = stream.read(limit + 1)
        require(len(raw) <= limit, "ORIGINAL_METADATA_GREW_BEYOND_BOUND")
        unchanged(stream, path, before)
    require(sha256(raw).hexdigest() == expected, "ORIGINAL_METADATA_DIGEST_MISMATCH")
    return raw


# Bind all external identities before any original metadata is consulted.
@dataclass(frozen=True, slots=True)
class Pins:
    profile: str
    completion_sha256: str
    manifest_sha256: str
    execution_sha256: str

    # Reject unknown profile labels and malformed independently reviewed hashes.
    def __post_init__(self):
        require(self.profile in PROFILES, "EXACT_ORIGINAL_PROFILE_REQUIRED")
        for value in (
            self.completion_sha256,
            self.manifest_sha256,
            self.execution_sha256,
        ):
            digest_value(value)


# Recover only explicit Docker bind mounts from the pinned original launch receipt.
def mounts_from_receipt(execution):
    require(type(execution) is dict, "ORIGINAL_EXECUTION_RECEIPT_REQUIRED")
    require(execution.get("real_orders") is False, "NONORDER_EXECUTION_REQUIRED")
    command = execution.get("command")
    require(
        type(command) is list
        and all(type(item) is str for item in command)
        and command[:2] == ["docker", "run"],
        "ORIGINAL_DOCKER_COMMAND_REQUIRED",
    )
    require("--mount" not in command, "UNSUPPORTED_MOUNT_SYNTAX")
    mounts = {}
    for index, value in enumerate(command):
        if value != "-v":
            continue
        require(index + 1 < len(command), "MISSING_MOUNT_ARGUMENT")
        pieces = command[index + 1].split(":")
        require(len(pieces) == 3, "EXPLICIT_BIND_MOUNT_REQUIRED")
        host, target, mode = pieces
        canonical(host, absolute=True)
        canonical(target, absolute=True)
        require(mode in ("ro", "rw"), "EXACT_MOUNT_MODE_REQUIRED")
        require(target not in mounts, "DUPLICATE_MOUNT_TARGET")
        mounts[target] = (host, mode)
    require(mounts.get("/app", (None, None))[1] == "ro", "READONLY_SOURCE_REQUIRED")
    return mounts


# Resolve one original container input through its longest exact read-only mount.
def mapped_input(name, mounts):
    canonical(name, absolute=True)
    matching = [
        target for target in mounts if name == target or name.startswith(target + "/")
    ]
    require(bool(matching), "UNMAPPED_ORIGINAL_INPUT")
    target = max(matching, key=len)
    host, mode = mounts[target]
    require(mode == "ro", "INPUT_FROM_WRITABLE_MOUNT")
    return Path(host + name[len(target) :])


# Reconstruct original container symlinks through its receipt-bound mount namespace.
def resolve_input(name, mounts):
    canonical(name, absolute=True)
    links = []
    seen = set()
    for _ in range(17):
        require(name not in seen, "CYCLIC_ORIGINAL_NAMESPACE_SYMLINK")
        seen.add(name)
        targets = [t for t in mounts if name == t or name.startswith(t + "/")]
        require(bool(targets), "UNMAPPED_ORIGINAL_INPUT")
        target = max(targets, key=len)
        host, mode = mounts[target]
        require(mode == "ro", "INPUT_FROM_WRITABLE_MOUNT")
        physical(host)
        suffix = PurePosixPath(name).relative_to(target).parts
        current = Path(host)
        for index, component in enumerate(suffix):
            current = current / component
            try:
                info = current.lstat()
            except FileNotFoundError as exc:
                raise ValueError("MISSING_ORIGINAL_INPUT: " + name) from exc
            if not stat.S_ISLNK(info.st_mode):
                continue
            text = os.readlink(current)
            canonical(text, absolute=text.startswith("/"))
            namespace_link = str(PurePosixPath(target).joinpath(*suffix[: index + 1]))
            destination = (
                PurePosixPath(text)
                if text.startswith("/")
                else PurePosixPath(namespace_link).parent / text
            )
            links.append(
                {
                    "namespace_path": namespace_link,
                    "host_path": str(current),
                    "target": text,
                    "identity": [
                        info.st_dev,
                        info.st_ino,
                        info.st_size,
                        info.st_mtime_ns,
                        info.st_ctime_ns,
                    ],
                }
            )
            name = str(destination.joinpath(*suffix[index + 1 :]))
            break
        else:
            return physical(current), links
    raise ValueError("ORIGINAL_NAMESPACE_SYMLINK_LIMIT")


# Verify sealed external maps completely at authentication acceptance boundaries.
def verify_sha_map(value):
    if type(value) is streamed.ShaMap:
        value.authenticate_contents()


# Authenticate every declared input and source twice, optionally using a sealed SHA map.
def authenticate(
    completion_path,
    manifest_path,
    execution_path,
    pins,
    *,
    external_inputs=False,
    scratch=None,
):
    require(type(pins) is Pins, "FROZEN_EXTERNAL_PINS_REQUIRED")
    if external_inputs:
        require(scratch is not None, "PRIVATE_INPUT_MAP_SCRATCH_REQUIRED")
        scratch = Path(scratch)
        scratch.mkdir(mode=0o700, parents=True, exist_ok=False)
    completion = streamed.read(
        completion_path,
        pins.completion_sha256,
        retain=False,
        directory=scratch,
        external_inputs=external_inputs,
    )
    manifest_raw = metadata(manifest_path, pins.manifest_sha256)
    execution_raw = metadata(execution_path, pins.execution_sha256)
    manifest, execution = map(decode, (manifest_raw, execution_raw))
    revision, source_count = PROFILES[pins.profile]
    require(
        completion.get("status") == "COMPLETED_UNVERIFIED_CURRENT_MODEL_ACCOUNT",
        "GENUINE_COMPLETE_REQUIRED",
    )
    require(
        type(execution.get("source_files")) is int
        and execution["source_files"] == source_count,
        "ORIGINAL_SOURCE_PROFILE_COUNT_MISMATCH",
    )
    files = manifest.get("files")
    require(
        type(files) is dict and len(files) == source_count,
        "COMPLETE_SOURCE_MANIFEST_REQUIRED",
    )
    if pins.profile == "complete-private-v10":
        require(manifest.get("base_revision") == revision, "BOUNDED_REVISION_MISMATCH")
    mounts = mounts_from_receipt(execution)
    inputs = completion.get("input_sha256")
    require(
        type(inputs) in (dict, streamed.ShaMap) and bool(inputs),
        "COMPLETE_INPUT_MANIFEST_REQUIRED",
    )
    verify_sha_map(inputs)
    requested = {}
    for name, expected in files.items():
        canonical(name, absolute=False)
        requested["source:" + name] = ("/app/" + name, expected)
    for name, expected in inputs.items():
        requested["input:" + name] = (name, expected)
    for name, expected in requested.values():
        digest_value(expected)
        resolve_input(name, mounts)
    records = {}
    for key, (name, expected) in requested.items():
        path, links = resolve_input(name, mounts)
        records[key] = {
            "path": str(path),
            "namespace_symlinks": links,
            **stream_file(path, expected),
        }
    for key, (name, expected) in requested.items():
        path, links = resolve_input(name, mounts)
        require(
            records[key]
            == {
                "path": str(path),
                "namespace_symlinks": links,
                **stream_file(path, expected),
            },
            "ORIGINAL_INPUT_IDENTITY_CHANGED_BETWEEN_PASSES",
        )
    for path, expected, raw, limit in (
        (manifest_path, pins.manifest_sha256, manifest_raw, METADATA_BYTES),
        (execution_path, pins.execution_sha256, execution_raw, METADATA_BYTES),
    ):
        require(metadata(path, expected, limit=limit) == raw, "METADATA_CHANGED")
    after_completion = streamed.read(
        completion_path,
        pins.completion_sha256,
        retain=False,
        directory=scratch,
        external_inputs=external_inputs,
    )
    require(
        after_completion == completion,
        "COMPLETION_METADATA_CHANGED",
    )
    verify_sha_map(inputs)
    verify_sha_map(after_completion["input_sha256"])
    return {
        "status": "INPUT_BYTES_AUTHENTICATED_ONLY",
        "profile": pins.profile,
        "declared_source_revision": revision,
        "source_revision_authenticated_by_git": False,
        "completion_sha256": pins.completion_sha256,
        "source_manifest_sha256": pins.manifest_sha256,
        "execution_receipt_sha256": pins.execution_sha256,
        "source_files": len(files),
        "input_files": len(inputs),
        "authenticated_bytes_per_pass": sum(row["bytes"] for row in records.values()),
        "passes": 2,
        "files": records,
        "model_or_timing_acceptance": "UNVERIFIED",
        "current_live_timing_parity": "FAILED",
        "publication": "CLOSED",
    }
