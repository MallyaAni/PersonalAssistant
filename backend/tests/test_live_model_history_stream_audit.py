"""Streaming composition cannot replace independent lineage with saved controls."""

import gzip
import json
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import paper
from backend.market import calendar, entry_timing
from backend.market import live_model_history_nightly_model as numerical
from backend.market import live_model_history_stream_audit as audit
from backend.market.live_model_history_receipts import ReceiptLedger
from backend.tests.test_live_model_history_nightly_model import analytic_policy, records
from backend.tests.test_live_model_history_pending_audit import evidence, fixture


# Build minimal externally pinned metadata without loading a model or an account.
def metadata_files(tmp_path, route, content):
    status = "COMPLETED_UNVERIFIED_CURRENT_MODEL_ACCOUNT"
    completion = {
        "status": status,
        "paper_state": {},
        "capture_sha256": "",
        "input_sha256": {},
        "source_sha256": {},
        "sessions": [{"session": "2019-03-01", "sha256": "a" * 64}],
    }
    raw_completion = json.dumps(completion).encode()
    manifest = b'{"files":{}}'
    capture = b'{"files":{},"source_sha256":{}}'
    if route == "completion":
        raw_completion = raw_completion[:-1] + b',"ambiguous":' + content + b"}"
    elif route == "manifest":
        manifest = b'{"files":{},"ambiguous":' + content + b"}"
    elif route == "capture":
        capture = b'{"files":{},"source_sha256":{},"ambiguous":' + content + b"}"
    completion_path = tmp_path / "completion.json"
    manifest_path = tmp_path / "source-manifest.json"
    capture_path = tmp_path / "capture.json"
    if route != "completion":
        completion["capture_sha256"] = sha256(capture).hexdigest()
        raw_completion = json.dumps(completion).encode()
    completion_path.write_bytes(raw_completion)
    manifest_path.write_bytes(manifest)
    capture_path.write_bytes(capture)
    return completion_path, manifest_path


# Oversized metadata must be rejected before any unbounded whole-file allocation.
def test_admission_metadata_size_is_checked_before_reading(tmp_path, monkeypatch):
    path = tmp_path / "large.json"
    raw = b"x" * 64
    path.write_bytes(raw)
    monkeypatch.setattr(audit, "MAX_METADATA_BYTES", 32, raising=False)

    # Any file opening would prove the size guard ran after allocation started.
    def forbidden_open(*args, **kwargs):
        raise AssertionError("Oversized metadata must fail before opening")

    monkeypatch.setattr(type(path), "open", forbidden_open)
    with pytest.raises(ValueError, match="size|bound|large"):
        audit.pinned(path, sha256(raw).hexdigest())


# Reach each actual metadata decoder without evaluating a model or account.
def admit_metadata_route(tmp_path, route, content):
    completion_path, manifest_path = metadata_files(tmp_path, route, content)
    if route == "initial":
        path = tmp_path / "initial-receipts.json"
        raw = b"[" + content + b"]"
        path.write_bytes(raw)
        return audit.InitialReceipts(path, sha256(raw).hexdigest()).attempts()
    archives = audit.OriginalArchives(
        tmp_path,
        sha256(completion_path.read_bytes()).hexdigest(),
        "0" * 64,
        manifest_path,
        sha256(manifest_path.read_bytes()).hexdigest(),
    )
    if route == "capture":
        archives.authenticate_inputs(tmp_path)
    return archives


# Every metadata route must reject duplicate keys and nonfinite numeric literals.
@pytest.mark.parametrize("route", ["initial", "completion", "manifest", "capture"])
@pytest.mark.parametrize(
    "content", [b'{"qty":1,"qty":2}', b"NaN", b"Infinity", b"1e999"]
)
def test_admission_metadata_is_strict_before_interpretation(tmp_path, route, content):
    with pytest.raises(ValueError, match="Duplicate|Nonfinite"):
        admit_metadata_route(tmp_path, route, content)


# A caller cannot replace the admitted immutable original receipt bytes afterward.
def test_admission_initial_receipt_identity_is_immutable(tmp_path):
    path = tmp_path / "initial-receipts.json"
    path.write_bytes(b"[]")
    receipts = audit.InitialReceipts(path, sha256(b"[]").hexdigest())
    with pytest.raises((AttributeError, TypeError)):
        receipts.raw = b"[1]"


