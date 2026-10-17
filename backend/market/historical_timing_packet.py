"""Pure source-bound archival packets for the declared conditional timing contract.

No acquisition, model, account, sender or fill occurs here. Assumed availability
and timestamp uncertainty are not recovered historical clocks. Quote sizes never
become share capacity. Production inference evidence is never manufactured.
"""

import base64
import calendar
import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from urllib.parse import parse_qs, urlencode, urlsplit

CONTRACT = "conditional-archival-forward-timing/1"
NS = 1_000_000_000
FIXED = MappingProxyType(
    {
        "final_archive_bar_available_delay_ns": 30 * NS,
        "inference_duration_ns": NS,
        "quote_receive_delay_ns": NS // 10,
        "sender_delay_ns": NS // 10,
        "route_delay_ns": NS // 10,
        "decision_delay_ns": 31 * NS + NS // 10,
        "trade_window_end_ns": NS,
        "quote_window_start_ns": 30 * NS,
        "quote_window_end_ns": 33 * NS,
        "event_timestamp_uncertainty_ns": NS // 1000,
        "arrival_clock_uncertainty_ns": NS // 1000,
    }
)
ENDPOINT = "https://data.alpaca.markets/v2/stocks/quotes"
MAX_PAGES = 10
_STAMP = re.compile(
    r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})"
    r"(?:\.(\d{1,9}))?(?:Z|\+00:00)"
)


# Preserve original byte evidence rather than accepting a detached row list.
@dataclass(frozen=True)
class ArchivedPacket:
    kind: str
    window_sha256: str
    source_sha256: str
    source_bytes: bytes
    verified_at: str


# Preserve provider nanoseconds without assigning unknown receive clocks.
def nanos(value):
    match = _STAMP.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError(
            "Explicit UTC timestamp with at most9 fractional digits required"
        )
    parsed = datetime.fromisoformat(match[1] + "T" + match[2] + "+00:00")
    return calendar.timegm(parsed.utctimetuple()) * NS + int(
        (match[3] or "").ljust(9, "0")
    )


# Serialize an assumed instant without truncating archival event ordering.
def stamp(value):
    if type(value) is not int:
        raise ValueError("Integer nanosecond clock required")
    seconds, fraction = divmod(value, NS)
    return (
        datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%S")
        + f".{fraction:09d}Z"
    )


# Reject duplicate JSON keys instead of choosing an ambiguous authenticated value.
def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


# Reject nonstandard financial constants rather than interpreting them as zeros.
def _constant(value):
    raise ValueError("Non-finite JSON constant: " + value)


# Parse immutable original JSON with ambiguity and non-finite guards enabled.
def _decode(raw):
    return json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)


# Hash a normalized declaration separately from original provider response bytes.
def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


# Freeze hypothetical delays and clock uncertainty before economic outcomes.
def schedule(completed_at, assumptions=None):
    supplied = FIXED if assumptions is None else assumptions
    if set(supplied) != set(FIXED) or any(
        type(supplied[k]) is not int or supplied[k] != v for k, v in FIXED.items()
    ):
        raise ValueError("Exact preregistered assumptions required; no tuning")
    boundary = nanos(completed_at)
    if boundary % (900 * NS):
        raise ValueError("Completed fifteen-minute UTC boundary required")
    decision = boundary + supplied["decision_delay_ns"]
    submitted = decision + supplied["sender_delay_ns"]
    return {
        "contract": CONTRACT,
        "completed_at": stamp(boundary),
        "assumed_bar_available_at": stamp(boundary + 30 * NS),
        "assumed_anchor_available_at": stamp(boundary + 30 * NS),
        "assumed_forecast_available_at": stamp(boundary + 31 * NS),
        "assumed_decision_at": stamp(decision),
        "assumed_submission_at": stamp(submitted),
        "assumed_arrival_at": stamp(submitted + supplied["route_delay_ns"]),
        "trade_start": stamp(boundary),
        "trade_end": stamp(boundary + NS),
        "quote_start": stamp(boundary + 30 * NS),
        "quote_end": stamp(boundary + 33 * NS),
        "assumptions": dict(supplied),
        "historical_actual_receive_publication_inference": None,
        "availability_basis": "hypothetical_final_archive_not_observed_publication",
        "fill_basis": "conditional_full_intent_at_touch_no_depth_or_impact_proof",
        "timestamp_uncertainty_basis": "declared_symmetric_1ms_not_measured_accuracy",
        "quote_size_unit": "unresolved_no_share_conversion",
    }


