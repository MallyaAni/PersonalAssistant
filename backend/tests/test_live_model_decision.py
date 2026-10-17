"""Saved numeric decisions must keep one grade, quantity, source and execution basis."""

import json
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import (
    grade_led_policy,
    joint_funded_policy,
)
from backend.market import (
    live_model_decision as view,
)
from backend.market.live_probability_timing import POLICY as TIMING_POLICY

SESSION = "2026-10-13"
NOW = datetime.fromisoformat("2026-10-14T10:00:00-04:00")


# Supply one exact terminal journal receipt with a partial actual fill.
def journal_fill():
    return {
        "client_order_id": f"anios-{SESSION}-buy-bbb-1",
        "symbol": "BBB",
        "side": "buy",
        "session": SESSION,
        "qty": 2,
        "filled_qty": 1,
        "filled_price": 25.5,
        "terminal": True,
        "status": "cancelled",
        "execution": {
            "decision_at": "2026-10-13T23:47:45+00:00",
            "created_at": "2026-10-14T13:30:00.123456789Z",
            "submitted_at": "2026-10-14T13:30:01Z",
            "filled_at": "2026-10-14T13:31:00.123456789Z",
            "reconciled_at": "2026-10-14T13:32:00Z",
        },
    }


# Keep actual partial fill quantity separate from original quantity without mutation.
def test_recorded_fills_preserve_actual_partial_quantity_and_clocks():
    journal = [journal_fill()]
    original = deepcopy(journal)
    rows = view.recorded_fills(journal, NOW)
    assert len(rows) == 1
    assert rows[0]["qty"] == 1
    assert rows[0]["original_qty"] == 2
    assert rows[0]["price"] == 25.5
    assert rows[0]["filled_at"] == original[0]["execution"]["filled_at"]
    assert rows[0]["created_at"] == original[0]["execution"]["created_at"]
    assert rows[0]["reconciled_at"] == original[0]["execution"]["reconciled_at"]
    rows[0]["execution"]["filled_at"] = "changed"
    assert journal == original


# Withhold undated legacy fills and zero-fill terminal records from actual fills.
def test_recorded_fills_withhold_missing_original_clock_and_unfilled_orders():
    entry = journal_fill()
    del entry["execution"]["filled_at"]
    entry["filled_price"] = None
    assert view.recorded_fills([entry], NOW) == []
    entry["filled_qty"] = 0
    assert view.recorded_fills([entry], NOW) == []


# Undated orders from the old identity format cannot erase later dated fill evidence.
def test_legacy_undated_journal_does_not_hide_dated_fills():
    legacy = journal_fill()
    legacy["client_order_id"] = f"anios-{SESSION}-buy-bbb"
    legacy.pop("execution")
    rows = view.recorded_fills([legacy, journal_fill()], NOW)
    assert len(rows) == 1
    assert rows[0]["client_order_id"] == journal_fill()["client_order_id"]


# Require terminal status and exact reconciliation clocks for any displayed fill.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "unknown"),
        ("status", "filled"),
        ("reconciled_at", "2026-10-14T13:30:00Z"),
        ("reconciled_at", "2026-10-15T13:32:00Z"),
        ("reconciled_at", "2026-10-14T13:32:00"),
    ],
)
def test_recorded_fill_status_and_reconciliation_corruption(field, value):
    entry = journal_fill()
    if field == "status":
        entry[field] = value
    else:
        entry["execution"][field] = value
    assert view.recorded_fills([entry], NOW) == []


