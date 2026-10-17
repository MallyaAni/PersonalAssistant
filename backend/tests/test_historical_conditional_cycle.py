"""Private synthetic cycles and separately admitted genuine pilot evidence."""

import base64
import os
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import forward_execution, live_probability_timing
from backend.market import forward_probability_timing as forward
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_conditional_cycle as connected
from backend.market import historical_packet_demand as demand
from backend.market import historical_packet_parser as parser
from backend.market import historical_packet_registry as registry
from backend.market import historical_post_resolution_marks as marks
from backend.market import historical_timing_packet as packet
from backend.market import probabilistic_execution as probability
from backend.market import replay_broker as native
from backend.market.alpaca_trading import AlpacaTradingError
from backend.market.historical_packet_store import Store, StorePause

CASES = []
WINDOW = connected.WINDOW
VERIFIED = "2026-10-17T16:00:00Z"


# Growing an old path after stat must never return or allocate an over-cap body.
def test_bounded_file_stat_growth_cannot_return_oversized_body(tmp_path, monkeypatch):
    path = tmp_path / "growing.json"
    path.write_bytes(b"12345678")
    monkeypatch.setattr(connected, "META_CAP", 32)
    original = Path.stat
    grew = False

    # Reproduce actual small-file growth in the original stat/read-by-path gap.
    def growing(value, *args, **kwargs):
        nonlocal grew
        info = original(value, *args, **kwargs)
        if value == path and kwargs.get("follow_symlinks", True) and not grew:
            grew = True
            path.write_bytes(b"x" * 33)
        return info

    monkeypatch.setattr(Path, "stat", growing)
    try:
        raw = connected._file(path)
    except StorePause:
        return
    assert len(raw) <= 32


# Reject growth or path replacement after opening the stable descriptor.
@pytest.mark.parametrize("mode", ["growth", "replacement"])
def test_bounded_file_stable_fd_identity(tmp_path, monkeypatch, mode):
    path = tmp_path / "component.json"
    path.write_bytes(b"12345678")
    monkeypatch.setattr(connected, "META_CAP", 32)
    original = os.fstat
    changed = False

    # Change only after the original descriptor metadata has been captured.
    def changing(descriptor):
        nonlocal changed
        info = original(descriptor)
        if not changed:
            changed = True
            if mode == "replacement":
                path.unlink()
            path.write_bytes(b"x" * (33 if mode == "growth" else 8))
        return info

    monkeypatch.setattr(os, "fstat", changing)
    with pytest.raises(StorePause, match="changed|cap"):
        connected._file(path)


# Admit an exact cap, reject the next byte, and refuse symlink/nonregular leaf paths.
def test_bounded_file_exact_cap_and_leaf_shape(tmp_path, monkeypatch):
    path = tmp_path / "component.json"
    monkeypatch.setattr(connected, "META_CAP", 32)
    path.write_bytes(b"x" * 32)
    assert connected._file(path) == b"x" * 32
    path.write_bytes(b"x" * 33)
    with pytest.raises(StorePause, match="cap"):
        connected._file(path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError, match="."):
        connected._file(link)
    with pytest.raises(StorePause, match="regular"):
        connected._file(tmp_path)


# Use the committed N2 declaration without requiring an unmounted absolute proof path.
def declaration():
    root = Path(connected.__file__).resolve().parents[2]
    path = (
        root
        / "docs/research"
        / "historical-numeric-merge-source-review-PROPOSED-2026-10-17.json"
    )
    source = packet._decode(path.read_bytes())["source_sha256"]
    assert (
        packet._digest(source)
        == "99e62ab9f8b02bc315ce59b81f8b461ae5c988e275cdf09cacf2d36b1025f8ab"
    )
    value = {
        "source_revision": codec.N2,
        "backend_image": codec.IMAGE,
        "broker_sha256": codec.BROKER,
        "calendar_sha256": codec.CALENDAR,
        "source_sha256": source,
        **codec.CONFIGS,
    }
    return {"identity": value, "identity_sha256": packet._digest(value)}


