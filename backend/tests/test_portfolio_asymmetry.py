"""Portfolio loss/gain research keeps causal features and real funded labels."""

import copy
import gzip
import json
import sys
from dataclasses import replace

import numpy as np
import pytest

from backend.cli import market_laggard_tilt as tilt
from backend.cli import market_portfolio_asymmetry as cli
from backend.market import filing_expectations as shared
from backend.market import portfolio_asymmetry as study
from backend.tests.test_market_pit_scorecard import _report


# Check features against a funded simulator account and independent journal replay.
def test_dataset_matches_funded_book_and_future_changes(tmp_path):
    report = _report()
    panel = report.panel
    mask = np.ones_like(panel.close, dtype=bool)
    mask[:, -1] = False
    bundle = {
        "report": report,
        "membership": mask,
        "spy": panel.adj_close[:, -1],
        "qqq": panel.adj_close[:, -2],
    }
    grid = np.full(panel.close.shape, np.nan)
    tilt.stock_account(bundle, grid, "v4", 10, 25, tmp_path, "test")
    with gzip.open(tmp_path / "journal-v4-10-25.json.gz", "rb") as handle:
        snapshot = json.load(handle)
    rows = study.dataset(bundle, snapshot)
    marks = {
        row["session_index"]: row for row in snapshot["events"] if row["type"] == "mark"
    }
    row = next(r for r in rows if r["session_index"] == 250)
    assert len(row["x"]) == 16
    assert row["return5"] == pytest.approx(marks[255]["nav"] / marks[250]["nav"] - 1)
    assert row["target"][0] - row["target"][1] == row["return5"]
    assert sum(r["endpoint"] is None for r in rows) == 5
    daily = np.array(
        [marks[t]["nav"] / marks[t - 1]["nav"] - 1 for t in range(231, 251)]
    )
    assert row["x"][10] == pytest.approx(
        np.minimum(daily, 0).dot(np.minimum(daily, 0)) / 20
    )
    fields = {}
    for name in ("open", "high", "low", "close", "adj_close"):
        fields[name] = getattr(panel, name).copy()
        fields[name][251:] *= 0.2
    changed = replace(panel, **fields)
    other = {
        **bundle,
        "report": replace(report, panel=changed),
        "spy": changed.adj_close[:, -1],
        "qqq": changed.adj_close[:, -2],
    }
    destination = tmp_path / "changed"
    destination.mkdir()
    tilt.stock_account(other, grid, "v4", 10, 25, destination, "test")
    with gzip.open(destination / "journal-v4-10-25.json.gz", "rb") as handle:
        after = study.dataset(other, json.load(handle))
    for before, new in zip(rows, after, strict=True):
        if before["session_index"] <= 250:
            np.testing.assert_array_equal(before["x"], new["x"])
    assert (
        row["return5"] != next(r for r in after if r["session_index"] == 250)["return5"]
    )


# Synthetic dated samples contain a learnable signal, without a market-data dependency.
def training_rows():
    rng = np.random.default_rng(7)
    dates = np.busday_offset("2015-01-02", np.arange(2900))
    x = rng.normal(size=(len(dates), 16))
    returns = 0.02 * x[:, 0] + rng.normal(0, 0.002, len(dates))
    return [
        {
            "date": str(day),
            "endpoint": str(dates[i + 5]) if i + 5 < len(dates) else None,
            "x": x[i].tolist(),
            "return5": value,
            "target": [max(value, 0), max(-value, 0)]
            if i + 5 < len(dates)
            else [None, None],
        }
        for i, (day, value) in enumerate(zip(dates, returns, strict=True))
    ]


# Labels crossing either annual boundary and the unknown tail never enter a fit.
def test_purge_and_missing_endpoints():
    rows = training_rows()
    split = study.masks(rows, 2023)
    for key, cutoff in (
        ("fit", "2023-01-01"),
        ("inner", "2022-01-01"),
        ("validation", "2023-01-01"),
    ):
        assert all(rows[i]["endpoint"] < cutoff for i in np.flatnonzero(split[key]))
        assert not split[key][-5:].any()
    assert all(
        rows[i]["date"] >= "2022-01-01" for i in np.flatnonzero(split["validation"])
    )


