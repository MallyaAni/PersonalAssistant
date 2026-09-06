"""Filing-text change: parsing, similarity, and the point-in-time fill.

The signal is the year-on-year similarity of a company's 10-K or 10-Q to
the same form a year earlier. Two things have to be right for it to mean
anything. The comparison has to pair a filing with the right partner, and
the reading has to reach a panel only from the session after the document
was public. Both are tested here, along with the parsing and the
arithmetic underneath them.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.market import filings
from backend.market.panel import Panel

BLOCK = {
    "form": ["10-K", "8-K", "10-Q", "10-Q", "10-K/A", "10-Q", "4"],
    "filingDate": [
        "2024-02-01",
        "2024-03-01",
        "2024-05-01",
        "2024-08-01",
        "2024-09-01",
        "2024-11-01",
        "2024-12-01",
    ],
    "accessionNumber": ["a-k24", "a-8k", "a-q1", "a-q2", "a-ka", "a-q3", "a-4"],
    "reportDate": [
        "2023-12-31",
        "",
        "2024-03-31",
        "2024-06-30",
        "2023-12-31",
        "2024-09-30",
        "",
    ],
}


# Only the periodic forms are kept, amendments are not, and they come back
# oldest first whatever order the block listed them in.
def test_parse_periodic_block_keeps_only_the_filings_that_continue_a_series():
    found = filings.parse_periodic_block(BLOCK)
    assert [f.form for f in found] == ["10-K", "10-Q", "10-Q", "10-Q"]
    assert [f.accession for f in found] == ["a-k24", "a-q1", "a-q2", "a-q3"]
    assert [f.filed for f in found] == [
        date(2024, 2, 1),
        date(2024, 5, 1),
        date(2024, 8, 1),
        date(2024, 11, 1),
    ]
    assert found[0].period == "2023-12-31"
    # A block with nothing in it is not an error.
    assert filings.parse_periodic_block({}) == []


# A malformed date drops that row rather than the whole block.
def test_parse_periodic_block_survives_a_bad_row():
    bad = {
        "form": ["10-K", "10-Q"],
        "filingDate": ["not a date", "2024-05-01"],
        "accessionNumber": ["a", "b"],
        "reportDate": ["", ""],
    }
    found = filings.parse_periodic_block(bad)
    assert [f.accession for f in found] == ["b"]


# The document of the form itself is the one wanted, not the exhibits
# beside it, and the inline-XBRL wrapper resolves to the same file.
def test_primary_document_href_picks_the_filing_itself():
    documents = [
        ("EX-31.1", "cert.htm", "/Archives/x/cert.htm"),
        ("10-Q", "form10q.htm", "/ix?doc=/Archives/x/form10q.htm"),
        ("GRAPHIC", "logo.jpg", "/Archives/x/logo.jpg"),
    ]
    assert (
        filings.primary_document_href(documents, "10-Q")
        == "https://www.sec.gov/Archives/x/form10q.htm"
    )
    # A filing whose index lists no document of that form gives nothing.
    assert filings.primary_document_href(documents, "10-K") is None
    assert filings.primary_document_href([], "10-K") is None


# Words are what is counted: case is folded, numbers and punctuation go,
# and a figure that changes every quarter cannot move the comparison.
def test_term_counts_keeps_words_and_drops_figures():
    counts = filings.term_counts("Revenue was $1,234.5 million; revenue GREW 12%.")
    assert counts["revenue"] == 2
    assert counts["million"] == 1
    assert counts["grew"] == 1
    assert not any(word.isdigit() for word in counts)
    # Two-letter words are noise in a filing and are not counted.
    assert "we" not in counts


# A document copied forward unchanged scores 1, a document sharing no
# vocabulary scores 0, and an empty side has no answer rather than a zero.
def test_cosine_is_one_for_an_unchanged_filing():
    a = filings.term_counts("the company expects continued demand for its products")
    assert filings.cosine(a, a) == pytest.approx(1.0)
    b = filings.term_counts("zebra xylophone quixotic")
    assert filings.cosine(a, b) == pytest.approx(0.0)
    assert np.isnan(filings.cosine(a, {}))
    # A small change moves it a little, not a lot: filings are copied.
    c = filings.term_counts("the company expects continued demand for its services")
    assert 0.8 < filings.cosine(a, c) < 1.0


# A filing is compared with the same form about a year earlier, so a 10-Q
# meets the same quarter of last year rather than last quarter, and a
# filing with no partner in the window has none rather than a wrong one.
def test_prior_filing_pairs_a_form_with_its_own_year_earlier():
    def f(form, when, name):
        return filings.PeriodicFiling(form, date.fromisoformat(when), name, "")

    history = [
        f("10-K", "2023-02-01", "k23"),
        f("10-Q", "2023-05-01", "q1-23"),
        f("10-Q", "2023-08-01", "q2-23"),
        f("10-Q", "2023-11-01", "q3-23"),
        f("10-K", "2024-02-01", "k24"),
        f("10-Q", "2024-05-01", "q1-24"),
    ]
    assert filings.prior_filing(history[4], history[:4]).accession == "k23"
    assert filings.prior_filing(history[5], history[:5]).accession == "q1-23"
    # The first filing in a history has nothing to be compared with.
    assert filings.prior_filing(history[0], []) is None
    # Neither does one whose only same-form neighbour is last quarter.
    recent = f("10-Q", "2024-02-01", "odd")
    assert filings.prior_filing(recent, [f("10-Q", "2023-11-01", "q3-23")]) is None


# Nothing may be read on the day of the filing itself: a document filed
# after the close is not tradable until the session after it, and the
# reading then stands until the next filing replaces it.
def test_features_start_the_session_after_the_filing():
    rows = 40
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(rows)],
        dtype="datetime64[D]",
    )
    close = np.full((rows, 2), 100.0)
    panel = Panel(
        dates=dates,
        tickers=("AAA", "SPY"),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={"AAA": ()},
        benchmark="SPY",
    )
    first = filings.FilingSimilarity(
        "AAA", "10-Q", dates[10].astype(date), "b", 0.97, "a", 20_000
    )
    second = filings.FilingSimilarity(
        "AAA", "10-Q", dates[25].astype(date), "c", 0.91, "b", 21_000
    )
    features = filings.filing_features(panel, [first, second])
    has = features[:, 0, filings.FEATURE_NAMES.index("has_filing")]
    similarity = features[:, 0, filings.FEATURE_NAMES.index("filing_similarity")]
    change = features[:, 0, filings.FEATURE_NAMES.index("filing_similarity_change")]
    since = features[:, 0, filings.FEATURE_NAMES.index("sessions_since_filing")]

    # Nothing before the filing, and nothing on its own session either.
    assert has[:11].sum() == 0
    assert has[11] == 1.0
    assert similarity[11:26] == pytest.approx(0.97)
    # The second filing takes over from the session after it is filed.
    assert similarity[25] == pytest.approx(0.97)
    assert similarity[26:] == pytest.approx(0.91)
    # The first filing has no earlier reading to change from; the second
    # records the fall.
    assert change[11] == pytest.approx(0.0)
    assert change[26] == pytest.approx(0.91 - 0.97)
    # The counter climbs from the first readable session and resets.
    assert since[11] == 0.0
    assert since[12] == 1.0
    assert since[26] == 0.0
    # A name with nothing on file reads as never having filed.
    assert (
        features[:, 1, filings.FEATURE_NAMES.index("sessions_since_filing")]
        == filings.NO_FILING_SESSIONS
    ).all()
    assert features[:, 1, filings.FEATURE_NAMES.index("has_filing")].sum() == 0


# A record survives a trip through the store's frame columns unchanged.
def test_records_round_trip_through_a_frame():
    records = [
        filings.FilingSimilarity(
            "AAA", "10-K", date(2024, 2, 1), "k24", 0.9912, "k23", 44_000
        ),
        filings.FilingSimilarity(
            "BBB", "10-Q", date(2024, 5, 1), "q1", 0.9701, "q0", 21_000
        ),
    ]
    frame = filings.similarity_frame(records)
    assert frame["ticker"] == ["AAA", "BBB"]
    back = filings.records_from_frame(frame)
    assert back == tuple(records)
    assert filings.records_from_frame({"ticker": []}) == ()


# A company whose documents cannot be fetched produces no records rather
# than an exception, and a filing with no earlier partner is skipped
# without a fetch at all.
def test_measure_company_skips_what_it_cannot_pair_or_fetch():
    history = [
        filings.PeriodicFiling("10-K", date(2023, 2, 1), "k23", ""),
        filings.PeriodicFiling("10-K", date(2024, 2, 1), "k24", ""),
    ]
    fetched: list[str] = []

    def transport(url):
        fetched.append(url)
        return 404, b""

    records = filings.measure_company(
        "AAA", 1, history, transport=transport, sleep=lambda _s: None
    )
    assert records == []
    # Only the pairable filing was ever reached for.
    assert fetched, "the pairable filing should have been attempted"
