"""Synthetic native lifecycle; no model, archive or provider calls."""

import os
from contextlib import closing
from dataclasses import asdict, replace
from datetime import UTC, datetime
from hashlib import sha256
from types import MappingProxyType, SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.market import grade_led_policy, learned_live_holding
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_conditional_market as market
from backend.market import historical_conditional_nightly as adapter
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.alpaca_trading import AlpacaTradingError
from backend.market.historical_packet_store import Store, StorePause
from backend.market.live_execution_inputs import (
    PassiveMarks,
    RawExecutionInputs,
    _freeze,
)
from backend.market.live_model_history import FrozenCurrentGradePolicy
from backend.market.live_model_history_audit_inputs import readonly
from backend.tests.test_joint_funded_policy import report

COHORT = ("AAA", "BBB", "SPY", "QQQ", *("S" + str(i) for i in range(92)))


# Admit the exact native CURRENT files; absence is a failed test environment, no skip.
@pytest.fixture
def pins():
    assert os.environ.get("ANIOS_CONDITIONAL_NIGHTLY_FIXTURE") == "1"
    source = learned_live_holding.source_identity()
    identity = {
        "source_revision": adapter.admitted.CURRENT_SOURCE,
        "backend_image": adapter.admitted.CURRENT_IMAGE,
        "broker_sha256": codec.BROKER,
        "calendar_sha256": codec.CALENDAR,
        "source_sha256": source,
        "holding_config_sha256": adapter.admitted.CURRENT_CONFIG,
        "holding_release_sha256": adapter.admitted.CURRENT_RELEASE,
        "timing_config_sha256": codec.CONFIGS["timing_config_sha256"],
    }
    value = {"identity": identity, "identity_sha256": packet._digest(identity)}
    codec._identity(**dict(identity=identity, expected_sha256=value["identity_sha256"]))
    return value


# Supply declared synthetic scenarios while retaining the actual native grade allocator.
def policy_fixture():
    reader = SimpleNamespace(
        dates=np.array(
            ["2019-02-28", "2019-03-01", "2019-03-04"], dtype="datetime64[D]"
        ),
        symbols=("AAA", "BBB", "SPY", "QQQ"),
    )

    # Use a fixed negative risk fixture, never a loaded head or a saved model target.
    def distribution(day, symbols):
        return SimpleNamespace(
            scenarios=np.full((2, len(symbols)), -0.02),
            probabilities=np.array([0.5, 0.5]),
            receipt={"status": "available", "synthetic": True},
        )

    # Check the explicit private close clock without pretending to load real features.
    def validate_clock(at):
        assert at.isoformat() == "2019-02-28T21:01:00+00:00"

    reader.distribution, reader.validate_clock = distribution, validate_clock
    policy = object.__new__(FrozenCurrentGradePolicy)
    policy.reader, policy.cost_bps = reader, 10
    policy.identity = {
        "policy": grade_led_policy.POLICY,
        "cost_bps": 10,
        "synthetic": True,
    }
    return policy, report(reader, day=0, grades=(3, 2))


# Isolate lifecycle tests from restoration and label their input as synthetic.
@pytest.fixture
def controlled_context(monkeypatch):
    value = object.__new__(adapter.HoldingContext)
    raw = SimpleNamespace(
        dates=np.array(["2019-02-28"], dtype="datetime64[D]"),
        tickers=COHORT,
        daily_close=np.full((1, 96), 100.0),
        actions={},
        inherited_actions={},
        passive=None,
    )
    provenance = adapter.admitted.encoded(
        {
            "schema": "SYNTHETIC_NIGHTLY_CONTEXT_NOT_MODEL_ADMISSION",
            "symbols": list(COHORT),
            "source": adapter.admitted.CURRENT_SOURCE,
        }
    )
    for name, content in {
        "approval": None,
        "panel": SimpleNamespace(dates=raw.dates),
        "raw": raw,
        "reader": None,
        "provenance": provenance,
    }.items():
        object.__setattr__(value, name, content)

    # Replace real-data admission only for this synthetic test capability.
    def validate(self):
        assert self is value
        return adapter.admitted.decoded(self.provenance)

    # Return the real native policy over declared synthetic distribution inputs.
    def select(self, session):
        assert self is value
        assert session == "2019-02-28"
        policy, shown = policy_fixture()
        return shown, policy, 0

    monkeypatch.setattr(adapter.HoldingContext, "validate", validate)
    monkeypatch.setattr(adapter.HoldingContext, "select", select)
    return value


