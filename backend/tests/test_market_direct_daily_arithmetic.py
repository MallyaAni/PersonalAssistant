"""Pin numeric model persistence and original-control artifact boundaries."""

import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from sklearn.ensemble import HistGradientBoostingRegressor

from backend.cli import market_direct_daily_arithmetic as cli


# Reconstruct predictions directly from serialized numeric nodes, including NaNs.
def tree_predictions(bundle, features):
    selected = features[:, bundle["columns"]]
    result = np.full(len(features), float(bundle["baseline"].ravel()[0]))
    for stage in range(int(bundle["iterations"])):
        nodes = bundle[f"nodes_{stage}"]
        for row, values in enumerate(selected):
            position = 0
            while not nodes[position]["is_leaf"]:
                node = nodes[position]
                value = values[int(node["feature_idx"])]
                left = (
                    bool(node["missing_go_to_left"])
                    if np.isnan(value)
                    else value <= node["num_threshold"]
                )
                position = int(node["left"] if left else node["right"])
            result[row] += nodes[position]["value"]
    return result


# Prove safe numeric snapshots reproduce the real fixed estimator's signed outputs.
def test_numeric_model_snapshot_preserves_real_predictions(tmp_path):
    rng = np.random.default_rng(4)
    features = rng.normal(size=(1000, 13)).astype(np.float32)
    features[::11, 5] = np.nan
    target = 0.02 * features[:, 2] - 0.007 * features[:, 8]
    columns = np.array([2, 5, 8])
    estimator = HistGradientBoostingRegressor(
        max_iter=64,
        max_leaf_nodes=15,
        learning_rate=0.05,
        min_samples_leaf=200,
        early_stopping=False,
        random_state=0,
    ).fit(features[:, columns], target)
    head = SimpleNamespace(estimator=estimator, columns=columns)
    records = cli.save_models(tmp_path, {"2026-09": head})
    path = tmp_path / records["2026-09"]["file"]
    assert records["2026-09"]["sha256"] == cli.saved.digest(path)
    with np.load(path, allow_pickle=False) as bundle:
        assert len(bundle.files) == 196
        np.testing.assert_array_equal(bundle["columns"], columns)
        np.testing.assert_allclose(
            tree_predictions(bundle, features),
            estimator.predict(features[:, columns]),
            rtol=1e-12,
            atol=1e-14,
        )
    assert estimator.predict(features[:, columns]).min() < 0
    with pytest.raises(ValueError, match="Fresh model"):
        cli.save_models(tmp_path, {"2026-09": head})


# Preserve unavailable warmup receipts without attempting to serialize no estimator.
def test_unavailable_month_has_no_model_artifact(tmp_path):
    records = cli.save_models(tmp_path, {"2020-02": None})
    assert records == {}
    assert not list(tmp_path.iterdir())


# Reject a missing fitted model instead of hiding it among legitimate warmup months.
def test_unavailable_model_requires_its_explicit_monthly_receipt():
    models = {"2020-02": None}
    manifest = {
        "months": [{"month": "2020-02", "status": "insufficient_training_days"}]
    }
    cli.validate_models(models, manifest)
    manifest["months"][0]["status"] = "fitted"
    with pytest.raises(ValueError, match="explicit unavailable receipt"):
        cli.validate_models(models, manifest)
    with pytest.raises(ValueError, match="ordered model receipt"):
        cli.validate_models({}, manifest)


# Stop substituted bytes and path traversal before any artifact parsing occurs.
def test_saved_artifact_boundary_refuses_substitution(tmp_path):
    path = tmp_path / "saved.json"
    path.write_text('{"ok":true}')
    expected = cli.saved.digest(path)
    anchors = {}
    assert cli.checked_file(tmp_path, path.name, expected, anchors) == path
    assert anchors == {path: expected}
    path.write_text('{"ok":false}')
    with pytest.raises(ValueError, match="Saved bytes differ"):
        cli.checked_file(tmp_path, path.name, expected, anchors)
    with pytest.raises(ValueError, match="path boundary"):
        cli.checked_file(tmp_path, "../outside.json", expected, anchors)


