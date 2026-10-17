"""Unused synthetic-local fixed-slot checkpoints, never native admission.

Two LOCAL fixture peers use precreated numeric names and actual fallocated
inodes. No network client, native writer, model, Store or account is imported.
After ARM the checkpoint writes existing file extents only. This does NOT
reserve filesystem journal/rename capacity for a native writer, prove two-host
durability, or permit a simulator to adopt readable objects. Recovery requires
an externally pinned owner decision and never accepts an effect callback.
"""

import fcntl
import hashlib
import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path

from backend.market import historical_physical_checkpoint as raw

VERSION = "synthetic-local-fixed-slot/1"
HELPER = "5d6169282f5054bc9871a5f4e3dec572a1b0b31482e4ff15ee6bc92ee7803604"
BUCKET = 256
PROBES = 32
PHASES = ("ARM", "PREPARED", "DECISION", "ACK")
LIMITS = {
    "body_slots",
    "page_slots",
    "span_bytes",
    "raw_bytes",
    "history_rows",
    "operations",
}
FALSE_CLAIMS = {
    "native_metadata_reserved": False,
    "native_operation_adopted": False,
    "real_two_host_proof": False,
    "restore_reserved": False,
}


# Bind this unused infrastructure closure without importing a native writer.
def _sources():
    helper = Path(raw.__file__)
    raw._require(helper.stat().st_size < raw.META, "Bounded helper required")
    raw._require(raw._sha(helper.read_bytes()) == HELPER, "Raw helper source differs")
    return {"adapter": raw._sha(Path(__file__).read_bytes()), "helper": HELPER}


# Detach small finite declarations before any injected callback can change them.
def _copy(value):
    return raw._decoded(raw._encoded(value))


# Admit finite opaque-byte and operation quotas without raising existing raw caps.
def _limits(value):
    raw._require(type(value) is dict and set(value) == LIMITS, "Exact limits required")
    raw._require(
        all(type(item) is int and 0 < item <= 2**40 for item in value.values()),
        "Finite positive limits required",
    )
    raw._require(
        value["body_slots"] <= 8192
        and value["page_slots"] <= 8192
        and value["operations"] <= 1024
        and value["span_bytes"] <= raw.SPAN
        and value["history_rows"] <= 1_000_000,
        "Primitive quota exceeded",
    )
    return _copy(value)


# Recompute a finite fixed index and every preallocated file byte/inode count.
def _amounts(limits):
    buckets = 1
    while buckets < 2 * (limits["body_slots"] + limits["page_slots"]):
        buckets *= 2
    return {
        "buckets": buckets,
        "file_bytes": limits["body_slots"] * limits["span_bytes"]
        + limits["page_slots"] * raw.META
        + buckets * BUCKET
        + (4 + 4 * limits["operations"]) * raw.META
        + 4096,
        "file_inodes": limits["body_slots"]
        + limits["page_slots"]
        + 4 * limits["operations"]
        + 6,
        "directories": 4,
    }


# Reserve worst-case new objects for one complete bounded capture before any effect.
def _capture_budget(limits):
    # Root metadata needs one page; eager full carries can add a singleton top page.
    bodies, remaining, pages = limits["history_rows"] + 2, limits["history_rows"] + 2, 2
    for _ in range(raw.DEPTH + 1):
        remaining = (remaining + raw.FANOUT - 1) // raw.FANOUT
        pages += remaining
        if remaining == 1:
            return {"body": bodies, "page": pages}
    raise raw.PhysicalPause("Declared capture exceeds manifest depth")


# Require exactly two short explicit fixture peer names and one named owner.
def _names(peers, owner):
    raw._require(
        type(peers) in (list, tuple)
        and len(peers) == 2
        and all(
            type(name) is str
            and 0 < len(name) <= 24
            and name.isascii()
            and name.replace("-", "").isalnum()
            for name in peers
        )
        and len(set(peers)) == 2
        and owner in peers,
        "Two distinct named fixture peers required",
    )
    return sorted(peers)


# Enumerate only the predeclared numeric namespace, never a growing CAS directory.
def _files(limits, amounts):
    yield "header", raw.META
    yield "control", raw.META
    yield "head0", raw.META
    yield "head1", raw.META
    yield "lock", 4096
    yield "index", amounts["buckets"] * BUCKET
    for kind in ("body", "page"):
        for index in range(limits[f"{kind}_slots"]):
            yield (
                f"{kind}/{index}",
                limits["span_bytes"] if kind == "body" else raw.META,
            )
    for sequence in range(limits["operations"]):
        for phase in PHASES:
            yield f"records/{sequence}.{phase}", raw.META


