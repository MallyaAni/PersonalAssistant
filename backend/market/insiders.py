"""Insider trades (Form 4) as a stance: the SEC's quarterly insider data
sets into per-name open-market transactions, the routine-trader rule of
Cohen, Malloy and Pomorski (2012), and a trailing-window signal dated by
the filing.

Registered in `docs/research/insider-stance-plan-2026-10-01.md` before
any of this was written. Four things live here, all pure except the
transport:

- **The quarterly zip** (`parse_zip`): `SUBMISSION`, `REPORTINGOWNER` and
  `NONDERIV_TRANS` joined on the accession into `Transaction` rows, kept
  for every issuer and every purchase (P) or sale (S), whatever the form
  (4, 4/A, 5), with the 10b5-1 flag, the owner's relationship and the
  filing date. Admission is decided later (`admit`), so a rule change
  never needs a refetch.
- **Admission** (`admit`): Form 4 originals, P or S, an officer or
  director among the reporting owners, not a flagged plan trade, shares
  present.
- **The routine rule** (`opportunistic`): for a row filed in year y, the
  insider's prior P/S trades *filed before this row* are grouped by
  (trade year, trade month). Classifiable when each of y-1, y-2, y-3
  holds a trade; routine when some calendar month holds a trade in all
  three. The opportunistic arm keeps the classifiable, non-routine rows.
- **The signal** (`window_signal`): a row becomes known on the first
  session strictly after its filing date (the bulk data carries no
  acceptance time, so the conservative rule). Over the trailing
  `WINDOW` sessions, net dollars (P minus S, shares times price) over the
  median daily dollar volume of the same sessions. A name with a
  denominator and no row scores exactly zero.
"""

import csv
import io
import re
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np

from backend.market.panel import Panel

INDEX_URL = (
    "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
)
# The pattern every quarter but the newest follows; the index page is
# the source of truth and this is the fallback when a quarter is missing
# from it.
ZIP_URL = (
    "https://www.sec.gov/files/structureddata/data/"
    "insider-transactions-data-sets/{quarter}_form345.zip"
)
FIRST_QUARTER = (2006, 1)
INSIDERS_KIND = "edgar_insiders"
ZIP_DIR = "edgar_insiders_zips"

WINDOW = 90
MIN_VOLUME_SESSIONS = 45
ROUTINE_YEARS = 3
CODES = frozenset({"P", "S"})
ORIGINAL_FORM = "4"
INSIDER_ROLES = ("Officer", "Director")
ARM_OPPORTUNISTIC = "A4-opp opportunistic insiders"
ARM_ALL = "A4-all all insiders"

_HREF = re.compile(r'href="([^"]*?/(\d{4}q[1-4])_form345\.zip)"', re.I)
_DATE_FORMAT = "%d-%b-%Y"


@dataclass(frozen=True, slots=True)
class Transaction:
    """One non-derivative purchase or sale reported on a Form 4 (or 4/A, 5)."""

    accession: str
    filed: date
    traded: date
    issuer_cik: int
    symbol: str
    owner_cik: int
    relationship: str
    code: str  # "P" or "S"
    shares: float
    price: float  # NaN when the filing left it blank
    direct: bool
    plan: bool  # flagged as a Rule 10b5-1 plan trade
    document_type: str
    timeliness: str

    # +1 for a purchase, -1 for a sale.
    @property
    def sign(self) -> int:
        return 1 if self.code == "P" else -1


# --- the index and the quarters ---------------------------------------------


# Every quarter label from the first data set to the quarter holding `today`.
def quarter_labels(today: date, first: tuple[int, int] = FIRST_QUARTER) -> list[str]:
    """Return ["2006q1", ..., "<today's quarter>"], oldest first."""
    out: list[str] = []
    year, quarter = first
    last = (today.year, (today.month - 1) // 3 + 1)
    while (year, quarter) <= last:
        out.append(f"{year}q{quarter}")
        quarter += 1
        if quarter > 4:
            year, quarter = year + 1, 1
    return out


# The zip links on the index page, {quarter label: absolute URL}.
def parse_index(html: str, base: str = "https://www.sec.gov") -> dict[str, str]:
    """Return {quarter: url} for every `<yyyy>q<n>_form345.zip` link."""
    out: dict[str, str] = {}
    for href, label in _HREF.findall(html):
        url = href if href.startswith("http") else base + href
        out.setdefault(label.lower(), url)
    return out


# --- the zip ---------------------------------------------------------------


# A DD-MON-YYYY field as a date, or None when blank or malformed.
def _parse_date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, _DATE_FORMAT).date()
    except ValueError:
        return None


