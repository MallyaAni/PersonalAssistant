"""Synthetic generic connected cycles; no provider/model/historical acceptance."""

import base64
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pytest
from test_historical_conditional_cycle import (
    import_capture,
    intent,
)
from test_historical_conditional_cycle import (
    no_external_calls as shared_external,
)
from test_historical_conditional_cycle import (
    pins as shared_pins,
)

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_conditional_cycle as connected
from backend.market import historical_conditional_market as market
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_parser as parser
from backend.market import historical_packet_registry as registry
from backend.market import historical_timing_packet as packet
from backend.market import probabilistic_execution as probability
from backend.market import replay_broker as native
from backend.market.historical_packet_store import Store, StorePause

CASES = []


# Admit the same fixture guards without depending on pytest's test-file import order.
@pytest.fixture(autouse=True)
def forbidden_external(monkeypatch):
    return shared_external.__wrapped__(monkeypatch)


# Reuse the original real source-admission fixture without any admission stub.
@pytest.fixture
def pins():
    return shared_pins.__wrapped__()


# Load only the committed cohort declaration, never its original model arrays.
def cohort():
    path = (
        Path(connected.__file__).parents[2]
        / "docs/research/historical-timing-genuine-feature-proof-2026-10-17.json"
    )
    return tuple(packet._decode(path.read_bytes())["symbols"])


# Bind one arbitrary reviewed regular bar to the frozen declared full cohort.
def context(at="2019-03-01T14:45:00Z"):
    names = cohort()
    return market.context(at, names, cohort_sha256=packet._digest(list(names)))


# Retain explicit synthetic request-name evidence for every due and held name.
def mapping(names):
    evidence = b"SYNTHETIC multi-name request metadata; no issuer proof"
    review = b"SYNTHETIC fixed entity-asof naming assumption"
    raw = demand.encoded(
        {
            "schema": "historical-entity-registry/1",
            "entries": [
                {
                    "cohort_key": name,
                    "query_symbol": name,
                    "entity_asof": "2026-10-13",
                    "status": "REVIEWED_CONDITIONAL_MAPPING",
                    "issuer_identity": None,
                    "assumption": "Synthetic names only, not authenticated issuers",
                    "review_sha256": connected.sha(review),
                    "sources": [
                        {
                            "kind": "request_metadata",
                            "sha256": connected.sha(evidence),
                            "source_label": "synthetic",
                        }
                    ],
                }
                for name in sorted(names)
            ],
        }
    )
    return registry.registry(
        raw,
        connected.sha(raw),
        {connected.sha(evidence): evidence, connected.sha(review): review},
    )


# Preserve each synthetic consumed raw opening as immutable independently pinned bytes.
def anchor_receipt(manifest, reg, *, alter=None):
    decl = demand.read(manifest, reg)
    refs, sources = {}, {}
    for name in sorted({r["symbol"] for r in decl["legs"]}):
        row = {
            "symbol": name,
            "at": decl["window"]["completed_at"],
            "open": 100.0,
            "basis": "raw_current_shares",
        }
        if alter is not None:
            row.update(alter)
        raw = demand.encoded(row)
        refs[name] = connected.sha(raw)
        sources[refs[name]] = raw
    raw = demand.encoded(
        {
            "schema": "conditional-raw-anchors/1",
            "origin": "SYNTHETIC_RAW_ROWS",
            "completed_at": decl["window"]["completed_at"],
            "references": refs,
        }
    )
    return market.anchors(raw, connected.sha(raw), sources)