# Reject conflicting identities, quantities, prices and clocks.
@pytest.mark.parametrize(
    "corruption",
    [
        "duplicate",
        "conflict",
        "cid",
        "session",
        "side",
        "oversize",
        "negative",
        "nan",
        "price",
        "future",
        "naive",
        "before_submission",
    ],
)
def test_recorded_fills_reject_corruption(corruption):  # noqa: C901
    entry = journal_fill()
    journal = [entry]
    if corruption in ("duplicate", "conflict"):
        journal.append(deepcopy(entry))
        if corruption == "conflict":
            journal[-1]["filled_qty"] = 2
    elif corruption == "cid":
        entry["client_order_id"] = f"anios-{SESSION}-buy-other-1"
    elif corruption == "session":
        entry["session"] = "2026-10-12"
    elif corruption == "side":
        entry["side"] = "sell"
    elif corruption == "oversize":
        entry["filled_qty"] = 3
    elif corruption == "negative":
        entry["filled_qty"] = -1
    elif corruption == "nan":
        entry["filled_qty"] = float("nan")
    elif corruption == "price":
        entry["filled_price"] = 0
    elif corruption == "future":
        entry["execution"]["filled_at"] = "2026-10-15T13:31:00Z"
    elif corruption == "naive":
        entry["execution"]["filled_at"] = "2026-10-14T13:31:00"
    else:
        entry["execution"]["filled_at"] = "2026-10-14T13:30:00Z"
    if corruption in ("duplicate", "conflict"):
        with pytest.raises(ValueError, match="Duplicate journal"):
            view.recorded_fills(journal, NOW)
    else:
        assert view.recorded_fills(journal, NOW) == []


# A terminal journal suppresses the original instruction after pending rows disappear.
@pytest.mark.parametrize("legacy_clock", [False, True])
def test_terminal_journal_suppresses_original_order_without_pending(
    monkeypatch, legacy_clock
):
    record, plan, _, _ = admitted(monkeypatch)
    plan["orders"] = [row for row in plan["orders"] if row["symbol"] != "BBB"]
    entry = journal_fill()
    if legacy_clock:
        del entry["execution"]["filled_at"]
    result = view.read("unused", record, plan, NOW, journal=[entry])
    assert result["status"] == "available"
    row = result["rows"]["BBB"]
    assert row["status"] == "complete"
    assert row["action"] is row["qty"] is row["when"] is row["execute_on"] is None
    assert row["executions"] == []


# The journal cannot resize an original instruction or stand in for a working order.
def test_terminal_journal_quantity_conflict_and_nonterminal_fail_closed(monkeypatch):
    record, plan, _, _ = admitted(monkeypatch)
    entry = journal_fill()
    entry["qty"] = 3
    result = view.read("unused", record, plan, NOW, journal=[entry])
    assert result["status"] == "unavailable"
    entry = journal_fill()
    entry["terminal"] = False
    plan["orders"] = [row for row in plan["orders"] if row["symbol"] != "BBB"]
    result = view.read("unused", record, plan, NOW, journal=[entry])
    assert result["rows"]["BBB"]["status"] == "unavailable"
    assert result["rows"]["BBB"]["qty"] is None


