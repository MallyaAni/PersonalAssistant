"""Only packet-envelope resource regressions; no acquisition or account replay."""

import pytest

from backend.market import historical_packet_parser as parser
from backend.market.historical_timing_packet import _digest
from backend.tests.test_historical_packet_demand import (
    VERIFIED,
    capture,
    declaration,
    demand,
    sha,
    source_registry,
)


# Retain a valid prior two-group source envelope for scaled resource-bound checks.
def envelope():
    reg = source_registry()
    manifest = declaration(reg)
    raw = demand.encoded(capture(reg, manifest))
    return reg, manifest, raw


# Reject over-cap retained bytes before any JSON, registry or base64 expansion.
def test_scaled_envelope_cap_precedes_every_decoder(monkeypatch):
    reg, manifest, raw = envelope()
    monkeypatch.setattr(parser, "MAX_CAPTURE_BYTES", len(raw) - 1, raising=False)
    calls = []

    # Make decoder reachability a failure rather than allocating an oversized object.
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Envelope decoded before resource admission")

    monkeypatch.setattr(parser.reg, "pinned", forbidden)
    packet = parser.Packets(raw, sha(raw), manifest.sha256, VERIFIED)
    with pytest.raises(ValueError, match="Packet envelope cap.*PAUSED"):
        parser.read(packet, manifest, reg)
    assert calls == []


# Accept the exact byte boundary without omitting held-name or trade groups.
def test_exact_cap_preserves_all_original_groups(monkeypatch):
    reg, manifest, raw = envelope()
    monkeypatch.setattr(parser, "MAX_CAPTURE_BYTES", len(raw), raising=False)
    packet = parser.packets(raw, sha(raw), manifest, reg, VERIFIED)
    result = parser.read(packet, manifest, reg)
    assert len(result["groups"]) == 2
    assert result["used"]["get_attempts"] == 3
    assert result["post_resolution_marks"] == "UNRESOLVED_NO_FRESH_MARK_SELECTION"
    assert _digest(capture(reg, manifest)) == sha(raw)


# Refuse an actual default-sized oversized envelope without expanding its JSON tree.
def test_default_envelope_bound_is_enforced_before_decode(monkeypatch):
    reg, manifest, raw = envelope()
    limit = getattr(parser, "MAX_CAPTURE_BYTES", 8 * 1024**2)
    assert limit == 8 * 1024**2
    padded = raw + b" " * (limit + 1 - len(raw))

    # Confirm that even whitespace padding cannot reach the old whole-envelope decoder.
    def forbidden(*args, **kwargs):
        raise AssertionError("Oversized JSON reached decoder")

    monkeypatch.setattr(parser.reg, "pinned", forbidden)
    packet = parser.Packets(padded, sha(padded), manifest.sha256, VERIFIED)
    with pytest.raises(ValueError, match="Packet envelope cap.*PAUSED"):
        parser.read(packet, manifest, reg)


# Preserve the existing pinned-byte failure for small tampered envelopes.
def test_within_cap_still_requires_original_envelope_hash():
    reg, manifest, raw = envelope()
    packet = parser.Packets(raw + b" ", sha(raw), manifest.sha256, VERIFIED)
    with pytest.raises(ValueError, match="Pinned original bytes differ"):
        parser.read(packet, manifest, reg)
