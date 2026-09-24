"""Actual-fit, synthetic acceptance of chronological research allocation selection.

Every account is independently replayed from its journal. These tests prove the
engineering contract on declared synthetic evidence, not historical availability,
label correctness, economic value, or readiness to promote any trading strategy.
"""

import hashlib
import json
import math
from dataclasses import asdict, replace

import numpy as np
import pytest

from backend.market import nested_allocation as nested
from backend.market.nested_ridge import RegressionInputs
from backend.market.panel import Panel
from backend.market.research_journal_replay import verify_snapshot


# Build nontrivial price paths and dated outcomes without relying on any market store.
def _case(rows=34, *, features=None, labels=None):
    calendar = np.arange("2024-01-02", "2025-01-01", dtype="datetime64[D]")
    calendar = calendar[np.is_busday(calendar)]
    dates = calendar[:rows]
    step = np.arange(rows, dtype=float)
    prices = 100 * np.exp(step[:, None] * np.array([0.008, -0.002, 0.003, 0.005]))
    panel = Panel(
        dates=dates,
        tickers=("AAA", "BBB", "SPY", "QQQ"),
        open=prices.copy(),
        high=prices + 1,
        low=prices - 1,
        close=prices.copy(),
        adj_close=prices.copy(),
        volume=np.full_like(prices, 1000),
        themes={},
        benchmark="SPY",
    )
    features = (
        np.column_stack((np.sin(step / 3), step / 10))
        if features is None
        else np.asarray(features)
    )
    outcomes = (
        np.tile([0.04, 0.01, -0.01], (rows, 1))
        if labels is None
        else np.asarray(labels)
    )
    inputs = RegressionInputs(
        dates=dates,
        features=features,
        feature_available_on=np.broadcast_to(dates[:, None], features.shape),
        labels=outcomes,
        label_end_on=np.broadcast_to(calendar[1 : rows + 1, None], outcomes.shape),
        label_available_on=np.broadcast_to(
            calendar[2 : rows + 2, None], outcomes.shape
        ),
    )
    weights = np.zeros_like(prices)
    weights[:, 0] = 1
    return panel, inputs, weights


# Use the real protocol on a small calendar with enough matured inner training rows.
def _protocol(**overrides):
    return replace(
        nested.NestedProtocol(
            first_outer=20,
            outer_sessions=4,
            inner_sessions=3,
            inner_blocks=3,
            min_train_rows=4,
        ),
        **overrides,
    )


# Independently reconcile every recorded state, fee, trade, and final pending order.
def _assert_account(account, dates):
    proof = verify_snapshot(account["journal"])
    result = account["result"]
    assert proof["ok"], proof["errors"]
    assert proof["accounting_verified"]
    assert proof["integrity_verified"]
    assert proof["complete"]
    # The general verifier checks pending shape; this test checks adapter retry intent.
    assert proof["pending_semantics_verified"] is False
    assert proof == account["verification"]
    np.testing.assert_array_equal(result["dates"], dates)
    for name in ("nav", "cash", "positions"):
        np.testing.assert_allclose(
            result[name],
            [mark[name] for mark in proof["marks"]],
            rtol=1e-12,
            atol=1e-12,
        )
    assert result["nav"][0] == result["cash"][0] == 1.0
    np.testing.assert_array_equal(result["positions"][0], np.zeros(4))
    np.testing.assert_allclose(result["cash_fraction"], result["cash"] / result["nav"])
    events = account["journal"]["events"]
    assert sum(event["type"] == "open_account" for event in events) == 1
    assert sum(event["type"] == "finish" for event in events) == 1
    fees = np.zeros(len(dates))
    for event in events:
        if event["type"] == "fill_batch":
            assert event["phase"] == "open"
            assert event["recycle_sells"] is False
            fees[event["session_index"]] += event["fee_total"]
    np.testing.assert_allclose(result["fees"], fees, rtol=1e-12, atol=1e-12)
    assert sum(result["fees"]) == pytest.approx(proof["total_fees"], abs=1e-12)
    traded = np.array([mark["traded"] for mark in proof["marks"]])
    assert result["turnover"][0] == 0
    np.testing.assert_allclose(
        result["turnover"][1:], np.diff(traded) / result["nav"][:-1], atol=1e-12
    )
    assert result["terminal_pending"] == proof["terminal"]["pending"]
    final_batches = [
        event
        for event in events
        if event["type"] == "fill_batch" and event["session_index"] == len(dates) - 1
    ]
    retry = False
    if final_batches:
        assert len(final_batches) == 1
        last = final_batches[0]
        after = np.array(last["positions_after"])
        retry = bool(
            np.any(after < last["positions_before"])
            and np.any(after < last["submitted_units"])
            and last["cash_after"] > 0
        )
    assert result["terminal_pending"] == ({"retry": True} if retry else {})
    assert len(result["decisions"]) == len(dates) - 1
    for index, decision in enumerate(result["decisions"]):
        assert decision["session"] == str(dates[index])
        assert decision["information_through"] == str(dates[index])
        assert decision["earliest_execution_session"] == str(dates[index + 1])
    encoded = (
        json.dumps(account["journal"], sort_keys=True, separators=(",", ":")) + "\n"
    )
    assert account["journal_sha256"] == hashlib.sha256(encoded.encode()).hexdigest()
    assert proof["adoption_eligible"] is result["adoption_eligible"] is False