# Original completion bytes and external selectors remain immutable after admission.
def test_admission_archive_identities_are_immutable(tmp_path):
    completion_path, manifest_path = metadata_files(tmp_path, "unchanged", b"0")
    archives = audit.OriginalArchives(
        tmp_path,
        sha256(completion_path.read_bytes()).hexdigest(),
        "0" * 64,
        manifest_path,
        sha256(manifest_path.read_bytes()).hexdigest(),
    )
    for field, replacement in (
        ("completion_raw", b"{}"),
        ("initial_sha256", "1" * 64),
        ("manifest_sha256", "1" * 64),
    ):
        with pytest.raises((AttributeError, TypeError)):
            setattr(archives, field, replacement)


# Exercise ordinary nested mutation routes rather than only dataclass assignment.
def mutate_identity(archives, field):
    if field == "source_item":
        archives.sources["new-source"] = "b" * 64
    elif field == "source_update":
        archives.sources.update({"new-source": "b" * 64})
    elif field == "input_item":
        archives.completion["input_sha256"]["/private/input"] = "b" * 64
    elif field == "input_update":
        archives.completion["input_sha256"].update({"/private/input": "b" * 64})
    elif field == "session_item":
        archives.completion["sessions"][0]["sha256"] = "b" * 64
    elif field == "session_append":
        archives.completion["sessions"].append({"session": "invented"})
    elif field == "consumed_item":
        archives.consumed_inputs["/private/input"] = "b" * 64
    else:
        archives.consumed_inputs.clear()


# External mutation cannot replace any previously admitted nested expectation.
@pytest.mark.parametrize(
    "field",
    [
        "source_item",
        "source_update",
        "input_item",
        "input_update",
        "session_item",
        "session_append",
        "consumed_item",
        "consumed_clear",
    ],
)
def test_admission_nested_identities_are_readonly(tmp_path, field):
    completion_path, manifest_path = metadata_files(tmp_path, "unchanged", b"0")
    archives = audit.OriginalArchives(
        tmp_path,
        sha256(completion_path.read_bytes()).hexdigest(),
        "0" * 64,
        manifest_path,
        sha256(manifest_path.read_bytes()).hexdigest(),
    )
    before = audit.digest(
        {
            "completion": archives.completion,
            "sources": archives.sources,
            "consumed": dict(archives.consumed_inputs),
        }
    )
    with pytest.raises((AttributeError, TypeError)):
        mutate_identity(archives, field)
    assert (
        audit.digest(
            {
                "completion": archives.completion,
                "sources": archives.sources,
                "consumed": dict(archives.consumed_inputs),
            }
        )
        == before
    )


# Recursive readonly values preserve the real comparison and serialization schemas.
def test_admission_readonly_metadata_preserves_existing_consumers():
    original = {"list": [{"qty": 3, "cash": 1.5, "missing": None}], "flag": True}
    readonly = audit._freeze(original)
    audit.economic.same(readonly, original, "Compatible readonly metadata")
    assert numerical.serialized(readonly) == original
    assert json.loads(json.dumps(readonly)) == original
    assert deepcopy(readonly) is readonly
    detached = readonly.copy()
    detached["new"] = "detached only"
    assert "new" not in readonly
    original["list"][0]["qty"] = 999
    assert readonly["list"][0]["qty"] == 3


# Cached metadata excludes the large final state and exposes only readonly bookkeeping.
def test_admission_metadata_is_cached_without_reparsing_full_state(tmp_path):
    completion_path, manifest_path = metadata_files(tmp_path, "unchanged", b"0")
    archives = audit.OriginalArchives(
        tmp_path,
        sha256(completion_path.read_bytes()).hexdigest(),
        "0" * 64,
        manifest_path,
        sha256(manifest_path.read_bytes()).hexdigest(),
    )
    assert "paper_state" not in archives.completion
    assert archives.completion is archives.completion
    view = archives.consumed_inputs
    assert not view
    archives.authenticate_inputs(tmp_path)
    assert len(view) == 1
    with pytest.raises((AttributeError, TypeError)):
        archives.consumed_inputs = {}


