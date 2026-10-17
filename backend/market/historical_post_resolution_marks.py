"""Unused conditional mark selector; no observation, NAV, fill or broker mutation.

The separate addendum declares mark observation at T+33.101s and previous
observation uncertainty of symmetric1ms. Both are hypothetical clock domains,
not recovered historical receive/publication times or measured clock accuracy.
"""

import math
from copy import deepcopy
from datetime import datetime

from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_parser as parser
from backend.market import historical_packet_registry as registry
from backend.market import historical_timing_packet as timing
from backend.market import replay_broker as native

PRIOR_OBSERVATION_UNCERTAINTY_NS = 1_000_000


# Canonicalize exact native state including tuple action keys and aware clocks.
def _plain(value):
    kind = type(value)
    if kind is datetime:
        return ["datetime", native._instant(value).isoformat()]
    if kind is dict:
        pairs = [[_plain(k), _plain(v)] for k, v in value.items()]
        return ["dict", sorted(pairs, key=lambda row: demand.encoded(row[0]))]
    if kind in (list, tuple):
        return [kind.__name__, [_plain(item) for item in value]]
    if kind not in (str, int, float, bool, type(None)):
        raise ValueError("Unsupported native state type")
    if kind is float and not math.isfinite(value):
        raise ValueError("Nonfinite native state")
    return [kind.__name__, value]


# Bind all exact private broker state without reading account NAV or changing marks.
def state_binding(broker):
    if type(broker) is not native.ReplayBroker:
        raise ValueError("Exact ReplayBroker required")
    return timing._digest(_plain(broker.__dict__))


# Preserve native fractional shares and nullable nonnegative acquisition bases.
def _holdings(ledger):
    held, averages = ledger["holdings"], ledger["average_prices"]
    if set(held) != set(averages):
        raise ValueError("Native holding and basis keys differ")
    required = {}
    for name, quantity in held.items():
        registry.symbol(name)
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, (int, float))
            or not math.isfinite(quantity)
            or quantity < 0
        ):
            raise ValueError("Finite native nonnegative held shares required")
        basis = averages[name]
        if basis is not None and (
            isinstance(basis, bool)
            or not isinstance(basis, (int, float))
            or not math.isfinite(basis)
            or basis < 0
        ):
            raise ValueError("Nullable native nonnegative acquisition basis required")
        if quantity > 0:
            required[name] = quantity
    return required


# Derive distinct prior-observation, resolution and proposed mark-observation clocks.
def _clocks(broker, ledger, window):
    if broker._now is None or broker._observed_at is None:
        raise ValueError(
            "Original native current and prior observation clocks required"
        )
    observed = timing.nanos(broker._observed_at.isoformat())
    now = timing.nanos(broker._now.isoformat())
    if ledger["observed_at"] != broker._observed_at.isoformat():
        raise ValueError("Ledger and native prior observation clocks differ")
    allowed = {
        timing.nanos(window["assumed_decision_at"]),
        timing.nanos(window["assumed_submission_at"]),
    }
    if observed not in allowed:
        raise ValueError(
            "Original current-window decision/submission observation required"
        )
    mark = (
        timing.nanos(window["quote_end"])
        + timing.FIXED["event_timestamp_uncertainty_ns"]
        + timing.FIXED["quote_receive_delay_ns"]
    )
    if not observed <= now < mark:
        raise ValueError("Proposed mark clock must strictly advance native clock")
    return {
        "previous_observed_at": broker._observed_at.isoformat(),
        "previous_observation_upper_at": timing.stamp(
            observed + PRIOR_OBSERVATION_UNCERTAINTY_NS
        ),
        "previous_observation_uncertainty_ns": PRIOR_OBSERVATION_UNCERTAINTY_NS,
        "native_current_clock": broker._now.isoformat(),
        "assumed_mark_observation_at": timing.stamp(mark),
        "actual_historical_receive_publication_at": None,
        "clock_basis": "DECLARED_CONDITIONAL_CLOCKS_NOT_MEASURED_ACCURACY",
    }