# Supply an available original receipt with a retained HOLD, buy, trim, exit and BUY0.
def fixture():
    names = ("AAA", "BBB", "CCC", "DDD", "EEE", "SPY")
    grades = np.array([[2, 3, 2, 2, 2, -1], [2, 3, 2, 2, 1, -1]])
    report = SimpleNamespace(
        panel=SimpleNamespace(
            tickers=names,
            benchmark="SPY",
            dates=np.array(["2026-10-12", SESSION], dtype="datetime64[D]"),
        ),
        graded=SimpleNamespace(grades=grades),
    )
    held = {"AAA": 10, "CCC": 10, "EEE": 5}
    current = dict.fromkeys(held, 0.1)
    model = {"AAA": 0.0, "BBB": 0.25, "CCC": 0.08, "DDD": 0.0, "EEE": 0.0}
    signals = grade_led_policy.signals(report, held)
    targets, receipt = grade_led_policy.preserve_grade_holdings(
        model,
        {"current_weights": current},
        signals,
        {"AAA": 10.0, "CCC": 10.0, "EEE": 20.0},
        1000.0,
    )
    policy = grade_led_policy.POLICY
    timing = {}
    orders, planned, executions, actions = [], [], [], []
    quantities = {"AAA": 0, "BBB": 2, "CCC": 2, "DDD": 0, "EEE": 5}
    for index, name in enumerate(names[:-1]):
        qty = quantities[name]
        side = "buy" if name == "BBB" else "sell"
        if qty:
            identity = f"anios-{SESSION}-{side}-{name.lower()}-{index}"
            routed = "next_open" if name == "EEE" else view.INTRADAY_TIMING
            timing[identity] = routed
            order = {
                "symbol": name,
                "side": side,
                "qty": qty,
                "reason": "Saved quantity",
                "kind": None,
            }
            if name == "EEE":
                orders.append({**order, "client_order_id": identity})
            else:
                planned.append({**order, "execute_on": "2026-10-14"})
            executions.append(
                {
                    "symbol": name,
                    "side": side,
                    "client_order_id": identity,
                    "planned_qty": qty,
                    "decided": SESSION,
                    "execute_on": "2026-10-14",
                    "timing": routed,
                    "timing_policy": TIMING_POLICY,
                    "state": "waiting",
                    "terminal": False,
                    "when": "Today · saved execution policy",
                    "status": "Waiting on original order",
                }
            )
        actions.append(
            {
                "ticker": name,
                "grade": signals[name]["grade"],
                "policy": policy,
                "decision_source": policy,
                "grade_signal": signals[name]["action"],
                "signal_session": SESSION,
                "model_target_weight": model[name],
                "order_quantity": qty,
                "action": "buy"
                if name == "BBB"
                else "trim"
                if name == "CCC"
                else "sell"
                if name == "EEE"
                else "hold",
                "signal_reason": "Original saved reason",
            }
        )
    receipt.update(
        policy=policy,
        session=SESSION,
        status="available",
        observed_equity=1000.0,
        observed_cash=700.0,
        sizing_model_targets=model,
        grades={
            name: int(grades[-1, column]) for column, name in enumerate(names[:-1])
        },
        source_sha256=sha256(
            Path(joint_funded_policy.__file__).read_bytes()
        ).hexdigest(),
        cost_bps=10,
        timing_policy=TIMING_POLICY,
        timing_source_sha256=sha256(
            Path(view.__file__).with_name("live_probability_timing.py").read_bytes()
        ).hexdigest(),
        company_exits=["EEE"],
        execution_timing={
            "orders": timing,
            "ordinary": TIMING_POLICY,
            "company_exit": "next_open",
        },
        execution={"blocked": [], "missing": ["DDD: buy rounds to zero shares"]},
        reason="joint_net_growth",
    )
    selected = {"policy": policy, "weights": dict(targets)}
    record = {
        "session": SESSION,
        "written": "2026-10-13T23:47:45+00:00",
        "grades": {name: {"grade": signals[name]["grade"]} for name in names[:-1]},
        "targets": deepcopy(selected),
        "actions": actions,
        "paper": {
            "policy": policy,
            "session": SESSION,
            "selected_targets": selected,
            "joint_funded": {
                "policy": policy,
                "as_of": SESSION,
                "targets": dict(targets),
                "receipt": receipt,
            },
            "positions": [
                {"symbol": name, "qty": qty, "market_value": 99999.0}
                for name, qty in held.items()
            ],
            "orders": orders,
            "planned": planned,
        },
    }
    return (
        record,
        {"policy": policy, "orders": executions},
        {"policy": policy, "cost_bps": 10},
        report,
    )


# Isolate installed admission while using the real saved-receipt validator.
def admitted(monkeypatch, supplied=None):
    record, plan, config, report = supplied or fixture()
    monkeypatch.setattr(view, "_authenticate", lambda *args: ("a" * 64, config, report))
    return record, plan, config, report