# Require genuine source admission, or label an unmatched normal checkout as skipped.
@pytest.fixture
def pins():
    value = declaration()
    try:
        codec._identity(value["identity"], value["identity_sha256"])
    except (ValueError, OSError):
        if os.environ.get("ANIOS_VERIFY_FROZEN_N2") == "1":
            raise
        pytest.skip(
            "Frozen N2 sources differ; retained native56 proof is not rerun here"
        )
    return value


# A changed profile rejects even outside the frozen native environment.
def test_nonmatching_source_profile_rejected():
    value = declaration()
    value["identity"]["source_revision"] = "0" * 40
    value["identity_sha256"] = packet._digest(value["identity"])
    with pytest.raises(ValueError, match="Frozen N2"):
        codec._identity(value["identity"], value["identity_sha256"])


# Make only explicitly synthetic pending intents, preserving original whole quantities.
def intent(side="buy", qty=5, index=0):
    return {
        "symbol": "AAPL",
        "side": side,
        "qty": qty,
        "session": "2019-02-28",
        "execute_on": "2019-03-01",
        "client_order_id": f"SYNTHETIC-connected-{side}-{index}",
        "execution_timing": intraday_orders.INTRADAY_TIMING,
        "timing_policy": live_probability_timing.POLICY,
        "execution": {"decision_at": "2019-02-28T16:01:00-05:00"},
    }


# Declare synthetic AAPL naming without claiming issuer identity proof.
def mapping():
    evidence = b"SYNTHETIC AAPL request-name fixture"
    review = b"SYNTHETIC conditional AAPL mapping, not issuer proof"
    raw = demand.encoded(
        {
            "schema": "historical-entity-registry/1",
            "entries": [
                {
                    "cohort_key": "AAPL",
                    "query_symbol": "AAPL",
                    "entity_asof": "2019-03-01",
                    "status": "REVIEWED_CONDITIONAL_MAPPING",
                    "issuer_identity": None,
                    "assumption": "Synthetic fixture mapping only",
                    "review_sha256": connected.sha(review),
                    "sources": [
                        {
                            "kind": "request_metadata",
                            "sha256": connected.sha(evidence),
                            "source_label": "synthetic",
                        }
                    ],
                }
            ],
        }
    )
    return registry.registry(
        raw,
        connected.sha(raw),
        {connected.sha(evidence): evidence, connected.sha(review): review},
    )


# Build complete synthetic quote/trade responses only after demand is frozen.
def capture(manifest, reg, *, gap=101, missing=False, conflict=False):
    groups = {}
    for query in demand.read(manifest, reg)["queries"]:
        rows = [
            {"t": "2019-03-01T14:45:30.9Z", "bp": 99.99, "ap": 100.01, "bs": 1, "as": 1}
        ]
        if not missing:
            rows.append(
                {
                    "t": "2019-03-01T14:45:31.332Z",
                    "bp": gap - 0.01,
                    "ap": gap,
                    "bs": 1,
                    "as": 1,
                }
            )
        if conflict:
            rows.append(
                {
                    "t": "2019-03-01T14:45:32.9Z",
                    "bp": 100,
                    "ap": 100.01,
                    "bs": 1,
                    "as": 1,
                    "ax": "J",
                }
            )
            rows.append({**rows[-1], "ax": "K"})
        if query["kind"] == "trades":
            rows = [
                {
                    "t": "2019-03-01T14:45:00.007Z",
                    "p": 100.0,
                    "s": 100,
                    "c": ["@"],
                    "z": "C",
                }
            ]
        body = demand.encoded({query["kind"]: {"AAPL": rows}, "next_page_token": None})
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
    return parser.packets(raw, connected.sha(raw), manifest, reg, VERIFIED)


