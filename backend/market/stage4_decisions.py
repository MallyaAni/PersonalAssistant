"""Stage 4's decision engine: the 14 registered candidates on the executor's orders.

`docs/research/stage4-plan-2026-09-29.md` registers everything here ("The
candidates", "The decision test", "Kill criteria, fixed now", "Trials and
multiplicity"); where it is silent the choice is named below and in the
plan's addendum.

**Orders.** `stage4_orders`: every changed position of the control
executor (`ew-redeploy`) from each start offset, with its decision session
t, side, weight (notional over equity at t), kind, detail and grade at t.

**Fills.** `stage4_labels.name_fills` per name on the panel's adjusted
basis, gathered on the (T, N) grid (`fill_grids`), once with bar-close
fills and once with `next_bar` (the plan's robustness run, candidate and
control alike):

- `control`: the board's dip_or_close in session t + 1;
- `level` (D0): C_t·e^(∓σ) resting through t+1..t+5, else the close of t+5;
- `turn` (D2) and `squeeze` (D3): their daily triggers, already the
  control's fill where the rule is inactive.

**Deciders.** Seven, each applied to one side, 14 candidates (`CANDIDATES`):

- D0: the level fill, always.
- D1: the level fill when the side's condition holds at t, else the
  control. Buys: the VIX under 25 at t and no earnings release in the last
  three sessions (t-2..t). Sells: no earnings release in t-2..t. The VIX is
  exp of the T-S1 export's date-level `d_vix_level` (ln VIX); a session
  without it fails the buy condition. Earnings days are
  `stage3_export.earnings_days` (EDGAR, strict publication).
- D2: the turn fill. D3: the squeeze fill.
- D4, D5, D6 (M1 LightGBM, M2 the I20 CNN, M3 the sequence model): the
  level fill when that family's forecast for the side at (t, name) is above
  zero, else the control. A missing forecast fills as the control and is
  counted. A family without its forecast file is not priced (SKIPPED).

**Per order.** g = `stage4_labels.gain(control, candidate, side)` in bp of
the order; d = the candidate's fill session - 1, the sessions it waited
past the control's t + 1. An order whose chosen fill or control has no
price (no complete cube session, orders before the cubes start) fills as
the control: g = 0, d = 0, counted as unpriced.

**The book.** Per offset and candidate, the gain on decision session t is
the sum over its side's orders decided at t of weight x g, in bp of equity;
a decision session without orders is zero. The series runs over the run's
decision sessions.

**Windows** (by decision date): `model` from the latest first-forecast date
among the model files given (2018-01-02 when none is given) through
2023-12-29; `2024-2026` from 2024-01-01 to the end.

**Statistics**, at the median offset (the middle of the offsets priced,
`offsets // 2`, stage 3's and every earlier study's `priced[len(priced) //
2]`):

- the mean gain a session and its Newey-West t (lag 20);
- per re-timed order (g != 0) the mean g, with the t clustered by decision
  date (`fill_timing.clustered_t`);
- orders, orders that waited (d > 0), the mean wait;
- the drift-adjusted gain g - s·μ·d per order (s = +1 for a sell, -1 for a
  buy; μ the mean daily log close-to-close return of the name-days graded
  A/A+ in the same window, `drift`), aggregated the same way with its own
  t.

The next-bar run is the same on the next-bar fills. For the models, each
single seed's column decides in turn; seed stability is
`stage3_verdict.seed_stability` on the model-window means. The deflated
Sharpe follows `stage3_verdict.deflated` at N = 14, with the
across-candidate variance of the priced candidates' model-window Sharpe
ratios.

**Verdict** (`verdict`), per candidate: REPLACES when all six criteria
hold, else RECORD, or "RECORD: real but immaterial" when criterion 1 fails
but the per-re-timed-order mean is at least 25 bp with a clustered t of at
least 3.

**Reported, never deciding:** the statistics by kind, by detail (rotation
exit, reset exit, trim; entry, add, retry; event), by grade group (A+ / A
buys; sells to B, to C or still A) and by VIX regime; the oracle (per order
the best 15-minute bar close over t+1..t+5, lowest for a buy, highest for a
sell, against the control) and each candidate's capture share; each
model's population skill by grade when the labels are given
(`population_skill`).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.market import candidate_stats, stage3_verdict
from backend.market import stage3_io as io
from backend.market import stage4_labels as lab
from backend.market import stage4_orders as so
from backend.market.fill_timing import clustered_t
from backend.market.sip_cube import SessionCube

PLAN = lab.PLAN
STUDY = "stage4_decisions"
WINDOW = lab.WINDOW
SIDES = lab.SIDES
CONTROL, LEVEL, TURN, SQUEEZE = lab.CONTROL, lab.LEVEL, lab.TURN, lab.SQUEEZE
# The seven deciders, in the plan's order.
DECIDERS: dict[str, str] = {
    "D0": "always",
    "D1": "news_and_stress",
    "D2": "turn",
    "D3": "squeeze",
    "D4": "m1_lgbm",
    "D5": "m2_cnn_i20",
    "D6": "m3_seq",
}
# The fill each decider waits with when it acts.
OWN_FILL: dict[str, str] = {
    "D0": LEVEL,
    "D1": LEVEL,
    "D2": TURN,
    "D3": SQUEEZE,
    "D4": LEVEL,
    "D5": LEVEL,
    "D6": LEVEL,
}
# The model deciders and the family whose forecast each reads.
MODEL_FAMILIES: dict[str, str] = {"D4": io.LGBM, "D5": io.CNN_I20, "D6": io.SEQ}
# The 14 outer candidates: each decider on each side.
CANDIDATES: tuple[str, ...] = tuple(f"{d}_{s}" for d in DECIDERS for s in SIDES)
# The plan's trial counts: the gate reads the outer count; the other two are
# printed beside it.
OUTER_CANDIDATES = 14
CONFIG_TRIALS = 42
CUMULATIVE_TRIALS = 451
TRIAL_COUNTS = {
    "outer": OUTER_CANDIDATES,
    "configurations": CONFIG_TRIALS,
    "cumulative": CUMULATIVE_TRIALS,
}
# D1's conditions.
VIX_STRESS = 25.0
EARNINGS_SESSIONS = 3
VIX_COLUMN = "d_vix_level"
# The kill criteria, fixed by the plan.
FLOOR_BP = 2.0
FLOOR_T = 2.0
DRIFT_FLOOR_BP = 1.0
DRIFT_FLOOR_T = 2.0
DSR_GATE = 0.95
IMMATERIAL_BP = 25.0
IMMATERIAL_T = 3.0
SEED_CHANGES = stage3_verdict.SEED_CHANGES
HAC_LAG = 20
OFFSETS = 20
# The windows, by decision date.
MODEL = "model"
REPORTED = "2024-2026"
MODEL_END = date(2024, 1, 1)
DEFAULT_MODEL_START = date(2018, 1, 2)
# The labels.
REPLACES = "REPLACES"
RECORD = "RECORD"
IMMATERIAL = "RECORD: real but immaterial"
SKIPPED = "SKIPPED"
# The report's groups: the order kinds and details, the grade groups and the
# VIX regimes.
BUY_GRADES = ("a_plus", "a", "below_a")
SELL_GRADES = ("to_b", "to_c", "still_a")
VIX_REGIMES = ("calm", "stress", "unknown")
GRADE_NAMES = {3: "A+", 2: "A", 1: "B", 0: "C"}
BP = 1e4

assert len(CANDIDATES) == OUTER_CANDIDATES
assert SEED_CHANGES == 2
assert len(io.SEEDS) == 5
assert HAC_LAG == io.HAC_LAG


# --- the fills ---------------------------------------------------------------


@dataclass(frozen=True)
class FillGrid:
    """Every (session, name)'s fills under one fill mode, on the panel's grid."""

    next_bar: bool
    # (convention, side) -> (T, N) adjusted fill price, NaN where unpriced.
    price: dict[tuple[str, str], np.ndarray]
    # (T, N) the fill session after t (1..W), 0 where unpriced.
    days: dict[tuple[str, str], np.ndarray]
    # (T, N) whether the rule acted at t.
    active: dict[tuple[str, str], np.ndarray]


# The best 15-minute bar close over sessions t+1..t+W on the adjusted basis
# (`stage4_labels.cube_scale`), per decision session of one name: the lowest
# for a buy, the highest for a sell. NaN unless all W sessions are complete
# cube sessions.
def oracle_prices(
    series: lab.NameSeries, cube: SessionCube, window: int = WINDOW
) -> dict[str, np.ndarray]:
    """Return {side: (T,) oracle price}."""
    length = len(series.dates)
    out = {side: np.full(length, np.nan) for side in SIDES}
    if not len(cube):
        return out
    rows = lab.cube_rows(series.dates, cube)
    scale = lab.cube_scale(series, cube)
    ahead = np.full((length, window), -1, dtype=np.int64)
    factor = np.full((length, window), np.nan)
    for j in range(1, window + 1):
        ahead[: length - j, j - 1] = rows[j:]
        factor[: length - j, j - 1] = scale[j:]
    idx = np.flatnonzero((ahead >= 0).all(axis=1) & np.isfinite(factor).all(axis=1))
    if len(idx):
        closes = cube.close[ahead[idx]] * factor[idx][:, :, None]
        out["buy"][idx] = closes.min(axis=(1, 2))
        out["sell"][idx] = closes.max(axis=(1, 2))
    return out


# Every name's fills on the panel's grid, with bar-close fills and with
# next-bar fills, and the oracle: `stage4_labels.name_series` and
# `name_fills` per name with a cube; a name without one is unpriced.
def fill_grids(
    panel: Any, cubes: Mapping[str, SessionCube], window: int = WINDOW
) -> tuple[FillGrid, FillGrid, dict[str, np.ndarray], dict[str, Any]]:
    """Return (bar-close grid, next-bar grid, {side: (T, N) oracle}, coverage)."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    keys = [(c, s) for c in lab.CONVENTIONS for s in SIDES]
    grids: dict[bool, FillGrid] = {}
    for mode in (False, True):
        grids[mode] = FillGrid(
            next_bar=mode,
            price={key: np.full(shape, np.nan) for key in keys},
            days={key: np.zeros(shape, dtype=np.int64) for key in keys},
            active={key: np.zeros(shape, dtype=bool) for key in keys},
        )
    oracle = {side: np.full(shape, np.nan) for side in SIDES}
    covered: list[str] = []
    for j, ticker in enumerate(panel.tickers):
        cube = cubes.get(ticker)
        if cube is None or not len(cube):
            continue
        series = lab.name_series(
            dates,
            panel.close[:, j],
            panel.adj_close[:, j],
            panel.high[:, j],
            panel.low[:, j],
        )
        for mode, grid in grids.items():
            for key, fills in lab.name_fills(
                series, cube, window, next_bar=mode
            ).items():
                grid.price[key][:, j] = fills.price
                grid.days[key][:, j] = fills.days
                grid.active[key][:, j] = fills.active
        for side, values in oracle_prices(series, cube, window).items():
            oracle[side][:, j] = values
        covered.append(str(ticker))
    first = min((cubes[t].dates[0] for t in covered), default=None)
    coverage = {
        "names_with_cube": len(covered),
        "names_without_cube": sorted(
            str(t) for t in panel.tickers if str(t) not in set(covered)
        ),
        "first_cube_date": str(first) if first is not None else None,
        "window": window,
    }
    return grids[False], grids[True], oracle, coverage


