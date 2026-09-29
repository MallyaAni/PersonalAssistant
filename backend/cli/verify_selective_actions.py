"""Reopen this study's local artifacts; never fit, trade or rewrite evidence.

This checks label arithmetic and teacher state, not an independent execution
engine for every counterfactual. Joblib is loaded only with explicit local trust.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from backend.market.research_journal_replay import verify_archive

ACTIONS = ("Buy", "Add", "Trim", "Sell")
STATE_NAMES = (
    "held_weight",
    "cash_share",
    "target_gap",
    "holding_age",
    "sessions_to_reset",
    "signed_incremental_weight",
    "incumbent_weight",
    "action_Buy",
    "action_Add",
    "action_Trim",
    "action_Sell",
)


# Reconstruct actual holding ages and reset clocks from the teacher's saved events.
def _teacher_states(events):
    states, plans, opened = {}, {}, {}
    last_reset, next_reset = -1, None
    for event in events:
        t, kind = event["session_index"], event["type"]
        if kind == "open_account":
            next_reset = t
        elif kind == "fill_batch":
            before = np.asarray(event["positions_before"])
            after = np.asarray(event["positions_after"])
            for j in np.flatnonzero((before <= 0) & (after > 0)):
                opened[int(j)] = t
            for j in np.flatnonzero((before > 0) & (after <= 0)):
                opened.pop(int(j), None)
        elif kind == "mark":
            states[t] = {
                "positions": np.asarray(event["positions"], dtype=float),
                "cash": event["cash"],
                "nav": event["nav"],
                "opened": dict(opened),
            }
        elif kind == "decision":
            if event["metadata"].get("scheduled"):
                last_reset, next_reset = t, t + 20
            plans[t] = (np.asarray(event["submitted_units"]), last_reset, next_reset)
    return states, plans


# Compare every saved candidate with its current teacher state and terminal arithmetic.
def _verify_labels(inputs, data, evidence, states, plans, teacher_nav, forks):
    if len(evidence) != len(data["dates"]):
        raise ValueError("label evidence and candidate arrays differ in length")
    columns = {str(symbol): j for j, symbol in enumerate(inputs["tickers"])}
    baseline = {row["t"]: row for row in forks["baseline"]}
    if len(baseline) != len(forks["baseline"]):
        raise ValueError("duplicate baseline fork checks")
    mature_times, mature_years = set(), set()
    for row, item in enumerate(evidence):
        assert item["row"] == row
        t, j = item["t"], columns[item["symbol"]]
        state = states[t]
        order, last_reset, next_reset = plans[t]
        prices = inputs["adj_close"][t]
        price, held, incumbent, nav = (
            prices[j],
            state["positions"][j],
            order[j],
            state["nav"],
        )
        assert data["dates"][row] == inputs["dates"][t]
        assert data["actions"][row] == item["action"]
        assert t - last_reset in (0, 5, 10, 15)
        np.testing.assert_allclose(
            [item["held_units"], item["incumbent_units"], item["nav"], item["cash"]],
            [held, incumbent, nav, state["cash"]],
            rtol=1e-12,
            atol=1e-12,
        )
        assert (item["last_rebalance"], item["next_rebalance"]) == (
            last_reset,
            next_reset,
        )
        members = (
            inputs["membership"][t] & (inputs["grades"][t] >= 2) & np.isfinite(prices)
        )
        members[columns["SPY"]] = False
        count = int(members.sum())
        target = min(1.0 / count, 0.2) if count and members[j] else 0.0
        signed = (item["units"] - incumbent) * price / nav
        assert abs(signed) >= 0.005 - 1e-12
        assert abs((item["units"] - held) * price / nav) >= 0.005 - 1e-12
        age = t - state["opened"][j] if held > 0 else 0
        expected = np.r_[
            inputs["features"][t, j],
            held * price / nav,
            state["cash"] / nav,
            target - held * price / nav,
            age,
            max(0, next_reset - t),
            signed,
            incumbent * price / nav,
            [item["action"] == a for a in ACTIONS],
        ]
        np.testing.assert_allclose(
            data["features"][row], expected, rtol=1e-12, atol=1e-12
        )
        stop = t + 20
        if stop < len(inputs["dates"]):
            mature_times.add(t)
            mature_years.add(str(inputs["dates"][t].astype("datetime64[Y]")))
            assert data["label_end"][row] == inputs["dates"][stop]
            assert baseline[t]["stop"] == stop
            np.testing.assert_allclose(
                [item["baseline_endpoint_nav"], baseline[t]["nav"]],
                teacher_nav[stop],
                rtol=1e-12,
                atol=1e-12,
            )
            value = (item["action_endpoint_nav"] - teacher_nav[stop]) / nav
            np.testing.assert_allclose(
                [item["label"], data["labels"][row]], value, rtol=1e-12, atol=1e-12
            )
        else:
            assert np.isnan(data["labels"][row])
            assert np.isnat(data["label_end"][row])
            assert item["label"] is None
            assert item["action_endpoint_nav"] is None
            assert item["baseline_endpoint_nav"] is None
    assert set(baseline) == mature_times
    observed = {(item["t"], item["symbol"], item["action"]) for item in evidence}
    prefix_years = set()
    for row in forks["full_prefix"]:
        assert (row["t"], row["symbol"], row["action"]) in observed
        prefix_years.add(str(inputs["dates"][row["t"]].astype("datetime64[Y]")))
    assert prefix_years == mature_years
    return {
        "label_rows": len(evidence),
        "baseline_forks": len(baseline),
        "recorded_prefix_checks": len(forks["full_prefix"]),
    }


# Independently rebuild chronological masks rather than calling the trainer's splitter.
def _training_rows(data, first, stop):
    return (
        (data["dates"] >= first)
        & (data["dates"] < stop)
        & np.isfinite(data["labels"])
        & ~np.isnat(data["label_end"])
        & (data["label_end"] < stop)
    )


# Reload only hash-matched trusted model bytes and check their actual fitted state.
def _verify_models(root, data):
    import joblib

    receipt = json.loads((root / "training/training_receipts.json").read_text())
    assert receipt["complete"]
    assert receipt["feature_names"] == list(data["feature_names"])
    predictions = np.load(root / "training/predictions.npz", allow_pickle=False)
    np.testing.assert_array_equal(predictions["dates"], data["dates"])
    np.testing.assert_array_equal(predictions["actions"], data["actions"])
    covered = np.zeros(len(data["dates"]), dtype=bool)
    model_count, sample_count = 0, 0
    for fold in receipt["folds"]:
        year = fold["year"]
        assert fold["status"] == "FITTED"
        assert len(fold["settings"]) == 8
        ridge_settings = [s for s in fold["settings"] if s["family"] == "ridge"]
        tree_settings = [s for s in fold["settings"] if s["family"] == "tree"]
        assert [s["alpha"] for s in ridge_settings] == [10.0, 1000.0]
        assert [(s["max_leaf_nodes"], s["max_iter"]) for s in tree_settings] == [
            (leaves, iterations) for leaves in (7, 15) for iterations in (25, 50, 100)
        ]
        best_ridge = min(ridge_settings, key=lambda s: s["validation_mse"])
        best_tree = min(tree_settings, key=lambda s: s["validation_mse"])
        assert fold["selected_ridge_alpha"] == best_ridge["alpha"]
        assert fold["selected_tree_leaves"] == best_tree["max_leaf_nodes"]
        assert fold["selected_tree_iterations"] == best_tree["max_iter"]
        first = np.datetime64("2016-01-01")
        validation = np.datetime64(f"{year - 1}-01-01")
        test = np.datetime64(f"{year}-01-01")
        for key, begin, end in (
            ("fit", first, validation),
            ("validation", validation, test),
            ("refit", first, test),
        ):
            rows = _training_rows(data, begin, end)
            dates, ends = data["dates"][rows], data["label_end"][rows]
            assert fold[key]["rows"] == int(rows.sum())
            assert fold[key]["first_decision"] == str(dates[0])
            assert fold[key]["last_decision"] == str(dates[-1])
            assert fold[key]["last_label_end"] == str(ends.max())
            assert fold[key]["actions"] == {
                a: int((data["actions"][rows] == a).sum()) for a in ACTIONS
            }
            if key == "refit":
                refit = rows
        assert fold["fit"]["rows"] >= 500
        assert fold["validation"]["rows"] >= 100
        outer = (data["dates"] >= test) & (
            data["dates"] < np.datetime64(f"{year + 1}-01-01")
        )
        assert not (covered & outer).any()
        covered |= outer
        indices = np.flatnonzero(outer)
        assert fold["prediction_rows"] == len(indices)
        sample = indices[np.unique([0, len(indices) // 2, len(indices) - 1])]
        for family in ("ridge", "tree"):
            path = root / "training/models" / f"{year}-{family}.joblib"
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != fold[f"{family}_model_sha256"]:
                raise ValueError(f"model hash mismatch: {path.name}")
            saved = joblib.load(io.BytesIO(body))
            assert tuple(saved["feature_names"]) == tuple(data["feature_names"])
            assert saved["year"] == year
            assert saved["label_boundary"] == str(test)
            model = saved["model"]
            np.testing.assert_allclose(
                model.predict(data["features"][sample]),
                predictions[family][sample],
                rtol=1e-12,
                atol=1e-14,
            )
            if family == "ridge":
                scaler = model.named_steps["standardscaler"]
                np.testing.assert_allclose(
                    scaler.mean_,
                    data["features"][refit].mean(axis=0),
                    rtol=1e-12,
                    atol=1e-12,
                )
                assert model.named_steps["ridge"].alpha == fold["selected_ridge_alpha"]
                np.testing.assert_allclose(
                    scaler.var_,
                    data["features"][refit].var(axis=0),
                    rtol=1e-12,
                    atol=1e-12,
                )
            else:
                assert model.max_iter == fold["selected_tree_iterations"]
                assert model.max_leaf_nodes == fold["selected_tree_leaves"]
                assert model.early_stopping is False
                assert model.learning_rate == 0.05
                assert model.l2_regularization == 10
                assert model.min_samples_leaf == 100
                assert model.random_state == 29
                assert model.loss == "squared_error"
            model_count += 1
            sample_count += len(sample)
        for action in ACTIONS:
            past = refit & (data["actions"] == action)
            mean = float(data["labels"][past].mean()) if past.any() else 0.0
            np.testing.assert_allclose(
                fold["action_means"][action], mean, rtol=1e-12, atol=1e-14
            )
            np.testing.assert_allclose(
                predictions["mean"][outer & (data["actions"] == action)],
                mean,
                rtol=1e-12,
                atol=1e-14,
            )
    expected = (data["dates"] >= np.datetime64("2019-01-01")) & (
        data["dates"] < np.datetime64("2027-01-01")
    )
    np.testing.assert_array_equal(covered, expected)
    for family in ("ridge", "tree", "mean"):
        np.testing.assert_array_equal(np.isfinite(predictions[family]), expected)
    return {
        "folds": len(receipt["folds"]),
        "models_reloaded": model_count,
        "prediction_samples": sample_count,
        "outer_rows_per_model": int(expected.sum()),
    }


# Reopen the study without changing evidence or claiming formulas prove execution.
def audit(root, *, trust_local_models=False):
    from backend.market.daily_action_model import build_dataset
    from backend.market.panel import Panel

    if not __debug__:
        raise RuntimeError("verification requires Python assertions enabled")
    if not trust_local_models:
        raise ValueError(
            "explicit trust in locally generated joblib models is required"
        )
    root = Path(root)
    # Materialize once: repeated NpzFile lookups decompress entire arrays per row.
    with np.load(root / "inputs.npz", allow_pickle=False) as archive:
        inputs = {key: archive[key] for key in archive.files}
    with np.load(root / "labels/action-data.npz", allow_pickle=False) as archive:
        data = {key: archive[key] for key in archive.files}
    assert tuple(data["feature_names"][-11:]) == STATE_NAMES
    panel = Panel(
        dates=inputs["dates"],
        tickers=tuple(inputs["tickers"]),
        open=inputs["open"],
        high=inputs["high"],
        low=inputs["low"],
        close=inputs["close"],
        adj_close=inputs["adj_close"],
        volume=inputs["volume"],
        themes={},
        benchmark="SPY",
    )
    rebuilt = build_dataset(
        panel, inputs["membership"], inputs["grades"], inputs["qqq"]
    )
    np.testing.assert_allclose(
        rebuilt.features, inputs["features"], rtol=1e-12, atol=1e-12, equal_nan=True
    )
    assert tuple(data["feature_names"][:22]) == rebuilt.feature_names
    evidence = json.loads((root / "labels/label-evidence.json").read_text())
    forks = json.loads((root / "labels/fork-checks.json").read_text())
    folder = root / "labels/teacher-journal"
    proof = verify_archive(folder)
    if not proof["ok"]:
        raise ValueError(
            f"teacher journal failed independent replay: {proof['errors']}"
        )
    states, plans = _teacher_states(json.loads((folder / "events.json").read_text()))
    teacher_nav = {t: state["nav"] for t, state in states.items()}
    curve = np.load(root / "labels/teacher-curve.npz", allow_pickle=False)
    np.testing.assert_array_equal(
        curve["dates"],
        np.asarray([m["session"] for m in proof["marks"]], dtype="datetime64[D]"),
    )
    np.testing.assert_allclose(
        curve["equity"], [m["nav"] for m in proof["marks"]], rtol=1e-12, atol=1e-12
    )
    result = _verify_labels(inputs, data, evidence, states, plans, teacher_nav, forks)
    result.update(_verify_models(root, data))
    result.update(
        {
            "ok": True,
            "teacher_accounting_verified": True,
            "counterfactual_check_scope": (
                "state/features, terminal arithmetic and recorded prefix-check coverage"
            ),
            "all_counterfactual_economic_paths_independently_replayed": False,
        }
    )
    return result


# Print bounded verification evidence; the command never writes study files.
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--trust-local-models", action="store_true")
    args = parser.parse_args(argv)
    if not args.trust_local_models:
        parser.error(
            "--trust-local-models is required for locally generated joblib files"
        )
    print(json.dumps(audit(args.run, trust_local_models=True), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