# Import retained synthetic bytes through the real Store without HTTP.
def import_capture(store, manifest, reg, captured):
    data = packet._decode(captured.raw)
    for query in demand.read(manifest, reg)["queries"]:
        for index, page in enumerate(data["groups"][query["sha256"]]):
            attempt = packet._digest(
                {"retained_synthetic_import": query["sha256"], "page": index}
            )
            store.begin_attempt(
                attempt=attempt,
                demand_sha256=manifest.sha256,
                query_sha256=query["sha256"],
                page=index,
                token=None,
            )
            raw = base64.b64decode(page["body_base64"], validate=True)
            reservation = packet._digest({"attempt": attempt, "read": 0})
            store.reserve_read(attempt, reservation, len(raw))
            store.confirm_read(reservation, raw)
            result = store.finish_attempt(
                attempt,
                status=200,
                complete=True,
                failure=None,
                requested_at=page["requested_at"],
                received_at=page["received_at"],
            )
            assert result["body_sha256"] == page["sha256"]


# Refuse inference, authentic-live observation persistence and provider access.
@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    # Accidental live/model boundaries must fail before any fallback can conceal them.
    def forbidden(*args, **kwargs):
        raise AssertionError("No provider/model/authentic-live observation call")

    monkeypatch.setattr("backend.market.execution_quotes.fetch", forbidden)
    monkeypatch.setattr("backend.market.learned_live_timing.observe", forbidden)
    monkeypatch.setattr("backend.market.learned_order_observation.retain", forbidden)
    monkeypatch.setattr(forward, "build_forecast_reader", forbidden)
    monkeypatch.setattr(forward_execution, "current_distributions", forbidden)
    monkeypatch.setattr(forward_execution, "load_publication", forbidden)
    monkeypatch.setattr(forward_execution, "predict_moments", forbidden)


# Keep every synthetic broker, paper write, durable receipt and restored clone private.
@pytest.fixture
def make(tmp_path, pins):
    stores = []

    # Freeze one account before supplying response prices or numeric verdict inputs.
    def new(
        rows=None,
        *,
        cash=10000,
        held=0,
        mode="buy",
        gap=101,
        missing=False,
        conflict=False,
        reserve=False,
    ):
        store = Store(
            tmp_path / f"store-{len(stores)}",
            pins["identity_sha256"],
            None,
            create=True,
        )
        stores.append(store)
        root = store.root / "working"
        client = native.ReplayBroker(
            cash,
            10,
            initial_holdings={"AAPL": held} if held else {},
            initial_average_prices={"AAPL": 100} if held else {},
        )
        client.observe(WINDOW["assumed_decision_at"], {"AAPL": 100, "GOOG": 100}, True)
        if reserve:
            client.submit_market_on_close(
                "GOOG", 1, "buy", "SYNTHETIC-nondue-reservation"
            )
        rows = rows or [intent()]
        paper.save_state(root, paper.PaperState(pending=deepcopy(rows)))
        latch = {
            "session": "2019-03-01",
            "stocks": {},
            "origin": "SYNTHETIC retained latch",
        }
        path = entry_latch(root)
        path.parent.mkdir(parents=True)
        path.write_bytes(demand.encoded(latch))
        cycle = connected.Cycle(store, client, root, pins=pins)
        reg = mapping()
        manifest = cycle.begin(reg)
        captured = capture(manifest, reg, gap=gap, missing=missing, conflict=conflict)
        import_capture(store, manifest, reg, captured)
        cycle.admit(manifest, reg, captured)
        means = {"buy": -0.02, "sell": 0.02, "wait": 0.02, "both": 0.0}
        distribution = (
            None
            if mode == "unavailable"
            else probability.Distribution(
                means[mode],
                0.001,
                np.array([0.0, 0.0] if mode == "both" else [-1.0, 1.0]),
                np.array([0.5, 0.5]),
            )
        )
        return {
            "cycle": cycle,
            "store": store,
            "client": client,
            "root": root,
            "manifest": manifest,
            "registry": reg,
            "captured": captured,
            "distributions": {"AAPL": distribution},
            "original": deepcopy(rows),
            "pins": pins,
        }

    yield new
    for store in stores:
        store.close()