# A numeric field as float, NaN when blank or malformed.
def _parse_float(text: str) -> float:
    text = (text or "").strip()
    if not text:
        return float("nan")
    try:
        return float(text)
    except ValueError:
        return float("nan")


# The 10b5-1 flag as the data writes it: 1 or true means flagged.
def _parse_flag(text: str) -> bool:
    return (text or "").strip().lower() in {"1", "true"}


# The rows of one tab-separated table inside the zip.
def _read_table(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with archive.open(name) as handle:
        text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
        reader = csv.DictReader(text, delimiter="\t", quoting=csv.QUOTE_NONE)
        return list(reader)


# The officer-or-director owner of a filing, if any: the first reporting
# owner whose relationship names one of INSIDER_ROLES. Pure 10% owners
# and "Other" yield None.
def insider_owner(owners: Sequence[Mapping[str, str]]) -> Mapping[str, str] | None:
    """Return the first officer/director owner row, or None."""
    for owner in owners:
        if is_insider(owner.get("RPTOWNER_RELATIONSHIP") or ""):
            return owner
    return owners[0] if owners else None


# Pure: a quarterly zip's bytes into Transaction rows, every issuer, P and
# S only, every document type. A row whose filing, transaction date,
# shares or owner cannot be read is dropped.
def parse_zip(data: bytes) -> list[Transaction]:
    """Return the purchase and sale rows of one quarterly data set."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    names = set(archive.namelist())
    for required in ("SUBMISSION.tsv", "REPORTINGOWNER.tsv", "NONDERIV_TRANS.tsv"):
        if required not in names:
            raise ValueError(f"zip lacks {required}")
    submissions = {
        row["ACCESSION_NUMBER"]: row for row in _read_table(archive, "SUBMISSION.tsv")
    }
    owners: dict[str, list[dict[str, str]]] = {}
    for row in _read_table(archive, "REPORTINGOWNER.tsv"):
        owners.setdefault(row["ACCESSION_NUMBER"], []).append(row)
    out: list[Transaction] = []
    for row in _read_table(archive, "NONDERIV_TRANS.tsv"):
        code = (row.get("TRANS_CODE") or "").strip().upper()
        if code not in CODES:
            continue
        accession = row["ACCESSION_NUMBER"]
        submission = submissions.get(accession)
        if submission is None:
            continue
        owner = insider_owner(owners.get(accession, []))
        filed = _parse_date(submission.get("FILING_DATE", ""))
        traded = _parse_date(row.get("TRANS_DATE", ""))
        shares = _parse_float(row.get("TRANS_SHARES", ""))
        if owner is None or filed is None or traded is None or not np.isfinite(shares):
            continue
        try:
            issuer_cik = int(submission.get("ISSUERCIK") or 0)
            owner_cik = int(owner.get("RPTOWNERCIK") or 0)
        except ValueError:
            continue
        if not issuer_cik or not owner_cik:
            continue
        out.append(
            Transaction(
                accession=accession,
                filed=filed,
                traded=traded,
                issuer_cik=issuer_cik,
                symbol=(submission.get("ISSUERTRADINGSYMBOL") or "").strip().upper(),
                owner_cik=owner_cik,
                relationship=(owner.get("RPTOWNER_RELATIONSHIP") or "").strip(),
                code=code,
                shares=shares,
                price=_parse_float(row.get("TRANS_PRICEPERSHARE", "")),
                direct=(row.get("DIRECT_INDIRECT_OWNERSHIP") or "D").strip().upper()
                != "I",
                plan=_parse_flag(submission.get("AFF10B5ONE", "")),
                document_type=(submission.get("DOCUMENT_TYPE") or "").strip(),
                timeliness=(row.get("TRANS_TIMELINESS") or "").strip(),
            )
        )
    out.sort(key=lambda r: (r.filed, r.accession, r.traded, r.owner_cik))
    return out


# --- the store frame ---------------------------------------------------------


# Serialise rows for MarketStore.write_frame.
def transactions_frame(rows: Iterable[Transaction]) -> dict[str, list]:
    """Return the columns of an `edgar_insiders` frame."""
    rows = list(rows)
    return {
        "accession": [r.accession for r in rows],
        "filed": [r.filed for r in rows],
        "traded": [r.traded for r in rows],
        "issuer_cik": [r.issuer_cik for r in rows],
        "symbol": [r.symbol for r in rows],
        "owner_cik": [r.owner_cik for r in rows],
        "relationship": [r.relationship for r in rows],
        "code": [r.code for r in rows],
        "shares": [float(r.shares) for r in rows],
        "price": [float(r.price) for r in rows],
        "direct": [bool(r.direct) for r in rows],
        "plan": [bool(r.plan) for r in rows],
        "document_type": [r.document_type for r in rows],
        "timeliness": [r.timeliness for r in rows],
    }


# Rows from a stored frame's columns.
def transactions_from_frame(columns: Mapping[str, list]) -> list[Transaction]:
    """Return the Transactions an `edgar_insiders` frame encodes."""
    out: list[Transaction] = []
    for i in range(len(columns.get("accession", []))):
        price = columns["price"][i]
        out.append(
            Transaction(
                accession=str(columns["accession"][i]),
                filed=_as_date(columns["filed"][i]),
                traded=_as_date(columns["traded"][i]),
                issuer_cik=int(columns["issuer_cik"][i]),
                symbol=str(columns["symbol"][i]),
                owner_cik=int(columns["owner_cik"][i]),
                relationship=str(columns["relationship"][i]),
                code=str(columns["code"][i]),
                shares=float(columns["shares"][i]),
                price=float("nan") if price is None else float(price),
                direct=bool(columns["direct"][i]),
                plan=bool(columns["plan"][i]),
                document_type=str(columns["document_type"][i]),
                timeliness=str(columns["timeliness"][i]),
            )
        )
    return out


# A stored date value (date, datetime or ISO text) as a date.
def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


# --- admission and the routine rule ------------------------------------------


# Whether an owner relationship names an officer or director.
def is_insider(relationship: str) -> bool:
    """Return True when the relationship includes Officer or Director."""
    roles = {r.strip().lower() for r in relationship.split(",")}
    return any(role.lower() in roles for role in INSIDER_ROLES)


# The rows the plan admits: Form 4 originals, P or S, an officer or
# director, not a flagged plan trade, positive shares. Returns the kept
# rows and a count per refusal reason.
def admit(rows: Iterable[Transaction]) -> tuple[list[Transaction], dict[str, int]]:
    """Return (admitted rows, {reason: refused count})."""
    kept: list[Transaction] = []
    refused: dict[str, int] = {
        "not_form_4_original": 0,
        "not_purchase_or_sale": 0,
        "not_officer_or_director": 0,
        "plan_trade": 0,
        "no_shares": 0,
    }
    for row in rows:
        if row.document_type != ORIGINAL_FORM:
            refused["not_form_4_original"] += 1
        elif row.code not in CODES:
            refused["not_purchase_or_sale"] += 1
        elif not is_insider(row.relationship):
            refused["not_officer_or_director"] += 1
        elif row.plan:
            refused["plan_trade"] += 1
        elif not (np.isfinite(row.shares) and row.shares > 0):
            refused["no_shares"] += 1
        else:
            kept.append(row)
    return kept, refused


# The routine/opportunistic classification of every row, point in time.
#
# `history` is every P/S row of the data set (admitted or not: a plan
# trade or an amendment is still evidence of when the insider trades);
# `rows` are the rows to classify. For a row filed in year y, the
# insider's history rows with a filing date strictly before this row's
# are grouped by (trade year, trade month). Classifiable: each of y-1,
# y-2, y-3 holds a trade. Routine: some month holds a trade in all three.
# Returns {(accession, owner_cik, traded, code, shares): "routine" |
# "opportunistic" | "unclassified"} keyed as `row_key` does.
def classify(
    rows: Sequence[Transaction],
    history: Sequence[Transaction],
    years: int = ROUTINE_YEARS,
) -> dict[tuple, str]:
    """Return the classification of each row under the routine rule."""
    by_insider: dict[tuple[int, int], list[Transaction]] = {}
    for row in history:
        by_insider.setdefault((row.issuer_cik, row.owner_cik), []).append(row)
    for items in by_insider.values():
        items.sort(key=lambda r: r.filed)
    out: dict[tuple, str] = {}
    for row in rows:
        prior = by_insider.get((row.issuer_cik, row.owner_cik), [])
        months_by_year: dict[int, set[int]] = {}
        for item in prior:
            if item.filed >= row.filed:
                break
            months_by_year.setdefault(item.traded.year, set()).add(item.traded.month)
        wanted = [row.filed.year - k for k in range(1, years + 1)]
        if not all(months_by_year.get(y) for y in wanted):
            out[row_key(row)] = "unclassified"
            continue
        common = set.intersection(*(months_by_year[y] for y in wanted))
        out[row_key(row)] = "routine" if common else "opportunistic"
    return out


# The identity of one row for the classification map.
def row_key(row: Transaction) -> tuple:
    """Return a hashable key naming one transaction row."""
    return (row.accession, row.owner_cik, row.traded, row.code, row.shares)


# The opportunistic subset of `rows`: classifiable and not routine.
def opportunistic(
    rows: Sequence[Transaction], history: Sequence[Transaction]
) -> list[Transaction]:
    """Return the rows whose insider is classifiable and not routine."""
    labels = classify(rows, history)
    return [r for r in rows if labels[row_key(r)] == "opportunistic"]


# --- dating and the signal ---------------------------------------------------


# The first session strictly after `filed`, as an index into `dates`;
# len(dates) when none. The bulk data carries no acceptance time, so a
# filing is treated as public only once the session of its date closed.
def known_session(filed: date, dates: np.ndarray) -> int:
    """Return the index of the first session after the filing date."""
    stamps = np.asarray(dates).astype("datetime64[D]")
    return int(np.searchsorted(stamps, np.datetime64(filed, "D"), side="right"))


@dataclass(frozen=True, slots=True)
class DatedRow:
    """One admitted row placed on the panel: when it is known and its dollars."""

    ticker: str
    session: int  # index into panel.dates; len(dates) when never known
    dollars: float  # signed: + bought, - sold
    row: Transaction
    opportunistic: bool = False


# Place rows on the panel: the known session and the signed dollar value,
# with a blank price replaced by the name's close on the known session.
# Rows whose issuer is not in `ticker_by_cik`, never known inside the
# panel, or without any usable price are dropped.
def date_rows(
    panel: Panel,
    rows: Iterable[Transaction],
    ticker_by_cik: Mapping[int, str],
    opportunistic_keys: set[tuple] | None = None,
) -> list[DatedRow]:
    """Return the DatedRows of `rows` on the panel."""
    size = len(panel.dates)
    out: list[DatedRow] = []
    for row in rows:
        ticker = ticker_by_cik.get(row.issuer_cik)
        if ticker is None or ticker not in panel.tickers:
            continue
        session = known_session(row.filed, panel.dates)
        if session >= size:
            continue
        price = row.price
        if not (np.isfinite(price) and price > 0):
            price = float(panel.close[session, panel.index(ticker)])
            if not (np.isfinite(price) and price > 0):
                continue
        out.append(
            DatedRow(
                ticker=ticker,
                session=session,
                dollars=float(row.sign * row.shares * price),
                row=row,
                opportunistic=bool(
                    opportunistic_keys is not None
                    and row_key(row) in opportunistic_keys
                ),
            )
        )
    return out


# The rolling median daily dollar volume (close x volume) over `window`
# sessions ending at each session, NaN when fewer than `min_sessions`
# of them have a bar.
def dollar_volume_scale(
    panel: Panel, window: int = WINDOW, min_sessions: int = MIN_VOLUME_SESSIONS
) -> np.ndarray:
    """Return the (T, N) median dollar volume over the trailing window."""
    with np.errstate(invalid="ignore"):
        dollars = panel.close * panel.volume
    size, names = dollars.shape
    out = np.full((size, names), np.nan)
    for t in range(size):
        block = dollars[max(0, t - window + 1) : t + 1]
        counts = np.isfinite(block).sum(axis=0)
        enough = counts >= min_sessions
        if enough.any():
            with np.errstate(all="ignore"):
                medians = np.nanmedian(block[:, enough], axis=0)
            out[t, enough] = medians
    return out


# The trailing-window net dollars per (session, name): the sum of the
# signed dollars of rows known on sessions t-window+1..t.
def window_net_dollars(
    panel: Panel, dated: Sequence[DatedRow], window: int = WINDOW
) -> np.ndarray:
    """Return the (T, N) net dollars bought over the trailing window."""
    size, names = len(panel.dates), len(panel.tickers)
    daily = np.zeros((size, names))
    for item in dated:
        if 0 <= item.session < size:
            daily[item.session, panel.index(item.ticker)] += item.dollars
    cumulative = np.cumsum(daily, axis=0)
    out = cumulative.copy()
    if window < size:
        out[window:] -= cumulative[:-window]
    return out


# The registered signal: net dollars over the window, divided by the
# median dollar volume of the same window. Zero where nothing was filed
# and the denominator exists; NaN only where the denominator is.
def window_signal(
    panel: Panel,
    dated: Sequence[DatedRow],
    window: int = WINDOW,
    min_sessions: int = MIN_VOLUME_SESSIONS,
    scale: np.ndarray | None = None,
) -> np.ndarray:
    """Return the (T, N) insider signal."""
    net = window_net_dollars(panel, dated, window)
    if scale is None:
        scale = dollar_volume_scale(panel, window, min_sessions)
    with np.errstate(all="ignore"):
        out = np.where(np.isfinite(scale) & (scale > 0), net / scale, np.nan)
    if panel.benchmark in panel.tickers:
        out[:, panel.index(panel.benchmark)] = np.nan
    return out


# Both registered arms' signals from the admitted rows: the opportunistic
# subset and all admitted rows. Returns ({arm: (T, N)}, the dated rows).
def arm_signals(
    panel: Panel,
    admitted: Sequence[Transaction],
    history: Sequence[Transaction],
    ticker_by_cik: Mapping[int, str],
    window: int = WINDOW,
) -> tuple[dict[str, np.ndarray], list[DatedRow]]:
    """Return the (T, N) signal per arm and the dated rows behind them."""
    labels = classify(admitted, history)
    keys = {k for k, v in labels.items() if v == "opportunistic"}
    dated = date_rows(panel, admitted, ticker_by_cik, keys)
    scale = dollar_volume_scale(panel, window)
    signals = {
        ARM_OPPORTUNISTIC: window_signal(
            panel, [d for d in dated if d.opportunistic], window, scale=scale
        ),
        ARM_ALL: window_signal(panel, dated, window, scale=scale),
    }
    return signals, dated


# The dated rows as a long table for the build output and the check.
def dated_frame(
    panel: Panel, dated: Sequence[DatedRow], labels: Mapping[tuple, str]
) -> dict[str, list]:
    """Return the columns of the per-row table `build` writes."""
    return {
        "ticker": [d.ticker for d in dated],
        "accession": [d.row.accession for d in dated],
        "owner_cik": [d.row.owner_cik for d in dated],
        "relationship": [d.row.relationship for d in dated],
        "code": [d.row.code for d in dated],
        "filed": [d.row.filed.isoformat() for d in dated],
        "traded": [d.row.traded.isoformat() for d in dated],
        "known_session": [str(panel.dates[d.session]) for d in dated],
        "shares": [float(d.row.shares) for d in dated],
        "price": [float(d.row.price) for d in dated],
        "dollars": [float(d.dollars) for d in dated],
        "classification": [labels.get(row_key(d.row), "unclassified") for d in dated],
        "opportunistic": [bool(d.opportunistic) for d in dated],
    }


# A DatedRow rebuilt from the long table (the check and the evaluate step
# read the table rather than the store).
def dated_from_frame(panel: Panel, columns: Mapping[str, list]) -> list[DatedRow]:
    """Return the DatedRows the per-row table encodes."""
    stamps = np.asarray(panel.dates).astype("datetime64[D]")
    out: list[DatedRow] = []
    for i in range(len(columns.get("ticker", []))):
        session = int(
            np.searchsorted(
                stamps, np.datetime64(str(columns["known_session"][i])[:10])
            )
        )
        row = Transaction(
            accession=str(columns["accession"][i]),
            filed=date.fromisoformat(str(columns["filed"][i])),
            traded=date.fromisoformat(str(columns["traded"][i])),
            issuer_cik=0,
            symbol=str(columns["ticker"][i]),
            owner_cik=int(columns["owner_cik"][i]),
            relationship=str(columns["relationship"][i]),
            code=str(columns["code"][i]),
            shares=float(columns["shares"][i]),
            price=float(columns["price"][i]),
            direct=True,
            plan=False,
            document_type=ORIGINAL_FORM,
            timeliness="",
        )
        out.append(
            DatedRow(
                ticker=str(columns["ticker"][i]),
                session=session,
                dollars=float(columns["dollars"][i]),
                row=row,
                opportunistic=bool(columns["opportunistic"][i]),
            )
        )
    return out
