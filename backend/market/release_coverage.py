"""Whether each book name's earnings releases are still being read.

The sentiment analyst grades a name from the tone of its scored earnings
releases (`edgar_tone`, read point in time), and `language.tone_features`
carries a reading forward until the next release is read. Two ways that
breaks make no noise anywhere:

1. a foreign filer joins the book without being on the Form 6-K allow-list
   (`edgar.RESULTS_6K_ISSUERS`): it never has an earnings filing on file, so
   it never gets a reading;
2. a filer changes its press-release layout or exhibit naming, so the 6-K
   classifier or the 8-K exhibit reader stops admitting its releases (or it
   stops furnishing results under item 2.02 at all): its last reading is
   carried forward, quarter after quarter.

This check looks at every book name at the record's session, from the stored
earnings filings (`edgar_events`) and release readings (`edgar_tone`) in the
newest partition on or before the desk's own `asof` (None: the newest, as
tonight's desk reads them), counting only filings and releases the market
could react to by the session - a release dated after the session is not
counted, as `tone_features` does not use it for that session either - and
gives each name one state:

* **no reading** - no scored release at all: no earnings filing on file
  (failure 1, or a name the filings layer has never held), or filings on
  file and none read;
* **unscored** - its newest earnings filing is newer than its newest scored
  release, is not one of the scored releases, and has gone unread for
  longer than the reader's normal lag (below); "no release text found in
  it" when the reader has run for the name since the filing and stored no
  score for it (an 8-K whose exhibits the reader does not recognise - the
  8-K side of failure 2 - or a 2.02 filing that carries no release),
  "not read yet" when it has not;
* **overdue** - the days since its newest scored release exceed TOLERANCE
  times its usual gap: its own median gap between consecutive scored
  releases when it has OWN_HISTORY or more of them, else the median of every
  such gap in the book (failure 2 on either path);
* **unchecked** - its stored data could not be read; one such name never
  stops the rest;
* **ok** otherwise.

The reader's normal lag is measured from the store, never assumed: for each
book name whose newest scored release was filed on or after the name's
first stored reading (so the store saw it arrive), the days from its filing
date to the first partition holding its score; the median over the book.
Read on the live store on 2026-10-01 (read-only), three releases qualified -
ADBE and ORCL filed 2026-09-10, MU 2026-09-30 - and each was scored in the
partition of its own filing date: a lag of 0 days, so a filing still unread
the night after it was filed is unscored. Until the store has seen a release
arrive the lag is unknown and no filing is called unscored; the overdue clock
still runs.

Nothing here changes a grade, a score or an order: the block is evidence on
the record, printed by the nightly and shown on the board as plain lines.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime
from typing import Any

from backend.market import edgar, language
from backend.market.language import TONE_KIND
from backend.market.store import MarketStore

EVENTS_KIND = "edgar_events"

# How far past its usual gap a name's newest reading may age before it is
# overdue: the only tuning constant in this check. Measured read-only on the
# live store on 2026-10-01 (94 book names, 3,452 gaps between consecutive
# scored releases of 93 names; NBIS has none): the gaps run p5 60, p25 86,
# median 91, p75 93, p95 105, p99 126 days. Against each name's own median
# (3,450 gaps of the 92 names with four or more releases) a gap is a median
# 1.00 of it, p90 1.08, p95 1.15, p99 1.38: an ordinary quarter, and the
# annual-report quarter that runs long (49 gaps between 1.25 and 1.40), stay
# under 1.4. Then the distribution is nearly empty - 2 gaps between 1.40 and
# 1.50, 3 between 1.50 and 1.75 - before the 27 above 1.75, which are
# releases missing from the store: ASML's fourth-quarter 6-Ks the old
# classifier refused (a 182-day gap every year), TSM 2020, SIMO, NXPI's five
# unread 8-Ks of 2019-20, AMAT's 2024-05 release. 1.5 sits in that valley:
# above 99% of ordinary gaps and below one missed release (about 2.0), which
# at a 91-day cadence it flags 46 days after the release was due.
TOLERANCE = 1.5
# The fewest scored releases a name's own cadence is read from (three gaps,
# so the median is never one or two gaps); fewer falls back to the book's.
OWN_HISTORY = 4

OK = "ok"
NO_READING = "no_reading"
UNSCORED = "unscored"
OVERDUE = "overdue"
UNCHECKED = "unchecked"
# The order the board's lines are written in.
ORDER = (NO_READING, UNSCORED, OVERDUE, UNCHECKED)

NO_FILING = "no earnings filing on file"
NONE_READ = "earnings filings on file, none read"
NO_TEXT = "no release text found in it"
NOT_YET = "not read yet"
UNREADABLE = "stored earnings data could not be read"


@dataclass(frozen=True, slots=True)
class Filing:
    """One earnings filing as the check reads it."""

    accession: str
    filed: _date
    reaction: _date


@dataclass(frozen=True, slots=True)
class Reading:
    """One name's earnings filings and release readings as of a session."""

    # Distinct reaction dates of its scored releases on or before the
    # session, oldest first.
    releases: tuple[_date, ...]
    # Every accession its reading holds a score for.
    scored: frozenset[str]
    # The accession of its newest scored release on or before the session.
    newest_scored: str | None
    # Its earnings filings the market could react to by the session, oldest
    # first.
    filings: tuple[Filing, ...]
    # The newest partition holding its reading (on or before the as-of).
    read_since: _date | None


