"""Unused, network-free AAPL conditional cycle; never a full historical runner.

Generic execution is restricted to explicitly synthetic fixtures. Retained genuine
pilot inputs have a separate receipt and are never renamed as generic captures.
Native forward arithmetic and sender are unchanged; no authentic-live inference
receipt or historical publication/receive/fill proof is manufactured here.
The decision snapshot is inside the last reader callback, before remaining native
sender/latch work. Outcome snapshots retain sent/pending paper rows; settlement
and journal reconciliation are deliberately not performed or claimed.
"""

import base64
import hashlib
import io
import os
import sqlite3
import stat
from copy import deepcopy
from dataclasses import fields
from datetime import date, timedelta
from pathlib import Path

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import calendar, entry_timing
from backend.market import forward_probability_timing as forward
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_parser as parser
from backend.market import historical_post_resolution_marks as marks
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.alpaca_trading import AlpacaTradingError
from backend.market.historical_packet_store import Store, StorePause
from backend.market.historical_timing_resolver import PilotResolver

WINDOW = packet.schedule("2019-03-01T14:45:00Z")
DAY = date(2019, 3, 1)
META_CAP = 256 * 1024


# Hash original bytes independently of normalized declaration hashes.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Bound local component reads before allocating or interpreting their contents.
def _file(path, *, absent=False):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        if absent:
            return None
        raise
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > META_CAP:
            raise StorePause("Private regular component cap; PAUSED")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(META_CAP + 1)
        after = os.fstat(descriptor)
        current = os.stat(path, follow_symlinks=False)
        identity = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            len(raw) > META_CAP
            or len(raw) != before.st_size
            or any(getattr(before, k) != getattr(after, k) for k in identity)
            or any(getattr(after, k) != getattr(current, k) for k in identity)
        ):
            raise StorePause("Private component changed or exceeded cap; PAUSED")
    finally:
        os.close(descriptor)
    return raw


# Retain immutable bounded components before referencing them in one atomic receipt.
def _put(store, raw, limit=META_CAP):
    return store.put_stream(io.BytesIO(raw), limit=limit, expected_sha256=sha(raw))[0]


# Keep full broker, paper and optional latch in the same complete-operation receipt.
def _components(store, client, root, pins):
    state = _file(paper.state_path(root))
    document = packet._decode(state)
    if set(document) != {f.name for f in fields(paper.PaperState)}:
        raise ValueError("Complete native paper state required")
    latch = _file(entry_timing.latch_path(root, DAY), absent=True)
    if latch is not None and packet._decode(latch).get("session") != DAY.isoformat():
        raise ValueError("Original current-session latch required")
    encoded = codec.encode(client, **pins)
    return {
        "broker": _put(store, encoded, codec.CAPS["bytes"]),
        "paper": _put(store, state),
        "latch": None if latch is None else _put(store, latch),
    }


# Persist one detached receipt containing all component references together.
def _receipt(store, client, root, pins, detail):
    value = {
        "schema": "private-conditional-cycle-receipt/1",
        "identity_sha256": pins["identity_sha256"],
        "adapter_sha256": sha(Path(__file__).read_bytes()),
        "components": _components(store, client, root, pins),
        "detail": deepcopy(detail),
        "actual_historical_clocks_or_fills": False,
        "paper_journal_reconciliation": "NOT_RUN_NATIVE_SENT_PENDING_RETAINED",
    }
    return _put(store, demand.encoded(value))


# Preserve account economics while treating delayed native clocks separately.
def _economics(client):
    value = deepcopy(client.__dict__)
    for key in (
        "_now",
        "_observed_at",
        "_marks",
        "_mark_times",
        "_batch_open",
        "_market_open",
    ):
        value.pop(key)
    return value


# Treat a pre-existing durable operation as uncertain instead of rerunning its work.
def _reserve(store, **parameters):
    try:
        store.reserve_operation(**parameters)
    except sqlite3.IntegrityError as error:
        raise StorePause("Original operation exists; PAUSED without replay") from error


# Bridge only synthetic exact AAPL quote pages to the unchanged pilot authenticator.
def _quote_packet(captured, manifest, verified):
    queries = [q for q in manifest["queries"] if q["kind"] == "quotes"]
    if len(queries) != 1 or queries[0]["parameters"]["symbols"] != "AAPL":
        raise ValueError("AAPL-only connected pilot; multi-symbol venue absent")
    raw = demand.encoded(
        {
            "origin": "SYNTHETIC_GENERIC_PACKET_NOT_PROVIDER_CAPTURE",
            "complete": True,
            "failure": None,
            "pages": captured["groups"][queries[0]["sha256"]],
        }
    )
    return packet.source_packet(WINDOW, raw, sha(raw), verified, kind="quotes")