# Open exactly one private Store and separate standalone descendant per test.
@pytest.fixture
def nightly(tmp_path, pins):
    with closing(
        Store(tmp_path / "store", pins["identity_sha256"], None, create=True)
    ) as store:
        yield adapter.Nightly(
            store, store.root / "nightly", pins=pins, expected_head=None, create=True
        )


# Birth and completed recovery preserve exact original references without rerunning it.
def test_birth_zero_state_recovery_and_marker_lineage(
    nightly, controlled_context, monkeypatch
):
    broker, reference = nightly.initialize(controlled_context)
    original = nightly.read_birth(reference)
    raw = adapter.physical(paper.state_path(nightly.root))
    assert broker._cash == 100000
    assert broker._held == {}
    assert not broker.attempt_history
    assert original["raw_initial_submissions"] == []
    assert nightly.store.snapshot()["head"] is None

    # Any second birth effect would be a defect; retained completion must be read only.
    def forbidden(*args, **kwargs):
        raise AssertionError("Completed birth re-executed")

    monkeypatch.setattr(native.ReplayBroker, "__init__", forbidden)
    assert nightly.initialize(controlled_context) == (None, reference)
    assert adapter.physical(paper.state_path(nightly.root)) == raw
    changed = dict(original, initial_cash=99999)
    fake = adapter.put(nightly.store, adapter.admitted.encoded(changed))
    with pytest.raises(ValueError, match="lineage"):
        nightly.read_birth(fake)


# A durable reservation without its final marker pauses, rather than repeating effects.
def test_interrupted_birth_never_adopts_or_reruns(nightly, controlled_context):
    digest = sha256(controlled_context.provenance).hexdigest()
    nightly.reserve("BIRTH", "2019-02-28", digest, None, None)
    with pytest.raises(StorePause, match="never re-execute"):
        nightly.initialize(controlled_context)
    assert not paper.state_path(nightly.root).exists()


# Actual native planning runs once; synthetic negative risk creates no buy.
def test_native_prior_close_reuses_zero_proposal_and_original_state(
    nightly, controlled_context
):
    broker, birth = nightly.initialize(controlled_context)
    result = nightly.close(
        controlled_context, broker, "2019-02-28", birth=birth, previous=birth
    )
    receipt = nightly.read_original(result)
    state = paper.load_state(nightly.root)
    assert receipt["status"] == "NATIVE_NIGHTLY_RETURNED"
    assert receipt["holding_policy_calls"] == 1
    assert receipt["native_capture"]["decisions"]
    assert receipt["native_capture"]["physical_writes"]
    assert not broker.attempt_history
    assert not state.pending
    assert state.allocation_state["receipt"]["sizing_model_targets"]["AAA"] == 0
    assert nightly.store.snapshot()["head"] is None
    assert receipt["packet_pipeline_integrated"] is False
    assert receipt["historical_actual_inference"] is None
    assert receipt["publication_barrier"] == "CLOSED"
    before = adapter.physical(paper.state_path(nightly.root))
    assert (
        nightly.close(
            controlled_context, broker, "2019-02-28", birth=birth, previous=birth
        )
        == result
    )
    assert adapter.physical(paper.state_path(nightly.root)) == before


# Missing native NAV must retain pre-reconciliation durable controls with no model call.
def test_native_unknown_account_keeps_state_and_no_fake_model_pass(
    nightly, controlled_context, monkeypatch
):
    broker, birth = nightly.initialize(controlled_context)
    before = adapter.physical(paper.state_path(nightly.root))

    # Simulate the actual broker surface's refusal before native reconciliation starts.
    def unavailable(self):
        raise AlpacaTradingError("unknown_claim_cash")

    monkeypatch.setattr(native.ReplayBroker, "account", unavailable)
    result = nightly.close(
        controlled_context, broker, "2019-02-28", birth=birth, previous=birth
    )
    receipt = nightly.read_original(result)
    assert receipt["status"] == "NIGHTLY_BROKER_UNAVAILABLE"
    assert receipt["reason"] == "unknown_claim_cash"
    assert receipt["holding_policy_calls"] == 0
    assert receipt["entry"] is None
    assert receipt["native_capture"] == {
        "physical_writes": [],
        "submissions": [],
        "decisions": [],
    }
    assert adapter.physical(paper.state_path(nightly.root)) == before


