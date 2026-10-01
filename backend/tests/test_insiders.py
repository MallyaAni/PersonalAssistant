"""The insider-stance arms on synthetic transaction tables.

What has to hold: the quarterly zip's three tables join into purchase and
sale rows with the filing date, the 10b5-1 flag and the owner's role;
admission keeps Form 4 originals by officers and directors and refuses
the rest; the routine rule classifies an insider from the three prior
calendar years of trades filed before the row, so a trade in the same
month three years running is routine, a scattered trader is
opportunistic, a short history is unclassified, and a late-filed prior
trade cannot make a current one routine; a row is known on the first
session strictly after its filing date, so a trade filed late never
appears before its filing and a Friday filing is known on Monday; the
window nets buys against sells in dollars over the median dollar volume
and drops a row after ninety sessions; an empty table gives a zero
signal, a rank of one half, no stance and no defined IC (the null);
`fetch` stores one frame per quarter with its SHA-256, skips what the
partition holds and continues past a refused quarter. No network.
"""

import io
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_insiders as cli
from backend.market import edgar, insiders
from backend.market.harness import evaluate_scores
from backend.market.panel import panel_from_histories
from backend.market.store import MarketStore
from backend.market.yahoo import DailyBar, TickerHistory

FIRST = date(2019, 1, 2)
SESSIONS = 1100
NAMES = 24
BENCHMARK = "SPY"
ACME, BETA = 1001, 1002


# Session dates: weekdays from FIRST, no holidays.
def _sessions(count: int = SESSIONS) -> list[date]:
    out: list[date] = []
    day = FIRST
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