# A stored date cell as a date: a date, a datetime, or ISO text. Anything
# else (None, a malformed string) raises, and the name is not checked.
def _day(value: object) -> _date:
    """Return `value` as a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    return _date.fromisoformat(str(value)[:10])


# Pure: a name's own usual gap between releases, the median of the gaps
# between consecutive scored releases, or None with fewer than OWN_HISTORY.
def own_cadence(releases: Iterable[_date]) -> float | None:
    """Return the median gap in days between consecutive releases, or None."""
    days = sorted(set(releases))
    if len(days) < OWN_HISTORY:
        return None
    return statistics.median(_gaps(days))


# Pure: the days between consecutive dates of a sorted list.
def _gaps(days: list[_date]) -> list[int]:
    """Return the gaps in days between consecutive dates."""
    return [(b - a).days for a, b in zip(days, days[1:], strict=False)]


# Pure: the median of every gap between consecutive scored releases across
# the book, the usual gap of a name with too short a history; None when the
# book holds no two releases of one name.
def book_cadence(histories: Iterable[Iterable[_date]]) -> float | None:
    """Return the median gap in days pooled over every name's releases, or None."""
    gaps: list[int] = []
    for releases in histories:
        gaps.extend(_gaps(sorted(set(releases))))
    return statistics.median(gaps) if gaps else None


# One name's filings and readings from the newest partitions on or before
# `asof`, point in time at `session`: a release or filing the market could
# first react to after the session is left out. Raises on a frame it cannot
# read; the caller records the name as unchecked.
def read_name(
    store: MarketStore, ticker: str, session: _date, asof: _date | None
) -> Reading:
    """Return the name's Reading as of `session`."""
    tone = store.read_frame(TONE_KIND, ticker, asof)
    events = store.read_frame(EVENTS_KIND, ticker, asof)
    rows = language.records_from_frame(tone[0]) if tone else ()
    dated = [(_day(r.reaction_date), str(r.accession)) for r in rows]
    counted = sorted(d for d in dated if d[0] <= session)
    filings = sorted(
        (
            Filing(str(e.accession), _day(e.filed), e.reaction_date)
            for e in (edgar.events_from_columns(events[0]) if events else [])
        ),
        key=lambda f: (f.reaction, f.filed, f.accession),
    )
    return Reading(
        releases=tuple(sorted({d for d, _ in counted})),
        scored=frozenset(a for _, a in dated),
        newest_scored=counted[-1][1] if counted else None,
        filings=tuple(f for f in filings if f.reaction <= session),
        read_since=store._latest_of_kind(TONE_KIND, ticker, asof),
    )


