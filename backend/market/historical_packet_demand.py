"""Pure causal demand declarations, not an acquirer or connected historical runner."""

import json
from dataclasses import dataclass
from types import MappingProxyType

from backend.market import historical_packet_registry as reg
from backend.market.historical_timing_packet import _digest, schedule

BUDGET = MappingProxyType(
    {
        "get_attempts": 250000,
        "body_bytes": 20 * 1024**3,
        "pages_per_group": 10,
        "bytes_per_group": 20 * 1024**2,
        "names_per_group": 8,
        "requests_per_minute": 180,
        "simulation_cpus": 1,
        "simulation_memory_bytes": 2 * 1024**3,
    }
)
PRIOR = {"ledger", "pending", "reservations", "actions", "inputs"}


# Freeze manifest bytes independently of mutable caller dictionaries.
@dataclass(frozen=True)
class Demand:
    raw: bytes
    sha256: str


# Serialize deterministic declarations with no hidden wall clock or nonfinite values.
def encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


# Require monotone exact integer usage rather than bool or fractional counters.
def usage(value):
    if type(value) is not dict or set(value) != {"get_attempts", "body_bytes"}:
        raise ValueError("Exact cumulative resource counters required")
    for name, used in value.items():
        if type(used) is not int or not 0 <= used <= BUDGET[name]:
            raise ValueError("Resource cap reached or invalid counter")
    return dict(value)


# Validate complete declared holding and original-leg coverage before querying prices.
def _coverage(held, legs, window):
    if type(held) is not list or held != sorted(set(held)):
        raise ValueError("Complete sorted unique all-held names required")
    for name in held:
        reg.symbol(name)
    if type(legs) is not list or len(legs) > 192:
        raise ValueError("Bounded complete original due-leg list required")
    cids, names = set(), set(held)
    session = window["completed_at"][:10]
    for leg in legs:
        if set(leg) != {"client_order_id", "symbol", "side", "qty", "phase", "session"}:
            raise ValueError("Exact pre-verdict leg identity required")
        cid = leg["client_order_id"]
        if type(cid) is not str or not cid or len(cid) > 128 or cid in cids:
            raise ValueError("Unique bounded original CID required")
        cids.add(cid)
        reg.symbol(leg["symbol"])
        if (
            leg["side"] not in {"buy", "sell"}
            or type(leg["qty"]) is not int
            or leg["qty"] <= 0
            or leg["phase"] != "market"
            or leg["session"] != session
        ):
            raise ValueError(
                "Whole-share current market legs only; auctions unresolved"
            )
        names.add(leg["symbol"])
    return names


# Group required names deterministically without inspecting any forecasts or responses.
def _queries(mapping, names, legs, window):
    queries = []
    for kind, wanted in (
        ("quotes", names),
        ("trades", {leg["symbol"] for leg in legs}),
    ):
        by_date = {}
        for name in sorted(wanted):
            row = mapping[name]
            by_date.setdefault(row["entity_asof"], []).append(name)
        for asof, members in sorted(by_date.items()):
            members.sort(key=lambda name: mapping[name]["query_symbol"])
            for offset in range(0, len(members), BUDGET["names_per_group"]):
                group = members[offset : offset + BUDGET["names_per_group"]]
                params = {
                    "symbols": ",".join(mapping[n]["query_symbol"] for n in group),
                    "feed": "sip",
                    "asof": asof,
                    "limit": "1000",
                    "sort": "asc",
                    "start": window[
                        "quote_start" if kind == "quotes" else "trade_start"
                    ].replace(".000000000Z", "Z"),
                    "end": window[
                        "quote_end" if kind == "quotes" else "trade_end"
                    ].replace(".000000000Z", "Z"),
                }
                query = {
                    "kind": kind,
                    "endpoint": "https://data.alpaca.markets/v2/stocks/" + kind,
                    "parameters": params,
                    "cohort_keys": group,
                }
                query["sha256"] = _digest(query)
                queries.append(query)
    return queries


# Freeze fixed queries from authenticated identity and declared causal prior state.
def build(
    registry,
    *,
    identity_sha256,
    parent_sha256,
    completed_at,
    prior,
    held,
    legs,
    used,
    branch="MODEL_TIMED_MARKET_ONLY",
):
    if branch not in {"MODEL_TIMED_MARKET_ONLY", "SESSION_COMPLETION_MARKET"}:
        raise ValueError("Explicit supported market branch required")
    reg.digest(identity_sha256)
    reg.digest(parent_sha256)
    if type(prior) is not dict or set(prior) != PRIOR:
        raise ValueError("Every causal prior-state digest required")
    for value in prior.values():
        reg.digest(value)
    window = schedule(completed_at)
    names = _coverage(held, legs, window)
    mapping = reg.admit(registry, names)
    value = {
        "schema": "historical-demand/1",
        "identity_sha256": identity_sha256,
        "parent_sha256": parent_sha256,
        "registry_sha256": registry.sha256,
        "prior": prior,
        "held": held,
        "legs": legs,
        "potential_holdings": sorted(names),
        "window": window,
        "queries": _queries(mapping, names, legs, window),
        "budget": dict(BUDGET),
        "used": usage(used),
        "branch": branch,
        "post_resolution_marks": "UNRESOLVED_NO_FRESH_MARK_SELECTION",
        "coverage_basis": "DECLARED_PRIOR_HELD_AND_LEGS_NOT_LEDGER_RECONCILIATION",
        "acquisition_authorized": False,
    }
    raw = encoded(value)
    return Demand(raw, _digest(value))


# Rebuild demand to refuse altered windows, coverage, budgets or grouping.
def read(demand, registry):
    if type(demand) is not Demand:
        raise ValueError("Immutable demand required")
    data = reg.pinned(demand.raw, demand.sha256)
    rebuilt = build(
        registry,
        identity_sha256=data["identity_sha256"],
        parent_sha256=data["parent_sha256"],
        completed_at=data["window"]["completed_at"],
        prior=data["prior"],
        held=data["held"],
        legs=data["legs"],
        used=data["used"],
        branch=data["branch"],
    )
    if rebuilt.raw != demand.raw:
        raise ValueError("Canonical original demand differs")
    return data
