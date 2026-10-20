"""Synthetic CURRENT settlement Cycle; no genuine model, provider or account reads."""

import json
import multiprocessing
import os
import signal
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import entry_timing
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_conditional_cycle as cycle
from backend.market import historical_conditional_market as market
from backend.market import historical_packet_demand as demand
from backend.market import historical_session_completion as completion
from backend.market import historical_timing_packet as packet
from backend.market import probabilistic_execution as probability
from backend.market import replay_broker as native
from backend.market.historical_packet_store import Store, StorePause
from backend.tests import test_historical_conditional_market as generic
from backend.tests.test_historical_conditional_cycle import import_capture, intent

CASES = []


# Read only public source declarations, never installed accounts or model arrays.
def declarations():
    identity = json.loads(Path("/fixture/identities.json").read_bytes())["CURRENT"]
    pins = {"identity": identity, "identity_sha256": packet._digest(identity)}
    codec._identity(identity, pins["identity_sha256"])
    return pins, tuple(json.loads(Path("/fixture/cohort.json").read_bytes()))


# Construct one new synthetic account through the exact native and Store paths.
def build(
    folder,
    *,
    rows=None,
    held=None,
    mode="execute",
    final=False,
    reserve=False,
    absent=(),
    settle_current=True,
):
    pins, names = declarations()
    at = "2019-03-01T20:45:00Z" if final else "2019-03-01T14:45:00Z"
    ctx = (market.session_completion_context if final else market.context)(
        at, names, cohort_sha256=packet._digest(list(names))
    )
    prior = native._instant(packet.stamp(packet.nanos(at) - 60 * packet.NS))
    held = held or {}
    legs = deepcopy([intent("buy", 5)] if rows is None else rows)
    client = native.ReplayBroker(
        1000,
        10,
        initial_holdings=held,
        initial_average_prices={name: 100 for name in held},
    )
    required = set(held) | {row["symbol"] for row in legs} | {"GOOG"}
    client.observe(
        prior, {name: 100 for name in sorted(required)}, native._session(prior)[1]
    )
    if reserve:
        client.submit_market_on_close("GOOG", 1, "buy", "SYNTHETIC-reserved")
    store = Store(folder, pins["identity_sha256"], None, create=True)
    root = store.root / "working"
    paper.save_state(root, paper.PaperState(pending=legs))
    latch = entry_timing.latch_path(root, native._instant(at).date())
    latch.parent.mkdir(parents=True, exist_ok=True)
    latch.write_bytes(
        demand.encoded({"session": at[:10], "stocks": {}, "origin": "SYNTHETIC"})
    )
    registry = generic.mapping(
        (set(held) | {row["symbol"] for row in legs}) or {"AAPL"}
    )
    current = cycle.Cycle(
        store, client, root, pins=pins, context=ctx, settle_current=settle_current
    )
    manifest = current.begin(registry)
    captured = generic.capture(manifest, registry, absent=absent)
    import_capture(store, manifest, registry, captured)
    current.admit(manifest, registry, captured)
    distributions = None if final else {name: None for name in names}
    if not final:
        for row in legs:
            distributions[row["symbol"]] = (
                None
                if mode == "unavailable"
                else probability.Distribution(
                    0.02 if mode == "wait" else 0.0,
                    0.001,
                    np.array([-1.0, 1.0]) if mode == "wait" else np.array([0.0, 0.0]),
                    np.array([0.5, 0.5]),
                )
            )
    return {
        "cycle": current,
        "client": client,
        "store": store,
        "root": root,
        "pins": pins,
        "context": ctx,
        "manifest": manifest,
        "registry": registry,
        "captured": captured,
        "distributions": distributions,
        "anchors": generic.anchor_receipt(manifest, registry),
    }


# Reach native decisions only through the production Cycle entry point.
def run(value):
    return value["cycle"].run(
        value["manifest"],
        value["registry"],
        value["captured"],
        value["distributions"],
        anchors=value["anchors"],
    )


# Sample external authoritative commitments before calling the recovery API.
def recovery_pins(value, submission_head):
    state = value["store"].snapshot()
    return {
        "pins": value["pins"],
        "expected_head": state["head"],
        "expected_cycle": state["cycle"],
        "submission_head": submission_head,
        "context_sha256": value["context"].sha256,
        "demand_sha256": value["manifest"].sha256,
        "registry_sha256": value["registry"].sha256,
        "packet_sha256": value["captured"].sha256,
    }


