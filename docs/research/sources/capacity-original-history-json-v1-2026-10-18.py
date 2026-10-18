# SOURCE ONLY: separately versioned capacity data interface; all bodies UNRUN.
# This is a new module/type identity, not the original verified reader or receipt.
"""Bounded ORIGINAL-audit JSON parsing and exact external history comparison.

No native account is seeded here. Physical nonfinite normalization is a separate,
explicit, SHA-pinned comparison mode; retained original bytes are never rewritten.
"""

import gzip
import io
import json
import math
import os
import sqlite3
import stat
import tempfile
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

CHUNK_BYTES = 64 * 1024
ROW_BYTES = 1024 * 1024  # Original observed largest physical row681694B.
CONTROL_BYTES = 16 * 1024 * 1024
HISTORY_ROWS = 1916  # Original1915 sessions plus independent initial prior close.
SHA_MAP_BYTES = 32 * 1024 * 1024
SHA_MAP_ENTRIES = 200000
SHA_MAP_KEY_BYTES = 4096
DEPTH = 128
STREAM_BYTES = (
    832110254  # Observed original physical832110254B; processed, not resident.
)


# Refer only to exact original compressed bytes selected by completion metadata.
@dataclass(frozen=True)
class ArchiveRef:
    path: Path
    sha256: str


# Refuse malformed or out-of-profile evidence instead of truncating it.
def require(value, reason):
    if not value:
        raise ValueError(reason)


# Reject duplicate JSON fields at every materialized nesting level.
def unique(pairs):
    result = {}
    for name, value in pairs:
        require(
            name not in result, "DUPLICATE_JSON_MEMBER: Duplicate original JSON field"
        )
        result[name] = value
    return result


# Reject numeric overflow independently of literal nonfinite handling.
def finite(value):
    number = float(value)
    require(math.isfinite(number), "Nonfinite original JSON number")
    return number


# Permit source-writer literals only under the explicit physical comparison mode.
def constant(value):
    raise ValueError("Nonfinite original JSON constant: " + value)


# Normalize original physical literals only in the separately pinned logical view.
def physical_constant(value):
    require(value in ("NaN", "Infinity", "-Infinity"), "Unknown physical literal")
    return None


# Decode a bounded unit without relaxing duplicates, overflow or trailing syntax.
def decode(raw, *, physical=False):
    require(
        isinstance(raw, (bytes, bytearray, str)) and len(raw) <= CONTROL_BYTES,
        "Bounded original JSON unit required",
    )
    return json.loads(
        raw,
        object_pairs_hook=unique,
        parse_float=finite,
        parse_constant=physical_constant if physical else constant,
    )


# Identify a regular file without accepting any symlinked ancestor.
def identity(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink(), "Symlink original JSON evidence")
    value = path.stat()
    require(stat.S_ISREG(value.st_mode), "Regular original JSON evidence required")
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


