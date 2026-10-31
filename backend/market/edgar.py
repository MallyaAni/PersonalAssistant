"""SEC EDGAR: the information a price series does not hold, point in time.

Every model on price and volume alone measured at zero on this universe, so
the next input has to come from somewhere else. EDGAR is the free source
that is also *historically honest*: every filing carries the date it was
accepted, and every XBRL fact carries the date it was filed, so a feature
at session t can be built from exactly what was public at t.

Three things are read per company:

- **Earnings events** — 8-K filings with item 2.02 (results of operations),
  with their acceptance timestamp. A release accepted after the close
  moves the next session, which is where the reaction is measured. A
  foreign private issuer files Form 6-K instead, with no item codes, so a
  6-K is admitted only for a listed issuer (`RESULTS_6K_ISSUERS`) and only
  when the filing's press release opens with a results headline: a
  reporting verb, a period and a result together, and no word of another
  kind of filing (`results_headline`, `classify_6k`); the many other 6-Ks
  such issuers file (monthly revenue, full statements a month later,
  call-date notices, financings) are refused, a dividend or buyback is
  refused when it is what the release announces but not when it closes a
  results headline, and so are the filings that sit beside a quarter's
  release without being it (a month's sales, a preliminary figure, the
  audited year restated later:
  `BESIDE_THE_RELEASE`; a guidance update or outlook that reports no
  results: `OUTLOOK_ONLY`); each decision
  is cached so a refresh reads only the filings it has not seen.
- **Quarterly fundamentals** — revenue, net income, diluted EPS, capital
  expenditure, operating cash flow and gross profit from the company-facts
  API, kept as the *earliest-filed* value for each period so a later
  restatement never leaks backwards. Fourth quarters, which filers report
  only inside the annual figure, are derived as the year minus the three
  quarters already known.
- **The release text** — reachable through the filing index for the later
  language pass; this module only locates it.

`edgar_features` turns those into per-(session, name) inputs: sessions
since the last release, the residual return over the release's reaction
window carried forward (the post-earnings drift signal), revenue growth and
acceleration, EPS change, margins, capital intensity and its growth, and
how stale the latest fundamentals are. Names with nothing on file get
neutral fills and an indicator saying so, rather than NaN — a foreign
filer must stay in the cross-section, not vanish from it.
"""

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html import unescape
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import numpy as np

from backend.market.panel import Panel

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_ARCHIVE_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/index.json"
_ARCHIVE_DOCUMENT_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{name}"
)
_USER_AGENT = "AniOS research ani96bob@gmail.com"
_NEW_YORK = ZoneInfo("America/New_York")

# SEC asks for at most ten requests a second; stay well under it.
REQUEST_INTERVAL_SECONDS = 0.15

# The fundamentals read, each with the tags filers use for it, in order of
# preference. The first tag with quarterly facts wins.
FACT_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ),
    "net_income": ("NetIncomeLoss",),
    "eps": ("EarningsPerShareDiluted", "EarningsPerShareBasic"),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "gross_profit": ("GrossProfit",),
}

# Further tags for revenue and net income, read only by the per-session as-of
# selectors (`fundamentals_asof` and `levels_pit.versions_levels`), never by
# the frozen `parse_company_facts` above. Each inner tuple is a tier below
# `FACT_TAGS` (tier 0): a tier's tag is chosen only on a session when its
# latest filed quarter is later than that of every tag in a better tier, so a
# filer that reports under a listed tag keeps exactly its present reading, and
# one that stopped (AEP's and AVGO's `NetIncomeLoss` in 2024, JPM's revenue
# reported net of interest expense, JNJ's `SalesRevenueGoodsNet` to 2017) is no
# longer carried at its last listed quarter for years.
#
# revenue: tier 1 are whole-company totals by definition (a bank's revenue
# net of interest expense, a utility's regulated plus unregulated operating
# revenue); tier 2 are the pre-2018 goods / services / real-estate revenue
# tags, which some filers used for their total and some for one component,
# so they rank below every total.
# net_income: the parent's net income first (`FACT_TAGS`), then the income
# available to common stockholders (the parent's less preferred dividends),
# then profit including the noncontrolling interest only when neither is
# reported any longer.
FALLBACK_FACT_TAGS: dict[str, tuple[tuple[str, ...], ...]] = {
    "revenue": (
        ("RevenuesNetOfInterestExpense", "RegulatedAndUnregulatedOperatingRevenue"),
        ("SalesRevenueGoodsNet", "SalesRevenueServicesNet", "RealEstateRevenueNet"),
    ),
    "net_income": (
        ("NetIncomeLossAvailableToCommonStockholdersBasic",),
        ("ProfitLoss",),
    ),
}

# Share counts read only by `levels_pit.versions_levels`, one tier below the
# cover-page and balance-sheet counts (`INSTANT_TAGS["shares"]`), never by the
# frozen `parse_company_facts`. The company-facts feed carries no dimensional
# facts, so a filer that reports its cover count per share class (META, NET,
# TEAM, CRWV, MA, V ...) has no undimensioned count at all, or only one from
# before it split its classes (ACN's of 2010, WDAY's of 2018, CMCSA's of
# 2009), and its market capitalisation was missing or a decade stale. The
# weighted-average diluted count is reported undimensioned for the whole
# company every quarter, on the basis of the diluted earnings per share.
# They are durations, stored in the versions frame under their own name
# (`WEIGHTED_SHARES_NAME`), so every reader of the instant "shares" versions
# (`fundamentals_asof.levels_for`, `neural_price_basis`) is untouched.
WEIGHTED_SHARES_NAME = "weighted_shares"
SHARE_COUNT_FALLBACK_TAGS: tuple[str, ...] = (
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
)

# The cover-page XBRL instance reports the common-share count per class when a
# filer has more than one, and the company-facts feed drops those dimensions:
# BRK-B's only undimensioned count is from 2011, ERIE and STZ have none, and
# ARES and V carry only a decade-old or stale one. `fetch_cover_class_shares`
# reads the instance and combines the classes onto the listed security's
# basis; the result is stored in the versions frame under this synthetic tag,
# so the standard cover and balance-sheet tags still win a tie and every
# existing reader of the "shares" name keeps working unchanged.
CLASS_SHARES_TAG = "dei:EntityCommonStockSharesOutstanding#class"
# The panel starts in 2016; a 2015 filing is the earliest that can supply its
# first cover count, so a full backfill need not walk the 1990s.
CLASS_SHARE_EARLIEST = date(2015, 1, 1)
# A cover count below this is not a share count (ERIE's weighted-average
# fallback reads 2,542, BRK-B's 2011 count 941,481); the same floor
# `levels_pit.MIN_SHARES` applies when the count is used.
MIN_COVER_SHARES = 1e6
# A class with no listed symbol is only folded into the listed class's count
# when it is immaterial: above this share of the listed count, the two classes
# are not the same economics (V's Class C converts at 4.0, ARES' Class C is
# 47% of Class A), and summing or taking the listed count would misstate the
# company. The count is refused instead.
CLASS_SHARE_OTHER_TOLERANCE = 0.01