# --- D1's conditions ---------------------------------------------------------


# The VIX level at each panel session from the T-S1 export: exp of the
# date-level column `d_vix_level` (ln VIX). Every row of a date carries the
# same value; a date whose rows disagree is refused. Sessions the export has
# no row for, or no value on, are NaN.
def vix_from_export(data: io.Stage3Data, dates: np.ndarray) -> np.ndarray:
    """Return the (T,) VIX level at each session, NaN where unknown."""
    if VIX_COLUMN not in data.feature_names:
        raise ValueError(f"the T-S1 export has no {VIX_COLUMN!r} column")
    dates = np.asarray(dates, dtype="datetime64[D]")
    out = np.full(len(dates), np.nan)
    if not len(data):
        return out
    values = np.asarray(data.x[:, data.feature_names.index(VIX_COLUMN)], dtype=float)
    row_dates = np.asarray(data.dates, dtype="datetime64[D]")
    if (row_dates[1:] < row_dates[:-1]).any():
        raise ValueError("the T-S1 export's rows must be sorted by date")
    starts = np.flatnonzero(np.r_[True, row_dates[1:] != row_dates[:-1]])
    low = np.fmin.reduceat(values, starts)
    high = np.fmax.reduceat(values, starts)
    known = np.isfinite(low)
    if (known & (low != high)).any():
        raise ValueError(
            f"{VIX_COLUMN} differs between the rows of one date; it must be date-level"
        )
    days = row_dates[starts]
    at = np.searchsorted(dates, days)
    on = (at < len(dates)) & (dates[np.minimum(at, len(dates) - 1)] == days) & known
    with np.errstate(over="ignore"):
        out[at[on]] = np.exp(low[on])
    return out


# Whether each name had an earnings reaction session in the last `sessions`
# panel sessions through t (t-2..t for the plan's three).
def recent_earnings(
    earnings: np.ndarray, sessions: int = EARNINGS_SESSIONS
) -> np.ndarray:
    """Return the (T, N) flag of an earnings session in t-sessions+1..t."""
    earnings = np.asarray(earnings, dtype=bool)
    out = earnings.copy()
    for k in range(1, int(sessions)):
        out[k:] |= earnings[:-k]
    return out


