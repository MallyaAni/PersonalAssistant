"""Original GET bytes, pagination, market clocks and unavailable raw anchors."""

import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import numpy as np
import pytest

from backend.market import calendar
from backend.market import sequential_shadow_prefix as prefix


# Supply an aware actual receipt after the opening completed candle.
def instant(day="2026-10-05", hour=9, minute=45):
    return datetime.fromisoformat(day).replace(
        hour=hour, minute=minute, second=1, tzinfo=calendar.NEW_YORK
    )


# Retain realistic endpoint rows rather than parsed quote summaries.
def bar(stamp="2026-10-05T13:30:00Z", **overrides):
    return {"t": stamp, "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 100, **overrides}


# Drive the real capture through an injectable GET endpoint with original bytes.
def run(pages, clocks=None, prior=None):
    requested = []
    responses = iter(pages)
    times = iter(clocks) if clocks is not None else None

    # Inspect query credentials separately without disclosing headers in receipts.
    def transport(url, headers):
        requested.append(parse_qs(urlsplit(url).query))
        assert headers == {"private": "not-in-receipt"}
        return next(responses)

    # Provide distinct request and response clocks when a boundary matters.
    def clock():
        return next(times) if times is not None else instant()

    result = prefix.capture(
        ["ONE"],
        "2026-10-05",
        transport=transport,
        headers={"private": "not-in-receipt"},
        clock=clock,
        prior_closes=prior,
    )
    return result, requested


# Keep raw OHLCV, forming bytes and page identities without using future closes.
def test_completed_prefix_retains_forming_bytes_but_masks_them():
    raw = json.dumps(
        {
            "bars": {"ONE": [bar(), bar("2026-10-05T13:45:00Z", c=999)]},
            "next_page_token": None,
        }
    ).encode()
    result, queries = run([(200, raw)], prior={"ONE": 10})
    assert result["pages"][0]["body"] == raw
    assert "private" not in result["pages"][0]["url"]
    assert queries[0]["adjustment"] == ["raw"]
    assert queries[0]["feed"] == ["iex"]
    assert result["observation_clock"] == 0
    cube = result["cubes"]["ONE"]
    assert cube.close[0, 0] == 10.5
    assert np.isnan(cube.close[0, 1:]).all()
    assert cube.prior_close[0] == 10


# Do not manufacture a raw anchor or a missing opening bar from adjusted history.
def test_missing_anchor_and_opening_are_explicit():
    raw = json.dumps({"bars": {"ONE": []}}).encode()
    result, _ = run([(200, raw)])
    assert np.isnan(result["cubes"]["ONE"].prior_close[0])
    assert np.isnan(result["cubes"]["ONE"].open).all()


# Honor the endpoint's page token exactly and preserve unknown numerical cells.
def test_pagination_and_invalid_cells_remain_original():
    first = json.dumps(
        {"bars": {"ONE": [bar(c="bad")]}, "next_page_token": "next"}
    ).encode()
    second = json.dumps({"bars": {"ONE": []}, "next_page_token": None}).encode()
    result, queries = run([(200, first), (200, second)])
    assert queries[1]["page_token"] == ["next"]
    assert len(result["pages"]) == 2
    assert np.isnan(result["cubes"]["ONE"].close[0, 0])


# Fail closed on source corruption rather than sorting or silently deleting it.
@pytest.mark.parametrize(
    "payload",
    [
        {"bars": {"OTHER": [bar()]}},
        {"bars": {"ONE": [bar(), bar()]}},
        {"bars": {"ONE": [bar(t="2026-10-05T13:30:00")]}},
        {"bars": {"ONE": [bar(t="2026-10-05T13:31:00Z")]}},
        {"bars": {"ONE": [bar(t="2026-10-06T13:30:00Z")]}},
        {"bars": {"ONE": [bar(t="2026-10-05T14:00:00Z")]}},
        {"bars": {"ONE": []}, "next_page_token": ""},
        {"bars": None},
    ],
)
def test_corrupt_provider_chain_is_rejected(payload):
    with pytest.raises(
        ValueError,
        match="unrequested|ordered|timezone|grid|session|future|token|bars object",
    ):
        run([(200, json.dumps(payload).encode())])


# Refuse a repeated token even when the provider omits all subsequent bars.
def test_repeated_pagination_does_not_loop():
    raw = json.dumps({"bars": {"ONE": []}, "next_page_token": "same"}).encode()
    with pytest.raises(ValueError, match="token repeated"):
        run([(200, raw), (200, raw)])


# Preserve a failed endpoint's bytes and prohibit scoring or fabricated retries.
def test_provider_failure_retains_original_response():
    result, requested = run([(403, b'{"message":"refused"}')])
    assert len(requested) == 1
    assert result["status"] == "provider_failure"
    assert result["pages"][0]["body"] == b'{"message":"refused"}'
    assert result["cubes"] == {}


# A response received across the next candle cannot pretend it arrived earlier.
def test_boundary_overrun_keeps_evidence_but_rejects_scoring():
    raw = json.dumps({"bars": {"ONE": [bar()]}}).encode()
    before, after = instant(minute=59), instant(hour=10, minute=0)
    result, _ = run([(200, raw)], clocks=[before, before, after])
    assert result["status"] == "observation_boundary_crossed"
    assert result["observation_clock"] is None
    assert result["pages"][0]["body"] == raw


# Clock rollback is an evidence defect rather than a stale but acceptable quote.
def test_receipt_rollback_is_rejected():
    now = instant()
    with pytest.raises(ValueError, match="backwards"):
        run([(200, b'{"bars":{}}')], clocks=[now, now, now - timedelta(seconds=1)])


# Keep corrupt successful responses attributable after parser failure as well.
def test_parser_failure_exposes_original_bytes_for_private_persistence():
    raw = b'{"bars":{"ONE":[{"t":"invalid"}]}}'
    with pytest.raises(prefix.CaptureError, match="Invalid isoformat") as failure:
        run([(200, raw)])
    assert failure.value.pages[0]["body"] == raw


# Do not map early-close or outside-session observations into normal-session heads.
@pytest.mark.parametrize(
    "when",
    [
        instant("2026-10-03"),
        instant(hour=9, minute=44),
        instant(hour=16, minute=0),
        instant("2026-11-27"),
    ],
)
def test_unsupported_observation_has_no_clock(when):
    assert prefix.observation_clock(when, str(when.date())) is None


# Use the final normal-session head only while its observed decision is still timely.
def test_terminal_clock_is_actual_1545_receipt():
    assert prefix.observation_clock(instant(hour=15, minute=45), "2026-10-05") == 24


# Attest provider units mechanically without fitting a price ratio or claiming parity.
def test_split_anchor_requires_exact_current_raw_equivalence():
    raw = json.dumps({"bars": {"ONE": [bar()]}}).encode()
    captured, _ = run([(200, raw)])
    adjusted = json.dumps(
        {
            "bars": {
                "ONE": [
                    bar("2026-10-02T19:45:00Z", c=5),
                    bar(),
                ]
            }
        }
    ).encode()
    requested = []

    # Inspect the provider adjustment while retaining the untouched original response.
    def transport(url, headers):
        requested.append(parse_qs(urlsplit(url).query))
        return 200, adjusted

    result = prefix.capture_split_anchors(
        captured,
        "2026-10-02",
        "2026-10-05",
        transport=transport,
        headers={},
        clock=instant,
    )
    assert requested[0]["adjustment"] == ["split"]
    assert result["anchors"] == {"ONE": 5}
    assert result["training_prior_source_matches"] is False
    assert result["pages"][0]["body"] == adjusted


# A provider correction or different unit must remain unknown rather than calibrated.
@pytest.mark.parametrize("change", [{"c": 100}, {"v": 200}, {"h": 12}])
def test_split_anchor_rejects_any_current_value_difference(change):
    captured, _ = run([(200, json.dumps({"bars": {"ONE": [bar()]}}).encode())])
    body = json.dumps(
        {
            "bars": {
                "ONE": [
                    bar("2026-10-02T19:45:00Z"),
                    bar(**change),
                ]
            }
        }
    ).encode()
    result = prefix.capture_split_anchors(
        captured,
        "2026-10-02",
        "2026-10-05",
        transport=lambda *_: (200, body),
        headers={},
        clock=instant,
    )
    assert result["anchors"] == {}


# A previous close is not synthesized when the expected final regular bar is absent.
def test_split_anchor_retains_missing_prior_and_missing_current():
    captured, _ = run([(200, json.dumps({"bars": {"ONE": []}}).encode())])
    body = json.dumps({"bars": {"ONE": [bar("2026-10-02T19:30:00Z")]}}).encode()
    result = prefix.capture_split_anchors(
        captured,
        "2026-10-02",
        "2026-10-05",
        transport=lambda *_: (200, body),
        headers={},
        clock=instant,
    )
    assert result["anchors"] == {}
