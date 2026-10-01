"""Form 6-K results releases: admitted by headline shape, refused otherwise.

No network: a fake transport serves a synthetic submissions document, filing
index pages and exhibit heads whose titles and file names are those of the
real filings read on EDGAR 2026-10-01 (bodies are synthetic). What has to
hold: a 6-K of a listed issuer is an event only when its press release opens
with a results headline, whatever the issuer's wording ("TSMC Reports Third
Quarter EPS", "ASML reports ... net income in 2024", "Nebius reports second
quarter financial results", "Silicon Motion Announces Results for the Fourth
Quarter and Year Ended"); the monthly revenue note, the statements, the
interim report, the call-date notice, a dividend, a buyback, a financing and
a board resolution are refused; an HTML entity inside a title does not
break it; a 6-K without an exhibit is read from its own document after the
cover page; an unlisted CIK admits no 6-K; a refused page fails the name
rather than caching "not a release"; a cached decision is not re-read
unless the refresh reclassifies; the audit counts four a year for each
filer on these fixtures.
"""

import json
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.cli import market_edgar, market_tone
from backend.market import edgar, language
from backend.market.store import MarketStore

TSM, ASML, ARM, SIMO, NBIS = 1046179, 937966, 1973239, 1329394, 1513845

# The Form 6-K cover page as TSMC's main-document filings carry it, with
# the release after the signature block (0001564590-20-016960, 2020-04-16;
# the same shape as every TSMC results 6-K from 2015 to 2019-07).
TSM_COVER = (
    "1934 Act Registration No. 1-14700 SECURITIES AND EXCHANGE COMMISSION "
    "Washington, DC 20549 FORM 6-K REPORT OF FOREIGN PRIVATE ISSUER PURSUANT TO "
    "RULE 13a-16 OR 15d-16 OF THE SECURITIES EXCHANGE ACT OF 1934 For the Month "
    "of April 2020 Taiwan Semiconductor Manufacturing Company Ltd. (Translation "
    "of Registrant's Name Into English) No. 8, Li-Hsin Rd. 6, Hsinchu Science "
    "Park, Taiwan (Address of Principal Executive Offices) (Indicate by check "
    "mark whether the registrant files or will file annual reports under cover "
    "of Form 20-F or Form 40-F.) Form 20-F ☒ Form 40-F ☐ (Indicate by "
    "check mark whether the registrant by furnishing the information contained "
    "in this form is also thereby furnishing the information to the Commission "
    "pursuant to Rule 12g3-2(b) under the Securities Exchange Act of 1934.) Yes "
    "☐ No ☒ (If “Yes” is marked, indicated below the file "
    "number assigned to the registrant in connection with Rule 12g3-2(b): 82: "
    "_______.) SIGNATURES Pursuant to the requirements of the Securities "
    "Exchange Act of 1934, the registrant has duly caused this report to be "
    "signed on its behalf by the undersigned, thereunto duly authorized. Taiwan "
    "Semiconductor Manufacturing Company Ltd. Date: April 16, 2020 By /s/ "
    "Wendell Huang Wendell Huang Vice President & Chief Financial Officer "
)

