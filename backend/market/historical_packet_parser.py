"""Multi-symbol original-byte parsing only; no reference selection or acquisition."""

import base64
import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from backend.market import historical_packet_demand as dem
from backend.market import historical_packet_registry as reg
from backend.market.historical_timing_packet import _clocks, _decode, _digest, _ordered


# Retain source bytes and independent pins rather than accepting detached parsed rows.
@dataclass(frozen=True)
class Packets:
    raw: bytes
    sha256: str
    demand_sha256: str
    verified_at: str


# Authenticate a bounded successful original page against its fixed query and clocks.
def _page(page, query, token, verified, previous):
    if set(page) != {
        "url",
        "requested_at",
        "received_at",
        "status",
        "body_base64",
        "sha256",
        "body_complete",
        "failure",
    }:
        raise ValueError("Exact original page acquisition fields required")
    if page["body_complete"] is not True or page["failure"] is not None:
        raise ValueError("Truncated/failed body cannot supply market evidence")
    params = dict(query["parameters"])
    if token is not None:
        params["page_token"] = token
    actual, expected = urlsplit(page["url"]), urlsplit(query["endpoint"])
    if (actual.scheme, actual.netloc, actual.path, actual.fragment) != (
        expected.scheme,
        expected.netloc,
        expected.path,
        "",
    ) or parse_qs(actual.query, keep_blank_values=True) != {
        k: [v] for k, v in params.items()
    }:
        raise ValueError("Exact fixed query and original page chain required")
    received = _clocks(
        page["requested_at"], page["received_at"], verified, params["end"], previous
    )
    if type(page["status"]) is not int or page["status"] != 200:
        raise ValueError("Acquisition failure pauses; not market missingness")
    if type(page["body_base64"]) is not str or len(page["body_base64"]) > 4 * (
        (dem.BUDGET["bytes_per_group"] + 2) // 3
    ):
        raise ValueError("Encoded body exceeds bounded memory allocation")
    raw = base64.b64decode(page["body_base64"], validate=True)
    if hashlib.sha256(raw).hexdigest() != reg.digest(page["sha256"]):
        raise ValueError("Original provider body differs")
    body = _decode(raw)
    _digest(body)  # Refuse numeric overflow to infinity as well as JSON NaN.
    if set(body) != {query["kind"], "next_page_token"}:
        raise ValueError("Exact original provider body fields required")
    return body, received, len(raw)


# Fold symbol-first rows without sorting temporal events or dropping required names.
def _members(members, rows, present, last_symbol):
    if type(members) is not dict or set(members) - set(rows):
        raise ValueError("Unexpected symbol or malformed provider rows")
    if sum(len(v) for v in members.values() if type(v) is list) > 1000:
        raise ValueError("Provider page exceeds declared total-row limit")
    for name in sorted(members):
        values = members[name]
        if type(values) is not list:
            raise ValueError("Original row lists required")
        present.add(name)
        if values and name < last_symbol:
            raise ValueError("Original symbol-first pagination order required")
        if values:
            last_symbol = name
        rows[name].extend(values)
    return last_symbol


# Require complete pagination before exposing any name from a grouped request.
def _group(pages, query, verified):
    if type(pages) is not list or not 1 <= len(pages) <= dem.BUDGET["pages_per_group"]:
        raise ValueError("Missing pages or group page cap")
    rows = {s: [] for s in query["parameters"]["symbols"].split(",")}
    present, token, seen, previous, byte_count, last_symbol = (
        set(),
        None,
        set(),
        None,
        0,
        "",
    )
    for index, page in enumerate(pages):
        body, previous, size = _page(page, query, token, verified, previous)
        byte_count += size
        if byte_count > dem.BUDGET["bytes_per_group"]:
            raise ValueError("Group byte cap; pause without window extension")
        last_symbol = _members(body[query["kind"]], rows, present, last_symbol)
        token = body["next_page_token"]
        if token is not None:
            if type(token) is not str or not token or token in seen:
                raise ValueError("Unique next-page chain required")
            seen.add(token)
        if (token is None) != (index == len(pages) - 1):
            raise ValueError("Short pages are not complete; extra pages also reject")
    for values in rows.values():
        _ordered(values, query["parameters"]["start"], query["parameters"]["end"])
    return {
        name: {
            "status": "COMPLETE_ROWS"
            if values
            else ("COMPLETE_EMPTY" if name in present else "COMPLETE_ABSENT_KEY"),
            "rows": values,
        }
        for name, values in rows.items()
    }, byte_count


# Validate all required source groups and resource totals before exposing packet rows.
def read(packet, demand, registry):
    if type(packet) is not Packets or packet.demand_sha256 != demand.sha256:
        raise ValueError("Immutable demand-bound packets required")
    manifest = dem.read(demand, registry)
    data = reg.pinned(packet.raw, packet.sha256)
    if (
        set(data) != {"schema", "demand_sha256", "complete", "failure", "groups"}
        or data["schema"] != "historical-demand-capture/1"
        or data["demand_sha256"] != demand.sha256
        or data["complete"] is not True
        or data["failure"] is not None
        or type(data["groups"]) is not dict
    ):
        raise ValueError("Failed/incomplete capture cannot supply market evidence")
    queries = {q["sha256"]: q for q in manifest["queries"]}
    if set(data["groups"]) != set(queries):
        raise ValueError(
            "Every original required group and held name must be finalized"
        )
    result, gets, byte_count = {}, 0, 0
    for key, query in queries.items():
        pages = data["groups"][key]
        result[key], size = _group(pages, query, packet.verified_at)
        gets += len(pages)
        byte_count += size
    used = dem.usage(
        {
            "get_attempts": manifest["used"]["get_attempts"] + gets,
            "body_bytes": manifest["used"]["body_bytes"] + byte_count,
        }
    )
    return {
        "groups": result,
        "used": used,
        "post_resolution_marks": manifest["post_resolution_marks"],
        "issuer_identity_proven_by_parser": False,
        "acquisition_authorized": False,
    }


# Seal already acquired byte evidence without enabling any new provider request.
def packets(raw, expected_sha256, demand, registry, verified_at):
    value = Packets(raw, expected_sha256, demand.sha256, verified_at)
    read(value, demand, registry)
    return value