# Persist raw immediate native acknowledgments before a caller can replace their fields.
@pytest.mark.parametrize(("qty", "accepted"), [(2, True), (4, False)])
def test_native_raw_request_ack_or_refusal_is_retained(nightly, qty, accepted):
    client = native.ReplayBroker(
        1000, 10, initial_holdings={"AAA": 3}, initial_average_prices={"AAA": 80}
    )
    client.observe("2019-02-28T21:01:00+00:00", {"AAA": 100}, False)
    policy, _ = policy_fixture()
    before = asdict(paper.PaperState())
    assert adapter.LOCK.acquire(blocking=False)
    try:
        with adapter.NativeCapture(
            nightly.store, nightly.root, client, policy
        ) as capture:
            paper.save_state(nightly.root, paper.PaperState())
            if accepted:
                response = client.submit_market_on_open(
                    "AAA", qty, "sell", "SYNTHETIC-CID"
                )
                response["qty"] = "CALLER_MUTATED"
            else:
                with pytest.raises(AlpacaTradingError, match="uncovered_sell"):
                    client.submit_market_on_open("AAA", qty, "sell", "SYNTHETIC-CID")
        raw = adapter.admitted.decoded(
            nightly.store.read_blob(capture.submissions[0], limit=adapter.CAP)
        )
        assert raw["attempts"][0]["qty"] == qty
        assert raw["attempts"][0]["accepted"] is accepted
        if accepted:
            assert raw["raw_response"]["qty"] == "2"
        else:
            assert raw["raw_response"] is None
        assert (
            adapter.admitted.decoded(
                nightly.store.read_blob(raw["pre_submission_paper"], limit=adapter.CAP)
            )
            == before
        )
    finally:
        adapter.LOCK.release()
    assert paper.save_state is adapter.SAVE_STATE
    assert native.ReplayBroker._submit is adapter.SUBMIT
    assert "decide" not in policy.__dict__


# Native zero sizing preserves an eligible holding while retaining the raw proposal.
def test_actual_grade_allocator_retains_eligible_zero_and_missing_holdings():
    policy, shown = policy_fixture()
    orders, state, _ = policy.plan(
        "2019-02-28",
        paper.PaperState(),
        10000,
        {"AAA": 10},
        {"AAA": 100, "BBB": 100},
        shown,
        9000,
        set(),
    )
    receipt = state.allocation_state["receipt"]
    assert receipt["sizing_model_targets"]["AAA"] == 0
    assert receipt["targets"]["AAA"] == 0.1
    assert not orders
    shown.graded.grades[-1, 0] = -1
    orders, state, _ = policy.plan(
        "2019-02-28",
        paper.PaperState(),
        10000,
        {"AAA": 10},
        {"AAA": 100, "BBB": 100},
        shown,
        9000,
        set(),
    )
    assert not any(row.symbol == "AAA" for row in orders)
    assert "AAA" in state.allocation_state["receipt"]["protected_holdings"]


# A nonfinite decision is not rejected before its original native persistence boundary.
def test_nonfinite_decision_recording_pauses_after_native_write(nightly, monkeypatch):
    policy, _ = policy_fixture()
    client = native.ReplayBroker(100000, 10)

    # Expose only the serializer seam; this is not a real fitted model result.
    def nonfinite(self, *args, **kwargs):
        return {"AAA": 0.0}, {"synthetic_nonfinite": float("nan")}

    monkeypatch.setattr(FrozenCurrentGradePolicy, "decide", nonfinite)
    assert adapter.LOCK.acquire(blocking=False)
    try:
        with adapter.NativeCapture(
            nightly.store, nightly.root, client, policy
        ) as capture:
            targets, receipt = policy.decide()
            assert targets == {"AAA": 0.0}
            paper.save_state(
                nightly.root, paper.PaperState(allocation_state={"receipt": receipt})
            )
        raw = adapter.physical(paper.state_path(nightly.root))
        assert b"NaN" in raw
        assert capture.writes
        with pytest.raises(StorePause, match="Native recording failure"):
            capture.finish()
        assert adapter.physical(paper.state_path(nightly.root)) == raw
        assert nightly.store.read_blob(capture.writes[-1], limit=adapter.CAP) == raw
    finally:
        adapter.LOCK.release()


