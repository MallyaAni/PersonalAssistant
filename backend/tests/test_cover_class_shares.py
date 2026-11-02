"""The cover-page class share counts: one number on the listed security.

What has to hold: the pure parser sums a single listed security's common
classes (STZ's Class A and convertible common, ERIE's Classes A and B),
reads the one undimensioned count of a single-class filer (ABT, C) or of a
utility that adds subsidiary counts beside its total (DTE, EXC, SO), takes
the listed class when every other common class is immaterial, and refuses
whenever the filing does not support one number (two listed common classes
such as BRK.A and BRK.B, a material unlisted class such as V's Class C or
ARES' Class C, a preferred class, no trading symbol, classes dated
differently, an undimensioned count beside class counts, or a common-class
count the class reader could not use); the
fetch reads the instance named by the filing index, advances a watermark
even when a structure is refused, and does not advance past a transient
fetch failure; the versions frame stores the result under the synthetic
class tag at the cover tier, so the valuation reader and the as-of levels
pick it up exactly as a standard cover count, while the standard tag wins
a tie and the weighted fallback stays out of the instant readers.
"""

import json
from datetime import UTC, date, datetime

import numpy as np
import pytest

from backend.cli import market_fundamentals_asof as cli
from backend.market import edgar, levels_pit
from backend.market import fundamentals_asof as fa

COVER = "dei:EntityCommonStockSharesOutstanding"
CLASS = edgar.CLASS_SHARES_TAG
Q = [
    ("2024-01-01", "2024-03-31", "2024-05-01"),
    ("2024-04-01", "2024-06-30", "2024-08-01"),
    ("2024-07-01", "2024-09-30", "2024-11-01"),
]

XBRL = (
    '<?xml version="1.0"?>'
    '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"'
    ' xmlns:dei="http://xbrl.sec.gov/dei/2025"'
    ' xmlns:us-gaap="http://fasb.org/us-gaap/2025"'
    ' xmlns:xbrldi="http://xbrl.org/2006/xbrldi">'
)


def context(cid, instant, member=None, dimension="us-gaap:StatementClassOfStockAxis"):
    segment = (
        '<xbrli:segment><xbrldi:explicitMember'
        f' dimension="{dimension}">'
        f"{member}</xbrldi:explicitMember></xbrli:segment>"
        if member
        else ""
    )
    return (
        f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier'
        ' scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>'
        f"</xbrli:entity><xbrli:period><xbrli:instant>{instant}"
        f"</xbrli:instant></xbrli:period>{segment}</xbrli:context>"
    )


def symbol(cid, value):
    return f'<dei:TradingSymbol contextRef="{cid}">{value}</dei:TradingSymbol>'


def count(cid, value):
    return (
        f'<dei:EntityCommonStockSharesOutstanding contextRef="{cid}"'
        f' unitRef="shares" decimals="0">{value}'
        "</dei:EntityCommonStockSharesOutstanding>"
    )


def instance(body):
    return (XBRL + body + "</xbrli:xbrl>").encode()


def undimensioned_multiclass():
    """One listed security, a common class and a convertible common class."""
    body = (
        context("c0", "2026-08-31")
        + symbol("c0", "STZ")
        + context("ca", "2026-08-31", "us-gaap:CommonClassAMember")
        + count("ca", 169198487)
        + context("cc", "2026-08-31", "us-gaap:ConvertibleCommonStockMember")
        + count("cc", 25733)
    )
    return instance(body)


def two_unlisted_classes():
    """ERIE: one listed security, Classes A and B, both common."""
    body = (
        context("c0", "2026-09-30")
        + symbol("c0", "ERIE")
        + context("ca", "2026-09-30", "us-gaap:CommonClassAMember")
        + count("ca", 46189068)
        + context("cb", "2026-09-30", "us-gaap:CommonClassBMember")
        + count("cb", 2542)
    )
    return instance(body)


def listed_class_with_other(member, other, value, other_value, ticker="V"):
    body = (
        context("ca", "2026-06-30", member)
        + symbol("ca", ticker)
        + count("ca", value)
        + context("co", "2026-06-30", other)
        + count("co", other_value)
    )
    return instance(body)


def two_listed_classes():
    body = (
        context("ca", "2026-06-30", "us-gaap:CommonClassAMember")
        + symbol("ca", "BRK.A")
        + count("ca", 488450)
        + context("cb", "2026-06-30", "us-gaap:CommonClassBMember")
        + symbol("cb", "BRK.B")
        + count("cb", 1408035161)
    )
    return instance(body)