# Rebuild each training transform and ridge solution from eligible source rows alone.
def _assert_fit(receipt, inputs, first):
    assert receipt["fit_index"] == first
    assert receipt["fit_on"] == str(inputs.dates[first])
    assert receipt["candidate_rows"] == list(range(first))
    for column, name in enumerate(("stock", "SPY", "QQQ")):
        target = receipt["targets"][name]
        prefix = np.arange(first)
        eligible = (
            np.isfinite(inputs.labels[:first, column])
            & (inputs.label_end_on[:first, column] < inputs.dates[first])
            & (inputs.label_available_on[:first, column] < inputs.dates[first])
        )
        rows = prefix[eligible]
        assert target["eligible_rows"] == rows.tolist()
        assert target["dropped_rows"] == prefix[~eligible].tolist()
        known = np.isfinite(inputs.features[rows]) & (
            inputs.feature_available_on[rows] <= inputs.dates[rows, None]
        )
        np.testing.assert_array_equal(target["feature_known_mask"], known)
        np.testing.assert_array_equal(target["feature_missing_mask"], ~known)
        medians = np.array(
            [
                np.median(inputs.features[rows[known[:, k]], k])
                if known[:, k].any()
                else 0
                for k in range(inputs.features.shape[1])
            ]
        )
        imputed = np.where(known, inputs.features[rows], medians)
        means, scales = imputed.mean(axis=0), imputed.std(axis=0)
        scales[scales == 0] = 1
        for key, expected in (("median", medians), ("mean", means), ("scale", scales)):
            np.testing.assert_allclose(target["transform"][key], expected)
        np.testing.assert_array_equal(
            target["transform"]["all_missing"], ~known.any(axis=0)
        )
        design = np.column_stack(((imputed - means) / scales, (~known).astype(float)))
        centered = design - design.mean(axis=0)
        outcomes = inputs.labels[rows, column]
        # Augmented least squares is independent of the kernel's normal equations.
        augmented = np.vstack(
            (centered, math.sqrt(receipt["alpha"]) * np.eye(design.shape[1]))
        )
        response = np.concatenate(
            (outcomes - outcomes.mean(), np.zeros(design.shape[1]))
        )
        coefficients = np.linalg.lstsq(augmented, response, rcond=None)[0]
        intercept = outcomes.mean() - design.mean(axis=0) @ coefficients
        np.testing.assert_allclose(
            target["coefficients"], coefficients, rtol=1e-10, atol=1e-12
        )
        assert target["intercept"] == pytest.approx(intercept, abs=1e-12)
        evidence = target["training_inputs"]
        assert evidence["rows"] == rows.tolist()
        assert evidence["decision_on"] == inputs.dates[rows].astype(str).tolist()
        np.testing.assert_array_equal(evidence["labels"], outcomes)
        for observed, expected, mask in zip(
            evidence["known_features"], inputs.features[rows], known, strict=True
        ):
            assert observed == [
                float(value) if present else None
                for value, present in zip(expected, mask, strict=True)
            ]


