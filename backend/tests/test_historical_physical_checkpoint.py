"""Synthetic raw bytes only; no account, native model or provider invocation.

The reviewed runner must supply /fixture/current-identity.json from the public
CURRENT source declaration and the exact readable f612 writer source. These
tests do not manufacture a fake31 map or call native paper.load/save functions.
Two-host reservation and native full lifecycle memory remain outside this proof.
"""

import errno
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
from unittest.mock import patch

from backend.market import historical_physical_checkpoint as physical


# Assert exact refusal types/messages using only stdlib in the isolated fixture.
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


# Produce small indent2 native-writer-shaped bytes with explicitly synthetic fields.
def synthetic(rows):
    return json.dumps(
        {
            "synthetic_fixture": True,
            "cash": 1000.0,
            "history": rows,
            "pending": [],
            "journal": [],
        },
        indent=2,
    ).encode()


# Kill only the fixture child immediately after one real CAS hardlink publication.
def killed_capture(root, identity_sha256, writer, source):
    store = physical.PhysicalCheckpoint(
        root, identity_sha256=identity_sha256, writer=writer
    )
    original = os.link

    # Preserve a real published inode before simulating a process crash.
    def publish_then_die(*args, **kwargs):
        original(*args, **kwargs)
        os.kill(os.getpid(), signal.SIGKILL)

    with patch.object(physical.os, "link", side_effect=publish_then_die):
        store.capture(source)