# Check synthetic opening eligibility without relabelling the generic trade query.
def _anchor(parsed, manifest, original_open):
    queries = [q for q in manifest["queries"] if q["kind"] == "trades"]
    if len(queries) != 1:
        raise ValueError("Complete due-leg trade evidence required")
    rows = parsed["groups"][queries[0]["sha256"]]["AAPL"]["rows"]
    first = []
    for row in rows:
        if first and packet.nanos(row["t"]) > packet.nanos(first[0]["t"]):
            break
        eligible = packet._eligible(row)
        if eligible is None:
            raise ValueError("Unknown synthetic opening eligibility")
        if eligible:
            first.append(row)
    if not first or any(row.get("p") != original_open for row in first):
        raise ValueError("Original synthetic opening reference differs")


# Restore exact component references without executing a decision or submission.
def restore_receipt(store, receipt_sha256, root, *, pins):
    raw = store.read_blob(receipt_sha256, limit=META_CAP)
    receipt = packet._decode(raw)
    if (
        receipt["schema"] != "private-conditional-cycle-receipt/1"
        or receipt["identity_sha256"] != pins["identity_sha256"]
        or receipt["adapter_sha256"] != sha(Path(__file__).read_bytes())
    ):
        raise ValueError("Original source-bound operation receipt required")
    refs = receipt["components"]
    encoded = store.read_blob(refs["broker"], limit=codec.CAPS["bytes"])
    client = codec.restore(encoded, expected_sha256=refs["broker"], **pins)
    state = store.read_blob(refs["paper"], limit=META_CAP)
    document = packet._decode(state)
    if set(document) != {f.name for f in fields(paper.PaperState)}:
        raise ValueError("Complete restored native paper fields required")
    paper.PaperState(**document)
    latch = (
        None
        if refs["latch"] is None
        else store.read_blob(refs["latch"], limit=META_CAP)
    )
    if latch is not None and packet._decode(latch).get("session") != DAY.isoformat():
        raise ValueError("Original restored latch required")
    root = Path(root)
    if not root.resolve().is_relative_to(store.root.resolve()):
        raise ValueError("Fresh private Store descendant required")
    root.mkdir(mode=0o700)
    for path, body in (
        (paper.state_path(root), state),
        (entry_timing.latch_path(root, DAY), latch),
    ):
        if body is None:
            continue
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with path.open("xb") as output:
            os.chmod(path, 0o600)
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
    return client, receipt


# Recover only already-committed operations; an interrupted OPEN operation pauses.
def restore_operation(store, operation, root, *, pins):
    entry = store.recover_operation(operation)
    return restore_receipt(store, entry["receipt_sha256"], root, pins=pins)


