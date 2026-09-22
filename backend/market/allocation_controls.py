"""Causal funded constant-exposure controls and their aligned-price builder.

The desk's funded allocation path is a daily decision: it decides from the
previous close and fills at the next open, pays 10 bps one way, funds buys
from the cash actually on hand and pays nothing on idle cash. A benchmark that
claims to share those conventions must obey the same causality, which is what
`constant_exposure` does. It is the exposure-matched hindsight diagnostic's
causal replacement: the existing `constant_equity_account` rebalances at the
same price it sizes from, so a decision made at a close is paid at that close
- the "same-close rebalancing disguised as next-open" this module refuses.

`constant_exposure(closes, opens, fraction, cost_bps)` walks a funded ledger
(shares plus cash) exactly the way `simulate._Book` does for the funded
candidate, for one benchmark asset:

* a decision on session t uses only t's close - the account's value and the
  target weight `fraction` are read at `closes[t]`, never at the fill price,
* the order is filled at session t+1's open with `cost_bps` charged one way,
* a buy is sized from the cash actually on hand, never from the same session's
  sale proceeds, and a sell never exceeds what is held,
* idle cash earns nothing (zero cash yield) and the NAV starts at 1.

Reproduced from the independently produced common-window reference, this
function reproduces the authoritative SPY and QQQ benchmark curves exactly
(NAV 1 at the window start, first fill at the first next open, 10 bps, zero
cash interest) to float precision, which is what makes it a control rather
than another estimate.

The module also owns the builder for the aligned `adjusted-opens` price
history. The cached daily bars store raw OHLC plus an adjusted close, and an
opening price must be scaled by the same factor that turns the close into the
adjusted close, so a return from one to the other never straddles a split or
a dividend (the same rule `simulate.adjusted_open` applies to a panel).
`build_adjusted_opens` reads the cached SPY/QQQ parquet bars, verifies the
dates and adjusted closes against the trusted benchmark price npz, records the
source hashes and writes a separate `{dates, SPY, QQQ}` adjusted-opens npz. It
refuses missing or unverifiable data and never overwrites an input file.

This is a diagnostic and a data construction tool only. It runs no candidate,
trains nothing, and promotes nothing; the evaluation role consumes its
artifacts as controls.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

# The fixed conventions the funded ledger and its controls share.
COST_BPS = 10.0
START_EQUITY = 1.0
SPY = "SPY"
QQQ = "QQQ"
TICKERS = (SPY, QQQ)


# Validate one price series shape and completeness, or raise.
def _validate_prices(name: str, values) -> np.ndarray:
    """Return the finite positive one-dimensional series, or raise ValueError."""
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be a one-dimensional series")
    if not len(arr):
        raise ValueError(f"{name} must not be empty")
    if not np.isfinite(arr).all() or not (arr > 0).all():
        raise ValueError(
            f"{name} must be complete finite positive prices; "
            "a missing price is refused, never filled"
        )
    return arr


# Scale an opening price by the same factor that turns the close into the
# adjusted close, so a return from one to the other never crosses a corporate
# action. This is the array-level form of `simulate.adjusted_open`.
def adjusted_open(open_prices, close_prices, adjusted_close) -> np.ndarray:
    """Return opening prices on the same adjusted basis as the closes.

    Each open is scaled by `adjusted_close / close`; a non-positive or missing
    close yields NaN, which the caller's completeness checks then refuse. The
    same adjustment the close carries is what makes an open-to-close return a
    single continuous price move.
    """
    open_prices = np.asarray(open_prices, dtype=float)
    close_prices = np.asarray(close_prices, dtype=float)
    adjusted_close = np.asarray(adjusted_close, dtype=float)
    if not (open_prices.shape == close_prices.shape == adjusted_close.shape):
        raise ValueError("open, close and adjusted_close must share a shape")
    with np.errstate(all="ignore"):
        factor = np.where(close_prices > 0, adjusted_close / close_prices, np.nan)
    return open_prices * factor


# Walk one funded constant-`fraction` account over the whole series.
def constant_exposure(
    closes, opens, fraction, cost_bps: float = COST_BPS
) -> np.ndarray:
    """Return the NAV series of a funded constant-`fraction` account.

    NAV 1 all in cash on the first session; each session from the second the
    account buys or sells toward holding `fraction` of its equity in the
    benchmark. The target is sized from the previous session's close and
    filled at the next session's open at `cost_bps` one way - never sized and
    filled at the same close, and never sized at the fill price. Buys are
    bounded by the cash actually on hand (no same-session sale proceeds) and
    sells never exceed what is held; idle cash earns nothing. The result is a
    (T,) NAV array starting at 1, aligned to `closes`.
    """
    fraction = float(fraction)
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be a fraction in [0, 1]")
    cost_bps = float(cost_bps)
    if not np.isfinite(cost_bps) or not 0 <= cost_bps < 1e4:
        raise ValueError("cost_bps must be finite and in [0, 10000)")
    cost = cost_bps / 1e4
    closes = _validate_prices("closes", closes)
    opens = _validate_prices("opens", opens)
    if len(closes) != len(opens):
        raise ValueError("closes and opens must cover the same sessions")
    if len(closes) < 2:
        raise ValueError("constant_exposure needs at least two sessions")
    shares = 0.0
    cash = START_EQUITY
    nav = np.full(len(closes), np.nan)
    nav[0] = cash
    for t in range(len(closes) - 1):
        # The decision is made at t's close, from the value the close gives
        # the account; the fill is at t+1's open.
        price = float(closes[t])
        current = shares * price + cash
        target_shares = fraction * current / price
        delta = target_shares - shares
        fill = float(opens[t + 1])
        if delta > 0:
            spend = delta * fill * (1.0 + cost)
            scale = min(1.0, max(0.0, cash) / spend) if spend > 0 else 0.0
            bought = delta * scale
            cash -= bought * fill * (1.0 + cost)
            shares += bought
        elif delta < 0:
            sold = min(-delta, shares)
            cash += sold * fill * (1.0 - cost)
            shares -= sold
        nav[t + 1] = shares * float(closes[t + 1]) + cash
    return nav


# Read one cached daily-bar parquet partition into aligned numpy arrays.
def _read_bar_partition(
    path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (dates, open, close, adjusted_close) from a cached parquet file."""
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - pyarrow is a dependency
        raise RuntimeError("pyarrow is required to read the cached daily bars") from exc
    table = pq.read_table(path)
    required = {"session_date", "open", "close", "adjusted_close"}
    missing = required - set(table.column_names)
    if missing:
        raise ValueError(f"{path} must hold columns: {sorted(missing)}")
    dates = np.asarray(table.column("session_date").to_pylist(), dtype="datetime64[D]")
    opens = np.asarray(table.column("open"), dtype=float)
    closes = np.asarray(table.column("close"), dtype=float)
    adjusted = np.asarray(table.column("adjusted_close"), dtype=float)
    return dates, opens, closes, adjusted