# Heads in the shape of the real documents: each title is the filing's
# own, the figures and the rest of the body are made up.
HEADS = {
    # TSMC (EX-99.1 since 2019-10; the 6-K's own document before, and 2020-04)
    "tsm_results": (
        "TSMC Reports Second Quarter EPS of NT$1.00 Hsinchu, Taiwan, R.O.C., July "
        "16, 2020 – TSMC (TWSE: 2330, NYSE: TSM) today announced consolidated "
        "revenue of NT$310.70 billion, net income of NT$120.82 billion, and diluted "
        "earnings per share of NT$4.66 for the second quarter ended June 30, 2020."
    ),
    "tsm_monthly": (
        "TSMC September 2020 Revenue Report Hsinchu, Taiwan, R.O.C. – Oct. 8, "
        "2020 - TSMC (TWSE: 2330, NYSE: TSM) today announced its net revenues for "
        "September 2020: On a consolidated basis, revenues for September 2020 were "
        "approximately NT$127.59 billion, an increase of 3.8 percent from August "
        "2020. Revenues for January through September 2020 totaled NT$977.72 "
        "billion, an increase of 29.9 percent compared to the same period in 2019."
    ),
    "tsm_statements": (
        "English Translation of Financial Statements Originally Issued in Chinese "
        "Taiwan Semiconductor Manufacturing Company Limited and Subsidiaries "
        "Consolidated Financial Statements for the Nine Months Ended September 30, "
        "2020 and 2019 and Independent Auditors' Review Report"
    ),
    "tsm_board": (
        "TSMC Board of Directors Meeting Resolutions Hsinchu, Taiwan, R.O.C., Nov. "
        "10, 2020 – TSMC (TWSE: 2330, NYSE: TSM) today held a meeting of the "
        "Board of Directors, which passed the following resolutions: 1. Approved "
        "the distribution of a cash dividend of NT$2.50 per share from 3Q20 "
        "earnings; the Board announced the quarterly dividend for the third "
        "quarter of 2020 and the capital appropriations."
    ),
    "tsm_notes": (
        "TSMC Announces Pricing of US$1,000 Million 0.750%, US$750 Million 1.000% "
        "and US$1,250 Million 1.375% Senior Unsecured Notes On September 23, 2020 "
        "New York time, TSMC Global Ltd. priced the notes."
    ),
    # ASML (EX-99.1 pressreleasequarterlyresul.htm; 2026: pressreleasefinancialresul)
    "asml_quarter": (
        "ASML reports €7.7 billion total net sales and €2.4 billion net "
        "income in Q1 2025 2025 total net sales expected to be between €30 "
        "billion and €35 billion VELDHOVEN, the Netherlands, April 16, 2025 "
        "– Today, ASML Holding NV (ASML) has published its 2025 first-quarter "
        "results."
    ),
    "asml_full_year": (
        "ASML reports €28.3 billion total net sales and €7.6 billion net "
        "income in 2024 2025 total net sales expected to be between €30 "
        "billion and €35 billion VELDHOVEN, the Netherlands, January 29, 2025 "
        "– Today, ASML Holding NV (ASML) has published its 2024 fourth-quarter "
        "and full-year results. • Q4 total net sales of €9.3 billion, "
        "gross margin of 51.7%, net income of €2.7 billion • Quarterly "
        "net bookings in Q4 of €7.1 billion • 2024 total net sales of "
        "€28.3 billion, gross margin of 51.3%, net income of €7.6 "
        "billion • ASML proposes a total dividend for 2024 of €6.40 per "
        "ordinary share."
    ),
    "asml_2020": (
        "ASML reports €2.4 billion net sales at 45.1% gross margin in Q1 2020 "
        "Strong order intake and currently no change in demand VELDHOVEN, the "
        "Netherlands, April 15, 2020 - today ASML Holding NV (ASML) publishes its "
        "Q1 2020 results."
    ),
    "asml_2017": (
        "Stronger than expected demand drives ASML Q1 sales Positive momentum "
        "expected to continue throughout 2017 VELDHOVEN, the Netherlands, April "
        "19, 2017 - ASML Holding N.V. (ASML) today publishes its 2017 first-quarter "
        "results. • Q1 net sales of EUR 1.94 billion, gross margin 47.6 percent"
    ),
    "asml_2015": (
        "ASML Q2 2015 press release Exhibit 99.1 Media Relations Contacts Lucas van "
        "Grinsven - Corporate Communications - +31 6 101 99 532 - Veldhoven, the "
        "Netherlands Niclas Mika – Corporate Communications - +31 6 201 528 63 "
        "– Veldhoven, the Netherlands Investor Relations Contacts Craig DeYoung "
        "- Investor Relations - +1 480 696 2762 - Chandler, Arizona, USA Marcel "
        "Kemp - Investor Relations - +31 40 268 6494 - Veldhoven, the Netherlands "
        "ASML reports Q2 results in line with guidance, on track for record 2015 "
        "sales VELDHOVEN, the Netherlands, 15 July 2015 - ASML Holding N.V. (ASML) "
        "today publishes its 2015 second-quarter results."
    ),
    "asml_buyback": (
        "ASML reports on share buyback transactions in the week of 13 January 2025 "
        "under its 2022-2025 program; the shares were repurchased on Euronext."
    ),
    "asml_annual": "ASML publishes its 2024 Annual Report based on US GAAP",
    "asml_investor_day": (
        "ASML SMALL TALK 2022 INVESTOR DAY VELDHOVEN 1 Opening Skip Miller Vice "
        "President Investor Relations Investor Day Veldhoven"
    ),
    # Arm (EX-99.1)
    "arm_results": (
        "Arm Holdings plc Reports Results for the First Quarter of the Fiscal Year "
        "Ending March 31, 2027"
    ),
    # Silicon Motion (EX-99.1 dNNNNNNdex991.htm throughout)
    "simo_results": (
        "Silicon Motion Announces Results for the Period Ended June 30, 2025 NEWS "
        "RELEASE Business Highlights • Second quarter of 2025 sales increased "
        "19% Q/Q and decreased 6% Y/Y • SSD controller sales: 2Q of 2025 "
        "increased 0% to 5% Q/Q"
    ),
    "simo_year_ended": (
        "Silicon Motion Announces Results for the Fourth Quarter and Year Ended "
        "December 31, 2025 NEWS RELEASE Business Highlights • Fourth quarter "
        "of 2025 sales increased 15% Q/Q and increased 46% Y/Y • SSD "
        "controller sales: 4Q of 2025 increased 25% to 30% Q/Q and increased 35% "
        "to 40% Y/Y • eMMC+UFS controller sales: 4Q of 2025 increased 0% to "
        "5% Q/Q and increased 50% to 55% Y/Y • SSD solutions sales: 4Q of 2025 "
        "increased 125% to 130% Q/Q and increased 110% to 115% Y/Y • Announced "
        "annual cash dividend of $2.00 per ADS"
    ),
    "simo_quarterly_period": (
        "Silicon Motion Announces Results for the Quarterly Period Ended March 31, "
        "2026 NEWS RELEASE Business Highlights • First quarter of 2026 sales "
        "increased 23% Q/Q and increased 105% Y/Y"
    ),
    "simo_call": (
        "Silicon Motion Announces Third Quarter 2025 Earnings Conference Call "
        "TAIPEI, Taiwan and MILPITAS, Calif., October 8, 2025 – Silicon Motion "
        "Technology Corporation (NasdaqGS: SIMO), a global leader in NAND flash "
        "controllers, plans to release its third quarter 2025 financial results "
        "after the market closes on October 30, 2025."
    ),
    "simo_dividend": (
        "Silicon Motion Announces Annual Cash Dividend Payable Quarterly TAIPEI, "
        "Taiwan and MILPITAS, Calif., October 27, 2025 – Silicon Motion "
        "Technology Corporation (NasdaqGS: SIMO) announces today that its Board "
        "of Directors has approved an annual dividend."
    ),
    "simo_repurchase": (
        "Silicon Motion Announces New $50 Million Share Repurchase Program NEWS "
        "RELEASE TAIPEI, Taiwan and MILPITAS, Calif., February 6, 2025 — "
        "Silicon Motion Technology Corporation today announced that its Board of "
        "Directors has authorized a new share repurchase program."
    ),
    # Nebius (EX-99.1 tmNNNNNNNdN_ex99-1.htm; the interim report nbis-...xex99d1.htm)
    "nbis_reports": (
        "Nebius reports second quarter financial results and raises ARR guidance "
        "for 2025 · Annualized run-rate revenue (ARR) guidance increased to "
        "$900 million to $1.1 billion for the end of 2025 · Revenue for Q2 of "
        "$105.1 million, up 625% year-on-year Amsterdam, August 7, 2025 – "
        "Nebius Group N.V. (NASDAQ: NBIS), a leading AI infrastructure company, "
        "today announced its unaudited financial results for the second quarter "
        "ended June 30, 2025."
    ),
    "nbis_announces": (
        "Nebius Group N.V. announces first quarter 2025 financial results "
        "Amsterdam, May 20, 2025 – Nebius Group N.V. (“Nebius Group”, "
        "the “Group” or the “Company”; NASDAQ: NBIS), a leading "
        "AI infrastructure company, today announced its unaudited financial "
        "results for the first quarter ended March 31, 2025."
    ),
    "nbis_full_year": (
        "Nebius reports fourth quarter and full-year 2025 financial results "
        "Amsterdam, February 12, 2026 – Nebius Group N.V. (NASDAQ: NBIS), the "
        "AI cloud company, today announced its unaudited financial results for the "
        "fourth quarter and full financial year ended December 31, 2025. The "
        "Company today also published founder and CEO Arkady Volozh’s "
        "quarterly letter to shareholders, available on its investor relations "
        "website at https://nebius.com/investor-hub. Management will hold an "
        "earnings webcast today at 8:00 a.m. Eastern Time."
    ),
    "nbis_interim_report": (
        "Operating and Financial Review and Prospects First Quarter Ended March "
        "31, 2025 and 2026 You should read the following discussion and analysis "
        "of our financial condition and results of operations for the three "
        "months ended March 31, 2025 and 2026 in conjunction with our unaudited "
        "condensed consolidated financial statements and related notes appearing "
        "elsewhere in this Report on Form 6-K."
    ),
    "nbis_placement": (
        "Nebius Group announces private placement of $1 billion in aggregate "
        "principal amount of convertible notes Amsterdam, June 2, 2025 — Nebius "
        "Group N.V. today announced that it has entered into definitive agreements."
    ),
    "nbis_offering": "Nebius Group Announces Pricing of Offering of Convertible Notes",
    "nbis_agreement": (
        "Nebius announces multi-billion dollar agreement with Microsoft for AI "
        "infrastructure ● Deal enables significantly more aggressive growth of "
        "Nebius’s AI cloud business in 2026 Amsterdam, September 8, 2025 "
        "— Nebius Group N.V. (NASDAQ: NBIS) today announced that it has "
        "entered into an agreement."
    ),
    "nbis_atm": (
        "On November 12, 2025, Nebius Group N.V. announced that it entered into an "
        "Equity Distribution Agreement for an at-the-market program of up to "
        "25,000,000 Class A shares, and filed a prospectus supplement."
    ),
}


