"""The measurement has to survive the deploy, and never cost the turn.

The context budget's summary line works - the live server prints it - but
docker logs die with the container and this repository rebuilds the backend
many times a day. Thirteen real turns' measurements were lost that way in the
two days after the budget shipped. So each report is also appended as JSONL
on a named volume, and a CLI reads the distribution back to suggest
enforcement floors.

What is pinned here: the row is valid JSON carrying what floor-setting needs,
an empty path disables persistence, no failure ever raises into a turn, and
the readout refuses to suggest floors from a handful of turns.
"""

import json

import pytest

from backend.cli.report_context_usage import load_rows
from backend.cli.report_context_usage import main as report_main
from backend.config.settings import settings
from backend.core.context_budget import Section, plan
from backend.core.observability import record_context_report


def _report():
    return plan(
        (
            Section("system", ("s" * 400,), priority=0, floor_items=1),
            Section("evidence", ("e" * 900, "e" * 900), priority=1),
        ),
        budget_tokens=10_000,
    )


@pytest.fixture
def report_path(tmp_path, monkeypatch):
    target = tmp_path / "telemetry" / "context_reports.jsonl"
    monkeypatch.setattr(settings, "CONTEXT_REPORT_PATH", str(target))
    return target


def test_a_report_lands_as_one_valid_json_line(report_path):
    record_context_report(_report(), "trace-1")

    lines = report_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["trace_id"] == "trace-1"
    assert row["used_tokens"] > 0
    assert "evidence" in row["sections"]
    assert "at" in row


def test_reports_append_rather_than_replace(report_path):
    record_context_report(_report(), "trace-1")
    record_context_report(_report(), "trace-2")

    lines = report_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["trace_id"] for line in lines] == ["trace-1", "trace-2"]


def test_an_empty_path_disables_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_REPORT_PATH", "")

    record_context_report(_report(), "trace-1")

    assert not list(tmp_path.iterdir())


# Measurement is an improvement to a turn, never a requirement of one. A path
# that cannot be a directory is the easiest real failure to provoke.
def test_a_failing_write_never_raises(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory is needed", encoding="utf-8")
    monkeypatch.setattr(
        settings, "CONTEXT_REPORT_PATH", str(blocker / "sub" / "x.jsonl")
    )

    record_context_report(_report(), "trace-1")  # must simply return


# A torn line from a crash mid-write costs that line, not the report.
def test_a_torn_line_is_skipped(report_path):
    record_context_report(_report(), "trace-1")
    with report_path.open("a", encoding="utf-8") as handle:
        handle.write('{"at": "2026-08-21", "used_tok')

    rows = load_rows(report_path)
    assert len(rows) == 1


def test_the_readout_refuses_floors_from_a_handful_of_turns(report_path, capsys):
    for index in range(3):
        record_context_report(_report(), f"trace-{index}")

    assert report_main(["--path", str(report_path)]) == 0
    out = capsys.readouterr().out
    assert "turns measured : 3" in out
    assert "not a distribution" in out
    assert "suggested floor_items" not in out


def test_the_readout_suggests_floors_once_there_is_a_distribution(report_path, capsys):
    for index in range(30):
        record_context_report(_report(), f"trace-{index}")

    assert report_main(["--path", str(report_path)]) == 0
    out = capsys.readouterr().out
    assert "suggested floor_items" in out
    assert "evidence" in out
    # Never-trimmable sections get no floor; a floor there is meaningless.
    assert "\n  system" not in out


def test_a_missing_file_reports_rather_than_crashes(tmp_path, capsys):
    assert report_main(["--path", str(tmp_path / "absent.jsonl")]) == 1
    assert "has any authenticated turn run" in capsys.readouterr().out
