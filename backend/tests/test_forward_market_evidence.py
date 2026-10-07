"""Original provider bytes must support causal prefixes and current quote transport."""

import base64
import json
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from urllib.parse import urlencode

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import calendar
from backend.market import forward_market_evidence as adapter
from backend.market import forward_probability_timing as forward
from backend.market import live_probability_timing as historical
from backend.market import sequential_shadow_prefix as source
from backend.market.replay_broker import ReplayBroker
from backend.tests.test_forward_execution import fitted as fitted
from backend.tests.test_forward_execution import residual_archive as residual_archive
from backend.tests.test_forward_execution import residual_month, write
from backend.tests.test_forward_probability_timing import inference_inputs
from backend.tests.test_live_probability_timing import intent

NOW = datetime(2026, 10, 5, 9, 45, 8, tzinfo=calendar.NEW_YORK)
NAMES = ("AAOI", "SPY", "QQQ")


# Capture the original raw/split endpoint responses through the real bounded parser.
def evidence():
    bar = {
        "t": "2026-10-05T13:30:00Z",
        "o": 100,
        "h": 102,
        "l": 99,
        "c": 101,
        "v": 1000,
    }
    forming = {**bar, "t": "2026-10-05T13:45:00Z", "o": 100.5, "c": 999}
    previous = {**bar, "t": "2026-10-02T19:45:00Z", "c": 99}
    raw_body = json.dumps(
        {"bars": {name: [bar, forming] for name in NAMES}, "next_page_token": None}
    ).encode()
    split_body = json.dumps(
        {
            "bars": {name: [previous, bar, forming] for name in NAMES},
            "next_page_token": None,
        }
    ).encode()
    clocks = iter(NOW - timedelta(seconds=seconds) for seconds in (7, 7, 6))
    raw = source.capture(
        NAMES,
        "2026-10-05",
        transport=lambda url, headers: (200, raw_body),
        headers={},
        clock=lambda: next(clocks),
    )
    clocks = iter(NOW - timedelta(seconds=seconds) for seconds in (5, 5, 4))
    anchors = source.capture_split_anchors(
        raw,
        "2026-10-02",
        "2026-10-05",
        transport=lambda url, headers: (200, split_body),
        headers={},
        clock=lambda: next(clocks),
    )
    quote_body = json.dumps(
        {
            "quotes": {
                name: {
                    "bp": 98.995,
                    "ap": 99.005,
                    "bs": 100,
                    "as": 100,
                    "t": "2026-10-05T13:45:05Z",
                }
                for name in NAMES
            }
        }
    ).encode()
    return raw, anchors, quote_body


# A forming bar supplies only its already-observed opening, never unfinished features.
def test_original_bytes_to_causal_market_packet():
    raw, anchors, quote_body = evidence()
    clocks = iter((NOW - timedelta(seconds=2), NOW - timedelta(seconds=1)))
    quote_page = adapter.capture_quotes(
        NAMES,
        transport=lambda url, headers: (200, quote_body),
        headers={},
        clock=lambda: next(clocks),
    )
    packet = adapter.prepare(raw, anchors, quote_page, observed_at=NOW)
    assert set(packet.prefixes) == set(NAMES)
    record = packet.prefixes["AAOI"]
    np.testing.assert_array_equal(record["close"], [101])
    assert record["prior_close"] == 99
    quote = packet.snapshot["quotes"]["AAOI"]
    assert quote["next_open"] == 100.5
    assert quote["next_open_at"] == "2026-10-05T09:45:00-04:00"
    assert quote["next_open_published_at"] == raw["received_at"]
    assert quote["last"] == quote["bid"] / 2 + quote["ask"] / 2
    assert packet.receipt["training_prior_source_matches"] is False
    assert packet.receipt["adoption_eligible"] is False
    assert packet.receipt["sources"]["quotes"][0]["body_base64"]