# Name the native latch file without loading a mutable fallback interpretation.
def entry_latch(root):
    from backend.market import entry_timing

    return entry_timing.latch_path(root, connected.DAY)


# Retain supplied quantities beside the actual connected native outcomes.
def run(value):
    result = value["cycle"].run(
        value["manifest"], value["registry"], value["captured"], value["distributions"]
    )
    CASES.append(
        {
            "origin": "SYNTHETIC_CONNECTED_CYCLE",
            "original_pending": value["original"],
            "native_orders": deepcopy(value["client"]._orders),
            "native_ledger": value["client"].ledger(),
            "result": result,
            "store_head": value["store"].snapshot()["head"],
            "actual_provider_gets": 0,
            "store_charged_import_usage": value["store"].snapshot()["used"],
        }
    )
    return result


# Restore final and operation states with matching broker/paper/latch references.
def check_restores(value, result):
    store, pins = value["store"], value["pins"]
    clone, receipt = connected.restore_receipt(
        store, result["receipt_sha256"], store.root / "restored-outcome", pins=pins
    )
    assert codec._pack(clone.__dict__) == codec._pack(value["client"].__dict__)
    assert (
        paper.state_path(store.root / "restored-outcome").read_bytes()
        == paper.state_path(value["root"]).read_bytes()
    )
    assert (
        entry_latch(store.root / "restored-outcome").read_bytes()
        == entry_latch(value["root"]).read_bytes()
    )
    assert set(receipt["components"]) == {"broker", "paper", "latch"}
    for kind in ("decision", "submission"):
        restored, saved = connected.restore_operation(
            store,
            result[kind + "_operation"],
            store.root / ("restored-" + kind),
            pins=pins,
        )
        expected = (
            WINDOW["assumed_decision_at"]
            if kind == "decision" or result["factory_calls"] == 0
            else WINDOW["assumed_submission_at"]
        )
        assert packet.nanos(restored._now.isoformat()) == packet.nanos(expected)
        if kind == "decision":
            assert restored.attempt_history == ()
        assert set(saved["components"]) == {"broker", "paper", "latch"}


# Freeze caller-owned forecasts before account capture can replace an input.
def test_forecast_replacement_after_receipt_cannot_change_verdict(make, monkeypatch):
    value = make()
    external = value["distributions"]
    original = forward.capture_account

    # Replace only the external distribution after its receipt has been retained.
    def replacing(*args, **kwargs):
        observed = original(*args, **kwargs)
        external["AAPL"] = probability.Distribution(
            0.02, 0.001, np.array([-1.0, 1.0]), np.array([0.5, 0.5])
        )
        return observed

    monkeypatch.setattr(forward, "capture_account", replacing)
    result = run(value)
    store = value["store"]
    entry = store.recover_operation(result["decision_operation"])
    receipt = packet._decode(
        store.read_blob(entry["receipt_sha256"], limit=connected.META_CAP)
    )
    frozen = packet._decode(
        store.read_blob(receipt["detail"]["forecast"], limit=2 * 1024**2)
    )
    verdict = result["verdicts"][0]["verdict"]["timed"]["forward_receipt"]
    assert frozen["forecast_identity"]["AAPL"]["mean"] == -0.02
    identity = verdict["forecast_identity"]["AAPL"]
    assert identity["mean"] == frozen["forecast_identity"]["AAPL"]["mean"]
    assert identity["scale"] == frozen["forecast_identity"]["AAPL"]["scale"]
    for name in ("residuals", "weights"):
        raw = np.asarray(frozen["arrays"]["AAPL"][name], dtype=np.float64).tobytes()
        assert identity[name] == connected.sha(raw)
    assert external["AAPL"].mean == 0.02
    assert value["client"]._cash == pytest.approx(9494.495, abs=1e-10, rel=0)
    assert value["client"]._held == {"AAPL": 5}