# Verify one synthetic saved-control grid with its original score and proof linkage.
def test_control_loader_authenticates_every_saved_book(tmp_path, monkeypatch):
    dates = np.array(["2020-03-02", "2020-03-03"], dtype="datetime64[D]")
    panel = SimpleNamespace(dates=dates, tickers=("A", "SPY", "QQQ"))
    np.savez(
        tmp_path / "bridge.npz",
        dates=dates,
        symbols=np.array(panel.tickers),
        calibrated=np.zeros((2, 3)),
        past_mean=np.zeros((2, 3)),
        labels=np.full((2, 3), np.nan),
        label_end_dates=np.full(2, np.datetime64("NaT", "D")),
        score_mask=np.zeros((2, 3), bool),
    )
    (tmp_path / "bridge-fit.json").write_text('{}')
    proof = {
        "ok": True,
        "source_revision": cli.CONTROL_SOURCE,
        "book_artifacts": {},
    }
    report = {
        "adoption_eligible": False,
        "identity": {
            "source": {"revision": cli.CONTROL_SOURCE},
            "common_anchor": "2020-03-02",
        },
        "fit_file": "bridge-fit.json",
        "fit_sha256": cli.saved.digest(tmp_path / "bridge-fit.json"),
        "bridge_file": "bridge.npz",
        "bridge_sha256": cli.saved.digest(tmp_path / "bridge.npz"),
        "rows": [],
    }
    for cost in cli.saved.COSTS:
        records = {}
        for name in cli.CONTROL_NAMES:
            key = f"{name}-{cost}"
            np.savez(tmp_path / f"{key}.npz", dates=dates, nav=np.ones(2))
            score = {"counts": {"plans": 1}, "windows": []}
            (tmp_path / f"{key}.json").write_text(
                json.dumps({"account": {"cash": [1, 1]}, "score": score})
            )
            records[name] = {
                "arrays_file": f"{key}.npz",
                "arrays_sha256": cli.saved.digest(tmp_path / f"{key}.npz"),
                "receipt_file": f"{key}.json",
                "receipt_sha256": cli.saved.digest(tmp_path / f"{key}.json"),
                "score": score,
            }
            proof["book_artifacts"][key] = {
                "arrays": records[name]["arrays_sha256"],
                "receipt": records[name]["receipt_sha256"],
            }
        report["rows"].append({"cost_bps": cost, "accounts": records})
    report_path, proof_path = tmp_path / "evaluation.json", tmp_path / "proof.json"
    report_path.write_text(json.dumps(report))
    proof["report_sha256"] = cli.saved.digest(report_path)
    proof_path.write_text(json.dumps(proof))
    monkeypatch.setattr(cli, "BRIDGE_REPORT", cli.saved.digest(report_path))
    monkeypatch.setattr(cli, "BRIDGE_PROOF", cli.saved.digest(proof_path))
    args = SimpleNamespace(bridge_study=tmp_path, bridge_proof=proof_path)
    anchors = {}
    bridge, books, records = cli.load_controls(args, panel, anchors)
    assert len(anchors) == 34
    assert set(books) == {0, 10, 25}
    assert set(records[10]) == set(cli.CONTROL_NAMES)
    np.testing.assert_array_equal(bridge.score_mask, np.zeros((2, 3), bool))
    np.testing.assert_array_equal(books[10]["equal"]["nav"], np.ones(2))
    (tmp_path / "equal-10.npz").write_bytes(b"substituted")
    with pytest.raises(ValueError, match="Saved bytes differ"):
        cli.load_controls(args, panel, {})