# Keep every visible grade and instruction on the same original admitted record.
def test_available_rows_keep_original_grades_quantities_and_zero_blockers(monkeypatch):
    record, plan, _, _ = admitted(monkeypatch)
    before = deepcopy((record, plan))
    result = view.read("unused", record, plan, NOW)
    assert result["status"] == "available"
    assert set(result["rows"]) == set(record["grades"])
    assert result["rows"]["AAA"]["action"] == "hold"
    assert result["rows"]["AAA"]["qty"] == 0
    assert result["rows"]["BBB"]["action"] == "buy"
    assert result["rows"]["BBB"]["qty"] == 2
    assert result["rows"]["CCC"]["action"] == "trim"
    assert result["rows"]["CCC"]["qty"] == 2
    assert result["rows"]["EEE"]["action"] == "sell"
    blocked = result["rows"]["DDD"]
    assert (blocked["action"], blocked["qty"], blocked["status"]) == (
        "buy",
        0,
        "blocked",
    )
    assert blocked["reason"] == "DDD: buy rounds to zero shares"
    for name, row in result["rows"].items():
        assert row["grade"] == record["grades"][name]["grade"]
        assert row["signal_session"] == SESSION
    assert (record, plan) == before
    result["rows"]["BBB"]["executions"][0]["planned_qty"] = 999
    assert (record, plan) == before


# Preserve an owned name with a missing grade without labelling it as unowned.
def test_missing_grade_preserved_holding_is_unavailable_with_original_reason(
    monkeypatch,
):
    record, plan, config, report = fixture()
    report.graded.grades[-1, 0] = -1
    receipt = record["paper"]["joint_funded"]["receipt"]
    held = {row["symbol"]: row["qty"] for row in record["paper"]["positions"]}
    signals = grade_led_policy.signals(report, held)
    model = dict(receipt["sizing_model_targets"])
    model["AAA"] = receipt["current_weights"]["AAA"]
    targets, receipt = grade_led_policy.preserve_grade_holdings(
        model,
        receipt,
        signals,
        {
            name: receipt["current_weights"][name] * receipt["observed_equity"] / qty
            for name, qty in held.items()
        },
        receipt["observed_equity"],
    )
    receipt["sizing_model_targets"] = model
    receipt["grades"]["AAA"] = -1
    record["grades"]["AAA"]["grade"] = None
    for selected in (record["targets"], record["paper"]["selected_targets"]):
        selected["weights"] = dict(targets)
    record["paper"]["joint_funded"]["targets"] = dict(targets)
    action = next(row for row in record["actions"] if row["ticker"] == "AAA")
    action.update(
        grade=None,
        grade_signal="unavailable",
        model_target_weight=model["AAA"],
        signal_reason=signals["AAA"]["reason"],
    )
    admitted(monkeypatch, (record, plan, config, report))
    original = deepcopy((record, plan))
    result = view.read("unused", record, plan, NOW)
    assert result["status"] == "available"
    row = result["rows"]["AAA"]
    assert row["status"] == "unavailable"
    assert row["grade"] is None
    assert row["reason"] == signals["AAA"]["reason"]
    assert row["current_qty"] == 10
    assert row["target_weight"] == receipt["current_weights"]["AAA"]
    assert row["action"] is row["qty"] is row["when"] is None
    assert (record, plan) == original


# Keep a reduced submission and partial fill distinct from the original model size.
def test_reduced_submission_and_partial_fill_preserve_original_numeric_plan(
    monkeypatch,
):
    record, plan, _, _ = admitted(monkeypatch)
    record["paper"]["planned"][0]["qty"] = 5
    next(row for row in record["actions"] if row["ticker"] == "BBB")[
        "order_quantity"
    ] = 5
    execution = plan["orders"][0]
    execution.update(
        planned_qty=5,
        submitted_qty=3,
        filled_qty=2,
        remaining_qty=1,
        qty=3,
        quantity_basis="submitted",
        state="partial",
    )
    before = deepcopy((record, plan))
    result = view.read("unused", record, plan, NOW)
    assert result["status"] == "available"
    row = result["rows"]["BBB"]
    assert (row["action"], row["qty"]) == ("buy", 5)
    actual = row["executions"][0]
    assert (actual["submitted_qty"], actual["filled_qty"], actual["remaining_qty"]) == (
        3,
        2,
        1,
    )
    assert (record, plan) == before


