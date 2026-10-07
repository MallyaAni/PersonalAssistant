"""Original-byte market packets for the existing private forward timing path.

IEX prefixes and prior anchors differ from the original SIP/Yahoo training
sources. This adapter preserves that limitation and never certifies an edge,
broker fill, account state or production policy adoption.
"""

import base64
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import numpy as np

from backend.market import calendar, execution_quotes
from backend.market import forward_probability_timing as inference
from backend.market import sequential_shadow_prefix as source
from backend.market.daily_arithmetic_bridge import _as_of

QUOTE_ENDPOINT = "https://data.alpaca.markets/v2/stocks/quotes/latest"


# Detach causal model inputs from their preserved original source receipts.
@dataclass(frozen=True)
class MarketPacket:
    prefixes: dict
    snapshot: dict
    receipt: dict
    receipt_sha256: str


# Capture one explicit free-feed GET without discarding its original response bytes.
def capture_quotes(symbols, *, transport, headers, clock, expected_window=None):
    names = source._symbols(symbols)
    url = QUOTE_ENDPOINT + "?" + urlencode({"symbols": ",".join(names), "feed": "iex"})
    requested = _as_of(clock())
    if expected_window is not None:
        _same_window(expected_window[0], requested, expected_window[1])
    status, body = transport(url, headers)
    received = _as_of(clock())
    return {
        "url": url,
        "requested_at": requested.isoformat(),
        "received_at": received.isoformat(),
        "status": status,
        "body": body,
        "sha256": sha256(body).hexdigest(),
    }


