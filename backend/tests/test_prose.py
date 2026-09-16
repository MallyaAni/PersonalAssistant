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

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


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


def test_a_request_that_keeps_producing_bytes_is_terminated_at_the_deadline(
    tmp_path, drip_server
):
    job = {
        "briefs": [{"ticker": "SNDK", "grade": "A+", "text": "evidence"}],
        "reads": [],
    }
    started = time.monotonic()
    briefs, reads, status = prose.run_with_deadline(
        job, tmp_path / "work", budget_seconds=6.0, llm_url=drip_server, llm_model="m"
    )
    elapsed = time.monotonic() - started
    assert _Drip.started.is_set(), "the child never reached the server"
    assert status.startswith("timed out after 0 min: 0 of 1 written")
    assert briefs == {}
    assert reads == {}
    assert elapsed < 6.0 + prose.TERMINATE_GRACE_SECONDS * 2 + 10
    # The child's connection died with it: the server saw the drop.
    assert _Drip.dropped.wait(timeout=15), "the dripping connection was not released"


def test_a_blocked_prose_request_cannot_prevent_the_core_record(tmp_path, capsys):
    def blocked(report, session, revision):
        time.sleep(0.2)
        raise TimeoutError("runtime blocked")

    data = market_daily.record(_report())
    path = market_daily.finish(Path(tmp_path), data, blocked, allow_overwrite=False)
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["session"] == "2026-09-03"
    assert saved["briefs"] == {}
    block = prose.load(tmp_path, "2026-09-03")
    assert block["status"].startswith("unavailable")
    assert "runtime blocked" in block["status"]
    merged = deskrecord.load(tmp_path, "2026-09-03")
    assert merged["prose_status"].startswith("unavailable")
    assert merged["grades"]["SNDK"]["read"] is None
    assert "reads" in merged["grades"]["SNDK"]  # the deterministic lines stand
    assert "prose: unavailable" in capsys.readouterr().out


def test_what_the_child_wrote_before_the_kill_is_kept(tmp_path):
    results = tmp_path / prose.RESULTS_NAME
    results.write_text(
        json.dumps({"kind": "brief", "ticker": "A", "fields": {"verdict": "v"}})
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
    assert prose.status_of(1, 3, failures, True, 120).startswith(
        "timed out after 2 min: 1 of 3 written"
    )
    assert prose.status_of(1, 3, failures, False, 120).startswith("partial: 1 of 3")
    assert prose.status_of(0, 3, failures, False, 120).startswith(
        "unavailable: read B: no read"
    )
    assert prose.status_of(3, 3, [], False, 120) == "ready"


def test_prose_is_merged_into_the_record_when_read(tmp_path):
    data = market_daily.record(_report())
    market_daily.save(Path(tmp_path), data)
    assert deskrecord.load(tmp_path, "2026-09-03")["prose_status"] == "absent"
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
        "ready",
        3.0,
    )
    merged = deskrecord.load(tmp_path, "2026-09-03")
    assert merged["prose_status"] == "ready"
    assert merged["briefs"]["SNDK"]["verdict"] == "v"
    assert merged["grades"]["SNDK"]["read"] == "a model-written read"
    raw = json.loads(market_daily.record_path(tmp_path, "2026-09-03").read_text())
    assert raw["briefs"] == {}
    assert raw["grades"]["SNDK"]["read"] is None


def test_an_older_record_with_embedded_prose_reads_as_embedded(tmp_path):
    data = market_daily.record(_report(), {"SNDK": {"stance": "own", "verdict": "v"}})
    market_daily.save(Path(tmp_path), data)
    assert deskrecord.load(tmp_path, "2026-09-03")["prose_status"] == "embedded"
