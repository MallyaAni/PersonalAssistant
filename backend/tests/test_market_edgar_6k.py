"""Form 6-K results releases: admitted by headline, refused otherwise, cached.

No network: a fake transport serves a synthetic submissions document, filing
index pages and exhibit heads. What has to hold: a 6-K of a listed issuer
is an event only when its press release opens with that issuer's results
headline; the monthly revenue note, the full-statements filing, the
call-date notice and a financing are refused; an unlisted CIK admits no
6-K; TSMC's pre-2019-10 release is read from the main document; a refused
page fails the name rather than caching "not a release"; a cached decision
is not re-read; the `form` column survives the frame round trip and old
frames read as 8-K; a non-dollar issuer's financial fields are stored None
while its tone scores are kept; the audit counts four a year.
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

# Synthetic heads in the shape of each issuer's release title. None is a
# copy of a filing; each is the headline pattern and a made-up figure.
HEADS = {
    "tsm_results": "TSMC Reports Second Quarter EPS of NT$1.00 TSMC today announced",
    "tsm_monthly": "TSMC June Revenue Report TSMC today announced revenue for June",
    "tsm_statements": "Consolidated Financial Statements for the six months ended ...",
    "asml_results": "ASML reports EUR 1.0 billion total net sales and EUR 0.1 billion "
    "net income in Q2 2025",
    "asml_buyback": "ASML reports on share buyback transactions in the week of ...",
    "asml_annual": "ASML publishes its 2024 Annual Report based on US GAAP",
    "arm_results": "Arm Holdings plc Reports Results for the First Quarter of the "
    "Fiscal Year Ending March 31, 2027",
    "simo_results": "Silicon Motion Announces Results for the Period Ended June 30",
    "simo_call": "Silicon Motion Announces Second Quarter 2025 Earnings Call",
    "nbis_results": "Nebius Group Announces Second Quarter 2025 Financial Results",
    "nbis_offering": "Nebius Group Announces Pricing of Offering of Convertible Notes",
}


@pytest.mark.parametrize(
    ("cik", "key", "expected"),
    [
        (TSM, "tsm_results", True),
        (TSM, "tsm_monthly", False),
        (TSM, "tsm_statements", False),
        (ASML, "asml_results", True),
        (ASML, "asml_buyback", False),
        (ASML, "asml_annual", False),
        (ARM, "arm_results", True),
        (SIMO, "simo_results", True),
        (SIMO, "simo_call", False),
        (NBIS, "nbis_results", True),
        (NBIS, "nbis_offering", False),
        (99, "tsm_results", False),  # an unlisted issuer admits nothing
    ],
)
# Each issuer's headline admits its results release and nothing else.
def test_results_headlines_admit_only_results(cik, key, expected):
    assert edgar.is_results_headline(cik, HEADS[key]) is expected


# A results phrase past the head of the document does not count: the
# monthly note may mention "Reports First Quarter EPS" in its boilerplate.
def test_headline_is_read_from_the_head_only():
    text = "TSMC June Revenue Report " + "x " * 400 + HEADS["tsm_results"]
    assert edgar.is_results_headline(TSM, text) is False


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


def _tsm_filings():
    return {
        # An old release in the main document (2019-01), as TSMC filed then.
        "0001193125-19-000001": (
            "6-K",
            "2019-01-17",
            "2019-01-17T11:30:00.000Z",
            [("6-K", "d1d6k.htm", HEADS["tsm_results"])],
        ),
        # The modern shape: EX-99.1 release, EX-99.2 deck.
        "0001046179-25-000116": (
            "6-K",
            "2025-10-16",
            "2025-10-16T10:39:55.000Z",
            [
                ("6-K", "tsm-6k.htm", "cover"),
                ("EX-99.1", "a3q25e.htm", HEADS["tsm_results"]),
                ("EX-99.2", "deck.htm", "slides"),
            ],
        ),
        # Monthly revenue, full statements a month later: refused.
        "0001046179-25-000120": (
            "6-K",
            "2025-11-10",
            "2025-11-10T10:00:00.000Z",
            [("6-K", "m.htm", "cover"), ("EX-99.1", "mrev.htm", HEADS["tsm_monthly"])],
        ),
        "0001046179-25-000128": (
            "6-K",
            "2025-11-14",
            "2025-11-14T10:00:00.000Z",
            [("6-K", "s.htm", "cover"), ("EX-99.1", "fs.htm", HEADS["tsm_statements"])],
        ),
        # A 6-K with no release document at all: refused.
        "0001046179-25-000130": (
            "6-K",
            "2025-11-20",
            "2025-11-20T10:00:00.000Z",
            [("6-K", "b.htm", "board resolution")],
        ),
        # A 20-F is never an event.
        "0001046179-25-000050": ("20-F", "2025-04-10", "2025-04-10T10:00:00.000Z", []),
    }


# Only the two results releases become events; the older one is read from
# the main document; every 6-K gets a decision; the release's reaction
# date is the filing day (accepted 06:39 New York, before the open).
def test_6k_events_are_selected_by_headline_and_decisions_cached():
    fake = FakeEdgar(TSM, _tsm_filings())
    events, decided = edgar.fetch_events_with_decisions(
        TSM,
        transport=fake,
        pacer=edgar.Pacer(sleep=_nosleep, interval=0),
        sleep=_nosleep,
    )
    assert [e.accession for e in events] == [
        "0001193125-19-000001",
        "0001046179-25-000116",
    ]
    assert all(e.form == "6-K" for e in events)
    assert events[1].reaction_date == date(2025, 10, 16)
    assert decided == {
        "0001193125-19-000001": True,
        "0001046179-25-000116": True,
        "0001046179-25-000120": False,
        "0001046179-25-000128": False,
        "0001046179-25-000130": False,
    }
    # The deck and the cover were never read; the old main document was.
    assert not any(u.endswith("deck.htm") for u in fake.urls)
    assert any(u.endswith("d1d6k.htm") for u in fake.urls)

    # A second fetch with the decisions in hand reads no filing page.
    fake.urls.clear()
    again, decided_again = edgar.fetch_events_with_decisions(
        TSM,
        transport=fake,
        pacer=edgar.Pacer(sleep=_nosleep, interval=0),
        sleep=_nosleep,
        decisions=decided,
    )
    assert [e.accession for e in again] == [e.accession for e in events]
    assert decided_again == decided
    assert fake.urls == [f"https://data.sec.gov/submissions/CIK{TSM:010d}.json"]


# A refused index page is an unavailable fetch, not a cached "no".
def test_refused_page_fails_the_name_rather_than_caching_a_no():
    fake = FakeEdgar(TSM, _tsm_filings())
    folder = "000104617925000116"
    fake.refuse.add(
        f"https://www.sec.gov/Archives/edgar/data/{TSM}/{folder}/"
        "0001046179-25-000116-index.html"
    )
    with pytest.raises(edgar.EdgarUnavailableError):
        edgar.fetch_events_with_decisions(
            TSM,
            transport=fake,
            pacer=edgar.Pacer(sleep=_nosleep, interval=0),
            sleep=_nosleep,
        )


# The same filings under a CIK that is not listed yield no 6-K events and
# no page reads beyond the submissions document.
def test_unlisted_issuer_admits_no_6k():
    fake = FakeEdgar(99, _tsm_filings())
    events, decided = edgar.fetch_events_with_decisions(
        99,
        transport=fake,
        pacer=edgar.Pacer(sleep=_nosleep, interval=0),
        sleep=_nosleep,
    )
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


# The main-document fallback applies only where asked: an index with no
# EX-99 yields None by default and the 6-K document when named.
def test_press_release_href_falls_back_to_the_main_document_only_when_asked():
    documents = [("6-K", "d1d6k.htm", "/Archives/edgar/data/1/0001/d1d6k.htm")]
    assert language.press_release_href(documents) is None
    assert language.press_release_href(documents, "6-K") == (
        "https://www.sec.gov/Archives/edgar/data/1/0001/d1d6k.htm"
    )
    old = edgar.EarningsEvent(
        datetime(2019, 1, 17, 11, tzinfo=UTC), date(2019, 1, 17), "a", "", form="6-K"
    )
    new = edgar.EarningsEvent(
        datetime(2025, 10, 16, 10, tzinfo=UTC), date(2025, 10, 16), "b", "", form="6-K"
    )
    assert edgar.release_in_main_document(TSM, old) is True
    assert edgar.release_in_main_document(TSM, new) is False
    assert edgar.release_in_main_document(ASML, old) is False


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