# Authenticate actual reserved inodes and modes without confusing headroom with extents.
def _inventory(root, limits, amounts):
    digest = hashlib.sha256()
    device = root.lstat().st_dev
    for name in (".", "body", "page", "records"):
        info = (root / name).lstat()
        raw._require(
            stat.S_ISDIR(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o700
            and info.st_dev == device,
            "Private same-device directories required",
        )
        digest.update(raw._encoded([name, info.st_dev, info.st_ino]))
    for name, size in _files(limits, amounts):
        info = raw._extent(root / name, size, 1)
        raw._require(info.st_dev == device, "Reserved inode device differs")
        digest.update(raw._encoded([name, info.st_dev, info.st_ino, size]))
    return digest.hexdigest()


# Read one checksummed existing-file region in bounded chunks with identity bookends.
def _read(path, size, *, offset=0, capacity=None):
    capacity = size if capacity is None else capacity
    info = raw._extent(path, size, 1)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw._opened(path, descriptor, info)
        result = bytearray()
        while len(result) < capacity:
            chunk = os.pread(
                descriptor, min(raw.READ, capacity - len(result)), offset + len(result)
            )
            raw._require(chunk, "Truncated reserved metadata")
            result.extend(chunk)
        raw._opened(path, descriptor, info)
    finally:
        os.close(descriptor)
    data = bytes(result)
    if not any(data):
        return None
    length = int.from_bytes(data[:8], "big")
    raw._require(0 < length < capacity - 40, "Torn reserved metadata length")
    value = data[40 : 40 + length]
    raw._require(raw._sha(value) == data[8:40].hex(), "Torn reserved metadata checksum")
    return raw._decoded(value)


# Overwrite only an existing owned extent and durably read back its bounded value.
def _write(path, size, value, *, offset=0, capacity=None):
    capacity = size if capacity is None else capacity
    encoded = raw._encoded(value)
    raw._require(len(encoded) + 40 < capacity, "Reserved metadata cap exhausted")
    data = len(encoded).to_bytes(8, "big") + hashlib.sha256(encoded).digest() + encoded
    info = raw._extent(path, size, 1)
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        raw._opened(path, descriptor, info)
        raw._require(
            os.pwrite(descriptor, data, offset) == len(data), "Short metadata write"
        )
        os.fsync(descriptor)
        raw._written(path, descriptor, info, size)
    finally:
        os.close(descriptor)
    raw._require(
        _read(path, size, offset=offset, capacity=capacity) == value,
        "Metadata durable readback differs",
    )
    return raw._sha(encoded)


# Initialize and verify the actual future extents, not a separate headroom placeholder.
def _initialize(path, size):
    before = raw._extent(path, size, 1)
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        raw._opened(path, descriptor, before)
        zeros = bytes(raw.READ)
        for offset in range(0, size, raw.READ):
            value = zeros[: min(raw.READ, size - offset)]
            raw._require(
                os.pwrite(descriptor, value, offset) == len(value),
                "Short reserved initialization",
            )
        os.fsync(descriptor)
        raw._written(path, descriptor, before, size)
        for offset in range(0, size, raw.READ):
            value = os.pread(descriptor, min(raw.READ, size - offset), offset)
            raw._require(
                value == zeros[: min(raw.READ, size - offset)],
                "Reserved initialization readback differs",
            )
        raw._written(path, descriptor, before, size)
    finally:
        os.close(descriptor)


# Prepare all real names and extents before issuing any synthetic effect permission.
def reserve(
    root,
    *,
    peer,
    peers,
    owner,
    genesis,
    identity,
    identity_sha256,
    writer_source,
    limits,
):
    sources = _sources()
    admitted = raw._identity(identity, identity_sha256, writer_source)
    peers, limits = _names(peers, owner), _limits(limits)
    raw._require(peer in peers, "Declared local peer required")
    raw._digest(genesis)
    amounts = _amounts(limits)
    root = raw._path(root)
    root.mkdir(mode=0o700)
    for name in ("body", "page", "records"):
        (root / name).mkdir(mode=0o700)
    for name, size in _files(limits, amounts):
        raw._allocate(root / name, size)
        _initialize(root / name, size)
    common = {
        "version": VERSION,
        "scope": "SYNTHETIC_LOCAL_PEERS_ONLY",
        "peers": peers,
        "owner": owner,
        "genesis": genesis,
        "sources": sources,
        "identity": admitted,
        "identity_sha256": identity_sha256,
        "limits": limits,
        "amounts": amounts,
        **FALSE_CLAIMS,
    }
    header = {
        "common": common,
        "peer": peer,
        "resources_sha256": _inventory(root, limits, amounts),
    }
    _write(root / "header", raw.META, header)
    _write(
        root / "control",
        raw.META,
        {"head": genesis, "next": 0, "open": None, "body": 0, "page": 0},
    )
    for bank in ("head0", "head1"):
        _write(root / bank, raw.META, {"head": genesis, "sequence": -1})
    for name in ("body", "page", "records", "."):
        raw._sync(root / name)
    raw._sync(root.parent)
    return Peer(root, identity_sha256=identity_sha256, writer_source=writer_source)


# Own one local preallocated namespace; this is not a host or account identity.
class Peer:
    # Reopen only exact source/profile, flags, resource arithmetic and actual inodes.
    def __init__(self, root, *, identity_sha256, writer_source):
        self.root, self.writer = raw._path(root), raw._path(writer_source)
        self.header = _read(self.root / "header", raw.META)
        raw._require(
            type(self.header) is dict
            and set(self.header) == {"common", "peer", "resources_sha256"},
            "Exact peer header required",
        )
        self.common = self.header["common"]
        keys = {
            "version",
            "scope",
            "peers",
            "owner",
            "genesis",
            "sources",
            "identity",
            "identity_sha256",
            "limits",
            "amounts",
            *FALSE_CLAIMS,
        }
        raw._require(
            type(self.common) is dict and set(self.common) == keys,
            "Exact common declaration required",
        )
        value = self.common
        raw._require(
            value["version"] == VERSION
            and value["scope"] == "SYNTHETIC_LOCAL_PEERS_ONLY"
            and value["sources"] == _sources()
            and value["identity_sha256"] == identity_sha256
            and all(value[key] is False for key in FALSE_CLAIMS),
            "Source/scope differs",
        )
        raw._require(
            value["peers"] == _names(value["peers"], value["owner"])
            and self.header["peer"] in value["peers"],
            "Peer identity differs",
        )
        raw._digest(value["genesis"])
        raw._identity(value["identity"], identity_sha256, self.writer)
        self.limits = _limits(value["limits"])
        raw._require(
            value["amounts"] == _amounts(self.limits), "Resource arithmetic differs"
        )
        self.binding = raw._sha(raw._encoded(value))
        self._resources()

    # Recheck immutable declarations and source bytes without interpreting native state.
    def _declaration(self):
        raw._require(
            _read(self.root / "header", raw.META) == self.header
            and raw._sha(raw._encoded(self.common)) == self.binding,
            "Immutable reservation declaration differs",
        )
        raw._require(
            self.common["sources"] == _sources(), "Infrastructure source drift"
        )
        raw._identity(
            self.common["identity"], self.common["identity_sha256"], self.writer
        )

    # Recheck actual reserved extents before issuing a pre-effect ARM acknowledgment.
    def _resources(self):
        self._declaration()
        raw._require(
            _inventory(self.root, self.limits, self.common["amounts"])
            == self.header["resources_sha256"],
            "Reservation inode substitution",
        )

    # Keep cooperating readers/writers bound to one real private kernel lock inode.
    @contextmanager
    def _locked(self):
        path = self.root / "lock"
        before = raw._extent(path, 4096, 1)
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            raw._opened(path, descriptor, before)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise raw.PhysicalPause("Peer already locked") from error
            raw._opened(path, descriptor, before)
            yield
            raw._opened(path, descriptor, before)
        finally:
            os.close(descriptor)

    # Decode monotone local charges without selecting an authoritative head by election.
    def _control(self):
        value = _read(self.root / "control", raw.META)
        raw._require(
            type(value) is dict
            and set(value) == {"head", "next", "open", "body", "page"},
            "Exact peer control required",
        )
        raw._digest(value["head"])
        raw._require(
            type(value["next"]) is int
            and 0 <= value["next"] <= self.limits["operations"]
            and (
                value["open"] is None
                or type(value["open"]) is int
                and value["open"] == value["next"] - 1
            )
            and all(
                type(value[kind]) is int
                and 0 <= value[kind] <= self.limits[f"{kind}_slots"]
                for kind in ("body", "page")
            ),
            "Invalid peer charge state",
        )
        return value

    # Permit only identical retransmission of an immutable phase record.
    def _record(self, sequence, phase, value=None):
        raw._require(
            type(sequence) is int
            and 0 <= sequence < self.limits["operations"]
            and phase in PHASES,
            "Finite named operation required",
        )
        path = self.root / "records" / f"{sequence}.{phase}"
        previous = _read(path, raw.META)
        if value is not None:
            raw._require(
                previous is None or previous == value, "Conflicting phase record"
            )
            if previous is None:
                _write(path, raw.META, value)
            previous = _read(path, raw.META)
        return previous

    # Charge a unique operation before acknowledging source-bound permission.
    def _arm(self, sequence, prior):
        self._resources()
        control = self._control()
        raw._require(
            control["open"] is None
            and control["head"] == prior
            and sequence == control["next"] < self.limits["operations"],
            "PAUSED or stale prior head; never repeat an effect",
        )
        raw._require(
            all(
                control[kind] + needed <= self.limits[f"{kind}_slots"]
                for kind, needed in _capture_budget(self.limits).items()
            ),
            "Complete capture reservation exhausted before ARM",
        )
        raw._require(
            any(
                _read(self.root / bank, raw.META)
                == {"head": prior, "sequence": sequence - 1}
                for bank in ("head0", "head1")
            ),
            "Pinned prior head bank differs",
        )
        control.update(open=sequence, next=sequence + 1)
        _write(self.root / "control", raw.META, control)
        value = {
            "binding": self.binding,
            "sequence": sequence,
            "prior": prior,
            "peer": self.header["peer"],
            "resources": self.header["resources_sha256"],
        }
        self._record(sequence, "ARM", value)
        return raw._sha(raw._encoded(value))

    # Require the exact charged operation for every object allocation or receipt.
    def _open(self, sequence):
        control = self._control()
        raw._require(control["open"] == sequence, "Charged OPEN operation required")
        return control

    # Find a digest in bounded fixed buckets; collisions cannot trigger unbounded work.
    def _bucket(self, kind, digest):
        raw._require(kind in {"body", "page"}, "Known object kind required")
        raw._digest(digest)
        count = self.common["amounts"]["buckets"]
        start = int(raw._sha((kind + digest).encode())[:16], 16) % count
        for probe in range(min(PROBES, count)):
            offset = ((start + probe) % count) * BUCKET
            value = _read(
                self.root / "index", count * BUCKET, offset=offset, capacity=BUCKET
            )
            if value is None:
                return offset, None
            self._reference(value)
            if value["kind"] == kind and value["sha256"] == digest:
                return offset, value
        raise raw.PhysicalPause("Finite index collision/probe capacity exhausted")

    # Check a fixed-slot reference against charged cursors and byte caps.
    def _reference(self, reference):
        raw._require(
            type(reference) is dict
            and set(reference) == {"kind", "slot", "length", "sha256"}
            and type(reference["kind"]) is str
            and reference["kind"] in {"body", "page"},
            "Exact object reference required",
        )
        kind = reference["kind"]
        cap = self.limits["span_bytes"] if kind == "body" else raw.META - 1
        control = self._control()
        raw._require(
            type(reference["slot"]) is int
            and 0 <= reference["slot"] < control[kind]
            and type(reference["length"]) is int
            and 0 < reference["length"] <= cap,
            "Object exceeds charged slot or byte cap",
        )
        raw._digest(reference["sha256"])

    # Stream only the immutable used prefix, retaining its reserved padding and inode.
    def _content(self, reference):
        self._reference(reference)
        _, indexed = self._bucket(reference["kind"], reference["sha256"])
        raw._require(indexed == reference, "Object index differs")
        kind = reference["kind"]
        size = self.limits["span_bytes"] if kind == "body" else raw.META
        path = self.root / kind / str(reference["slot"])
        before = raw._extent(path, size, 1)
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        hashed, remaining = hashlib.sha256(), reference["length"]
        try:
            raw._opened(path, descriptor, before)
            while remaining:
                chunk = os.read(descriptor, min(raw.READ, remaining))
                raw._require(chunk, "Truncated fixed-slot body")
                remaining -= len(chunk)
                hashed.update(chunk)
                yield chunk
            raw._require(
                hashed.hexdigest() == reference["sha256"], "Object content differs"
            )
            raw._opened(path, descriptor, before)
        finally:
            os.close(descriptor)

    # Charge and fsync the actual preallocated object inode before publishing its index.
    def _put(self, sequence, kind, value):
        control = self._open(sequence)
        cap = self.limits["span_bytes"] if kind == "body" else raw.META - 1
        raw._require(
            type(value) is bytes and 0 < len(value) <= cap, "Object cap exhausted"
        )
        digest = raw._sha(value)
        offset, previous = self._bucket(kind, digest)
        if previous is not None:
            raw._require(
                b"".join(self._content(previous)) == value, "Dedup content differs"
            )
            return previous
        slot = control[kind]
        raw._require(slot < self.limits[f"{kind}_slots"], "Object slots exhausted")
        control[kind] += 1
        _write(self.root / "control", raw.META, control)
        size = self.limits["span_bytes"] if kind == "body" else raw.META
        path = self.root / kind / str(slot)
        before = raw._extent(path, size, 1)
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            raw._opened(path, descriptor, before)
            raw._require(
                os.pwrite(descriptor, value, 0) == len(value), "Short object write"
            )
            os.fsync(descriptor)
            raw._written(path, descriptor, before, size)
        finally:
            os.close(descriptor)
        reference = {"kind": kind, "slot": slot, "length": len(value), "sha256": digest}
        _write(
            self.root / "index",
            self.common["amounts"]["buckets"] * BUCKET,
            reference,
            offset=offset,
            capacity=BUCKET,
        )
        raw._require(
            b"".join(self._content(reference)) == value, "Object readback differs"
        )
        return reference

    # Traverse strict ordered fixed pages without decoding opaque native JSON bodies.
    def _walk(self, reference, level=None, ancestors=frozenset()):
        self._reference(reference)
        raw._require(reference["kind"] == "page", "Manifest must reference a page")
        raw._require(
            reference["sha256"] not in ancestors and len(ancestors) <= raw.DEPTH,
            "Manifest cycle/depth exceeded",
        )
        value = raw._decoded(b"".join(self._content(reference)))
        raw._require(
            type(value) is dict
            and set(value) == {"level", "refs"}
            and type(value["level"]) is int
            and 0 <= value["level"] <= raw.DEPTH
            and (level is None or value["level"] == level)
            and type(value["refs"]) is list
            and 1 <= len(value["refs"]) <= raw.FANOUT,
            "Exact bounded manifest page required",
        )
        for item in value["refs"]:
            if value["level"]:
                yield from self._walk(
                    item, value["level"] - 1, ancestors | {reference["sha256"]}
                )
            else:
                raw._require(
                    type(item) is dict
                    and set(item) == {"role", "content"}
                    and item["role"] in {"prefix", "row", "suffix"},
                    "Exact opaque span reference required",
                )
                self._reference(item["content"])
                raw._require(
                    item["content"]["kind"] == "body", "Opaque span must reference body"
                )
                yield item

    # Verify every opaque byte without treating it as account admission.
    def _verify(self, reference):
        self._reference(reference)
        raw._require(reference["kind"] == "page", "Root must reference a page")
        value = raw._decoded(b"".join(self._content(reference)))
        raw._require(
            type(value) is dict
            and set(value) == {"binding", "raw_sha256", "bytes", "rows", "tree"}
            and value["binding"] == self.binding
            and type(value["bytes"]) is int
            and 0 < value["bytes"] <= self.limits["raw_bytes"]
            and type(value["rows"]) is int
            and 0 <= value["rows"] <= self.limits["history_rows"],
            "Exact complete opaque root required",
        )
        raw._digest(value["raw_sha256"])
        hashed, total, rows, previous = hashlib.sha256(), 0, 0, None
        for item in self._walk(value["tree"]):
            role = item["role"]
            raw._require(
                (previous is None and role == "prefix")
                or (previous in {"prefix", "row"} and role in {"row", "suffix"}),
                "Opaque span ordering differs",
            )
            for chunk in self._content(item["content"]):
                total += len(chunk)
                raw._require(total <= value["bytes"], "Excess opaque bytes")
                hashed.update(chunk)
            rows += role == "row"
            previous = role
        raw._require(
            previous == "suffix"
            and total == value["bytes"]
            and rows == value["rows"]
            and hashed.hexdigest() == value["raw_sha256"],
            "Complete opaque bytes differ",
        )
        return value

    # Bind one fully verified local root to its immutable ARM witness.
    def _prepare(self, sequence, prior, reference):
        self._declaration()
        self._open(sequence)
        root = self._verify(reference)
        arm = self._record(sequence, "ARM")
        raw._require(arm is not None and arm["prior"] == prior, "Original ARM required")
        value = {
            "binding": self.binding,
            "peer": self.header["peer"],
            "sequence": sequence,
            "prior": prior,
            "root": reference,
            "arm": raw._sha(raw._encoded(arm)),
            "raw": root["raw_sha256"],
        }
        self._record(sequence, "PREPARED", value)
        return raw._sha(raw._encoded(value))

    # Advance fixed head banks only for an explicit owner decision.
    def _finish(self, sequence, prior, decision):
        self._declaration()
        control = self._control()
        if control["open"] is None:
            raw._require(
                control["head"] == decision and control["next"] == sequence + 1,
                "Conflicting completed head",
            )
            raw._require(
                _read(self.root / f"head{sequence % 2}", raw.META)
                == {"head": decision, "sequence": sequence},
                "Completed head bank differs",
            )
            return
        raw._require(
            control["open"] == sequence and control["head"] == prior,
            "Conflicting OPEN head",
        )
        _write(
            self.root / f"head{sequence % 2}",
            raw.META,
            {"head": decision, "sequence": sequence},
        )
        control.update(head=decision, open=None)
        _write(self.root / "control", raw.META, control)


# Provide in-process fixture transport without a client or network fallback.
class FixtureTransport:
    # Retain exactly two caller-created local peers and a named observation fault seam.
    def __init__(self, peers):
        raw._require(
            type(peers) is list
            and len(peers) == 2
            and all(type(p) is Peer for p in peers),
            "Two explicit local peers required",
        )
        self.peers = {peer.header["peer"]: peer for peer in peers}
        raw._require(len(self.peers) == 2, "Duplicate peer forbidden")

    # Expose acknowledgment uncertainty without claiming remote host evidence.
    def point(self, name):
        pass

    # Dispatch only bounded checkpoint operations inside the synthetic local process.
    def call(self, peer, operation, *args):
        raw._require(
            operation in {"_arm", "_put", "_prepare", "_finish"},
            "Known fixture operation required",
        )
        result = getattr(self.peers[peer], operation)(*args)
        self.point(f"after:{operation}:{peer}")
        return result


# Coordinate fixture witnesses without consensus, network or native behavior.
class Pair:
    # Require matching declarations, distinct namespaces and fixture transport.
    def __init__(self, transport):
        raw._require(
            type(transport) is FixtureTransport, "Explicit fixture transport required"
        )
        self.transport = transport
        self.peers = [transport.peers[key] for key in sorted(transport.peers)]
        first, second = self.peers
        raw._require(
            first.common == second.common
            and first.header["peer"] != second.header["peer"]
            and (first.root.stat().st_dev, first.root.stat().st_ino)
            != (second.root.stat().st_dev, second.root.stat().st_ino),
            "Exact distinct reservation pair required",
        )
        self.common, self.binding = _copy(first.common), first.binding
        raw._require(
            [peer.header["peer"] for peer in self.peers] == self.common["peers"],
            "Declared peer pair differs",
        )

    # Acquire local kernel locks in stable order without timeout elections.
    @contextmanager
    def _locked(self):
        with ExitStack() as stack:
            for peer in self.peers:
                stack.enter_context(peer._locked())
            yield

    # Durably store identical content on both peers before returning a reference.
    def _put(self, sequence, kind, value):
        refs = [
            self.transport.call(peer.header["peer"], "_put", sequence, kind, value)
            for peer in self.peers
        ]
        raw._require(refs[0] == refs[1], "Peer slot/root divergence")
        return refs[0]

    # Carry bounded pages upward without repeating a flat historical manifest.
    def _push(self, sequence, levels, level, reference):
        raw._require(level <= raw.DEPTH, "Manifest depth exhausted")
        levels[level].append(reference)
        if len(levels[level]) == raw.FANOUT:
            page = self._put(
                sequence, "page", raw._encoded({"level": level, "refs": levels[level]})
            )
            levels[level] = []
            self._push(sequence, levels, level + 1, page)

    # Close the bounded right edge while preserving identical prior row/page objects.
    def _tree(self, sequence, levels):
        for level in range(raw.DEPTH + 1):
            if not levels[level]:
                continue
            page = self._put(
                sequence, "page", raw._encoded({"level": level, "refs": levels[level]})
            )
            levels[level] = []
            if not any(levels[level + 1 :]):
                return page
            self._push(sequence, levels, level + 1, page)
        raise raw.PhysicalPause("Empty or excessive manifest")

    # Capture stable physical bytes without decoding native JSON.
    def _capture(self, sequence, source):
        source = raw._path(source)
        before = raw._regular(source)
        limits = self.common["limits"]
        raw._require(
            0 < before.st_size <= limits["raw_bytes"], "Raw byte cap exhausted"
        )
        levels, hashed, total, rows = (
            [[] for _ in range(raw.DEPTH + 1)],
            hashlib.sha256(),
            0,
            0,
        )
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as handle:
            raw._opened(source, handle.fileno(), before)
            for role, value in raw._spans(handle, limits):
                hashed.update(value)
                total += len(value)
                rows += role == "row"
                reference = self._put(sequence, "body", value)
                self._push(sequence, levels, 0, {"role": role, "content": reference})
            raw._opened(source, handle.fileno(), before)
        raw._require(total == before.st_size, "Physical framing omitted bytes")
        root = {
            "binding": self.binding,
            "raw_sha256": hashed.hexdigest(),
            "bytes": total,
            "rows": rows,
            "tree": self._tree(sequence, levels),
        }
        return self._put(sequence, "page", raw._encoded(root))

    # Verify an externally pinned prior decision and both completed peer witnesses.
    def _prior(self, sequence, prior):
        if sequence == 0:
            raw._require(prior == self.common["genesis"], "Exact genesis required")
            return
        owner = self.transport.peers[self.common["owner"]]
        decision = owner._record(sequence - 1, "DECISION")
        raw._require(
            decision is not None and raw._sha(raw._encoded(decision)) == prior,
            "Pinned prior decision differs",
        )
        self._decision(decision)
        for peer in self.peers:
            ack = peer._record(sequence - 1, "ACK")
            raw._require(
                ack
                == {
                    "binding": self.binding,
                    "peer": peer.header["peer"],
                    "decision": prior,
                    "resources": peer.header["resources_sha256"],
                },
                "Prior acknowledgment differs",
            )

    # Run at most one caller-labelled synthetic effect after both durable ARM readbacks.
    def run(self, effect, *, expected_prior):
        raw._digest(expected_prior)
        raw._require(callable(effect), "Explicit synthetic effect callback required")
        with self._locked():
            controls = [peer._control() for peer in self.peers]
            raw._require(
                all(
                    value["open"] is None and value["head"] == expected_prior
                    for value in controls
                )
                and controls[0]["next"] == controls[1]["next"],
                "PAUSED or stale pair; no effect replay",
            )
            sequence = controls[0]["next"]
            self._prior(sequence, expected_prior)
            arms = {
                peer.header["peer"]: self.transport.call(
                    peer.header["peer"], "_arm", sequence, expected_prior
                )
                for peer in self.peers
            }
            for peer in self.peers:
                raw._require(
                    raw._sha(raw._encoded(peer._record(sequence, "ARM")))
                    == arms[peer.header["peer"]],
                    "ARM acknowledgment differs",
                )
                peer._resources()
            self.transport.point("before:effect")
            source = effect()
            self.transport.point("after:effect")
            reference = self._capture(sequence, source)
            prepared = {
                peer.header["peer"]: self.transport.call(
                    peer.header["peer"], "_prepare", sequence, expected_prior, reference
                )
                for peer in self.peers
            }
            decision = {
                "binding": self.binding,
                "sequence": sequence,
                "prior": expected_prior,
                "owner": self.common["owner"],
                "root": reference,
                "prepared": prepared,
            }
            owner = self.transport.peers[self.common["owner"]]
            owner._record(sequence, "DECISION", decision)
            self.transport.point("owner:decision")
            return self._commit(decision)

    # Validate a decision against durable PREPARED records and complete bytes.
    def _decision(self, value):
        raw._require(
            type(value) is dict
            and set(value)
            == {"binding", "sequence", "prior", "owner", "root", "prepared"}
            and value["binding"] == self.binding
            and value["owner"] == self.common["owner"]
            and type(value["prepared"]) is dict
            and set(value["prepared"]) == set(self.common["peers"]),
            "Exact owner decision required",
        )
        raw._digest(value["prior"])
        for peer in self.peers:
            peer._declaration()
            arm = peer._record(value["sequence"], "ARM")
            raw._require(
                arm
                == {
                    "binding": self.binding,
                    "sequence": value["sequence"],
                    "prior": value["prior"],
                    "peer": peer.header["peer"],
                    "resources": peer.header["resources_sha256"],
                },
                "Decision original ARM differs",
            )
            prepared = peer._record(value["sequence"], "PREPARED")
            expected = {
                "binding": self.binding,
                "peer": peer.header["peer"],
                "sequence": value["sequence"],
                "prior": value["prior"],
                "root": value["root"],
                "arm": raw._sha(raw._encoded(arm)),
                "raw": peer._verify(value["root"])["raw_sha256"],
            }
            raw._require(
                prepared == expected
                and raw._sha(raw._encoded(prepared))
                == value["prepared"][peer.header["peer"]],
                "Owner decision PREPARED witness differs",
            )

    # Mirror an owner decision and acknowledgments without invoking an effect.
    def _commit(self, decision):
        self._decision(decision)
        sequence = decision["sequence"]
        digest = raw._sha(raw._encoded(decision))
        acknowledgments = {}
        for peer in self.peers:
            peer._record(sequence, "DECISION", decision)
            self.transport.point(f"decision:mirrored:{peer.header['peer']}")
            ack = {
                "binding": self.binding,
                "peer": peer.header["peer"],
                "decision": digest,
                "resources": peer.header["resources_sha256"],
            }
            peer._record(sequence, "ACK", ack)
            acknowledgments[peer.header["peer"]] = raw._sha(raw._encoded(ack))
            self.transport.point(f"ack:durable:{peer.header['peer']}")
        for peer in self.peers:
            self.transport.call(
                peer.header["peer"], "_finish", sequence, decision["prior"], digest
            )
        receipt = {
            "version": VERSION,
            "binding": self.binding,
            "sequence": sequence,
            "prior": decision["prior"],
            "decision": digest,
            "root": decision["root"],
            "acks": acknowledgments,
            **FALSE_CLAIMS,
        }
        self._completed(receipt)
        return receipt

    # Recover metadata under an external decision pin without any callback.
    def recover(self, *, sequence, expected_prior, owner_decision_sha256):
        raw._require(
            type(sequence) is int
            and 0 <= sequence < self.common["limits"]["operations"],
            "Exact external operation sequence required",
        )
        raw._digest(expected_prior)
        raw._digest(owner_decision_sha256)
        with self._locked():
            owner = self.transport.peers[self.common["owner"]]
            decision = owner._record(sequence, "DECISION")
            raw._require(
                type(decision) is dict
                and type(decision.get("sequence")) is int
                and decision["sequence"] == sequence
                and decision.get("prior") == expected_prior
                and raw._sha(raw._encoded(decision)) == owner_decision_sha256,
                "Externally pinned durable owner decision required",
            )
            return self._commit(decision)

    # Admit an external receipt, never a discovered latest object.
    def completed(self, receipt):
        with self._locked():
            return self._completed(receipt)

    # Recheck source, full content, heads and ACKs before returning a local receipt.
    def _completed(self, receipt):
        raw._require(
            type(receipt) is dict
            and set(receipt)
            == {
                "version",
                "binding",
                "sequence",
                "prior",
                "decision",
                "root",
                "acks",
                *FALSE_CLAIMS,
            }
            and receipt["version"] == VERSION
            and receipt["binding"] == self.binding
            and all(receipt[key] is False for key in FALSE_CLAIMS),
            "Exact local receipt required",
        )
        raw._require(
            type(receipt["acks"]) is dict
            and set(receipt["acks"]) == set(self.common["peers"]),
            "Exact acknowledgment map required",
        )
        owner = self.transport.peers[self.common["owner"]]
        decision = owner._record(receipt["sequence"], "DECISION")
        raw._require(
            type(decision) is dict
            and raw._sha(raw._encoded(decision)) == receipt["decision"]
            and type(decision.get("sequence")) is int
            and decision["sequence"] == receipt["sequence"]
            and decision.get("prior") == receipt["prior"]
            and decision.get("root") == receipt["root"],
            "Receipt owner decision differs",
        )
        self._decision(decision)
        for peer in self.peers:
            control = peer._control()
            ack = peer._record(receipt["sequence"], "ACK")
            head = _read(peer.root / f"head{receipt['sequence'] % 2}", raw.META)
            raw._require(
                control["open"] is None
                and control["head"] == receipt["decision"]
                and control["next"] == receipt["sequence"] + 1
                and peer._record(receipt["sequence"], "DECISION") == decision
                and head
                == {"head": receipt["decision"], "sequence": receipt["sequence"]}
                and ack
                == {
                    "binding": self.binding,
                    "peer": peer.header["peer"],
                    "decision": receipt["decision"],
                    "resources": peer.header["resources_sha256"],
                }
                and raw._sha(raw._encoded(ack)) == receipt["acks"][peer.header["peer"]],
                "Pair completion/acknowledgment differs",
            )
        return {"root": self.peers[0]._verify(receipt["root"]), **FALSE_CLAIMS}
