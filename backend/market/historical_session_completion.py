"""Private synchronous observation of native final dispatch, never learned timing.

Module function replacement is confined to one isolated private process and one
non-reentrant owner. Native functions and returned verdicts are not rewritten.
"""

import hashlib
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from threading import Lock, get_ident

from backend.agents.trading.desk import intraday_orders
from backend.market import historical_conditional_market as market
from backend.market import historical_timing_packet as packet
from backend.market import live_probability_timing
from backend.market import replay_broker as native
from backend.market.alpaca_trading import AlpacaTradingError
from backend.market.historical_packet_store import StorePause

READY = intraday_orders._ready
DECIDE = intraday_orders.decide
LOCK = Lock()


# Preserve actual native account/clock evidence without applying model-only guards.
def preflight(broker, *, missing, missing_submission):
    if type(broker) is not native.ReplayBroker:
        raise ValueError("Exact private ReplayBroker preflight required")
    before = deepcopy(broker.__dict__)
    evidence = {
        "broker_clock": None,
        "native_now": None if broker._now is None else broker._now.isoformat(),
        "native_observed_at": None
        if broker._observed_at is None
        else broker._observed_at.isoformat(),
        "account": None,
        "positions": None,
        "native_error": None,
        "missing_held_marks": sorted(missing),
        "missing_submission_marks": sorted(missing_submission),
    }
    try:
        evidence["broker_clock"] = deepcopy(broker.clock())
        evidence["account"] = asdict(broker.account())
        evidence["positions"] = [asdict(row) for row in broker.positions()]
    except (AlpacaTradingError, ValueError, OSError) as error:
        evidence["native_error"] = str(error)
    if broker.__dict__ != before:
        raise StorePause("Final account preflight changed native state")
    evidence["allowed"] = (
        not missing and not missing_submission and evidence["native_error"] is None
    )
    return evidence


# Observe each original final verdict after native annotations and before transport.
def dispatch(*, root, rows, now, context, source_sha256, factory, freeze):  # noqa: C901 -- The synchronous observation boundary remains visible.
    data = market.read_context(context)
    expected = deepcopy(rows)
    if (
        data["phase"] != "SESSION_COMPLETION_MARKET"
        or packet.nanos(now.isoformat())
        != packet.nanos(data["window"]["assumed_decision_at"])
        or hashlib.sha256(Path(intraday_orders.__file__).read_bytes()).hexdigest()
        != source_sha256
        or intraday_orders._ready is not READY
        or intraday_orders.decide is not DECIDE
        or not rows
        or any(
            r.get("timing_policy") != live_probability_timing.POLICY
            or "execution_policy" in r
            or r.get("event_id")
            or r.get("sent")
            or r.get("sending")
            for r in rows
        )
        or len({r["client_order_id"] for r in rows}) != len(rows)
    ):
        raise ValueError("Exact native ordinary final invocation required")
    if not LOCK.acquire(blocking=False):
        raise StorePause("Nested/concurrent final observer refused")
    owner, ready_calls, deciding, frozen = get_ident(), 0, False, False
    observed = []

    # Check owner and original installed wrapper identities at every interception.
    def owned():
        if (
            get_ident() != owner
            or intraday_orders._ready is not ready
            or intraday_orders.decide is not decide
        ):
            raise StorePause("Concurrent or changed final observer functions")

    # Retain the exact native verdict reference until its final annotations exist.
    def decide(row, latch, quote, instant, session):
        owned()
        if (
            not deciding
            or instant != now
            or session != now.astimezone(intraday_orders.NEW_YORK).date()
            or len(observed) >= len(expected)
            or row != expected[len(observed)]
            or quote is not None
        ):
            raise StorePause("Inexact or repeated native final decision")
        verdict = DECIDE(row, latch, quote, instant, session)
        observed.append((row, verdict))
        return verdict

    # Freeze references only after original _ready applies final annotations.
    def ready(
        actual,
        folder,
        snapshot,
        instant,
        session,
        timing_reader=None,
        observation_sink=None,
    ):
        nonlocal ready_calls, deciding, frozen
        owned()
        ready_calls += 1
        if (
            ready_calls != 1
            or deciding
            or actual != expected
            or Path(folder) != Path(root)
            or snapshot != {"quotes": {}}
            or instant != now
            or session != now.astimezone(intraday_orders.NEW_YORK).date()
            or timing_reader is not None
        ):
            raise StorePause("Inexact or repeated native final ready invocation")
        deciding = True
        try:
            result = READY(
                actual,
                folder,
                snapshot,
                instant,
                session,
                timing_reader,
                observation_sink,
            )
        finally:
            deciding = False
        if len(observed) != len(expected) or any(
            verdict.get("send") not in (None, intraday_orders.MARKET)
            or verdict.get("timed", {}).get("reason") != "Session completion"
            or verdict["timed"].get("level") is not None
            or verdict["timed"].get("level_fraction") is not None
            or "forward_receipt" in verdict["timed"]
            for _, verdict in observed
        ):
            raise StorePause("Incomplete or inexact native final verdict set")
        expected_ready = [(r, v) for r, v in observed if v["send"]]
        if len(result) != len(expected_ready) or any(
            r is not er or v is not ev
            for (r, v), (er, ev) in zip(result, expected_ready, strict=True)
        ):
            raise StorePause("Native final readiness identity differs")
        freeze(
            {
                "classification": "NOT_MODEL_TIMED",
                "snapshot_boundary": "AFTER_NATIVE_READY_BEFORE_FACTORY",
                "native_ready_calls": ready_calls,
                "native_decide_calls": len(observed),
                "verdicts": [
                    {"client_order_id": r["client_order_id"], "verdict": deepcopy(v)}
                    for r, v in observed
                ],
            }
        )
        owned()
        frozen = True
        return result

    # Permit transport only after the complete annotated verdict set is committed.
    def guarded_factory():
        owned()
        if not frozen or deciding or ready_calls != 1:
            raise StorePause("Native final decision not frozen before factory")
        return factory()

    intraday_orders._ready, intraday_orders.decide = ready, decide
    try:
        logs = intraday_orders.send_due(root, {"quotes": {}}, now, guarded_factory)
        owned()
        if not frozen:
            raise StorePause("Native final observation did not complete")
        return logs
    finally:
        changed = (
            intraday_orders._ready is not ready or intraday_orders.decide is not decide
        )
        intraday_orders._ready, intraday_orders.decide = READY, DECIDE
        LOCK.release()
        if changed:
            raise StorePause(
                "Native final function identities changed; originals restored"
            )
