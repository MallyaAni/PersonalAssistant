"""Real private filesystem/process fixtures; all receipts and bodies are synthetic."""

import hashlib
import io
import json
import multiprocessing
import os
import signal
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

import pytest

from backend.market import historical_packet_checkpoint as checkpoint
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_registry as registry
from backend.market.historical_packet_store import Store, StorePause


# Give every synthetic fixture artifact a deterministic content identity.
def sha(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


# Build explicit synthetic conditional mapping, never a provider identity claim.
def mapping():
    evidence = b"SYNTHETIC request metadata only"
    review = b"SYNTHETIC conditional mapping review"
    evidence_sha = hashlib.sha256(evidence).hexdigest()
    review_sha = hashlib.sha256(review).hexdigest()
    raw = demand.encoded(
        {
            "schema": "historical-entity-registry/1",
            "entries": [
                {
                    "cohort_key": "AAPL",
                    "query_symbol": "AAPL",
                    "entity_asof": "2026-10-12",
                    "status": "REVIEWED_CONDITIONAL_MAPPING",
                    "issuer_identity": None,
                    "assumption": "Synthetic fixture only",
                    "review_sha256": review_sha,
                    "sources": [
                        {
                            "kind": "request_metadata",
                            "sha256": evidence_sha,
                            "source_label": "synthetic",
                        }
                    ],
                }
            ],
        }
    )
    return registry.registry(
        raw,
        hashlib.sha256(raw).hexdigest(),
        {evidence_sha: evidence, review_sha: review},
    )


# Start one causal cycle with authentic pure demand validation over fake inputs.
def paused(store, cycle, held=False):
    first = store.append(
        expected_head=store.snapshot()["head"],
        cycle_sha256=cycle,
        stage="PRIOR_VERIFIED",
        receipt_sha256=sha(cycle + "prior"),
    )
    value = demand.build(
        mapping(),
        identity_sha256=store.identity,
        parent_sha256=first["sha256"],
        completed_at="2019-03-01T14:45:00Z",
        prior={key: sha("SYNTHETIC " + key) for key in demand.PRIOR},
        held=["AAPL"] if held else [],
        legs=[],
        used=store.snapshot()["used"],
    )
    store.declare(value, mapping())
    store.append(
        expected_head=first["sha256"],
        cycle_sha256=cycle,
        stage="DEMAND_FROZEN",
        receipt_sha256=value.sha256,
    )
    store.append(
        expected_head=store.snapshot()["head"],
        cycle_sha256=cycle,
        stage="WAIT_PACKETS",
        receipt_sha256=sha(cycle + "wait"),
    )
    return value


# Reach the next decision stage only after every required page is finalized.
def ready(store, cycle):
    paused(store, cycle)
    return store.append(
        expected_head=store.snapshot()["head"],
        cycle_sha256=cycle,
        stage="PACKETS_FINALIZED",
        receipt_sha256=sha(cycle + "packet"),
    )


# Complete synthetic reserved stages without calling any decision or sender.
def finish_cycle(store, cycle):
    for stage in ("DECISION_FROZEN", "SUBMISSION_CAPTURED"):
        operation = sha(cycle + stage)
        store.reserve_operation(
            operation=operation,
            expected_head=store.snapshot()["head"],
            cycle=cycle,
            stage=stage,
            inputs=sha("synthetic inputs"),
        )
        store.complete_operation(operation, sha(cycle + stage + "receipt"))
    return store.append(
        expected_head=store.snapshot()["head"],
        cycle_sha256=cycle,
        stage="OUTCOME_COMMITTED",
        receipt_sha256=sha(cycle + "outcome"),
    )


# Stop at a real process boundary so the parent can kill the active writer.
def blocked(connection, name):
    connection.send(name)
    connection.recv()


# Build a test-only callback for one selected process-crash boundary.
def crash_hook(connection, boundary):
    # Report a real crash point for the parent to kill, never emulate persistence.
    def fault(point):
        if point == boundary:
            blocked(connection, point)

    return fault


# Perform one competing append or stop at an injected durability boundary.
def child(root, expected, connection, mode, boundary=None):
    try:
        store = Store(root, sha("identity"), expected)
        store.fault = crash_hook(
            connection, boundary if mode != "operation_commit" else None
        )
        if mode == "append":
            entry = store.append(
                expected_head=expected,
                cycle_sha256=sha("child cycle"),
                stage="PRIOR_VERIFIED",
                receipt_sha256=sha(os.getpid()),
            )
            connection.send(("committed", entry["sha256"]))
        elif mode == "operation":
            store.reserve_operation(
                operation=sha("uncertain"),
                expected_head=expected,
                cycle=sha("cycle"),
                stage=store.snapshot()["next_stage"],
                inputs=sha("inputs"),
            )
            blocked(connection, "reserved_operation")
        elif mode == "operation_commit":
            store.reserve_operation(
                operation=sha("committed-operation"),
                expected_head=expected,
                cycle=sha("cycle"),
                stage="DECISION_FROZEN",
                inputs=sha("inputs"),
            )
            store.fault = crash_hook(connection, boundary)
            store.complete_operation(sha("committed-operation"), sha("original"))
        elif mode == "attempt":
            value = store.connection.execute("SELECT sha,raw FROM demands").fetchone()
            data = demand.encoded({}) if value is None else value["raw"]
            query = json.loads(data)["queries"][0]["sha256"]
            store.begin_attempt(
                attempt=sha("attempt"),
                demand_sha256=value["sha"],
                query_sha256=query,
                page=0,
                token=None,
            )
            store.reserve_read(sha("attempt"), sha("read"), 64)
            blocked(connection, "reserved_read")
        elif mode == "blob":
            store.put_stream(io.BytesIO(b"SYNTHETIC body"), limit=64)
        store.close()
    except (ValueError, OSError, sqlite3.Error) as error:
        connection.send(("refused", type(error).__name__))
    finally:
        connection.close()


# Count every requested allocation while supplying a deliberately oversized stream.
class BoundedReader:
    # Initialize a synthetic stream without allocating its declared full length.
    def __init__(self):
        self.requests = []

    # Return exactly the bounded requested bytes and retain allocation evidence.
    def read(self, count):
        self.requests.append(count)
        return b"x" * count


# Exercise private durability, bounded counters and real multiprocess crashes.
class PacketStoreTests(unittest.TestCase):
    # Create a unique private root; no original account or run path is read.
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="SYNTHETIC-packet-store-")
        self.root = Path(self.temporary.name) / "store"
        self.store = Store(self.root, sha("identity"), None, create=True)

    # Close private descriptors and remove only this fixture's temporary files.
    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    # Kill an actually blocked child process and require a genuine SIGKILL exit.
    def kill_at(self, mode, boundary=None):
        head = self.store.snapshot()["head"]
        self.store.close()
        context = multiprocessing.get_context("spawn")
        parent, remote = context.Pipe()
        process = context.Process(
            target=child, args=(self.root, head, remote, mode, boundary)
        )
        process.start()
        remote.close()
        assert parent.poll(20), "child failed before expected crash boundary"
        observed = parent.recv()
        assert observed == (
            boundary
            or {"operation": "reserved_operation", "attempt": "reserved_read"}[mode]
        )
        for path in self.root.rglob("*"):
            assert stat.S_IMODE(path.stat().st_mode) == (448 if path.is_dir() else 384)
        os.kill(process.pid, signal.SIGKILL)
        process.join(20)
        assert process.exitcode == -signal.SIGKILL
        parent.close()
        return head

    # Two process writers cannot publish competing descendants of the same head.
    def test_multiprocess_competing_descendants(self):
        self.store.close()
        context = multiprocessing.get_context("spawn")
        handles = []
        for _ in range(2):
            parent, remote = context.Pipe()
            process = context.Process(
                target=child, args=(self.root, None, remote, "append")
            )
            process.start()
            remote.close()
            handles.append((parent, process))
        results = []
        for pipe, process in handles:
            assert pipe.poll(20)
            results.append(pipe.recv())
            process.join(20)
            assert process.exitcode == 0
            pipe.close()
        assert sum(row[0] == "committed" for row in results) == 1
        winner = next(row[1] for row in results if row[0] == "committed")
        self.store = Store(self.root, sha("identity"), winner)
        assert self.store.audit(winner)["entries"] == 1

    # Death before commit leaves the old head while death afterward retains the new one.
    def test_sigkill_commit_boundaries(self):
        old = self.kill_at("append", "before_commit")
        self.store = Store(self.root, sha("identity"), old)
        assert self.store.snapshot()["head"] is None
        self.kill_at("append", "after_commit")
        connection = sqlite3.connect(self.root / "state.sqlite")
        new = json.loads(
            connection.execute("SELECT raw FROM meta WHERE key='state'").fetchone()[0]
        )["head"]
        connection.close()
        assert new != old
        self.store = Store(self.root, sha("identity"), new)
        assert self.store.audit(new)["entries"] == 1

    # Durable orphan body bytes never create an authoritative checkpoint reference.
    def test_sigkill_blob_publication_boundaries(self):
        for boundary in ("blob_fsynced", "blob_linked"):
            with self.subTest(boundary=boundary):
                self.kill_at("blob", boundary)
                self.store = Store(self.root, sha("identity"), None)
                assert self.store.snapshot()["head"] is None
                assert self.store.snapshot()["sequence"] == 0
        assert list((self.root / "blobs").iterdir())

    # Interrupted external reservations cannot be executed or completed on restart.
    def test_sigkill_operation_is_uncertain_not_repeated(self):
        ready(self.store, sha("cycle"))
        head = self.kill_at("operation")
        self.store = Store(self.root, sha("identity"), head)
        with pytest.raises(StorePause):
            self.store.complete_operation(sha("uncertain"), sha("invented receipt"))
        with pytest.raises((StorePause, sqlite3.IntegrityError)):
            self.store.reserve_operation(
                operation=sha("second"),
                expected_head=head,
                cycle=sha("cycle"),
                stage="DECISION_FROZEN",
                inputs=sha("inputs"),
            )
        assert self.store.snapshot()["head"] == head

    # A committed receipt survives a crash before the caller receives its result.
    def test_sigkill_completed_operation_recovers_original_only(self):
        ready(self.store, sha("cycle"))
        self.kill_at("operation_commit", "after_commit")
        connection = sqlite3.connect(self.root / "state.sqlite")
        head = json.loads(
            connection.execute("SELECT raw FROM meta WHERE key='state'").fetchone()[0]
        )["head"]
        connection.close()
        self.store = Store(self.root, sha("identity"), head)
        recovered = self.store.recover_operation(sha("committed-operation"))
        assert recovered["receipt_sha256"] == sha("original")
        assert self.store.snapshot()["sequence"] == 5

    # Interrupted native-submission reservations remain paused just like decisions.
    def test_sigkill_submission_reservation_never_repeats(self):
        ready(self.store, sha("cycle"))
        self.store.reserve_operation(
            operation=sha("decision"),
            expected_head=self.store.snapshot()["head"],
            cycle=sha("cycle"),
            stage="DECISION_FROZEN",
            inputs=sha("inputs"),
        )
        self.store.complete_operation(sha("decision"), sha("decision-receipt"))
        head = self.kill_at("operation")
        self.store = Store(self.root, sha("identity"), head)
        with pytest.raises(StorePause):
            self.store.complete_operation(sha("uncertain"), sha("invented acceptance"))

    # Interrupted HTTP/read reservations preserve conservative charge and unknown bytes.
    def test_sigkill_acquisition_charge_survives(self):
        value = paused(self.store, sha("cycle"), True)
        head = self.kill_at("attempt")
        self.store = Store(self.root, sha("identity"), head)
        snapshot = self.store.snapshot()
        assert snapshot["used"] == {"get_attempts": 1, "body_bytes": 64}
        assert snapshot["confirmed_bytes"] == 0
        assert snapshot["unresolved"] == {"get_attempts": 1, "body_bytes": 64}
        with pytest.raises(StorePause):
            self.store.confirm_read(sha("read"), b"guessed")
        query = demand.read(value, mapping())["queries"][0]["sha256"]
        with pytest.raises(StorePause):
            self.store.begin_attempt(
                attempt=sha("refetch"),
                demand_sha256=value.sha256,
                query_sha256=query,
                page=0,
                token=None,
            )

    # Failed HTTP evidence retains bytes/charges without becoming a completed packet.
    def test_failed_http_and_partial_body_preserve_budget(self):
        value = paused(self.store, sha("cycle"), True)
        query = demand.read(value, mapping())["queries"][0]["sha256"]
        self.store.begin_attempt(
            attempt=sha("attempt"),
            demand_sha256=value.sha256,
            query_sha256=query,
            page=0,
            token=None,
        )
        self.store.reserve_read(sha("attempt"), sha("chunk"), 64)
        self.store.confirm_read(sha("chunk"), b"SYNTHETIC failed body")
        result = self.store.finish_attempt(
            sha("attempt"),
            status=503,
            complete=False,
            failure="SYNTHETIC HTTP failure",
            requested_at="synthetic",
            received_at="synthetic",
        )
        assert result["market_packet_validation"] == "NOT_PERFORMED"
        snapshot = self.store.snapshot()
        assert snapshot["used"] == {"get_attempts": 1, "body_bytes": 64}
        assert snapshot["confirmed_bytes"] == len(b"SYNTHETIC failed body")
        assert snapshot["unresolved"] == {"get_attempts": 0, "body_bytes": 0}
        with pytest.raises(StorePause):
            self.store.page_manifest(value.sha256, query)
        with pytest.raises(StorePause):
            self.store.append(
                expected_head=snapshot["head"],
                cycle_sha256=sha("cycle"),
                stage="PACKETS_FINALIZED",
                receipt_sha256=sha("not ready"),
            )

    # Retained short pages require exact complete continuation before stage progress.
    def test_exact_page_tokens_and_complete_manifest(self):
        value = paused(self.store, sha("cycle"), True)
        query = demand.read(value, mapping())["queries"][0]["sha256"]
        for index, token in enumerate((None, "synthetic-next")):
            attempt = sha(index)
            body = demand.encoded(
                {
                    "quotes": {"AAPL": []},
                    "next_page_token": "synthetic-next" if index == 0 else None,
                }
            )
            self.store.begin_attempt(
                attempt=attempt,
                demand_sha256=value.sha256,
                query_sha256=query,
                page=index,
                token=token,
            )
            self.store.reserve_read(attempt, sha("read" + str(index)), len(body))
            self.store.confirm_read(sha("read" + str(index)), body)
            self.store.finish_attempt(
                attempt,
                status=200,
                complete=True,
                failure=None,
                requested_at="synthetic",
                received_at="synthetic",
            )
            if index == 0:
                with pytest.raises(StorePause):
                    self.store.page_manifest(value.sha256, query)
                with pytest.raises(StorePause):
                    self.store.begin_attempt(
                        attempt=sha("wrong"),
                        demand_sha256=value.sha256,
                        query_sha256=query,
                        page=1,
                        token="wrong",
                    )
        pages = self.store.page_manifest(value.sha256, query)
        assert len(pages) == 2
        self.store.append(
            expected_head=self.store.snapshot()["head"],
            cycle_sha256=sha("cycle"),
            stage="PACKETS_FINALIZED",
            receipt_sha256=sha("externally validated receipt"),
        )
        assert self.store.snapshot()["next_stage"] == "DECISION_FROZEN"

    # A complete committed operation can be recovered without repeating or appending it.
    def test_committed_operation_recovery_and_same_identity_resume(self):
        ready(self.store, sha("cycle"))
        self.store.reserve_operation(
            operation=sha("once"),
            expected_head=self.store.snapshot()["head"],
            cycle=sha("cycle"),
            stage="DECISION_FROZEN",
            inputs=sha("inputs"),
        )
        entry = self.store.complete_operation(sha("once"), sha("original receipt"))
        self.store.close()
        self.store = Store(self.root, sha("identity"), entry["sha256"])
        assert self.store.recover_operation(sha("once")) == entry
        assert self.store.snapshot()["sequence"] == 5
        with pytest.raises(StorePause):
            self.store.complete_operation(sha("once"), sha("replacement"))

    # Wrong identities and stale heads fail without rewriting the valid store.
    def test_wrong_identity_stale_head_and_repeat_reject(self):
        entry = self.store.append(
            expected_head=None,
            cycle_sha256=sha("cycle"),
            stage="PRIOR_VERIFIED",
            receipt_sha256=sha("prior"),
        )
        with pytest.raises(StorePause):
            self.store.append(
                expected_head=None,
                cycle_sha256=sha("fork"),
                stage="PRIOR_VERIFIED",
                receipt_sha256=sha("fork receipt"),
            )
        self.store.close()
        before = (self.root / "state.sqlite").read_bytes()
        with pytest.raises(StorePause):
            Store(self.root, sha("wrong identity"), entry["sha256"])
        with pytest.raises(StorePause):
            Store(self.root, sha("identity"), None)
        assert (self.root / "state.sqlite").read_bytes() == before
        self.store = Store(self.root, sha("identity"), entry["sha256"])

    # A damaged index/receipt schema must not be silently rebuilt on resume.
    def test_missing_cycle_table_refuses_instead_of_repairing(self):
        self.store.close()
        connection = sqlite3.connect(self.root / "state.sqlite")
        connection.execute("DROP TABLE cycles")
        connection.commit()
        connection.close()
        with pytest.raises((StorePause, sqlite3.Error)):
            Store(self.root, sha("identity"), None)

    # Missing lookup indexes cannot silently turn future appends into table scans.
    def test_missing_index_and_changed_head_summary_refuse(self):
        self.store.connection.execute("DROP INDEX entry_cycle")
        self.store.close()
        with pytest.raises(StorePause):
            Store(self.root, sha("identity"), None)

    # Global cap failures roll back while partial-read reservations remain charged.
    def test_group_and_global_budget_pause_without_refund(self):
        value = paused(self.store, sha("cycle"), True)
        query = demand.read(value, mapping())["queries"][0]["sha256"]
        self.store.begin_attempt(
            attempt=sha("attempt"),
            demand_sha256=value.sha256,
            query_sha256=query,
            page=0,
            token=None,
        )
        for index in range(320):
            self.store.reserve_read(sha("attempt"), sha(index), 65536)
        before = self.store.snapshot()
        with pytest.raises(StorePause):
            self.store.reserve_read(sha("attempt"), sha("over cap"), 1)
        assert self.store.snapshot() == before
        assert before["unresolved"]["body_bytes"] == demand.BUDGET["bytes_per_group"]
        # This synthetic near-cap state avoids250000 fake request authorizations.
        cap_store = Store(
            self.root.parent / "global-cap", sha("identity"), None, create=True
        )
        try:
            with cap_store._transaction():
                state = cap_store._state()
                state["used"]["get_attempts"] = demand.BUDGET["get_attempts"]
                cap_store._write_state(state)
            cap_value = paused(cap_store, sha("cap cycle"), True)
            cap_query = demand.read(cap_value, mapping())["queries"][0]["sha256"]
            before = cap_store.snapshot()
            with pytest.raises(ValueError, match="cap"):
                cap_store.begin_attempt(
                    attempt=sha("over global"),
                    demand_sha256=cap_value.sha256,
                    query_sha256=cap_query,
                    page=0,
                    token=None,
                )
            assert cap_store.snapshot() == before
        finally:
            cap_store.close()

    # A corrupted next-stage summary cannot change the authenticated head transition.
    def test_corrupt_head_summary_refuses(self):
        entry = self.store.append(
            expected_head=None,
            cycle_sha256=sha("cycle"),
            stage="PRIOR_VERIFIED",
            receipt_sha256=sha("prior"),
        )
        self.store.close()
        connection = sqlite3.connect(self.root / "state.sqlite")
        state = json.loads(
            connection.execute("SELECT raw FROM meta WHERE key='state'").fetchone()[0]
        )
        state["index"] = 4
        connection.execute(
            "UPDATE meta SET raw=? WHERE key='state'", (demand.encoded(state),)
        )
        connection.commit()
        connection.close()
        with pytest.raises(StorePause):
            Store(self.root, sha("identity"), entry["sha256"])

    # Empty/malformed successful bodies are retained failures, never missing data.
    def test_empty_successful_body_is_retained_but_not_market_evidence(self):
        value = paused(self.store, sha("cycle"), True)
        query = demand.read(value, mapping())["queries"][0]["sha256"]
        self.store.begin_attempt(
            attempt=sha("empty"),
            demand_sha256=value.sha256,
            query_sha256=query,
            page=0,
            token=None,
        )
        self.store.reserve_read(sha("empty"), sha("empty read"), 16)
        self.store.confirm_read(sha("empty read"), b"")
        receipt = self.store.finish_attempt(
            sha("empty"),
            status=200,
            complete=True,
            failure=None,
            requested_at="SYNTHETIC",
            received_at="SYNTHETIC",
        )
        assert receipt["body_validation_failure"] == "INVALID_OR_REPEATED_SOURCE_BODY"
        assert receipt["failure"] is None
        assert self.store.read_blob(receipt["body_sha256"], limit=16) == b""
        with pytest.raises(StorePause):
            self.store.page_manifest(value.sha256, query)

    # Direct appends cannot bypass decision/submission reservations.
    def test_direct_decision_append_and_unsafe_blob_link_refuse(self):
        ready(self.store, sha("cycle"))
        with pytest.raises(StorePause):
            self.store.append(
                expected_head=self.store.snapshot()["head"],
                cycle_sha256=sha("cycle"),
                stage="DECISION_FROZEN",
                receipt_sha256=sha("unreserved"),
            )
        body, _ = self.store.put_stream(io.BytesIO(b"original"), limit=64)
        (self.root / "blobs" / body).unlink()
        (self.root / "blobs" / body).symlink_to(self.root / "state.sqlite")
        with pytest.raises(OSError, match="symbolic links"):
            self.store.read_blob(body, limit=64)

    # Indexed appends perform a bounded number of statements at larger history lengths.
    def test_indexed_append_does_not_rescan_prior_chain(self):
        for index in range(30):
            cycle = sha(index)
            ready(self.store, cycle)
            finish_cycle(self.store, cycle)
        statements = []
        self.store.connection.set_trace_callback(statements.append)
        head = self.store.snapshot()["head"]
        self.store.append(
            expected_head=head,
            cycle_sha256=sha("next cycle"),
            stage="PRIOR_VERIFIED",
            receipt_sha256=sha("next receipt"),
        )
        self.store.connection.set_trace_callback(None)
        assert len(statements) <= 10
        assert not any("SELECT * FROM entries" in sql for sql in statements)
        plan = self.store.connection.execute(
            "EXPLAIN QUERY PLAN SELECT 1 FROM cycles WHERE sha=?", (sha(0),)
        ).fetchall()
        assert any("INDEX" in row[3] for row in plan)

    # Enforce private modes, original bytes and bounded preallocation reads.
    def test_private_modes_corruption_and_bounded_reads(self):
        body, _ = self.store.put_stream(io.BytesIO(b"original"), limit=64)
        for path in self.root.rglob("*"):
            assert stat.S_IMODE(path.stat().st_mode) == (448 if path.is_dir() else 384)
        reader = BoundedReader()
        with pytest.raises(StorePause):
            self.store.put_stream(reader, limit=128)
        assert sum(reader.requests) == 129
        with pytest.raises(StorePause):
            self.store.read_blob(body, limit=2)
        (self.root / "blobs" / body).write_bytes(b"corrupt")
        with pytest.raises(StorePause):
            self.store.read_blob(body, limit=64)

    # Streaming audit matches the existing pure fold without using quadratic append.
    def test_streaming_audit_matches_pure_contract(self):
        for index in range(3):
            cycle = sha(index)
            ready(self.store, cycle)
            finish_cycle(self.store, cycle)
        chain = [
            json.loads(row[0])
            for row in self.store.connection.execute(
                "SELECT raw FROM entries ORDER BY sequence"
            )
        ]
        head = self.store.snapshot()["head"]
        pure = checkpoint.verify(
            chain, identity_sha256=sha("identity"), expected_head=head
        )
        assert self.store.audit(head)["next_stage"] == pure["next_stage"]
        with pytest.raises(ValueError, match="cannot be repeated"):
            self.store.append(
                expected_head=head,
                cycle_sha256=sha(0),
                stage="PRIOR_VERIFIED",
                receipt_sha256=sha("repeated cycle"),
            )

    # Valid SQLite edits cannot replace declared original query/window bytes.
    def test_mutated_declared_demand_refuses_before_attempt(self):
        value = paused(self.store, sha("cycle"), True)
        data = json.loads(value.raw)
        query = data["queries"][0]["sha256"]
        data["queries"][0]["parameters"]["end"] = "2099-01-01T00:00:00Z"
        self.store.connection.execute(
            "UPDATE demands SET raw=? WHERE sha=?", (demand.encoded(data), value.sha256)
        )
        with pytest.raises(StorePause):
            self.store.begin_attempt(
                attempt=sha("mutated"),
                demand_sha256=value.sha256,
                query_sha256=query,
                page=0,
                token=None,
            )

    # Deleting auxiliary cycle membership cannot authorize a completed-cycle replay.
    def test_deleted_cycle_membership_cannot_repeat_completed_cycle(self):
        cycle = sha("completed cycle")
        ready(self.store, cycle)
        finish_cycle(self.store, cycle)
        self.store.connection.execute("DELETE FROM cycles")
        with pytest.raises((ValueError, StorePause)):
            self.store.append(
                expected_head=self.store.snapshot()["head"],
                cycle_sha256=cycle,
                stage="PRIOR_VERIFIED",
                receipt_sha256=sha("replay"),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