# Observation serialization failure cannot replace an authentic accepted/refused result.
@pytest.mark.parametrize(("qty", "accepted"), [(2, True), (4, False)])
def test_submission_recording_failure_preserves_native_outcome(
    nightly, monkeypatch, qty, accepted
):
    policy, _ = policy_fixture()
    client = native.ReplayBroker(
        1000, 10, initial_holdings={"AAA": 3}, initial_average_prices={"AAA": 80}
    )
    client.observe("2019-02-28T21:01:00+00:00", {"AAA": 100}, False)
    original = adapter.admitted.encoded

    # Fail this observer record, leaving actual native broker/paper code intact.
    def broken_record(value):
        if type(value) is dict and "raw_response" in value:
            raise TypeError("SYNTHETIC observation serializer failure")
        return original(value)

    monkeypatch.setattr(adapter.admitted, "encoded", broken_record)
    assert adapter.LOCK.acquire(blocking=False)
    try:
        with adapter.NativeCapture(
            nightly.store, nightly.root, client, policy
        ) as capture:
            paper.save_state(nightly.root, paper.PaperState())
            if accepted:
                response = client.submit_market_on_open(
                    "AAA", qty, "sell", "SYNTHETIC-CID"
                )
                assert response["status"] == "accepted"
            else:
                with pytest.raises(AlpacaTradingError, match="uncovered_sell"):
                    client.submit_market_on_open("AAA", qty, "sell", "SYNTHETIC-CID")
        assert client.attempt_history[-1]["accepted"] is accepted
        with pytest.raises(StorePause, match="Native recording failure"):
            capture.finish()
    finally:
        adapter.LOCK.release()


# The precise corrected clock is coupled to authenticated birth and canonical96 context.
@pytest.mark.parametrize("change", [None, "clock", "legacy", "symbol", "birth"])
def test_corrected_capability_never_relabels_native_or_legacy_clocks(
    nightly, controlled_context, change
):
    _, birth = nightly.initialize(controlled_context)
    context = market.context(
        "2019-03-01T14:45:00Z", COHORT, cohort_sha256=packet._digest(list(COHORT))
    )
    capability = adapter.submission_clock(nightly, birth, context)
    intent = {
        "client_order_id": "fixture-CID",
        "symbol": "AAA",
        "side": "buy",
        "execution_timing": "dip_or_close",
        "execute_on": "2019-03-01",
    }
    attempt = {
        "client_order_id": "fixture-CID",
        "symbol": "AAA",
        "side": "buy",
        "at": "2019-03-01T14:45:31.200000+00:00",
    }
    if change == "clock":
        attempt["at"] = "2019-03-01T14:45:00+00:00"
    elif change == "legacy":
        intent["execution_timing"] = "intraday"
    elif change == "symbol":
        attempt["symbol"] = "BBB"
    elif change == "birth":
        (nightly.operation("BIRTH", "2019-02-28") / "result.json").unlink()
    if change is None:
        assert adapter.admit_attempt(capability, attempt, intent)
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            adapter.admit_attempt(capability, attempt, intent)


# Nonfinite physical paper is preserved exactly and never normalized into a pass.
def test_physical_nan_is_retained_but_not_admitted(nightly, pins):
    client = native.ReplayBroker(100000, 10)
    state = paper.PaperState(start_equity=float("nan"))
    paper.save_state(nightly.root, state)
    raw = adapter.physical(paper.state_path(nightly.root))
    reference = sha256(raw).hexdigest()
    with pytest.raises(StorePause, match="exact bytes retained:" + reference):
        adapter.components(nightly.store, client, nightly.root, pins)
    assert nightly.store.read_blob(reference, limit=adapter.CAP) == raw
    assert adapter.physical(paper.state_path(nightly.root)) == raw


# Exact cap and regular-file admission fail closed without accepting linked metadata.
def test_physical_cap_and_symlink_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "CAP", 16)
    path = tmp_path / "state"
    path.write_bytes(b"x" * 16)
    assert adapter.physical(path) == b"x" * 16
    path.write_bytes(b"x" * 17)
    with pytest.raises(ValueError, match="cap"):
        adapter.physical(path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="Regular conditional source"):
        adapter.physical(link)