@pytest.mark.parametrize(
    ("key", "expected", "reason"),
    [
        ("tsm_results", True, ""),
        ("tsm_monthly", False, "Revenue Report"),
        ("tsm_statements", False, "no reporting verb"),
        ("tsm_board", False, "resolutions"),
        ("tsm_notes", False, "Senior Unsecured Notes"),
        ("asml_quarter", True, ""),
        ("asml_full_year", True, ""),
        ("asml_2020", True, ""),
        ("asml_2017", True, ""),
        ("asml_2015", True, ""),
        ("asml_buyback", False, "buyback"),
        ("asml_annual", False, "Annual Report"),
        ("asml_investor_day", False, "no reporting verb"),
        ("arm_results", True, ""),
        ("simo_results", True, ""),
        ("simo_year_ended", True, ""),
        ("simo_quarterly_period", True, ""),
        ("simo_call", False, "Conference Call"),
        ("simo_dividend", False, "Dividend"),
        ("simo_repurchase", False, "Repurchase"),
        ("nbis_reports", True, ""),
        ("nbis_announces", True, ""),
        ("nbis_full_year", True, ""),
        ("nbis_interim_report", False, "no reporting verb"),
        ("nbis_placement", False, "private placement"),
        ("nbis_offering", False, "Offering of"),
        ("nbis_agreement", False, "no period"),
        ("nbis_atm", False, "prospectus"),
    ],
)
# Every results release of every filer is admitted by the shape of its
# headline, and every other kind of 6-K is refused with a reason that
# names what it is.
def test_results_headline_admits_releases_and_refuses_the_rest(key, expected, reason):
    admitted, why = edgar.results_headline(HEADS[key])
    assert admitted is expected, why
    assert reason in why


# A results headline admits only for a listed issuer; an unlisted CIK
# admits nothing however the text reads.
def test_listed_issuers_only():
    assert edgar.is_results_headline(TSM, HEADS["tsm_results"]) is True
    assert edgar.is_results_headline(NBIS, HEADS["nbis_reports"]) is True
    assert edgar.is_results_headline(99, HEADS["tsm_results"]) is False
    assert edgar.is_results_headline(TSM, HEADS["tsm_monthly"]) is False


# A headline past the head of the document does not count: the monthly
# note's own verb is the first one found, and its kind refuses it.
def test_headline_is_read_from_the_head_only():
    text = HEADS["tsm_monthly"] + " x" * 400 + " " + HEADS["tsm_results"]
    assert edgar.is_results_headline(TSM, text) is False
    assert edgar.is_results_headline(TSM, "x " * 500 + HEADS["tsm_results"]) is False


