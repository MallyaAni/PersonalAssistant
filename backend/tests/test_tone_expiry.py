"""A stale release-tone reading ages by the coverage check's own rule, point in time.

`tone_expiry` (study A5, `docs/research/tone-expiry-plan-2026-10-01.md`)
judges each (session, name) reading by its age against the name's usual gap
between releases - its own median gap with four or more releases, else the
book's - computed only from releases dated on or before the session, through
`release_coverage`'s own functions. A5-hard treats a reading older than 1.5 x
that gap as missing; A5-decay shrinks it linearly to neutral between 1.0 x
and 2.0 x. The tone tables here are synthetic `ToneRecord`s; the stores are
stubs that hand back the frames the tone layer writes.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import plainly, sentiment
from backend.market import language
from backend.market import release_coverage as rc
from backend.market import tone_expiry as te
from backend.market.panel import Panel


# Business days from `start`, `count` of them.
def _sessions(start: date, count: int) -> list[date]:
    days, d = [], start
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


# `count` dates `step` days apart from `start`.
def _every(start: date, step: int, count: int) -> list[date]:
    return [start + timedelta(days=step * k) for k in range(count)]


# One scored release on `reaction`, with the given guidance and demand tone.
def _record(
    ticker: str, reaction: date, guidance: float = 1.0, demand: float = 0.5
) -> language.ToneRecord:
    return language.ToneRecord(
        accession=f"{ticker}-{reaction}",
        reaction_date=reaction,
        guidance=guidance,
        demand=demand,
        pricing=-0.5,
        capex=0.0,
        supply_constrained=0.0,
        summary="A results release.",
        model="deepseek-v4-flash",
        prompt_version="release_tone/3",
        truncated=False,
    )


# A panel over `days` holding `tickers` plus SPY, prices a gentle random walk.
def _panel(days: list[date], tickers: tuple[str, ...], seed: int = 0) -> Panel:
    rng = np.random.default_rng(seed)
    names = tuple(tickers) + ("SPY",)
    shape = (len(days), len(names))
    close = 100.0 * np.exp(rng.normal(0.0003, 0.015, size=shape).cumsum(axis=0))
    return Panel(
        dates=np.array(days, dtype="datetime64[D]"),
        tickers=names,
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=np.full(shape, 1e6),
        themes={t: ("ai",) for t in tickers},
        benchmark="SPY",
    )


# The store a desk reads, stubbed: each ticker's tone frame as the tone layer
# writes it (`language.tone_frame`), nothing else.
class _Store:
    # Hold {ticker: records}.
    def __init__(self, records):
        self.records = records

    # The newest tone frame of a ticker, or None.
    def read_frame(self, kind, ticker, asof=None):
        rows = self.records.get(ticker)
        if kind != language.TONE_KIND or not rows:
            return None
        return language.tone_frame(rows), {}


# A book of three: REG reports every 91 days throughout; SHORT has only two
# releases (its gap is the book's); LATE reports every 91 days, then stops.
@pytest.fixture
def book():
    days = {
        "REG": _every(date(2023, 1, 24), 91, 9),
        "SHORT": [date(2023, 3, 1), date(2023, 6, 5)],
        "LATE": _every(date(2023, 2, 7), 91, 5),
    }
    return days


# Every reading's age, usual gap and A5-hard weight agree with the coverage
# check's own verdict at every session: the board's "overdue" and the
# study's expiry are one rule (reading the check's code, not a copy of it).
def test_the_horizon_is_the_coverage_checks_overdue_rule_at_every_session(book):
    sessions = _sessions(date(2023, 1, 2), 520)
    tickers = ("LATE", "REG", "SHORT")
    found = te.ages(sessions, tickers, book)
    hard = te.weights(found, te.HARD)
    states = set()
    for t, session in enumerate(sessions):
        counted = {k: [d for d in v if d <= session] for k, v in book.items()}
        usual = rc.book_cadence(counted.values())
        for j, ticker in enumerate(tickers):
            reading = rc.Reading(
                releases=tuple(sorted(set(counted[ticker]))),
                scored=frozenset(),
                newest_scored=None,
                filings=(),
                read_since=None,
            )
            entry = rc.assess(reading, session, usual, None)
            states.add(entry["state"])
            if entry["state"] == rc.NO_READING:
                assert np.isnan(found.age[t, j])
                assert hard[t, j] == 1.0
                continue
            assert found.age[t, j] == entry["days_since"]
            assert found.last_read[t, j] == np.datetime64(entry["last_read"])
            if entry["cadence_days"] is None:
                assert np.isnan(found.cadence[t, j])
                assert hard[t, j] == 1.0
                continue
            assert found.cadence[t, j] == entry["cadence_days"]
            assert bool(found.own[t, j]) == (entry["cadence_from"] == "own")
            assert (hard[t, j] == 0.0) == (entry["state"] == rc.OVERDUE)
    # Not vacuous: the replay saw names with no reading, ok and overdue.
    assert {rc.NO_READING, rc.OK, rc.OVERDUE} <= states


# A release dated after a session never counts at it: not for the reading's
# age, the name's own gap or the book's gap. Adding a late release to one
# name and a whole new name after the session leaves every number at and
# before the session as it was, and changes them after.
def test_a_release_dated_after_the_session_never_counts(book):
    sessions = _sessions(date(2023, 1, 2), 400)
    cut = date(2023, 11, 15)
    later = dict(book)
    later["LATE"] = [*book["LATE"], date(2023, 11, 20)]
    later["NEW"] = _every(date(2023, 11, 16), 30, 6)
    tickers = ("LATE", "REG", "SHORT", "NEW")
    before = te.ages(sessions, tickers, book)
    after = te.ages(sessions, tickers, later)
    calendar = np.array(sessions, dtype="datetime64[D]")
    upto = calendar <= np.datetime64(cut)
    for field in ("age", "cadence", "own", "last_read"):
        a, b = getattr(before, field)[upto], getattr(after, field)[upto]
        if field == "last_read":
            assert np.array_equal(a.astype("int64"), b.astype("int64"))
        else:
            assert np.array_equal(a, b, equal_nan=field != "own")
    for mode in te.MODES:
        assert np.array_equal(
            te.weights(before, mode)[upto], te.weights(after, mode)[upto]
        )
    # Not vacuous: after the cut the late release and the new name move them.
    rest = ~upto
    assert not np.array_equal(
        before.age[rest][:, 0], after.age[rest][:, 0], equal_nan=True
    )
    assert np.isfinite(after.age[rest][:, 3]).any()


# The usual gap is the name's own median once four releases count, and the
# book's median of every pooled gap before that - switching on the very
# session the fourth release counts.
def test_the_usual_gap_is_the_names_own_from_four_releases_else_the_books():
    days = {
        "A": [
            date(2023, 1, 10),
            date(2023, 4, 20),
            date(2023, 7, 10),
            date(2023, 10, 30),
        ],
        "B": _every(date(2022, 1, 10), 80, 10),
    }
    sessions = [date(2023, 10, 27), date(2023, 10, 30), date(2023, 11, 1)]
    found = te.ages(sessions, ("A", "B"), days)
    pooled_before = rc.book_cadence(
        [d for d in v if d <= sessions[0]] for v in days.values()
    )
    # Three releases on 10-27: the book's gap.
    assert not found.own[0, 0]
    assert found.cadence[0, 0] == pooled_before
    # The fourth counts on 10-30: the name's own median (100, 81, 112 -> 100).
    assert found.own[1, 0]
    assert found.cadence[1, 0] == rc.own_cadence(days["A"]) == 100
    assert found.age[1, 0] == 0
    assert found.age[2, 0] == 2
    # B has ten releases 80 days apart: its own gap is 80 throughout.
    assert np.all(found.own[:, 1])
    assert np.all(found.cadence[:, 1] == 80)


# The arithmetic on a name whose own gap is 100 days: A5-hard keeps the
# reading up to 150 days and treats it as missing from 151; A5-decay keeps
# it whole to 100 days, scales it by 2 - age/100 to 200, and treats it as
# missing from 200. Applied to the tone block, the ten fields scale with the
# weight, the indicator stays on while the weight is above 0, and a weight
# of 0 is exactly the missing-reading fill.
def test_hard_and_decay_arithmetic_and_the_block_they_make():
    releases = _every(date(2022, 1, 1), 100, 5)
    last = releases[-1]
    ages_wanted = (0, 100, 150, 151, 175, 199, 200, 250)
    sessions = [last + timedelta(days=a) for a in ages_wanted]
    found = te.ages(sessions, ("X",), {"X": releases})
    assert list(found.age[:, 0]) == list(ages_wanted)
    assert np.all(found.cadence[:, 0] == 100)
    hard = te.weights(found, te.HARD)[:, 0]
    decay = te.weights(found, te.DECAY)[:, 0]
    assert list(hard) == [1, 1, 1, 0, 0, 0, 0, 0]
    np.testing.assert_allclose(decay, [1, 1, 0.5, 0.49, 0.25, 0.01, 0, 0])
    tone = np.zeros((len(sessions), 1, language.FEATURE_COUNT), dtype=np.float32)
    names = language.FEATURE_NAMES
    tone[:, 0, names.index("tone_guidance")] = 1.0
    tone[:, 0, names.index("tone_demand")] = -0.5
    tone[:, 0, names.index("tone_guidance_change")] = 0.5
    tone[:, 0, names.index("has_tone")] = 1.0
    out = te.apply(tone, decay[:, None])
    assert out.dtype == np.float32
    np.testing.assert_allclose(
        out[:, 0, names.index("tone_guidance")], decay, rtol=1e-6
    )
    np.testing.assert_allclose(
        out[:, 0, names.index("tone_demand")], -0.5 * decay, rtol=1e-6
    )
    np.testing.assert_allclose(
        out[:, 0, names.index("tone_guidance_change")], 0.5 * decay, rtol=1e-6
    )
    assert list(out[:, 0, te.HAS_TONE]) == [1, 1, 1, 1, 1, 1, 0, 0]
    gone = out[6:, 0, :]
    assert np.array_equal(gone, np.zeros_like(gone))
    hard_block = te.apply(tone, hard[:, None])
    assert list(hard_block[:, 0, te.HAS_TONE]) == [1, 1, 1, 0, 0, 0, 0, 0]
    assert np.array_equal(hard_block[:3], tone[:3])
    with pytest.raises(ValueError, match="unknown tone expiry"):
        te.weights(found, "soft")


# The null test's path: an infinite horizon gives every reading weight 1
# under either arm, and the block that comes out is the block that went in
# to the bit (negative zeros and float32 included); with the flag off the
# loader hands back the very array `tone_features` made.
def test_the_null_reproduces_the_block_to_the_bit(book, monkeypatch):
    sessions = _sessions(date(2023, 1, 2), 520)
    tickers = ("LATE", "REG", "SHORT")
    found = te.ages(sessions, tickers, book)
    for mode in te.MODES:
        assert np.all(te.weights(found, mode, null=True) == 1.0)
        assert np.any(te.weights(found, mode) < 1.0)
    panel = _panel(sessions, tickers)
    records = {t: [_record(t, d, guidance=-1.0) for d in book[t]] for t in tickers}
    tone = language.tone_features(panel, records)
    tone[:, :, 7] = -0.0
    assert te.on_load(tone, panel, records) is tone
    for mode in te.MODES:
        monkeypatch.setattr(te, "TONE_EXPIRY", mode)
        monkeypatch.setattr(te, "TONE_EXPIRY_NULL", True)
        same = te.on_load(tone, panel, records)
        assert same is not tone
        assert same.dtype == tone.dtype
        assert same.tobytes() == tone.tobytes()
        monkeypatch.setattr(te, "TONE_EXPIRY_NULL", False)
        assert te.on_load(tone, panel, records).tobytes() != tone.tobytes()


# An expired reading takes the path a name with no reading takes: the
# block's row is the row the tone layer makes when the name never had the
# release, so the analyst's scores on that session are identical; the name
# has no score, no conviction and nothing to cite, its held stance relaxes
# to neutral after the persistence, and the board's reason drops the line.
def test_an_expired_reading_takes_the_missing_reading_path():
    sessions = _sessions(date(2022, 1, 3), 700)
    rng = np.random.default_rng(3)
    tickers = tuple(f"N{k:02d}" for k in range(24))
    records = {}
    for k, ticker in enumerate(tickers):
        stop = 4 if ticker == "N05" else 13
        records[ticker] = [
            _record(
                ticker, d, float(rng.choice([-1, 0, 1])), float(rng.choice([-1, 0, 1]))
            )
            for d in _every(date(2021, 11, 1) + timedelta(days=3 * k), 91, stop)
        ]
    # N05 is bullish on its last release, so its stance has something to lose.
    records["N05"][-1] = _record("N05", records["N05"][-1].reaction_date, 1.0, 1.0)
    panel = _panel(sessions, tickers)
    found = te.ages(panel.dates, panel.tickers, te.histories(records), "SPY")
    hard = te.weights(found, te.HARD)
    column = panel.index("N05")
    expired = np.flatnonzero(hard[:, column] == 0)
    assert len(expired) > 50
    assert np.all(np.diff(expired) == 1)
    block = te.apply(language.tone_features(panel, records), hard)
    others = {t: r for t, r in records.items() if t != "N05"}
    missing = language.tone_features(panel, others)
    assert np.array_equal(block[expired], missing[expired])
    aged = sentiment.opine(block)
    never = sentiment.opine(missing)
    assert np.array_equal(aged.scores[expired], never.scores[expired], equal_nan=True)
    assert np.all(np.isnan(aged.scores[expired, column]))
    assert np.all(np.isnan(aged.conviction()[expired, column]))
    first = int(expired[0])
    assert aged.cite(first, column) == {}
    assert aged.cite(first - 1, column)
    stances = aged.stances()
    assert np.all(stances[expired[2:], column] == 0)
    view = {
        "stances": {"sentiment": int(stances[first, column])},
        "evidence": {"sentiment": aged.cite(first, column)},
    }
    assert plainly.reason(view) == "No analyst had a view on it today."


# The plan's words for the board's grade detail, exactly: the expired line
# (the coverage note's facts and rounding), the weighted-down line (the
# release's own words, then its age and weight, never the shrunk number),
# the weight shown between 1% and 99%, and no advice word anywhere.
def test_the_board_words_are_the_plans():
    expired = te.expired_words("·", date(2025, 3, 25), 555, 91, own=False)
    assert expired == (
        "· Sentiment: no current earnings reading (last release read "
        "2025-03-25, 555 days ago; usually every 91 days across the book)"
    )
    weighted = te.weighted_words(
        "+ Sentiment: upbeat on outlook; upbeat on demand",
        date(2026, 6, 14),
        109,
        91,
        True,
        2.0 - 109 / 91,
    )
    assert weighted == (
        "+ Sentiment: upbeat on outlook; upbeat on demand (release read "
        "2026-06-14, 109 days ago, usually every 91 days; weighted 80% for its age)"
    )
    assert "92 days" in te.expired_words("+", date(2026, 1, 2), 200, 91.5, own=True)
    assert "weighted 1% " in te.weighted_words(
        "x", date(2026, 1, 2), 199, 100, True, 0.001
    )
    assert "weighted 99% " in te.weighted_words(
        "x", date(2026, 1, 2), 101, 100, True, 0.999
    )
    for text in (expired, weighted):
        assert not set(re.findall(r"[a-z]+", text.lower())) & set(te.ADVICE)


# The desk's tone loader applies the flag and nothing else: off, it returns
# `tone_features`' own block; on, the aged block; an unknown mode is refused;
# and the strict path the expectations-gap learner reads is untouched. The
# loader lives beside the torch models, so this runs where torch does.
def test_the_desk_loader_applies_the_flag_and_nothing_else(book, monkeypatch):
    pytest.importorskip("torch")
    from backend.market import model

    sessions = _sessions(date(2023, 1, 2), 520)
    tickers = ("LATE", "REG", "SHORT")
    panel = _panel(sessions, tickers)
    records = {t: [_record(t, d) for d in book[t]] for t in tickers}
    store = _Store(records)
    plain = language.tone_features(panel, records)
    strict = language.tone_features(panel, records, strict_before_session=True)
    assert np.array_equal(model.load_tone_features(store, panel), plain)
    found = te.ages(panel.dates, panel.tickers, book, "SPY")
    for mode in te.MODES:
        monkeypatch.setattr(te, "TONE_EXPIRY", mode)
        aged = model.load_tone_features(store, panel)
        assert np.array_equal(aged, te.apply(plain, te.weights(found, mode)))
        assert not np.array_equal(aged, plain)
        again = language.tone_features(panel, records, strict_before_session=True)
        assert np.array_equal(again, strict)
    monkeypatch.setattr(te, "TONE_EXPIRY", "soft")
    with pytest.raises(ValueError, match="unknown tone expiry"):
        model.load_tone_features(store, panel)
    assert model.load_tone_features(_Store({}), panel) is None


# The tone layer's records loader reads every name's newest frame and skips
# names without one; `on_load` over what it read is the aged block under
# the flag and the block itself without it (the desk loader's two steps,
# checked where torch is absent).
def test_stored_records_and_on_load_compose_the_desk_loader(book, monkeypatch):
    # Off by default: the live desk never ages a reading.
    assert te.TONE_EXPIRY is None
    assert te.TONE_EXPIRY_NULL is False
    sessions = _sessions(date(2023, 1, 2), 520)
    tickers = ("LATE", "REG", "SHORT")
    panel = _panel(sessions, tickers)
    records = {t: [_record(t, d) for d in book[t]] for t in tickers}
    found = language.stored_records(_Store(records), panel.tickers)
    assert set(found) == set(tickers)
    assert [r.reaction_date for r in found["LATE"]] == book["LATE"]
    plain = language.tone_features(panel, found)
    assert np.array_equal(plain, language.tone_features(panel, records))
    assert te.on_load(plain, panel, found) is plain
    monkeypatch.setattr(te, "TONE_EXPIRY", te.HARD)
    aged = te.on_load(plain, panel, found)
    expected = te.weights(te.ages(panel.dates, panel.tickers, book, "SPY"), te.HARD)
    assert np.array_equal(aged, te.apply(plain, expected))
    assert language.stored_records(_Store({}), panel.tickers) == {}


# Reaction dates are read as the coverage check reads them (a date, a
# datetime or ISO text), duplicates collapsed; the benchmark is never aged
# and its dates never join the book's gap.
def test_histories_and_the_benchmark():
    records = {
        "A": [
            _record("A", date(2023, 1, 5)),
            _record("A", date(2023, 1, 5)),
            _record("A", datetime(2023, 4, 5, 13, 0)),
            _record("A", "2023-07-05"),
        ]
    }
    assert te.histories(records) == {
        "A": (date(2023, 1, 5), date(2023, 4, 5), date(2023, 7, 5))
    }
    days = {
        "A": [date(2023, 1, 5), date(2023, 4, 5)],
        "SPY": _every(date(2022, 1, 3), 7, 60),
    }
    sessions = [date(2023, 5, 1)]
    with_spy = te.ages(sessions, ("A", "SPY"), days, benchmark="SPY")
    assert np.isnan(with_spy.age[0, 1])
    assert with_spy.cadence[0, 0] == 90
    pooled = te.ages(sessions, ("A", "SPY"), days)
    assert pooled.cadence[0, 0] == 7
