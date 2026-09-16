"""Prose beside the decision: saved after it, killed at the deadline, never in it.

What has to hold: a request that keeps producing bytes past the deadline
is terminated at the wall clock, the child's sockets go with it, the
decision stays saved and the prose block says it timed out; a blocked or
failing enrichment likewise leaves the record saved; what the child had
written before the kill is kept; a record reads back with its prose
merged and a status, and older records with embedded prose still read.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend.cli import market_daily
from backend.market import deskrecord, prose
from backend.tests.test_market_daily import _report


# A model server that never finishes: it acknowledges the request and then
# drips a byte every 50 ms for as long as the connection lives, so no
# inactivity timeout can end it. It records when the client goes away.
class _Drip(BaseHTTPRequestHandler):
    dropped = threading.Event()
    started = threading.Event()

    # Any POST is a model call: acknowledge it and never finish the body.
    def do_POST(self):  # noqa: N802 - http.server's name
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        _Drip.started.set()
        try:
            while True:
                self.wfile.write(b"1\r\nx\r\n")
                self.wfile.flush()
                time.sleep(0.05)
        except OSError:
            _Drip.dropped.set()

    # A GET (a model list or health probe) answers at once.
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    # Keep the test output free of request logging.
    def log_message(self, *args):
        pass


# The dripping server on a free local port, stopped after the test.
@pytest.fixture
def drip_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Drip)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Drip.dropped.clear()
    _Drip.started.clear()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


# The bound Codex asked for: a response that keeps sending bytes cannot
# outlive the wall-clock deadline, because the child holding it is killed.
# The elapsed bound allows the budget, two grace periods and process
# start-up on a slow machine.
def test_a_request_that_keeps_producing_bytes_is_terminated_at_the_deadline(
    tmp_path, drip_server
):
    job = {
        "briefs": [{"ticker": "SNDK", "grade": "A+", "text": "evidence"}],
        "reads": [],
    }
    started = time.monotonic()
    briefs, reads, status, failures = prose.run_with_deadline(
        job, tmp_path / "work", budget_seconds=15.0, llm_url=drip_server, llm_model="m"
    )
    elapsed = time.monotonic() - started
    assert _Drip.started.is_set(), "the child never reached the server"
    assert status[0] == "timed_out"
    assert status[1].startswith("timed out after 0 min: 0 of 1 written")
    assert briefs == {}
    assert reads == {}
    assert elapsed < 15.0 + prose.TERMINATE_GRACE_SECONDS * 2 + 10
    assert failures == []
    # The child's connection died with it: the server saw the drop.
    assert _Drip.dropped.wait(timeout=15), "the dripping connection was not released"


# A prose step that blocks and then fails leaves the decision saved and
# the block saying why; the deterministic reads remain on the record.
def test_a_blocked_prose_request_cannot_prevent_the_core_record(tmp_path, capsys):
    # The enrichment as the nightly sees it: it hangs, then raises.
    def blocked():
        time.sleep(0.2)
        raise TimeoutError("runtime blocked")

    data = market_daily.record(_report())
    path = market_daily.finish(Path(tmp_path), data, blocked, allow_overwrite=False)
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["session"] == "2026-09-03"
    assert saved["briefs"] == {}
    block = prose.load(tmp_path, "2026-09-03")
    assert block["state"] == "unavailable"
    assert "runtime blocked" in block["detail"]
    merged = prose.merge(deskrecord.load(tmp_path, "2026-09-03"), block)
    assert merged["prose_state"] == "unavailable"
    assert merged["prose_status"].startswith("unavailable: TimeoutError")
    assert merged["grades"]["SNDK"]["read"] is None
    assert "reads" in merged["grades"]["SNDK"]  # the deterministic lines stand
    assert "prose: unavailable" in capsys.readouterr().out


# Results are appended line by line, so a kill loses at most the line in
# flight; the status names what was kept and what was not.
def test_what_the_child_wrote_before_the_kill_is_kept(tmp_path):
    results = tmp_path / prose.RESULTS_NAME
    results.write_text(
        json.dumps({"kind": "brief", "ticker": "A", "value": {"verdict": "v"}})
        + "\n"
        + json.dumps({"kind": "read", "ticker": "B", "error": "no read"})
        + "\n"
        + '{"kind": "read", "ticker": "C", "te',  # cut off by the kill
        encoding="utf-8",
    )
    briefs, reads, failures = prose.collect(results)
    assert briefs == {"A": {"verdict": "v"}}
    assert reads == {}
    assert failures == ["read B: no read"]
    state, detail = prose.status_of(1, 3, failures, True, 120)
    assert state == "timed_out"
    assert detail.startswith("timed out after 2 min: 1 of 3 written")
    assert prose.status_of(1, 3, failures, False, 120)[0] == "partial"
    assert prose.status_of(0, 3, failures, False, 120) == (
        "unavailable",
        "read B: no read",
    )
    assert prose.status_of(3, 3, [], False, 120)[0] == "ready"


# The record on disk stays the decision; the page's record carries the
# prose merged in with its status.
def test_prose_is_merged_into_the_record_when_read(tmp_path):
    data = market_daily.record(_report())
    market_daily.save(Path(tmp_path), data)
    raw = deskrecord.load(tmp_path, "2026-09-03")
    assert prose.merge(raw, None)["prose_state"] == "absent"
    prose.write(
        tmp_path,
        "2026-09-03",
        data["provenance"]["code_revision"],
        {
            "SNDK": {
                "stance": "own",
                "verdict": "v",
                "reasoning": "r",
                "risks": "k",
                "watch": "w",
            }
        },
        {"SNDK": "a model-written read"},
        ("ready", "2 of 2 written"),
        3.0,
    )
    merged = prose.merge(raw, prose.load(tmp_path, "2026-09-03"))
    assert merged["prose_state"] == "ready"
    assert merged["briefs"]["SNDK"]["verdict"] == "v"
    assert merged["grades"]["SNDK"]["read"] == "a model-written read"
    raw = json.loads(market_daily.record_path(tmp_path, "2026-09-03").read_text())
    assert raw["briefs"] == {}
    assert raw["grades"]["SNDK"]["read"] is None


# Records written before this change carry their prose inside; they read
# as embedded, not as missing.
def test_an_older_record_with_embedded_prose_reads_as_embedded(tmp_path):
    data = market_daily.record(_report(), {"SNDK": {"stance": "own", "verdict": "v"}})
    market_daily.save(Path(tmp_path), data)
    raw = deskrecord.load(tmp_path, "2026-09-03")
    assert "prose_state" not in raw  # the reader stays the decision alone
    assert prose.merge(raw, None)["prose_state"] == "embedded"


# The child leaves at once when its parent is gone, so a killed nightly
# never leaves an orphan calling the model.
def test_the_child_watchdog_exits_when_the_parent_is_gone():
    import threading

    exits = []

    def leave(code):
        exits.append(code)
        raise SystemExit(code)

    stop = threading.Event()
    calls = iter([True, True, False])
    with pytest.raises(SystemExit):
        prose._watch_parent(lambda: next(calls), stop, interval=0.01, leave=leave)
    assert exits == [3]


# A child that wrote every row but was still winding down at the deadline
# is complete, not timed out; a crash inside the child becomes a row that
# names the cause and the names it never reached.
def test_complete_is_not_timed_out_and_a_crash_is_named(tmp_path):
    state, detail = prose.status_of(3, 3, [], False, 120)
    assert state == "ready"
    failures = ["worker: RuntimeError: clients failed"]
    state, detail = prose.status_of(1, 4, failures, False, 120)
    assert state == "partial"
    assert "3 not attempted" in detail
    state, detail = prose.status_of(0, 4, failures, False, 120)
    assert (state, detail) == ("unavailable", "worker: RuntimeError: clients failed")


# Prose from an earlier run of the same session is not this decision's: a
# forced rerun killed after the record was saved and before the prose was
# rewritten leaves last run's briefs on file, and they must read as absent.
def test_prose_older_than_the_decision_is_not_merged():
    record = {
        "session": "2026-09-03",
        "written": "2026-09-03T23:10:00+00:00",
        "grades": {"AAA": {"grade": "A"}},
    }
    block = {
        "state": "ready",
        "written": "2026-09-03T22:40:00+00:00",
        "briefs": {"AAA": {"verdict": "old"}},
        "reads": {"AAA": "old read"},
    }
    merged = prose.merge(record, block)
    assert merged["prose_state"] == "absent"
    assert "predates" in merged["prose_status"]
    assert "briefs" not in merged
    assert "read" not in merged["grades"]["AAA"]
    fresh = prose.merge(record, {**block, "written": "2026-09-03T23:20:00+00:00"})
    assert fresh["prose_state"] == "ready"
    assert fresh["briefs"] == {"AAA": {"verdict": "old"}}
