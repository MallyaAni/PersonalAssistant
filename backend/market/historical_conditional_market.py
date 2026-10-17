"""Unused generic conditional market adapter, not a historical loader or venue.

Consumes existing demand-bound packets directly. Source-bound anchor rows are
commitments to supplied raw rows, not proof of provider/issuer identity or actual
publication. No model inference, HTTP, auctions or paper settlement happens here.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta

from backend.market import calendar, entry_timing
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_parser as parser
from backend.market import historical_packet_registry as registry
from backend.market import historical_timing_packet as packet
from backend.market import historical_timing_resolver as pilot
from backend.market import replay_broker as native

CAP = 256 * 1024


# Keep the declared cohort and clock immutable before any packet is examined.
@dataclass(frozen=True)
class Context:
    raw: bytes
    sha256: str


# Keep per-name raw anchor bytes separate from caller-selected numeric prices.
@dataclass(frozen=True)
class Anchors:
    raw: bytes
    sha256: str
    sources: tuple


# Admit only exact prior-registered assumptions and supported native reader phases.
def context(completed_at, cohort, *, cohort_sha256):
    window = packet.schedule(completed_at)
    completed = native._instant(completed_at).astimezone(calendar.NEW_YORK)
    session = completed.date()
    clocks = entry_timing.session_clock(session)
    offset = (completed - clocks["open"]).total_seconds()
    decision = native._instant(window["assumed_decision_at"])
    if (
        not native._session(completed)[0]
        or offset < 900
        or offset % 900
        or not clocks["open"] <= decision < clocks["final"]
        or native._instant(window["quote_end"]) >= clocks["close"]
    ):
        raise ValueError("Model-timed regular phase required; final/auctions refused")
    if (
        type(cohort) is not tuple
        or len(cohort) != 96
        or len(set(cohort)) != 96
        or not {"SPY", "QQQ"} <= set(cohort)
        or packet._digest(list(cohort)) != registry.digest(cohort_sha256)
    ):
        raise ValueError("Explicit pinned complete96 timing cohort required")
    for name in cohort:
        registry.symbol(name)
    raw = demand.encoded(
        {
            "schema": "conditional-market-context/1",
            "window": window,
            "cohort": list(cohort),
            "cohort_sha256": cohort_sha256,
            "phase": "MODEL_TIMED_MARKET_ONLY",
        }
    )
    return Context(raw, packet._digest(packet._decode(raw)))


# Rebuild immutable context bytes instead of trusting detached mutable attributes.
def read_context(value):
    if (
        type(value) is not Context
        or type(value.raw) is not bytes
        or len(value.raw) > CAP
    ):
        raise ValueError("Bounded immutable context required")
    data = registry.pinned(value.raw, value.sha256)
    rebuilt = context(
        data["window"]["completed_at"],
        tuple(data["cohort"]),
        cohort_sha256=data["cohort_sha256"],
    )
    if rebuilt.raw != value.raw:
        raise ValueError("Original canonical context required")
    return data


# Retain bounded independently pinned anchor rows with their original byte hashes.
def anchors(raw, expected_sha256, sources):
    if type(raw) is not bytes or len(raw) > CAP or type(sources) is not dict:
        raise ValueError("Bounded original raw anchor receipt required")
    if len(sources) > 192 or any(
        type(v) is not bytes or len(v) > CAP for v in sources.values()
    ):
        raise ValueError("Bounded original raw anchor sources required")
    if sum(len(v) for v in sources.values()) > CAP:
        raise ValueError("Anchor source cap; pause without truncation")
    registry.pinned(raw, expected_sha256)
    for sha, body in sources.items():
        registry.pinned(body, sha)
    return Anchors(raw, expected_sha256, tuple(sources.items()))


# Resolve query symbols without treating request-name provenance as issuer proof.
def rows(captured, manifest, entities):
    declaration = demand.read(manifest, entities)
    parsed = parser.read(captured, manifest, entities)
    mapping = registry.admit(entities, declaration["potential_holdings"])
    output = {"quotes": {}, "trades": {}}
    for query in declaration["queries"]:
        group = parsed["groups"][query["sha256"]]
        for name in query["cohort_keys"]:
            output[query["kind"]][name] = group[mapping[name]["query_symbol"]]["rows"]
    return declaration, output


# Select the latest conservatively received decision book without older fallback.
def _decision(values, window):
    uncertainty = packet.FIXED["event_timestamp_uncertainty_ns"]
    cutoff = (
        packet.nanos(window["assumed_decision_at"])
        - packet.FIXED["quote_receive_delay_ns"]
    )
    known = [r for r in values if packet.nanos(r["t"]) + uncertainty <= cutoff]
    if not known:
        return None
    latest = max(packet.nanos(r["t"]) for r in known)
    cluster = [r for r in known if packet.nanos(r["t"]) == latest]
    return (
        deepcopy(cluster[0])
        if packet._unique(cluster) and packet._book(cluster[0])
        else None
    )


# Validate earliest eligible trades against each pinned consumed raw opening row.
def _anchors(value, declaration, supplied):  # noqa: C901 -- Check each raw source once.
    if type(value) is not Anchors:
        raise ValueError("Immutable original anchor receipt required")
    if type(value.sources) is not tuple or len(dict(value.sources)) != len(
        value.sources
    ):
        raise ValueError("Unique original anchor sources required")
    checked = anchors(value.raw, value.sha256, dict(value.sources))
    data = registry.pinned(checked.raw, checked.sha256)
    names = {r["symbol"] for r in declaration["legs"]}
    if (
        set(data) != {"schema", "origin", "completed_at", "references"}
        or data["schema"] != "conditional-raw-anchors/1"
        or data["origin"]
        not in {"SYNTHETIC_RAW_ROWS", "PINNED_RAW_ROWS_NOT_PROVIDER_PROOF"}
        or data["completed_at"] != declaration["window"]["completed_at"]
        or set(data["references"]) != names
    ):
        raise ValueError("Complete original per-leg anchor binding required")
    output = {}
    for name in sorted(names):
        ref = data["references"][name]
        registry.digest(ref)
        if ref not in dict(checked.sources):
            raise ValueError("Missing original anchor source bytes")
        row = registry.pinned(dict(checked.sources)[ref], ref)
        if (
            set(row) != {"symbol", "at", "open", "basis"}
            or row["symbol"] != name
            or row["at"] != data["completed_at"]
            or row["basis"] != "raw_current_shares"
        ):
            raise ValueError("Original raw anchor identity differs")
        price = pilot._number(row["open"], positive=True)
        first = []
        for trade in supplied["trades"][name]:
            if first and packet.nanos(trade["t"]) > packet.nanos(first[0]["t"]):
                break
            eligible = packet._eligible(trade)
            if eligible is None:
                first = []
                break
            if eligible:
                first.append(trade)
        output[name] = (
            price if first and all(t.get("p") == price for t in first) else None
        )
    return output


# Derive all reader quotes and fresh preheld marks before a native observation occurs.
def decision_inputs(broker, captured, manifest, entities, anchor_receipt, ctx):
    data = read_context(ctx)
    declaration, supplied = rows(captured, manifest, entities)
    window = data["window"]
    if declaration["window"] != window or type(broker) is not native.ReplayBroker:
        raise ValueError("Exact context and private broker required")
    original = deepcopy(broker.__dict__)
    held = {n for n, q in broker._held.items() if q > 0}
    if held != set(declaration["held"]):
        raise ValueError("Full prior holding coverage differs")
    opening = _anchors(anchor_receipt, declaration, supplied)
    decision = packet.nanos(window["assumed_decision_at"])
    prior = (
        None
        if broker._observed_at is None
        else packet.nanos(broker._observed_at.isoformat())
    )
    if broker._now is None or packet.nanos(broker._now.isoformat()) > decision:
        raise ValueError("Original prior clock exceeds upcoming decision")
    quotes, candidates, missing = {}, {}, []
    completed = native._instant(window["completed_at"]).astimezone(calendar.NEW_YORK)
    for name, values in supplied["quotes"].items():
        q = _decision(values, window)
        if q is None or (
            prior is not None
            and packet.nanos(q["t"]) - packet.FIXED["event_timestamp_uncertainty_ns"]
            <= prior + packet.FIXED["event_timestamp_uncertainty_ns"]
        ):
            if name in held:
                missing.append(name)
            continue
        midpoint = q["bp"] / 2 + q["ap"] / 2
        candidates[name] = midpoint
        if name not in opening or opening[name] is None:
            continue
        quotes[name] = {
            "bid": q["bp"],
            "ask": q["ap"],
            "bid_size": q["bs"],
            "ask_size": q["as"],
            "last": midpoint,
            "open": opening[name],
            "next_open": opening[name],
            "bar": (completed - timedelta(minutes=15)).isoformat(),
            "as_of": q["t"],
            "received_at": packet.stamp(
                packet.nanos(q["t"])
                + packet.FIXED["event_timestamp_uncertainty_ns"]
                + packet.FIXED["quote_receive_delay_ns"]
            ),
            "next_open_at": window["completed_at"],
            "next_open_published_at": window["assumed_anchor_available_at"],
            "basis": "raw_current_shares",
            "feed": "sip",
        }
    if held - set(candidates):
        missing = sorted(held - set(candidates))
    if broker.__dict__ != original:
        raise ValueError("Decision packet selection changed native state")
    return {
        "snapshot": {"quotes": quotes},
        "candidate_marks": None if missing else candidates,
        "missing": missing,
        "anchors_sha256": anchor_receipt.sha256,
        "packet_sha256": captured.sha256,
        "historical_actual_clocks": None,
    }


# Choose the first conservative side reference, preserving full-row tie refusal.
def _reference(values, window, side, source_sha256):
    uncertainty = packet.FIXED["event_timestamp_uncertainty_ns"]
    arrival = (
        packet.nanos(window["assumed_arrival_at"])
        + packet.FIXED["arrival_clock_uncertainty_ns"]
    )
    future = [
        r
        for r in values
        if packet.nanos(r["t"]) - uncertainty > arrival
        and packet.nanos(r["t"]) + uncertainty <= packet.nanos(window["quote_end"])
    ]
    for at in sorted({packet.nanos(r["t"]) for r in future}):
        cluster = [r for r in future if packet.nanos(r["t"]) == at]
        if not packet._unique(cluster):
            break
        if packet._book(cluster[0]):
            q = cluster[0]
            return {
                "status": "available",
                "price": q["ap" if side == "buy" else "bp"],
                "event_at": q["t"],
                "quote": deepcopy(q),
                "source_sha256": source_sha256,
                "actual_fill_proven": False,
                "liquidity_capacity_shares": None,
            }
    return {
        "status": "unavailable",
        "price": None,
        "source_sha256": source_sha256,
        "reason": "No qualified unambiguous post-arrival reference; fixed window",
    }


# Admit every original CID and reference before composing native market arithmetic.
class Resolver:
    # Retain one exact private broker and an idempotent complete-batch signature.
    def __init__(self, broker):
        if type(broker) is not native.ReplayBroker:
            raise ValueError("Exact ReplayBroker required")
        self.broker, self.completed = broker, None

    # Resolve the complete current market batch once with a frozen ex-sale cash budget.
    def resolve(self, *, ctx, submitted, captured, manifest, entities, at):  # noqa: C901 -- Batch admission precedes every mutation.
        context_data = read_context(ctx)
        declaration, supplied = rows(captured, manifest, entities)
        window = context_data["window"]
        if declaration["window"] != window or packet.nanos(at) != packet.nanos(
            window["quote_end"]
        ):
            raise ValueError("Exact fixed current deadline required")
        signature = packet._digest(
            {
                "context": ctx.sha256,
                "submitted": submitted,
                "packet": captured.sha256,
                "manifest": manifest.sha256,
                "registry": entities.sha256,
                "at": at,
            }
        )
        broker = self.broker
        if self.completed is not None:
            if (
                signature != self.completed["signature"]
                or broker.__dict__ != self.completed["after"]
            ):
                raise ValueError("Completed batch changed")
            return deepcopy(self.completed["receipt"])
        if (
            broker.cost_bps != 10
            or not broker._batch_open
            or not broker._market_open
            or packet.nanos(broker._now.isoformat())
            != packet.nanos(window["assumed_submission_at"])
        ):
            raise ValueError("Original current10bp submission observation required")
        broker.account()
        pilot._ledger(broker)
        session = native._instant(at).astimezone(calendar.NEW_YORK).date().isoformat()
        due, nondue = pilot._orders(broker, session)
        if type(submitted) not in (list, tuple) or any(
            type(r) is not dict for r in submitted
        ):
            raise ValueError("Complete original native submitted receipts required")
        ids = [r.get("client_order_id") for r in submitted]
        if len(set(ids)) != len(ids) or set(ids) != {
            r["client_order_id"] for _, r in due
        }:
            raise ValueError("Entire native market CID set required")
        bound = dict(zip(ids, submitted, strict=True))
        legs = {r["client_order_id"]: r for r in declaration["legs"]}
        selected = []
        for index, row in due:
            leg = legs.get(row["client_order_id"])
            if (
                leg is None
                or row["symbol"] != leg["symbol"]
                or row["side"] != leg["side"]
                or int(row["qty"]) > leg["qty"]
                or pilot._json(bound[row["client_order_id"]]) != pilot._json(row)
                or packet.nanos(row["submitted_at"])
                != packet.nanos(window["assumed_submission_at"])
            ):
                raise ValueError(
                    "Original CID/side/quantity/submission binding differs"
                )
            reference = _reference(
                supplied["quotes"][row["symbol"]], window, row["side"], captured.sha256
            )
            event = (
                packet.nanos(reference["event_at"])
                + packet.FIXED["event_timestamp_uncertainty_ns"]
                if reference["status"] == "available"
                else packet.nanos(at)
            )
            selected.append((event, index, row["client_order_id"], reference))
        before = deepcopy(broker.__dict__)
        preview, budget = deepcopy(broker), max(0.0, broker._cash - nondue)
        initial, first_fill = budget, len(preview._fills)
        for event, _, cid, reference in sorted(selected, key=lambda r: r[:2]):
            budget = preview._fill(
                preview._orders[cid],
                reference["price"],
                native._instant(packet.stamp(event)),
                budget,
            )
            pilot._number(budget)
            pilot._ledger(preview)
        preview._now, preview._batch_open = native._instant(at), False
        receipt = {
            "status": "CONDITIONAL_GENERIC_MARKET_RESOLUTION",
            "context_sha256": ctx.sha256,
            "original_submitted": deepcopy(list(submitted)),
            "references": [
                {
                    "client_order_id": cid,
                    "assumed_outcome_at": packet.stamp(event),
                    "reference": reference,
                }
                for event, _, cid, reference in sorted(selected, key=lambda r: r[:2])
            ],
            "initial_budget": initial,
            "nondue_reserved_cash": nondue,
            "remaining_budget": budget,
            "outcomes": deepcopy(preview._fills[first_fill:]),
            "nav": None,
            "actual_fills_proven": False,
            "auction_or_full_runner_acceptance": False,
        }
        if broker.__dict__ != before:
            raise ValueError("Native broker changed before atomic batch mutation")
        broker.__dict__ = deepcopy(preview.__dict__)
        self.completed = {
            "signature": signature,
            "after": deepcopy(broker.__dict__),
            "receipt": deepcopy(receipt),
        }
        return receipt
