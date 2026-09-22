"""Causal funded constant-exposure controls, independently tested.

These tests pin the boundary of `backend.market.allocation_controls`: the
causal fill contract (decide at the previous close, fill at the next open -
never same-close rebalancing), the funded ledger arithmetic (buys bounded by
the cash on hand, sells never exceeding what is held, one-way `cost_bps`,
zero cash yield), the adjusted-open scaling, and the aligned-price builder's
refusal of missing or unverifiable data. The tests are self-contained
(synthetic series and tmp_path parquet/npz files), so they run without the
cached inputs or any service; the reproduction of the authoritative cached
SPY/QQQ benchmark curves is a separate test that skips when that cache is
absent.
"""

from pathlib import Path

import numpy as np
import pytest

from backend.market import allocation_controls as controls

# The fixed conventions shared with the funded ledger.
COST_BPS = 10.0


# A small hand-checkable flat-price series for ledger arithmetic tests.
def _flat(n: int = 4, price: float = 100.0) -> tuple[np.ndarray, np.ndarray]:
    """Return (closes, opens) as a flat `n`-session series at `price`."""
    closes = np.full(n, price)
    opens = np.full(n, price)
    return closes, opens


# The reference reproduction's cached inputs, skipped when absent.
def _cached_inputs() -> tuple[Path, Path]:
    """Return (bars_dir, inputs_dir) of the trusted cache, or raise SkipTest."""
    bars_dir = Path("/home/animallya96/anios/data/market/bars/asof=2026-09-18")
    inputs_dir = Path("/tmp/codex-trading-evaluation-inputs-20260921")
    reference = inputs_dir / "common-window-reference.npz"
    if not bars_dir.is_dir() or not reference.is_file():
        pytest.skip("cached bars or benchmark reference npz is absent")
    return bars_dir, inputs_dir


# A fully cash account never moves, whatever the prices do.
def test_zero_fraction_stays_all_cash():
    closes, opens = _flat()
    nav = controls.constant_exposure(closes, opens, 0.0, cost_bps=COST_BPS)
    assert nav.shape == closes.shape
    assert nav[0] == pytest.approx(1.0)
    assert np.allclose(nav, 1.0)


# A flat price with a full-equity target pays the one-way cost exactly once.
def test_flat_prices_full_fraction_pays_cost_once():
    closes, opens = _flat()
    paid = controls.constant_exposure(closes, opens, 1.0, cost_bps=COST_BPS)
    free = controls.constant_exposure(closes, opens, 1.0, cost_bps=0.0)
    # Cost-free: the first buy fills the full target and the NAV stays 1.
    assert free[1] == pytest.approx(1.0)
    assert np.allclose(free, 1.0)
    # Costed: the account can only afford 1/(1+cost) of the full target out of
    # cash, so it holds that weight at a flat price and the NAV stays there.
    assert paid[1] == pytest.approx(1.0 / (1.0 + COST_BPS / 1e4))
    assert np.allclose(paid[1:], paid[1])


# A decision sized from a close must be filled at the NEXT open, never at the
# same close - a gap between them is part of the fill, not free information.
def test_fill_is_at_the_next_open_not_the_same_close():
    closes = np.array([100.0, 100.0])
    opens = np.array([100.0, 105.0])
    nav = controls.constant_exposure(closes, opens, 1.0, cost_bps=0.0)
    # Sized at close 100 for full equity, but the open is 105: cash buys only
    # 100/105 of the target. A same-close fill would have paid 100 and held
    # NAV 1; the causal account holds 100/105.
    assert nav[1] == pytest.approx(100.0 / 105.0)
    assert nav[1] != pytest.approx(1.0)


# A buy is bounded by the cash actually on hand: a gap-up open beyond cash is
# only partially filled, never borrowed against.
def test_buy_is_bounded_by_existing_cash():
    closes = np.array([100.0, 100.0])
    opens = np.array([100.0, 1000.0])
    nav = controls.constant_exposure(closes, opens, 1.0, cost_bps=0.0)
    # Cash 1.0 buys 0.001 shares at 1000; at the close they are worth 100.
    assert nav[1] == pytest.approx(0.1)


# After the asset rises, the account sells back to `fraction` at the next open,
# never below zero shares and never spending more cash than it has.
def test_sells_restore_exposure_and_never_exceed_held():
    closes = np.array([100.0, 200.0, 200.0])
    opens = np.array([100.0, 100.0, 200.0])
    nav = controls.constant_exposure(closes, opens, 0.5, cost_bps=0.0)
    assert nav[0] == pytest.approx(1.0)
    # First buy at open 100 (0.5 weight): 0.005 shares, cash 0.5. The close
    # at 200 makes the account 1.5.
    assert nav[1] == pytest.approx(1.5)
    # The rise to 200 makes the holding overweight; the next-open sell restores
    # the 0.5 weight: 0.00375 shares at 200 plus cash 0.75.
    assert nav[2] == pytest.approx(1.5)