# Reject oversized or inconsistent execution quantities for the same saved CID.
@pytest.mark.parametrize(
    "quantities",
    [
        {"submitted_qty": 3},
        {"submitted_qty": -1},
        {"submitted_qty": True},
        {"submitted_qty": float("nan")},
        {"submitted_qty": "2"},
        {"filled_qty": 3},
        {"filled_qty": -1},
        {"filled_qty": True},
        {"submitted_qty": 1, "filled_qty": 1.5},
        {"remaining_qty": 3},
        {"remaining_qty": -1},
        {"remaining_qty": False},
        {"submitted_qty": 1, "remaining_qty": 1.5},
        {"submitted_qty": 2, "filled_qty": 1, "remaining_qty": 2},
        {"qty": 3, "quantity_basis": "submitted", "submitted_qty": 2},
        {"qty": 1, "quantity_basis": "submitted", "submitted_qty": 2},
    ],
)
def test_execution_quantities_cannot_exceed_original_or_known_submitted_basis(
    monkeypatch, quantities
):
    record, plan, _, _ = admitted(monkeypatch)
    plan["orders"][0].update(quantities)
    before = deepcopy((record, plan))
    result = view.read("unused", record, plan, NOW)
    assert result["status"] == "unavailable"
    for row in result["rows"].values():
        assert row["action"] is row["qty"] is row["when"] is None
    assert (record, plan) == before


# Concluded partials must not revive an original planned order as a fresh instruction.
@pytest.mark.parametrize(
    ("state", "terminal"),
    [
        ("partial", True),
        ("filled", False),
        ("canceled", True),
        ("expired", True),
        ("dead", True),
    ],
)
def test_terminal_orders_suppress_action_quantity_and_time(
    monkeypatch, state, terminal
):
    record, plan, _, _ = admitted(monkeypatch)
    plan["orders"][0].update(state=state, terminal=terminal, filled_qty=1)
    row = view.read("unused", record, plan, NOW)["rows"]["BBB"]
    assert row["status"] == "complete"
    assert row["action"] is row["qty"] is row["when"] is row["execute_on"] is None
    assert row["grade"] == "A+"


# Withhold quantities when the execution state is missing or unknown.
def test_missing_or_unknown_execution_withholds_only_the_instruction(monkeypatch):
    record, plan, _, _ = admitted(monkeypatch)
    plan["orders"][0]["state"] = "problem"
    result = view.read("unused", record, plan, NOW)
    assert result["rows"]["BBB"]["action"] is None
    assert result["rows"]["BBB"]["qty"] is None
    assert result["rows"]["BBB"]["status"] == "unavailable"
    plan["orders"].pop(0)
    assert view.read("unused", record, plan, NOW)["rows"]["BBB"]["qty"] is None


# A stripped planned CID must resolve uniquely from the original policy receipt.
def test_planned_legs_without_ids_bind_to_canonical_original_timing(monkeypatch):
    record, plan, _, _ = admitted(monkeypatch)
    assert "client_order_id" not in record["paper"]["planned"][0]
    result = view.read("unused", record, plan, NOW)
    assert result["status"] == "available"
    assert (
        result["rows"]["BBB"]["executions"][0]["client_order_id"]
        == "anios-2026-10-13-buy-bbb-1"
    )


# Reject duplicate identities or repeated stock legs instead of summing sizes.
@pytest.mark.parametrize("kind", ["basket", "execution", "ambiguous", "malformed"])
def test_duplicate_and_ambiguous_baskets_fail_closed(monkeypatch, kind):
    record, plan, _, _ = admitted(monkeypatch)
    if kind == "basket":
        record["paper"]["planned"].append(deepcopy(record["paper"]["planned"][0]))
    elif kind == "execution":
        plan["orders"].append(deepcopy(plan["orders"][0]))
    else:
        timing = record["paper"]["joint_funded"]["receipt"]["execution_timing"][
            "orders"
        ]
        timing[
            "anios-2026-10-13-buy-bbb-99"
            if kind == "ambiguous"
            else "anios-2026-10-13-buy-bbb-no-id"
        ] = view.INTRADAY_TIMING
    result = view.read("unused", record, plan, NOW)
    assert result["status"] == "unavailable"
    assert all(
        row["grade"] is row["action"] is row["qty"] is row["when"] is None
        for row in result["rows"].values()
    )


