"""The nightly grade parity check catches every way the board and the replay drift.

The record is built by `market_daily.record` on the point-in-time fixture's
report, so on a membership file that admits every name the check passes; a
flipped live grade, a name missing from the membership history, a target
weight off by more than the tolerance and a store that moved on are each
caught and named. The CLI turns the verdict into an exit code, and the
nightly path calls the check without letting it raise. A mismatch is parity
(same code, nothing moved: do not trade) or drift (a later checkout or a
store partition newer than the record: the board is stale); the nightly
path is parity by construction and the CLI exits 3 on drift.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime

import numpy as np
import pytest

from backend.agents.trading.desk import live_policy
from backend.cli import market_daily, market_grade_parity
from backend.market import grade_parity
from backend.tests.test_market_pit_scorecard import NAMES, _report

LAST = "2024-03-22"


# A membership history admitting every fixture name for the whole window, so
# the point-in-time book on the last session is exactly the board.
@pytest.fixture
def full_history(tmp_path):
    path = tmp_path / "membership_history.csv"
    rows = ["ticker,entered,entry_announced,exited,exit_announced,source,rule"]
    for t in NAMES:
        rows.append(f"{t},2016-01-04,2016-01-04,,,test,member throughout")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# The same history with FFF gone since mid-2023, as the scorecard fixture has it.
@pytest.fixture
def fff_left(tmp_path):
    path = tmp_path / "membership_history_fff.csv"
    rows = ["ticker,entered,entry_announced,exited,exit_announced,source,rule"]
    for t in NAMES[:-1]:
        rows.append(f"{t},2016-01-04,2016-01-04,,,test,member throughout")
    rows.append("FFF,2016-01-04,2016-01-04,2023-07-03,2023-07-03,test,leaves mid-2023")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# A record built by the nightly's own writer on the fixture report.
def _record(report=None) -> dict:
    return market_daily.record(report or _report())


# The record written by the same code on the same report agrees with the
# replay on every name, on membership and on every target.
def test_parity_ok_on_the_pit_fixture(full_history):
    report = _report()
    result = grade_parity.compare(_record(report), report, LAST, full_history)
    assert result["ok"] is True
    assert result["mismatches"] == []
    assert result["names"] == len(NAMES)
    assert result["targets_compared"] is True
    assert result["replay_session"] == LAST
    assert grade_parity.line(result) == f"grade parity: OK ({len(NAMES)} names)"


# The replay letter is the point-in-time report's letter at the record's
# row: the same as the scorecard's restricted report, name for name.
def test_replay_is_the_point_in_time_letter(fff_left):
    from backend.agents.trading.desk import point_in_time

    report = _report()
    restricted, mask = point_in_time.point_in_time(report, fff_left)
    rep = grade_parity.replay(report, LAST, fff_left)
    last = len(report.panel.dates) - 1
    for column, ticker in enumerate(report.panel.tickers):
        if ticker == "SPY":
            assert ticker not in rep["grades"]
            continue
        assert rep["grades"][ticker] == restricted.graded.letter(last, column)
        assert rep["members"][ticker] == bool(mask[last, column])
    assert rep["grades"]["FFF"] == "C"
    assert rep["members"]["FFF"] is False
    with pytest.raises(ValueError, match="no session"):
        grade_parity.replay(report, "1999-01-01", fff_left)


# A live grade that is not the replay's is named with both letters.
def test_a_flipped_grade_is_caught_with_both_letters(full_history):
    report = _report()
    record = _record(report)
    record["grades"]["CCC"]["grade"] = "B"
    result = grade_parity.compare(record, report, LAST, full_history)
    assert result["ok"] is False
    flips = [m for m in result["mismatches"] if m["kind"] == grade_parity.GRADE]
    assert flips == [
        {
            "kind": "grade",
            "ticker": "CCC",
            "live": "B",
            "replay": "A+",
            "detail": "live grade differs from the point-in-time replay",
        }
    ]
    text = grade_parity.line(result)
    assert text.startswith(f"GRADE PARITY MISMATCH: {LAST}: 1 names")
    assert "CCC grade live=B replay=A+" in text
    assert text.endswith("do not trade from the board")
    assert grade_parity.names_touched(result) == ["CCC"]


# A name on the board that the membership history says left the book is a
# membership difference, not a grade flip, and a member the board does not
# grade is the other direction.
def test_membership_discrepancies_are_caught_both_ways(fff_left):
    report = _report()
    record = _record(report)
    del record["grades"]["AAA"]
    result = grade_parity.compare(record, report, LAST, fff_left)
    assert result["ok"] is False
    rows = {
        m["ticker"]: m
        for m in result["mismatches"]
        if m["kind"] == grade_parity.MEMBERSHIP
    }
    assert set(rows) == {"FFF", "AAA"}
    assert rows["FFF"]["live"] == "A+"
    assert rows["FFF"]["replay"] == "C"
    assert "membership_history.csv" in rows["FFF"]["detail"]
    assert rows["AAA"]["live"] is None
    assert rows["AAA"]["replay"] == "A+"
    assert not [m for m in result["mismatches"] if m["kind"] == grade_parity.GRADE]
    # The names compared are those on both sides.
    assert result["names"] == len(NAMES) - 2


# A target weight off by more than the tolerance is caught; one inside it
# is not; a name the record sizes that the policy does not is caught too.
def test_target_discrepancies_are_caught_to_the_tolerance(full_history):
    report = _report()
    record = _record(report)
    fine = dict(record["targets"]["weights"])
    fine["AAA"] += 1e-12
    assert grade_parity.compare(
        {**record, "targets": {"weights": fine}}, report, LAST, full_history
    )["ok"]
    off = dict(record["targets"]["weights"])
    off["AAA"] += 1e-6
    off["SPY"] = 0.05
    result = grade_parity.compare(
        {**record, "targets": {"weights": off}}, report, LAST, full_history
    )
    rows = {
        m["ticker"]: m
        for m in result["mismatches"]
        if m["kind"] == grade_parity.TARGETS
    }
    assert set(rows) == {"AAA", "SPY"}
    assert rows["AAA"]["live"] == pytest.approx(off["AAA"])
    assert rows["AAA"]["replay"] == pytest.approx(live_policy.targets(report)["AAA"])
    assert rows["SPY"]["replay"] is None


# A rebuilt report whose last session is later than the record's means the
# store moved on: the grades at the record's row are still compared, the
# session difference is reported, and targets are not compared.
def test_a_store_that_moved_on_is_reported_and_targets_skipped(full_history):
    report = _report()
    record = _record(report)
    later = replace(
        report.panel,
        dates=np.append(report.panel.dates[1:], np.datetime64("2024-03-25")),
    )
    # Every price and grade shifts one row, so the record's session row exists
    # and carries the same letters.
    moved = replace(report, panel=later)
    result = grade_parity.compare(record, moved, LAST, full_history)
    assert result["ok"] is False
    assert result["targets_compared"] is False
    assert result["replay_session"] == "2024-03-25"
    kinds = [m["kind"] for m in result["mismatches"]]
    assert kinds == [grade_parity.SESSION]
    assert "store moved on" in result["mismatches"][0]["detail"]


# `run` loads the record from the store's folder, rebuilds the report with
# the nightly's own `desk_report`, writes the file (replacing the same date,
# keeping 90 days) and returns the result.
def test_run_writes_the_file_and_keeps_ninety_days(tmp_path, monkeypatch, full_history):
    report = _report()
    record = _record(report)
    market_daily.save(tmp_path, record)
    calls = []

    def fake_desk_report(store, asof):
        calls.append((store.root, asof))
        return report

    monkeypatch.setattr(market_daily, "desk_report", fake_desk_report)
    old = {
        "version": grade_parity.VERSION,
        "date": "2023-01-02",
        "ok": True,
        "mismatches": [],
    }
    stale = {
        "version": grade_parity.VERSION,
        "date": LAST,
        "ok": False,
        "mismatches": [{"kind": "grade"}],
    }
    recent = {
        "version": grade_parity.VERSION,
        "date": "2024-01-15",
        "ok": True,
        "mismatches": [],
    }
    grade_parity.path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    grade_parity.path(tmp_path).write_text(json.dumps({"rows": [old, stale, recent]}))
    result = grade_parity.run(tmp_path, history_path=full_history)
    assert result["ok"] is True
    assert calls == [(str(tmp_path), None)] or calls == [(tmp_path, None)]
    rows = grade_parity.load(tmp_path)["rows"]
    assert [r["date"] for r in rows] == ["2024-01-15", LAST]
    assert rows[-1]["ok"] is True, "the row for the same date is replaced"
    assert grade_parity.for_session(tmp_path, LAST)["ok"] is True
    assert grade_parity.for_session(tmp_path, "2023-01-02") is None
    # An explicit date bounds the rebuilt desk to that session.
    grade_parity.run(tmp_path, LAST, history_path=full_history)
    assert calls[-1][1] == date(2024, 3, 22)
    with pytest.raises(ValueError, match="not 2024-03-21"):
        grade_parity.run(tmp_path, "2024-03-21", record=record)
    with pytest.raises(FileNotFoundError):
        grade_parity.run(tmp_path / "empty")


# The CLI: 0 when live and replay agree, 1 on a mismatch with each row
# printed, 2 when there is nothing to check.
def test_cli_exit_codes(tmp_path, monkeypatch, capsys, full_history, fff_left):
    report = _report()
    market_daily.save(tmp_path, _record(report))
    monkeypatch.setattr(market_daily, "desk_report", lambda store, asof: report)
    assert (
        market_grade_parity.main(
            ["--root", str(tmp_path), "--membership", str(full_history)]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "grade parity: OK (6 names)" in out
    assert (
        market_grade_parity.main(
            ["--root", str(tmp_path), "--membership", str(fff_left)]
        )
        == 1
    )
    out = capsys.readouterr().out
    assert "GRADE PARITY MISMATCH" in out
    assert "membership: FFF:" in out
    assert market_grade_parity.main(["--root", str(tmp_path / "nowhere")]) == 2
    err = capsys.readouterr().err
    assert "not checked" in err
    assert "no desk record" in err
    assert grade_parity.for_session(tmp_path, LAST)["ok"] is False


# The nightly's hook: the verdict goes onto the record and into the log,
# a mismatch does not raise, and neither does a check that blows up.
def test_nightly_hook_never_raises(
    tmp_path, monkeypatch, capsys, full_history, fff_left
):
    report = _report()
    core = _record(report)
    monkeypatch.setattr(grade_parity, "_history", lambda history_path: full_history)
    result = market_daily._grade_parity(tmp_path, report, core)
    assert result["ok"] is True
    assert "grade parity: OK (6 names)" in capsys.readouterr().out
    monkeypatch.setattr(grade_parity, "_history", lambda history_path: fff_left)
    result = market_daily._grade_parity(tmp_path, report, core)
    assert result["ok"] is False
    out = capsys.readouterr().out
    assert "GRADE PARITY MISMATCH" in out
    assert "FFF membership" in out
    assert grade_parity.for_session(tmp_path, LAST)["ok"] is False

    def boom(*args, **kwargs):
        raise RuntimeError("membership_history.csv unreadable")

    monkeypatch.setattr(grade_parity, "run", boom)
    result = market_daily._grade_parity(tmp_path, report, core)
    assert result["ok"] is False
    assert result["mismatches"][0]["kind"] == "unavailable"
    assert (
        "not checked (RuntimeError: membership_history.csv unreadable)"
        in capsys.readouterr().out
    )


# The record the nightly saves carries the verdict, and the API hands the
# board the stored row for that session over the record's own.
def test_api_prefers_the_stored_row(tmp_path, monkeypatch):
    market_api = pytest.importorskip("backend.api.v1.market")
    monkeypatch.setattr(market_api, "_root", lambda: tmp_path)
    assert market_api._grade_parity_for(None) is None
    record = {
        "session": LAST,
        "grade_parity": {"ok": True, "date": LAST, "mismatches": []},
    }
    assert market_api._grade_parity_for(record) == record["grade_parity"]
    grade_parity.write(
        tmp_path,
        {
            "version": grade_parity.VERSION,
            "date": LAST,
            "ok": False,
            "mismatches": [
                {"kind": "grade", "ticker": "AAA", "live": "A", "replay": "B"}
            ],
        },
    )
    assert market_api._grade_parity_for(record)["ok"] is False
    assert market_api._grade_parity_for({"session": "2020-01-01"}) is None


# The nightly path end to end: `main()` on a store with no record, the desk
# faked to the fixture report, and a membership file that omits a board
# name. The run finishes, the record is written with the failed verdict on
# it, and the mismatch line is in the run's output.
def test_the_nightly_finishes_and_records_a_mismatch(
    tmp_path, monkeypatch, capsys, fff_left
):
    import sys

    from backend.cli import market_economics
    from backend.market import learned_inputs

    report = _report()
    monkeypatch.setattr(
        market_daily.trading_desk, "run", lambda store, asof=None, **kw: report
    )
    for name in ("_print_regime", "_print_grades", "_print_book"):
        monkeypatch.setattr(market_daily, name, lambda *a, **k: None)
    monkeypatch.setattr(market_daily, "observe_ml_forward", lambda *a, **k: None)
    monkeypatch.setattr(market_daily, "_policy_shadows", lambda *a, **k: {})
    monkeypatch.setattr(market_daily, "_reversal_shadows", lambda *a, **k: None)
    monkeypatch.setattr(market_daily, "_fundamentals_block", lambda *a, **k: None)
    monkeypatch.setattr(market_daily, "curves", lambda *a, **k: {})
    monkeypatch.setattr(market_daily, "_tone_revisions", lambda *a, **k: {})
    monkeypatch.setattr(market_daily, "write_history", lambda *a, **k: 0)
    monkeypatch.setattr(
        market_daily, "enrich_prose", lambda *a, **k: ("skipped", "test")
    )
    monkeypatch.setattr(learned_inputs, "capture", lambda *a, **k: "skipped")
    monkeypatch.setattr(market_economics, "refresh_if_current", lambda *a, **k: None)
    monkeypatch.setattr(grade_parity, "_history", lambda history_path: fff_left)
    monkeypatch.setattr(sys, "argv", ["market_daily", "--data-dir", str(tmp_path)])
    market_daily.main()
    out = capsys.readouterr().out
    assert "GRADE PARITY MISMATCH" in out
    assert "FFF membership live=A+ replay=C" in out
    assert "record written" in out
    saved = json.loads(market_daily.record_path(tmp_path, LAST).read_text())
    assert saved["grade_parity"]["ok"] is False
    assert saved["grade_parity"]["mismatches"][0]["ticker"] == "FFF"
    assert grade_parity.for_session(tmp_path, LAST)["ok"] is False


# The context that says "same code, nothing moved", for tests of parity mode.
def _same(code="abc1234") -> dict:
    return {"record_code": code, "replay_code": code, "moved_inputs": []}


# Parity mode when the record's code is the replay's and nothing moved;
# with no context at all the reading is parity too, because a mismatch is
# never made milder by not knowing what produced it.
def test_mode_is_parity_when_code_equal_and_nothing_moved(full_history):
    report = _report()
    record = _record(report)
    record["grades"]["CCC"]["grade"] = "B"
    result = grade_parity.compare(record, report, LAST, full_history, _same())
    assert result["ok"] is False
    assert result["mode"] == grade_parity.PARITY
    assert result["code"] == {"record": "abc1234", "replay": "abc1234"}
    assert result["moved_inputs"] == []
    assert grade_parity.line(result).startswith("GRADE PARITY MISMATCH")
    assert grade_parity.line(result).endswith("do not trade from the board")
    assert grade_parity.compare(record, report, LAST, full_history)["mode"] == "parity"
    # A passing result still says what mode it was checked in.
    fine = grade_parity.compare(_record(report), report, LAST, full_history, _same())
    assert fine["ok"] is True
    assert fine["mode"] == "parity"


# Drift mode when the replay's code differs from the record's: `ok` stays
# False, the rows are unchanged, and the line names the code pair, says the
# board is stale and does not say "do not trade".
def test_mode_is_drift_when_code_differs(full_history):
    report = _report()
    record = _record(report)
    record["grades"]["CCC"]["grade"] = "B"
    same = grade_parity.compare(record, report, LAST, full_history, _same())
    result = grade_parity.compare(
        record,
        report,
        LAST,
        full_history,
        {"record_code": "879abc56", "replay_code": "1325466b", "moved_inputs": []},
    )
    assert result["ok"] is False
    assert result["mode"] == grade_parity.DRIFT
    assert result["code"] == {"record": "879abc56", "replay": "1325466b"}
    assert result["mismatches"] == same["mismatches"]
    text = grade_parity.line(result)
    assert text == (
        f"GRADE DRIFT since {LAST}'s record (code 879abc56→1325466b; "
        "inputs moved: none): 1 names - CCC grade live=B replay=A+"
        " - the board is stale; the next nightly re-grades"
    )
    assert "do not trade" not in text


# Drift mode when a store partition is newer than the record, even on the
# same code; the moved partitions are listed on the result and in the line.
def test_mode_is_drift_when_an_input_moved(full_history):
    report = _report()
    record = _record(report)
    record["grades"]["CCC"]["grade"] = "B"
    result = grade_parity.compare(
        record,
        report,
        LAST,
        full_history,
        {
            "record_code": "abc1234",
            "replay_code": "abc1234",
            "moved_inputs": [
                "edgar_events/asof=2024-03-25",
                "edgar_facts/asof=2024-03-25",
            ],
        },
    )
    assert result["mode"] == grade_parity.DRIFT
    assert result["moved_inputs"] == [
        "edgar_events/asof=2024-03-25",
        "edgar_facts/asof=2024-03-25",
    ]
    text = grade_parity.line(result)
    moved = "edgar_events/asof=2024-03-25, edgar_facts/asof=2024-03-25"
    assert f"(code abc1234\u2192abc1234; inputs moved: {moved})" in text
    assert text.endswith("the board is stale; the next nightly re-grades")


# `moved_inputs` finds every dated partition after the record's session, or
# touched after the record was written, under any input folder - and
# nothing under desk/, history/ or research/, nor a partition that predates
# the record.
def test_moved_inputs_finds_later_partitions_and_ignores_outputs(tmp_path):
    import os

    record = {"session": LAST, "written": "2024-03-22T21:05:00+00:00"}
    before = datetime(2024, 3, 22, 20, 0, tzinfo=UTC).timestamp()
    after = datetime(2024, 3, 24, 9, 0, tzinfo=UTC).timestamp()
    for rel, when in [
        ("edgar_facts/asof=2024-03-25", after),  # later date
        ("edgar_events/asof=2024-03-22", after),  # same date, written after
        ("bars/asof=2024-03-22", before),  # tonight's own partition
        ("fundamentals-features/asof=2024-03-01", before),  # older
        ("options/asof=2024-03-26", after),
        ("desk/asof=2024-03-26", after),  # outputs, never inputs
        ("history/asof=2024-03-26", after),
        ("research/asof=2024-03-26", after),
        ("edgar_facts/not-a-partition", after),
        ("edgar_facts/asof=garbage", after),
    ]:
        d = tmp_path / rel
        d.mkdir(parents=True)
        os.utime(d, (when, when))
    (tmp_path / "desk" / "grade_parity.json").write_text("{}")
    assert grade_parity.moved_inputs(tmp_path, record) == [
        "edgar_events/asof=2024-03-22",
        "edgar_facts/asof=2024-03-25",
        "options/asof=2024-03-26",
    ]
    # Without a `written` timestamp only the dates decide.
    assert grade_parity.moved_inputs(tmp_path, {"session": LAST}) == [
        "edgar_facts/asof=2024-03-25",
        "options/asof=2024-03-26",
    ]
    assert grade_parity.moved_inputs(tmp_path / "nowhere", record) == []


# `run` from the store (the CLI path) reads the running checkout's revision
# the way `market_daily` stamps provenance and lists the moved partitions;
# the nightly path (report in hand) is parity by construction whatever the
# store has since gained.
def test_run_builds_the_context_per_path(tmp_path, monkeypatch, full_history):
    import os

    report = _report()
    record = _record(report)
    record["grades"]["CCC"]["grade"] = "B"
    record["provenance"]["code_revision"] = "879abc56"
    market_daily.save(tmp_path, record)
    monkeypatch.setattr(market_daily, "desk_report", lambda store, asof: report)
    monkeypatch.setattr(market_daily, "_git_revision", lambda: "1325466b")
    later = tmp_path / "edgar_facts" / "asof=2024-03-26"
    later.mkdir(parents=True)
    stamp = datetime(2024, 3, 26, 9, 0, tzinfo=UTC).timestamp()
    os.utime(later, (stamp, stamp))
    result = grade_parity.run(tmp_path, history_path=full_history)
    assert result["ok"] is False
    assert result["mode"] == grade_parity.DRIFT
    assert result["code"] == {"record": "879abc56", "replay": "1325466b"}
    assert result["moved_inputs"] == ["edgar_facts/asof=2024-03-26"]
    assert grade_parity.for_session(tmp_path, LAST)["mode"] == "drift"
    # Same code, but the partition moved: still drift.
    monkeypatch.setattr(market_daily, "_git_revision", lambda: "879abc56")
    assert grade_parity.run(tmp_path, history_path=full_history)["mode"] == "drift"
    # The nightly path: report and record in hand, parity whatever the store holds.
    monkeypatch.setattr(market_daily, "_git_revision", lambda: "1325466b")
    nightly = grade_parity.run(
        tmp_path, LAST, report=report, record=record, history_path=full_history
    )
    assert nightly["ok"] is False
    assert nightly["mode"] == grade_parity.PARITY
    assert nightly["code"] == {"record": "879abc56", "replay": "879abc56"}
    assert nightly["moved_inputs"] == []
    hook = market_daily._grade_parity(tmp_path, report, record)
    assert hook["mode"] == grade_parity.PARITY


# The CLI exits 3 on drift, printing the drift line, and 1 on a parity
# mismatch from the same store when nothing has moved.
def test_cli_exits_three_on_drift(tmp_path, monkeypatch, capsys, fff_left):
    report = _report()
    record = _record(report)
    record["provenance"]["code_revision"] = "879abc56"
    market_daily.save(tmp_path, record)
    monkeypatch.setattr(market_daily, "desk_report", lambda store, asof: report)
    monkeypatch.setattr(market_daily, "_git_revision", lambda: "1325466b")
    args = ["--root", str(tmp_path), "--membership", str(fff_left)]
    assert market_grade_parity.main(args) == 3
    out = capsys.readouterr().out
    assert f"GRADE DRIFT since {LAST}'s record (code 879abc56→1325466b" in out
    assert "the board is stale; the next nightly re-grades" in out
    assert "membership: FFF:" in out
    monkeypatch.setattr(market_daily, "_git_revision", lambda: "879abc56")
    assert market_grade_parity.main(args) == 1
    assert "GRADE PARITY MISMATCH" in capsys.readouterr().out
