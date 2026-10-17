"""Deferred synthetic local-peer tests; not two-host or native admission.

All files/effects are artificial retained fixtures. No native module, model,
provider, genuine state, network transport or repository conftest is imported.
Run only after separate source and isolated invocation approval.
"""

import hashlib
import json
import multiprocessing
import os
import signal
import tempfile
import unittest
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from backend.market import historical_fixed_slot_checkpoint as fixed


# Require an explicit bounded refusal without importing pytest or application fixtures.
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
        assert match in str(caught)


# Increment a preexisting fake effect counter without creating any new namespace entry.
def fake_effect(source, counter):
    descriptor = os.open(counter, os.O_RDWR | os.O_NOFOLLOW)
    try:
        value = int(os.read(descriptor, 1))
        assert value == 0
        assert os.pwrite(descriptor, b"1", 0) == 1
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return source


# Kill only the synthetic child after the named real local durability boundary.
def killed(pair, source, counter, point):
    # Observe real local work before simulating a crash, never a remote acknowledgment.
    def cut(name):
        if name == point:
            os.kill(os.getpid(), signal.SIGKILL)

    # Supply no decision, model or native writer behavior to the local fixture callback.
    def effect():
        return fake_effect(source, counter)

    pair.transport.point = cut
    pair.run(effect, expected_prior=pair.common["genesis"])


