"""Authenticate old books and exercise the six new funded account paths."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_direct_feature_arithmetic as cli


# Create a hash-linked synthetic saved-band grid without running its producer.
def saved_band(tmp_path, monkeypatch):
    records = {cost: {"direct": {"original": cost}} for cost in cli.saved.COSTS}
    controls = {cost: {} for cost in cli.saved.COSTS}
    proof = {
        "ok": True,
        "source_revision": cli.BAND_SOURCE,
        "new_stock_accounts": 3,
        "reused_control_accounts": 18,
        "book_artifacts": {},
    }
    report = {
        "status": "complete_error_band_daily_component_not_adopted",
        "adoption_eligible": False,
        "controls_scores_are_original": True,
        "identity": {
            "source": {"revision": cli.BAND_SOURCE},
            "common_anchor": "2020-03-02",
        },
        "rows": [],
    }
    for cost in cli.saved.COSTS:
        key = f"error-band-{cost}"
        np.savez(tmp_path / (key + ".npz"), nav=np.ones(2))
        score = {"original_gain": cost}
        cli.saved.write_json(
            tmp_path / (key + ".json"), {"account": {"cash": [1, 1]}, "score": score}
        )
        record = {
            "arrays_file": key + ".npz",
            "receipt_file": key + ".json",
            "arrays_sha256": cli.saved.digest(tmp_path / (key + ".npz")),
            "receipt_sha256": cli.saved.digest(tmp_path / (key + ".json")),
            "score": score,
        }
        proof["book_artifacts"][key] = {
            "arrays": record["arrays_sha256"],
            "receipt": record["receipt_sha256"],
        }
        report["rows"].append(
            {
                "cost_bps": cost,
                "error_band": record,
                "reused_controls": records[cost].copy(),
            }
        )
    cli.saved.write_json(tmp_path / "evaluation.json", report)
    proof["report_sha256"] = cli.saved.digest(tmp_path / "evaluation.json")
    cli.saved.write_json(tmp_path / "proof.json", proof)
    monkeypatch.setattr(cli, "BAND_REPORT", proof["report_sha256"])
    monkeypatch.setattr(cli, "BAND_PROOF", cli.saved.digest(tmp_path / "proof.json"))
    return (
        SimpleNamespace(band_study=tmp_path, band_proof=tmp_path / "proof.json"),
        controls,
        records,
    )


# Preserve all three authentic saved scores and append only their saved states.
def test_saved_band_controls_are_original(tmp_path, monkeypatch):
    args, controls, records = saved_band(tmp_path, monkeypatch)
    anchors = {}
    cli.load_band(args, anchors, controls, records)
    assert len(anchors) == 8
    assert all(
        records[cost]["old_band"]["score"] == {"original_gain": cost}
        for cost in cli.saved.COSTS
    )
    assert all(controls[cost]["old_band"]["cash"] == [1, 1] for cost in cli.saved.COSTS)


# Changed original bytes cannot enter a supposedly authenticated control comparison.
@pytest.mark.parametrize(
    "file",
    [
        "proof.json",
        "evaluation.json",
        "error-band-0.npz",
        "error-band-10.json",
        "error-band-25.npz",
    ],
)
def test_changed_saved_band_is_rejected(tmp_path, monkeypatch, file):
    args, controls, records = saved_band(tmp_path, monkeypatch)
    (tmp_path / file).write_bytes(b"changed")
    with pytest.raises(ValueError, match="proof bytes|Saved bytes differ"):
        cli.load_band(args, {}, controls, records)


# One fit supplies both default or held-B arms through actual funded ledgers.
@pytest.mark.parametrize("hold_b", [False, True])
def test_cli_runs_six_actual_funded_books_only(tmp_path, monkeypatch, hold_b):
    from backend.market import (
        daily_bridge_replay,
        direct_daily_arithmetic,
        direct_feature_arithmetic,
    )

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
    if hold_b:
        grades[first + 1 :, 1] = 1
    radii = np.zeros(prices.shape)
    radii[:, 0] = 0.1
    old_books = {
        cost: {
            name: daily_bridge_replay.benchmark_account(
                panel,
                ticker="QQQ" if name == "QQQ" else "SPY",
                cost_bps=cost,
                first=first,
            )
            for name in (
                "direct",
                "old_band",
                "calibrated",
                "mean",
                "equal",
                "SPY",
                "QQQ",
            )
            + (("feature_raw", "feature_band") if hold_b else ())
        }
        for cost in cli.saved.COSTS
    }
    calls, fits, calibrations = [], [], []
    actual_run = daily_bridge_replay.run_account

    # Count new books while retaining the real cash, fee and covered-share path.
    def run(*args, **kwargs):
        assert kwargs.get("hold_b", False) is hold_b
        calls.append((kwargs["cost_bps"], kwargs["radii"] is not None))
        return actual_run(*args, **kwargs)

    # Restore fixed control state without fitting or replaying an old strategy.
    def controls(*args):
        return SimpleNamespace(), old_books, {cost: {} for cost in cli.saved.COSTS}

    # Replace only artifact restoration that separate corruption cases exercise.
    def restore(*args):
        return None

    # Supply signed means once so this test measures the actual account path.
    def fit(prepared, bridge, observed_grades, observed_eligible, **kwargs):
        assert kwargs == ({"hold_b": True} if hold_b else {})
        fits.append(prepared)
        np.testing.assert_array_equal(observed_grades, grades)
        np.testing.assert_array_equal(observed_eligible, eligible)
        assert prepared["feature_names"] == list(direct_daily_arithmetic.FEATURE_NAMES)
        return SimpleNamespace(
            forecasts=means,
            score_mask=np.ones(prices.shape, bool),
            models={},
            manifest={"months": []},
        )

    # Supply uncertainty separately from actual execution costs and funding.
    def calibration(*args):
        calibrations.append(args)
        return SimpleNamespace(radii=radii, manifest={"fixture": True})

    # Keep exact synthetic source identity stable for orchestration acceptance.
    def source(*args):
        return {"revision": "synthetic"}

    monkeypatch.setattr(daily_bridge_replay, "run_account", run)
    monkeypatch.setattr(cli.old.direct, "load_controls", controls)
    monkeypatch.setattr(cli.old, "load_direct", restore)
    monkeypatch.setattr(cli, "load_band", restore)
    monkeypatch.setattr(cli, "load_feature", restore)
    monkeypatch.setattr(direct_feature_arithmetic, "walk_forward", fit)
    monkeypatch.setattr(direct_feature_arithmetic, "calibrate", calibration)
    monkeypatch.setattr(cli.saved, "source_identity", source)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    np.savez(
        inputs / "prepared.npz",
        dates=dates,
        X=np.zeros((*prices.shape, 13), np.float32),
        valid=np.ones(prices.shape, bool),
    )
    cli.saved.write_json(
        inputs / "fit.json",
        {"identity": {"features": list(direct_daily_arithmetic.FEATURE_NAMES)}},
    )
    args = SimpleNamespace(
        output=tmp_path / "results",
        daily=inputs,
        daily_dir=inputs / "bars",
        snapshot=inputs / "snapshot.npz",
        bridge_study=inputs / "bridge",
        bridge_proof=inputs / "bridge-proof.json",
        direct_study=inputs / "direct",
        direct_proof=inputs / "direct-proof.json",
        band_study=inputs / "band",
        band_proof=inputs / "band-proof.json",
        feature_study=inputs / "feature",
        feature_proof=inputs / "feature-proof.json",
        hold_b=hold_b,
    )
    original = {"relative": np.zeros(prices.shape), "spy": np.zeros(len(dates))}
    input_hashes = {
        path: cli.saved.digest(path) for path in inputs.iterdir() if path.is_file()
    }
    report = cli.evaluate(args, (panel, grades, eligible, original, {}, {}), source())
    assert len(fits) == len(calibrations) == 1
    assert calls == [(cost, band) for cost in cli.saved.COSTS for band in (False, True)]
    assert report["identity"]["new_stock_accounts"] == 6
    assert report["identity"]["reused_control_accounts"] == (27 if hold_b else 21)
    assert all(
        set(row["accounts"])
        == ({"held_raw", "held_band"} if hold_b else {"feature_raw", "feature_band"})
        for row in report["rows"]
    )
    if hold_b:
        assert report["identity"]["policy"] == "learned-held-exits/1-research"
        assert report["identity"]["hold_b"] is True
        assert report["identity"]["buys"] == "A/A+ only"
    assert not list(args.output.glob("model-*.npz"))
    assert_account_actions(args, report)
    assert all(
        cli.saved.digest(path) == expected for path, expected in input_hashes.items()
    )
    np.testing.assert_array_equal(prices, panel.adj_close)
    with pytest.raises(ValueError, match="Fresh private output"):
        cli.evaluate(args, (panel, grades, eligible, original, {}, {}), source())


# Check recorded decisions and actual cash/share/fee state in each new account.
def assert_account_actions(args, report):
    for row in report["rows"]:
        for name, record in row["accounts"].items():
            receipt = json.loads((args.output / record["receipt_file"]).read_bytes())
            intents = receipt["account"]["intent_trace"]
            assert any(
                item["symbol"] == "B" and item["side"] == "buy" for item in intents
            )
            assert any(
                item["symbol"] == "B" and item["side"] == "sell" for item in intents
            )
            if name in ("feature_band", "held_band"):
                assert not any(
                    item["symbol"] == "A" and item["side"] == "buy" for item in intents
                )
            if name in ("held_raw", "held_band"):
                assert receipt["account"]["hold_b"] is True
                first_buy = next(
                    item
                    for item in intents
                    if item["symbol"] == "B" and item["side"] == "buy"
                )
                assert not any(
                    item["symbol"] == "B"
                    and item["side"] == "buy"
                    and item["decision_session"] > first_buy["decision_session"]
                    for item in intents
                )
            with np.load(
                args.output / record["arrays_file"], allow_pickle=False
            ) as numeric:
                assert (numeric["cash"] >= 0).all()
                assert (numeric["shares"] >= 0).all()
                if row["cost_bps"] == 0:
                    assert numeric["fees"].sum() == 0


# Construct six hash-linked saved feature books and all 21 original control records.
def saved_feature(tmp_path, monkeypatch, *, fault=None):
    names = ("direct", "old_band", "calibrated", "mean", "equal", "SPY", "QQQ")
    records = {
        cost: {name: {"original": f"{name}-{cost}"} for name in names}
        for cost in cli.saved.COSTS
    }
    controls = {
        cost: {name: {"original": f"{name}-{cost}"} for name in names}
        for cost in cli.saved.COSTS
    }
    proof = {
        "ok": True,
        "source_revision": cli.FEATURE_SOURCE,
        "new_stock_accounts": 6,
        "reused_control_accounts": 21,
        "book_artifacts": {},
    }
    report = {
        "status": "complete_independent_feature_component_not_adopted",
        "adoption_eligible": False,
        "controls_scores_are_original": True,
        "identity": {
            "source": {"revision": cli.FEATURE_SOURCE},
            "common_anchor": "2020-03-02",
        },
        "rows": [],
    }
    for cost in cli.saved.COSTS:
        accounts = {}
        for name in ("feature_raw", "feature_band"):
            key = f"{name}-{cost}"
            np.savez(tmp_path / (key + ".npz"), nav=np.ones(2))
            score = {"original_gain": f"{key}-score"}
            account = {"cash": [1, 1]}
            if fault == "overlap" and key == "feature_raw-0":
                account["nav"] = [1, 1]
            claimed = (
                {"different": True}
                if fault == "score" and key == "feature_raw-0"
                else score
            )
            cli.saved.write_json(
                tmp_path / (key + ".json"), {"account": account, "score": claimed}
            )
            record = {
                "arrays_file": key + ".npz",
                "receipt_file": key + ".json",
                "arrays_sha256": cli.saved.digest(tmp_path / (key + ".npz")),
                "receipt_sha256": cli.saved.digest(tmp_path / (key + ".json")),
                "score": score,
            }
            proof["book_artifacts"][key] = {
                "arrays": record["arrays_sha256"],
                "receipt": record["receipt_sha256"],
            }
            accounts[name] = record
        report["rows"].append(
            {
                "cost_bps": cost,
                "accounts": accounts,
                "reused_controls": records[cost].copy(),
            }
        )
    if fault == "source":
        report["identity"]["source"]["revision"] = "another-source"
    elif fault == "anchor":
        report["identity"]["common_anchor"] = "2020-03-03"
    elif fault == "controls":
        report["rows"][0]["reused_controls"] = {}
    elif fault == "arms":
        report["rows"][0]["accounts"].pop("feature_band")
    elif fault == "link":
        proof["book_artifacts"]["feature_raw-0"]["arrays"] = "wrong"
    elif fault == "count":
        proof["reused_control_accounts"] = 20
    cli.saved.write_json(tmp_path / "evaluation.json", report)
    proof["report_sha256"] = cli.saved.digest(tmp_path / "evaluation.json")
    cli.saved.write_json(tmp_path / "feature-proof.json", proof)
    monkeypatch.setattr(cli, "FEATURE_REPORT", proof["report_sha256"])
    monkeypatch.setattr(
        cli, "FEATURE_PROOF", cli.saved.digest(tmp_path / "feature-proof.json")
    )
    return (
        SimpleNamespace(
            feature_study=tmp_path, feature_proof=tmp_path / "feature-proof.json"
        ),
        controls,
        records,
    )


# Restore all six original books and append their immutable scores to 21 controls.
def test_saved_feature_appends_exact_twenty_seven_controls(tmp_path, monkeypatch):
    args, controls, records = saved_feature(tmp_path, monkeypatch)
    original = {cost: records[cost].copy() for cost in cli.saved.COSTS}
    anchors = {}
    cli.load_feature(args, anchors, controls, records)
    assert sum(len(row) for row in records.values()) == 27
    assert sum(len(row) for row in controls.values()) == 27
    assert len(anchors) == 14
    for cost in cli.saved.COSTS:
        for name, record in original[cost].items():
            assert records[cost][name] == record
        for name in ("feature_raw", "feature_band"):
            assert records[cost][name]["score"] == {
                "original_gain": f"{name}-{cost}-score"
            }
            assert controls[cost][name]["cash"] == [1, 1]
            np.testing.assert_array_equal(controls[cost][name]["nav"], 1)


# Original byte corruption cannot be hidden behind a healthy saved report status.
@pytest.mark.parametrize(
    "file",
    [
        "feature-proof.json",
        "evaluation.json",
        "feature_raw-0.npz",
        "feature_band-10.json",
        "feature_band-25.npz",
    ],
)
def test_saved_feature_changed_bytes_refused(tmp_path, monkeypatch, file):
    args, controls, records = saved_feature(tmp_path, monkeypatch)
    (tmp_path / file).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Feature proof bytes|Saved bytes differ"):
        cli.load_feature(args, {}, controls, records)


# Authenticated bytes must also describe the exact sources, controls and book states.
@pytest.mark.parametrize(
    "fault",
    ["source", "anchor", "controls", "arms", "link", "count", "score", "overlap"],
)
def test_saved_feature_semantic_corruption_refused(tmp_path, monkeypatch, fault):
    args, controls, records = saved_feature(tmp_path, monkeypatch, fault=fault)
    with pytest.raises(
        ValueError,
        match=(
            "Complete saved|Exact21|Both original|Proof-linked|"
            "completed feature proof|Separated old"
        ),
    ):
        cli.load_feature(args, {}, controls, records)


# Held-B mode requires both original feature artifacts instead of fabricating controls.
@pytest.mark.parametrize("missing", ["feature_study", "feature_proof"])
def test_saved_feature_required_arguments(tmp_path, missing):
    args = SimpleNamespace(
        feature_study=tmp_path, feature_proof=tmp_path / "proof.json"
    )
    setattr(args, missing, None)
    with pytest.raises(ValueError, match="requires.*feature study and proof"):
        cli.load_feature(args, {}, {}, {})
