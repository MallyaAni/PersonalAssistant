"""SEC EDGAR: the information a price series does not hold, point in time.

Every model on price and volume alone measured at zero on this universe, so
the next input has to come from somewhere else. EDGAR is the free source
that is also *historically honest*: every filing carries the date it was
accepted, and every XBRL fact carries the date it was filed, so a feature
at session t can be built from exactly what was public at t.

Three things are read per company:

- **Earnings events** — 8-K filings with item 2.02 (results of operations),
  with their acceptance timestamp. A release accepted after the close
  moves the next session, which is where the reaction is measured.
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
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from backend.market.panel import Panel

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/index.json"
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
)
FEATURE_COUNT = len(FEATURE_NAMES)

# Neutral fills for a name with nothing on file, and the clip for the
# "sessions since" counters so a never-reporting name is not an outlier.
NO_EVENT_SESSIONS = 250
NO_FACT_SESSIONS = 400


class EdgarUnavailableError(RuntimeError):
    """A fetch failed or was refused; the caller must flag, not crash."""


@dataclass(frozen=True, slots=True)
class EarningsEvent:
    """One results release: when it was accepted, and its filing identity."""

    accepted: datetime  # UTC
    filed: date
    accession: str
    items: str

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


# Fetch JSON from EDGAR with pacing and bounded retries on throttling.
def _get_json(
    url: str, transport: Transport, pacer: Pacer, sleep: Callable[[float], None]
) -> Any:
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
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                raise EdgarUnavailableError(f"{url}: non-JSON body") from exc
        if status == 404:
            raise EdgarUnavailableError(f"{url}: not found (404)")
        last = f"HTTP {status}"
        if status in (403, 429, 500, 502, 503):
            sleep(2.0 * attempt)
            continue
        break
    raise EdgarUnavailableError(f"{url}: refused ({last})")


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


# Pure: one submissions block (recent or an older file) into events.
def parse_submissions_block(block: Mapping[str, Any]) -> list[EarningsEvent]:
    """Return the 8-K item 2.02 events in one submissions block."""
    forms = block.get("form") or []
    items = block.get("items") or []
    accepted = block.get("acceptanceDateTime") or []
    filed = block.get("filingDate") or []
    accession = block.get("accessionNumber") or []
    events: list[EarningsEvent] = []
    for i, form in enumerate(forms):
        if form != "8-K" or "2.02" not in (items[i] if i < len(items) else ""):
            continue
        try:
            stamp = accepted[i].replace("Z", "+00:00")
            when = datetime.fromisoformat(stamp).astimezone(UTC)
            events.append(
                EarningsEvent(
                    accepted=when,
                    filed=date.fromisoformat(filed[i]),
                    accession=accession[i],
                    items=items[i],
                )
            )
        except (IndexError, ValueError, AttributeError):
            continue
    return events


# Fetch every earnings event for a company: the recent block plus each
# older block the submissions document points at.
def fetch_events(
    cik: int,
    transport: Transport = sec_transport,
    pacer: Pacer | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[EarningsEvent, ...]:
    """Return all 8-K item 2.02 events for a CIK, oldest first."""
    pacer = pacer or Pacer(sleep=sleep)
    payload = _get_json(
        _SUBMISSIONS_URL.format(name=f"CIK{cik:010d}.json"), transport, pacer, sleep
    )
    filings = payload.get("filings") or {}
    events = parse_submissions_block(filings.get("recent") or {})
    for older in filings.get("files") or []:
        name = older.get("name")
        if not name:
            continue
        block = _get_json(_SUBMISSIONS_URL.format(name=name), transport, pacer, sleep)
        events.extend(parse_submissions_block(block))
    unique = {e.accession: e for e in events}
    return tuple(sorted(unique.values(), key=lambda e: e.accepted))


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
        # Filers switch tags over the years; the tag with the most quarters
        # on file is the one with the history worth reading.
        best_count = 0
        for taxonomy in ("us-gaap", "ifrs-full"):
            for tag in tags:
                rows = _rows_for(facts_root, taxonomy, tag)
                quarters, years = _split_spans(rows, name)
                if len(quarters) > best_count:
                    best_count = len(quarters)
                    chosen = _with_derived_fourth_quarters(quarters, years)
        out.extend(chosen)
    out.sort(key=lambda f: (f.name, f.end, f.filed))
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
) -> CompanyRecord:
    """Return the CompanyRecord for a ticker: events, facts, fetch time."""
    pacer = pacer or Pacer(sleep=sleep)
    events = fetch_events(cik, transport, pacer, sleep)
    facts = fetch_facts(cik, transport, pacer, sleep)
    return CompanyRecord(
        ticker=ticker,
        cik=cik,
        events=events,
        facts=facts,
        source_time=now or datetime.now(tz=UTC),
    )


# The filing-index entries of one accession, so a later pass can find the
# press release (its type is EX-99.1 in the index page; names are free).
def filing_index_url(cik: int, accession: str) -> str:
    """Return the index.json URL for a filing."""
    return _INDEX_URL.format(cik=cik, folder=accession.replace("-", ""))


# --- features -------------------------------------------------------------


# The quarterly values of `name` known as of each session: the latest
# quarter, and the quarters one, four and five back from it as they were
# known then, plus the session index at which the latest was filed.
#
# Returns {0: latest, 1: one back, 4: four back, 5: five back} of (T,)
# arrays, NaN where unknown, and filed_at (T,) NaN until the first filing.
def _known_series(
    facts: Sequence[QuarterFact],
    name: str,
    dates: np.ndarray,
) -> tuple[dict[int, np.ndarray], np.ndarray]:
    rows = sorted((f for f in facts if f.name == name), key=lambda f: (f.filed, f.end))
    size = len(dates)
    lags = (0, 1, 4, 5)
    series = {lag: np.full(size, np.nan) for lag in lags}
    filed_at = np.full(size, np.nan)
    if not rows:
        return series, filed_at
    calendar = dates.astype("datetime64[D]")
    by_end: dict[date, float] = {}
    known_ends: list[date] = []
    pointer = 0
    current_end: date | None = None
    for t in range(size):
        session = calendar[t].astype("datetime64[D]").astype(object)
        while pointer < len(rows) and rows[pointer].filed <= session:
            fact = rows[pointer]
            if fact.end not in by_end:
                by_end[fact.end] = fact.value
                known_ends.append(fact.end)
                known_ends.sort()
            if current_end is None or fact.end > current_end:
                current_end = fact.end
                filed_at[t:] = t
            pointer += 1
        if current_end is None:
            continue
        series[0][t] = by_end[current_end]
        for lag in lags[1:]:
            series[lag][t] = _quarters_back(by_end, known_ends, current_end, lag)
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
# carried forward until the next event.
def _event_series(
    events: Sequence[EarningsEvent],
    dates: np.ndarray,
    residual: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    size = len(dates)
    since = np.full(size, float(NO_EVENT_SESSIONS))
    reaction = np.zeros(size)
    if not events:
        return since, reaction
    calendar = dates.astype("datetime64[D]")
    reaction_days = np.asarray(
        sorted({e.reaction_date for e in events}), dtype="datetime64[D]"
    )
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
# neutral fills and zero indicators.
def edgar_features(panel: Panel, records: Mapping[str, CompanyRecord]) -> np.ndarray:
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
            record.events, panel.dates, residual_all[:, column]
        )
        out[:, column, FEATURE_NAMES.index("sessions_since_earnings")] = since
        out[:, column, FEATURE_NAMES.index("earnings_reaction")] = reaction
        out[:, column, FEATURE_NAMES.index("has_events")] = (
            1.0 if record.events else 0.0
        )

        rev, filed_at = _known_series(record.facts, "revenue", panel.dates)
        ni, _ = _known_series(record.facts, "net_income", panel.dates)
        eps, _ = _known_series(record.facts, "eps", panel.dates)
        capex, _ = _known_series(record.facts, "capex", panel.dates)
        ocf, _ = _known_series(record.facts, "operating_cash_flow", panel.dates)
        gp, _ = _known_series(record.facts, "gross_profit", panel.dates)
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


# Rebuild a record from stored frames.
def record_from_frames(
    ticker: str,
    cik: int,
    events: Mapping[str, list],
    facts: Mapping[str, list],
    source_time: datetime,
) -> CompanyRecord:
    """Return the CompanyRecord encoded by two stored frames."""
    event_rows = tuple(
        EarningsEvent(
            accepted=datetime.fromisoformat(events["accepted"][i]),
            filed=events["filed"][i],
            accession=events["accession"][i],
            items=events["items"][i],
        )
        for i in range(len(events.get("accepted", [])))
    )
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


# Strip an HTML press release to text for the language pass.
def html_to_text(html: str) -> str:
    """Return the visible text of an HTML document, whitespace collapsed."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