# Refuse tampered conditional windows at every source and selector boundary.
def _window(window):
    if window != schedule(window["completed_at"]):
        raise ValueError("Original fixed window required")


# Describe only the separately authorized old AAPL quote query and pagination.
def quote_request(window, *, page_token=None):
    _window(window)
    if window["completed_at"] != "2019-03-01T14:45:00.000000000Z":
        raise ValueError("Only the authorized bounded old packet may be acquired")
    query = {
        "symbols": "AAPL",
        "feed": "sip",
        "start": "2019-03-01T14:45:30Z",
        "end": "2019-03-01T14:45:33Z",
        "limit": "1000",
        "sort": "asc",
        "asof": "2019-03-01",
    }
    if page_token is not None:
        if not isinstance(page_token, str) or not page_token:
            raise ValueError("Original nonempty pagination token required")
        query["page_token"] = page_token
    return ENDPOINT + "?" + urlencode(query)


# Bound actual acquisition clocks by a separately recorded verification instant.
def _clocks(requested, received, verified, historical_end, previous=None):
    began, ended, checked = nanos(requested), nanos(received), nanos(verified)
    if not began <= ended <= checked or began - nanos(historical_end) < 900 * NS:
        raise ValueError("Actual acquisition clocks exceed their verification bound")
    if previous is not None and began < previous:
        raise ValueError("Actual acquisition page clocks moved backward")
    return ended


# Authenticate one original successful body without accepting self-repaired data.
def _body(page, *, encoded="body_base64", digest="sha256"):
    raw = base64.b64decode(page[encoded], validate=True)
    if type(page["status"]) is not int or page["status"] != 200:
        raise ValueError("Original successful provider status required")
    if hashlib.sha256(raw).hexdigest() != page[digest]:
        raise ValueError("Original successful provider body bytes required")
    return _decode(raw)


# Validate one exact quote page and retain its original next-page instruction.
def _quote_page(window, page, token, previous, verified):
    expected = urlsplit(quote_request(window, page_token=token))
    actual = urlsplit(page["url"])
    if (actual.scheme, actual.netloc, actual.path, actual.fragment) != (
        expected.scheme,
        expected.netloc,
        expected.path,
        "",
    ) or parse_qs(actual.query, keep_blank_values=True) != parse_qs(expected.query):
        raise ValueError("Exact whitelisted request and original page chain required")
    received = _clocks(
        page["requested_at"],
        page["received_at"],
        verified,
        window["quote_end"],
        previous,
    )
    body = _body(page)
    quotes = body.get("quotes")
    if not isinstance(quotes, dict) or set(quotes) - {"AAPL"}:
        raise ValueError("Exact requested AAPL response cohort required")
    rows = quotes.get("AAPL", [])
    if not isinstance(rows, list):
        raise ValueError("Original quote row list required")
    return rows, body.get("next_page_token"), received


# Preserve chronological in-window events without sorting or dropping duplicates.
def _ordered(rows, first, last):
    times = [nanos(row["t"]) for row in rows]
    if times != sorted(times) or any(
        not nanos(first) <= at <= nanos(last) for at in times
    ):
        raise ValueError("Ordered original in-window source events required")
    return rows


# Restore all quote pages, including short or empty pages with further tokens.
def _quotes(window, captured, verified):
    if ("complete" in captured and captured["complete"] is not True) or captured.get(
        "failure"
    ) is not None:
        raise ValueError("Declared failed acquisition cannot supply a quote packet")
    pages = captured.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError("One to ten original quote pages required")
    rows, token, seen, previous = [], None, set(), None
    for index, page in enumerate(pages):
        parsed, token, previous = _quote_page(window, page, token, previous, verified)
        rows.extend(parsed)
        if token is not None:
            if not isinstance(token, str) or not token or token in seen:
                raise ValueError("Original unique next page token required")
            seen.add(token)
        if (token is None) != (index == len(pages) - 1):
            raise ValueError(
                "Incomplete or extra pagination; short pages are not proof"
            )
    return _ordered(rows, window["quote_start"], window["quote_end"])