# The dates of every partition of `kind` on or before `asof`, oldest first.
def _partitions(store: MarketStore, kind: str, asof: _date | None) -> list[_date]:
    """Return the kind's partition dates up to `asof`."""
    from backend.market.store import _partition_date

    base = store.root / kind
    if not base.exists():
        return []
    found = (_partition_date(p.name) for p in base.iterdir() if p.is_dir())
    return sorted(d for d in found if d and (asof is None or d <= asof))


# The reader's lag on one name, when the store saw its newest scored release
# arrive: the days from that release's filing date to the first partition
# holding its score. None when the release was filed before the name's
# first stored reading (a backfill, or a name new to the store), or its
# filing is not on file.
def release_lag(
    store: MarketStore, ticker: str, reading: Reading, partitions: Sequence[_date]
) -> int | None:
    """Return the days the reader took over the name's newest scored release."""
    if reading.newest_scored is None:
        return None
    filed = next(
        (f.filed for f in reading.filings if f.accession == reading.newest_scored),
        None,
    )
    if filed is None:
        return None
    held = [p for p in partitions if store.has_frame(TONE_KIND, p, ticker)]
    if not held or filed < held[0]:
        return None
    for partition in held:
        if partition < filed:
            continue
        found = store.read_frame(TONE_KIND, ticker, partition)
        if found and reading.newest_scored in {
            str(a) for a in found[0].get("accession") or []
        }:
            return (partition - filed).days
    return None


# Pure: one name's state at the session, with the facts behind it. `book` is
# the book's usual gap (the fallback cadence) and `lag` the reader's normal
# lag in days (None when the store has not seen a release arrive).
def assess(
    reading: Reading, session: _date, book: float | None, lag: float | None
) -> dict[str, Any]:
    """Return the name's entry: its state, reason and the dates behind them."""
    last = reading.releases[-1] if reading.releases else None
    newest = reading.filings[-1] if reading.filings else None
    own = own_cadence(reading.releases)
    cadence = own if own is not None else book
    entry: dict[str, Any] = {
        "state": OK,
        "reason": None,
        "last_read": last.isoformat() if last else None,
        "releases": len(reading.releases),
        "filings": len(reading.filings),
        "newest_filing": newest.filed.isoformat() if newest else None,
        "cadence_days": None,
        "cadence_from": None,
        "days_since": None,
    }
    if last is None:
        entry["state"] = NO_READING
        entry["reason"] = NONE_READ if reading.filings else NO_FILING
        return entry
    since = (session - last).days
    entry["days_since"] = since
    if cadence is not None:
        entry["cadence_days"] = cadence
        entry["cadence_from"] = "own" if own is not None else "book"
    if (
        newest is not None
        and newest.accession not in reading.scored
        and newest.reaction > last
        and lag is not None
        and (session - newest.filed).days > lag
    ):
        seen = reading.read_since is not None and reading.read_since >= newest.filed
        entry["state"] = UNSCORED
        entry["reason"] = NO_TEXT if seen else NOT_YET
        return entry
    if cadence is not None and since > TOLERANCE * cadence:
        entry["state"] = OVERDUE
    return entry


# A cadence in whole days for the board, rounded half up.
def _whole(days: float) -> int:
    """Return `days` rounded to the nearest whole day."""
    return int(days + 0.5)