# Connect only an already private synthetic N2 account to retained Store operations.
class Cycle:
    # Bind exact native objects and keep every sender write under the private Store.
    def __init__(self, store, client, root, *, pins):
        if type(store) is not Store or type(client) is not native.ReplayBroker:
            raise ValueError("Exact private Store and ReplayBroker required")
        self.store, self.client, self.root, self.pins = store, client, Path(root), pins
        if not self.root.resolve().is_relative_to(store.root.resolve()):
            raise ValueError("Private Store descendant required")
        codec._identity(pins["identity"], pins["identity_sha256"])
        if store.identity != pins["identity_sha256"]:
            raise ValueError("Store and frozen broker identities differ")

    # Derive demand from original full state before examining any response or forecast.
    def begin(self, registry):
        client, store = self.client, self.store
        if store.snapshot()["next_stage"] != "PRIOR_VERIFIED":
            raise StorePause("Cycle already started; never repeat decisions")
        if packet.nanos(client._now.isoformat()) != packet.nanos(
            WINDOW["assumed_decision_at"]
        ):
            raise ValueError("Original fixed decision observation required")
        state = paper.load_state(self.root)
        rows = intraday_orders.due(state, DAY)
        if not rows or any(
            r["symbol"] != "AAPL" or "sending" in r or "execution_policy" in r
            for r in rows
        ):
            raise ValueError("New unsent AAPL-only synthetic pilot legs required")
        prior = _components(store, client, self.root, self.pins)
        cycle = packet._digest(
            {"prior": prior, "window": WINDOW, "identity": store.identity}
        )
        receipt = _receipt(
            store,
            client,
            self.root,
            self.pins,
            {"stage": "PRIOR_VERIFIED", "origin": "SYNTHETIC_GENERIC_PACKET"},
        )
        entry = store.append(
            expected_head=store.snapshot()["head"],
            cycle_sha256=cycle,
            stage="PRIOR_VERIFIED",
            receipt_sha256=receipt,
        )
        value = demand.build(
            registry,
            identity_sha256=store.identity,
            parent_sha256=entry["sha256"],
            completed_at=WINDOW["completed_at"],
            prior={
                "ledger": prior["broker"],
                "pending": packet._digest(state.pending),
                "reservations": packet._digest(client.open_orders()),
                "actions": packet._digest(codec._pack(client._actions)),
                "inputs": receipt,
            },
            held=sorted(n for n, q in client._held.items() if q > 0),
            legs=[
                {
                    "client_order_id": r["client_order_id"],
                    "symbol": r["symbol"],
                    "side": r["side"],
                    "qty": r["qty"],
                    "phase": "market",
                    "session": DAY.isoformat(),
                }
                for r in rows
            ],
            used=store.snapshot()["used"],
        )
        store.declare(value, registry)
        store.append(
            expected_head=store.snapshot()["head"],
            cycle_sha256=cycle,
            stage="DEMAND_FROZEN",
            receipt_sha256=value.sha256,
        )
        store.append(
            expected_head=store.snapshot()["head"],
            cycle_sha256=cycle,
            stage="WAIT_PACKETS",
            receipt_sha256=packet._digest({"cycle": cycle, "waiting": True}),
        )
        return value

    # Bind complete Store bodies to parser admission before freezing inputs.
    def admit(self, manifest, registry, captured):
        declaration = demand.read(manifest, registry)
        parsed = parser.read(captured, manifest, registry)
        raw = packet._decode(captured.raw)
        for query in declaration["queries"]:
            stored = self.store.page_manifest(manifest.sha256, query["sha256"])
            pages = raw["groups"][query["sha256"]]
            if len(stored) != len(pages):
                raise ValueError("Original Store pagination differs")
            for ref, page in zip(stored, pages, strict=True):
                body = self.store.read_blob(
                    ref["receipt"]["body_sha256"],
                    limit=demand.BUDGET["bytes_per_group"],
                )
                if body != base64.b64decode(page["body_base64"], validate=True) or any(
                    ref["receipt"][k] != page[k]
                    for k in ("requested_at", "received_at", "status")
                ):
                    raise ValueError("Original Store page bytes/clocks differ")
        digest = _put(self.store, captured.raw, parser.MAX_CAPTURE_BYTES)
        receipt = _receipt(
            self.store,
            self.client,
            self.root,
            self.pins,
            {
                "stage": "PACKETS_FINALIZED",
                "origin": "SYNTHETIC_GENERIC_PACKET",
                "packet": digest,
                "manifest": manifest.sha256,
                "parser_local_used": parsed["used"],
                "store_charged_used": self.store.snapshot()["used"],
                "actual_http_gets": 0,
            },
        )
        self.store.append(
            expected_head=self.store.snapshot()["head"],
            cycle_sha256=self.store.snapshot()["cycle"],
            stage="PACKETS_FINALIZED",
            receipt_sha256=receipt,
        )
        self.admitted = (
            manifest.sha256,
            registry.sha256,
            captured.sha256,
            self.store.snapshot()["head"],
        )

    # Run one native cycle with explicit synthetic inputs and atomic boundaries.
    def run(self, manifest, registry, captured, distributions, *, original_open=100.0):  # noqa: C901 -- Sequential native/durable boundaries stay visible.
        store, client, root, pins = self.store, self.client, self.root, self.pins
        if store.snapshot()["next_stage"] != "DECISION_FROZEN":
            raise StorePause(
                "Uncertain/already-run cycle must pause; no decision replay"
            )
        if getattr(self, "admitted", None) != (
            manifest.sha256,
            registry.sha256,
            captured.sha256,
            store.snapshot()["head"],
        ):
            raise ValueError("Exact admitted packet/head required")
        declaration = demand.read(manifest, registry)
        prior = packet._decode(
            store.read_blob(declaration["prior"]["inputs"], limit=META_CAP)
        )
        if _components(store, client, root, pins) != prior["components"]:
            raise ValueError("Full broker/paper/latch state changed before decisions")
        parsed = parser.read(captured, manifest, registry)
        raw = packet._decode(captured.raw)
        quote_source = _quote_packet(raw, declaration, captured.verified_at)
        _anchor(parsed, declaration, original_open)
        selected = packet.decision_quote(WINDOW, quote_source)
        if selected["status"] != "available":
            raise StorePause("Decision packet unavailable; no fabricated quote")
        rows = deepcopy(intraday_orders.due(paper.load_state(root), DAY))
        if declaration["prior"]["pending"] != packet._digest(
            paper.load_state(root).pending
        ):
            raise ValueError("Original pending changed before decisions")
        decision = native._instant(WINDOW["assumed_decision_at"])
        completed = native._instant(WINDOW["completed_at"]).astimezone(
            calendar.NEW_YORK
        )
        q = selected["quote"]
        snapshot = {
            "quotes": {
                "AAPL": {
                    "bid": q["bp"],
                    "ask": q["ap"],
                    "bid_size": q["bs"],
                    "ask_size": q["as"],
                    "last": selected["price"],
                    "open": original_open,
                    "next_open": original_open,
                    "bar": (completed - timedelta(minutes=15)).isoformat(),
                    "as_of": q["t"],
                    "received_at": selected["assumed_receive_upper_at"],
                    "next_open_at": WINDOW["completed_at"],
                    "next_open_published_at": WINDOW["assumed_anchor_available_at"],
                    "basis": "raw_current_shares",
                    "feed": "sip",
                }
            }
        }
        distributions = deepcopy(distributions)
        forecasts = forward._forecast_identity(distributions)
        frozen = _put(
            store,
            demand.encoded(
                {
                    "origin": "SYNTHETIC_NUMERIC_FIXTURE",
                    "forecast_identity": forecasts,
                    "arrays": {
                        n: None
                        if v is None
                        else {
                            "residuals": v.residuals.tolist(),
                            "weights": v.weights.tolist(),
                        }
                        for n, v in distributions.items()
                    },
                }
            ),
            2 * 1024**2,
        )
        cycle = store.snapshot()["cycle"]
        decision_op = packet._digest({"cycle": cycle, "stage": "DECISION_FROZEN"})
        submission_op = packet._digest({"cycle": cycle, "stage": "SUBMISSION_CAPTURED"})
        _reserve(
            store,
            operation=decision_op,
            expected_head=store.snapshot()["head"],
            cycle=cycle,
            stage="DECISION_FROZEN",
            inputs=frozen,
        )
        observed = forward.capture_account(client, completed, clock=lambda: decision)
        trace, verdicts = [], []
        reader = forward.build_reader(
            distributions,
            tuple(distributions),
            0,
            DAY,
            decision,
            snapshot,
            rows,
            observed,
            10,
            trace,
            forecast_available_at=native._instant(
                WINDOW["assumed_forecast_available_at"]
            ),
            source_identity={
                "model_receipt": frozen,
                "residual_receipt": frozen,
                "observation": captured.sha256,
            },
        )
        original_economics = _economics(client)
        decision_binding = marks.state_binding(client)
        cached = {"AAPL": client._marks.get("AAPL")}
        factory_calls = 0
        transport_complete = False

        # Freeze every native verdict before the sender can request a client.
        def wrapped(row, latch, quote, now, today):
            if now != decision or today != DAY or client._now != decision:
                raise ValueError("Native decision domain changed")
            verdict = reader(row, latch, quote, now, today)
            if "inference" in (verdict["timed"].get("forward_receipt") or {}):
                raise ValueError("Authentic-live inference receipt forbidden")
            verdicts.append(
                {
                    "client_order_id": row["client_order_id"],
                    "verdict": deepcopy(verdict),
                }
            )
            if len(verdicts) == len(rows):
                receipt = _receipt(
                    store,
                    client,
                    root,
                    pins,
                    {
                        "stage": "DECISION_FROZEN",
                        "snapshot_boundary": (
                            "LAST_READER_CALLBACK_BEFORE_REMAINING_"
                            "NATIVE_SENDER_LATCH_WORK"
                        ),
                        "origin": "SYNTHETIC_NUMERIC_FIXTURE",
                        "verdicts": verdicts,
                        "trace": trace,
                        "forecast": frozen,
                    },
                )
                store.complete_operation(decision_op, receipt)
            return verdict

        # Reserve once, then advance the exact broker using cached decision marks.
        def factory():
            nonlocal factory_calls, transport_complete
            factory_calls += 1
            if (
                factory_calls != 1
                or len(verdicts) != len(rows)
                or _economics(client) != original_economics
                or marks.state_binding(client) != decision_binding
            ):
                raise StorePause("Unfrozen/repeated or changed conditional transport")
            _reserve(
                store,
                operation=submission_op,
                expected_head=store.snapshot()["head"],
                cycle=cycle,
                stage="SUBMISSION_CAPTURED",
                inputs=store.recover_operation(decision_op)["receipt_sha256"],
            )
            if set(client._held) - {"AAPL"}:
                raise ValueError("All held cached marks required; pilot AAPL only")
            client.observe(
                WINDOW["assumed_submission_at"],
                cached,
                native._session(native._instant(WINDOW["assumed_submission_at"]))[1],
            )
            if _economics(client) != original_economics:
                raise StorePause("Delayed transport changed native economics")
            transport_complete = True
            return client

        logs = intraday_orders.send_due(
            root, snapshot, decision, factory, timing_reader=wrapped
        )
        if len(verdicts) != len(rows):
            raise StorePause("Incomplete native verdict set; no decision replay")
        if factory_calls and not transport_complete:
            raise StorePause("Native transport incomplete; OPEN operation stays paused")
        if factory_calls == 0:
            _reserve(
                store,
                operation=submission_op,
                expected_head=store.snapshot()["head"],
                cycle=cycle,
                stage="SUBMISSION_CAPTURED",
                inputs=store.recover_operation(decision_op)["receipt_sha256"],
            )
        submitted = [
            deepcopy(r)
            for r in client._orders.values()
            if r["status"] == "accepted" and r["execution_phase"] == "market"
        ]
        receipt = _receipt(
            store,
            client,
            root,
            pins,
            {
                "stage": "SUBMISSION_CAPTURED",
                "submitted": submitted,
                "attempts": client.attempt_history,
                "factory_calls": factory_calls,
                "empty_submission": factory_calls == 0,
                "native_logs": logs,
                "conditional_window": WINDOW,
            },
        )
        store.complete_operation(submission_op, receipt)
        venue = (
            PilotResolver(client).resolve(
                window=WINDOW,
                submitted=submitted,
                packet=quote_source,
                at=WINDOW["quote_end"],
            )
            if factory_calls
            else {"status": "NO_NATIVE_SUBMISSION", "outcomes": []}
        )
        binding = marks.state_binding(client)
        candidates = marks.select(
            client,
            expected_state_sha256=binding,
            packet=captured,
            manifest=manifest,
            entity_registry=registry,
        )
        nav, reason = None, "Missing all-held candidate marks"
        if candidates["candidate_marks"] is not None:
            at = native._instant(candidates["clocks"]["assumed_mark_observation_at"])
            client.observe(at, candidates["candidate_marks"], native._session(at)[1])
            try:
                nav, reason = client.account().equity, ""
            except AlpacaTradingError as error:
                reason = str(error)
        detail = {
            "stage": "OUTCOME_COMMITTED",
            "origin": "SYNTHETIC_GENERIC_PACKET",
            "verdicts": verdicts,
            "venue": venue,
            "marks": candidates,
            "nav": nav,
            "nav_reason": reason,
            "decision_operation": decision_op,
            "submission_operation": submission_op,
        }
        receipt = _receipt(store, client, root, pins, detail)
        entry = store.append(
            expected_head=store.snapshot()["head"],
            cycle_sha256=cycle,
            stage="OUTCOME_COMMITTED",
            receipt_sha256=receipt,
        )
        return {
            **detail,
            "entry": entry,
            "receipt_sha256": receipt,
            "factory_calls": factory_calls,
        }


