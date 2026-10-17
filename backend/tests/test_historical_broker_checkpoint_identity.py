"""Synthetic identity-only native fixtures; no original account or model reads."""

import hashlib
import json
import os
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.market import historical_broker_checkpoint as codec
from backend.market import replay_broker as native

CASES = []
N2_MAP = "99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab"
CURRENT_MAP = "bfbcb6ece4ea500726e00abbb06fc2c84d63d386bb307958016915357aaef5b3"


# Read only public source declarations, never installed selectors or account files.
def identities():
    path = Path("/fixture/identities.json")
    if path.stat().st_size > 32768:
        raise AssertionError("Public fixture declarations exceed their fixed cap")
    values = json.loads(path.read_bytes())
    assert set(values) == {"N2", "CURRENT"}
    assert codec._digest(values["N2"]["source_sha256"]) == N2_MAP
    assert codec._digest(values["CURRENT"]["source_sha256"]) == CURRENT_MAP
    return values


# Exercise one exact native image profile without substituting guarded source files.
class BrokerCheckpointIdentityTests(unittest.TestCase):
    # Keep absent exact native fixtures as explicit skips, never acceptance proof.
    def setUp(self):
        self.profile = os.environ.get("ANIOS_CODEC_PROFILE")
        if self.profile not in {"CURRENT", "N2"}:
            pytest.skip("Exact native profile fixture absent; skip is not proof")
        self.values = identities()
        self.identity = self.values[self.profile]
        self.pin = codec._digest(self.identity)

    # Restore all20 original synthetic state fields byte deterministically.
    def test_active_profile_roundtrip(self):
        broker = native.ReplayBroker(
            1000,
            10,
            initial_holdings={"MSFT": 2},
            initial_average_prices={"MSFT": 20},
        )
        broker.observe(
            "2019-03-01T14:45:31.200000+00:00", {"AAPL": 100, "MSFT": 20}, True
        )
        broker.submit_market("AAPL", 3, "buy", "SYNTHETIC-original-buy")
        broker.submit_market_on_close("MSFT", 1, "sell", "SYNTHETIC-original-sale")
        before = deepcopy(broker.__dict__)
        raw = codec.encode(broker, identity=self.identity, identity_sha256=self.pin)
        restored = codec.restore(
            raw,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            identity=self.identity,
            identity_sha256=self.pin,
        )
        assert type(restored) is native.ReplayBroker
        assert restored is not broker
        assert restored.__dict__ == before
        assert codec._pack(restored.__dict__) == codec._pack(before)
        assert (
            codec.encode(restored, identity=self.identity, identity_sha256=self.pin)
            == raw
        )
        assert broker.__dict__ == before
        assert set(before) == codec.FIELDS
        CASES.append(
            {
                "kind": "SYNTHETIC_EXACT_NATIVE_PROFILE_ROUNDTRIP",
                "profile": self.profile,
                "identity_sha256": self.pin,
                "state_fields": sorted(before),
                "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
                "cash": before["_cash"],
                "held": before["_held"],
                "cost_bps": before["cost_bps"],
                "orders": deepcopy(before["_orders"]),
            }
        )

    # Reject each mixed exact tuple before attempting any actual source-file access.
    def test_mixed_profile_members_before_source_access(self):
        fields = (
            "source_revision",
            "backend_image",
            "holding_config_sha256",
            "holding_release_sha256",
            "source_sha256",
        )
        for selected, original in self.values.items():
            other = self.values["N2" if selected == "CURRENT" else "CURRENT"]
            for name in fields:
                with self.subTest(profile=selected, field=name):
                    changed = deepcopy(original)
                    changed[name] = deepcopy(other[name])
                    with (
                        patch.object(
                            Path,
                            "stat",
                            side_effect=AssertionError(
                                "Actual source accessed before exact profile admission"
                            ),
                        ),
                        pytest.raises(
                            ValueError, match="identity|source|chain|profile"
                        ),
                    ):
                        codec._identity(changed, codec._digest(changed))

    # Refuse unknown profile and broker/calendar/timing pins before reads.
    def test_unknown_identity_members_before_source_access(self):
        for name, replacement in (
            ("source_revision", "0" * 40),
            ("backend_image", "sha256:" + "0" * 64),
            ("broker_sha256", "0" * 64),
            ("calendar_sha256", "0" * 64),
            ("timing_config_sha256", "0" * 64),
        ):
            changed = {**deepcopy(self.identity), name: replacement}
            message = "Frozen N2" if name == "source_revision" else "identity|source"
            with (
                self.subTest(field=name),
                patch.object(
                    Path,
                    "stat",
                    side_effect=AssertionError("Premature actual source read"),
                ),
                pytest.raises(ValueError, match=message),
            ):
                codec._identity(changed, codec._digest(changed))

    # A same-count source replacement cannot stand in for either exact reviewed31 map.
    def test_count_preserving_and_corrupt_source_maps_before_reads(self):
        for original in self.values.values():
            for mode in ("replace", "digest", "missing", "extra"):
                changed = deepcopy(original)
                sources = changed["source_sha256"]
                name = next(iter(sources))
                if mode == "replace":
                    sources["backend/market/unreviewed.py"] = sources.pop(name)
                elif mode == "digest":
                    sources[name] = "0" * 64
                elif mode == "missing":
                    sources.pop(name)
                else:
                    sources["backend/market/unreviewed.py"] = "0" * 64
                with (
                    self.subTest(mode=mode),
                    patch.object(
                        Path,
                        "stat",
                        side_effect=AssertionError("Premature actual source read"),
                    ),
                    pytest.raises(ValueError, match="identity|source|chain|profile"),
                ):
                    codec._identity(changed, codec._digest(changed))

    # Rehashing a changed checkpoint header cannot retag a snapshot to another profile.
    def test_cross_profile_checkpoint_header_rejected(self):
        raw = codec.encode(
            native.ReplayBroker(1000, 10),
            identity=self.identity,
            identity_sha256=self.pin,
        )
        data = json.loads(raw)
        other = self.values["N2" if self.profile == "CURRENT" else "CURRENT"]
        data["identity"] = other
        data["identity_sha256"] = codec._digest(other)
        changed = json.dumps(data, allow_nan=False, separators=(",", ":")).encode()
        with pytest.raises(ValueError, match="header differs"):
            codec.restore(
                changed,
                expected_sha256=hashlib.sha256(changed).hexdigest(),
                identity=self.identity,
                identity_sha256=self.pin,
            )

    # Caller identity bytes still require their external digest before any file access.
    def test_external_identity_pin_rejected_before_source_reads(self):
        with (
            patch.object(
                Path, "stat", side_effect=AssertionError("Premature source read")
            ),
            pytest.raises(ValueError, match="Externally pinned"),
        ):
            codec._identity(self.identity, "0" * 64)