# Atime-only reads remain valid; mtime and ctime changes still reject admission.
@pytest.mark.parametrize("change", ["atime", "mtime", "ctime"])
def test_physical_file_identity_excludes_only_access_time(
    tmp_path, monkeypatch, change
):
    path = tmp_path / "original"
    path.write_bytes(b"unchanged source bytes")
    original = os.fstat
    count = 0

    # Model only the second descriptor metadata observation, without changing bytes.
    def observed(descriptor):
        nonlocal count
        info = original(descriptor)
        count += 1
        value = SimpleNamespace(
            **{
                name: getattr(info, name)
                for name in (
                    "st_dev",
                    "st_ino",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                    "st_mode",
                )
            }
        )
        value.st_atime = info.st_atime + (100 if count == 2 else 0)
        if count == 2 and change != "atime":
            field = "st_" + change + "_ns"
            setattr(value, field, getattr(value, field) + 1)
        return value

    monkeypatch.setattr(os, "fstat", observed)
    if change == "atime":
        assert adapter.physical(path) == b"unchanged source bytes"
    else:
        with pytest.raises(ValueError, match="Physical bytes changed"):
            adapter.physical(path)


# Changed actual helper bytes cannot borrow a prior source declaration.
def test_source_manifest_is_literal_and_current_native_map_unchanged(pins):
    declared = adapter.sources()
    assert (
        packet._digest(pins["identity"]["source_sha256"])
        == codec.PROFILES[adapter.admitted.CURRENT_SOURCE][3]
    )
    assert all(len(value) == 64 for value in declared.values())
    assert "backend/market/data/fomc_decisions.csv" in declared
    assert "docs/research/forward-arithmetic-publication-2026-10-04.md" in declared


# Exercise real context validation over declared synthetic buffers, without a loader.
def integrity_context():
    dates = np.array(["2019-02-28"], dtype="datetime64[D]")
    panel = SimpleNamespace(dates=dates, tickers=("AAA", "SPY", "QQQ"))
    for name in ("open", "high", "low", "close", "adj_close", "volume"):
        setattr(panel, name, np.full((1, 3), 100.0))
    passive = PassiveMarks(
        dates.copy(),
        ("CHILD", "OTHER"),
        np.full((1, 2), 10.0),
        np.full((1, 26, 2), 11.0),
        np.array([[12.0, 15.0]]),
        _freeze({"synthetic": True, "supplied": {"source": "fixture-only"}}),
    )
    raw = readonly(
        RawExecutionInputs(
            dates,
            panel.tickers,
            np.zeros((1, 3), dtype=np.int16),
            np.ones((1, 3), dtype=bool),
            *(getattr(panel, name).copy() for name in ("open", "high", "low", "close")),
            None,
            None,
            None,
            None,
            None,
            None,
            np.ones((1, 3)),
            {},
            {"synthetic": True},
            passive,
            {},
        )
    )
    parent = SimpleNamespace(_bank={"features": np.full((1, 3, 21), 1.0)})
    for name in (
        "_frozen_dates",
        "_features",
        "_forecasts",
        "_support",
        "_prices",
        "_history_prices",
        "_history_grades",
    ):
        setattr(
            parent, name, dates.copy() if name == "_frozen_dates" else np.ones((1, 3))
        )
    reader = SimpleNamespace(
        _parent=parent, _market=np.full((1, 4), 0.25), symbols=panel.tickers
    )
    reader._market.flags.writeable = False

    # Identify this capability as a synthetic approval, never authentic model admission.
    def approval_validate():
        return {"synthetic": True}

    provenance = {
        "source_sha256": adapter.sources(),
        "input_sha256": {},
        "symbols": list(panel.tickers),
        "array_sha256": adapter.arrays(panel, raw, reader),
        "actions_sha256": packet._digest(raw.actions),
        "inherited_actions_sha256": packet._digest(raw.inherited_actions),
        "model_fit_date": datetime.now(UTC).date().isoformat(),
        "scope": "SYNTHETIC_MEMORY_COMMITMENT_ONLY_NO_MODEL_OR_INPUT_ADMISSION",
    }
    context = object.__new__(adapter.HoldingContext)
    for name, value in {
        "approval": SimpleNamespace(validate=approval_validate),
        "panel": panel,
        "raw": raw,
        "reader": reader,
        "provenance": adapter.admitted.encoded(provenance),
    }.items():
        object.__setattr__(context, name, value)
    return context


