"""Deferred synthetic source/native-writer tests; no execution on import.

Pure fixtures instantiate ONLY three exact a8 code objects in a synthetic
namespace. The separately named native parity test imports actual paper ONLY
when ROOT authorizes a native fixture. No account, broker, planner or model runs.
Every work/anchor/failed slot stays under /out/cases for independent inspection.
"""

import builtins
import dataclasses
import fcntl
import hashlib
import json
import multiprocessing
import os
import re
import signal
import tempfile
import unittest
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import CodeType, FunctionType
from unittest.mock import patch

from backend.market import historical_native_write_reservation as reservation


# Require an exact refusal without adding a pytest import or loading repo conftest.
@contextmanager
def refuses(errors, match=None):
    caught = None
    try:
        yield
    except errors as error:
        caught = error
    if caught is None:
        raise AssertionError(f"Expected refusal: {errors}")
    if match is not None:
        assert re.search(match, str(caught)) is not None


# Carry fake fields through the exact native writer without pretending to be an account.
@dataclasses.dataclass
class SyntheticPaper:
    history: list
    marker: str = "SYNTHETIC_NOT_ACCOUNT"


# Extract native code from full compilation without executing its module or imports.
def source_writer(path):
    compiled = compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
    selected = {
        item.co_name: item
        for item in compiled.co_consts
        if type(item) is CodeType and item.co_name in reservation.NAMES
    }
    assert set(selected) == reservation.NAMES
    namespace = {
        "__name__": "SYNTHETIC_NATIVE_FUNCTION_SOURCE_ONLY",
        "__builtins__": vars(builtins),
        "Path": Path,
        "PAPER_KIND": "paper",
        "PaperState": SyntheticPaper,
        "tempfile": tempfile,
        "json": json,
        "os": os,
        "is_dataclass": dataclasses.is_dataclass,
        "fields": dataclasses.fields,
    }
    namespace.update(
        {name: FunctionType(code, namespace, name) for name, code in selected.items()}
    )
    return namespace["save_state"]


# Kill only the fixture child at an explicitly named infrastructure boundary.
def killed_save(root, identity_sha256, source, point):
    writer = source_writer(source)
    pool = reservation.ReservedWriter(
        root, writer=writer, writer_source=source, identity_sha256=identity_sha256
    )

    # Preserve real native filesystem work before simulating a process crash.
    def cut(name):
        if name == point:
            os.kill(os.getpid(), signal.SIGKILL)

    pool._point = cut
    pool.save(SyntheticPaper([{"value": float("nan")}]), expected_preimage=None)


