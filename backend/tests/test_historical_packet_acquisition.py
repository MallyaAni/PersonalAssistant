"""Native-only synthetic fake acquisition; no provider transport or real permission."""

import errno
import hashlib
import io
import json
import multiprocessing
import os
import signal
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from backend.market import historical_packet_acquisition as acquisition
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_parser as parser
from backend.market import historical_packet_registry as registry
from backend.market import historical_packet_store as store_module
from backend.market.historical_packet_store import Store, StorePause
from backend.tests.test_historical_packet_rate import Clock
from backend.tests.test_historical_packet_store import mapping, sha

OBSERVATIONS = []


# Make explicit synthetic mapping claims without manufacturing provider issuer identity.
def reviewed_names(names):
    original = mapping()
    template = json.loads(original.raw)["entries"][0]
    entries = [{**template, "cohort_key": name, "query_symbol": name} for name in names]
    raw = demand.encoded({"schema": "historical-entity-registry/1", "entries": entries})
    return registry.registry(
        raw, hashlib.sha256(raw).hexdigest(), dict(original.evidence)
    )


# Freeze identical prior heads and original demands in two passive LOCAL roots.
def pair(root, names=("AAPL",), legs=False, when="2019-03-01T14:45:00Z"):
    root.mkdir(mode=0o700)
    reviewed = reviewed_names(names)
    stores = tuple(
        Store(root / name, sha("identity"), None, create=True)
        for name in ("left", "right")
    )
    declared = None
    for store in stores:
        first = store.append(
            expected_head=None,
            cycle_sha256=sha("cycle"),
            stage="PRIOR_VERIFIED",
            receipt_sha256=sha("SYNTHETIC prior"),
        )
        declared = demand.build(
            reviewed,
            identity_sha256=store.identity,
            parent_sha256=first["sha256"],
            completed_at=when,
            prior={key: sha(key) for key in demand.PRIOR},
            held=sorted(names),
            used=store.snapshot()["used"],
            legs=[
                {
                    "client_order_id": name,
                    "symbol": name,
                    "side": "buy",
                    "qty": 1,
                    "phase": "market",
                    "session": when[:10],
                }
                for name in names
            ]
            if legs
            else [],
        )
        store.declare(declared, reviewed)
        store.append(
            expected_head=first["sha256"],
            cycle_sha256=sha("cycle"),
            stage="DEMAND_FROZEN",
            receipt_sha256=declared.sha256,
        )
        store.append(
            expected_head=store.snapshot()["head"],
            cycle_sha256=sha("cycle"),
            stage="WAIT_PACKETS",
            receipt_sha256=sha("SYNTHETIC wait"),
        )
    return stores, declared, reviewed


# Pin actual implementation bytes and keep the fixture permit explicitly non-live.
def permit(stores, declared, reviewed, **changes):
    value = {
        "schema": "historical-fixture-acquisition/1",
        "mode": "SYNTHETIC_LOCAL_ONLY",
        "real_gets_authorized": False,
        "identity_sha256": stores[0].identity,
        "demand_sha256": declared.sha256,
        "registry_sha256": reviewed.sha256,
        "initial_heads": [store.snapshot()["head"] for store in stores],
        "source_sha256": acquisition.source_pins(),
        "budget": dict(demand.BUDGET),
        "page_body_cap": 256,
        "metadata_headroom": "UNVERIFIED_LOCAL_FIXTURE",
        **changes,
    }
    raw = demand.encoded(value)
    return raw, hashlib.sha256(raw).hexdigest()


# Build a successful empty original-shaped body without any price or model inference.
def body(token=None, symbol="AAPL"):
    return demand.encoded({"quotes": {symbol: []}, "next_page_token": token})


