"""Unused CURRENT-writer raw-byte rope; not JSON or financial admission.

This standalone primitive never imports paper, a model, a broker or the Store.
It preserves native NaN bytes opaquely. Local preallocated slots are the actual
published inodes; directory/SQLite headroom, a second host, native work files and
full lifecycle RAM are NOT reserved or proved here. No existing caps change.

Capture scans a complete stable source, but reuses immutable physical rows and
128-way manifest pages. Thus append storage is not a fresh flat prefix manifest
or shifted fixed-offset body copy. Each physical span is capped at 20 MiB.
An interrupted mutation retains a durable OPEN marker and cannot auto-resume.
Opaque verification never completes an operation or authenticates native effects.
Only the latest locally completed capture has a control-file completion binding.
Changing prefix/suffix spans are still copied as whole bounded spans; this is not
a full-horizon nonquadratic storage or dual-host/native adoption proof.
"""

import fcntl
import hashlib
import json
import math
import os
import stat
from contextlib import contextmanager
from pathlib import Path

READ = 64 * 1024
SPAN = 20 * 1024**2
META = 256 * 1024
FANOUT = 128
DEPTH = 6
VERSION = "current-native-physical-rope/1"
CURRENT = "3b72cd4e0bc15acd24432d501918c721685a5333"
IMAGE = "sha256:f6127ef3d56d9d5d858ee82fea0dbde95886d286288570aa6b590a6ab53d3272"
PAPER = "a8c5083f1828df7395164882ba877d5a134d55295d6a0cda0dcdc0047bcde42c"
SOURCE_MAP = "bfbcb6ece4ea500726e00abbb06fc2c84d63d386bb307958016915357aaef5b3"
PROFILE = {
    "source_revision": CURRENT,
    "backend_image": IMAGE,
    "broker_sha256": "c3d427e180e6b7527d3b666a450c6076b24e1cd75bfce1786852dced9eb2d616",
    "calendar_sha256": (
        "f5ceca3cd12484f66a13f75026c4466970c8810496bf7b7871f5973d749f05f4"
    ),
    "holding_config_sha256": (
        "f96a29777403f5f08623709b70f36b15300500065202acbd215cd43f3c99a588"
    ),
    "holding_release_sha256": (
        "1c1c6e9bcc7e9fa8d095f6ce5e6bf973c99ed19531e88c38a9aba5ed8410cd3e"
    ),
    "timing_config_sha256": (
        "d03339a3ad4b590ef8ed4205375d39d634df12a6fb49e290ab5b0f3642ea679a"
    ),
}
LIMIT_KEYS = {
    "span_bytes",
    "raw_bytes",
    "history_rows",
    "body_slots",
    "page_slots",
    "directory_headroom_bytes",
}


# Report missing resources or uncertain publication without inventing account data.
class PhysicalPause(ValueError):  # noqa: N818 -- Explicit same-source pause.
    """The caller must retain this private root and must not replay an effect."""


# Refuse unsafe framing, references and resources before silently dropping bytes.
def _require(condition, message):
    if not condition:
        raise PhysicalPause(message)


# Serialize only bounded finite checkpoint metadata, never the native paper body.
def _encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


# Keep duplicate or nonfinite metadata from acquiring an ambiguous interpretation.
def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate checkpoint metadata key")
        result[key] = value
    return result


# Reject nonfinite checkpoint declarations without inspecting opaque paper values.
def _constant(value):
    raise PhysicalPause("Nonfinite checkpoint metadata: " + value)


# Reject finite-looking exponent overflow before metadata decoding can produce inf.
def _float(value):
    result = float(value)
    _require(math.isfinite(result), "Nonfinite checkpoint metadata exponent")
    return result


# Decode small finite metadata only; this is not a native-paper JSON parser.
def _decoded(raw):
    _require(type(raw) is bytes and len(raw) < META, "Bounded metadata required")
    try:
        return json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=_constant,
            parse_float=_float,
        )
    except (ValueError, RecursionError, UnicodeError) as error:
        raise PhysicalPause("Invalid checkpoint metadata") from error


# Bind independently supplied profile hashes and immutable object references.
def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Require canonical lowercase full digests before constructing any object path.
def _digest(value):
    _require(
        type(value) is str
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value),
        "Full lowercase SHA256 required",
    )
    return value