# Silicon Motion's 2025-10-31 release (0001193125-25-259296) carries its
# title with non-breaking spaces as entities between the words; the text
# layer decodes them, so the title reads as words and is admitted.
def test_html_entities_inside_a_title_are_decoded():
    html = (
        "<p>Silicon&nbsp;Motion&nbsp;Announces&nbsp;Results&nbsp;for&nbsp;the"
        "&nbsp;Period Ended September 30, 2025 &nbsp;&nbsp; NEWS RELEASE</p>"
        "<p>ASML reports &#8364;7.5&#160;billion total net sales in Q3 2025</p>"
    )
    text = edgar.html_to_text(html)
    assert text.startswith(
        "Silicon Motion Announces Results for the Period Ended September 30, 2025 "
        "NEWS RELEASE"
    )
    assert "ASML reports €7.5 billion total net sales in Q3 2025" in text
    assert edgar.is_results_headline(SIMO, text) is True


# The Form 6-K cover page is removed down to the signature block when the
# release is the 6-K's own document; an unsigned cover ends at its last
# check mark; a document without a cover is returned whole.
def test_form_cover_is_stripped_before_the_headline():
    stripped = edgar.strip_form_cover(TSM_COVER + HEADS["tsm_results"])
    assert stripped.startswith("& Chief Financial Officer TSMC Reports Second Quarter")
    assert edgar.is_results_headline(TSM, TSM_COVER + HEADS["tsm_results"]) is True
    assert edgar.is_results_headline(TSM, TSM_COVER + HEADS["tsm_monthly"]) is False
    unsigned = TSM_COVER.split("SIGNATURES")[0]
    assert (
        edgar.strip_form_cover(unsigned + HEADS["tsm_results"]) == HEADS["tsm_results"]
    )
    assert edgar.strip_form_cover(HEADS["tsm_results"]) == HEADS["tsm_results"]
    # The cover's own "annual reports" is not read as the headline verb.
    assert edgar.results_headline(TSM_COVER + HEADS["tsm_statements"])[0] is False


# --- a fake EDGAR ----------------------------------------------------------

_ROW = (
    '<tr><td>{seq}</td><td>{kind}</td><td><a href="{href}">{name}</a></td>'
    "<td>{kind}</td><td>1000</td></tr>"
)


# One filing index page listing the given (type, file name) documents.
def _index(cik: int, accession: str, documents: list[tuple[str, str]]) -> str:
    folder = accession.replace("-", "")
    rows = "".join(
        _ROW.format(
            seq=i + 1,
            kind=kind,
            href=f"/Archives/edgar/data/{cik}/{folder}/{name}",
            name=name,
        )
        for i, (kind, name) in enumerate(documents)
    )
    return f'<table class="tableFile"><tr><th>Seq</th></tr>{rows}</table>'


# A transport serving a submissions document and the filings it lists.
# `filings` maps accession -> (form, filed, accepted, [(type, name, text)]).
class FakeEdgar:
    def __init__(self, cik: int, filings: dict) -> None:
        self.cik = cik
        self.filings = filings
        self.pages: dict[str, bytes] = {}
        self.urls: list[str] = []
        self.refuse: set[str] = set()
        block = {
            "form": [],
            "items": [],
            "acceptanceDateTime": [],
            "filingDate": [],
            "accessionNumber": [],
        }
        for accession, (form, filed, accepted, documents) in filings.items():
            block["form"].append(form)
            block["items"].append("")
            block["acceptanceDateTime"].append(accepted)
            block["filingDate"].append(filed)
            block["accessionNumber"].append(accession)
            folder = accession.replace("-", "")
            base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{folder}"
            self.pages[f"{base}/{accession}-index.html"] = _index(
                cik, accession, [(t, n) for t, n, _ in documents]
            ).encode()
            for _kind, name, text in documents:
                self.pages[f"{base}/{name}"] = (
                    f"<html><body>{text}</body></html>".encode()
                )
        self.pages[f"https://data.sec.gov/submissions/CIK{cik:010d}.json"] = json.dumps(
            {"filings": {"recent": block, "files": []}}
        ).encode()

    # Serve a page, or 503 for one marked refused.
    def __call__(self, url: str) -> tuple[int, bytes]:
        self.urls.append(url)
        if url in self.refuse:
            return 503, b""
        return (200, self.pages[url]) if url in self.pages else (404, b"")


def _nosleep(_seconds: float) -> None:
    return None


def _fetch(cik: int, fake: FakeEdgar, decisions=None):
    return edgar.fetch_events_with_decisions(
        cik,
        transport=fake,
        pacer=edgar.Pacer(sleep=_nosleep, interval=0),
        sleep=_nosleep,
        decisions=decisions,
    )


# One 6-K filing row: filed on `day`, accepted at `hour` UTC.
def _filing(day: date, documents, hour: int = 10) -> tuple:
    stamp = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
    return (
        "6-K",
        day.isoformat(),
        stamp.isoformat().replace("+00:00", ".000Z"),
        documents,
    )