# Balance-sheet facts are instants (a value at a date, no span). Shares
# outstanding live in the dei taxonomy on the cover page; the us-gaap tag
# is the balance-sheet count. Either serves for growth in the share count.
# Cash-flow statements in a 10-Q run from the start of the fiscal year, so
# their spans are three, six and nine months; the quarter is the
# difference between consecutive spans of the same year.
YEAR_TO_DATE_NAMES: frozenset[str] = frozenset({"capex", "operating_cash_flow"})
INSTANT_TAGS: dict[str, tuple[tuple[str, str], ...]] = {
    "assets": (("us-gaap", "Assets"), ("ifrs-full", "Assets")),
    # For enterprise value: debt and cash as last reported. Filers tag
    # debt several ways; the first with a history is read.
    "debt": (
        ("us-gaap", "LongTermDebtNoncurrent"),
        ("us-gaap", "LongTermDebt"),
        ("us-gaap", "LongTermDebtAndCapitalLeaseObligations"),
        ("us-gaap", "DebtLongtermAndShorttermCombinedAmount"),
    ),
    "cash": (
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
        ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
        ("ifrs-full", "CashAndCashEquivalents"),
    ),
    "equity": (
        ("us-gaap", "StockholdersEquity"),
        (
            "us-gaap",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        ("ifrs-full", "Equity"),
    ),
    "shares": (
        ("dei", "EntityCommonStockSharesOutstanding"),
        ("us-gaap", "CommonStockSharesOutstanding"),
    ),
}

FEATURE_NAMES: tuple[str, ...] = (
    "sessions_since_earnings",
    "earnings_reaction",
    "revenue_yoy",
    "revenue_qoq",
    "revenue_acceleration",
    "eps_change_yoy",
    "net_margin",
    "net_margin_change_yoy",
    "capex_to_revenue",
    "capex_yoy",
    "ocf_to_revenue",
    "gross_margin",
    "fundamentals_staleness",
    "has_fundamentals",
    "has_events",
    "share_issuance",
    "asset_growth",
    "book_to_market",
)
FEATURE_COUNT = len(FEATURE_NAMES)

# Neutral fills for a name with nothing on file, and the clip for the
# "sessions since" counters so a never-reporting name is not an outlier.
NO_EVENT_SESSIONS = 250
NO_FACT_SESSIONS = 400

# --- Form 6-K results releases ---------------------------------------------
#
# A 6-K carries no item code, so the only way to tell a results release
# from the rest of an issuer's 6-Ks is the document itself. A results
# release opens with a headline of a fixed shape, whoever files it: a
# reporting verb ("reports", "announces", "publishes"), a period (a quarter,
# a full or fiscal year, a period ended) and a result (results, EPS, net
# sales, revenue, net income) within a few lines of each other, and no
# word of the other kinds of 6-K (a call notice, a dividend, a buyback, an
# offering, an annual general meeting, the statements themselves). This is
# a test of the document's shape, not a judgement of intent, and it applies
# only to the issuers listed below: an unlisted CIK admits nothing.
#
# Read 2026-10-01 against the filings themselves (NBIS 2024-10 to 2026-08,
# ASML 2015-2026, SIMO 2025-2026, TSM 2015 and 2019-2020); the previous
# per-issuer headline table refused NBIS entirely ("Nebius reports ...",
# "Nebius Group N.V. announces ..."), ASML's fourth-quarter release ("... net
# income in 2024", no "Q4 2024"), SIMO's 2025-10 release (non-breaking
# spaces as HTML entities inside the title) and its "Fourth Quarter and
# Year Ended" wording, and every TSMC release carried in the 6-K's main
# document (2015 to 2019-07, and 2020-04), where the cover page precedes
# the headline.
RESULTS_6K_ISSUERS: frozenset[int] = frozenset(
    {
        1046179,  # TSMC: "TSMC Reports Third Quarter EPS of NT$17.44"
        937966,  # ASML: "ASML reports €7.7 billion total net sales ... in Q1 2025"
        1973239,  # Arm: "Arm Holdings plc Reports Results for the Second Quarter ..."
        1329394,  # Silicon Motion: "... Announces Results for the Period Ended ..."
        1513845,  # Nebius: "Nebius reports second quarter financial results"
    }
)

# The first 6-K date admitted per issuer. Nebius reports under the CIK
# Yandex N.V. used until 2024; Yandex's releases are another business.
EARLIEST_6K: dict[int, date] = {1513845: date(2024, 10, 1)}

# Issuers whose releases state their figures in a currency other than the
# US dollar. The tone reader's financial fields are dollar amounts, so for
# these the fields are left unread (the five tone scores are kept).
REPORTING_CURRENCY: dict[int, str] = {1046179: "TWD", 937966: "EUR"}

# How much of a document's text the headline is looked for in, after the
# Form 6-K cover page (when the release is the main document) is removed.
# ASML's 2015 releases open with a block of media contacts; 800 covers it.
HEADLINE_CHARS = 800
# The title zone: the opening of the document, where the kind of a
# non-release (an interim report, the statements) is named.
TITLE_CHARS = 300
# The headline is the text around the first reporting verb: this many
# characters before it and after it.
HEADLINE_BEFORE = 120
HEADLINE_AFTER = 200

REPORTING_VERB = re.compile(
    r"\b(?:reports|reported|announces|announced|publishes|published"
    r"|releases|released)\b",
    re.I,
)
PERIOD_WORDS = re.compile(
    r"\b(?:(?:first|second|third|fourth)[ -]quarter|q[1-4]\b|[1-4]q(?:\d{2}|\d{4})?\b"
    r"|(?:quarter(?:ly)?(?: period)?|period|year|months)\s+ended"
    r"|full[- ]year|half[- ]year|fiscal (?:year|20\d\d)"
    r"|(?:three|six|nine|twelve) months"
    # "net income in 2024": a full-year figure named by its year. "sales"
    # alone is a figure too: "ASML reports record sales for 2015". The year
    # can also precede the figure: "ASML reports 2013 results as guided".
    r"|(?:net sales|sales|net income|net profit|revenues?|results)[^.]{0,20}?"
    r"\b(?:in|for) (?:fiscal |fy ?)?20\d\d\b"
    r"|\b20\d\d\s+(?:annual\s+|full[- ]year\s+)?(?:results|sales|revenues?)\b)",
    re.I,
)
RESULT_WORDS = re.compile(
    r"\b(?:results|earnings|eps|net sales|sales|net income|net profit|net loss"
    r"|revenues?)\b",
    re.I,
)
# The other kinds of 6-K, by the words their titles carry: the call-date
# notice ("Announces Third Quarter 2025 Earnings Conference Call", "plans
# to release"), dividends, buybacks and repurchases, the AGM, the annual
# report, an investor day, financings (offerings, placements, notes), the
# statements and interim reports ("Operating and Financial Review and
# Prospects"), TSMC's monthly "Revenue Report" and board resolutions.
NOT_A_RELEASE = re.compile(
    r"\b(?:conference call|earnings call|webcast"
    r"|(?:will|plans? to|to) (?:announce|report|release|host|hold|publish)"
    r"|annual general meeting|general meeting"
    r"|agm|annual report|investor day|prospectus"
    r"|(?:public|private|secondary|notes?|debt|equity|share|ads|follow-on) offering"
    r"|offering of|private placement|convertible|notes due"
    r"|senior (?:unsecured )?notes"
    r"|financial statements|operating and financial review|discussion and analysis"
    r"|interim report|revenue report|monthly|board of directors|resolutions?)\b",
    re.I,
)
# A dividend or a buyback named as the thing the release announces is
# another kind of filing ("Silicon Motion Announces Annual Cash Dividend
# Payable Quarterly", "ASML reports on share buyback transactions"). The
# same words also close a genuine results headline ("ASML reports EUR 10.9
# billion net sales and EUR 2.6 billion net income in 2018 ... proposes to
# raise dividend by 50%"; "ASML reports €11.8 billion sales and €2.6
# billion net income in 2019 ... announces a three-year share buyback
# program"), so they refuse only a headline that names no result before
# them.
NOT_A_RESULTS = re.compile(r"\b(?:dividends?|buy-?backs?|repurchases?)\b", re.I)
# A calendar month's name, for a month's sales ("March 2006 Sales Report").
_MONTH = (
    r"(?:january|february|march|april|may|june|july|august|september|october"
    r"|november|december)"
)
# The filings that sit beside a quarter's results release without being
# it, read 2026-10-01 against every admitted 6-K of the five filers: a
# month's sales ("TSMC March 2006 Sales Report", "net sales for December
# 2008", "TSMC Announce May 2005 Sales and Revise Upward 2Q2005
# Guidance"); a preliminary figure ("Announces Preliminary 1Q 2010
# Revenue", "based upon its preliminary first quarter financial results,
# sequential revenue growth is expected to be ..."); and the audited year
# restated months after the fourth-quarter release ("TSMC Announces 2012
# Fiscal Year-End Results ... the audited consolidated results ...
# SELECTED FINANCIAL DATA"). Each names a period and a figure, so the
# shape test alone admitted them beside the quarter's own release (TSMC
# and Silicon Motion counted five or six releases in a completed year).
# "unaudited" is not "audited".
BESIDE_THE_RELEASE = re.compile(
    rf"\b(?:{_MONTH}\s+(?:19|20)\d\d\s+(?:net\s+)?(?:sales|revenues?)"
    rf"|(?:sales|revenues?)\s+(?:for|in)\s+(?:the\s+month\s+of\s+)?{_MONTH}"
    r"\s+(?:19|20)\d\d"
    r"|(?:sales|revenues?) report"
    r"|preliminary"
    r"|audited|selected financial data)\b",
    re.I,
)
# A guidance update, revision or confirmation, or an outlook ("Updates
# First Quarter 2009 Guidance", "an update to its fourth quarter 2008
# financial guidance", "Confirms Previously Released Guidance", "TSMC
# Fourth Quarter and Full Year 2015 Revenue Outlook"). These words also
# appear in real releases ("ASML confirms 2013 outlook ... today publishes
# 2013 third-quarter results", "Nebius reports second quarter financial
# results and raises ARR guidance"), so they refuse only a head that does
# not also say results are published (`RESULTS_REPORTED`), including in the
# dateline after the title ("today publishes 2013 second-quarter results").
OUTLOOK_ONLY = re.compile(
    r"\b(?:(?:updates?|update to|updated|revises?|revised|confirms?|confirmed"
    r"|reaffirms?|reaffirmed)\b[^.]{0,60}?\bguidance"
    r"|(?:revenue|sales|earnings|business|financial) outlook)\b",
    re.I,
)
# A headline that says the period's results are out: a reporting verb with
# "results" a few words on ("today publishes 2013 third-quarter results",
# "announced its unaudited financial results"), or "EPS of". Only finite
# forms count: "ahead of reporting its results" is a notice, not a release.
RESULTS_REPORTED = re.compile(
    r"\b(?:(?:publishes|published|reports|reported|announces|announced"
    r"|releases|released)\s+(?:\S+\s+){0,6}?results"
    r"|eps of)\b",
    re.I,
)

# The Form 6-K cover page, when the release is the 6-K's own document: it
# ends with the signature block ("... duly caused this report to be signed
# ... By /s/ Name, Chief Financial Officer") or, unsigned, with the last
# check-mark line.
_COVER_MARK = re.compile(r"REPORT OF FOREIGN PRIVATE ISSUER", re.I)
_COVER_SIGNATURE = re.compile(
    r"the registrant has duly caused this report to be signed.{0,400}?/s/.{0,160}?"
    r"\b(?:Officer|Director|President|Secretary|Counsel|CFO|CEO|Treasurer|Chairman)\b",
    re.I | re.S,
)
_COVER_CHECKMARK = re.compile(
    r"Indicate by check mark[^\u2610\u2612]{0,400}?[\u2610\u2612]|82:[\s_]*\.?\)",
    re.I,
)


class EdgarUnavailableError(RuntimeError):
    """A fetch failed or was refused; the caller must flag, not crash."""


@dataclass(frozen=True, slots=True)
class EarningsEvent:
    """One results release: when it was accepted, and its filing identity."""

    accepted: datetime  # UTC
    filed: date
    accession: str
    items: str
    # The form filed: "8-K", or "6-K" for a foreign private issuer's
    # release (frames stored before the field existed read as 8-K).
    form: str = "8-K"

    # The first session on which the market could react: the acceptance
    # date itself when accepted before the close in New York, else the
    # next calendar day (the panel maps that to the next session).
    @property
    def reaction_date(self) -> date:
        local = self.accepted.astimezone(_NEW_YORK)
        if local.hour >= 16:
            return local.date() + timedelta(days=1)
        return local.date()


@dataclass(frozen=True, slots=True)
class QuarterFact:
    """One quarterly value of one fundamental, as first reported."""

    name: str  # key of FACT_TAGS
    start: date
    end: date
    value: float
    filed: date
    derived: bool = False  # a fourth quarter computed from the year


@dataclass(frozen=True, slots=True)
class CompanyRecord:
    """Everything fetched for one company, ready to store."""

    ticker: str
    cik: int
    events: tuple[EarningsEvent, ...]
    facts: tuple[QuarterFact, ...]
    source_time: datetime
    # Every 6-K looked at for this issuer, accession -> admitted, so the
    # next refresh reads only the filings it has not seen.
    decisions_6k: Mapping[str, bool] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FilingRef:
    """One periodic filing: its identity and the date it became public."""

    accession: str
    form: str
    filed: date
    accepted: datetime | None
    primary_document: str


@dataclass(frozen=True, slots=True)
class CoverShareCount:
    """A cover-page common-share count on the listed security's basis."""

    end: date
    value: float
    filed: date
    accepted: datetime | None
    accession: str
    form: str


Transport = Callable[[str], tuple[int, bytes]]


# The default transport: a plain GET with the contact user agent SEC asks
# for. EDGAR does not fingerprint; it rate-limits, which the Pacer handles.
def sec_transport(url: str) -> tuple[int, bytes]:
    """GET an EDGAR URL and return (status, body)."""
    from curl_cffi import requests

    response = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=60)
    return response.status_code, response.content