# Resolve an actually completed active window on the reviewed exchange calendar.
def _window(now):
    session = now.date()
    years, exchange = calendar.reviewed_sessions()
    opening = datetime.combine(session, calendar.REGULAR_OPEN, calendar.NEW_YORK)
    closing = datetime.combine(
        session, calendar.session_close(session), calendar.NEW_YORK
    )
    if (
        session.year not in years
        or not np.is_busday(np.datetime64(session), busdaycal=exchange)
        or not opening + timedelta(minutes=15) <= now < closing
    ):
        raise ValueError("Current completed regular observation required")
    count = int((now - opening) // timedelta(minutes=15))
    return session, count, opening + timedelta(minutes=15 * count)


# Stop subsequent requests when the clock moves backward or crosses a bar boundary.
def _same_window(completed, now, minimum):
    if now < minimum or _window(now)[2] != completed:
        raise ValueError("Original source observation window changed")


# Bound each individual bar request while retaining the parser's original receipts.
def _capture_bars(names, query, completed, started, transport, headers, clock):
    pages, last, seen = [], {}, set()
    rows, received = {name: [] for name in names}, started
    try:
        for _ in range(100):
            requested = _as_of(clock())
            _same_window(completed, requested, received)
            first = [requested]

            # Retain the checked request instant and read the response clock afterward.
            def request_clock(first=first):
                return first.pop() if first else clock()

            status, body, received = source._request_page(
                source.ENDPOINT + "?" + urlencode(query),
                headers,
                transport,
                request_clock,
                received,
                pages,
            )
            if status != 200:
                raise source.CaptureError("Bar source endpoint unavailable", pages)
            _same_window(completed, received, requested)
            parsed, token = source._captured_page(body, names, last, pages)
            for name, bars in parsed.items():
                rows[name].extend(bars)
            if token is None:
                return {
                    "status": "captured",
                    "pages": pages,
                    "rows": rows,
                    "received_at": received.isoformat(),
                }
            if token in seen:
                raise ValueError("Repeated source pagination token")
            seen.add(token)
            query["page_token"] = token
        raise ValueError("Source page chain exceeded its declared bound")
    except (ValueError, TypeError, KeyError) as exc:
        raise source.CaptureError(
            "Market source evidence unavailable: " + str(exc), pages
        ) from exc


# Acquire one causal packet without orders, fitting or replacement windows.
def capture(symbols, *, transport, headers, clock):
    names = source._symbols(symbols)
    started = _as_of(clock())
    session, _, completed = _window(started)
    _, exchange = calendar.reviewed_sessions()
    prior = np.busday_offset(np.datetime64(session), -1, busdaycal=exchange).astype(
        object
    )
    pages = []
    try:
        raw = _capture_bars(
            names,
            source._query(names, session, started, "raw"),
            completed,
            started,
            transport,
            headers,
            clock,
        )
        pages.extend(raw["pages"])
        received = _as_of(raw["received_at"])
        _same_window(completed, received, started)
        raw["cubes"] = source.cubes_from_rows(
            raw.pop("rows"), str(session), received, {}
        )
        raw.update(feed="iex", price_basis="raw")
        anchor_started = _as_of(clock())
        _same_window(completed, anchor_started, received)
        anchors = _capture_bars(
            names,
            source._query(names, prior, received, "split"),
            completed,
            anchor_started,
            transport,
            headers,
            clock,
        )
        pages.extend(anchors["pages"])
        attested = _as_of(anchors["received_at"])
        _same_window(completed, attested, received)
        split_rows = anchors.pop("rows")
        anchors.update(
            anchors={},
            anchor_basis="IEX_split_adjusted_prior_regular_close_current_raw_equivalence",
            training_prior_source_matches=False,
        )
        for name, cube in raw["cubes"].items():
            value = source._anchor_for_symbol(
                cube, split_rows[name], str(session), str(prior), received
            )
            if value is not None:
                anchors["anchors"][name] = value
        quote = capture_quotes(
            names,
            transport=transport,
            headers=headers,
            clock=clock,
            expected_window=(completed, attested),
        )
        pages.append(quote)
        return prepare(raw, anchors, quote, observed_at=clock())
    except source.CaptureError as exc:
        raise source.CaptureError(str(exc), pages + exc.pages) from exc
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise source.CaptureError(
            "Market source evidence unavailable: " + str(exc), pages
        ) from exc


# Authenticate original bytes and clocks before parsing an endpoint response.
def _page(page, endpoint, now, previous=None):
    parts = urlsplit(page["url"])
    body = page["body"]
    requested, received = _as_of(page["requested_at"]), _as_of(page["received_at"])
    if (
        parts.scheme + "://" + parts.netloc + parts.path != endpoint
        or parts.fragment
        or page["status"] != 200
        or not isinstance(body, bytes)
        or sha256(body).hexdigest() != page["sha256"]
        or not requested <= received <= now
        or (previous is not None and requested < previous)
    ):
        raise ValueError(
            "Original successful endpoint bytes and receipt clocks required"
        )
    query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True)
    if any(len(values) != 1 or not values[0] for values in query.values()):
        raise ValueError("Unique nonempty original query parameters required")
    return {key: values[0] for key, values in query.items()}, requested, received


# Authenticate the original request window and any required matching endpoint.
def _bounded_end(query, requested, expected):
    declared = query.get("end")
    if (
        declared is None
        or _as_of(declared) > requested
        or (expected is not None and _as_of(declared) != expected)
    ):
        raise ValueError("Original bounded source window required")
    return declared


# Restore the exact page chain without requesting, sorting or repairing any bars.
def _chain(captured, names, now, start, adjustment, *, end=None):
    if captured["status"] != "captured" or not 1 <= len(captured["pages"]) <= 100:
        raise ValueError("Completed original bar page chain required")
    rows, last, previous, token, seen, declared = (
        {name: [] for name in names},
        {},
        None,
        None,
        set(),
        None,
    )
    for index, page in enumerate(captured["pages"]):
        query, requested, received = _page(page, source.ENDPOINT, now, previous)
        expected = {
            "symbols": ",".join(names),
            "timeframe": "15Min",
            "feed": "iex",
            "adjustment": adjustment,
            "limit": "10000",
            "sort": "asc",
            "start": datetime.combine(start, datetime.min.time(), UTC).isoformat(),
        }
        if index == 0:
            declared = _bounded_end(query, requested, end)
        expected["end"] = declared
        if token is not None:
            expected["page_token"] = token
        if query != expected:
            raise ValueError("Original source basis and connected pagination required")
        parsed, token = source._page(page["body"], names, last)
        for name, bars in parsed.items():
            rows[name].extend(bars)
        if token is None and index != len(captured["pages"]) - 1:
            raise ValueError("Unexpected pages after terminal response")
        if token is not None and token in seen:
            raise ValueError("Repeated source pagination token")
        seen.add(token)
        previous = received
    if token is not None or previous != _as_of(captured["received_at"]):
        raise ValueError("Complete original source receipt chain required")
    return rows, previous