def _tsm_filings():
    return {
        # A release in the main document, after the cover (2015 to 2019-07).
        "0001193125-15-254327": _filing(
            date(2015, 7, 16),
            [("6-K", "d138469d6k.htm", TSM_COVER + HEADS["tsm_results"])],
            11,
        ),
        # The modern shape: EX-99.1 release, EX-99.2 deck.
        "0001564590-20-001200": _filing(
            date(2020, 1, 16),
            [
                ("6-K", "tsm-6k_20200116.htm", TSM_COVER),
                ("EX-99.1", "tsm-ex991_8.htm", HEADS["tsm_results"]),
                ("EX-99.2", "tsm-ex992_9.htm", "slides"),
            ],
        ),
        # 2020-04-16: filed with no exhibit, the release in the 6-K itself.
        "0001564590-20-016960": _filing(
            date(2020, 4, 16),
            [("6-K", "tsm-6k_20200416.htm", TSM_COVER + HEADS["tsm_results"])],
        ),
        "0001564590-20-032443": _filing(
            date(2020, 7, 16),
            [
                ("6-K", "tsm-6k_20200716.htm", TSM_COVER),
                ("EX-99.1", "tsm-ex991_64.htm", HEADS["tsm_results"]),
            ],
        ),
        "0001564590-20-046453": _filing(
            date(2020, 10, 15),
            [
                ("6-K", "tsm-6k_20201015.htm", TSM_COVER),
                ("EX-99.1", "tsm-ex991_7.htm", HEADS["tsm_results"]),
            ],
        ),
        # Monthly revenue, a notes pricing and board resolutions are main
        # documents; the full statements a month later are an EX-99.1.
        "0001564590-20-046046": _filing(
            date(2020, 10, 8),
            [("6-K", "tsm-6k_20201008.htm", TSM_COVER + HEADS["tsm_monthly"])],
        ),
        "0001564590-20-044420": _filing(
            date(2020, 9, 24),
            [("6-K", "tsm-6k_20200923.htm", TSM_COVER + HEADS["tsm_notes"])],
        ),
        "0001564590-20-052746": _filing(
            date(2020, 11, 10),
            [("6-K", "tsm-6k_20201110.htm", TSM_COVER + HEADS["tsm_board"])],
        ),
        "0001564590-20-053724": _filing(
            date(2020, 11, 13),
            [
                ("6-K", "tsm-6k_20201113.htm", TSM_COVER),
                ("EX-99.1", "tsm-ex991_61.htm", HEADS["tsm_statements"]),
            ],
        ),
        # A 20-F is never an event.
        "0001564590-20-050000": ("20-F", "2020-04-10", "2020-04-10T10:00:00.000Z", []),
    }


# The five results releases become events, three of them read from the
# 6-K's own document; every 6-K gets a decision; the deck is never read;
# the release's reaction date is the filing day (accepted before the open).
def test_tsm_6k_events_are_selected_by_headline_and_decisions_cached():
    fake = FakeEdgar(TSM, _tsm_filings())
    events, decided = _fetch(TSM, fake)
    assert [e.accession for e in events] == [
        "0001193125-15-254327",
        "0001564590-20-001200",
        "0001564590-20-016960",
        "0001564590-20-032443",
        "0001564590-20-046453",
    ]
    assert all(e.form == "6-K" for e in events)
    assert events[2].reaction_date == date(2020, 4, 16)
    assert {k: v for k, v in decided.items() if not v} == {
        "0001564590-20-046046": False,
        "0001564590-20-044420": False,
        "0001564590-20-052746": False,
        "0001564590-20-053724": False,
    }
    assert len(decided) == 9
    assert not any(u.endswith("tsm-ex992_9.htm") for u in fake.urls)
    assert any(u.endswith("tsm-6k_20200416.htm") for u in fake.urls)

    # A second fetch with the decisions in hand reads no filing page.
    fake.urls.clear()
    again, decided_again = _fetch(TSM, fake, decided)
    assert [e.accession for e in again] == [e.accession for e in events]
    assert decided_again == decided
    assert fake.urls == [f"https://data.sec.gov/submissions/CIK{TSM:010d}.json"]


# A refused index page is an unavailable fetch, not a cached "no".
def test_refused_page_fails_the_name_rather_than_caching_a_no():
    fake = FakeEdgar(TSM, _tsm_filings())
    folder = "000156459020046453"
    fake.refuse.add(
        f"https://www.sec.gov/Archives/edgar/data/{TSM}/{folder}/"
        "0001564590-20-046453-index.html"
    )
    with pytest.raises(edgar.EdgarUnavailableError):
        _fetch(TSM, fake)


# The same filings under a CIK that is not listed yield no 6-K events and
# no page reads beyond the submissions document.
def test_unlisted_issuer_admits_no_6k():
    fake = FakeEdgar(99, _tsm_filings())
    events, decided = _fetch(99, fake)
    assert events == ()
    assert decided == {}
    assert len(fake.urls) == 1


# Nebius reports under the CIK Yandex used; 6-Ks before 2024-10-01 are
# not candidates, whatever they say.
def test_nebius_starts_in_october_2024():
    block = {
        "form": ["6-K", "6-K"],
        "items": ["", ""],
        "acceptanceDateTime": ["2024-07-30T11:00:00.000Z", "2024-10-31T12:00:00.000Z"],
        "filingDate": ["2024-07-30", "2024-10-31"],
        "accessionNumber": ["old", "new"],
    }
    assert [e.accession for e in edgar.parse_submissions_block(block, NBIS)] == ["new"]
    # An 8-K with no item 2.02 is still refused, and a 6-K without a CIK too.
    block["form"] = ["8-K", "6-K"]
    block["filingDate"] = ["2024-11-30", "2024-10-31"]
    assert [e.accession for e in edgar.parse_submissions_block(block, NBIS)] == ["new"]
    assert edgar.parse_submissions_block(block) == []


# An index with no EX-99 yields None by default and the 6-K document when
# named; through `fetch_release_text`, a 6-K without an exhibit is read
# from its own document with the cover removed, an 8-K without one is not.
def test_release_text_falls_back_to_the_6k_document_only():
    documents = [("6-K", "d1d6k.htm", "/Archives/edgar/data/1/0001/d1d6k.htm")]
    assert language.press_release_href(documents) is None
    assert language.press_release_href(documents, "6-K") == (
        "https://www.sec.gov/Archives/edgar/data/1/0001/d1d6k.htm"
    )
    fake = FakeEdgar(TSM, _tsm_filings())
    main = edgar.EarningsEvent(
        datetime(2020, 4, 16, 10, tzinfo=UTC),
        date(2020, 4, 16),
        "0001564590-20-016960",
        "",
        form="6-K",
    )
    pacer = edgar.Pacer(sleep=_nosleep, interval=0)
    text = language.fetch_release_text(TSM, main, fake, pacer, _nosleep)
    assert text.startswith("& Chief Financial Officer TSMC Reports Second Quarter")
    eight_k = edgar.EarningsEvent(main.accepted, main.filed, main.accession, "2.02")
    assert language.fetch_release_text(TSM, eight_k, fake, pacer, _nosleep) is None