# Check connected BUY, post-arrival touch, fees, midpoint NAV and restoration.
def test_connected_buy_and_complete_restoration(make):
    value = make()
    result = run(value)
    client = value["client"]
    assert client._cash == pytest.approx(float(Decimal("9494.495")), abs=1e-10, rel=0)
    assert client._held == {"AAPL": 5}
    assert client._average == {"AAPL": 101.0}
    assert result["nav"] == pytest.approx(float(Decimal("9999.47")), abs=1e-10, rel=0)
    order = next(iter(client._orders.values()))
    assert packet.nanos(order["submitted_at"]) == packet.nanos(
        WINDOW["assumed_submission_at"]
    )
    assert order["filled_at"] == "2019-03-01T14:45:31.333000+00:00"
    assert result["marks"]["candidate_marks"]["AAPL"] != float(
        order["filled_avg_price"]
    )
    assert value["store"].snapshot()["next_stage"] == "PRIOR_VERIFIED"
    check_restores(value, result)


# Preserve desiredSELL8 separately from submittedSELL5 and native fill5.
def test_connected_covered_sell_quantity_domains(make):
    value = make([intent("sell", 8)], cash=1000, held=5, mode="sell")
    result = run(value)
    assert value["original"][0]["qty"] == 8
    row = next(iter(value["client"]._orders.values()))
    assert row["qty"] == "5"
    assert row["filled_qty"] == "5"
    assert value["client"]._held == {}
    assert value["client"]._cash == pytest.approx(
        float(Decimal("1504.44505")), abs=1e-10, rel=0
    )
    assert result["marks"]["candidate_marks"] == {}
    check_restores(value, result)


# WAIT and unavailable forecasts commit empty submission without a client.
@pytest.mark.parametrize("mode", ["wait", "unavailable"])
def test_wait_unavailable_empty_submission_no_factory(make, mode):
    value = make(mode=mode)
    result = run(value)
    assert result["factory_calls"] == 0
    assert value["client"]._attempts == []
    assert value["client"]._fills == []
    assert value["client"]._cash == 10000
    assert result["venue"]["status"] == "NO_NATIVE_SUBMISSION"
    check_restores(value, result)


# Preserve nondue cash and exclude sale proceeds from the frozen gap-fill budget.
def test_gap_partial_and_no_same_batch_sale_funding(make):
    value = make(
        [intent("buy", 5), intent("sell", 5, 1)],
        cash=1000,
        held=5,
        mode="both",
        gap=200,
        reserve=True,
    )
    result = run(value)
    assert result["venue"]["initial_budget"] == pytest.approx(899.9)
    assert result["venue"]["nondue_reserved_cash"] == pytest.approx(100.1)
    assert [r["filled_qty"] for r in result["venue"]["outcomes"]] == [4, 5]
    assert value["client"]._cash == pytest.approx(
        float(Decimal("1198.15005")), abs=1e-10, rel=0
    )
    assert value["client"]._held == {"AAPL": 4}
    assert value["client"]._average["AAPL"] == pytest.approx(
        float(Decimal(1300) / Decimal(9))
    )
    assert (
        value["client"]._orders["SYNTHETIC-nondue-reservation"]["status"] == "accepted"
    )


