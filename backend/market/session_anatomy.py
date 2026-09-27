"""Session anatomy: how the 26 fifteen-minute bars build the daily bar.

The first study on the consolidated SIP store (`intraday_sip`, cubes from
`sip_cube`). It asks, for the names the book could have held on each
session (the dated membership, `point_in_time.eligibility`), how a
session's variance, extremes and return are distributed across the day,
and whether what has happened by mid-morning says anything about the
rest of the day. Nothing here trades, ranks or sizes; the output is the
shape of the day, with counts, so the fifteen-minute engine's later
questions (when to fill, whether to wait for a dip) are asked against
measured structure rather than lore.

Hypotheses, written before any number exists (2026-09-27):

H1 (variance, A). The share of the session's squared bar returns is
    U-shaped across the 26 slots: the first slot (09:30-09:45) carries the
    largest share, the last (15:45-16:00) the second largest, and the
    midday slots the least. The session high and low are set in the first
    two or last two slots far more often than the 4/26 a uniform day
    would give.
H2 (open drive, B). The first half-hour's return (open to the 10:00
    close, `r1`) carries no usable information about the rest of the
    session (`r_rest`, 10:00 close to 16:00 close) at the pooled level:
    the slope of `r_rest` on `r1` on the daily cross-sectional averages
    is within noise of zero (|t| < 2 at HAC lag 5 on 2016-2023). A
    negative slope would be intraday reversal, a positive one
    continuation; either is recorded, not acted on.
H3 (dips and extensions, C). Conditioning on a drawdown from the open of
    at least 1/2/3% by 10:30, 11:30 or 12:45 does not change the expected
    return from that bar's close to the session close by more than the
    spread of bar-by-bar noise; the same for run-ups. That is, the
    conditional-minus-unconditional differences are within |t| < 2 on
    the choosing window. Any cell outside that on 2016-2023 is a lead to
    re-test on 2024-2026, never a rule.
H4 (execution, D). Buying at the first hour's volume-weighted price costs
    less than buying at the open on a median session (the open bar is the
    widest), and the session VWAP sits between the open and the close in
    expectation; the standard deviation of open-to-close across the book
    is the scale every fill-timing idea has to beat.

Discipline. The choosing window is 2016-2023; 2024-2026 is reported and
never tuned on. Quintile edges for the open-drive table come from the
choosing window only and are applied unchanged to the later one. The
thresholds and check slots are fixed here before the run. Names are
pooled equally (one row per session per name), restricted to sessions
where the name was a book member; SPY, QQQ, SMH and IGV are reported
separately as benchmarks and never pooled with the book.

Statistics. Every t-statistic is computed on the daily cross-sectional
average series, never on the pooled rows: on a given date the book's
names move together, so N names on one date are closer to one
observation than to N, and a pooled t overstates the evidence by a factor
that grows with the book's correlation. The daily series is then serially
dependent as well, so its t is Newey-West at lag `HAC_LAG`
(`candidate_stats.hac_t`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

import numpy as np

from backend.market.candidate_stats import hac_t
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

# Study version, carried in the payload.
STUDY_VERSION = 1
# The four names reported separately, never pooled with the book.
BENCHMARKS = ("SPY", "QQQ", "SMH", "IGV")
# The choosing window and the reported-only window, [start, end).
WINDOWS: dict[str, tuple[date, date | None]] = {
    "2016-2023": (date(2016, 1, 1), date(2024, 1, 1)),
    "2024-2026": (date(2024, 1, 1), None),
}
CHOOSING_WINDOW = "2016-2023"
# The open drive is the first two bars: open_0 to the close of slot 1 (10:00).
OPEN_DRIVE_END_SLOT = 1
# Bar closes at which a dip or extension from the open is checked:
# 10:30, 11:30 and 12:45.
CHECK_SLOTS = (3, 7, 12)
# Drawdown-from-open thresholds (log), and run-up thresholds.
DIP_THRESHOLDS = (-0.01, -0.02, -0.03)
EXT_THRESHOLDS = (0.01, 0.02, 0.03)
# The first hour is the first four slots (09:30-10:30).
FIRST_HOUR_SLOTS = 4
# Quantile bins for the conditional-mean table.
QUINTILES = 5
# Newey-West lag for every t on a daily series.
HAC_LAG = 5
# A t on fewer contributing dates than this is not reported (NaN): a HAC
# variance on a handful of dates is noise dressed as a statistic. The
# count is always reported beside it.
MIN_CELL_DATES = 30
# Slots reported by name in the rendered table: the first two and last two.
EDGE_SLOTS = (0, 1, FULL_SESSION_SLOTS - 2, FULL_SESSION_SLOTS - 1)
# Basis points per unit log return, for reporting.
BP = 1e4

# A membership mask: a callable (ticker, dates) -> (N,) bool, or a mapping
# from ticker to the dates (datetime64[D] array, or a set of dates) on
# which the name was a member. Benchmarks bypass it.
MaskByDate = Callable[[str, np.ndarray], np.ndarray] | Mapping[str, Any]


# Log return of each bar's close on the previous close, with slot 0 on
# the session's open: (N, 26).
def bar_returns(cube: SessionCube) -> np.ndarray:
    """Return (N, 26) log returns close_k / close_{k-1}, slot 0 on open_0."""
    if len(cube) == 0:
        return np.zeros((0, FULL_SESSION_SLOTS))
    previous = np.column_stack([cube.open[:, :1], cube.close[:, :-1]])
    return np.log(cube.close / previous)


# The session's open-to-close log return: (N,).
def session_return(cube: SessionCube) -> np.ndarray:
    """Return log(close_25 / open_0) per session."""
    if len(cube) == 0:
        return np.zeros(0)
    return np.log(cube.close[:, -1] / cube.open[:, 0])


# The overnight gap into the session on the session's own raw basis: (N,).
def gap(cube: SessionCube) -> np.ndarray:
    """Return log(open_0 / prior_close) per session."""
    if len(cube) == 0:
        return np.zeros(0)
    return np.log(cube.open[:, 0] / cube.prior_close)


# A. Share of the summed squared bar returns by slot, over all rows: (26,).
def variance_shares(cube: SessionCube) -> np.ndarray:
    """Return the (26,) share of squared bar returns by slot; sums to 1."""
    return _variance_shares(bar_returns(cube))


# The variance shares of a (rows, 26) bar-return matrix; NaN when empty.
def _variance_shares(returns: np.ndarray) -> np.ndarray:
    if returns.shape[0] == 0:
        return np.full(FULL_SESSION_SLOTS, np.nan)
    squared = (returns**2).sum(axis=0)
    total = float(squared.sum())
    if total <= 0:
        return np.full(FULL_SESSION_SLOTS, np.nan)
    return squared / total


# A. Where the session's high and low are set: two (26,) histograms of the
# first slot holding the session high and the session low.
def extreme_slot_shares(cube: SessionCube) -> tuple[np.ndarray, np.ndarray]:
    """Return (high shares, low shares), each (26,) and summing to 1."""
    return _extreme_slot_shares(cube.high, cube.low)


# The histograms of the argmax of `high` and argmin of `low` by row.
def _extreme_slot_shares(
    high: np.ndarray, low: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    if high.shape[0] == 0:
        empty = np.full(FULL_SESSION_SLOTS, np.nan)
        return empty, empty.copy()
    high_slot = np.bincount(high.argmax(axis=1), minlength=FULL_SESSION_SLOTS)
    low_slot = np.bincount(low.argmin(axis=1), minlength=FULL_SESSION_SLOTS)
    return high_slot / high.shape[0], low_slot / low.shape[0]


# B. The open drive r1 = log(close_1 / open_0) and the rest of the
# session r_rest = log(close_25 / close_1): two (N,) arrays.
def open_drive(cube: SessionCube) -> tuple[np.ndarray, np.ndarray]:
    """Return (r1, r_rest) per session."""
    if len(cube) == 0:
        return np.zeros(0), np.zeros(0)
    r1 = np.log(cube.close[:, OPEN_DRIVE_END_SLOT] / cube.open[:, 0])
    rest = np.log(cube.close[:, -1] / cube.close[:, OPEN_DRIVE_END_SLOT])
    return r1, rest


# Quantile edges of `x` at the interior quintile points, from the
# choosing window only; the caller passes them into `conditional_means`.
def quintile_edges(x: np.ndarray, bins: int = QUINTILES) -> np.ndarray:
    """Return the (bins - 1,) interior edges of `x`'s quantile bins."""
    v = np.asarray(x, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < bins:
        return np.full(bins - 1, np.nan)
    return np.quantile(v, np.arange(1, bins) / bins)


# The bin index of every x under `edges` (bins - 1 interior edges).
def _bin_of(x: np.ndarray, edges: np.ndarray) -> np.ndarray:
    return np.searchsorted(
        np.asarray(edges, dtype=float), np.asarray(x, dtype=float), side="right"
    )


# B. Mean of y by bin of x under fixed edges, with the count, the mean
# of x in the bin, and a t on the daily average of y within the bin when
# `dates` is given (each date's members in the bin averaged first).
def conditional_means(
    x: np.ndarray,
    y: np.ndarray,
    edges: np.ndarray,
    dates: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Return one record per bin: bin, lo, hi, n, mean_x, mean_y, t, dates."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    edges = np.asarray(edges, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    bins = _bin_of(x, edges)
    out = []
    for b in range(len(edges) + 1):
        rows = ok & (bins == b)
        lo = float(edges[b - 1]) if b > 0 else -math.inf
        hi = float(edges[b]) if b < len(edges) else math.inf
        record: dict[str, Any] = {
            "bin": b,
            "lo": lo,
            "hi": hi,
            "n": int(rows.sum()),
            "mean_x": float(x[rows].mean()) if rows.any() else math.nan,
            "mean_y": float(y[rows].mean()) if rows.any() else math.nan,
            "t": math.nan,
            "dates": 0,
        }
        if dates is not None and rows.any():
            daily = daily_average(dates[rows], y[rows])
            record["t"] = _daily_t(daily)
            record["dates"] = int(len(daily))
        out.append(record)
    return out


# The Newey-West t of the mean of a daily series, NaN below MIN_CELL_DATES.
def _daily_t(daily: np.ndarray) -> float:
    if len(daily) < MIN_CELL_DATES:
        return math.nan
    return hac_t(daily, HAC_LAG)


# The cross-sectional average of `values` on each distinct date, in date
# order: one number per date that has at least one row.
def daily_average(dates: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Return the per-date mean of `values`, ascending by date."""
    days = np.asarray(dates, dtype="datetime64[D]")
    v = np.asarray(values, dtype=float)
    if len(days) == 0:
        return np.zeros(0)
    unique, inverse = np.unique(days, return_inverse=True)
    sums = np.bincount(inverse, weights=v, minlength=len(unique))
    counts = np.bincount(inverse, minlength=len(unique))
    return sums / counts


# The OLS slope of y on x and its Newey-West t at `lag`, with `hac_t`
# reused exactly rather than approximated: the score of the slope is
# s_t = xc_t * e_t (xc the centred x, e the OLS residual), which has mean
# zero, and beta = sum(xc * y) / sum(xc^2). Adding the constant
# beta * mean(xc^2) to s_t gives a series whose mean is that constant and
# whose centred values are s_t, so hac_t of it is
# beta * mean(xc^2) / sqrt(LRV(s) / n) = beta * sum(xc^2) / sqrt(n LRV(s)),
# which is the HAC t of the slope. Returns (slope, t, n).
def slope_hac_t(
    x: np.ndarray, y: np.ndarray, lag: int = HAC_LAG
) -> tuple[float, float, int]:
    """Return (OLS slope of y on x, its Newey-West t at `lag`, rows used)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    n = len(x)
    if n < 3:
        return math.nan, math.nan, n
    xc = x - x.mean()
    sxx = float(xc @ xc)
    if sxx <= 0:
        return math.nan, math.nan, n
    beta = float(xc @ (y - y.mean())) / sxx
    residual = (y - y.mean()) - beta * xc
    score = xc * residual + beta * sxx / n
    return beta, hac_t(score, lag), n


# C. For every check slot: the drawdown and run-up from the open through
# that slot's close, and the return from that close to the session close.
# Returns {slot: (drawdown, runup, forward)}, each (N,).
def dips_and_extensions(
    cube: SessionCube,
) -> dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Return per check slot the (drawdown_k, runup_k, forward_k) arrays."""
    out = {}
    if len(cube) == 0:
        for k in CHECK_SLOTS:
            out[k] = (np.zeros(0), np.zeros(0), np.zeros(0))
        return out
    path = np.log(cube.close / cube.open[:, :1])  # log(close_j / open_0)
    running_min = np.minimum.accumulate(path, axis=1)
    running_max = np.maximum.accumulate(path, axis=1)
    for k in CHECK_SLOTS:
        forward = np.log(cube.close[:, -1] / cube.close[:, k])
        out[k] = (running_min[:, k], running_max[:, k], forward)
    return out


# C. One cell of the dip/extension table: the mean forward return of the
# rows where `condition` holds minus the unconditional mean over all
# rows, with the row count, the number of dates with a qualifying row,
# and a t on the daily cross-sectional average of the difference (a date
# contributes when at least one name qualifies). The unconditional mean
# is treated as known; with thousands of rows its own error is small
# beside the conditional cell's.
def conditional_difference(
    dates: np.ndarray, forward: np.ndarray, condition: np.ndarray
) -> dict[str, Any]:
    """Return {n, dates, difference, unconditional_mean, conditional_mean, t}."""
    forward = np.asarray(forward, dtype=float)
    ok = np.isfinite(forward)
    condition = np.asarray(condition, dtype=bool) & ok
    unconditional = float(forward[ok].mean()) if ok.any() else math.nan
    n = int(condition.sum())
    if n == 0:
        return {
            "n": 0,
            "dates": 0,
            "difference": math.nan,
            "unconditional_mean": unconditional,
            "conditional_mean": math.nan,
            "t": math.nan,
        }
    conditional = float(forward[condition].mean())
    daily = daily_average(dates[condition], forward[condition] - unconditional)
    return {
        "n": n,
        "dates": int(len(daily)),
        "difference": conditional - unconditional,
        "unconditional_mean": unconditional,
        "conditional_mean": conditional,
        "t": _daily_t(daily),
    }


# D. Fill costs against the open: log(vwap_first_hour / open_0),
# log(vwap_session / open_0) and log(close_25 / open_0), where the VWAP
# is a proxy built from bar closes weighted by bar volume (the store has
# no per-bar VWAP; a bar's close is its last print, not its average).
# Returns {"first_hour_vwap", "session_vwap", "close"}, each (N,).
def fill_costs(cube: SessionCube) -> dict[str, np.ndarray]:
    """Return per-session log fill costs of three windows against the open."""
    if len(cube) == 0:
        return {k: np.zeros(0) for k in ("first_hour_vwap", "session_vwap", "close")}
    open0 = cube.open[:, 0]
    return {
        "first_hour_vwap": np.log(
            _vwap(cube.close[:, :FIRST_HOUR_SLOTS], cube.volume[:, :FIRST_HOUR_SLOTS])
            / open0
        ),
        "session_vwap": np.log(_vwap(cube.close, cube.volume) / open0),
        "close": np.log(cube.close[:, -1] / open0),
    }


# Volume-weighted mean of `price` by row; NaN when a row has no volume.
def _vwap(price: np.ndarray, volume: np.ndarray) -> np.ndarray:
    total = volume.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(total > 0, (price * volume).sum(axis=1) / total, np.nan)


# Mean, median, standard deviation and count of a series, NaN when empty.
def _moments(values: np.ndarray) -> dict[str, float | int]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return {"mean": math.nan, "median": math.nan, "std": math.nan, "n": 0}
    return {
        "mean": float(v.mean()),
        "median": float(np.median(v)),
        "std": float(v.std(ddof=1)) if len(v) > 1 else math.nan,
        "n": int(len(v)),
    }


# The (N,) membership of one cube's dates under the mask.
def _member_rows(mask: MaskByDate, ticker: str, dates: np.ndarray) -> np.ndarray:
    if callable(mask):
        return np.asarray(mask(ticker, dates), dtype=bool)
    member = mask.get(ticker)
    if member is None:
        return np.zeros(len(dates), dtype=bool)
    if isinstance(member, np.ndarray):
        return np.isin(dates.astype("datetime64[D]"), member.astype("datetime64[D]"))
    wanted = {np.datetime64(d, "D") for d in member}
    return np.array([d in wanted for d in dates.astype("datetime64[D]")], dtype=bool)


# Sessions inside [start, end) as a mask over `dates`.
def _window_rows(dates: np.ndarray, start: date | None, end: date | None) -> np.ndarray:
    days = np.asarray(dates, dtype="datetime64[D]")
    out = np.ones(len(days), dtype=bool)
    if start is not None:
        out &= days >= np.datetime64(start, "D")
    if end is not None:
        out &= days < np.datetime64(end, "D")
    return out


# Everything one cube contributes, per row, so the study can pool rows
# across names before any statistic is taken.
def _rows(cube: SessionCube, keep: np.ndarray) -> dict[str, np.ndarray]:
    r1, rest = open_drive(cube)
    costs = fill_costs(cube)
    checks = dips_and_extensions(cube)
    out: dict[str, np.ndarray] = {
        "dates": cube.dates[keep],
        "bar_returns": bar_returns(cube)[keep],
        "high": cube.high[keep],
        "low": cube.low[keep],
        "gap": gap(cube)[keep],
        "session_return": session_return(cube)[keep],
        "r1": r1[keep],
        "r_rest": rest[keep],
    }
    for name, values in costs.items():
        out[f"cost_{name}"] = values[keep]
    for k, (drawdown, runup, forward) in checks.items():
        out[f"drawdown_{k}"] = drawdown[keep]
        out[f"runup_{k}"] = runup[keep]
        out[f"forward_{k}"] = forward[keep]
    return out


# Concatenate per-name row dicts into one pooled dict (each name's rows
# count once; no name is weighted by anything but its session count).
def _pool(parts: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    if not parts:
        return _rows(_empty_cube(), np.zeros(0, dtype=bool))
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


# An empty cube, for the shape of an empty pool.
def _empty_cube() -> SessionCube:
    shape = (0, FULL_SESSION_SLOTS)
    return SessionCube(
        "",
        np.zeros(0, dtype="datetime64[D]"),
        np.zeros(shape),
        np.zeros(shape),
        np.zeros(shape),
        np.zeros(shape),
        np.zeros(shape),
        np.zeros(0),
        {},
    )


# All four pieces on one pooled set of rows. `edges` are the open-drive
# quintile edges (from the choosing window); `names` is the count of
# names that contributed at least one row.
def analyse(
    rows: dict[str, np.ndarray], edges: np.ndarray, names: int
) -> dict[str, Any]:
    """Return the JSON-ready analysis of pooled rows."""
    dates = rows["dates"]
    sessions = int(len(dates))
    distinct = int(len(np.unique(dates))) if sessions else 0
    high_shares, low_shares = _extreme_slot_shares(rows["high"], rows["low"])
    r1, rest = rows["r1"], rows["r_rest"]
    daily_r1 = daily_average(dates, r1)
    daily_rest = daily_average(dates, rest)
    slope, t, n_dates = slope_hac_t(daily_r1, daily_rest)
    dips = []
    for k in CHECK_SLOTS:
        for d in DIP_THRESHOLDS:
            cell = conditional_difference(
                dates, rows[f"forward_{k}"], rows[f"drawdown_{k}"] <= d
            )
            dips.append({"slot": k, "threshold": d, **cell})
    extensions = []
    for k in CHECK_SLOTS:
        for e in EXT_THRESHOLDS:
            cell = conditional_difference(
                dates, rows[f"forward_{k}"], rows[f"runup_{k}"] >= e
            )
            extensions.append({"slot": k, "threshold": e, **cell})
    return {
        "names": int(names),
        "sessions": sessions,
        "dates": distinct,
        "variance_shares": _list(_variance_shares(rows["bar_returns"])),
        "high_slot_shares": _list(high_shares),
        "low_slot_shares": _list(low_shares),
        "gap": _moments(rows["gap"]),
        "session_return": _moments(rows["session_return"]),
        "open_drive": {
            "slope": slope,
            "t": t,
            "dates": n_dates,
            "r1": _moments(r1),
            "r_rest": _moments(rest),
            "edges": _list(edges),
            "quintiles": conditional_means(r1, rest, edges, dates),
        },
        "dips": dips,
        "extensions": extensions,
        "fill_costs": {
            name: _moments(rows[f"cost_{name}"])
            for name in ("first_hour_vwap", "session_vwap", "close")
        },
    }


# A float array as a plain list.
def _list(values: np.ndarray) -> list[float]:
    return [float(v) for v in np.asarray(values, dtype=float)]


# The study: pool the book's names equally on their member sessions,
# report each benchmark on its own, per window, with quintile edges from
# the choosing window applied to every window.
def study(
    cubes: Mapping[str, SessionCube],
    mask_by_date: MaskByDate,
    windows: Mapping[str, tuple[date | None, date | None]] = WINDOWS,
    benchmarks: tuple[str, ...] = BENCHMARKS,
    choosing: str = CHOOSING_WINDOW,
) -> dict[str, Any]:
    """Return the JSON-serialisable study payload."""
    if choosing not in windows:
        raise ValueError(f"choosing window {choosing!r} is not one of {list(windows)}")
    book = {t: c for t, c in cubes.items() if t not in benchmarks}
    bench = {t: c for t, c in cubes.items() if t in benchmarks}
    # The book: member rows per name, pooled per window.
    book_rows: dict[str, dict[str, np.ndarray]] = {}
    book_names: dict[str, int] = {}
    for name, (start, end) in windows.items():
        parts = []
        for ticker, cube in book.items():
            keep = _member_rows(mask_by_date, ticker, cube.dates) & _window_rows(
                cube.dates, start, end
            )
            if keep.any():
                parts.append(_rows(cube, keep))
        book_rows[name] = _pool(parts)
        book_names[name] = len(parts)
    book_edges = quintile_edges(book_rows[choosing]["r1"])
    book_out = {
        name: analyse(book_rows[name], book_edges, book_names[name]) for name in windows
    }
    # Benchmarks: every session of the name, never masked, never pooled.
    bench_out: dict[str, dict[str, Any]] = {}
    for ticker, cube in bench.items():
        per_window = {
            name: _rows(cube, _window_rows(cube.dates, start, end))
            for name, (start, end) in windows.items()
        }
        edges = quintile_edges(per_window[choosing]["r1"])
        bench_out[ticker] = {
            name: analyse(
                per_window[name], edges, int(len(per_window[name]["dates"]) > 0)
            )
            for name in windows
        }
    return json_ready(
        {
            "study": "session_anatomy",
            "version": STUDY_VERSION,
            "choosing_window": choosing,
            "windows": {
                name: {"start": _iso(start), "end": _iso(end)}
                for name, (start, end) in windows.items()
            },
            "constants": {
                "slots": FULL_SESSION_SLOTS,
                "open_drive_end_slot": OPEN_DRIVE_END_SLOT,
                "check_slots": list(CHECK_SLOTS),
                "dip_thresholds": list(DIP_THRESHOLDS),
                "ext_thresholds": list(EXT_THRESHOLDS),
                "first_hour_slots": FIRST_HOUR_SLOTS,
                "quintiles": QUINTILES,
                "hac_lag": HAC_LAG,
                "vwap": "proxy: bar closes weighted by bar volume",
            },
            "book_tickers": sorted(book),
            "benchmark_tickers": sorted(bench),
            "book": book_out,
            "benchmarks": bench_out,
        }
    )


# A date as ISO text, or None.
def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


# The payload with every NaN or infinite float as None and every numpy
# scalar as a Python one, so `json.dumps` writes strict JSON.
def json_ready(value: Any) -> Any:
    """Return `value` with only JSON-representable leaves."""
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, np.ndarray):
        return [json_ready(v) for v in value.tolist()]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    return value