# --- the model forecasts -----------------------------------------------------


@dataclass(frozen=True)
class ModelForecast:
    """One model family's forecast for one side, placed on the panel's (T, N) grid."""

    family: str
    side: str
    grid: np.ndarray  # (T, N) the seed ensemble's yhat at (t, name); NaN where none
    seeds: np.ndarray  # (T, N, S) each single seed's yhat
    first: date | None  # the first date with a finite ensemble forecast
    identity: dict[str, Any]


# Refuse a forecast file that is not this (family, side)'s stage-4 file:
# another kind, family or side (when its meta names one), a slot other
# than 0, other than five seed columns, rows other than the T-S1 export's
# (when `keys` are given), or no finite forecast at all.
def check_forecast(
    forecast: io.Stage3Forecast,
    family: str,
    side: str,
    keys: tuple[np.ndarray, np.ndarray] | None = None,
) -> None:
    """Raise ValueError unless the file is a usable (family, side) forecast."""
    if forecast.kind not in io.KINDS:
        raise ValueError(f"forecast kind {forecast.kind!r} is not one of {io.KINDS}")
    if forecast.family != family:
        raise ValueError(f"the forecast is family {forecast.family!r}, not {family!r}")
    named = forecast.meta.get("side")
    if named is not None and str(named) != side:
        raise ValueError(f"the forecast is for the {named!r} side, not {side!r}")
    if (np.asarray(forecast.slot) != 0).any():
        raise ValueError("a stage-4 forecast has slot 0 on every row")
    rows = len(forecast.dates)
    shapes = (np.shape(forecast.yhat), np.shape(forecast.yhat_seeds))
    if shapes != ((rows,), (rows, len(io.SEEDS))):
        raise ValueError(
            f"yhat and yhat_seeds are {shapes}; they must fit {rows} rows and 5 seeds"
        )
    own = _forecast_keys(forecast)
    if keys is not None and not _same_keys(own, keys):
        raise ValueError("the forecast's rows are not the T-S1 export's rows")
    pairs = np.rec.fromarrays([own[0].astype(np.int64), own[1]])
    if len(np.unique(pairs)) != rows:
        raise ValueError("the forecast gives some (date, ticker) more than once")
    if not np.isfinite(np.asarray(forecast.yhat, dtype=float)).any():
        raise ValueError("the forecast has no finite value")


# A forecast file's row keys: its dates and tickers.
def _forecast_keys(forecast: io.Stage3Forecast) -> tuple[np.ndarray, np.ndarray]:
    """Return ((R,) datetime64[D] dates, (R,) str tickers)."""
    return (
        np.asarray(forecast.dates, dtype="datetime64[D]"),
        np.asarray(forecast.tickers).astype(str),
    )


# Whether two (dates, tickers) key pairs are the same rows in the same order.
def _same_keys(
    a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray]
) -> bool:
    """Return True when both keys' dates and tickers are equal."""
    dates = np.array_equal(a[0], np.asarray(b[0], dtype="datetime64[D]"))
    return bool(dates and np.array_equal(a[1], np.asarray(b[1]).astype(str)))


# Place one (family, side) forecast file on the panel's grid: row (date t,
# ticker) at cell [t, ticker], after `check_forecast`. Rows whose date or
# ticker the panel lacks are counted and left out.
def place_forecast(
    forecast: io.Stage3Forecast,
    dates: np.ndarray,
    tickers: Sequence[str],
    family: str,
    side: str,
    keys: tuple[np.ndarray, np.ndarray] | None = None,
    identity: dict[str, Any] | None = None,
) -> ModelForecast:
    """Return the ModelForecast of a forecast file."""
    check_forecast(forecast, family, side, keys)
    rows = len(forecast.dates)
    yhat = np.asarray(forecast.yhat, dtype=float)
    seeds = np.asarray(forecast.yhat_seeds, dtype=float)
    own_dates, own_tickers = _forecast_keys(forecast)
    dates = np.asarray(dates, dtype="datetime64[D]")
    sessions, names = len(dates), len(tickers)
    at = np.searchsorted(dates, own_dates)
    on = np.zeros(rows, dtype=bool)
    if sessions:
        on = (at < sessions) & (dates[np.minimum(at, sessions - 1)] == own_dates)
    index = {str(t): j for j, t in enumerate(tickers)}
    cols = np.array([index.get(t, -1) for t in own_tickers], dtype=np.int64)
    on &= cols >= 0
    grid = np.full((sessions, names), np.nan)
    grid[at[on], cols[on]] = yhat[on]
    seed_grid = np.full((sessions, names, len(io.SEEDS)), np.nan)
    seed_grid[at[on], cols[on]] = seeds[on]
    first = own_dates[np.isfinite(yhat)].min().astype(object)
    record = {
        **(identity or {}),
        "family": family,
        "side": side,
        "kind": forecast.kind,
        "rows": int(rows),
        "placed": int(on.sum()),
        "off_panel": int((~on).sum()),
        "finite": int(np.isfinite(yhat).sum()),
        "first_forecast_date": str(first),
        "seed_finite": [int(v) for v in np.isfinite(seeds).sum(axis=0)],
    }
    return ModelForecast(family, side, grid, seed_grid, first, record)


# The model window's first date: the latest first-forecast date among the
# model files given, or DEFAULT_MODEL_START when none is. Returns (date,
# source, {file key: its first date}).
def model_start(
    forecasts: Mapping[tuple[str, str], ModelForecast],
) -> tuple[date, str, dict[str, str]]:
    """Return the model window's start, its source and each file's first date."""
    firsts = {f"{fam}_{side}": fc.first for (fam, side), fc in forecasts.items()}
    known = [d for d in firsts.values() if d is not None]
    if not known:
        return DEFAULT_MODEL_START, "default", {}
    return max(known), "forecasts", {k: str(v) for k, v in firsts.items()}


# The study's two windows by decision date: the model window from `start`
# through 2023-12-29, and 2024-2026.
def windows(start: date) -> dict[str, tuple[date | None, date | None]]:
    """Return {window: (start, end)}, end exclusive."""
    return {MODEL: (start, MODEL_END), REPORTED: (MODEL_END, None)}


# --- the market the engine reads ---------------------------------------------


@dataclass(frozen=True)
class Market:
    """Everything the engine reads besides the orders, on the panel's (T, N) grid."""

    dates: np.ndarray  # (T,) datetime64[D]
    tickers: tuple[str, ...]
    fills: FillGrid  # bar-close fills
    next_bar: FillGrid  # next-bar fills
    oracle: dict[str, np.ndarray]  # side -> (T, N) the oracle's price
    vix: np.ndarray  # (T,) VIX level at t, NaN unknown
    recent: np.ndarray  # (T, N) bool: an earnings session in t-2..t
    grades: np.ndarray  # (T, N) the desk grade of the report the orders came from
    closes: np.ndarray  # (T, N) adjusted closes (the drift)
    forecasts: Mapping[tuple[str, str], ModelForecast]


