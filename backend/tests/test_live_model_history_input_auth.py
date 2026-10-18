"""Prove byte-only input admission cannot silently resolve or skip evidence."""

import json
from hashlib import sha256
from pathlib import Path

import pytest

from backend.market import live_model_history_input_auth as auth


# Produce a canonical test evidence digest without numerical dependencies.
def digest(raw):
    return sha256(raw).hexdigest()


# Write small synthetic receipt bytes and return their exact external identity.
def write_json(path, value):
    raw = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)
    return digest(raw)


# Build a complete synthetic source-count fixture with no numerical input arrays.
@pytest.fixture
def cohort(tmp_path):
    source = tmp_path / "source"
    inputs = tmp_path / "inputs"
    output = tmp_path / "output"
    for root in (source, inputs, output):
        root.mkdir()
    files = {}
    for index in range(2428):
        name = f"source-{index}.txt"
        (source / name).write_bytes(b"original source")
        files[name] = digest(b"original source")
    (inputs / "unused.bin").write_bytes(b"not interpreted")
    completion = {
        "status": "COMPLETED_UNVERIFIED_CURRENT_MODEL_ACCOUNT",
        "input_sha256": {"/inputs/unused.bin": digest(b"not interpreted")},
    }
    manifest = {
        "base_revision": auth.PROFILES["complete-private-v10"][0],
        "files": files,
    }
    execution = {
        "source_files": 2428,
        "real_orders": False,
        "command": [
            "docker",
            "run",
            "-v",
            f"{source}:/app:ro",
            "-v",
            f"{inputs}:/inputs:ro",
            "-v",
            f"{output}:/results:rw",
        ],
    }
    paths = [
        tmp_path / name
        for name in ("completion.json", "manifest.json", "execution.json")
    ]
    return paths, completion, manifest, execution


# Bind synthetic metadata externally exactly as a reviewed caller would.
def run(cohort, profile="complete-private-v10"):
    paths, *values = cohort
    pins = auth.Pins(
        profile, *(write_json(p, v) for p, v in zip(paths, values, strict=True))
    )
    return auth.authenticate(*paths, pins)


# Require all source and unused input bytes in both unchanged authentication passes.
def test_all_bytes_are_authenticated(cohort):
    result = run(cohort)
    assert result["status"] == "INPUT_BYTES_AUTHENTICATED_ONLY"
    assert result["source_files"] == 2428
    assert result["input_files"] == 1
    assert len(result["files"]) == 2429
    assert result["passes"] == 2
    assert result["current_live_timing_parity"] == "FAILED"
    assert result["publication"] == "CLOSED"


# Sealed-map mode authenticates every source/input twice and retains identical receipts.
def test_external_input_map_preserves_all_authentication_receipts(cohort, tmp_path):
    expected = run(cohort)
    paths, *_ = cohort
    pins = auth.Pins(
        "complete-private-v10", *(digest(path.read_bytes()) for path in paths)
    )
    actual = auth.authenticate(
        *paths, pins, external_inputs=True, scratch=tmp_path / "map-auth"
    )
    assert actual == expected
    assert actual["input_files"] == 1
    assert len(actual["files"]) == 2429


# A bounded receipt cannot be relabelled as the original full source profile.
def test_full_and_bounded_profiles_are_distinct(cohort):
    with pytest.raises(ValueError, match="PROFILE_COUNT"):
        run(cohort, "original-full-27471")


# Refuse absent, changed, or unavailable inputs even when no model consumes them.
@pytest.mark.parametrize("mutation", ["missing", "wrong", "null", "missing-sentinel"])
def test_unused_corruption_fails(cohort, mutation):
    paths, completion, _, _ = cohort
    path = paths[0].parent / "inputs/unused.bin"
    if mutation == "missing":
        path.unlink()
    elif mutation == "wrong":
        path.write_bytes(b"corrupt")
    else:
        completion["input_sha256"]["/inputs/unused.bin"] = (
            None if mutation == "null" else "MISSING"
        )
    with pytest.raises(ValueError, match="MISSING|DIGEST|SHA256"):
        run(cohort)