# Reuse the original separately captured trade page without any additional GET.
def _trades(window, captured, verified):
    selected = [p for p in captured.get("requests", []) if p.get("kind") == "trades"]
    if len(selected) != 1:
        raise ValueError("One original bounded trade acquisition required")
    page = selected[0]
    expected = {
        "start": "2019-03-01T14:45:00Z",
        "end": "2019-03-01T14:45:01Z",
        "feed": "sip",
        "limit": 1000,
        "sort": "asc",
    }
    if (
        page["endpoint"] != "https://data.alpaca.markets/v2/stocks/AAPL/trades"
        or page["parameters"] != expected
    ):
        raise ValueError("Exact original historical trade query required")
    _clocks(
        page["actual_requested_at"],
        page["actual_received_at"],
        verified,
        window["trade_end"],
    )
    body = _body(page, encoded="raw_body_base64", digest="raw_body_sha256")
    rows = body.get("trades")
    if body.get("symbol") != "AAPL" or not isinstance(rows, list):
        raise ValueError("Original AAPL trade body required")
    if body.get("next_page_token") is not None or page["more_available"] is not False:
        raise ValueError("Complete original trade page required")
    if rows != page["observations"]:
        raise ValueError("Original trade interpretation differs from body")
    return _ordered(rows, window["trade_start"], window["trade_end"])


# Validate sealed immutable source bytes before exposing any decision or outcome row.
def _rows(window, archived, kind):
    _window(window)
    if not isinstance(archived, ArchivedPacket) or archived.kind != kind:
        raise ValueError("Authenticated immutable source packet required")
    if (
        archived.window_sha256 != _digest(window)
        or hashlib.sha256(archived.source_bytes).hexdigest() != archived.source_sha256
    ):
        raise ValueError("Original packet declaration or source bytes differ")
    captured = _decode(archived.source_bytes)
    return (_quotes if kind == "quotes" else _trades)(
        window, captured, archived.verified_at
    )


# Bind an independently pinned acquisition receipt to its exact conditional window.
def source_packet(window, raw, expected_sha256, verified_at, *, kind):
    if type(raw) is not bytes or kind not in ("quotes", "trades"):
        raise ValueError("Original immutable source bytes and explicit kind required")
    archived = ArchivedPacket(kind, _digest(window), expected_sha256, raw, verified_at)
    _rows(window, archived, kind)
    return archived


# Keep unavailable evidence explicit without assigning a price or executable size.
def _missing(reason):
    return {
        "status": "unavailable",
        "reason": reason,
        "price": None,
        "quote": None,
        "liquidity_capacity_shares": None,
    }


# Preserve native positive-book and25bp checks without assigning share size units.
def _book(row):
    values = [row.get(name) for name in ("bp", "ap", "bs", "as")]
    if any(
        isinstance(v, bool)
        or not isinstance(v, (int, float))
        or not math.isfinite(v)
        or v <= 0
        for v in values
    ):
        return False
    bid, ask, _, _ = values
    midpoint = bid / 2 + ask / 2
    return (
        ask >= bid and math.isfinite(midpoint) and (ask - bid) / midpoint * 10000 <= 25
    )


# Reject conflicting equal-clock source values rather than picking an ordering.
def _unique(rows):
    return len({_digest(row) for row in rows}) == 1


# Select only the latest quote whose assumed receive upper bound precedes decision.
def decision_quote(window, archived):
    rows = _rows(window, archived, "quotes")
    tolerance = FIXED["event_timestamp_uncertainty_ns"]
    cutoff = nanos(window["assumed_decision_at"]) - FIXED["quote_receive_delay_ns"]
    known = [row for row in rows if nanos(row["t"]) + tolerance <= cutoff]
    if not known:
        return _missing("No quote conservatively available by the fixed decision")
    latest = max(nanos(row["t"]) for row in known)
    cluster = [row for row in known if nanos(row["t"]) == latest]
    if not _unique(cluster) or not _book(cluster[0]):
        return _missing("Latest quote conflicting or unqualified; no older fallback")
    return {
        "status": "available",
        "reason": "Conditional decision packet only",
        "quote": deepcopy(cluster[0]),
        "price": cluster[0]["bp"] / 2 + cluster[0]["ap"] / 2,
        "assumed_receive_upper_at": stamp(
            latest + tolerance + FIXED["quote_receive_delay_ns"]
        ),
        "source_sha256": archived.source_sha256,
        "liquidity_capacity_shares": None,
    }