# File growth after its stat cannot cause an unbounded read or silently change identity.
@pytest.mark.parametrize("extra", [1, 64])
def test_admission_metadata_growth_uses_bounded_read_and_stability_check(
    tmp_path, monkeypatch, extra
):
    path = tmp_path / "changing.json"
    raw = b"x" * 16
    path.write_bytes(raw)
    original_open, sizes = type(path).open, []
    monkeypatch.setattr(audit, "MAX_METADATA_BYTES", 32)

    # Wrap the original file descriptor while retaining real stat identity checks.
    class GrowingFile:
        # Open only the original small file, without pre-reading its contents.
        def __init__(self):
            self.stream = original_open(path, "rb")

        # Preserve ordinary context-manager lifetime for the bounded reader.
        def __enter__(self):
            return self

        # Close the authentic underlying descriptor after success or refusal.
        def __exit__(self, *args):
            self.stream.close()

        # Expose the original descriptor for genuine fstat admission checks.
        def fileno(self):
            return self.stream.fileno()

        # Grow only after the caller has checked stat, then honor its read bound.
        def read(self, size):
            sizes.append(size)
            with original_open(path, "ab") as changed:
                changed.write(b"y" * extra)
            return self.stream.read(size)

    # Intercept only the reader while letting the wrapper use the captured opener.
    def opened(*args, **kwargs):
        return GrowingFile()

    monkeypatch.setattr(type(path), "open", opened)
    with pytest.raises(ValueError, match="size|changed"):
        audit.pinned(path, sha256(raw).hexdigest())
    assert sizes == [33]


# Large binary authentication must stream fixed chunks and return only a digest.
def test_admission_binary_authentication_never_allocates_whole_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "model.npz"
    raw = b"fixed original artifact" * 17
    path.write_bytes(raw)
    monkeypatch.setattr(audit, "HASH_CHUNK_BYTES", 64)
    original_open, sizes = type(path).open, []

    # Require every actual digest read to use the fixed binary chunk size.
    @contextmanager
    def opened(selected, *args, **kwargs):
        with original_open(selected, *args, **kwargs) as stream:
            # Keep even the final EOF read bounded instead of using read-all.
            def read(size=-1):
                assert size == 64
                sizes.append(size)
                return stream.read(size)

            yield SimpleNamespace(read=read, fileno=stream.fileno)

    # Whole-file byte reads are forbidden for this digest-only input path.
    def forbidden_read(*args, **kwargs):
        raise AssertionError("Binary authentication must stream")

    monkeypatch.setattr(type(path), "read_bytes", forbidden_read)
    monkeypatch.setattr(type(path), "open", opened)
    assert (
        audit.authenticate_file(path, sha256(raw).hexdigest())
        == sha256(raw).hexdigest()
    )
    with pytest.raises(ValueError, match="Pinned"):
        audit.authenticate_file(path, "0" * 64)
    assert len(sizes) > 2


# Configuration admission rejects ambiguous bytes before any numerical use.
@pytest.mark.parametrize(
    "content", [b'{"qty":1,"qty":2}', b"NaN", b"Infinity", b"1e999"]
)
def test_admission_config_is_strict_before_composition(tmp_path, monkeypatch, content):
    folder = tmp_path / "desk/learned-holding"
    folder.mkdir(parents=True)
    raw = (
        b'{"policy":"private","cost_bps":10,"model_receipt_sha256":"model","risk_receipt_sha256":"risk","ambiguous":'
        + content
        + b"}"
    )
    (folder / "config.json").write_bytes(raw)
    completion = {
        "status": "COMPLETED_UNVERIFIED_CURRENT_MODEL_ACCOUNT",
        "paper_state": {},
        "source_sha256": {},
        "holding_config_sha256": sha256(raw).hexdigest(),
        "policy": "private",
        "cost_bps": 10,
        "real_orders": False,
        "base_models_fitted": 0,
        "model_receipt_sha256": "model",
        "risk_receipt_sha256": "risk",
        "current_model_inference": {},
        "first": "2019-03-01",
        "through": "2019-03-01",
        "sessions": [{"session": "2019-03-01"}],
    }
    completion_raw = json.dumps(completion).encode()
    (tmp_path / "completion.json").write_bytes(completion_raw)
    manifest = tmp_path / "source-manifest.json"
    manifest.write_bytes(b'{"files":{}}')
    archives = audit.OriginalArchives(
        tmp_path,
        sha256(completion_raw).hexdigest(),
        "0" * 64,
        manifest,
        sha256(manifest.read_bytes()).hexdigest(),
    )

    # Separate source tests permit reaching this actual configuration decoder.
    def no_sources(self):
        return None

    # Admit an explicit empty source fixture without importing or evaluating model data.
    def capture(self, market):
        return {"source_sha256": {}}

    # Keep the admission test at the configuration boundary, before policy semantics.
    def policy(*args):
        return SimpleNamespace()

    # The cohort matrix is independent of malformed configuration admission.
    def cohort(*args):
        return []

    monkeypatch.setattr(audit.OriginalArchives, "authenticate_sources", no_sources)
    monkeypatch.setattr(audit.OriginalArchives, "authenticate_inputs", capture)
    monkeypatch.setattr(audit, "FrozenCurrentGradePolicy", policy)
    monkeypatch.setattr(audit, "complete_cohort", cohort)
    panel = SimpleNamespace(dates=np.array(["2019-03-01"], dtype="datetime64[D]"))
    reader = SimpleNamespace(_parent=SimpleNamespace(identity={}))
    with pytest.raises(ValueError, match="Duplicate|Nonfinite"):
        audit.StreamAudit(
            archives,
            tmp_path,
            panel,
            SimpleNamespace(actions={}, inherited_actions=None),
            reader,
            json.loads(raw),
            {},
            verified_at=datetime.now(UTC),
        )