# Assemble the Market from the panel, its grades, the fills, the VIX, the
# earnings sessions and the placed forecasts.
def build_market(
    panel: Any,
    grades: np.ndarray,
    fills: FillGrid,
    next_bar: FillGrid,
    oracle: dict[str, np.ndarray],
    vix: np.ndarray,
    earnings: np.ndarray,
    forecasts: Mapping[tuple[str, str], ModelForecast] | None = None,
) -> Market:
    """Return the Market."""
    if fills.next_bar or not next_bar.next_bar:
        raise ValueError(
            "fills must be the bar-close grid and next_bar the next-bar grid"
        )
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    shape = (len(dates), len(panel.tickers))
    earnings = np.asarray(earnings, dtype=bool)
    if (
        earnings.shape != shape
        or np.asarray(grades).shape != shape
        or len(vix) != len(dates)
    ):
        raise ValueError("grades, earnings and the VIX must be on the panel's grid")
    return Market(
        dates=dates,
        tickers=tuple(str(t) for t in panel.tickers),
        fills=fills,
        next_bar=next_bar,
        oracle=oracle,
        vix=np.asarray(vix, dtype=float),
        recent=recent_earnings(earnings),
        grades=np.asarray(grades),
        closes=np.asarray(panel.adj_close, dtype=float),
        forecasts=dict(forecasts or {}),
    )


# --- the drift ----------------------------------------------------------------


# The mean daily log close-to-close return of the name-days graded A or A+
# at t whose decision date lies in [lo, hi): ln(C[t+1] / C[t]) pooled over
# (t, name), on the adjusted closes.
def drift(market: Market, lo: date | None, hi: date | None) -> dict[str, Any]:
    """Return {"mu", "mu_bp", "name_days"} for a window."""
    closes = market.closes
    ret = np.full(closes.shape, np.nan)
    with np.errstate(all="ignore"):
        ret[:-1] = np.log(closes[1:] / closes[:-1])
    keep = (
        point_in_time.window(market.dates, lo, hi)[:, None]
        & (market.grades >= so.A)
        & np.isfinite(ret)
    )
    mu = float(ret[keep].mean()) if keep.any() else math.nan
    return {"mu": mu, "mu_bp": mu * BP, "name_days": int(keep.sum())}


# --- pricing one candidate ----------------------------------------------------


@dataclass(frozen=True)
class Book:
    """One candidate's side of one run: its orders' fills and gains, aligned."""

    candidate: str
    side: str
    start: int  # the run's first decision session
    stop: int  # one past its last
    rows: np.ndarray  # (K,) positions of these orders in the run's Orders
    session: np.ndarray  # (K,) decision session t
    weight: np.ndarray  # (K,) notional over equity at t
    gain: np.ndarray  # (K,) g in bp of the order; 0 where it fills as the control
    wait: np.ndarray  # (K,) d: sessions waited past t + 1
    acted: np.ndarray  # (K,) bool: the decider chose its own fill
    unpriced: np.ndarray  # (K,) bool: the chosen fill or the control had no price
    no_forecast: np.ndarray  # (K,) bool: a model had no forecast at (t, name)
    oracle: np.ndarray  # (K,) the oracle's gain over the control, bp; NaN unpriced


# The decider and side of a candidate name, refused when unknown.
def split_candidate(candidate: str) -> tuple[str, str]:
    """Return (decider, side) of "D<k>_<side>"."""
    if candidate not in CANDIDATES:
        raise ValueError(
            f"unknown candidate {candidate!r}; registered: {', '.join(CANDIDATES)}"
        )
    decider, side = candidate.split("_")
    return decider, side


# Price one candidate on one run's orders: its side's orders, the fill its
# decider chooses per order (its own, or the control's), g, d and the
# counts. `next_bar` reads the next-bar fills; `seed` a single seed's column
# of a model's forecast instead of the ensemble.
def price_book(
    orders: so.Orders,
    market: Market,
    candidate: str,
    next_bar: bool = False,
    seed: int | None = None,
) -> Book:
    """Return the candidate's Book on the orders."""
    decider, side = split_candidate(candidate)
    grid = market.next_bar if next_bar else market.fills
    rows = np.flatnonzero(orders.side == side)
    t = orders.session[rows]
    j = orders.column[rows]
    control = grid.price[(CONTROL, side)][t, j]
    control_days = grid.days[(CONTROL, side)][t, j]
    no_forecast = np.zeros(len(rows), dtype=bool)
    if decider == "D0":
        acted = np.ones(len(rows), dtype=bool)
    elif decider == "D1":
        acted = ~market.recent[t, j]
        if side == "buy":
            with np.errstate(invalid="ignore"):
                acted &= market.vix[t] < VIX_STRESS
    elif decider in ("D2", "D3"):
        acted = grid.active[(OWN_FILL[decider], side)][t, j]
    else:
        forecast = market.forecasts.get((MODEL_FAMILIES[decider], side))
        if forecast is None:
            y = np.full(len(rows), np.nan)
        elif seed is None:
            y = forecast.grid[t, j]
        else:
            y = forecast.seeds[t, j, int(seed)]
        no_forecast = ~np.isfinite(y)
        with np.errstate(invalid="ignore"):
            acted = y > 0
    own = OWN_FILL[decider]
    price = np.where(acted, grid.price[(own, side)][t, j], control)
    days = np.where(acted, grid.days[(own, side)][t, j], control_days)
    unpriced = ~np.isfinite(control) | ~np.isfinite(price)
    gain = np.where(unpriced, 0.0, lab.gain(control, price, side))
    wait = np.where(unpriced, 0, days - 1).astype(np.int64)
    oracle = lab.gain(control, market.oracle[side][t, j], side)
    return Book(
        candidate=candidate,
        side=side,
        start=orders.start,
        stop=orders.stop,
        rows=rows,
        session=t,
        weight=orders.weight[rows],
        gain=gain,
        wait=wait,
        acted=np.asarray(acted, dtype=bool),
        unpriced=unpriced,
        no_forecast=no_forecast,
        oracle=oracle,
    )


# --- statistics ----------------------------------------------------------------


# The book's gain series over the run's decision sessions: per session the
# sum over the (selected) orders decided there of weight x value.
def session_series(
    book: Book, values: np.ndarray, subset: np.ndarray | None = None
) -> np.ndarray:
    """Return the (stop - start,) series in bp of equity."""
    length = max(book.stop - book.start, 0)
    keep = (
        np.ones(len(book.session), dtype=bool)
        if subset is None
        else np.asarray(subset, dtype=bool)
    )
    if len(book.session) and (
        book.session.min() < book.start or book.session.max() >= book.stop
    ):
        raise ValueError("an order lies outside its run's decision sessions")
    return np.bincount(
        book.session[keep] - book.start,
        weights=book.weight[keep] * np.asarray(values, dtype=float)[keep],
        minlength=length,
    )[:length]