def test_a_single_listed_security_sums_its_common_classes():
    assert edgar.parse_cover_class_shares(undimensioned_multiclass(), "STZ") == (
        date(2026, 8, 31),
        169224220.0,
    )
    assert edgar.parse_cover_class_shares(two_unlisted_classes(), "ERIE") == (
        date(2026, 9, 30),
        46191610.0,
    )


def test_a_listed_class_is_taken_when_the_others_are_immaterial():
    body = listed_class_with_other(
        "us-gaap:CommonClassAMember",
        "us-gaap:CommonClassBMember",
        1_000_000_000,
        5_000_000,
    )
    assert edgar.parse_cover_class_shares(body, "V") == (
        date(2026, 6, 30),
        1_000_000_000.0,
    )


@pytest.mark.parametrize(
    ("body", "ticker"),
    [
        # V: Class C is 4.7% of the listed Class A and converts at 4.0.
        (listed_class_with_other(
            "us-gaap:CommonClassAMember",
            "us-gaap:CommonClassCMember",
            1_704_112_694,
            80_299_152,
        ), "V"),
        # ARES: Class C is 47% of the listed Class A.
        (listed_class_with_other(
            "us-gaap:CommonClassAMember",
            "us-gaap:CommonClassCMember",
            223_957_742,
            102_828_576,
            ticker="ARES",
        ), "ARES"),
        # BRK.A and BRK.B are both listed and do not share economics.
        (two_listed_classes(), "BRK-B"),
        # The ticker is not one of the listed classes.
        (listed_class_with_other(
            "us-gaap:CommonClassAMember",
            "us-gaap:CommonClassBMember",
            1_000_000_000,
            1_000,
            ticker="OTHER",
        ), "V"),
    ],
)
def test_an_ambiguous_class_structure_is_refused(body, ticker):
    assert edgar.parse_cover_class_shares(body, ticker) is None


def test_a_preferred_class_is_not_a_common_share():
    body = (
        context("c0", "2026-09-30")
        + symbol("c0", "ERIE")
        + context("ca", "2026-09-30", "us-gaap:CommonClassAMember")
        + count("ca", 46189068)
        + context("cp", "2026-09-30", "us-gaap:PreferredStockMember")
        + count("cp", 30_000_000)
    )
    assert edgar.parse_cover_class_shares(instance(body), "ERIE") == (
        date(2026, 9, 30),
        46189068.0,
    )


def test_no_trading_symbol_is_refused():
    body = (
        context("ca", "2026-09-30", "us-gaap:CommonClassAMember")
        + count("ca", 46189068)
    )
    assert edgar.parse_cover_class_shares(instance(body), "ERIE") is None


def test_classes_dated_differently_are_refused():
    body = (
        context("c0", "2026-09-30")
        + symbol("c0", "ERIE")
        + context("ca", "2026-09-30", "us-gaap:CommonClassAMember")
        + count("ca", 46189068)
        + context("cb", "2026-06-30", "us-gaap:CommonClassBMember")
        + count("cb", 2542)
    )
    assert edgar.parse_cover_class_shares(instance(body), "ERIE") is None


def test_an_undimensioned_count_beside_class_counts_is_refused():
    body = (
        context("c0", "2026-09-30")
        + symbol("c0", "ERIE")
        + count("c0", 46191610)
        + context("ca", "2026-09-30", "us-gaap:CommonClassAMember")
        + count("ca", 46189068)
    )
    assert edgar.parse_cover_class_shares(instance(body), "ERIE") is None


def test_a_single_class_filer_reads_the_undimensioned_count():
    # ABT: one undimensioned count, the ticker on two exchange listings.
    body = (
        context("c0", "2026-06-30")
        + count("c0", 1730383296)
        + context("cx1", "", "exch:XNYS", "dei:EntityListingsExchangeAxis")
        + symbol("cx1", "ABT")
        + context("cx2", "", "exch:XCHI", "dei:EntityListingsExchangeAxis")
        + symbol("cx2", "ABT")
    )
    assert edgar.parse_cover_class_shares(instance(body), "ABT") == (
        date(2026, 6, 30),
        1730383296.0,
    )