# Real annual fits reload identically; later labels cannot alter earlier predictions.
def test_actual_models_reload_and_future_label_invariance():
    import lightgbm as lgb

    rows = training_rows()
    predictions, fits = study.walk_forward(rows)
    assert np.isfinite(predictions["lightgbm"][-5:]).all()
    for receipt in fits:
        if receipt["status"] != "all_scored":
            continue
        test = study.masks(rows, receipt["year"])["test"]
        x = np.asarray([r["x"] for r in rows])[test]
        features = shared.transform(x, np.array(receipt["preprocessing"]))
        for head, saved in enumerate(receipt["heads"]):
            restored = lgb.Booster(model_str=saved["model"])
            np.testing.assert_allclose(
                np.maximum(restored.predict(features), 0),
                predictions["lightgbm"][test, head],
                atol=1e-14,
            )
    altered = copy.deepcopy(rows)
    for row in altered:
        if row["date"] >= "2024-01-01" and row["endpoint"] is not None:
            row["target"] = [0.5, 0.0]
    changed, _ = study.walk_forward(altered)
    early = np.array([r["date"] < "2024-01-01" for r in rows])
    for name in predictions:
        np.testing.assert_array_equal(predictions[name][early], changed[name][early])


# Perfect sign/magnitude forecasts pass, while symmetric magnitude accuracy cannot.
def test_summary_requires_net_skill_and_rejects_missing_models():
    rows = training_rows()
    truth = np.array([r["target"] for r in rows], dtype=float)
    predictions = {
        "lightgbm": truth.copy(),
        "mean": np.full_like(truth, 0.01),
        "ridge": truth * 0.5,
    }
    result = study.summarize(rows, predictions)
    assert result["verdict"] == "RESEARCH_PROMISING_NOT_PROMOTION"
    assert result["immature_rows"] == 5
    predictions["lightgbm"] = np.full_like(truth, 0.01)
    assert study.summarize(rows, predictions)["verdict"] == "DO_NOT_ADVANCE"
    predictions["lightgbm"][:] = np.nan
    result = study.summarize(rows, predictions)
    assert result["verdict"] == "DO_NOT_ADVANCE"
    assert result["live_promotion_authorized"] is False


# The CLI writes complete artifacts, refuses reuse and rejects a different baseline.
def test_cli_artifacts_and_account_binding(tmp_path, monkeypatch):
    report = _report()
    mask = np.ones_like(report.panel.close, dtype=bool)
    mask[:, -1] = False
    bundle = {
        "report": report,
        "membership": mask,
        "spy": report.panel.adj_close[:, -1],
        "qqq": report.panel.adj_close[:, -2],
    }
    grid = np.full(report.panel.close.shape, np.nan)
    tilt.stock_account(bundle, grid, "v4", 10, 25, tmp_path, cli.BASELINE_REVISION)
    journal = tmp_path / "journal-v4-10-25.json.gz"
    snapshot, digest = cli.load_baseline(journal)
    assert len(digest) == 64
    out = tmp_path / "output"
    monkeypatch.setattr(cli, "load_cache", lambda path: bundle)
    monkeypatch.setattr(
        cli.subprocess,
        "check_output",
        lambda args, **kwargs: "" if "status" in args else "test-revision",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "test",
            "--trusted-cache",
            "synthetic",
            "--journal",
            str(journal),
            "--out",
            str(out),
        ],
    )
    cli.main()
    result = json.loads((out / "summary.json").read_text())
    assert result["verdict"] == "DO_NOT_ADVANCE"
    assert result["baseline_journal_sha256_uncompressed"] == digest
    assert result["immature_rows"] == 5
    assert len(result["artifacts"]) == 3
    with pytest.raises(FileExistsError):
        cli.main()
    snapshot["manifest"]["cost_bps"] = 10
    wrong = tmp_path / "wrong.json.gz"
    with gzip.open(wrong, "wb") as handle:
        handle.write(json.dumps(snapshot).encode())
    with pytest.raises(ValueError, match="identity mismatch"):
        cli.load_baseline(wrong)