# The run's decision sessions inside [lo, hi), as a mask over its series.
def session_window(
    book: Book, dates: np.ndarray, lo: date | None, hi: date | None
) -> np.ndarray:
    """Return the (stop - start,) window mask."""
    return point_in_time.window(np.asarray(dates)[book.start : book.stop], lo, hi)


# The per-order drift adjustment: g - s·μ·d, s = +1 for a sell (waiting
# holds the stock) and -1 for a buy (waiting holds cash), μ in bp a session.
def drift_adjusted(book: Book, mu_bp: float) -> np.ndarray:
    """Return the (K,) drift-adjusted gains in bp."""
    sign = 1.0 if book.side == "sell" else -1.0
    return book.gain - sign * float(mu_bp) * book.wait


# A mean over finite values, NaN when there are none.
def _mean(x: np.ndarray) -> float:
    """Return the finite mean, NaN when empty."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return float(x.mean()) if len(x) else math.nan


# The plan's statistics of a book (or a subset of its orders) over one
# window: the gain series' mean and Newey-West t, its drift-adjusted twin,
# its moments (for the deflated Sharpe), the orders, the re-timed orders'
# mean with its date-clustered t, the waits, the counts, and the oracle's
# gain and the book's capture of it.
def summarize(
    book: Book,
    dates: np.ndarray,
    lo: date | None,
    hi: date | None,
    mu_bp: float,
    subset: np.ndarray | None = None,
) -> dict[str, Any]:
    """Return the statistics of one window."""
    keep_sessions = session_window(book, dates, lo, hi)
    chosen = (
        np.ones(len(book.session), dtype=bool)
        if subset is None
        else np.asarray(subset, dtype=bool)
    )
    series = session_series(book, book.gain, chosen)[keep_sessions]
    adjusted = drift_adjusted(book, mu_bp)
    adjusted_series = session_series(book, adjusted, chosen)[keep_sessions]
    moments = candidate_stats.moments(series)
    n = len(series)
    inside = (
        chosen & keep_sessions[book.session - book.start]
        if len(book.session)
        else chosen
    )
    orders = int(inside.sum())
    retimed = inside & (book.gain != 0)
    waited = inside & (book.wait > 0)
    oracle_ok = inside & np.isfinite(book.oracle)
    oracle_sum = float(book.oracle[oracle_ok].sum())
    oracle_weighted = float((book.weight * book.oracle)[oracle_ok].sum())
    return {
        "sessions": int(n),
        "mean_bp": float(series.mean()) if n else math.nan,
        "hac_t": candidate_stats.hac_t(series, HAC_LAG) if n > 2 else math.nan,
        "drift_mean_bp": float(adjusted_series.mean())
        if n and math.isfinite(mu_bp)
        else math.nan,
        "drift_hac_t": candidate_stats.hac_t(adjusted_series, HAC_LAG)
        if n > 2 and math.isfinite(mu_bp)
        else math.nan,
        "excess": {
            "sharpe": moments.sharpe,
            "skew": moments.skew,
            "kurtosis": moments.kurtosis,
            "length": moments.length,
        },
        "orders": orders,
        "sessions_with_orders": int(len(np.unique(book.session[inside]))),
        "mean_weight": _mean(book.weight[inside]),
        "per_order_bp": _mean(book.gain[inside]),
        "acted": int((inside & book.acted).sum()),
        "retimed": int(retimed.sum()),
        "retimed_bp": _mean(book.gain[retimed]),
        "retimed_t": clustered_t(book.gain[retimed], book.session[retimed]),
        "retimed_sessions": int(len(np.unique(book.session[retimed]))),
        "waited": int(waited.sum()),
        "waited_share": float(waited.sum() / orders) if orders else math.nan,
        "mean_wait": _mean(book.wait[waited]),
        "mean_wait_all": _mean(book.wait[inside]),
        "unpriced": int((inside & book.unpriced).sum()),
        "no_forecast": int((inside & book.no_forecast).sum()),
        "oracle_orders": int(oracle_ok.sum()),
        "oracle_bp": _mean(book.oracle[oracle_ok]),
        "capture": float(book.gain[oracle_ok].sum() / oracle_sum)
        if oracle_sum > 0
        else math.nan,
        "capture_weighted": (
            float((book.weight * book.gain)[oracle_ok].sum() / oracle_weighted)
            if oracle_weighted > 0
            else math.nan
        ),
    }


# The mean of a book's gain series over a window (the per-offset reading).
def window_mean(
    book: Book, dates: np.ndarray, lo: date | None, hi: date | None
) -> float:
    """Return the mean bp a session over the window, NaN when it is empty."""
    series = session_series(book, book.gain)[session_window(book, dates, lo, hi)]
    return float(series.mean()) if len(series) else math.nan


# The report's group of every order: the Ledger kind, the detail, the grade
# group (buys: A+, A, below A; sells: to B, to C, still A) and the VIX
# regime at t (calm under 25, stress at 25 or more, unknown).
def order_groups(orders: so.Orders, vix: np.ndarray) -> dict[str, np.ndarray]:
    """Return {group: (M,) label per order}."""
    grade = orders.grade
    buy_group = np.where(
        grade >= so.A_PLUS, "a_plus", np.where(grade == so.A, "a", "below_a")
    )
    sell_group = np.where(
        grade >= so.A, "still_a", np.where(grade == so.B, "to_b", "to_c")
    )
    level = np.asarray(vix, dtype=float)[orders.session] if len(orders) else np.zeros(0)
    with np.errstate(invalid="ignore"):
        regime = np.where(
            ~np.isfinite(level),
            "unknown",
            np.where(level < VIX_STRESS, "calm", "stress"),
        )
    return {
        "kind": orders.kind,
        "detail": orders.detail,
        "grade": np.where(orders.buy, buy_group, sell_group),
        "vix": regime,
    }


# The labels each group reports for one side, in a fixed order.
def group_values(side: str) -> dict[str, tuple[str, ...]]:
    """Return {group: labels} for `side`."""
    return {
        "kind": so.KINDS,
        "detail": so.BUY_DETAILS if side == "buy" else so.SELL_DETAILS,
        "grade": BUY_GRADES if side == "buy" else SELL_GRADES,
        "vix": VIX_REGIMES,
    }


# The same statistics per group label of a book's orders, per window.
def splits(
    book: Book,
    groups: Mapping[str, np.ndarray],
    dates: np.ndarray,
    spans: Mapping[str, tuple[date | None, date | None]],
    mus: Mapping[str, float],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return {group: {label: {window: statistics}}}."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for group, labels in group_values(book.side).items():
        mine = np.asarray(groups[group])[book.rows]
        out[group] = {
            label: {
                window: summarize(
                    book, dates, lo, hi, mus[window], subset=mine == label
                )
                for window, (lo, hi) in spans.items()
            }
            for label in labels
        }
    return out


# The deflated Sharpe of one candidate's model-window excess, as
# `stage3_verdict.deflated` reads it but at the stage-4 trial counts: the
# gate at N = 14, the trial variance the across-candidate variance (ddof 1)
# of the finite Sharpe ratios supplied; the configuration-level (42) and
# cumulative (451) readings beside it. Not judged with fewer than two
# finite Sharpes or no record for the candidate.
def deflated(excess: Mapping[str, Mapping[str, Any]], candidate: str) -> dict[str, Any]:
    """Return the deflated Sharpe record of `candidate`."""
    sharpes = np.array(
        [_f((e or {}).get("sharpe")) for e in excess.values()], dtype=float
    )
    sharpes = sharpes[np.isfinite(sharpes)]
    variance = float(sharpes.var(ddof=1)) if len(sharpes) >= 2 else math.nan
    own = excess.get(candidate) or {}
    sharpe = _f(own.get("sharpe"))
    length = int(own.get("length") or 0)
    skew = _f(own.get("skew"))
    kurtosis = _f(own.get("kurtosis"))
    values: dict[str, float] = {}
    for label, trials in TRIAL_COUNTS.items():
        if math.isfinite(variance) and math.isfinite(sharpe):
            values[label] = candidate_stats.deflated_sharpe(
                sharpe, length, skew, kurtosis, trials, variance
            )
        else:
            values[label] = math.nan
    dsr = values["outer"]
    return {
        "candidate": candidate,
        "sharpe": sharpe,
        "length": length,
        "candidates": int(len(sharpes)),
        "trial_variance": variance,
        "trials": OUTER_CANDIDATES,
        "dsr": dsr,
        "dsr_configurations": values["configurations"],
        "dsr_cumulative": values["cumulative"],
        "gate": DSR_GATE,
        "passes": bool(math.isfinite(dsr) and dsr >= DSR_GATE),
    }


# A payload number as a float: None (a NaN written to JSON) reads NaN.
def _f(value: Any) -> float:
    """Return `value` as a float, NaN for None."""
    return math.nan if value is None else float(value)


# --- the whole test --------------------------------------------------------------


# The candidate's record for the payload: which decider and side, the model
# family, and whether it is priced (a model needs its forecast file).
def candidate_record(candidate: str, market: Market) -> dict[str, Any]:
    """Return {"decider", "rule", "side", "family", "priced"}."""
    decider, side = split_candidate(candidate)
    family = MODEL_FAMILIES.get(decider)
    return {
        "decider": decider,
        "rule": DECIDERS[decider],
        "side": side,
        "fill": OWN_FILL[decider],
        "family": family,
        "priced": family is None or (family, side) in market.forecasts,
    }


# Price every candidate on every offset's orders and assemble the payload:
# per offset the model-window and 2024-2026 means (and the next-bar
# model-window mean); at the median offset every statistic, the next-bar
# run, the seeds, the splits and the oracle; the deflated Sharpe, the seed
# stability and the verdict. `registered` is the plan's offset count; a
# run over fewer offsets is a smoke run and says so.
def evaluate(
    runs: Sequence[so.Orders], market: Market, registered: int = OFFSETS
) -> dict[str, Any]:
    """Return the decision test's payload."""
    if not runs:
        raise ValueError("no offsets were priced")
    bases = {o.basis for o in runs}
    if len(bases) != 1:
        raise ValueError(f"the offsets' orders mix bases: {sorted(bases)}")
    start, source, firsts = model_start(market.forecasts)
    spans = windows(start)
    median = len(runs) // 2
    dates = market.dates
    drifts = {w: drift(market, lo, hi) for w, (lo, hi) in spans.items()}
    mus = {w: d["mu_bp"] for w, d in drifts.items()}
    records = {c: candidate_record(c, market) for c in CANDIDATES}
    per_offset: dict[str, dict[str, list[float]]] = {
        c: {"model_bp": [], "reported_bp": [], "next_bar_model_bp": []}
        for c in CANDIDATES
    }
    for orders in runs:
        for c in CANDIDATES:
            book = price_book(orders, market, c)
            nb = price_book(orders, market, c, next_bar=True)
            per_offset[c]["model_bp"].append(window_mean(book, dates, *spans[MODEL]))
            per_offset[c]["reported_bp"].append(
                window_mean(book, dates, *spans[REPORTED])
            )
            per_offset[c]["next_bar_model_bp"].append(
                window_mean(nb, dates, *spans[MODEL])
            )
    at_median = runs[median]
    groups = order_groups(at_median, market.vix)
    results: dict[str, dict[str, Any]] = {}
    for c in CANDIDATES:
        decider, _ = split_candidate(c)
        book = price_book(at_median, market, c)
        nb = price_book(at_median, market, c, next_bar=True)
        result: dict[str, Any] = {
            "default": {
                w: summarize(book, dates, lo, hi, mus[w])
                for w, (lo, hi) in spans.items()
            },
            "next_bar": {
                w: summarize(nb, dates, lo, hi, mus[w]) for w, (lo, hi) in spans.items()
            },
            "splits": splits(book, groups, dates, spans, mus),
            "across_offsets": _across(per_offset[c]["model_bp"]),
        }
        if decider in MODEL_FAMILIES:
            seeds = []
            for k in range(len(io.SEEDS)):
                seeded = price_book(at_median, market, c, seed=k)
                seeds.append(
                    {
                        w: summarize(seeded, dates, lo, hi, mus[w])
                        for w, (lo, hi) in spans.items()
                    }
                )
            result["seeds"] = {
                "columns": list(range(len(io.SEEDS))),
                "model_bp": [s[MODEL]["mean_bp"] for s in seeds],
                "model_t": [s[MODEL]["hac_t"] for s in seeds],
                "stats": seeds,
            }
        results[c] = result
    excess = {
        c: results[c]["default"][MODEL]["excess"]
        for c in CANDIDATES
        if records[c]["priced"]
    }
    dsr = {c: deflated(excess, c) for c in CANDIDATES}
    stability: dict[str, dict[str, Any]] = {}
    for c in CANDIDATES:
        if "seeds" in results[c]:
            stability[c] = stage3_verdict.seed_stability(
                results[c]["default"][MODEL]["mean_bp"], results[c]["seeds"]["model_bp"]
            )
    payload: dict[str, Any] = {
        "study": STUDY,
        "plan": PLAN,
        "asof": str(dates[-1]) if len(dates) else None,
        "control": {
            "executor": so.CONTROL,
            "fills": "dip_or_close",
            "basis": runs[0].basis,
        },
        "window_sessions": WINDOW,
        "offsets": {
            "registered": int(registered),
            "priced": len(runs),
            "median": median,
            "smoke": len(runs) < int(registered),
            "starts": [int(o.start) for o in runs],
        },
        "windows": {
            w: [str(lo) if lo else None, str(hi) if hi else None]
            for w, (lo, hi) in spans.items()
        },
        "model_start": {"date": str(start), "source": source, "files": firsts},
        "hac_lag": HAC_LAG,
        "constants": {
            "VIX_STRESS": VIX_STRESS,
            "EARNINGS_SESSIONS": EARNINGS_SESSIONS,
            "FLOOR_BP": FLOOR_BP,
            "FLOOR_T": FLOOR_T,
            "DRIFT_FLOOR_BP": DRIFT_FLOOR_BP,
            "DRIFT_FLOOR_T": DRIFT_FLOOR_T,
            "DSR_GATE": DSR_GATE,
            "IMMATERIAL_BP": IMMATERIAL_BP,
            "IMMATERIAL_T": IMMATERIAL_T,
            "SEED_CHANGES": SEED_CHANGES,
            "TRIAL_COUNTS": TRIAL_COUNTS,
            "expected_best_null_t": {
                k: candidate_stats.expected_max_sharpe(n, 1.0)
                for k, n in TRIAL_COUNTS.items()
            },
        },
        "candidates": records,
        "drift": drifts,
        "conditions": _conditions(market, spans),
        "forecasts": {
            f"{fam}_{side}": fc.identity for (fam, side), fc in market.forecasts.items()
        },
        "orders": {
            "per_offset": [so.order_counts(o) for o in runs],
            "median_by_window": {
                w: so.order_counts(
                    at_median.subset(
                        point_in_time.window(dates[at_median.session], lo, hi)
                    ),
                    int(
                        point_in_time.window(
                            dates[at_median.start : at_median.stop], lo, hi
                        ).sum()
                    ),
                )
                for w, (lo, hi) in spans.items()
            },
        },
        "per_offset": per_offset,
        "results": results,
        "deflated": dsr,
        "seed_stability": stability,
    }
    payload["verdict"] = verdict(payload)
    return payload