# Retain exact original provider bytes inside the immutable inference evidence.
def _original_pages(pages):
    return [
        {
            **{
                key: deepcopy(page[key])
                for key in ("url", "requested_at", "received_at", "status", "sha256")
            },
            "body_base64": base64.b64encode(page["body"]).decode("ascii"),
        }
        for page in pages
    ]


# Join original bars, unit attestations and quotes without using forming-bar features.
def prepare(raw, anchors, quote_page, *, observed_at):
    now = _as_of(observed_at)
    session, count, completed = _window(now)
    _, exchange = calendar.reviewed_sessions()
    opening = datetime.combine(session, calendar.REGULAR_OPEN, calendar.NEW_YORK)
    first_query = parse_qs(urlsplit(raw["pages"][0]["url"]).query)
    names = source._symbols(first_query["symbols"][0].split(","))
    if raw.get("price_basis") != "raw" or raw.get("feed") != "iex":
        raise ValueError("Original raw IEX source required")
    rows, received = _chain(raw, names, now, session, "raw")
    prior = np.busday_offset(np.datetime64(session), -1, busdaycal=exchange).astype(
        object
    )
    split_rows, attested = _chain(anchors, names, now, prior, "split", end=received)
    if not completed <= received <= attested <= now < completed + timedelta(minutes=15):
        raise ValueError("Original sources must share the current completed clock")
    cubes = source.cubes_from_rows(rows, str(session), received, {})
    prefixes, computed = {}, {}
    for name, cube in cubes.items():
        value = source._anchor_for_symbol(
            cube, split_rows[name], str(session), str(prior), received
        )
        if value is not None:
            computed[name] = value
        prefixes[name] = {
            **{
                field: getattr(cube, field)[0, :count].copy()
                for field in ("open", "high", "low", "close", "volume")
            },
            "prior_close": value if value is not None else np.nan,
            "starts": [
                opening + timedelta(minutes=15 * index) for index in range(count)
            ],
            "published_at": attested,
        }
    if (
        anchors["anchors"] != computed
        or anchors.get("anchor_basis")
        != "IEX_split_adjusted_prior_regular_close_current_raw_equivalence"
        or anchors.get("training_prior_source_matches") is not False
    ):
        raise ValueError(
            "Original independently reconstructed unit attestation required"
        )
    query, _, quoted_at = _page(quote_page, QUOTE_ENDPOINT, now)
    if query != {"symbols": ",".join(names), "feed": "iex"}:
        raise ValueError("Original explicit IEX quote cohort required")
    quotes = json.loads(quote_page["body"])["quotes"]
    if not isinstance(quotes, dict) or set(quotes) - set(names):
        raise ValueError("Explicit requested quote symbols required")
    snapshot = {
        "quotes": _snapshots(rows, cubes, quotes, completed, now, received, quoted_at)
    }
    receipt = {
        "contract": "forward-market-evidence/1-private",
        "observed_at": now.isoformat(),
        "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "sources": {
            "raw": _original_pages(raw["pages"]),
            "split": _original_pages(anchors["pages"]),
            "quotes": _original_pages([quote_page]),
        },
        "training_prior_source_matches": False,
        "conditional_midpoint_proxy": True,
        "confidence_guarantee": False,
        "adoption_eligible": False,
    }
    receipt["arrays_sha256"] = _inputs_hash(prefixes, snapshot)
    return MarketPacket(prefixes, snapshot, receipt, inference._digest(receipt))