# Exercise real file syscalls and a8 writer code with explicitly fake state only.
class NativeWriteReservationTests(unittest.TestCase):
    # Read only reviewed public CURRENT identity/source fixtures before a test starts.
    @classmethod
    def setUpClass(cls):
        cls.source = Path("/fixture/current-writer.py")
        path = Path("/fixture/current-identity.json")
        assert path.stat().st_size < 32768
        cls.identity = json.loads(path.read_bytes())
        cls.pin = reservation.physical._sha(reservation.physical._encoded(cls.identity))

    # Retain each finite synthetic pool rather than deleting failed/crashed evidence.
    def setUp(self):
        retained = Path("/out/cases")
        retained.mkdir(mode=0o700, exist_ok=True)
        self.root = Path(
            tempfile.mkdtemp(prefix=f"SYNTHETIC-{self._testMethodName}-", dir=retained)
        )

    # Create one fresh pool from the exact pure source function fixture.
    def pool(self, name="pool", slots=2, writer=None):
        writer = source_writer(self.source) if writer is None else writer
        return reservation.reserve(
            self.root / name,
            writer=writer,
            writer_source=self.source,
            identity=self.identity,
            identity_sha256=self.pin,
            slots=slots,
        )

    # Verify a different callable with unchanged code and exactly one changed global.
    def test_distinct_callable_and_opaque_byte_parity(self):
        pool = self.pool()
        writer = pool.writer
        state = SyntheticPaper(
            [
                {
                    "nan": float("nan"),
                    "infinity": float("inf"),
                    "text": 'line\n\rBMP\u00e9 astral\U0001f680 surrogate\ud800 \\"',
                }
            ]
        )
        original_factory = tempfile.NamedTemporaryFile
        control_root = self.root / "ordinary-writer-control"
        writer(control_root, state)
        expected = (control_root / "paper/state.json").read_bytes()
        receipt = pool.save(state, expected_preimage=None)
        current = pool.root / "work/paper/state.json"
        assert current.read_bytes() == expected
        assert b"NaN" in expected
        assert b"Infinity" in expected
        assert receipt["state"]["sha256"] == hashlib.sha256(expected).hexdigest()
        assert current.stat().st_ino == (pool.root / "anchors/0").stat().st_ino
        assert current.stat().st_size == len(expected) < reservation.SLOT_BYTES
        assert pool._clone is not writer
        assert pool._clone.__code__ is writer.__code__
        assert [
            key
            for key in writer.__globals__
            if pool._clone.__globals__[key] is not writer.__globals__[key]
        ] == ["tempfile"]
        assert tempfile.NamedTemporaryFile is original_factory
        assert pool.completed() == receipt
        assert receipt["native_operation_adopted"] is False
        assert pool.header["directory_metadata_reserved"] is False

    # Preserve old anchor bytes and require the exact current preimage for saving.
    def test_preimage_binding_replacement_and_slot_exhaustion(self):
        pool = self.pool()
        first = pool.save(SyntheticPaper([{"x": 1}]), expected_preimage=None)
        prior = (pool.root / "anchors/0").read_bytes()
        with refuses(reservation.physical.PhysicalPause, "prior image"):
            pool.save(SyntheticPaper([]), expected_preimage=None)
        second = pool.save(SyntheticPaper([{"x": 2}]), expected_preimage=first["state"])
        assert first["state"]["inode"] != second["state"]["inode"]
        assert (pool.root / "anchors/0").read_bytes() == prior
        with refuses(reservation.physical.PhysicalPause, "exhausted"):
            pool.save(SyntheticPaper([]), expected_preimage=second["state"])
        assert pool.completed() == second

    # Refuse a foreign destination before arming an unused native slot.
    def test_unexpected_destination_and_corrupt_preimage_refuse(self):
        pool = self.pool()
        destination = pool.root / "work/paper/state.json"
        destination.write_bytes(b"SYNTHETIC FOREIGN")
        destination.chmod(0o600)
        with refuses(reservation.physical.PhysicalPause, "existing native destination"):
            pool.save(SyntheticPaper([]), expected_preimage=None)
        assert pool._control()["next_slot"] == 0
        assert destination.read_bytes() == b"SYNTHETIC FOREIGN"
        destination.unlink()
        first = pool.save(SyntheticPaper([]), expected_preimage=None)
        with destination.open("r+b") as handle:
            handle.write(b"!")
        with refuses(reservation.physical.PhysicalPause, "preimage differs"):
            pool.save(SyntheticPaper([]), expected_preimage=first["state"])
        assert pool._control()["next_slot"] == 1

    # Refuse mixed identity, changed function/default/global bindings and mutated code.
    def test_source_and_callable_drift_refuse(self):
        identity = deepcopy(self.identity)
        identity["source_revision"] = "ad44d536a70d5c037cb931836a3c9f48b014d84a"
        with refuses(reservation.physical.PhysicalPause, "CURRENT profile"):
            reservation.reserve(
                self.root / "mixed",
                writer=source_writer(self.source),
                writer_source=self.source,
                identity=identity,
                identity_sha256=reservation.physical._sha(
                    reservation.physical._encoded(identity)
                ),
                slots=1,
            )
        pool = self.pool()
        writer = pool.writer
        old = writer.__globals__["PAPER_KIND"]
        writer.__globals__["PAPER_KIND"] = "SYNTHETIC-OTHER"
        with refuses(reservation.physical.PhysicalPause, "globals drift"):
            pool.save(SyntheticPaper([]), expected_preimage=None)
        writer.__globals__["PAPER_KIND"] = old
        writer.__defaults__ = (None,)
        with refuses(reservation.physical.PhysicalPause, "native writer callable"):
            pool.save(SyntheticPaper([]), expected_preimage=None)
        writer.__defaults__ = None
        original_code = writer.__code__
        writer.__code__ = writer.__globals__["state_path"].__code__
        with refuses(reservation.physical.PhysicalPause, "native writer callable"):
            pool.save(SyntheticPaper([]), expected_preimage=None)
        writer.__code__ = original_code
        assert pool._control()["next_slot"] == 0
        changed = self.root / "SYNTHETIC-changed-writer.py"
        changed.write_bytes(self.source.read_bytes() + b"\n# SYNTHETIC source drift\n")
        with refuses(reservation.physical.PhysicalPause):
            reservation.reserve(
                self.root / "changed-source",
                writer=source_writer(self.source),
                writer_source=changed,
                identity=self.identity,
                identity_sha256=self.pin,
                slots=1,
            )
        assert not (self.root / "changed-source").exists()

    # Refuse drift of the NEW callable's attributes before charging any operation.
    def test_new_callable_attributes_must_remain_exact(self):
        pool = self.pool(slots=1)
        for attribute, replacement in (
            ("__defaults__", (None,)),
            ("__kwdefaults__", {"unexpected": 1}),
            ("__name__", "different"),
            ("__annotations__", {"unexpected": str}),
        ):
            old = getattr(pool._clone, attribute)
            setattr(pool._clone, attribute, replacement)
            with refuses(reservation.physical.PhysicalPause, "NEW callable attributes"):
                pool.save(SyntheticPaper([]), expected_preimage=None)
            setattr(pool._clone, attribute, old)
        assert pool._control()["next_slot"] == 0

    # Block completion readers during a writer and reject a substituted reader lock.
    def test_completion_uses_shared_real_lock_and_identity_bookends(self):
        pool = self.pool(slots=1)
        receipt = pool.save(SyntheticPaper([]), expected_preimage=None)
        descriptor = os.open(pool.root / "lock", os.O_RDWR | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with refuses(reservation.physical.PhysicalPause, "already active"):
                pool.completed()
        finally:
            os.close(descriptor)
        assert pool.completed() == receipt
        target = pool.root / "lock"
        replacement = pool.root / "SYNTHETIC-reader-lock-replacement"
        reservation.physical._allocate(replacement, 4096)
        original_open = os.open

        # Substitute only after lstat so the reader must reject its opened fd.
        def substituted(path, *args, **kwargs):
            if Path(path) == target:
                os.replace(target, pool.root / "SYNTHETIC-old-reader-lock")
                os.replace(replacement, target)
            return original_open(path, *args, **kwargs)

        with (
            patch.object(os, "open", side_effect=substituted),
            refuses(reservation.physical.PhysicalPause),
        ):
            pool.completed()

    # Reject unknown native factory arguments after a durable charged OPEN marker.
    def test_strict_factory_arguments_leave_uncertainty(self):
        pool = self.pool(slots=1)

        # Exercise refusal through only the private factory, never shared tempfile.
        def bad_arguments(name):
            if name == "armed":
                pool._factory(
                    mode="a",
                    encoding="utf-8",
                    dir=pool.root / "work/paper",
                    delete=False,
                )

        pool._point = bad_arguments
        with refuses(reservation.physical.PhysicalPause, "temporary arguments"):
            pool.save(SyntheticPaper([]), expected_preimage=None)
        assert pool._control()["operation"] == 0
        assert pool._control()["next_slot"] == 1
        with refuses(reservation.physical.PhysicalPause, "OPEN"):
            pool.completed()

    # Bound encoded bytes before an overflowing physical write can extend its inode.
    def test_byte_overflow_preserves_old_state_and_charges_slot(self):
        pool = self.pool()
        first = pool.save(SyntheticPaper([]), expected_preimage=None)
        prior = (pool.root / "work/paper/state.json").read_bytes()
        state = SyntheticPaper(
            [{"too_large": "\U0001f680" * (reservation.SLOT_BYTES // 12 + 1)}]
        )
        with refuses(reservation.physical.PhysicalPause, "byte reservation exhausted"):
            pool.save(state, expected_preimage=first["state"])
        assert (pool.root / "work/paper/state.json").read_bytes() == prior
        assert (pool.root / "anchors/1").stat().st_size == reservation.SLOT_BYTES
        assert pool._control()["operation"] == 1

    # Refuse substituted working-name or lock inodes before writing through a wrong fd.
    def test_preopen_substitution_and_symlink_refuse(self):
        for kind in ("work", "lock", "symlink"):
            with self.subTest(kind=kind):
                pool = self.pool(name=f"pool-{kind}", slots=1)
                target = pool.root / (
                    "lock" if kind == "lock" else "work/paper/.reserved-0.tmp"
                )
                if kind == "symlink":
                    target.unlink()
                    target.symlink_to(pool.root / "anchors/0")
                    with refuses(reservation.physical.PhysicalPause):
                        pool.save(SyntheticPaper([]), expected_preimage=None)
                    continue
                replacement = pool.root / "SYNTHETIC-replacement"
                reservation.physical._allocate(replacement, target.stat().st_size)
                saved = pool.root / "SYNTHETIC-original"
                original_open = os.open
                replaced = False

                # Replace a real path only after its original lstat sample was taken.
                def swapped(
                    path,
                    *args,
                    target=target,
                    replacement=replacement,
                    saved=saved,
                    original_open=original_open,
                    **kwargs,
                ):
                    nonlocal replaced
                    if Path(path) == target and not replaced:
                        os.replace(target, saved)
                        os.replace(replacement, target)
                        replaced = True
                    return original_open(path, *args, **kwargs)

                with (
                    patch.object(os, "open", side_effect=swapped),
                    refuses(reservation.physical.PhysicalPause),
                ):
                    pool.save(SyntheticPaper([]), expected_preimage=None)
                assert replaced
                assert saved.stat().st_ino != target.stat().st_ino

    # Retain named failure boundaries without forging fsync observations.
    def test_named_failures_never_adopt_readable_orphan_bytes(self):
        points = (
            "armed",
            "factory_ready",
            "before_raw_write",
            "native_flush_returned",
            "native_fileno",
            "native_block_returned",
            "writer_closed",
            "truncated",
            "truncated_fsynced",
            "before_native_replace",
            "native_returned",
            "state_verified",
            "receipt_written",
        )
        for index, point in enumerate(points):
            with self.subTest(point=point):
                pool = self.pool(name=f"cut-{index}", slots=1)

                # Raise only at a named adapter boundary in this synthetic invocation.
                def failure(name, point=point):
                    if name == point:
                        raise OSError(f"SYNTHETIC cut:{point}")

                pool._point = failure
                with refuses(OSError, "SYNTHETIC cut"):
                    pool.save(
                        SyntheticPaper([{"nan": float("nan")}]), expected_preimage=None
                    )
                assert pool._control()["operation"] == 0
                assert (pool.root / "anchors/0").is_file()
                with refuses(reservation.physical.PhysicalPause, "OPEN"):
                    pool.completed()

    # Preserve actual killed process evidence before replace and after native return.
    def test_sigkill_cuts_leave_durable_open_slots(self):
        for index, point in enumerate(("before_native_replace", "native_returned")):
            pool = self.pool(name=f"kill-{index}", slots=1)
            process = multiprocessing.get_context("fork").Process(
                target=killed_save, args=(pool.root, self.pin, self.source, point)
            )
            process.start()
            process.join(15)
            if process.is_alive():
                process.kill()
                process.join()
                self.fail("SYNTHETIC child did not reach named writer cut")
            assert process.exitcode == -signal.SIGKILL
            assert pool._control()["operation"] == 0
            assert (pool.root / "anchors/0").stat().st_size < reservation.SLOT_BYTES
            with refuses(reservation.physical.PhysicalPause, "OPEN"):
                pool.completed()
            with refuses(reservation.physical.PhysicalPause, "OPEN"):
                pool.save(SyntheticPaper([]), expected_preimage=None)

    # Reject unsupported physical allocation and header arithmetic/claim corruption.
    def test_allocation_and_header_integrity_refuse(self):
        with (
            patch.object(
                os, "posix_fallocate", side_effect=OSError("SYNTHETIC ENOSPC")
            ),
            refuses(reservation.physical.PhysicalPause, "allocation"),
        ):
            self.pool(name="no-space", slots=1)
        pool = self.pool(slots=1)
        header = deepcopy(pool.header)
        for change in (
            {"dual_host_reserved": True},
            {"reserved_file_inodes": header["reserved_file_inodes"] + 1},
            {"unknown": True},
        ):
            reservation.physical._fixed_write(
                pool.root / "header", {**header, **change}
            )
            with refuses(reservation.physical.PhysicalPause):
                reservation.ReservedWriter(
                    pool.root,
                    writer=pool.writer,
                    writer_source=self.source,
                    identity_sha256=self.pin,
                )

    # Refuse sparse fake reservation extents before touching any native output bytes.
    def test_sparse_anchor_refuses_before_native_write(self):
        pool = self.pool(slots=1)
        anchor = pool.root / "anchors/0"
        with anchor.open("r+b") as handle:
            handle.truncate(0)
            handle.truncate(reservation.SLOT_BYTES)
        assert anchor.stat().st_blocks * 512 < reservation.SLOT_BYTES
        with refuses(reservation.physical.PhysicalPause, "physically allocated"):
            pool.save(SyntheticPaper([]), expected_preimage=None)
        assert not (pool.root / "work/paper/state.json").exists()
        assert pool._control()["operation"] == 0

    # Reject receipt claim/schema drift even when its local control checksum is updated.
    def test_completion_schema_refuses_unsupported_claim(self):
        pool = self.pool(slots=1)
        receipt = pool.save(SyntheticPaper([]), expected_preimage=None)
        receipt["dual_host_reserved"] = True
        reservation.physical._fixed_write(pool.root / "receipts/0", receipt)
        control = pool._control()
        control["last"]["receipt_sha256"] = reservation.physical._sha(
            reservation.physical._encoded(receipt)
        )
        reservation.physical._fixed_write(pool.root / "control", control)
        with refuses(reservation.physical.PhysicalPause, "Unsupported local receipt"):
            pool.completed()

    # Compare the genuinely imported native writer with the NEW callable at GO.
    def test_actual_native_writer_byte_parity(self):
        from backend.agents.trading.desk import paper

        assert (
            reservation.physical._sha(Path(paper.__file__).read_bytes())
            == reservation.physical.PAPER
        )
        pool = self.pool(name="actual-native", writer=paper.save_state, slots=1)
        state = paper.PaperState()
        state.history = [
            {
                "session": "SYNTHETIC",
                "value": float("nan"),
                "text": "\n\r\u00e9\U0001f680\ud800",
            }
        ]
        control = self.root / "actual-native-control"
        paper.save_state(control, state)
        expected = paper.state_path(control).read_bytes()
        receipt = pool.save(state, expected_preimage=None)
        assert (pool.root / "work/paper/state.json").read_bytes() == expected
        assert receipt["writer_sha256"] == reservation.physical.PAPER
        assert receipt["native_operation_adopted"] is False
