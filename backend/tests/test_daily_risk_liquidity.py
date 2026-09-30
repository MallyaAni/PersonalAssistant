"""Causal data/fit boundaries and real CPU-model acceptance for the daily study."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from backend.cli import market_daily_risk_liquidity as cli
from backend.market import daily_risk_liquidity as study
from backend.market import liquidity_relevance
from backend.market.calendar import reviewed_sessions
from backend.market.sip_cube import SessionCube


# Make coherent bars with predictable volatility and volume, on reviewed dates.
def cube(ticker: str = "ABC", n: int = 240) -> SessionCube:
    calendar = reviewed_sessions()[1]
    days = np.arange("2018-01-01", "2023-01-01", dtype="datetime64[D]")
    days = days[np.is_busday(days, busdaycal=calendar)][:n]
    t = np.arange(n)
    sigma = 0.0007 + 0.0005 * (1 + np.sin(t / 12))
    r = sigma[:, None] * np.sin(np.arange(26)[None, :] * 2.3 + t[:, None] / 7)
    prior = 100 + t * 0.01
    opening = prior * np.exp(0.004 * np.sin(t / 8))
    close = opening[:, None] * np.exp(np.cumsum(r, axis=1))
    opens = np.column_stack([opening, close[:, :-1]])
    return SessionCube(
        ticker=ticker,
        dates=days,
        open=opens,
        high=np.maximum(opens, close) * 1.0001,
        low=np.minimum(opens, close) * 0.9999,
        close=close,
        volume=np.broadcast_to((10000 * (2 + np.sin(t / 12)))[:, None], (n, 26)).copy(),
        prior_close=prior,
        excluded={},
        auction_open=close[:, -1],
        auction_volume=np.full(n, 1000.0),
    )


# Keep all fixture stocks eligible while the builder excludes context ETFs.
def membership(days: np.ndarray, names: tuple[str, ...]) -> np.ndarray:
    return np.ones((len(days), len(names)), dtype=bool)


# Build a small real dataset for partition and model tests.
def dataset(n: int = 240) -> study.Dataset:
    return study.build_dataset(
        {name: cube(name, n) for name in ("ABC", "XYZ", "SPY")},
        membership,
        reviewed_sessions()[1],
    )


# Future prices and volumes cannot change features or membership-selected row keys.
def test_features_and_rows_are_causal():
    original = cube()
    spy = cube("SPY")
    changed = replace(
        original,
        close=original.close.copy(),
        open=original.open.copy(),
        high=original.high.copy(),
        low=original.low.copy(),
        volume=original.volume.copy(),
        prior_close=original.prior_close.copy(),
    )
    for values in (
        changed.close,
        changed.open,
        changed.high,
        changed.low,
        changed.prior_close,
    ):
        values[180:] *= 2
    changed.volume[180:] *= 3
    before = study.build_dataset(
        {"ABC": original, "SPY": spy}, membership, reviewed_sessions()[1]
    )
    after = study.build_dataset(
        {"ABC": changed, "SPY": spy}, membership, reviewed_sessions()[1]
    )
    np.testing.assert_array_equal(before.dates, after.dates)
    earlier = before.dates < original.dates[180]
    np.testing.assert_allclose(before.x[earlier], after.x[earlier], equal_nan=True)
    assert np.isnan(before.y[-1]).all()
    assert np.isfinite(before.x[-1]).any()


# Missing future exchange sessions invalidate labels instead of shifting to a later day.
def test_missing_session_does_not_bridge_labels():
    original = cube()
    keep = np.arange(len(original)) != 150
    fields = (
        "dates",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "prior_close",
        "auction_open",
        "auction_volume",
    )
    missing = replace(original, **{key: getattr(original, key)[keep] for key in fields})
    ds = study.build_dataset(
        {"ABC": missing, "SPY": cube("SPY")}, membership, reviewed_sessions()[1]
    )
    i = np.flatnonzero(ds.dates == original.dates[149])[0]
    assert np.isnan(ds.y[i]).all()
    assert original.dates[150] not in ds.dates
    assert np.isfinite(ds.x[i]).any()


# Verify the gap-augmented target actually adds overnight risk, unlike RTH variance.
def test_gap_target_and_dollar_turnover_have_exact_meaning():
    c = cube()
    s = study.cube_series(c, c.dates)
    np.testing.assert_allclose(
        s["total"] - s["rv"], np.log(c.open[:, 0] / c.prior_close) ** 2
    )
    np.testing.assert_allclose(
        s["turnover"], ((c.high + c.low + c.close) / 3 * c.volume).sum(axis=1)
    )
    altered = replace(c, auction_volume=c.auction_volume * 1000)
    np.testing.assert_array_equal(
        study.cube_series(altered, c.dates)["turnover"], s["turnover"]
    )


# A consistent price/share split cannot manufacture a turnover or volatility shock.
def test_split_invariance():
    c = cube()
    split = replace(
        c,
        open=c.open / 2,
        close=c.close / 2,
        high=c.high / 2,
        low=c.low / 2,
        prior_close=c.prior_close / 2,
        volume=c.volume * 2,
    )
    a, b = study.cube_series(c, c.dates), study.cube_series(split, c.dates)
    for name in ("turnover", "rv", "total", "gap"):
        np.testing.assert_allclose(a[name], b[name])


# Invalid bars remain missing while genuine large but internally coherent moves remain.
def test_bad_prints_missing_and_crash_not_clipped():
    c = cube()
    c.high[100, 0] = 0
    c.prior_close[101] *= 2
    s = study.cube_series(c, c.dates)
    assert np.isnan(s["rv"][100])
    assert s["total"][101] > 0.4
    assert study.positive_log(np.array([0, -1, np.nan, np.inf])).tolist() != [
        0,
        0,
        0,
        0,
    ]


# All fit boundaries use date blocks shared by stocks with explicit five-day purges.
def test_chronological_partitions_and_configuration():
    ds = dataset()
    config = study.Config(min_train=80, validation=20, refit=80)
    for fold in study.partitions(ds, config):
        assert fold["train_stop"] + 5 == fold["validation_start"]
        assert fold["validation_stop"] + 5 == fold["test_start"]
    with pytest.raises(ValueError, match="purge"):
        study.partitions(ds, replace(config, purge=0))


# Test-set extremes cannot change training-only missing-value replacements.
def test_imputation_is_training_only():
    train, test = study.impute(
        np.array([[1.0, np.nan], [3.0, np.nan]]), np.array([[np.nan, 100000.0]])
    )
    np.testing.assert_array_equal(train, [[1, 0], [3, 0]])
    np.testing.assert_array_equal(test, [[2, 100000]])


# Exercise real CPU models and prove that test outcomes cannot affect forecasts.
def test_real_models_ignore_test_outcomes_and_preserve_latest_row():
    ds = dataset(180)
    config = study.Config(
        min_train=80, validation=20, refit=10000, trees=5, patience=2, threads=1
    )
    result = study.forecast(ds, config)
    test_start = result["fits"][0]["test_start"]
    mutated = replace(ds, y=ds.y.copy())
    mutated.y[ds.session_index >= test_start] *= 100
    repeat = study.forecast(mutated, config)
    np.testing.assert_allclose(result["point"], repeat["point"], equal_nan=True)
    np.testing.assert_allclose(result["interval"], repeat["interval"], equal_nan=True)
    assert np.isfinite(result["point"][-1]).all()
    assert np.isnan(ds.y[-1]).all()
    for target in result["fits"][0]["targets"].values():
        assert target["train_label_end_max"] < result["fits"][0]["validation_start"]
        assert target["validation_label_end_max"] < test_start
    scores = study.score(ds, result)
    assert scores
    assert study.verdict(scores)["live_promotion"] is False


# Dated membership controls training rows without consulting future grades.
def test_membership_controls_rows():
    c = cube()

    # Admit the stock only after the declared fixture entry date.
    def late(days, names):
        return np.broadcast_to((days >= c.dates[100])[:, None], (len(days), len(names)))

    ds = study.build_dataset(
        {"ABC": c, "SPY": cube("SPY")}, late, reviewed_sessions()[1]
    )
    assert ds.dates.min() == c.dates[100]
    assert set(ds.tickers) == {"ABC"}


# Unknown completion times and old strategy versions must remain unqualified evidence.
def test_paper_relevance_does_not_invent_execution_dates_or_policy():
    ds = dataset()
    predictions = {"point": np.ones((len(ds.dates), 3, 3)) * 1000000}
    state = {
        "policy_version": "graded-equal-weight/4",
        "journal": [
            {
                "symbol": "ABC",
                "session": "2018-09-12",
                "filled_qty": 10,
                "filled_price": 100,
            }
        ],
        "history": [{"session": "2018-09-12", "equity": 100000}],
    }
    result = liquidity_relevance.evaluate(state, ds, predictions)
    assert result["journal_policy_version"].endswith("/4")
    assert result["completion_date_matched_orders"] == 0
    assert (
        result["excluded_from_forecast_matching"]["missing_completion_timestamp"] == 1
    )
    assert result["saving_sensitivity"][0]["hypothetical_dollars"] == pytest.approx(0.1)
    assert result["measured_savings"] is None
    assert result["v5_size_scenario"]["order_dollars"] == 25000


# Existing result directories must be refused before data loading or model fitting.
def test_cli_refuses_existing_output(tmp_path):
    with pytest.raises(ValueError, match="new directory"):
        cli.main(["--cubes-dir", str(tmp_path), "--out-dir", str(tmp_path)])


# Persist a real fixture cube with the production schema for CLI acceptance.
def save_cube(path: Path, c: SessionCube) -> None:
    arrays = {
        key: getattr(c, key)
        for key in (
            "dates",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "prior_close",
            "auction_open",
            "auction_volume",
        )
    }
    np.savez(
        path,
        **arrays,
        key=np.array([str(len(c)), str(c.dates[-1]), "2"]),
        ticker=np.array(c.ticker),
        excluded_reasons=np.array([], dtype=str),
        excluded_counts=np.array([], dtype=int),
    )


# Loading an existing cube is read-only and checks its stored identity.
def test_cube_loader_is_read_only_and_rejects_wrong_identity(tmp_path):
    path = tmp_path / "ABC.npz"
    save_cube(path, cube())
    before = cli.sha256(path)
    cubes, manifest = cli.load_cubes(tmp_path)
    assert len(cubes["ABC"]) == 240
    assert manifest["ABC.npz"]["sha256"] == before == cli.sha256(path)
    path.rename(tmp_path / "BAD.npz")
    with pytest.raises(ValueError, match="identity"):
        cli.load_cubes(tmp_path)


# The seasonal estimate uses the next weekday's past volumes, never tomorrow's.
def test_same_weekday_baseline_is_causal():
    c = cube()
    weekday = (c.dates.astype(int) + 3) % 7
    values = (weekday + 1).astype(float) * 100
    original = study.seasonal_volume(values, c.dates, reviewed_sessions()[1])
    tomorrow = np.busday_offset(c.dates, 1, busdaycal=reviewed_sessions()[1])
    expected = ((tomorrow.astype(int) + 3) % 7 + 1) * 100
    np.testing.assert_allclose(original[80:], expected[80:])
    values[150:] *= 100
    changed = study.seasonal_volume(values, c.dates, reviewed_sessions()[1])
    np.testing.assert_allclose(original[:150], changed[:150], equal_nan=True)


# Run the actual CLI through real fitting, artifact persistence and JSON readback.
def test_cli_real_fit_and_artifact_readback(tmp_path):
    inputs = tmp_path / "cubes"
    inputs.mkdir()
    for name in ("ABC", "XYZ", "SPY"):
        save_cube(inputs / f"{name}.npz", cube(name, 180))
    history = tmp_path / "members.csv"
    history.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        "ABC,2017-01-01,2017-01-01,,,fixture,test\n"
        "XYZ,2017-01-01,2017-01-01,,,fixture,test\n"
    )
    output = tmp_path / "result"
    assert (
        cli.main(
            [
                "--cubes-dir",
                str(inputs),
                "--out-dir",
                str(output),
                "--membership",
                str(history),
                "--smoke",
            ]
        )
        == 0
    )
    result = json.loads((output / "results.json").read_text())
    assert result["registered_config"] is False
    assert result["verdict"]["live_promotion"] is False
    assert result["predictions_sha256"] == cli.sha256(output / "predictions.npz")
    with np.load(output / "predictions.npz", allow_pickle=False) as archive:
        assert archive["point"].shape[2] == len(study.MODELS)
        assert np.isfinite(archive["point"][-1]).all()
        assert np.isnan(archive["y"][-1]).all()