# Unchanged native-shaped buffers and recursively frozen passive metadata remain usable.
def test_context_integrity_unchanged_passive_and_market():
    context = integrity_context()
    assert context.validate()["scope"].startswith("SYNTHETIC_MEMORY")
    assert context.raw.passive.daily_close.flags.owndata
    assert context.reader._market.flags.owndata


# Re-enabling NumPy writes must not bypass any consumed passive or market commitment.
@pytest.mark.parametrize(
    "field", ["dates", "session_open", "observation_close", "daily_close", "market"]
)
def test_context_integrity_rejects_owned_buffer_mutation(field):
    context = integrity_context()
    context.validate()
    before = adapter.live_policy_replay.account_marks(
        context.raw,
        0,
        datetime.fromisoformat("2019-02-28T21:01:00+00:00"),
        context.raw.daily_close[0],
    )
    value = (
        context.reader._market
        if field == "market"
        else getattr(context.raw.passive, field)
    )
    value.setflags(write=True)
    value.flat[0] += np.timedelta64(1, "D") if field == "dates" else 1.0
    value.setflags(write=False)
    if field == "daily_close":
        after = adapter.live_policy_replay.account_marks(
            context.raw,
            0,
            datetime.fromisoformat("2019-02-28T21:01:00+00:00"),
            context.raw.daily_close[0],
        )
        assert before["CHILD"] == 12.0
        assert after["CHILD"] == 13.0
    with pytest.raises(ValueError, match="Nightly input/model arrays changed"):
        context.validate()


# Equal-shaped passive buffers cannot be rebound to different identities or provenance.
@pytest.mark.parametrize("field", ["tickers", "provenance", "absent"])
def test_context_integrity_rejects_passive_binding_mutation(field):
    context = integrity_context()
    context.validate()
    passive = context.raw.passive
    if field == "tickers":
        passive = replace(passive, tickers=tuple(reversed(passive.tickers)))
    elif field == "provenance":
        passive = replace(
            passive, provenance=_freeze({"synthetic": True, "source": "changed"})
        )
    else:
        passive = None
    object.__setattr__(context, "raw", replace(context.raw, passive=passive))
    with pytest.raises(ValueError, match="Nightly input/model arrays changed"):
        context.validate()


# Absence is committed too, so later adding passive valuation inputs is refused.
def test_context_integrity_rejects_added_passive_binding():
    context = integrity_context()
    passive = context.raw.passive
    raw = replace(context.raw, passive=None)
    object.__setattr__(context, "raw", raw)
    provenance = adapter.admitted.decoded(context.provenance)
    provenance["array_sha256"] = adapter.arrays(context.panel, raw, context.reader)
    object.__setattr__(context, "provenance", adapter.admitted.encoded(provenance))
    context.validate()
    object.__setattr__(context, "raw", replace(raw, passive=passive))
    with pytest.raises(ValueError, match="Nightly input/model arrays changed"):
        context.validate()


# Commit plain expected actions before exposing the same native-shaped frozen metadata.
def action_context(field):
    context = integrity_context()
    actions = {
        "AAA": [
            {
                "kind": "split",
                "date": "2019-02-28",
                "value": 2.0,
                "declaration": {"known": True, "missing": None, "count": 1},
            }
        ]
    }
    inherited = {"CHILD": [{"kind": "dividend", "date": "2019-02-28", "value": 0.25}]}
    provenance = adapter.admitted.decoded(context.provenance)
    provenance["actions_sha256"] = packet._digest(actions)
    provenance["inherited_actions_sha256"] = packet._digest(inherited)
    raw = replace(
        context.raw,
        actions=_freeze(actions) if field in ("actions", "both") else actions,
        inherited_actions=(
            _freeze(inherited) if field in ("inherited_actions", "both") else inherited
        ),
    )
    object.__setattr__(context, "raw", raw)
    object.__setattr__(context, "provenance", adapter.admitted.encoded(provenance))
    return context, actions, inherited


# Admit unchanged native frozen actions and inherited events through real validation.
@pytest.mark.parametrize("field", ["actions", "inherited_actions", "both"])
def test_action_metadata_context_accepts_frozen(field):
    context, actions, inherited = action_context(field)
    before = context.provenance
    admitted = context.validate()
    assert admitted["actions_sha256"] == packet._digest(actions)
    assert admitted["inherited_actions_sha256"] == packet._digest(inherited)
    assert context.provenance == before