# Over a deterministic varying series the ledger never goes negative: NAV is
# always finite positive and the shares/cash reconstruction stays sane.
def test_ledger_stays_finite_and_positive_over_varying_prices():
    rng = np.random.default_rng(7)
    closes = 100.0 * np.cumprod(1.0 + rng.normal(0.0004, 0.01, 120))
    opens = closes * (1.0 + rng.normal(0.0, 0.005, 120))
    for fraction in (0.25, 0.5, 1.0):
        nav = controls.constant_exposure(closes, opens, fraction, cost_bps=COST_BPS)
        assert np.isfinite(nav).all()
        assert (nav > 0).all()
        assert nav[0] == pytest.approx(1.0)


# The required public signature and argument validation.
def test_constant_exposure_validates_its_arguments():
    closes, opens = _flat()
    with pytest.raises(ValueError, match="fraction"):
        controls.constant_exposure(closes, opens, -0.1)
    with pytest.raises(ValueError, match="fraction"):
        controls.constant_exposure(closes, opens, 1.5)
    with pytest.raises(ValueError, match="cost_bps"):
        controls.constant_exposure(closes, opens, 0.5, cost_bps=-1.0)
    for invalid in (np.nan, np.inf, 10000.0):
        with pytest.raises(ValueError, match="cost_bps"):
            controls.constant_exposure(closes, opens, 0.5, cost_bps=invalid)
    with pytest.raises(ValueError, match="same sessions"):
        controls.constant_exposure(closes, opens[:2], 0.5)
    with pytest.raises(ValueError, match="at least two sessions"):
        controls.constant_exposure(closes[:1], opens[:1], 0.5)
    broken = closes.copy()
    broken[2] = np.nan
    with pytest.raises(ValueError, match="finite positive"):
        controls.constant_exposure(broken, opens, 0.5)
    with pytest.raises(ValueError, match="finite positive"):
        controls.constant_exposure(closes, opens * -1.0, 0.5)


# The adjusted open scales the raw open by the close's own adjustment, so a
# return across a corporate action stays one continuous price move.
def test_adjusted_open_scales_by_the_close_adjustment():
    raw_open = np.array([110.0, 55.0])
    raw_close = np.array([100.0, 50.0])
    adjusted_close = np.array([90.0, 100.0])
    adjusted = controls.adjusted_open(raw_open, raw_close, adjusted_close)
    assert adjusted[0] == pytest.approx(110.0 * 90.0 / 100.0)
    assert adjusted[1] == pytest.approx(55.0 * 100.0 / 50.0)


# A non-positive close yields NaN for that session, never a silent factor.
def test_adjusted_open_marks_unadjustable_closes_nan():
    raw_open = np.array([110.0, 55.0])
    raw_close = np.array([100.0, 0.0])
    adjusted_close = np.array([90.0, 80.0])
    adjusted = controls.adjusted_open(raw_open, raw_close, adjusted_close)
    assert adjusted[0] == pytest.approx(110.0 * 90.0 / 100.0)
    assert np.isnan(adjusted[1])
    with pytest.raises(ValueError, match="shape"):
        controls.adjusted_open(raw_open, raw_close, adjusted_close[:1])


# The builder writes a separate aligned adjusted-opens npz and records hashes.
def test_build_adjusted_opens_writes_aligned_npz_and_hashes(tmp_path):
    bars = tmp_path / "bars"
    bars.mkdir()
    dates = np.array(
        ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        dtype="datetime64[D]",
    )
    for ticker in ("SPY", "QQQ"):
        _write_bar_partition(bars / f"{ticker}.parquet", dates, ticker)
    benchmark = tmp_path / "benchmark.npz"
    np.savez(
        benchmark,
        dates=dates,
        SPY=_adj_close(dates, "SPY"),
        QQQ=_adj_close(dates, "QQQ"),
    )
    out = tmp_path / "adjusted-opens.npz"
    hashes = tmp_path / "hashes.json"
    evidence = controls.build_adjusted_opens(bars, benchmark, out, hashes)
    assert Path(evidence["out_path"]) == out
    assert evidence["sessions"] == len(dates)
    assert evidence["calendar_match"] is True
    assert evidence["adjusted_close_match"] is True
    saved = np.load(out)
    assert np.array_equal(saved["dates"], dates)
    expected = controls.adjusted_open(
        _raw_open(dates, "SPY"), _raw_close(dates, "SPY"), _adj_close(dates, "SPY")
    )
    assert np.allclose(saved["SPY"], expected)
    assert set(evidence["hashes"]) == {
        "SPY.parquet",
        "QQQ.parquet",
        "benchmark_npz",
        "adjusted_opens_npz",
    }
    assert all(len(h) == 64 for h in evidence["hashes"].values())
    recorded = Path(hashes).read_text(encoding="utf-8")
    assert "adjusted_opens_npz" in recorded
    original = benchmark.read_bytes()
    for target, sidecar in ((benchmark, hashes), (out, hashes), (hashes, benchmark)):
        with pytest.raises(ValueError, match="overwrite"):
            controls.build_adjusted_opens(bars, benchmark, target, sidecar)
    assert benchmark.read_bytes() == original