# Reject an original source byte change even when it is unrelated to numerical calls.
def test_source_corruption_fails(cohort):
    paths = cohort[0]
    (paths[0].parent / "source/source-0.txt").write_bytes(b"changed source")
    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        run(cohort)


# Detect a namespace remap between passes even when replacement content is identical.
def test_changed_namespace_chain_fails(cohort, monkeypatch):
    paths, completion, _, execution = cohort
    root = paths[0].parent
    (root / "inputs/other.bin").write_bytes(b"not interpreted")
    link = root / "inputs/link"
    link.symlink_to("unused.bin")
    completion["input_sha256"] = {"/inputs/link": digest(b"not interpreted")}
    calls = 0
    original = auth.stream_file

    # Change the original symlink only after the complete first pass was captured.
    def remap(path, expected):
        nonlocal calls
        result = original(path, expected)
        calls += 1
        if calls == 2429:
            link.unlink()
            link.symlink_to("other.bin")
        return result

    monkeypatch.setattr(auth, "stream_file", remap)
    with pytest.raises(ValueError, match="BETWEEN_PASSES"):
        run(cohort)


# Actual metadata admission rejects duplicate members before interpreting completion.
def test_completion_duplicate_decoder(cohort):
    paths, completion, manifest, execution = cohort
    raw = json.dumps(completion).encode()
    raw = raw[:-1] + b',"input_sha256":{}}'
    paths[0].write_bytes(raw)
    pins = auth.Pins(
        "complete-private-v10",
        digest(raw),
        write_json(paths[1], manifest),
        write_json(paths[2], execution),
    )
    with pytest.raises(ValueError, match="DUPLICATE_JSON"):
        auth.authenticate(*paths, pins)


# Validate original mount syntax and reject shadowed, unmapped, or writable routes.
@pytest.mark.parametrize(
    ("extra", "name", "reason"),
    [
        (["-v", "/host:/inputs:ro"], "/inputs/a", "DUPLICATE"),
        ([], "/elsewhere/a", "UNMAPPED"),
        ([], "/results/a", "WRITABLE"),
        (["--mount", "x"], "/inputs/a", "UNSUPPORTED"),
    ],
)
def test_mount_admission(extra, name, reason, tmp_path):
    receipt = {
        "real_orders": False,
        "command": [
            "docker",
            "run",
            "-v",
            f"{tmp_path}:/app:ro",
            "-v",
            f"{tmp_path}:/inputs:ro",
            "-v",
            f"{tmp_path}:/results:rw",
            *extra,
        ],
    }
    with pytest.raises(ValueError, match=reason):
        auth.resolve_input(name, auth.mounts_from_receipt(receipt))


# Reproduce the genuine frozen absolute symlink in its original container namespace.
def test_receipt_namespace_symlink(tmp_path):
    private = tmp_path / "private"
    original = tmp_path / "original"
    private.mkdir()
    original.mkdir()
    (original / "bars").mkdir()
    (original / "bars/a").write_bytes(b"raw original bytes")
    (private / "bars").symlink_to("/original/bars")
    assert not (private / "bars/a").exists()
    resolved, links = auth.resolve_input(
        "/private/bars/a",
        {"/private": (str(private), "ro"), "/original": (str(original), "ro")},
    )
    assert resolved == original / "bars/a"
    assert links[0]["target"] == "/original/bars"
    assert auth.stream_file(resolved, digest(b"raw original bytes"))["bytes"] == 18


# Reject cycles, writable escapes, unknown mounts, and relative traversal aliases.
@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("/private/link", "CYCLIC"),
        ("/results/escape", "WRITABLE"),
        ("/unknown/escape", "UNMAPPED"),
        ("../escape", "TRAVERSING"),
    ],
)
def test_namespace_symlink_escape(tmp_path, target, reason):
    (tmp_path / "link").symlink_to(target)
    mounts = {"/private": (str(tmp_path), "ro"), "/results": (str(tmp_path), "rw")}
    with pytest.raises(ValueError, match=reason):
        auth.resolve_input("/private/link", mounts)


# A mount's host root cannot introduce an unrecorded host namespace alias.
def test_host_mount_symlink_fails(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real)
    with pytest.raises(ValueError, match="SYMLINK"):
        auth.resolve_input("/inputs/a", {"/inputs": (str(alias), "ro")})


