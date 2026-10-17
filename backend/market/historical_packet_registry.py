"""Pure registry envelopes; byte integrity never proves provider issuer identity.

No HTTP, filesystem, model or account operation occurs here. An independently
pinned registry and supporting bytes retain the reviewer's claims explicitly.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from backend.market.historical_timing_packet import _decode


# Preserve original registry bytes rather than a mutable admitted-name dictionary.
@dataclass(frozen=True)
class Registry:
    raw: bytes
    sha256: str
    evidence: tuple


# Reject malformed digests without treating a digest as external authentication.
def digest(value):
    if type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("Full lowercase SHA256 required")
    return value


# Validate provider label shape without deciding what issuer it names.
def symbol(value):
    if (
        type(value) is not str
        or re.fullmatch("[A-Z0-9][A-Z0-9.-]{0,31}", value) is None
    ):
        raise ValueError("Explicit source/query symbol required")
    return value


# Bind exact immutable bytes to an independently supplied expected digest.
def pinned(raw, expected):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != digest(expected):
        raise ValueError("Pinned original bytes differ")
    return _decode(raw)


# Validate an explicit lookup date independently of the historical event session.
def lookup_date(value):
    if type(value) is not str or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Explicit canonical entity-asof date required")
    return value


# Validate retained source references without interpreting request names as issuers.
def _sources(sources, evidence):
    if type(sources) is not list or not sources:
        raise ValueError("Retained source evidence required")
    kinds = set()
    for source in sources:
        if set(source) != {"kind", "sha256", "source_label"}:
            raise ValueError("Exact source evidence reference required")
        if source["kind"] not in {"request_metadata", "issuer_chain", "action", "sec"}:
            raise ValueError("Explicit source evidence kind required")
        if (
            digest(source["sha256"]) not in evidence
            or type(source["source_label"]) is not str
            or not source["source_label"]
        ):
            raise ValueError("Missing retained source bytes")
        kinds.add(source["kind"])
    return kinds


# Validate an external review's issuer claim without manufacturing a provider ID.
def _identity(row, kinds):
    identity = row["issuer_identity"]
    if row["status"] == "VERIFIED_CHAIN":
        if (
            type(identity) is not dict
            or set(identity) != {"scheme", "value", "share_class"}
            or not all(type(v) is str and v for v in identity.values())
            or "issuer_chain" not in kinds
            or row["assumption"] is not None
        ):
            raise ValueError("Reviewed issuer and security-class chain required")
    elif identity is not None:
        raise ValueError("Request-name provenance cannot claim issuer identity")


# Preserve conditional mapping assumptions separately from reviewed issuer-chain claims.
def _claim(row, kinds, evidence):
    status = row["status"]
    if status not in {
        "UNRESOLVED",
        "REQUEST_NAME_ONLY",
        "REVIEWED_CONDITIONAL_MAPPING",
        "VERIFIED_CHAIN",
    }:
        raise ValueError("Explicit identity status required")
    if status in {"REVIEWED_CONDITIONAL_MAPPING", "VERIFIED_CHAIN"}:
        if digest(row["review_sha256"]) not in evidence:
            raise ValueError("Pinned mapping review bytes required")
    elif row["review_sha256"] is not None:
        raise ValueError("Unadmitted entry cannot claim a mapping review")
    _identity(row, kinds)
    if status == "REVIEWED_CONDITIONAL_MAPPING":
        if type(row["assumption"]) is not str or not row["assumption"].strip():
            raise ValueError("Conditional mapping assumption must remain explicit")
    elif row["assumption"] is not None:
        raise ValueError("Unexpected mapping assumption")


# Revalidate a sealed registry and expose detached review claims and source references.
def entries(registry):
    if type(registry) is not Registry:
        raise ValueError("Original immutable registry required")
    data = pinned(registry.raw, registry.sha256)
    if (
        set(data) != {"schema", "entries"}
        or data["schema"] != "historical-entity-registry/1"
    ):
        raise ValueError("Exact registry schema required")
    evidence = dict(registry.evidence)
    if len(evidence) != len(registry.evidence):
        raise ValueError("Duplicate evidence digest")
    for sha, raw in evidence.items():
        if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != digest(sha):
            raise ValueError("Supporting original bytes differ")
    rows = data["entries"]
    if type(rows) is not list or not 1 <= len(rows) <= 96:
        raise ValueError("One to96 explicit registry entries required")
    found, queries = {}, set()
    for row in rows:
        if set(row) != {
            "cohort_key",
            "query_symbol",
            "entity_asof",
            "status",
            "issuer_identity",
            "assumption",
            "sources",
            "review_sha256",
        }:
            raise ValueError("Exact registry entry fields required")
        key, query = symbol(row["cohort_key"]), symbol(row["query_symbol"])
        lookup_date(row["entity_asof"])
        if key in found or (query, row["entity_asof"]) in queries:
            raise ValueError("Duplicate or ambiguous registry mapping")
        queries.add((query, row["entity_asof"]))
        _claim(row, _sources(row["sources"], evidence), evidence)
        found[key] = row
    return found


# Preserve incomplete identity evidence while refusing to use it for acquisition.
def admit(registry, names):
    rows = entries(registry)
    for name in names:
        if name not in rows or rows[name]["status"] not in {
            "VERIFIED_CHAIN",
            "REVIEWED_CONDITIONAL_MAPPING",
        }:
            raise ValueError(
                "Unresolved/request-name-only entity mapping: " + str(name)
            )
    return {name: rows[name] for name in sorted(names)}


# Seal registry bytes and source evidence without manufacturing identity evidence.
def registry(raw, expected_sha256, evidence):
    value = Registry(raw, expected_sha256, tuple(sorted(evidence.items())))
    entries(value)
    return value
