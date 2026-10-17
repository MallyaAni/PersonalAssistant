"""Native-only local synthetic extent fixtures; never run body allocation on Mac.

Two passive local roots represent fixture replicas, not real dual-host acceptance.
Set ANIOS_SYNTHETIC_SPOOL_ROOT only to a named isolated runtime's private /out.
"""

import errno
import hashlib
import json
import multiprocessing
import os
import signal
import sqlite3
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.market import historical_packet_demand as demand
from backend.market.historical_packet_spool import ReservedSpool
from backend.market.historical_packet_store import (
    CHUNK,
    MAX_ENTRY,
    MAX_META,
    Store,
    StorePause,
)
from backend.tests.test_historical_packet_store import mapping, paused, sha

OBSERVATIONS = []
BODY = demand.encoded({"quotes": {"AAPL": []}, "next_page_token": None})


# Create only a private synthetic query and charge, never call any transport.
def synthetic_store(root):
    store = Store(root, sha("spool identity"), None, create=True)
    value = paused(store, sha(str(root)), True)
    query = demand.read(value, mapping())["queries"][0]["sha256"]
    attempt = sha(str(root) + "attempt")
    store.begin_attempt(
        attempt=attempt,
        demand_sha256=value.sha256,
        query_sha256=query,
        page=0,
        token=None,
    )
    return store, attempt


# Reserve on both passive local fixture roots before allowing a fake response read.
def spied_read(stores, spools, raw, calls):
    for store, attempt in stores:
        store.reserve_read(attempt, sha(attempt + "read"), 128)
    calls.append("SYNTHETIC_READ_ONLY_AFTER_BOTH_RESERVATIONS")
    for (store, attempt), spool in zip(stores, spools, strict=True):
        store.confirm_read(sha(attempt + "read"), raw, spool=spool)


# Admit both passive local fixture spools before reaching a fake response read.
def prepare_then_spied(stores, calls):
    spools = [ReservedSpool(store, attempt, (128,)) for store, attempt in stores]
    spied_read(stores, spools, BODY, calls)


# Retain actual child files at the CAS boundary for the parent to inspect and kill.
def spool_child(root, connection, boundary):
    store, attempt = synthetic_store(root)
    spool = ReservedSpool(store, attempt, (128,))
    reservation = sha(attempt + "read")
    store.reserve_read(attempt, reservation, 128)

    # Report exact source/destination inode paths only after actual fsync or link.
    def fault(point):
        if point == boundary:
            connection.send(
                {
                    "point": point,
                    "head": store.snapshot()["head"],
                    "attempt": attempt,
                    "reservation": reservation,
                    "source": str(spool.root / "0"),
                    "sha": hashlib.sha256(BODY).hexdigest(),
                }
            )
            connection.recv()

    store.fault = fault
    store.confirm_read(reservation, BODY, spool=spool)
    raise AssertionError("Parent should kill at requested publication boundary")


