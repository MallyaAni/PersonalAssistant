"""Original pending metadata conservation never certifies live timing correctness."""

import gzip
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import UTC
from hashlib import sha256
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.cli import market_daily
from backend.market import entry_timing
from backend.market import live_model_history_pending_audit as audit
from backend.market.live_model_history_nightly_model import serialized


# Encode one private fixture under an externally selected exact archive digest.
def evidence(value):
    raw = gzip.compress(json.dumps(value).encode(), mtime=0)
    return audit.OriginalProxyEvidence(
        raw, sha256(raw).hexdigest(), audit.ORIGINAL_SOURCES
    )


# Build independent funded rows and literal old sender receipts without executing them.
def fixture(*, crossing=False):
    session = "2019-03-01"
    names = ("AAA", "BBB", "CCC", "DDD")
    raw = SimpleNamespace(
        dates=np.array([session], dtype="datetime64[D]"),
        tickers=names,
        session_open=np.full((1, 4), 100.0),
        observation_close=np.full((1, 25, 4), 100.0),
    )
    if crossing:
        raw.observation_close[0, 3, 2] = 98.0
    state = paper.PaperState(
        sessions_seen=["2019-02-28"],
        order_seq=4,
        allocation_state={"original": "recomputed-not-saved-target-input"},
        journal=[{"original": "journal untouched"}],
        history=[{"original": "history untouched"}],
    )
    for name in names:
        state.pending.append(
            {
                "client_order_id": name,
                "symbol": name,
                "side": "buy",
                "qty": 5,
                "session": "2019-02-28",
                "execute_on": session,
                "execution_timing": "dip_or_close",
                "timing_policy": audit.POLICY,
                "execution": {"decision_at": "2019-02-28T16:01:00-05:00"},
            }
        )
    value = {
        "session": session,
        "forecast_decisions": [],
        "observations": [],
        "attempts": [],
        "paper_state": {"MUST_NOT_BE_READ": True},
        "actions": [{"MUST_NOT_BE_READ": True}],
    }
    accepted, expected, latches = {}, deepcopy(state), {}
    clock = entry_timing.session_clock(raw.dates[0].astype(object))
    for slot in range(25):
        now = clock["open"] + (slot + 1) * entry_timing.BAR
        due = [row for row in expected.pending if not row.get("sent")]
        if not due:
            continue
        value["observations"].append(
            {"at": now.isoformat(), "due": serialized(deepcopy(due)), "sender_logs": []}
        )
        for row in due:
            name = row["symbol"]
            close = float(raw.observation_close[0, slot, names.index(name)])
            quote = {
                "open": 100.0,
                "last": close,
                "bar": (now - entry_timing.BAR).isoformat(),
                "as_of": now.isoformat(),
            }
            latches[name] = entry_timing._merge(
                latches.get(name), 100.0, close, now - entry_timing.BAR, now.isoformat()
            )
            early = name == "AAA" or name == "BBB"
            state_word = (
                "execute" if early else "wait" if name == "CCC" else "unavailable"
            )
            if now < clock["final"]:
                trace = {
                    "policy": audit.POLICY,
                    "intent_id": name,
                    "symbol": name,
                    "side": "buy",
                    "desired_qty": 5,
                    "observed_qty": 5,
                    "observed_price": close,
                    "day": 0,
                    "clock": slot,
                    "at": now.isoformat(),
                    "state": state_word,
                }
                value["forecast_decisions"].append(trace)
                timed = {
                    **trace,
                    "open": 100.0,
                    "trigger_bar": quote["bar"],
                    "trigger_price": close,
                }
            else:
                timed = entry_timing.timing(
                    latches[name], quote, "buy", now, raw.dates[0].astype(object)
                )
                timed.update(
                    level=None,
                    level_fraction=None,
                    policy=audit.POLICY,
                    reason="Session completion",
                )
            if not early and now < clock["final"]:
                continue
            refused = name == "BBB" and slot == 0
            attempt = {
                "client_order_id": name,
                "symbol": name,
                "side": "buy",
                "qty": 5,
                "at": now.astimezone(UTC).isoformat(),
                "accepted": not refused,
                "reason": "insufficient_reserved_cash" if refused else None,
                "observed_price": 100.0,
                "available_cash": 10000.0,
            }
            value["attempts"].append(attempt)
            row["sending"] = now.isoformat(timespec="seconds")
            if refused:
                row["send_error"] = "insufficient_reserved_cash"
            else:
                accepted[name] = attempt
                row["sent"] = {
                    **intraday_orders._why_sent(timed, "market", now),
                    "qty": 5,
                }
                row.pop("send_error", None)
                row["execution"].update(
                    created_at=attempt["at"],
                    submitted_at=attempt["at"],
                    time_in_force="day",
                )
    return state, expected, value, accepted, raw