def test_a_utility_total_beside_subsidiary_counts_is_read():
    # DTE: the registrant's total is undimensioned, subsidiaries carry
    # counts on dei:LegalEntityAxis, and the ticker is a common class.
    body = (
        context("c0", "2026-06-30")
        + count("c0", 208088069)
        + context("ce", "2026-06-30", "dte:DTEElectricMember", "dei:LegalEntityAxis")
        + count("ce", 138632324)
        + context("cs", "", "us-gaap:CommonStockMember")
        + symbol("cs", "DTE")
        + context("cn", "", "dte:SeriesNotesMember")
        + symbol("cn", "DTW")
    )
    assert edgar.parse_cover_class_shares(instance(body), "DTE") == (
        date(2026, 6, 30),
        208088069.0,
    )


def test_ordinary_shares_are_common_equity():
    # JCI: the ticker is on an ordinary-shares class, the total undimensioned.
    body = (
        context("c0", "2026-06-30")
        + count("c0", 605741470)
        + context("cs", "", "jci:OrdinarySharesParValue001Member")
        + symbol("cs", "JCI")
        + context("cn", "", "jci:Notes0375PercentDue2027Member")
        + symbol("cn", "JCI27")
    )
    assert edgar.parse_cover_class_shares(instance(body), "JCI") == (
        date(2026, 6, 30),
        605741470.0,
    )


def test_a_preferred_count_beside_the_total_is_not_a_common_class():
    body = (
        context("c0", "2026-09-30")
        + symbol("c0", "C")
        + count("c0", 1677436783)
        + context("cp", "2026-09-30", "us-gaap:PreferredStockMember")
        + count("cp", 30000000)
    )
    assert edgar.parse_cover_class_shares(instance(body), "C") == (
        date(2026, 9, 30),
        1677436783.0,
    )


@pytest.mark.parametrize(
    ("body", "ticker"),
    [
        # Two listed common classes and no class counts: the total is a
        # cross-class sum, so BRK-B's own count is not decidable.
        (instance(
            context("c0", "2026-06-30")
            + count("c0", 1409000000)
            + context("ca", "", "us-gaap:CommonClassAMember")
            + symbol("ca", "BRK.A")
            + context("cb", "", "us-gaap:CommonClassBMember")
            + symbol("cb", "BRK.B")
        ), "BRK-B"),
        # No trading symbol: the count cannot be tied to the ticker.
        (instance(context("c0", "2026-06-30") + count("c0", 1000000)), "ABT"),
        # Two undimensioned counts: the cover date is not decided.
        (instance(
            context("c0", "2026-06-30")
            + count("c0", 1000000)
            + context("c1", "2026-07-31")
            + count("c1", 1000001)
        ), "ABT"),
        # A common class count the class reader could not date: the total
        # is a cross-class sum the filing does not split here.
        (instance(
            context("c0", "2026-06-30")
            + symbol("c0", "ABT")
            + count("c0", 1730383296)
            + context("ca", "", "us-gaap:CommonClassAMember")
            + count("ca", 1000000)
        ), "ABT"),
        # The ticker is a preferred listing, not a common share.
        (instance(
            context("c0", "2026-06-30")
            + count("c0", 1677436783)
            + context("cp", "", "us-gaap:PreferredStockMember")
            + symbol("cp", "C PR R")
        ), "C PR R"),
    ],
)
def test_an_ambiguous_undimensioned_structure_is_refused(body, ticker):
    assert edgar.parse_cover_class_shares(body, ticker) is None


def test_a_malformed_instance_is_refused():
    assert edgar.parse_cover_class_shares(b"<not xml", "ERIE") is None


def test_parse_filings_block_keeps_only_periodic_forms():
    block = {
        "form": ["10-Q", "8-K", "10-K", "6-K"],
        "filingDate": ["2026-07-24", "2026-07-24", "2026-02-13", "2026-05-01"],
        "acceptanceDateTime": [
            "2026-07-24T16:05:00Z",
            "2026-07-24T16:10:00Z",
            "2026-02-13T17:00:00Z",
            "2026-05-01T12:00:00Z",
        ],
        "accessionNumber": ["a", "b", "c", "d"],
        "primaryDocument": ["q.htm", "e.htm", "k.htm", "f.htm"],
    }
    found = edgar.parse_filings_block(block)
    assert [(f.accession, f.form, f.filed) for f in found] == [
        ("a", "10-Q", date(2026, 7, 24)),
        ("c", "10-K", date(2026, 2, 13)),
    ]
    assert found[0].accepted == datetime(2026, 7, 24, 16, 5, tzinfo=UTC)


