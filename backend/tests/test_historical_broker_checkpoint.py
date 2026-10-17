"""Private synthetic native checkpoints; no account/model/provider/archive reads."""

import hashlib
import io
import json
import os
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from backend.market import historical_broker_checkpoint as codec
from backend.market import replay_broker as native
from backend.market.alpaca_trading import AlpacaTradingError

NOW = "2019-03-01T14:45:31.200000+00:00"
END = "2019-03-01T14:45:33+00:00"
OPEN = "2019-03-01T14:30:00+00:00"
LATER = "2019-03-04T14:45:31.200000+00:00"
CASES = []


# Read the exact N2 declaration without requiring a private absolute mount.
def declared_identity():
    path = Path("/proof.json")
    if not path.is_file():
        path = (
            Path(codec.__file__).resolve().parents[2]
            / "docs/research"
            / "historical-numeric-merge-source-review-PROPOSED-2026-10-17.json"
        )
    proof = json.loads(path.read_bytes())
    assert codec._digest(proof["source_sha256"]) == (
        "99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab"
    )
    identity = {
        "source_revision": codec.N2,
        "backend_image": codec.IMAGE,
        "broker_sha256": codec.BROKER,
        "calendar_sha256": codec.CALENDAR,
        "source_sha256": proof["source_sha256"],
        **codec.CONFIGS,
    }
    return identity


# Native positives require the actual frozen files; skips outside them are not proof.
@pytest.fixture
def pins():
    identity = declared_identity()
    root = Path(native.__file__).resolve().parents[2]
    sources = {
        **identity["source_sha256"],
        "backend/market/replay_broker.py": codec.BROKER,
        "backend/market/calendar.py": codec.CALENDAR,
    }
    different = [
        name
        for name, expected in sources.items()
        if not (root / name).is_file()
        or hashlib.sha256((root / name).read_bytes()).hexdigest() != expected
    ]
    if different and os.environ.get("ANIOS_VERIFY_FROZEN_N2") != "1":
        pytest.skip(
            "Frozen N2 native runtime absent; retained native9b8561d1 is separate"
        )
    assert not different, "Explicit native N2 fixture source differs"
    return {"identity": identity, "identity_sha256": codec._digest(identity)}


# Always exercise rejection of changed actual files, including outside the frozen image.
def test_nonmatching_actual_source_is_rejected(tmp_path, monkeypatch):
    identity = declared_identity()
    name = next(iter(identity["source_sha256"]))
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"SYNTHETIC_WRONG_SOURCE")
    monkeypatch.setattr(
        native, "__file__", str(tmp_path / "backend/market/replay_broker.py")
    )
    with pytest.raises(ValueError, match="Actual frozen source bytes differ"):
        codec._identity(identity, codec._digest(identity))


# Hash original immutable checkpoint bytes without normalizing their ordered contents.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Build only synthetic native cash, holdings and reviewed observation clocks.
def broker(cash=1000, held=None):
    held = held or {}
    value = native.ReplayBroker(
        cash,
        10,
        initial_holdings=held,
        initial_average_prices={name: 10 for name in held},
    )
    value.observe(NOW, {"AAPL": 100, "MSFT": 20, "GOOG": 30}, True)
    return value


# Assert byte-deterministic reconstruction, exact state types and no source mutation.
def roundtrip(client, pins):
    before = deepcopy(client.__dict__)
    raw = codec.encode(client, **pins)
    restored = codec.restore(raw, expected_sha256=sha(raw), **pins)
    assert type(restored) is native.ReplayBroker
    assert restored is not client
    assert restored.__dict__ == before
    assert codec._pack(restored.__dict__) == codec._pack(before)
    assert codec.encode(restored, **pins) == raw
    assert client.__dict__ == before
    return restored, raw


# Retain independent Decimal expectations alongside actual native synthetic ledgers.
def ledger(client, *, cash, held, basis):
    assert client._cash == pytest.approx(float(Decimal(cash)), rel=0, abs=1e-10)
    assert client._held == held
    assert client._average == basis
    CASES.append(
        {
            "cash": client._cash,
            "expected_cash_decimal": cash,
            "held": deepcopy(held),
            "basis": deepcopy(basis),
            "observed_at": client._observed_at.isoformat(),
            "now": client._now.isoformat(),
        }
    )