# Verify one bar partition against the trusted benchmark price npz.
def _verify_bars_against_cache(
    ticker: str,
    dates: np.ndarray,
    adjusted: np.ndarray,
    cache_dates: np.ndarray,
    cache_prices: np.ndarray,
) -> None:
    """Raise ValueError when the bars' dates or adjusted closes disagree."""
    if len(dates) != len(cache_dates) or not np.array_equal(dates, cache_dates):
        raise ValueError(
            f"{ticker} bars and the benchmark cache calendars disagree; "
            "the adjusted-opens build is refused rather than re-aligned"
        )
    if not np.allclose(adjusted, cache_prices, rtol=1e-9, atol=1e-12):
        raise ValueError(
            f"{ticker} adjusted closes do not match the trusted benchmark cache; "
            "the adjusted-opens build is refused rather than built from "
            "unverified bars"
        )


# Hash one file and return its hex sha256.
def _sha256(path: Path) -> str:
    """Return the sha256 hex digest of the file at `path`."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Load and validate the trusted benchmark price npz for the given tickers.
def _load_benchmark_cache(
    benchmark_npz: Path, tickers: tuple[str, ...]
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Return (dates, {ticker: adjusted close}) from `benchmark_npz`, or raise."""
    with np.load(benchmark_npz, allow_pickle=False) as cache:
        missing_fields = [k for k in ("dates", *tickers) if k not in cache.files]
        if missing_fields:
            raise ValueError(f"{benchmark_npz} must hold: {sorted(missing_fields)}")
        cache_dates = np.asarray(cache["dates"])
        cache_prices = {
            ticker: np.asarray(cache[ticker], dtype=float) for ticker in tickers
        }
    if cache_dates.dtype.kind != "M":
        raise ValueError("benchmark cache dates must be datetime64")
    if len(np.unique(cache_dates)) != len(cache_dates) or not np.all(
        cache_dates[1:] > cache_dates[:-1]
    ):
        raise ValueError("benchmark cache dates must be unique and ascending")
    return cache_dates, cache_prices


