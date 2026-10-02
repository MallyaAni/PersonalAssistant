"""A5-hard on the live desk (2026-10-01): the switch, the stamp, the board's lines.

`tone_expiry.TONE_EXPIRY` is "hard" in the code itself, because the nightly
cron exports only the broker keys and no environment flag reaches it. Every
record stamps the mode it was decided under (`record_block`), the grade
parity replay reads that stamp back (`stamp_of`, `using`), and the board
shows one plain line per name whose reading the rule changed, with the
grade it was given against the grade it would have had with the reading
counted. The record block is checked against an independent rebuild: the
same synthetic desk the study's tests use, run with the flag off.
"""

from __future__ import annotations

import re

import pytest

from backend.cli import market_daily
from backend.market import tone_expiry as te
from backend.tests.test_tone_expiry_study import (
    NAMES,
    _desk,
    _opinions,
    _panel,
    _records,
    _Store,
)

ADVICE = re.compile(
    r"\b(trade|buy|sell|should|avoid|safe|consider|recommend|own|wait)\b", re.I
)


# The synthetic desk and its stub store, the study tests' own.
@pytest.fixture
def desk_run(monkeypatch):
    panel = _panel()
    monkeypatch.setattr(_Store, "records", _records())
    return panel, _desk(panel, _opinions(panel))


# The live switch is the module constant itself: HARD, never null, and the
# only modes are the study's two.
def test_the_live_desk_expires_hard_by_default():
    assert te.TONE_EXPIRY == te.HARD
    assert te.TONE_EXPIRY_NULL is False
    assert te.MODES == (te.HARD, te.DECAY)


# `using` sets both flags inside the block and puts them back however the
# block ends; an unknown mode is refused before anything changes.
def test_using_sets_and_restores_the_flags():
    with te.using(None):
        assert (te.TONE_EXPIRY, te.TONE_EXPIRY_NULL) == (None, False)
    assert (te.TONE_EXPIRY, te.TONE_EXPIRY_NULL) == (te.HARD, False)
    inside = []

    # Fail inside the block after noting the flags it saw.
    def fail():
        with te.using(te.DECAY, null=True):
            inside.append((te.TONE_EXPIRY, te.TONE_EXPIRY_NULL))
            raise RuntimeError("the block failed")

    with pytest.raises(RuntimeError):
        fail()
    assert inside == [(te.DECAY, True)]
    assert (te.TONE_EXPIRY, te.TONE_EXPIRY_NULL) == (te.HARD, False)
    with pytest.raises(ValueError, match="unknown tone expiry"):
        te.using("soft").__enter__()
    assert te.TONE_EXPIRY == te.HARD


# A record is replayed under the mode it carries: none (a record from before
# the stamp), a block without a mode or a mode of None all read as off; a
# mode this code does not know is refused rather than guessed.
def test_stamp_of_reads_the_records_mode():
    assert te.stamp_of(None) is None
    assert te.stamp_of({"session": "2026-10-01"}) is None
    assert te.stamp_of({"tone_expiry": None}) is None
    assert te.stamp_of({"tone_expiry": {"mode": None}}) is None
    assert te.stamp_of({"tone_expiry": {"mode": "hard"}}) == te.HARD
    assert te.stamp_of({"tone_expiry": {"mode": "decay"}}) == te.DECAY
    with pytest.raises(ValueError, match="not one of"):
        te.stamp_of({"tone_expiry": {"mode": "soft"}})


# The board's line says what was read, when, how old it is against which
# usual gap, what the rule did, and the grade either way - true numbers, no
# advice words - for an expired reading and a weighted-down one.
def test_record_line_states_the_reading_and_both_grades():
    entry = {
        "last_read": "2025-03-25",
        "days_since": 555,
        "cadence_days": 91.4,
        "cadence_from": "book",
        "weight": 0.0,
        "grade": "C",
        "grade_if_counted": "C",
    }
    same = te.record_line("OKLO", entry)
    assert same == (
        "Earnings tone expired: OKLO (last release read 2025-03-25, 555 days ago, "
        "usually every 91 days across the book); the reading no longer counts, "
        "graded C either way"
    )
    moved = te.record_line(
        "SIMO", {**entry, "cadence_from": "own", "grade": "B", "grade_if_counted": "A"}
    )
    assert moved.endswith(
        "usually every 91 days); the reading no longer counts, "
        "graded B; A with the reading counted"
    )
    weighted = te.record_line("ABC", {**entry, "weight": 0.004})
    assert weighted.startswith("Earnings tone weighted down: ABC (")
    assert "the reading counts at 1%, graded C either way" in weighted
    for text in (same, moved, weighted):
        assert not ADVICE.search(text)
    assert te.record_lines(None) == []
    assert te.record_lines({"ZZ": entry, "AA": entry})[0].startswith(
        "Earnings tone expired: AA"
    )