# The builder refuses missing inputs, missing npz fields and tampered bars.
def test_build_adjusted_opens_refuses_missing_or_mismatched_data(tmp_path):
    bars = tmp_path / "bars"
    bars.mkdir()
    dates = np.array(["2024-01-02", "2024-01-03"], dtype="datetime64[D]")
    _write_bar_partition(bars / "SPY.parquet", dates, "SPY")
    benchmark = tmp_path / "benchmark.npz"
    np.savez(
        benchmark,
        dates=dates,
        SPY=_adj_close(dates, "SPY"),
        QQQ=_adj_close(dates, "QQQ"),
    )
    with pytest.raises(ValueError, match="missing"):
        controls.build_adjusted_opens(bars, benchmark, tmp_path / "a.npz")  # no QQQ bar
    missing = tmp_path / "nonexistent.npz"
    with pytest.raises(ValueError, match="missing"):
        controls.build_adjusted_opens(bars, missing, tmp_path / "b.npz")
    _write_bar_partition(bars / "QQQ.parquet", dates, "QQQ")
    dropped = tmp_path / "dropped.npz"
    np.savez(dropped, dates=dates, SPY=_adj_close(dates, "SPY"))
    with pytest.raises(ValueError, match="must hold"):
        controls.build_adjusted_opens(bars, dropped, tmp_path / "c.npz")
    tampered = tmp_path / "tampered.npz"
    np.savez(
        tampered,
        dates=dates,
        SPY=_adj_close(dates, "SPY") * 1.01,
        QQQ=_adj_close(dates, "QQQ"),
    )
    with pytest.raises(ValueError, match="do not match"):
        controls.build_adjusted_opens(bars, tampered, tmp_path / "d.npz")


# The causal control reproduces the authoritative cached SPY/QQQ benchmark
# curves exactly over the fixed common window (NAV 1, next-open fills, 10 bps,
# zero cash interest). Skipped when the trusted cache is absent.
def test_constant_exposure_reproduces_cached_benchmark_curves():
    bars_dir, inputs_dir = _cached_inputs()
    reference = np.load(inputs_dir / "common-window-reference.npz")
    common_dates = reference["dates"]
    for ticker, field in (("SPY", "spy_equity"), ("QQQ", "qqq_equity")):
        dates, opens, closes, adjusted = controls._read_bar_partition(
            bars_dir / f"{ticker}.parquet"
        )
        lo = int(np.where(dates == common_dates[0])[0][0])
        hi = int(np.where(dates == common_dates[-1])[0][0]) + 1
        slice_dates = dates[lo:hi]
        assert np.array_equal(slice_dates, common_dates)
        scaled = controls.adjusted_open(opens, closes, adjusted)[lo:hi]
        nav = controls.constant_exposure(
            adjusted[lo:hi], scaled, 1.0, cost_bps=COST_BPS
        )
        assert np.allclose(nav, reference[field], rtol=1e-12, atol=1e-12)


# --------------------------------------------------------------------------- #
# Synthetic bar helpers (shared by the builder tests).
# --------------------------------------------------------------------------- #


# Produce reproducible raw opens for the synthetic partitions.
def _raw_open(dates: np.ndarray, ticker: str) -> np.ndarray:
    """Return a deterministic synthetic raw-open series for `ticker`."""
    seed = 1 if ticker == "SPY" else 2
    rng = np.random.default_rng(seed)
    return 100.0 * np.cumprod(1.0 + 0.001 * rng.normal(size=len(dates)))


# Produce synthetic closes with a fixed intraday move.
def _raw_close(dates: np.ndarray, ticker: str) -> np.ndarray:
    """Return a deterministic synthetic raw-close series for `ticker`."""
    return _raw_open(dates, ticker) * (1.0 + 0.002)


# Apply a fixed corporate-action adjustment in the synthetic partition.
def _adj_close(dates: np.ndarray, ticker: str) -> np.ndarray:
    """Return a deterministic synthetic adjusted-close series for `ticker`."""
    return _raw_close(dates, ticker) * 0.9


# Write one synthetic cached bar partition (date, OHLC, adjusted close).
def _write_bar_partition(path: Path, dates: np.ndarray, ticker: str) -> None:
    """Write a synthetic daily-bar parquet with the fields the builder reads."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    opens = _raw_open(dates, ticker)
    closes = _raw_close(dates, ticker)
    table = pa.table(
        {
            "session_date": np.asarray(dates, dtype="datetime64[D]").astype(
                "datetime64[us]"
            ),
            "open": opens,
            "high": np.maximum(opens, closes) * 1.005,
            "low": np.minimum(opens, closes) * 0.995,
            "close": closes,
            "adjusted_close": _adj_close(dates, ticker),
            "volume": np.full(len(dates), 1_000_000, dtype=np.int64),
        }
    )
    pq.write_table(table, path)