# Start a private synthetic composition at an already independently derived boundary.
def stream_boundary(state=None):
    result = audit.StreamAudit.__new__(audit.StreamAudit)
    result.state = paper.PaperState() if state is None else deepcopy(state)
    result.intents, result.receipts = {}, ReceiptLedger()
    result.held, result.chain = {"AAA": 10}, "0" * 64
    result.counts = dict.fromkeys(
        (
            "nights",
            "model",
            "event_priority",
            "already_planned",
            "nightly_broker_unavailable",
            "intraday_transitions",
            "filled_receipts",
        ),
        0,
    )
    result.completion = {"actual_started_at": "2026-10-17T12:00:00+00:00"}
    result.verified_at = datetime(2026, 10, 17, 14, tzinfo=UTC)
    return result


# Assemble synthetic expected outputs from a separate pure planning invocation.
def planned_target(policy, shown, previous, observed, *, attempts=None):
    session = str(shown.panel.dates[-1])
    at = (
        datetime.combine(
            shown.panel.dates[-1].astype(object),
            calendar.session_close(shown.panel.dates[-1].astype(object)),
            calendar.NEW_YORK,
        )
        + entry_timing.BAR / 15
    )
    attempts = [] if attempts is None else attempts
    accepted = {row["client_order_id"]: row for row in attempts if row["accepted"]}
    before, settled, _ = audit.controls.before_plan(
        previous, {}, {}, session, at.isoformat()
    )
    state, planned, entry, _ = numerical.pure_plan(
        shown, policy, before, observed, session, at.isoformat(), attempts, accepted
    )
    if state.start_equity is None:
        state.start_equity = observed["equity"]
    full_entry = {
        **entry,
        "written": "2026-10-17T13:00:00+00:00",
        "pl": observed["equity"] - state.start_equity,
        "pl_pct": observed["equity"] / state.start_equity - 1,
        "settled": [],
    }
    state.history = [row for row in previous.history if row["session"] != session] + [
        full_entry
    ]
    return {
        "session": session,
        "nightly": {
            "session": session,
            "at": at.isoformat(),
            "status": "planned",
            "persisted_policy": state.policy_version,
            "entry": numerical.serialized(full_entry),
        },
        "attempts": attempts,
        "new_intents": numerical.serialized(planned),
        "paper_state": numerical.serialized(asdict(state)),
    }, numerical.serialized(asdict(state))


# Inspect exact same-close metadata without using acknowledgments to select quantities.
def test_new_acknowledgments_are_unique_same_close_receipts():
    row = {
        "client_order_id": "original",
        "at": "2019-03-01T16:01:00-05:00",
        "accepted": True,
    }
    assert audit.candidate_acknowledgments([row], {}, row["at"]) == {"original": row}
    with pytest.raises(ValueError, match="Duplicate"):
        audit.candidate_acknowledgments([row, row], {}, row["at"])
    with pytest.raises(ValueError, match="clock"):
        audit.candidate_acknowledgments([row], {}, "2019-03-04T16:01:00-05:00")