# Compare descriptor identity with the unchanged physical path after bounded I/O.
def stable(stream, path, before):
    value = os.fstat(stream.fileno())
    require(
        (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
        == before
        == identity(path),
        "Original JSON evidence changed",
    )


# Hash exact physical bytes before interpreting their authenticated representation.
def authenticate(path, expected):
    require(
        type(expected) is str
        and len(expected) == 64
        and all(char in "0123456789abcdef" for char in expected),
        "External JSON SHA required",
    )
    before = identity(path)
    digest = sha256()
    with Path(path).open("rb") as stream:
        stable(stream, path, before)
        while raw := stream.read(CHUNK_BYTES):
            digest.update(raw)
        stable(stream, path, before)
    require(digest.hexdigest() == expected, "Original JSON SHA differs")
    return before


# Keep only immutable byte ranges for previously validated bounded history rows.
@dataclass(frozen=True)
class Row:
    path: Path
    offset: int
    size: int
    sha256: str
    source_identity: tuple

    # Recheck exact private canonical row bytes without expanding the whole history.
    def raw(self):
        require(self.size <= ROW_BYTES, "Original history row exceeds bound")
        require(identity(self.path) == self.source_identity, "History spool changed")
        with self.path.open("rb") as stream:
            stable(stream, self.path, self.source_identity)
            stream.seek(self.offset)
            raw = stream.read(self.size + 1)
            # Adjacent rows share a spool; read exactly the indexed range.
            raw = raw[: self.size]
            stable(stream, self.path, self.source_identity)
        require(
            len(raw) == self.size and sha256(raw).hexdigest() == self.sha256,
            "History spool row changed",
        )
        return raw


# Expose complete ordered history lazily, never as saved planner state inputs.
@dataclass(frozen=True)
class Rows:
    entries: tuple
    disposable_path: Path | None = None

    # Preserve immutable row references through control-only native copies.
    def __deepcopy__(self, memo):
        return self

    # Report every original row without discarding an initial or unavailable prefix.
    def __len__(self):
        return len(self.entries)

    # Materialize at most one independently bounded row on indexed access.
    def __getitem__(self, index):
        return decode(self.entries[index].raw())

    # Yield all ordered rows without concatenating their decoded objects.
    def __iter__(self):
        for index in range(len(self)):
            yield self[index]


# Select every map pair in the exact Unicode order used by json.dumps sort_keys.
def canonical_items(value):
    if isinstance(value, ShaMap):
        return value.pairs(canonical=True)
    return ((name, value[name]) for name in sorted(value))


# Encode the exact existing sort_keys/default-separator digest representation.
def chunks(value):
    if isinstance(value, Rows):
        yield b"["
        for index, row in enumerate(value.entries):
            if index:
                yield b", "
            yield row.raw()
        yield b"]"
    elif isinstance(value, (dict, ShaMap)):
        yield b"{"
        for index, (name, item) in enumerate(canonical_items(value)):
            if index:
                yield b", "
            yield json.dumps(name, allow_nan=False).encode()
            yield b": "
            yield from chunks(item)
        yield b"}"
    elif isinstance(value, (tuple, list)):
        yield b"["
        for index, row in enumerate(value):
            if index:
                yield b", "
            yield from chunks(row)
        yield b"]"
    else:
        yield json.dumps(value, sort_keys=True, allow_nan=False).encode()


# Preserve the old complete-state SHA without building its complete encoded string.
def digest(value):
    result = sha256()
    for raw in chunks(value):
        result.update(raw)
    return result.hexdigest()


# Keep a complete SHA map in sealed private files, not in one resident dictionary.
@dataclass(frozen=True, eq=False)
class ShaMap:
    index: Path
    spool: Path
    count: int
    index_identity: tuple
    spool_identity: tuple
    index_sha256: str
    spool_sha256: str
    canonical_sha256: str
    __hash__ = None

    # Preserve the sealed immutable mapping through native metadata-only copies.
    def __deepcopy__(self, memo):
        return self

    # Return the complete admitted pair count without truncation.
    def __len__(self):
        self._stable()
        return self.count

    # Check both physical paths before any indexed read or cursor advance.
    def _stable(self):
        require(identity(self.index) == self.index_identity, "SHA map index changed")
        require(identity(self.spool) == self.spool_identity, "SHA map spool changed")

    # Decode one indexed row only after its bounded bytes and hash agree.
    def _row(self, key, offset, size, expected):
        self._stable()
        require(
            type(size) is int and 0 < size <= SHA_MAP_KEY_BYTES + 128,
            "SHA map row exceeds bound",
        )
        with self.spool.open("rb") as source:
            stable(source, self.spool, self.spool_identity)
            source.seek(offset)
            raw = source.read(size)
            stable(source, self.spool, self.spool_identity)
        require(
            len(raw) == size and sha256(raw).hexdigest() == expected,
            "SHA map row changed",
        )
        row = decode(raw)
        require(
            type(row) is list
            and len(row) == 2
            and type(row[0]) is str
            and json.dumps(row[0], allow_nan=False).encode() == key,
            "SHA map index row differs",
        )
        require(
            type(row[1]) is str
            and len(row[1]) == 64
            and all(char in "0123456789abcdef" for char in row[1]),
            "SHA map digest differs",
        )
        self._stable()
        return row

    # Stream pairs in source insertion order or exact Python Unicode sort order.
    def pairs(self, *, canonical=False):
        self._stable()
        with self.index.open("rb") as guard:
            stable(guard, self.index, self.index_identity)
            connection = sqlite3.connect(
                self.index.as_uri() + "?mode=ro&immutable=1", uri=True
            )
            try:
                connection.execute("PRAGMA cache_size=-512")
                order = "sort_key" if canonical else "ordinal"
                cursor = connection.execute(
                    "SELECT key,offset,size,sha FROM entries ORDER BY " + order
                )
                seen = 0
                for record in cursor:
                    yield tuple(self._row(*record))
                    seen += 1
                    stable(guard, self.index, self.index_identity)
                require(seen == self.count, "SHA map index count differs")
            finally:
                connection.close()
            stable(guard, self.index, self.index_identity)
        self._stable()

    # Match dictionary items while retaining every original pair and source order.
    def items(self):
        return self.pairs()

    # Yield exact decoded keys without materializing all names.
    def __iter__(self):
        for key, _ in self.pairs():
            yield key

    # Resolve one exact key without hashing or decoding the whole map again.
    def __getitem__(self, name):
        if type(name) is not str:
            raise KeyError(name)
        self._stable()
        key = json.dumps(name, allow_nan=False).encode()
        with self.index.open("rb") as guard:
            stable(guard, self.index, self.index_identity)
            connection = sqlite3.connect(
                self.index.as_uri() + "?mode=ro&immutable=1", uri=True
            )
            try:
                row = connection.execute(
                    "SELECT key,offset,size,sha FROM entries WHERE key=?", (key,)
                ).fetchone()
            finally:
                connection.close()
            stable(guard, self.index, self.index_identity)
        if row is None:
            raise KeyError(name)
        return self._row(*row)[1]

    # Preserve ordinary dictionary missing-key behavior without inventing a digest.
    def get(self, name, default=None):
        try:
            return self[name]
        except KeyError:
            return default

    # Check membership through the same verified bounded indexed lookup.
    def __contains__(self, name):
        try:
            self[name]
            return True
        except KeyError:
            return False

    # Compare every canonical pair rather than accepting count or digest alone.
    def __eq__(self, other):
        if type(other) is ShaMap:
            if len(self) != len(other):
                return False
            return all(
                a == b
                for a, b in zip(
                    self.pairs(canonical=True), other.pairs(canonical=True), strict=True
                )
            )
        if type(other) is dict:
            return len(self) == len(other) and all(
                key in other and other[key] == value for key, value in self.pairs()
            )
        return NotImplemented

    # Rehash both complete sealed files and every canonical pair at acceptance edges.
    def authenticate_contents(self):
        self._stable()
        authenticate(self.index, self.index_sha256)
        authenticate(self.spool, self.spool_sha256)
        require(
            digest(self) == self.canonical_sha256, "SHA map canonical digest differs"
        )
        self._stable()
        return {
            "pairs": self.count,
            "canonical_sha256": self.canonical_sha256,
            "index_sha256": self.index_sha256,
            "spool_sha256": self.spool_sha256,
        }


# Hash newly sealed private bytes with bounded reads before exposing their identity.
def private_digest(path):
    value = sha256()
    with Path(path).open("rb") as source:
        while raw := source.read(CHUNK_BYTES):
            value.update(raw)
    return value.hexdigest()


# Frame every source token with bounded buffers before strict unit decoding.
class Cursor:
    # Begin with no evidence consumed and a bounded Unicode decoder buffer.
    def __init__(self, stream, physical, directory, retain, external_inputs=False):
        self.stream, self.physical, self.directory, self.retain = (
            stream,
            physical,
            directory,
            retain,
        )
        self.buffer, self.index, self.control_bytes, self.stream_bytes = "", 0, 0, 0
        self.external_inputs, self.map_bytes = external_inputs, None

    # Fetch one bounded block without a whole-source read or hidden rewind.
    def peek(self):
        if self.index == len(self.buffer):
            self.buffer, self.index = self.stream.read(CHUNK_BYTES), 0
            self.stream_bytes += len(self.buffer.encode("utf-8"))
            require(
                self.stream_bytes <= STREAM_BYTES,
                "Original stream processing bound exceeded",
            )
        return self.buffer[self.index : self.index + 1]

    # Consume one character only after preserving the parser's explicit position.
    def take(self):
        value = self.peek()
        require(bool(value), "Truncated original JSON framing")
        self.index += 1
        if self.map_bytes is not None:
            self.map_bytes += len(value.encode("utf-8"))
            require(self.map_bytes <= SHA_MAP_BYTES, "SHA map bytes exceed bound")
        return value

    # Parse only the explicitly selected root SHA map as bounded unique pairs.
    def sha_map(self):
        require(self.directory is not None, "Private SHA map directory required")
        paths = []
        for prefix in ("original-sha-index-", "original-sha-pairs-"):
            descriptor, name = tempfile.mkstemp(prefix=prefix, dir=self.directory)
            os.close(descriptor)
            paths.append(Path(name))
        index, spool = paths
        count, connection = 0, None
        self.map_bytes = 0
        try:
            connection = sqlite3.connect(index)
            connection.execute("PRAGMA cache_size=-512")
            connection.execute(
                "CREATE TABLE entries (key BLOB PRIMARY KEY,"
                "sort_key BLOB UNIQUE NOT NULL,ordinal INTEGER UNIQUE NOT NULL,"
                "offset INTEGER NOT NULL,size INTEGER NOT NULL,sha TEXT NOT NULL)"
            )
            self.expect("{")
            with spool.open("wb") as output:
                self.whitespace()
                if self.peek() != "}":
                    while True:
                        key = self.unit(SHA_MAP_KEY_BYTES)
                        require(type(key) is str, "SHA map key must be a string")
                        self.expect(":")
                        value = self.unit(128)
                        require(
                            type(value) is str
                            and len(value) == 64
                            and all(char in "0123456789abcdef" for char in value),
                            "SHA map value must be a lower-case SHA256",
                        )
                        count += 1
                        require(
                            count <= SHA_MAP_ENTRIES,
                            "SHA map entry count exceeds bound",
                        )
                        raw = json.dumps([key, value], allow_nan=False).encode()
                        require(
                            len(raw) <= SHA_MAP_KEY_BYTES + 128,
                            "SHA map row exceeds bound",
                        )
                        offset = output.tell()
                        output.write(raw)
                        try:
                            connection.execute(
                                "INSERT INTO entries VALUES (?,?,?,?,?,?)",
                                (
                                    json.dumps(key, allow_nan=False).encode(),
                                    key.encode("utf-32-be", errors="surrogatepass"),
                                    count - 1,
                                    offset,
                                    len(raw),
                                    sha256(raw).hexdigest(),
                                ),
                            )
                        except sqlite3.IntegrityError as exc:
                            raise ValueError(
                                "Duplicate original SHA map decoded key"
                            ) from exc
                        self.whitespace()
                        if self.peek() == "}":
                            break
                        self.expect(",")
                self.expect("}")
                output.flush()
                os.fsync(output.fileno())
            connection.commit()
            connection.close()
            connection = None
            result = ShaMap(
                index.absolute(),
                spool.absolute(),
                count,
                identity(index),
                identity(spool),
                private_digest(index),
                private_digest(spool),
                "",
            )
            result = replace(result, canonical_sha256=digest(result))
            result.authenticate_contents()
            return result
        except BaseException:
            if connection is not None:
                connection.close()
            for path in paths:
                path.unlink(missing_ok=True)
            raise
        finally:
            self.map_bytes = None

    # Admit only JSON whitespace between values and delimiters.
    def whitespace(self):
        while self.peek() and self.peek() in " \t\r\n":
            self.take()

    # Require each structural delimiter rather than skipping opaque source content.
    def expect(self, character):
        self.whitespace()
        require(self.take() == character, "Malformed original JSON framing")

    # Frame a single bounded value while checking nested brackets and quoted escapes.
    def unit(self, limit, *, control=False):  # noqa: C901 - One explicit JSON framing state.
        self.whitespace()
        parts, stack, quoted, escaped = bytearray(), [], False, False
        first = self.peek()
        require(bool(first), "Truncated original JSON value")
        while self.peek():
            char = self.peek()
            if not quoted and not stack and parts:
                break
            char = self.take()
            parts.extend(char.encode("utf-8"))
            require(len(parts) <= limit, "Original JSON unit exceeds bound")
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                stack.append(char)
                require(len(stack) <= DEPTH, "Original JSON depth exceeds bound")
            elif char in "]}":
                require(
                    bool(stack) and stack.pop() == ({"]": "[", "}": "{"}[char]),
                    "Malformed original JSON brackets",
                )
            if first not in '[{"':
                while self.peek() and self.peek() not in ",]} \t\r\n":
                    parts.extend(self.take().encode("utf-8"))
                    require(len(parts) <= limit, "Original JSON unit exceeds bound")
                break
        require(not stack and not quoted, "Truncated original JSON unit")
        if control:
            self.control_bytes += len(parts)
            require(
                self.control_bytes <= CONTROL_BYTES, "Original controls exceed bound"
            )
        # The decoder validates every nested key and grammar, even discarded rows.
        value = decode(parts, physical=self.physical)
        return value

    # Stream the only large array, retaining all rows or validating explicit discard.
    def history(self):
        self.expect("[")
        refs, count = [], 0
        path = None
        output = None
        if self.retain:
            import tempfile

            descriptor, name = tempfile.mkstemp(
                prefix="original-history-", dir=self.directory
            )
            path, output = Path(name), os.fdopen(descriptor, "wb")
        try:
            self.whitespace()
            if self.peek() != "]":
                while True:
                    row = self.unit(ROW_BYTES)
                    require(type(row) is dict, "Original history row must be an object")
                    count += 1
                    require(
                        count <= HISTORY_ROWS,
                        "Original history row count exceeds profile",
                    )
                    if output is not None:
                        raw = json.dumps(row, sort_keys=True, allow_nan=False).encode()
                        require(
                            len(raw) <= ROW_BYTES, "Canonical history row exceeds bound"
                        )
                        offset = output.tell()
                        output.write(raw)
                        refs.append((offset, len(raw), sha256(raw).hexdigest()))
                    self.whitespace()
                    if self.peek() == "]":
                        break
                    self.expect(",")
            self.expect("]")
        finally:
            if output is not None:
                output.close()
        if path is None:
            return None
        before = identity(path)
        return Rows(
            tuple(Row(path, offset, size, sha, before) for offset, size, sha in refs),
            path,
        )

    # Interpret root/state objects while framing every other nested unit strictly.
    def object(self, *, state=False):
        self.expect("{")
        result = {}
        self.whitespace()
        if self.peek() != "}":
            while True:
                name = self.unit(CONTROL_BYTES, control=True)
                require(type(name) is str, "Original object key must be a string")
                require(
                    name not in result,
                    "DUPLICATE_JSON_MEMBER: Duplicate original JSON field",
                )
                self.expect(":")
                if name == "input_sha256" and not state and self.external_inputs:
                    result[name] = self.sha_map()
                elif name == "paper_state" and not state:
                    result[name] = self.object(state=True)
                elif name == "history":
                    result[name] = self.history()
                else:
                    result[name] = self.unit(CONTROL_BYTES, control=True)
                self.whitespace()
                if self.peek() == "}":
                    break
                self.expect(",")
        self.expect("}")
        return result


# Authenticate and parse every byte, including all streamed history and gzip trailers.
def read(
    path,
    expected,
    *,
    directory=None,
    compressed=False,
    physical=False,
    retain=True,
    external_inputs=False,
):
    require(
        type(external_inputs) is bool and not (external_inputs and physical),
        "Explicit root SHA map mode required",
    )
    require(
        not external_inputs or directory is not None,
        "Private SHA map directory required",
    )
    before = authenticate(path, expected)
    require(
        not retain or directory is not None, "Private history spool directory required"
    )
    with Path(path).open("rb") as raw:
        stable(raw, path, before)
        binary = gzip.GzipFile(fileobj=raw) if compressed else raw
        text = io.TextIOWrapper(binary, encoding="utf-8", errors="strict", newline="")
        cursor = Cursor(text, physical, directory, retain, external_inputs)
        try:
            value = cursor.object(state=physical)
            cursor.whitespace()
            require(cursor.peek() == "", "Trailing original JSON bytes")
            # Consuming EOF forces gzip CRC/size and concatenated-member validation.
            stable(raw, path, before)
        finally:
            text.detach()
            if compressed:
                binary.close()
    authenticate(path, expected)
    return value


# Retain independently derived rows in private immutable files rather than saved seeds.
class History:
    # Create no account history until an independent initial/nightly row is derived.
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.entries, self.sessions, self.next_row = [], [], 0

    # Expose the exact independently derived ordered prefix without materialization.
    def view(self):
        return Rows(tuple(self.entries))

    # Apply the original same-session replacement rule to independently generated rows.
    def record(self, row):
        raw = json.dumps(row, sort_keys=True, allow_nan=False).encode()
        require(len(raw) <= ROW_BYTES, "Derived original row exceeds bound")
        name = row["session"]
        kept = [
            (session, item)
            for session, item in zip(self.sessions, self.entries, strict=True)
            if session != name
        ]
        require(len(kept) < HISTORY_ROWS, "Derived history exceeds original profile")
        path = self.directory / (str(self.next_row) + ".json")
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as stream:
            stream.write(raw)
        self.next_row += 1
        before = identity(path)
        self.sessions = [session for session, _ in kept] + [name]
        self.entries = [item for _, item in kept] + [
            Row(path, 0, len(raw), sha256(raw).hexdigest(), before)
        ]


# Release only disposable authenticated-source spools, never independent row evidence.
def release(value):
    if isinstance(value, Rows):
        if value.disposable_path is not None:
            value.disposable_path.unlink()
    elif isinstance(value, dict):
        for row in value.values():
            release(row)
