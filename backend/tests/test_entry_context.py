"""Point-in-time fundamental context and the ten-session ablation replay."""

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.market import entry_context as ec
from backend.market import entry_pilot as ep
from backend.market import fundamental_features as ff

K = len(ff.FEATURE_NAMES)
HORIZON = 10
_NY = ZoneInfo("America/New_York")


# Load the optional research CLI only for tests requiring its ML environment.
@pytest.fixture
def c():
    pytest.importorskip("joblib", reason="requires optional research dependencies")
    pytest.importorskip("sklearn", reason="requires optional research dependencies")
    pytest.importorskip("threadpoolctl", reason="requires optional research dependencies")
    from backend.cli import market_entry_context

    return market_entry_context


# A tiny feature tensor with one name, one real value and one known period end.
def _one_name_features(dates):
    t = len(dates)
    values = np.zeros((t, 1, K))
    ends = np.full((t, 1, K), np.datetime64("NaT", "D"))
    for k in range(K):
        values[:, 0, k] = 10.0 + k + 0.1 * np.arange(t)
        ends[:, 0, k] = dates - np.timedelta64(30, "D")
    return ff.FundamentalFeatures(
        values, ff.FEATURE_NAMES, np.ones((t, 1), dtype=bool), np.zeros((t, 1)), ends
    )


# A small dataset spanning a training window and a later report window.
def _synthetic_dataset():
    rng = np.random.default_rng(0)
    t = 200
    dates = np.datetime64("2020-01-01", "D") + np.arange(t)
    days = np.array([5, 12, 19, 26, 33, 40, 47, 61, 68, 75, 82, 89, 96, 103, 110])
    r = len(days)
    return ep.Dataset(
        x=rng.normal(size=(r, len(ep.NAMES))).astype("float32"),
        sequence=np.ones((r, ep.SEQUENCE, 7), dtype="float32"),
        y=rng.normal(size=(r, 2)),
        day=days,
        slot=np.where(np.arange(r) % 2, 3, 7),
        name=np.arange(r) % 2,
        entry_prices=np.column_stack((100.0 + days * 0.1, 101.0 + days * 0.1)).astype(
            "float32"
        ),
        exit_day=days + HORIZON,
        dates=dates,
        closes=np.column_stack(
            (100.0 + 0.05 * np.arange(t), 120.0 + 0.03 * np.arange(t))
        ).astype("float32"),
        tickers=np.array(["AAA", "BBB"]),
        candidate=np.ones(r, dtype=bool),
        horizon=HORIZON,
    )


# A feature tensor aligned to the synthetic panel, with a NaN and a zero.
def _synthetic_features(dates):
    t = len(dates)
    n = 2
    values = np.zeros((t, n, K))
    ends = np.full((t, n, K), np.datetime64("NaT", "D"))
    for j in range(n):
        for k in range(K):
            values[:, j, k] = 0.1 * (j + 1) + 0.01 * np.arange(t)
            ends[:, j, k] = dates - np.timedelta64(30, "D")
    values[10, 0, 0] = np.nan
    ends[10, 0, 0] = np.datetime64("NaT", "D")
    values[20, 1, 1] = 0.0
    ends[20, 1, 1] = dates[20] - np.timedelta64(30, "D")
    return ff.FundamentalFeatures(
        values, ff.FEATURE_NAMES, np.ones((t, n), dtype=bool), np.zeros((t, n)), ends
    )


# The join reads the session before the decision, never the decision session.
def test_context_block_reads_the_prior_session():
    dates = np.arange("2020-01-01", "2020-01-10", dtype="datetime64[D]")
    features = _one_name_features(dates)
    values, ends = ec.context_block(features, np.array([5]), np.array([0]))
    np.testing.assert_array_equal(values[0], features.values[4, 0])
    np.testing.assert_array_equal(ends[0], features.period_ends[4, 0])
    features.values[6, 0, :] = 999.0
    features.period_ends[6, 0, :] = dates[6] - np.timedelta64(5, "D")
    values, ends = ec.context_block(features, np.array([5]), np.array([0]))
    np.testing.assert_array_equal(values[0], features.values[4, 0])


# A decision with no prior session has no context and must fail, not guess.
def test_day_zero_lookup_fails():
    dates = np.arange("2020-01-01", "2020-01-10", dtype="datetime64[D]")
    features = _one_name_features(dates)
    with pytest.raises(ValueError, match="no prior session"):
        ec.prior_context(features, 0, 0)
    with pytest.raises(ValueError, match="day-zero"):
        ec.context_block(features, np.array([0]), np.array([0]))
    with pytest.raises(ValueError, match="day-zero"):
        ec.context_block(features, np.array([0, 3]), np.array([0, 0]))