# Build fixed-window synthetic plural bodies without relabelling retained pilot bytes.
def capture(manifest, reg, *, absent=(), no_reference=(), conflict=()):
    groups = {}
    decl = demand.read(manifest, reg)
    boundary = packet.nanos(decl["window"]["completed_at"])
    for query in decl["queries"]:
        values = {}
        for name in query["parameters"]["symbols"].split(","):
            if name in absent:
                continue
            if query["kind"] == "trades":
                rows = [
                    {
                        "t": packet.stamp(boundary + 7_000_000),
                        "p": 100.0,
                        "s": 100,
                        "c": ["@"],
                        "z": "C",
                    }
                ]
            else:
                rows = [
                    {
                        "t": packet.stamp(boundary + 30_900_000_000),
                        "bp": 99.99,
                        "ap": 100.01,
                        "bs": 1,
                        "as": 1,
                    }
                ]
                if name not in no_reference:
                    rows.append(
                        {
                            "t": packet.stamp(boundary + 31_332_000_000),
                            "bp": 199.99,
                            "ap": 200.0,
                            "bs": 1,
                            "as": 1,
                        }
                    )
                if name in conflict:
                    rows.extend(
                        [
                            {
                                **rows[-1],
                                "t": packet.stamp(boundary + 32_900_000_000),
                                "ax": exchange,
                            }
                            for exchange in ("J", "K")
                        ]
                    )
            values[name] = rows
        body = demand.encoded({query["kind"]: values, "next_page_token": None})
        groups[query["sha256"]] = [
            {
                "url": query["endpoint"] + "?" + urlencode(query["parameters"]),
                "requested_at": "2026-10-17T15:59:00Z",
                "received_at": "2026-10-17T15:59:01Z",
                "status": 200,
                "body_complete": True,
                "failure": None,
                "body_base64": base64.b64encode(body).decode(),
                "sha256": connected.sha(body),
            }
        ]
    raw = demand.encoded(
        {
            "schema": "historical-demand-capture/1",
            "demand_sha256": manifest.sha256,
            "complete": True,
            "failure": None,
            "groups": groups,
        }
    )
    return parser.packets(
        raw, connected.sha(raw), manifest, reg, "2026-10-17T16:00:00Z"
    )


# Construct private accounts at their prior observation, before acquisition.
@pytest.fixture
def make(tmp_path, pins):
    stores = []

    # Admit one synthetic cycle through original Store and parser paths.
    def new(
        *,
        rows=None,
        held=None,
        absent=(),
        no_reference=(),
        conflict=(),
        mode="execute",
        at="2019-03-01T14:45:00Z",
        reserve=False,
        prior_market=False,
        registry_missing=(),
        prior_delay=-60,
    ):
        ctx = context(at)
        window = market.read_context(ctx)["window"]
        day = native._instant(at).astimezone(native.calendar.NEW_YORK).date()
        legs = [] if rows == [] else deepcopy(rows or [intent("buy", 5)])
        for row in legs:
            row["execute_on"] = day.isoformat()
        store = Store(
            tmp_path / str(len(stores)), pins["identity_sha256"], None, create=True
        )
        stores.append(store)
        client = native.ReplayBroker(
            1000,
            10,
            initial_holdings={
                n: int(q * 4) if q != int(q) else q for n, q in (held or {}).items()
            },
            initial_average_prices={
                n: 25 if q != int(q) else 100 for n, q in (held or {}).items()
            },
        )
        prior = native._instant(
            packet.stamp(packet.nanos(window["completed_at"]) + prior_delay * packet.NS)
        )
        names = set(held or {}) | {r["symbol"] for r in legs}
        client.observe(
            prior, {n: 100 for n in names | {"GOOG"}}, native._session(prior)[1]
        )
        for name, quantity in (held or {}).items():
            if quantity != int(quantity):
                client.apply_split(name, 0.25, prior)
        client.observe(
            prior, {n: 100 for n in names | {"GOOG"}}, native._session(prior)[1]
        )
        if reserve:
            client.submit_market_on_close("GOOG", 1, "buy", "SYNTHETIC-nondue-reserve")
        if prior_market:
            client.submit_market("AAPL", 1, "buy", "SYNTHETIC-unresolved-prior")
        root = store.root / "working"
        paper.save_state(root, paper.PaperState(pending=deepcopy(legs)))
        latch = connected.entry_timing.latch_path(root, day)
        latch.parent.mkdir(parents=True, exist_ok=True)
        latch.write_bytes(
            demand.encoded(
                {"session": day.isoformat(), "stocks": {}, "origin": "SYNTHETIC"}
            )
        )
        reg = mapping((names or {"AAPL"}) - set(registry_missing))
        cycle = connected.Cycle(store, client, root, pins=pins, context=ctx)
        manifest = cycle.begin(reg)
        original = codec._pack(client.__dict__)
        prior_attempts = deepcopy(client._attempts)
        captured = capture(
            manifest, reg, absent=absent, no_reference=no_reference, conflict=conflict
        )
        import_capture(store, manifest, reg, captured)
        cycle.admit(manifest, reg, captured)
        assert codec._pack(client.__dict__) == original
        distributions = {name: None for name in cohort()}
        for row in legs:
            distributions[row["symbol"]] = (
                None
                if mode == "unavailable"
                else probability.Distribution(
                    0.02 if mode == "wait" else 0.0,
                    0.001,
                    np.array([-1.0, 1.0]) if mode == "wait" else np.array([0.0, 0.0]),
                    np.array([0.5, 0.5]),
                )
            )
        return {
            "cycle": cycle,
            "client": client,
            "store": store,
            "root": root,
            "pins": pins,
            "context": ctx,
            "manifest": manifest,
            "registry": reg,
            "captured": captured,
            "distributions": distributions,
            "anchors": anchor_receipt(manifest, reg),
            "prior": original,
            "prior_attempts": prior_attempts,
        }

    yield new
    for store in stores:
        store.close()


