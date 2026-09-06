"""Periodic filings, how much of one a company rewrote, and why no analyst
reads it.

Cohen, Malloy and Nguyen ("Lazy Prices", Journal of Finance, 2020) report
one of the more durable anomalies in the literature. Filings are mostly
copied forward, so a company that rewrites part of one is usually doing it
for a reason, and the market is slow to read a document nobody wants to
read. Firms whose filings changed the most went on to underperform those
whose filings barely moved.

It does not reproduce on this book. **Nothing here feeds the desk.** The
collector is kept because it is cheap, tested, and the measurement below
is worth not repeating.

What was measured
-----------------
Every 10-K and 10-Q the ninety-three names filed since 2019, each compared
with the same form a year earlier: 2,274 comparisons, a median similarity
of 0.9947 and a fifth percentile of 0.9311. Coverage is not the problem -
83 of the book carry a reading on a median session.

Beta-adjusted rank IC on the similarity is +0.026 (t 1.6) at twenty
sessions and +0.048 (t 1.5) at sixty. The sign is the paper's, and neither
number clears significance. The year-on-year *change* in similarity is
nothing at all: -0.005 and +0.000.

A first look appeared to say something much stronger and in the opposite
direction - the most-rewritten fifth beating the least by 5.05% over 120
sessions at t -12.58. Both halves of that were artefacts, and both are
traps this book has fallen into before:

| horizon | measured how                        | least minus most |
| h20     | raw, overlapping windows            | -0.65% (t -5.11) |
| h20     | raw, non-overlapping                | -0.74% (t -1.27) |
| h20     | beta-adjusted, non-overlapping      | +0.35% (t +0.69) |
| h120    | raw, overlapping windows            | -5.05% (t -12.58)|
| h120    | raw, non-overlapping                | -7.82% (t -1.74) |
| h120    | beta-adjusted, non-overlapping      | +1.26% (t +0.38) |

Twenty-seven thousand observations drawn from thirteen hundred sessions
share almost all of their days, so the t-statistic describes the overlap.
And the names that rewrite their filings most are the higher-beta ones, so
in a rising market they earn more without earning anything a portfolio can
keep. Stepping the windows so none overlap costs the result its
significance; adjusting for beta reverses its sign.

Given a vote in the desk's summed conviction, the signal moves rank IC
from 0.0459 to 0.0492 at twenty sessions while dropping net Sharpe from
0.79 to 0.58. It buys a slightly better ordering and a worse portfolio.

Why it probably fails here
--------------------------
The paper works on the whole US cross-section over two decades, where most
names are small and thinly followed and the premise holds: nobody reads
the document. Ninety-three large AI-infrastructure and software companies
are not that population. Their filings are read by many analysts within
hours, so the slow-diffusion story has nothing to be slow about.

How it works
------------
The submissions document already fetched for 8-K events lists every 10-K
and 10-Q; the index and document fetchers the tone reader uses work
unchanged. A filing is reduced to its term counts, compared with the same
form a year earlier, and the text thrown away, so the store gains a few
kilobytes a name rather than gigabytes of HTML. A 10-Q meets the same
quarter of last year rather than last quarter, so a seasonal difference in
what a quarter discusses is not read as a change.

Point in time. `filing_features` fills a panel forward from the session
after the filing date, so nothing reads a document the market had not
seen, and each filing is compared only with one already public.
"""

import re
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from backend.market.edgar import Pacer, Transport, sec_transport
from backend.market.language import _get_text, html_to_text, parse_index_page
from backend.market.panel import Panel

_INDEX_PAGE_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}-index.htm"
)
_ARCHIVE_ROOT = "https://www.sec.gov"
PERIODIC_FORMS = ("10-K", "10-Q")