# Apply documented minute-price conditions while preserving unknown eligibility.
def _eligible(row):
    allowed = {"A": {" ", "E"}, "B": {" ", "E"}, "C": {"@", "A", "B", "D", "Y"}}
    common = {"F", "K", "L", "O", "T", "X", "5", "6"}
    excluded = {
        "C",
        "G",
        "H",
        "I",
        "M",
        "N",
        "P",
        "Q",
        "R",
        "U",
        "V",
        "W",
        "Z",
        "4",
        "7",
        "9",
    }
    conditions, tape = row.get("c"), row.get("z")
    if tape not in allowed or not isinstance(conditions, list) or not conditions:
        return None
    if any(not isinstance(c, str) for c in conditions):
        return None
    if any(c in excluded or (c == "B" and tape in ("A", "B")) for c in conditions):
        return False
    return True if all(c in allowed[tape] | common for c in conditions) else None


# Verify the first eligible reported print rather than finding a desired price later.
def opening_anchor(window, archived, original_open):
    trades = _rows(window, archived, "trades")
    if (
        isinstance(original_open, bool)
        or not isinstance(original_open, (int, float))
        or not math.isfinite(original_open)
        or original_open <= 0
    ):
        raise ValueError("Original positive raw opening anchor required")
    first = []
    for row in trades:
        if first and nanos(row["t"]) > nanos(first[0]["t"]):
            break
        eligible = _eligible(row)
        if eligible is None:
            return _missing("Unknown eligibility before or tied with first print")
        if eligible:
            first.append(row)
    if not first:
        return _missing("No eligible opening print in the fixed trade window")
    prices = [row.get("p") for row in first]
    if (
        any(
            isinstance(p, bool)
            or not isinstance(p, (int, float))
            or not math.isfinite(p)
            or p <= 0
            for p in prices
        )
        or len(set(prices)) != 1
        or prices[0] != original_open
    ):
        return _missing("First eligible print does not uniquely match raw bar opening")
    return {
        "status": "available",
        "reason": "First eligible print matches; publication assumed",
        "price": original_open,
        "trades": deepcopy(first),
        "assumed_available_at": window["assumed_anchor_available_at"],
        "actual_historical_published_at": None,
        "source_sha256": archived.source_sha256,
    }


# Choose the first qualified touch whose event lower bound exceeds arrival upper.
def execution_reference(window, archived, side):
    rows = _rows(window, archived, "quotes")
    if side not in ("buy", "sell"):
        raise ValueError("Explicit buy or sell side required")
    tolerance = FIXED["event_timestamp_uncertainty_ns"]
    arrival = (
        nanos(window["assumed_arrival_at"]) + FIXED["arrival_clock_uncertainty_ns"]
    )
    future = [
        row
        for row in rows
        if nanos(row["t"]) - tolerance > arrival
        and nanos(row["t"]) + tolerance <= nanos(window["quote_end"])
    ]
    for at in sorted({nanos(row["t"]) for row in future}):
        cluster = [row for row in future if nanos(row["t"]) == at]
        if not _unique(cluster):
            return _missing("Conflicting post-arrival ordering; no later fallback")
        row = cluster[0]
        if _book(row):
            return {
                "status": "available",
                "reason": "Conditional reference, not broker fill",
                "quote": deepcopy(row),
                "price": row["ap" if side == "buy" else "bp"],
                "event_at": row["t"],
                "event_lower_at": stamp(at - tolerance),
                "arrival_upper_at": stamp(arrival),
                "actual_fill_proven": False,
                "liquidity_capacity_shares": None,
                "raw_displayed_size": row["as" if side == "buy" else "bs"],
                "quote_size_unit": "unresolved_no_conversion",
                "source_sha256": archived.source_sha256,
            }
    return _missing("No qualifying conservatively post-arrival event in fixed window")
