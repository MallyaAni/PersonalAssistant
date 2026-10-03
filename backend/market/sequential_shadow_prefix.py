"""Strict read-only capture of contemporaneous IEX raw completed prefixes.

Original endpoint bytes, request and response clocks remain evidence. A supplied
prior close must already be attested on the current session's raw basis; this
module never estimates a corporate-action ratio or substitutes an adjusted
daily price. Missing anchors and bars remain unavailable model inputs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, time, timedelta
from urllib.parse import urlencode

import numpy as np

from backend.market import calendar
from backend.market.sequential_execution_shadow import _aware
from backend.market.sip_cube import SessionCube

ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"
FIELDS = ("o", "h", "l", "c", "v")


class CaptureError(ValueError):
    # Carry original failed response pages so callers can preserve the first boundary.
    def __init__(self, message, pages):
        super().__init__(message)
        self.pages = pages


# Parse timestamps strictly so malformed evidence cannot disappear from a prefix.
def _timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Provider bar timestamps must be timezone aware")
    return parsed.astimezone(UTC)


# Preserve invalid numerical cells as NaN rather than repairing market observations.
def _number(value):
    if isinstance(value, bool):
        return np.nan
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return np.nan


# Decode all requested symbols while refusing unknown keys or reordered duplicates.
def _page(body, names, last):
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get("bars"), dict):
        raise ValueError("Explicit bars object required")
    if set(payload["bars"]) - set(names):
        raise ValueError("Response contains an unrequested symbol")
    parsed = {}
    for name, rows in payload["bars"].items():
        if not isinstance(rows, list):
            raise ValueError("Each symbol requires an explicit bar list")
        parsed[name] = []
        for row in rows:
            if not isinstance(row, dict) or "t" not in row:
                raise ValueError("Every source row requires an attributable timestamp")
            stamp = _timestamp(row["t"])
            if name in last and stamp <= last[name]:
                raise ValueError("Source bars must be strictly ordered and unique")
            last[name] = stamp
            parsed[name].append((stamp, [_number(row.get(key)) for key in FIELDS]))
    token = payload.get("next_page_token")
    if token is not None and (not isinstance(token, str) or not token):
        raise ValueError("Pagination token must be nonempty text or null")
    return parsed, token


# Derive a regular observation clock from an actual receipt, never a requested time.
def observation_clock(received_at, session):
    received = _aware(received_at)
    if str(received.date()) != str(session):
        raise ValueError("Receipt and requested session must match")
    day = received.date()
    years, sessions = calendar.reviewed_sessions()
    if day.year not in years:
        raise ValueError("Observation date is outside the reviewed exchange calendar")
    if not np.is_busday(np.datetime64(session, "D"), busdaycal=sessions):
        return None
    opening = datetime.combine(day, time(9, 30), calendar.NEW_YORK)
    closing = datetime.combine(day, calendar.session_close(day), calendar.NEW_YORK)
    if (
        closing.time() != time(16)
        or not opening + timedelta(minutes=15) <= received < closing
    ):
        return None
    return min(24, int((received - opening) // timedelta(minutes=15)) - 1)


# Put only actually completed source bars into their original slots without padding.
def cubes_from_rows(rows, session, received_at, prior_closes):
    received = _aware(received_at)
    day = received.date()
    if str(day) != str(session):
        raise ValueError("Raw prefix belongs to another receipt session")
    opening = datetime.combine(day, time(9, 30), calendar.NEW_YORK)
    closing = datetime.combine(day, calendar.session_close(day), calendar.NEW_YORK)
    cubes = {}
    for name, bars in rows.items():
        columns = np.full((5, 1, 26), np.nan)
        for stamp, values in bars:
            if stamp.astimezone(calendar.NEW_YORK).date() != day:
                raise ValueError("Endpoint returned another session")
            if stamp > received:
                raise ValueError("Endpoint returned a future bar timestamp")
            if not opening <= stamp < closing:
                continue
            elapsed = (stamp - opening).total_seconds()
            if elapsed % 900:
                raise ValueError("Regular bars must align with the 15-minute grid")
            if stamp + timedelta(minutes=15) <= received:
                columns[:, 0, int(elapsed // 900)] = values
        prior = _number(prior_closes.get(name))
        cubes[name] = SessionCube(
            name,
            np.array([np.datetime64(session, "D")]),
            *columns,
            prior_close=np.array([prior]),
            excluded={},
            auction_open=np.array([np.nan]),
            auction_volume=np.array([np.nan]),
        )
    return cubes


# Attach the original page chain to a decoding failure without losing source bytes.
def _captured_page(body, names, last, pages):
    try:
        return _page(body, names, last)
    except (ValueError, TypeError) as exc:
        raise CaptureError(str(exc), pages) from exc


# Keep one explicit source identity per symbol without normalizing user inputs.
def _symbols(symbols):
    names = tuple(symbols)
    if (
        not names
        or len(set(names)) != len(names)
        or any(not isinstance(name, str) or not name or "," in name for name in names)
    ):
        raise ValueError("Unique explicit symbols required")
    return names


# Preserve sequential receipt clocks and earlier bytes when a later request fails.
def _request_page(url, headers, transport, clock, previous, pages):
    requested = _aware(clock())
    if requested < previous:
        raise CaptureError("Provider receipt clocks cannot move backwards", pages)
    try:
        status, body = transport(url, headers)
    except OSError as exc:
        raise CaptureError("Provider transport failed", pages) from exc
    received = _aware(clock())
    pages.append(
        {
            "url": url,
            "requested_at": requested.isoformat(),
            "received_at": received.isoformat(),
            "status": status,
            "body": body,
            "sha256": hashlib.sha256(body).hexdigest(),
        }
    )
    if received < requested:
        raise CaptureError("Provider receipt clocks cannot move backwards", pages)
    return status, body, received


# Reuse one bounded original-byte page chain for raw bars and declared split anchors.
def _fetch_chain(names, query, transport, headers, clock, started):
    rows = {name: [] for name in names}
    pages, last, seen = [], {}, set()
    received = started
    for _ in range(100):
        url = ENDPOINT + "?" + urlencode(query)
        status, body, received = _request_page(
            url, headers, transport, clock, received, pages
        )
        if status != 200:
            return {
                "status": "provider_failure",
                "pages": pages,
                "rows": {},
                "received_at": received.isoformat(),
            }
        parsed, token = _captured_page(body, names, last, pages)
        for name, bars in parsed.items():
            rows[name].extend(bars)
        if token is None:
            break
        if token in seen:
            raise CaptureError("Pagination token repeated", pages)
        seen.add(token)
        query["page_token"] = token
    else:
        raise CaptureError(
            "Page chain did not terminate within its declared bound", pages
        )
    return {
        "status": "captured",
        "pages": pages,
        "rows": rows,
        "received_at": received.isoformat(),
    }


# Construct the same explicit free-feed request with its declared adjustment basis.
def _query(names, start, end, adjustment):
    return {
        "symbols": ",".join(names),
        "timeframe": "15Min",
        "feed": "iex",
        "adjustment": adjustment,
        "limit": "10000",
        "sort": "asc",
        "start": datetime.combine(start, time(), UTC).isoformat(),
        "end": end.astimezone(UTC).isoformat(),
    }


# Capture a bounded GET page chain and return original bytes before any scoring.
def capture(symbols, session, *, transport, headers, clock, prior_closes=None):
    names = _symbols(symbols)
    started = _aware(clock())
    if (
        str(started.date()) != str(session)
        or observation_clock(started, session) is None
    ):
        raise ValueError("A supported active regular-session observation is required")
    captured = _fetch_chain(
        names,
        _query(names, started.date(), started, "raw"),
        transport,
        headers,
        clock,
        started,
    )
    rows, pages = captured.pop("rows"), captured["pages"]
    received = _aware(datetime.fromisoformat(captured["received_at"]))
    if captured["status"] != "captured":
        return {**captured, "cubes": {}, "observation_clock": None}
    decision_clock = observation_clock(received, session)
    if decision_clock != observation_clock(started, session):
        return {
            "status": "observation_boundary_crossed",
            "pages": pages,
            "cubes": {},
            "observation_clock": None,
            "received_at": received.isoformat(),
        }
    try:
        cubes = cubes_from_rows(rows, session, received, prior_closes or {})
    except ValueError as exc:
        raise CaptureError(str(exc), pages) from exc
    return {
        "status": "captured",
        "pages": pages,
        "cubes": cubes,
        "observation_clock": decision_clock,
        "received_at": received.isoformat(),
        "price_basis": "raw",
        "feed": "iex",
        "prior_anchor_required_on_current_raw_basis": True,
    }


# Require exact contemporaneous current OHLCV equality, never an estimated scale ratio.
def _anchor_for_symbol(raw_cube, rows, session, prior_session, received):
    current = [
        row
        for row in rows
        if str(row[0].astimezone(calendar.NEW_YORK).date()) == session
    ]
    previous = [
        row
        for row in rows
        if str(row[0].astimezone(calendar.NEW_YORK).date()) == prior_session
    ]
    if len(current) + len(previous) != len(rows):
        raise ValueError("Split anchor response contains an unrequested session")
    split_cube = cubes_from_rows({raw_cube.ticker: current}, session, received, {})[
        raw_cube.ticker
    ]
    fields = ("open", "high", "low", "close", "volume")
    # Comparison includes missingness; a split-response gap is never treated as a match.
    if any(
        not np.array_equal(
            getattr(raw_cube, key), getattr(split_cube, key), equal_nan=True
        )
        for key in fields
    ):
        return None
    known = np.isfinite(raw_cube.close[0])
    if not known.any():
        return None
    expected = datetime.combine(
        datetime.fromisoformat(prior_session).date(),
        calendar.session_close(datetime.fromisoformat(prior_session).date()),
        calendar.NEW_YORK,
    ) - timedelta(minutes=15)
    matches = [values[3] for stamp, values in previous if stamp == expected]
    if len(matches) != 1 or not np.isfinite(matches[0]) or matches[0] <= 0:
        return None
    return float(matches[0])


# Attest a provider split-adjusted prior regular close beside exactly equal raw bars.
def capture_split_anchors(raw, prior_session, session, *, transport, headers, clock):
    if raw["status"] != "captured" or raw["price_basis"] != "raw":
        raise ValueError("Completed raw capture required before unit attestation")
    names = tuple(raw["cubes"])
    previous_day = datetime.fromisoformat(prior_session).date()
    started = _aware(clock())
    original = _aware(datetime.fromisoformat(raw["received_at"]))
    years, sessions = calendar.reviewed_sessions()
    if (
        previous_day.year not in years
        or str(np.busday_offset(np.datetime64(session, "D"), -1, busdaycal=sessions))
        != prior_session
    ):
        raise ValueError("Anchor must belong to the preceding exchange session")
    if started < original:
        raise ValueError("Anchor capture cannot precede its raw evidence")
    result = _fetch_chain(
        names,
        _query(names, previous_day, original, "split"),
        transport,
        headers,
        clock,
        started,
    )
    received = _aware(datetime.fromisoformat(result["received_at"]))
    rows = result.pop("rows")
    result["anchors"] = {}
    result["anchor_basis"] = (
        "IEX_split_adjusted_prior_regular_close_current_raw_equivalence"
    )
    result["training_prior_source_matches"] = False
    if result["status"] != "captured":
        return result
    if observation_clock(received, session) != raw["observation_clock"]:
        result["status"] = "observation_boundary_crossed"
        return result
    for name, cube in raw["cubes"].items():
        try:
            value = _anchor_for_symbol(
                cube, rows[name], session, prior_session, original
            )
        except ValueError as exc:
            raise CaptureError(str(exc), result["pages"]) from exc
        if value is not None:
            result["anchors"][name] = value
    return result