FEATURE_NAMES = (
    "has_filing",
    "filing_similarity",
    "filing_similarity_change",
    "sessions_since_filing",
)
FEATURE_COUNT = len(FEATURE_NAMES)
# A name that has never filed should not read as an extreme value, so the
# "sessions since" counter is clipped the same way the EDGAR one is.
NO_FILING_SESSIONS = 400
# Filings shorter than this are cover pages or stubs, not documents.
MIN_TOKENS = 500
# Words carrying no meaning for this comparison. The list is short on
# purpose: "Lazy Prices" works on raw text, and aggressive filtering
# removes exactly the boilerplate whose stability is the signal.
_WORD = re.compile(r"[a-z][a-z']{2,}")


@dataclass(frozen=True)
class PeriodicFiling:
    """One 10-K or 10-Q: what it is, when it was filed, and where it lives."""

    form: str
    filed: date
    accession: str
    period: str  # the report period the filer declared, "" when absent


@dataclass(frozen=True)
class FilingSimilarity:
    """One filing, compared with the same form a year earlier."""

    ticker: str
    form: str
    filed: date
    accession: str
    similarity: float  # cosine on term counts, 1.0 is unchanged
    compared_with: str  # the accession it was compared against
    tokens: int


# Pure: the 10-K and 10-Q filings in one submissions block, oldest first.
def parse_periodic_block(block: Mapping[str, object]) -> list[PeriodicFiling]:
    """Return the periodic filings a submissions block lists."""
    forms = list(block.get("form") or [])
    filed = list(block.get("filingDate") or [])
    accessions = list(block.get("accessionNumber") or [])
    periods = list(block.get("reportDate") or [])
    out: list[PeriodicFiling] = []
    for i, form in enumerate(forms):
        # 10-K/A and 10-Q/A are amendments and restate a filing rather than
        # continuing the series, so comparing one against a year ago
        # measures the amendment, not the year.
        if form not in PERIODIC_FORMS:
            continue
        if i >= len(filed) or i >= len(accessions):
            continue
        try:
            when = date.fromisoformat(filed[i])
        except (TypeError, ValueError):
            continue
        out.append(
            PeriodicFiling(
                form=form,
                filed=when,
                accession=str(accessions[i]),
                period=str(periods[i]) if i < len(periods) and periods[i] else "",
            )
        )
    out.sort(key=lambda f: f.filed)
    return out


# The archive URL of the filing's own primary document, or None. The index
# lists exhibits alongside it; the one whose type is the form itself is the
# document, and on newer filings its href is wrapped in the inline-XBRL
# viewer, which serves the same file.
def primary_document_href(
    documents: Sequence[tuple[str, str, str]], form: str
) -> str | None:
    """Return the href of the 10-K or 10-Q document itself."""
    wanted = form.upper()
    ranked = [d for d in documents if d[0].upper() == wanted]
    if not ranked:
        return None
    href = ranked[0][2]
    if href.startswith("/ix?doc="):
        href = href[len("/ix?doc=") :]
    return href if href.startswith("http") else _ARCHIVE_ROOT + href


