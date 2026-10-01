"""Which names' stored earnings data changed between a record and a later reading.

A grade can move for two different reasons: the market moved, or the store's
view of the past changed - an earnings release read for the first time, more
of a name's old releases admitted, a release re-scored. The second is a
data-vintage change, not news: on 2026-09-30 22:20 ET ARM, ASML, SIMO and TSM
got release tone for the first time (Form 6-K), after that evening's record,
and the next record graded them on it; on 2026-10-01 20:05 ET the widened 6-K
classifier re-read NBIS, ASML, SIMO and TSM again. Nothing on the board said
why those grades moved.

**The signal is point in time.** The store is immutable (`store.py`): a
ticker's frame of a kind is written once per dated partition and never
modified, and `read_frame(kind, ticker, d)` returns exactly what a run on `d`
saw. So "this name's stored release tone or filings changed since the record
for session `d`" is `read_frame(kind, t, d)` against the frame read now (the
newest, or the replay's own as-of), for the two kinds that carry it,
`edgar_tone` and `edgar_events`, compared by content:

* a release or filing dated after `d` is new data, not a vintage change;
* a past one (reaction or filing date on or before `d`) that was not there
  is a vintage change - read for the first time when the name had no release
  reading at all, else more of its releases read;
* the same accession with a different score, prompt version, model,
  reaction session or release figure is a re-read; an accession gone is a
  drop; a filing is compared as the desk reads it (its reaction session,
  filing date, items and form), never by the raw acceptance text;
* the nightly's own re-fetch with the same content is no change at all.

Replayed over the 18 live records of 2026-09-04 to 09-30 it is empty on
ordinary nights and names exactly the known updates: every name's releases
read for the first time (09-08), the `release_tone/2` and `/3` re-scores
(09-11, 09-14 to 09-16), GLW's first reading (09-21), WDAY's 8-K moved past
the close (09-30), and ARM, ASML, SIMO, TSM after the 6-K backfill.

The comparison is decided by partition dates, as `tone_revisions` does, not
by file times: a store copied without its modification times must never make
every name read as "read for the first time". File times only ever withhold a
claim - a newer partition whose file was already on disk when the record was
written was read by that record, so it is not "after" it.

What it is used for, in `explain`: a name whose grade moved (the parity
replay's letter against the record's, or tonight's record against the
previous one) *and* whose own stored earnings data changed in between gets a
plain line saying so. That is coincidence in time, stated as such, never a
claim that the data update alone moved the grade; a name whose grade moved
with no change in its own data is left to whatever the board already says.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as _date

from backend.market.language import TONE_KIND

EVENTS_KIND = "edgar_events"
KINDS = (TONE_KIND, EVENTS_KIND)
# The fields of a release reading that feed the desk: the five tone scores,
# the reader that produced them and the release figures `release_facts` folds
# into the fundamental layer. The summary is prose and is not compared.
TONE_FIELDS = (
    "reaction_date",
    "guidance",
    "demand",
    "pricing",
    "capex",
    "supply_constrained",
    "prompt_version",
    "model",
    "revenue_usd_m",
    "eps_usd",
    "net_income_usd_m",
    "gross_margin_pct",
)
# What the desk reads from an earnings filing: the session the market could
# first react (`EarningsEvent.reaction_date`, from the acceptance time in New
# York), the filing date, the items and the form. The raw acceptance time is
# not compared: CIEN's 2011-2012 8-Ks were stored five hours apart on
# 2026-09-21 and back on 09-23, both before the open, which no grade can see;
# WDAY's 2026-09-29 8-K moved from 12:01 to 16:01 New York on 09-30, which
# moves its reaction to the next session and is a change.
EVENT_FIELDS = ("reaction_date", "filed", "items", "form")
# What changed, in the order the lines are written; one phrase each, for one
# name and for several.
FIRST = "first"
MORE = "more"
REREAD = "reread"
DROPPED = "dropped"
FILINGS = "filings"
ORDER = (FIRST, MORE, REREAD, DROPPED, FILINGS)
PHRASES = {
    FIRST: (
        "its earnings releases were read for the first time",
        "their earnings releases were read for the first time",
    ),
    MORE: (
        "more of its earnings releases were read",
        "more of their earnings releases were read",
    ),
    REREAD: (
        "its earnings releases were re-read",
        "their earnings releases were re-read",
    ),
    DROPPED: (
        "some of its earnings releases were dropped",
        "some of their earnings releases were dropped",
    ),
    FILINGS: (
        "its earnings filings were re-read",
        "their earnings filings were re-read",
    ),
}


# A cell as comparable text: dates and datetimes by their ISO form, numbers
# to the tolerance below, None as None.
def _text(value) -> str | None:
    """Return `value` as a comparable string, or None."""
    if value is None:
        return None
    if isinstance(value, (datetime, _date)):
        return value.isoformat()
    return str(value)


# Two cells differ: numbers beyond 1e-9 (a NaN never equals anything but a
# NaN), anything else by its text.
def _differs(a, b) -> bool:
    """Return True when the two stored values are not the same."""
    if a is None or b is None:
        return (a is None) != (b is None)
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return _text(a) != _text(b)
    if x != x or y != y:
        return (x != x) != (y != y)
    return abs(x - y) > 1e-9


# One stored frame as {accession: row}; a frame without accessions is empty.
# A release reading is compared as stored; an earnings filing as the desk
# reads it (`edgar.events_from_columns`), so its row is the reaction session,
# the filing date, the items and the form.
def _rows(columns: dict | None, kind: str = TONE_KIND) -> dict[str, dict]:
    """Return the frame's rows keyed by accession."""
    columns = columns or {}
    if kind == EVENTS_KIND:
        from backend.market import edgar

        return {
            str(e.accession): {
                "reaction_date": e.reaction_date,
                "filed": e.filed,
                "items": e.items,
                "form": e.form,
            }
            for e in edgar.events_from_columns(columns)
        }
    accessions = list(columns.get("accession") or [])
    out: dict[str, dict] = {}
    for i, accession in enumerate(accessions):
        out[str(accession)] = {
            k: (v[i] if i < len(v) else None) for k, v in columns.items()
        }
    return out