# The form column round-trips through the store, and a frame written
# before the column existed reads every event as an 8-K; the decisions
# ride on the metadata and come back intact.
def test_form_and_decisions_round_trip_and_legacy_frames_read_as_8k(tmp_path):
    store = MarketStore(tmp_path)
    events = (
        edgar.EarningsEvent(
            datetime(2025, 5, 1, 20, 10, tzinfo=UTC), date(2025, 5, 1), "a", "2.02"
        ),
        edgar.EarningsEvent(
            datetime(2025, 10, 16, 10, 39, tzinfo=UTC),
            date(2025, 10, 16),
            "b",
            "",
            "6-K",
        ),
    )
    record = edgar.CompanyRecord(
        "TSM",
        TSM,
        events,
        (),
        datetime(2026, 1, 1, tzinfo=UTC),
        {"b": True, "c": False},
    )
    columns, _facts = edgar.record_frames(record)
    assert columns["form"] == ["8-K", "6-K"]
    meta = {
        "cik": str(TSM),
        "classified_6k": edgar.decisions_to_metadata(record.decisions_6k),
    }
    assert store.write_frame("edgar_events", date(2026, 1, 2), "TSM", columns, meta)
    stored, stored_meta = store.read_frame("edgar_events", "TSM")
    assert [e.form for e in edgar.events_from_columns(stored)] == ["8-K", "6-K"]
    assert edgar.decisions_from_metadata(stored_meta) == {"b": True, "c": False}
    assert market_edgar.prior_decisions(store, "TSM", date(2026, 1, 3)) == {
        "b": True,
        "c": False,
    }
    legacy = {k: v for k, v in columns.items() if k != "form"}
    assert [e.form for e in edgar.events_from_columns(legacy)] == ["8-K", "8-K"]
    assert edgar.decisions_from_metadata({"cik": "1"}) == {}


# `--reclassify-6k` drops the carried refusals and keeps the admissions,
# so a refresh re-reads exactly the 6-Ks the previous rule refused; without
# it every carried decision is kept.
def test_reclassify_drops_carried_refusals_only(tmp_path, monkeypatch):
    store = MarketStore(tmp_path)
    asof = date(2026, 10, 2)
    store.write_frame(
        "edgar_events",
        asof - timedelta(days=1),
        "NBIS",
        {"accepted": [], "filed": [], "accession": [], "items": [], "form": []},
        {
            "cik": str(NBIS),
            "classified_6k": edgar.decisions_to_metadata({"yes": True, "no": False}),
        },
    )
    seen: list[dict] = []

    def fake_company(ticker, cik, pacer=None, decisions=None, **_):
        seen.append(dict(decisions or {}))
        return edgar.CompanyRecord(
            ticker, cik, (), (), datetime(2026, 10, 2, tzinfo=UTC), decisions or {}
        )

    monkeypatch.setattr(edgar, "fetch_cik_map", lambda pacer=None: {"NBIS": NBIS})
    monkeypatch.setattr(edgar, "fetch_company", fake_company)
    assert market_edgar.refresh(store, ("NBIS",), asof) == ()
    assert seen == [{"yes": True, "no": False}]
    store2 = MarketStore(tmp_path / "again")
    store2.write_frame(
        "edgar_events",
        asof - timedelta(days=1),
        "NBIS",
        {"accepted": [], "filed": [], "accession": [], "items": [], "form": []},
        {
            "cik": str(NBIS),
            "classified_6k": edgar.decisions_to_metadata({"yes": True, "no": False}),
        },
    )
    seen.clear()
    assert market_edgar.refresh(store2, ("NBIS",), asof, reclassify_6k=True) == ()
    assert seen == [{"yes": True}]
    assert market_edgar.build_parser().parse_args(["--reclassify-6k"]).reclassify_6k


# --- four a year ------------------------------------------------------------


# Four quarterly results filings a year on the given days, each with the
# filer's exhibit naming, plus the filings that must stay refused.
def _nbis_filings():
    ex = "EX-99.1"
    filings = {
        "0001104659-24-112875": _filing(
            date(2024, 10, 31),
            [(ex, "tm2427209d1_ex99-1.htm", HEADS["nbis_announces"])],
        ),
        "0001104659-25-015480": _filing(
            date(2025, 2, 20), [(ex, "tm257185d1_ex99-1.htm", HEADS["nbis_announces"])]
        ),
        "0001104659-25-050975": _filing(
            date(2025, 5, 20),
            [
                (ex, "tm2515580d1_ex99-1.htm", HEADS["nbis_announces"]),
                ("EX-99.2", "tm2515580d1_ex99-2.htm", "letter"),
                ("EX-99.3", "tm2515580d1_ex99-3.htm", "deck"),
            ],
        ),
        "0001104659-25-055197": _filing(
            date(2025, 6, 2), [(ex, "tm2516825d1_ex99-1.htm", HEADS["nbis_placement"])]
        ),
        "0001104659-25-075028": _filing(
            date(2025, 8, 7), [(ex, "tm2522866d1_ex99-1.htm", HEADS["nbis_reports"])]
        ),
        "0001104659-25-088312": _filing(
            date(2025, 9, 8), [(ex, "tm2525580d1_ex99-1.htm", HEADS["nbis_agreement"])]
        ),
        "0001104659-25-109806": _filing(
            date(2025, 11, 12), [(ex, "tm2530882d1_ex99-1.htm", HEADS["nbis_reports"])]
        ),
        # The same day: the ATM program (no exhibit) and its agreement.
        "0001104659-25-109803": _filing(
            date(2025, 11, 12),
            [("6-K", "tm2530882d2_6k.htm", TSM_COVER + HEADS["nbis_atm"])],
        ),
        "0001104659-25-110028": _filing(
            date(2025, 11, 12),
            [(ex, "tm2530882d3_ex99-1.htm", "NEBIUS GROUP N.V. Equity Distribution")],
        ),
        "0001104659-26-013946": _filing(
            date(2026, 2, 12), [(ex, "tm266173d1_ex99-1.htm", HEADS["nbis_full_year"])]
        ),
        "0001104659-26-059872": _filing(
            date(2026, 5, 13), [(ex, "tm2614392d1_ex99-1.htm", HEADS["nbis_reports"])]
        ),
        # The interim report a week later, and again beside the Q2 release.
        "0001104659-26-064092": _filing(
            date(2026, 5, 20),
            [(ex, "nbis-20260331xex99d1.htm", HEADS["nbis_interim_report"])],
        ),
        "0001104659-26-094568": _filing(
            date(2026, 8, 12), [(ex, "tm2622968d1_ex99-1.htm", HEADS["nbis_reports"])]
        ),
        "0001104659-26-094844": _filing(
            date(2026, 8, 12),
            [(ex, "nbis-20260812xex99d1.htm", HEADS["nbis_interim_report"])],
        ),
    }
    return filings