# Keep explicit finite slot, byte, metadata and inode declarations separate from GETs.
def _limits(value):
    _require(type(value) is dict and set(value) == LIMIT_KEYS, "Exact limits required")
    _require(
        all(type(item) is int and 0 < item < 2**63 for item in value.values()),
        "Positive finite integer limits required",
    )
    _require(
        value["span_bytes"] <= SPAN
        and value["raw_bytes"] <= 1024**4
        and value["history_rows"] <= 1_000_000
        and value["body_slots"] <= 1_000_000
        and value["page_slots"] <= 1_000_000,
        "Declared physical checkpoint limit exceeds primitive caps",
    )
    return _decoded(_encoded(value))


# Reject symlink components rather than treating an alias as a private reservation.
def _path(value):
    path = Path(value).absolute()
    _require(
        path == path.resolve(), "Resolved path without symlink components required"
    )
    return path


# Distinguish immutable regular files from symlinks and special filesystem objects.
def _regular(path, *, private=False):
    _require(path.parent == path.parent.resolve(), "Nonsymlink parent path required")
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode), "Regular nonsymlink file required")
    if private:
        _require(stat.S_IMODE(info.st_mode) == 0o600, "Private file mode0600 required")
    return info


# Detect replacement or mutation across each bounded read of a source or CAS inode.
def _fingerprint(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


# Refuse sparse or substituted slots before writing their future published inodes.
def _extent(path, size, links):
    info = _regular(path, private=True)
    _require(
        info.st_size == size
        and info.st_nlink == links
        and info.st_blocks * 512 >= size,
        "Original physically allocated reservation required",
    )
    return info


# Refuse a substituted slot or lock before acting through its opened descriptor.
def _opened(path, descriptor, before):
    _require(
        _fingerprint(before)
        == _fingerprint(os.fstat(descriptor))
        == _fingerprint(_regular(path, private=True)),
        "Opened descriptor/path identity differs",
    )


# Keep a completed reserved write bound to its original inode and current pathname.
def _written(path, descriptor, before, size):
    after = os.fstat(descriptor)
    _require(
        (after.st_dev, after.st_ino, after.st_size)
        == (before.st_dev, before.st_ino, size)
        and _fingerprint(after) == _fingerprint(_regular(path, private=True)),
        "Written descriptor/path identity differs",
    )


# Sync published directory entries independently of the file content fsync.
def _sync(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# Preallocate the exact future body or metadata inode without a sparse-file fallback.
def _allocate(path, size):
    descriptor = os.open(
        path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            os.posix_fallocate(descriptor, 0, size)
        except (AttributeError, OSError) as error:
            raise PhysicalPause(
                "Physical allocation unsupported or unavailable"
            ) from error
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# Fill a fixed reserved control extent with length-framed finite metadata.
def _fixed_write(path, value):
    raw = _encoded(value)
    _require(len(raw) + 40 < META, "Control metadata cap reached")
    info = _extent(path, META, 1)
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        _require(
            _fingerprint(info) == _fingerprint(os.fstat(descriptor)),
            "Control replaced before write",
        )
        body = len(raw).to_bytes(8, "big") + hashlib.sha256(raw).digest() + raw
        _require(os.pwrite(descriptor, body, 0) == len(body), "Short reserved write")
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        final = _regular(path, private=True)
        _require(
            (after.st_dev, after.st_ino, after.st_size)
            == (info.st_dev, info.st_ino, META)
            and _fingerprint(after) == _fingerprint(final),
            "Control path changed during write",
        )
    finally:
        os.close(descriptor)


# Read a small reserved control file without loading its padding or native history.
def _fixed_read(path):
    info = _extent(path, META, 1)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        _require(
            _fingerprint(info) == _fingerprint(os.fstat(descriptor)),
            "Control replaced before read",
        )
        header = os.read(descriptor, 40)
        _require(len(header) == 40, "Truncated control header")
        length = int.from_bytes(header[:8], "big")
        _require(0 < length < META - 40, "Torn or excessive control length")
        raw = os.read(descriptor, length)
        _require(
            len(raw) == length and hashlib.sha256(raw).digest() == header[8:],
            "Torn or truncated control metadata",
        )
        _require(
            _fingerprint(info)
            == _fingerprint(os.fstat(descriptor))
            == _fingerprint(_regular(path, private=True)),
            "Control path changed during read",
        )
        return _decoded(raw)
    finally:
        os.close(descriptor)


# Admit only the exact CURRENT declaration and actual reviewed native writer bytes.
def _identity(identity, expected_sha256, writer):
    raw = _encoded(identity)
    _require(
        _sha(raw) == _digest(expected_sha256), "Externally pinned identity differs"
    )
    _require(
        type(identity) is dict and set(identity) == {*PROFILE, "source_sha256"},
        "Exact CURRENT identity schema required",
    )
    _require(
        all(identity[key] == value for key, value in PROFILE.items()),
        "CURRENT profile differs",
    )
    sources = identity["source_sha256"]
    _require(
        type(sources) is dict
        and len(sources) == 31
        and _sha(_encoded(sources)) == SOURCE_MAP
        and sources.get("backend/agents/trading/desk/paper.py") == PAPER,
        "Exact CURRENT31 source map required",
    )
    path = _path(writer)
    info = _regular(path)
    _require(info.st_size < META, "Bounded writer source required")
    with path.open("rb") as handle:
        actual = handle.read(META)
        _require(
            _fingerprint(info) == _fingerprint(os.fstat(handle.fileno())),
            "Writer changed",
        )
    _require(_sha(actual) == PAPER, "Actual CURRENT writer bytes differ")
    _require(_fingerprint(info) == _fingerprint(path.lstat()), "Writer replaced")
    return _decoded(raw)


# Recompute the complete fixed local file reservation, independently of header claims.
def _reservation(limits):
    return {
        "reserved_file_bytes": (
            2 * META
            + 4096
            + limits["raw_bytes"]
            + limits["body_slots"] * limits["span_bytes"]
            + limits["page_slots"] * META
        ),
        "reserved_file_inodes": 4 + limits["body_slots"] + limits["page_slots"],
    }


# Refuse altered header schemas, resource arithmetic or unsupported adoption claims.
def _header(value, identity_sha256, writer):
    expected = {
        "version",
        "scope",
        "identity",
        "identity_sha256",
        "primitive_sha256",
        "limits",
        "reserved_file_bytes",
        "reserved_file_inodes",
        "directory_headroom_reserved",
        "dual_host_reserved",
        "native_work_reserved",
    }
    _require(
        type(value) is dict and set(value) == expected,
        "Exact local header schema required",
    )
    _require(
        value["version"] == VERSION
        and value["scope"] == "OPAQUE_BYTES_LOCAL_ONLY"
        and value["primitive_sha256"] == _sha(Path(__file__).read_bytes())
        and value["identity_sha256"] == _digest(identity_sha256),
        "Reserved checkpoint source identity differs",
    )
    _require(
        all(
            value[name] is False
            for name in (
                "directory_headroom_reserved",
                "dual_host_reserved",
                "native_work_reserved",
            )
        ),
        "Unsupported reservation or adoption claim",
    )
    limits = _limits(value["limits"])
    _require(
        all(
            type(value[key]) is int and value[key] == count
            for key, count in _reservation(limits).items()
        ),
        "Reserved byte/inode arithmetic differs",
    )
    _identity(value["identity"], identity_sha256, writer)
    return value


# Validate the fixed small control state without inferring external operation success.
def _control(value, limits):
    _require(
        type(value) is dict
        and set(value)
        == {"operation", "body", "page", "captures", "restored", "completed_capture"}
        and (value["operation"] is None or type(value["operation"]) is str)
        and value["operation"] in {None, "CAPTURE", "RESTORE"}
        and type(value["restored"]) is bool
        and all(
            type(value[key]) is int and 0 <= value[key] < 2**63
            for key in ("body", "page", "captures")
        )
        and value["body"] <= limits["body_slots"]
        and value["page"] <= limits["page_slots"],
        "Reserved control state differs",
    )
    reference = value["completed_capture"]
    _require(
        (reference is None) == (value["captures"] == 0),
        "Local capture completion binding differs",
    )
    if reference is not None:
        _require(
            type(reference) is dict and set(reference) == {"sha256", "length"},
            "Completed capture reference required",
        )
        _digest(reference["sha256"])
        _require(
            type(reference["length"]) is int and 0 < reference["length"] < META,
            "Bounded completed capture reference required",
        )
    return value


# Assemble bounded physical lines from reads no larger than64KiB, including EOF.
def _lines(handle, limits):
    line, total = bytearray(), 0
    while fragment := handle.readline(READ):
        _require(
            type(fragment) is bytes and len(fragment) <= READ,
            "Bounded byte read required",
        )
        total += len(fragment)
        _require(total <= limits["raw_bytes"], "Raw checkpoint byte cap reached")
        line.extend(fragment)
        _require(len(line) <= limits["span_bytes"], "Native physical line cap reached")
        if not fragment.endswith(b"\n"):
            continue
        yield bytes(line)
        line.clear()
    if line:
        yield bytes(line)


# Validate native object-row delimiters without interpreting any row's JSON values.
def _row_line(state, current, previous_comma):
    if state == "row_start" or (state == "after_row" and previous_comma):
        _require(
            current in (b"    {\n", b"    {},\n", b"    {}\n"),
            "Native history object row required",
        )
        complete = current != b"    {\n"
        return "after_row" if complete else "row", complete, current == b"    {},\n"
    if state == "row":
        _require(
            current.startswith(b"      ") or current in (b"    },\n", b"    }\n"),
            "Malformed native row indentation",
        )
        complete = current in (b"    },\n", b"    }\n")
        return "after_row" if complete else "row", complete, current == b"    },\n"
    _require(
        state == "after_row" and current == b"  ],\n",
        "Native history closing framing required",
    )
    return "suffix", False, False


# Frame native indent2 history spans while preserving every original physical byte.
def _spans(handle, limits):
    state, span, rows, last = "prefix", bytearray(), 0, None
    previous_comma, first = False, True
    for current in _lines(handle, limits):
        if first:
            _require(current == b"{\n", "Native object framing required")
            first = False
        _require(
            len(span) + len(current) <= limits["span_bytes"],
            "Physical span cap reached",
        )
        span.extend(current)
        last = current
        if state == "prefix":
            if current in (b'  "history": [\n', b'  "history": [],\n'):
                yield "prefix", bytes(span)
                span.clear()
                state = "row_start" if current.endswith(b"[\n") else "suffix"
        elif state == "suffix":
            _require(
                current not in (b'  "history": [\n', b'  "history": [],\n'),
                "Duplicate native history framing",
            )
        else:
            state, complete, previous_comma = _row_line(state, current, previous_comma)
            if complete:
                rows += 1
                _require(rows <= limits["history_rows"], "History row cap reached")
                yield "row", bytes(span)
                span.clear()
    _require(state == "suffix" and last == b"}", "Native complete suffix required")
    yield "suffix", bytes(span)


# Reserve one local bounded raw-byte checkpoint namespace without native side effects.
def reserve(root, *, identity, identity_sha256, writer, limits):
    admitted = _identity(identity, identity_sha256, writer)
    limits = _limits(limits)
    root = _path(root)
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name in ("body-slots", "page-slots", "bodies", "pages"):
        (root / name).mkdir(mode=0o700)
    for name in ("header", "control"):
        _allocate(root / name, META)
    _allocate(root / "lock", 4096)
    _allocate(root / "restore", limits["raw_bytes"])
    for kind, count, size in (
        ("body", limits["body_slots"], limits["span_bytes"]),
        ("page", limits["page_slots"], META),
    ):
        for index in range(count):
            _allocate(root / f"{kind}-slots" / str(index), size)
        _sync(root / f"{kind}-slots")
    info = os.statvfs(root)
    _require(
        info.f_bavail * info.f_frsize >= limits["directory_headroom_bytes"]
        and info.f_favail >= 16,
        "Unreserved directory metadata headroom unavailable",
    )
    header = {
        "version": VERSION,
        "scope": "OPAQUE_BYTES_LOCAL_ONLY",
        "identity": admitted,
        "identity_sha256": identity_sha256,
        "primitive_sha256": _sha(Path(__file__).read_bytes()),
        "limits": limits,
        **_reservation(limits),
        "directory_headroom_reserved": False,
        "dual_host_reserved": False,
        "native_work_reserved": False,
    }
    _fixed_write(root / "header", header)
    _fixed_write(
        root / "control",
        {
            "operation": None,
            "body": 0,
            "page": 0,
            "captures": 0,
            "restored": False,
            "completed_capture": None,
        },
    )
    _sync(root)
    _sync(root.parent)
    return PhysicalCheckpoint(root, identity_sha256=identity_sha256, writer=writer)


# Keep capture/restore independent of simulation stages and numerical admission.
class PhysicalCheckpoint:
    # Reopen only the exact locally reserved source/profile and primitive version.
    def __init__(self, root, *, identity_sha256, writer):
        self.root = _path(root)
        info = self.root.lstat()
        _require(
            stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700,
            "Private root mode0700 required",
        )
        self.writer = _path(writer)
        self.header = _header(
            _fixed_read(self.root / "header"), identity_sha256, self.writer
        )
        self.limits = _limits(self.header["limits"])
        for name in ("body-slots", "page-slots", "bodies", "pages"):
            info = (self.root / name).lstat()
            _require(
                stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700,
                "Private nonsymlink directory required",
            )

    # Serialize mutations and retain uncertain OPEN operations across process crashes.
    @contextmanager
    def _locked(self, operation):
        _require(operation in {"CAPTURE", "RESTORE"}, "Known local operation required")
        path = self.root / "lock"
        info = _extent(path, 4096, 1)
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            _opened(path, descriptor, info)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise PhysicalPause("Checkpoint mutation already active") from error
            _opened(path, descriptor, info)
            self.control = _control(_fixed_read(self.root / "control"), self.limits)
            _require(
                self.control["operation"] is None,
                "Interrupted checkpoint operation remains OPEN",
            )
            self.control["operation"] = operation
            _fixed_write(self.root / "control", self.control)
            yield
            _opened(path, descriptor, info)
            self.control["operation"] = None
            _fixed_write(self.root / "control", self.control)
            _opened(path, descriptor, info)
        finally:
            os.close(descriptor)

    # Read and hash only an admitted used prefix of one padded immutable CAS inode.
    def _content(self, kind, reference):
        _require(
            type(reference) is dict and set(reference) == {"sha256", "length"},
            "Exact content reference required",
        )
        digest = _digest(reference["sha256"])
        size = reference["length"]
        cap = self.limits["span_bytes"] if kind == "body" else META - 1
        _require(
            type(size) is int and 0 < size <= cap, "Bounded content length required"
        )
        path = self.root / ("bodies" if kind == "body" else "pages") / digest
        info = _regular(path, private=True)
        _require(
            info.st_size == (self.limits["span_bytes"] if kind == "body" else META)
            and info.st_nlink >= 2,
            "Reserved immutable CAS inode differs",
        )
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        hashed, remaining = hashlib.sha256(), size
        try:
            while remaining:
                chunk = os.read(descriptor, min(READ, remaining))
                _require(chunk, "Truncated immutable content")
                remaining -= len(chunk)
                hashed.update(chunk)
                yield chunk
            _require(hashed.hexdigest() == digest, "Immutable content hash differs")
            _require(
                _fingerprint(info)
                == _fingerprint(os.fstat(descriptor))
                == _fingerprint(path.lstat()),
                "Immutable content changed",
            )
        finally:
            os.close(descriptor)

    # Publish a used preallocated slot by hardlink, never copying to fresh extents.
    def _put(self, kind, raw):
        cap = self.limits["span_bytes"] if kind == "body" else META - 1
        _require(
            type(raw) is bytes and 0 < len(raw) <= cap, "Immutable content cap reached"
        )
        reference = {"sha256": _sha(raw), "length": len(raw)}
        directory = self.root / ("bodies" if kind == "body" else "pages")
        destination = directory / reference["sha256"]
        if destination.exists() or destination.is_symlink():
            _require(
                b"".join(self._content(kind, reference)) == raw,
                "Conflicting CAS object",
            )
            return reference
        index = self.control[kind]
        _require(
            type(index) is int and 0 <= index < self.limits[f"{kind}_slots"],
            "Reserved slot quota reached",
        )
        source = self.root / f"{kind}-slots" / str(index)
        info = _extent(source, self.limits["span_bytes"] if kind == "body" else META, 1)
        descriptor = os.open(source, os.O_RDWR | os.O_NOFOLLOW)
        try:
            _opened(source, descriptor, info)
            _require(
                os.pwrite(descriptor, raw, 0) == len(raw),
                "Short reserved content write",
            )
            os.fsync(descriptor)
            _written(source, descriptor, info, info.st_size)
        finally:
            os.close(descriptor)
        os.link(source, destination, follow_symlinks=False)
        _sync(directory)
        _require(
            destination.lstat().st_ino == info.st_ino,
            "CAS publication copied the inode",
        )
        self.control[kind] = index + 1
        return reference

    # Store one bounded tree page whose unchanged descendants are content addressed.
    def _page(self, level, references):
        _require(
            0 <= level <= DEPTH and 1 <= len(references) <= FANOUT,
            "Bounded manifest page required",
        )
        value = {"version": VERSION, "level": level, "refs": references}
        return self._put("page", _encoded(value))

    # Frame a stable native file into an append-sharing ordered physical rope.
    def capture(self, source):
        _identity(self.header["identity"], self.header["identity_sha256"], self.writer)
        source = _path(source)
        before = _regular(source)
        _require(
            0 < before.st_size <= self.limits["raw_bytes"],
            "Source raw byte cap reached",
        )
        with self._locked("CAPTURE"):
            levels, hashed, count, rows, total = (
                [[] for _ in range(DEPTH + 1)],
                hashlib.sha256(),
                0,
                0,
                0,
            )
            descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as handle:
                for role, raw in _spans(handle, self.limits):
                    hashed.update(raw)
                    total += len(raw)
                    count += 1
                    rows += role == "row"
                    reference = {"role": role, "content": self._put("body", raw)}
                    self._push(levels, 0, reference)
                _require(
                    _fingerprint(before)
                    == _fingerprint(os.fstat(handle.fileno()))
                    == _fingerprint(source.lstat()),
                    "Source changed during capture",
                )
            _require(total == before.st_size, "Native framing omitted source bytes")
            tree = self._finish(levels)
            root = {
                "version": VERSION,
                "scope": "OPAQUE_NATIVE_BYTES_NOT_JSON_ADMISSION",
                "identity_sha256": self.header["identity_sha256"],
                "primitive_sha256": self.header["primitive_sha256"],
                "limits_sha256": _sha(_encoded(self.limits)),
                "raw_sha256": hashed.hexdigest(),
                "raw_bytes": total,
                "history_rows": rows,
                "spans": count,
                "tree": tree,
            }
            reference = self._put("page", _encoded(root))
            self.verify(reference)
            self.control["captures"] += 1
            self.control["completed_capture"] = reference
            return reference

    # Carry a complete fixed-fanout page upward without retaining a flat prefix list.
    def _push(self, levels, level, reference):
        _require(level <= DEPTH, "Manifest depth cap reached")
        levels[level].append(reference)
        if len(levels[level]) == FANOUT:
            page = {"page": self._page(level, levels[level])}
            levels[level] = []
            self._push(levels, level + 1, page)

    # Close partial right-edge pages while reusing every identical prior subtree.
    def _finish(self, levels):
        for level in range(DEPTH + 1):
            if not levels[level]:
                continue
            reference = {"page": self._page(level, levels[level])}
            levels[level] = []
            if not any(levels[level + 1 :]):
                return reference
            self._push(levels, level + 1, reference)
        raise PhysicalPause("Empty or excessive manifest tree")

    # Traverse bounded tree pages in exact order with depth and ancestor-cycle guards.
    def _walk(self, reference, level=None, ancestors=frozenset()):
        _require(
            type(reference) is dict and set(reference) == {"page"},
            "Manifest page reference required",
        )
        pin = reference["page"]
        _require(
            pin["sha256"] not in ancestors and len(ancestors) <= DEPTH,
            "Manifest cycle or depth cap reached",
        )
        value = _decoded(b"".join(self._content("page", pin)))
        _require(
            type(value) is dict and set(value) == {"version", "level", "refs"},
            "Exact manifest page schema required",
        )
        actual = value["level"]
        _require(
            value["version"] == VERSION
            and type(actual) is int
            and 0 <= actual <= DEPTH
            and (level is None or actual == level),
            "Manifest level differs",
        )
        _require(
            type(value["refs"]) is list and 1 <= len(value["refs"]) <= FANOUT,
            "Manifest fanout cap reached",
        )
        for item in value["refs"]:
            if actual:
                yield from self._walk(item, actual - 1, ancestors | {pin["sha256"]})
            else:
                _require(
                    type(item) is dict
                    and set(item) == {"role", "content"}
                    and item["role"] in {"prefix", "row", "suffix"},
                    "Physical span reference required",
                )
                yield item

    # Authenticate opaque objects without completing or adopting a native operation.
    def verify(self, reference, sink=None):
        root = _decoded(b"".join(self._content("page", reference)))
        _require(
            type(root) is dict
            and set(root)
            == {
                "version",
                "scope",
                "identity_sha256",
                "primitive_sha256",
                "limits_sha256",
                "raw_sha256",
                "raw_bytes",
                "history_rows",
                "spans",
                "tree",
            },
            "Exact root schema required",
        )
        _require(
            root["version"] == VERSION
            and root["scope"] == "OPAQUE_NATIVE_BYTES_NOT_JSON_ADMISSION"
            and root["identity_sha256"] == self.header["identity_sha256"]
            and root["primitive_sha256"] == self.header["primitive_sha256"]
            and root["limits_sha256"] == _sha(_encoded(self.limits)),
            "Physical root identity differs",
        )
        _digest(root["raw_sha256"])
        _require(
            type(root["raw_bytes"]) is int
            and 0 < root["raw_bytes"] <= self.limits["raw_bytes"]
            and type(root["history_rows"]) is int
            and 0 <= root["history_rows"] <= self.limits["history_rows"]
            and type(root["spans"]) is int
            and root["spans"] == root["history_rows"] + 2,
            "Root resource bounds differ",
        )
        hashed, total, rows, count, last = hashlib.sha256(), 0, 0, 0, None
        for item in self._walk(root["tree"]):
            role = item["role"]
            _require(
                (count == 0 and role == "prefix")
                or (count > 0 and last != "suffix" and role in {"row", "suffix"}),
                "Physical span order differs",
            )
            for chunk in self._content("body", item["content"]):
                total += len(chunk)
                _require(total <= root["raw_bytes"], "Excess physical body bytes")
                hashed.update(chunk)
                if sink is not None:
                    _require(sink.write(chunk) == len(chunk), "Short restored write")
            rows += role == "row"
            count += 1
            _require(count <= root["spans"], "Excess physical references")
            last = role
        _require(
            last == "suffix"
            and count == root["spans"]
            and rows == root["history_rows"]
            and total == root["raw_bytes"]
            and hashed.hexdigest() == root["raw_sha256"],
            "Complete raw checkpoint differs",
        )
        return root

    # Distinguish the latest completed local capture from readable orphan CAS objects.
    def completed(self, reference):
        path = self.root / "lock"
        info = _extent(path, 4096, 1)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            _opened(path, descriptor, info)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise PhysicalPause("Checkpoint mutation already active") from error
            _opened(path, descriptor, info)
            control = _control(_fixed_read(self.root / "control"), self.limits)
            _require(
                control["operation"] is None
                and control["completed_capture"] == reference,
                "No completed local capture binding; OPEN objects cannot be adopted",
            )
            root = self.verify(reference)
            _opened(path, descriptor, info)
            return {
                "root": root,
                "local_capture_committed": True,
                "native_operation_committed": False,
                "durable_simulator_adoption": False,
                "dual_host_reserved": False,
            }
        finally:
            os.close(descriptor)

    # Restore once into the actual reserved inode and publish only a fresh target link.
    def restore(self, reference, destination):
        destination = _path(destination)
        _require(
            not destination.exists() and not destination.is_symlink(),
            "Exclusive fresh restore target required",
        )
        _require(
            stat.S_IMODE(destination.parent.stat().st_mode) == 0o700,
            "Private restore parent mode0700 required",
        )
        _require(
            destination.parent.stat().st_dev == self.root.stat().st_dev,
            "Same-filesystem reserved restore required",
        )
        with self._locked("RESTORE"):
            _require(
                self.control["restored"] is False,
                "Restore reservation already consumed",
            )
            path = self.root / "restore"
            info = _extent(path, self.limits["raw_bytes"], 1)
            descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "r+b") as handle:
                _opened(path, handle.fileno(), info)
                result = self.verify(reference, sink=handle)
                handle.truncate(result["raw_bytes"])
                handle.flush()
                os.fsync(handle.fileno())
                _written(path, handle.fileno(), info, result["raw_bytes"])
            os.link(path, destination, follow_symlinks=False)
            _sync(destination.parent)
            _require(
                destination.lstat().st_ino == info.st_ino,
                "Restore publication copied the inode",
            )
            self.control["restored"] = True
            return result