# Supply one private original-byte packet without any live provider request.
def packet_inputs():
    raw, anchors, body = evidence()
    clocks = iter((NOW - timedelta(seconds=2), NOW - timedelta(seconds=1)))
    page = adapter.capture_quotes(
        NAMES,
        transport=lambda url, headers: (200, body),
        headers={"secret": "private"},
        clock=lambda: next(clocks),
    )
    return raw, anchors, page


# Change original synthetic bytes while preserving their explicit source hash.
def update_body(page, payload):
    page["body"] = json.dumps(payload).encode()
    page["sha256"] = sha256(page["body"]).hexdigest()


# Current unfinished prices must not alter any completed model feature.
def test_forming_prices_are_not_features():
    raw, anchors, page = packet_inputs()
    before = adapter.prepare(raw, anchors, page, observed_at=NOW)
    changed = deepcopy(raw)
    payload = json.loads(changed["pages"][0]["body"])
    for bars in payload["bars"].values():
        bars[-1].update(h=100000, l=-100000, c=1, v=999999)
    update_body(changed["pages"][0], payload)
    after = adapter.prepare(changed, anchors, page, observed_at=NOW)
    assert before.receipt_sha256 != after.receipt_sha256
    assert before.receipt["arrays_sha256"] == after.receipt["arrays_sha256"]
    for name in NAMES:
        for field in ("open", "high", "low", "close", "volume"):
            np.testing.assert_array_equal(
                before.prefixes[name][field], after.prefixes[name][field]
            )


# Absent current openings stay unavailable despite an otherwise usable quote.
def test_missing_opening_is_not_invented():
    raw, anchors, page = packet_inputs()
    payload = json.loads(raw["pages"][0]["body"])
    payload["bars"]["AAOI"].pop()
    update_body(raw["pages"][0], payload)
    packet = adapter.prepare(raw, anchors, page, observed_at=NOW)
    assert "AAOI" not in packet.snapshot["quotes"]
    assert set(packet.prefixes) == set(NAMES)
    assert (
        "AAOI"
        in json.loads(
            base64.b64decode(packet.receipt["sources"]["raw"][0]["body_base64"])
        )["bars"]
    )


# Unsupported per-name quotes remain in original evidence and cannot fund an action.
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("bs", True),
        ("bp", True),
        ("ap", 110),
        ("as", 0),
        ("t", "malformed"),
        ("t", "2026-10-05T13:45:09Z"),
        ("t", "2026-10-05T13:44:59Z"),
    ],
)
def test_invalid_quotes_remain_unavailable(key, value):
    raw, anchors, page = packet_inputs()
    payload = json.loads(page["body"])
    payload["quotes"]["AAOI"][key] = value
    update_body(page, payload)
    packet = adapter.prepare(raw, anchors, page, observed_at=NOW)
    assert "AAOI" not in packet.snapshot["quotes"]
    assert set(packet.snapshot["quotes"]) == {"SPY", "QQQ"}
    original = base64.b64decode(packet.receipt["sources"]["quotes"][0]["body_base64"])
    assert original == page["body"]
    assert json.loads(original)["quotes"]["AAOI"][key] == value


# Tampered, disconnected, incompatible or late source packets fail before inference.
@pytest.mark.parametrize("defect", ["bytes", "pagination", "basis", "clock", "anchor"])
def test_source_defects_are_rejected(defect):
    raw, anchors, page = packet_inputs()
    if defect == "bytes":
        raw["pages"][0]["body"] += b" "
    elif defect == "pagination":
        raw["pages"][0]["url"] += "&page_token=unconnected"
    elif defect == "basis":
        raw["pages"][0]["url"] = raw["pages"][0]["url"].replace(
            "adjustment=raw", "adjustment=all"
        )
    elif defect == "clock":
        page["received_at"] = (NOW + timedelta(seconds=1)).isoformat()
    else:
        anchors["anchors"]["AAOI"] = 10000
    with pytest.raises(ValueError, match="Original"):
        adapter.prepare(raw, anchors, page, observed_at=NOW)


