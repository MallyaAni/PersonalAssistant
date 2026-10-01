"""Every book name's earnings reading is checked, and one that went stale says so.

`release_coverage` reads each book name's stored earnings filings
(`edgar_events`) and release readings (`edgar_tone`) point in time at the
record's session and flags a name with no reading at all, a newest filing
the reader has left unread past its normal lag (measured from the store),
or a newest reading older than 1.5 times its usual gap (its own median gap
with four or more releases, else the book's, computed). The stores here are
synthetic and written the way the nightly writes them: immutable `asof=`
partitions of the two kinds. The nightly carries the block on the record,
prints it, and never fails because of it.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from backend.cli import market_daily
from backend.market import release_coverage as rc
from backend.market.language import TONE_KIND
from backend.market.store import MarketStore

EVENTS = rc.EVENTS_KIND
SESSION = date(2026, 9, 30)
# The partition most stores here are written in: before every session read.
BASE = date(2026, 9, 1)
# Eight releases, one every 91 days, the last on 2026-07-28.
REGULAR = tuple(date(2024, 10, 29) + timedelta(days=91 * k) for k in range(8))
ADVICE = ("trade", "buy", "sell", "should", "avoid", "safe", "consider", "recommend")


# One release reading as the tone frame stores it: an accession, the
# session the market could react, the five scores and the reader.
def _release(accession: str, reaction: date | None) -> dict:
    return {
        "accession": accession,
        "reaction_date": reaction,
        "guidance": 0.5,
        "demand": 0.25,
        "pricing": 0.0,
        "capex": 0.0,
        "supply_constrained": 0.0,
        "summary": "A results release.",
        "model": "deepseek-v4-flash",
        "prompt_version": "release_tone/3",
        "truncated": False,
    }


# One earnings filing as the events frame stores it: accepted at 10:00 UTC
# (before the open in New York) unless `at` says otherwise.
def _filing(
    accession: str, filed: date, form: str = "8-K", at: str = "10:00:00"
) -> dict:
    return {
        "accepted": f"{filed.isoformat()}T{at}+00:00",
        "filed": filed,
        "accession": accession,
        "items": "2.02,9.01" if form == "8-K" else "",
        "form": form,
    }


# Rows to the column frame `write_frame` takes; no rows is an empty frame
# with the kind's columns, which is what the store holds for a name with none.
def _columns(rows: list[dict], kind: str) -> dict[str, list]:
    keys = (
        list(_release("x", date(2020, 1, 1)))
        if kind == TONE_KIND
        else list(_filing("x", date(2020, 1, 1)))
    )
    return {k: [r[k] for r in rows] for k in keys}


# Write one name's frame of one kind into one partition.
def _put(store: MarketStore, kind: str, asof: date, ticker: str, rows: list) -> None:
    assert store.write_frame(kind, asof, ticker, _columns(rows, kind))


# The accession a name's filing on `day` carries in these stores.
def _acc(ticker: str, day: date) -> str:
    return f"{ticker}-{day.isoformat()}"


# One name's filings and readings in one partition: a filing on each of
# `filed`, a scored release for each of `scored` (default: every filing).
def _name(store, asof, ticker, filed, scored=None, form="8-K") -> None:
    scored = filed if scored is None else scored
    filings = [_filing(_acc(ticker, d), d, form) for d in filed]
    _put(store, EVENTS, asof, ticker, filings)
    _put(store, TONE_KIND, asof, ticker, [_release(_acc(ticker, d), d) for d in scored])


# A regular reporter is not flagged: its own usual gap is 91 days and its
# newest reading is 64 days old. The entry carries the facts behind that.
def test_a_regular_reporter_is_not_flagged(tmp_path):
    store = MarketStore(tmp_path)
    _name(store, BASE, "NVDA", REGULAR)
    block = rc.check(store, ["NVDA"], SESSION)
    assert block["flagged"] == []
    assert block["lines"] == []
    assert block["names"]["NVDA"] == {
        "state": rc.OK,
        "reason": None,
        "last_read": "2026-07-28",
        "releases": 8,
        "filings": 8,
        "newest_filing": "2026-07-28",
        "cadence_days": 91,
        "cadence_from": "own",
        "days_since": 64,
    }
    assert block["session"] == "2026-09-30"
    assert block["tolerance"] == 1.5
    assert block["book_cadence_days"] == 91
    json.dumps(block)


# Overdue: the newest release a classifier stopped admitting is missing from
# both kinds, so the newest reading is 2026-04-28. Past 1.5 times its own
# 91-day gap (136.5 days) it is overdue, at 136 days it is not.
def test_a_reading_older_than_its_usual_gap_allows_is_overdue(tmp_path):
    store = MarketStore(tmp_path)
    _name(store, BASE, "ASML", REGULAR[:-1])
    last = REGULAR[-2]
    assert rc.check(store, ["ASML"], last + timedelta(days=136))["flagged"] == []
    block = rc.check(store, ["ASML"], last + timedelta(days=137))
    assert block["flagged"] == ["ASML"]
    assert block["names"]["ASML"]["state"] == rc.OVERDUE
    block = rc.check(store, ["ASML"], SESSION)
    assert block["names"]["ASML"]["days_since"] == 155
    assert block["lines"] == [
        "Earnings reading overdue: ASML (last release read 2026-04-28, "
        "usually every 91 days)"
    ]


# A name with no earnings filing on file - a foreign filer not on the 6-K
# allow-list, with empty frames, or a name the filings layer never held -
# has no reading; they share one line.
def test_a_name_with_no_earnings_filing_has_no_reading(tmp_path):
    store = MarketStore(tmp_path)
    _name(store, BASE, "NBIS", ())
    _name(store, BASE, "NVDA", REGULAR)
    block = rc.check(store, ["NVDA", "NBIS", "NEWCO"], SESSION)
    assert block["flagged"] == ["NBIS", "NEWCO"]
    assert block["names"]["NBIS"]["state"] == rc.NO_READING
    assert block["names"]["NEWCO"]["reason"] == rc.NO_FILING
    assert block["lines"] == [
        "No earnings reading: NBIS, NEWCO (no earnings filing on file)"
    ]


# Filings on file and none read (an empty reading, or none stored at all) is
# a name with no reading too, said differently.
def test_filings_with_no_scored_release_are_no_reading(tmp_path):
    store = MarketStore(tmp_path)
    _name(store, BASE, "XYZ", REGULAR[-3:], scored=())
    _put(store, EVENTS, BASE, "ABC", [_filing("ABC-1", REGULAR[-1])])
    block = rc.check(store, ["XYZ", "ABC"], SESSION)
    assert block["names"]["XYZ"]["state"] == rc.NO_READING
    assert block["names"]["XYZ"]["filings"] == 3
    assert block["lines"] == [
        "No earnings reading: ABC, XYZ (earnings filings on file, none read)"
    ]


# Fewer than four releases: the name is judged by the median of every gap in
# the book, computed - here 98 days, not the 91 a typed-in default would
# give. At 140 days it is within 1.5 x 98 = 147; at 148 days it is overdue,
# and the line says the cadence is the book's.
def test_a_short_history_falls_back_to_the_books_computed_usual_gap(tmp_path):
    store = MarketStore(tmp_path)
    for ticker in ("AAA", "BBB"):
        steps = tuple(date(2026, 4, 20) - timedelta(days=98 * k) for k in range(6))
        _name(store, BASE, ticker, sorted(steps))
    short = (date(2025, 6, 2), date(2025, 9, 3), date(2026, 1, 2))
    _name(store, BASE, "OKLO", short)
    block = rc.check(store, ["AAA", "BBB", "OKLO"], short[-1] + timedelta(days=140))
    assert block["book_cadence_days"] == 98
    oklo = block["names"]["OKLO"]
    assert (oklo["state"], oklo["cadence_days"], oklo["cadence_from"]) == (
        rc.OK,
        98,
        "book",
    )
    block = rc.check(store, ["AAA", "BBB", "OKLO"], short[-1] + timedelta(days=148))
    assert block["flagged"] == ["OKLO"]
    assert block["lines"] == [
        "Earnings reading overdue: OKLO (last release read 2026-01-02, "
        "usually every 98 days across the book)"
    ]


# One name whose stored filings cannot be parsed, and one whose reading has
# a release with no date, are unchecked - with the error kept - while every
# other name is judged as usual; they share one line.
def test_a_malformed_name_does_not_stop_the_rest(tmp_path):
    store = MarketStore(tmp_path)
    _name(store, BASE, "GOOD", REGULAR)
    _name(store, BASE, "OLD", REGULAR[:-2])
    bad = _filing("BAD-1", REGULAR[-1])
    bad["accepted"] = "not a time"
    _put(store, EVENTS, BASE, "BAD", [bad])
    _put(store, TONE_KIND, BASE, "BAD", [_release("BAD-1", REGULAR[-1])])
    _put(store, EVENTS, BASE, "NODATE", [_filing("N-1", REGULAR[-1])])
    _put(
        store,
        TONE_KIND,
        BASE,
        "NODATE",
        [_release("N-0", REGULAR[-2]), _release("N-1", None)],
    )
    block = rc.check(store, ["GOOD", "BAD", "NODATE", "OLD"], SESSION)
    states = {t: e["state"] for t, e in block["names"].items()}
    assert states == {
        "BAD": rc.UNCHECKED,
        "GOOD": rc.OK,
        "NODATE": rc.UNCHECKED,
        "OLD": rc.OVERDUE,
    }
    assert block["names"]["BAD"]["error"].startswith("ValueError")
    assert block["lines"][-1] == (
        "Earnings reading not checked: BAD, NODATE "
        "(stored earnings data could not be read)"
    )
    assert block["checked"] == 4


# Point in time: a release filed after the close on the session day reacts
# the next day, so it is neither the newest reading nor the newest filing at
# the session (`tone_features` does not use it either); a partition dated
# after the as-of is never read, while the newest partitions are what the
# nightly's own desk reads (as-of None).
def test_point_in_time_a_release_after_the_session_is_not_counted(tmp_path):
    store = MarketStore(tmp_path)
    late = date(2026, 9, 30)
    filings = [_filing(_acc("MU", d), d) for d in REGULAR]
    filings.append(_filing(_acc("MU", late), late, at="20:30:00"))
    releases = [_release(_acc("MU", d), d) for d in REGULAR]
    releases.append(_release(_acc("MU", late), late + timedelta(days=1)))
    _put(store, EVENTS, SESSION, "MU", filings)
    _put(store, TONE_KIND, SESSION, "MU", releases)
    entry = rc.check(store, ["MU"], SESSION)["names"]["MU"]
    assert (entry["last_read"], entry["newest_filing"], entry["releases"]) == (
        "2026-07-28",
        "2026-07-28",
        8,
    )
    assert (
        rc.check(store, ["MU"], SESSION + timedelta(days=1))["names"]["MU"]["last_read"]
        == "2026-10-01"
    )
    # A re-read admitted an old release into a partition after the as-of.
    _name(store, BASE, "SIMO", REGULAR[:-1])
    _name(store, date(2026, 10, 2), "SIMO", REGULAR)
    assert rc.check(store, ["SIMO"], SESSION, asof=SESSION)["flagged"] == ["SIMO"]
    newest = rc.check(store, ["SIMO"], SESSION)["names"]["SIMO"]
    assert (newest["state"], newest["last_read"]) == (rc.OK, "2026-07-28")


# The reader's lag measured on the store: two releases filed inside the
# store's window were each scored in the partition of their filing date
# (lag 0). WDAY's newest filing was read the night it was filed and holds no
# release text; LATE's has not been read since it was filed. Both are
# unscored the session after; on the filing's own session WDAY is not.
def test_a_filing_left_unread_past_the_measured_lag_is_unscored(tmp_path):
    store = MarketStore(tmp_path)
    start = date(2026, 9, 21)
    for ticker in ("REG", "REG2", "WDAY", "LATE"):
        _name(store, start, ticker, REGULAR)
    _name(store, date(2026, 9, 23), "REG", REGULAR + (date(2026, 9, 23),))
    _name(store, date(2026, 9, 24), "REG2", REGULAR + (date(2026, 9, 24),))
    wday = date(2026, 9, 29)
    _name(store, wday, "WDAY", REGULAR + (wday,), scored=REGULAR)
    late = date(2026, 9, 28)
    filings = [_filing(_acc("LATE", d), d) for d in REGULAR + (late,)]
    _put(store, EVENTS, late, "LATE", filings)
    names = ["REG", "REG2", "WDAY", "LATE"]
    block = rc.check(store, names, SESSION)
    assert (block["read_lag_days"], block["read_lag_releases"]) == (0, 2)
    assert block["flagged"] == ["LATE", "WDAY"]
    assert block["names"]["WDAY"]["reason"] == rc.NO_TEXT
    assert block["names"]["LATE"]["reason"] == rc.NOT_YET
    assert block["lines"] == [
        "Earnings filing not read: LATE (filed 2026-09-28, not read yet; "
        "last release read 2026-07-28)",
        "Earnings filing not read: WDAY (filed 2026-09-29, no release text found "
        "in it; last release read 2026-07-28)",
    ]
    on_the_day = rc.check(store, ["REG", "REG2", "WDAY"], wday)
    assert on_the_day["names"]["WDAY"]["state"] == rc.OK


# The same filing read against a slower reader: releases scored two days
# after they were filed make the normal lag 2, so a filing two days unread
# is not flagged and three days unread is. The threshold is the store's.
def test_the_unscored_threshold_follows_the_measured_lag(tmp_path):
    store = MarketStore(tmp_path)
    start = date(2026, 9, 14)
    for ticker in ("REG", "REG2", "SLOW"):
        _name(store, start, ticker, REGULAR)
    for ticker, filed in (("REG", date(2026, 9, 21)), ("REG2", date(2026, 9, 22))):
        _name(store, filed, ticker, REGULAR + (filed,), scored=REGULAR)
        _name(store, filed + timedelta(days=2), ticker, REGULAR + (filed,))
    slow = date(2026, 9, 28)
    _name(store, slow, "SLOW", REGULAR + (slow,), scored=REGULAR)
    block = rc.check(store, ["REG", "REG2", "SLOW"], slow + timedelta(days=2))
    assert (block["read_lag_days"], block["flagged"]) == (2, [])
    block = rc.check(store, ["REG", "REG2", "SLOW"], slow + timedelta(days=3))
    assert block["flagged"] == ["SLOW"]


# Until the store has seen a release arrive (every stored release was filed
# before the name's first stored reading) the lag is unknown and no filing is
# called unscored; the summary line says so.
def test_without_a_release_seen_arriving_the_lag_is_unknown(tmp_path):
    store = MarketStore(tmp_path)
    _name(store, BASE, "REG", REGULAR)
    filed = date(2026, 8, 20)
    _name(store, BASE, "WDAY", REGULAR + (filed,), scored=REGULAR)
    block = rc.check(store, ["REG", "WDAY"], SESSION)
    assert (block["read_lag_days"], block["read_lag_releases"]) == (None, 0)
    assert block["flagged"] == []
    assert rc.summary(block) == (
        "release coverage: 2 names at 2026-09-30; usual gap 91 days across the "
        "book; read lag unknown (no release seen arriving); flagged: none"
    )


# The board's words state facts only: no word of advice in any kind of line.
def test_lines_carry_no_advice():
    names = {
        "AAA": {"state": rc.NO_READING, "reason": rc.NO_FILING},
        "BBB": {"state": rc.NO_READING, "reason": rc.NONE_READ},
        "CCC": {
            "state": rc.UNSCORED,
            "reason": rc.NO_TEXT,
            "newest_filing": "2026-09-29",
            "last_read": "2026-08-28",
        },
        "DDD": {
            "state": rc.OVERDUE,
            "last_read": "2025-03-25",
            "cadence_days": 91.5,
            "cadence_from": "book",
        },
        "EEE": {"state": rc.UNCHECKED, "reason": rc.UNREADABLE},
        "FFF": {"state": rc.OK},
    }
    text = rc.lines(names)
    assert len(text) == 5
    assert "usually every 92 days across the book" in text[3]
    for line in text:
        for word in ADVICE:
            assert word not in line.lower()


# The nightly prints the block and carries it, and never raises: a store it
# cannot read, or a block it cannot print, leaves the record without it and
# says so.
def test_the_nightly_prints_the_block_and_never_raises(tmp_path, monkeypatch, capsys):
    store = MarketStore(tmp_path)
    _name(store, BASE, "NVDA", REGULAR)
    core = {"session": "2026-09-30", "grades": {"NVDA": {}, "NBIS": {}}}
    block = market_daily._release_coverage(store, core, None)
    assert block["flagged"] == ["NBIS"]
    out = capsys.readouterr().out
    assert "release coverage: 2 names at 2026-09-30; usual gap 91 days" in out
    assert "  No earnings reading: NBIS (no earnings filing on file)" in out

    # Raise the way an unreadable store would.
    def boom(*args, **kwargs):
        raise OSError("store unreadable")

    monkeypatch.setattr(rc, "check", boom)
    assert market_daily._release_coverage(store, core, None) is None
    assert "release coverage: skipped (OSError: store unreadable)" in (
        capsys.readouterr().out
    )
    monkeypatch.undo()
    monkeypatch.setattr(rc, "summary", boom)
    assert market_daily._release_coverage(store, core, None) is None


# A membership history admitting every fixture name, as the parity tests
# have it, so the nightly's parity check passes on the fixture desk.
@pytest.fixture
def members(tmp_path):
    from backend.tests.test_market_pit_scorecard import NAMES

    path = tmp_path / "membership_history.csv"
    rows = ["ticker,entered,entry_announced,exited,exit_announced,source,rule"]
    for t in NAMES:
        rows.append(f"{t},2016-01-04,2016-01-04,,,test,member throughout")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# The nightly end to end on the fixture desk, as the parity tests run it,
# into `root`; returns the saved record.
def _nightly(root, monkeypatch, members) -> dict:
    import sys

    from backend.cli import market_economics
    from backend.market import grade_parity, learned_inputs
    from backend.tests.test_grade_parity import LAST
    from backend.tests.test_market_pit_scorecard import _report

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
    monkeypatch.setattr(market_daily, "enrich_prose", lambda *a, **k: ("skipped", "t"))
    monkeypatch.setattr(learned_inputs, "capture", lambda *a, **k: "skipped")
    monkeypatch.setattr(market_economics, "refresh_if_current", lambda *a, **k: None)
    monkeypatch.setattr(grade_parity, "_history", lambda history_path: members)
    monkeypatch.setattr(sys, "argv", ["market_daily", "--data-dir", str(root)])
    market_daily.main()
    return json.loads(market_daily.record_path(root, LAST).read_text())


# The record is written whatever the check does, and the check moves no
# grade, score, target or action: a run whose check fails writes the same
# decision as one whose check succeeds, with `release_coverage` None.
def test_the_record_is_written_and_unchanged_when_the_check_fails(
    tmp_path, monkeypatch, capsys, members
):
    checked = _nightly(tmp_path / "a", monkeypatch, members)
    assert checked["release_coverage"]["checked"] == len(checked["grades"])
    assert "release coverage: " in capsys.readouterr().out

    # Raise the way an unreadable store would.
    def boom(*args, **kwargs):
        raise OSError("store unreadable")

    monkeypatch.setattr(rc, "check", boom)
    failed = _nightly(tmp_path / "b", monkeypatch, members)
    out = capsys.readouterr().out
    assert failed["release_coverage"] is None
    assert "release coverage: skipped (OSError: store unreadable)" in out
    assert "record written" in out
    for key in ("grades", "targets", "book", "actions", "levels"):
        assert failed[key] == checked[key]