# Preserve unobserved, WAIT and stale-after-resolution domains without refreshing NAV.
@pytest.mark.parametrize("mode", ["unobserved", "wait", "stale", "missing_mark"])
def test_clock_domains_roundtrip_without_observe(mode, pins):
    value = (
        native.ReplayBroker(1000, 10)
        if mode == "unobserved"
        else broker(held={"AAPL": 1})
    )
    if mode == "stale":
        value.flush(END, {})
    if mode == "missing_mark":
        value.observe(NOW, {"AAPL": None}, True)
    restored, raw = roundtrip(value, pins)
    assert (
        codec.read(io.BytesIO(raw), expected_sha256=sha(raw), **pins).__dict__
        == restored.__dict__
    )
    if mode in {"unobserved", "stale", "missing_mark"}:
        with pytest.raises(AlpacaTradingError):
            restored.account()
    else:
        assert restored.account().equity == 1100
    assert restored._attempts == []
    assert restored._fills == []


# Continue FIFO orders once, retaining reservations and duplicate-CID behavior.
def test_partial_reserved_fifo_continuation_and_duplicate_cid(pins):
    value = broker(held={"MSFT": 2})
    value.submit_market("AAPL", 8, "buy", "z-first")
    value.submit_market("MSFT", 2, "sell", "a-second")
    value.submit_market_on_close("GOOG", 3, "buy", "later-close")
    restored, _ = roundtrip(value, pins)
    assert list(restored._orders) == ["z-first", "a-second", "later-close"]
    assert restored._orders["later-close"]["reserved_cash"] == pytest.approx(90.09)
    for client in (value, restored):
        original = client.submit_market("AAPL", 8, "buy", "z-first")
        assert original["qty"] == "8"
        assert len(client._attempts) == 3
        before = deepcopy(client.__dict__)
        with pytest.raises(AlpacaTradingError, match="Conflicting duplicate"):
            client.submit_market("AAPL", 9, "buy", "z-first")
        assert client.__dict__ == before
        client.flush(END, {"AAPL": 200, "MSFT": 50})
        # Prebatch1000 less90.09 reserve =>4 buys;100 sale cannot fund a fifth.
        ledger(client, cash="299.1", held={"AAPL": 4}, basis={"AAPL": 200.0})
        assert client._fills[0]["fee"] == 0.8
        assert client._orders["z-first"]["status"] == "expired"
        assert client._orders["z-first"]["filled_qty"] == "4"
        assert client._orders["later-close"]["status"] == "accepted"
        with pytest.raises(AlpacaTradingError, match="Fresh observed account"):
            client.account()
        client.observe(LATER, {"AAPL": 200, "GOOG": 30}, True)
        assert client.account().buying_power == pytest.approx(209.01)
    assert value.__dict__ == restored.__dict__
    roundtrip(restored, pins)


# Preserve each filled, missing, cash-zero and canceled receipt variant exactly.
@pytest.mark.parametrize("mode", ["filled", "missing", "cash_zero", "canceled"])
def test_terminal_order_variants(mode, pins):
    value = broker()
    value.submit_market("AAPL", 2, "buy", "one")
    if mode == "canceled":
        value.cancel_orders(["one"])
    else:
        value.flush(
            END,
            {} if mode == "missing" else {"AAPL": 2000 if mode == "cash_zero" else 100},
        )
    restored, _ = roundtrip(value, pins)
    expected = (
        "canceled"
        if mode == "canceled"
        else "filled"
        if mode == "filled"
        else "expired"
    )
    assert restored._orders["one"]["status"] == expected
    ledger(
        restored,
        cash="799.8" if mode == "filled" else "1000",
        held={"AAPL": 2} if mode == "filled" else {},
        basis={"AAPL": 100.0} if mode == "filled" else {},
    )


# Preserve delayed auction scheduling and exact calendar-phase continuation.
@pytest.mark.parametrize(
    ("phase", "clock"),
    [("open", "2019-03-04T14:30:00+00:00"), ("close", "2019-03-01T21:00:00+00:00")],
)
def test_auction_continuation(phase, clock, pins):
    value = broker()
    if phase == "open":
        value.observe("2019-03-01T21:01:00+00:00", {"AAPL": 100}, False)
    method = (
        value.submit_market_on_open if phase == "open" else value.submit_market_on_close
    )
    method("AAPL", 1, "buy", "auction")
    restored, _ = roundtrip(value, pins)
    for client in (value, restored):
        client.flush(clock, {"AAPL": 101}, phase=phase)
        ledger(client, cash="898.899", held={"AAPL": 1}, basis={"AAPL": 101.0})
    assert value.__dict__ == restored.__dict__
    roundtrip(restored, pins)