# Original verdict states preserve literal mutations and all prior controls.
def test_mixed_original_pending_receipts_reconstruct_metadata_without_reconciliation():
    previous, expected, value, accepted, raw = fixture()
    originals = deepcopy((previous, value, accepted))
    outcomes = {
        "AAA": {
            "client_order_id": "AAA",
            "requested_qty": 5,
            "status": "filled",
            "filled_qty": 5,
        }
    }
    actual, scope = audit.fold_pending(
        previous,
        evidence(value),
        accepted,
        outcomes,
        raw,
        0,
        value["session"],
        conserved_attempts=value["attempts"],
    )
    assert actual == expected
    assert len(actual.pending) == 4
    assert actual.journal == previous.journal
    assert actual.history == previous.history
    assert scope["scope"] == "pending_metadata_receipt_conservation_only"
    assert (
        scope["current_live_timing_parity"] == "FAILED_SEPARATE_ORIGINAL_PATH_CONTRACT"
    )
    assert scope["model_provider_sender_broker_calls"] == 0
    assert (previous, value, accepted) == originals


# Forged archive identity or another producer cannot authenticate the old proxy trace.
def test_archive_and_producer_source_bindings_are_exact():
    _, _, value, _, _ = fixture()
    raw = gzip.compress(json.dumps(value).encode(), mtime=0)
    with pytest.raises(ValueError, match="bytes differ"):
        audit.OriginalProxyEvidence(raw, "0" * 64, audit.ORIGINAL_SOURCES)
    with pytest.raises(ValueError, match="proxy sources"):
        audit.OriginalProxyEvidence(raw, sha256(raw).hexdigest(), {})


# A pinned digest and its original bytes cannot be reassigned together after admission.
def test_original_archive_identity_is_immutable():
    _, _, value, _, _ = fixture()
    pinned = evidence(value)
    with pytest.raises(FrozenInstanceError):
        pinned._archive = b"replacement"
    with pytest.raises(FrozenInstanceError):
        pinned.sha256 = "0" * 64


# Bounded expansion refuses compressed excess before decoding arbitrary saved state.
def test_original_gzip_expansion_is_bounded(monkeypatch):
    _, _, value, _, _ = fixture()
    pinned = evidence(value)
    monkeypatch.setattr(audit, "MAX_JSON_BYTES", 128, raising=False)
    with pytest.raises(ValueError, match="ARCHIVE_SIZE"):
        pinned.records(value["session"])


# Nonfinite literals and overflowed exponents are invalid even under a pinned digest.
@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e9999"])
def test_original_json_nonfinite_numbers_are_rejected(literal):
    text = (
        '{"session":"2019-03-01","forecast_decisions":[],"observations":[],"attempts":[],"invalid":'
        + literal
        + "}"
    )
    archive = gzip.compress(text.encode(), mtime=0)
    pinned = audit.OriginalProxyEvidence(
        archive, sha256(archive).hexdigest(), audit.ORIGINAL_SOURCES
    )
    with pytest.raises(ValueError, match="Nonfinite"):
        pinned.records("2019-03-01")


# Boolean and out-of-range indexes cannot silently select another raw-array shape.
@pytest.mark.parametrize("day", [True, False, -1, 1, 0.0])
def test_raw_day_identity_is_an_exact_in_range_integer(day):
    previous, _, value, accepted, raw = fixture()
    with pytest.raises(ValueError, match="integer original raw day"):
        audit.fold_pending(
            previous,
            evidence(value),
            accepted,
            {},
            raw,
            day,
            value["session"],
            conserved_attempts=value["attempts"],
        )