class Pacer:
    """Keeps requests at least `interval` apart; sleep and clock injectable."""

    def __init__(
        self,
        interval: float = REQUEST_INTERVAL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = interval
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    # Wait out whatever remains of the interval since the last request.
    def wait(self) -> None:
        """Sleep so that consecutive requests are spaced by the interval."""
        if self._last is not None:
            remaining = self._interval + self._last - self._clock()
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()


# Fetch a body from EDGAR with pacing and bounded retries on throttling.
def _get_bytes(
    url: str, transport: Transport, pacer: Pacer, sleep: Callable[[float], None]
) -> bytes:
    last = "no attempt"
    for attempt in range(1, 4):
        pacer.wait()
        try:
            status, body = transport(url)
        except Exception as exc:  # network layer
            last = f"transport error: {exc}"
            sleep(2.0 * attempt)
            continue
        if status == 200:
            return body
        if status == 404:
            raise EdgarUnavailableError(f"{url}: not found (404)")
        last = f"HTTP {status}"
        if status in (403, 429, 500, 502, 503):
            sleep(2.0 * attempt)
            continue
        break
    raise EdgarUnavailableError(f"{url}: refused ({last})")


# Fetch JSON from EDGAR with the same pacing and retries.
def _get_json(
    url: str, transport: Transport, pacer: Pacer, sleep: Callable[[float], None]
) -> Any:
    body = _get_bytes(url, transport, pacer, sleep)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise EdgarUnavailableError(f"{url}: non-JSON body") from exc


# Ticker -> CIK from SEC's own map. Class shares appear as BRK-B there.
def fetch_cik_map(
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, int]:
    """Return {ticker: cik} for every SEC-registered ticker."""
    payload = _get_json(_TICKERS_URL, transport, pacer or Pacer(sleep=sleep), sleep)
    return parse_cik_map(payload)


# Pure: the ticker map payload into a dict.
def parse_cik_map(payload: Mapping[str, Any]) -> dict[str, int]:
    """Parse company_tickers.json into {ticker: cik}."""
    out: dict[str, int] = {}
    for entry in payload.values():
        try:
            out[str(entry["ticker"]).upper()] = int(entry["cik_str"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


# Pure: one submissions block (recent or an older file) into events. An
# 8-K is an event when it carries item 2.02. A 6-K is a *candidate* only
# for an issuer in RESULTS_6K_ISSUERS (and not before its EARLIEST_6K date);
# whether it is a results release is decided later by `classify_6k` from
# the document itself, since the submissions block has no exhibit titles.
def parse_submissions_block(
    block: Mapping[str, Any], cik: int | None = None
) -> list[EarningsEvent]:
    """Return the 8-K item 2.02 events (and 6-K candidates) in a block."""
    forms = block.get("form") or []
    items = block.get("items") or []
    accepted = block.get("acceptanceDateTime") or []
    filed = block.get("filingDate") or []
    accession = block.get("accessionNumber") or []
    events: list[EarningsEvent] = []
    for i, form in enumerate(forms):
        row_items = items[i] if i < len(items) else ""
        if form == "8-K":
            if "2.02" not in row_items:
                continue
        elif form == "6-K":
            if cik is None or cik not in RESULTS_6K_ISSUERS:
                continue
        else:
            continue
        try:
            stamp = accepted[i].replace("Z", "+00:00")
            when = datetime.fromisoformat(stamp).astimezone(UTC)
            filed_on = date.fromisoformat(filed[i])
            if form == "6-K" and filed_on < EARLIEST_6K.get(cik, date.min):
                continue
            events.append(
                EarningsEvent(
                    accepted=when,
                    filed=filed_on,
                    accession=accession[i],
                    items=row_items,
                    form=form,
                )
            )
        except (IndexError, ValueError, AttributeError):
            continue
    return events


# Pure: the periodic filings in one submissions block, oldest first. The
# cover-page count lives in the 10-K or 10-Q instance, so only those forms
# are kept; a foreign private issuer files 20-F instead and has no cover
# count in this feed.
def parse_filings_block(
    block: Mapping[str, Any], forms: Sequence[str] = ("10-K", "10-Q")
) -> list[FilingRef]:
    """Return the 10-K/10-Q filings in a submissions block."""
    wanted = set(forms)
    filed = block.get("filingDate") or []
    accepted = block.get("acceptanceDateTime") or []
    accession = block.get("accessionNumber") or []
    primary = block.get("primaryDocument") or []
    out: list[FilingRef] = []
    for i, form in enumerate(block.get("form") or []):
        if form not in wanted:
            continue
        try:
            day = date.fromisoformat(filed[i])
        except (IndexError, TypeError, ValueError):
            continue
        when: datetime | None = None
        if i < len(accepted) and accepted[i]:
            try:
                when = datetime.fromisoformat(
                    str(accepted[i]).replace("Z", "+00:00")
                ).astimezone(UTC)
            except ValueError:
                when = None
        out.append(
            FilingRef(
                accession=str(accession[i]) if i < len(accession) else "",
                form=str(form),
                filed=day,
                accepted=when,
                primary_document=str(primary[i]) if i < len(primary) else "",
            )
        )
    return out


# Pure: the earliest filing date in a submissions block, whatever its form.
# The recent block's oldest filing decides whether an older block can hold a
# filing after `since`: every older-block filing predates it.
def _earliest_filed(block: Mapping[str, Any]) -> date | None:
    """Return the block's earliest filing date, or None."""
    dates: list[date] = []
    for value in block.get("filingDate") or []:
        try:
            dates.append(date.fromisoformat(str(value)))
        except ValueError:
            continue
    return min(dates, default=None)


# Fetch every 10-K and 10-Q for a company: the recent block plus each older
# block the submissions document points at, deduplicated by accession and
# returned oldest first. With `since`, the older blocks are read only when
# the recent block does not reach back that far, so a nightly incremental
# check reads one submissions document rather than the whole filing history.
def fetch_filings(
    cik: int,
    forms: Sequence[str] = ("10-K", "10-Q"),
    since: date | None = None,
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[FilingRef]:
    """Return all 10-K/10-Q filings for a CIK, oldest first."""
    pacer = pacer or Pacer(sleep=sleep)
    payload = _get_json(
        _SUBMISSIONS_URL.format(name=f"CIK{cik:010d}.json"), transport, pacer, sleep
    )
    filings = payload.get("filings") or {}
    recent = filings.get("recent") or {}
    out = parse_filings_block(recent, forms)
    earliest = _earliest_filed(recent)
    need_older = since is None or earliest is None or earliest > since
    if need_older:
        for older in filings.get("files") or []:
            name = older.get("name")
            if not name:
                continue
            block = _get_json(
                _SUBMISSIONS_URL.format(name=name), transport, pacer, sleep
            )
            out.extend(parse_filings_block(block, forms))
    unique = {filing.accession: filing for filing in out}
    return sorted(unique.values(), key=lambda f: (f.filed, f.accession))


# Pure: the text of a 6-K's main document with its Form 6-K cover page
# removed, so the headline search starts at the release. A document
# without the cover is returned as it is.
def strip_form_cover(text: str) -> str:
    """Return `text` after the Form 6-K cover page and signature block."""
    if not _COVER_MARK.search(text[:2000]):
        return text
    signed = _COVER_SIGNATURE.search(text[:3500])
    if signed:
        return text[signed.end() :].lstrip()
    marks = list(_COVER_CHECKMARK.finditer(text[:3000]))
    return text[marks[-1].end() :].lstrip() if marks else text


# Pure: the first dividend or buyback word in `text` when no result word
# precedes it, so a mention that is the announcement itself can be told
# from one that closes an otherwise genuine results headline. None when
# the text names no such word or names a result first.
def _money_before_results(text: str) -> re.Match[str] | None:
    """Return the dividend/buyback match that no result word precedes."""
    money = NOT_A_RESULTS.search(text)
    if money is None:
        return None
    result = RESULT_WORDS.search(text)
    if result is not None and result.start() < money.start():
        return None
    return money


# Pure: the first word in `text` that names another kind of filing, taking
# the earlier of an unconditional marker ("Resolutions", "Annual Report")
# and a dividend or buyback that is the announcement itself. The earlier
# word is what the filing is about: a board-resolution title with a
# dividend inside it is a resolution, while a dividend title that mentions
# the board is a dividend.
def _other_kind(text: str) -> re.Match[str] | None:
    """Return the earliest other-kind match in `text`, or None."""
    money = _money_before_results(text)
    other = NOT_A_RELEASE.search(text)
    if money is None or (other is not None and other.start() < money.start()):
        return other
    return money


# Pure: whether a release's text opens with a results headline, and why
# not. The headline is the text around the first reporting verb in the
# head of the document; it must name a period and a result, and neither
# it nor the document's title zone may name another kind of filing.
def results_headline(text: str) -> tuple[bool, str]:
    """Return (admitted, reason) for the head of a release's text."""
    head = strip_form_cover(text)[:HEADLINE_CHARS]
    verb = REPORTING_VERB.search(head)
    if verb is None:
        return False, "no reporting verb in the head"
    headline = head[
        max(0, verb.start() - HEADLINE_BEFORE) : verb.end() + HEADLINE_AFTER
    ]
    other = _other_kind(headline) or _other_kind(head[:TITLE_CHARS])
    if other is not None:
        return False, f"not a results release: {other.group(0)!r}"
    beside = BESIDE_THE_RELEASE.search(headline) or BESIDE_THE_RELEASE.search(
        head[:TITLE_CHARS]
    )
    if beside is None and RESULTS_REPORTED.search(head) is None:
        beside = OUTLOOK_ONLY.search(headline) or OUTLOOK_ONLY.search(
            head[:TITLE_CHARS]
        )
    if beside is not None:
        return False, f"not the quarter's results release: {beside.group(0)!r}"
    if PERIOD_WORDS.search(headline) is None:
        return False, "no period in the headline"
    if RESULT_WORDS.search(headline) is None:
        return False, "no result in the headline"
    return True, headline


# Pure: whether the head of a listed issuer's release opens with a results
# headline. An unlisted CIK admits nothing, whatever the text says.
def is_results_headline(cik: int, text: str) -> bool:
    """Return True when `text` opens with a results headline (listed CIK)."""
    return cik in RESULTS_6K_ISSUERS and results_headline(text)[0]


# Decide whether one 6-K is a results release: read its filing index,
# take the press-release document (EX-99.1, or the 6-K's own document when
# the filing has no exhibit, where TSMC put its releases until 2019 and
# again in 2020-04), and test its head for a results headline. A filing
# with no document at all is refused.
def classify_6k(
    cik: int,
    event: EarningsEvent,
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Return True when the 6-K's press release is a results release."""
    from backend.market import language

    pacer = pacer or Pacer(sleep=sleep)
    try:
        text = language.fetch_release_text(cik, event, transport, pacer, sleep)
    except RuntimeError as exc:
        # A refused page must not be cached as "not a release": the name
        # fails this refresh and keeps its last partition.
        raise EdgarUnavailableError(f"{event.accession}: {exc}") from exc
    return bool(text) and is_results_headline(cik, text)


# Fetch every earnings event for a company: the recent block plus each
# older block the submissions document points at. 6-K candidates are
# classified from their documents unless `decisions` already holds the
# accession; the decisions made (old and new) are returned beside the
# events so the caller can store them.
def fetch_events(
    cik: int,
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
    decisions: Mapping[str, bool] | None = None,
) -> tuple[EarningsEvent, ...]:
    """Return all earnings events for a CIK, oldest first."""
    events, _decided = fetch_events_with_decisions(
        cik, transport, pacer, sleep, decisions
    )
    return events


# `fetch_events` plus the 6-K decisions, for a caller that caches them.
def fetch_events_with_decisions(
    cik: int,
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
    decisions: Mapping[str, bool] | None = None,
) -> tuple[tuple[EarningsEvent, ...], dict[str, bool]]:
    """Return (events oldest first, {6-K accession: admitted})."""
    pacer = pacer or Pacer(sleep=sleep)
    payload = _get_json(
        _SUBMISSIONS_URL.format(name=f"CIK{cik:010d}.json"), transport, pacer, sleep
    )
    filings = payload.get("filings") or {}
    events = parse_submissions_block(filings.get("recent") or {}, cik)
    for older in filings.get("files") or []:
        name = older.get("name")
        if not name:
            continue
        block = _get_json(_SUBMISSIONS_URL.format(name=name), transport, pacer, sleep)
        events.extend(parse_submissions_block(block, cik))
    decided = dict(decisions or {})
    kept: dict[str, EarningsEvent] = {}
    for event in events:
        if event.form == "6-K":
            if event.accession not in decided:
                decided[event.accession] = classify_6k(
                    cik, event, transport, pacer, sleep
                )
            if not decided[event.accession]:
                continue
        kept[event.accession] = event
    return tuple(sorted(kept.values(), key=lambda e: e.accepted)), decided


# The local name of an XML element or attribute, without its namespace.
def _local(name: str) -> str:
    """Return an XML name with any namespace prefix removed."""
    return name.rsplit("}", 1)[-1]


# The local part of a QName, in either Clark notation (an element tag) or
# the prefixed form XBRL uses for a dimension and its member.
def _qname(name: str) -> str:
    """Return the local part of a QName."""
    return name.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


# A cover-page trading symbol on the same punctuation as a ticker, so
# "BRK.B" and "BRK-B" compare equal.
def _normalise_symbol(value: str) -> str:
    """Return a trading symbol in the ticker convention."""
    return value.strip().upper().replace(".", "-").replace("/", "-")


# Pure: the contexts of an XBRL instance, id -> (instant, dimensions).
def _instance_contexts(
    root: ElementTree.Element,
) -> dict[str, tuple[date | None, tuple[tuple[str, str], ...]]]:
    """Return each context's instant and its explicit dimensions."""
    contexts: dict[str, tuple[date | None, tuple[tuple[str, str], ...]]] = {}
    for element in root.iter():
        if _local(element.tag) != "context":
            continue
        context_id = element.get("id")
        if not context_id:
            continue
        instant: date | None = None
        members: list[tuple[str, str]] = []
        for child in element.iter():
            local = _local(child.tag)
            if local == "instant" and child.text:
                try:
                    instant = date.fromisoformat(child.text.strip())
                except ValueError:
                    instant = None
            elif local == "explicitMember":
                dimension = child.get("dimension") or ""
                if dimension:
                    members.append((dimension, (child.text or "").strip()))
        contexts[context_id] = (instant, tuple(members))
    return contexts


# Pure: the cover counts and trading symbols in an instance. A context whose
# two count facts disagree is marked ambiguous and never used.
def _cover_facts(
    root: ElementTree.Element,
    contexts: Mapping[str, tuple[date | None, tuple[tuple[str, str], ...]]],
) -> tuple[dict[str, float], set[str], dict[str, str]]:
    """Return (counts by context, ambiguous contexts, symbols by context)."""
    counts: dict[str, float] = {}
    ambiguous: set[str] = set()
    symbols: dict[str, str] = {}
    for element in root.iter():
        local = _local(element.tag)
        context_id = element.get("contextRef")
        if context_id is None:
            continue
        if local == "TradingSymbol":
            symbol = _normalise_symbol(element.text or "")
            if symbol:
                symbols[context_id] = symbol
        elif local == "EntityCommonStockSharesOutstanding":
            if context_id not in contexts:
                continue
            try:
                value = float((element.text or "").strip().replace(",", ""))
            except ValueError:
                continue
            if not np.isfinite(value) or value <= 0:
                continue
            if context_id in counts and counts[context_id] != value:
                ambiguous.add(context_id)
            counts[context_id] = value
    return counts, ambiguous, symbols


# Pure: the contexts that carry a common-share cover count for one class.
# A preferred class is not a common share; a context with another dimension
# beside the class axis is not a cover count; a context with disagreeing
# facts is ambiguous.
def _common_classes(
    contexts: Mapping[str, tuple[date | None, tuple[tuple[str, str], ...]]],
    counts: Mapping[str, float],
    ambiguous: set[str],
) -> dict[str, str]:
    """Return {context: class member} for the common classes."""
    out: dict[str, str] = {}
    for context_id, (instant, members) in contexts.items():
        if context_id not in counts or instant is None or context_id in ambiguous:
            continue
        if len(members) != 1:
            continue
        dimension, member = members[0]
        if _qname(dimension) != "StatementClassOfStockAxis":
            continue
        if "preferred" in _qname(member).lower():
            continue
        out[context_id] = member
    return out


# Pure: the one cover date the common classes share, or None.
def _class_end(
    contexts: Mapping[str, tuple[date | None, tuple[tuple[str, str], ...]]],
    classes: Mapping[str, str],
) -> date | None:
    """Return the classes' common instant date, or None."""
    ends: set[date] = set()
    for context_id in classes:
        instant = contexts[context_id][0]
        if instant is None:
            return None
        ends.add(instant)
    return ends.pop() if len(ends) == 1 else None


# Pure: the listed class's count when every other common class is
# immaterial. None when more than one common class is listed (BRK.A and
# BRK.B do not share economics, and the instance carries no conversion
# ratio), the ticker is not the listed class, or another common class is
# material (V's Class C converts at 4.0, ARES' Class C is 47% of Class A).
def _listed_class_count(
    listed: Mapping[str, str],
    classes: Mapping[str, str],
    counts: Mapping[str, float],
    wanted: str,
) -> float | None:
    """Return the listed class's count, or None when it is ambiguous."""
    if len(set(listed.values())) != 1 or set(listed.values()) != {wanted}:
        return None
    matching = [cid for cid, symbol in listed.items() if symbol == wanted]
    if len(matching) != 1:
        return None
    listed_id = matching[0]
    others = [cid for cid in classes if cid != listed_id]
    if any(
        counts[cid] > counts[listed_id] * CLASS_SHARE_OTHER_TOLERANCE
        for cid in others
    ):
        return None
    return float(counts[listed_id])


# Pure: whether a class member names common equity. Ordinary shares are
# common stock under another name (JCI, an Irish plc, lists
# jci:OrdinarySharesParValue001Member); preferred classes are not.
def _is_common_member(member: str) -> bool:
    """Return whether a class member names common equity."""
    lower = _qname(member).lower()
    return ("common" in lower or "ordinary" in lower) and "preferred" not in lower


# Pure: whether a trading-symbol context names a common share listing. An
# undimensioned symbol is the registrant's own cover-page line; an exchange
# listing is the same security on another exchange (ABT lists on XNYS and
# XCHI); a stock-class member is common only when its name says so. Notes,
# debentures and preferred classes are not common.
def _is_common_symbol_context(
    members: tuple[tuple[str, str], ...],
) -> bool:
    """Return whether a symbol context names a common share listing."""
    if not members:
        return True
    if len(members) != 1:
        return False
    dimension, member = members[0]
    name = _qname(dimension)
    if name == "EntityListingsExchangeAxis":
        return True
    if name != "StatementClassOfStockAxis":
        return False
    return _is_common_member(member)


# Pure: the one undimensioned cover count when the filing reports no
# common-class count. This is the ordinary single-class filer (ABT, C) and
# the utility filers that add subsidiary counts on dei:LegalEntityAxis
# beside the registrant's total (DTE, EXC, SO). The total is the listed
# security's count only when the ticker is a common or exchange listing and
# no other common class is listed: BRK.A beside BRK.B would make it a
# cross-class total. A preferred count or a subsidiary count does not
# disqualify the total, because neither is a common share of the registrant.
def _undimensioned_count(
    contexts: Mapping[str, tuple[date | None, tuple[tuple[str, str], ...]]],
    counts: Mapping[str, float],
    ambiguous: set[str],
    symbols: Mapping[str, str],
    wanted: str,
) -> tuple[date, float] | None:
    """Return (cover date, shares) for a single-class filer, or None."""
    candidates = [
        context_id
        for context_id, (instant, members) in contexts.items()
        if context_id in counts
        and context_id not in ambiguous
        and not members
        and instant is not None
    ]
    if len(candidates) != 1:
        return None
    listed = [
        symbol
        for context_id, symbol in symbols.items()
        if context_id in contexts
        and _is_common_symbol_context(contexts[context_id][1])
    ]
    if wanted not in listed or any(symbol != wanted for symbol in listed):
        return None
    # A common-class count the class reader could not use (no instant, or an
    # extra dimension beside the class axis) means the total is a cross-class
    # sum the filing does not split here; refuse rather than overstate.
    for context_id, (_, members) in contexts.items():
        if context_id not in counts or context_id == candidates[0]:
            continue
        if any(
            _qname(dimension) == "StatementClassOfStockAxis"
            and _is_common_member(member)
            for dimension, member in members
        ):
            return None
    context_id = candidates[0]
    instant = contexts[context_id][0]
    if instant is None:
        return None
    return instant, float(counts[context_id])


# Pure: the sum of the common classes when the filing lists one security
# undimensioned and reports its classes without symbols (STZ, ERIE).
def _undimensioned_sum(
    contexts: Mapping[str, tuple[date | None, tuple[tuple[str, str], ...]]],
    classes: Mapping[str, str],
    counts: Mapping[str, float],
    symbols: Mapping[str, str],
    wanted: str,
) -> float | None:
    """Return the sum of the common classes, or None when not one security."""
    undimensioned = {
        symbols[context_id]
        for context_id, (_, members) in contexts.items()
        if context_id in symbols and not members
    }
    if undimensioned != {wanted}:
        return None
    return float(sum(counts[cid] for cid in classes))


# Pure: the common-share count on one cover-page instance, on the listed
# security's basis. None whenever the filing does not support one number:
# no usable count, classes dated differently, a preferred class mixed in, an
# undimensioned count beside class counts, more than one listed common class
# (BRK.A and BRK.B have different economics, and the instance carries no
# conversion ratio), or a material unlisted class (V's Class C converts at
# 4.0, ARES' Class C is 47% of Class A). A refusal is the honest answer; a
# raw sum would misstate the company by tens of percent.
def parse_cover_class_shares(body: bytes, ticker: str) -> tuple[date, float] | None:
    """Return (cover date, common shares) for the listed security, or None."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return None
    wanted = _normalise_symbol(ticker)
    contexts = _instance_contexts(root)
    counts, ambiguous, symbols = _cover_facts(root, contexts)
    classes = _common_classes(contexts, counts, ambiguous)
    if not classes:
        return _undimensioned_count(contexts, counts, ambiguous, symbols, wanted)
    end = _class_end(contexts, classes)
    if end is None:
        return None
    # An undimensioned count beside class counts presents the total and its
    # split; which one is the company is a judgement the filing does not make.
    if any(not contexts[context_id][1] for context_id in counts):
        return None
    listed = {
        context_id: symbols[context_id]
        for context_id in classes
        if context_id in symbols
    }
    if listed:
        value = _listed_class_count(listed, classes, counts, wanted)
        return None if value is None else (end, value)
    total = _undimensioned_sum(contexts, classes, counts, symbols, wanted)
    return None if total is None else (end, total)


# Pure: the XBRL instance among a filing index's items. The instance is the
# XML document that is not a linkbase and not the filing summary; the
# largest is chosen because the instance carries the facts and the others
# are small.
def _instance_name(items: Sequence[Mapping[str, Any]]) -> str | None:
    """Return the XBRL instance document's name, or None."""
    best: tuple[int, str] | None = None
    for item in items:
        name = str(item.get("name") or "")
        if not name.lower().endswith(".xml"):
            continue
        base = name.rsplit("/", 1)[-1].lower()
        if base == "filingsummary.xml" or base.endswith(
            ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml")
        ):
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        candidate = (size, name)
        if best is None or candidate > best:
            best = candidate
    return best[1] if best else None


# Read the cover-page class counts from each periodic filing filed after
# `since` (or from 2015, when `since` is None). A filing whose index,
# instance or class structure cannot be read is skipped and named in the
# second return value; one refusal must not discard the others. The
# earliest-filed count for a cover date wins, matching the point-in-time
# rule that a later restatement never leaks backwards.
#
# The third return value is the latest filing date the reader got all the
# way through (index and instance fetched, structure judged), capped one
# day before the earliest transient fetch failure. The caller stores it as
# a watermark so the next night reads only newer filings: a name whose
# class structure is refused every time (V, ARES, BRK-B) must not download
# its whole filing history again each night, while a failed fetch must not
# be skipped permanently.
# Read one filing's cover-page class count. The third value is False when
# the fetch failed transiently, so the watermark must not advance past the
# filing; a structure the parser refuses is deterministic and does advance.
def _filing_cover_count(
    cik: int,
    ticker: str,
    filing: FilingRef,
    transport: Transport,
    pacer: Pacer,
    sleep: Callable[[float], None],
) -> tuple[CoverShareCount | None, str | None, bool]:
    """Return (count, refusal reason, fetched successfully)."""
    folder = filing.accession.replace("-", "")
    try:
        index = _get_json(
            _ARCHIVE_INDEX_URL.format(cik=cik, folder=folder),
            transport,
            pacer,
            sleep,
        )
    except EdgarUnavailableError as exc:
        return None, f"{filing.accession}: {exc}", False
    items = (index.get("directory") or {}).get("item") or []
    name = _instance_name(items)
    if name is None:
        return None, f"{filing.accession}: no XBRL instance", True
    try:
        body = _get_bytes(
            _ARCHIVE_DOCUMENT_URL.format(cik=cik, folder=folder, name=name),
            transport,
            pacer,
            sleep,
        )
    except EdgarUnavailableError as exc:
        return None, f"{filing.accession}: {exc}", False
    parsed = parse_cover_class_shares(body, ticker)
    if parsed is None:
        return None, f"{filing.accession}: no unambiguous class count", True
    end, value = parsed
    return (
        CoverShareCount(
            end=end,
            value=value,
            filed=filing.filed,
            accepted=filing.accepted,
            accession=filing.accession,
            form=filing.form,
        ),
        None,
        True,
    )


def fetch_cover_class_shares(
    cik: int,
    ticker: str,
    filings: Sequence[FilingRef],
    since: date | None = None,
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[CoverShareCount], list[str], date | None]:
    """Return (cover counts oldest first, skipped filings, checked-through)."""
    pacer = pacer or Pacer(sleep=sleep)
    by_end: dict[date, CoverShareCount] = {}
    skipped: list[str] = []
    checked: date | None = None
    failed: date | None = None
    for filing in filings:
        if since is not None:
            if filing.filed <= since:
                continue
        elif filing.filed < CLASS_SHARE_EARLIEST:
            continue
        count, reason, ok = _filing_cover_count(
            cik, ticker, filing, transport, pacer, sleep
        )
        if reason is not None:
            skipped.append(reason)
        if not ok:
            failed = filing.filed if failed is None else min(failed, filing.filed)
            continue
        if count is not None:
            held = by_end.get(count.end)
            if held is None or count.filed < held.filed:
                by_end[count.end] = count
        checked = filing.filed if checked is None else max(checked, filing.filed)
    if failed is not None:
        cap = failed - timedelta(days=1)
        checked = cap if checked is None else min(checked, cap)
    return sorted(by_end.values(), key=lambda c: c.end), skipped, checked


# Six- and nine-month spans of a year-to-date fact, earliest filed.
def _ytd_spans(
    rows: Sequence[Mapping[str, Any]], name: str
) -> dict[tuple[date, date], QuarterFact]:
    out: dict[tuple[date, date], QuarterFact] = {}
    for row in rows:
        try:
            start = date.fromisoformat(row["start"])
            end = date.fromisoformat(row["end"])
            filed = date.fromisoformat(row["filed"])
            value = float(row["val"])
        except (KeyError, TypeError, ValueError):
            continue
        days = (end - start).days
        if not (170 <= days <= 195 or 260 <= days <= 285):
            continue
        key = (start, end)
        fact = QuarterFact(name, start, end, value, filed)
        if key not in out or filed < out[key].filed:
            out[key] = fact
    return out


# Quarters from year-to-date spans: the six-month span less the first
# quarter of the same year gives the second quarter; the nine-month span
# less the six-month gives the third. Each derived quarter is stamped with
# the later filing of its two parts, so it is known when both were.
def _with_year_to_date_quarters(
    quarters: Mapping[tuple[date, date], QuarterFact],
    ytd: Mapping[tuple[date, date], QuarterFact],
) -> dict[tuple[date, date], QuarterFact]:
    out = dict(quarters)
    by_start: dict[date, list[QuarterFact]] = {}
    for fact in list(quarters.values()) + list(ytd.values()):
        by_start.setdefault(fact.start, []).append(fact)
    for facts in by_start.values():
        facts.sort(key=lambda f: f.end)
        for earlier, later in zip(facts, facts[1:], strict=False):
            kind = _span_kind(earlier.end + timedelta(days=1), later.end)
            if kind != "quarter":
                continue
            key = (earlier.end + timedelta(days=1), later.end)
            if key in out:
                continue
            out[key] = QuarterFact(
                later.name,
                key[0],
                key[1],
                later.value - earlier.value,
                max(later.filed, earlier.filed),
                derived=True,
            )
    return out


# Whether a (start, end) span is one quarter, or one fiscal year.
def _span_kind(start: date, end: date) -> str | None:
    days = (end - start).days
    if 80 <= days <= 100:
        return "quarter"
    if 350 <= days <= 380:
        return "year"
    return None


# Pure: the company-facts payload into earliest-filed quarterly facts, with
# fourth quarters derived from the annual figure where a filer reported
# none. EPS is a per-share figure, so its fourth quarter is derived too but
# the arithmetic is the same (the annual less the three quarters is what a
# filer's own Q4 would be, save for share-count drift).
def parse_company_facts(payload: Mapping[str, Any]) -> list[QuarterFact]:
    """Parse companyfacts JSON into point-in-time quarterly facts."""
    facts_root = payload.get("facts") or {}
    out: list[QuarterFact] = []
    for name, tags in FACT_TAGS.items():
        chosen: list[QuarterFact] = []
        # Filers switch tags over the years (ASC 606 renamed revenue for most
        # of the market in 2018). A tag that stopped being filed freezes its
        # series at its last reported quarter, so "most quarters" selects the
        # dead tag forever. Prefer the tag still being reported: the one with
        # the most recent period end, ties broken by how much history it has.
        best: tuple[date, int] | None = None
        for taxonomy in ("us-gaap", "ifrs-full"):
            for tag in tags:
                rows = _rows_for(facts_root, taxonomy, tag)
                quarters, years = _split_spans(rows, name)
                if name in YEAR_TO_DATE_NAMES:
                    quarters = _with_year_to_date_quarters(
                        quarters, _ytd_spans(rows, name)
                    )
                candidate = _with_derived_fourth_quarters(quarters, years)
                if not candidate:
                    continue
                latest = max(f.end for f in candidate)
                key = (latest, len(candidate))
                if best is None or key > best:
                    best = key
                    chosen = candidate
        out.extend(chosen)
    out.extend(_instant_facts(facts_root))
    out.sort(key=lambda f: (f.name, f.end, f.filed))
    return out


# Instant facts (assets, equity, shares): the earliest-filed value at each
# balance-sheet date, from the taxonomy/tag pair with the most recent date
# on file (ties broken by how many dates it carries), so a filer that
# switched tags mid-history is read from its current tag rather than a
# frozen one. Stored as QuarterFact rows with start == end.
def _instant_facts(facts_root: Mapping[str, Any]) -> list[QuarterFact]:
    out: list[QuarterFact] = []
    for name, pairs in INSTANT_TAGS.items():
        best: dict[date, QuarterFact] = {}
        best_key: tuple[date, int] | None = None
        for taxonomy, tag in pairs:
            rows = _rows_for(facts_root, taxonomy, tag)
            found: dict[date, QuarterFact] = {}
            for row in rows:
                if "start" in row and row.get("start"):
                    continue
                try:
                    end = date.fromisoformat(row["end"])
                    filed = date.fromisoformat(row["filed"])
                    value = float(row["val"])
                except (KeyError, TypeError, ValueError):
                    continue
                if end not in found or filed < found[end].filed:
                    found[end] = QuarterFact(name, end, end, value, filed)
            if not found:
                continue
            latest = max(found)
            key = (latest, len(found))
            if best_key is None or key > best_key:
                best_key = key
                best = found
        out.extend(best.values())
    return out


# All (unit-agnostic) rows for one tag in one taxonomy.
def _rows_for(facts_root: Mapping[str, Any], taxonomy: str, tag: str) -> list[dict]:
    units = ((facts_root.get(taxonomy) or {}).get(tag) or {}).get("units") or {}
    if not units:
        return []
    # One unit per tag in practice (USD, or USD/shares); take the largest.
    return max(units.values(), key=len)


# Earliest-filed value per quarter span and per year span.
def _split_spans(
    rows: Sequence[Mapping[str, Any]], name: str
) -> tuple[dict[tuple[date, date], QuarterFact], dict[tuple[date, date], QuarterFact]]:
    quarters: dict[tuple[date, date], QuarterFact] = {}
    years: dict[tuple[date, date], QuarterFact] = {}
    for row in rows:
        try:
            start = date.fromisoformat(row["start"])
            end = date.fromisoformat(row["end"])
            filed = date.fromisoformat(row["filed"])
            value = float(row["val"])
        except (KeyError, TypeError, ValueError):
            continue
        kind = _span_kind(start, end)
        if kind is None:
            continue
        bucket = quarters if kind == "quarter" else years
        key = (start, end)
        fact = QuarterFact(name, start, end, value, filed)
        if key not in bucket or filed < bucket[key].filed:
            bucket[key] = fact
    return quarters, years


# Add a derived fourth quarter for each year whose last quarter is not
# reported but whose first three are.
def _with_derived_fourth_quarters(
    quarters: Mapping[tuple[date, date], QuarterFact],
    years: Mapping[tuple[date, date], QuarterFact],
) -> list[QuarterFact]:
    result = list(quarters.values())
    ends = {q.end: q for q in quarters.values()}
    for (y_start, y_end), year in years.items():
        if y_end in ends:
            continue
        inside = [q for q in quarters.values() if q.start >= y_start and q.end < y_end]
        if len(inside) != 3:
            continue
        inside.sort(key=lambda q: q.end)
        last_start = inside[-1].end + timedelta(days=1)
        result.append(
            QuarterFact(
                year.name,
                last_start,
                y_end,
                year.value - sum(q.value for q in inside),
                max(year.filed, max(q.filed for q in inside)),
                derived=True,
            )
        )
    result.sort(key=lambda f: (f.end, f.filed))
    return result


# Fetch the quarterly fundamentals for a company.
def fetch_facts(
    cik: int,
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[QuarterFact, ...]:
    """Return point-in-time quarterly facts for a CIK."""
    payload = _get_json(
        _FACTS_URL.format(cik=cik), transport, pacer or Pacer(sleep=sleep), sleep
    )
    return tuple(parse_company_facts(payload))


# Fetch events and facts for one ticker.
def fetch_company(
    ticker: str,
    cik: int,
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
    decisions: Mapping[str, bool] | None = None,
) -> CompanyRecord:
    """Return the CompanyRecord for a ticker: events, facts, fetch time."""
    pacer = pacer or Pacer(sleep=sleep)
    events, decided = fetch_events_with_decisions(
        cik, transport, pacer, sleep, decisions
    )
    facts = fetch_facts(cik, transport, pacer, sleep)
    return CompanyRecord(
        ticker=ticker,
        cik=cik,
        events=events,
        facts=facts,
        source_time=now or datetime.now(tz=UTC),
        decisions_6k=decided,
    )


# The 6-K decisions as one metadata string for an events frame, and back.
# Frame metadata is str -> str, so the map is stored as JSON under the
# key `classified_6k`; a frame written before the key existed has none.
def decisions_to_metadata(decisions: Mapping[str, bool]) -> str:
    """Return the JSON text of {accession: admitted}."""
    return json.dumps({k: bool(v) for k, v in sorted(decisions.items())})


# Read the decisions back from a frame's metadata, tolerating absence.
def decisions_from_metadata(meta: Mapping[str, str]) -> dict[str, bool]:
    """Return {accession: admitted} from an events frame's metadata."""
    raw = meta.get("classified_6k")
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return (
        {str(k): bool(v) for k, v in payload.items()}
        if isinstance(payload, dict)
        else {}
    )


# --- features -------------------------------------------------------------


# The quarterly values of `name` known as of each session: the latest
# quarter, and the quarters one, four and five back from it as they were
# known then, plus the session index at which the latest was filed.
#
# Returns {0: latest, 1: one back, 4: four back, 5: five back} of (T,)
# arrays, NaN where unknown, first-visible rows and the selected source filing
# dates (NaT where unknown). Strict mode excludes date-only same-day facts.
def _known_quarters(
    facts: Sequence[QuarterFact],
    name: str,
    dates: np.ndarray,
    *,
    strict_before_session: bool = False,
) -> tuple[dict[int, np.ndarray], np.ndarray, np.ndarray]:
    rows = sorted((f for f in facts if f.name == name), key=lambda f: (f.filed, f.end))
    size = len(dates)
    lags = (0, 1, 4, 5)
    series = {lag: np.full(size, np.nan) for lag in lags}
    filed_at = np.full(size, np.nan)
    source_filed = np.full(size, np.datetime64("NaT", "D"))
    if not rows:
        return series, filed_at, source_filed
    calendar = dates.astype("datetime64[D]")
    by_end: dict[date, float] = {}
    filed_by_end: dict[date, date] = {}
    known_ends: list[date] = []
    pointer = 0
    current_end: date | None = None
    for t in range(size):
        session = calendar[t].astype("datetime64[D]").astype(object)
        while pointer < len(rows) and (
            rows[pointer].filed < session
            or (not strict_before_session and rows[pointer].filed == session)
        ):
            fact = rows[pointer]
            if fact.end not in by_end:
                by_end[fact.end] = fact.value
                filed_by_end[fact.end] = fact.filed
                known_ends.append(fact.end)
                known_ends.sort()
            if current_end is None or fact.end > current_end:
                current_end = fact.end
                filed_at[t:] = t
            pointer += 1
        if current_end is None:
            continue
        series[0][t] = by_end[current_end]
        source_filed[t] = np.datetime64(filed_by_end[current_end], "D")
        for lag in lags[1:]:
            series[lag][t] = _quarters_back(by_end, known_ends, current_end, lag)
    return series, filed_at, source_filed


# Preserve the legacy two-array interface while optionally excluding same-day facts.
def _known_series(
    facts: Sequence[QuarterFact],
    name: str,
    dates: np.ndarray,
    *,
    strict_before_session: bool = False,
) -> tuple[dict[int, np.ndarray], np.ndarray]:
    series, filed_at, _source_filed = _known_quarters(
        facts, name, dates, strict_before_session=strict_before_session
    )
    return series, filed_at


# The value ending about `quarters` quarters before `end`, if known.
def _quarters_back(
    by_end: Mapping[date, float], known_ends: Sequence[date], end: date, quarters: int
) -> float:
    target = end - timedelta(days=91 * quarters)
    best = None
    for candidate in known_ends:
        if abs((candidate - target).days) <= 20:
            best = candidate
    return by_end[best] if best is not None else np.nan


# Sessions since each session's most recent earnings reaction date, and the
# residual return over the reaction window (that session and the next),
# carried forward until the next event. Strict mode uses reviewed session closes.
def _event_series(
    events: Sequence[EarningsEvent],
    dates: np.ndarray,
    residual: np.ndarray,
    *,
    strict_publication: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    size = len(dates)
    since = np.full(size, float(NO_EVENT_SESSIONS))
    reaction = np.zeros(size)
    if not events:
        return since, reaction
    calendar = dates.astype("datetime64[D]")
    if strict_publication:
        from backend.market.calendar import publication_session

        days = {
            day
            for event in events
            if (day := publication_session(event.accepted, before=False)) is not None
        }
    else:
        days = {event.reaction_date for event in events}
    reaction_days = np.asarray(sorted(days), dtype="datetime64[D]")
    # The session on or after each reaction date.
    positions = np.searchsorted(calendar, reaction_days, side="left")
    positions = positions[positions < size]
    last = -1
    value = 0.0
    pointer = 0
    for t in range(size):
        while pointer < len(positions) and positions[pointer] <= t:
            last = int(positions[pointer])
            window = residual[last : min(last + 2, size)]
            window = window[np.isfinite(window)]
            value = float(window.sum()) if len(window) else 0.0
            pointer += 1
        if last >= 0:
            # The reaction is known only once its window has closed.
            if t >= last + 1:
                since[t] = min(t - last, NO_EVENT_SESSIONS)
                reaction[t] = value
            else:
                since[t] = 0.0
                reaction[t] = 0.0
    return since, reaction


# Build the (T, N, FEATURE_COUNT) EDGAR feature array for a panel.
#
# `records` maps ticker -> CompanyRecord; names absent from it get the
# neutral fills and zero indicators. Optional strict publication timing keeps
# date-only facts past their filing day and respects actual exchange close times.
def edgar_features(
    panel: Panel,
    records: Mapping[str, CompanyRecord],
    *,
    strict_publication: bool = False,
) -> np.ndarray:
    """Return point-in-time event and fundamental features per (session, name)."""
    size = len(panel.dates)
    names = len(panel.tickers)
    out = np.zeros((size, names, FEATURE_COUNT), dtype=np.float32)
    out[:, :, FEATURE_NAMES.index("sessions_since_earnings")] = NO_EVENT_SESSIONS
    out[:, :, FEATURE_NAMES.index("fundamentals_staleness")] = NO_FACT_SESSIONS
    returns = panel.log_returns()
    residual_all = returns - panel.benchmark_returns()[:, None]
    for column, ticker in enumerate(panel.tickers):
        record = records.get(ticker)
        if record is None:
            continue
        since, reaction = _event_series(
            record.events,
            panel.dates,
            residual_all[:, column],
            strict_publication=strict_publication,
        )
        out[:, column, FEATURE_NAMES.index("sessions_since_earnings")] = since
        out[:, column, FEATURE_NAMES.index("earnings_reaction")] = reaction
        out[:, column, FEATURE_NAMES.index("has_events")] = (
            1.0 if record.events else 0.0
        )

        known = {
            name: _known_series(
                record.facts,
                name,
                panel.dates,
                strict_before_session=strict_publication,
            )
            for name in (
                "revenue",
                "net_income",
                "eps",
                "capex",
                "operating_cash_flow",
                "gross_profit",
                "assets",
                "equity",
                "shares",
            )
        }
        rev, filed_at = known["revenue"]
        ni, _ = known["net_income"]
        eps, _ = known["eps"]
        capex, _ = known["capex"]
        ocf, _ = known["operating_cash_flow"]
        gp, _ = known["gross_profit"]
        assets, _ = known["assets"]
        equity, _ = known["equity"]
        shares, _ = known["shares"]
        has = np.isfinite(rev[0])
        with np.errstate(divide="ignore", invalid="ignore"):
            yoy = np.log(rev[0] / rev[4])
            qoq = np.log(rev[0] / rev[1])
            # Acceleration: this quarter's year-on-year growth less the
            # previous quarter's, both as known at the session.
            accel = yoy - np.log(rev[1] / rev[5])
            eps_change = (eps[0] - eps[4]) / np.maximum(np.abs(eps[4]), 0.1)
            margin = ni[0] / rev[0]
            margin_change = margin - ni[4] / rev[4]
            capex_rev = capex[0] / rev[0]
            capex_yoy = np.log(capex[0] / capex[4])
            ocf_rev = ocf[0] / rev[0]
            gross = gp[0] / rev[0]
            issuance = np.log(shares[0] / shares[4])
            asset_growth = np.log(assets[0] / assets[4])
            market_cap = shares[0] * panel.close[:, column]
            book_to_market = np.log(equity[0] / market_cap)
        staleness = np.where(
            np.isfinite(filed_at),
            np.minimum(np.arange(size) - np.nan_to_num(filed_at), NO_FACT_SESSIONS),
            NO_FACT_SESSIONS,
        )
        values = {
            "revenue_yoy": yoy,
            "revenue_qoq": qoq,
            "revenue_acceleration": accel,
            "eps_change_yoy": eps_change,
            "net_margin": margin,
            "net_margin_change_yoy": margin_change,
            "capex_to_revenue": capex_rev,
            "capex_yoy": capex_yoy,
            "ocf_to_revenue": ocf_rev,
            "gross_margin": gross,
            "share_issuance": issuance,
            "asset_growth": asset_growth,
            "book_to_market": book_to_market,
        }
        for key, series in values.items():
            clean = np.where(np.isfinite(series), series, 0.0)
            out[:, column, FEATURE_NAMES.index(key)] = np.clip(clean, -5.0, 5.0)
        out[:, column, FEATURE_NAMES.index("fundamentals_staleness")] = staleness
        out[:, column, FEATURE_NAMES.index("has_fundamentals")] = has.astype(np.float32)
    return out


# Serialise a record for the store's generic frames.
def record_frames(record: CompanyRecord) -> tuple[dict[str, list], dict[str, list]]:
    """Return (events_columns, facts_columns) for MarketStore.write_frame."""
    events = {
        "accepted": [e.accepted.isoformat() for e in record.events],
        "filed": [e.filed for e in record.events],
        "accession": [e.accession for e in record.events],
        "items": [e.items for e in record.events],
        "form": [e.form for e in record.events],
    }
    facts = {
        "name": [f.name for f in record.facts],
        "start": [f.start for f in record.facts],
        "end": [f.end for f in record.facts],
        "value": [f.value for f in record.facts],
        "filed": [f.filed for f in record.facts],
        "derived": [f.derived for f in record.facts],
    }
    return events, facts


# The events a stored frame encodes; a frame written before the `form`
# column existed holds 8-Ks only.
def events_from_columns(events: Mapping[str, list]) -> list[EarningsEvent]:
    """Return the EarningsEvents of an events frame's columns."""
    forms = events.get("form")
    return [
        EarningsEvent(
            accepted=datetime.fromisoformat(events["accepted"][i]),
            filed=events["filed"][i],
            accession=events["accession"][i],
            items=events["items"][i],
            form=str(forms[i]) if forms else "8-K",
        )
        for i in range(len(events.get("accepted", [])))
    ]


# Rebuild a record from stored frames.
def record_from_frames(
    ticker: str,
    cik: int,
    events: Mapping[str, list],
    facts: Mapping[str, list],
    source_time: datetime,
) -> CompanyRecord:
    """Return the CompanyRecord encoded by two stored frames."""
    event_rows = tuple(events_from_columns(events))
    fact_rows = tuple(
        QuarterFact(
            name=facts["name"][i],
            start=facts["start"][i],
            end=facts["end"][i],
            value=float(facts["value"][i]),
            filed=facts["filed"][i],
            derived=bool(facts["derived"][i]),
        )
        for i in range(len(facts.get("name", [])))
    )
    return CompanyRecord(ticker, cik, event_rows, fact_rows, source_time)


# The release-reported financials as quarterly facts, so the fundamental
# layer reads an 8-K's own numbers between 10-Qs. Each release record (a
# language.ToneRecord) yields a revenue, net income and EPS fact for the
# quarter it reports, filed on its reaction date, and a gross-profit fact
# derived from the reported gross margin so the margin feature stays on
# the same quarter. A field a release does not state contributes nothing.
def release_facts(records: Mapping[str, Sequence]) -> dict[str, list[QuarterFact]]:
    """Return {ticker: release-reported QuarterFacts} from tone records."""
    out: dict[str, list[QuarterFact]] = {}
    for ticker, rows in records.items():
        facts: list[QuarterFact] = []
        for record in rows:
            end = getattr(record, "quarter_end", None)
            filed = getattr(record, "reaction_date", None)
            if not end or not filed:
                continue
            revenue = getattr(record, "revenue_usd_m", None)
            if revenue is not None:
                facts.append(QuarterFact("revenue", end, end, revenue * 1e6, filed))
            eps = getattr(record, "eps_usd", None)
            if eps is not None:
                facts.append(QuarterFact("eps", end, end, eps, filed))
            ni = getattr(record, "net_income_usd_m", None)
            if ni is not None:
                facts.append(QuarterFact("net_income", end, end, ni * 1e6, filed))
            margin = getattr(record, "gross_margin_pct", None)
            if margin is not None and revenue is not None:
                facts.append(
                    QuarterFact(
                        "gross_profit",
                        end,
                        end,
                        margin / 100.0 * revenue * 1e6,
                        filed,
                    )
                )
        out[ticker] = facts
    return out


# A run of inline formatting tags between two letters with no space: the
# filer's editor split one word across styled runs ("n</font><font ...>et
# income", ASML's 2021-01-20 release), so the tags join, not separate.
_SPLIT_WORD = re.compile(
    r"(?<=[A-Za-z])(?:</?(?:font|span|b|i|u|em|strong|small)\b[^>]*>)+(?=[A-Za-z])",
    re.I,
)


# Strip an HTML press release to text for the language pass.
def html_to_text(html: str) -> str:
    """Return the visible text of an HTML document, whitespace collapsed."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = _SPLIT_WORD.sub("", text)
    text = re.sub(r"<[^>]+>", " ", text)
    # Entities become their characters (a filer's "&nbsp;" inside a title
    # must not break it), and the no-break and zero-width spaces that
    # filers put between words become ordinary spaces.
    text = unescape(text).replace("\u00a0", " ").replace("\u200b", " ")
    return re.sub(r"\s+", " ", text).strip()