# Record actual synthetic connected results while retaining original receipt references.
def run(value):
    result = value["cycle"].run(
        value["manifest"],
        value["registry"],
        value["captured"],
        value["distributions"],
        anchors=value["anchors"],
    )
    CASES.append(
        {
            "origin": "SYNTHETIC_GENERIC_CONNECTED",
            "context": market.read_context(value["context"]),
            "result": result,
            "ledger": value["client"].ledger(),
            "attempts": value["client"].attempt_history,
            "provider_gets": 0,
            "new_head_inference_calls": 0,
        }
    )
    return result


# Restore each complete operation without replaying decisions or native submissions.
def restored(value, result):
    for stage in ("decision", "submission"):
        clone, receipt = connected.restore_operation(
            value["store"],
            result[stage + "_operation"],
            value["store"].root / ("restored-" + stage),
            pins=value["pins"],
        )
        assert receipt["context"]["sha256"] == value["context"].sha256
        assert clone._attempts == (
            value["prior_attempts"]
            if stage == "decision"
            else value["client"]._attempts
        )
    clone, receipt = connected.restore_receipt(
        value["store"],
        result["receipt_sha256"],
        value["store"].root / "restored-final",
        pins=value["pins"],
    )
    assert codec._pack(clone.__dict__) == codec._pack(value["client"].__dict__)
    assert (
        receipt["paper_journal_reconciliation"]
        == "NOT_RUN_NATIVE_SENT_PENDING_RETAINED"
    )
    assert (
        paper.state_path(value["root"]).read_bytes()
        == paper.state_path(value["store"].root / "restored-final").read_bytes()
    )


# Prove a first SELL cannot fund the later other-symbol BUY under one frozen budget.
def test_two_symbol_sell_first_cash_basis_fee_and_restoration(make):
    sell, buy = intent("sell", 8), intent("buy", 5, 1)
    buy["symbol"] = "MSFT"
    value = make(rows=[sell, buy], held={"AAPL": 5, "NVDA": 2}, reserve=True)
    result = run(value)
    client = value["client"]
    assert client._held == {"MSFT": 4, "NVDA": 2}
    assert client._average == {"MSFT": 200, "NVDA": 100}
    assert client._cash == pytest.approx(float(Decimal("1198.15005")), abs=1e-10, rel=0)
    assert result["venue"]["initial_budget"] == pytest.approx(899.9)
    assert result["venue"]["nondue_reserved_cash"] == pytest.approx(100.1)
    assert [r["symbol"] for r in result["venue"]["outcomes"]] == ["AAPL", "MSFT"]
    assert [r["filled_qty"] for r in result["venue"]["outcomes"]] == [5, 4]
    assert result["marks"]["required_holdings"] == {"MSFT": 4, "NVDA": 2}
    assert result["nav"] == pytest.approx(
        float(Decimal("1198.15005") + Decimal("199.995") * 6)
    )
    assert paper.load_state(value["root"]).journal == []
    restored(value, result)