# Reject altered routing, timing policies, source hashes, quantities and visible grades.
@pytest.mark.parametrize(
    ("part", "path", "value"),
    [
        (0, ("grades", "AAA", "grade"), "C"),
        (0, ("actions", 1, "order_quantity"), 3),
        (0, ("paper", "joint_funded", "receipt", "source_sha256"), "x" * 64),
        (0, ("paper", "joint_funded", "receipt", "timing_source_sha256"), "x" * 64),
        (0, ("paper", "joint_funded", "receipt", "status"), "unavailable"),
        (0, ("paper", "planned", 0, "execute_on"), "2026-10-15"),
        (1, ("orders", 0, "planned_qty"), 3),
        (1, ("orders", 0, "timing"), "next_open"),
        (1, ("orders", 0, "timing_policy"), "other-policy"),
        (1, ("orders", 0, "decided"), "2026-10-12"),
        (1, ("orders", 0, "symbol"), "CCC"),
        (1, ("orders", 0, "terminal"), 1),
        (1, ("orders", 0, "execute_on"), "2026-10-15"),
    ],
)
def test_corrupted_model_or_execution_evidence_withholds_all(
    monkeypatch, part, path, value
):
    saved = admitted(monkeypatch)
    target = saved[part]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    result = view.read("unused", saved[0], saved[1], NOW)
    assert result["status"] == "unavailable"
    assert all(
        row["grade"] is row["qty"] is row["action"] is None
        for row in result["rows"].values()
    )


# Expired weekend plans cannot authenticate or turn chart grades into numeric decisions.
def test_stale_plan_is_withheld_before_any_authentication(monkeypatch):
    record, plan, _, _ = fixture()

    # Prove stale reads neither load artifacts nor invoke a model.
    def forbidden(*args):
        raise AssertionError("Expired plan authenticated")

    monkeypatch.setattr(view, "_authenticate", forbidden)
    result = view.read(
        "unused", record, plan, datetime.fromisoformat("2026-10-17T10:00:00-04:00")
    )
    assert result["status"] == "stale"
    assert all(
        row["grade"] is row["action"] is row["qty"] is None
        for row in result["rows"].values()
    )


# Invalid outer record shapes must return a safe unavailable envelope.
@pytest.mark.parametrize(
    "record",
    [
        None,
        [],
        [1],
        {"grades": []},
        {"session": 123, "grades": {"AAA": {"grade": "A"}}},
    ],
)
def test_bad_outer_record_shapes_are_safe(record):
    result = view.read("unused", record, {}, NOW)
    assert result["status"] == "unavailable"
    assert all(row["grade"] is None for row in result["rows"].values())


# Later broker mark fields cannot affect original targets or whole-share instructions.
def test_later_mark_changes_do_not_resize_the_admitted_plan(monkeypatch):
    record, plan, _, _ = admitted(monkeypatch)
    initial = view.read("unused", record, plan, NOW)
    for row in record["paper"]["positions"]:
        row["market_value"] *= 100
        row["current_price"] = 12345
    assert view.read("unused", record, plan, NOW) == initial


# Broker lookup failure withholds every instruction even when state still says sent.
def test_broker_status_failure_is_not_an_actionable_plan(monkeypatch):
    record, plan, _, _ = admitted(monkeypatch)
    plan["reason"] = "The broker's order status could not be read"
    plan["orders"][0]["state"] = "sent"
    result = view.read("unused", record, plan, NOW)
    assert result["status"] == "unavailable"
    assert all(
        row["grade"] is row["action"] is row["qty"] is row["when"] is None
        for row in result["rows"].values()
    )