# The rows of the ticker's frame of `kind` in exactly one partition; a
# partition that does not hold it reads as no rows.
def _read(store, kind: str, ticker: str, partition: _date | None) -> dict[str, dict]:
    """Return {accession: row} from that partition's frame."""
    if partition is None:
        return {}
    found = store.read_frame(kind, ticker, partition)
    return _rows(found[0], kind) if found is not None else {}


# Whether the newest frame's file was already on disk when the record was
# written: then that record read it, and nothing in it is "after" the record.
# Only ever withholds a claim; a store whose file times were lost claims as
# the dates alone decide.
def _on_disk_before(store, kind: str, ticker: str, partition: _date, written) -> bool:
    """Return True when the partition's file predates `written`."""
    if written is None:
        return False
    try:
        stamp = store._path(kind, partition, ticker).stat().st_mtime
    except OSError:
        return False
    return datetime.fromtimestamp(stamp, tz=UTC) <= written


# The record's `written` timestamp as an aware datetime, or None.
def written_at(record: dict | None) -> datetime | None:
    """Return when `record` was written, or None when it does not say."""
    try:
        written = datetime.fromisoformat(str((record or {}).get("written")))
    except (TypeError, ValueError):
        return None
    return written if written.tzinfo else written.replace(tzinfo=UTC)


# What changed between two readings of one kind for one name, or None when
# nothing did. `cut` is the earlier record's session: a release or filing
# the market could first react to after it is new data and never counts.
# Returns the counts that decide the phrase.
def compare_rows(
    kind: str, before: dict[str, dict], after: dict[str, dict], cut: _date
) -> dict | None:
    """Return {"before", "after", "added", "reread", "dropped"} or None."""
    fields = TONE_FIELDS if kind == TONE_KIND else EVENT_FIELDS
    limit = cut.isoformat()
    added = [
        a
        for a, row in after.items()
        if a not in before and (_text(row.get("reaction_date")) or "")[:10] <= limit
    ]
    dropped = [a for a in before if a not in after]
    reread = [
        a
        for a, row in after.items()
        if a in before
        and any(
            f in row and f in before[a] and _differs(row[f], before[a][f])
            for f in fields
        )
    ]
    if not (added or dropped or reread):
        return None
    return {
        "before": len(before),
        "after": len(after),
        "added": len(added),
        "reread": len(reread),
        "dropped": len(dropped),
    }


# The phrase one name's changes earn: the release reading first (it is what
# the sentiment vote and the release figures read), the filings only when the
# reading itself did not change.
def what_changed(tone: dict | None, events: dict | None) -> str | None:
    """Return FIRST, MORE, REREAD, DROPPED, FILINGS or None."""
    if tone:
        if tone["added"] and tone["before"] == 0:
            return FIRST
        if tone["added"]:
            return MORE
        if tone["reread"]:
            return REREAD
        if tone["dropped"]:
            return DROPPED
    if events:
        return FILINGS
    return None