# Validate fixed files and crash semantics without treating local peers as two hosts.
class FixedSlotCheckpointTests(unittest.TestCase):
    # Read only the public CURRENT identity and reviewed writer bytes as inert fixtures.
    @classmethod
    def setUpClass(cls):
        cls.writer = Path("/fixture/current-writer.py")
        path = Path("/fixture/current-identity.json")
        assert path.stat().st_size < 32768
        cls.identity = json.loads(path.read_bytes())
        cls.pin = fixed.raw._sha(fixed.raw._encoded(cls.identity))
        cls.genesis = hashlib.sha256(b"SYNTHETIC_EMPTY_HEAD").hexdigest()

    # Keep every successful, failed and killed fixture under the retained output root.
    def setUp(self):
        retained = Path("/out/cases")
        retained.mkdir(mode=0o700, exist_ok=True)
        self.root = Path(
            tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=retained)
        )

    # Declare small finite budgets sufficient for every possible admitted fixture row.
    def limits(self, **changes):
        return {
            "body_slots": 24,
            "page_slots": 12,
            "span_bytes": 4096,
            "raw_bytes": 65536,
            "history_rows": 4,
            "operations": 3,
            **changes,
        }

    # Create two actual preallocated local roots without any network/host assertion.
    def pair(self, name="pair", **changes):
        root = self.root / name
        root.mkdir(mode=0o700)
        peers = [
            fixed.reserve(
                root / peer,
                peer=peer,
                peers=["a", "b"],
                owner="a",
                genesis=self.genesis,
                identity=self.identity,
                identity_sha256=self.pin,
                writer_source=self.writer,
                limits=self.limits(**changes),
            )
            for peer in ("a", "b")
        ]
        return fixed.Pair(fixed.FixtureTransport(peers))

    # Write fake native-shaped raw bytes before ARM, including opaque physical NaNs.
    def source(self, name="source", rows=None):
        rows = (
            [{"x": float("nan"), "note": "SYNTHETIC\n\u00e9\U0001f680"}]
            if rows is None
            else rows
        )
        path = self.root / name
        path.write_bytes(
            json.dumps(
                {"before": "SYNTHETIC", "history": rows, "after": 1}, indent=2
            ).encode()
        )
        path.chmod(0o600)
        return path

    # Create fake effect counters outside the checkpoint namespace before ARM.
    def counter(self, name="effect-counter"):
        path = self.root / name
        path.write_bytes(b"0")
        path.chmod(0o600)
        return path

    # Return an artificial source and count exactly one synthetic callback.
    def run_pair(self, pair, source, prior=None, counter=None):
        counter = self.counter() if counter is None else counter

        # Record only a synthetic callback, never a paper/model decision.
        def effect():
            return fake_effect(source, counter)

        receipt = pair.run(
            effect, expected_prior=self.genesis if prior is None else prior
        )
        assert counter.read_bytes() == b"1"
        return receipt

    # Verify opaque bytes and local source/ACK claims without native adoption.
    def test_complete_pair_preserves_opaque_bytes_and_actual_inodes(self):
        pair, source = self.pair(), self.source()
        inventory = [
            {
                name: (peer.root / name).stat().st_ino
                for name, _ in fixed._files(peer.limits, peer.common["amounts"])
            }
            for peer in pair.peers
        ]
        receipt = self.run_pair(pair, source)
        result = pair.completed(receipt)
        assert (
            result["root"]["raw_sha256"]
            == hashlib.sha256(source.read_bytes()).hexdigest()
        )
        for key in fixed.FALSE_CLAIMS:
            assert result[key] is False
        for peer, before in zip(pair.peers, inventory, strict=True):
            assert before == {name: (peer.root / name).stat().st_ino for name in before}
            rebuilt = b"".join(
                chunk
                for item in peer._walk(result["root"]["tree"])
                for chunk in peer._content(item["content"])
            )
            assert rebuilt == source.read_bytes()
            assert b"NaN" in rebuilt

    # Refuse checkpoint namespace allocation after a durable ARM acknowledgment.
    def test_no_post_arm_namespace_allocation(self):
        pair, source, counter = self.pair(), self.source(), self.counter()
        original_open, armed = os.open, False

        # Mark the real acknowledged ARM after reservation preparation.
        def observed(name):
            nonlocal armed
            if name == "after:_arm:a":
                armed = True

        # Permit only opens of existing paths after the charged boundary.
        def existing(path, flags, *args, **kwargs):
            assert not armed or flags & os.O_CREAT == 0
            return original_open(path, flags, *args, **kwargs)

        # Refuse every namespace mutation during this guarded fixture invocation.
        def forbidden(*args, **kwargs):
            raise AssertionError("SYNTHETIC namespace allocation after ARM")

        pair.transport.point = observed
        with (
            patch.object(os, "open", side_effect=existing),
            patch.object(os, "mkdir", side_effect=forbidden),
            patch.object(os, "link", side_effect=forbidden),
            patch.object(os, "rename", side_effect=forbidden),
            patch.object(os, "replace", side_effect=forbidden),
            patch.object(os, "unlink", side_effect=forbidden),
        ):
            receipt = self.run_pair(pair, source, counter=counter)
            assert pair.completed(receipt)["root"]["bytes"] == source.stat().st_size
        assert armed

    # Bound new right-edge pages and preserve unchanged row inodes on append.
    def test_append_last_row_and_identical_capture_reuse(self):
        pair = self.pair(
            body_slots=400,
            page_slots=16,
            history_rows=130,
            raw_bytes=262144,
            operations=4,
        )
        first = self.run_pair(
            pair, self.source("initial", [{"i": i} for i in range(128)])
        )
        initial = [peer._control() for peer in pair.peers]
        second = self.run_pair(
            pair,
            self.source("append", [{"i": i} for i in range(129)]),
            first["decision"],
            self.counter("counter2"),
        )
        appended = [peer._control() for peer in pair.peers]
        for old, new in zip(initial, appended, strict=True):
            assert 0 < new["body"] - old["body"] <= 2
            assert 0 < new["page"] - old["page"] <= 4
        changed = [{"i": i} for i in range(128)] + [{"i": "CHANGED"}]
        third = self.run_pair(
            pair,
            self.source("last", changed),
            second["decision"],
            self.counter("counter3"),
        )
        before = [peer._control() for peer in pair.peers]
        fourth = self.run_pair(
            pair, self.root / "last", third["decision"], self.counter("counter4")
        )
        for old, peer in zip(before, pair.peers, strict=True):
            assert peer._control()["body"] == old["body"]
            assert peer._control()["page"] == old["page"]
        assert fourth["root"] == third["root"]

    # Refuse known quota exhaustion and stale heads before an effect callback.
    def test_known_capacity_and_stale_heads_refuse_before_effect(self):
        pair, source = self.pair(body_slots=6), self.source()
        first = self.run_pair(pair, source)
        counter = self.counter("second-effect")
        with refuses(fixed.raw.PhysicalPause, "reservation exhausted"):
            self.run_pair(pair, source, first["decision"], counter)
        assert counter.read_bytes() == b"0"
        pair = self.pair("one-operation", operations=1)
        first = self.run_pair(pair, source, counter=self.counter("one-effect"))
        with refuses(fixed.raw.PhysicalPause):
            self.run_pair(pair, source, first["decision"], self.counter("never-effect"))
        with refuses(fixed.raw.PhysicalPause, "stale"):
            self.run_pair(pair, source, self.genesis, self.counter("stale-effect"))

    # Reserve the singleton top page produced by an eager exact-FANOUT carry.
    def test_exact_fanout_page_budget_refuses_before_callback(self):
        pair = self.pair(body_slots=128, page_slots=2, history_rows=126, operations=1)
        source, counter = self.source(), self.counter()
        with refuses(fixed.raw.PhysicalPause, "reservation exhausted"):
            self.run_pair(pair, source, counter=counter)
        assert counter.read_bytes() == b"0"
        assert all(peer._control()["open"] is None for peer in pair.peers)

    # Bind recovery to the requested operation instead of a copied older decision.
    def test_copied_decision_slot_cannot_change_requested_sequence(self):
        pair, source, counter = self.pair(), self.source(), self.counter()
        receipt = self.run_pair(pair, source, counter=counter)
        owner = pair.transport.peers[pair.common["owner"]]
        decision = owner._record(0, "DECISION")
        owner._record(1, "DECISION", decision)
        before = [peer._control() for peer in pair.peers]
        with refuses(fixed.raw.PhysicalPause, "Externally pinned"):
            pair.recover(
                sequence=1,
                expected_prior=self.genesis,
                owner_decision_sha256=receipt["decision"],
            )
        assert [peer._control() for peer in pair.peers] == before
        assert counter.read_bytes() == b"1"
        for invalid in (True, False, -1, 1.0):
            with refuses(fixed.raw.PhysicalPause):
                pair.recover(
                    sequence=invalid,
                    expected_prior=self.genesis,
                    owner_decision_sha256=receipt["decision"],
                )

    # Retain uncertainty when the second peer's ARM acknowledgment is unknown.
    def test_lost_arm_ack_never_runs_or_replays_effect(self):
        pair, source, counter = self.pair(), self.source(), self.counter()

        # Lose an acknowledgment after real metadata fsync/readback.
        def lost(name):
            if name == "after:_arm:b":
                raise OSError("SYNTHETIC unknown ARM ACK")

        pair.transport.point = lost
        with refuses(OSError, "unknown ARM ACK"):
            self.run_pair(pair, source, counter=counter)
        assert counter.read_bytes() == b"0"
        assert all(peer._control()["open"] == 0 for peer in pair.peers)
        with refuses(fixed.raw.PhysicalPause, "PAUSED"):
            self.run_pair(pair, source, counter=counter)
        with refuses(fixed.raw.PhysicalPause, "owner decision"):
            pair.recover(
                sequence=0, expected_prior=self.genesis, owner_decision_sha256="0" * 64
            )

    # Recover metadata under an external owner pin, never another effect.
    def test_owner_decision_recovery_is_idempotent_and_pin_bound(self):
        pair, source, counter = self.pair(), self.source(), self.counter()

        # Stop after an actual immutable owner decision, before peer commit transfer.
        def lost(name):
            if name == "owner:decision":
                raise OSError("SYNTHETIC owner decision ACK lost")

        pair.transport.point = lost
        with refuses(OSError):
            self.run_pair(pair, source, counter=counter)
        assert counter.read_bytes() == b"1"
        decision = pair.peers[0]._record(0, "DECISION")
        pin = fixed.raw._sha(fixed.raw._encoded(decision))
        with refuses(fixed.raw.PhysicalPause, "Externally pinned"):
            pair.recover(
                sequence=0, expected_prior=self.genesis, owner_decision_sha256="0" * 64
            )
        receipt = pair.recover(
            sequence=0, expected_prior=self.genesis, owner_decision_sha256=pin
        )
        assert (
            pair.recover(
                sequence=0, expected_prior=self.genesis, owner_decision_sha256=pin
            )
            == receipt
        )
        assert counter.read_bytes() == b"1"
        assert pair.completed(receipt)["real_two_host_proof"] is False

    # Preserve real SIGKILL windows both before the effect and after the owner decision.
    def test_sigkill_controls_never_elect_or_repeat_effect(self):
        for index, point in enumerate(("after:_arm:a", "owner:decision")):
            pair = self.pair(f"kill{index}")
            source, counter = (
                self.source(f"source{index}"),
                self.counter(f"counter{index}"),
            )
            child = multiprocessing.get_context("fork").Process(
                target=killed, args=(pair, source, counter, point)
            )
            child.start()
            child.join(20)
            if child.is_alive():
                child.kill()
                child.join()
                self.fail("Synthetic child failed to reach named cut")
            assert child.exitcode == -signal.SIGKILL
            assert counter.read_bytes() == (b"0" if index == 0 else b"1")
            with refuses(fixed.raw.PhysicalPause, "PAUSED"):
                self.run_pair(pair, source, counter=counter)
            if index:
                decision = pair.peers[0]._record(0, "DECISION")
                receipt = pair.recover(
                    sequence=0,
                    expected_prior=self.genesis,
                    owner_decision_sha256=fixed.raw._sha(fixed.raw._encoded(decision)),
                )
                assert pair.completed(receipt)["root"]["bytes"] == source.stat().st_size
                assert counter.read_bytes() == b"1"

    # Reject torn index/body bytes and authenticate prior content before another effect.
    def test_corrupt_object_or_index_cannot_be_adopted(self):
        for kind in ("body", "index", "head"):
            pair = self.pair(kind)
            receipt = self.run_pair(
                pair,
                self.source(kind + "-source"),
                counter=self.counter(kind + "-counter"),
            )
            peer = pair.peers[0]
            root = peer._verify(receipt["root"])
            reference = next(peer._walk(root["tree"]))["content"]
            offset = 0
            path = peer.root / "body" / str(reference["slot"])
            if kind == "index":
                offset, _ = peer._bucket("body", reference["sha256"])
                path = peer.root / "index"
            elif kind == "head":
                path = peer.root / "head0"
            descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
            try:
                assert os.pwrite(descriptor, b"!", offset) == 1
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            with refuses(fixed.raw.PhysicalPause):
                pair.completed(receipt)
            counter = self.counter(kind + "-no-effect")
            with refuses(fixed.raw.PhysicalPause):
                self.run_pair(
                    pair, self.root / (kind + "-source"), receipt["decision"], counter
                )
            assert counter.read_bytes() == b"0"

    # Reject false declarations and duplicate local peer identities.
    def test_declaration_source_profile_and_duplicate_peer_refuse(self):
        identity = deepcopy(self.identity)
        identity["source_revision"] = "ad44d536a70d5c037cb931836a3c9f48b014d84a"
        with refuses(fixed.raw.PhysicalPause, "CURRENT profile"):
            fixed.reserve(
                self.root / "mixed",
                peer="a",
                peers=["a", "b"],
                owner="a",
                genesis=self.genesis,
                identity=identity,
                identity_sha256=fixed.raw._sha(fixed.raw._encoded(identity)),
                writer_source=self.writer,
                limits=self.limits(),
            )
        assert not (self.root / "mixed").exists()
        pair = self.pair()
        with refuses(fixed.raw.PhysicalPause, "Duplicate peer"):
            fixed.FixtureTransport([pair.peers[0], pair.peers[0]])
        peer = pair.peers[0]
        header = deepcopy(peer.header)
        header["common"]["amounts"]["file_bytes"] += 1
        fixed._write(peer.root / "header", fixed.raw.META, header)
        with refuses(fixed.raw.PhysicalPause, "Resource arithmetic"):
            fixed.Peer(peer.root, identity_sha256=self.pin, writer_source=self.writer)
        counter = self.counter()
        with refuses(fixed.raw.PhysicalPause, "declaration differs"):
            self.run_pair(pair, self.source(), counter=counter)
        assert counter.read_bytes() == b"0"

    # Refuse missing extents, sparse substitutions and symlinks before issuing ARM.
    def test_missing_sparse_or_symlink_reservation_refuse(self):
        for kind in ("missing", "sparse", "symlink"):
            pair = self.pair(kind)
            path = pair.peers[0].root / "body/0"
            if kind == "sparse":
                with path.open("r+b") as handle:
                    handle.truncate(0)
                    handle.truncate(pair.common["limits"]["span_bytes"])
            else:
                path.unlink()
                if kind == "symlink":
                    path.symlink_to(pair.peers[0].root / "body/1")
            counter = self.counter(kind + "-counter")
            with refuses((fixed.raw.PhysicalPause, OSError)):
                self.run_pair(pair, self.source(kind + "-source"), counter=counter)
            assert counter.read_bytes() == b"0"

    # Preserve charged OPEN state on real partial-write, fsync and readback error paths.
    def test_short_write_fsync_and_readback_failures_pause(self):
        for kind in ("short", "fsync", "read"):
            pair = self.pair(kind)
            source, counter = (
                self.source(kind + "-source"),
                self.counter(kind + "-counter"),
            )
            inode = (pair.peers[0].root / "body/0").stat().st_ino
            original_write, original_sync, original_read = os.pwrite, os.fsync, os.read

            # Shorten only a real body write, retaining its partially written bytes.
            def short(descriptor, value, offset, inode=inode, original=original_write):
                if os.fstat(descriptor).st_ino == inode:
                    return original(descriptor, value[:-1], offset)
                return original(descriptor, value, offset)

            # Refuse one body durability call without changing metadata/source bytes.
            def failed_sync(descriptor, inode=inode, original=original_sync):
                if os.fstat(descriptor).st_ino == inode:
                    raise OSError("SYNTHETIC fsync failure")
                return original(descriptor)

            # Corrupt only observed body readback, not the actual retained file content.
            def failed_read(descriptor, amount, inode=inode, original=original_read):
                value = original(descriptor, amount)
                if os.fstat(descriptor).st_ino == inode and value:
                    return b"!" + value[1:]
                return value

            attribute, replacement = {
                "short": ("pwrite", short),
                "fsync": ("fsync", failed_sync),
                "read": ("read", failed_read),
            }[kind]
            with (
                patch.object(os, attribute, side_effect=replacement),
                refuses((fixed.raw.PhysicalPause, OSError)),
            ):
                self.run_pair(pair, source, counter=counter)
            assert counter.read_bytes() == b"1"
            assert pair.peers[0]._control()["open"] == 0
            with refuses(fixed.raw.PhysicalPause, "PAUSED"):
                self.run_pair(pair, source, counter=counter)

    # Refuse effects when allocation or initialization is unavailable.
    def test_preparation_allocation_and_initialization_failures(self):
        with (
            patch.object(
                os, "posix_fallocate", side_effect=OSError("SYNTHETIC ENOSPC")
            ),
            refuses(fixed.raw.PhysicalPause, "allocation"),
        ):
            self.pair("no-space")
        with (
            patch.object(os, "pwrite", return_value=0),
            refuses(fixed.raw.PhysicalPause, "initialization"),
        ):
            self.pair("short-initialization")
        original = fixed.raw._allocate

        # Fail the second peer only after the first peer's real reservation is retained.
        def second_peer(path, size):
            if Path(path).parent.name == "b":
                raise fixed.raw.PhysicalPause("SYNTHETIC second allocation refused")
            return original(path, size)

        with (
            patch.object(fixed.raw, "_allocate", side_effect=second_peer),
            refuses(fixed.raw.PhysicalPause, "second allocation"),
        ):
            self.pair("second-peer-failure")
        assert (self.root / "second-peer-failure/a/header").stat().st_blocks > 0

    # Reject a rehashed but reordered manifest and an incorrect physical slot reference.
    def test_reordered_manifest_and_wrong_slot_refuse(self):
        pair, source = self.pair(), self.source(rows=[{"i": 1}, {"i": 2}])
        with pair._locked():
            for peer in pair.peers:
                peer._arm(0, self.genesis)
            reference = pair._capture(0, source)
            peer = pair.peers[0]
            root = peer._verify(reference)
            page = fixed.raw._decoded(b"".join(peer._content(root["tree"])))
            assert page["level"] == 0
            page["refs"][1], page["refs"][2] = page["refs"][2], page["refs"][1]
            root["tree"] = pair._put(0, "page", fixed.raw._encoded(page))
            bad = pair._put(0, "page", fixed.raw._encoded(root))
            with refuses(fixed.raw.PhysicalPause, "Complete opaque bytes"):
                peer._verify(bad)
            wrong = deepcopy(reference)
            wrong["slot"] = (wrong["slot"] + 1) % peer._control()["page"]
            with refuses(fixed.raw.PhysicalPause, "index differs"):
                b"".join(peer._content(wrong))

    # Keep both roots OPEN when a durable peer ACK is unobserved by the coordinator.
    def test_unknown_final_ack_requires_pinned_metadata_recovery(self):
        pair, source, counter = self.pair(), self.source(), self.counter()

        # Lose only the post-readback notification of the second local ACK record.
        def lost(name):
            if name == "ack:durable:b":
                raise OSError("SYNTHETIC final ACK unknown")

        pair.transport.point = lost
        with refuses(OSError, "final ACK"):
            self.run_pair(pair, source, counter=counter)
        assert all(peer._control()["open"] == 0 for peer in pair.peers)
        with refuses(fixed.raw.PhysicalPause, "PAUSED"):
            self.run_pair(pair, source, counter=counter)
        decision = pair.peers[0]._record(0, "DECISION")
        pin = fixed.raw._sha(fixed.raw._encoded(decision))

        # Restore transport observation only; recovery still has no callback parameter.
        def observed(name):
            pass

        pair.transport.point = observed
        receipt = pair.recover(
            sequence=0, expected_prior=self.genesis, owner_decision_sha256=pin
        )
        assert pair.completed(receipt)["native_metadata_reserved"] is False
        assert counter.read_bytes() == b"1"

    # Keep malformed framing, receipt flags and missing owner decisions unadoptable.
    def test_malformed_framing_and_false_completion_refuse(self):
        pair = self.pair()
        source = self.root / "malformed"
        source.write_bytes(b'{\n  "history": [\n    {\n      "x": NaN\n')
        source.chmod(0o600)
        with refuses(fixed.raw.PhysicalPause):
            self.run_pair(pair, source)
        with refuses(fixed.raw.PhysicalPause, "owner decision"):
            pair.recover(
                sequence=0, expected_prior=self.genesis, owner_decision_sha256="0" * 64
            )
        pair = self.pair("complete")
        receipt = self.run_pair(
            pair, self.source(), counter=self.counter("complete-counter")
        )
        receipt["native_metadata_reserved"] = True
        with refuses(fixed.raw.PhysicalPause, "Exact local receipt"):
            pair.completed(receipt)
