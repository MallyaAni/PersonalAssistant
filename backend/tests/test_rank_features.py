"""Functional tests for the point-in-time ranker feature/label assembly.

These run in the functional-tests image (numpy + pyarrow only, no pandas, no
sklearn). They use small synthetic in-memory parquet snapshots written to a
tmp dir, so nothing here depends on the real ``data/`` tree, plus one test
that loads the real as-of=2026-09-22 snapshot when it exists.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.market.rank_features import (
    FEATURE_COLUMNS,
    feature_matrix,
    forward_labels,
    load_snapshot,
)

# The expected order of FEATURE_COLUMNS, pinned so a reorder cannot slip past.
EXPECTED_FEATURE_COLUMNS = [
    "momentum_5",
    "momentum_10",
    "momentum_21",
    "momentum_63",
    "vol_21",
    "vol_63",
    "ma_dist_21",
    "ma_dist_63",
    "rsi_14",
    "volume_z_21",
    "drawdown_63",
    "atr_21",
]

REAL_SNAPSHOT = (
    Path(__file__).resolve().parents[2] / "data" / "market" / "bars" / "asof=2026-09-22"
)


def _session_dates(start_iso: str, n: int) -> list[str]:
    """Return `n` consecutive weekdays (ISO strings) starting at `start_iso`."""
    out: list[str] = []
    day = datetime.date.fromisoformat(start_iso)
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += datetime.timedelta(days=1)
    return out


def _bars_for(
    dates: list[str], *, scale: float = 1.0, base: float = 100.0
) -> dict[str, list[float]]:
    """Return the OHLC/volume columns for a deterministic synthetic series."""
    n = len(dates)
    close = [base + 0.7 * i + 5.0 * np.sin(float(i)) for i in range(n)]
    adj = [c * scale for c in close]
    open_ = [c - 0.5 for c in close]
    high = [c + 1.0 for c in close]
    low = [c - 1.0 for c in close]
    volume = [1_000_000 + 1_000 * i for i in range(n)]
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "adj_close": adj,
        "volume": volume,
    }


def _write_snapshot(
    root: Path, asof: str, tickers_data: dict[str, dict[str, list[float]]]
) -> Path:
    """Write one as-of snapshot directory of synthetic parquet files; returns `root`."""
    snap_dir = root / f"asof={asof}"
    snap_dir.mkdir(parents=True, exist_ok=True)
    for ticker, data in tickers_data.items():
        dates = np.array(data["dates"], dtype="datetime64[D]")
        schema = pa.schema(
            [
                pa.field("session_date", pa.date32()),
                pa.field("open", pa.float64()),
                pa.field("high", pa.float64()),
                pa.field("low", pa.float64()),
                pa.field("close", pa.float64()),
                pa.field("adjusted_close", pa.float64()),
                pa.field("volume", pa.int64()),
            ],
            metadata={"asof": asof, "complete_through": asof, "ticker": ticker},
        )
        table = pa.table(
            {
                "session_date": pa.array(dates, type=pa.date32()),
                "open": pa.array(data["open"], type=pa.float64()),
                "high": pa.array(data["high"], type=pa.float64()),
                "low": pa.array(data["low"], type=pa.float64()),
                "close": pa.array(data["close"], type=pa.float64()),
                "adjusted_close": pa.array(data["adj_close"], type=pa.float64()),
                "volume": pa.array(data["volume"], type=pa.int64()),
            },
            schema=schema,
        )
        pq.write_table(table, snap_dir / f"{ticker}.parquet")
    return root


def _reference_features(  # noqa: C901 - a deliberately explicit independent reference
    adj: np.ndarray, vol: np.ndarray, high: np.ndarray, low: np.ndarray
) -> dict[str, np.ndarray]:
    """Independently hand-computed features for one ticker, for the semantics test."""
    n = len(adj)
    cols: dict[str, np.ndarray] = {}

    for k in (5, 10, 21, 63):
        r = np.full(n, np.nan)
        for t in range(k, n):
            a, b = adj[t], adj[t - k]
            if a > 0 and b > 0 and np.isfinite(a) and np.isfinite(b):
                r[t] = a / b - 1.0
        cols[f"momentum_{k}"] = r

    ret = np.full(n, np.nan)
    for t in range(1, n):
        a, b = adj[t], adj[t - 1]
        if a > 0 and b > 0 and np.isfinite(a) and np.isfinite(b):
            ret[t] = a / b - 1.0
    for k in (21, 63):
        r = np.full(n, np.nan)
        for t in range(k, n):
            window = ret[t - k + 1 : t + 1]
            if np.isfinite(window).all():
                r[t] = float(np.std(window))
        cols[f"vol_{k}"] = r

    for k in (21, 63):
        r = np.full(n, np.nan)
        for t in range(k - 1, n):
            window = adj[t - k + 1 : t + 1]
            if np.isfinite(window).all() and window.min() > 0:
                r[t] = adj[t] / float(np.mean(window)) - 1.0
        cols[f"ma_dist_{k}"] = r

    rsi = np.full(n, np.nan)
    if n >= 15:
        deltas = np.diff(adj[0:15])
        ag = float(np.clip(deltas, 0, None).mean())
        al = float(np.clip(-deltas, 0, None).mean())
        rsi[14] = 100.0 if al == 0 else 100.0 * ag / (ag + al)
        for t in range(15, n):
            d = adj[t] - adj[t - 1]
            if not (
                np.isfinite(d)
                and np.isfinite(adj[t])
                and np.isfinite(adj[t - 1])
                and adj[t] > 0
                and adj[t - 1] > 0
            ):
                continue
            g, loss = max(d, 0.0), max(-d, 0.0)
            ag = (ag * 13 + g) / 14.0
            al = (al * 13 + loss) / 14.0
            rsi[t] = 100.0 if al == 0 else 100.0 * ag / (ag + al)
    cols["rsi_14"] = rsi

    vz = np.full(n, np.nan)
    for t in range(20, n):
        window = vol[t - 20 : t + 1]
        if np.isfinite(window).all():
            s = float(np.std(window))
            if s > 0:
                vz[t] = (vol[t] - float(np.mean(window))) / s
    cols["volume_z_21"] = vz

    dd = np.full(n, np.nan)
    for t in range(62, n):
        window = adj[t - 62 : t + 1]
        if np.isfinite(window).all() and window.min() > 0:
            dd[t] = adj[t] / float(np.max(window)) - 1.0
    cols["drawdown_63"] = dd

    tr = np.full(n, np.nan)
    for t in range(1, n):
        if (
            np.isfinite(high[t])
            and np.isfinite(low[t])
            and np.isfinite(adj[t - 1])
            and high[t] > 0
            and low[t] > 0
            and adj[t - 1] > 0
        ):
            tr[t] = max(
                high[t] - low[t],
                abs(high[t] - adj[t - 1]),
                abs(low[t] - adj[t - 1]),
            )
    atr = np.full(n, np.nan)
    for t in range(20, n):
        window = tr[t - 20 : t + 1]
        if np.isfinite(window).all() and np.isfinite(adj[t]) and adj[t] > 0:
            atr[t] = float(np.mean(window)) / adj[t]
    cols["atr_21"] = atr
    return cols


def test_feature_columns_order_and_semantics_are_pinned():
    """FEATURE_COLUMNS is exactly the documented order."""
    assert FEATURE_COLUMNS == EXPECTED_FEATURE_COLUMNS


def test_features_use_only_rows_up_to_the_decision_date(tmp_path):
    """Perturbing a later close leaves every earlier feature unchanged."""
    dates = _session_dates("2026-01-02", 80)
    bars_a = _bars_for(dates)
    bars_b = dict(bars_a)
    bars_b["close"] = list(bars_a["close"])
    bars_b["adj_close"] = list(bars_a["adj_close"])
    # Perturb the final session's close/adjusted_close and open.
    bars_b["close"][-1] += 999.0
    bars_b["adj_close"][-1] += 999.0
    bars_b["open"][-1] += 999.0
    root_a = _write_snapshot(
        tmp_path / "a", "2026-09-05", {"AAA": {"dates": dates, **bars_a}}
    )
    root_b = _write_snapshot(
        tmp_path / "b", "2026-09-05", {"AAA": {"dates": dates, **bars_b}}
    )
    snap_a = load_snapshot("2026-09-05", root_a)
    snap_b = load_snapshot("2026-09-05", root_b)
    _, _, x_a, valid_a = feature_matrix(snap_a)
    _, _, x_b, valid_b = feature_matrix(snap_b)
    n_dates = len(dates)
    # Rows for dates 0..T-2 must be identical; only the last date may differ.
    earlier = slice(0, (n_dates - 1) * 1)
    assert np.array_equal(x_a[earlier], x_b[earlier], equal_nan=True)
    assert np.array_equal(valid_a[earlier], valid_b[earlier])
    # The last date's own features do change (they include the perturbed price).
    assert not np.array_equal(
        x_a[(n_dates - 1) * 1 :], x_b[(n_dates - 1) * 1 :], equal_nan=True
    )


def test_feature_semantics_hand_computed(tmp_path):
    """Every feature matches an independent hand computation on adjusted closes."""
    dates = _session_dates("2026-01-02", 80)
    bars = _bars_for(dates, scale=1.0)
    root = _write_snapshot(tmp_path, "2026-09-05", {"AAA": {"dates": dates, **bars}})
    snap = load_snapshot("2026-09-05", root)
    _, tickers, x, valid = feature_matrix(snap)
    assert tickers == ["AAA"]
    ref = _reference_features(
        np.asarray(bars["adj_close"], dtype=float),
        np.asarray(bars["volume"], dtype=float),
        np.asarray(bars["high"], dtype=float),
        np.asarray(bars["low"], dtype=float),
    )
    for col, expected in ref.items():
        idx = FEATURE_COLUMNS.index(col)
        got = x[0::1, idx]  # ticker 0, all dates
        mask = np.isfinite(expected)
        assert mask.any(), col
        np.testing.assert_allclose(got[mask], expected[mask], atol=1e-9, err_msg=col)
        # Both agree on where the feature is finite.
        assert np.array_equal(np.isfinite(got), np.isfinite(expected)), col


def test_features_use_adjusted_close_not_raw_close(tmp_path):
    """A split is smoothed by adjusted_close: momentum equals the adjusted ratio."""
    dates = _session_dates("2026-01-02", 30)
    close = [100.0 + i for i in range(30)]
    # A 2-for-1 split at index 10 halves the raw close but not the adjusted close.
    raw_close = [c / 2.0 if i >= 10 else c for i, c in enumerate(close)]
    adj_close = list(close)  # the split-adjusted view is continuous
    open_ = [c - 0.5 for c in raw_close]
    high = [c + 1.0 for c in raw_close]
    low = [c - 1.0 for c in raw_close]
    volume = [1_000_000 + 1_000 * i for i in range(30)]
    bars = {
        "open": open_,
        "high": high,
        "low": low,
        "close": raw_close,
        "adj_close": adj_close,
        "volume": volume,
    }
    root = _write_snapshot(tmp_path, "2026-09-05", {"AAA": {"dates": dates, **bars}})
    snap = load_snapshot("2026-09-05", root)
    _, _, x, _ = feature_matrix(snap)
    momentum_idx = FEATURE_COLUMNS.index("momentum_5")
    raw = np.asarray(raw_close, dtype=float)
    adj = np.asarray(adj_close, dtype=float)
    for t in (12, 14):
        # The 5-session window straddles the split, so the adjusted-close
        # ratio (split-smoothed) differs from the raw ratio.
        expected_adj = adj[t] / adj[t - 5] - 1.0
        expected_raw = raw[t] / raw[t - 5] - 1.0
        got = x[t, momentum_idx]
        np.testing.assert_allclose(got, expected_adj, atol=1e-12)
        assert not np.isclose(got, expected_raw, atol=1e-9)


def test_forward_label_next_open_convention(tmp_path):
    """Labels are exactly close[D+horizon]/open[D+1] - 1 with the next open."""
    dates = _session_dates("2026-09-01", 5)
    bars = _bars_for(dates, base=10.0)
    root1 = _write_snapshot(
        tmp_path / "s1", "2026-09-08", {"AAA": {"dates": dates, **bars}}
    )
    snap1 = load_snapshot("2026-09-08", root1)

    dates2 = _session_dates("2026-09-01", 9)
    bars2 = _bars_for(dates2, base=10.0)
    root2 = _write_snapshot(
        tmp_path / "s2", "2026-09-14", {"AAA": {"dates": dates2, **bars2}}
    )
    snap2 = load_snapshot("2026-09-14", root2)

    labels = forward_labels(snap1, horizon=2, next_snapshot=snap2)
    open2 = np.asarray(bars2["open"], dtype=float)
    close2 = np.asarray(bars2["close"], dtype=float)
    # Every decision session gets a label: buy at the next session's open,
    # sell at the session two sessions later, both from next_snapshot.
    for i in range(5):
        expected = close2[i + 2] / open2[i + 1] - 1.0
        assert labels[i] == pytest.approx(expected, rel=1e-12, abs=1e-12), i


def test_forward_label_uses_next_snapshot_close(tmp_path):
    """The sell close is read from next_snapshot, so a split there is consistent."""
    dates = _session_dates("2026-09-01", 5)
    bars = _bars_for(dates, base=10.0)
    root1 = _write_snapshot(
        tmp_path / "s1", "2026-09-08", {"AAA": {"dates": dates, **bars}}
    )
    snap1 = load_snapshot("2026-09-08", root1)

    dates2 = _session_dates("2026-09-01", 9)
    bars2 = _bars_for(dates2, base=10.0)
    # next_snapshot has split-adjusted closes (a 2-for-1 split after snapshot 1).
    bars2["close"] = [c / 2.0 for c in bars2["close"]]
    bars2["open"] = [o / 2.0 for o in bars2["open"]]
    bars2["high"] = [h / 2.0 for h in bars2["high"]]
    bars2["low"] = [lo / 2.0 for lo in bars2["low"]]
    root2 = _write_snapshot(
        tmp_path / "s2", "2026-09-14", {"AAA": {"dates": dates2, **bars2}}
    )
    snap2 = load_snapshot("2026-09-14", root2)

    labels = forward_labels(snap1, horizon=2, next_snapshot=snap2)
    open2 = np.asarray(bars2["open"], dtype=float)
    close2 = np.asarray(bars2["close"], dtype=float)
    for i in range(5):
        expected = close2[i + 2] / open2[i + 1] - 1.0
        assert labels[i] == pytest.approx(expected, rel=1e-12, abs=1e-12), i


def test_valid_mask_and_beyond_coverage_nan(tmp_path):
    """Insufficient history is not valid; labels beyond next coverage are NaN."""
    dates = _session_dates("2026-01-02", 8)
    bars = _bars_for(dates)
    root = _write_snapshot(
        tmp_path / "short", "2026-09-05", {"AAA": {"dates": dates, **bars}}
    )
    snap = load_snapshot("2026-09-05", root)
    _, _, x, valid = feature_matrix(snap)
    # Only 8 sessions: no row has even 21 sessions of history, so nothing is valid.
    assert not valid.any()

    dates_long = _session_dates("2026-01-02", 70)
    bars_long = _bars_for(dates_long)
    root_long = _write_snapshot(
        tmp_path / "long", "2026-09-05", {"AAA": {"dates": dates_long, **bars_long}}
    )
    snap_long = load_snapshot("2026-09-05", root_long)
    _, _, x_long, valid_long = feature_matrix(snap_long)
    # The first fully-valid row needs 63 sessions of prices plus a return to
    # measure vol_63, i.e. index >= 63.
    assert not valid_long[:63].any()
    assert valid_long[63:].all()
    assert np.isfinite(x_long[63:]).all()

    # Labels: a decision whose D+horizon lies beyond next_snapshot's own
    # coverage for that ticker, or whose ticker is absent there, is NaN.
    dec_dates = _session_dates("2026-09-01", 7)  # 09-01 .. 09-10
    dec_bars = _bars_for(dec_dates, base=10.0)
    root_dec = _write_snapshot(
        tmp_path / "dec", "2026-09-10", {"AAA": {"dates": dec_dates, **dec_bars}}
    )
    snap_dec = load_snapshot("2026-09-10", root_dec)
    next_dates = _session_dates("2026-09-01", 9)  # 09-01 .. 09-14, a later as-of
    next_bars = _bars_for(next_dates, base=10.0)
    root_next = _write_snapshot(
        tmp_path / "next", "2026-09-14", {"AAA": {"dates": next_dates, **next_bars}}
    )
    snap_next = load_snapshot("2026-09-14", root_next)
    labels = forward_labels(snap_dec, horizon=3, next_snapshot=snap_next)
    # D at index 3 -> D+3 at next index 6, well inside next_snapshot.
    assert np.isfinite(labels[3])
    # D at index 6 (09-10) -> D+3 at next index 9, beyond next_snapshot.
    assert np.isnan(labels[6])
    # A decision ticker absent from next_snapshot gets no label.
    zzz_bars = _bars_for(dec_dates, base=5.0)
    root_dec2 = _write_snapshot(
        tmp_path / "dec2",
        "2026-09-10",
        {
            "AAA": {"dates": dec_dates, **dec_bars},
            "ZZZ": {"dates": dec_dates, **zzz_bars},
        },
    )
    snap_dec2 = load_snapshot("2026-09-10", root_dec2)
    labels2 = forward_labels(snap_dec2, horizon=3, next_snapshot=snap_next)
    j_zzz = snap_dec2.tickers.index("ZZZ")
    assert np.isnan(labels2[j_zzz :: len(snap_dec2.tickers)]).all()


def test_alignment_different_row_sets(tmp_path):
    """Tickers with different row sets align with NaN, never the wrong value."""
    dates = _session_dates("2026-01-02", 10)
    bars_a = _bars_for(dates, base=100.0)
    # Ticker B starts three sessions later and trades a different scale.
    bars_b = _bars_for(dates[3:], base=1000.0)
    root = _write_snapshot(
        tmp_path,
        "2026-09-05",
        {
            "AAA": {"dates": dates, **bars_a},
            "BBB": {"dates": dates[3:], **bars_b},
        },
    )
    snap = load_snapshot("2026-09-05", root)
    assert snap.tickers == ["AAA", "BBB"]
    j_a = snap.tickers.index("AAA")
    j_b = snap.tickers.index("BBB")
    # BBB has no row on the first three grid dates.
    assert np.isnan(snap.close[:3, j_b]).all()
    assert np.isnan(snap.adjusted_close[:3, j_b]).all()
    assert np.isfinite(snap.close[3:, j_b]).all()
    # The grid dates still map each ticker to its own prices.
    assert snap.close[0, j_a] == pytest.approx(bars_a["close"][0])
    assert snap.close[3, j_b] == pytest.approx(bars_b["close"][0])
    # Features never read the wrong ticker: momentum_5 at grid index 8 for BBB
    # uses BBB's own series (adj[grid 8]/adj[grid 3]), not AAA's.
    _, _, x, valid = feature_matrix(snap)
    mom = FEATURE_COLUMNS.index("momentum_5")
    row_b = 8 * 2 + j_b
    expected_b = bars_b["adj_close"][5] / bars_b["adj_close"][0] - 1.0
    assert np.isfinite(x[row_b, mom])
    assert x[row_b, mom] == pytest.approx(expected_b, rel=1e-12, abs=1e-12)
    row_a = 8 * 2 + j_a
    expected_a = bars_a["adj_close"][8] / bars_a["adj_close"][3] - 1.0
    assert np.isfinite(x[row_a, mom])
    assert x[row_a, mom] == pytest.approx(expected_a, rel=1e-12, abs=1e-12)
    # A date where BBB is missing is not valid.
    assert not valid[2 * 2 + j_b]


def test_determinism(tmp_path):
    """feature_matrix and forward_labels are pure: same inputs, same output."""
    dates = _session_dates("2026-01-02", 70)
    bars = _bars_for(dates)
    root = _write_snapshot(tmp_path, "2026-09-05", {"AAA": {"dates": dates, **bars}})
    snap = load_snapshot("2026-09-05", root)
    _, _, x1, v1 = feature_matrix(snap)
    _, _, x2, v2 = feature_matrix(snap)
    assert np.array_equal(x1, x2, equal_nan=True)
    assert np.array_equal(v1, v2)
    labels1 = forward_labels(snap, 5, snap)
    labels2 = forward_labels(snap, 5, snap)
    assert np.array_equal(labels1, labels2, equal_nan=True)


def test_load_snapshot_validation(tmp_path):
    """Metadata asof mismatch, future rows and duplicate dates are rejected."""
    dates = _session_dates("2026-01-02", 20)
    bars = _bars_for(dates)
    # Directory asof differs from metadata asof.
    snap_dir = tmp_path / "asof=2026-09-05"
    snap_dir.mkdir(parents=True)
    schema = pa.schema(
        [
            pa.field("session_date", pa.date32()),
            pa.field("open", pa.float64()),
            pa.field("high", pa.float64()),
            pa.field("low", pa.float64()),
            pa.field("close", pa.float64()),
            pa.field("adjusted_close", pa.float64()),
            pa.field("volume", pa.int64()),
        ],
        metadata={"asof": "2026-09-06", "ticker": "AAA"},
    )
    table = pa.table(
        {
            "session_date": pa.array(
                np.array(dates, dtype="datetime64[D]"), type=pa.date32()
            ),
            "open": pa.array(bars["open"], type=pa.float64()),
            "high": pa.array(bars["high"], type=pa.float64()),
            "low": pa.array(bars["low"], type=pa.float64()),
            "close": pa.array(bars["close"], type=pa.float64()),
            "adjusted_close": pa.array(bars["adj_close"], type=pa.float64()),
            "volume": pa.array(bars["volume"], type=pa.int64()),
        },
        schema=schema,
    )
    pq.write_table(table, snap_dir / "AAA.parquet")
    with pytest.raises(ValueError, match="metadata asof"):
        load_snapshot("2026-09-05", tmp_path)

    # A row dated after the snapshot's as-of date is rejected.
    dates_future = list(dates) + ["2026-10-01"]
    bars_future = _bars_for(dates_future)
    bad = tmp_path / "asof=2026-09-06"
    bad.mkdir()
    schema2 = pa.schema(
        [
            pa.field("session_date", pa.date32()),
            pa.field("open", pa.float64()),
            pa.field("high", pa.float64()),
            pa.field("low", pa.float64()),
            pa.field("close", pa.float64()),
            pa.field("adjusted_close", pa.float64()),
            pa.field("volume", pa.int64()),
        ],
        metadata={"asof": "2026-09-06", "ticker": "AAA"},
    )
    table2 = pa.table(
        {
            "session_date": pa.array(
                np.array(dates_future, dtype="datetime64[D]"), type=pa.date32()
            ),
            "open": pa.array(bars_future["open"], type=pa.float64()),
            "high": pa.array(bars_future["high"], type=pa.float64()),
            "low": pa.array(bars_future["low"], type=pa.float64()),
            "close": pa.array(bars_future["close"], type=pa.float64()),
            "adjusted_close": pa.array(bars_future["adj_close"], type=pa.float64()),
            "volume": pa.array(bars_future["volume"], type=pa.int64()),
        },
        schema=schema2,
    )
    pq.write_table(table2, bad / "AAA.parquet")
    with pytest.raises(ValueError, match="after the snapshot"):
        load_snapshot("2026-09-06", tmp_path)

    # Duplicate session dates are rejected.
    dup_dates = [dates[0], dates[0]] + list(dates[1:])
    bars_dup = _bars_for(dup_dates)
    dup = tmp_path / "asof=2026-09-07"
    dup.mkdir()
    schema3 = pa.schema(
        [
            pa.field("session_date", pa.date32()),
            pa.field("open", pa.float64()),
            pa.field("high", pa.float64()),
            pa.field("low", pa.float64()),
            pa.field("close", pa.float64()),
            pa.field("adjusted_close", pa.float64()),
            pa.field("volume", pa.int64()),
        ],
        metadata={"asof": "2026-09-07", "ticker": "AAA"},
    )
    table3 = pa.table(
        {
            "session_date": pa.array(
                np.array(dup_dates, dtype="datetime64[D]"), type=pa.date32()
            ),
            "open": pa.array(bars_dup["open"], type=pa.float64()),
            "high": pa.array(bars_dup["high"], type=pa.float64()),
            "low": pa.array(bars_dup["low"], type=pa.float64()),
            "close": pa.array(bars_dup["close"], type=pa.float64()),
            "adjusted_close": pa.array(bars_dup["adj_close"], type=pa.float64()),
            "volume": pa.array(bars_dup["volume"], type=pa.int64()),
        },
        schema=schema3,
    )
    pq.write_table(table3, dup / "AAA.parquet")
    with pytest.raises(ValueError, match="duplicate session dates"):
        load_snapshot("2026-09-07", tmp_path)


def test_real_snapshot_loads():
    """The real as-of=2026-09-22 snapshot parses and produces finite features."""
    if not REAL_SNAPSHOT.is_dir():
        pytest.skip("real data/market/bars/asof=2026-09-22 is not present")
    snap = load_snapshot("2026-09-22")
    assert "AAPL" in snap.tickers
    assert "SPY" in snap.tickers
    assert "QQQ" in snap.tickers
    assert len(snap.dates) > 2500
    assert np.all(snap.dates[1:] > snap.dates[:-1])
    _, _, x, valid = feature_matrix(snap)
    assert x.shape == (len(snap.dates) * len(snap.tickers), len(FEATURE_COLUMNS))
    assert valid.any()
    assert valid.shape == (len(snap.dates) * len(snap.tickers),)
    # AAPL has a full history, so its most recent row is fully valid.
    i = len(snap.dates) - 1
    j = snap.tickers.index("AAPL")
    assert valid[i * len(snap.tickers) + j]
    # Determinism holds on the real data too.
    _, _, x2, v2 = feature_matrix(snap)
    assert np.array_equal(x, x2, equal_nan=True)
    assert np.array_equal(valid, v2)