# True cannot equal a one-dollar price at the original evidence admission boundary.
def test_original_price_rejects_boolean_before_numeric_equality():
    previous, _, value, _, _ = fixture()
    trace = value["forecast_decisions"][0]
    trace["observed_price"] = True
    now = entry_timing._instant(trace["at"])
    with pytest.raises(ValueError, match="positive finite original legacy price"):
        audit.proxy_timed(
            previous.pending[0], trace, {"last": 1.0, "open": 1.0}, now, 0, 0
        )


# Source-bound original trace remains a comparison receipt, never a fresh judgement.
@pytest.mark.parametrize(
    "change",
    [
        "qty",
        "price",
        "duplicate",
        "missing",
        "future",
        "forward",
        "due_float",
        "unknown_attempt",
        "no_attempt",
    ],
)
def test_original_pending_corruptions_fail_closed(change):
    previous, _, value, accepted, raw = fixture()
    if change == "qty":
        value["forecast_decisions"][0]["desired_qty"] = 6
    elif change == "price":
        value["forecast_decisions"][0]["observed_price"] = 101.0
    elif change == "duplicate":
        value["forecast_decisions"].append(value["forecast_decisions"][0])
    elif change == "missing":
        value["forecast_decisions"].pop(0)
    elif change == "future":
        value["forecast_decisions"][0]["at"] = "2019-03-04T09:45:00-05:00"
    elif change == "forward":
        value["forecast_decisions"][0]["forward_receipt"] = {"not": "legacy"}
    elif change == "due_float":
        value["observations"][0]["due"][0]["qty"] = 5.0
    elif change == "unknown_attempt":
        value["attempts"][0]["client_order_id"] = "unknown"
    elif change == "no_attempt":
        value["attempts"].pop(0)
    with pytest.raises(
        ValueError,
        match="differ|required|missing|quantity|identity|lacks|UNRECONSTRUCTIBLE",
    ):
        audit.fold_pending(
            previous,
            evidence(value),
            accepted,
            {},
            raw,
            0,
            value["session"],
            conserved_attempts=value["attempts"],
        )


# A terminal broker fact cannot erase pending or roll back controls before reconcile.
def test_terminal_facts_and_withdrawal_selection_do_not_settle_pending():
    previous, expected, value, accepted, raw = fixture()
    outcomes = {
        name: {
            "client_order_id": name,
            "requested_qty": 5,
            "status": "expired",
            "filled_qty": 0,
        }
        for name in accepted
    }
    result, _ = audit.fold_pending(
        previous,
        evidence(value),
        accepted,
        outcomes,
        raw,
        0,
        value["session"],
        conserved_attempts=value["attempts"],
    )
    assert result == expected
    assert result.order_seq == previous.order_seq
    assert result.sessions_seen == previous.sessions_seen
    assert all("status" not in row for row in result.pending)
    assert market_daily._ids_to_withdraw(result, value["session"]) == [
        "AAA",
        "BBB",
        "CCC",
        "DDD",
    ]
    assert result == expected


# Authenticated archive refusals must also belong to the separately conserved batch.
def test_refused_attempt_cannot_enter_from_archival_bytes_alone():
    previous, _, value, accepted, raw = fixture()
    admitted = [row for row in value["attempts"] if row["accepted"]]
    with pytest.raises(ValueError, match="conserved original attempt"):
        audit.fold_pending(
            previous,
            evidence(value),
            accepted,
            {},
            raw,
            0,
            value["session"],
            conserved_attempts=admitted,
        )


# A new nightly request stays outside this old intraday metadata acceptance scope.
def test_new_nightly_request_is_deferred_without_becoming_a_pending_input():
    previous, expected, value, accepted, raw = fixture()
    conserved = deepcopy(value["attempts"])
    value["attempts"].append(
        {
            "client_order_id": "new-nightly-not-a-prior-intent",
            "at": "2019-03-01T16:01:00-05:00",
        }
    )
    derived, scope = audit.fold_pending(
        previous,
        evidence(value),
        accepted,
        {},
        raw,
        0,
        value["session"],
        conserved_attempts=conserved,
    )
    assert derived == expected
    assert scope["new_nightly_attempts_not_validated_here"] == 1


