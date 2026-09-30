import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

parser = argparse.ArgumentParser(description="Read-only independent daily-study audit")
parser.add_argument("results_dir", type=Path)
parser.add_argument("cubes_dir", type=Path)
args = parser.parse_args()
root = args.results_dir
report = json.loads((root / "results.json").read_text())
artifact = root / "predictions.npz"
assert hashlib.sha256(artifact.read_bytes()).hexdigest() == report["predictions_sha256"]
models = ("trailing20", "har_ridge", "lightgbm", "weekday_volume")
targets = ("rth_variance_1", "gap_augmented_variance_5", "dollar_volume_1")
archive = np.load(artifact, allow_pickle=False)
p = {k: archive[k] for k in ("dates", "tickers", "y", "point", "raw_log", "regime")}
max_difference = 0.0
for row in report["scores"]:
    k = targets.index(row["target"])
    m = models.index(row["model"])
    low, high = (
        ("2018-01-01", "2024-01-01")
        if row["window"] == "2018-2023"
        else ("2024-01-01", "2027-01-01")
    )
    ok = (p["dates"] >= np.datetime64(low)) & (p["dates"] < np.datetime64(high))
    if row["regime"] != -1:
        ok &= p["regime"] == row["regime"]
    ok &= np.isfinite(p["y"][:, k]) & (p["y"][:, k] > 0)
    ok &= np.isfinite(p["point"][:, k]).all(axis=1) & (p["point"][:, k] > 0).all(axis=1)
    assert ok.sum() == row["rows"]
    truth = p["y"][ok, k]
    forecast = p["point"][ok, k, m]
    error = p["raw_log"][ok, k, m] - np.log(truth)
    primary = (
        np.abs(error).mean()
        if k == 2
        else np.mean(truth / forecast - np.log(truth / forecast) - 1)
    )
    for a, b in ((primary, row["primary_loss"]), ((error**2).mean(), row["log_mse"])):
        max_difference = max(max_difference, abs(a - b))
        assert abs(a - b) < 1e-12
for fold in report["fits"]:
    for t in fold["targets"].values():
        assert t["train_label_end_max"] < fold["validation_start"]
        assert t["validation_label_end_max"] < fold["test_start"]
# Recompute labels from raw cube prices/volumes, not study helpers.
rng = np.random.default_rng(92)
checked = 0
missing = 0
largest = 0.0
cache = {}
for i in rng.choice(len(p["dates"]), size=2000, replace=False):
    ticker = str(p["tickers"][i])
    day = p["dates"][i]
    if ticker not in cache:
        c = np.load(args.cubes_dir / (ticker + ".npz"), allow_pickle=False)
        cache[ticker] = {
            k: c[k]
            for k in ("dates", "open", "high", "low", "close", "volume", "prior_close")
        }
    c = cache[ticker]
    for k, h in enumerate((1, 5, 1)):
        # Derive expected date from row date and target endpoint session index.
        # Reviewed closures are data, not the label-building implementation.
        from backend.market.calendar import reviewed_sessions

        days = np.busday_offset(
            day, np.arange(1, h + 1), busdaycal=reviewed_sessions()[1]
        )
        positions = np.searchsorted(c["dates"], days)
        if (positions >= len(c["dates"])).any() or not np.array_equal(
            c["dates"][positions], days
        ):
            assert np.isnan(p["y"][i, k])
            missing += 1
            continue
        op = c["open"][positions]
        hi = c["high"][positions]
        lo = c["low"][positions]
        cl = c["close"][positions]
        vol = c["volume"][positions]
        prev = c["prior_close"][positions]
        valid = (
            np.isfinite(op)
            & np.isfinite(hi)
            & np.isfinite(lo)
            & np.isfinite(cl)
            & np.isfinite(vol)
        ).all()
        valid = (
            valid
            and (op > 0).all()
            and (hi > 0).all()
            and (lo > 0).all()
            and (cl > 0).all()
        )
        valid = (
            valid
            and (vol >= 0).all()
            and (vol.sum(axis=1) > 0).all()
            and (hi >= np.maximum(op, cl)).all()
            and (lo <= np.minimum(op, cl)).all()
        )
        valid = valid and np.isfinite(prev).all() and (prev > 0).all()
        if not valid:
            assert np.isnan(p["y"][i, k])
            missing += 1
            continue
        r = np.log(cl / np.column_stack((op[:, 0], cl[:, :-1])))
        value = (r * r).sum(axis=1)
        if k == 1:
            value += np.log(op[:, 0] / prev) ** 2
        if k == 2:
            value = (((hi + lo + cl) / 3) * vol).sum(axis=1)
        actual = max(float(value.mean()), 1e-12)
        assert np.isclose(actual, p["y"][i, k], rtol=1e-12, atol=1e-12)
        largest = max(largest, abs(actual - p["y"][i, k]))
        checked += 1
print(
    json.dumps(
        {
            "score_rows_checked": len(report["scores"]),
            "maximum_score_difference": max_difference,
            "fold_boundaries_checked": len(report["fits"]) * 3,
            "sampled_label_cells": checked,
            "missing_label_cells_checked": missing,
            "maximum_label_difference": largest,
            "prediction_sha256": report["predictions_sha256"],
        }
    )
)
