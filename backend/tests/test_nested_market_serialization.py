"""Independent byte and bounded-buffering contracts for nested study archives."""

import copy
import hashlib
import json
import tracemalloc
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from backend.market import nested_market_study as study
from backend.market.research_journal import _encode
from backend.market.research_journal_replay import verify_archive, verify_snapshot
from backend.tests.test_nested_market_study import _case

CHUNK_BYTES = 65536


# Retain the pre-streaming canonical byte contract independently of the new helpers.
def _canonical(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


@dataclass
class PackedExample:
    matrix: np.ndarray
    when: np.datetime64
    score: float


# Combine array ownership, scalar conversion and nonfinite metadata in one fixture.
def _pack_example():
    matrix = np.arange(24, dtype=np.float64).reshape(4, 6)[::-1, ::2]
    matrix[0, 1] = np.nan
    payload = {
        "record": PackedExample(
            matrix, np.datetime64("2026-09-24"), np.float64(np.nan)
        ),
        "z": (np.int64(4), float("inf"), float("-inf"), -0.0),
    }
    expected = {
        "record": {
            "matrix": {
                "array_ref": "array_00000",
                "shape": [4, 3],
                "dtype": matrix.dtype.str,
                "sha256": hashlib.sha256(matrix.tobytes(order="C")).hexdigest(),
            },
            "when": {"daily_date": "2026-09-24"},
            "score": {"nonfinite_float": "nan"},
        },
        "z": [4, {"nonfinite_float": "inf"}, {"nonfinite_float": "-inf"}, -0.0],
    }
    return payload, matrix, expected


class BoundedReader:
    # Observe every byte request, optionally returning less than the requested count.
    def __init__(self, stream, requests, fragment):
        self.stream, self.requests, self.fragment = stream, requests, fragment

    # Keep the wrapped file under the same context-managed lifetime as a normal read.
    def __enter__(self):
        self.stream.__enter__()
        return self

    # Close the actual file and preserve its normal exception propagation.
    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    # Reject unbounded reads and retain the exact bytes returned to the caller.
    def read(self, size=-1):
        assert 0 < size <= CHUNK_BYTES
        body = self.stream.read(min(size, self.fragment) if self.fragment else size)
        self.requests.append((size, len(body)))
        return body


# Retain one small artificial study; never load or refit historical market evidence.
@pytest.fixture(scope="module")
def synthetic_study():
    report, inputs, protocol = _case()
    return study.run(report, inputs, protocol=protocol)


# The public archive path must not allocate full byte buffers for its root artifacts.
def test_archive_streams_root_artifacts_instead_of_reading_whole_files(
    synthetic_study, tmp_path, monkeypatch
):
    destination = tmp_path / "streamed-study"
    original = Path.read_bytes
    artifacts = {"arrays.npz", "evidence.json", "summary.json"}

    # Permit source and journal reads while rejecting the reproduced root boundary.
    def reject_whole_artifact(path):
        assert not (path.parent == destination and path.name in artifacts), (
            f"Archive must stream root artifact: {path.name}"
        )
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", reject_whole_artifact)
    receipt = study.archive(synthetic_study, destination)
    assert receipt == destination / "manifest.json"
    assert receipt.is_file()


# Streaming must preserve canonical spelling, ordering, escaping and terminal newline.
@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        [],
        {"z": 1, "a": [False, None, {"b": 2, "a": 3}]},
        {"minus_zero": -0.0, "tiny": 5e-324, "huge": 1.7976931348623157e308},
        {"unicode": "雪 😀", "controls": "\n\t\u0000", "surrogate": "\ud800"},
        {"nested": ([1, 2], (3, {"quote": '"\\'})), "big_int": 10**100},
        "a" * (CHUNK_BYTES * 3 + 7),
        "雪😀" * CHUNK_BYTES,
    ],
    ids=[
        "null",
        "boolean",
        "empty",
        "ordering",
        "floats",
        "escapes",
        "nested",
        "long_ascii",
        "long_escaped",
    ],
)
def test_json_chunks_and_digest_match_original_canonical_bytes(value):
    expected = _canonical(value)
    assert expected == _encode(value)
    chunks = list(study._json_chunks(value))
    assert chunks
    assert all(type(part) is bytes and 0 < len(part) <= CHUNK_BYTES for part in chunks)
    assert b"".join(chunks) == expected
    assert study._json_digest(value) == hashlib.sha256(expected).hexdigest()


