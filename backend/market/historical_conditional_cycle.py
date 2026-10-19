"""Unused, network-free conditional cycle; never a full historical runner.

Generic execution is restricted to explicitly synthetic fixtures. Retained genuine
pilot inputs have a separate receipt and are never renamed as generic captures.
Native forward arithmetic and sender are unchanged; no authentic-live inference
receipt or historical publication/receive/fill proof is manufactured here.
The decision snapshot is inside the last reader callback, before remaining native
sender/latch work. Default snapshots retain sent/pending paper rows. The optional
CURRENT path retains native reconciliation only with the final complete snapshot.
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
from backend.market import historical_conditional_market as market
from backend.market import historical_packet_checkpoint as checkpoint
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_parser as parser
from backend.market import historical_packet_registry as entities
from backend.market import historical_post_resolution_marks as marks
from backend.market import historical_session_completion as completion
from backend.market import historical_timing_packet as packet
from backend.market import replay_broker as native
from backend.market.alpaca_trading import AlpacaTradingError
from backend.market.historical_packet_store import Store, StorePause
from backend.market.historical_timing_resolver import PilotResolver

WINDOW = packet.schedule("2019-03-01T14:45:00Z")
DAY = date(2019, 3, 1)
META_CAP = 256 * 1024
CURRENT = "3b72cd4e0bc15acd24432d501918c721685a5333"
SETTLEMENT_SHA256 = "b4184036f2cb7899fe72494c9bdccadbc9a1278850e692d402b221afce6e132a"


# Hash original bytes independently of normalized declaration hashes.
def sha(raw):
    return hashlib.sha256(raw).hexdigest()


# Load only the exact reviewed optional fold, leaving the default dependency path alone.
def _settlement_source():
    from backend.market import historical_conditional_settlement

    if sha(Path(historical_conditional_settlement.__file__).read_bytes()) != (
        SETTLEMENT_SHA256
    ):
        raise ValueError("Exact reviewed current settlement source required")
    return historical_conditional_settlement


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


# Capture broker/latch and either legacy paper bytes or a tagged opaque component.
def _components(store, client, root, pins, session=DAY, *, raw_checkpoint=None):
    if raw_checkpoint is None:
        state = _file(paper.state_path(root))
        document = packet._decode(state)
        if set(document) != {f.name for f in fields(paper.PaperState)}:
            raise ValueError("Complete native paper state required")
        paper_ref = None
    else:
        from backend.market import historical_paper_component

        if store.identity != pins["identity_sha256"]:
            raise ValueError("Raw paper Store identity differs")
        paper_ref = historical_paper_component.capture(
            raw_checkpoint, paper.state_path(root), expected_identity=store.identity
        )
    namespace = store.metadata_reservation
    if namespace is not None and namespace.header['account'] != str(root):
        raise ValueError('Original metadata latch workspace differs')
    latch = (_file(entry_timing.latch_path(root, session), absent=True) if namespace is None
             else namespace.read_latch(session.isoformat()))
    if (
        latch is not None
        and packet._decode(latch).get("session") != session.isoformat()
    ):
        raise ValueError("Original current-session latch required")
    encoded = codec.encode(client, **pins)
    return {
        "broker": _put(store, encoded, codec.CAPS["bytes"]),
        "paper": _put(store, state) if raw_checkpoint is None else paper_ref,
        "latch": None if latch is None else _put(store, latch),
    }


# Persist distinct component versions and optionally bind a raw reconciliation save.
def _receipt(
    store,
    client,
    root,
    pins,
    detail,
    *,
    session=DAY,
    context=None,
    settle_current=False,
    raw_checkpoint=None,
    raw_reconciliation=None,
):
    if raw_checkpoint is not None and settle_current:
        raise ValueError("Raw paper settlement is not admitted")
    if raw_reconciliation is not None and raw_checkpoint is None:
        raise ValueError("Raw reconciliation requires explicit component storage")
    value = {
        "schema": "private-conditional-cycle-receipt/1" if raw_checkpoint is None
        else "private-conditional-cycle-receipt/2",
        "identity_sha256": pins["identity_sha256"],
        "adapter_sha256": sha(Path(__file__).read_bytes()),
        "session": session.isoformat(),
        "context": context,
        "generic_adapter_sha256": sha(Path(market.__file__).read_bytes()),
        "final_observer_sha256": sha(Path(completion.__file__).read_bytes()),
        "components": _components(
            store, client, root, pins, session, raw_checkpoint=raw_checkpoint
        ),
        "detail": deepcopy(detail),
        "actual_historical_clocks_or_fills": False,
        "paper_journal_reconciliation": "NOT_RUN_NATIVE_SENT_PENDING_RETAINED",
    }
    if raw_reconciliation is not None:
        value["raw_reconciliation"] = deepcopy(raw_reconciliation)
        value["paper_journal_reconciliation"] = "CURRENT_RAW_NATIVE_RECONCILIATION_COMPONENTS"
        _raw_reconciliation(store, value, pins, raw_checkpoint)
    if settle_current:
        _settlement_source()
        value["current_settlement_sha256"] = SETTLEMENT_SHA256
        if detail["stage"] == "OUTCOME_COMMITTED":
            value["paper_journal_reconciliation"] = (
                "CURRENT_NATIVE_RECONCILIATION_FINAL_COMPONENTS"
            )
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


# Authenticate source-bound receipts and explicit storage mode without adoption.
def _read_receipt(store, receipt_sha256, pins, *, raw_checkpoint=None):
    raw = store.read_blob(receipt_sha256, limit=META_CAP)
    receipt = packet._decode(raw)
    if (
        receipt["schema"] not in (
            "private-conditional-cycle-receipt/1", "private-conditional-cycle-receipt/2"
        )
        or receipt["identity_sha256"] != pins["identity_sha256"]
        or receipt["adapter_sha256"] != sha(Path(__file__).read_bytes())
        or receipt["generic_adapter_sha256"] != sha(Path(market.__file__).read_bytes())
        or receipt["final_observer_sha256"]
        != sha(Path(completion.__file__).read_bytes())
    ):
        raise ValueError("Original source-bound operation receipt required")
    if receipt["schema"] == "private-conditional-cycle-receipt/2":
        from backend.market import historical_paper_component

        if "current_settlement_sha256" in receipt or raw_checkpoint is None:
            raise ValueError("Raw component storage required; settlement not admitted")
        historical_paper_component.verify(
            receipt["components"]["paper"], raw_checkpoint,
            expected_identity=pins["identity_sha256"],
        )
    elif raw_checkpoint is not None or type(receipt["components"]["paper"]) is not str:
        raise ValueError("Receipt paper storage mode differs")
    if "raw_reconciliation" in receipt:
        _raw_reconciliation(store, receipt, pins, raw_checkpoint)
    elif receipt["paper_journal_reconciliation"] == "CURRENT_RAW_NATIVE_RECONCILIATION_COMPONENTS":
        raise ValueError("Raw reconciliation evidence missing")
    if "current_settlement_sha256" in receipt:
        if (
            receipt["current_settlement_sha256"] != SETTLEMENT_SHA256
            or pins["identity"]["source_revision"] != CURRENT
        ):
            raise ValueError("Exact CURRENT settlement receipt profile required")
        _settlement_source()
    return receipt


# Bind final raw state to one plain prior receipt without adopting a Store operation.
def _raw_reconciliation(store, receipt, pins, raw_checkpoint):
    if (receipt["schema"] != "private-conditional-cycle-receipt/2"
            or raw_checkpoint is None or "current_settlement_sha256" in receipt
            or receipt["paper_journal_reconciliation"] != "CURRENT_RAW_NATIVE_RECONCILIATION_COMPONENTS"):
        raise ValueError("Exact raw reconciliation receipt mode required")
    link = receipt["raw_reconciliation"]
    if type(link) is not dict or set(link) != {"pre_settlement_receipt", "evidence"}:
        raise ValueError("Exact prior raw reconciliation link required")
    reference = link["pre_settlement_receipt"]
    prior = packet._decode(store.read_blob(reference, limit=META_CAP))
    if "raw_reconciliation" in prior:
        raise ValueError("Plain prior raw receipt required; recursive evidence refused")
    prior = _read_receipt(store, reference, pins, raw_checkpoint=raw_checkpoint)
    evidence = link["evidence"]
    if (prior["schema"] != "private-conditional-cycle-receipt/2"
            or prior["session"] != receipt["session"]
            or prior["context"] != receipt["context"]
            or evidence["outcome_sha256"] != reference
            or evidence["prior_component"] != prior["components"]["paper"]
            or evidence["broker_checkpoint_sha256"] != receipt["components"]["broker"]
            or any(prior["components"][key] != receipt["components"][key]
                   for key in ("broker", "latch"))):
        raise ValueError("Original raw reconciliation component graph differs")
    broker_ref = receipt["components"]["broker"]
    client = codec.restore(
        store.read_blob(broker_ref, limit=codec.CAPS["bytes"]),
        expected_sha256=broker_ref, **pins,
    )
    if (client._now is None
            or evidence["conditional_observed_at"] != client._now.isoformat()):
        raise ValueError("Raw reconciliation broker observation clock differs")
    return _settlement_source().verify_raw_saved(
        evidence, receipt["components"]["paper"], raw_checkpoint, pins=pins
    )


# Read one bounded indexed checkpoint and reuse its original integrity validator.
def _head_entry(store, expected_head):
    entities.digest(expected_head)
    row = store.connection.execute(
        "SELECT length(raw),substr(raw,1,?) FROM entries WHERE sha=?",
        (META_CAP + 1, expected_head),
    ).fetchone()
    if row is None or row[0] > META_CAP:
        raise StorePause("Original bounded authoritative checkpoint required")
    entry = packet._decode(row[1])
    checkpoint._entry(entry, entry["sequence"], store.identity, entry["parent"])
    if entry["sha256"] != expected_head:
        raise ValueError("Authoritative checkpoint hash differs")
    return entry


# Require immutable continuation from the already committed native submission.
def _current_submission(store, pins, submission_head, cycle):
    operation = packet._digest({"cycle": cycle, "stage": "SUBMISSION_CAPTURED"})
    entry = store.recover_operation(operation)
    if (
        entry["sha256"] != submission_head
        or entry["cycle_sha256"] != cycle
        or entry["stage"] != "SUBMISSION_CAPTURED"
        or _head_entry(store, submission_head) != entry
    ):
        raise ValueError("Exact original committed submission required")
    receipt = _read_receipt(store, entry["receipt_sha256"], pins)
    descriptor = receipt["detail"].get("current_outcome")
    if (
        receipt.get("current_settlement_sha256") != SETTLEMENT_SHA256
        or receipt["detail"]["stage"] != "SUBMISSION_CAPTURED"
        or type(descriptor) is not dict
        or set(descriptor)
        != {
            "schema",
            "settlement_sha256",
            "context_sha256",
            "manifest",
            "registry",
            "registry_evidence",
            "packet",
            "verified_at",
            "facts",
        }
        or descriptor["schema"] != "current-pure-outcome-continuation/1"
        or descriptor["settlement_sha256"] != SETTLEMENT_SHA256
        or descriptor["context_sha256"] != receipt["context"]["sha256"]
        or descriptor["facts"]["submitted"] != receipt["detail"]["submitted"]
        or descriptor["facts"]["factory_calls"] != receipt["detail"]["factory_calls"]
        or descriptor["facts"]["submission_operation"] != operation
        or descriptor["facts"]["decision_operation"]
        != packet._digest({"cycle": cycle, "stage": "DECISION_FROZEN"})
    ):
        raise ValueError("Original opt-in submission continuation required")
    return receipt, descriptor


# Verify legacy settlement only, before any finite decoding of paper components.
def _final_settlement(store, receipt, pins):
    if (receipt["schema"] != "private-conditional-cycle-receipt/1"
            or type(receipt["components"]["paper"]) is not str):
        raise ValueError("Raw paper settlement is not admitted")
    detail = receipt["detail"]
    reference = detail["pre_settlement_receipt"]
    pre = _read_receipt(store, reference, pins)
    evidence = detail["native_reconciliation"]
    parent, cycle = detail["settlement_submission_head"], detail["settlement_cycle"]
    submission, descriptor = _current_submission(store, pins, parent, cycle)
    resolved = {
        key: value
        for key, value in detail.items()
        if key
        not in {
            "pre_settlement_receipt",
            "native_reconciliation",
            "settlement_submission_head",
            "settlement_cycle",
        }
    }
    prior_paper = packet._decode(
        store.read_blob(pre["components"]["paper"], limit=META_CAP)
    )
    final_paper = packet._decode(
        store.read_blob(receipt["components"]["paper"], limit=META_CAP)
    )
    if (
        pre.get("current_settlement_sha256") != SETTLEMENT_SHA256
        or pre["context"] != receipt["context"]
        or receipt["context"] != submission["context"]
        or pre["detail"]
        != {
            "stage": "PRE_SETTLEMENT_OUTCOME",
            "submission_head": parent,
            "cycle": cycle,
            "manifest": descriptor["manifest"],
            "registry": descriptor["registry"],
            "packet": descriptor["packet"],
            "resolved": resolved,
        }
        or any(
            pre["components"][key] != receipt["components"][key]
            for key in ("broker", "latch")
        )
        or any(
            pre["components"][key] != submission["components"][key]
            for key in ("paper", "latch")
        )
        or evidence["outcome_sha256"] != reference
        or evidence["identity_sha256"] != pins["identity_sha256"]
        or evidence["adapter_sha256"] != SETTLEMENT_SHA256
        or evidence["broker_checkpoint_sha256"] != pre["components"]["broker"]
        or evidence["prior_paper_sha256"] != packet._digest(prior_paper)
        or evidence["reconciled_paper_sha256"] != packet._digest(final_paper)
        or evidence["durable_state_committed"] is not False
        or evidence["actual_execution_claim"] is not False
        or receipt["paper_journal_reconciliation"]
        != "CURRENT_NATIVE_RECONCILIATION_FINAL_COMPONENTS"
    ):
        raise ValueError("Original reconciled outcome component graph differs")


# Restore explicit component versions without decisions, submissions or replay.
def restore_receipt(store, receipt_sha256, root, *, pins, raw_checkpoint=None):
    receipt = _read_receipt(
        store, receipt_sha256, pins, raw_checkpoint=raw_checkpoint
    )
    if (
        "current_settlement_sha256" in receipt
        and receipt["detail"]["stage"] == "OUTCOME_COMMITTED"
    ):
        _final_settlement(store, receipt, pins)
    session = date.fromisoformat(receipt["session"])
    if session.isoformat() != receipt["session"]:
        raise ValueError("Canonical original receipt session required")
    if receipt["context"] is not None:
        context = market.Context(
            receipt["context"]["raw"].encode(), receipt["context"]["sha256"]
        )
        if (
            market.read_context(context)["window"]["completed_at"][:10]
            != session.isoformat()
        ):
            raise ValueError("Original context session differs")
    refs = receipt["components"]
    encoded = store.read_blob(refs["broker"], limit=codec.CAPS["bytes"])
    client = codec.restore(encoded, expected_sha256=refs["broker"], **pins)
    raw_paper = receipt["schema"] == "private-conditional-cycle-receipt/2"
    state = None
    if not raw_paper:
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
    if (
        latch is not None
        and packet._decode(latch).get("session") != session.isoformat()
    ):
        raise ValueError("Original restored latch required")
    root = Path(root)
    if not root.resolve().is_relative_to(store.root.resolve()):
        raise ValueError("Fresh private Store descendant required")
    root.mkdir(mode=0o700)
    if raw_paper:
        from backend.market import historical_paper_component

        destination = paper.state_path(root)
        destination.parent.mkdir(mode=0o700, parents=True)
        historical_paper_component.restore(
            refs["paper"], raw_checkpoint, destination,
            expected_identity=pins["identity_sha256"],
        )
    for path, body in (
        (paper.state_path(root), state),
        (entry_timing.latch_path(root, session), latch),
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


# Recover committed components with explicit raw storage; OPEN operations pause.
def restore_operation(store, operation, root, *, pins, raw_checkpoint=None):
    entry = store.recover_operation(operation)
    return restore_receipt(
        store, entry["receipt_sha256"], root, pins=pins, raw_checkpoint=raw_checkpoint
    )


# Connect a private synthetic account to retained native operations.
class Cycle:
    # Bind exact native objects and keep every sender write under the private Store.
    def __init__(
        self, store, client, root, *, pins, context=None, settle_current=False
    ):
        if type(store) is not Store or type(client) is not native.ReplayBroker:
            raise ValueError("Exact private Store and ReplayBroker required")
        self.store, self.client, self.root, self.pins = store, client, Path(root), pins
        if type(settle_current) is not bool:
            raise ValueError("Explicit optional settlement boolean required")
        if settle_current:
            if context is None or pins["identity"]["source_revision"] != CURRENT:
                raise ValueError("CURRENT contextual settlement profile required")
            _settlement_source()
        self.settle_current = settle_current
        self.context = context
        data = None if context is None else market.read_context(context)
        self.window = WINDOW if data is None else data["window"]
        self.day = (
            native._instant(self.window["completed_at"])
            .astimezone(calendar.NEW_YORK)
            .date()
        )
        self.clock = (
            int(
                (
                    native._instant(self.window["completed_at"]).astimezone(
                        calendar.NEW_YORK
                    )
                    - entry_timing.session_clock(self.day)["open"]
                ).total_seconds()
                // 900
            )
            - 1
        )
        self.cohort = None if data is None else tuple(data["cohort"])
        self.phase = "MODEL_TIMED_MARKET_ONLY" if data is None else data["phase"]
        if not self.root.resolve().is_relative_to(store.root.resolve()):
            raise ValueError("Private Store descendant required")
        codec._identity(pins["identity"], pins["identity_sha256"])
        if store.identity != pins["identity_sha256"]:
            raise ValueError("Store and frozen broker identities differ")

    # Bind every snapshot to the current explicit context and both adapter sources.
    def _retain(self, detail):
        context = (
            None
            if self.context is None
            else {"raw": self.context.raw.decode(), "sha256": self.context.sha256}
        )
        return _receipt(
            self.store,
            self.client,
            self.root,
            self.pins,
            detail,
            session=self.day,
            context=context,
            settle_current=self.settle_current,
        )

    # Derive demand from original full state before examining any response or forecast.
    def begin(self, registry):
        client, store = self.client, self.store
        if store.snapshot()["next_stage"] != "PRIOR_VERIFIED":
            raise StorePause("Cycle already started; never repeat decisions")
        if (
            client._now is None
            or (
                self.context is None
                and packet.nanos(client._now.isoformat())
                != packet.nanos(self.window["assumed_decision_at"])
            )
            or packet.nanos(client._now.isoformat())
            > packet.nanos(self.window["assumed_decision_at"])
        ):
            raise ValueError("Original fixed decision observation required")
        state = paper.load_state(self.root)
        rows = intraday_orders.due(state, self.day)
        if (self.context is None and not rows) or any(
            (self.context is None and r["symbol"] != "AAPL")
            or "sending" in r
            or "execution_policy" in r
            or r.get("execution_phase", "market") != "market"
            or (self.cohort is not None and r["symbol"] not in self.cohort)
            or (
                self.phase == "SESSION_COMPLETION_MARKET"
                and r.get("timing_policy") != completion.live_probability_timing.POLICY
            )
            for r in rows
        ):
            raise ValueError("New unsent AAPL-only synthetic pilot legs required")
        if self.context is not None:
            market.read_context(self.context)
            # Prior market legs need their original outcome, never a new window.
            if any(
                r.get("status") == "accepted" and r.get("execution_phase") == "market"
                for r in client._orders.values()
            ):
                raise ValueError("Unresolved prior market batch; no decision replay")
        prior = _components(store, client, self.root, self.pins, self.day)
        cycle = packet._digest(
            {
                "prior": prior,
                "window": self.window,
                "identity": store.identity,
                "context": None if self.context is None else self.context.sha256,
                **(
                    {"current_settlement_sha256": SETTLEMENT_SHA256}
                    if self.settle_current
                    else {}
                ),
            }
        )
        receipt = self._retain(
            {"stage": "PRIOR_VERIFIED", "origin": "SYNTHETIC_GENERIC_PACKET"}
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
            completed_at=self.window["completed_at"],
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
                    "session": self.day.isoformat(),
                }
                for r in rows
            ],
            used=store.snapshot()["used"],
            branch=self.phase,
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
        if declaration["branch"] != self.phase or declaration["window"] != self.window:
            raise ValueError("Original context/demand branch differs")
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
        receipt = self._retain(
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

    # Commit exact continuation inputs before resolver work, never live reader objects.
    def _continuation(self, manifest, registry, captured, facts):
        return {
            "schema": "current-pure-outcome-continuation/1",
            "settlement_sha256": SETTLEMENT_SHA256,
            "context_sha256": self.context.sha256,
            "manifest": _put(self.store, manifest.raw),
            "registry": _put(self.store, registry.raw),
            "registry_evidence": [
                [digest, _put(self.store, raw)] for digest, raw in registry.evidence
            ],
            "packet": _put(self.store, captured.raw, parser.MAX_CAPTURE_BYTES),
            "verified_at": captured.verified_at,
            "facts": deepcopy(facts),
        }

    # Run one native cycle with explicit synthetic inputs and atomic boundaries.
    def run(  # noqa: C901 -- Native and durable boundaries remain sequential.
        self,
        manifest,
        registry,
        captured,
        distributions,
        *,
        original_open=100.0,
        anchors=None,
    ):
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
        final = self.phase == "SESSION_COMPLETION_MARKET"
        if declaration["branch"] != self.phase:
            raise ValueError("Original context/demand branch differs")
        prior = packet._decode(
            store.read_blob(declaration["prior"]["inputs"], limit=META_CAP)
        )
        if prior.get("current_settlement_sha256") != (
            SETTLEMENT_SHA256 if self.settle_current else None
        ):
            raise ValueError("Frozen optional settlement mode changed before decisions")
        if _components(store, client, root, pins, self.day) != prior["components"]:
            raise ValueError("Full broker/paper/latch state changed before decisions")
        decision_inputs = None
        quote_source = None
        if self.context is not None:
            if (
                declaration["window"] != self.window
                or (
                    not final
                    and (
                        tuple(distributions) != self.cohort
                        or any(distributions[n] is not None for n in ("SPY", "QQQ"))
                    )
                )
                or (final and distributions is not None)
            ):
                raise ValueError(
                    "Exact context/cohort and excluded benchmarks required"
                )
            decision_inputs = market.decision_inputs(
                client, captured, manifest, registry, anchors, self.context
            )
        else:
            parsed = parser.read(captured, manifest, registry)
            raw = packet._decode(captured.raw)
            quote_source = _quote_packet(raw, declaration, captured.verified_at)
            _anchor(parsed, declaration, original_open)
            selected = packet.decision_quote(self.window, quote_source)
            if selected["status"] != "available":
                raise StorePause("Decision packet unavailable; no fabricated quote")
        rows = deepcopy(intraday_orders.due(paper.load_state(root), self.day))
        if declaration["prior"]["pending"] != packet._digest(
            paper.load_state(root).pending
        ):
            raise ValueError("Original pending changed before decisions")
        decision = native._instant(self.window["assumed_decision_at"])
        completed = native._instant(self.window["completed_at"]).astimezone(
            calendar.NEW_YORK
        )
        q = None if decision_inputs is not None else selected["quote"]
        snapshot = (
            decision_inputs["snapshot"]
            if decision_inputs is not None
            else {
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
                        "next_open_at": self.window["completed_at"],
                        "next_open_published_at": self.window[
                            "assumed_anchor_available_at"
                        ],
                        "basis": "raw_current_shares",
                        "feed": "sip",
                    }
                }
            }
        )
        if decision_inputs is not None and decision_inputs["candidate_marks"] is None:
            # A recent old account is not permission to skip full held-mark admission.
            snapshot = {"quotes": {}}
        distributions = {} if final else deepcopy(distributions)
        forecasts = None if final else forward._forecast_identity(distributions)
        frozen = _put(
            store,
            demand.encoded(
                {
                    "origin": "NOT_MODEL_TIMED"
                    if final
                    else "SYNTHETIC_NUMERIC_FIXTURE",
                    "forecast_identity": forecasts,
                    "cohort": list(self.cohort) if final else list(distributions),
                    "anchor_receipt": None if anchors is None else anchors.sha256,
                    "anchor_sources": None
                    if anchors is None
                    else {ref: _put(store, body) for ref, body in anchors.sources},
                    "anchor_bytes": None
                    if anchors is None
                    else _put(store, anchors.raw),
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
        decision_admitted = (
            decision_inputs is None or decision_inputs["candidate_marks"] is not None
        )
        if decision_inputs is not None and decision_admitted:
            client.observe(
                decision,
                decision_inputs["candidate_marks"],
                native._session(decision)[1],
            )
        preflight = None
        if final:
            cached_marks = decision_inputs["candidate_marks"] or {}
            preflight = completion.preflight(
                client,
                missing=decision_inputs["missing"],
                missing_submission={r["symbol"] for r in rows} - set(cached_marks),
            )
        observed = (
            None
            if final
            else forward.capture_account(client, completed, clock=lambda: decision)
        )
        trace, verdicts = [], []
        reader = (
            None
            if final
            else forward.build_reader(
                distributions,
                tuple(distributions),
                self.clock,
                self.day,
                decision,
                snapshot,
                rows,
                observed,
                10,
                trace,
                forecast_available_at=native._instant(
                    self.window["assumed_forecast_available_at"]
                ),
                source_identity={
                    "model_receipt": frozen,
                    "residual_receipt": frozen,
                    "observation": captured.sha256,
                },
            )
        )
        original_economics = _economics(client)
        decision_binding = marks.state_binding(client)
        cached = (
            {"AAPL": client._marks.get("AAPL")}
            if decision_inputs is None
            else decision_inputs["candidate_marks"]
        )
        factory_calls = 0
        transport_complete = False

        # Freeze every native verdict before the sender can request a client.
        def wrapped(row, latch, quote, now, today):
            if (
                now != decision
                or today != self.day
                or (decision_admitted and client._now != decision)
                or marks.state_binding(client) != decision_binding
            ):
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
                receipt = self._retain(
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
                        "decision_inputs": decision_inputs,
                        "decision_guard": None
                        if decision_admitted
                        else "DECISION_OBSERVATION_UNAVAILABLE",
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
            if cached is None or set(client._held) - set(cached):
                raise ValueError("All held cached marks required; pilot AAPL only")
            client.observe(
                self.window["assumed_submission_at"],
                cached,
                native._session(native._instant(self.window["assumed_submission_at"]))[
                    1
                ],
            )
            if _economics(client) != original_economics:
                raise StorePause("Delayed transport changed native economics")
            transport_complete = True
            return client

        # Persist native final references only after _ready's original annotations.
        def freeze_final(observation):
            if marks.state_binding(client) != decision_binding:
                raise StorePause("Native final observation changed account state")
            verdicts.extend(observation["verdicts"])
            receipt = self._retain(
                {
                    "stage": "DECISION_FROZEN",
                    "origin": "NOT_MODEL_TIMED",
                    "native_observation": observation,
                    "verdicts": verdicts,
                    "conditional_inputs": frozen,
                    "forecast": None,
                    "decision_inputs": decision_inputs,
                    "preflight": preflight,
                }
            )
            store.complete_operation(decision_op, receipt)

        skipped_final = []
        if final and rows and not preflight["allowed"]:
            skipped_final = [
                {
                    "client_order_id": r["client_order_id"],
                    "disposition": "SKIPPED_NATIVE_FINAL",
                    "native_verdict": None,
                }
                for r in rows
            ]
            receipt = self._retain(
                {
                    "stage": "DECISION_FROZEN",
                    "origin": "NOT_MODEL_TIMED",
                    "verdicts": [],
                    "skipped_native_final": skipped_final,
                    "native_ready_calls": 0,
                    "native_decide_calls": 0,
                    "snapshot_boundary": "PREFLIGHT_SKIP_BEFORE_NATIVE_DISPATCH",
                    "conditional_inputs": frozen,
                    "forecast": None,
                    "decision_inputs": decision_inputs,
                    "preflight": preflight,
                }
            )
            store.complete_operation(decision_op, receipt)
        elif not rows:
            receipt = self._retain(
                {
                    "stage": "DECISION_FROZEN",
                    "origin": "NOT_MODEL_TIMED"
                    if final
                    else "SYNTHETIC_NUMERIC_FIXTURE",
                    "verdicts": [],
                    "trace": [],
                    "forecast": None if final else frozen,
                    "conditional_inputs": frozen if final else None,
                    "snapshot_boundary": "NO_DUE_INTENTS_EXPLICIT_EMPTY_DECISION",
                }
            )
            store.complete_operation(decision_op, receipt)
        logs = (
            completion.dispatch(
                root=root,
                rows=rows,
                now=decision,
                context=self.context,
                source_sha256=pins["identity"]["source_sha256"][
                    "backend/agents/trading/desk/intraday_orders.py"
                ],
                factory=factory,
                freeze=freeze_final,
            )
            if final and rows and preflight["allowed"]
            else []
            if final
            else intraday_orders.send_due(
                root, snapshot, decision, factory, timing_reader=wrapped
            )
        )
        if not skipped_final and len(verdicts) != len(rows):
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
        facts = {
            "verdicts": verdicts,
            "submitted": submitted,
            "decision_operation": decision_op,
            "submission_operation": submission_op,
            "decision_inputs": decision_inputs,
            "classification": "NOT_MODEL_TIMED" if final else "MODEL_TIMED_MARKET_ONLY",
            "preflight": preflight,
            "skipped_native_final": skipped_final,
            "decision_guard": None
            if decision_admitted
            else "DECISION_OBSERVATION_UNAVAILABLE",
            "factory_calls": factory_calls,
        }
        submission = {
            "stage": "SUBMISSION_CAPTURED",
            "submitted": submitted,
            "attempts": client.attempt_history,
            "factory_calls": factory_calls,
            "empty_submission": factory_calls == 0,
            "native_logs": logs,
            "conditional_window": self.window,
        }
        if self.settle_current:
            submission["current_outcome"] = self._continuation(
                manifest, registry, captured, facts
            )
        receipt = self._retain(submission)
        store.complete_operation(submission_op, receipt)
        return self._finish_outcome(manifest, registry, captured, facts, quote_source)

    # Recompute only deterministic resolver/mark/fold work after committed submission.
    def _finish_outcome(self, manifest, registry, captured, facts, quote_source=None):
        store, client = self.store, self.client
        state = store.snapshot()
        submission_head, cycle = state["head"], state["cycle"]
        if state["next_stage"] != "OUTCOME_COMMITTED":
            raise StorePause("Exact committed submission required before outcome")
        head = _head_entry(store, submission_head)
        submitted_receipt = _read_receipt(store, head["receipt_sha256"], self.pins)
        if submitted_receipt.get("current_settlement_sha256") != (
            SETTLEMENT_SHA256 if self.settle_current else None
        ):
            raise ValueError("Frozen optional settlement mode changed after submission")
        if self.settle_current:
            submission, continuation = _current_submission(
                store, self.pins, submission_head, cycle
            )
            if continuation != self._continuation(
                manifest, registry, captured, facts
            ) or submission["components"] != _components(
                store, client, self.root, self.pins, self.day
            ):
                raise ValueError("Original immutable outcome continuation differs")
        submitted, factory_calls = facts["submitted"], facts["factory_calls"]
        decision_inputs = facts["decision_inputs"]
        decision_admitted = facts["decision_guard"] is None
        venue = (
            market.Resolver(client).resolve(
                ctx=self.context,
                submitted=submitted,
                captured=captured,
                manifest=manifest,
                entities=registry,
                at=self.window["quote_end"],
            )
            if factory_calls and self.context is not None
            else PilotResolver(client).resolve(
                window=self.window,
                submitted=submitted,
                packet=quote_source,
                at=self.window["quote_end"],
            )
            if factory_calls
            else {"status": "NO_NATIVE_SUBMISSION", "outcomes": []}
        )
        binding = marks.state_binding(client)
        candidates = (
            marks.select(
                client,
                expected_state_sha256=binding,
                packet=captured,
                manifest=manifest,
                entity_registry=registry,
            )
            if decision_admitted
            else {
                "candidate_marks": None,
                "missing": decision_inputs["missing"],
                "status": "DECISION_OBSERVATION_UNAVAILABLE",
                "nav": None,
            }
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
            "verdicts": facts["verdicts"],
            "venue": venue,
            "marks": candidates,
            "nav": nav,
            "nav_reason": reason,
            "decision_operation": facts["decision_operation"],
            "submission_operation": facts["submission_operation"],
            "decision_inputs": decision_inputs,
            "classification": facts["classification"],
            "preflight": facts["preflight"],
            "skipped_native_final": facts["skipped_native_final"],
            "decision_guard": None
            if decision_admitted
            else "DECISION_OBSERVATION_UNAVAILABLE",
        }
        if self.settle_current:
            self._fold_current(
                detail, manifest, registry, captured, submission_head, cycle
            )
        receipt = self._retain(detail)
        entry = store.append(
            expected_head=store.snapshot()["head"],
            cycle_sha256=cycle,
            stage="OUTCOME_COMMITTED",
            receipt_sha256=receipt,
        )
        if self.settle_current:
            store._point("current_outcome_committed")
        return {
            **detail,
            "entry": entry,
            "receipt_sha256": receipt,
            "factory_calls": factory_calls,
        }

    # Authenticate an internally retained outcome before pure fold and native save/read.
    def _fold_current(self, detail, manifest, registry, captured, parent, cycle):
        pre_detail = {
            "stage": "PRE_SETTLEMENT_OUTCOME",
            "submission_head": parent,
            "cycle": cycle,
            "manifest": manifest.sha256,
            "registry": registry.sha256,
            "packet": captured.sha256,
            "resolved": deepcopy(detail),
        }
        reference = self._retain(pre_detail)
        retained = _read_receipt(self.store, reference, self.pins)
        if (
            retained["detail"] != pre_detail
            or retained["components"]
            != _components(self.store, self.client, self.root, self.pins, self.day)
            or retained["context"]["sha256"] != self.context.sha256
        ):
            raise ValueError(
                "Original internally bound pre-settlement receipt required"
            )
        self.store._point("current_outcome_resolved")
        before = codec.encode(self.client, **self.pins)
        updated, evidence = _settlement_source().reconcile(
            self.client,
            paper.load_state(self.root),
            pins=self.pins,
            outcome_sha256=reference,
            observed_at=self.client._now.isoformat(),
        )
        paper.save_state(self.root, updated)
        if (
            demand.encoded(paper.load_state(self.root).__dict__)
            != demand.encoded(updated.__dict__)
            or codec.encode(self.client, **self.pins) != before
            or _file(entry_timing.latch_path(self.root, self.day), absent=True)
            != (
                None
                if retained["components"]["latch"] is None
                else self.store.read_blob(
                    retained["components"]["latch"], limit=META_CAP
                )
            )
        ):
            raise StorePause("Native reconciled save/read changed original components")
        self.store._point("current_settlement_saved")
        detail.update(
            {
                "pre_settlement_receipt": reference,
                "native_reconciliation": evidence,
                "settlement_submission_head": parent,
                "settlement_cycle": cycle,
            }
        )


# Restore externally pinned continuation inputs without evaluating a reader or sender.
def _restore_continuation(store, descriptor, receipt):
    context = market.Context(
        receipt["context"]["raw"].encode(), descriptor["context_sha256"]
    )
    market.read_context(context)
    registry = entities.Registry(
        store.read_blob(descriptor["registry"], limit=META_CAP),
        descriptor["registry"],
        tuple(
            (digest, store.read_blob(reference, limit=META_CAP))
            for digest, reference in descriptor["registry_evidence"]
        ),
    )
    manifest = demand.Demand(
        store.read_blob(descriptor["manifest"], limit=META_CAP), descriptor["manifest"]
    )
    declaration = demand.read(manifest, registry)
    if (
        declaration["window"] != market.read_context(context)["window"]
        or declaration["branch"] != market.read_context(context)["phase"]
    ):
        raise ValueError("Original continuation demand/context differs")
    captured = parser.packets(
        store.read_blob(descriptor["packet"], limit=parser.MAX_CAPTURE_BYTES),
        descriptor["packet"],
        manifest,
        registry,
        descriptor["verified_at"],
    )
    return context, manifest, registry, captured


# Recover only the pure submission tail, or restore an already committed final snapshot.
def resume_current_outcome(
    store,
    root,
    *,
    pins,
    expected_head,
    expected_cycle,
    submission_head,
    context_sha256,
    demand_sha256,
    registry_sha256,
    packet_sha256,
):
    if type(store) is not Store or pins["identity"]["source_revision"] != CURRENT:
        raise ValueError("Exact CURRENT private outcome recovery required")
    for digest in (
        expected_head,
        expected_cycle,
        submission_head,
        context_sha256,
        demand_sha256,
        registry_sha256,
        packet_sha256,
    ):
        entities.digest(digest)
    state = store.snapshot()
    if (
        state["head"] != expected_head
        or state["cycle"] != expected_cycle
        or store.identity != pins["identity_sha256"]
    ):
        raise StorePause("External authoritative outcome head/cycle differs")
    entry = _head_entry(store, expected_head)
    submission, descriptor = _current_submission(
        store, pins, submission_head, expected_cycle
    )
    if (
        descriptor["context_sha256"] != context_sha256
        or descriptor["manifest"] != demand_sha256
        or descriptor["registry"] != registry_sha256
        or descriptor["packet"] != packet_sha256
    ):
        raise ValueError("Externally pinned continuation inputs differ")
    if entry["stage"] == "OUTCOME_COMMITTED":
        if entry["parent"] != submission_head:
            raise ValueError("Original immediate outcome descendant required")
        final = _read_receipt(store, entry["receipt_sha256"], pins)
        if (
            final.get("current_settlement_sha256") != SETTLEMENT_SHA256
            or final["detail"]["settlement_submission_head"] != submission_head
            or final["detail"]["settlement_cycle"] != expected_cycle
        ):
            raise ValueError("Original committed reconciled outcome required")
        client, final = restore_receipt(store, entry["receipt_sha256"], root, pins=pins)
        return client, {
            **final["detail"],
            "entry": entry,
            "receipt_sha256": entry["receipt_sha256"],
            "factory_calls": descriptor["facts"]["factory_calls"],
        }
    if (
        entry["stage"] != "SUBMISSION_CAPTURED"
        or expected_head != submission_head
        or state["next_stage"] != "OUTCOME_COMMITTED"
    ):
        raise StorePause("Uncommitted decision/submission never re-executed")
    context, manifest, registry, captured = _restore_continuation(
        store, descriptor, submission
    )
    client, _ = restore_receipt(store, entry["receipt_sha256"], root, pins=pins)
    current = Cycle(
        store, client, root, pins=pins, context=context, settle_current=True
    )
    result = current._finish_outcome(manifest, registry, captured, descriptor["facts"])
    return client, result


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
