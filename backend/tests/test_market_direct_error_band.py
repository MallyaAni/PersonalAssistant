"""Authenticate reused direct evidence and exercise new funded books only."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_direct_error_band as cli


# Build a small complete saved artifact grid with exact original proof linkage.
def saved_direct(tmp_path, monkeypatch):
    dates = np.array(["2020-03-02", "2020-03-03"], dtype="datetime64[D]")
    panel = SimpleNamespace(dates=dates, tickers=("A", "SPY", "QQQ"))
    np.savez(
        tmp_path / "direct-forecasts.npz",
        dates=dates,
        symbols=np.asarray(panel.tickers),
        forecasts=np.ones((2, 3)) * 0.01,
        score_mask=np.tile([True, False, False], (2, 1)),
    )
    cli.saved.write_json(
        tmp_path / "direct-fit.json", {"forecast_manifest": {"identity": "fixture"}}
    )
    records = {
        cost: {name: {"saved": f"{name}-{cost}"} for name in cli.direct.CONTROL_NAMES}
        for cost in cli.saved.COSTS
    }
    report = {
        "status": "complete_direct_daily_component_not_adopted",
        "adoption_eligible": False,
        "controls_scores_are_original": True,
        "identity": {
            "source": {"revision": cli.DIRECT_SOURCE},
            "common_anchor": "2020-03-02",
        },
        "forecast_file": "direct-forecasts.npz",
        "forecast_sha256": cli.saved.digest(tmp_path / "direct-forecasts.npz"),
        "fit_file": "direct-fit.json",
        "fit_sha256": cli.saved.digest(tmp_path / "direct-fit.json"),
        "rows": [],
    }
    for cost in cli.saved.COSTS:
        score = {"counts": {"plans": 1}, "windows": []}
        np.savez(tmp_path / f"direct-{cost}.npz", dates=dates, nav=np.ones(2))
        cli.saved.write_json(
            tmp_path / f"direct-{cost}.json",
            {"account": {"cash": [1.0, 1.0]}, "score": score},
        )
        report["rows"].append(
            {
                "cost_bps": cost,
                "reused_controls": records[cost].copy(),
                "direct": {
                    "arrays_file": f"direct-{cost}.npz",
                    "arrays_sha256": cli.saved.digest(tmp_path / f"direct-{cost}.npz"),
                    "receipt_file": f"direct-{cost}.json",
                    "receipt_sha256": cli.saved.digest(
                        tmp_path / f"direct-{cost}.json"
                    ),
                    "score": score,
                },
            }
        )
    report_path, proof_path = tmp_path / "evaluation.json", tmp_path / "proof.json"
    cli.saved.write_json(report_path, report)
    proof = {
        "ok": True,
        "source_revision": cli.DIRECT_SOURCE,
        "report_sha256": cli.saved.digest(report_path),
        "new_stock_accounts": 3,
        "reused_control_accounts": 15,
        "fit_sha256": report["fit_sha256"],
        "forecast_sha256": report["forecast_sha256"],
    }
    cli.saved.write_json(proof_path, proof)
    monkeypatch.setattr(cli, "DIRECT_REPORT", cli.saved.digest(report_path))
    monkeypatch.setattr(cli, "DIRECT_PROOF", cli.saved.digest(proof_path))
    args = SimpleNamespace(direct_study=tmp_path, direct_proof=proof_path)
    controls = {cost: {} for cost in cli.saved.COSTS}
    return args, panel, controls, records, report, proof


# Retain all eighteen original control identities without fitting or account replay.
def test_direct_loader_authenticates_all_three_books(tmp_path, monkeypatch):
    args, panel, controls, records, _, _ = saved_direct(tmp_path, monkeypatch)
    anchors = {}
    numeric, manifest = cli.load_direct(args, panel, anchors, controls, records)
    assert len(anchors) == 10
    assert manifest == {"identity": "fixture"}
    np.testing.assert_array_equal(numeric["dates"], panel.dates)
    assert all(
        set(records[cost]) == {*cli.direct.CONTROL_NAMES, "direct"}
        for cost in cli.saved.COSTS
    )
    assert all(
        controls[cost]["direct"]["cash"] == [1.0, 1.0] for cost in cli.saved.COSTS
    )


# Reject actual changed bytes before parsing supposedly completed direct artifacts.
@pytest.mark.parametrize(
    "name",
    [
        "proof.json",
        "evaluation.json",
        "direct-fit.json",
        "direct-forecasts.npz",
        "direct-10.npz",
        "direct-25.json",
    ],
)
def test_substituted_direct_artifact_is_refused(tmp_path, monkeypatch, name):
    args, panel, controls, records, _, _ = saved_direct(tmp_path, monkeypatch)
    (tmp_path / name).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Direct proof|Saved bytes differ"):
        cli.load_direct(args, panel, {}, controls, records)


# An authenticated report still cannot replace the full cost grid or prior records.
@pytest.mark.parametrize(
    "mutation", ["missing_cost", "changed_control", "wrong_anchor", "path_escape"]
)
def test_report_contract_cannot_hide_old_controls(tmp_path, monkeypatch, mutation):
    args, panel, controls, records, report, proof = saved_direct(tmp_path, monkeypatch)
    if mutation == "missing_cost":
        report["rows"].pop()
    elif mutation == "changed_control":
        report["rows"][0]["reused_controls"]["equal"] = {"saved": "different"}
    elif mutation == "wrong_anchor":
        report["identity"]["common_anchor"] = "2020-03-03"
    else:
        report["forecast_file"] = "../escaped.npz"
    (tmp_path / "evaluation.json").write_text(json.dumps(report))
    proof["report_sha256"] = cli.saved.digest(tmp_path / "evaluation.json")
    args.direct_proof.write_text(json.dumps(proof))
    monkeypatch.setattr(cli, "DIRECT_REPORT", proof["report_sha256"])
    monkeypatch.setattr(cli, "DIRECT_PROOF", cli.saved.digest(args.direct_proof))
    with pytest.raises(ValueError, match="cost grid|control records|path boundary"):
        cli.load_direct(args, panel, {}, controls, records)


# Exercise three actual funded ledgers with controlled means and uncertainty only.
def test_error_band_cli_runs_only_three_new_books(tmp_path, monkeypatch):
    from backend.market import daily_bridge_replay, direct_error_band

    dates = np.arange(np.datetime64("2019-01-02"), np.datetime64("2020-03-10"))
    dates = dates[np.is_busday(dates)]
    first = int(np.flatnonzero(dates == np.datetime64("2020-03-02"))[0])
    day = np.arange(len(dates))[:, None]
    prices = np.exp(0.0002 * day + 0.05 * np.sin(day / 13)) * [10, 20, 30, 40]
    panel = SimpleNamespace(
        dates=dates,
        tickers=("A", "B", "SPY", "QQQ"),
        open=prices.copy(),
        close=prices.copy(),
        adj_close=prices.copy(),
    )
    grades, eligible = np.full(prices.shape, 2), np.ones(prices.shape, bool)
    means = np.full(prices.shape, 0.02)
    means[first + 2 :, 1] = -0.02
    radii = np.zeros(prices.shape)
    radii[:, 0] = 0.1
    original = prices.copy()
    old = {
        cost: {
            name: daily_bridge_replay.benchmark_account(
                panel,
                ticker="QQQ" if name == "QQQ" else "SPY",
                cost_bps=cost,
                first=first,
            )
            for name in (*cli.direct.CONTROL_NAMES, "direct")
        }
        for cost in cli.saved.COSTS
    }
    calls, calibrations = [], []
    real_run = daily_bridge_replay.run_account

    # Count new accounts while exercising their actual funded trade path.
    def new_run(*args, **kwargs):
        calls.append(kwargs["cost_bps"])
        return real_run(*args, **kwargs)

    # Supply only authenticated input restoration at this fixture's boundary.
    def controls(*args):
        return (
            SimpleNamespace(score_mask=np.ones(prices.shape, bool)),
            old,
            {cost: {} for cost in cli.saved.COSTS},
        )

    # Return original prediction bytes without invoking any estimator or old ledger.
    def saved_predictions(*args):
        return {
            "dates": dates,
            "symbols": np.asarray(panel.tickers),
            "forecasts": means,
            "score_mask": np.ones(prices.shape, bool),
        }, {"supplied": True}

    # Isolate calibration statistics here while measuring the actual decision/account.
    def calibration(*args):
        calibrations.append(args)
        return SimpleNamespace(radii=radii, manifest={"fixture": True})

    # Keep exact source identity stable within this synthetic orchestration fixture.
    def source_identity(*args):
        return {"revision": "synthetic-pinned"}

    monkeypatch.setattr(daily_bridge_replay, "run_account", new_run)
    monkeypatch.setattr(cli.direct, "load_controls", controls)
    monkeypatch.setattr(cli, "load_direct", saved_predictions)
    monkeypatch.setattr(direct_error_band, "calibrate", calibration)
    monkeypatch.setattr(cli.saved, "source_identity", source_identity)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    args = SimpleNamespace(
        output=tmp_path / "results",
        daily=inputs,
        daily_dir=inputs / "bars",
        snapshot=inputs / "snapshot.npz",
        bridge_study=inputs / "bridge",
        bridge_proof=inputs / "bridge-proof.json",
        direct_study=inputs / "direct",
        direct_proof=inputs / "direct-proof.json",
    )
    report = cli.evaluate(
        args, (panel, grades, eligible, {}, {}, {}), source_identity()
    )
    assert calls == [0, 10, 25]
    assert len(calibrations) == 1
    assert report["identity"]["new_stock_accounts"] == 3
    assert report["identity"]["reused_control_accounts"] == 18
    assert report["identity"]["radius_is_fee"] is False
    assert not list(args.output.glob("direct-*.npz"))
    assert not list(args.output.glob("model-*.npz"))
    for row in report["rows"]:
        receipt = json.loads(
            (args.output / row["error_band"]["receipt_file"]).read_bytes()
        )
        intents = receipt["account"]["intent_trace"]
        assert not any(
            intent["symbol"] == "A" and intent["side"] == "buy" for intent in intents
        )
        assert any(
            intent["symbol"] == "B" and intent["side"] == "buy" for intent in intents
        )
        assert any(
            intent["symbol"] == "B" and intent["side"] == "sell" for intent in intents
        )
        with np.load(
            args.output / row["error_band"]["arrays_file"], allow_pickle=False
        ) as numeric:
            assert (numeric["cash"] >= 0).all()
            assert (numeric["shares"] >= 0).all()
            if row["cost_bps"] == 0:
                assert numeric["fees"].sum() == 0
    np.testing.assert_array_equal(prices, original)
    with pytest.raises(ValueError, match="Fresh private output"):
        cli.evaluate(args, (panel, grades, eligible, {}, {}, {}), source_identity())