# Sell proceeds received first cannot enlarge the later BUY's original frozen budget.
def test_sell_first_cannot_fund_later_buy(make):
    value = make(
        [intent("sell", 5), intent("buy", 5, 1)],
        cash=1000,
        held=5,
        mode="both",
        gap=200,
        reserve=True,
    )
    result = run(value)
    assert result["venue"]["initial_budget"] == pytest.approx(899.9)
    assert result["venue"]["nondue_reserved_cash"] == pytest.approx(100.1)
    assert [row["side"] for row in result["venue"]["outcomes"]] == ["sell", "buy"]
    assert [row["filled_qty"] for row in result["venue"]["outcomes"]] == [5, 4]
    assert value["client"]._cash == pytest.approx(
        float(Decimal("1198.15005")), abs=1e-10, rel=0
    )
    assert value["client"]._held == {"AAPL": 4}
    assert value["client"]._average == {"AAPL": 200.0}
    assert (
        value["client"]._orders["SYNTHETIC-nondue-reservation"]["status"] == "accepted"
    )


# Missing references expire once; conflicting latest marks never fall back.
@pytest.mark.parametrize("mode", ["missing", "conflict"])
def test_missing_and_conflicting_mark_boundaries(make, mode):
    value = make(held=1, missing=mode == "missing", conflict=mode == "conflict")
    result = run(value)
    assert result["nav"] is None
    assert result["marks"]["candidate_marks"] is None
    assert value["client"]._observed_at != value["client"]._now
    with pytest.raises(AlpacaTradingError, match="Fresh observed"):
        value["client"].account()
    if mode == "missing":
        assert value["client"]._fills[0]["filled_qty"] == 0
        assert (
            value["client"]._orders[value["original"][0]["client_order_id"]]["status"]
            == "expired"
        )


# A crash after complete decision commitment cannot evaluate that decision again.
def test_committed_decision_crash_pauses_without_re_evaluation(make, monkeypatch):
    value = make()
    store = value["store"]

    # Raise only after durable complete decision commitment, before factory/submission.
    def fault(point):
        if (
            point == "after_commit"
            and store.snapshot()["next_stage"] == "SUBMISSION_CAPTURED"
        ):
            raise RuntimeError("SYNTHETIC crash after committed decision")

    store.fault = fault
    with pytest.raises(RuntimeError, match="committed decision"):
        run(value)
    store.fault = None
    assert value["client"]._attempts == []

    # Any repeat of native reader construction would be a failure.
    def forbidden(*args, **kwargs):
        raise AssertionError("Repeated native decision")

    monkeypatch.setattr(forward, "build_reader", forbidden)
    with pytest.raises(StorePause, match="no decision replay"):
        run(value)


# A reserved OPEN decision pauses before native reader construction after interruption.
def test_open_decision_reservation_never_repeats_reader_construction(make, monkeypatch):
    value = make()
    store = value["store"]

    # Stop after operation reservation commits and before any reader is constructed.
    def fault(point):
        if (
            point == "after_commit"
            and store.snapshot()["next_stage"] == "DECISION_FROZEN"
        ):
            raise RuntimeError("SYNTHETIC crash after OPEN decision reservation")

    store.fault = fault
    with pytest.raises(RuntimeError, match="OPEN decision"):
        run(value)
    store.fault = None

    # Existing operation admission must reject before recomputing any native reader.
    def forbidden(*args, **kwargs):
        raise AssertionError("Repeated reader construction after OPEN decision")

    monkeypatch.setattr(forward, "build_reader", forbidden)
    with pytest.raises(StorePause, match="operation exists"):
        run(value)
    assert value["client"]._attempts == []


# An OPEN submission after synthetic acceptance stays uncertain without replay.
def test_open_submission_with_accepted_native_order_never_replays(make, monkeypatch):
    value = make()
    original = intraday_orders.send_due

    # Stop after native acceptance and before complete submission commitment.
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("SYNTHETIC crash after native acceptance")

    monkeypatch.setattr(intraday_orders, "send_due", interrupted)
    with pytest.raises(RuntimeError, match="native acceptance"):
        run(value)
    assert len(value["client"]._attempts) == 1
    assert len(value["client"]._orders) == 1
    operation = packet._digest(
        {"cycle": value["store"].snapshot()["cycle"], "stage": "SUBMISSION_CAPTURED"}
    )
    with pytest.raises(StorePause, match="paused"):
        connected.restore_operation(
            value["store"],
            operation,
            value["store"].root / "invalid-resume",
            pins=value["pins"],
        )
    with pytest.raises(StorePause, match="no decision replay"):
        run(value)
    assert len(value["client"]._attempts) == 1


