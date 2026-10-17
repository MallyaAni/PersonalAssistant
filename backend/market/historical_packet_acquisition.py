"""Unused fake-transport-only coordinator; no real GET client or launch permission.

Both replicas here are passive LOCAL Stores. Physical page extents do not reserve
SQLite/directory headroom or establish real dual-host resource/issuance admission.
The existing8MiB parser cap pauses broader captures rather than widening scope.
"""

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_parser as parser
from backend.market import historical_packet_registry as registry
from backend.market.historical_packet_spool import ReservedSpool
from backend.market.historical_packet_store import (
    CHUNK,
    MAX_ENTRY,
    MAX_META,
    Store,
    StorePause,
    _require,
)
from backend.market.historical_timing_packet import _clocks, _decode

SOURCE_NAMES = (
    "historical_packet_acquisition.py",
    "historical_packet_store.py",
    "historical_packet_spool.py",
    "historical_packet_parser.py",
    "historical_packet_demand.py",
    "historical_packet_registry.py",
    "historical_packet_checkpoint.py",
    "historical_timing_packet.py",
)


# Retain only immutable source references, never decoded rows or a network client.
@dataclass(frozen=True)
class CaptureRef:
    raw: bytes
    sha256: str


# Give the fake callback an immutable exact request with no credentials or overrides.
@dataclass(frozen=True)
class Request:
    url: str
    method: str = "GET"
    redirects: bool = False
    retries: int = 0
    decode_content: bool = False
    accept_encoding: str = "identity"
    timeout_seconds: int = 30
    provenance: str = "SYNTHETIC_LOCAL_ONLY"


# Hash bounded actual implementation files, including the shared clock validators.
def source_pins():
    result = {}
    for name in SOURCE_NAMES:
        path = Path(__file__).parent / name
        with path.open("rb") as stream:
            _require(path.stat().st_size <= MAX_META, "Source pin read cap")
            raw = stream.read(MAX_META + 1)
        _require(len(raw) <= MAX_META, "Source pin read cap")
        result[name] = hashlib.sha256(raw).hexdigest()
    return result


# Sample actual acquisition time without a launch-clock or historical override.
def _clock():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# Reconstruct only canonical demand parameters and the original retained token.
def _url(query, token):
    parameters = dict(query["parameters"])
    if token is not None:
        parameters["page_token"] = token
    return query["endpoint"] + "?" + urlencode(parameters)


# Detach and authenticate every declaration before the first fake callback.
def _admit(stores, declared, reviewed, permit_raw, expected_permit, transport):
    _require(
        type(stores) is tuple and len(stores) == 2, "Two local fixture Stores required"
    )
    _require(
        all(type(store) is Store for store in stores) and stores[0] is not stores[1],
        "Distinct exact local Stores required",
    )
    _require(
        type(declared) is demand.Demand and type(reviewed) is registry.Registry,
        "Frozen declarations required",
    )
    detached = demand.Demand(declared.raw, declared.sha256)
    reviewed = registry.Registry(
        reviewed.raw,
        reviewed.sha256,
        tuple((sha, raw) for sha, raw in reviewed.evidence),
    )
    manifest = demand.read(detached, reviewed)
    _require(
        type(permit_raw) is bytes and len(permit_raw) <= MAX_META,
        "Bounded explicit fixture permit required",
    )
    permit = registry.pinned(permit_raw, expected_permit)
    _require(
        set(permit)
        == {
            "schema",
            "mode",
            "real_gets_authorized",
            "identity_sha256",
            "demand_sha256",
            "registry_sha256",
            "initial_heads",
            "source_sha256",
            "budget",
            "page_body_cap",
            "metadata_headroom",
        },
        "Exact fixture permit schema required",
    )
    _require(
        permit["schema"] == "historical-fixture-acquisition/1"
        and permit["mode"] == "SYNTHETIC_LOCAL_ONLY"
        and permit["real_gets_authorized"] is False
        and permit["metadata_headroom"] == "UNVERIFIED_LOCAL_FIXTURE"
        and permit["identity_sha256"] == manifest["identity_sha256"]
        and permit["demand_sha256"] == detached.sha256
        and permit["registry_sha256"] == reviewed.sha256
        and permit["source_sha256"] == source_pins()
        and permit["budget"] == dict(demand.BUDGET)
        and all(type(value) is int for value in permit["budget"].values()),
        "Exact synthetic permit/source/budget pins required",
    )
    cap = permit["page_body_cap"]
    _require(
        type(cap) is int and 0 < cap < demand.BUDGET["bytes_per_group"],
        "Finite page cap plus EOF/overflow guard required",
    )
    _require(
        getattr(transport, "synthetic_only", None) is True
        and callable(getattr(transport, "get", None)),
        "Injected fake-only transport required; no real client exists",
    )
    states = [store.snapshot() for store in stores]
    _require(
        permit["initial_heads"] == [state["head"] for state in states]
        and states[0]["head"] == states[1]["head"]
        and states[0]["cycle"] == states[1]["cycle"]
        and states[0]["used"] == states[1]["used"]
        and all(
            state["identity"] == manifest["identity_sha256"]
            and state["next_stage"] == "PACKETS_FINALIZED"
            for state in states
        ),
        "Pinned local replica heads/identity/budgets/phase differ",
    )
    for store in stores:
        for query in manifest["queries"]:
            _require(
                store._query(detached.sha256, query["sha256"]) == query,
                "Original stored demand differs",
            )
    return detached, reviewed, manifest, permit, transport.get