# Exercise the unused primitive against bounded fake paper bytes and local files only.
class PhysicalCheckpointTests(unittest.TestCase):
    # Read only a bounded externally supplied public CURRENT identity declaration.
    @classmethod
    def setUpClass(cls):
        fixture = Path("/fixture/current-identity.json")
        if not fixture.is_file() or fixture.stat().st_size > 32768:
            raise AssertionError("Reviewed CURRENT public source fixture required")
        cls.identity = json.loads(fixture.read_bytes())
        cls.pin = physical._sha(physical._encoded(cls.identity))
        cls.writer = Path("/fixture/current-writer.py")

    # Retain every synthetic mutation in a unique private output directory for review.
    def setUp(self):
        retained = Path("/out/cases")
        retained.mkdir(mode=0o700, exist_ok=True)
        self.directory = Path(
            tempfile.mkdtemp(
                prefix=f"SYNTHETIC-{self._testMethodName}-",
                dir=retained,
            )
        )
        self.limits = {
            "span_bytes": 4096,
            "raw_bytes": 1024 * 1024,
            "history_rows": 1024,
            "body_slots": 512,
            "page_slots": 48,
            "directory_headroom_bytes": 65536,
        }

    # Allocate finite actual local file extents without touching Store or acquisition.
    def reserve(self, name="rope", **changes):
        limits = {**self.limits, **changes}
        return physical.reserve(
            self.directory / name,
            identity=self.identity,
            identity_sha256=self.pin,
            writer=self.writer,
            limits=limits,
        )

    # Write a fake source file independently of the checkpoint reservation.
    def source(self, raw, name="synthetic-paper.json"):
        path = self.directory / name
        path.write_bytes(raw)
        return path

    # Snapshot CAS hashes and inodes without loading physical body contents.
    def objects(self, store, kind):
        directory = store.root / kind
        return {path.name: path.stat().st_ino for path in directory.iterdir()}

    # Retain every raw NaN and escaped newline through a fresh same-inode restore.
    def test_roundtrip_opaque_nan_and_escaped_newlines(self):
        raw = synthetic(
            [{"session": "SYNTHETIC", "value": float("nan"), "text": 'a\nb\\c"d'}]
        )
        source = self.source(raw)
        before = (physical._fingerprint(source.stat()), hashlib.sha256(raw).hexdigest())
        store = self.reserve()
        reference = store.capture(source)
        root = store.verify(reference)
        assert root["scope"] == "OPAQUE_NATIVE_BYTES_NOT_JSON_ADMISSION"
        assert root["raw_sha256"] == before[1]
        assert root["raw_bytes"] == len(raw)
        assert root["history_rows"] == 1
        completion = store.completed(reference)
        assert completion["local_capture_committed"] is True
        assert completion["native_operation_committed"] is False
        assert completion["durable_simulator_adoption"] is False
        restored = self.directory / "fresh-restored.json"
        result = store.restore(reference, restored)
        assert result == root
        assert restored.read_bytes() == raw
        assert b"NaN" in restored.read_bytes()
        assert restored.stat().st_ino == (store.root / "restore").stat().st_ino
        assert source.read_bytes() == raw
        assert physical._fingerprint(source.stat()) == before[0]
        assert store.header["dual_host_reserved"] is False
        assert store.header["native_work_reserved"] is False
        assert store.header["directory_headroom_reserved"] is False

    # Preserve the exact empty history line without inventing an initial row.
    def test_empty_history_and_modes(self):
        raw = synthetic([])
        store = self.reserve()
        reference = store.capture(self.source(raw))
        assert store.verify(reference)["history_rows"] == 0
        restored = self.directory / "empty-restored.json"
        store.restore(reference, restored)
        assert restored.read_bytes() == raw
        assert store.root.stat().st_mode & 0o777 == 0o700
        for path in store.root.rglob("*"):
            assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)

    # Preserve native one-line empty object rows without interpreting their validity.
    def test_empty_object_rows_preserve_physical_native_framing(self):
        raw = synthetic([{}, {"x": 1}, {}])
        store = self.reserve(body_slots=8, page_slots=8)
        reference = store.capture(self.source(raw))
        assert store.verify(reference)["history_rows"] == 3
        restored = self.directory / "empty-rows-restored.json"
        store.restore(reference, restored)
        assert restored.read_bytes() == raw

    # Share prior rows and manifest subtrees while appending or replacing the last row.
    def test_append_and_replacement_have_bounded_new_pages_and_reuse_inodes(self):
        rows = [
            {"session": f"SYNTHETIC-{index:04}", "value": index} for index in range(130)
        ]
        store = self.reserve()
        source = self.source(synthetic(rows))
        first = store.capture(source)
        first_bodies, first_pages = (
            self.objects(store, "bodies"),
            self.objects(store, "pages"),
        )
        source.write_bytes(
            synthetic(rows + [{"session": "SYNTHETIC-0130", "value": 130}])
        )
        second = store.capture(source)
        second_bodies, second_pages = (
            self.objects(store, "bodies"),
            self.objects(store, "pages"),
        )
        assert len(set(second_bodies) - set(first_bodies)) == 2
        assert len(set(second_pages) - set(first_pages)) <= 4
        assert all(second_bodies[key] == inode for key, inode in first_bodies.items())
        assert all(second_pages[key] == inode for key, inode in first_pages.items())
        assert set(first_pages) & set(second_pages)
        rows.append({"session": "SYNTHETIC-0130", "value": 999})
        source.write_bytes(synthetic(rows))
        third = store.capture(source)
        third_pages = self.objects(store, "pages")
        assert len(set(third_pages) - set(second_pages)) <= 4
        assert store.verify(first)["history_rows"] == 130
        assert store.verify(second)["history_rows"] == 131
        assert (
            store.verify(third)["raw_sha256"]
            == hashlib.sha256(source.read_bytes()).hexdigest()
        )
        slot_inodes = {
            path.stat().st_ino for path in (store.root / "body-slots").iterdir()
        }
        for digest, inode in self.objects(store, "bodies").items():
            assert inode in slot_inodes
            assert (store.root / "bodies" / digest).stat().st_nlink == 2

    # Bound reads even when one native escaped string crosses a64KiB read boundary.
    def test_fragmented_long_line_remains_byte_identical(self):
        raw = synthetic([{"value": "x" * (physical.READ + 19) + "\n"}])
        store = self.reserve(span_bytes=2 * physical.READ, body_slots=8, page_slots=8)
        source = self.source(raw)
        reference = store.capture(source)
        restored = self.directory / "long-restored.json"
        store.restore(reference, restored)
        assert restored.read_bytes() == raw

    # Reject missing, duplicate, incomplete and wrong-indentation native row framing.
    def test_malformed_framing_refuses_without_claiming_json_validation(self):
        cases = [
            b"{}",
            synthetic([]).replace(b'  "history": [],\n', b""),
            synthetic([]).replace(b'  "pending": [],\n', b'  "history": [],\n'),
            synthetic([{"x": 1}]).replace(b"    {\n", b"   {\n"),
            synthetic([{"x": 1}]).replace(b"    }\n", b"    },\n"),
            synthetic([{"x": 1}])[:-1],
        ]
        for index, raw in enumerate(cases):
            with self.subTest(index=index):
                store = self.reserve(
                    name=f"malformed-{index}", body_slots=8, page_slots=8
                )
                with refuses(physical.PhysicalPause):
                    store.capture(self.source(raw, name=f"malformed-{index}.json"))
                assert (
                    physical._fixed_read(store.root / "control")["operation"]
                    == "CAPTURE"
                )

    # Keep finite span, row, raw and reserved-object exhaustion as explicit pauses.
    def test_limits_refuse_and_keep_open_evidence(self):
        cases = [
            ({"span_bytes": 80}, synthetic([{"x": "z" * 100}])),
            ({"history_rows": 1}, synthetic([{"x": 1}, {"x": 2}])),
            ({"body_slots": 1}, synthetic([{"x": 1}])),
            ({"page_slots": 1}, synthetic([{"x": 1}])),
        ]
        for index, (changes, raw) in enumerate(cases):
            with self.subTest(index=index):
                store = self.reserve(name=f"limit-{index}", **changes)
                with refuses(physical.PhysicalPause):
                    store.capture(self.source(raw, name=f"limit-{index}.json"))
                assert (
                    physical._fixed_read(store.root / "control")["operation"]
                    == "CAPTURE"
                )
        store = self.reserve(name="raw-cap", raw_bytes=32, body_slots=4, page_slots=4)
        with refuses(physical.PhysicalPause, "byte cap"):
            store.capture(self.source(synthetic([]), name="too-large.json"))
        assert physical._fixed_read(store.root / "control")["operation"] is None

    # Refuse unsupported physical allocation and real ENOSPC without a sparse fallback.
    def test_allocation_failure_is_retained_before_capture(self):
        for index, error in enumerate((errno.ENOSPC, errno.EOPNOTSUPP)):
            with self.subTest(error=error):
                with (
                    patch.object(
                        physical.os,
                        "posix_fallocate",
                        side_effect=OSError(error, "SYNTHETIC"),
                    ),
                    refuses(physical.PhysicalPause, "allocation"),
                ):
                    self.reserve(name=f"allocation-failure-{index}")
                assert (self.directory / f"allocation-failure-{index}").is_dir()
                assert (
                    list(
                        (
                            self.directory / f"allocation-failure-{index}" / "bodies"
                        ).iterdir()
                    )
                    == []
                )

    # Reject mixed profile declarations before allocating a checkpoint namespace.
    def test_exact_current_identity_and_actual_writer_required(self):
        identity = deepcopy(self.identity)
        identity["source_revision"] = "ad44d536a70d5c037cb931836a3c9f48b014d84a"
        with refuses(physical.PhysicalPause, "CURRENT profile"):
            physical.reserve(
                self.directory / "mixed",
                identity=identity,
                identity_sha256=physical._sha(physical._encoded(identity)),
                writer=self.writer,
                limits=self.limits,
            )
        assert not (self.directory / "mixed").exists()
        wrong = self.source(b"SYNTHETIC not native source", name="wrong-writer.py")
        with refuses(physical.PhysicalPause, "writer bytes"):
            physical.reserve(
                self.directory / "wrong",
                identity=self.identity,
                identity_sha256=self.pin,
                writer=wrong,
                limits=self.limits,
            )
        assert not (self.directory / "wrong").exists()
        replaced = deepcopy(self.identity)
        name = next(iter(replaced["source_sha256"]))
        replaced["source_sha256"]["backend/market/SYNTHETIC-unreviewed.py"] = replaced[
            "source_sha256"
        ].pop(name)
        assert len(replaced["source_sha256"]) == 31
        with refuses(physical.PhysicalPause, "CURRENT31"):
            physical.reserve(
                self.directory / "replaced",
                identity=replaced,
                identity_sha256=physical._sha(physical._encoded(replaced)),
                writer=self.writer,
                limits=self.limits,
            )
        assert not (self.directory / "replaced").exists()

    # Refuse overflow, duplicate keys and constants only in finite checkpoint metadata.
    def test_nonfinite_and_duplicate_metadata_refuse(self):
        for raw in (
            b'{"x":1e9999}',
            b'{"x":-1e9999}',
            b'{"x":NaN}',
            b'{"x":Infinity}',
            b'{"x":1,"x":2}',
        ):
            with self.subTest(raw=raw), refuses(physical.PhysicalPause):
                physical._decoded(raw)
        assert physical._decoded(b'{"x":1.25}') == {"x": 1.25}

    # Refuse altered local-only claims, unknown fields and false reservation arithmetic.
    def test_header_reopen_rejects_claims_schema_and_arithmetic(self):
        store = self.reserve(body_slots=8, page_slots=8)
        original = deepcopy(store.header)
        changes = [
            {"dual_host_reserved": True},
            {"native_work_reserved": True},
            {"directory_headroom_reserved": 0},
            {"scope": "NATIVE_OPERATION_ADMITTED"},
            {"reserved_file_bytes": original["reserved_file_bytes"] + 1},
            {"reserved_file_inodes": original["reserved_file_inodes"] + 1},
            {"unknown": True},
        ]
        for change in changes:
            with self.subTest(change=change):
                physical._fixed_write(store.root / "header", {**original, **change})
                with refuses(physical.PhysicalPause):
                    physical.PhysicalCheckpoint(
                        store.root, identity_sha256=self.pin, writer=self.writer
                    )
        physical._fixed_write(store.root / "header", original)
        reopened = physical.PhysicalCheckpoint(
            store.root, identity_sha256=self.pin, writer=self.writer
        )
        assert reopened.header == original

    # Detect replaced control paths both before opening and after a real fd read/write.
    def test_control_fd_and_path_identity_bookends(self):
        for action in ("read", "write"):
            for phase in ("before_open", "after_io"):
                with self.subTest(action=action, phase=phase):
                    store = self.reserve(
                        name=f"control-{action}-{phase}", body_slots=8, page_slots=8
                    )
                    control = store.root / "control"
                    original_state = physical._fixed_read(control)
                    replacement = store.root / "SYNTHETIC-replacement-control"
                    physical._allocate(replacement, physical.META)
                    physical._fixed_write(replacement, original_state)
                    saved = store.root / "SYNTHETIC-original-control"
                    changed = False
                    original_open, original_read, original_write = (
                        os.open,
                        os.read,
                        os.pwrite,
                    )

                    # Retain the original inode while replacing its pathname once.
                    def replace_path(
                        control=control, saved=saved, replacement=replacement
                    ):
                        nonlocal changed
                        if not changed:
                            os.replace(control, saved)
                            os.replace(replacement, control)
                            changed = True

                    # Substitute a real allocated inode after the pre-open lstat sample.
                    def open_replaced(
                        path,
                        *args,
                        control=control,
                        original_open=original_open,
                        replace=replace_path,
                        **kwargs,
                    ):
                        if Path(path) == control:
                            replace()
                        return original_open(path, *args, **kwargs)

                    # Substitute the path while the original read fd stays open.
                    def read_replaced(
                        *args,
                        original_read=original_read,
                        replace=replace_path,
                        **kwargs,
                    ):
                        result = original_read(*args, **kwargs)
                        replace()
                        return result

                    # Retain a real write before substituting its visible pathname.
                    def write_replaced(
                        *args,
                        original_write=original_write,
                        replace=replace_path,
                        **kwargs,
                    ):
                        result = original_write(*args, **kwargs)
                        replace()
                        return result

                    operation = (
                        "open"
                        if phase == "before_open"
                        else ("read" if action == "read" else "pwrite")
                    )
                    replacement_call = (
                        open_replaced
                        if phase == "before_open"
                        else (read_replaced if action == "read" else write_replaced)
                    )
                    with (
                        patch.object(
                            physical.os, operation, side_effect=replacement_call
                        ),
                        refuses(physical.PhysicalPause, "Control.*(replaced|changed)"),
                    ):
                        if action == "read":
                            physical._fixed_read(control)
                        else:
                            physical._fixed_write(control, original_state)
                    assert changed
                    assert saved.stat().st_ino != control.stat().st_ino

    # Refuse pre-open slot/lock replacement before writing or accepting the wrong inode.
    def test_slot_and_lock_preopen_identity_refuse(self):
        for action in ("put", "restore", "capture_lock", "completed_lock"):
            with self.subTest(action=action):
                store = self.reserve(
                    name=f"preopen-{action}", body_slots=8, page_slots=8
                )
                source = self.source(
                    synthetic([{"x": 1}]), name=f"preopen-{action}.json"
                )
                reference = (
                    store.capture(source)
                    if action in {"restore", "completed_lock"}
                    else None
                )
                if action == "put":
                    target = store.root / "body-slots" / "0"
                elif action == "restore":
                    target = store.root / "restore"
                else:
                    target = store.root / "lock"
                replacement = store.root / "SYNTHETIC-replacement-inode"
                physical._allocate(replacement, target.stat().st_size)
                with replacement.open("r+b") as handle:
                    handle.write(b"SYNTHETIC KEEP")
                before = hashlib.sha256(replacement.read_bytes()).hexdigest()
                saved = store.root / "SYNTHETIC-original-inode"
                changed = False
                original_open = os.open

                # Replace only the requested path after its original lstat was sampled.
                def replace_before_open(
                    path,
                    *args,
                    target=target,
                    saved=saved,
                    replacement=replacement,
                    original_open=original_open,
                    **kwargs,
                ):
                    nonlocal changed
                    if Path(path) == target and not changed:
                        os.replace(target, saved)
                        os.replace(replacement, target)
                        changed = True
                    return original_open(path, *args, **kwargs)

                with (
                    patch.object(physical.os, "open", side_effect=replace_before_open),
                    refuses(physical.PhysicalPause, "descriptor/path identity"),
                ):
                    if action == "restore":
                        store.restore(
                            reference, self.directory / "must-not-publish.json"
                        )
                    elif action == "completed_lock":
                        store.completed(reference)
                    else:
                        store.capture(source)
                assert changed
                assert hashlib.sha256(target.read_bytes()).hexdigest() == before
                assert saved.stat().st_ino != target.stat().st_ino
                operation = physical._fixed_read(store.root / "control")["operation"]
                assert operation == (
                    {"put": "CAPTURE", "restore": "RESTORE"}.get(action)
                )

    # Reject a missing body or changed body hash instead of silently skipping a span.
    def test_missing_and_corrupt_body_refuse(self):
        for index, corrupt in enumerate((False, True)):
            store = self.reserve(
                name=f"corrupt-body-{index}", body_slots=8, page_slots=8
            )
            reference = store.capture(
                self.source(synthetic([{"x": 1}]), name=f"body-{index}.json")
            )
            path = next((store.root / "bodies").iterdir())
            if corrupt:
                with path.open("r+b") as handle:
                    handle.write(b"!")
            else:
                path.unlink()
            with refuses((physical.PhysicalPause, FileNotFoundError)):
                store.verify(reference)

    # Reject changed pages, wrong root lengths and reordered valid content references.
    def test_manifest_corruption_reorder_and_reference_lengths_refuse(self):
        store = self.reserve()
        reference = store.capture(self.source(synthetic([{"x": 1}, {"x": 2}])))
        root = store.verify(reference)
        value = physical._decoded(
            b"".join(store._content("page", root["tree"]["page"]))
        )
        value["refs"][1:3] = reversed(value["refs"][1:3])
        with store._locked("CAPTURE"):
            changed = deepcopy(root)
            changed["tree"] = {"page": store._put("page", physical._encoded(value))}
            reordered = store._put("page", physical._encoded(changed))
        with refuses(physical.PhysicalPause, "checkpoint differs"):
            store.verify(reordered)
        wrong = {**reference, "length": reference["length"] - 1}
        with refuses(physical.PhysicalPause):
            store.verify(wrong)
        path = store.root / "pages" / reference["sha256"]
        with path.open("r+b") as handle:
            handle.write(b"!")
        with refuses(physical.PhysicalPause):
            store.verify(reference)

    # Reject a missing child manifest and a torn mutable control checksum explicitly.
    def test_missing_manifest_and_torn_control_refuse(self):
        store = self.reserve(body_slots=8, page_slots=8)
        reference = store.capture(self.source(synthetic([])))
        root = store.verify(reference)
        (store.root / "pages" / root["tree"]["page"]["sha256"]).unlink()
        with refuses(FileNotFoundError):
            store.verify(reference)
        with (store.root / "control").open("r+b") as handle:
            handle.seek(40)
            handle.write(b"!")
        with refuses(physical.PhysicalPause, "Torn"):
            store.capture(self.directory / "synthetic-paper.json")

    # Reject source, CAS and restore symlinks and never overwrite an existing target.
    def test_symlinks_and_exclusive_restore(self):
        source = self.source(synthetic([]))
        linked = self.directory / "source-link"
        linked.symlink_to(source)
        store = self.reserve()
        with refuses(physical.PhysicalPause, "symlink"):
            store.capture(linked)
        reference = store.capture(source)
        existing = self.source(b"SYNTHETIC KEEP", name="existing")
        with refuses(physical.PhysicalPause, "fresh restore"):
            store.restore(reference, existing)
        assert existing.read_bytes() == b"SYNTHETIC KEEP"
        linked_target = self.directory / "target-link"
        linked_target.symlink_to(existing)
        with refuses(physical.PhysicalPause, "symlink"):
            store.restore(reference, linked_target)
        body = next((store.root / "bodies").iterdir())
        body.unlink()
        body.symlink_to(source)
        with refuses(physical.PhysicalPause, "nonsymlink"):
            store.verify(reference)

    # Preserve an OPEN marker and published same-inode body after a real child SIGKILL.
    def test_sigkill_after_cas_publication_refuses_capture_resume(self):
        store = self.reserve(body_slots=8, page_slots=8)
        source = self.source(synthetic([{"x": 1}]))
        context = multiprocessing.get_context("fork")
        process = context.Process(
            target=killed_capture, args=(store.root, self.pin, self.writer, source)
        )
        process.start()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()
            self.fail("SYNTHETIC child failed to reach publication boundary")
        assert process.exitcode == -signal.SIGKILL
        assert physical._fixed_read(store.root / "control")["operation"] == "CAPTURE"
        bodies = self.objects(store, "bodies")
        assert len(bodies) == 1
        assert (
            next(iter(bodies.values()))
            == (store.root / "body-slots" / "0").stat().st_ino
        )
        reopened = physical.PhysicalCheckpoint(
            store.root, identity_sha256=self.pin, writer=self.writer
        )
        with refuses(physical.PhysicalPause, "remains OPEN"):
            reopened.capture(source)

    # Retain prepublication failure evidence and refuse a sparse replacement slot.
    def test_prepublication_failure_and_sparse_reservation_refuse(self):
        store = self.reserve(body_slots=8, page_slots=8)
        source = self.source(synthetic([]))
        with (
            patch.object(
                physical.os,
                "link",
                side_effect=OSError(errno.EIO, "SYNTHETIC before publication"),
            ),
            refuses(OSError),
        ):
            store.capture(source)
        assert self.objects(store, "bodies") == {}
        assert physical._fixed_read(store.root / "control")["operation"] == "CAPTURE"
        other = self.reserve(name="sparse", body_slots=8, page_slots=8)
        slot = other.root / "body-slots" / "0"
        slot.unlink()
        with slot.open("wb") as handle:
            handle.truncate(other.limits["span_bytes"])
        slot.chmod(0o600)
        assert slot.stat().st_blocks * 512 < slot.stat().st_size
        with refuses(physical.PhysicalPause, "physically allocated"):
            other.capture(source)

    # Refuse successful-operation adoption even when an orphan root verifies fully.
    def test_verified_orphan_is_not_a_completed_operation(self):
        store = self.reserve(body_slots=8, page_slots=8)
        source = self.source(synthetic([{"x": 1}]))
        first = store.capture(source)
        assert store.completed(first)["local_capture_committed"] is True
        source.write_bytes(synthetic([{"x": 2}]))
        original = physical._fixed_write

        # Leave the durable CAPTURE marker intact when the final control update fails.
        def refuse_completion(path, value):
            if path.name == "control" and value["operation"] is None:
                raise OSError(errno.EIO, "SYNTHETIC final control failure")
            return original(path, value)

        with (
            patch.object(physical, "_fixed_write", side_effect=refuse_completion),
            refuses(OSError),
        ):
            store.capture(source)
        orphan = store.control["completed_capture"]
        assert orphan != first
        assert (
            store.verify(orphan)["raw_sha256"]
            == hashlib.sha256(source.read_bytes()).hexdigest()
        )
        assert store.verify(first)["history_rows"] == 1
        for reference in (first, orphan):
            with refuses(physical.PhysicalPause, "cannot be adopted"):
                store.completed(reference)
        assert physical._fixed_read(store.root / "control")["operation"] == "CAPTURE"

    # Retain failed restore publication without consuming another extent silently.
    def test_interrupted_restore_keeps_original_root_and_open_marker(self):
        raw = synthetic([{"x": float("nan")}])
        store = self.reserve(body_slots=8, page_slots=8)
        reference = store.capture(self.source(raw))
        target = self.directory / "interrupted-restored.json"
        original = os.link

        # Preserve the actual target inode before simulating a failed directory commit.
        def publish_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError(errno.EIO, "SYNTHETIC publication interruption")

        with (
            patch.object(physical.os, "link", side_effect=publish_then_fail),
            refuses(OSError),
        ):
            store.restore(reference, target)
        assert target.read_bytes() == raw
        assert physical._fixed_read(store.root / "control")["operation"] == "RESTORE"
        assert store.verify(reference)["raw_sha256"] == hashlib.sha256(raw).hexdigest()
        with refuses(physical.PhysicalPause, "remains OPEN"):
            store.restore(reference, self.directory / "second.json")