# Original bytes reach real numeric inference without trusting a changed caller array.
def test_original_packet_to_numeric_forecast(fitted, residual_archive, tmp_path):
    raw, anchors, page = packet_inputs()
    page["headers"] = {"Authorization": "must not be persisted"}
    packet = adapter.prepare(raw, anchors, page, observed_at=NOW)
    assert "headers" not in packet.receipt["sources"]["quotes"][0]
    (panel, grades, eligible, _), clocks = inference_inputs()
    folder = tmp_path / "models"
    model_hash = write(folder, fitted[1])
    forecast = adapter.prepare_forecast(
        packet,
        panel,
        grades,
        eligible,
        daily_as_of=clocks["daily_as_of"],
        model_folder=folder,
        model_receipt_sha256=model_hash,
        residual_month=residual_month(residual_archive[1]),
        clock=lambda: NOW + timedelta(seconds=1),
    )
    assert forecast.distributions["AAOI"] is not None
    assert forecast.distributions["SPY"] is None
    assert forecast.receipt["market_source_evidence"] == packet.receipt
    packet.prefixes["AAOI"]["close"][0] = 1
    with pytest.raises(ValueError, match="unchanged market evidence"):
        adapter.prepare_forecast(
            packet,
            panel,
            grades,
            eligible,
            daily_as_of=clocks["daily_as_of"],
            model_folder=folder,
            model_receipt_sha256=model_hash,
            residual_month=residual_month(residual_archive[1]),
            clock=lambda: NOW,
        )


# Real private acknowledgments retain source bytes and the exact inferred distribution.
def test_original_packet_to_persisted_sender(fitted, residual_archive, tmp_path):
    raw, anchors, page = packet_inputs()
    packet = adapter.prepare(raw, anchors, page, observed_at=NOW)
    (panel, grades, eligible, _), clocks = inference_inputs()
    folder = tmp_path / "models"
    digest = write(folder, fitted[1])
    forecast = adapter.prepare_forecast(
        packet,
        panel,
        grades,
        eligible,
        daily_as_of=clocks["daily_as_of"],
        model_folder=folder,
        model_receipt_sha256=digest,
        residual_month=residual_month(residual_archive[1]),
        clock=lambda: NOW + timedelta(seconds=1),
    )
    now = NOW + timedelta(seconds=2)
    client = ReplayBroker(10000, 0)
    client.observe(NOW, {"AAOI": 99}, True)
    observed = forward.capture_account(client, NOW.replace(second=0), clock=lambda: now)
    state = paper.PaperState()
    row = intent(symbol="AAOI", qty=5)
    row["execute_on"] = NOW.date().isoformat()
    row["timing_policy"] = historical.POLICY
    state.pending = [row]
    root = tmp_path / "paper"
    paper.save_state(root, state)
    trace = []
    reader = forward.build_forecast_reader(
        forecast,
        now,
        packet.snapshot,
        state.pending,
        observed,
        10,
        trace,
        evidence_root=root,
    )
    assert (
        len(
            intraday_orders.send_due(
                root,
                packet.snapshot,
                now,
                lambda: client,
                timing_reader=reader,
            )
        )
        == 1
    )
    reference = paper.load_state(root).pending[0]["sent"]["forward_timing"]["receipt"][
        "inference"
    ]
    stored = (root / reference["path"]).read_bytes()
    assert sha256(stored).hexdigest() == reference["sha256"] == forecast.receipt_sha256
    persisted = json.loads(stored)["market_source_evidence"]["sources"]
    for key, original in (
        ("raw", raw["pages"][0]),
        ("split", anchors["pages"][0]),
        ("quotes", page),
    ):
        assert base64.b64decode(persisted[key][0]["body_base64"]) == original["body"]
    assert client.ledger()["holdings"] == {}
    assert (
        intraday_orders.send_due(
            root, packet.snapshot, now, lambda: client, timing_reader=reader
        )
        == []
    )