def test_the_instance_is_the_largest_non_linkbase_xml():
    items = [
        {"name": "filingsummary.xml", "size": 900},
        {"name": "synth_cal.xml", "size": 800},
        {"name": "synth_def.xml", "size": 800},
        {"name": "synth_lab.xml", "size": 800},
        {"name": "synth_pre.xml", "size": 800},
        {"name": "synth-20260630_htm.xml", "size": 5000},
        {"name": "synth-20260630_htm.xml", "size": 4000},
    ]
    assert edgar._instance_name(items) == "synth-20260630_htm.xml"
    assert edgar._instance_name(items[:5]) is None


def filing(accession, filed):
    return edgar.FilingRef(
        accession=accession,
        form="10-Q",
        filed=filed,
        accepted=None,
        primary_document="q.htm",
    )


class Transport:
    """A URL map transport that records what was asked for."""

    def __init__(self, responses):
        self.responses = responses
        self.seen = []

    def __call__(self, url):
        self.seen.append(url)
        return self.responses.get(url, (404, b""))


def archive_urls(cik, accession, name="synth-20260630_htm.xml"):
    folder = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/index.json",
        f"https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{name}",
    )


INDEX = {
    "directory": {
        "item": [{"name": "synth-20260630_htm.xml", "size": 5000}]
    }
}


def test_an_incremental_fetch_skips_the_older_submissions_blocks():
    submissions_url = "https://data.sec.gov/submissions/CIK0000000001.json"
    older_url = "https://data.sec.gov/submissions/CIK0000000001-submissions-001.json"
    recent = {
        "form": ["10-Q"],
        "filingDate": ["2026-07-24"],
        "acceptanceDateTime": ["2026-07-24T16:05:00Z"],
        "accessionNumber": ["0000000001-26-000001"],
        "primaryDocument": ["q.htm"],
    }
    older = {
        "form": ["10-K"],
        "filingDate": ["2015-02-13"],
        "acceptanceDateTime": ["2015-02-13T17:00:00Z"],
        "accessionNumber": ["0000000001-15-000001"],
        "primaryDocument": ["k.htm"],
    }
    payload = {
        "filings": {
            "recent": recent,
            "files": [{"name": "CIK0000000001-submissions-001.json"}],
        }
    }
    transport = Transport(
        {
            submissions_url: (200, json.dumps(payload).encode()),
            older_url: (200, json.dumps(older).encode()),
        }
    )
    incremental = edgar.fetch_filings(1, since=date(2026, 8, 1), transport=transport)
    assert [f.filed for f in incremental] == [date(2026, 7, 24)]
    assert older_url not in transport.seen
    full = edgar.fetch_filings(1, transport=transport)
    assert [f.filed for f in full] == [date(2015, 2, 13), date(2026, 7, 24)]
    assert older_url in transport.seen


def test_a_recent_block_with_no_periodic_form_still_skips_older_blocks():
    # A 20-F/6-K filer files no 10-K or 10-Q, so the recent block holds no
    # periodic form at all. The nightly watermark is newer than the recent
    # block's oldest filing, so no older block can hold a filing after it.
    submissions_url = "https://data.sec.gov/submissions/CIK0000000002.json"
    older_url = "https://data.sec.gov/submissions/CIK0000000002-submissions-001.json"
    recent = {
        "form": ["6-K", "20-F"],
        "filingDate": ["2026-10-01", "2026-04-15"],
        "acceptanceDateTime": ["2026-10-01T10:00:00Z", "2026-04-15T10:00:00Z"],
        "accessionNumber": ["0000000002-26-000002", "0000000002-26-000001"],
        "primaryDocument": ["a.htm", "b.htm"],
    }
    older = {
        "form": ["20-F"],
        "filingDate": ["2015-04-15"],
        "acceptanceDateTime": ["2015-04-15T10:00:00Z"],
        "accessionNumber": ["0000000002-15-000001"],
        "primaryDocument": ["c.htm"],
    }
    payload = {
        "filings": {
            "recent": recent,
            "files": [{"name": "CIK0000000002-submissions-001.json"}],
        }
    }
    transport = Transport(
        {
            submissions_url: (200, json.dumps(payload).encode()),
            older_url: (200, json.dumps(older).encode()),
        }
    )
    filings = edgar.fetch_filings(2, since=date(2026, 10, 2), transport=transport)
    assert filings == []
    assert older_url not in transport.seen
    # A watermark older than the recent block's oldest filing leaves a gap
    # only an older block can fill, so that block is read.
    filings = edgar.fetch_filings(2, since=date(2026, 4, 1), transport=transport)
    assert filings == []
    assert older_url in transport.seen


