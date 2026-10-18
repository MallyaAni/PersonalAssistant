"""Source-only synthetic Store stage fixtures; no closed test body."""
import hashlib
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_registry as registry

# Give every synthetic fixture artifact a deterministic content identity.
def sha(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


# Build explicit synthetic conditional mapping, never a provider identity claim.
def mapping():
    evidence = b"SYNTHETIC request metadata only"
    review = b"SYNTHETIC conditional mapping review"
    evidence_sha = hashlib.sha256(evidence).hexdigest()
    review_sha = hashlib.sha256(review).hexdigest()
    raw = demand.encoded(
        {
            "schema": "historical-entity-registry/1",
            "entries": [
                {
                    "cohort_key": "AAPL",
                    "query_symbol": "AAPL",
                    "entity_asof": "2026-10-12",
                    "status": "REVIEWED_CONDITIONAL_MAPPING",
                    "issuer_identity": None,
                    "assumption": "Synthetic fixture only",
                    "review_sha256": review_sha,
                    "sources": [
                        {
                            "kind": "request_metadata",
                            "sha256": evidence_sha,
                            "source_label": "synthetic",
                        }
                    ],
                }
            ],
        }
    )
    return registry.registry(
        raw,
        hashlib.sha256(raw).hexdigest(),
        {evidence_sha: evidence, review_sha: review},
    )


# Start one causal cycle with authentic pure demand validation over fake inputs.
def paused(store, cycle, held=False):
    first = store.append(
        expected_head=store.snapshot()["head"],
        cycle_sha256=cycle,
        stage="PRIOR_VERIFIED",
        receipt_sha256=sha(cycle + "prior"),
    )
    value = demand.build(
        mapping(),
        identity_sha256=store.identity,
        parent_sha256=first["sha256"],
        completed_at="2019-03-01T14:45:00Z",
        prior={key: sha("SYNTHETIC " + key) for key in demand.PRIOR},
        held=["AAPL"] if held else [],
        legs=[],
        used=store.snapshot()["used"],
    )
    store.declare(value, mapping())
    store.append(
        expected_head=first["sha256"],
        cycle_sha256=cycle,
        stage="DEMAND_FROZEN",
        receipt_sha256=value.sha256,
    )
    store.append(
        expected_head=store.snapshot()["head"],
        cycle_sha256=cycle,
        stage="WAIT_PACKETS",
        receipt_sha256=sha(cycle + "wait"),
    )
    return value


# Reach the next decision stage only after every required page is finalized.
def ready(store, cycle):
    paused(store, cycle)
    return store.append(
        expected_head=store.snapshot()["head"],
        cycle_sha256=cycle,
        stage="PACKETS_FINALIZED",
        receipt_sha256=sha(cycle + "packet"),
    )