# The plain text of a periodic filing, or None when the index has no
# document of that form (an occasional paper or wrapper filing).
def fetch_filing_text(
    cik: int,
    filing: PeriodicFiling,
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str | None:
    """Return the text of a 10-K or 10-Q, or None if it has no document."""
    pacer = pacer or Pacer(sleep=sleep)
    folder = filing.accession.replace("-", "")
    page = _get_text(
        _INDEX_PAGE_URL.format(cik=cik, folder=folder, accession=filing.accession),
        transport,
        pacer,
        sleep,
    )
    href = primary_document_href(parse_index_page(page), filing.form)
    if href is None:
        return None
    return html_to_text(_get_text(href, transport, pacer, sleep))


# Pure: a document reduced to the counts of the words in it. Numbers and
# punctuation go, because a filing's figures change every quarter by
# definition and would swamp the language they are wrapped in.
def term_counts(text: str) -> Counter:
    """Return the word counts of a filing's text."""
    return Counter(_WORD.findall(text.lower()))


# Pure: how alike two filings are, as the cosine of their term counts. 1.0
# is a document copied forward unchanged, 0.0 shares no vocabulary.
def cosine(a: Mapping[str, int], b: Mapping[str, int]) -> float:
    """Return the cosine similarity of two term-count maps."""
    if not a or not b:
        return float("nan")
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    dot = float(sum(count * large.get(word, 0) for word, count in small.items()))
    na = float(np.sqrt(sum(float(c) * c for c in a.values())))
    nb = float(np.sqrt(sum(float(c) * c for c in b.values())))
    if na <= 0 or nb <= 0:
        return float("nan")
    return dot / (na * nb)


# Pure: which earlier filing a filing should be compared against. A 10-K
# is compared with the previous 10-K and a 10-Q with the 10-Q from four
# quarters back, so a seasonal difference in what a quarter discusses is
# not read as a change. The most recent earlier filing of the same form
# that is at least 300 days older is the match.
def prior_filing(
    filing: PeriodicFiling, earlier: Sequence[PeriodicFiling]
) -> PeriodicFiling | None:
    """Return the filing a year or so before `filing`, or None."""
    same = [
        f
        for f in earlier
        if f.form == filing.form and 300 <= (filing.filed - f.filed).days <= 460
    ]
    return max(same, key=lambda f: f.filed) if same else None


# A company's documents, fetched once each and reduced to word counts. A
# filing EDGAR will not serve costs its own comparison and nothing else: a
# company with twenty years on file should not lose all of it because one
# document from 2017 has moved.
class _Documents:
    """Word counts per accession, fetched on demand and remembered."""

    def __init__(
        self,
        cik: int,
        transport: Transport,
        pacer: Pacer,
        sleep: Callable[[float], None],
    ) -> None:
        self._cik = cik
        self._transport = transport
        self._pacer = pacer
        self._sleep = sleep
        self._counts: dict[str, Counter] = {}
        self.failed: list[tuple[str, str]] = []

    # The word counts of one filing, or None when it cannot be read.
    def counts_for(self, filing: PeriodicFiling) -> Counter | None:
        """Return the filing's term counts, fetching it the first time."""
        if filing.accession in self._counts:
            return self._counts[filing.accession]
        try:
            text = fetch_filing_text(
                self._cik, filing, self._transport, self._pacer, self._sleep
            )
        except Exception as exc:  # one unreachable filing, not one lost name
            self.failed.append((filing.accession, str(exc)))
            return None
        if text is None:
            return None
        seen = term_counts(text)
        self._counts[filing.accession] = seen
        return seen


# Compare every periodic filing a company made with the one a year before
# it, fetching each document once. `on_record` is called as each filing is
# measured so a long run can be written down as it goes.
def measure_company(
    ticker: str,
    cik: int,
    filings: Sequence[PeriodicFiling],
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_record: Callable[[FilingSimilarity], None] | None = None,
    skip: Callable[[str], bool] | None = None,
    on_failure: Callable[[list[tuple[str, str]]], None] | None = None,
) -> list[FilingSimilarity]:
    """Return the year-on-year similarity of each of a company's filings."""
    ordered = sorted(filings, key=lambda f: f.filed)
    reader = _Documents(cik, transport, pacer or Pacer(sleep=sleep), sleep)
    out: list[FilingSimilarity] = []
    for index, filing in enumerate(ordered):
        if skip is not None and skip(filing.accession):
            continue
        earlier = prior_filing(filing, ordered[:index])
        if earlier is None:
            continue
        record = _compare(ticker, filing, earlier, reader.counts_for)
        if record is None:
            continue
        out.append(record)
        if on_record is not None:
            on_record(record)
    if reader.failed and on_failure is not None:
        on_failure(reader.failed)
    return out


# One filing against its partner, or None when either cannot be read or is
# too short to be a document.
def _compare(
    ticker: str,
    filing: PeriodicFiling,
    earlier: PeriodicFiling,
    counts_for: Callable[[PeriodicFiling], Counter | None],
) -> FilingSimilarity | None:
    now = counts_for(filing)
    before = counts_for(earlier)
    if now is None or before is None:
        return None
    total = int(sum(now.values()))
    if total < MIN_TOKENS or sum(before.values()) < MIN_TOKENS:
        return None
    return FilingSimilarity(
        ticker=ticker,
        form=filing.form,
        filed=filing.filed,
        accession=filing.accession,
        similarity=cosine(now, before),
        compared_with=earlier.accession,
        tokens=total,
    )


# --- storage ---------------------------------------------------------------


# Serialise records for the store's frames.
def similarity_frame(records: Sequence[FilingSimilarity]) -> dict[str, list]:
    """Return the frame columns for a set of similarity records."""
    ordered = sorted(records, key=lambda r: (r.ticker, r.filed, r.accession))
    return {
        "ticker": [r.ticker for r in ordered],
        "form": [r.form for r in ordered],
        "filed": [r.filed.isoformat() for r in ordered],
        "accession": [r.accession for r in ordered],
        "similarity": [float(r.similarity) for r in ordered],
        "compared_with": [r.compared_with for r in ordered],
        "tokens": [int(r.tokens) for r in ordered],
    }


# Rebuild records from a stored frame.
def records_from_frame(columns: Mapping[str, list]) -> tuple[FilingSimilarity, ...]:
    """Return the similarity records a stored frame holds."""
    rows = len(columns.get("ticker", []))
    return tuple(
        FilingSimilarity(
            ticker=str(columns["ticker"][i]),
            form=str(columns["form"][i]),
            filed=date.fromisoformat(str(columns["filed"][i])),
            accession=str(columns["accession"][i]),
            similarity=float(columns["similarity"][i]),
            compared_with=str(columns["compared_with"][i]),
            tokens=int(columns["tokens"][i]),
        )
        for i in range(rows)
    )


# --- features --------------------------------------------------------------


# Build the (T, N, FEATURE_COUNT) filing feature array for a panel. A
# filing is readable from the session after it is filed, and stays the
# name's current reading until the next one replaces it.
def filing_features(panel: Panel, records: Sequence[FilingSimilarity]) -> np.ndarray:
    """Return the filing-similarity features aligned to `panel`."""
    rows, names = panel.adj_close.shape
    out = np.zeros((rows, names, FEATURE_COUNT))
    out[:, :, FEATURE_NAMES.index("sessions_since_filing")] = NO_FILING_SESSIONS
    by_ticker: dict[str, list[FilingSimilarity]] = {}
    for record in records:
        by_ticker.setdefault(record.ticker, []).append(record)
    stamps = panel.dates.astype("datetime64[D]")
    for ticker, items in by_ticker.items():
        try:
            column = panel.index(ticker)
        except (KeyError, ValueError):
            continue
        items = sorted(items, key=lambda r: r.filed)
        previous = float("nan")
        for i, record in enumerate(items):
            if not np.isfinite(record.similarity):
                continue
            # The session after the filing date: the first one on which a
            # reader could have had the document.
            start = int(np.searchsorted(stamps, np.datetime64(record.filed), "right"))
            if start >= rows:
                continue
            stop = rows
            for later in items[i + 1 :]:
                nxt = int(np.searchsorted(stamps, np.datetime64(later.filed), "right"))
                if nxt > start:
                    stop = min(stop, nxt)
                    break
            out[start:stop, column, FEATURE_NAMES.index("has_filing")] = 1.0
            out[start:stop, column, FEATURE_NAMES.index("filing_similarity")] = (
                record.similarity
            )
            change = record.similarity - previous if np.isfinite(previous) else 0.0
            out[start:stop, column, FEATURE_NAMES.index("filing_similarity_change")] = (
                change
            )
            since = np.arange(stop - start, dtype=float)
            out[start:stop, column, FEATURE_NAMES.index("sessions_since_filing")] = (
                np.minimum(since, NO_FILING_SESSIONS)
            )
            previous = record.similarity
    return out