def test_the_fetch_reads_the_instance_and_advances_the_watermark():
    accession = "0000000001-26-000001"
    index_url, document_url = archive_urls(1, accession)
    transport = Transport(
        {
            index_url: (200, json.dumps(INDEX).encode()),
            document_url: (200, two_unlisted_classes()),
        }
    )
    counts, skipped, checked = edgar.fetch_cover_class_shares(
        1, "ERIE", [filing(accession, date(2026, 7, 24))], transport=transport
    )
    assert skipped == []
    assert [(c.end, c.value) for c in counts] == [(date(2026, 9, 30), 46191610.0)]
    assert checked == date(2026, 7, 24)


def test_a_refused_structure_still_advances_the_watermark():
    accession = "0000000001-26-000001"
    index_url, document_url = archive_urls(1, accession)
    transport = Transport(
        {
            index_url: (200, json.dumps(INDEX).encode()),
            document_url: (200, two_listed_classes()),
        }
    )
    counts, skipped, checked = edgar.fetch_cover_class_shares(
        1, "BRK-B", [filing(accession, date(2026, 8, 10))], transport=transport
    )
    assert counts == []
    assert "no unambiguous class count" in skipped[0]
    assert checked == date(2026, 8, 10)


def test_a_transient_failure_caps_the_watermark():
    good = "0000000001-26-000001"
    bad = "0000000001-26-000002"
    good_index, good_document = archive_urls(1, good)
    bad_index, _bad_document = archive_urls(1, bad)
    transport = Transport(
        {
            good_index: (200, json.dumps(INDEX).encode()),
            good_document: (200, two_unlisted_classes()),
            bad_index: (500, b""),
        }
    )
    counts, skipped, checked = edgar.fetch_cover_class_shares(
        1,
        "ERIE",
        [filing(good, date(2026, 5, 1)), filing(bad, date(2026, 8, 1))],
        transport=transport,
    )
    assert len(counts) == 1
    assert "HTTP 500" in skipped[0]
    # Only the good filing is behind the watermark; the next run reads the
    # failed one again.
    assert checked == date(2026, 5, 1)


def v(name, tag, start, end, value, filed, accession=None):
    return fa.Version(
        name,
        tag,
        None if start is None else date.fromisoformat(start),
        date.fromisoformat(end),
        float(value),
        date.fromisoformat(filed),
        None,
        accession or f"acc-{filed}",
        "10-Q",
    )


def days(*values):
    return np.array(values, dtype="datetime64[D]")


def test_the_class_tag_sits_after_the_standard_cover_tag():
    tiers = fa._tag_tiers("shares")
    assert tiers[CLASS] == 0
    order = fa._tag_order("shares")
    assert order[-1] == CLASS
    assert order.index(f"dei:{COVER.split(':')[1]}") < order.index(CLASS)


def test_levels_for_reads_a_class_count_as_shares():
    versions = [
        v("shares", COVER, None, "2011-04-29", 941481, "2011-05-06"),
        v("shares", CLASS, None, "2026-06-30", 46191610, "2026-07-24"),
    ]
    out = fa.levels_for(versions, days("2026-07-01", "2026-10-30"))
    np.testing.assert_array_equal(out["shares"], [941481, 46191610])


def test_a_standard_cover_count_wins_the_same_period():
    versions = [
        v("shares", CLASS, None, "2026-06-30", 46191610, "2026-07-24"),
        v("shares", COVER, None, "2026-06-30", 46189068, "2026-07-24"),
    ]
    out = fa.levels_for(versions, days("2026-10-30"))
    np.testing.assert_array_equal(out["shares"], [46189068])


def test_versions_levels_read_the_class_count_from_its_filing_date():
    versions = [
        v("shares", COVER, None, "2011-04-29", 941481, "2011-05-06"),
        v("shares", CLASS, None, "2026-06-30", 46191610, "2026-07-24"),
    ]
    sessions = days("2026-07-23", "2026-07-24", "2026-10-30")
    latest, _back, _source = levels_pit.versions_levels(versions, sessions)["shares"]
    # The 2011 count is below the valuation floor, so the class count is the
    # first usable value.
    np.testing.assert_array_equal(latest, [np.nan, 46191610, 46191610])
    strict = levels_pit.versions_levels(
        versions, sessions, strict_publication=True
    )["shares"][0]
    np.testing.assert_array_equal(strict, [np.nan, np.nan, 46191610])


