"""A release re-read under a new prompt is a data revision, and the record names it.

PANW's Sep 2 release was scored 1.0 on guidance and demand; on 2026-09-11
the same release was re-read under `release_tone/2` as 0.8 and 0.8, and
again under `release_tone/3` on 09-15. Nothing new was filed, yet the
sentiment vote flipped in one night because the recomputed history already
held three sessions of the new reading. The grade moved on a re-read, not
on news, and the page could not say so. This compares each name's newest
release reading with the previous session's: the same accession with a
different scored field or prompt version is a revision.
"""

from datetime import date

from backend.market.language import TONE_KIND

SCORED = ("guidance", "demand", "pricing", "capex", "supply_constrained")


# The newest release row of a tone frame, by reaction date.
def newest(columns: dict) -> dict | None:
    """Return the newest row of `columns` as a dict, or None when empty."""
    n = len(columns.get("accession") or [])
    if not n:
        return None
    dates = columns.get("reaction_date") or [None] * n
    i = max(range(n), key=lambda k: (dates[k] is not None, str(dates[k]), k))
    return {k: v[i] for k, v in columns.items() if len(v) == n}


def _differs(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) > 1e-9
    except (TypeError, ValueError):
        return a != b


# The revision between two readings of the same release, or None: a new
# accession is a new release, not a revision.
def compare(now: dict | None, before: dict | None) -> dict | None:
    """Return the revision from `before` to `now`, or None."""
    if not now or not before or now.get("accession") != before.get("accession"):
        return None
    fields = {
        n: [before.get(n), now.get(n)]
        for n in SCORED
        if n in now and n in before and _differs(now[n], before[n])
    }
    versions = [before.get("prompt_version"), now.get("prompt_version")]
    if not fields and versions[0] == versions[1]:
        return None
    return {
        "accession": now["accession"],
        "reaction_date": str(now.get("reaction_date")),
        "prompt_version": versions,
        "fields": fields,
    }


# Every name whose newest release reading changed between `previous` and
# `session` without a new release. Never raises: a name that cannot be read
# is a name without a revision.
def detect(store, tickers, session: date, previous: date) -> dict[str, dict]:
    """Return {ticker: revision} for the names re-read between the sessions."""
    out: dict[str, dict] = {}
    for ticker in tickers:
        try:
            now = store.read_frame(TONE_KIND, ticker, session)
            before = store.read_frame(TONE_KIND, ticker, previous)
        except Exception:  # noqa: BLE001 - reporting must not stop the record
            continue
        if now is None or before is None:
            continue
        found = compare(newest(now[0]), newest(before[0]))
        if found:
            out[ticker] = found
    return out