# Retain exact genuine pilot inputs separately without claiming generic query admission.
def retain_pilot_inputs(store, *, quote_packet, trade_packet, original_open):
    if quote_packet.kind != "quotes" or trade_packet.kind != "trades":
        raise ValueError("Original separate quote and trade evidence required")
    quote = packet.decision_quote(WINDOW, quote_packet)
    anchor = packet.opening_anchor(WINDOW, trade_packet, original_open)
    quote_capture = packet._decode(quote_packet.source_bytes)
    trade_capture = packet._decode(trade_packet.source_bytes)
    value = {
        "schema": "private-pilot-retained-input/1",
        "status": "PILOT_RETAINED_INPUT",
        "quote_source": _put(
            store, quote_packet.source_bytes, parser.MAX_CAPTURE_BYTES
        ),
        "trade_source": _put(
            store, trade_packet.source_bytes, parser.MAX_CAPTURE_BYTES
        ),
        "decision_quote": quote,
        "opening_anchor": anchor,
        "original_quote_requests": [
            {k: page[k] for k in ("url", "sha256", "requested_at", "received_at")}
            for page in quote_capture["pages"]
        ],
        "original_trade_requests": [
            {
                k: page[k]
                for k in (
                    "endpoint",
                    "parameters",
                    "raw_body_sha256",
                    "actual_requested_at",
                    "actual_received_at",
                )
            }
            for page in trade_capture["requests"]
            if page.get("kind") == "trades"
        ],
        "generic_packets_finalized": False,
        "generic_market_acceptance": False,
        "actual_historical_publication_or_fills": False,
    }
    return value, _put(store, demand.encoded(value))