def test_the_weighted_fallback_is_still_ignored_by_the_instant_reader():
    versions = [
        v(
            edgar.WEIGHTED_SHARES_NAME,
            "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
            "2024-01-01",
            "2024-03-31",
            250e6,
            "2024-05-01",
        ),
        v("shares", CLASS, None, "2024-06-30", 240e6, "2024-08-01"),
    ]
    out = fa.levels_for(versions, days("2024-09-01"))
    np.testing.assert_array_equal(out["shares"], [240e6])


def test_latest_share_count_sees_both_names():
    versions = [
        v("shares", COVER, None, "2026-03-31", 208e6, "2026-04-30"),
        v(
            edgar.WEIGHTED_SHARES_NAME,
            "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
            "2025-01-01",
            "2025-12-31",
            207e6,
            "2026-02-17",
        ),
    ]
    assert fa.latest_share_count(versions).end == date(2026, 3, 31)
    assert fa.latest_share_count([]) is None


def test_merge_versions_keeps_one_copy_and_sorts():
    a = v("shares", CLASS, None, "2026-06-30", 1e6, "2026-07-24", accession="x")
    b = v("shares", CLASS, None, "2026-09-30", 2e6, "2026-10-29", accession="y")
    assert fa.merge_versions([a], [a, b]) == [a, b]


class Store:
    def __init__(self, prior=None):
        self.prior = prior
        self.written = None

    def read_frame(self, kind, ticker, asof=None):
        return self.prior if ticker == "STZ" and kind == fa.KIND else None

    def write_frame(self, kind, asof, ticker, columns, metadata):
        self.written = (kind, asof, ticker, columns, metadata)
        return True


def test_refresh_merges_the_class_count_into_the_nightly_frame():
    accession = "0000000001-26-000001"
    index_url, document_url = archive_urls(1, accession)
    facts_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"
    submissions_url = "https://data.sec.gov/submissions/CIK0000000001.json"
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    transport = Transport(
        {
            tickers_url: (
                200,
                json.dumps({"0": {"ticker": "STZ", "cik_str": 1}}).encode(),
            ),
            facts_url: (200, json.dumps({"facts": {}}).encode()),
            submissions_url: (
                200,
                json.dumps(
                    {
                        "filings": {
                            "recent": {
                                "form": ["10-Q"],
                                "filingDate": ["2026-07-24"],
                                "acceptanceDateTime": ["2026-07-24T16:05:00Z"],
                                "accessionNumber": [accession],
                                "primaryDocument": ["q.htm"],
                            }
                        }
                    }
                ).encode(),
            ),
            index_url: (200, json.dumps(INDEX).encode()),
            document_url: (200, undimensioned_multiclass()),
        }
    )
    store = Store()
    failed = cli.refresh(store, ("STZ",), date(2026, 10, 30), transport=transport)
    assert failed == []
    _kind, _asof, _ticker, columns, metadata = store.written
    assert metadata["class_checked_through"] == "2026-07-24"
    shares = [
        (columns["tag"][i], columns["end"][i], columns["value"][i])
        for i in range(len(columns["tag"]))
        if columns["name"][i] == "shares"
    ]
    assert shares == [(CLASS, "2026-08-31", 169224220.0)]


def test_a_failure_capped_watermark_is_not_moved_by_a_later_class_filing(monkeypatch):
    # The prior run failed at 2026-05-02 (watermark capped to 2026-05-01)
    # but a later filing succeeded and stored a class count. The retry must
    # start at the capped watermark, not at the later filing.
    prior = v("shares", CLASS, None, "2026-06-30", 1_000_000, "2026-07-24")
    store = Store((fa.frame([prior]), {"class_checked_through": "2026-05-01"}))
    seen = {}

    monkeypatch.setattr(edgar, "fetch_cik_map", lambda **_kwargs: {"STZ": 1})
    monkeypatch.setattr(fa, "fetch_versions", lambda _cik, **_kwargs: [])

    def fake_class_versions(_cik, _ticker, since=None, **_kwargs):
        seen["since"] = since
        return [], [], None

    monkeypatch.setattr(fa, "class_share_versions", fake_class_versions)
    cli.refresh(store, ("STZ",), date(2026, 10, 30), transport=None)
    assert seen["since"] == date(2026, 5, 1)