# Check full prior state and admitted packet identity before invoking the reader.
@pytest.mark.parametrize("mode", ["cash", "paper", "latch", "packet"])
def test_changed_prior_or_packet_fails_before_decision(make, mode):
    value = make()
    if mode == "cash":
        value["client"]._cash += 1
    elif mode == "paper":
        state = paper.load_state(value["root"])
        state.order_seq += 1
        paper.save_state(value["root"], state)
    elif mode == "latch":
        entry_latch(value["root"]).write_bytes(
            demand.encoded({"session": "2019-03-01", "changed": True})
        )
    else:
        value["captured"] = capture(value["manifest"], value["registry"], gap=102)
    with pytest.raises(ValueError, match="changed|admitted"):
        run(value)
    assert value["client"]._attempts == []


# Reuse retained real inputs while preserving the synthetic BUY1 WAIT.
def test_retained_genuine_pilot_wait_is_separate_from_generic_acceptance(
    tmp_path, pins
):
    if not Path("/retained/observations.json").exists():
        pytest.skip(
            "Requires bounded retained AAPL/calibration mount; not a new native proof"
        )
    repository = Path(connected.__file__).resolve().parents[2]
    raw_proof = (
        repository
        / "docs/research/historical-timing-genuine-feature-proof-2026-10-17.json"
    ).read_bytes()
    assert (
        connected.sha(raw_proof)
        == "6176e4e4b6a4f98fad7d0ad59f68bd88989d249cf61bd24a1437f612cc442378"
    )
    previous = packet._decode(raw_proof)
    raw_quote = Path("/retained/observations.json").read_bytes()
    raw_trade = Path("/retained/aapl-observations.json").read_bytes()
    verified = packet._decode(Path("/retained/verification.json").read_bytes())[
        "independently_verified_at"
    ]
    quotes = packet.source_packet(
        WINDOW,
        raw_quote,
        previous["input_sha256"]["quote_packet"],
        verified,
        kind="quotes",
    )
    trades = packet.source_packet(
        WINDOW,
        raw_trade,
        previous["input_sha256"]["trade_packet"],
        verified,
        kind="trades",
    )
    # Reuse authenticated calibration arrays without recomputing heads or features.
    residual = Path("/retained/residual")
    assert (residual / "residuals.npz").stat().st_size <= 16 * 1024**2
    receipt = previous["native_forward_verdict"]["timed"]["forward_receipt"]
    restored = forward.load_residual_month(
        residual,
        receipt_sha256=receipt["source_identity"]["residual_receipt"],
        observed_at=previous["actual_computed_at"],
    )
    sample = restored.samples["AAPL"]
    distribution = probability.Distribution(
        previous["distribution_mean"],
        previous["distribution_scale"],
        sample.residuals,
        sample.weights,
    )
    original_identity = receipt["forecast_identity"]["AAPL"]
    assert (
        connected.sha(distribution.residuals.tobytes())
        == original_identity["residuals"]
    )
    assert connected.sha(distribution.weights.tobytes()) == original_identity["weights"]
    store = Store(
        tmp_path / "retained-pilot", pins["identity_sha256"], None, create=True
    )
    try:
        admission, input_ref = connected.retain_pilot_inputs(
            store, quote_packet=quotes, trade_packet=trades, original_open=174.01
        )
        assert admission["status"] == "PILOT_RETAINED_INPUT"
        assert admission["generic_packets_finalized"] is False
        assert admission["generic_market_acceptance"] is False
        root = store.root / "working"
        client = native.ReplayBroker(100000, 10)
        client.observe(
            WINDOW["assumed_decision_at"],
            {"AAPL": admission["decision_quote"]["price"]},
            True,
        )
        row = {
            "client_order_id": "private-genuine-feature-no-order",
            "symbol": "AAPL",
            "side": "buy",
            "qty": 1,
            "execute_on": "2019-03-01",
            "execution_timing": intraday_orders.INTRADAY_TIMING,
        }
        paper.save_state(root, paper.PaperState(pending=[row]))
        decision = native._instant(WINDOW["assumed_decision_at"])
        observed = forward.capture_account(
            client,
            native._instant(WINDOW["completed_at"]).astimezone(
                connected.calendar.NEW_YORK
            ),
            clock=lambda: decision,
        )
        trace = []
        distributions = {
            name: distribution if name == "AAPL" else None
            for name in previous["symbols"]
        }
        reader = forward.build_reader(
            distributions,
            previous["symbols"],
            0,
            connected.DAY,
            decision,
            {"quotes": {"AAPL": previous["decision_packet"]}},
            [row],
            observed,
            10,
            trace,
            forecast_available_at=native._instant(
                WINDOW["assumed_forecast_available_at"]
            ),
            source_identity=receipt["source_identity"],
        )

        # A genuine WAIT must never invoke even a private broker transport factory.
        def forbidden_factory():
            raise AssertionError("Genuine retained WAIT became an order")

        logs = intraday_orders.send_due(
            root,
            {"quotes": {"AAPL": previous["decision_packet"]}},
            decision,
            forbidden_factory,
            timing_reader=reader,
        )
        assert logs == []
        assert trace[0]["state"] == previous["conditional_trace"][0]["state"]
        assert (
            trace[0]["trade_fraction"]
            == previous["conditional_trace"][0]["trade_fraction"]
        )
        assert trace[0]["expected_log_utility"] == pytest.approx(
            previous["conditional_trace"][0]["expected_log_utility"], abs=1e-15, rel=0
        )
        assert client.attempt_history == ()
        assert client.fill_history == ()
        clocks = marks._clocks(client, client.ledger(), WINDOW)
        hypothetical_held_mark = marks._mark(
            packet._rows(WINDOW, quotes, "quotes"), clocks, quotes.source_sha256
        )
        assert hypothetical_held_mark["status"] == "MISSING"
        assert "conflicting" in hypothetical_held_mark["reason"]
        reference = connected._receipt(
            store,
            client,
            root,
            pins,
            {
                "stage": "PILOT_RETAINED_INPUT",
                "input_receipt": input_ref,
                "origin": "RETAINED_GENUINE_DISTRIBUTION_SYNTHETIC_100K_ZERO_HELD_BUY1",
                "actual_original_numeric_computed_at": previous["actual_computed_at"],
                "new_head_inference_calls": 0,
                "trace": trace,
                "counterfactual_positive_holding_mark": hypothetical_held_mark,
            },
        )
        clone, _ = connected.restore_receipt(
            store, reference, store.root / "restored", pins=pins
        )
        assert codec._pack(clone.__dict__) == codec._pack(client.__dict__)
        assert store.snapshot()["next_stage"] == "PRIOR_VERIFIED"
        CASES.append(
            {
                "origin": "PILOT_RETAINED_INPUT",
                "retained_inference_proof": connected.sha(raw_proof),
                "native_head_inference_calls": 0,
                "input_receipt": input_ref,
                "state_receipt": reference,
                "conditional_trace": trace,
                "synthetic_account": {"cash": 100000, "held": {}, "intent_qty": 1},
                "counterfactual_positive_holding_mark": hypothetical_held_mark,
                "generic_packets_finalized": False,
                "generic_market_acceptance": False,
            }
        )
    finally:
        store.close()