# Generate native corporate-action records rather than hand-writing receipt variants.
def corporate(kind):
    value = broker(held={"AAPL": 5, "MSFT": 3})
    if kind == "split":
        value.apply_split("AAPL", 0.5, OPEN)
    elif kind == "dividend":
        value.accrue_dividend("AAPL", 0.5, OPEN, pay_at=LATER)
        value.accrue_dividend("MSFT", 1, OPEN)
    elif kind == "consolidation":
        value.apply_share_consolidation(
            "AAPL", 1, 2, OPEN, fractional_policy="cash_in_lieu_unknown"
        )
    elif kind.startswith("distribution"):
        unknown = kind == "distribution_unknown"
        value.apply_stock_distribution(
            "AAPL",
            "MSFT",
            1,
            2,
            OPEN,
            parent_basis_fraction=None if unknown else 0.6,
            basis_policy="unallocated_at_effective_clock" if unknown else None,
        )
    elif kind.startswith("exchange"):
        cash = kind == "exchange_cash"
        value.apply_security_exchange(
            "AAPL",
            1,
            2,
            OPEN,
            old_security_id="synthetic-old",
            new_security_id="synthetic-new",
            fractional_policy="cash_in_lieu_unknown"
            if cash
            else "floor_no_compensation",
            election_policy="declared_no_election_default_shares" if cash else None,
        )
    else:
        value.apply_cash_merger(
            "AAPL",
            50,
            OPEN,
            old_security_id="synthetic-old",
            election_policy="declared_no_election_default_cash",
        )
    return value


# Preserve fractional claims, security receipts and unallocated bases.
@pytest.mark.parametrize(
    "kind",
    [
        "split",
        "dividend",
        "consolidation",
        "distribution_known",
        "distribution_unknown",
        "exchange_floor",
        "exchange_cash",
        "merger",
    ],
)
def test_native_corporate_variants_and_future_continuation(kind, pins):
    value = corporate(kind)
    restored, _ = roundtrip(value, pins)
    for client in (value, restored):
        client.observe(LATER, {"AAPL": 100, "MSFT": 20}, True)
        if kind == "consolidation":
            client.settle_consolidation_cash("AAPL", OPEN, 7, LATER)
        elif kind.startswith("distribution"):
            client.settle_distribution_cash("AAPL", "MSFT", OPEN, 7, LATER)
        elif kind == "exchange_cash":
            client.settle_exchange_cash("AAPL", OPEN, 7, LATER)
        elif kind == "merger":
            client.settle_merger_cash("AAPL", OPEN, 250, LATER)
            with pytest.raises(AlpacaTradingError, match="terminated_security"):
                client.submit_market("AAPL", 1, "buy", "dead")
    assert value.__dict__ == restored.__dict__
    again, _ = roundtrip(restored, pins)
    expected = (
        "1002.5"
        if kind == "dividend"
        else "1250"
        if kind == "merger"
        else "1007"
        if kind
        in {
            "consolidation",
            "distribution_known",
            "distribution_unknown",
            "exchange_cash",
        }
        else "1000"
    )
    ledger(
        again, cash=expected, held=deepcopy(value._held), basis=deepcopy(value._average)
    )
    if kind == "split":
        assert again._held["AAPL"] == 2.5
        assert again._average["AAPL"] == 20
    if kind == "dividend":
        assert again._dividends[1]["paid"] is False
        assert again.account().equity == 1565.5
    if kind == "distribution_unknown":
        assert again._average == {"AAPL": None, "MSFT": None}


# Unknown cash fractions retain the native account guard.
def test_unknown_claim_and_fractional_sell_survive_restore(pins):
    unknown = corporate("consolidation")
    restored, _ = roundtrip(unknown, pins)
    with pytest.raises(AlpacaTradingError, match="cash"):
        restored.account()
    value = corporate("split")
    value.submit_market("AAPL", 2, "sell", "floor-covered")
    clone, _ = roundtrip(value, pins)
    clone.flush(END, {"AAPL": 100})
    ledger(
        clone,
        cash="1199.8",
        held={"AAPL": 0.5, "MSFT": 3.0},
        basis={"AAPL": 20.0, "MSFT": 10.0},
    )
    roundtrip(clone, pins)


# Native underflow preserves zero basis distinctly from unallocated basis.
def test_zero_and_unknown_basis_types_preserved(pins):
    value = native.ReplayBroker(
        1000, 10, initial_holdings={"AAPL": 2}, initial_average_prices={"AAPL": 5e-324}
    )
    value.observe(NOW, {"AAPL": 100}, True)
    value.apply_stock_distribution(
        "AAPL", "MSFT", 1, 2, OPEN, parent_basis_fraction=0.5
    )
    assert value._average["AAPL"] == 0.0
    clone, _ = roundtrip(value, pins)
    assert clone._average["AAPL"] == 0.0
    assert type(clone._average["AAPL"]) is float