# Invalid JSON numbers must still fail rather than receive nonstandard literal tokens.
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_json_streaming_refuses_nonfinite_numbers_before_a_digest_is_returned(value):
    with pytest.raises(ValueError, match="Out of range float values"):
        list(study._json_chunks({"number": value}))
    with pytest.raises(ValueError, match="Out of range float values"):
        study._json_digest({"number": value})


# Packing preserves typed metadata and owns array bytes before canonical serialization.
def test_packed_dataclass_arrays_and_nonfinite_sentinels_keep_their_exact_contract():
    payload, matrix, expected = _pack_example()
    arrays = {}
    packed = study._pack(payload, arrays, {})
    assert packed == expected
    assert list(arrays) == ["array_00000"]
    assert not np.shares_memory(arrays["array_00000"], matrix)
    np.testing.assert_array_equal(arrays["array_00000"], matrix)
    assert b"".join(study._json_chunks(packed)) == _canonical(expected)
    assert (
        study._json_digest(packed) == hashlib.sha256(_canonical(expected)).hexdigest()
    )


# The complete evidence digest keeps hash-based journals and excludes only its receipt.
def test_evidence_digest_matches_the_pre_streaming_formula(synthetic_study):
    evidence = copy.deepcopy(synthetic_study)
    payload, matrix, _ = _pack_example()
    evidence["serialization_fixture"] = payload
    content = {
        key: value for key, value in evidence.items() if key != "evidence_sha256"
    }
    references = {
        id(snapshot): "sha256:" + hashlib.sha256(_canonical(snapshot)).hexdigest()
        for _, snapshot in study._journals(evidence)
    }
    expected = hashlib.sha256(
        _canonical(study._pack(content, {}, references))
    ).hexdigest()
    assert study._evidence_digest(evidence) == expected
    evidence["evidence_sha256"] = "not part of its own digest"
    assert study._evidence_digest(evidence) == expected
    matrix[0, 0] += 1
    assert study._evidence_digest(evidence) != expected