# The reviewed early-close calendar controls the final usable observation window.
def test_early_close_original_evidence():
    now = datetime(2026, 11, 27, 12, 45, 8, tzinfo=calendar.NEW_YORK)
    opening = now.replace(hour=9, minute=30, second=0)
    prior = datetime(2026, 11, 25, 15, 45, tzinfo=calendar.NEW_YORK)
    raw, anchors, page = packet_inputs()
    bars = [
        {
            "t": (opening + timedelta(minutes=15 * index)).isoformat(),
            "o": 100,
            "h": 102,
            "l": 99,
            "c": 101,
            "v": 1000,
        }
        for index in range(14)
    ]
    previous = {**bars[0], "t": prior.isoformat(), "c": 99}
    for captured, adjustment, start, data, request_seconds, receipt_seconds, end in (
        (raw, "raw", now.date(), bars, 7, 6, now - timedelta(seconds=7)),
        (
            anchors,
            "split",
            prior.date(),
            [previous, *bars],
            5,
            4,
            now - timedelta(seconds=6),
        ),
    ):
        original = captured["pages"][0]
        original["url"] = (
            source.ENDPOINT
            + "?"
            + urlencode(source._query(NAMES, start, end, adjustment))
        )
        original["requested_at"] = (
            now - timedelta(seconds=request_seconds)
        ).isoformat()
        original["received_at"] = (now - timedelta(seconds=receipt_seconds)).isoformat()
        captured["received_at"] = original["received_at"]
        update_body(
            original, {"bars": {name: data for name in NAMES}, "next_page_token": None}
        )
    page["requested_at"] = (now - timedelta(seconds=2)).isoformat()
    page["received_at"] = (now - timedelta(seconds=1)).isoformat()
    payload = json.loads(page["body"])
    for quote in payload["quotes"].values():
        quote["t"] = (now - timedelta(seconds=3)).isoformat()
    update_body(page, payload)
    packet = adapter.prepare(raw, anchors, page, observed_at=now)
    assert len(packet.prefixes["AAOI"]["close"]) == 13
    assert (
        packet.snapshot["quotes"]["AAOI"]["next_open_at"] == "2026-11-27T12:45:00-05:00"
    )
    with pytest.raises(ValueError, match="completed regular observation"):
        adapter.prepare(
            raw, anchors, page, observed_at=now.replace(hour=13, minute=0, second=0)
        )


