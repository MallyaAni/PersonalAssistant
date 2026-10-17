"""Pure receipt fold; no persistence, decisions, submissions or account replay.

The caller must pin the authoritative head and serialize exclusive atomic writes.
This helper validates a supplied chain; it cannot discover an external fork.
"""

from backend.market import historical_packet_demand as dem
from backend.market import historical_packet_registry as reg
from backend.market.historical_timing_packet import _digest

STAGES = (
    "PRIOR_VERIFIED",
    "DEMAND_FROZEN",
    "WAIT_PACKETS",
    "PACKETS_FINALIZED",
    "DECISION_FROZEN",
    "SUBMISSION_CAPTURED",
    "OUTCOME_COMMITTED",
)


# Check one checkpoint envelope before interpreting its state-machine stage.
def _entry(entry, sequence, identity_sha256, prior):
    if set(entry) != {
        "sequence",
        "parent",
        "identity_sha256",
        "cycle_sha256",
        "stage",
        "receipt_sha256",
        "used",
        "sha256",
    }:
        raise ValueError("Exact checkpoint receipt fields required")
    body = {k: v for k, v in entry.items() if k != "sha256"}
    if (
        type(entry["sequence"]) is not int
        or entry["sequence"] != sequence
        or entry["identity_sha256"] != identity_sha256
        or entry["parent"] != prior
        or entry["sha256"] != _digest(body)
    ):
        raise ValueError("Checkpoint identity, parent or original bytes differ")
    reg.digest(entry["receipt_sha256"])
    reg.digest(entry["cycle_sha256"])


# Advance one causal cycle while allowing acquisition-only progress at a paused demand.
def _advance(entry, index, cycle, seen_cycles):
    progress = entry["stage"] == "ACQUISITION_PROGRESS" and index == 3
    if entry["stage"] != STAGES[index] and not progress:
        raise ValueError("Repeated/skipped decision or submission stage")
    if index == 0:
        if entry["cycle_sha256"] in seen_cycles:
            raise ValueError("Completed cycle cannot be repeated")
        cycle = entry["cycle_sha256"]
        seen_cycles.add(cycle)
    elif entry["cycle_sha256"] != cycle:
        raise ValueError("Paused account cycle cannot change identity")
    return (index if progress else (index + 1) % len(STAGES)), cycle


# Reconcile stage order, pause counters and original receipts against a pinned head.
def verify(chain, *, identity_sha256, expected_head):
    reg.digest(identity_sha256)
    if type(chain) is not list or not chain:
        raise ValueError("Original nonempty checkpoint chain required")
    prior, seen_receipts, previous_used = (
        None,
        set(),
        {"get_attempts": 0, "body_bytes": 0},
    )
    cycle, index, seen_cycles = None, 0, set()
    for sequence, entry in enumerate(chain):
        _entry(entry, sequence, identity_sha256, prior)
        index, cycle = _advance(entry, index, cycle, seen_cycles)
        receipt_key = (entry["stage"], entry["receipt_sha256"])
        if receipt_key in seen_receipts:
            raise ValueError("Receipt already consumed")
        seen_receipts.add(receipt_key)
        current = dem.usage(entry["used"])
        if any(current[k] < previous_used[k] for k in current):
            raise ValueError("Resource usage cannot reset on resume")
        previous_used, prior = current, entry["sha256"]
    if prior != reg.digest(expected_head):
        raise ValueError("Authoritative pinned head differs; fork or stale checkpoint")
    return {
        "head": prior,
        "next_stage": STAGES[index],
        "used": previous_used,
        "cycle_sha256": cycle,
        "external_exclusive_atomic_persistence": "UNVERIFIED",
    }


# Append one detached receipt without repeating any completed decision or submission.
def append(
    chain, *, identity_sha256, cycle_sha256, stage, receipt_sha256, used, expected_head
):
    if chain:
        state = verify(
            chain, identity_sha256=identity_sha256, expected_head=expected_head
        )
        if stage != state["next_stage"] and not (
            stage == "ACQUISITION_PROGRESS"
            and state["next_stage"] == "PACKETS_FINALIZED"
        ):
            raise ValueError("Only exact next checkpoint stage may append")
    elif expected_head is not None or stage != STAGES[0]:
        raise ValueError("Only exclusive initial checkpoint may start a chain")
    body = {
        "sequence": len(chain),
        "parent": expected_head,
        "identity_sha256": identity_sha256,
        "cycle_sha256": cycle_sha256,
        "stage": stage,
        "receipt_sha256": receipt_sha256,
        "used": dem.usage(used),
    }
    result = [dict(row, used=dict(row["used"])) for row in chain] + [
        dict(body, sha256=_digest(body))
    ]
    verify(result, identity_sha256=identity_sha256, expected_head=result[-1]["sha256"])
    return result