# Exercise real fallocate and same-inode adoption only inside the named Linux fixture.
class PacketSpoolTests(unittest.TestCase):
    # Refuse accidental workstation body allocation before creating any fixture file.
    def setUp(self):
        base = os.environ.get("ANIOS_SYNTHETIC_SPOOL_ROOT", "")
        if sys.platform != "linux" or not base.startswith("/out/"):
            raise RuntimeError(
                "Run only in named native fixture with private /out root"
            )
        self.root = Path(base) / uuid4().hex
        self.root.mkdir(mode=0o700, parents=True)
        self.store, self.attempt = synthetic_store(self.root / "replica-a")
        self.others = []

    # Close descriptors but retain every private filesystem and failed orphan on Spark.
    def tearDown(self):
        self.store.close()
        for store in self.others:
            store.close()

    # Finalize a synthetic response with the same explicit preallocated spool.
    def finish(self, spool):
        return self.store.finish_attempt(
            self.attempt,
            status=200,
            complete=True,
            failure=None,
            requested_at="SYNTHETIC",
            received_at="SYNTHETIC",
            spool=spool,
        )

    # Real physical extents bound chunks, assembled body and receipt metadata exactly.
    def test_physical_finite_allowance_and_private_files(self):
        spool = ReservedSpool(self.store, self.attempt, (128, 256))
        assert spool.logical_ceiling == 2 * (128 + 256) + MAX_META + MAX_ENTRY
        assert spool.logical_ceiling <= spool.allocated_bytes <= spool.physical_ceiling
        for name in spool.files:
            info = (spool.root / name).stat()
            assert info.st_mode & 0o777 == 0o600
            if name != "manifest":
                assert info.st_blocks * 512 >= spool.files[name]["capacity"]
        allocation = json.loads(self.store.read_blob(spool.allocation, limit=MAX_META))
        assert allocation["sqlite_and_directory_headroom_reserved"] is False
        assert allocation["real_two_host_replication"] is False
        OBSERVATIONS.append(
            {
                "kind": "SYNTHETIC_LOCAL_ALLOCATION",
                "root": str(spool.root),
                "logical_ceiling": spool.logical_ceiling,
                "allocated_bytes": spool.allocated_bytes,
                "physical_ceiling": spool.physical_ceiling,
            }
        )

    # Unsupported physical allocation pauses and cannot silently use sparse files.
    def test_unsupported_allocator_and_no_default_fallback(self):
        with (
            patch("os.posix_fallocate", None),
            pytest.raises(StorePause, match="unsupported"),
        ):
            ReservedSpool(self.store, self.attempt, (128,))
        self.store.reserve_read(self.attempt, sha("read"), 128)
        with pytest.raises(StorePause, match="spool"):
            self.store.confirm_read(sha("read"), BODY)
        assert self.store.snapshot()["confirmed_bytes"] == 0
        other, attempt = synthetic_store(self.root / "unsupported-syscall")
        self.others.append(other)
        with (
            patch(
                "os.posix_fallocate", side_effect=OSError(errno.EOPNOTSUPP, "SYNTHETIC")
            ),
            pytest.raises(StorePause, match="allocation failed"),
        ):
            ReservedSpool(other, attempt, (128,))

    # ENOSPC on either passive fixture replica occurs before the external-read spy.
    def test_either_replica_allocation_failure_precedes_read(self):
        real = os.posix_fallocate
        for failed in ("replica-a", "replica-b"):
            with self.subTest(failed=failed):
                left, attempt_left = synthetic_store(self.root / (failed + "-left"))
                right, attempt_right = synthetic_store(self.root / (failed + "-right"))
                self.others.extend((left, right))
                calls = []

                # Fail the selected descriptor while retaining earlier real extents.
                def allocate(descriptor, offset, length, failed=failed):
                    path = os.readlink("/proc/self/fd/" + str(descriptor))
                    wanted = "-left/" if failed == "replica-a" else "-right/"
                    if wanted in path:
                        raise OSError(errno.ENOSPC, "SYNTHETIC ENOSPC")
                    return real(descriptor, offset, length)

                with (
                    patch("os.posix_fallocate", side_effect=allocate),
                    pytest.raises(StorePause, match="allocation failed"),
                ):
                    prepare_then_spied(
                        [(left, attempt_left), (right, attempt_right)], calls
                    )
                assert calls == []
                OBSERVATIONS.append(
                    {
                        "kind": "SYNTHETIC_REPLICA_ENOSPC",
                        "failed": failed,
                        "external_read_calls": len(calls),
                    }
                )

    # Fixed cap failures and charged budget exhaustion both precede a fake body read.
    def test_cap_exhaustion_precedes_read(self):
        calls = []
        with pytest.raises(StorePause, match="allowance"):
            ReservedSpool(self.store, self.attempt, (CHUNK,) * 321)
        assert calls == []
        other, attempt = synthetic_store(self.root / "budget")
        self.others.append(other)
        spool = ReservedSpool(other, attempt, (128,))
        with other._transaction():
            state = other._state()
            state["used"]["body_bytes"] = demand.BUDGET["body_bytes"]
            other._write_state(state)
        with pytest.raises(ValueError, match="cap"):
            spied_read([(other, attempt)], [spool], BODY, calls)
        assert calls == []

    # All body/metadata publications reuse their exact original preallocated inodes.
    def test_two_local_replicas_same_inodes_and_no_put_stream_copy(self):
        right, attempt_right = synthetic_store(self.root / "replica-b")
        self.others.append(right)
        stores = [(self.store, self.attempt), (right, attempt_right)]
        with patch.object(
            Store, "put_stream", side_effect=AssertionError("Unreserved copy")
        ):
            spools = [
                ReservedSpool(store, attempt, (128, 128)) for store, attempt in stores
            ]
            calls = []
            middle = len(BODY) // 2
            for index, raw in enumerate((BODY[:middle], BODY[middle:])):
                for store, attempt in stores:
                    store.reserve_read(attempt, sha(attempt + str(index)), 128)
                calls.append("SYNTHETIC_READ_AFTER_BOTH_RESERVATIONS")
                for (store, attempt), spool in zip(stores, spools, strict=True):
                    store.confirm_read(sha(attempt + str(index)), raw, spool=spool)
            for (store, attempt), spool in zip(stores, spools, strict=True):
                receipt = store.finish_attempt(
                    attempt,
                    status=200,
                    complete=True,
                    failure=None,
                    requested_at="SYNTHETIC",
                    received_at="SYNTHETIC",
                    spool=spool,
                )
                assert store.read_blob(receipt["body_sha256"], limit=128) == BODY
                for name, (_, digest, length) in spool.sealed.items():
                    source, destination = (
                        spool.root / name,
                        store.root / "blobs" / digest,
                    )
                    assert (source.stat().st_dev, source.stat().st_ino) == (
                        destination.stat().st_dev,
                        destination.stat().st_ino,
                    )
                    assert destination.stat().st_size == length
                OBSERVATIONS.append(
                    {
                        "kind": "SYNTHETIC_SAME_INODE",
                        "root": str(store.root),
                        "body_inode": (store.root / "blobs" / receipt["body_sha256"])
                        .stat()
                        .st_ino,
                        "put_stream_calls": 0,
                    }
                )
            assert len(calls) == 2

    # Wrong owner, allocation, inode, digest and length cannot become CAS references.
    def test_wrong_reference_hash_and_length_are_refused(self):
        spool = ReservedSpool(self.store, self.attempt, (128,))
        ref, digest, length = spool.chunk(sha("read"), BODY, 128)
        for wrong in (
            replace(ref, owner="foreign"),
            replace(ref, allocation=sha("wrong")),
            replace(ref, inode=ref.inode + 1),
            replace(ref, name="../body"),
        ):
            with (
                self.subTest(wrong=str(wrong)),
                pytest.raises(StorePause, match="reference"),
            ):
                self.store.adopt_spool(
                    spool, wrong, expected_sha256=digest, length=length
                )
        for bad_hash, bad_length in ((sha("wrong"), length), (digest, length + 1)):
            with pytest.raises(StorePause, match="reference"):
                self.store.adopt_spool(
                    spool, ref, expected_sha256=bad_hash, length=bad_length
                )
        assert not (self.store.root / "blobs" / digest).exists()

    # A sealed file changed in place fails its actual digest before CAS publication.
    def test_changed_sealed_bytes_are_refused(self):
        spool = ReservedSpool(self.store, self.attempt, (128,))
        ref, digest, length = spool.chunk(sha("read"), BODY, 128)
        descriptor = os.open(spool.root / "0", os.O_RDWR)
        try:
            os.pwrite(descriptor, b"x", 0)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        with pytest.raises(StorePause, match="digest"):
            self.store.adopt_spool(spool, ref, expected_sha256=digest, length=length)
        assert not (self.store.root / "blobs" / digest).exists()

    # Assembled bytes must still equal the original committed chunk sequence.
    def test_changed_assembled_body_is_refused(self):
        spool = ReservedSpool(self.store, self.attempt, (128,))
        self.store.reserve_read(self.attempt, sha("read"), 128)
        self.store.confirm_read(sha("read"), BODY, spool=spool)
        changed = BODY.replace(b"AAPL", b"AXPL")
        assert len(changed) == len(BODY)
        assert changed != BODY
        descriptor = os.open(spool.root / "body", os.O_RDWR)
        try:
            os.pwrite(descriptor, changed, 0)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        with pytest.raises(StorePause, match="assembled body"):
            self.finish(spool)
        assert not (
            self.store.root / "blobs" / hashlib.sha256(changed).hexdigest()
        ).exists()

    # Unreserved fallback, repeated writes and altered chunk ordering stay refused.
    def test_missing_spool_repeat_and_wrong_chunk_refs_refuse(self):
        spool = ReservedSpool(self.store, self.attempt, (128,))
        reservation = sha("read")
        self.store.reserve_read(self.attempt, reservation, 128)
        with pytest.raises(StorePause, match="spool"):
            self.store.confirm_read(reservation, BODY)
        self.store.confirm_read(reservation, BODY, spool=spool)
        with pytest.raises(StorePause, match="spool"):
            self.finish(None)
        with pytest.raises(StorePause, match="references"):
            spool.body([])
        result = self.finish(spool)
        before = self.store.read_blob(result["body_sha256"], limit=128)
        with pytest.raises(StorePause, match="allowance"):
            spool.chunk(sha("again"), b"changed", 128)
        with pytest.raises(StorePause, match="unsealed"):
            spool.receipt(b"changed")
        assert self.store.read_blob(result["body_sha256"], limit=128) == before

    # Publication ENOSPC retains sealed source bytes without confirming the read.
    def test_cas_link_enospc_retains_orphan(self):
        spool = ReservedSpool(self.store, self.attempt, (128,))
        self.store.reserve_read(self.attempt, sha("read"), 128)
        with (
            patch("os.link", side_effect=OSError(errno.ENOSPC, "SYNTHETIC")),
            pytest.raises(StorePause, match="adoption failed"),
        ):
            self.store.confirm_read(sha("read"), BODY, spool=spool)
        assert (spool.root / "0").read_bytes() == BODY
        assert self.store.snapshot()["confirmed_bytes"] == 0
        assert self.store.snapshot()["unresolved"]["body_bytes"] == 128

    # A SQLite commit failure keeps orphan CAS and the original unresolved charge.
    def test_sqlite_enospc_retains_orphan_without_false_confirmation(self):
        spool = ReservedSpool(self.store, self.attempt, (128,))
        self.store.reserve_read(self.attempt, sha("read"), 128)
        with (
            patch.object(
                self.store,
                "_write_state",
                side_effect=sqlite3.OperationalError("SYNTHETIC disk full"),
            ),
            pytest.raises(StorePause, match="orphan CAS"),
        ):
            self.store.confirm_read(sha("read"), BODY, spool=spool)
        digest = hashlib.sha256(BODY).hexdigest()
        assert self.store.read_blob(digest, limit=128) == BODY
        row = self.store.connection.execute(
            "SELECT actual FROM reads WHERE id=?", (sha("read"),)
        ).fetchone()
        assert row[0] is None
        assert self.store.snapshot()["confirmed_bytes"] == 0

    # Final receipt commit failure keeps body/receipt CAS without declaring success.
    def test_response_sqlite_enospc_retains_body_and_receipt_orphans(self):
        spool = ReservedSpool(self.store, self.attempt, (128,))
        self.store.reserve_read(self.attempt, sha("read"), 128)
        self.store.confirm_read(sha("read"), BODY, spool=spool)
        with (
            patch.object(
                self.store,
                "_write_state",
                side_effect=sqlite3.OperationalError("SYNTHETIC disk full"),
            ),
            pytest.raises(StorePause, match="orphan CAS"),
        ):
            self.finish(spool)
        row = self.store.connection.execute(
            "SELECT status,body,raw FROM attempts WHERE id=?",
            (self.attempt,),
        ).fetchone()
        assert tuple(row) == ("OPEN", None, None)
        assert self.store.snapshot()["unresolved"]["get_attempts"] == 1
        assert self.store.snapshot()["confirmed_bytes"] == len(BODY)
        for name in ("body", "receipt"):
            _, digest, length = spool.sealed[name]
            assert (
                len(self.store.read_blob(digest, limit=spool.files[name]["capacity"]))
                == length
            )

    # Real SIGKILL retains absent or published CAS at the actual durability boundary.
    def test_sigkill_before_after_cas_publication(self):
        self.store.close()
        context = multiprocessing.get_context("spawn")
        for boundary in ("spool_fsynced", "spool_linked"):
            with self.subTest(boundary=boundary):
                parent, remote = context.Pipe()
                root = self.root / boundary
                process = context.Process(
                    target=spool_child, args=(root, remote, boundary)
                )
                process.start()
                remote.close()
                assert parent.poll(20)
                observed = parent.recv()
                assert observed["point"] == boundary
                destination = root / "blobs" / observed["sha"]
                assert destination.exists() == (boundary == "spool_linked")
                if destination.exists():
                    assert (
                        destination.stat().st_ino
                        == Path(observed["source"]).stat().st_ino
                    )
                os.kill(process.pid, signal.SIGKILL)
                process.join(20)
                assert process.exitcode == -signal.SIGKILL
                parent.close()
                resumed = Store(root, sha("spool identity"), observed["head"])
                try:
                    assert resumed.snapshot()["confirmed_bytes"] == 0
                    assert resumed.snapshot()["unresolved"]["body_bytes"] == 128
                    with pytest.raises(StorePause, match="Interrupted"):
                        resumed.confirm_read(observed["reservation"], BODY)
                finally:
                    resumed.close()
                OBSERVATIONS.append(
                    {
                        "kind": "SYNTHETIC_SPOOL_SIGKILL",
                        **observed,
                        "child_exitcode": process.exitcode,
                        "cas_present": destination.exists(),
                        "read_confirmed": False,
                    }
                )


if __name__ == "__main__":
    unittest.main()