def _asml_filings():
    filings = {}
    n = 0
    for year in range(2021, 2027):
        for month, key in (
            (1, "asml_full_year"),
            (4, "asml_quarter"),
            (7, "asml_quarter"),
            (10, "asml_quarter"),
        ):
            if (year, month) == (2026, 10):
                continue
            n += 1
            name = (
                "pressreleasefinancialresul.htm"
                if year == 2026
                else "pressreleasequarterlyresul.htm"
            )
            filings[f"0000937966-{year % 100:02d}-{n:06d}"] = _filing(
                date(year, month, 16),
                [
                    ("6-K", "form6-kquarterlyfilings.htm", "cover"),
                    ("EX-99.1", name, HEADS[key]),
                    ("EX-99.2", "presentationinvestorrela.htm", "deck"),
                    ("EX-99.3", "financialstatementsusgaapq.htm", "statements"),
                ],
            )
        n += 1
        filings[f"0000937966-{year % 100:02d}-{n:06d}"] = _filing(
            date(year, 2, 25),
            [("EX-99.1", "pressreleaseannualreport.htm", HEADS["asml_annual"])],
        )
        n += 1
        filings[f"0000937966-{year % 100:02d}-{n:06d}"] = _filing(
            date(year, 3, 11),
            [("EX-99.1", "pressreleasebuyback.htm", HEADS["asml_buyback"])],
        )
    filings["0001193125-22-283523"] = _filing(
        date(2022, 11, 14),
        [("EX-99.1", "d369368dex991.htm", HEADS["asml_investor_day"])],
    )
    return filings


def _simo_filings():
    ex = "EX-99.1"
    return {
        "0001193125-24-247899": _filing(
            date(2024, 10, 31), [(ex, "d767261dex991.htm", HEADS["simo_results"])], 1
        ),
        "0001193125-25-020960": _filing(
            date(2025, 2, 6), [(ex, "d852766dex991.htm", HEADS["simo_results"])], 1
        ),
        "0001193125-25-020962": _filing(
            date(2025, 2, 6), [(ex, "d910912dex991.htm", HEADS["simo_repurchase"])], 1
        ),
        "0001193125-25-076840": _filing(
            date(2025, 4, 9), [(ex, "d941953dex991.htm", HEADS["simo_call"])], 20
        ),
        "0001193125-25-104428": _filing(
            date(2025, 4, 30), [(ex, "d866776dex991.htm", HEADS["simo_results"])], 1
        ),
        "0001193125-25-156599": _filing(
            date(2025, 7, 8), [(ex, "d45450dex991.htm", HEADS["simo_call"])], 20
        ),
        "0001193125-25-169571": _filing(
            date(2025, 7, 31), [(ex, "d56272dex991.htm", HEADS["simo_results"])], 1
        ),
        "0001193125-25-234040": _filing(
            date(2025, 10, 8), [(ex, "d35925dex991.htm", HEADS["simo_call"])], 12
        ),
        "0001193125-25-251599": _filing(
            date(2025, 10, 27), [(ex, "d27715dex991.htm", HEADS["simo_dividend"])], 20
        ),
        "0001193125-25-259296": _filing(
            date(2025, 10, 31), [(ex, "d51890dex991.htm", HEADS["simo_results"])]
        ),
        "0001193125-26-036180": _filing(
            date(2026, 2, 4), [(ex, "d10809dex991.htm", HEADS["simo_year_ended"])], 1
        ),
        "0001193125-26-188049": _filing(
            date(2026, 4, 29),
            [(ex, "d285401dex991.htm", HEADS["simo_quarterly_period"])],
            1,
        ),
        "0001193125-26-324391": _filing(
            date(2026, 7, 30),
            [(ex, "d114913dex991.htm", HEADS["simo_quarterly_period"])],
            1,
        ),
    }


# Each filer's fixtures through the fetch, the store and the audit: four
# admitted a year for NBIS 2025, ASML 2021-2025 and SIMO 2025, the partial
# first and last years reported, every other 6-K refused, no CHECK.
def test_audit_shows_four_a_year_per_filer(tmp_path, capsys):
    store = MarketStore(tmp_path)
    asof = date(2026, 10, 1)
    expected = {
        "NBIS": ("2024:1 2025:4 2026:3", 6),
        "ASML": ("2021:4 2022:4 2023:4 2024:4 2025:4 2026:3", 13),
        "SIMO": ("2024:1 2025:4 2026:3", 5),
    }
    for ticker, cik, filings in (
        ("NBIS", NBIS, _nbis_filings()),
        ("ASML", ASML, _asml_filings()),
        ("SIMO", SIMO, _simo_filings()),
    ):
        events, decided = _fetch(cik, FakeEdgar(cik, filings))
        assert len(decided) == len(filings)
        record = edgar.CompanyRecord(
            ticker, cik, events, (), datetime(2026, 10, 1, tzinfo=UTC), decided
        )
        columns, _facts = edgar.record_frames(record)
        meta = {"cik": str(cik), "classified_6k": edgar.decisions_to_metadata(decided)}
        assert store.write_frame("edgar_events", asof, ticker, columns, meta)
    assert market_edgar.audit_6k(store, ("NBIS", "ASML", "SIMO"), asof) is True
    out = capsys.readouterr().out
    for ticker, (years, refused) in expected.items():
        line = next(ln for ln in out.splitlines() if ln.startswith(ticker))
        assert f"refused={refused:4d} ok {years}" in line, line
    assert "CHECK" not in out
    # SIMO's newest admitted release is the 2026-07-30 filing, not 2025-07-31.
    assert "2026-07-30 0001193125-26-324391" in out