# Read at most one original group's ten page records, including uncertain attempts.
def _rows(store, declared, query):
    rows = store.connection.execute(
        "SELECT * FROM attempts WHERE demand=? AND query=? ORDER BY page LIMIT 11",
        (declared.sha256, query["sha256"]),
    ).fetchall()
    _require(len(rows) <= demand.BUDGET["pages_per_group"], "Original page cap")
    return rows


# Pin both original metadata CAS objects rather than trusting mutable row dictionaries.
def _references(stores, declared, manifest):
    result = {}
    for query in manifest["queries"]:
        groups = [
            store.page_manifest(declared.sha256, query["sha256"]) for store in stores
        ]
        _require(len(groups[0]) == len(groups[1]), "Local replica page counts differ")
        pages = []
        for left, right in zip(*groups, strict=True):
            _require(
                all(left[key] == right[key] for key in ("page", "token", "next_token")),
                "Original local page chain differs",
            )
            receipts = []
            for store, page in zip(stores, (left, right), strict=True):
                raw = demand.encoded(page["receipt"])
                sha = hashlib.sha256(raw).hexdigest()
                _require(
                    store.read_blob(sha, limit=MAX_ENTRY) == raw,
                    "Original metadata CAS differs",
                )
                receipts.append(sha)
            pages.append(
                {
                    "page": left["page"],
                    "token": left["token"],
                    "next_token": left["next_token"],
                    "receipts": receipts,
                }
            )
        result[query["sha256"]] = pages
    return result