# Missing any third held name prevents decision observation and every submission.
def test_missing_third_held_preserves_prior_clock_and_no_sender(make):
    value = make(held={"NVDA": 2}, absent=("NVDA",))
    result = run(value)
    assert codec._pack(value["client"].__dict__) == value["prior"]
    assert result["factory_calls"] == 0
    assert result["nav"] is None
    assert result["marks"]["status"] == "DECISION_OBSERVATION_UNAVAILABLE"
    assert result["decision_inputs"]["missing"] == ["NVDA"]
    restored(value, result)


# A recent prior account must not bypass missing all-held packet admission.
def test_recent_prior_account_cannot_bypass_missing_held_packet(make):
    value = make(held={"NVDA": 2}, absent=("NVDA",), prior_delay=10)
    result = run(value)
    assert result["factory_calls"] == 0
    assert value["client"]._attempts == []
    assert codec._pack(value["client"].__dict__) == value["prior"]
    assert result["nav"] is None
    assert result["marks"]["status"] == "DECISION_OBSERVATION_UNAVAILABLE"
    assert result["verdicts"][0]["verdict"]["send"] is None
    evidence = result["verdicts"][0]["verdict"]["timed"]["forward_receipt"]
    assert evidence["account"]["receipt"]["reason"] == ""
    assert (
        evidence["account"]["receipt"]["source_timestamps"]
        == ["2019-03-01T14:45:10+00:00"] * 2
    )
    assert evidence["quotes"] == {}
    assert "AAPL" in result["decision_inputs"]["snapshot"]["quotes"]
    assert result["decision_guard"] == "DECISION_OBSERVATION_UNAVAILABLE"


# Legitimate fractional residue is preserved while native timing refuses its account.
def test_fractional_held_is_not_rounded_to_force_timing(make):
    value = make(held={"NVDA": 2.5})
    result = run(value)
    assert value["client"]._held == {"NVDA": 2.5}
    assert result["factory_calls"] == 0
    assert "whole-share" in result["verdicts"][0]["verdict"]["timed"]["reason"]
    assert result["nav"] == pytest.approx(1499.9875)


# Explicit WAIT, unavailable and no-intent decisions all commit empty submission.
@pytest.mark.parametrize("mode", ["wait", "unavailable", "empty"])
def test_empty_submission_branches(make, mode):
    value = make(rows=[] if mode == "empty" else None, mode=mode)
    result = run(value)
    assert result["factory_calls"] == 0
    assert value["client"]._attempts == []
    assert result["venue"]["status"] == "NO_NATIVE_SUBMISSION"
    assert result["verdicts"] == [] if mode == "empty" else len(result["verdicts"]) == 1
    restored(value, result)


# Missing execution evidence expires the whole native intent at the fixed deadline.
def test_missing_postarrival_reference_expires_without_fill(make):
    value = make(no_reference=("AAPL",))
    result = run(value)
    assert value["client"]._held == {}
    assert value["client"]._cash == 1000
    order = next(iter(value["client"]._orders.values()))
    assert order["status"] == "expired"
    assert order["filled_qty"] == "0"
    assert result["venue"]["references"][0]["reference"]["status"] == "unavailable"


