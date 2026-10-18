"""Versioned native-format metadata bytes, never paper-state or operation adoption.

Chunks use existing bounded Store blobs. The aggregate bound applies to one
descriptor, not a reservation across descriptors, native effects or a full run.
Standalone native JSON bytes are not the indented span inside paper.history.
"""
import hashlib
import io
import json
from pathlib import Path

from backend.agents.trading.desk import paper
from backend.market import historical_packet_demand as demand
from backend.market.historical_packet_registry import digest
from backend.market.historical_packet_store import Store

CHUNK = 64 * 1024
LIMIT = demand.BUDGET["bytes_per_group"]
META_CAP = 256 * 1024
SCHEMA = "native-json-metadata/1"
KINDS = ("nightly-entry", "holding-decision")
KEYS = {"schema", "kind", "identity_sha256", "adapter_sha256", "producer_sha256",
        "encoder_sha256", "encoding", "raw_sha256", "raw_bytes", "chunks",
        "native_operation_committed", "durable_simulator_adoption"}


# Bind metadata storage and its producer without accepting a path from the receipt.
def _authority(store, kind, producer_sha256):
    if type(store) is not Store or kind not in KINDS:
        raise ValueError("Exact Store and native metadata kind required")
    digest(store.identity)
    digest(producer_sha256)


# Publish only native JSON chunks under an explicit per-descriptor aggregate bound.
def capture(store, value, *, kind, producer_sha256, byte_limit=LIMIT):
    _authority(store, kind, producer_sha256)
    if store.blob_reservation is not None:
        from backend.market import historical_reserved_native_metadata

        return historical_reserved_native_metadata.capture(store, value, kind=kind,
            producer_sha256=producer_sha256, byte_limit=byte_limit)
    if type(byte_limit) is not int or not 0 < byte_limit <= LIMIT:
        raise ValueError("Native metadata remaining allowance required")
    if kind == "holding-decision" and (
        type(value) is not dict or set(value) != {"targets", "receipt"}
    ):
        raise ValueError("Original holding decision shape required")
    if kind == "nightly-entry" and value is not None and type(value) is not dict:
        raise ValueError("Original native entry or unavailable result required")
    encoder = json.JSONEncoder(indent=2, default=paper._state_json)
    chunks, pending, total, hashed = [], bytearray(), 0, hashlib.sha256()
    for text in encoder.iterencode(value):
        if len(text) > byte_limit - total:
            raise ValueError("Native metadata aggregate bound exceeded")
        raw = text.encode("utf-8")
        total += len(raw)
        if total > byte_limit:
            raise ValueError("Native metadata aggregate bound exceeded")
        hashed.update(raw)
        offset = 0
        while offset < len(raw):
            take = min(CHUNK - len(pending), len(raw) - offset)
            pending.extend(raw[offset:offset + take])
            offset += take
            if len(pending) == CHUNK:
                body = bytes(pending)
                reference, length = store.put_stream(io.BytesIO(body), limit=CHUNK,
                    expected_sha256=hashlib.sha256(body).hexdigest())
                chunks.append({"sha256": reference, "bytes": length})
                pending.clear()
    if pending:
        body = bytes(pending)
        reference, length = store.put_stream(io.BytesIO(body), limit=CHUNK,
            expected_sha256=hashlib.sha256(body).hexdigest())
        chunks.append({"sha256": reference, "bytes": length})
    result = {
        "schema": SCHEMA, "kind": kind, "identity_sha256": store.identity,
        "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "producer_sha256": producer_sha256,
        "encoder_sha256": hashlib.sha256(Path(paper.__file__).read_bytes()).hexdigest(),
        "encoding": "python-json-indent2-native-nonfinite/1",
        "raw_sha256": hashed.hexdigest(), "raw_bytes": total, "chunks": chunks,
        "native_operation_committed": False, "durable_simulator_adoption": False,
    }
    if len(demand.encoded(result)) > META_CAP:
        raise ValueError("Native metadata descriptor bound exceeded")
    return result


# Authenticate finite metadata before reading any bounded opaque native chunks.
def _declaration(store, reference, kind, producer_sha256):
    _authority(store, kind, producer_sha256)
    if type(reference) is dict and reference.get('schema') == 'native-json-metadata/2':
        from backend.market import historical_reserved_native_metadata

        return historical_reserved_native_metadata._declaration(store, reference, kind, producer_sha256)
    if store.blob_reservation is not None:
        raise ValueError('Reserved Store requires native metadata schema2; no downgrade')
    if (type(reference) is not dict or set(reference) != KEYS
            or len(demand.encoded(reference)) > META_CAP
            or reference["schema"] != SCHEMA or reference["kind"] != kind
            or reference["identity_sha256"] != store.identity
            or reference["producer_sha256"] != producer_sha256
            or reference["adapter_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            or reference["encoder_sha256"] != hashlib.sha256(Path(paper.__file__).read_bytes()).hexdigest()
            or reference["encoding"] != "python-json-indent2-native-nonfinite/1"
            or type(reference["raw_bytes"]) is not int or not 0 < reference["raw_bytes"] <= LIMIT
            or reference["native_operation_committed"] is not False
            or reference["durable_simulator_adoption"] is not False
            or type(reference["chunks"]) is not list
            or not 0 < len(reference["chunks"]) <= (LIMIT + CHUNK - 1) // CHUNK):
        raise ValueError("Exact versioned native metadata descriptor required")
    digest(reference["raw_sha256"])
    total = 0
    for index, row in enumerate(reference["chunks"]):
        if (type(row) is not dict or set(row) != {"sha256", "bytes"}
                or type(row["bytes"]) is not int or not 0 < row["bytes"] <= CHUNK
                or (index < len(reference["chunks"]) - 1 and row["bytes"] != CHUNK)):
            raise ValueError("Exact ordered native metadata chunks required")
        digest(row["sha256"])
        total += row["bytes"]
    if total != reference["raw_bytes"]:
        raise ValueError("Native metadata aggregate length differs")


# Read exact native-format bytes without finite decoding or NaN normalization.
def read_bytes(store, reference, *, kind, producer_sha256):
    _declaration(store, reference, kind, producer_sha256)
    result, hashed = bytearray(), hashlib.sha256()
    for row in reference["chunks"]:
        body = store.read_blob(row["sha256"], limit=CHUNK)
        if len(body) != row["bytes"]:
            raise ValueError("Native metadata chunk length differs")
        hashed.update(body)
        result.extend(body)
    if hashed.hexdigest() != reference["raw_sha256"]:
        raise ValueError("Native metadata complete digest differs")
    return bytes(result)
