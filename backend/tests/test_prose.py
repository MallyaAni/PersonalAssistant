"""Prose beside the decision: the record is saved first, the prose cannot stop it.

What has to hold: a blocked or failing prose request leaves the core
record saved and the prose block unavailable; the budget stops the
enrichment between names and says so; a record reads back with its prose
merged and a status, and without prose the deterministic reads stand.
"""

import json
import time
from datetime import date
from pathlib import Path

from backend.cli import market_daily
from backend.market import deskrecord, prose
from backend.tests.test_market_daily import _report


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
    assert block is not None
    assert block["status"].startswith("unavailable")
    assert "runtime blocked" in block["status"]
    merged = deskrecord.load(tmp_path, "2026-09-03")
    assert merged["prose_status"].startswith("unavailable")
    assert merged["grades"]["SNDK"]["read"] is None  # no model prose
    assert "reads" in merged["grades"]["SNDK"]  # the deterministic lines stand
    assert "prose: unavailable" in capsys.readouterr().out


def test_the_budget_stops_enrichment_between_names():
    calls = []

    def slow(name):
        calls.append(name)
        time.sleep(0.15)
        return {"verdict": name}

    briefs, reads, status = prose.enrich(
        ["A", "B", "C"], ["D"], slow, lambda n: "read", budget_seconds=0.2
    )
    assert list(briefs) in (["A"], ["A", "B"])
    assert status.startswith("partial")
    assert "skipped" in status


def test_failures_are_counted_and_a_dead_runtime_is_unavailable():
    def dead(name):
        raise ConnectionError("away")

    briefs, reads, status = prose.enrich(["A"], ["B"], dead, dead, budget_seconds=10)
    assert briefs == {}
    assert reads == {}
    assert status.startswith("unavailable: brief A: ConnectionError")
    briefs, reads, status = prose.enrich(
        ["A"], [], lambda n: {"verdict": "v"}, dead, budget_seconds=10
    )
    assert status == "ready"


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
    # The decision itself was not rewritten.
    raw = json.loads(market_daily.record_path(tmp_path, "2026-09-03").read_text())
    assert raw["briefs"] == {}
    assert raw["grades"]["SNDK"]["read"] is None


def test_an_older_record_with_embedded_prose_reads_as_embedded(tmp_path):
    data = market_daily.record(_report(), {"SNDK": {"stance": "own", "verdict": "v"}})
    market_daily.save(Path(tmp_path), data)
    assert deskrecord.load(tmp_path, "2026-09-03")["prose_status"] == "embedded"
    assert date.fromisoformat("2026-09-03")
