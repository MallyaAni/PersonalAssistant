"""Deferred fake-stream/session tests; no actual transport or native account.

All source/body/host bindings and sessions are SYNTHETIC. Only public reviewed
CURRENT identity/writer bytes are read inertly. No native code/model/provider is
imported. Retain every file, partially received body and killed session in /out.
"""

import hashlib
import io
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

from backend.market import historical_checkpoint_peer_rpc as rpc


# Require explicit refusal without pytest, application conftest or account fixtures.
@contextmanager
def refuses(errors, text=None):
    caught = None
    try:
        yield
    except errors as error:
        caught = error
    if caught is None:
        raise AssertionError(f"Expected refusal: {errors}")
    if text is not None:
        assert text in str(caught)


# Construct one finite synthetic frame; this is not a network client or host receipt.
def frame(header, payload=b""):
    value = rpc.fixed.raw._encoded(header)
    return len(value).to_bytes(8, "big") + value + payload + rpc.TRAILER


# Retain finite fake replies for the next request's observed control preimage.
class Replies(io.BytesIO):
    # Preserve all reply dictionaries without writing any filesystem object.
    def __init__(self):
        super().__init__()
        self.values = []

    # Decode each flushed reply while retaining the bytes only in this fake stream.
    def flush(self):
        value = self.getvalue()
        amount = int.from_bytes(value[:8], "big")
        assert len(value) == amount + 16
        assert value[-8:] == rpc.TRAILER
        self.values.append(rpc.fixed.raw._decoded(value[8 : 8 + amount]))
        self.seek(0)
        self.truncate(0)


# Generate bounded positive short reads from an explicit finite synthetic conversation.
class Script:
    # Keep no default socket, network client, file path or executable method name.
    def __init__(self, server, replies, steps, *, fragment=97, ordinary=True):
        self.server, self.replies, self.steps = server, replies, steps
        self.fragment, self.ordinary = fragment, ordinary
        self.index, self.current, self.offset, self.max_read = 0, b"", 0, 0

    # Build a header from an observed reply or pinned initial preimage.
    def header(self, verb, args, payload, changes):
        permit = self.server.permit
        control = (
            self.replies.values[-1]["status"]["peer_control"]
            if self.replies.values
            else permit["control"]
        )
        return {
            "version": rpc.VERSION,
            "permit": self.server.pin,
            "launch": permit["launch"],
            "peer": permit["peer"],
            "request": self.index if self.ordinary else 0,
            "operation": permit["operation"],
            "prior": permit["prior"],
            "control": None if verb == "STATUS" else control,
            "verb": verb,
            "args": args,
            "payload_bytes": len(payload),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            **changes,
        }

    # Return no more than the requested64KiB fragment, or explicit EOF after all steps.
    def read(self, amount):
        assert 0 < amount <= rpc.fixed.raw.READ
        self.max_read = max(self.max_read, amount)
        if self.offset == len(self.current):
            if self.index == len(self.steps):
                return b""
            verb, args, payload, changes = self.steps[self.index]
            self.current = frame(self.header(verb, args, payload, changes), payload)
            self.index += 1
            self.offset = 0
        end = min(len(self.current), self.offset + min(amount, self.fragment))
        value = self.current[self.offset : end]
        self.offset = end
        return value


# Kill a fixture child after real session-consumption or ingress charges.
def killed(server, steps, point):
    # Preserve actual local writes before stopping at the named adapter cut.
    def stop(name):
        if name == point:
            os.kill(os.getpid(), signal.SIGKILL)

    server.point = stop
    replies = Replies()
    server.serve(Script(server, replies, steps), replies, ordinary=True)


