"""Source integrity and conservative causality, never model/account acceptance."""

import base64
import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from backend.market import historical_timing_packet as packet

VERIFIED = "2026-10-17T12:31:00Z"


# Supply an explicit conditional boundary without using today's clock.
def window():
    return packet.schedule("2019-03-01T14:45:00Z")


# Construct labelled synthetic quote evidence for source and causality properties.
def quote(at="2019-03-01T14:45:30.99Z", *, bid=100, ask=100.01, size=1):
    return {
        "t": at,
        "bp": bid,
        "ap": ask,
        "bs": size,
        "as": size,
        "bx": "Q",
        "ax": "Q",
        "c": ["R"],
        "z": "C",
    }


# Serialize a source fixture page with no credential-bearing fields.
def page(rows, *, token=None, requested_token=None):
    raw = json.dumps({"quotes": {"AAPL": rows}, "next_page_token": token}).encode()
    return {
        "url": packet.quote_request(window(), page_token=requested_token),
        "requested_at": "2026-10-17T12:30:00Z",
        "received_at": "2026-10-17T12:30:00.1Z",
        "status": 200,
        "body_base64": base64.b64encode(raw).decode(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


# Bind fixture receipt bytes exactly as a separately pinned acquisition manifest.
def sealed_quotes(rows=None, *, pages=None):
    raw = json.dumps(
        {"pages": pages if pages is not None else [page(rows or [])]}
    ).encode()
    return packet.source_packet(
        window(), raw, hashlib.sha256(raw).hexdigest(), VERIFIED, kind="quotes"
    )


# Reproduce the retained trade acquisition schema without making a network call.
def sealed_trades(rows):
    body = json.dumps(
        {"symbol": "AAPL", "trades": rows, "next_page_token": None}
    ).encode()
    receipt = {
        "requests": [
            {
                "kind": "trades",
                "endpoint": "https://data.alpaca.markets/v2/stocks/AAPL/trades",
                "parameters": {
                    "start": "2019-03-01T14:45:00Z",
                    "end": "2019-03-01T14:45:01Z",
                    "feed": "sip",
                    "limit": 1000,
                    "sort": "asc",
                },
                "actual_requested_at": "2026-10-17T12:30:00Z",
                "actual_received_at": "2026-10-17T12:30:00.1Z",
                "status": 200,
                "raw_body_base64": base64.b64encode(body).decode(),
                "raw_body_sha256": hashlib.sha256(body).hexdigest(),
                "observations": rows,
                "more_available": False,
            }
        ]
    }
    raw = json.dumps(receipt).encode()
    return packet.source_packet(
        window(), raw, hashlib.sha256(raw).hexdigest(), VERIFIED, kind="trades"
    )


# Keep all hypothetical clocks explicit and reject omitted or tuned assumptions.
@pytest.mark.parametrize(
    "bad",
    [
        {},
        {**packet.FIXED, "sender_delay_ns": False},
        {**packet.FIXED, "route_delay_ns": -1},
        {**packet.FIXED, "inference_duration_ns": 1},
    ],
)
def test_fixed_schedule_rejects_missing_or_changed_parameters(bad):
    with pytest.raises(ValueError, match="preregistered"):
        packet.schedule("2019-03-01T14:45:00Z", bad)


# Pin conditional ordering and uncertainty without calling either observed.
def test_fixed_schedule_and_nanosecond_order():
    w = window()
    assert w["assumed_decision_at"] == "2019-03-01T14:45:31.100000000Z"
    assert w["assumed_submission_at"] == "2019-03-01T14:45:31.200000000Z"
    assert w["assumed_arrival_at"] == "2019-03-01T14:45:31.300000000Z"
    assert w["historical_actual_receive_publication_inference"] is None
    assert packet.FIXED["event_timestamp_uncertainty_ns"] == 1_000_000
    at = "2019-03-01T14:45:31.000000001Z"
    assert packet.stamp(packet.nanos(at)) == at


# Reject malformed or precision-losing stamps rather than assigning a time zone.
@pytest.mark.parametrize(
    "at",
    [
        "2019-03-01T14:45:00",
        "2019-03-01T14:45:00-05:00",
        "2019-03-01T14:45:00.1234567891Z",
        True,
    ],
)
def test_timestamp_shape_guard(at):
    with pytest.raises(ValueError, match="Explicit UTC"):
        packet.nanos(at)


# Authenticate every short page through its token chain and preserve source bytes.
def test_complete_short_pages_and_input_preservation():
    first = page([quote("2019-03-01T14:45:30Z")], token="next")
    second = page([quote()], requested_token="next")
    second["requested_at"] = "2026-10-17T12:30:00.2Z"
    second["received_at"] = "2026-10-17T12:30:00.3Z"
    before = deepcopy([first, second])
    result = packet.decision_quote(window(), sealed_quotes(pages=[first, second]))
    assert result["quote"] == quote()
    assert [first, second] == before


# Reject an unfinished short page instead of silently losing its pagination.
def test_incomplete_page_rejected():
    with pytest.raises(ValueError, match="Incomplete"):
        sealed_quotes(pages=[page([], token="next")])


# Keep a complete empty response separate from failed acquisition or zero prices.
def test_complete_empty_response_is_explicitly_unavailable():
    value = page([])
    raw = b'{"quotes":{},"next_page_token":null}'
    value["body_base64"] = base64.b64encode(raw).decode()
    value["sha256"] = hashlib.sha256(raw).hexdigest()
    source = sealed_quotes(pages=[value])
    assert packet.decision_quote(window(), source)["status"] == "unavailable"
    assert packet.execution_reference(window(), source, "buy")["price"] is None


# Refuse a declared failed acquisition even when its retained last page looks complete.
@pytest.mark.parametrize(
    "declaration", [{"complete": False}, {"complete": True, "failure": "body_cap"}]
)
def test_failed_acquisition_cannot_be_reinterpreted_as_complete(declaration):
    raw = json.dumps({"pages": [page([quote()])], **declaration}).encode()
    with pytest.raises(ValueError, match="Declared failed acquisition"):
        packet.source_packet(
            window(), raw, hashlib.sha256(raw).hexdigest(), VERIFIED, kind="quotes"
        )


# Reject body ambiguity even when its original checksum matches exactly.
@pytest.mark.parametrize(
    "raw",
    [b'{"quotes":{},"quotes":{"AAPL":[]}}', b'{"quotes":{"AAPL":[{"t":"a","t":"b"}]}}'],
)
def test_duplicate_json_keys_rejected(raw):
    value = page([])
    value["body_base64"] = base64.b64encode(raw).decode()
    value["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="Duplicate JSON"):
        sealed_quotes(pages=[value])


# Fail on byte drift, query drift, HTTP errors and impossible acquisition clocks.
@pytest.mark.parametrize(
    "change", ["body", "url", "http", "clock", "future", "extra_page"]
)
def test_authentication_corruption(change):
    value = page([quote()])
    pages = [value]
    if change == "body":
        value["body_base64"] = base64.b64encode(b"{}").decode()
    elif change == "url":
        value["url"] = value["url"].replace("feed=sip", "feed=iex")
    elif change == "http":
        value["status"] = 429
    elif change == "clock":
        value["received_at"] = "2026-10-17T12:29:59Z"
    elif change == "future":
        value["received_at"] = "2099-01-01T00:00:00Z"
    else:
        pages.append(page([]))
    with pytest.raises(
        ValueError, match="body bytes|whitelisted|status|clocks|pagination"
    ):
        sealed_quotes(pages=pages)


# Prevent accidental native-hook use of unbound lists or mutated immutable receipts.
def test_source_bound_selector_and_tampered_receipt():
    source = sealed_quotes([quote()])
    with pytest.raises(ValueError, match="Authenticated immutable"):
        packet.decision_quote(window(), [quote()])
    damaged = replace(source, source_bytes=source.source_bytes + b" ")
    with pytest.raises(ValueError, match="source bytes differ"):
        packet.decision_quote(window(), damaged)


# Exclude future quotes and conservative receive overlaps from decision evidence.
def test_decision_uses_conservative_receive_upper():
    known = quote()
    overlap = quote("2019-03-01T14:45:31Z", bid=40, ask=40.01)
    result = packet.decision_quote(window(), sealed_quotes([known, overlap]))
    assert result["quote"] == known
    assert result["liquidity_capacity_shares"] is None
    assert result["assumed_receive_upper_at"] == "2019-03-01T14:45:31.091000000Z"
    future = quote("2019-03-01T14:45:32Z", bid=999, ask=999.01)
    assert (
        packet.decision_quote(window(), sealed_quotes([known, future]))["quote"]
        == known
    )


# Reject the latest qualified-time bad book instead of choosing an older quote.
def test_latest_bad_quote_has_no_older_fallback():
    rows = [quote("2019-03-01T14:45:30Z"), quote(bid=100, ask=110)]
    assert (
        packet.decision_quote(window(), sealed_quotes(rows))["status"] == "unavailable"
    )


# Reject contradictory source events rather than choosing favorable price order.
def test_conflicting_event_identity():
    source = sealed_quotes([quote(), quote(bid=101, ask=101.01)])
    assert packet.decision_quote(window(), source)["status"] == "unavailable"
    at = "2019-03-01T14:45:31.4Z"
    source = sealed_quotes([quote(at), quote(at, bid=101, ask=101.01)])
    assert (
        packet.execution_reference(window(), source, "buy")["status"] == "unavailable"
    )


# Use the first safely later side quote, retaining uncertain display size as raw.
def test_strict_postarrival_side_specific_first_reference():
    overlap = quote("2019-03-01T14:45:31.302Z", bid=50, ask=50.01)
    earliest = quote("2019-03-01T14:45:31.303Z", bid=100, ask=100.01)
    better = quote("2019-03-01T14:45:32Z", bid=40, ask=40.01)
    source = sealed_quotes([overlap, earliest, better])
    assert packet.execution_reference(window(), source, "buy")["price"] == 100.01
    sell = packet.execution_reference(window(), source, "sell")
    assert sell["price"] == 100
    assert sell["liquidity_capacity_shares"] is None
    assert sell["raw_displayed_size"] == 1
    assert sell["actual_fill_proven"] is False


# Do not use an overlapping deadline event as an execution beyond fixed coverage.
def test_missing_later_reference_stays_unavailable():
    source = sealed_quotes([quote(), quote("2019-03-01T14:45:33Z")])
    assert packet.execution_reference(window(), source, "buy")["price"] is None


# Pin first-eligible construction and immunity to later unknown trade conditions.
def test_first_eligible_anchor_and_later_unknown_invariance():
    trades = [
        {
            "t": "2019-03-01T14:45:00.006Z",
            "p": 174.03,
            "s": 6,
            "c": ["@", "I"],
            "z": "C",
        },
        {
            "t": "2019-03-01T14:45:00.007Z",
            "p": 174.01,
            "s": 100,
            "c": ["@", "F"],
            "z": "C",
        },
        {
            "t": "2019-03-01T14:45:00.008Z",
            "p": 174.03,
            "s": 100,
            "c": ["UNKNOWN"],
            "z": "C",
        },
    ]
    before = deepcopy(trades)
    source = sealed_trades(trades)
    assert packet.opening_anchor(window(), source, 174.01)["status"] == "available"
    assert packet.opening_anchor(window(), source, 174.03)["status"] == "unavailable"
    assert trades == before
    trades[-1]["t"] = trades[1]["t"]
    assert (
        packet.opening_anchor(window(), sealed_trades(trades), 174.01)["status"]
        == "unavailable"
    )


# Distinguish known excluded tapeAB average-price prints from unknown conditions.
def test_tape_ab_average_price_is_known_excluded():
    trades = [
        {"t": "2019-03-01T14:45:00.006Z", "p": 99, "c": ["B"], "z": "A"},
        {"t": "2019-03-01T14:45:00.007Z", "p": 100, "c": [" "], "z": "A"},
    ]
    assert (
        packet.opening_anchor(window(), sealed_trades(trades), 100)["status"]
        == "available"
    )


# Refuse unknown early eligibility and contradictory first reported prices.
def test_unknown_or_conflicting_anchor_unavailable():
    first = {"t": "2019-03-01T14:45:00.007Z", "p": 100, "c": ["UNKNOWN"], "z": "C"}
    assert (
        packet.opening_anchor(window(), sealed_trades([first]), 100)["status"]
        == "unavailable"
    )
    first["c"] = ["@"]
    assert (
        packet.opening_anchor(
            window(), sealed_trades([first, {**first, "p": 101}]), 100
        )["status"]
        == "unavailable"
    )


# Reject tampered schedules at every selector instead of trusting caller clocks.
@pytest.mark.parametrize(
    ("selector", "args"),
    [
        (packet.decision_quote, ()),
        (packet.execution_reference, ("buy",)),
        (packet.opening_anchor, (100,)),
    ],
)
def test_tampered_window_rejected(selector, args):
    altered = {**window(), "assumed_arrival_at": "2019-03-01T14:45:00Z"}
    source = sealed_trades([]) if args == (100,) else sealed_quotes([])
    with pytest.raises(ValueError, match="Original fixed window"):
        selector(altered, source, *args)