# Select the latest time-eligible fresh quote before testing its book, with no fallback.
def _mark(rows, clocks, source_sha256):
    tolerance = timing.FIXED["event_timestamp_uncertainty_ns"]
    prior_upper = timing.nanos(clocks["previous_observation_upper_at"])
    mark_clock = timing.nanos(clocks["assumed_mark_observation_at"])
    eligible = [
        row
        for row in rows
        if timing.nanos(row["t"]) - tolerance > prior_upper
        and timing.nanos(row["t"]) + tolerance + timing.FIXED["quote_receive_delay_ns"]
        <= mark_clock
    ]
    if not eligible:
        return {
            "status": "MISSING",
            "reason": "No conservatively fresh quote before mark observation",
            "price": None,
        }
    latest = max(timing.nanos(row["t"]) for row in eligible)
    cluster = [row for row in eligible if timing.nanos(row["t"]) == latest]
    if not timing._unique(cluster) or not timing._book(cluster[0]):
        return {
            "status": "MISSING",
            "reason": "Latest quote conflicting/unqualified; no older fallback",
            "price": None,
        }
    row = cluster[0]
    return {
        "status": "CANDIDATE",
        "reason": "Latest qualified fresh midpoint; not fill price",
        "price": row["bp"] / 2 + row["ap"] / 2,
        "raw_quote": deepcopy(row),
        "raw_event_at": row["t"],
        "event_lower_at": timing.stamp(latest - tolerance),
        "event_upper_at": timing.stamp(latest + tolerance),
        "assumed_receive_upper_at": timing.stamp(
            latest + tolerance + timing.FIXED["quote_receive_delay_ns"]
        ),
        "source_sha256": source_sha256,
        "liquidity_capacity_shares": None,
    }


# Return every actual positive holding's candidate mark without observing or valuing it.
def select(broker, *, expected_state_sha256, packet, manifest, entity_registry):
    registry.digest(expected_state_sha256)
    if state_binding(broker) != expected_state_sha256:
        raise ValueError("Original current native state binding differs")
    before = deepcopy(broker.__dict__)
    ledger = broker.ledger()
    held = _holdings(ledger)
    declaration = demand.read(manifest, entity_registry)
    if broker.cost_bps != 10 or not set(held) <= set(declaration["potential_holdings"]):
        raise ValueError("Actual resulting holdings exceed frozen request coverage")
    clocks = _clocks(broker, ledger, declaration["window"])
    captured = parser.read(packet, manifest, entity_registry)
    identities = registry.admit(entity_registry, held)
    details = {}
    for query in declaration["queries"]:
        if query["kind"] != "quotes":
            continue
        group = captured["groups"][query["sha256"]]
        for name in set(query["cohort_keys"]) & set(held):
            details[name] = _mark(
                group[identities[name]["query_symbol"]]["rows"], clocks, packet.sha256
            )
    if set(details) != set(held):
        raise ValueError(
            "Every actual resulting holding requires a finalized quote group"
        )
    missing = sorted(
        name for name, row in details.items() if row["status"] != "CANDIDATE"
    )
    if broker.__dict__ != before or state_binding(broker) != expected_state_sha256:
        raise ValueError("Native state changed during pure mark selection")
    return {
        "schema": "conditional-post-resolution-marks/1",
        "state_sha256": expected_state_sha256,
        "ledger_sha256": timing._digest(ledger),
        "required_holdings": held,
        "candidate_marks": None
        if missing
        else {name: row["price"] for name, row in details.items()},
        "missing": missing,
        "details": details,
        "clocks": clocks,
        "status": "MISSING_ALL_HELD_MARKS"
        if missing
        else "CANDIDATES_ONLY_NATIVE_ADMISSION_REQUIRED",
        "nav": None,
        "nav_reason": "No native observe/account admission performed",
        "packet_sha256": packet.sha256,
        "manifest_sha256": manifest.sha256,
        "registry_sha256": entity_registry.sha256,
        "mapping_status": {name: row["status"] for name, row in identities.items()},
        "issuer_identity_proven_by_selector": False,
        "broker_mutated": False,
        "actual_historical_publication_or_fill_proven": False,
    }
