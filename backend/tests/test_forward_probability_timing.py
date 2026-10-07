"""Actual-clock CDF timing through the real private persisted paper sender."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import forward_probability_timing as forward
from backend.market import live_probability_timing as historical
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.probabilistic_execution import Distribution
from backend.market.replay_broker import ReplayBroker
from backend.tests.test_forward_entry_features import current, fixture
from backend.tests.test_forward_execution import fitted as fitted
from backend.tests.test_forward_execution import residual_archive as residual_archive
from backend.tests.test_forward_execution import residual_month, write
from backend.tests.test_live_probability_timing import (
    NOW,
    SESSION,
    SYMBOLS,
    broker,
    intent,
)

DECISION = NOW + timedelta(seconds=5)
SOURCE = {key: "a" * 64 for key in ("model_receipt", "residual_receipt", "observation")}


# A restarted process must recover exact dated residuals before computing forecasts.
def test_residual_publication_restores_original_samples(residual_archive, tmp_path):
    original = residual_month(residual_archive[1])
    folder = tmp_path / "residuals"
    digest = forward.write_residual_month(
        folder, original, clock=lambda: "2026-10-05T08:00:00-04:00"
    )
    restored = forward.load_residual_month(
        folder, receipt_sha256=digest, observed_at="2026-10-05T09:45:00-04:00"
    )
    assert set(restored.samples) == set(original.samples) == {"AAOI"}
    assert restored.receipt["stocks"] == original.receipt["stocks"]
    assert restored.receipt["preparation_receipt_sha256"] == original.receipt_sha256
    assert restored.receipt["identity"]["prepared_at"] == "2026-10-01T08:00:00-04:00"
    assert restored.receipt["identity"]["published_at"] == "2026-10-05T08:00:00-04:00"
    for name in ("day_indices", "clock_indices", "residuals", "weights"):
        before = getattr(original.samples["AAOI"], name)
        after = getattr(restored.samples["AAOI"], name)
        assert _hash(before) == _hash(after)
        np.testing.assert_array_equal(before, after)
        assert not after.flags.writeable
    assert folder.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in folder.iterdir())


# Reject altered evidence even when the caller supplies a new outer file hash.
@pytest.mark.parametrize("damage", ["receipt", "bytes", "field", "sample"])
def test_residual_restoration_rejects_changed_artifacts(
    residual_archive, tmp_path, damage
):
    folder = tmp_path / "residuals"
    digest = forward.write_residual_month(
        folder,
        residual_month(residual_archive[1]),
        clock=lambda: "2026-10-05T08:00:00-04:00",
    )
    receipt_path, array_path = folder / "residuals.json", folder / "residuals.npz"
    receipt = json.loads(receipt_path.read_bytes())
    if damage == "receipt":
        receipt_path.write_bytes(receipt_path.read_bytes() + b" ")
    elif damage == "bytes":
        array_path.write_bytes(array_path.read_bytes() + b"changed")
    else:
        with np.load(array_path, allow_pickle=False) as saved:
            arrays = {name: saved[name].copy() for name in saved.files}
        if damage == "field":
            arrays["unexpected"] = np.zeros(1)
        else:
            arrays["s0_residuals"][0] += 0.1
        np.savez_compressed(array_path, **arrays)
        receipt["identity"]["residual_artifact"]["sha256"] = sha256(
            array_path.read_bytes()
        ).hexdigest()
        receipt["identity_sha256"] = forward._digest(receipt["identity"])
        raw = json.dumps(receipt, sort_keys=True, allow_nan=False).encode()
        receipt_path.write_bytes(raw)
        digest = sha256(raw).hexdigest()
    reason = {
        "receipt": "publication bytes differ",
        "bytes": "array file bytes differ",
        "field": "archive fields required",
        "sample": "supported residual bytes",
    }[damage]
    with pytest.raises(ValueError, match=reason):
        forward.load_residual_month(
            folder, receipt_sha256=digest, observed_at="2026-10-05T09:45:00-04:00"
        )


# An unavailable or expired publication must never supply inference residuals.
@pytest.mark.parametrize(
    "observed", ["2026-10-05T07:59:59-04:00", "2026-11-02T09:45:00-05:00"]
)
def test_residual_restoration_enforces_actual_availability(
    residual_archive, tmp_path, observed
):
    folder = tmp_path / "residuals"
    digest = forward.write_residual_month(
        folder,
        residual_month(residual_archive[1]),
        clock=lambda: "2026-10-05T08:00:00-04:00",
    )
    with pytest.raises(ValueError, match="causal residual"):
        forward.load_residual_month(folder, receipt_sha256=digest, observed_at=observed)


# Failed publication clocks leave no receipt claiming usable residual evidence.
@pytest.mark.parametrize(
    "published", ["2026-10-01T07:59:59-04:00", "2026-11-02T08:00:00-05:00"]
)
def test_residual_publication_rejects_backdated_or_expired_clocks(
    residual_archive, tmp_path, published
):
    folder = tmp_path / "residuals"
    with pytest.raises(ValueError, match="causal residual"):
        forward.write_residual_month(
            folder, residual_month(residual_archive[1]), clock=lambda: published
        )
    assert not (folder / "residuals.json").exists()


# A retry must preserve the existing exclusive publication rather than replace it.
def test_residual_publication_preserves_existing_artifacts(residual_archive, tmp_path):
    folder = tmp_path / "residuals"
    original = residual_month(residual_archive[1])
    forward.write_residual_month(
        folder, original, clock=lambda: "2026-10-05T08:00:00-04:00"
    )
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    with pytest.raises(FileExistsError):
        forward.write_residual_month(
            folder, original, clock=lambda: "2026-10-05T09:00:00-04:00"
        )
    assert before == {path.name: path.read_bytes() for path in folder.iterdir()}
    assert "prepared_at" not in original.receipt["identity"]


# Supply independently published raw quotes and the original next-bar opening.
def snapshot(price=10):
    return {
        "quotes": {
            symbol: {
                "bid": price - 0.005,
                "ask": price + 0.005,
                "bid_size": 100,
                "ask_size": 100,
                "last": price,
                "open": 10,
                "bar": (NOW - timedelta(minutes=15)).isoformat(),
                "as_of": (DECISION - timedelta(seconds=1)).isoformat(),
                "received_at": DECISION.isoformat(),
                "feed": "iex",
                "basis": "raw_current_shares",
                "next_open": 10,
                "next_open_at": NOW.isoformat(),
                "next_open_published_at": (NOW + timedelta(seconds=1)).isoformat(),
            }
            for symbol in ("AAA", "BBB")
        }
    }


# Supply positive-risk empirical forecasts without acquiring market data or orders.
def forecasts(mean=-0.01):
    return {
        symbol: Distribution(mean, 0.0001, np.array([-1.0, 1.0]), np.array([1.0, 1.0]))
        if symbol in ("AAA", "BBB")
        else None
        for symbol in SYMBOLS
    }


# Run actual sender persistence with quote, forecast and account clocks kept separate.
def send(root, rows=None, *, mean=-0.01, quotes=None, client=None, captured=None):
    client = client or broker(now=DECISION - timedelta(seconds=1))
    account = captured or forward.capture_account(client, NOW, clock=lambda: DECISION)
    client.observe(DECISION, {"AAA": 10, "BBB": 10}, True)
    state = paper.PaperState()
    state.pending = deepcopy(rows or [intent()])
    for row in state.pending:
        row["timing_policy"] = historical.POLICY
    paper.save_state(root, state)
    quotes, trace = quotes or snapshot(), []
    reader = forward.build_reader(
        forecasts(mean),
        SYMBOLS,
        0,
        SESSION,
        DECISION,
        quotes,
        state.pending,
        account,
        10,
        trace,
        forecast_available_at=NOW + timedelta(seconds=2),
        source_identity=SOURCE,
    )
    lines = intraday_orders.send_due(
        root, quotes, DECISION, lambda: client, timing_reader=reader
    )
    return trace, paper.load_state(root), client, lines


# The actual acknowledgment retains the delayed receipt without claiming an execution.
def test_delayed_buy_persists_receipt_without_one_percent_gate(tmp_path):
    trace, state, client, lines = send(tmp_path)
    assert len(lines) == 1
    evidence = state.pending[0]["sent"]["forward_timing"]
    assert evidence["receipt_sha256"] == trace[0]["forward_receipt_sha256"]
    assert evidence["receipt"]["completed_at"] == NOW.isoformat()
    assert (
        evidence["receipt"]["forecast_available_at"]
        == (NOW + timedelta(seconds=2)).isoformat()
    )
    assert evidence["receipt"]["decided_at"] == DECISION.isoformat()
    assert evidence["receipt"]["midpoint_fill_proven"] is False
    assert evidence["trade_fraction"] == 0.05
    assert state.pending[0]["sent"]["qty"] == 5
    assert client.ledger()["holdings"] == {}


# Known price movement transports the opening target with opposite buy/sell directions.
@pytest.mark.parametrize(
    ("side", "price", "expected"),
    [
        ("buy", 10, "execute"),
        ("sell", 10, "wait"),
        ("buy", 10.3, "wait"),
        ("sell", 10.3, "execute"),
    ],
)
def test_observed_price_transport(tmp_path, side, price, expected):
    trace, state, _, _ = send(
        tmp_path,
        [intent(side=side)],
        quotes=snapshot(price),
        client=broker(holdings={"AAA": 10}, now=DECISION),
    )
    assert trace[0]["state"] == expected
    assert bool(state.pending[0].get("sent")) == (expected == "execute")


# Defective evidence remains unavailable instead of falling back to fixed-price timing.
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("as_of", (DECISION + timedelta(seconds=1)).isoformat()),
        ("received_at", (DECISION + timedelta(seconds=1)).isoformat()),
        ("next_open_published_at", (DECISION + timedelta(seconds=1)).isoformat()),
        ("next_open_at", DECISION.isoformat()),
        ("next_open", None),
        ("as_of", (NOW - timedelta(seconds=1)).isoformat()),
        ("basis", "adjusted"),
        ("bid", 9),
        ("last", 10.1),
    ],
)
def test_invalid_evidence_blocks_actual_sender(tmp_path, key, value):
    quotes = snapshot()
    quotes["quotes"]["AAA"][key] = value
    trace, state, client, lines = send(tmp_path, quotes=quotes)
    assert trace[0]["state"] == "unavailable"
    assert not state.pending[0].get("sent")
    assert client.attempt_history == ()
    assert lines == []


# No cash cannot be replaced by the hoped-for proceeds of a held position.
def test_zero_cash_preserves_pending(tmp_path):
    trace, state, client, _ = send(
        tmp_path, client=broker(0, holdings={"AAA": 10}, now=DECISION)
    )
    assert trace[0]["state"] == "no_trade"
    assert trace[0]["buying_power_budget"] == 0
    assert not state.pending[0].get("sent")
    assert client.ledger()["cash"] == 0


# Different current feed marks do not permit selling more shares than actually held.
def test_independent_marks_and_covered_sell(tmp_path):
    trace, state, _, _ = send(
        tmp_path,
        [intent(side="sell")],
        mean=0.01,
        client=broker(holdings={"AAA": 3}, now=DECISION),
        quotes=snapshot(10.01),
    )
    assert trace[0]["observed_qty"] == 3
    assert state.pending[0]["sent"]["qty"] == 3


# Concurrent funds, shares or impossible source clocks fail the actual GET boundary.
@pytest.mark.parametrize("field", ["cash", "shares", "future_clock"])
def test_concurrent_account_change_is_unavailable(field):
    client = broker(now=DECISION)
    account, positions, source_clock, calls = (
        client.account,
        client.positions,
        client.clock,
        [0],
    )

    # Alter only the second real account response to reproduce changing funds.
    def changed():
        calls[0] += 1
        value = account()
        return (
            replace(value, cash=value.cash + 1)
            if calls[0] == 2 and field == "cash"
            else value
        )

    # Reproduce a held-share change without changing either account valuation.
    def changed_positions():
        values = positions()
        if field == "shares" and calls[0] == 2:
            values = [
                type("Position", (), {"symbol": "AAA", "qty": 1, "current_price": 10})()
            ]
        return values

    # Reproduce a source clock that was not yet known when its response was captured.
    def changed_clock():
        value = source_clock()
        if field == "future_clock":
            value["timestamp"] = (DECISION + timedelta(seconds=1)).isoformat()
        return value

    client.account, client.positions, client.clock = (
        changed,
        changed_positions,
        changed_clock,
    )
    result = forward.capture_account(client, NOW, clock=lambda: DECISION)
    assert result["receipt"]["reason"]
    assert result["receipt"]["budget"] is None


# Receipt tampering cannot manufacture funds while retaining the captured identity.
def test_changed_receipt_rejected(tmp_path):
    captured = forward.capture_account(
        broker(now=DECISION), NOW, clock=lambda: DECISION
    )
    captured["receipt"]["budget"] += 1000
    with pytest.raises(ValueError, match="account receipt"):
        send(tmp_path, captured=captured)


# The original client identity prevents another submission on a repeated observation.
def test_repeated_sender_does_not_submit_twice(tmp_path):
    _, state, client, _ = send(tmp_path)
    captured = forward.capture_account(client, NOW, clock=lambda: DECISION)
    reader = forward.build_reader(
        forecasts(),
        SYMBOLS,
        0,
        SESSION,
        DECISION,
        snapshot(),
        state.pending,
        captured,
        10,
        [],
        forecast_available_at=NOW + timedelta(seconds=2),
        source_identity=SOURCE,
    )
    before = client.attempt_history
    assert (
        intraday_orders.send_due(
            tmp_path, snapshot(), DECISION, lambda: client, timing_reader=reader
        )
        == []
    )
    assert client.attempt_history == before


# Actual publication cannot precede the prefix, arrive in the future or expire.
@pytest.mark.parametrize(
    ("available", "decision"),
    [
        (NOW - timedelta(seconds=1), DECISION),
        (DECISION + timedelta(seconds=1), DECISION),
        (DECISION, NOW + timedelta(minutes=15)),
    ],
)
def test_impossible_or_expired_forecast_publication_rejected(available, decision):
    captured = forward.capture_account(
        broker(now=DECISION), NOW, clock=lambda: DECISION
    )
    with pytest.raises(ValueError, match="forecast publication"):
        forward.build_reader(
            forecasts(),
            SYMBOLS,
            0,
            SESSION,
            decision,
            snapshot(),
            [intent()],
            captured,
            10,
            [],
            forecast_available_at=available,
            source_identity=SOURCE,
        )


# Missing stock risk remains unavailable rather than inventing a tiny variance.
def test_missing_distribution_keeps_actual_order_pending(tmp_path):
    client = broker(now=DECISION)
    captured = forward.capture_account(client, NOW, clock=lambda: DECISION)
    supplied = forecasts()
    supplied["AAA"] = None
    state = paper.PaperState()
    state.pending = [intent()]
    state.pending[0]["timing_policy"] = historical.POLICY
    paper.save_state(tmp_path, state)
    trace = []
    reader = forward.build_reader(
        supplied,
        SYMBOLS,
        0,
        SESSION,
        DECISION,
        snapshot(),
        state.pending,
        captured,
        10,
        trace,
        forecast_available_at=DECISION,
        source_identity=SOURCE,
    )
    assert (
        intraday_orders.send_due(
            tmp_path, snapshot(), DECISION, lambda: client, timing_reader=reader
        )
        == []
    )
    assert trace[0]["state"] == "unavailable"
    assert not paper.load_state(tmp_path).pending[0].get("sent")
    assert client.attempt_history == ()


# The original historical reader still rejects observations after its exact boundary.
def test_historical_contract_unchanged():
    with pytest.raises(ValueError, match="exact current completed"):
        historical.build_reader(
            None,
            SYMBOLS,
            0,
            0,
            SESSION,
            DECISION,
            snapshot(),
            [intent()],
            broker(now=DECISION),
            10,
            [],
        )


# Supply a real observed prefix with the same three-stock cohort as the model archive.
def inference_inputs():
    inputs, clocks = current(fixture("2026-10-05"), 1, delay=1)
    panel, grades, eligible, records = inputs
    indices = [0, 2, 3]
    panel = SimpleNamespace(
        dates=panel.dates,
        tickers=("AAOI", "SPY", "QQQ"),
        adj_close=panel.adj_close[:, indices],
    )
    records = {"AAOI": records["AAA"], "SPY": records["SPY"], "QQQ": records["QQQ"]}
    return (panel, grades[:, indices], eligible[:, indices], records), clocks


# Publish fitted numeric heads and dated residuals for one actual observation.
def inferred(
    folder, fitted, residual_archive, *, inputs=None, available=None, stored=False
):
    digest = write(folder, fitted[1])
    inputs, clocks = inputs or inference_inputs()
    available = available or clocks["observed_at"] + timedelta(seconds=2)
    residuals = residual_month(residual_archive[1])
    if stored:
        residual_folder = folder.parent / "residuals"
        residual_digest = forward.write_residual_month(
            residual_folder, residuals, clock=lambda: "2026-10-05T08:00:00-04:00"
        )
        residuals = forward.load_residual_month(
            residual_folder,
            receipt_sha256=residual_digest,
            observed_at=clocks["observed_at"],
        )
    packet = forward.prepare_forecast(
        *inputs,
        **clocks,
        model_folder=folder,
        model_receipt_sha256=digest,
        residual_month=residuals,
        clock=lambda: available,
    )
    return packet, inputs, clocks


# Authenticate numeric inference, past residuals and post-inference availability.
def test_inferred_packet_matches_actual_numeric_head_and_past_residuals(
    fitted, residual_archive, tmp_path
):
    packet, inputs, clocks = inferred(tmp_path / "models", fitted, residual_archive)
    from backend.market import forward_execution as models
    from backend.market.forward_entry_features import observe

    frame = observe(*inputs, **clocks)
    heads, _ = models.load_publication(
        tmp_path / "models",
        receipt_sha256=packet.receipt["model_receipt"],
        observed_at=clocks["observed_at"],
    )
    moments = models.predict_moments(heads, frame["features"]).astype(np.float64)
    value = packet.distributions["AAOI"]
    assert value is not None
    assert value.mean == moments[0, 0]
    assert value.scale == np.sqrt(moments[1, 0] - moments[0, 0] ** 2)
    sample = residual_month(residual_archive[1]).samples["AAOI"]
    np.testing.assert_array_equal(value.residuals, sample.residuals)
    np.testing.assert_array_equal(value.weights, sample.weights)
    assert packet.distributions["SPY"] is None
    assert packet.distributions["QQQ"] is None
    assert not value.residuals.flags.writeable
    assert (
        packet.receipt["forecast_available_at"]
        == (clocks["observed_at"] + timedelta(seconds=2)).isoformat()
    )


# Preserve actual inferred evidence through the real private sender acknowledgment.
@pytest.mark.parametrize("stored", [False, True])
def test_real_inference_to_actual_persisted_sender(
    fitted, residual_archive, tmp_path, stored
):
    packet, _, clocks = inferred(
        tmp_path / "models", fitted, residual_archive, stored=stored
    )
    completed = clocks["observed_at"] - timedelta(seconds=1)
    now = completed + timedelta(seconds=6)
    client = ReplayBroker(10000, 0)
    client.observe(now - timedelta(seconds=1), {"AAOI": 100}, True)
    account = forward.capture_account(client, completed, clock=lambda: now)
    opening = packet.receipt["raw_session_openings"]["AAOI"]
    quotes = {
        "quotes": {
            "AAOI": {
                "bid": 99.995,
                "ask": 100.005,
                "bid_size": 100,
                "ask_size": 100,
                "last": 100,
                "open": opening,
                "feed": "iex",
                "basis": "raw_current_shares",
                "bar": (completed - timedelta(minutes=15)).isoformat(),
                "as_of": (now - timedelta(seconds=1)).isoformat(),
                "received_at": now.isoformat(),
                "next_open": 105,
                "next_open_at": completed.isoformat(),
                "next_open_published_at": (
                    completed + timedelta(seconds=1)
                ).isoformat(),
            }
        }
    }
    state = paper.PaperState()
    row = intent(symbol="AAOI", qty=5)
    row["execute_on"] = completed.date().isoformat()
    row["timing_policy"] = historical.POLICY
    state.pending = [row]
    paper.save_state(tmp_path / "paper", state)
    traces = []
    reader = forward.build_forecast_reader(
        packet,
        now,
        quotes,
        state.pending,
        account,
        10,
        traces,
        evidence_root=tmp_path / "paper",
    )
    client.observe(now, {"AAOI": 100}, True)
    assert (
        len(
            intraday_orders.send_due(
                tmp_path / "paper", quotes, now, lambda: client, timing_reader=reader
            )
        )
        == 1
    )
    sent = paper.load_state(tmp_path / "paper").pending[0]["sent"]
    assert sent["qty"] == 5
    reference = sent["forward_timing"]["receipt"]["inference"]
    raw = (tmp_path / "paper" / reference["path"]).read_bytes()
    assert json.loads(raw) == packet.receipt
    assert sha256(raw).hexdigest() == reference["sha256"] == packet.receipt_sha256
    assert (
        sent["forward_timing"]["receipt_sha256"] == traces[0]["forward_receipt_sha256"]
    )
    assert client.ledger()["holdings"] == {}


# Caller edits after inference cannot rewrite the observed inputs or resulting forecast.
def test_input_mutation_after_forecast_leaves_packet_unchanged(
    fitted, residual_archive, tmp_path
):
    packet, inputs, _ = inferred(tmp_path / "models", fitted, residual_archive)
    before = deepcopy(packet.receipt)
    inputs[0].adj_close[:] = 10000
    inputs[1][:] = -1
    inputs[3]["AAOI"]["close"][:] = 10000
    assert packet.receipt == before
    assert forward._digest(packet.receipt) == packet.receipt_sha256


# Modified inferred values or receipts cannot be swapped into an authenticated sender.
@pytest.mark.parametrize("defect", ["receipt", "distribution"])
def test_changed_inferred_packet_rejected_before_account_or_submission(
    fitted, residual_archive, tmp_path, defect
):
    packet, _, _ = inferred(tmp_path / "models", fitted, residual_archive)
    if defect == "receipt":
        packet.receipt["forecast_available_at"] = "2026-10-05T09:44:00-04:00"
    else:
        packet.distributions["AAOI"] = replace(packet.distributions["AAOI"], mean=-1)
    with pytest.raises(ValueError, match="inferred forecast"):
        forward.build_forecast_reader(
            packet, DECISION, {}, [], {}, 10, [], evidence_root=tmp_path
        )


# Actual compute completion cannot be backdated or used after its next-bar expiry.
@pytest.mark.parametrize("seconds", [-1, 900])
def test_inference_completion_clock_rejected(
    fitted, residual_archive, tmp_path, seconds
):
    inputs, clocks = inference_inputs()
    with pytest.raises(ValueError, match="forecast completion"):
        inferred(
            tmp_path / "models",
            fitted,
            residual_archive,
            inputs=(inputs, clocks),
            available=clocks["observed_at"] + timedelta(seconds=seconds),
        )


# Reusing an identical inference writes one artifact and never replaces corrupted bytes.
def test_inference_evidence_is_content_addressed_and_immutable(
    fitted, residual_archive, tmp_path
):
    packet, _, _ = inferred(tmp_path / "models", fitted, residual_archive)
    first = forward._store_inference(
        tmp_path / "evidence", packet.receipt, packet.receipt_sha256
    )
    path = tmp_path / "evidence" / first["path"]
    before = path.stat().st_mtime_ns
    assert (
        forward._store_inference(
            tmp_path / "evidence", packet.receipt, packet.receipt_sha256
        )
        == first
    )
    assert path.stat().st_mtime_ns == before
    assert len(list(path.parent.glob("*.json"))) == 1
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="immutable inference"):
        forward._store_inference(
            tmp_path / "evidence", packet.receipt, packet.receipt_sha256
        )
    assert path.read_bytes() == b"corrupt"
