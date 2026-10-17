"""Synthetic rate-slot fixtures; no transport, credentials or market calls."""

import json
import multiprocessing
import os
import signal
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_store as module
from backend.tests.test_historical_packet_store import (
    finish_cycle,
    mapping,
    paused,
    sha,
)

REAL_CLOCK = getattr(module, "_clock", None)
OBSERVATIONS = []


# Advance only synthetic fixture clocks without sleeping or changing host clocks.
class Clock:
    # Start a deterministic aware UTC and monotonic pair for private fixtures.
    def __init__(self):
        self.utc = datetime(2026, 10, 17, 18, tzinfo=UTC)
        self.monotonic = 100_000_000_000

    # Return the same clock domain shape as the production internal sampler.
    def __call__(self):
        return self.utc, self.monotonic

    # Move both fixture domains together by an exact number of microseconds.
    def advance(self, microseconds):
        self.utc += timedelta(microseconds=microseconds)
        self.monotonic += microseconds * 1000


# Retain a synthetic successful continuation so the next page is a valid request.
def retain(store, attempt, token="synthetic-next"):
    body = demand.encoded({"quotes": {"AAPL": []}, "next_page_token": token})
    store.reserve_read(attempt, sha(attempt + "read"), len(body))
    store.confirm_read(sha(attempt + "read"), body)
    store.finish_attempt(
        attempt,
        status=200,
        complete=True,
        failure=None,
        requested_at="SYNTHETIC",
        received_at="SYNTHETIC",
    )


# Stop a real child before or after its SQLite commit, never emulate a process crash.
def rate_child(root, head, query, demand_sha, connection, boundary, external):
    clock = Clock()
    clock.advance(61_000_000)
    try:
        with patch.object(module, "_clock", clock):
            store = module.Store(root, sha("identity"), head)
            clock.advance(60_000_000)

            # Block precisely at a durable boundary so the parent can send SIGKILL.
            def fault(point):
                if point == boundary:
                    connection.send(point)
                    connection.recv()

            store.fault = fault
            reservation = store.begin_attempt(
                attempt=sha("child request"),
                demand_sha256=demand_sha,
                query_sha256=query,
                page=0,
                token=None,
            )
            # Inspect actual committed rows before recording a synthetic external call.
            with sqlite3.connect(root / "state.sqlite") as observer:
                observed = observer.execute(
                    "SELECT reserved_utc_us,reserved_monotonic_ns FROM attempts"
                ).fetchone()
                state = json.loads(
                    observer.execute(
                        "SELECT raw FROM meta WHERE key='state'"
                    ).fetchone()[0]
                )
            assert observed == (
                reservation["reserved_utc_us"],
                reservation["reserved_monotonic_ns"],
            )
            assert state["used"]["get_attempts"] == 1
            external.write_text(
                json.dumps({"reservation": reservation, "row": observed})
            )
            connection.send("fake_external_after_durable_slot")
            store.close()
    finally:
        connection.close()