# File receipts count actual short reads and never infer byte counts from a stat call.
@pytest.mark.parametrize(
    ("size", "fragment"), [(0, None), (177, 7), (CHUNK_BYTES * 3 + 9, None)]
)
def test_file_receipt_uses_bounded_actual_reads(tmp_path, monkeypatch, size, fragment):
    target = tmp_path / "artifact.bin"
    body = (b"sample\x00\xff" * ((size + 7) // 8))[:size]
    target.write_bytes(body)
    original, original_stat = Path.open, Path.stat
    requests = []

    # Wrap only this artifact, leaving unrelated fixture or interpreter reads alone.
    def open_bounded(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return BoundedReader(stream, requests, fragment) if path == target else stream

    # A stat-based byte count would conceal truncated or short actual reads.
    def forbidden_stat(path, *args, **kwargs):
        if path == target:
            pytest.fail("File receipt must count actual read bytes, not stat metadata")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_bounded)
    monkeypatch.setattr(Path, "stat", forbidden_stat)
    receipt = study._file_receipt(target)
    assert receipt == {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    assert requests
    assert sum(returned for _, returned in requests) == len(body)
    assert requests[-1][1] == 0


# A missing artifact cannot receive a fabricated empty-file checksum receipt.
def test_file_receipt_refuses_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        study._file_receipt(tmp_path / "missing")


# Exclusive JSON writing records precisely the persisted canonical bytes and hash.
def test_json_writer_matches_bytes_and_refuses_overwrite(tmp_path):
    path = tmp_path / "payload.json"
    value = {"z": "雪", "a": [1, -0.0, None]}
    manifest = {}
    study._write_json(path, value, tmp_path, manifest)
    body = _canonical(value)
    assert path.read_bytes() == body
    assert manifest == {
        "payload.json": {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    }
    saved = copy.deepcopy(manifest)
    with pytest.raises(FileExistsError):
        study._write_json(path, {"replacement": True}, tmp_path, manifest)
    assert path.read_bytes() == body
    assert manifest == saved


# Interrupted serialization retains its partial file but cannot register success.
def test_json_writer_retains_partial_file_without_manifest_entry(tmp_path, monkeypatch):
    target = tmp_path / "partial.json"
    manifest = {}

    # Fail after one observable write to exercise the actual interrupted-file boundary.
    def interrupted_chunks(value):
        yield b"{"
        raise OSError("synthetic serialization interruption")

    monkeypatch.setattr(study, "_json_chunks", interrupted_chunks)
    with pytest.raises(OSError, match="synthetic serialization interruption"):
        study._write_json(target, {}, tmp_path, manifest)
    assert target.read_bytes() == b"{"
    assert manifest == {}
    with pytest.raises(FileExistsError):
        study._write_json(target, {}, tmp_path, manifest)
    assert target.read_bytes() == b"{"


# Short writes and failed close operations cannot register a completed JSON artifact.
@pytest.mark.parametrize("failure", ["short_write", "close"])
def test_json_writer_refuses_incomplete_filesystem_writes(
    tmp_path, monkeypatch, failure
):
    target = tmp_path / "failed-write.json"
    manifest = {}
    original = Path.open

    class FaultingWriter:
        # Own the normal file while exposing a chosen filesystem failure.
        def __init__(self, stream):
            self.stream = stream

        # Keep the write in a real file rather than an in-memory success stub.
        def __enter__(self):
            self.stream.__enter__()
            return self

        # Surface a close failure only after the file's real close has completed.
        def __exit__(self, *args):
            result = self.stream.__exit__(*args)
            if failure == "close":
                raise OSError("synthetic close failure")
            return result

        # Write fewer bytes than requested when exercising the short-write guard.
        def write(self, body):
            return self.stream.write(body[:-1] if failure == "short_write" else body)

    # Alter only the new output's exclusive writer, never unrelated reads.
    def open_faulting(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return FaultingWriter(stream) if path == target and args == ("xb",) else stream

    monkeypatch.setattr(Path, "open", open_faulting)
    with pytest.raises(OSError, match="Incomplete study JSON write|synthetic close"):
        study._write_json(target, {"test": True}, tmp_path, manifest)
    assert target.is_file()
    assert manifest == {}


# Additional encoder memory stays bounded for large collections of small JSON scalars.
@pytest.mark.parametrize("operation", ["digest", "write"])
def test_large_json_uses_bounded_document_buffers(tmp_path, operation):
    value = {"rows": ["abcdef0123456789" * 64] * 8192}
    expected = hashlib.sha256(_canonical(value)).hexdigest()
    target = tmp_path / "large.json"
    manifest = {}
    tracemalloc.start()
    try:
        if operation == "digest":
            actual = study._json_digest(value)
        else:
            study._write_json(target, value, tmp_path, manifest)
            actual = manifest["large.json"]["sha256"]
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert actual == expected
    assert peak < 2 * 1024 * 1024, "Whole-document JSON buffering regressed"
    if operation == "write":
        assert study._file_receipt(target) == manifest["large.json"]


# Same-size corruption, appended bytes and truncation still prevent final publication.
@pytest.mark.parametrize("corruption", ["same_size", "append", "truncate"])
def test_archive_readback_rejects_altered_artifact(
    synthetic_study, tmp_path, monkeypatch, corruption
):
    destination = tmp_path / "corrupt-study"
    target = destination / "summary.json"
    original = study._file_receipt
    changed = []

    # Corrupt only a completed synthetic artifact immediately before its readback.
    def corrupt_before_readback(path):
        if path == target and not changed:
            body = path.read_bytes()
            altered = {
                "same_size": b"!" + body[1:],
                "append": body + b" ",
                "truncate": body[:-1],
            }[corruption]
            path.write_bytes(altered)
            changed.append(True)
        return original(path)

    monkeypatch.setattr(study, "_file_receipt", corrupt_before_readback)
    with pytest.raises(ValueError, match="Archive readback mismatch: summary.json"):
        study.archive(synthetic_study, destination)
    assert changed == [True]
    assert not (destination / "manifest.json").exists()
    assert target.is_file()
    with pytest.raises(ValueError, match="must be new"):
        study.archive(synthetic_study, destination)


# Summary mutations before or during archival must remain bound by the evidence digest.
@pytest.mark.parametrize("when", ["before", "during"])
def test_archive_preserves_evidence_mutation_guards(
    synthetic_study, tmp_path, monkeypatch, when
):
    evidence = copy.deepcopy(synthetic_study)
    destination = tmp_path / "mutated-evidence"
    if when == "before":
        evidence["unexpected_metadata"] = True
    else:
        original = study._write_json

        # Change metadata only after the initial digest and summary write have passed.
        def mutate_after_write(path, value, root, manifest):
            original(path, value, root, manifest)
            if path == destination / "summary.json":
                evidence["unexpected_metadata"] = True

        monkeypatch.setattr(study, "_write_json", mutate_after_write)
    with pytest.raises(ValueError, match="Study evidence changed"):
        study.archive(evidence, destination)
    assert not (destination / "manifest.json").exists()
    assert destination.exists() == (when == "during")


# Source revision guards still reject drift before output and before final publication.
@pytest.mark.parametrize("when", ["before", "during"])
def test_archive_preserves_source_mutation_guards(
    synthetic_study, tmp_path, monkeypatch, when
):
    destination = tmp_path / "mutated-source"
    original = study._source_hashes
    calls = []

    # Change only the attested source hash at the chosen guard, never an actual file.
    def changed_source_hashes():
        calls.append(True)
        hashes = original()
        if when == "before" or len(calls) > 1:
            hashes[next(iter(hashes))] = "0" * 64
        return hashes

    monkeypatch.setattr(study, "_source_hashes", changed_source_hashes)
    with pytest.raises(ValueError, match="Exercised source changed"):
        study.archive(synthetic_study, destination)
    assert not (destination / "manifest.json").exists()
    assert destination.exists() == (when == "during")


# Real synthetic archives preserve every JSON byte, array value and replayed ledger.
def test_streamed_synthetic_archive_matches_legacy_bytes_and_replays(
    synthetic_study, tmp_path
):
    destination = tmp_path / "complete-study"
    receipt_path = study.archive(synthetic_study, destination)
    receipt = json.loads(receipt_path.read_bytes())
    journals = study._journals(synthetic_study)
    paths = {id(snapshot): f"journals/{name}" for name, snapshot in journals}
    arrays = {}
    expected = {
        "evidence.json": study._pack(synthetic_study, arrays, paths),
        "summary.json": synthetic_study["summary"],
        "source-hashes.json": synthetic_study["source_hashes"],
    }
    for name, snapshot in journals:
        for field in ("events", "prices", "manifest"):
            expected[f"journals/{name}/{field}.json"] = snapshot[field]
        proof = verify_snapshot(snapshot)
        assert verify_archive(destination / "journals" / name) == proof
        expected[f"journals/{name}/verification.json"] = proof
    for name, value in expected.items():
        body = _canonical(value)
        assert (destination / name).read_bytes() == body
        assert receipt["files"][name] == {
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
    with np.load(destination / "arrays.npz", allow_pickle=False) as saved:
        assert set(saved.files) == set(arrays)
        for name, values in arrays.items():
            np.testing.assert_array_equal(saved[name], values)
    assert receipt_path.read_bytes() == _canonical(receipt)
    assert receipt["evidence_sha256"] == synthetic_study["evidence_sha256"]
    assert receipt["journal_count"] == 20
    assert receipt["file_count"] == len(receipt["files"])
    assert receipt["adoption_eligible"] is False