# Supply only in-memory scripted bytes while observing actual durable reservations.
class FakeTransport:
    synthetic_only = True

    # Retain the script and real local stores without creating any network client.
    def __init__(self, stores, script=(), hook=None, repeated=False):
        self.stores, self.script, self.hook = stores, list(script), hook
        self.repeated = repeated
        self.calls, self.responses, self.reads = [], [], []

    # Require both real reservations and allocated extents before this fake callback.
    def get(self, request):
        self.calls.append(request)
        for store in self.stores:
            latest = store.connection.execute(
                "SELECT * FROM attempts ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            assert latest["reserved_utc_us"] > 0
            spool = store._spools[latest["id"]]
            assert spool.allocated_bytes >= spool.logical_ceiling
            for name, row in spool.files.items():
                if name != "manifest":
                    info = (spool.root / name).stat()
                    assert info.st_ino == row["inode"]
                    assert info.st_blocks * 512 >= row["capacity"]
            assert (
                store.connection.execute(
                    "SELECT COUNT(*) FROM reads WHERE attempt=?", (latest["id"],)
                ).fetchone()[0]
                == 1
            )
        if self.hook is not None:
            self.hook(self, request)
        if self.repeated:
            parameters = parse_qs(urlsplit(request.url).query)
            token = parameters.get("page_token", ["0"])[0]
            index = int(token)
            kind = urlsplit(request.url).path.rsplit("/", 1)[1]
            spec = {
                "body": demand.encoded(
                    {
                        kind: {
                            name: [] for name in parameters["symbols"][0].split(",")
                        },
                        "next_page_token": str(index + 1) if index < 7 else None,
                    }
                )
            }
        else:
            spec = self.script.pop(0)
        if isinstance(spec, Exception):
            raise spec
        response_type = (
            BrokenReadResponse if spec.get("read_property_failure") else FakeResponse
        )
        response = response_type(self, request.url, spec)
        self.responses.append(response)
        return response


# Expose a bounded raw-byte reader; all data and failures remain labelled synthetic.
class FakeResponse:
    # Detach scripted header values while keeping its body only in an in-memory stream.
    def __init__(self, transport, url, spec):
        self.transport, self.spec = transport, dict(spec)
        self.url, self.status = spec.get("url", url), spec.get("status", 200)
        self.content_encoding = spec.get("encoding", "identity")
        self.stream = io.BytesIO(spec.get("body", b""))
        self.count, self.closed = 0, False

    # Check the durable allowance before returning at most the requested fake bytes.
    def read(self, count):
        self.transport.reads.append(count)
        for store in self.transport.stores:
            row = store.connection.execute(
                "SELECT * FROM reads ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            assert row["actual"] is None
            assert row["allowance"] == count
        if self.count == self.spec.get("read_failure_at"):
            raise OSError("SYNTHETIC_SECRET_MUST_NOT_BE_LOGGED")
        self.count += 1
        if self.spec.get("mutate_headers"):
            self.url, self.status, self.content_encoding = (
                "https://mutated.invalid/",
                503,
                "gzip",
            )
        return self.stream.read(min(count, self.spec.get("short", count)))

    # Mark closure without issuing a cancellation, retry or other external action.
    def close(self):
        self.closed = True
        hook = self.spec.get("close_hook")
        if hook is not None:
            hook()


# Fail reader retrieval after the response has already become owned.
class BrokenReadResponse(FakeResponse):
    # Raise while leaving the original cleanup method independently callable.
    @property
    def read(self):
        raise OSError("SYNTHETIC reader property failure")


# Check only actual original statuses without assuming a particular close sequence.
def both_retained(stores):
    rows = [
        store.connection.execute("SELECT status FROM attempts").fetchone()
        for store in stores
    ]
    return all(row is not None and row[0] == "RETAINED" for row in rows)


# Freeze a child at real pre-call, callback-entry or fully-retained-page boundaries.
def capture_child(root, connection, boundary):
    stores, declared, reviewed = pair(root)
    raw, digest = permit(stores, declared, reviewed)

    # Retain actual state before the parent sends a real SIGKILL.
    def block(point):
        connection.send(
            {
                "point": point,
                "heads": [store.snapshot()["head"] for store in stores],
                "used": [store.snapshot()["used"] for store in stores],
            }
        )
        connection.recv()

    # Stop after allocation publication while no fake external callback ran.
    def fault(point):
        if point == "spool_linked":
            block("before_transport")

    # Stop inside the sole fake call while the external outcome remains uncertain.
    def hook(transport, request):
        if boundary == "transport_entered":
            block(boundary)

    # Stop after the actual second receipt commit, independently of close ordering.
    def retained(point):
        if point == "after_commit" and both_retained(stores):
            block(boundary)

    if boundary == "before_transport":
        stores[1].fault = fault
    elif boundary == "retained":
        stores[1].fault = retained
    transport = FakeTransport(stores, [{"body": body()}], hook)
    acquisition.capture(
        stores,
        declared,
        reviewed,
        permit_raw=raw,
        expected_permit_sha256=digest,
        transport=transport,
    )
    raise AssertionError("Parent should kill at requested synthetic boundary")


# Exercise native local filesystem composition without any provider/acquirer permission.
class PacketAcquisitionTests(unittest.TestCase):
    # Refuse accidental workstation body roots before allocating any fixture file.
    def setUp(self):
        base = os.environ.get("ANIOS_SYNTHETIC_ACQUISITION_ROOT", "")
        if sys.platform != "linux" or not base.startswith("/out/"):
            raise RuntimeError("Named network-none native fixture required")
        self.root = Path(base) / uuid4().hex
        self.root.mkdir(mode=0o700, parents=True)
        self.stores, self.declared, self.reviewed = pair(self.root / "initial")
        self.all_stores = list(self.stores)

    # Close descriptors while retaining all failed/native body files only on Spark.
    def tearDown(self):
        for store in self.all_stores:
            store.close()

    # Execute the small coordinator with an explicitly externally pinned fixture permit.
    def run_capture(self, transport, **changes):
        raw, digest = permit(self.stores, self.declared, self.reviewed, **changes)
        return acquisition.capture(
            self.stores,
            self.declared,
            self.reviewed,
            permit_raw=raw,
            expected_permit_sha256=digest,
            transport=transport,
        )

    # Check durable slot/extent ordering and load authenticated references.
    def test_successful_pagination_and_network_none_reference_load(self):
        transport = FakeTransport(
            self.stores, [{"body": body("next")}, {"body": body()}]
        )
        ref = self.run_capture(transport)
        packet = acquisition.load(ref, self.stores, self.declared, self.reviewed)
        parsed = parser.read(packet, self.declared, self.reviewed)
        assert len(transport.calls) == 2
        assert transport.reads == [256, 1, 256, 1]
        assert all(reply.closed for reply in transport.responses)
        assert all(
            request.method == "GET"
            and request.retries == 0
            and not request.redirects
            and not request.decode_content
            and request.accept_encoding == "identity"
            for request in transport.calls
        )
        assert parsed["acquisition_authorized"] is False
        assert (
            next(iter(parsed["groups"].values()))["AAPL"]["status"] == "COMPLETE_EMPTY"
        )
        assert all(
            store.snapshot()["used"] == {"get_attempts": 2, "body_bytes": 514}
            for store in self.stores
        )
        OBSERVATIONS.append(
            {
                "kind": "SYNTHETIC_SUCCESS",
                "fake_calls": 2,
                "read_allowances": transport.reads,
                "reference_sha256": ref.sha256,
                "provider_calls": 0,
            }
        )

    # Refuse changed admission pins before callbacks or datastore changes.
    def test_exact_permit_refusals_before_any_callback(self):
        bad_sources = acquisition.source_pins()
        bad_sources["historical_packet_store.py"] = sha("wrong source")
        cases = [
            {"mode": "LIVE"},
            {"real_gets_authorized": True},
            {"identity_sha256": sha("wrong")},
            {"demand_sha256": sha("wrong")},
            {"registry_sha256": sha("wrong")},
            {"initial_heads": [sha("wrong"), sha("wrong")]},
            {"source_sha256": bad_sources},
            {"budget": {**dict(demand.BUDGET), "simulation_cpus": True}},
            {"page_body_cap": True},
            {"page_body_cap": demand.BUDGET["bytes_per_group"]},
            {"extra": "forbidden"},
        ]
        before = [store.snapshot() for store in self.stores]
        for changes in cases:
            with self.subTest(changes=str(changes)):
                transport = FakeTransport(self.stores)
                with pytest.raises(StorePause):
                    self.run_capture(transport, **changes)
                assert transport.calls == []
                assert [store.snapshot() for store in self.stores] == before
        raw, _ = permit(self.stores, self.declared, self.reviewed)
        with pytest.raises(ValueError, match="Pinned"):
            acquisition.capture(
                self.stores,
                self.declared,
                self.reviewed,
                permit_raw=raw,
                expected_permit_sha256=sha("wrong"),
                transport=FakeTransport(self.stores),
            )

    # Endpoint/window/asof mutations cannot replace the original canonical declaration.
    def test_altered_demand_refuses_before_transport(self):
        original = json.loads(self.declared.raw)
        for field, value in (
            ("endpoint", "http://localhost/"),
            ("end", "2020-01-01T00:00:00Z"),
            ("asof", "2020-01-01"),
        ):
            altered = json.loads(demand.encoded(original))
            if field == "endpoint":
                altered["queries"][0][field] = value
            else:
                altered["queries"][0]["parameters"][field] = value
            raw = demand.encoded(altered)
            declared = demand.Demand(raw, hashlib.sha256(raw).hexdigest())
            permit_raw, pin = permit(self.stores, declared, self.reviewed)
            transport = FakeTransport(self.stores)
            with pytest.raises(ValueError, match="Canonical"):
                acquisition.capture(
                    self.stores,
                    declared,
                    self.reviewed,
                    permit_raw=permit_raw,
                    expected_permit_sha256=pin,
                    transport=transport,
                )
            assert transport.calls == []

    # Allocation failure on either passive local replica cannot reach fake transport.
    def test_either_replica_enospc_before_transport(self):
        actual = os.posix_fallocate
        for side in ("left", "right"):
            stores, declared, reviewed = pair(self.root / side)
            self.all_stores.extend(stores)
            raw, pin = permit(stores, declared, reviewed)
            transport = FakeTransport(stores, [{"body": body()}])

            # Fail a chosen reserved descriptor without changing Store metadata writes.
            def fail(descriptor, offset, length, side=side):
                if "/" + side + "/incoming/" in os.readlink(
                    "/proc/self/fd/" + str(descriptor)
                ):
                    raise OSError(errno.ENOSPC, "SYNTHETIC")
                return actual(descriptor, offset, length)

            with (
                patch("os.posix_fallocate", side_effect=fail),
                pytest.raises(StorePause),
            ):
                acquisition.capture(
                    stores,
                    declared,
                    reviewed,
                    permit_raw=raw,
                    expected_permit_sha256=pin,
                    transport=transport,
                )
            assert transport.calls == []
            assert all(
                store.snapshot()["used"]["get_attempts"] == 1 for store in stores
            )
            with pytest.raises(StorePause, match="OPEN"):
                acquisition.capture(
                    stores,
                    declared,
                    reviewed,
                    permit_raw=raw,
                    expected_permit_sha256=pin,
                    transport=transport,
                )
            OBSERVATIONS.append(
                {
                    "kind": "SYNTHETIC_ALLOCATION_FAILURE",
                    "side": side,
                    "fake_calls": 0,
                    "charged_gets_each": 1,
                }
            )

    # A second reservation failure keeps the first charge and refuses later replay.
    def test_second_replica_reservation_failure_is_not_rolled_back(self):
        transport = FakeTransport(self.stores)
        with (
            patch.object(
                self.stores[1], "begin_attempt", side_effect=StorePause("SYNTHETIC")
            ),
            pytest.raises(StorePause),
        ):
            self.run_capture(transport)
        assert [store.snapshot()["used"]["get_attempts"] for store in self.stores] == [
            1,
            0,
        ]
        with pytest.raises(StorePause, match="budgets"):
            self.run_capture(transport)
        assert transport.calls == []

    # Changed final URL, HTTP errors and decompression never reach a body read.
    def test_response_header_failures_pause_without_retry(self):
        for index, changes in enumerate(
            (
                {"status": 301},
                {"status": 403},
                {"status": 429},
                {"status": 503},
                {"encoding": "gzip"},
                {"url": "https://wrong.invalid/"},
            )
        ):
            stores, declared, reviewed = pair(self.root / str(index))
            self.all_stores.extend(stores)
            raw, pin = permit(stores, declared, reviewed)
            transport = FakeTransport(stores, [{"body": body(), **changes}])
            with pytest.raises(StorePause):
                acquisition.capture(
                    stores,
                    declared,
                    reviewed,
                    permit_raw=raw,
                    expected_permit_sha256=pin,
                    transport=transport,
                )
            assert len(transport.calls) == 1
            assert transport.reads == []
            assert transport.responses[0].closed
            assert all(
                store.snapshot()["unresolved"] == {"get_attempts": 1, "body_bytes": 256}
                for store in stores
            )

    # Retain the observed prefix and uncertain charge without leaking error text.
    def test_failed_body_read_retains_prefix_and_no_retry(self):
        transport = FakeTransport(self.stores, [{"body": body(), "read_failure_at": 1}])
        with pytest.raises(StorePause):
            self.run_capture(transport)
        assert transport.responses[0].closed
        assert transport.reads == [256, 1]
        for store in self.stores:
            assert store.snapshot()["confirmed_bytes"] == len(body())
            assert store.snapshot()["unresolved"] == {
                "get_attempts": 1,
                "body_bytes": 1,
            }
            spool = next(iter(store._spools.values()))
            failure = store.read_blob(spool.sealed["receipt"][1], limit=4096)
            assert b"SYNTHETIC_SECRET" not in failure
        with pytest.raises(StorePause, match="OPEN"):
            self.run_capture(transport)
        assert len(transport.calls) == 1

    # A failed fake call keeps charged unknown work and never invents an empty response.
    def test_transport_failure_retains_uncertainty_without_retry(self):
        transport = FakeTransport(self.stores, [OSError("SYNTHETIC transport failure")])
        with pytest.raises(StorePause, match="retained charges"):
            self.run_capture(transport)
        assert len(transport.calls) == 1
        assert transport.reads == []
        assert all(
            store.snapshot()["unresolved"] == {"get_attempts": 1, "body_bytes": 256}
            for store in self.stores
        )
        with pytest.raises(StorePause, match="OPEN"):
            self.run_capture(transport)
        assert len(transport.calls) == 1

    # A failed reader property still requires cleanup of the owned response.
    def test_reader_property_failure_closes_owned_response(self):
        transport = FakeTransport(self.stores, [{"read_property_failure": True}])
        with pytest.raises(StorePause):
            self.run_capture(transport)
        assert len(transport.calls) == 1
        assert transport.responses[0].closed

    # Failed cleanup cannot leave RETAINED pages that a later capture auto-finalizes.
    def test_failed_close_stays_uncertain_on_fresh_resume(self):
        # Fail cleanup only, without making any other external call.
        def failed_close():
            raise OSError("SYNTHETIC close failure")

        transport = FakeTransport(
            self.stores, [{"body": body(), "close_hook": failed_close}]
        )
        with pytest.raises(StorePause, match="close failed"):
            self.run_capture(transport)
        heads = [store.snapshot()["head"] for store in self.stores]
        for store in self.stores:
            store.close()
        stores = tuple(
            Store(self.root / "initial" / side, sha("identity"), head)
            for side, head in zip(("left", "right"), heads, strict=True)
        )
        self.all_stores.extend(stores)
        raw, pin = permit(stores, self.declared, self.reviewed)
        fresh = FakeTransport(stores)
        with pytest.raises(StorePause, match="OPEN"):
            acquisition.capture(
                stores,
                self.declared,
                self.reviewed,
                permit_raw=raw,
                expected_permit_sha256=pin,
                transport=fresh,
            )
        assert fresh.calls == []

    # Overflow and short reads cannot be relabelled complete or missing observations.
    def test_overflow_and_short_non_eof_read_pause(self):
        for label, spec, cap in (
            ("overflow", {"body": b"x" * 9}, 8),
            ("short", {"body": body(), "short": 8}, 64),
        ):
            stores, declared, reviewed = pair(self.root / label)
            self.all_stores.extend(stores)
            raw, pin = permit(stores, declared, reviewed, page_body_cap=cap)
            transport = FakeTransport(stores, [spec])
            with pytest.raises(StorePause):
                acquisition.capture(
                    stores,
                    declared,
                    reviewed,
                    permit_raw=raw,
                    expected_permit_sha256=pin,
                    transport=transport,
                )
            assert transport.responses[0].closed
            assert all(
                store.snapshot()["next_stage"] == "PACKETS_FINALIZED"
                for store in stores
            )
            assert len(transport.calls) == 1

    # Repeated continuation tokens remain a failed page rather than an implicit retry.
    def test_repeated_token_and_empty_body_do_not_finalize(self):
        for label, script in (
            ("repeat", [{"body": body("same")}, {"body": body("same")}]),
            ("empty", [{"body": b""}]),
        ):
            stores, declared, reviewed = pair(self.root / label)
            self.all_stores.extend(stores)
            raw, pin = permit(stores, declared, reviewed)
            transport = FakeTransport(stores, script)
            with pytest.raises(StorePause, match="FAILED"):
                acquisition.capture(
                    stores,
                    declared,
                    reviewed,
                    permit_raw=raw,
                    expected_permit_sha256=pin,
                    transport=transport,
                )
            assert all(
                store.snapshot()["next_stage"] == "PACKETS_FINALIZED"
                for store in stores
            )
            assert all(reply.closed for reply in transport.responses)

    # Callbacks cannot replace detached inputs or cached transport methods.
    def test_callback_mutation_does_not_change_owned_inputs_or_headers(self):
        declared = demand.Demand(self.declared.raw, self.declared.sha256)
        reviewed = registry.Registry(
            self.reviewed.raw, self.reviewed.sha256, self.reviewed.evidence
        )

        # Refuse any second lookup of a callback that was replaced after admission.
        def forbidden(request):
            raise AssertionError("Mutable callback was looked up again")

        # Change only caller-owned fixture objects after the coordinator detached them.
        def mutate(transport, request):
            object.__setattr__(self.declared, "raw", b"SYNTHETIC MUTATED")
            object.__setattr__(self.reviewed, "raw", b"SYNTHETIC MUTATED")
            transport.get, transport.hook = forbidden, None

        transport = FakeTransport(
            self.stores,
            [{"body": body("next"), "mutate_headers": True}, {"body": body()}],
            mutate,
        )
        ref = self.run_capture(transport)
        packet = acquisition.load(ref, self.stores, declared, reviewed)
        assert len(transport.calls) == 2
        assert (
            parser.read(packet, declared, reviewed)["acquisition_authorized"] is False
        )

    # Unreviewed mappings and nonfake transports refuse without a request reservation.
    def test_unresolved_registry_and_real_transport_marker_refuse(self):
        transport = FakeTransport(self.stores)
        transport.synthetic_only = False
        with pytest.raises(StorePause, match="fake-only"):
            self.run_capture(transport)
        altered = json.loads(self.reviewed.raw)
        altered["entries"][0].update(
            status="REQUEST_NAME_ONLY", review_sha256=None, assumption=None
        )
        raw = demand.encoded(altered)
        reviewed = registry.registry(
            raw, hashlib.sha256(raw).hexdigest(), dict(self.reviewed.evidence)
        )
        permit_raw, pin = permit(self.stores, self.declared, reviewed)
        transport.synthetic_only = True
        with pytest.raises(ValueError, match="Unresolved"):
            acquisition.capture(
                self.stores,
                self.declared,
                reviewed,
                permit_raw=permit_raw,
                expected_permit_sha256=pin,
                transport=transport,
            )
        assert transport.calls == []
        assert all(
            store.snapshot()["used"]["get_attempts"] == 0 for store in self.stores
        )

    # Future/recent windows fail the shared free-SIP clock guard before fake transport.
    def test_recent_window_refuses_before_fake_transport(self):
        now = datetime.now(UTC)
        future = now.replace(
            minute=(now.minute // 15) * 15, second=0, microsecond=0
        ) + timedelta(minutes=15)
        stores, declared, reviewed = pair(
            self.root / "future", when=future.isoformat().replace("+00:00", "Z")
        )
        self.all_stores.extend(stores)
        raw, pin = permit(stores, declared, reviewed)
        transport = FakeTransport(stores)
        with pytest.raises(StorePause):
            acquisition.capture(
                stores,
                declared,
                reviewed,
                permit_raw=raw,
                expected_permit_sha256=pin,
                transport=transport,
            )
        assert transport.calls == []

    # Apply the envelope cap before reloading complete retained page bodies.
    def test_aggregate_envelope_cap_precedes_body_reload(self):
        raw_body = body() + b" " * (6 * 1024**2 - len(body()))
        digest = hashlib.sha256(raw_body).hexdigest()
        armed = []

        # Start checking only after both original body receipts were retained.
        def retained(point):
            if point == "after_commit" and both_retained(self.stores):
                armed.append(True)

        original = Store.read_blob

        # Detect an oversized envelope rebuild before any additional body allocation.
        def read(store, sha, *, limit):
            if armed and sha == digest:
                raise AssertionError("Body reloaded before aggregate cap")
            return original(store, sha, limit=limit)

        self.stores[1].fault = retained
        transport = FakeTransport(self.stores, [{"body": raw_body}])
        with (
            patch.object(Store, "read_blob", read),
            pytest.raises(StorePause, match="Aggregate8MiB"),
        ):
            self.run_capture(transport, page_body_cap=6 * 1024**2)
        assert len(transport.calls) == 1

    # Actual rate reservations include all180 fake starts before the181st is refused.
    def test_real_store_rolling_rate_cap_in_composed_path(self):
        names = tuple("N" + str(index).zfill(2) for index in range(96))
        with patch.object(store_module, "_clock", Clock()):
            stores, declared, reviewed = pair(self.root / "rate", names, legs=True)
            self.all_stores.extend(stores)
            raw, pin = permit(stores, declared, reviewed)
            transport = FakeTransport(stores, repeated=True)
            with pytest.raises(StorePause, match="rate cap"):
                acquisition.capture(
                    stores,
                    declared,
                    reviewed,
                    permit_raw=raw,
                    expected_permit_sha256=pin,
                    transport=transport,
                )
            assert len(transport.calls) == 180
            assert all(
                store.snapshot()["used"]["get_attempts"] == 180 for store in stores
            )
            OBSERVATIONS.append(
                {
                    "kind": "SYNTHETIC_COMPOSED_RATE",
                    "fake_calls": 180,
                    "charged_gets_each": 180,
                    "clock": "EXPLICIT_FROZEN_FIXTURE_ONLY",
                }
            )

    # Real child crashes cannot repeat uncertain calls but can reuse complete pages.
    def test_sigkill_resumption_never_refetches_uncertain_or_retained_pages(self):
        context = multiprocessing.get_context("spawn")
        for boundary in ("before_transport", "transport_entered", "retained"):
            root = self.root / boundary
            parent, remote = context.Pipe()
            child = context.Process(target=capture_child, args=(root, remote, boundary))
            child.start()
            remote.close()
            assert parent.poll(30)
            observed = parent.recv()
            assert observed["point"] == boundary
            os.kill(child.pid, signal.SIGKILL)
            child.join(20)
            assert child.exitcode == -signal.SIGKILL
            parent.close()
            stores = tuple(
                Store(root / side, sha("identity"), head)
                for side, head in zip(("left", "right"), observed["heads"], strict=True)
            )
            self.all_stores.extend(stores)
            reviewed = reviewed_names(("AAPL",))
            row = stores[0].connection.execute("SELECT sha,raw FROM demands").fetchone()
            declared = demand.Demand(row["raw"], row["sha"])
            raw, pin = permit(stores, declared, reviewed)
            transport = FakeTransport(stores)
            if boundary == "retained":
                ref = acquisition.capture(
                    stores,
                    declared,
                    reviewed,
                    permit_raw=raw,
                    expected_permit_sha256=pin,
                    transport=transport,
                )
                acquisition.load(ref, stores, declared, reviewed)
            else:
                with pytest.raises(StorePause, match="OPEN"):
                    acquisition.capture(
                        stores,
                        declared,
                        reviewed,
                        permit_raw=raw,
                        expected_permit_sha256=pin,
                        transport=transport,
                    )
            assert transport.calls == []
            OBSERVATIONS.append(
                {
                    "kind": "SYNTHETIC_ACQUISITION_SIGKILL",
                    "boundary": boundary,
                    "child_exitcode": child.exitcode,
                    "resume_fake_calls": 0,
                }
            )


if __name__ == "__main__":
    unittest.main()