# With the flag off the record carries the mode and nothing else; with it on
# the block names exactly the names whose weight is below 1 at the last
# session, each with the report's own letter and the letter the same desk
# gives it with the flag off, rebuilt independently here - and the lines
# are the board's lines for those entries.
def test_record_block_matches_an_independent_rebuild(desk_run):
    panel, run = desk_run
    with te.using(None):
        plain = run(_Store())
        assert te.record_block(_Store(), plain) == {
            "mode": None,
            "expired": {},
            "also_moved": {},
            "lines": [],
        }
    report = run(_Store())
    block = te.record_block(_Store(), report)
    assert block["mode"] == te.HARD
    last = len(panel.dates) - 1
    records = {t: _records()[t] for t in NAMES}
    found = te.ages(panel.dates, panel.tickers, te.histories(records), panel.benchmark)
    weight = te.weights(found, te.HARD)
    expected = {
        t for c, t in enumerate(panel.tickers) if t in NAMES and weight[last, c] < 1.0
    }
    assert expected, "the synthetic book has names that stopped reporting"
    assert set(block["expired"]) == expected
    moved = 0
    for ticker, entry in block["expired"].items():
        column = panel.tickers.index(ticker)
        assert entry["weight"] == 0.0
        assert entry["last_read"] == str(found.last_read[last, column])
        assert entry["days_since"] == int(found.age[last, column])
        assert entry["days_since"] > te.HORIZON * entry["cadence_days"]
        assert entry["grade"] == report.graded.letter(last, column)
        assert entry["grade_if_counted"] == plain.graded.letter(last, column)
        moved += entry["grade"] != entry["grade_if_counted"]
    # A name whose own reading still counts but whose letter moved (the
    # analyst ranks names against each other) is named too, and only then.
    also = {
        t: {
            "grade": report.graded.letter(last, c),
            "grade_if_counted": plain.graded.letter(last, c),
        }
        for c, t in enumerate(panel.tickers)
        if t in NAMES
        and t not in expected
        and report.graded.letter(last, c) != plain.graded.letter(last, c)
    }
    assert also, "the synthetic book has a name moved by another's expiry"
    assert block["also_moved"] == also
    assert block["lines"] == te.record_lines(block["expired"]) + te.also_moved_lines(
        also
    )
    for text in te.also_moved_lines(also):
        assert text.startswith("Earnings tone expiry elsewhere in the book: ")
        assert "with the expired readings counted (its reading still counts)" in text
        assert not ADVICE.search(text)
    summary = te.summary(block)
    assert summary.startswith("tone expiry: hard; readings not counted in full: ")
    for ticker in also:
        assert ticker in summary.split("grade letter moved: ")[1]
    assert moved + len(also) > 0


# A nightly that cannot list the names still stamps the mode (the replay
# needs it) and, with the expiry on, puts one plain line on the board saying
# the list is missing; off, there is nothing to explain.
def test_unlisted_block_says_the_list_is_missing():
    on = te.unlisted_block(te.HARD, OSError("store unreadable"))
    assert on["mode"] == te.HARD
    assert on["expired"] is None
    assert len(on["lines"]) == 1
    assert "could not be listed" in on["lines"][0]
    assert not ADVICE.search(on["lines"][0])
    assert te.summary(on) == (
        "tone expiry: hard; names not listed (OSError: store unreadable)"
    )
    off = te.unlisted_block(None, OSError("x"))
    assert off["mode"] is None
    assert off["lines"] == []


# The nightly's block: printed with its lines, and a failure to list the
# names never stops the record - it stamps the mode and says so.
def test_the_nightly_records_the_block_and_never_raises(desk_run, monkeypatch, capsys):
    _panel_, run = desk_run
    report = run(_Store())
    block = market_daily._tone_expiry(_Store(), report, None)
    assert block["mode"] == te.HARD
    assert block["expired"]
    out = capsys.readouterr().out
    assert "tone expiry: hard; readings not counted in full: " in out
    for text in block["lines"]:
        assert f"  {text}" in out

    # Raise the way an unreadable store would.
    def boom(*args, **kwargs):
        raise OSError("store unreadable")

    monkeypatch.setattr(te, "record_block", boom)
    failed = market_daily._tone_expiry(_Store(), report, None)
    assert failed["mode"] == te.HARD
    assert failed["expired"] is None
    assert "names not listed (OSError: store unreadable)" in capsys.readouterr().out


# The point-in-time scorecard grades as the live desk does unless a run
# names a mode: none is the live default, "off" is the desk before A5 (the
# study's control), an arm is itself; the null test refuses "off".
def test_the_scorecard_defaults_to_the_live_mode():
    from backend.cli import market_pit_scorecard as sc

    assert sc._expiry_mode(None) == te.TONE_EXPIRY == te.HARD
    assert sc._expiry_mode(sc.OFF) is None
    assert sc._expiry_mode(te.DECAY) == te.DECAY
    with pytest.raises(SystemExit):
        sc.main(["--tone-expiry", "off", "--null-test"])