# The saved target can be compared but cannot supply the next state or action quantity.
@pytest.mark.parametrize(
    "corruption", [None, "target", "action", "state", "quantity_float"]
)
def test_connected_nightly_comparison_recomputes_controls_and_quantities(
    monkeypatch, corruption
):
    policy, shown = analytic_policy()
    stream = stream_boundary()
    stream.policy, stream.reader = policy, policy.reader
    stream.panel, stream.raw = shown.panel, SimpleNamespace(grades=None, eligible=None)
    observed = numerical.account(
        9000, {"AAA": 10}, {"AAA": 100}, [], records(), {"AAA": 100}
    )
    value, expected = planned_target(policy, shown, stream.state, observed)

    # Fix the synthetic report; native integration covers actual frozen prefixes.
    def report(*args):
        return shown

    # Record selected synthetic rows without loading a native model in this fixture.
    def select(day):
        assert day == len(shown.panel.dates) - 1

    # Existing prefix properties have their own actual-feature tests.
    def prefix(*args):
        return {"synthetic": True}

    monkeypatch.setattr(audit.continuation, "close_report", report)
    monkeypatch.setattr(stream.reader, "select", select, raising=False)
    monkeypatch.setattr(numerical, "prefix_model", prefix)
    if corruption == "target":
        value["nightly"]["entry"]["joint_funded"]["targets"]["AAA"] = 0.9
    elif corruption == "action":
        value["nightly"]["entry"]["actions"][0]["order_quantity"] = 999
    elif corruption == "state":
        value["paper_state"]["opened"] = {"invented": "2019-01-01"}
    elif corruption == "quantity_float":
        value["paper_state"]["order_seq"] = float(value["paper_state"]["order_seq"])
    before = deepcopy(value)
    if corruption is None:
        mode = stream.nightly(value, len(shown.panel.dates) - 1, stream.state, observed)
        assert mode["path"] == "model"
        assert numerical.serialized(asdict(stream.state)) == expected
        assert stream.counts["model"] == 1
    else:
        with pytest.raises(ValueError, match="differ|required"):
            stream.nightly(value, len(shown.panel.dates) - 1, stream.state, observed)
        assert stream.counts["nights"] == 0
    assert value == before


# Account failures preserve derived intraday state across consecutive closing sessions.
def test_prior_unavailable_state_propagates_without_saved_controls_or_reconciliation(
    monkeypatch,
):
    previous, expected, value, accepted, raw = fixture()
    derived, _ = audit.pending.fold_pending(
        previous,
        evidence(value),
        accepted,
        {},
        raw,
        0,
        value["session"],
        conserved_attempts=value["attempts"],
    )
    stream = stream_boundary(previous)

    # The first-account failure must precede reconciliation and model calls.
    def forbidden(*args, **kwargs):
        raise AssertionError("Unavailable account must retain pre-reconciliation state")

    monkeypatch.setattr(audit.controls, "before_plan", forbidden)
    monkeypatch.setattr(audit.continuation, "close_report", forbidden)
    for session in ("2019-03-01", "2019-03-04"):
        at = session + "T16:01:00-05:00"
        target = {
            "session": session,
            "nightly": {
                "session": session,
                "at": at,
                "text": "",
                "status": "nightly_broker_unavailable",
                "reason": "Fresh raw held mark unavailable for AAA",
            },
            "new_intents": [],
            "attempts": [],
            "paper_state": numerical.serialized(asdict(expected)),
        }
        stream.nightly(
            target,
            0,
            derived,
            {"problem": "missing_held_close", "missing_symbols": ["AAA"]},
        )
        assert stream.state == expected
        derived = stream.state
    assert stream.counts["nightly_broker_unavailable"] == 2
    assert stream.counts["model"] == 0
    assert stream.state.journal == previous.journal
    assert stream.state.history == previous.history