# Transport only verified current quotes with an already observed opening anchor.
def _snapshots(rows, cubes, quotes, completed, now, received, quoted_at):
    opening = completed.replace(hour=9, minute=30)
    count = int((completed - opening) // timedelta(minutes=15))
    snapshots = {}
    for name, quote in quotes.items():
        if not isinstance(quote, dict):
            continue
        cells = [source._number(quote.get(key)) for key in ("bp", "ap", "bs", "as")]
        if not all(np.isfinite(cell) and cell > 0 for cell in cells):
            continue
        described = execution_quotes.describe(quote, "iex", True, now)
        try:
            stamp = (
                source._timestamp(quote["t"]) if quote.get("t") is not None else None
            )
        except (TypeError, ValueError, OverflowError):
            stamp = None
        current = [values[0] for at, values in rows[name] if at == completed]
        if (
            not described.get("eligible")
            or described.get("spread_verified") is not True
            or stamp is None
            or not completed <= stamp <= quoted_at <= now
            or len(current) != 1
            or not np.isfinite(current[0])
            or current[0] <= 0
        ):
            continue
        midpoint = described["bid"] / 2 + described["ask"] / 2
        snapshots[name] = {
            **{key: described[key] for key in ("bid", "ask", "bid_size", "ask_size")},
            "last": midpoint,
            "reference_kind": "observed_bid_ask_midpoint",
            "completed_bar_close": float(cubes[name].close[0, count - 1]),
            "open": float(cubes[name].open[0, 0]),
            "bar": (completed - timedelta(minutes=15)).isoformat(),
            "as_of": stamp.isoformat(),
            "received_at": quoted_at.isoformat(),
            "feed": "iex",
            "basis": "raw_current_shares",
            "next_open": current[0],
            "next_open_at": completed.isoformat(),
            "next_open_published_at": received.isoformat(),
        }
    return snapshots


# Bind every supplied array, publication clock and quote before numerical inference.
def _inputs_hash(prefixes, snapshot):
    from backend.market.daily_arithmetic_bridge import _hash

    return inference._digest(
        {
            "prefixes": {
                name: {
                    key: _hash(value)
                    if isinstance(value, np.ndarray)
                    else (
                        [at.isoformat() for at in value]
                        if key == "starts"
                        else value.isoformat()
                        if isinstance(value, datetime)
                        else _hash(np.asarray(value))
                    )
                    for key, value in record.items()
                }
                for name, record in prefixes.items()
            },
            "snapshot": snapshot,
        }
    )


# Preserve original source bytes alongside the existing actual numeric forecast receipt.
def prepare_forecast(
    packet,
    panel,
    grades,
    eligible,
    *,
    daily_as_of,
    model_folder,
    model_receipt_sha256,
    residual_month,
    clock=None,
):
    if (
        not isinstance(packet, MarketPacket)
        or inference._digest(packet.receipt) != packet.receipt_sha256
        or packet.receipt["arrays_sha256"]
        != _inputs_hash(packet.prefixes, packet.snapshot)
        or packet.receipt["source_sha256"]
        != sha256(Path(__file__).read_bytes()).hexdigest()
    ):
        raise ValueError("Original unchanged market evidence packet required")
    forecast = inference.prepare_forecast(
        panel,
        grades,
        eligible,
        packet.prefixes,
        observed_at=packet.receipt["observed_at"],
        daily_as_of=daily_as_of,
        model_folder=model_folder,
        model_receipt_sha256=model_receipt_sha256,
        residual_month=residual_month,
        clock=clock,
    )
    receipt = deepcopy(forecast.receipt)
    receipt["market_source_evidence"] = deepcopy(packet.receipt)
    return inference.ObservedForecast(
        forecast.distributions, receipt, inference._digest(receipt)
    )