# Preserve the original canonical hash at construction and later validation.
def test_action_metadata_digest_preserves_canonical_values_and_detaches():
    plain = {"outer": [{"float": 1.0, "integer": 1, "boolean": True, "missing": None}]}
    frozen = _freeze(plain)
    detached = adapter.action_primitives(frozen)
    assert detached == plain
    assert packet._digest(detached) == adapter.action_digest(frozen)
    assert adapter.action_digest(frozen) == packet._digest(plain)
    assert type(detached["outer"][0]["float"]) is float
    assert type(detached["outer"][0]["integer"]) is int
    detached["outer"][0]["integer"] = 9
    assert frozen["outer"][0]["integer"] == 1
    assert plain["outer"][0]["integer"] == 1


# Reject changed frozen actions against their previously admitted commitment.
@pytest.mark.parametrize("field", ["actions", "inherited_actions"])
def test_action_metadata_context_rejects_corruption(field):
    context, actions, inherited = action_context("both")
    context.validate()
    changed = actions if field == "actions" else inherited
    symbol = "AAA" if field == "actions" else "CHILD"
    changed[symbol][0]["value"] += 1
    object.__setattr__(
        context, "raw", replace(context.raw, **{field: _freeze(changed)})
    )
    with pytest.raises(ValueError, match="Economic action declarations changed"):
        context.validate()


# Nonfinite action values must fail instead of being replaced with a missing value.
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["actions", "inherited_actions"])
def test_action_metadata_context_rejects_nonfinite(field, value):
    context, _, _ = action_context("both")
    altered = MappingProxyType(
        {"AAA": (MappingProxyType({"nested": MappingProxyType({"value": value})}),)}
    )
    object.__setattr__(context, "raw", replace(context.raw, **{field: altered}))
    with pytest.raises(ValueError, match="finite JSON primitives"):
        context.validate()


# Shape conversion must not stringify keys or accept arbitrary Python objects.
@pytest.mark.parametrize(
    "value",
    [
        {1: "integer key"},
        {True: "boolean key"},
        {None: "missing key"},
        {("key",): "tuple key"},
        {"nested": object()},
        {"nested": b"bytes"},
        {"nested": {"set"}},
        {"nested": np.float64(1.0)},
    ],
)
def test_action_metadata_rejects_nonprimitive(value):
    with pytest.raises(ValueError, match="Action metadata requires"):
        adapter.action_digest(MappingProxyType(value))


# Keep original same-date declarations visible without inventing account entitlements.
def prior_close_dividends(context):
    context.raw.actions = {
        "AAA": (
            MappingProxyType({"date": "2019-02-28", "kind": "dividend", "value": 0.54}),
        ),
        "BBB": (
            MappingProxyType(
                {"date": "2019-02-28", "kind": "dividend", "value": 0.004}
            ),
        ),
    }


# The original prior-close plan starts before the account's first economic session.
def test_birth_prior_close_records_dividends_without_applying(
    nightly, controlled_context
):
    prior_close_dividends(controlled_context)
    broker, birth = nightly.initialize(controlled_context)
    result = nightly.close(
        controlled_context, broker, "2019-02-28", birth=birth, previous=birth
    )
    receipt = nightly.read_original(result)
    evidence = receipt["pre_inception_actions"]
    assert evidence["status"] == "PRE_INCEPTION_NOT_APPLIED"
    assert evidence["session"] == "2019-02-28"
    assert evidence["first_account_session"] == "2019-03-01"
    assert evidence["actions"] == [
        {
            "symbol": name,
            "declaration": {"date": "2019-02-28", "kind": "dividend", "value": value},
            "effective_at": "2019-02-28T09:30:00-05:00",
        }
        for name, value in (("AAA", 0.54), ("BBB", 0.004))
    ]
    assert broker._cash == 100000.0
    assert broker._held == broker._orders == broker._actions == {}
    assert broker._dividends == []
    assert broker.attempt_history == broker.fill_history == ()
    assert receipt["holding_policy_calls"] == 1
    assert receipt["native_capture"]["submissions"] == []
    raw = adapter.admitted.decoded(
        nightly.store.read_blob(receipt["raw_submission_receipts"], limit=adapter.CAP)
    )
    assert raw["attempts"] == raw["accepted"] == []
    assert receipt["entry"] is not None
    assert paper.load_state(nightly.root).sessions_seen == ["2019-02-28"]