# Hash typed arrays with the saved close contract rather than rebuilding predictions.
def array_hash(value):
    value = np.ascontiguousarray(value)
    return sha256(
        str(value.dtype).encode() + json.dumps(value.shape).encode() + value.tobytes()
    ).hexdigest()


# Save a small original-format numeric close and model byte receipt for read-only tests.
def saved_close(tmp_path):
    _, _, config, report = fixture()
    folder, model = tmp_path / "close", tmp_path / "model"
    folder.mkdir()
    model.mkdir()
    published = "2026-10-01T16:10:00-04:00"
    (model / "model.npz").write_bytes(b"authenticated numeric bytes never restored")
    publication = {
        "identity": {"published_at": published},
        "model_file": {
            "name": "model.npz",
            "sha256": sha256((model / "model.npz").read_bytes()).hexdigest(),
        },
    }
    (model / "publication.json").write_text(json.dumps(publication))
    config["model_receipt_sha256"] = sha256(
        (model / "publication.json").read_bytes()
    ).hexdigest()
    n = len(report.panel.tickers)
    arrays = {
        "dates": report.panel.dates,
        "symbols": np.array(report.panel.tickers),
        "features": np.ones((n, 13)),
        "prices": np.ones(n),
        "forecasts": np.ones(n),
        "support": np.ones(n, dtype=bool),
        "history_prices": np.ones((2, n)),
        "history_grades": report.graded.grades,
    }
    np.savez_compressed(folder / "close.npz", **arrays)
    provenance = {"basis": "original_synthetic_inputs"}
    identity = {
        "model_publication_sha256": config["model_receipt_sha256"],
        "model_published_at": published,
        "observed_at": "2026-10-13T19:46:38-04:00",
        "published_at": "2026-10-13T19:46:40-04:00",
        "policy": "forward-holding-close/1-shadow",
        "symbols": list(report.panel.tickers),
        "provenance": provenance,
        "array_sha256": {name: array_hash(value) for name, value in arrays.items()},
    }
    close = {
        "identity": identity,
        "identity_sha256": sha256(
            json.dumps(identity, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "arrays_sha256": sha256((folder / "close.npz").read_bytes()).hexdigest(),
        "adoption_eligible": False,
    }
    (folder / "close.json").write_text(json.dumps(close))
    admission = {
        "close_receipt_sha256": sha256(
            (folder / "close.json").read_bytes()
        ).hexdigest(),
        "provenance": provenance,
    }
    return folder, model, admission, config


# Authentication must inspect saved bytes without prediction, restoration or load_close.
def test_saved_close_never_runs_or_restores_a_numeric_model(tmp_path, monkeypatch):
    from backend.market import direct_daily_arithmetic, forward_arithmetic

    folder, model, admission, config = saved_close(tmp_path)

    # Fail if an artifact read reaches either the old loader or numerical inference.
    def forbidden(*args, **kwargs):
        raise AssertionError("Model called during projection")

    monkeypatch.setattr(forward_arithmetic, "load_close", forbidden)
    monkeypatch.setattr(forward_arithmetic, "load_publication", forbidden)
    monkeypatch.setattr(direct_daily_arithmetic, "predict", forbidden)
    original_load = np.load

    # Only the close arrays may be decoded; the model's numeric artifact stays opaque.
    def load(path, **kwargs):
        assert Path(path).name == "close.npz"
        return original_load(path, **kwargs)

    monkeypatch.setattr(np, "load", load)
    observed = view._saved_close(folder, model, admission, config, NOW)
    assert str(observed.dates[-1]) == SESSION
    assert observed.history_grades.shape == (2, 6)


# Corrupt close or model bytes must fail before any projection is returned.
@pytest.mark.parametrize(
    "name", ["close.json", "close.npz", "publication.json", "model.npz"]
)
def test_saved_artifact_corruption_is_rejected(tmp_path, name):
    folder, model, admission, config = saved_close(tmp_path)
    target = (folder if name.startswith("close") else model) / name
    target.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash differs"):
        view._saved_close(folder, model, admission, config, NOW)