# Reject malformed path identity before any original filesystem lookup.
@pytest.mark.parametrize("path", ["/inputs/../a", "/inputs//a", "/inputs/./a", "/"])
def test_path_shape(path):
    with pytest.raises(ValueError, match="NONCANONICAL|TRAVERSING"):
        auth.resolve_input(path, {})


# Reject duplicate members, nonfinite constants, and exponent overflow.
@pytest.mark.parametrize(
    "raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e999}']
)
def test_strict_metadata(raw):
    with pytest.raises(ValueError, match="DUPLICATE|NONFINITE"):
        auth.decode(raw)


# Enforce metadata size before opening or allocating the oversized body.
def test_metadata_bound_precedes_open(tmp_path, monkeypatch):
    path = tmp_path / "large"
    path.write_bytes(b"x" * 33)

    # Opening this oversized fixture would show the admission bound was too late.
    def forbidden(*args, **kwargs):
        raise AssertionError("oversized metadata opened")

    monkeypatch.setattr(Path, "open", forbidden)
    with pytest.raises(ValueError, match="TOO_LARGE"):
        auth.metadata(path, digest(b"x" * 33), limit=32)


# Stream large binaries in fixed-size chunks without whole-file convenience reads.
def test_hash_uses_bounded_chunks(tmp_path, monkeypatch):
    path = tmp_path / "binary"
    raw = b"x" * (2 * auth.CHUNK_BYTES + 9)
    path.write_bytes(raw)
    original = Path.open
    reads = []

    # Observe the real descriptor while rejecting any unbounded read size.
    class Observed:
        # Retain one actual opened file for the hash context.
        def __init__(self, stream):
            self.stream = stream

        # Enter the observed real descriptor.
        def __enter__(self):
            return self

        # Close the original descriptor normally.
        def __exit__(self, *args):
            self.stream.close()

        # Preserve real fstat identity checks.
        def fileno(self):
            return self.stream.fileno()

        # Reject unbounded reads and record the bounded chunk contract.
        def read(self, size):
            assert size == auth.CHUNK_BYTES
            reads.append(size)
            return self.stream.read(size)

    # Wrap only the file descriptor opened by the streaming function.
    def observed(self, *args, **kwargs):
        return Observed(original(self, *args, **kwargs))

    monkeypatch.setattr(Path, "open", observed)
    assert auth.stream_file(path, digest(raw))["bytes"] == len(raw)
    assert len(reads) == 4


# Reject file growth after its first streamed block even when initial bytes match.
def test_changed_file_rejected(tmp_path, monkeypatch):
    path = tmp_path / "binary"
    path.write_bytes(b"original")
    original = auth.unchanged

    # Mutate one fixture exactly at the descriptor-versus-path stability boundary.
    def changed(stream, target, before):
        path.write_bytes(b"original plus new bytes")
        original(stream, target, before)

    monkeypatch.setattr(auth, "unchanged", changed)
    with pytest.raises(ValueError, match="CHANGED"):
        auth.stream_file(path, digest(b"original"))


# The implementation stays byte-only and does not import financial or array machinery.
def test_no_numerical_imports():
    import ast

    tree = ast.parse(Path(auth.__file__).read_text())
    roots = {
        (node.module if isinstance(node, ast.ImportFrom) else alias.name).split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    }
    assert roots <= {
        "json",
        "math",
        "os",
        "stat",
        "dataclasses",
        "hashlib",
        "pathlib",
        "backend",
    }
    internal = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module.startswith("backend")
    ]
    assert len(internal) == 1
    assert internal[0].module == "backend.market"
    assert [name.name for name in internal[0].names] == ["original_history_json"]
    helper = ast.parse(Path(auth.streamed.__file__).read_text())
    pure_roots = {
        (node.module if isinstance(node, ast.ImportFrom) else alias.name).split(".")[0]
        for node in ast.walk(helper)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    }
    assert pure_roots <= {
        "gzip",
        "io",
        "json",
        "math",
        "os",
        "stat",
        "sqlite3",
        "dataclasses",
        "hashlib",
        "pathlib",
        "tempfile",
    }