# A missing raw prefix has an explicit coverage failure rather than invented metadata.
def test_missing_raw_prefix_fails_with_scoped_coverage_reason():
    previous, _, value, accepted, raw = fixture()
    raw.observation_close = None
    with pytest.raises(ValueError, match="UNRECONSTRUCTIBLE_RAW_PREFIX"):
        audit.fold_pending(
            previous,
            evidence(value),
            accepted,
            {},
            raw,
            0,
            value["session"],
            conserved_attempts=value["attempts"],
        )


# Missing complete raw prefixes cannot be replaced with a fabricated fallback latch.
def test_final_fallback_refuses_a_changed_earlier_raw_prefix():
    previous, _, value, accepted, raw = fixture()
    raw.observation_close[0, 3, 2] = 98.0
    with pytest.raises(ValueError, match="raw prefix"):
        audit.fold_pending(
            previous,
            evidence(value),
            accepted,
            {},
            raw,
            0,
            value["session"],
            conserved_attempts=value["attempts"],
        )


# The final historical label comes from the complete original prefix, not a new rule.
def test_final_fallback_retains_the_original_earliest_raw_crossing_metadata():
    previous, expected, value, accepted, raw = fixture(crossing=True)
    actual, _ = audit.fold_pending(
        previous,
        evidence(value),
        accepted,
        {},
        raw,
        0,
        value["session"],
        conserved_attempts=value["attempts"],
    )
    assert actual == expected
    row = next(row for row in actual.pending if row["symbol"] == "CCC")
    assert row["sent"]["state"] == "triggered"
    assert row["sent"]["trigger_bar"] == "2019-03-01T10:15:00-05:00"
    assert row["sent"]["level"] is None


# All first-account failure reasons compare the entire unreconciled durable snapshot.
@pytest.mark.parametrize(
    "problem",
    [
        "unknown_distribution_cash_in_lieu",
        "unknown_consolidation_cash_in_lieu",
        "unknown_exchange_cash_in_lieu",
        "missing_held_close",
    ],
)
def test_unavailable_account_retains_full_original_pending_and_controls(problem):
    previous, _, source, accepted, raw = fixture()
    derived, _ = audit.fold_pending(
        previous,
        evidence(source),
        accepted,
        {},
        raw,
        0,
        source["session"],
        conserved_attempts=source["attempts"],
    )
    observed = {
        "problem": problem,
        **({"missing_symbols": ["AAA"]} if problem == "missing_held_close" else {}),
    }
    reasons = {
        "unknown_distribution_cash_in_lieu": (
            "Unknown distribution cash-in-lieu prevents full NAV"
        ),
        "unknown_consolidation_cash_in_lieu": (
            "Unknown consolidation cash-in-lieu prevents full NAV"
        ),
        "unknown_exchange_cash_in_lieu": (
            "Unknown exchange cash-in-lieu prevents full NAV"
        ),
        "missing_held_close": "Fresh raw held mark unavailable for AAA",
    }
    at = "2019-03-01T16:01:00-05:00"
    target = {
        "session": source["session"],
        "new_intents": [],
        "paper_state": serialized(vars(derived)),
        "nightly": {
            "session": source["session"],
            "at": at,
            "text": "",
            "status": "nightly_broker_unavailable",
            "reason": reasons[problem],
        },
    }
    mode = audit.compare_unavailable(
        target, previous, derived, observed, {"AAA": 5}, source["session"], at
    )
    assert not mode["model_required"]
    assert not mode["model_invoked"]
    for change in (
        "journal",
        "pending",
        "policy",
        "entry",
        "reason",
        "new_intents",
        "count_float",
    ):
        bad = deepcopy(target)
        if change == "journal":
            bad["paper_state"]["journal"] = []
        elif change == "pending":
            bad["paper_state"]["pending"] = []
        elif change in ("policy", "entry"):
            bad["nightly"]["persisted_policy" if change == "policy" else "entry"] = {}
        elif change == "reason":
            bad["nightly"]["reason"] = "fabricated missing state"
        elif change == "new_intents":
            bad["new_intents"] = [{"qty": 1}]
        else:
            bad["paper_state"]["order_seq"] = 4.0
        with pytest.raises(ValueError, match="differ|integer|lengths|value"):
            audit.compare_unavailable(
                bad, previous, derived, observed, {"AAA": 5}, source["session"], at
            )