# Verify persisted pre-request rate accounting independently of any HTTP client.
class PacketRateTests(unittest.TestCase):
    # Create a private synthetic database and replace only its internal clock seam.
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="SYNTHETIC-packet-rate-")
        self.root = Path(self.temporary.name) / "store"
        self.clock = Clock()
        self.patcher = patch.object(module, "_clock", self.clock, create=True)
        self.patcher.start()
        self.store = module.Store(self.root, sha("identity"), None, create=True)
        self.value = paused(self.store, sha("cycle"), True)
        self.query = demand.read(self.value, mapping())["queries"][0]["sha256"]

    # Remove only this fixture's private files after closing its descriptors.
    def tearDown(self):
        self.store.close()
        self.patcher.stop()
        self.temporary.cleanup()

    # Reserve the exact next synthetic page without making an external call.
    def begin(self, page, token=None, label=None):
        return self.store.begin_attempt(
            attempt=sha(label or str(page)),
            demand_sha256=self.value.sha256,
            query_sha256=self.query,
            page=page,
            token=token,
        )

    # Complete whole synthetic cycles so every rate slot uses the real admission path.
    def completed(self, count):
        for index in range(count):
            attempt = sha("completed " + str(index))
            self.begin(0, label="completed " + str(index))
            retain(self.store, attempt, None)
            cycle = self.store.snapshot()["cycle"]
            self.store.append(
                expected_head=self.store.snapshot()["head"],
                cycle_sha256=cycle,
                stage="PACKETS_FINALIZED",
                receipt_sha256=sha(attempt + "packets"),
            )
            finish_cycle(self.store, cycle)
            self.value = paused(self.store, sha("following " + str(index)), True)
            self.query = demand.read(self.value, mapping())["queries"][0]["sha256"]

    # A new process owner cannot reset the rate window by immediately reopening.
    def test_restart_requires_quiet_period_without_resetting_charge(self):
        self.begin(0)
        retain(self.store, sha("0"))
        head = self.store.snapshot()["head"]
        self.store.close()
        self.store = module.Store(self.root, sha("identity"), head)
        with pytest.raises(module.StorePause, match="quiet"):
            self.begin(1, "synthetic-next")
        assert self.store.snapshot()["used"]["get_attempts"] == 1
        self.clock.advance(59_999_999)
        with pytest.raises(module.StorePause, match="quiet"):
            self.begin(1, "synthetic-next")
        self.clock.advance(1)
        self.begin(1, "synthetic-next")
        assert self.store.snapshot()["used"]["get_attempts"] == 2

    # Exactly180 starts fit one rolling minute and the boundary expires at60seconds.
    def test_rolling_180_and_exact_expiry(self):
        self.completed(180)
        before = self.store.snapshot()
        with pytest.raises(module.StorePause, match="rate cap"):
            self.begin(0, label="181")
        assert self.store.snapshot() == before
        self.clock.advance(59_999_999)
        with pytest.raises(module.StorePause, match="rate cap"):
            self.begin(0, label="181")
        self.clock.advance(1)
        receipt = self.begin(0, label="181")
        assert receipt["charged_get_attempts"] == 181
        assert receipt["acquisition_authorized"] is False

    # Neither unresolved nor known failed requests refund a rolling rate slot.
    def test_failed_and_uncertain_attempts_keep_slots(self):
        self.completed(179)
        self.begin(0, label="uncertain")
        with pytest.raises(module.StorePause, match="rate cap"):
            self.store._rate_slot(self.store.snapshot())
        self.store.finish_attempt(
            sha("uncertain"),
            status=503,
            complete=False,
            failure="SYNTHETIC",
            requested_at="SYNTHETIC",
            received_at="SYNTHETIC",
        )
        with pytest.raises(module.StorePause, match="rate cap"):
            self.store._rate_slot(self.store.snapshot())
        assert self.store.snapshot()["used"]["get_attempts"] == 180
        assert self.store.snapshot()["unresolved"]["get_attempts"] == 0

    # A forward UTC correction cannot reset this process's monotonic rolling window.
    def test_forward_wall_clock_does_not_reset_rate(self):
        self.completed(180)
        self.clock.utc += timedelta(minutes=2)
        with pytest.raises(module.StorePause, match="rate cap"):
            self.begin(0, label="forward clock")
        assert self.store.snapshot()["used"]["get_attempts"] == 180

    # Reversed UTC or monotonic domains are refused before a second charge.
    def test_clock_reversals_do_not_charge(self):
        self.begin(0)
        retain(self.store, sha("0"))
        original = self.clock()
        for domain in ("utc", "monotonic"):
            with self.subTest(domain=domain):
                self.clock.utc, self.clock.monotonic = original
                if domain == "utc":
                    self.clock.utc -= timedelta(microseconds=1)
                else:
                    self.clock.monotonic -= 1
                with pytest.raises(module.StorePause, match="reversal"):
                    self.begin(1, "synthetic-next")
                assert self.store.snapshot()["used"]["get_attempts"] == 1
        self.clock.utc, self.clock.monotonic = original

    # Resume rejects a UTC clock older than the original durable reservation.
    def test_resume_rejects_utc_reversal(self):
        self.begin(0)
        head = self.store.snapshot()["head"]
        self.store.close()
        self.clock.utc -= timedelta(microseconds=1)
        with pytest.raises(module.StorePause, match="reversal"):
            module.Store(self.root, sha("identity"), head)

    # Naive, nonUTC and noninteger monotonic metadata cannot become actual slots.
    def test_clock_shapes_are_strict(self):
        from datetime import timezone

        invalid = (
            (datetime(2026, 10, 17), 1),
            (datetime(2026, 10, 17, tzinfo=timezone(timedelta(hours=1))), 1),
            (self.clock.utc, True),
            (self.clock.utc, -1),
            (self.clock.utc, 2**63),
        )
        for value in invalid:
            with (
                self.subTest(value=str(value)),
                patch.object(module, "_clock", return_value=value),
                pytest.raises(module.StorePause, match="clock"),
            ):
                self.begin(0)
        assert self.store.snapshot()["used"]["get_attempts"] == 0

    # The default source samples actual aware UTC without a launch-clock argument.
    def test_default_clock_is_actual_aware_utc(self):
        before = datetime.now(UTC)
        utc, monotonic = REAL_CLOCK()
        after = datetime.now(UTC)
        assert before <= utc <= after
        assert utc.tzinfo is UTC
        assert type(monotonic) is int
        assert monotonic > 0
        module._clock_values((utc, monotonic))

    # Existing records without the required clock columns pause without migration.
    def test_missing_rate_schema_is_not_repaired(self):
        head = self.store.snapshot()["head"]
        self.store.close()
        with sqlite3.connect(self.root / "state.sqlite") as connection:
            connection.execute("ALTER TABLE attempts DROP COLUMN reserved_utc_us")
        before = (self.root / "state.sqlite").read_bytes()
        with pytest.raises(module.StorePause, match="schema"):
            module.Store(self.root, sha("identity"), head)
        assert (self.root / "state.sqlite").read_bytes() == before

    # Removing a recent reservation cannot silently create new quota capacity.
    def test_missing_recent_slot_is_rejected(self):
        self.completed(2)
        self.store.connection.execute("DELETE FROM attempts WHERE rowid=1")
        with pytest.raises(module.StorePause, match="slots missing"):
            self.begin(0, label="replacement")

    # Real child execution sees a committed slot before any fake external side effect.
    def test_child_external_observes_durable_slot(self):
        head = self.store.snapshot()["head"]
        self.store.close()
        context = multiprocessing.get_context("spawn")
        parent, remote = context.Pipe()
        external = self.root.parent / "SYNTHETIC-external.json"
        process = context.Process(
            target=rate_child,
            args=(
                self.root,
                head,
                self.query,
                self.value.sha256,
                remote,
                None,
                external,
            ),
        )
        process.start()
        remote.close()
        assert parent.poll(20)
        assert parent.recv() == "fake_external_after_durable_slot"
        process.join(20)
        assert process.exitcode == 0
        proof = json.loads(external.read_text())
        assert proof["reservation"]["charged_get_attempts"] == 1
        assert proof["row"][0] == proof["reservation"]["reserved_utc_us"]
        OBSERVATIONS.append({"kind": "SYNTHETIC_FAKE_EXTERNAL_AFTER_COMMIT", **proof})
        parent.close()

    # SIGKILL before commit rolls back; after commit retains quota without any call.
    def test_sigkill_rate_commit_and_external_boundaries(self):
        head = self.store.snapshot()["head"]
        self.store.close()
        context = multiprocessing.get_context("spawn")
        for boundary, charged in (("before_commit", 0), ("rate_reserved", 1)):
            with self.subTest(boundary=boundary):
                parent, remote = context.Pipe()
                external = self.root.parent / (boundary + "-external.json")
                process = context.Process(
                    target=rate_child,
                    args=(
                        self.root,
                        head,
                        self.query,
                        self.value.sha256,
                        remote,
                        boundary,
                        external,
                    ),
                )
                process.start()
                remote.close()
                assert parent.poll(20)
                assert parent.recv() == boundary
                os.kill(process.pid, signal.SIGKILL)
                process.join(20)
                assert process.exitcode == -signal.SIGKILL
                assert not external.exists()
                parent.close()
                self.clock.advance(121_000_000)
                self.store = module.Store(self.root, sha("identity"), head)
                assert self.store.snapshot()["used"]["get_attempts"] == charged
                with sqlite3.connect(self.root / "state.sqlite") as observer:
                    assert (
                        observer.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
                        == charged
                    )
                OBSERVATIONS.append(
                    {
                        "kind": "SYNTHETIC_SIGKILL",
                        "boundary": boundary,
                        "child_exitcode": process.exitcode,
                        "durable_get_slots": charged,
                        "fake_external_occurred": external.exists(),
                    }
                )
                if charged:
                    with pytest.raises(module.StorePause, match="quiet"):
                        self.store._rate_slot(self.store.snapshot())
                self.store.close()


if __name__ == "__main__":
    unittest.main()