# Pure: the board's plain lines for the flagged names, one kind at a time
# (no reading, unscored, overdue, unchecked), names in alphabetical order.
# Names that share a reason share a line where the line has no per-name
# dates. Statements of fact only, no advice.
def lines(names: dict[str, dict[str, Any]]) -> list[str]:
    """Return the lines the board shows for `names` (ok names have none)."""
    out: list[str] = []
    grouped: dict[str, list[str]] = {}
    for ticker in sorted(names):
        entry = names[ticker]
        if entry.get("state") == NO_READING:
            grouped.setdefault(str(entry.get("reason")), []).append(ticker)
    for reason in (NO_FILING, NONE_READ):
        if grouped.get(reason):
            out.append(f"No earnings reading: {', '.join(grouped[reason])} ({reason})")
    for ticker in sorted(names):
        entry = names[ticker]
        if entry.get("state") == UNSCORED:
            out.append(
                f"Earnings filing not read: {ticker} (filed {entry['newest_filing']}, "
                f"{entry['reason']}; last release read {entry['last_read']})"
            )
    for ticker in sorted(names):
        entry = names[ticker]
        if entry.get("state") == OVERDUE:
            book = " across the book" if entry.get("cadence_from") == "book" else ""
            out.append(
                f"Earnings reading overdue: {ticker} (last release read "
                f"{entry['last_read']}, usually every "
                f"{_whole(entry['cadence_days'])} days{book})"
            )
    unchecked = [t for t in sorted(names) if names[t].get("state") == UNCHECKED]
    if unchecked:
        out.append(
            f"Earnings reading not checked: {', '.join(unchecked)} ({UNREADABLE})"
        )
    return out


# Every book name's state at `session`, from the store as of `asof` (None:
# the newest partitions, as tonight's desk reads them), with the book's usual
# gap and the reader's normal lag the states were judged by, and the board's
# lines. Reads only; one name that cannot be read is recorded as unchecked
# and never stops the rest.
def check(
    store: MarketStore,
    tickers: Iterable[str],
    session: object,
    asof: _date | None = None,
) -> dict[str, Any]:
    """Return the record's `release_coverage` block for `tickers`."""
    day = _day(session)
    partitions = _partitions(store, TONE_KIND, asof)
    names: dict[str, dict[str, Any]] = {}
    readings: dict[str, Reading] = {}
    lags: list[int] = []
    for ticker in sorted(set(tickers)):
        try:
            reading = read_name(store, ticker, day, asof)
            lag = release_lag(store, ticker, reading, partitions)
        except Exception as exc:  # noqa: BLE001 - one name never stops the rest
            names[ticker] = _unchecked(exc)
            continue
        readings[ticker] = reading
        if lag is not None:
            lags.append(lag)
    book = book_cadence(r.releases for r in readings.values())
    normal = statistics.median(lags) if lags else None
    for ticker, reading in readings.items():
        try:
            names[ticker] = assess(reading, day, book, normal)
        except Exception as exc:  # noqa: BLE001 - one name never stops the rest
            names[ticker] = _unchecked(exc)
    names = dict(sorted(names.items()))
    return {
        "session": day.isoformat(),
        "tolerance": TOLERANCE,
        "book_cadence_days": book,
        "read_lag_days": normal,
        "read_lag_releases": len(lags),
        "checked": len(names),
        "flagged": [t for t, e in names.items() if e["state"] != OK],
        "lines": lines(names),
        "names": names,
    }


# The entry of a name whose stored data could not be read, with the error.
def _unchecked(exc: Exception) -> dict[str, Any]:
    """Return an unchecked entry carrying the exception's type and message."""
    return {
        "state": UNCHECKED,
        "reason": UNREADABLE,
        "error": f"{type(exc).__name__}: {exc}",
    }


# Pure: the one-line summary the nightly prints above the board's lines.
def summary(block: dict[str, Any]) -> str:
    """Return the `release coverage:` log line for a block."""
    book = block.get("book_cadence_days")
    lag = block.get("read_lag_days")
    usual = f"{_whole(book)} days" if book is not None else "unknown"
    read = (
        f"{lag:g} days ({block.get('read_lag_releases', 0)} releases)"
        if lag is not None
        else "unknown (no release seen arriving)"
    )
    flagged = ", ".join(block.get("flagged") or []) or "none"
    return (
        f"release coverage: {block.get('checked', 0)} names at {block.get('session')}; "
        f"usual gap {usual} across the book; read lag {read}; flagged: {flagged}"
    )
