"""Unused local extent reservations; no transport or cross-host replication.

Only response chunks, assembled body and bounded receipt/manifest bytes are
physically reserved. SQLite journals and filesystem directory metadata still need
separate headroom. An allocation or commit failure pauses and retains orphans.
"""

import hashlib
import os
import stat
from dataclasses import dataclass
from uuid import uuid4

from backend.market import historical_packet_demand as demand
from backend.market.historical_packet_store import (
    CHUNK,
    MAX_ENTRY,
    MAX_META,
    StorePause,
    _private,
    _require,
    _sync_directory,
)


# Bind an original reserved inode to one Store owner and allocation manifest.
@dataclass(frozen=True)
class SpoolRef:
    owner: str
    identity: str
    attempt: str
    allocation: str
    name: str
    device: int
    inode: int
    capacity: int


# Reserve real local extents before any caller reads a response body.
class ReservedSpool:
    # Allocate finite response and metadata files without a sparse-file fallback.
    def __init__(self, store, attempt, chunk_allowances):
        store._owned_attempt(attempt)
        _require(attempt not in store._spools, "Original spool already bound; pause")
        self.store, self.attempt, self.owner = store, attempt, store.owner
        store._spools[attempt] = self
        _require(
            type(chunk_allowances) is tuple
            and 0 < len(chunk_allowances) <= 321
            and all(type(cap) is int and 0 < cap <= CHUNK for cap in chunk_allowances)
            and sum(chunk_allowances) <= demand.BUDGET["bytes_per_group"],
            "Finite original chunk/body allowance required",
        )
        _require(
            callable(getattr(os, "posix_fallocate", None)),
            "Physical allocation unsupported",
        )
        self.capacities = chunk_allowances
        self.root = store.root / "incoming" / ("spool-" + uuid4().hex)
        self.root.mkdir(mode=0o700)
        _private(self.root, True)
        unit = os.statvfs(self.root).f_frsize
        _require(
            type(unit) is int and 0 < unit <= 1024**2,
            "Bounded allocation unit required",
        )
        self.files, self.sealed, self.chunks = {}, {}, []
        self.offset = 0
        self.allocation = None
        caps = {
            **{str(index): cap for index, cap in enumerate(chunk_allowances)},
            "body": sum(chunk_allowances),
            "manifest": MAX_META,
            "receipt": MAX_ENTRY,
        }
        self.logical_ceiling = sum(caps.values())
        self.physical_ceiling = sum(
            ((cap + unit - 1) // unit) * unit for cap in caps.values()
        )
        for name, cap in caps.items():
            self.files[name] = self._allocate(name, cap, unit)
        self.allocated_bytes = sum(
            row["allocated_bytes"] for row in self.files.values()
        )
        metadata = {
            "schema": "historical-local-spool/1",
            "identity": store.identity,
            "owner": self.owner,
            "attempt": attempt,
            "files": self.files,
            "logical_ceiling": self.logical_ceiling,
            "physical_ceiling": self.physical_ceiling,
            "allocated_bytes": self.allocated_bytes,
            "sqlite_and_directory_headroom_reserved": False,
            "real_two_host_replication": False,
            "acquisition_authorized": False,
        }
        raw = demand.encoded(metadata)
        _require(len(raw) <= MAX_META, "Allocation manifest cap")
        self.allocation = hashlib.sha256(raw).hexdigest()
        self._write_at("manifest", raw, 0)
        ref, sha, length = self._seal("manifest", len(raw))
        store.adopt_spool(self, ref, expected_sha256=sha, length=length)
        _sync_directory(self.root)
        _sync_directory(store.root / "incoming")

    # Retain an actual allocated private file and its finite filesystem-rounded bound.
    def _allocate(self, name, capacity, unit):
        descriptor = os.open(
            self.root / name, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600
        )
        try:
            try:
                os.posix_fallocate(descriptor, 0, capacity)
                os.fsync(descriptor)
            except OSError as error:
                raise StorePause(
                    "Physical allocation failed; retain partial spool"
                ) from error
            info = os.fstat(descriptor)
            allocated = info.st_blocks * 512
            _require(
                info.st_size == capacity
                and capacity <= allocated <= ((capacity + unit - 1) // unit) * unit,
                "Physical extent reservation differs from finite allowance",
            )
            return {
                "device": info.st_dev,
                "inode": info.st_ino,
                "capacity": capacity,
                "allocated_bytes": allocated,
            }
        finally:
            os.close(descriptor)

    # Refuse another owner, symlink, changed inode or foreign path before any write.
    def _open(self, name, flags):
        _require(self.store.owner == self.owner, "Original live spool owner required")
        _private(self.root, True)
        row = self.files[name]
        try:
            descriptor = os.open(self.root / name, flags | os.O_NOFOLLOW)
        except OSError as error:
            raise StorePause("Original reserved path unavailable") from error
        info = os.fstat(descriptor)
        if not (
            stat.S_ISREG(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_dev == row["device"]
            and info.st_ino == row["inode"]
        ):
            os.close(descriptor)
            raise StorePause("Original reserved inode required")
        return descriptor

    # Write bounded bytes only inside their already-allocated original extents.
    def _write_at(self, name, raw, offset):
        _require(
            name not in self.sealed
            and type(raw) is bytes
            and type(offset) is int
            and offset >= 0
            and offset + len(raw) <= self.files[name]["capacity"],
            "Original unsealed spool capacity required",
        )
        descriptor = self._open(name, os.O_RDWR)
        try:
            written = 0
            while written < len(raw):
                count = os.pwrite(descriptor, raw[written:], offset + written)
                _require(count > 0, "Reserved spool write made no progress")
                written += count
        except OSError as error:
            raise StorePause("Reserved write failed; retain uncertain spool") from error
        finally:
            os.close(descriptor)

    # Seal the same inode and independently hash its exact written prefix.
    def _seal(self, name, length):
        _require(name not in self.sealed, "Sealed spool cannot be rewritten")
        _require(
            type(length) is int and 0 <= length <= self.files[name]["capacity"],
            "Seal length cap",
        )
        descriptor = self._open(name, os.O_RDWR)
        try:
            os.ftruncate(descriptor, length)
            os.fsync(descriptor)
            digest, total = hashlib.sha256(), 0
            while total < length:
                raw = os.pread(descriptor, min(CHUNK, length - total), total)
                _require(bool(raw), "Reserved spool truncated during sealing")
                digest.update(raw)
                total += len(raw)
        except OSError as error:
            raise StorePause("Reserved seal failed; retain uncertain spool") from error
        finally:
            os.close(descriptor)
        ref = self.reference(name)
        self.sealed[name] = (ref, digest.hexdigest(), length)
        return self.sealed[name]

    # Return an exact immutable binding instead of accepting a caller pathname.
    def reference(self, name):
        row = self.files[name]
        return SpoolRef(
            self.owner,
            self.store.identity,
            self.attempt,
            self.allocation,
            name,
            row["device"],
            row["inode"],
            row["capacity"],
        )

    # Resolve only this original sealed reference with its exact length and digest.
    def resolve(self, ref, sha, length):
        _require(
            type(ref) is SpoolRef
            and ref.name in self.sealed
            and self.sealed[ref.name] == (ref, sha, length)
            and ref == self.reference(ref.name),
            "Exact sealed spool reference/hash/length required",
        )
        descriptor = self._open(ref.name, os.O_RDONLY)
        os.close(descriptor)
        return self.root / ref.name

    # Write one original read into both its chunk and assembled reserved files.
    def chunk(self, reservation, raw, allowance):
        index = len(self.chunks)
        _require(
            index < len(self.capacities)
            and allowance == self.capacities[index]
            and type(raw) is bytes
            and len(raw) <= allowance,
            "Exact declared next chunk allowance required",
        )
        self._write_at(str(index), raw, 0)
        self._write_at("body", raw, self.offset)
        sealed = self._seal(str(index), len(raw))
        self.offset += len(raw)
        self.chunks.append((reservation, sealed[1], len(raw)))
        return sealed

    # Seal only assembled bytes matching the original committed chunk sequence.
    def body(self, chunks):
        expected = [(row["id"], row["blob"], row["actual"]) for row in chunks]
        _require(
            expected == self.chunks, "Original committed chunk references required"
        )
        digest = hashlib.sha256()
        for row in chunks:
            raw = self.store.read_blob(row["blob"], limit=CHUNK)
            _require(len(raw) == row["actual"], "Original chunk length differs")
            digest.update(raw)
        sealed = self._seal("body", self.offset)
        _require(
            sealed[1] == digest.hexdigest(),
            "Original assembled body differs from committed chunks",
        )
        return sealed

    # Keep bounded canonical receipt bytes on their own preallocated original inode.
    def receipt(self, raw):
        _require(len(raw) <= MAX_ENTRY, "Reserved receipt metadata cap")
        self._write_at("receipt", raw, 0)
        return self._seal("receipt", len(raw))