# Exercise the exact zero-state guard independently of authenticated component hashes.
def birth_evidence(broker, state, **changes):
    arguments = {
        "prior_kind": "NIGHTLY",
        "prior": {"phase": "BIRTH", "session": "2019-02-28"},
        "previous": "original-birth",
        "birth": "original-birth",
        "birth_record": {"first": "2019-03-01"},
        "session": "2019-02-28",
        "due": [],
        **changes,
    }
    return adapter.pre_inception_actions(broker, state, **arguments)


# Neither a different predecessor nor a changed inception date can borrow the exception.
@pytest.mark.parametrize(
    "changes",
    [
        {"prior_kind": "CYCLE"},
        {"prior": {"phase": "NIGHTLY_CLOSE", "session": "2019-02-28"}},
        {"previous": "different-birth"},
        {"session": "2019-03-01"},
        {"birth_record": {"first": "2019-02-28"}},
        {"birth_record": {"first": "2019-03-04"}},
    ],
)
def test_birth_prior_close_rejects_false_boundary(changes):
    with pytest.raises(ValueError, match="prior-close birth boundary"):
        birth_evidence(native.ReplayBroker(100000, 10), paper.PaperState(), **changes)


# Every nonempty broker economic, order, mark and observation component must fail.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("_cash", 99999.0),
        ("cost_bps", 11.0),
        ("_last_equity", 99999.0),
        ("_held", {"AAA": 1}),
        ("_average", {"AAA": 100.0}),
        ("_orders", {"accepted": {}}),
        ("_attempts", [{}]),
        ("_fills", [{}]),
        ("_actions", {"dividend": True}),
        ("_dividends", [{}]),
        ("_security_distributions", [{}]),
        ("_security_exchanges", [{}]),
        ("_share_consolidations", [{}]),
        ("_cash_mergers", [{}]),
        ("_marks", {"AAA": 100.0}),
        ("_mark_times", {"AAA": "2019-02-28T21:01:00+00:00"}),
        ("_now", datetime(2019, 2, 28, 21, 1, tzinfo=UTC)),
        ("_observed_at", datetime(2019, 2, 28, 21, 1, tzinfo=UTC)),
        ("_market_open", True),
        ("_batch_open", True),
    ],
)
def test_birth_prior_close_rejects_nonzero_native_component(field, value):
    broker = native.ReplayBroker(100000, 10)
    setattr(broker, field, value)
    with pytest.raises(ValueError, match="Untouched native zero-account"):
        birth_evidence(broker, paper.PaperState())


# Full paper controls and durable receipts must be empty, not just current holdings.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sessions_seen", ["2019-02-27"]),
        ("journal", [{}]),
        ("pending", [{}]),
        ("order_seq", 1),
        ("event_cycle", {"active": True}),
        ("allocation_state", {"receipt": {}}),
    ],
)
def test_birth_prior_close_rejects_nonempty_paper_state(field, value):
    state = paper.PaperState()
    setattr(state, field, value)
    with pytest.raises(ValueError, match="Untouched native zero-account"):
        birth_evidence(native.ReplayBroker(100000, 10), state)


# Normal-session declarations still require a separate authenticated coordinator.
@pytest.mark.parametrize("prior_kind", ["NIGHTLY", "CYCLE"])
def test_normal_prior_close_still_requires_event_coordinator(
    nightly, controlled_context, monkeypatch, prior_kind
):
    prior_close_dividends(controlled_context)
    broker, birth = nightly.initialize(controlled_context)
    original = nightly.read_birth(birth)
    prior = dict(original, phase="NIGHTLY_CLOSE", session="2019-02-27", birth=birth)
    if prior_kind == "CYCLE":
        prior["session"] = "2019-02-28"

    # Supply a declared synthetic predecessor only to isolate the unchanged event guard.
    def predecessor(self, reference):
        assert self is nightly
        assert reference == birth
        return prior, prior_kind

    monkeypatch.setattr(adapter.Nightly, "predecessor", predecessor)
    with pytest.raises(ValueError, match="Economic coordinator evidence required"):
        nightly.close(
            controlled_context, broker, "2019-02-28", birth=birth, previous=birth
        )
    assert broker._now is None
    assert broker._actions == {}
    assert broker._dividends == []
    assert not broker.attempt_history