# Exercise one fixed-slot Peer through fake bytes only, never actual remote placement.
class PeerRPCTests(unittest.TestCase):
    # Read only inert public CURRENT identity/writer fixtures before any test starts.
    @classmethod
    def setUpClass(cls):
        cls.writer = Path("/fixture/current-writer.py")
        path = Path("/fixture/current-identity.json")
        assert path.stat().st_size < 32768
        cls.identity = json.loads(path.read_bytes())
        cls.pin = rpc.fixed.raw._sha(rpc.fixed.raw._encoded(cls.identity))
        cls.genesis = hashlib.sha256(b"SYNTHETIC_RPC_GENESIS").hexdigest()

    # Retain successful, failed and killed synthetic fixtures.
    def setUp(self):
        parent = Path("/out/cases")
        parent.mkdir(mode=0o700, exist_ok=True)
        self.root = Path(
            tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=parent)
        )

    # Reserve one exact CURRENT local Peer without starting any stream/session.
    def bare_peer(self, name="peer", **changes):
        limits = {
            "body_slots": 12,
            "page_slots": 8,
            "span_bytes": 4096,
            "raw_bytes": 65536,
            "history_rows": 4,
            "operations": 1,
            **changes,
        }
        return rpc.fixed.reserve(
            self.root / name,
            peer="a",
            peers=["a", "b"],
            owner="a",
            genesis=self.genesis,
            identity=self.identity,
            identity_sha256=self.pin,
            writer_source=self.writer,
            limits=limits,
        )

    # Reserve unique actual future session files over a source-pinned local Peer.
    def fixture(self, name="peer", **changes):
        peer = self.bare_peer(name, **changes)
        host, launch = (
            hashlib.sha256(("SYNTHETIC_HOST" + name).encode()).hexdigest(),
            hashlib.sha256(("SYNTHETIC_LAUNCH" + name).encode()).hexdigest(),
        )
        result = rpc.prepare(
            peer,
            host_binding_sha256=host,
            launch_sha256=launch,
            operation=0,
            prior=self.genesis,
            control_sha256=rpc.fixed.raw._sha(rpc.fixed.raw._encoded(peer._control())),
        )
        return rpc.Server(
            peer,
            expected_permit_sha256=result["permit_sha256"],
            expected_host_binding_sha256=host,
            expected_launch_sha256=launch,
        )

    # Reopen the same pinned session without creating another ordinary grant.
    def reopen(self, server):
        return rpc.Server(
            server.peer,
            expected_permit_sha256=server.pin,
            expected_host_binding_sha256=server.permit["host_binding"],
            expected_launch_sha256=server.permit["launch"],
        )

    # Build an opaque root from fake physical spans and numeric slots.
    def full_steps(self, server):
        data = json.dumps(
            {"before": "SYNTHETIC", "history": [{"x": float("nan")}], "after": 1},
            indent=2,
        ).encode()
        steps = [("HELLO", {}, b"", {}), ("ARM", {}, b"", {})]
        references = []
        for slot, (role, value) in enumerate(
            rpc.fixed.raw._spans(io.BytesIO(data), server.peer.limits)
        ):
            steps.append(("PUT", {"kind": "body"}, value, {}))
            references.append(
                {
                    "role": role,
                    "content": {
                        "kind": "body",
                        "slot": slot,
                        "length": len(value),
                        "sha256": hashlib.sha256(value).hexdigest(),
                    },
                }
            )
        page = rpc.fixed.raw._encoded({"level": 0, "refs": references})
        tree = {
            "kind": "page",
            "slot": 0,
            "length": len(page),
            "sha256": hashlib.sha256(page).hexdigest(),
        }
        root = rpc.fixed.raw._encoded(
            {
                "binding": server.peer.binding,
                "raw_sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "rows": 1,
                "tree": tree,
            }
        )
        reference = {
            "kind": "page",
            "slot": 1,
            "length": len(root),
            "sha256": hashlib.sha256(root).hexdigest(),
        }
        steps.extend(
            [
                ("PUT", {"kind": "page"}, page, {}),
                ("PUT", {"kind": "page"}, root, {}),
                ("VERIFY", {"root": reference}, b"", {}),
            ]
        )
        return steps, data

    # Return STATUS without a mutation preimage or ordinary grant.
    def status(self, server):
        replies = Replies()
        server.serve(
            Script(server, replies, [("STATUS", {}, b"", {})], ordinary=False),
            replies,
            ordinary=False,
        )
        return replies.values[-1]["result"]

    # Preserve real opaque NaN bytes through ingress and finish only at local PREPARED.
    def test_full_fake_conversation_prepared_is_not_commit(self):
        server = self.fixture()
        steps, data = self.full_steps(server)
        replies = Replies()
        incoming = Script(server, replies, steps, fragment=7)
        result = server.serve(incoming, replies, ordinary=True)
        assert result["status"]["rpc"]["phase"] == "PREPARED"
        assert result["status"]["peer_open"] == 0
        assert result["status"]["rpc"]["payload"] == sum(len(step[2]) for step in steps)
        reference = result["result"]["root"]
        assert (
            server.peer._verify(reference)["raw_sha256"]
            == hashlib.sha256(data).hexdigest()
        )
        assert incoming.max_read <= rpc.fixed.raw.READ
        assert server.peer._record(0, "DECISION") is None
        assert server.peer._record(0, "ACK") is None
        for key in rpc.CLAIMS:
            assert result["result"][key] is False
        status = self.status(self.reopen(server))
        assert status["ordinary_available"] is False
        assert status["prepared"] is not None

    # Reject trailing input before a PREPARED reply without granting another mutation.
    def test_prepared_terminal_rejects_following_frame(self):
        server, replies = self.fixture(), Replies()
        steps, _ = self.full_steps(server)
        terminal_requests = len(steps)
        steps.append(("STATUS", {}, b"", {}))
        with refuses(rpc.fixed.raw.PhysicalPause, "Terminal frame requires input EOF"):
            server.serve(Script(server, replies, steps), replies, ordinary=True)
        assert len(replies.values) == terminal_requests - 1
        assert server._control()["requests"] == terminal_requests
        assert server._control()["phase"] == "PAUSED"
        assert server._control()["prepared"] is not None
        assert server.peer._control()["open"] == 0
        assert server.peer._record(0, "DECISION") is None
        assert server.peer._record(0, "ACK") is None
        with refuses(rpc.fixed.raw.PhysicalPause, "STATUS only"):
            self.reopen(server).serve(io.BytesIO(), Replies(), ordinary=True)

    # Reject a trailing STATUS frame before any response or ordinary grant is emitted.
    def test_status_terminal_rejects_following_frame(self):
        server, replies = self.fixture(), Replies()
        before = deepcopy(server._control()), deepcopy(server.peer._control())
        incoming = Script(
            server,
            replies,
            [("STATUS", {}, b"", {}), ("STATUS", {}, b"", {})],
            ordinary=False,
        )
        with refuses(rpc.fixed.raw.PhysicalPause, "Terminal frame requires input EOF"):
            server.serve(incoming, replies, ordinary=False)
        assert replies.values == []
        assert (server._control(), server.peer._control()) == before
        assert server._session() is None
        assert server.peer._record(0, "DECISION") is None
        assert server.peer._record(0, "ACK") is None

    # Report a stale closed control preimage without consuming an ordinary session.
    def test_status_changed_closed_preimage_is_unavailable(self):
        server = self.fixture()
        changed = deepcopy(server.peer._control())
        changed["head"] = hashlib.sha256(b"SYNTHETIC_CHANGED_CLOSED_HEAD").hexdigest()
        with server.peer._locked():
            rpc.fixed._write(server.peer.root / "control", rpc.fixed.raw.META, changed)
        assert server.peer._control() == changed
        assert changed["open"] is None
        before = deepcopy(server._control()), deepcopy(server.peer._control())
        status = self.status(server)
        assert status["ordinary_available"] is False
        assert status["peer_control"] != server.permit["control"]
        assert (server._control(), server.peer._control()) == before
        assert server._session() is None
        with refuses(rpc.fixed.raw.PhysicalPause, "STATUS only"):
            server.serve(io.BytesIO(), Replies(), ordinary=True)
        assert (server._control(), server.peer._control()) == before
        assert server._session() is None

    # Consume durably before even retrieving a failing external read implementation.
    def test_read_failure_before_arm_never_grants_another_session(self):
        server = self.fixture()

        # Fail the first external read after the unique session receipt already exists.
        class Broken:
            # Inspect only the actual local consumption record before raising.
            def read(self, amount):
                assert (
                    rpc.fixed._read(server.root / "session", rpc.fixed.raw.META)
                    is not None
                )
                raise OSError("SYNTHETIC read unavailable")

        with refuses(OSError, "read unavailable"):
            server.serve(Broken(), Replies(), ordinary=True)
        assert server.peer._control()["open"] is None
        assert server._control()["requests"] == 1
        with refuses(rpc.fixed.raw.PhysicalPause, "STATUS only"):
            self.reopen(server).serve(io.BytesIO(), Replies(), ordinary=True)
        assert self.status(self.reopen(server))["ordinary_available"] is False
        with refuses(FileExistsError):
            rpc.prepare(
                server.peer,
                host_binding_sha256=server.permit["host_binding"],
                launch_sha256=server.permit["launch"],
                operation=0,
                prior=self.genesis,
                control_sha256=server.permit["control"],
            )

    # Keep HELLO/EOF consumed even while the Peer remains idle.
    def test_eof_after_hello_remains_status_only(self):
        server, replies = self.fixture(), Replies()
        with refuses(rpc.fixed.raw.PhysicalPause, "Truncated"):
            server.serve(
                Script(server, replies, [("HELLO", {}, b"", {})]),
                replies,
                ordinary=True,
            )
        assert server._control()["next"] == 1
        assert server._control()["requests"] == 2
        assert self.status(self.reopen(server))["peer_open"] is None
        with refuses(rpc.fixed.raw.PhysicalPause, "STATUS only"):
            self.reopen(server).serve(io.BytesIO(), Replies(), ordinary=True)

    # Retain PUT charges before body reads when delivery never occurs.
    def test_partial_body_is_charged_before_read_and_never_retried(self):
        server, replies = self.fixture(), Replies()
        steps = [
            ("HELLO", {}, b"", {}),
            ("ARM", {}, b"", {}),
            ("PUT", {"kind": "body"}, b"SYNTHETIC" * 10, {}),
        ]

        # Stop exactly at the durable payload-charge boundary before any payload read.
        def stop(name):
            if name == "put_ingress_charged":
                assert server._control()["payload"] == 90
                assert server.peer._control()["body"] == 0
                raise OSError("SYNTHETIC payload channel lost")

        server.point = stop
        with refuses(OSError, "channel lost"):
            server.serve(Script(server, replies, steps), replies, ordinary=True)
        assert server._control()["payload"] == 90
        assert server.peer._control()["open"] == 0
        with refuses(rpc.fixed.raw.PhysicalPause, "STATUS only"):
            self.reopen(server).serve(io.BytesIO(), Replies(), ordinary=True)

    # Refuse partial EOF and extra body bytes before object publication.
    def test_truncated_payload_and_wrong_trailer_keep_charges(self):
        for kind in ("truncated", "trailer"):
            server, replies = self.fixture(kind), Replies()
            steps = [
                ("HELLO", {}, b"", {}),
                ("ARM", {}, b"", {}),
                ("PUT", {"kind": "body"}, b"SYNTHETIC" * 10, {}),
            ]

            # Corrupt only the last finite fake frame, preserving its original header.
            class Damaged(Script):
                # Modify fake bytes after their first prefix read, not real files.
                def read(self, amount, kind=kind):
                    old = self.index
                    value = super().read(amount)
                    if old == 2 and self.index == 3:
                        if kind == "truncated":
                            self.current = self.current[: -len(rpc.TRAILER) - 7]
                        else:
                            self.current = self.current[:-8] + b"BADTRAIL"
                    return value

            with refuses(rpc.fixed.raw.PhysicalPause):
                server.serve(Damaged(server, replies, steps), replies, ordinary=True)
            assert server._control()["payload"] == 90
            assert server.peer._control()["body"] == 0

    # Preserve immutable consumption even if an old unused control image reappears.
    def test_immutable_session_blocks_ready_control_replay(self):
        server = self.fixture()
        unused = deepcopy(server._control())
        with refuses(rpc.fixed.raw.PhysicalPause, "Truncated"):
            server.serve(io.BytesIO(), Replies(), ordinary=True)
        session = rpc.fixed._read(server.root / "session", rpc.fixed.raw.META)
        rpc.fixed._write(server.root / "control", rpc.fixed.raw.META, unused)
        with refuses(rpc.fixed.raw.PhysicalPause, "STATUS only"):
            self.reopen(server).serve(io.BytesIO(), Replies(), ordinary=True)
        assert rpc.fixed._read(server.root / "session", rpc.fixed.raw.META) == session
        assert self.status(self.reopen(server))["ordinary_available"] is False

    # Reject source/operation/control/sequence drift without dispatching an ARM or PUT.
    def test_exact_header_and_preimage_refusals(self):
        changes = [
            {"permit": "0" * 64},
            {"operation": True},
            {"request": True},
            {"control": "0" * 64},
            {"encoding": "gzip"},
            {"verb": "DECISION"},
            {"args": {"path": "/never"}},
            {"request": 1},
        ]
        for index, change in enumerate(changes):
            server, replies = self.fixture(f"case{index}"), Replies()
            with refuses(rpc.fixed.raw.PhysicalPause):
                server.serve(
                    Script(server, replies, [("HELLO", {}, b"", change)]),
                    replies,
                    ordinary=True,
                )
            assert server.peer._control()["open"] is None
            assert server._control()["payload"] == 0

    # Refuse malformed hash/overflow/duplicate-key/header frames.
    def test_hash_header_duplicate_and_overflow_refusals(self):
        for index, change in enumerate(
            ({"payload_sha256": "0" * 64}, {"payload_bytes": 4097})
        ):
            server, replies = self.fixture(f"body{index}"), Replies()
            steps = [
                ("HELLO", {}, b"", {}),
                ("ARM", {}, b"", {}),
                ("PUT", {"kind": "body"}, b"SYNTHETIC", change),
            ]
            with refuses(rpc.fixed.raw.PhysicalPause):
                server.serve(Script(server, replies, steps), replies, ordinary=True)
            assert server.peer._control()["body"] == 0
        for index, header in enumerate(
            (b'{"version":1,"version":2}', b'{"value":1e999}')
        ):
            server = self.fixture(f"header{index}")
            with refuses(rpc.fixed.raw.PhysicalPause):
                server.serve(
                    io.BytesIO(len(header).to_bytes(8, "big") + header + rpc.TRAILER),
                    Replies(),
                    ordinary=True,
                )
        server = self.fixture("long-header")
        with refuses(rpc.fixed.raw.PhysicalPause, "Header cap"):
            server.serve(
                io.BytesIO((rpc.fixed.raw.META + 1).to_bytes(8, "big")),
                Replies(),
                ordinary=True,
            )

    # Count every received body even when the immutable object already exists by hash.
    def test_dedup_does_not_refund_ingress_quota(self):
        server, replies = self.fixture(history_rows=1), Replies()
        steps = [("HELLO", {}, b"", {}), ("ARM", {}, b"", {})]
        steps += [("PUT", {"kind": "body"}, b"SYNTHETIC", {})] * 4
        with refuses(rpc.fixed.raw.PhysicalPause, "Cumulative ingress"):
            server.serve(Script(server, replies, steps), replies, ordinary=True)
        assert server._control()["body_puts"] == 3
        assert server._control()["body_bytes"] == 27
        assert server.peer._control()["body"] == 1

    # Preserve unknown response delivery after the actual ARM was already durable.
    def test_response_failure_keeps_open_and_status_only(self):
        server = self.fixture()

        # Lose only the second flushed response, after local ARM metadata was written.
        class Lost(Replies):
            # Retain the actual decoded reply before simulating a failed external ACK.
            def flush(self):
                super().flush()
                if len(self.values) == 2:
                    raise OSError("SYNTHETIC response unknown")

        replies = Lost()
        with refuses(OSError, "response unknown"):
            server.serve(
                Script(server, replies, [("HELLO", {}, b"", {}), ("ARM", {}, b"", {})]),
                replies,
                ordinary=True,
            )
        assert server.peer._control()["open"] == 0
        assert self.status(self.reopen(server))["ordinary_available"] is False

    # Check continuous lock ownership without leases or takeover.
    def test_continuous_lock_and_launch_binding_refuse(self):
        server = self.fixture()
        with server._locked(), refuses(rpc.fixed.raw.PhysicalPause, "already active"):
            self.reopen(server).serve(io.BytesIO(), Replies(), ordinary=False)
        with refuses(rpc.fixed.raw.PhysicalPause, "Launch"):
            rpc.Server(
                server.peer,
                expected_permit_sha256=server.pin,
                expected_host_binding_sha256="0" * 64,
                expected_launch_sha256=server.permit["launch"],
            )
        permit = deepcopy(server.permit)
        permit["peer_root"]["inode"] += 1
        rpc.fixed._write(server.root / "permit", rpc.fixed.raw.META, permit)
        with refuses(rpc.fixed.raw.PhysicalPause, "resources differ"):
            rpc.Server(
                server.peer,
                expected_permit_sha256=rpc.fixed.raw._sha(
                    rpc.fixed.raw._encoded(permit)
                ),
                expected_host_binding_sha256=permit["host_binding"],
                expected_launch_sha256=permit["launch"],
            )

    # Refuse unavailable or sparse actual future session inodes without any stream read.
    def test_session_allocation_and_extent_integrity_refuse(self):
        peer = self.bare_peer("allocation-failure")
        with (
            patch.object(
                os, "posix_fallocate", side_effect=OSError("SYNTHETIC ENOSPC")
            ),
            refuses(rpc.fixed.raw.PhysicalPause, "allocation"),
        ):
            rpc.prepare(
                peer,
                host_binding_sha256="1" * 64,
                launch_sha256="2" * 64,
                operation=0,
                prior=self.genesis,
                control_sha256=rpc.fixed.raw._sha(
                    rpc.fixed.raw._encoded(peer._control())
                ),
            )
        assert peer._control()["open"] is None
        server = self.fixture("actual-extents")
        total = 0
        for name, size in (
            ("permit", rpc.fixed.raw.META),
            ("control", rpc.fixed.raw.META),
            ("session", rpc.fixed.raw.META),
            ("lock", 4096),
        ):
            info = (server.root / name).stat()
            assert info.st_size == size
            assert info.st_blocks * 512 >= size
            assert info.st_mode & 0o777 == 0o600
            total += size
        assert total == rpc._amounts()["file_bytes"]
        with (server.root / "control").open("r+b") as handle:
            handle.truncate(0)
            handle.truncate(rpc.fixed.raw.META)
        with refuses(rpc.fixed.raw.PhysicalPause):
            self.reopen(server)

    # Refuse namespace creation after durable session consumption.
    def test_no_post_consume_namespace_creation(self):
        server, replies = self.fixture(), Replies()
        steps, _ = self.full_steps(server)
        original, consumed = os.open, False

        # Observe actual durable consumption rather than the start of preparation.
        def mark(name):
            nonlocal consumed
            if name == "session_consumed":
                consumed = True

        # Permit opens of existing files only after the ordinary grant was consumed.
        def existing(path, flags, *args, **kwargs):
            assert not consumed or flags & os.O_CREAT == 0
            return original(path, flags, *args, **kwargs)

        # Fail namespace mutation in this synthetic checkpoint-only invocation.
        def forbidden(*args, **kwargs):
            raise AssertionError("SYNTHETIC post-consume namespace allocation")

        server.point = mark
        with (
            patch.object(os, "open", side_effect=existing),
            patch.object(os, "mkdir", side_effect=forbidden),
            patch.object(os, "link", side_effect=forbidden),
            patch.object(os, "rename", side_effect=forbidden),
            patch.object(os, "replace", side_effect=forbidden),
            patch.object(os, "unlink", side_effect=forbidden),
        ):
            server.serve(Script(server, replies, steps), replies, ordinary=True)
        assert consumed

    # Retain actual process kills before ARM and after payload charging before read.
    def test_sigkill_session_and_ingress_are_never_regranted(self):
        for index, point in enumerate(("session_consumed", "put_ingress_charged")):
            server = self.fixture(f"kill{index}")
            steps = [
                ("HELLO", {}, b"", {}),
                ("ARM", {}, b"", {}),
                ("PUT", {"kind": "body"}, b"SYNTHETIC", {}),
            ]
            process = multiprocessing.get_context("fork").Process(
                target=killed, args=(server, steps, point)
            )
            process.start()
            process.join(20)
            if process.is_alive():
                process.kill()
                process.join()
                self.fail("Synthetic RPC child did not reach named cut")
            assert process.exitcode == -signal.SIGKILL
            assert server._control()["consumed"] is True
            assert server._control()["payload"] == (9 if index else 0)
            assert server.peer._control()["open"] == (0 if index else None)
            assert server.peer._control()["body"] == 0
            with refuses(rpc.fixed.raw.PhysicalPause, "STATUS only"):
                self.reopen(server).serve(io.BytesIO(), Replies(), ordinary=True)
            assert self.status(self.reopen(server))["ordinary_available"] is False

    # Measure the full20MiB ingress/readback path separately from tiny framing fixtures.
    def test_maximum_binary_buffer_is_bounded_and_charged(self):
        span = rpc.fixed.raw.SPAN
        server = self.fixture(
            body_slots=3, page_slots=3, history_rows=1, span_bytes=span, raw_bytes=span
        )
        replies = Replies()
        payload = b"x" * span
        steps = [
            ("HELLO", {}, b"", {}),
            ("ARM", {}, b"", {}),
            ("PUT", {"kind": "body"}, payload, {}),
        ]
        incoming = Script(server, replies, steps, fragment=rpc.fixed.raw.READ)
        with refuses(rpc.fixed.raw.PhysicalPause, "Truncated"):
            server.serve(incoming, replies, ordinary=True)
        assert server._control()["payload"] == span
        assert server.peer._control()["body"] == 1
        assert incoming.max_read <= rpc.fixed.raw.READ
        assert server._control()["phase"] == "PAUSED"