# The latest conflicting held quote cannot fall back after a real conditional fill.
def test_conflicting_postfill_mark_keeps_nav_unavailable(make):
    value = make(conflict=("AAPL",))
    result = run(value)
    assert value["client"]._held == {"AAPL": 4}
    assert result["nav"] is None
    assert result["marks"]["missing"] == ["AAPL"]
    assert value["client"]._observed_at.isoformat().endswith("31.200000+00:00")


# Final windows, auction/open boundaries, holidays and unaligned clocks refuse early.
@pytest.mark.parametrize(
    "at",
    [
        "2019-03-01T20:45:00Z",
        "2019-03-01T14:30:00Z",
        "2019-03-02T14:45:00Z",
        "2019-03-01T14:46:00Z",
        "2019-11-29T17:45:00Z",
    ],
)
def test_unsupported_calendar_phase_before_transport(at):
    with pytest.raises(ValueError, match="phase|boundary"):
        context(at)


# An arbitrary early-close session still uses its reviewed bar and conditional clocks.
def test_early_close_supported_bar_context_and_restoration(make):
    value = make(at="2019-11-29T17:15:00Z", mode="wait")
    result = run(value)
    assert value["cycle"].clock == 10
    assert result["factory_calls"] == 0
    restored(value, result)


# Changed raw anchors or incomplete forecast cohorts fail before native observation.
@pytest.mark.parametrize("mode", ["anchor", "cohort"])
def test_source_bound_inputs_refuse_before_mutation(make, mode):
    value = make()
    if mode == "anchor":
        value["anchors"] = anchor_receipt(
            value["manifest"], value["registry"], alter={"symbol": "MSFT"}
        )
    else:
        value["distributions"].pop("QQQ")
    before = deepcopy(value["client"].__dict__)
    with pytest.raises(ValueError, match="anchor identity|context/cohort"):
        run(value)
    assert value["client"].__dict__ == before
    assert not value["client"]._attempts


# An OPEN decision receipt blocks every second reader evaluation after interruption.
def test_open_decision_crash_pauses_without_repeated_reader(make, monkeypatch):
    value = make()
    original = value["store"].complete_operation

    # Interrupt only the first native verdict commit, retaining the OPEN operation.
    def failed(operation, receipt):
        raise StorePause("SYNTHETIC crash before decision commit")

    monkeypatch.setattr(value["store"], "complete_operation", failed)
    with pytest.raises(StorePause):
        run(value)
    monkeypatch.setattr(value["store"], "complete_operation", original)
    before = deepcopy(value["client"].__dict__)
    with pytest.raises((StorePause, ValueError)):
        run(value)
    assert value["client"].__dict__ == before
    assert not value["client"]._attempts


# A committed submission can restore after an outcome interruption without replay.
def test_submission_restore_after_resolver_crash(make, monkeypatch):
    value = make()

    # Interrupt before any native venue arithmetic while preserving accepted orders.
    def failed(*args, **kwargs):
        raise StorePause("SYNTHETIC crash before resolver")

    monkeypatch.setattr(market.Resolver, "resolve", failed)
    with pytest.raises(StorePause):
        run(value)
    snapshot = value["store"].snapshot()
    operation = packet._digest(
        {"cycle": snapshot["cycle"], "stage": "SUBMISSION_CAPTURED"}
    )
    clone, _ = connected.restore_operation(
        value["store"],
        operation,
        value["store"].root / "accepted-clone",
        pins=value["pins"],
    )
    assert codec._pack(clone.__dict__) == codec._pack(value["client"].__dict__)
    before = deepcopy(value["client"].__dict__)
    with pytest.raises(StorePause):
        run(value)
    assert value["client"].__dict__ == before


# Opposite sides of one name retain distinct CID-bound bid and ask references.
def test_opposite_side_same_symbol_uses_bid_and_ask(make):
    value = make(rows=[intent("sell", 5), intent("buy", 5, 1)], held={"AAPL": 5})
    result = run(value)
    assert [r["reference"]["price"] for r in result["venue"]["references"]] == [
        199.99,
        200.0,
    ]
    assert [r["client_order_id"] for r in result["venue"]["references"]] == [
        "SYNTHETIC-connected-sell-0",
        "SYNTHETIC-connected-buy-1",
    ]
    assert value["client"]._held == {"AAPL": 4}
    assert value["client"]._average == {"AAPL": 200}