# Exercise real funded books while replacing only the expensive head and old inputs.
def test_direct_cli_creates_only_three_new_funded_books(tmp_path, monkeypatch):
    import backend.market
    from backend.market import daily_bridge_replay, direct_daily_arithmetic

    dates = np.arange(
        np.datetime64("2019-01-02"), np.datetime64("2020-03-10")
    )
    dates = dates[np.is_busday(dates)]
    first = int(np.flatnonzero(dates == np.datetime64("2020-03-02"))[0])
    day = np.arange(len(dates))[:, None]
    prices = np.exp(0.0002 * day + 0.05 * np.sin(day / 13)) * np.array(
        [10, 20, 30, 40]
    )
    panel = SimpleNamespace(
        dates=dates,
        tickers=("A", "B", "SPY", "QQQ"),
        open=prices.copy(),
        close=prices.copy(),
        adj_close=prices.copy(),
    )
    grades, eligible = np.full(prices.shape, 2), np.ones(prices.shape, bool)
    grades[first + 1 :, 0] = 1
    forecasts = np.full(prices.shape, 0.02)
    forecasts[first + 2 :, 1] = -0.02
    before = prices.copy()
    controls = {
        cost: {
            name: daily_bridge_replay.benchmark_account(
                panel,
                ticker="SPY" if name != "QQQ" else "QQQ",
                cost_bps=cost,
                first=first,
            )
            for name in cli.CONTROL_NAMES
        }
        for cost in cli.saved.COSTS
    }
    original_calls = []
    real_run = daily_bridge_replay.run_account

    # Count actual new ledger runs while preserving its cash and ownership behavior.
    def record_run(*args, **kwargs):
        original_calls.append(kwargs["cost_bps"])
        return real_run(*args, **kwargs)

    monkeypatch.setattr(daily_bridge_replay, "run_account", record_run)
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    (input_dir / "fit.json").write_text(json.dumps({"features": list(range(13))}))
    np.savez(
        input_dir / "prepared.npz",
        dates=dates,
        X=np.zeros((*prices.shape, 13), dtype=np.float32),
        valid=np.ones(prices.shape, bool),
    )
    fits = []

    # Supply one deterministic head so the test measures the actual CLI/account path.
    def fit_once(prepared, bridge):
        fits.append(prepared)
        return SimpleNamespace(
            forecasts=forecasts.copy(), manifest={"months": []}, models={}
        )

    stub = SimpleNamespace(
        walk_forward=fit_once, model_identity=direct_daily_arithmetic.model_identity
    )
    monkeypatch.setitem(sys.modules, "backend.market.direct_daily_arithmetic", stub)
    monkeypatch.setattr(backend.market, "direct_daily_arithmetic", stub, raising=False)
    bridge = SimpleNamespace(score_mask=np.ones(prices.shape, bool))

    # Restore supplied controls without invoking any previous account producer.
    def supplied_controls(*args):
        return bridge, controls, {cost: {} for cost in cli.saved.COSTS}

    monkeypatch.setattr(cli, "load_controls", supplied_controls)
    source = {"revision": "synthetic-exact-source"}

    # Keep source authentication stable for this isolated integration fixture.
    def supplied_source(*args):
        return source

    monkeypatch.setattr(cli.saved, "source_identity", supplied_source)
    args = SimpleNamespace(
        output=tmp_path / "results",
        daily=input_dir,
        daily_dir=input_dir / "bars",
        snapshot=input_dir / "portfolio.npz",
        bridge_study=input_dir / "old-study",
        bridge_proof=input_dir / "proof.json",
    )
    original = {"relative": forecasts.copy(), "spy": np.zeros(len(dates))}
    report = cli.evaluate(
        args, (panel, grades, eligible, original, {}, {}), source
    )
    assert len(fits) == 1
    assert original_calls == [0, 10, 25]
    assert report["identity"]["new_stock_accounts"] == 3
    assert report["identity"]["reused_control_accounts"] == 15
    assert report["adoption_eligible"] is False
    assert not list(args.output.glob("equal-*.npz"))
    for row in report["rows"]:
        receipt = json.loads(
            (args.output / row["direct"]["receipt_file"]).read_bytes()
        )
        intents = receipt["account"]["intent_trace"]
        assert any(intent["side"] == "buy" for intent in intents)
        assert any(intent["side"] == "sell" for intent in intents)
        assert any(
            intent["symbol"] == "B"
            and intent["side"] == "sell"
            and intent["decision_session"] == str(dates[first + 2])
            for intent in intents
        )
        assert grades[first + 2, 1] == 2
        assert eligible[first + 2, 1]
        with np.load(args.output / row["direct"]["arrays_file"]) as numeric:
            assert (numeric["cash"] >= 0).all()
            assert (numeric["shares"] >= 0).all()
    np.testing.assert_array_equal(prices, before)
    with pytest.raises(ValueError, match="Fresh private output"):
        cli.evaluate(args, (panel, grades, eligible, original, {}, {}), source)