# Read and verify one ticker's bar partition, returning its adjusted opens.
def _ticker_adjusted_opens(
    bars_dir: Path,
    ticker: str,
    cache_dates: np.ndarray,
    cache_prices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, str]:
    """Return (dates, adjusted opens, parquet hash) for `ticker`, or raise."""
    bar_path = bars_dir / f"{ticker}.parquet"
    if not bar_path.is_file():
        raise ValueError(f"cached bar missing: {bar_path}")
    dates, opens, closes, adjusted = _read_bar_partition(bar_path)
    _verify_bars_against_cache(ticker, dates, adjusted, cache_dates, cache_prices)
    scaled = adjusted_open(opens, closes, adjusted)
    if not np.isfinite(scaled).all() or not (scaled > 0).all():
        raise ValueError(
            f"{ticker} adjusted opens are incomplete; "
            "the build is refused rather than filled"
        )
    return dates, scaled, _sha256(bar_path)


# Build and verify the aligned adjusted-opens npz from the cached bars.
def build_adjusted_opens(  # noqa: C901 - explicit refusal order, like the store
    bars_dir: str | Path,
    benchmark_npz: str | Path,
    out_path: str | Path,
    hashes_path: str | Path | None = None,
    tickers: tuple[str, ...] = TICKERS,
) -> dict[str, object]:
    """Return verification evidence and write `{dates, SPY, QQQ}` adjusted opens.

    Reads `<tickers>.parquet` from `bars_dir` (the cached as-of bar partition),
    scales each raw open by `adjusted_close / close`, and verifies that the
    bars' session calendar and adjusted closes reproduce the trusted benchmark
    price npz at `benchmark_npz` exactly before writing the separate aligned
    adjusted-opens npz at `out_path`. The source hashes (each bar partition,
    the benchmark npz and the written output) are recorded in a sidecar JSON at
    `hashes_path` when given and always returned in the evidence dict. A
    missing file, a missing npz field or any dates/adjusted-close mismatch is
    refused with ValueError; input files are never overwritten.
    """
    bars_dir = Path(bars_dir)
    benchmark_npz = Path(benchmark_npz)
    out_path = Path(out_path)
    protected = {benchmark_npz.resolve()}
    protected.update((bars_dir / f"{ticker}.parquet").resolve() for ticker in tickers)
    outputs = [out_path]
    if hashes_path is not None:
        outputs.append(Path(hashes_path))
    if len({p.resolve() for p in outputs}) != len(outputs):
        raise ValueError("output paths must be distinct")
    if any(p.resolve() in protected or p.exists() for p in outputs):
        raise ValueError("refusing to overwrite an input or existing output")
    if not bars_dir.is_dir():
        raise ValueError(f"bars directory missing: {bars_dir}")
    if not benchmark_npz.is_file():
        raise ValueError(f"benchmark price npz missing: {benchmark_npz}")
    cache_dates, cache_prices = _load_benchmark_cache(benchmark_npz, tickers)

    adjusted_opens: dict[str, np.ndarray] = {}
    hashes: dict[str, str] = {}
    bar_dates: np.ndarray | None = None
    for ticker in tickers:
        dates, scaled, bar_hash = _ticker_adjusted_opens(
            bars_dir, ticker, cache_dates, cache_prices[ticker]
        )
        if bar_dates is None:
            bar_dates = dates
        elif not np.array_equal(bar_dates, dates):
            raise ValueError(f"{ticker} bar calendar disagrees with the first ticker")
        adjusted_opens[ticker] = scaled
        hashes[f"{ticker}.parquet"] = bar_hash
    hashes["benchmark_npz"] = _sha256(benchmark_npz)
    if bar_dates is None:
        raise ValueError("no ticker bar partition was read")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("xb") as handle:
        np.savez(
            handle,
            dates=bar_dates,
            **{ticker: adjusted_opens[ticker] for ticker in tickers},
        )
    hashes["adjusted_opens_npz"] = _sha256(out_path)
    evidence: dict[str, object] = {
        "out_path": str(out_path),
        "sessions": int(len(bar_dates)),
        "dates_from": str(bar_dates[0]),
        "dates_to": str(bar_dates[-1]),
        "tickers": list(tickers),
        "verified_against": str(benchmark_npz),
        "calendar_match": bool(np.array_equal(bar_dates, cache_dates)),
        "adjusted_close_match": True,
        "hashes": hashes,
    }
    if hashes_path is not None:
        Path(hashes_path).write_text(
            json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8"
        )
    return evidence