# Event reductions/restorations and duplicate closes cannot count as fresh model plans.
@pytest.mark.parametrize("branch", ["reduction", "restoration", "duplicate"])
def test_connected_nonmodel_paths_keep_actual_orders_and_zero_model_counts(
    monkeypatch, branch
):
    policy, shown = analytic_policy()
    stream = stream_boundary()
    stream.policy, stream.reader = policy, policy.reader
    stream.panel, stream.raw = shown.panel, SimpleNamespace(grades=None, eligible=None)
    session = str(shown.panel.dates[-1])
    day = shown.panel.dates[-1].astype(object)
    at = datetime.combine(
        day, calendar.session_close(day), calendar.NEW_YORK
    ) + timedelta(minutes=1)
    event = {
        "calendar_known": True,
        "factor": 0.5 if branch == "reduction" else 1.0,
        "decision_date": (day + timedelta(days=1)).isoformat()
        if branch == "reduction"
        else session,
    }
    quantity = 5 if branch == "restoration" else 10
    observed = numerical.account(
        10000 - quantity * 100,
        {"AAA": quantity},
        {"AAA": 100},
        [],
        records(),
        {"AAA": 100},
    )
    if branch == "duplicate":
        stream.state.sessions_seen = [session]
    elif branch == "restoration":
        stream.state.event_cycle = {
            "id": "original-event",
            "decision_date": session,
            "baseline": {"AAA": 10.0},
        }
        stream.state.journal = [
            {
                "client_order_id": "old-original-sale",
                "symbol": "AAA",
                "side": "sell",
                "qty": 5,
                "filled_qty": 5,
                "event_id": "original-event",
            }
        ]
    attempts = (
        []
        if branch == "duplicate"
        else [
            {
                "client_order_id": paper.order_id(
                    session, "AAA", "buy" if branch == "restoration" else "sell", 0
                ),
                "symbol": "AAA",
                "side": "buy" if branch == "restoration" else "sell",
                "qty": 5,
                "at": at.astimezone(UTC).isoformat(),
                "accepted": True,
                "reason": None,
                "observed_price": 100,
                "available_cash": observed["cash"],
            }
        ]
    )

    # Fix the explicit event fixture independently of current calendar publication.
    def event_decision(panel):
        return event

    # Any distribution call would falsely turn an event/duplicate into model inference.
    def forbidden(*args, **kwargs):
        raise AssertionError("No numeric distribution on event or duplicate branch")

    # Reuse the synthetic report with the actual dispatcher and action builder.
    def report(*args):
        return shown

    # Selecting a synthetic date is metadata only, with no model invocation.
    def select(day):
        return None

    monkeypatch.setattr(audit.event_risk, "decision", event_decision)
    monkeypatch.setattr(audit.continuation, "close_report", report)
    monkeypatch.setattr(stream.reader, "distribution", forbidden)
    monkeypatch.setattr(stream.reader, "select", select, raising=False)
    monkeypatch.setattr(numerical, "prefix_model", forbidden)
    value, expected = planned_target(
        policy, shown, stream.state, observed, attempts=attempts
    )
    mode = stream.nightly(value, len(shown.panel.dates) - 1, stream.state, observed)
    assert mode["path"] == (
        "already_planned" if branch == "duplicate" else "event_priority"
    )
    assert stream.counts["model"] == 0
    assert numerical.serialized(asdict(stream.state)) == expected
    assert [row["qty"] for row in stream.intents.values()] == (
        [] if branch == "duplicate" else [5]
    )


# Missing initial acknowledgments fail coverage instead of adopting an order.
def test_initial_immediate_submission_without_standalone_receipt_fails(monkeypatch):
    policy, shown = analytic_policy(grades=(1, 3))
    stream = stream_boundary()
    stream.policy, stream.reader = policy, policy.reader
    stream.panel, stream.raw = shown.panel, SimpleNamespace(grades=None, eligible=None)
    session = str(shown.panel.dates[-1])
    day = shown.panel.dates[-1].astype(object)
    at = datetime.combine(
        day, calendar.session_close(day), calendar.NEW_YORK
    ) + timedelta(minutes=1)
    observed = numerical.account(
        9000, {"AAA": 10}, {"AAA": 100}, [], records(), {"AAA": 100}
    )

    # Feed the declared synthetic daily report without constructing a broker.
    def report(*args):
        return shown

    # Keep this coverage test independent of frozen native model acceptance.
    def select(day):
        return None

    # Prefix implementation is exercised separately and in genuine native integration.
    def prefix(*args):
        return {"synthetic": True}

    monkeypatch.setattr(audit.continuation, "close_report", report)
    monkeypatch.setattr(stream.reader, "select", select, raising=False)
    monkeypatch.setattr(numerical, "prefix_model", prefix)
    value = {
        "session": session,
        "nightly": {"at": at.isoformat()},
        "paper_state": {"journal": []},
        "attempts": [],
    }
    with pytest.raises(
        ValueError, match="UNRECONSTRUCTIBLE_INITIAL_IMMEDIATE_RECEIPTS"
    ):
        stream.nightly(
            value, len(shown.panel.dates) - 1, stream.state, observed, initial=True
        )
    assert stream.counts["nights"] == 0