# Rebuild a capped original envelope from hashes and use the existing parser unchanged.
def _packet(data, stores, declared, reviewed, manifest):
    _require(
        data["groups"] == _references(stores, declared, manifest),
        "Immutable group references differ",
    )
    envelope = {
        "schema": "historical-demand-capture/1",
        "demand_sha256": declared.sha256,
        "complete": True,
        "failure": None,
        "groups": {},
    }
    pending, encoded_size = [], 0
    verified = None
    for query in manifest["queries"]:
        pages = []
        for ref in data["groups"][query["sha256"]]:
            metadata = [
                _decode(store.read_blob(sha, limit=MAX_ENTRY))
                for store, sha in zip(stores, ref["receipts"], strict=True)
            ]
            keys = (
                "status",
                "body_complete",
                "failure",
                "requested_at",
                "received_at",
                "body_sha256",
                "body_bytes",
                "body_validation_failure",
            )
            _require(
                all(metadata[0][key] == metadata[1][key] for key in keys),
                "Local response observations differ",
            )
            row = metadata[0]
            _require(
                row["body_validation_failure"] is None, "Invalid retained source body"
            )
            page = {
                "url": _url(query, ref["token"]),
                "status": row["status"],
                "requested_at": row["requested_at"],
                "received_at": row["received_at"],
                "sha256": row["body_sha256"],
                "body_complete": row["body_complete"],
                "failure": row["failure"],
                "body_base64": "",
            }
            encoded_size += 4 * ((row["body_bytes"] + 2) // 3)
            pending.append((page, row["body_sha256"], row["body_bytes"]))
            pages.append(page)
            verified = row["received_at"]
        envelope["groups"][query["sha256"]] = pages
    _require(
        verified is not None and data["verified_at"] == verified,
        "Original final received-clock pin required",
    )
    _require(
        len(demand.encoded(envelope)) + encoded_size <= parser.MAX_CAPTURE_BYTES,
        "Aggregate8MiB envelope cap; pause, never narrow coverage",
    )
    for page, sha, length in pending:
        raw = stores[0].read_blob(sha, limit=length)
        _require(
            len(raw) == length and stores[1].read_blob(sha, limit=length) == raw,
            "Original local body replicas differ",
        )
        page["body_base64"] = base64.b64encode(raw).decode()
    raw = demand.encoded(envelope)
    actual_sha = hashlib.sha256(raw).hexdigest()
    _require(
        data["packet_sha256"] is None or actual_sha == data["packet_sha256"],
        "Original reconstructed packet hash differs",
    )
    return parser.packets(raw, actual_sha, declared, reviewed, verified)


# Build a reference solely from complete retained original page receipts.
def _ref(stores, declared, reviewed, manifest, permit_sha):
    groups = _references(stores, declared, manifest)
    data = {
        "schema": "historical-synthetic-capture-ref/1",
        "mode": "SYNTHETIC_LOCAL_ONLY",
        "identity_sha256": manifest["identity_sha256"],
        "demand_sha256": declared.sha256,
        "registry_sha256": reviewed.sha256,
        "permit_sha256": permit_sha,
        "source_sha256": source_pins(),
        "groups": groups,
        "verified_at": _decode(
            stores[0].read_blob(
                groups[manifest["queries"][-1]["sha256"]][-1]["receipts"][0],
                limit=MAX_ENTRY,
            )
        )["received_at"],
        "packet_sha256": None,
    }
    data["packet_sha256"] = _packet(data, stores, declared, reviewed, manifest).sha256
    encoded = demand.encoded(data)
    _require(len(encoded) <= MAX_META, "Immutable reference metadata cap")
    return CaptureRef(encoded, hashlib.sha256(encoded).hexdigest())


# Retain synthetic failure bytes without resolving charged uncertainty.
def _failure(stores, spools, phase, error, observation):
    raw = demand.encoded(
        {
            "schema": "historical-synthetic-acquisition-failure/1",
            "mode": "SYNTHETIC_LOCAL_ONLY",
            "phase": phase,
            "error_type": type(error).__name__,
            "observed_response": observation,
            "observed_at": _clock(),
            "real_gets_authorized": False,
        }
    )
    for store, spool in zip(stores, spools, strict=True):
        if "receipt" not in spool.sealed:
            try:
                ref, sha, size = spool.receipt(raw)
                store.adopt_spool(spool, ref, expected_sha256=sha, length=size)
            except (OSError, ValueError):
                pass  # A resource failure cannot justify an unreserved recovery write.


# Read only after both original allowances were durably charged.
def _body(stores, spools, attempt, allowances, cap, read):
    total = 0
    for index, allowance in enumerate(allowances):
        reservation = hashlib.sha256(demand.encoded([attempt, index])).hexdigest()
        if index:
            for store in stores:
                store.reserve_read(attempt, reservation, allowance)
        raw = read(allowance)
        _require(
            type(raw) is bytes and len(raw) <= allowance,
            "Fake raw bounded-read contract violated",
        )
        for store, spool in zip(stores, spools, strict=True):
            store.confirm_read(reservation, raw, spool=spool)
        total += len(raw)
        _require(total <= cap, "Fixed body cap exceeded; pause without truncation")
        if not raw:
            return
    raise StorePause("No observed EOF within finite read slots")


# Charge both local replicas and allocate extents before one fake page call.
def _page(stores, declared, query, page, token, cap, get):
    attempt = hashlib.sha256(
        demand.encoded([declared.sha256, query["sha256"], page, token])
    ).hexdigest()
    for store in stores:
        store.begin_attempt(
            attempt=attempt,
            demand_sha256=declared.sha256,
            query_sha256=query["sha256"],
            page=page,
            token=token,
        )
    whole, tail = divmod(cap, CHUNK)
    allowances = (CHUNK,) * whole + ((tail,) if tail else ()) + (1,)
    spools = [ReservedSpool(store, attempt, allowances) for store in stores]
    reservation = hashlib.sha256(demand.encoded([attempt, 0])).hexdigest()
    for store in stores:
        store.reserve_read(attempt, reservation, allowances[0])
    request = Request(_url(query, token))
    close, phase = None, "transport"
    observation = {"status": None, "url_matches": None, "identity_encoding": None}
    began = _clock()
    try:
        _clocks(began, began, began, query["parameters"]["end"])
        response = get(request)
        close = response.close
        read = response.read
        status, final_url, encoding = (
            response.status,
            response.url,
            response.content_encoding,
        )
        observation = {
            "status": status if type(status) is int else None,
            "url_matches": final_url == request.url,
            "identity_encoding": encoding in (None, "identity"),
        }
        _require(
            type(status) is int
            and status == 200
            and final_url == request.url
            and encoding in (None, "identity"),
            "Fake final URL/status/raw encoding differs",
        )
        phase = "body"
        _body(stores, spools, attempt, allowances, cap, read)
        ended = _clock()
        _clocks(began, ended, ended, query["parameters"]["end"])
        phase = "close"
        closing, close = close, None
        closing()
        phase = "retention"
        for store, spool in zip(stores, spools, strict=True):
            store.finish_attempt(
                attempt,
                status=status,
                complete=True,
                failure=None,
                requested_at=began,
                received_at=ended,
                spool=spool,
            )
    except Exception as error:
        _failure(stores, spools, phase, error, observation)
        if phase == "close":
            raise StorePause("Synthetic close failed; no retry") from error
        raise StorePause(
            "Synthetic acquisition paused; retained charges, no retry"
        ) from error
    finally:
        if close is not None:
            try:
                close()
            except Exception as error:
                _failure(stores, spools, "close", error, observation)
                raise StorePause("Synthetic close failed; no retry") from error


# Capture fake local evidence without granting any real GET permission.
def capture(
    stores, declared, reviewed, *, permit_raw, expected_permit_sha256, transport
):
    declared, reviewed, manifest, permit, get = _admit(
        stores, declared, reviewed, permit_raw, expected_permit_sha256, transport
    )
    _require(bool(manifest["queries"]), "No empty demand fallback")
    for query in manifest["queries"]:
        while True:
            sides = [_rows(store, declared, query) for store in stores]
            _require(
                len(sides[0]) == len(sides[1]),
                "Partial local reservation remains uncertain",
            )
            _require(
                all(row["status"] == "RETAINED" for rows in sides for row in rows),
                "OPEN/FAILED attempt remains paused, never refetch",
            )
            if sides[0] and sides[0][-1]["next_token"] is None:
                break
            token = sides[0][-1]["next_token"] if sides[0] else None
            _require(
                not sides[1] or token == sides[1][-1]["next_token"],
                "Original local continuation differs",
            )
            _page(
                stores,
                declared,
                query,
                len(sides[0]),
                token,
                permit["page_body_cap"],
                get,
            )
    _require(
        source_pins() == permit["source_sha256"],
        "Implementation changed during fake callbacks",
    )
    ref = _ref(stores, declared, reviewed, manifest, expected_permit_sha256)
    for store in stores:
        state = store.snapshot()
        store.append(
            expected_head=state["head"],
            cycle_sha256=state["cycle"],
            stage="PACKETS_FINALIZED",
            receipt_sha256=ref.sha256,
        )
    return ref


# Authenticate returned references against current pinned heads before network-none use.
def load(ref, stores, declared, reviewed):
    _require(
        type(ref) is CaptureRef and len(ref.raw) <= MAX_META,
        "Bounded immutable capture reference required",
    )
    data = registry.pinned(ref.raw, ref.sha256)
    manifest = demand.read(declared, reviewed)
    _require(
        set(data)
        == {
            "schema",
            "mode",
            "identity_sha256",
            "demand_sha256",
            "registry_sha256",
            "permit_sha256",
            "source_sha256",
            "groups",
            "verified_at",
            "packet_sha256",
        }
        and data["schema"] == "historical-synthetic-capture-ref/1"
        and data["mode"] == "SYNTHETIC_LOCAL_ONLY"
        and data["identity_sha256"] == manifest["identity_sha256"]
        and data["demand_sha256"] == declared.sha256
        and data["registry_sha256"] == reviewed.sha256
        and data["source_sha256"] == source_pins(),
        "Original synthetic reference/source bindings differ",
    )
    for store in stores:
        state = store.snapshot()
        row = store.connection.execute(
            "SELECT receipt FROM entries WHERE sha=?", (state["head"],)
        ).fetchone()
        _require(
            row is not None
            and row[0] == ref.sha256
            and state["next_stage"] == "DECISION_FROZEN",
            "Reference not anchored in current finalized head",
        )
    return _packet(data, stores, declared, reviewed, manifest)