# Rebuild forecasts from fitted state and features known at each decision.
def _assert_predictions(fold, inputs):
    rows = np.arange(fold["start"], fold["stop"])
    known = np.isfinite(inputs.features[rows]) & (
        inputs.feature_available_on[rows] <= inputs.dates[rows, None]
    )
    predictions = []
    for name in ("stock", "SPY", "QQQ"):
        target = fold["fit"]["targets"][name]
        transform = target["transform"]
        imputed = np.where(known, inputs.features[rows], transform["median"])
        standardized = (imputed - transform["mean"]) / transform["scale"]
        design = np.column_stack((standardized, (~known).astype(float)))
        predictions.append(design @ target["coefficients"] + target["intercept"])
    np.testing.assert_allclose(
        fold["predictions"], np.column_stack(predictions), atol=1e-12
    )


# Exercise all inner fits and both funded costs before one continuous outer account.
def test_real_nested_fits_selection_geometry_and_every_account_reconcile():
    panel, inputs, weights = _case()
    protocol = _protocol()
    output = nested.run(panel, inputs, weights, protocol=protocol)
    assert [fold["start"] for fold in output["outer_folds"]] == [20, 24, 28, 32]
    assert [fold["stop"] for fold in output["outer_folds"]] == [24, 28, 32, 33]
    assert len(output["instructions"]) == 13
    assert len(output["inner_runs"]) == 4 * 4 * 2
    for fold in output["outer_folds"]:
        first = fold["start"] - 10
        last_mark = fold["start"] - 1
        assert fold["inner_first"] == first
        assert fold["inner_last_mark"] == last_mark
        _assert_fit(fold["fit"], inputs, fold["start"])
        _assert_predictions(fold, inputs)
        for number, candidate in enumerate(fold["candidates"]):
            assert candidate["id"] == f"candidate-{number}"
            assert candidate["alpha"] == protocol.alphas[number // 2]
            assert candidate["margin"] == protocol.switch_margins[number % 2]
            assert [
                (item["first"], item["stop"]) for item in candidate["inner_fits"]
            ] == [(first, first + 3), (first + 3, first + 6), (first + 6, last_mark)]
            for item in candidate["inner_fits"]:
                _assert_fit(item["fit"], inputs, item["first"])
            growth = {}
            for cost in (10, 25):
                account = next(
                    item
                    for item in output["inner_runs"]
                    if item["outer_start"] == fold["start"]
                    and item["candidate_id"] == candidate["id"]
                    and item["cost_bps"] == cost
                )
                assert account["first"] == first
                assert account["last_mark"] == last_mark
                _assert_account(account, panel.dates[first : last_mark + 1])
                nav = account["result"]["nav"]
                growth[str(cost)] = math.log(nav[-1] / nav[0])
                assert nav[3] != 1
                assert nav[6] > nav[3]
                assert account["result"]["positions"][3, 0] > 0
                assert account["result"]["positions"][6, 0] > 0
            assert candidate["log_growth_by_cost"] == growth
            assert candidate["score"] == min(growth.values())
        best = max(fold["candidates"], key=lambda candidate: candidate["score"])
        assert fold["selected_id"] == best["id"]
    for cost, accounts in output["accounts"].items():
        for account in accounts.values():
            _assert_account(account, panel.dates[20:])
            assert account["journal"]["manifest"]["cost_bps"] == int(cost)
            assert account["result"]["nav"][4] > 1
            assert account["result"]["nav"][8] > account["result"]["nav"][4]
        for key in ("nav", "cash", "positions", "fees", "turnover"):
            np.testing.assert_array_equal(
                accounts["candidate"]["result"][key],
                accounts["no_gate_adapter"]["result"][key],
            )
    assert (
        output["accounts"]["10"]["candidate"]["result"]["nav"][-1]
        > output["accounts"]["25"]["candidate"]["result"]["nav"][-1]
    )
    assert all(
        output[name] is False
        for name in (
            "adoption_eligible",
            "historical_availability_verified",
            "label_derivation_verified",
            "benchmark_study_complete",
        )
    )


# Exact zero forecasts exercise real ridge fits while keeping every candidate in cash.
def test_cash_ties_use_declared_candidate_order_not_a_hidden_preference():
    panel, inputs, weights = _case(labels=np.zeros((34, 3)))
    protocol = _protocol(alphas=(100.0, 1.0), switch_margins=(0.005, 0.0))
    output = nested.run(panel, inputs, weights, protocol=protocol)
    for fold in output["outer_folds"]:
        assert fold["selected_id"] == "candidate-0"
        assert fold["starting_mode"] == fold["ending_mode"] == "cash"
        np.testing.assert_array_equal(
            fold["predictions"], np.zeros((fold["stop"] - fold["start"], 3))
        )
        assert all(candidate["score"] == 0 for candidate in fold["candidates"])
    for accounts in output["accounts"].values():
        account = accounts["candidate"]
        _assert_account(account, panel.dates[20:])
        np.testing.assert_array_equal(account["result"]["nav"], np.ones(14))
        assert sum(account["result"]["fees"]) == 0
        assert accounts["no_gate_adapter"]["result"]["nav"][-1] > 1


# Select the less costly real account and include the last inner mark in its score.
def test_real_inner_trading_costs_select_a_non_first_candidate_before_outer_prices():
    x = np.full(25, 0.034)
    x[:10] = np.linspace(-0.1, 0.1, 10)
    x[10:19:2] = 0.028
    labels = np.column_stack((x, np.full(25, 0.03), np.full(25, -0.02)))
    panel, inputs, weights = _case(25, features=x[:, None], labels=labels)
    prices = np.full_like(panel.open, 100.0)
    panel = replace(
        panel, open=prices.copy(), close=prices.copy(), adj_close=prices.copy()
    )
    protocol = _protocol(alphas=(1.0,), switch_margins=(0.0, 0.005))
    output = nested.run(panel, inputs, weights, protocol=protocol)
    fold = output["outer_folds"][0]
    assert fold["selected_id"] == "candidate-1"
    assert fold["candidates"][1]["score"] > fold["candidates"][0]["score"]
    for cost in (10, 25):
        accounts = {
            account["candidate_id"]: account
            for account in output["inner_runs"]
            if account["cost_bps"] == cost
        }
        for account in accounts.values():
            _assert_account(account, panel.dates[10:20])
        churn = accounts["candidate-0"]["result"]
        held = accounts["candidate-1"]["result"]
        assert sum(churn["fees"]) > sum(held["fees"])
        assert churn["nav"][-1] < held["nav"][-1]
    prices[19, 2] = 50.0
    last_mark_changed = nested.run(
        replace(panel, close=prices.copy(), adj_close=prices.copy()),
        inputs,
        weights,
        protocol=protocol,
    )
    for old, new in zip(
        fold["candidates"],
        last_mark_changed["outer_folds"][0]["candidates"],
        strict=True,
    ):
        assert new["score"] == pytest.approx(old["score"] - math.log(2))
        assert new["inner_fits"] == old["inner_fits"]
    prices[19, 2] = 100.0
    prices[20:] *= 8
    future_changed = nested.run(
        replace(panel, open=prices.copy(), close=prices.copy(), adj_close=prices),
        inputs,
        weights,
        protocol=protocol,
    )
    assert future_changed["outer_folds"][0] == fold


# Margin is the sole switching hurdle, with strict comparison and stable mode ties.
@pytest.mark.parametrize(
    ("prediction", "current", "margin", "expected"),
    [
        ([0.001, 0, 0], "cash", 0, "stock"),
        ([0.005, 0, 0], "cash", 0.005, "cash"),
        ([0.005001, 0, 0], "cash", 0.005, "stock"),
        ([0.25, 0.125, -0.1], "SPY", 0.125, "SPY"),
        ([0.251, 0.125, -0.1], "SPY", 0.125, "stock"),
        ([0.1, 0.1, 0.1], "QQQ", 0, "QQQ"),
        ([0.1, 0.1, 0.1], "cash", 0, "stock"),
        ([0, 0, 0], "SPY", 0, "SPY"),
        ([-0.01, -0.02, -0.03], "QQQ", 0, "cash"),
        ([0.01, 0.02, 0.03], "cash", 0, "QQQ"),
    ],
)
def test_switching_uses_only_the_declared_strict_margin(
    prediction, current, margin, expected
):
    assert nested.choose_mode(prediction, current, margin) == expected


# Carry mode through inner refits and outer folds when a rival's edge is below margin.
def test_hysteresis_intent_and_account_wealth_survive_all_refit_boundaries():
    x = np.full(29, 0.036)
    x[:10] = np.linspace(-0.1, 0.1, 10)
    x[10:13] = x[20:24] = 0.02
    labels = np.column_stack((x, np.full(29, 0.03), np.full(29, -0.02)))
    panel, inputs, weights = _case(29, features=x[:, None], labels=labels)
    output = nested.run(
        panel,
        inputs,
        weights,
        protocol=_protocol(alphas=(1.0,), switch_margins=(0.01,)),
    )
    first, second = output["outer_folds"]
    assert first["starting_mode"] == "cash"
    assert first["ending_mode"] == "SPY"
    assert second["starting_mode"] == second["ending_mode"] == "SPY"
    for stock, spy, _ in second["predictions"]:
        assert spy < stock < spy + 0.01
        assert stock > 0.01
    assert all(row.spy_weight == 1 for row in output["instructions"])
    for cost in ("10", "25"):
        outer = output["accounts"][cost]["candidate"]
        _assert_account(outer, panel.dates[20:])
        assert outer["result"]["positions"][4, 2] > 0
        np.testing.assert_array_equal(
            outer["result"]["positions"][4:],
            np.broadcast_to(outer["result"]["positions"][4], (5, 4)),
        )
        inner = next(
            item
            for item in output["inner_runs"]
            if item["outer_start"] == 20 and item["cost_bps"] == int(cost)
        )
        _assert_account(inner, panel.dates[10:20])
        assert all(row["spy_weight"] == 1 for row in inner["result"]["decisions"])
        assert not inner["result"]["decisions"][3]["planned"]
        assert not inner["result"]["decisions"][6]["planned"]


# Seed off-cadence accounts once and refresh only at absolute multiples of twenty.
def test_stock_composition_cadence_is_global_not_reset_by_inner_or_outer_folds():
    panel, inputs, weights = _case(45)
    weights[:20, :2] = [0.3, 0.1]
    weights[20:40, :2] = [0.2, 0.4]
    weights[40:, :2] = [0.1, 0.2]
    output = nested.run(
        panel,
        inputs,
        weights,
        protocol=_protocol(first_outer=23, alphas=(1.0,), switch_margins=(0.0,)),
    )
    for offset, instruction in enumerate(output["instructions"]):
        absolute = 23 + offset
        if absolute == 23 or absolute % 20 == 0:
            assert instruction.stock_weights == dict(
                zip(("AAA", "BBB"), weights[absolute, :2], strict=True)
            )
        else:
            assert instruction.stock_weights is None
    for accounts in output["accounts"].values():
        for account in accounts.values():
            _assert_account(account, panel.dates[23:])
            for offset, decision in enumerate(account["result"]["decisions"]):
                absolute = 23 + offset
                np.testing.assert_array_equal(
                    decision["stock_weights"], weights[absolute]
                )
                np.testing.assert_array_equal(
                    decision["desired_weights"], weights[absolute]
                )
                assert decision["planned"] is (absolute in (23, 40))
    for inner in output["inner_runs"]:
        _assert_account(inner, panel.dates[inner["first"] : inner["last_mark"] + 1])
        for offset, decision in enumerate(inner["result"]["decisions"]):
            absolute = inner["first"] + offset
            assert decision["planned"] is (offset == 0 or absolute % 20 == 0)
            np.testing.assert_array_equal(decision["stock_weights"], weights[absolute])


# Carry a sell-funded retry over a fold boundary and execute the latest intent.
def test_funding_retry_crosses_outer_fold_and_uses_the_latest_mode():
    x = np.full(29, 0.08)
    x[:10] = np.linspace(-0.1, 0.1, 10)
    x[23] = 0.0
    labels = np.column_stack((x, np.full(29, 0.03), np.full(29, -0.02)))
    panel, inputs, weights = _case(29, features=x[:, None], labels=labels)
    output = nested.run(
        panel, inputs, weights, protocol=_protocol(alphas=(1.0,), switch_margins=(0.0,))
    )
    assert output["instructions"][3].spy_weight == 1
    assert output["instructions"][4].stock_scale == 1
    for accounts in output["accounts"].values():
        account = accounts["candidate"]
        _assert_account(account, panel.dates[20:])
        result = account["result"]
        assert result["positions"][3, 0] > 0
        np.testing.assert_array_equal(result["positions"][4], np.zeros(4))
        assert result["cash"][4] > 0
        assert "funding follow-up" in result["decisions"][4]["triggers"]
        np.testing.assert_array_equal(
            result["decisions"][4]["desired_weights"], [1, 0, 0, 0]
        )
        assert result["positions"][5, 0] > 0
        assert result["positions"][5, 2] == 0


# Preserve earlier decisions and marks when each future source changes independently.
@pytest.mark.parametrize("changed_source", ["labels", "features", "prices"])
def test_future_sources_cannot_change_earlier_fits_selection_or_account_prefix(
    changed_source,
):
    panel, inputs, weights = _case()
    original = nested.run(panel, inputs, weights, protocol=_protocol())
    changed_panel, changed_inputs = panel, inputs
    if changed_source in ("labels", "features"):
        values = getattr(inputs, changed_source).copy()
        values[24:] = values[24:] * 17 + 7
        changed_inputs = replace(inputs, **{changed_source: values})
    else:
        prices = panel.adj_close.copy()
        prices[25:] *= 1.7
        changed_panel = replace(
            panel, open=prices.copy(), close=prices.copy(), adj_close=prices
        )
    observed = nested.run(changed_panel, changed_inputs, weights, protocol=_protocol())
    assert observed["outer_folds"][0] == original["outer_folds"][0]
    assert observed["instructions"][:4] == original["instructions"][:4]
    assert observed["source_inputs"]["sha256"] != original["source_inputs"]["sha256"]
    for before, after in zip(
        original["inner_runs"][:8], observed["inner_runs"][:8], strict=True
    ):
        assert before["journal"] == after["journal"]
        assert before["journal_sha256"] == after["journal_sha256"]
    for cost in ("10", "25"):
        before = original["accounts"][cost]["candidate"]
        after = observed["accounts"][cost]["candidate"]
        _assert_account(after, panel.dates[20:])
        for name in ("nav", "cash", "positions", "fees", "turnover"):
            np.testing.assert_array_equal(
                before["result"][name][:5], after["result"][name][:5]
            )
        before_marks = [
            event
            for event in before["journal"]["events"]
            if event["type"] in ("open_account", "fill_batch", "mark")
            and event["session_index"] <= 4
        ]
        after_marks = [
            event
            for event in after["journal"]["events"]
            if event["type"] in ("open_account", "fill_batch", "mark")
            and event["session_index"] <= 4
        ]
        assert before_marks == after_marks
    if changed_source == "prices":
        assert (
            original["accounts"]["10"]["candidate"]["result"]["nav"][-1]
            != observed["accounts"]["10"]["candidate"]["result"]["nav"][-1]
        )


# Exclude unannounced outcomes and mask features unavailable at their original decision.
def test_publication_lags_and_training_only_transforms_control_real_fits():
    panel, inputs, weights = _case()
    feature_dates = inputs.feature_available_on.copy()
    feature_dates[:, 1] = inputs.dates + np.timedelta64(1, "D")
    publication = inputs.label_available_on.copy()
    publication[1, 0] = inputs.dates[20]
    publication[2, 1] = inputs.dates[21]
    labels = inputs.labels.copy()
    labels[0, 2] = np.nan
    inputs = replace(
        inputs,
        feature_available_on=feature_dates,
        label_available_on=publication,
        labels=labels,
    )
    output = nested.run(panel, inputs, weights, protocol=_protocol())
    first = output["outer_folds"][0]
    _assert_fit(first["fit"], inputs, 20)
    _assert_predictions(first, inputs)
    assert (
        18
        in first["fit"]["targets"]["stock"]["dropped_by_reason"][
            "label_not_available_before_fit"
        ]
    )
    assert inputs.label_end_on[18, 0] < inputs.dates[20]
    assert inputs.label_available_on[18, 0] == inputs.dates[20]
    assert 1 not in first["fit"]["targets"]["stock"]["eligible_rows"]
    assert 2 not in first["fit"]["targets"]["SPY"]["eligible_rows"]
    assert 0 not in first["fit"]["targets"]["QQQ"]["eligible_rows"]
    for target in first["fit"]["targets"].values():
        assert target["transform"]["all_missing"] == [False, True]
        assert target["transform"]["median"][1] == 0
        assert target["transform"]["scale"][1] == 1
    values = inputs.features.copy()
    values[:, 1] = np.arange(len(values)) * 10000 + 12345
    labels = inputs.labels.copy()
    labels[1, 0] = 1000
    labels[2, 1] = -1000
    changed = replace(inputs, features=values, labels=labels)
    repeated = nested.run(panel, changed, weights, protocol=_protocol())
    assert first == repeated["outer_folds"][0]
    assert output["instructions"][:4] == repeated["instructions"][:4]
    assert output["source_inputs"]["sha256"] != repeated["source_inputs"]["sha256"]


# Excluded-label diagnostics can change without changing the fitted model or action IDs.
def test_unavailable_label_classification_changes_receipt_but_not_model_or_actions():
    panel, inputs, weights = _case(25)
    output = nested.run(panel, inputs, weights, protocol=_protocol())
    labels = inputs.labels.copy()
    labels[18, 0] = np.nan
    changed = nested.run(
        panel, replace(inputs, labels=labels), weights, protocol=_protocol()
    )
    before, after = output["outer_folds"][0], changed["outer_folds"][0]
    assert before["fit_receipt_sha256"] != after["fit_receipt_sha256"]
    assert before["model_hash"] == after["model_hash"]
    assert before["fit"]["fitted_input_sha256"] == after["fit"]["fitted_input_sha256"]
    assert before["predictions"] == after["predictions"]
    assert before["selected_id"] == after["selected_id"]
    assert output["instructions"] == changed["instructions"]
    for cost in ("10", "25"):
        assert (
            output["accounts"][cost]["candidate"]["journal"]
            == changed["accounts"][cost]["candidate"]["journal"]
        )


# Missing prices for a never-used symbol cannot impose global all-symbol completeness.
def test_unused_missing_prices_do_not_block_any_inner_or_outer_account():
    panel, inputs, weights = _case()
    for values in (panel.open, panel.close, panel.adj_close):
        values[:, 1] = np.nan
    output = nested.run(panel, inputs, weights, protocol=_protocol())
    for account in output["inner_runs"]:
        _assert_account(
            account, panel.dates[account["first"] : account["last_mark"] + 1]
        )
        assert np.all(account["result"]["positions"][:, 1] == 0)
    for accounts in output["accounts"].values():
        for account in accounts.values():
            _assert_account(account, panel.dates[20:])
            assert np.all(account["result"]["positions"][:, 1] == 0)


# Missing required execution evidence fails the run instead of silently dropping a name.
def test_missing_required_open_fails_the_entire_nested_run():
    panel, inputs, weights = _case()
    panel.open[11, 0] = np.nan
    with pytest.raises(ValueError, match="missing required price: open"):
        nested.run(panel, inputs, weights, protocol=_protocol())


# Fail the whole run when matured training is insufficient, never substitute a cash fit.
def test_unmatured_training_rows_fail_closed_before_any_result_is_returned():
    panel, inputs, weights = _case()
    with pytest.raises(ValueError, match="8 eligible training rows; requires 10"):
        nested.run(panel, inputs, weights, protocol=_protocol(min_train_rows=10))


# Fail real overflowing arithmetic without returning cash or a previous model.
def test_real_fit_arithmetic_failure_is_not_hidden_by_an_all_cash_fallback():
    panel, inputs, weights = _case(features=np.full((34, 2), 1e308))
    with pytest.raises(ValueError, match="fit arithmetic failed"):
        nested.run(panel, inputs, weights, protocol=_protocol())


# Refuse invalid geometry and ambiguous candidate order before beginning selection.
@pytest.mark.parametrize(
    "overrides",
    [
        {"first_outer": 10},
        {"first_outer": 33},
        {"first_outer": True},
        {"outer_sessions": 0},
        {"inner_sessions": 1.5},
        {"inner_blocks": 0},
        {"min_train_rows": False},
        {"alphas": ()},
        {"alphas": [1.0]},
        {"alphas": (1.0, 1.0)},
        {"alphas": (0.0,)},
        {"alphas": (np.inf,)},
        {"switch_margins": (True,)},
        {"switch_margins": (-0.005,)},
        {"switch_margins": (0.0, 0.0)},
    ],
)
def test_invalid_geometry_or_candidate_grid_is_rejected(overrides):
    panel, inputs, weights = _case()
    with pytest.raises(ValueError, match="history|integer|alphas|switch_margins"):
        nested.run(panel, inputs, weights, protocol=_protocol(**overrides))


# Reject unscheduled basket changes even if their values are otherwise cash bounded.
@pytest.mark.parametrize("changed_at", [1, 19, 21, 24])
def test_basket_cannot_change_at_a_fold_or_arbitrary_non_cadence_index(changed_at):
    panel, inputs, weights = _case()
    weights[changed_at:, 0] = 0.5
    with pytest.raises(ValueError, match="outside the absolute cadence"):
        nested.run(panel, inputs, weights, protocol=_protocol())


# Bind owned source arrays and clearly distinguish a decision hash from full accounting.
def test_input_manifest_and_output_hash_have_replayable_explicit_scopes():
    panel, inputs, weights = _case(25)
    output = nested.run(panel, inputs, weights, protocol=_protocol())
    evidence = output["source_inputs"]
    manifest = evidence["manifest"]
    for name, values in evidence["arrays"].items():
        item = manifest["arrays"][name]
        assert item["shape"] == list(values.shape)
        assert item["dtype"] == values.dtype.str
        assert (
            item["sha256"]
            == hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()
        )
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    assert evidence["sha256"] == hashlib.sha256(encoded.encode()).hexdigest()
    payload = {
        "protocol_sha256": output["protocol_sha256"],
        "outer_folds": output["outer_folds"],
        "instructions": [asdict(row) for row in output["instructions"]],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    assert (
        output["decision_output_sha256"] == hashlib.sha256(encoded.encode()).hexdigest()
    )
    assert "not account results" in output["decision_output_hash_scope"]
    source_prices = evidence["arrays"]["adjusted_close"].copy()
    source_weights = evidence["arrays"]["stock_weights"].copy()
    panel.adj_close[:] = 999
    weights[:] = 0
    np.testing.assert_array_equal(evidence["arrays"]["adjusted_close"], source_prices)
    np.testing.assert_array_equal(evidence["arrays"]["stock_weights"], source_weights)
