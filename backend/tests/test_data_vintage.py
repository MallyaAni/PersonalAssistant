"""A grade that moved on a data update says so; one that moved without one does not.

`data_vintage` compares each name's own stored earnings data - its release
reading (`edgar_tone`) and its earnings filings (`edgar_events`) - as of a
record's session with a later reading of the immutable store. A release or
filing read for the first time, more old releases admitted, a re-scored or
dropped release is a data-vintage change; a release dated after the record
is new data, and the nightly's identical re-fetch is nothing. The parity
check (CLI path) marks a drift row of such a name as explained and keeps the
banner for every other row; the nightly carries the same block on the record
against the previous record. Three cases each way: detected, not detected,
mixed.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime

import pytest

from backend.cli import market_daily, market_grade_parity
from backend.market import data_vintage, grade_parity
from backend.market.language import TONE_KIND
from backend.market.store import MarketStore
from backend.tests.test_grade_parity import LAST, _record
from backend.tests.test_market_pit_scorecard import NAMES, _report

CUT = date(2026, 9, 30)
BEFORE = date(2026, 9, 30)
AFTER = date(2026, 10, 1)
WRITTEN = datetime(2026, 9, 30, 23, 45, 49, tzinfo=UTC)
FIRST_LINE = (
    "ARM, ASML, SIMO, TSM: grades recomputed after their earnings releases were "
    "read for the first time (data update after the 2026-09-30 record)"
)


# One release reading as the tone frame stores it: an accession, the
# session the market could react, and the five scores.
def _release(accession: str, reaction: str, guidance: float = 0.5) -> dict:
    return {
        "accession": accession,
        "reaction_date": date.fromisoformat(reaction),
        "guidance": guidance,
        "demand": 0.25,
        "pricing": 0.0,
        "capex": 0.0,
        "supply_constrained": 0.0,
        "summary": "A results release.",
        "model": "deepseek-v4-flash",
        "prompt_version": "release_tone/3",
    }


# One earnings filing as the events frame stores it: accepted in UTC, by
# default 06:00 New York, before the open.
def _filing(
    accession: str, filed: str, form: str = "6-K", at: str = "10:00:00"
) -> dict:
    return {
        "accepted": f"{filed}T{at}+00:00",
        "filed": date.fromisoformat(filed),
        "accession": accession,
        "items": "2.02" if form == "8-K" else "",
        "form": form,
    }


# Rows to the column frame `write_frame` takes; no rows is an empty frame with
# the kind's columns, which is what the store holds for a name with nothing.
def _columns(rows: list[dict], kind: str) -> dict[str, list]:
    keys = (
        list(_release("x", "2020-01-01"))
        if kind == TONE_KIND
        else list(_filing("x", "2020-01-01"))
    )
    return {k: [r[k] for r in rows] for k in keys}


# Write one name's frame of one kind into one partition, at a given file time.
def _put(store, kind, asof, ticker, rows, when: datetime | None = None) -> None:
    assert store.write_frame(kind, asof, ticker, _columns(rows, kind))
    if when is not None:
        stamp = when.timestamp()
        os.utime(store._path(kind, asof, ticker), (stamp, stamp))


# Both kinds for one name in one partition.
def _both(store, asof, ticker, releases, filings, when=None) -> None:
    _put(store, TONE_KIND, asof, ticker, releases, when)
    _put(store, data_vintage.EVENTS_KIND, asof, ticker, filings, when)


# After the record (file times later than WRITTEN), as the 6-K backfill was.
LATER = datetime(2026, 10, 1, 2, 33, tzinfo=UTC)
# Tonight's own nightly partition, before the record it feeds was written.
EARLIER = datetime(2026, 9, 30, 23, 35, tzinfo=UTC)


# The 2026-09-30 picture: ARM, ASML, SIMO and TSM had no release reading in
# the record's partition and gained one in a later partition, after the
# record was written. Each is a first reading, of both kinds.
def test_a_first_reading_after_the_record_is_detected(tmp_path):
    store = MarketStore(tmp_path)
    for ticker in ("ARM", "ASML", "SIMO", "TSM"):
        _both(store, BEFORE, ticker, [], [], EARLIER)
        _both(
            store,
            AFTER,
            ticker,
            [
                _release(f"{ticker}-1", "2025-07-30"),
                _release(f"{ticker}-2", "2026-07-30"),
            ],
            [
                _filing(f"{ticker}-1", "2025-07-30"),
                _filing(f"{ticker}-2", "2026-07-30"),
            ],
            LATER,
        )
    found = data_vintage.changes(
        store, ["ARM", "ASML", "SIMO", "TSM"], CUT, None, WRITTEN
    )
    assert sorted(found) == ["ARM", "ASML", "SIMO", "TSM"]
    arm = found["ARM"]
    assert arm["what"] == data_vintage.FIRST
    assert arm["partition"] == "2026-10-01"
    assert arm[TONE_KIND] == {
        "before": 0,
        "after": 2,
        "added": 2,
        "reread": 0,
        "dropped": 0,
    }
    assert arm[data_vintage.EVENTS_KIND]["added"] == 2
    assert data_vintage.lines(found, found, "2026-09-30") == [FIRST_LINE]


# More old releases, a re-scored one, a dropped one and filings alone are
# each a change, each with its own words; one name or several.
def test_each_kind_of_change_is_detected_with_its_own_words(tmp_path):
    store = MarketStore(tmp_path)
    old = [_release("A-1", "2025-01-20"), _release("A-2", "2025-04-20")]
    _both(store, BEFORE, "ASML", old[:1], [_filing("A-1", "2025-01-20")], EARLIER)
    _both(store, AFTER, "ASML", old, [_filing("A-1", "2025-01-20")], LATER)
    _both(store, BEFORE, "SIMO", [_release("S-1", "2025-07-31")], [], EARLIER)
    _both(
        store, AFTER, "SIMO", [_release("S-1", "2025-07-31", guidance=-0.5)], [], LATER
    )
    _both(store, BEFORE, "TSM", old, [], EARLIER)
    _both(store, AFTER, "TSM", old[:1], [], LATER)
    _both(store, BEFORE, "NBIS", [], [], EARLIER)
    _both(store, AFTER, "NBIS", [], [_filing("N-1", "2025-08-07")], LATER)
    # WDAY's 2026-09-29 8-K as stored on 09-29 (16:01 UTC, 12:01 New York:
    # the market reacts that day) and on 09-30 (20:01 UTC, after the close:
    # the next session) - the same filing read with a different reaction.
    wday = ("0001327811-26-000048", "2026-09-29", "8-K")
    _both(store, BEFORE, "WDAY", [], [_filing(*wday, at="16:01:40")], EARLIER)
    _both(store, AFTER, "WDAY", [], [_filing(*wday, at="20:01:40")], LATER)
    found = data_vintage.changes(
        store, ["ASML", "SIMO", "TSM", "NBIS", "WDAY"], CUT, None, WRITTEN
    )
    assert {t: c["what"] for t, c in found.items()} == {
        "ASML": data_vintage.MORE,
        "SIMO": data_vintage.REREAD,
        "TSM": data_vintage.DROPPED,
        "NBIS": data_vintage.FILINGS,
        "WDAY": data_vintage.FILINGS,
    }
    assert found["WDAY"][data_vintage.EVENTS_KIND]["reread"] == 1
    found.pop("WDAY")
    assert data_vintage.lines(found, found, "2026-10-01") == [
        "ASML: grade recomputed after more of its earnings releases were read "
        "(data update after the 2026-10-01 record)",
        "SIMO: grade recomputed after its earnings releases were re-read "
        "(data update after the 2026-10-01 record)",
        "TSM: grade recomputed after some of its earnings releases were dropped "
        "(data update after the 2026-10-01 record)",
        "NBIS: grade recomputed after its earnings filings were re-read "
        "(data update after the 2026-10-01 record)",
    ]
    for text in data_vintage.lines(found, found, "2026-10-01"):
        for word in ("trade", "buy", "sell", "should", "avoid", "safe"):
            assert word not in text.lower()


# Not detected: a release dated after the record is new data; the nightly's
# identical re-fetch in a new partition is nothing; a filing whose stored
# acceptance time moved without moving its reaction session is nothing (CIEN's
# 2011 8-K stored at 12:23 and at 07:23 UTC, both before the open); a name
# with no newer partition, or no frames at all, is nothing.
def test_new_data_and_identical_refetches_are_not_detected(tmp_path):
    store = MarketStore(tmp_path)
    same = [_release("M-1", "2026-07-28")]
    _both(store, BEFORE, "MSFT", same, [_filing("M-1", "2026-07-28", "8-K")], EARLIER)
    _both(store, AFTER, "MSFT", same, [_filing("M-1", "2026-07-28", "8-K")], LATER)
    _both(store, BEFORE, "AAPL", same, [], EARLIER)
    _both(store, AFTER, "AAPL", same + [_release("P-2", "2026-10-01")], [], LATER)
    cien = ("0000936395-11-000005", "2011-12-08", "8-K")
    _both(store, BEFORE, "CIEN", [], [_filing(*cien, at="12:23:13")], EARLIER)
    _both(store, AFTER, "CIEN", [], [_filing(*cien, at="07:23:13")], LATER)
    _both(store, BEFORE, "NVDA", same, [], EARLIER)
    found = data_vintage.changes(
        store, ["MSFT", "AAPL", "CIEN", "NVDA", "NONE"], CUT, None, WRITTEN
    )
    assert found == {}


# A newer partition whose file was already on disk when the record was
# written was that record's own input, so it is not "after" it; with no
# timestamp, or the file written later, the dates decide.
def test_a_partition_on_disk_before_the_record_is_not_after_it(tmp_path):
    store = MarketStore(tmp_path)
    _both(store, BEFORE, "ARM", [], [], EARLIER)
    _both(store, AFTER, "ARM", [_release("R-1", "2025-07-30")], [], EARLIER)
    assert data_vintage.changes(store, ["ARM"], CUT, None, WRITTEN) == {}
    assert sorted(data_vintage.changes(store, ["ARM"], CUT, None, None)) == ["ARM"]
    # The replay's own as-of bounds the reading: as of the record's session
    # nothing newer is read, so nothing changed.
    assert data_vintage.changes(store, ["ARM"], CUT, CUT, None) == {}


# Tonight's record against the previous one (mixed): a name whose grade
# moved and whose data changed is named; one whose data changed with no move
# is in `changes` only; one that moved with no data change is not named.
def test_since_previous_names_only_moves_with_a_data_change(tmp_path):
    store = MarketStore(tmp_path)
    for ticker in ("ARM", "ASML"):
        _both(store, BEFORE, ticker, [], [], EARLIER)
        _both(store, AFTER, ticker, [_release(f"{ticker}-1", "2025-07-30")], [], LATER)
    _both(store, BEFORE, "AAPL", [_release("P-1", "2026-07-30")], [], EARLIER)
    previous = {
        "session": "2026-09-30",
        "written": WRITTEN.isoformat(),
        "grades": {
            "ARM": {"grade": "C"},
            "ASML": {"grade": "C"},
            "AAPL": {"grade": "A"},
        },
    }
    record = {
        "session": "2026-10-01",
        "grades": {
            "ARM": {"grade": "B"},
            "ASML": {"grade": "C"},
            "AAPL": {"grade": "B"},
            "NEW": {"grade": "A"},
        },
    }
    block = data_vintage.since_previous(store, record, previous)
    assert block["since"] == "2026-09-30"
    assert block["names"] == ["ARM"]
    assert sorted(block["changes"]) == ["ARM", "ASML"]
    assert block["lines"] == [
        "ARM: grade recomputed after its earnings releases were read for the "
        "first time (data update after the 2026-09-30 record)"
    ]
    assert data_vintage.since_previous(store, record, None) is None


# A drift of a name whose own data changed after the record (detected): its
# grade row is explained, the block names it with the board's line, and
# `ok`, `mode` and the line the nightly log reads are what they were.
def test_parity_marks_a_drift_row_explained_when_the_names_data_changed(full_history):
    report = _report()
    record = _record(report)
    record["grades"]["CCC"]["grade"] = "B"
    vintage = {"CCC": {"what": data_vintage.FIRST, "partition": "2024-03-25"}}
    context = {
        "record_code": "abc1234",
        "replay_code": "abc1234",
        "moved_inputs": ["edgar_tone/asof=2024-03-25"],
    }
    plain = grade_parity.compare(record, report, LAST, full_history, context)
    result = grade_parity.compare(
        record, report, LAST, full_history, {**context, "vintage": vintage}
    )
    assert result["ok"] is False
    assert result["mode"] == grade_parity.DRIFT
    assert result["mismatches"] == [{**plain["mismatches"][0], "explained": True}]
    assert result["data_vintage"]["names"] == ["CCC"]
    assert result["data_vintage"]["lines"] == [
        "CCC: grade recomputed after its earnings releases were read for the "
        f"first time (data update after the {LAST} record)"
    ]
    assert grade_parity.line(result) == grade_parity.line(plain)


# Not detected: with no name's data changed the result is exactly the one
# before this existed - no block, no row marked - and the red parity banner's
# rows are untouched.
def test_parity_without_a_data_change_is_unchanged(full_history):
    report = _report()
    record = _record(report)
    record["grades"]["CCC"]["grade"] = "B"
    same = {"record_code": "abc1234", "replay_code": "abc1234", "moved_inputs": []}
    before = grade_parity.compare(record, report, LAST, full_history, same)
    after = grade_parity.compare(
        record, report, LAST, full_history, {**same, "vintage": {}}
    )
    assert "data_vintage" not in after
    assert after["mismatches"] == before["mismatches"]
    assert all("explained" not in m for m in after["mismatches"])
    assert after["mode"] == grade_parity.PARITY
    # A parity mismatch ran on the record's own code and store, so even a
    # change handed in is never used to thin the red banner.
    vintage = {"CCC": {"what": data_vintage.FIRST, "partition": "2024-03-25"}}
    red = grade_parity.compare(
        record, report, LAST, full_history, {**same, "vintage": vintage}
    )
    assert red["mode"] == grade_parity.PARITY
    assert "data_vintage" not in red
    assert red["mismatches"] == before["mismatches"]


# Mixed: of three drifting names only the one whose own data changed is
# explained; a grade flip with no data change keeps its row, and a
# membership row is never put down to a data update even when the name's
# data changed too.
def test_parity_mixed_explains_only_names_whose_data_changed(tmp_path, fff_history):
    report = _report()
    record = _record(report)
    record["grades"]["CCC"]["grade"] = "B"
    record["grades"]["DDD"]["grade"] = "C"
    vintage = {
        "CCC": {"what": data_vintage.MORE, "partition": "2024-03-25"},
        "FFF": {"what": data_vintage.FIRST, "partition": "2024-03-25"},
    }
    context = {
        "record_code": "abc1234",
        "replay_code": "abc1234",
        "moved_inputs": ["edgar_tone/asof=2024-03-25"],
        "vintage": vintage,
    }
    result = grade_parity.compare(record, report, LAST, fff_history, context)
    marks = {
        (m["kind"], m.get("ticker")): m.get("explained") for m in result["mismatches"]
    }
    assert marks[(grade_parity.GRADE, "CCC")] is True
    assert marks[(grade_parity.GRADE, "DDD")] is None
    assert marks[(grade_parity.MEMBERSHIP, "FFF")] is None
    assert result["data_vintage"]["names"] == ["CCC"]
    assert sorted(result["data_vintage"]["changes"]) == ["CCC", "FFF"]


# A membership history admitting every fixture name, as the parity tests
# have it: the point-in-time book on the last session is the board.
@pytest.fixture
def full_history(tmp_path):
    path = tmp_path / "membership_history.csv"
    rows = ["ticker,entered,entry_announced,exited,exit_announced,source,rule"]
    for t in NAMES:
        rows.append(f"{t},2016-01-04,2016-01-04,,,test,member throughout")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# The membership history with FFF gone, as the parity tests have it.
@pytest.fixture
def fff_history(tmp_path):
    path = tmp_path / "membership_history_fff.csv"
    rows = ["ticker,entered,entry_announced,exited,exit_announced,source,rule"]
    for t in NAMES[:-1]:
        rows.append(f"{t},2016-01-04,2016-01-04,,,test,member throughout")
    rows.append("FFF,2016-01-04,2016-01-04,2023-07-03,2023-07-03,test,leaves mid-2023")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# The CLI path end to end: a record on disk, a later partition giving CCC
# its first release reading, the desk faked to the fixture. The stored row
# explains CCC, the CLI prints the board's line and still exits 3 (drift).
def test_cli_reads_the_data_change_from_the_store(
    tmp_path, monkeypatch, capsys, full_history
):
    report = _report()
    record = _record(report)
    record["grades"]["CCC"]["grade"] = "B"
    record["written"] = "2024-03-22T21:05:00+00:00"
    market_daily.save(tmp_path, record)
    monkeypatch.setattr(market_daily, "desk_report", lambda store, asof: report)
    store = MarketStore(tmp_path)
    at = datetime(2024, 3, 22, 20, 0, tzinfo=UTC)
    _both(store, date(2024, 3, 22), "CCC", [], [], at)
    _both(store, date(2024, 3, 25), "CCC", [_release("C-1", "2023-11-02")], [], None)
    args = ["--root", str(tmp_path), "--membership", str(full_history)]
    assert market_grade_parity.main(args) == market_grade_parity.DRIFT
    out = capsys.readouterr().out
    line = (
        "CCC: grade recomputed after its earnings releases were read for the first "
        f"time (data update after the {LAST} record)"
    )
    assert f"  data update: {line}" in out
    stored = grade_parity.for_session(tmp_path, LAST)
    assert stored["data_vintage"]["names"] == ["CCC"]
    assert stored["mismatches"][0]["explained"] is True
    assert "edgar_tone/asof=2024-03-25" in stored["moved_inputs"]


# The nightly carries the block on the record against the previous record,
# prints what it found, and never raises: a store it cannot read leaves the
# record without the block and says so.
def test_the_nightly_carries_the_block_and_never_raises(tmp_path, monkeypatch, capsys):
    store = MarketStore(tmp_path)
    _both(store, BEFORE, "ARM", [], [], EARLIER)
    _both(store, AFTER, "ARM", [_release("R-1", "2025-07-30")], [], LATER)
    previous = {
        "session": "2026-09-30",
        "written": WRITTEN.isoformat(),
        "grades": {"ARM": {"grade": "C"}},
    }
    path = market_daily.record_path(tmp_path, "2026-09-30")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(previous), encoding="utf-8")
    core = {"session": "2026-10-01", "grades": {"ARM": {"grade": "B"}}}
    block = market_daily._data_vintage(store, core, None)
    assert block["names"] == ["ARM"]
    out = capsys.readouterr().out
    assert "data vintage since 2026-09-30: earnings data changed for ARM" in out
    assert "ARM: grade recomputed after its earnings releases were read" in out
    assert (
        market_daily._data_vintage(store, {**core, "session": "2026-09-29"}, None)
        is None
    )
    assert "no earlier record" in capsys.readouterr().out

    def boom(*args, **kwargs):
        raise OSError("store unreadable")

    monkeypatch.setattr(data_vintage, "since_previous", boom)
    assert market_daily._data_vintage(store, core, None) is None
    assert (
        "data vintage: skipped (OSError: store unreadable)" in capsys.readouterr().out
    )