# Supply original responses for either a full session or a reviewed early close.
def capture_payloads(now, prior):
    opening = datetime.combine(now.date(), calendar.REGULAR_OPEN, calendar.NEW_YORK)
    count = int((now - opening) // timedelta(minutes=15))
    bars = [
        {
            "t": (opening + timedelta(minutes=15 * index)).isoformat(),
            "o": 100,
            "h": 102,
            "l": 99,
            "c": 101,
            "v": 1000,
        }
        for index in range(count + 1)
    ]
    bars[-1].update(o=100.5, c=999)
    previous = {**bars[0], "t": prior.isoformat(), "c": 99}
    return [
        json.dumps(
            {"bars": {name: rows for name in NAMES}, "next_page_token": None}
        ).encode()
        for rows in (bars, [previous, *bars])
    ] + [
        json.dumps(
            {
                "quotes": {
                    name: {
                        "bp": 98.995,
                        "ap": 99.005,
                        "bs": 100,
                        "as": 100,
                        "t": (now - timedelta(seconds=3)).isoformat(),
                    }
                    for name in NAMES
                }
            }
        ).encode()
    ]


# One acquisition must work on the actual early-close clock without a wrapper override.
@pytest.mark.parametrize(
    ("now", "prior", "count"),
    [
        (NOW, datetime(2026, 10, 2, 15, 45, tzinfo=calendar.NEW_YORK), 1),
        (
            datetime(2026, 11, 27, 12, 45, 8, tzinfo=calendar.NEW_YORK),
            datetime(2026, 11, 25, 15, 45, tzinfo=calendar.NEW_YORK),
            13,
        ),
    ],
)
def test_capture_current_regular_and_early_close(now, prior, count):
    bodies = capture_payloads(now, prior)
    responses = iter(bodies)
    requests = []
    clocks = iter(now - timedelta(seconds=seconds) for seconds in range(8, -1, -1))

    # Count exact request URLs without copying credential headers into the evidence.
    def transport(url, headers):
        requests.append(url)
        assert headers == {"Authorization": "private"}
        return 200, next(responses)

    packet = adapter.capture(
        NAMES,
        transport=transport,
        headers={"Authorization": "private"},
        clock=lambda: next(clocks),
    )
    assert len(requests) == 3
    assert "adjustment=raw" in requests[0]
    assert "adjustment=split" in requests[1]
    assert requests[2].startswith(adapter.QUOTE_ENDPOINT)
    assert len(packet.prefixes["AAOI"]["close"]) == count
    assert packet.receipt["observed_at"] == now.isoformat()
    for label, original in zip(("raw", "split", "quotes"), bodies, strict=True):
        assert (
            base64.b64decode(packet.receipt["sources"][label][0]["body_base64"])
            == original
        )


# Failed later requests retain earlier original bytes without retrying another window.
@pytest.mark.parametrize("failed", [0, 1, 2])
def test_capture_preserves_failed_endpoint(failed):
    bodies = capture_payloads(
        NOW, datetime(2026, 10, 2, 15, 45, tzinfo=calendar.NEW_YORK)
    )
    requests = []
    clocks = iter(NOW - timedelta(seconds=seconds) for seconds in range(8, -1, -1))

    # Stop at the first unavailable source while retaining its exact failure response.
    def transport(url, headers):
        index = len(requests)
        requests.append(url)
        return (
            (403, b'{"message":"source unavailable"}')
            if index == failed
            else (200, bodies[index])
        )

    with pytest.raises(source.CaptureError, match="source|endpoint") as caught:
        adapter.capture(
            NAMES, transport=transport, headers={}, clock=lambda: next(clocks)
        )
    assert len(requests) == failed + 1
    assert len(caught.value.pages) == failed + 1
    assert caught.value.pages[-1]["status"] == 403
    assert caught.value.pages[-1]["body"] == b'{"message":"source unavailable"}'
    for index in range(failed):
        assert caught.value.pages[index]["body"] == bodies[index]


# A closed session must cause no request at all.
def test_capture_closed_session_does_not_request():
    requests = []
    with pytest.raises(ValueError, match="completed regular observation"):
        adapter.capture(
            NAMES,
            transport=lambda url, headers: requests.append(url),
            headers={},
            clock=lambda: NOW.replace(hour=16, minute=0, second=0),
        )
    assert requests == []


# Crossing a window stops later requests while preserving all already captured bytes.
@pytest.mark.parametrize(("crossed_at", "requests_expected"), [(2, 1), (6, 2), (7, 3)])
def test_capture_does_not_continue_expired_window(crossed_at, requests_expected):
    bodies = capture_payloads(
        NOW, datetime(2026, 10, 2, 15, 45, tzinfo=calendar.NEW_YORK)
    )
    clocks = [NOW - timedelta(seconds=seconds) for seconds in range(8, -1, -1)]
    clocks[crossed_at:] = [NOW + timedelta(minutes=15)] * (len(clocks) - crossed_at)
    times = iter(clocks)
    requests = []

    # Return only the original response for each actually permitted endpoint request.
    def transport(url, headers):
        index = len(requests)
        requests.append(url)
        return 200, bodies[index]

    with pytest.raises(source.CaptureError, match="window|source") as caught:
        adapter.capture(
            NAMES, transport=transport, headers={}, clock=lambda: next(times)
        )
    assert len(requests) == requests_expected
    assert len(caught.value.pages) == requests_expected
    assert [page["body"] for page in caught.value.pages] == bodies[:requests_expected]


# A missing quote response preserves bars and unit evidence without fabricating bytes.
def test_capture_preserves_transport_failure():
    bodies = capture_payloads(
        NOW, datetime(2026, 10, 2, 15, 45, tzinfo=calendar.NEW_YORK)
    )
    clocks = iter(NOW - timedelta(seconds=seconds) for seconds in range(8, -1, -1))
    requests = []

    # Reproduce an endpoint outage after the two successful original bar responses.
    def transport(url, headers):
        requests.append(url)
        if len(requests) == 3:
            raise OSError("quote response unavailable")
        return 200, bodies[len(requests) - 1]

    with pytest.raises(
        source.CaptureError, match="quote response unavailable"
    ) as caught:
        adapter.capture(
            NAMES, transport=transport, headers={}, clock=lambda: next(clocks)
        )
    assert len(requests) == 3
    assert [page["body"] for page in caught.value.pages] == bodies[:2]


# A paginated response that expires must not trigger a further provider request.
def test_capture_stops_expired_pagination():
    body = capture_payloads(
        NOW, datetime(2026, 10, 2, 15, 45, tzinfo=calendar.NEW_YORK)
    )[0]
    original = json.loads(body)
    first = json.dumps(
        {
            "bars": {name: bars[:1] for name, bars in original["bars"].items()},
            "next_page_token": "next",
        }
    ).encode()
    final = json.dumps(
        {
            "bars": {name: bars[1:] for name, bars in original["bars"].items()},
            "next_page_token": None,
        }
    ).encode()
    clocks = iter(
        [NOW - timedelta(seconds=8), NOW - timedelta(seconds=7)]
        + [NOW + timedelta(minutes=15)] * 10
    )
    requests = []

    # Return distinct original pages so only the clock boundary explains refusal.
    def transport(url, headers):
        requests.append(url)
        return 200, first if len(requests) == 1 else final

    with pytest.raises(source.CaptureError, match="window|source") as caught:
        adapter.capture(
            NAMES, transport=transport, headers={}, clock=lambda: next(clocks)
        )
    assert len(requests) == 1
    assert [page["body"] for page in caught.value.pages] == [first]


# Connected pages must arrive once in order; a repeated continuation is refused.
@pytest.mark.parametrize("repeated", [False, True])
def test_capture_connected_pagination(repeated):
    now = NOW + timedelta(seconds=2)
    bodies = capture_payloads(
        now, datetime(2026, 10, 2, 15, 45, tzinfo=calendar.NEW_YORK)
    )
    original = json.loads(bodies[0])
    first = json.dumps(
        {
            "bars": {name: bars[:1] for name, bars in original["bars"].items()},
            "next_page_token": "next",
        }
    ).encode()
    final = json.dumps(
        {
            "bars": {name: bars[1:] for name, bars in original["bars"].items()},
            "next_page_token": "next" if repeated else None,
        }
    ).encode()
    responses = iter([first, final, *bodies[1:]])
    clocks = iter(now - timedelta(seconds=seconds) for seconds in range(10, -1, -1))
    requests = []

    # Return exactly the next page from the fixed original source chain.
    def transport(url, headers):
        requests.append(url)
        return 200, next(responses)

    if repeated:
        with pytest.raises(
            source.CaptureError, match="Repeated source pagination"
        ) as caught:
            adapter.capture(
                NAMES, transport=transport, headers={}, clock=lambda: next(clocks)
            )
        assert len(requests) == 2
        assert [page["body"] for page in caught.value.pages] == [first, final]
    else:
        packet = adapter.capture(
            NAMES, transport=transport, headers={}, clock=lambda: next(clocks)
        )
        assert len(requests) == 4
        assert "page_token=next" in requests[1]
        assert len(packet.receipt["sources"]["raw"]) == 2
        assert packet.snapshot["quotes"]["AAOI"]["next_open"] == 100.5