# Preserve original explicit refusals without manufacturing an order or modifying cash.
def test_refused_attempts_and_repeated_failed_cids(pins):
    value = broker()
    for side in ("buy", "buy", "sell"):
        with pytest.raises(AlpacaTradingError):
            value.submit_market("AAPL", 20, side, "repeated-refused")
    clone, _ = roundtrip(value, pins)
    assert len(clone._attempts) == 3
    assert clone._orders == {}
    assert clone._cash == 1000


# Encode malicious state in an otherwise genuine externally SHA-pinned envelope.
def tampered(client, pins, change):
    raw = codec.encode(client, **pins)
    data = json.loads(raw)
    state = codec._unpack(data["state"])
    change(state)
    data["state"] = codec._pack(state)
    return json.dumps(data, separators=(",", ":"), allow_nan=False).encode()


# Reject corruption even when an external caller pins the corrupted snapshot bytes.
@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("_cash",), True),
        (("cost_bps",), 9.0),
        (("_market_open",), 1),
        (("_orders", "one", "qty"), "2"),
        (("_orders", "one", "execute_on"), "2019-03-04"),
        (("_orders", "one", "execution_phase"), "open"),
        (("_attempts", 0, "qty"), 1.0),
        (("_attempts", 0, "accepted"), 1),
        (("_orders", "one", "reserved_cash"), 0),
        (("_held", "AAPL"), -1),
        (("_average", "AAPL"), False),
    ],
)
def test_corrupt_state_rejected_before_native_construction(
    path, value, pins, monkeypatch
):
    client = broker(held={"AAPL": 1})
    client.submit_market("AAPL", 1, "buy", "one")

    # Change one native field while retaining external identity pins.
    def change(state):
        row = state
        for key in path[:-1]:
            row = row[key]
        row[path[-1]] = value

    raw = tampered(client, pins, change)

    # Construction must be unreachable for malformed state.
    def forbidden(*args, **kwargs):
        raise AssertionError("Constructed native broker before validation")

    monkeypatch.setattr(native, "ReplayBroker", forbidden)
    with pytest.raises(ValueError, match="."):
        codec.restore(raw, expected_sha256=sha(raw), **pins)


# Reject duplicate maps, missing fields and arbitrary restoration tags.
@pytest.mark.parametrize(
    "mode", ["duplicate", "extra", "missing", "object", "nonfinite", "duplicate_json"]
)
def test_shape_and_json_corruption(mode, pins):
    raw = codec.encode(broker(), **pins)
    data = json.loads(raw)
    pairs = data["state"]["map"]
    if mode == "duplicate":
        pairs.append(deepcopy(pairs[0]))
    elif mode == "extra":
        pairs.append(["_credential", "forbidden"])
    elif mode == "missing":
        pairs.pop()
    elif mode == "object":
        data["state"] = {"python_class": "ReplayBroker"}
    raw = json.dumps(data, separators=(",", ":")).encode()
    if mode == "nonfinite":
        raw = raw.replace(
            b'"private_synthetic_only":true', b'"private_synthetic_only":NaN'
        )
    if mode == "duplicate_json":
        raw = b'{"schema":"wrong",' + raw[1:]
    with pytest.raises(ValueError, match="."):
        codec.restore(raw, expected_sha256=sha(raw), **pins)


# Reject duplicate CIDs and forged fill arithmetic or clocks.
@pytest.mark.parametrize(
    "mode",
    [
        "duplicate_attempt",
        "duplicate_fill",
        "fee",
        "phase_clock",
        "zero_price",
        "claim_ratio",
        "claim_payment",
    ],
)
def test_receipt_and_claim_corruption(mode, pins):
    value = corporate("consolidation") if mode.startswith("claim") else broker()
    if not mode.startswith("claim"):
        value.submit_market("AAPL", 1, "buy", "one")
        value.flush(END, {} if mode == "zero_price" else {"AAPL": 100})

    # Corrupt saved receipts without invoking any economic replay.
    def change(state):
        if mode == "duplicate_attempt":
            state["_attempts"].append(deepcopy(state["_attempts"][0]))
        elif mode == "duplicate_fill":
            state["_fills"].append(deepcopy(state["_fills"][0]))
        elif mode == "fee":
            state["_fills"][0]["fee"] = 0
        elif mode == "phase_clock":
            state["_fills"][0]["at"] = OPEN
            state["_orders"]["one"]["filled_at"] = OPEN
        elif mode == "zero_price":
            state["_fills"][0]["price"] = 100
        elif mode == "claim_ratio":
            state["_share_consolidations"][0]["fractional_qty"] = 0.25
        else:
            state["_share_consolidations"][0]["cash_in_lieu"] = 7

    raw = tampered(value, pins, change)
    with pytest.raises(ValueError, match="."):
        codec.restore(raw, expected_sha256=sha(raw), **pins)