# A false successful cancellation cannot enter through a current allocation field.
def test_cancellation_extraction_selects_only_exact_original_receipt_fields():
    at = "2019-03-01T16:01:00-05:00"
    row = {
        "client_order_id": "old",
        "symbol": "AAA",
        "side": "buy",
        "qty": 5,
        "status": "dead",
        "terminal": True,
        "filled_qty": 0,
        "allocation_state": {"must_not_enter": True},
        "execution": {
            "created_at": at,
            "submitted_at": at,
            "canceled_at": at,
            "unrelated": True,
        },
    }
    value = {"paper_state": {"journal": [row]}}
    selected = audit.cancellation_receipts(value, {"old": {}}, {}, at)
    assert "allocation_state" not in selected["old"]
    assert set(selected["old"]["execution"]) == {
        "created_at",
        "submitted_at",
        "canceled_at",
    }
    assert row["execution"]["unrelated"]
    with pytest.raises(ValueError, match="Unconserved"):
        audit.cancellation_receipts(value, {}, {}, at)


# External archive identities and bounded decoding reject malformed original inputs.
def test_stream_archive_reading_requires_pins_and_strict_json(tmp_path):
    path = tmp_path / "initial.json.gz"
    path.write_bytes(gzip.compress(b'{"x":1,"x":2}'))
    with pytest.raises(ValueError, match="Duplicate"):
        audit.archive_value(audit.pinned(path, sha256(path.read_bytes()).hexdigest()))
    with pytest.raises(ValueError, match="Pinned"):
        audit.pinned(path, "0" * 64)
    with pytest.raises(ValueError, match="Nonfinite"):
        audit.archive_value(gzip.compress(b'{"x":NaN}'))


# Standalone initial receipts cannot be substituted with an arbitrary in-memory list.
def test_initial_receipts_require_independently_pinned_file(tmp_path):
    path = tmp_path / "receipts.json"
    path.write_text(json.dumps([{"client_order_id": "original"}]))
    receipts = audit.InitialReceipts(path, sha256(path.read_bytes()).hexdigest())
    assert receipts.attempts() == [{"client_order_id": "original"}]
    with pytest.raises(ValueError, match="standalone"):
        stream_boundary().initial(receipts=[])


# Session quote views retain global indices while storing one readonly day of prices.
def test_quote_prefix_uses_readonly_global_views_and_exact_raw_identity(
    tmp_path, monkeypatch
):
    stream = stream_boundary()
    stream.market = tmp_path
    stream.panel = SimpleNamespace(
        dates=np.array(["2019-02-28", "2019-03-01"], dtype="datetime64[D]"),
        tickers=("AAA",),
    )
    path = tmp_path / "bars_15m_sip/asof=2019-03-01/AAA.parquet"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"authenticated fixture raw source")
    stream.completion["input_sha256"] = {
        str(path): sha256(path.read_bytes()).hexdigest()
    }
    bars = [SimpleNamespace(open=100, close=101), SimpleNamespace(open=102, close=103)]

    # Return a tiny explicit complete session after its physical fixture hash passed.
    def read(*args):
        return bars, None, {"complete": "true"}

    monkeypatch.setattr(audit.intraday_sip, "read_session_full", read)
    raw = stream.quote_prefix(1)
    assert raw.observation_close.shape == (2, 25, 1)
    assert raw.session_open.shape == (2, 1)
    assert raw.observation_close.strides[0] == 0
    assert str(raw.dates[1]) == "2019-03-01"
    assert raw.tickers == ("AAA",)
    assert raw.observation_close[1, 0, 0] == 101
    assert np.isnan(raw.observation_close[1, 1, 0])
    with pytest.raises(ValueError, match="read-only"):
        raw.observation_close[1, 0, 0] = 999
    path.write_bytes(b"corrupt raw file")
    with pytest.raises(ValueError, match="Pinned"):
        stream.quote_prefix(1)