# The spread of the per-offset means: how many offsets, how many positive,
# the median, the smallest and the largest, and (reported only) the offset
# holding the lower median of the means - the statistics are read at the
# middle offset, `offsets // 2`, whatever its mean.
def _across(values: Sequence[float]) -> dict[str, Any]:
    """Return the across-offset summary of per-offset means."""
    v = np.asarray(values, dtype=float)
    index = np.flatnonzero(np.isfinite(v))
    finite = v[index]
    ranked = index[np.argsort(finite, kind="stable")]
    return {
        "offsets": int(len(finite)),
        "positive": int((finite > 0).sum()),
        "median": float(np.median(finite)) if len(finite) else math.nan,
        "min": float(finite.min()) if len(finite) else math.nan,
        "max": float(finite.max()) if len(finite) else math.nan,
        "offset_at_lower_median_mean": int(ranked[(len(ranked) - 1) // 2])
        if len(ranked)
        else None,
    }


# What D1 reads, per window: decision sessions with a VIX, in stress, and
# name-sessions inside an earnings window.
def _conditions(
    market: Market, spans: Mapping[str, tuple[date | None, date | None]]
) -> dict[str, Any]:
    """Return the counts of D1's conditions per window."""
    out: dict[str, Any] = {}
    for w, (lo, hi) in spans.items():
        keep = point_in_time.window(market.dates, lo, hi)
        vix = market.vix[keep]
        with np.errstate(invalid="ignore"):
            out[w] = {
                "sessions": int(keep.sum()),
                "vix_known": int(np.isfinite(vix).sum()),
                "vix_stress": int((vix >= VIX_STRESS).sum()),
                "earnings_window_name_sessions": int(market.recent[keep].sum()),
            }
    return out


# --- the verdict ---------------------------------------------------------------


# The floor: at least `bp` a session with a t of at least `floor_t`, both
# finite.
def clears(value: Any, t: Any, bp: float = FLOOR_BP, floor_t: float = FLOOR_T) -> bool:
    """Return True when value >= bp and t >= floor_t."""
    v, s = _f(value), _f(t)
    return bool(math.isfinite(v) and math.isfinite(s) and v >= bp and s >= floor_t)


# The plan's six criteria for one candidate at the median offset: the
# model-window floor, the next-bar floor, 2024-2026 not negative, the
# deflated Sharpe gate, seed stability (a rule has no seeds to fail; a
# model without a seed record fails) and the drift-adjusted floor.
def criteria_of(
    record: Mapping[str, Any],
    result: Mapping[str, Any],
    dsr: Mapping[str, Any],
    seeds: Mapping[str, Any] | None,
) -> dict[str, bool]:
    """Return {criterion: passes}."""
    model = result["default"][MODEL]
    later = _f(result["default"][REPORTED]["mean_bp"])
    bar = result["next_bar"][MODEL]
    stable = not_model = record["family"] is None
    if not not_model:
        stable = bool(seeds is not None and seeds["stable"])
    return {
        "1_floor": clears(model["mean_bp"], model["hac_t"]),
        "2_next_bar": clears(bar["mean_bp"], bar["hac_t"]),
        "3_not_negative_2024_2026": bool(math.isfinite(later) and later >= 0.0),
        "4_deflated_sharpe": bool(dsr["passes"]),
        "5_seed_stable": stable,
        "6_drift_adjusted": clears(
            model["drift_mean_bp"], model["drift_hac_t"], DRIFT_FLOOR_BP, DRIFT_FLOOR_T
        ),
    }


# One candidate's verdict record: its label - SKIPPED for a model without
# its forecast file, REPLACES when all six criteria hold, "RECORD: real but
# immaterial" when the floor fails but the re-timed orders gain at least
# 25 bp at a clustered t of 3, else RECORD - with the numbers behind it.
def judge(
    record: Mapping[str, Any],
    result: Mapping[str, Any],
    dsr: Mapping[str, Any],
    seeds: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the candidate's label, criteria and numbers."""
    criteria = criteria_of(record, result, dsr, seeds)
    model = result["default"][MODEL]
    bar = result["next_bar"][MODEL]
    later = result["default"][REPORTED]
    per_order = clears(
        model["retimed_bp"], model["retimed_t"], IMMATERIAL_BP, IMMATERIAL_T
    )
    real = bool(not criteria["1_floor"] and per_order)
    if not record["priced"]:
        label = SKIPPED
    elif all(criteria.values()):
        label = REPLACES
    else:
        label = IMMATERIAL if real else RECORD
    return {
        "label": label,
        "criteria": criteria,
        "real_but_immaterial": real,
        "model_bp": _f(model["mean_bp"]),
        "model_t": _f(model["hac_t"]),
        "next_bar_bp": _f(bar["mean_bp"]),
        "next_bar_t": _f(bar["hac_t"]),
        "reported_bp": _f(later["mean_bp"]),
        "reported_t": _f(later["hac_t"]),
        "dsr": _f(dsr["dsr"]),
        "seed_changes": seeds["sign_changes"] if seeds is not None else None,
        "seed_reference": _f(seeds["reference"]) if seeds is not None else math.nan,
        "drift_bp": _f(model["drift_mean_bp"]),
        "drift_t": _f(model["drift_hac_t"]),
        "retimed_bp": _f(model["retimed_bp"]),
        "retimed_t": _f(model["retimed_t"]),
        "orders": int(model["orders"]),
        "retimed": int(model["retimed"]),
        "waited_share": _f(model["waited_share"]),
        "mean_wait": _f(model["mean_wait"]),
    }


# The plan's verdict per candidate from the payload, one line each, and the
# headline; a smoke run's headline says it is not the registered test.
def verdict(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return {"candidates", "replaces", "immaterial", "lines", "text"}."""
    candidates = {
        c: judge(
            payload["candidates"][c],
            payload["results"][c],
            payload["deflated"][c],
            payload["seed_stability"].get(c),
        )
        for c in CANDIDATES
    }
    replaces = [c for c, v in candidates.items() if v["label"] == REPLACES]
    immaterial = [c for c, v in candidates.items() if v["label"] == IMMATERIAL]
    return {
        "candidates": candidates,
        "replaces": replaces,
        "immaterial": immaterial,
        "lines": [_line(c, v, payload["candidates"][c]) for c, v in candidates.items()],
        "text": _headline(payload.get("offsets") or {}, replaces, immaterial),
    }


# The verdict's headline: which candidates replace the board's rule for
# their side, or that none does, and which are real but immaterial.
def _headline(
    offsets: Mapping[str, Any], replaces: Sequence[str], immaterial: Sequence[str]
) -> str:
    """Return the headline text."""
    head = ""
    if offsets.get("smoke"):
        head = (
            f"SMOKE RUN ({offsets.get('priced')} of {offsets.get('registered')} "
            "offsets): not the registered test. "
        )
    if replaces:
        head += (
            f"{REPLACES}: {', '.join(replaces)} clear every criterion against "
            "dip_or_close for their side; a live change needs a separate "
            "registration and the operator's go-ahead"
        )
    else:
        head += (
            f"{RECORD}: no candidate clears every criterion; the board keeps "
            "dip_or_close"
        )
    if immaterial:
        head += f". {IMMATERIAL}: {', '.join(immaterial)}"
    return head


# A signed number for a verdict line, "n/a" when missing.
def _signed(x: Any, digits: int = 2) -> str:
    """Return `x` with its sign, "n/a" when missing."""
    v = _f(x)
    return f"{v:+.{digits}f}" if math.isfinite(v) else "n/a"


# A share as a whole percentage, "n/a" when missing.
def _share(x: Any) -> str:
    """Return `x` as a percentage, "n/a" when missing."""
    v = _f(x)
    return f"{v * 100:.0f}%" if math.isfinite(v) else "n/a"


# The seed reading of a verdict line: none for a rule, stable or not with
# the sign changes for a model, or why it cannot be stable.
def _seed_text(info: Mapping[str, Any], record: Mapping[str, Any]) -> str:
    """Return the seeds' part of a verdict line."""
    reference = _f(info.get("seed_reference"))
    if record["family"] is None:
        return "seeds n/a (a rule)"
    if info["seed_changes"] is None:
        return "seeds not run"
    if not math.isfinite(reference) or reference == 0.0:
        return "seeds not stable (the ensemble's model-window mean is zero or missing)"
    stable = "stable" if info["criteria"]["5_seed_stable"] else "not stable"
    return f"seeds {stable} ({info['seed_changes']} sign changes of 5)"


# One candidate's verdict line, stage-3 style: each criterion's number, then
# the label.
def _line(candidate: str, info: Mapping[str, Any], record: Mapping[str, Any]) -> str:
    """Return the candidate's verdict line."""
    name = f"{candidate} ({record['rule']})"
    if info["label"] == SKIPPED:
        missing = f"{record['family']}_{record['side']}"
        return f"{name}: not priced - no {missing} forecast file - {SKIPPED}"
    holds = "holds" if info["criteria"]["2_next_bar"] else "fails"
    parts = [
        f"model window {_signed(info['model_bp'], 1)} bp/session "
        f"(t {_signed(info['model_t'])})",
        f"next-bar {_signed(info['next_bar_bp'], 1)} "
        f"(t {_signed(info['next_bar_t'])}) {holds}",
        f"{REPORTED} {_signed(info['reported_bp'], 1)} bp/session",
        f"deflated Sharpe {_signed(info['dsr'])} at N = {OUTER_CANDIDATES}",
        _seed_text(info, record),
        f"drift-adjusted {_signed(info['drift_bp'], 1)} (t {_signed(info['drift_t'])})",
        f"per re-timed order {_signed(info['retimed_bp'], 1)} bp "
        f"(t {_signed(info['retimed_t'])}) over {info['retimed']} of "
        f"{info['orders']} orders",
        f"waited {_share(info['waited_share'])} "
        f"(mean {_signed(info['mean_wait'], 1)} sessions)",
    ]
    return f"{name}: {'; '.join(parts)} - {info['label']}"


# --- population skill (reported) -----------------------------------------------


# Each model's population skill on the T-S1 rows, per window (by row date)
# and grade (all, A+, A, B, C): the pooled Spearman of the forecast with
# the label, and the decision's hit rate - of the rows the model would make
# wait (yhat > 0), the share whose label is positive - beside the share it
# would make wait and the label's own positive share. `yhat`, `label` and
# `grades` are in the export's row order.
def population_skill(
    yhat: np.ndarray,
    label: np.ndarray,
    grades: np.ndarray,
    row_dates: np.ndarray,
    spans: Mapping[str, tuple[date | None, date | None]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return {window: {grade: skill}}: rows, spearman, wait, hit and base rates."""
    yhat = np.asarray(yhat, dtype=float)
    label = np.asarray(label, dtype=float)
    grades = np.asarray(grades)
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for w, (lo, hi) in spans.items():
        inside = (
            point_in_time.window(row_dates, lo, hi)
            & np.isfinite(yhat)
            & np.isfinite(label)
        )
        out[w] = {}
        for name, keep in (
            ("all", inside),
            *((GRADE_NAMES[g], inside & (grades == g)) for g in (3, 2, 1, 0)),
        ):
            wait = keep & (yhat > 0)
            out[w][name] = {
                "rows": int(keep.sum()),
                "spearman": io.spearman(yhat[keep], label[keep]),
                "wait_share": float(wait.sum() / keep.sum())
                if keep.any()
                else math.nan,
                "hit_rate": float((label[wait] > 0).mean()) if wait.any() else math.nan,
                "base_rate": float((label[keep] > 0).mean())
                if keep.any()
                else math.nan,
            }
    return out