# Submitted receipt corruption refuses the entire batch before any venue mutation.
@pytest.mark.parametrize("mode", ["side", "qty", "cid", "missing", "early"])
def test_entire_submitted_binding_and_deadline_before_mutation(make, monkeypatch, mode):
    value = make()
    supplied = {}
    original = market.Resolver.resolve

    # Stop after the real sender has committed its original accepted receipt.
    def stop(self, **kwargs):
        supplied.update(kwargs)
        raise StorePause("SYNTHETIC stop before venue")

    monkeypatch.setattr(market.Resolver, "resolve", stop)
    with pytest.raises(StorePause, match="before venue"):
        run(value)
    altered = {**supplied, "submitted": deepcopy(supplied["submitted"])}
    if mode == "missing":
        altered["submitted"] = []
    elif mode == "early":
        altered["at"] = market.read_context(value["context"])["window"][
            "assumed_submission_at"
        ]
    else:
        key, replacement = {
            "side": ("side", "sell"),
            "qty": ("qty", "6"),
            "cid": ("client_order_id", "SYNTHETIC-other"),
        }[mode]
        altered["submitted"][0][key] = replacement
    before = deepcopy(value["client"].__dict__)
    with pytest.raises(ValueError, match="binding|CID|deadline"):
        original(market.Resolver(value["client"]), **altered)
    assert value["client"].__dict__ == before


# Completed resolution can be read twice but never changes shares or fees again.
def test_resolver_retry_is_idempotent_and_changed_state_refuses(make, monkeypatch):
    value = make()
    supplied = {}
    original = market.Resolver.resolve

    # Capture original submission inputs without performing the first resolution.
    def stop(self, **kwargs):
        supplied.update(kwargs)
        raise StorePause("SYNTHETIC stop before venue")

    monkeypatch.setattr(market.Resolver, "resolve", stop)
    with pytest.raises(StorePause, match="before venue"):
        run(value)
    resolver = market.Resolver(value["client"])
    receipt = original(resolver, **supplied)
    before = deepcopy(value["client"].__dict__)
    assert original(resolver, **supplied) == receipt
    assert value["client"].__dict__ == before
    value["client"]._cash += 1
    with pytest.raises(ValueError, match="Completed batch changed"):
        original(resolver, **supplied)


# Prior unresolved markets and explicit auction legs cannot start a new cycle.
@pytest.mark.parametrize("mode", ["prior", "auction", "inherited"])
def test_unresolved_phase_and_uncovered_assets_refuse_before_reader(
    make, monkeypatch, mode
):
    # No rejected demand can invoke native reader construction or transport.
    def forbidden(*args, **kwargs):
        raise AssertionError("Reader or transport reached after rejected demand")

    monkeypatch.setattr(connected.forward, "build_reader", forbidden)
    if mode == "prior":
        with pytest.raises(ValueError, match="Unresolved prior"):
            make(prior_market=True)
    elif mode == "auction":
        row = {**intent(), "execution_phase": "open"}
        with pytest.raises(ValueError, match="unsent"):
            make(rows=[row])
    else:
        with pytest.raises(
            ValueError, match="registry|mapping|Missing|Unresolved|coverage"
        ):
            make(held={"UNMAPPED": 2}, registry_missing=("UNMAPPED",))


# Changed prior economics cannot borrow the old immutable checkpoint's packet.
def test_changed_prior_before_decision_refuses(make):
    value = make()
    value["client"]._cash += 1
    before = deepcopy(value["client"].__dict__)
    with pytest.raises(ValueError, match="Full broker"):
        run(value)
    assert value["client"].__dict__ == before
    assert not value["client"]._attempts