# A genuine zero is not missing: flag 0, and imputation leaves the zero as zero.
def test_missing_flag_and_imputation_distinguish_zero():
    values = np.array([[0.0, np.nan], [5.0, 3.0]])
    flags = ec.missing_flags(values)
    np.testing.assert_array_equal(flags, [[0, 1], [0, 0]])
    medians = ec.training_medians(values, np.array([True, True]))
    np.testing.assert_allclose(medians, [2.5, 3.0])
    filled = ec.impute(values, medians)
    np.testing.assert_allclose(filled, [[0.0, 3.0], [5.0, 3.0]])


# Medians come from training rows only, and an all-missing column falls to zero.
def test_median_uses_training_rows_only():
    values = np.array([[np.nan, np.nan], [4.0, np.nan], [6.0, 100.0]])
    train = np.array([True, True, False])
    medians = ec.training_medians(values, train)
    assert medians[0] == pytest.approx(4.0)
    assert medians[1] == pytest.approx(0.0)
    values[2, 0] = 9000.0
    again = ec.training_medians(values, train)
    np.testing.assert_allclose(medians, again)


# Ages are anchored to the read session: unknown is 2000, past is clamped.
def test_fiscal_age_clamp_and_unknown():
    dates = np.arange("2020-01-01", "2020-01-10", dtype="datetime64[D]")
    values = np.array([[np.nan, 1.0, 2.0]])
    ends = np.array(
        [
            [np.datetime64("NaT", "D"), "2010-01-01", "2020-01-04"],
        ],
        dtype="datetime64[D]",
    )
    ages = ec.fiscal_ages(dates, np.array([5]), values, ends)
    assert ages[0, 0] == ec.UNKNOWN_AGE
    assert ages[0, 1] == ec.UNKNOWN_AGE
    assert ages[0, 2] == pytest.approx(1.0)


# A period dated after the read session is invalid data and fails.
def test_negative_fiscal_age_fails():
    dates = np.arange("2020-01-01", "2020-01-10", dtype="datetime64[D]")
    values = np.array([[1.0]])
    ends = np.array([[np.datetime64("2020-02-01", "D")]])
    with pytest.raises(ValueError, match="negative fiscal age"):
        ec.fiscal_ages(dates, np.array([5]), values, ends)


# The assembled block is three companion columns per economic feature.
def test_context_columns_shape_and_medians():
    dates = np.arange("2020-01-01", "2020-01-10", dtype="datetime64[D]")
    features = _one_name_features(dates)
    days = np.array([3, 5])
    names = np.zeros(2, dtype=int)
    train = np.array([True, False])
    block, medians = ec.context_columns(features, days, names, dates, train)
    assert block.shape == (2, 3 * K)
    assert medians.shape == (K,)
    for k in range(K):
        assert medians[k] == pytest.approx(10.0 + k + 0.1 * 2)


# A small synthetic run trains, replays, and reproduces its own artifacts.
def test_small_synthetic_end_to_end_run_and_replay(tmp_path, c):
    data = _synthetic_dataset()
    features = _synthetic_features(data.dates)
    out = tmp_path / "run"
    periods = {
        "train_rep": ("2020-01-01", "2020-03-01"),
        "report": ("2020-03-01", "2020-06-01"),
    }
    c.run(
        data, features, out, train_period=("2020-01-01", "2020-03-01"), periods=periods
    )
    c.verify(out)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["horizon"] == HORIZON
    assert manifest["split_counts"]["training"] == 7
    assert manifest["split_counts"]["report"] == 8
    assert len(manifest["features"]["context"]) == K
    assert manifest["features"]["context_columns"] == 3 * K
    assert any("retrospective" in label for label in manifest["limitations"])
    assert "median_vector" in manifest
    assert "intraday_partition" in manifest
    assert "artifact_sha256" in manifest


# A realistic bars partition for a synthetic panel: real 15-minute parquet
# aligned to the New York session across DST, so `ep.build` reads it for real.
def _panel_and_partition(tmp_path):
    """Return (panel, data_dir) with a real 15m partition under bars_15m."""
    from backend.market.panel import Panel

    dates = np.arange("2020-01-01", "2020-09-07", dtype="datetime64[D]")
    t = len(dates)
    close = np.repeat((100 + np.arange(t))[:, None], 2, axis=1).astype(float)
    panel = Panel(
        dates,
        ("AAA", "SPY"),
        close.copy(),
        close + 2,
        close - 2,
        close.copy(),
        close.copy(),
        np.ones_like(close) * 1000,
        {"AAA": ("theme",)},
        "SPY",
    )
    part = tmp_path / "bars_15m" / "asof=2020-01-01"
    part.mkdir(parents=True)
    starts, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    for d in range(t):
        base = close[d, 0]
        day = dates[d].astype(object)
        offset = (
            datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
            .astimezone(_NY)
            .utcoffset()
            .total_seconds()
            // 60
        )
        for slot in range(26):
            minutes = 570 + 15 * slot - int(offset)
            start = np.datetime64(dates[d], "m") + np.timedelta64(minutes, "m")
            starts.append(str(start))
            opens.append(base)
            highs.append(base + 2)
            lows.append(base - 2)
            closes.append(base + 1)
            volumes.append(1000)
    pq.write_table(
        pa.table(
            {
                "start": starts,
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
            }
        ),
        part / "AAA.parquet",
    )
    return panel, tmp_path