def _tone(**overrides):
    base = dict(
        guidance=0.6,
        demand=0.4,
        pricing=0.1,
        capex=0.5,
        supply_constrained=0.7,
        summary="outlook up",
        truncated=False,
        quarter_end="2025-09-30",
        revenue_usd_m=989_920.0,
        eps_usd=17.44,
        net_income_usd_m=452_300.0,
        gross_margin_pct=59.5,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# A 6-K from an issuer reporting in another currency keeps its five scores
# and summary but stores no dollar figures; a dollar-reporting 6-K issuer
# and an 8-K keep them.
def test_non_dollar_6k_release_stores_no_financials():
    when = datetime(2025, 10, 16, 10, 39, tzinfo=UTC)
    tsm = edgar.EarningsEvent(when, date(2025, 10, 16), "a", "", "6-K")
    record = market_tone.tone_record(tsm, _tone(), TSM, "m")
    assert (record.guidance, record.demand, record.supply_constrained) == (
        0.6,
        0.4,
        0.7,
    )
    assert record.summary == "outlook up"
    assert record.quarter_end == date(2025, 9, 30)
    assert (
        record.revenue_usd_m,
        record.eps_usd,
        record.net_income_usd_m,
        record.gross_margin_pct,
    ) == (None, None, None, None)
    asml = market_tone.tone_record(tsm, _tone(), ASML, "m")
    assert asml.revenue_usd_m is None
    arm = market_tone.tone_record(tsm, _tone(), ARM, "m")
    assert arm.revenue_usd_m == 989_920.0
    eight_k = edgar.EarningsEvent(when, date(2025, 10, 16), "a", "2.02")
    assert market_tone.tone_record(eight_k, _tone(), TSM, "m").eps_usd == 17.44
    # Nothing a non-dollar release states reaches the fundamental layer.
    assert edgar.release_facts({"TSM": [record]}) == {"TSM": []}


# The refresh path stores the 6-K release with its tone and no figures,
# reading the frame's form column.
def test_refresh_scores_a_6k_event_with_financials_none(tmp_path, monkeypatch):
    store = MarketStore(tmp_path)
    asof = date(2026, 9, 13)
    store.write_frame(
        "edgar_events",
        asof,
        "TSM",
        {
            "accepted": ["2025-10-16T10:39:55+00:00"],
            "filed": [date(2025, 10, 16)],
            "accession": ["0001046179-25-000116"],
            "items": [""],
            "form": ["6-K"],
        },
        {"cik": str(TSM)},
    )
    monkeypatch.setattr(language, "fetch_release_text", lambda *a, **k: "release")
    reader = SimpleNamespace(score_sync=lambda text: _tone())
    scored, missing, stored = market_tone._refresh_ticker(
        store, "TSM", asof, date(2015, 1, 1), [reader], "m", edgar.Pacer()
    )
    assert (scored, missing, stored) == (1, 0, 1)
    columns, _meta = store.read_frame(language.TONE_KIND, "TSM", asof)
    assert columns["guidance"] == [0.6]
    assert columns["revenue_usd_m"] == [None]
    assert columns["reaction_date"] == [date(2025, 10, 16)]


# The audit counts admitted 6-Ks per filing year and flags a full year
# without four; the partial first and last years are reported, not flagged.
def test_audit_counts_four_a_year(tmp_path, capsys):
    rows = []
    day = date(2023, 10, 16)
    for i in range(10):  # 2023: 1, 2024: 4, 2025: 4, 2026: 1
        rows.append((day + timedelta(days=91 * i), f"acc{i}"))
    columns = {
        "accepted": [
            datetime.combine(d, datetime.min.time(), UTC).isoformat() for d, _ in rows
        ],
        "filed": [d for d, _ in rows],
        "accession": [a for _, a in rows],
        "items": [""] * len(rows),
        "form": ["6-K"] * len(rows),
    }
    counts, short = market_edgar.audit_6k_frame(columns)
    assert counts == {2023: 1, 2024: 4, 2025: 4, 2026: 1}
    assert short == []
    columns["form"][3] = "8-K"  # one 2024 release lost: the year is flagged
    counts, short = market_edgar.audit_6k_frame(columns)
    assert counts[2024] == 3
    assert short == [2024]

    store = MarketStore(tmp_path)
    store.write_frame(
        "edgar_events", date(2026, 9, 1), "TSM", columns, {"cik": str(TSM)}
    )
    assert market_edgar.audit_6k(store, ("TSM", "ZZZ"), None) is False
    out = capsys.readouterr().out
    assert "CHECK [2024]" in out
    assert "ZZZ    MISSING" in out
    assert "2024:3" in out


# The stored round trip of a ToneRecord with None figures still reads back.
def test_tone_frame_with_none_financials_round_trips():
    record = language.ToneRecord(
        "a", date(2025, 10, 16), 0.6, 0.4, 0.1, 0.5, 0.7, "s", "m", "v", False
    )
    columns = language.tone_frame([record])
    assert asdict(language.records_from_frame(columns)[0]) == asdict(record)
