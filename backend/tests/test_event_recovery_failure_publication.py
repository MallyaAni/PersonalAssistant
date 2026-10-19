"""Publish recovery failures without inventing an account or policy observation."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.agents.trading.desk import paper
from backend.cli import market_event_recovery as recovery
from backend.market import alpaca_trading, event_status

LATEST = {"session": "2026-10-16"}
POLICY = {
    "session": LATEST["session"],
    "factor": 0.5,
    "calendar_known": True,
    "decision_date": "2099-12-16",
}
PRIVATE_ERROR = "synthetic-provider-detail-must-not-be-published"


# Keep a real serialized native account whose bytes and original inode can be checked.
def native_account(root, active=False):
    state = paper.PaperState(
        order_seq=7,
        history=[{"note": "Synthetic Unicode \u2603", "value": float("nan")}],
        event_cycle={"id": "synthetic-event"} if active else {},
    )
    path = paper.save_state(root, state)
    before = path.stat()
    identity = (
        before.st_dev, before.st_ino, before.st_uid, before.st_gid,
        before.st_mode, before.st_size, before.st_mtime_ns,
    )
    return path, path.read_bytes(), identity


# Assert failure reporting never rewrites the authoritative account.
def assert_native_unchanged(original):
    path, raw, identity = original
    after = path.stat()
    assert path.read_bytes() == raw
    assert (
        after.st_dev, after.st_ino, after.st_uid, after.st_gid,
        after.st_mode, after.st_size, after.st_mtime_ns,
    ) == identity


# Read the actual published JSON rather than relying on a mocked writer call.
def published(root, result):
    path = root / "desk" / "event-live.json"
    raw = path.read_text(encoding="utf-8")
    assert json.loads(raw) == result
    assert PRIVATE_ERROR not in raw
    assert not path.with_suffix(".tmp").exists()
    assert datetime.fromisoformat(result["as_of"]).tzinfo is not None
    return json.loads(raw)


# Stop before policy or broker work while exercising the complete publication wrapper.
def fail_before_policy(monkeypatch):
    calls = []

    # Represent the original local history failure, not a secondary state failure.
    def unavailable_panel(*args, **kwargs):
        calls.append("panel")
        raise OSError(PRIVATE_ERROR)

    # Refuse accidental client construction after the policy input already failed.
    def no_client():
        pytest.fail("An unavailable policy must not construct a broker client")

    monkeypatch.setattr(recovery, "activated", lambda root: True)
    monkeypatch.setattr(recovery, "book_panel", unavailable_panel)
    monkeypatch.setattr(recovery.alpaca_trading, "client_from_env", no_client)
    return calls


# Supply an explicit synthetic policy without reading market artifacts or credentials.
def prepared_policy(monkeypatch, client):
    monkeypatch.setattr(recovery, "activated", lambda root: True)
    monkeypatch.setattr(
        recovery, "book_panel",
        lambda *args: (SimpleNamespace(dates=[LATEST["session"]]), None),
    )
    monkeypatch.setattr(recovery.event_risk, "decision", lambda panel: deepcopy(POLICY))
    monkeypatch.setattr(recovery.alpaca_trading, "client_from_env", lambda: client)


class UnavailableClock:
    base_url = alpaca_trading.PAPER_URL

    # Record the sole broker read and stop before any reconciliation or submission.
    def __init__(self):
        self.calls = []

    # Model a failed clock observation without producing an execution response.
    def clock(self):
        self.calls.append("clock")
        raise OSError(PRIVATE_ERROR)


# A denied secondary read must not replace the original failure or invent inactive state.
def test_original_error_publishes_when_secondary_native_read_is_denied(tmp_path, monkeypatch):
    original = native_account(tmp_path, active=True)
    calls = fail_before_policy(monkeypatch)
    state_reads = []

    # Inject denied access at the exact handler read while retaining the real native file.
    def denied_state(root):
        state_reads.append(root)
        raise PermissionError(PRIVATE_ERROR)

    monkeypatch.setattr(paper, "load_state", denied_state)
    result = recovery.run(tmp_path, LATEST, {})
    saved = published(tmp_path, result)
    assert saved["status"] == "recovery unavailable"
    assert saved["error_type"] == "OSError"
    assert saved["state_error_type"] == "PermissionError"
    assert set(saved) == {"as_of", "status", "error_type", "state_error_type"}
    assert state_reads == [tmp_path]
    assert calls == ["panel"]
    assert_native_unchanged(original)


# Readable native state supplies an actual boolean even when no policy was computed.
@pytest.mark.parametrize("active", [False, True])
def test_failure_retains_authoritative_readable_cycle(tmp_path, monkeypatch, active):
    original = native_account(tmp_path, active=active)
    calls = fail_before_policy(monkeypatch)
    result = recovery.run(tmp_path, LATEST, {})
    saved = published(tmp_path, result)
    assert saved["active"] is active
    assert saved["error_type"] == "OSError"
    assert set(saved) == {"as_of", "status", "error_type", "active"}
    assert calls == ["panel"]
    assert_native_unchanged(original)


# Keep the genuinely calculated policy when the real recovery's first broker read fails.
def test_computed_policy_survives_later_recovery_failure(tmp_path, monkeypatch):
    original = native_account(tmp_path)
    client = UnavailableClock()
    prepared_policy(monkeypatch, client)
    result = recovery.run(tmp_path, LATEST, {})
    saved = published(tmp_path, result)
    assert saved["policy"] == POLICY
    assert saved["active"] is False
    assert saved["error_type"] == "OSError"
    assert "state_error_type" not in saved
    assert client.calls == ["clock"]
    assert event_status.load(tmp_path)["planning_paused"] is True
    assert_native_unchanged(original)


# The real recovery and its handler can both encounter denied state without losing the record.
def test_original_state_denial_is_published_without_broker_effects(tmp_path, monkeypatch):
    original = native_account(tmp_path)
    client = UnavailableClock()
    prepared_policy(monkeypatch, client)
    state_reads = []

    # Simulate the same inaccessible account on the original and bounded handler lookup.
    def denied_state(root):
        state_reads.append(root)
        raise PermissionError(PRIVATE_ERROR)

    monkeypatch.setattr(paper, "load_state", denied_state)
    saved = published(tmp_path, recovery.run(tmp_path, LATEST, {}))
    assert saved["policy"] == POLICY
    assert saved["error_type"] == saved["state_error_type"] == "PermissionError"
    assert not {"active", "pending_orders", "sold", "cycle"} & set(saved)
    assert state_reads == [tmp_path, tmp_path]
    assert client.calls == []
    assert_native_unchanged(original)


# A newly published failed observation cannot clear planning while no cycle is recorded.
def test_fresh_unavailable_publication_pauses_without_rewriting_nightly(tmp_path, monkeypatch):
    original = native_account(tmp_path)
    fail_before_policy(monkeypatch)
    published(tmp_path, recovery.run(tmp_path, LATEST, {}))
    nightly = {"session": LATEST["session"], "event_risk": {"factor": 1.0}}
    prior = deepcopy(nightly)
    status = event_status.load(tmp_path)
    assert status["active"] is False
    assert status["stale"] is False
    assert status["planning_paused"] is True
    assert event_status.for_planning(nightly, tmp_path)["event_risk"]["execution_pending"] is True
    assert nightly == prior
    assert_native_unchanged(original)


# Keep the existing fresh-policy and stale-cycle rules outside this new failure condition.
@pytest.mark.parametrize(
    ("active", "stale", "status", "policy", "paused"),
    [
        (False, False, "monitoring", {"factor": 1.0}, False),
        (False, False, "fresh completed prices required", {"factor": 0.5}, True),
        (False, True, "recovery unavailable", None, False),
        (True, True, "recovery unavailable", None, True),
    ],
)
def test_existing_planning_freshness_controls_remain_bounded(
    tmp_path, active, stale, status, policy, paused,
):
    original = native_account(tmp_path, active=active)
    folder = tmp_path / "desk"
    folder.mkdir()
    record = {
        "as_of": (datetime.now(UTC) - timedelta(seconds=901 if stale else 0)).isoformat(),
        "status": status,
    }
    if policy is not None:
        record["policy"] = policy
    (folder / "event-live.json").write_text(json.dumps(record), encoding="utf-8")
    observed = event_status.load(tmp_path)
    assert observed["active"] is active
    assert observed["stale"] is stale
    assert observed["planning_paused"] is paused
    nightly = {"event_risk": {"execution_pending": True}}
    assert event_status.for_planning(nightly, tmp_path)["event_risk"]["execution_pending"] is paused
    assert nightly == {"event_risk": {"execution_pending": True}}
    assert_native_unchanged(original)


# Reporting remains failed if its own output cannot be written; do not report fake success.
def test_status_write_failure_propagates_and_preserves_account(tmp_path, monkeypatch):
    original = native_account(tmp_path)
    fail_before_policy(monkeypatch)
    real_write = Path.write_text
    pending = tmp_path / "desk" / "event-live.tmp"

    # Fail only the synthetic status output and leave all native paths untouched.
    def denied_output(path, *args, **kwargs):
        if path == pending:
            raise OSError("synthetic status output failure")
        return real_write(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", denied_output)
    with pytest.raises(OSError, match="synthetic status output failure"):
        recovery.run(tmp_path, LATEST, {})
    assert not (tmp_path / "desk" / "event-live.json").exists()
    assert_native_unchanged(original)


# An old activation cannot publish or execute after its source binding changes.
def test_changed_execution_activation_refuses_before_work(tmp_path, monkeypatch):
    original = native_account(tmp_path)
    recovery.activate(tmp_path)
    enabled = (tmp_path / "desk" / "event-recovery-enabled.json").read_bytes()
    monkeypatch.setattr(recovery, "execution_hash", lambda: "changed-synthetic-source")

    # Prevent a false pass if the source guard ever permits policy construction.
    def no_panel(*args, **kwargs):
        pytest.fail("An obsolete activation must stop before policy construction")

    monkeypatch.setattr(recovery, "book_panel", no_panel)
    assert recovery.run(tmp_path, LATEST, {}) == {"status": "waiting for gated deployment"}
    assert (tmp_path / "desk" / "event-recovery-enabled.json").read_bytes() == enabled
    assert not (tmp_path / "desk" / "event-live.json").exists()
    assert_native_unchanged(original)


# The public status reader still requires authoritative native state rather than assuming inactive.
def test_status_reader_does_not_convert_denied_state_to_inactive(tmp_path, monkeypatch):
    original = native_account(tmp_path)

    # Retain the explicit API-read failure instead of bypassing inaccessible native state.
    def denied_state(root):
        raise PermissionError("synthetic authoritative state unavailable")

    monkeypatch.setattr(paper, "load_state", denied_state)
    with pytest.raises(PermissionError, match="synthetic authoritative state unavailable"):
        event_status.load(tmp_path)
    assert_native_unchanged(original)