# A history at a constant price with a constant volume, one bar a session.
def _history(ticker: str, price: float, volume: int, sessions) -> TickerHistory:
    bars = tuple(
        DailyBar(day, price, price * 1.01, price * 0.99, price, price, volume)
        for day in sessions
    )
    return TickerHistory(
        ticker, bars, (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


# A panel of NAMES names plus the benchmark: ACME at $10 with one million
# shares a day (ten million dollars), the rest at $50.
@pytest.fixture(scope="module")
def panel():
    sessions = _sessions()
    histories = {BENCHMARK: _history(BENCHMARK, 400.0, 50_000_000, sessions)}
    histories["ACME"] = _history("ACME", 10.0, 1_000_000, sessions)
    histories["BETA"] = _history("BETA", 20.0, 500_000, sessions)
    for i in range(NAMES - 2):
        histories[f"N{i:02d}"] = _history(f"N{i:02d}", 50.0, 200_000, sessions)
    return panel_from_histories(histories, BENCHMARK, {})


CIKS = {ACME: "ACME", BETA: "BETA"}


# One transaction row with sensible defaults.
def _row(
    filed: date,
    traded: date | None = None,
    code: str = "P",
    shares: float = 1000.0,
    price: float = 10.0,
    issuer: int = ACME,
    owner: int = 7,
    relationship: str = "Officer",
    document_type: str = "4",
    plan: bool = False,
    accession: str | None = None,
) -> insiders.Transaction:
    traded = traded or filed - timedelta(days=2)
    return insiders.Transaction(
        accession=accession or f"{issuer}-{owner}-{filed.isoformat()}-{code}",
        filed=filed,
        traded=traded,
        issuer_cik=issuer,
        symbol=CIKS.get(issuer, ""),
        owner_cik=owner,
        relationship=relationship,
        code=code,
        shares=shares,
        price=price,
        direct=True,
        plan=plan,
        document_type=document_type,
        timeliness="",
    )


# --- the zip -----------------------------------------------------------------


# A quarterly zip in the SEC's layout from three lists of rows.
def _zip(submissions, owners, transactions) -> bytes:
    sub_cols = (
        "ACCESSION_NUMBER",
        "FILING_DATE",
        "PERIOD_OF_REPORT",
        "DOCUMENT_TYPE",
        "ISSUERCIK",
        "ISSUERNAME",
        "ISSUERTRADINGSYMBOL",
        "AFF10B5ONE",
    )
    own_cols = (
        "ACCESSION_NUMBER",
        "RPTOWNERCIK",
        "RPTOWNERNAME",
        "RPTOWNER_RELATIONSHIP",
    )
    tr_cols = (
        "ACCESSION_NUMBER",
        "NONDERIV_TRANS_SK",
        "TRANS_DATE",
        "TRANS_CODE",
        "TRANS_TIMELINESS",
        "TRANS_SHARES",
        "TRANS_PRICEPERSHARE",
        "TRANS_ACQUIRED_DISP_CD",
        "DIRECT_INDIRECT_OWNERSHIP",
    )

    def table(cols, rows):
        lines = ["\t".join(cols)]
        for row in rows:
            lines.append("\t".join(str(row.get(c, "")) for c in cols))
        return "\n".join(lines) + "\n"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SUBMISSION.tsv", table(sub_cols, submissions))
        archive.writestr("REPORTINGOWNER.tsv", table(own_cols, owners))
        archive.writestr("NONDERIV_TRANS.tsv", table(tr_cols, transactions))
        archive.writestr("FOOTNOTES.tsv", "ACCESSION_NUMBER\tFOOTNOTE_ID\n")
    return buffer.getvalue()


SAMPLE_ZIP = _zip(
    [
        {
            "ACCESSION_NUMBER": "0001-24-000001",
            "FILING_DATE": "31-JAN-2024",
            "DOCUMENT_TYPE": "4",
            "ISSUERCIK": "0000001001",
            "ISSUERTRADINGSYMBOL": "ACME",
            "AFF10B5ONE": "0",
        },
        {
            "ACCESSION_NUMBER": "0001-24-000002",
            "FILING_DATE": "05-FEB-2024",
            "DOCUMENT_TYPE": "4",
            "ISSUERCIK": "0000001001",
            "ISSUERTRADINGSYMBOL": "ACME",
            "AFF10B5ONE": "true",
        },
        {
            "ACCESSION_NUMBER": "0001-24-000003",
            "FILING_DATE": "06-FEB-2024",
            "DOCUMENT_TYPE": "4/A",
            "ISSUERCIK": "0000001002",
            "ISSUERTRADINGSYMBOL": "BETA",
            "AFF10B5ONE": "",
        },
    ],
    [
        {
            "ACCESSION_NUMBER": "0001-24-000001",
            "RPTOWNERCIK": "0000000007",
            "RPTOWNER_RELATIONSHIP": "Director,Officer",
        },
        {
            "ACCESSION_NUMBER": "0001-24-000002",
            "RPTOWNERCIK": "0000000008",
            "RPTOWNER_RELATIONSHIP": "Officer",
        },
        {
            "ACCESSION_NUMBER": "0001-24-000003",
            "RPTOWNERCIK": "0000000009",
            "RPTOWNER_RELATIONSHIP": "TenPercentOwner",
        },
        {
            "ACCESSION_NUMBER": "0001-24-000003",
            "RPTOWNERCIK": "0000000010",
            "RPTOWNER_RELATIONSHIP": "Director",
        },
    ],
    [
        {
            "ACCESSION_NUMBER": "0001-24-000001",
            "TRANS_DATE": "15-NOV-2022",
            "TRANS_CODE": "S",
            "TRANS_SHARES": "200.0",
            "TRANS_PRICEPERSHARE": "21.97",
            "DIRECT_INDIRECT_OWNERSHIP": "D",
        },
        {
            "ACCESSION_NUMBER": "0001-24-000001",
            "TRANS_DATE": "29-JAN-2024",
            "TRANS_CODE": "F",
            "TRANS_SHARES": "50.0",
            "TRANS_PRICEPERSHARE": "22.0",
            "DIRECT_INDIRECT_OWNERSHIP": "D",
        },
        {
            "ACCESSION_NUMBER": "0001-24-000002",
            "TRANS_DATE": "01-FEB-2024",
            "TRANS_CODE": "P",
            "TRANS_SHARES": "1000",
            "TRANS_PRICEPERSHARE": "",
            "DIRECT_INDIRECT_OWNERSHIP": "I",
        },
        {
            "ACCESSION_NUMBER": "0001-24-000003",
            "TRANS_DATE": "02-FEB-2024",
            "TRANS_CODE": "P",
            "TRANS_SHARES": "10",
            "TRANS_PRICEPERSHARE": "5",
            "DIRECT_INDIRECT_OWNERSHIP": "D",
        },
    ],
)


# The zip joins into P/S rows with the filing date, the flag and the
# officer-or-director owner; the F row is left out; a blank price is NaN.
def test_parse_zip_joins_the_three_tables():
    rows = insiders.parse_zip(SAMPLE_ZIP)
    assert [r.code for r in rows] == ["S", "P", "P"]
    late = rows[0]
    assert late.filed == date(2024, 1, 31)
    assert late.traded == date(2022, 11, 15)
    assert (late.issuer_cik, late.owner_cik) == (ACME, 7)
    assert late.relationship == "Director,Officer"
    assert not late.plan
    assert (late.shares, late.price, late.direct) == (200.0, 21.97, True)
    plan = rows[1]
    assert plan.plan
    assert np.isnan(plan.price)
    assert not plan.direct
    amended = rows[2]
    assert (amended.document_type, amended.symbol) == ("4/A", "BETA")
    # The officer/director owner is chosen over the 10% owner listed first.
    assert (amended.owner_cik, amended.relationship) == (10, "Director")


# A zip without the transaction table is refused rather than read as empty.
def test_parse_zip_refuses_a_zip_without_the_tables():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SUBMISSION.tsv", "ACCESSION_NUMBER\n")
    with pytest.raises(ValueError, match="lacks"):
        insiders.parse_zip(buffer.getvalue())


# The index page's links map quarter labels to absolute URLs, whichever
# prefix a quarter sits under.
def test_parse_index_reads_every_prefix():
    html = (
        '<a href="/files/datastandardsinnovation/data/insider-transactions-data-sets/'
        '2026q2_form345.zip">x</a> '
        '<a href="/files/structureddata/data/insider-transactions-data-sets/'
        '2006q1_form345.zip">y</a>'
    )
    index = insiders.parse_index(html)
    assert index["2026q2"].startswith("https://www.sec.gov/files/datastandards")
    assert index["2006q1"].endswith("2006q1_form345.zip")
    labels = insiders.quarter_labels(date(2026, 10, 1))
    assert (labels[0], labels[-1], len(labels)) == ("2006q1", "2026q4", 84)


# The frame round-trips every row, NaN price included.
def test_frame_round_trip():
    rows = insiders.parse_zip(SAMPLE_ZIP)
    back = insiders.transactions_from_frame(insiders.transactions_frame(rows))
    assert len(back) == len(rows)
    for a, b in zip(rows, back, strict=True):
        assert (a.accession, a.filed, a.traded, a.code, a.shares) == (
            b.accession,
            b.filed,
            b.traded,
            b.code,
            b.shares,
        )
        assert (np.isnan(a.price) and np.isnan(b.price)) or a.price == b.price
        assert (a.plan, a.document_type) == (b.plan, b.document_type)


# --- admission ---------------------------------------------------------------


# Form 4 originals by officers and directors, P or S, unflagged, with
# shares: everything else is refused and counted by reason.
def test_admit_keeps_originals_by_insiders_and_counts_refusals():
    day = date(2024, 3, 1)
    rows = [
        _row(day),
        _row(day, code="S", owner=8),
        _row(day, document_type="4/A"),
        _row(day, document_type="5"),
        _row(day, relationship="TenPercentOwner"),
        _row(day, relationship="Other"),
        _row(day, plan=True),
        _row(day, shares=0.0),
        _row(day, shares=float("nan")),
        _row(day, relationship="Director,TenPercentOwner"),
    ]
    kept, refused = insiders.admit(rows)
    assert [r.relationship for r in kept] == [
        "Officer",
        "Officer",
        "Director,TenPercentOwner",
    ]
    assert refused == {
        "not_form_4_original": 2,
        "not_purchase_or_sale": 0,
        "not_officer_or_director": 2,
        "plan_trade": 1,
        "no_shares": 2,
    }


# --- the routine rule --------------------------------------------------------


# Insider 1 sells every March for three years: the 2022 trades are
# routine. Insider 2 trades in a different month each year: opportunistic.
# Insider 3 has two years of history: unclassified. Insider 4's March
# pattern in 2019 was filed late, after the 2022 row: not routine at the
# time, so the row is opportunistic... unless the 2019 trade was filed
# in time, in which case it is routine.
def test_routine_rule_over_three_prior_years_point_in_time():
    history = []
    for year in (2019, 2020, 2021):
        history.append(_row(date(year, 3, 10), code="S", owner=1))
    for year, month in ((2019, 2), (2020, 6), (2021, 11)):
        history.append(_row(date(year, month, 10), code="S", owner=2))
    for year in (2020, 2021):
        history.append(_row(date(year, 3, 10), code="S", owner=3))
    # Insider 4: March 2020 and 2021 filed on time, March 2019 filed in 2023.
    history.append(_row(date(2020, 3, 10), code="S", owner=4))
    history.append(_row(date(2021, 3, 10), code="S", owner=4))
    history.append(_row(date(2023, 1, 5), traded=date(2019, 3, 10), code="S", owner=4))
    current = [
        _row(date(2022, 3, 8), code="S", owner=1),
        _row(date(2022, 7, 8), code="S", owner=1),  # a routine trader's July too
        _row(date(2022, 3, 8), code="S", owner=2),
        _row(date(2022, 3, 8), code="S", owner=3),
        _row(date(2022, 3, 8), code="S", owner=4),
    ]
    labels = insiders.classify(current, history + current)
    by_owner = [labels[insiders.row_key(r)] for r in current]
    assert by_owner == [
        "routine",
        "routine",
        "opportunistic",
        "unclassified",
        "unclassified",
    ]
    kept = insiders.opportunistic(current, history + current)
    assert [r.owner_cik for r in kept] == [2]
    # Had insider 4's March 2019 trade been filed in time, the same 2022
    # row would be routine: the late filing is what hid the pattern.
    on_time = [r for r in history if r.owner_cik != 4 or r.filed.year != 2023]
    on_time.append(_row(date(2019, 3, 12), code="S", owner=4))
    labels = insiders.classify(current, on_time + current)
    assert labels[insiders.row_key(current[4])] == "routine"


# The rule is per insider per issuer: the same owner's trades at another
# issuer do not count toward the pattern.
def test_routine_rule_is_per_issuer():
    history = [
        _row(date(y, 3, 10), code="S", owner=1, issuer=BETA) for y in (2019, 2020, 2021)
    ]
    history.append(_row(date(2019, 5, 1), code="S", owner=1))
    history.append(_row(date(2020, 5, 1), code="S", owner=1))
    history.append(_row(date(2021, 9, 1), code="S", owner=1))
    current = [_row(date(2022, 3, 8), code="S", owner=1)]
    labels = insiders.classify(current, history + current)
    assert labels[insiders.row_key(current[0])] == "opportunistic"


# --- dating ------------------------------------------------------------------


# A filing is known on the first session strictly after its date: a
# Friday filing on Monday, a Saturday filing on Monday, a filing after
# the last session never.
def test_known_session_is_the_first_session_after_the_filing(panel):
    dates = panel.dates
    friday = date(2019, 1, 4)
    monday = date(2019, 1, 7)
    assert dates[insiders.known_session(friday, dates)] == np.datetime64(monday)
    assert dates[insiders.known_session(date(2019, 1, 5), dates)] == np.datetime64(
        monday
    )
    assert dates[insiders.known_session(date(2019, 1, 1), dates)] == np.datetime64(
        FIRST
    )
    last = dates[-1].astype("datetime64[D]").astype(object)
    assert insiders.known_session(last, dates) == len(dates)
    assert insiders.known_session(last + timedelta(days=30), dates) == len(dates)


# A trade transacted in 2019 but filed in 2020 contributes nothing before
# its filing and everything from the session after it.
def test_a_late_filing_never_appears_before_its_filing(panel):
    filed = date(2020, 2, 3)  # a Monday
    row = _row(filed, traded=date(2019, 11, 15), shares=1000.0, price=10.0)
    dated = insiders.date_rows(panel, [row], CIKS)
    assert len(dated) == 1
    known = dated[0].session
    assert panel.dates[known] == np.datetime64(date(2020, 2, 4))
    net = insiders.window_net_dollars(panel, dated)
    column = panel.index("ACME")
    traded_at = insiders.known_session(date(2019, 11, 15), panel.dates)
    assert net[traded_at, column] == 0.0
    assert net[known - 1, column] == 0.0
    assert net[known, column] == 10_000.0


# --- the window --------------------------------------------------------------


# A buy of 1,000 at $10 and a sale of 300 at $20 net to +4,000 dollars;
# over ACME's ten-million-dollar median day that is 4e-4; the buy leaves
# the window ninety sessions after it was known.
def test_window_nets_buys_against_sells_and_drops_after_ninety(panel):
    buy = _row(date(2020, 3, 2), shares=1000.0, price=10.0)
    sell = _row(date(2020, 3, 4), code="S", shares=300.0, price=20.0, owner=8)
    dated = insiders.date_rows(panel, [buy, sell], CIKS)
    signal = insiders.window_signal(panel, dated)
    column = panel.index("ACME")
    s_buy, s_sell = dated[0].session, dated[1].session
    assert signal[s_buy, column] == pytest.approx(10_000.0 / 10_000_000.0)
    assert signal[s_sell, column] == pytest.approx(4_000.0 / 10_000_000.0)
    assert signal[s_buy + insiders.WINDOW - 1, column] == pytest.approx(
        4_000.0 / 10_000_000.0
    )
    assert signal[s_buy + insiders.WINDOW, column] == pytest.approx(
        -6_000.0 / 10_000_000.0
    )
    assert signal[s_sell + insiders.WINDOW, column] == 0.0
    # Another name with no row is exactly zero, and the benchmark is NaN.
    assert signal[s_buy, panel.index("BETA")] == 0.0
    assert np.isnan(signal[s_buy, panel.index(BENCHMARK)])


# A blank price is replaced by the name's close on the session the row
# becomes known.
def test_blank_price_uses_the_close_on_the_known_session(panel):
    row = _row(date(2020, 3, 2), shares=100.0, price=float("nan"), issuer=BETA)
    dated = insiders.date_rows(panel, [row], CIKS)
    assert dated[0].dollars == pytest.approx(100.0 * 20.0)


# The scale is NaN until forty-five sessions have a bar, then the median.
def test_dollar_volume_scale_needs_forty_five_sessions(panel):
    scale = insiders.dollar_volume_scale(panel)
    column = panel.index("ACME")
    assert np.isnan(scale[insiders.MIN_VOLUME_SESSIONS - 2, column])
    assert scale[insiders.MIN_VOLUME_SESSIONS - 1, column] == pytest.approx(1e7)
    assert scale[-1, column] == pytest.approx(1e7)


# Rows whose issuer is not mapped, or that are only known after the
# panel ends, are dropped.
def test_date_rows_drops_unmapped_and_unknowable(panel):
    last = panel.dates[-1].astype("datetime64[D]").astype(object)
    rows = [
        _row(date(2020, 3, 2), issuer=9999),
        _row(last),
        _row(date(2020, 3, 2)),
    ]
    dated = insiders.date_rows(panel, rows, CIKS)
    assert [d.ticker for d in dated] == ["ACME"]


# The opportunistic arm leaves out the routine insider's rows, the
# all-insiders arm keeps them; both share one scale.
def test_arm_signals_split_routine_from_opportunistic(panel):
    history = [_row(date(y, 3, 10), code="S", owner=1) for y in (2019, 2020, 2021)]
    history += [
        _row(date(y, m, 10), code="S", owner=2)
        for y, m in ((2019, 2), (2020, 6), (2021, 11))
    ]
    current = [
        _row(date(2022, 3, 8), code="S", owner=1, shares=1000.0, price=10.0),
        _row(date(2022, 3, 8), code="P", owner=2, shares=1000.0, price=10.0),
    ]
    admitted, _ = insiders.admit(current)
    signals, dated = insiders.arm_signals(panel, admitted, history + current, CIKS)
    column = panel.index("ACME")
    session = dated[0].session
    assert signals[insiders.ARM_OPPORTUNISTIC][session, column] == pytest.approx(1e-3)
    assert signals[insiders.ARM_ALL][session, column] == pytest.approx(0.0)
    assert [d.opportunistic for d in dated] == [False, True]


# The per-row table round-trips the dated rows.
def test_dated_frame_round_trip(panel):
    rows = [_row(date(2020, 3, 2)), _row(date(2020, 3, 4), code="S", owner=8)]
    dated = insiders.date_rows(panel, rows, CIKS, {insiders.row_key(rows[0])})
    labels = insiders.classify(rows, rows)
    back = insiders.dated_from_frame(panel, insiders.dated_frame(panel, dated, labels))
    assert [(d.ticker, d.session, d.dollars, d.opportunistic) for d in back] == [
        (d.ticker, d.session, d.dollars, d.opportunistic) for d in dated
    ]


# --- the null ----------------------------------------------------------------


# An empty table: zero wherever the denominator exists, NaN only where it
# does not, a rank of one half, no stance, and no defined IC.
def test_null_empty_table_is_the_neutral_baseline(panel):
    signal = insiders.window_signal(panel, [])
    scale = insiders.dollar_volume_scale(panel)
    book = np.array([t != BENCHMARK for t in panel.tickers])
    assert np.all(signal[:, book][np.isfinite(scale[:, book])] == 0.0)
    assert np.all(np.isnan(signal[:, book][~np.isfinite(scale[:, book])]))
    ranks = Opinion("null", np.where(book[None, :], signal, np.nan)).ranks()
    assert np.all(ranks[np.isfinite(ranks)] == 0.5)
    assert cli.stance_table(panel, ranks)["stance"] == []
    report = evaluate_scores(ranks, panel, 20, min_names=15)
    assert report.count > 0
    assert len(report.defined_ics) == 0
    sides = {t: "ai" for t in panel.tickers if t != BENCHMARK}
    in_book = np.array([t in sides for t in panel.tickers])
    result = cli.null_test(panel, in_book)
    assert result["pass"], result


# --- the criteria ------------------------------------------------------------


# One in-window arm block with the given numbers.
def _block(ic, t, delta=0.0, pair_t=0.0, corr=0.1):
    arms = {
        cli.ARM_DESK: {"ic": 0.04, "t": 3.0},
        insiders.ARM_OPPORTUNISTIC: {"ic": ic, "t": t},
        insiders.ARM_ALL: {"ic": 0.0, "t": 0.0},
    }
    return {
        "arms": arms,
        "paired_vs_desk": {
            a: {"delta": delta, "t": pair_t} for a in arms if a != cli.ARM_DESK
        },
        "correlation_with_desk": {a: {"mean": corr} for a in arms if a != cli.ARM_DESK},
    }


# The IC floor with agreeing halves and a non-negative pairing is a
# candidate; opposite halves, or a worse-than-desk pairing, is RECORD;
# a failed null is INVALID.
def test_criteria_apply_the_plan():
    windows = {
        "in_window": _block(0.03, 2.5),
        "first_half": _block(0.02, 1.0),
        "second_half": _block(0.04, 2.0),
        "out_of_window": _block(0.01, 0.5),
    }
    crit = cli.criteria(windows, True)[insiders.ARM_OPPORTUNISTIC]
    assert crit["clears_ic_floor"]
    assert crit["halves_not_opposite"]
    assert crit["role"] == "sixth analyst"
    assert cli.verdict(crit).startswith("CANDIDATE (sixth analyst)")
    assert crit["book_gate"].startswith("pending")
    windows["second_half"] = _block(-0.01, -0.5)
    crit = cli.criteria(windows, True)[insiders.ARM_OPPORTUNISTIC]
    assert not crit["halves_not_opposite"]
    assert cli.verdict(crit) == "RECORD"
    windows["second_half"] = _block(0.04, 2.0)
    windows["in_window"] = _block(0.03, 2.5, delta=-0.02, pair_t=-2.0, corr=0.5)
    crit = cli.criteria(windows, True)[insiders.ARM_OPPORTUNISTIC]
    assert not crit["not_worse_than_desk"]
    assert crit["role"] == "replacement candidate"
    assert cli.verdict(cli.criteria(windows, False)[insiders.ARM_ALL]).startswith(
        "INVALID"
    )


# --- fetch -------------------------------------------------------------------


# A transport answering the index and two quarters, refusing a third.
def _transport(calls: list[str]):
    index = (
        '<a href="/files/structureddata/data/insider-transactions-data-sets/'
        '2024q1_form345.zip">a</a>'
    )

    def transport(url: str) -> tuple[int, bytes]:
        calls.append(url)
        if url == insiders.INDEX_URL:
            return 200, index.encode()
        if "2024q1" in url or "2024q2" in url:
            return 200, SAMPLE_ZIP
        return 404, b""

    return transport


# `fetch` stores one frame per quarter with the SHA-256, keeps the zip on
# disk, reports the refused quarter and continues; a second run skips
# what the partition holds and makes no request.
def test_fetch_stores_quarters_resumably(tmp_path: Path):
    store = MarketStore(tmp_path)
    calls: list[str] = []
    asof = date(2026, 10, 1)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    failed = cli.fetch(
        store,
        asof,
        only=("2024q1", "2024q2", "2024q3"),
        transport=_transport(calls),
        pacer=edgar.Pacer(sleep=lambda _: None),
        sleep=lambda _: None,
        now=now,
    )
    assert failed == ("2024q3",)
    assert calls[0] == insiders.INDEX_URL
    assert store.has_frame(insiders.INSIDERS_KIND, asof, "2024q1")
    assert store.has_frame(insiders.INSIDERS_KIND, asof, "2024q2")
    assert not store.has_frame(insiders.INSIDERS_KIND, asof, "2024q3")
    columns, meta = store.read_frame(insiders.INSIDERS_KIND, "2024q1", asof)
    assert meta["sha256"] == cli.sha256_of(SAMPLE_ZIP)
    assert meta["rows"] == "3"
    assert len(insiders.transactions_from_frame(columns)) == 3
    assert (tmp_path / insiders.ZIP_DIR / "2024q1_form345.zip").exists()
    # The pattern URL served 2024q2, which the index did not list.
    assert any("2024q2_form345.zip" in url for url in calls)
    # A second run: the two stored quarters are kept, only the refused
    # one is requested again.
    before = len(calls)
    cli.fetch(
        store,
        asof,
        only=("2024q1", "2024q2", "2024q3"),
        transport=_transport(calls),
        pacer=edgar.Pacer(sleep=lambda _: None),
        sleep=lambda _: None,
        now=now,
    )
    requested = calls[before:]
    assert insiders.INDEX_URL in requested
    assert not any("2024q1" in u or "2024q2" in u for u in requested)
    # Nothing to do once every quarter is present: no request at all.
    before = len(calls)
    assert (
        cli.fetch(
            store,
            asof,
            only=("2024q1", "2024q2"),
            transport=_transport(calls),
            pacer=edgar.Pacer(sleep=lambda _: None),
            sleep=lambda _: None,
            now=now,
        )
        == ()
    )
    assert len(calls) == before


# A corrupt zip on disk is removed and reported, so the next run fetches it.
def test_fetch_discards_a_corrupt_zip_on_disk(tmp_path: Path):
    store = MarketStore(tmp_path)
    zip_dir = tmp_path / insiders.ZIP_DIR
    zip_dir.mkdir()
    (zip_dir / "2024q1_form345.zip").write_bytes(b"not a zip")
    calls: list[str] = []
    failed = cli.fetch(
        store,
        date(2026, 10, 1),
        only=("2024q1",),
        transport=_transport(calls),
        pacer=edgar.Pacer(sleep=lambda _: None),
        sleep=lambda _: None,
        now=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert failed == ("2024q1",)
    assert not (zip_dir / "2024q1_form345.zip").exists()


# --- the build's CIK map -----------------------------------------------------


# Names resolve through the stored `edgar_events` metadata first, then
# through the data set's symbol when exactly one issuer uses it.
def test_ticker_ciks_from_events_then_symbol(tmp_path: Path):
    store = MarketStore(tmp_path)
    asof = date(2026, 10, 1)
    store.write_frame(cli.EVENTS_KIND, asof, "ACME", {"accepted": []}, {"cik": "1001"})
    rows = [_row(date(2024, 1, 5), issuer=BETA), _row(date(2024, 1, 5), issuer=ACME)]
    mapped = cli.ticker_ciks(store, ["ACME", "BETA", "NONE"], rows, asof)
    assert mapped == {ACME: "ACME", BETA: "BETA"}


# --- build and evaluate end to end -------------------------------------------


# A store holding synthetic bars for every book name and the benchmark,
# one quarter's rows for two names (CIKs from the events metadata), and
# the build run over it; then the arms evaluated against a synthetic desk.
def test_build_and_evaluate_on_a_synthetic_store(tmp_path: Path):
    from backend.market.universe import MARKET_BENCHMARK, book_sides, build_universe

    sides = book_sides(build_universe())
    names = sorted(sides)
    sessions = _sessions(700)
    store = MarketStore(tmp_path)
    asof = date(2026, 10, 1)
    rng = np.random.default_rng(7)
    for ticker in [*names, MARKET_BENCHMARK]:
        returns = rng.normal(0.0, 0.01, len(sessions) - 1)
        prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
        bars = tuple(
            DailyBar(day, p, p * 1.01, p * 0.99, p, p, 1_000_000)
            for day, p in zip(sessions, prices, strict=True)
        )
        store.write(
            asof,
            TickerHistory(
                ticker, bars, (), sessions[-1], datetime(2026, 1, 1, tzinfo=UTC)
            ),
        )
    first, second = names[0], names[1]
    store.write_frame(cli.EVENTS_KIND, asof, first, {"accepted": []}, {"cik": "1001"})
    store.write_frame(cli.EVENTS_KIND, asof, second, {"accepted": []}, {"cik": "1002"})
    rows = [_row(date(y, 3, 10), code="S", owner=1) for y in (2019, 2020)]
    rows += [
        _row(date(2021, 3, 10), code="S", owner=1, shares=500.0, price=100.0),
        _row(
            date(2021, 4, 12), code="P", owner=2, issuer=BETA, shares=50.0, price=100.0
        ),
        _row(date(2021, 4, 12), code="P", owner=3, issuer=BETA, plan=True),
    ]
    store.write_frame(
        insiders.INSIDERS_KIND, asof, "2021q2", insiders.transactions_frame(rows), {}
    )
    out = tmp_path / "work"
    summary = cli.run_build(tmp_path, out, asof)
    assert summary["admitted"] == 4
    assert summary["refused"]["plan_trade"] == 1
    assert summary["names_mapped"] == 2
    assert second not in summary["names_without_rows"]
    table = cli.read_table(out / cli.ROWS_TABLE)
    assert sorted(set(table["ticker"])) == [first, second]
    assert all(
        date.fromisoformat(k) > date.fromisoformat(f)
        for k, f in zip(table["known_session"], table["filed"], strict=True)
    )
    panel, _ = cli._panel(tmp_path, asof)
    signals = cli.load_signals(out / cli.SIGNALS, panel)
    column = panel.index(second)
    known = insiders.known_session(date(2021, 4, 12), panel.dates)
    assert signals[insiders.ARM_ALL][known, column] == pytest.approx(
        5_000.0
        / float(np.median((panel.close * panel.volume)[known - 89 : known + 1, column]))
    )
    # Insider 2 has no history: unclassified, so absent from the opportunistic arm.
    assert signals[insiders.ARM_OPPORTUNISTIC][known, column] == 0.0

    # Evaluate against a synthetic desk: the payload carries every window
    # and horizon, the null passes, both arms get a verdict and a stance
    # table.
    desk = rng.normal(size=panel.close.shape)
    desk[:, panel.index(MARKET_BENCHMARK)] = np.nan
    arms = cli.arm_ranks(panel, signals, desk)
    payload = cli.evaluate_arms(panel, sides, arms)
    assert payload["null_test"]["pass"], payload["null_test"]
    assert set(payload["horizons"]) == {"20", "60"}
    assert set(payload["horizons"]["20"]) == set(cli.WINDOWS)
    assert set(payload["verdicts"]) == set(cli.ARMS)
    for arm in cli.ARMS:
        assert payload["verdicts"][arm] in {"RECORD"} or payload["verdicts"][
            arm
        ].startswith("CANDIDATE")
        stances = cli.stance_table(panel, arms[arm])
        assert set(stances) == {"session", "ticker", "stance"}