# Source, config, codec and original-byte pins must each fail closed independently.
@pytest.mark.parametrize("mode", ["snapshot", "config", "source", "codec", "caps"])
def test_external_identity_and_header_pins(mode, pins):
    raw = codec.encode(broker(), **pins)
    expected = sha(raw)
    if mode in {"config", "source"}:
        pins = deepcopy(pins)
        if mode == "config":
            pins["identity"]["holding_config_sha256"] = "0" * 64
        else:
            first = next(iter(pins["identity"]["source_sha256"]))
            pins["identity"]["source_sha256"][first] = "0" * 64
        pins["identity_sha256"] = codec._digest(pins["identity"])
    elif mode == "snapshot":
        expected = "0" * 64
    else:
        data = json.loads(raw)
        if mode == "codec":
            data["codec_sha256"] = "0" * 64
        else:
            data["caps"]["names"] = 256.0
        raw = json.dumps(data).encode()
        expected = sha(raw)
    with pytest.raises(ValueError, match="."):
        codec.restore(raw, expected_sha256=expected, **pins)


# Check scaled caps before decoding or native construction.
def test_bounded_raw_stream_and_record_admission(pins, monkeypatch):
    value = broker()
    raw = codec.encode(value, **pins)
    caps = {**codec.CAPS, "bytes": len(raw)}
    monkeypatch.setattr(codec, "CAPS", caps)
    # Exact-size bytes pass admission but the changed cap header must refuse.
    with pytest.raises(ValueError, match="header"):
        codec.restore(raw, expected_sha256=sha(raw), **pins)

    # Decoding must remain unreachable once the original bytes exceed the cap by one.
    def forbidden(*args, **kwargs):
        raise AssertionError("Decoded an over-cap checkpoint")

    monkeypatch.setattr(codec, "_decode", forbidden)
    with pytest.raises(codec.CheckpointPause):
        codec.restore(raw + b" ", expected_sha256="0" * 64, **pins)
    with pytest.raises(codec.CheckpointPause):
        codec.read(io.BytesIO(raw + b" "), expected_sha256="0" * 64, **pins)
    caps["orders"] = 0
    value.submit_market("AAPL", 1, "buy", "one")
    with pytest.raises(codec.CheckpointPause, match="record"):
        codec.encode(value, **pins)


# Reject record/depth/string expansion before packing or constructing a native clone.
def test_container_and_string_caps(pins, monkeypatch):
    caps = {**codec.CAPS, "attempts": 2, "string_chars": 32, "depth": 3}
    monkeypatch.setattr(codec, "CAPS", caps)
    with pytest.raises(codec.CheckpointPause, match="container"):
        codec._unpack({"list": [0, 0, 0]})
    with pytest.raises(codec.CheckpointPause, match="string"):
        codec._pack("x" * 33)
    with pytest.raises(codec.CheckpointPause, match="depth"):
        codec._pack([[[[[1]]]]])


# Reject impossible claim booleans, fractional merger quantities and null zero cost.
@pytest.mark.parametrize("mode", ["cash_bool", "fractional_merger", "null_zero_basis"])
def test_exact_native_claim_types(mode, pins):
    value = corporate("merger" if mode == "fractional_merger" else "exchange_floor")

    # Retain all native identities while corrupting one impossible claim value.
    def change(state):
        if mode == "cash_bool":
            state["_security_exchanges"][0]["cash_credit"] = False
        elif mode == "fractional_merger":
            state["_cash_mergers"][0]["quantity_before"] = 2.5
            state["_cash_mergers"][0]["amount"] = 125.0
        else:
            row = state["_security_exchanges"][0]
            row["quantity_before"] = 4.0
            row["quantity_after"] = 2
            row["forfeited_fraction"] = 0.0
            row["forfeited_basis"] = None

    raw = tampered(value, pins, change)
    with pytest.raises(ValueError, match="."):
        codec.restore(raw, expected_sha256=sha(raw), **pins)
