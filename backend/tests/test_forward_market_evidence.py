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