# Every name among `tickers` whose release reading or earnings filings
# changed between the reading as of `cut` (the record's session) and the
# reading as of `asof` (None: the newest). `written` is the record's own
# timestamp: a newer partition already on disk then was that record's input,
# not a change after it. A name that cannot be read is a name without a
# change; this never raises for one name.
def changes(
    store,
    tickers,
    cut: _date,
    asof: _date | None = None,
    written: datetime | None = None,
) -> dict[str, dict]:
    """Return {ticker: {"what", "partition", kind: counts}} for changed names."""
    out: dict[str, dict] = {}
    for ticker in sorted(set(tickers)):
        try:
            found = _changes_for(store, ticker, cut, asof, written)
        except Exception:  # noqa: BLE001 - one unreadable name never stops the rest
            continue
        if found:
            out[ticker] = found
    return out


# One name's changes across both kinds, or None.
def _changes_for(store, ticker: str, cut: _date, asof, written) -> dict | None:
    """Return the name's change block, or None when its data did not change."""
    per_kind: dict[str, dict] = {}
    partitions: list[str] = []
    for kind in KINDS:
        # The partition each reading resolves to; the same one is the same
        # immutable file, so nothing is read unless they differ.
        now = store._latest_of_kind(kind, ticker, asof)
        then = store._latest_of_kind(kind, ticker, cut)
        if now is None or now == then:
            continue
        if _on_disk_before(store, kind, ticker, now, written):
            continue
        found = compare_rows(
            kind,
            _read(store, kind, ticker, then),
            _read(store, kind, ticker, now),
            cut,
        )
        if found:
            per_kind[kind] = found
            partitions.append(now.isoformat())
    what = what_changed(per_kind.get(TONE_KIND), per_kind.get(EVENTS_KIND))
    if what is None:
        return None
    return {"what": what, "partition": max(partitions), **per_kind}


# The plain lines for the names whose grade moved and whose own earnings data
# changed since the record for `since`: one line per kind of change, names in
# alphabetical order, "grade"/"its" for one name and "grades"/"their" for
# several. No advice, no claim beyond the two facts and their order in time.
def lines(names, found: dict[str, dict], since: str) -> list[str]:
    """Return the board's lines for `names` (those absent from `found` are skipped)."""
    groups: dict[str, list[str]] = {}
    for ticker in sorted(set(names)):
        what = (found.get(ticker) or {}).get("what")
        if what in PHRASES:
            groups.setdefault(what, []).append(ticker)
    out = []
    for what in ORDER:
        group = groups.get(what)
        if not group:
            continue
        several = len(group) > 1
        out.append(
            f"{', '.join(group)}: {'grades' if several else 'grade'} recomputed "
            f"after {PHRASES[what][1 if several else 0]} "
            f"(data update after the {since} record)"
        )
    return out


# The block a record or a parity result carries: the session the comparison
# starts from, the names whose grade moved with a change in their own data,
# the lines the board shows for them, and every name whose data changed
# (moved or not) for the log and the tests.
def explain(moved, found: dict[str, dict], since: str) -> dict:
    """Return {"since", "names", "lines", "changes"} for the grade moves `moved`."""
    names = sorted({t for t in moved if t in found})
    return {
        "since": since,
        "names": names,
        "lines": lines(names, found, since),
        "changes": found,
    }


# Tonight's record against the previous one: the names whose letter moved
# between the two records and whose own earnings data changed after the
# previous record's session. None when there is no previous record to
# compare with. `asof` is the desk's own (None for tonight: the newest).
def since_previous(
    store, record: dict, previous: dict | None, asof: _date | None = None
) -> dict | None:
    """Return the record's data-vintage block against `previous`, or None."""
    if not previous or not previous.get("session"):
        return None
    since = str(previous["session"])
    grades = record.get("grades") or {}
    before = previous.get("grades") or {}
    found = changes(
        store,
        list(grades),
        _date.fromisoformat(since),
        asof,
        written_at(previous),
    )
    moved = [
        t
        for t, g in grades.items()
        if t in before
        and (g or {}).get("grade") is not None
        and (before[t] or {}).get("grade") is not None
        and (g or {}).get("grade") != (before[t] or {}).get("grade")
    ]
    return explain(moved, found, since)