# Fail structurally if recovery reaches any decision, sender or optional outcome replay.
def deny_decisions(monkeypatch, *, final_restore=False):
    # Preserve a visible failure rather than merely counting a forbidden invocation.
    def forbidden(*args, **kwargs):
        raise AssertionError("Recovery reached forbidden decision/submission work")

    for module, name in (
        (cycle.forward, "build_reader"),
        (cycle.forward, "capture_account"),
        (intraday_orders, "send_due"),
        (completion, "dispatch"),
        (cycle.Cycle, "begin"),
        (cycle.Cycle, "run"),
        (cycle.Cycle, "admit"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    if final_restore:
        monkeypatch.setattr(market.Resolver, "resolve", forbidden)
        monkeypatch.setattr(cycle.marks, "select", forbidden)
        monkeypatch.setattr(cycle._settlement_source(), "reconcile", forbidden)


# Restore final broker, paper and latch with their authenticated pre-fold reference.
def restored(value, result):
    destination = value["store"].root / "restored-final"
    clone, receipt = cycle.restore_receipt(
        value["store"], result["receipt_sha256"], destination, pins=value["pins"]
    )
    assert codec.encode(clone, **value["pins"]) == codec.encode(
        value["client"], **value["pins"]
    )
    assert (
        paper.state_path(destination).read_bytes()
        == paper.state_path(value["root"]).read_bytes()
    )
    assert (
        entry_timing.latch_path(destination, value["cycle"].day).read_bytes()
        == entry_timing.latch_path(value["root"], value["cycle"].day).read_bytes()
    )
    assert (
        receipt["paper_journal_reconciliation"]
        == "CURRENT_NATIVE_RECONCILIATION_FINAL_COMPONENTS"
    )
    assert (
        receipt["detail"]["native_reconciliation"]["durable_state_committed"] is False
    )
    CASES.append(
        {
            "origin": "SYNTHETIC_CURRENT_SETTLEMENT_CYCLE",
            "result": result,
            "paper": paper.load_state(destination).__dict__,
            "broker_checkpoint_utf8": codec.encode(clone, **value["pins"]).decode(),
            "receipt": receipt,
            "sizes": measurements(destination, clone, value["pins"]),
            "provider_or_genuine_model_calls": 0,
        }
    )


# Measure existing fixture snapshots without changing caps or financial state.
def measurements(root, client, pins):
    raw = paper.state_path(root).read_bytes()
    state = paper.load_state(root)
    return {
        "raw_paper_bytes": len(raw),
        "journal_rows": len(state.journal),
        "history_rows": len(state.history),
        "pending_rows": len(state.pending),
        "broker_bytes": len(codec.encode(client, **pins)),
    }


# Hold a real child immediately after native save or after final Store commit.
def crash_child(folder, connection, point):
    generic.shared_external.__wrapped__(pytest.MonkeyPatch())
    value = build(folder)
    counts = {"readers": 0, "sender": 0, "submissions": 0}
    codes = {
        cycle.forward.build_reader.__code__: "readers",
        intraday_orders.send_due.__code__: "sender",
        native.ReplayBroker._submit.__code__: "submissions",
    }

    # Observe original native functions without replacing their financial behavior.
    def profile(frame, event, arg):
        if event == "call" and frame.f_code in codes:
            counts[codes[frame.f_code]] += 1

    # Send external source/head pins and preserve the suspect working components.
    def fault(boundary):
        if boundary == point:
            state = value["store"].snapshot()
            operation = packet._digest(
                {"cycle": state["cycle"], "stage": "SUBMISSION_CAPTURED"}
            )
            submission = value["store"].recover_operation(operation)["sha256"]
            connection.send(
                {
                    "point": point,
                    "pins": recovery_pins(value, submission),
                    "counts": counts,
                    "working_paper": paper.state_path(value["root"]).read_bytes(),
                }
            )
            connection.recv()

    value["store"].fault = fault
    sys.setprofile(profile)
    run(value)
    raise AssertionError("Crash boundary was not reached")


# Keep absent native fixtures explicit and forbid every external acquisition boundary.
@pytest.fixture(autouse=True)
def fixture_scope(monkeypatch):
    if os.environ.get("ANIOS_CURRENT_SETTLEMENT_CYCLE_FIXTURE") != "1":
        pytest.skip("Exact CURRENT Cycle fixture absent; skip is not proof")
    generic.shared_external.__wrapped__(monkeypatch)


# Retain all fixture data while releasing only its exclusive Store lock afterward.
@pytest.fixture
def make(tmp_path):
    stores = []

    # Put every synthetic account under its own private output descendant.
    def create(**kwargs):
        value = build(tmp_path / str(len(stores)), **kwargs)
        stores.append(value["store"])
        return value

    yield create
    for store in stores:
        store.close()


# Default CURRENT keeps native sent/pending rows and its original no-settlement label.
def test_default_current_retains_pending_semantics(make):
    value = make(settle_current=False)
    result = run(value)
    state = paper.load_state(value["root"])
    assert state.journal == []
    assert state.pending[0]["sent"]["qty"] == 5
    receipt = cycle._read_receipt(
        value["store"], result["receipt_sha256"], value["pins"]
    )
    assert "current_settlement_sha256" not in receipt
    assert (
        receipt["paper_journal_reconciliation"]
        == "NOT_RUN_NATIVE_SENT_PENDING_RETAINED"
    )


# The durable prior mode cannot be changed before native decisions are evaluated.
def test_settlement_mode_cannot_change_before_native_decisions(make):
    value = make()
    value["cycle"].settle_current = False
    with pytest.raises(ValueError, match="Frozen optional settlement mode"):
        run(value)
    assert value["client"]._attempts == []
    assert paper.load_state(value["root"]).journal == []


# Model-timed cash partials retain separate quantities and the complete final graph.
def test_model_partial_and_complete_restore(make):
    value = make()
    result = run(value)
    row = paper.load_state(value["root"]).journal[0]
    assert (row["qty"], row["submitted_qty"], row["sender_qty"], row["filled_qty"]) == (
        5,
        5,
        5,
        4,
    )
    assert row["status"] == "partial"
    assert row["terminal"] is True
    assert value["client"]._cash == pytest.approx(199.2)
    restored(value, result)


# First-sale proceeds cannot increase the later BUY budget or hide capped desired8.
def test_sell_first_preserves_capped_domains_and_budget(make):
    sell, buy = intent("sell", 8), intent("buy", 5, 1)
    buy["symbol"] = "MSFT"
    value = make(rows=[sell, buy], held={"AAPL": 5, "NVDA": 2}, reserve=True)
    result = run(value)
    rows = {row["side"]: row for row in paper.load_state(value["root"]).journal}
    assert (
        rows["sell"]["qty"],
        rows["sell"]["submitted_qty"],
        rows["sell"]["sender_qty"],
        rows["sell"]["filled_qty"],
    ) == (8, 5, 5, 5)
    assert rows["sell"]["status"] == "partial"
    assert rows["buy"]["filled_qty"] == 4
    assert result["venue"]["initial_budget"] == pytest.approx(899.9)
    assert value["client"]._cash == pytest.approx(1198.15005)
    restored(value, result)


# Final dispatch and empty due sets never use numerical timing readers.
def test_final_native_and_empty_scopes(make, monkeypatch):
    # Make accidental numerical timing a failing boundary in the final phase.
    def forbidden(*args, **kwargs):
        raise AssertionError("Final dispatch reached numerical timing")

    monkeypatch.setattr(cycle.forward, "build_reader", forbidden)
    monkeypatch.setattr(cycle.forward, "capture_account", forbidden)
    for rows in ([intent("buy", 2)], []):
        value = make(final=True, rows=rows)
        result = run(value)
        assert result["classification"] == "NOT_MODEL_TIMED"
        assert len(paper.load_state(value["root"]).journal) == len(rows)
        restored(value, result)


# WAIT and unavailable marks preserve unsent pending instead of fabricating fills.
@pytest.mark.parametrize(
    ("mode", "absent", "held"),
    [("wait", (), {}), ("unavailable", (), {}), ("execute", ("NVDA",), {"NVDA": 2})],
)
def test_wait_or_missing_keeps_unsent_pending(make, mode, absent, held):
    value = make(mode=mode, absent=absent, held=held)
    result = run(value)
    state = paper.load_state(value["root"])
    assert result["factory_calls"] == 0
    assert state.journal == []
    assert not state.pending[0].get("sent")
    restored(value, result)


# An outer final skip cannot expire an unsent request or invent a native verdict.
def test_outer_final_skip_preserves_original_pending(make, monkeypatch):
    value = make(final=True, held={"NVDA": 2}, absent=("NVDA",))
    original = paper.load_state(value["root"]).pending

    # A failed preflight must remain outside the native dispatch boundary.
    def forbidden(*args, **kwargs):
        raise AssertionError("Outer skip invoked native dispatch")

    monkeypatch.setattr(completion, "dispatch", forbidden)
    result = run(value)
    assert result["factory_calls"] == 0
    assert result["verdicts"] == []
    assert paper.load_state(value["root"]).pending == original
    restored(value, result)


# A changed pre-fold object cannot be accepted under its original source commitment.
def test_corrupt_pre_settlement_reference_refused_before_save(make, monkeypatch):
    value = make()
    original = cycle.Cycle._retain

    # Corrupt the actual private CAS file without changing its committed digest.
    def changed(current, detail):
        reference = original(current, detail)
        if detail["stage"] == "PRE_SETTLEMENT_OUTCOME":
            (current.store.root / "blobs" / reference).write_bytes(b"SYNTHETIC-corrupt")
        return reference

    monkeypatch.setattr(cycle.Cycle, "_retain", changed)
    with pytest.raises(ValueError, match="Original blob bytes differ"):
        run(value)
    assert paper.load_state(value["root"]).journal == []
    assert value["store"].snapshot()["next_stage"] == "OUTCOME_COMMITTED"


# An incomplete resolver cannot turn accepted market requests into reconciled outcomes.
def test_unresolved_market_request_refuses_fold(make, monkeypatch):
    value = make()

    # Preserve the real accepted broker row while simulating no resolver completion.
    def unresolved(*args, **kwargs):
        return {"status": "SYNTHETIC_UNRESOLVED", "outcomes": []}

    monkeypatch.setattr(market.Resolver, "resolve", unresolved)
    with pytest.raises(ValueError, match="unresolved"):
        run(value)
    assert paper.load_state(value["root"]).journal == []
    assert value["store"].snapshot()["next_stage"] == "OUTCOME_COMMITTED"


# Recovery rejects every stale or substituted external commitment before root creation.
def test_recovery_refuses_substituted_external_inputs(make, monkeypatch):
    value = make()

    # Stop after the durable native submission without running any outcome tail.
    def stop(*args, **kwargs):
        raise StorePause("SYNTHETIC committed-submission stop")

    monkeypatch.setattr(cycle.Cycle, "_finish_outcome", stop)
    with pytest.raises(StorePause, match="SYNTHETIC"):
        run(value)
    head = value["store"].snapshot()["head"]
    pins = recovery_pins(value, head)
    for key in (
        "expected_head",
        "expected_cycle",
        "submission_head",
        "context_sha256",
        "demand_sha256",
        "registry_sha256",
        "packet_sha256",
    ):
        root = value["store"].root / ("refused-" + key)
        with pytest.raises(
            ValueError, match="authoritative|committed|paused|pinned|continuation"
        ):
            cycle.resume_current_outcome(
                value["store"], root, **{**pins, key: "0" * 64}
            )
        assert not root.exists()


# Real pre/postcommit SIGKILL recovery never repeats a model, reader or submission.
@pytest.mark.parametrize(
    "point", ["current_settlement_saved", "current_outcome_committed"]
)
def test_actual_sigkill_current_recovery(tmp_path, point, monkeypatch):
    baseline = build(tmp_path / "baseline")
    expected = run(baseline)
    expected_broker = codec.encode(baseline["client"], **baseline["pins"])
    expected_paper = paper.state_path(baseline["root"]).read_bytes()
    day = baseline["cycle"].day
    expected_latch = entry_timing.latch_path(baseline["root"], day).read_bytes()
    baseline["store"].close()
    context = multiprocessing.get_context("spawn")
    parent, remote = context.Pipe()
    folder = tmp_path / "crashed"
    child = context.Process(target=crash_child, args=(folder, remote, point))
    child.start()
    remote.close()
    assert parent.poll(30)
    observed = parent.recv()
    os.kill(child.pid, signal.SIGKILL)
    child.join(20)
    assert child.exitcode == -signal.SIGKILL
    assert observed["counts"] == {"readers": 1, "sender": 1, "submissions": 1}
    store = Store(
        folder,
        observed["pins"]["pins"]["identity_sha256"],
        observed["pins"]["expected_head"],
    )
    try:
        deny_decisions(monkeypatch, final_restore=point == "current_outcome_committed")
        fresh = store.root / "fresh-recovery"
        client, result = cycle.resume_current_outcome(store, fresh, **observed["pins"])
        assert codec.encode(client, **observed["pins"]["pins"]) == expected_broker
        assert paper.state_path(fresh).read_bytes() == expected_paper
        assert entry_timing.latch_path(fresh, day).read_bytes() == expected_latch
        assert result["receipt_sha256"] == expected["receipt_sha256"]
        assert (
            paper.state_path(store.root / "working").read_bytes()
            == observed["working_paper"]
        )
        CASES.append(
            {
                "origin": "SYNTHETIC_ACTUAL_SIGKILL_CURRENT_RECOVERY",
                "boundary": point,
                "child_exitcode": child.exitcode,
                "original_counts": observed["counts"],
                "result": result,
                "recovery_decision_or_sender_calls": 0,
                "restored_broker_sha256": cycle.sha(expected_broker),
                "sizes": measurements(fresh, client, observed["pins"]["pins"]),
            }
        )
    finally:
        store.close()