# The build selects the newest 15m partition, and the store root fails.
def test_build_data_uses_the_partition_not_the_store_root(tmp_path, monkeypatch, c):
    panel, data_dir = _panel_and_partition(tmp_path)
    monkeypatch.setattr(c, "book_panel", lambda store: (panel, {}))
    store = c.MarketStore(data_dir)
    _, data, root = c.build_data(store, data_dir)
    assert root == data_dir / "bars_15m" / "asof=2020-01-01"
    assert len(data.x) > 0
    with pytest.raises(ValueError, match="No usable"):
        c.ep.build(panel, store.root, c.HORIZON)


# main() runs the full boundary and verifies its own output before returning.
def test_main_runs_and_self_verifies(tmp_path, monkeypatch, c):
    panel, data_dir = _panel_and_partition(tmp_path)
    monkeypatch.setattr(c, "book_panel", lambda store: (panel, {}))
    out = tmp_path / "out"
    calls = {"verified": False}
    real_verify = c.verify

    def spy_verify(path):
        calls["verified"] = True
        real_verify(path)

    monkeypatch.setattr(c, "verify", spy_verify)
    c.main(["--data-dir", str(data_dir), "--output", str(out)])
    assert calls["verified"] is True
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["intraday_partition"] == str(
        data_dir / "bars_15m" / "asof=2020-01-01"
    )


# One-ulp input tampering cannot change predictions but must still be rejected.
def test_verify_rejects_tampered_input_that_preserves_predictions(tmp_path, c):
    data = _synthetic_dataset()
    features = _synthetic_features(data.dates)
    out = tmp_path / "run"
    periods = {
        "train_rep": ("2020-01-01", "2020-03-01"),
        "report": ("2020-03-01", "2020-06-01"),
    }
    c.run(
        data, features, out, train_period=("2020-01-01", "2020-03-01"), periods=periods
    )
    c.verify(out)
    ctx = c._load_npz(out / "context.npz")
    ctx["values"][0, 0] = np.nextafter(ctx["values"][0, 0], np.inf)
    np.savez_compressed(out / "context.npz", **ctx)
    with pytest.raises(Exception, match="artifact context.npz"):
        c.verify(out)


# Model artifacts are pinned too, and rejected before being loaded.
def test_verify_rejects_tampered_model(tmp_path, c):
    data = _synthetic_dataset()
    features = _synthetic_features(data.dates)
    out = tmp_path / "run"
    periods = {
        "train_rep": ("2020-01-01", "2020-03-01"),
        "report": ("2020-03-01", "2020-06-01"),
    }
    c.run(
        data, features, out, train_period=("2020-01-01", "2020-03-01"), periods=periods
    )
    model_path = out / "context_models.joblib"
    blob = bytearray(model_path.read_bytes())
    blob[len(blob) // 2] ^= 0x01
    model_path.write_bytes(bytes(blob))
    with pytest.raises(Exception, match="artifact context_models.joblib"):
        c.verify(out)


# Model results carry paired intervals against both baselines and (context) price.
def test_model_results_carry_paired_intervals(tmp_path, c):
    data = _synthetic_dataset()
    features = _synthetic_features(data.dates)
    out = tmp_path / "run"
    periods = {
        "train_rep": ("2020-01-01", "2020-03-01"),
        "report": ("2020-03-01", "2020-06-01"),
    }
    c.run(
        data, features, out, train_period=("2020-01-01", "2020-03-01"), periods=periods
    )
    summary = json.loads((out / "summary.json").read_text())
    ctx = summary["report@5bps/context/timing"]
    assert ctx["paired_vs_enter"] is not None
    assert ctx["paired_vs_wait"] is not None
    assert ctx["paired_vs_price"] is not None
    price = summary["report@5bps/price/timing"]
    assert price["paired_vs_wait"] is not None
    assert price["paired_vs_price"] is None
    assert summary["report@5bps/enter"]["paired_vs_enter"] is None
