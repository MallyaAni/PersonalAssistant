"""Volatility sizing on the `/4` book: the CNN's forecast against trailing volatility as the sizing input.

The graded equal-weight policy (`policy_v4.allocator(mask)`: every A/A+
member at min(1 / count, HOLD_CAP)) is the arm the paper account runs. The
deep-intraday study left one usable result, a next-session volatility
forecast with out-of-sample R² 0.27 against trailing volatility
(`docs/research/deep-intraday-stage1-2026-09-27.md`), and registered this
trial: does that forecast, used to size the book, earn anything over the
book without it - and over the same sizing rule fed trailing volatility,
which is the control that separates "the forecast" from "inverse vol".

Every variant wraps the policy's allocator: it calls `policy_v4` for the
session's control weights and rescales them, never choosing a different
set of names. `VARIANTS` is fixed here before any run; each is one
registered trial. Two weight schemes and their combination, each fed the
CNN forecast or the trailing-20-session baseline:

- inverse volatility: the held names' weights proportional to 1 / sigma,
  renormalised to the control's total invested that session, each capped
  at `policy_v4.HOLD_CAP` with the excess redistributed (water-filling);
- volatility target: the control's weights scaled by min(1, target /
  predicted book volatility), where the predicted book volatility is the
  exposure-weighted sum of the names' sigma (a full-correlation proxy - the
  book's names move together) and the target is the median of the same
  quantity on the control's own book with the *realized* next-session
  volatility, over the choosing window, measured once before the run
  (`measure_vol_target`) and recorded in the payload; exposure never
  exceeds 1.0 (no leverage);
- hybrid: the inverse-volatility weights, then the volatility target.

sigma is exp(x / 2) of a log realized variance, the forecast's own scale
(`vol_forecast.sigma`). A held name with no sigma that session keeps the
control's weight - before the first fit (2018-02 on the store), on a
session the dataset has no row for, or for a name outside the dataset -
and the fallback share is counted and reported: a variant that falls back
often is the control wearing a different name.

Each variant is priced under the plain options (next-open fills) and under
the live execution policy (`market_pit_scorecard._live_options`), on the
pit scorecard's offsets and costs; the verdict reads live, because that is
what the account runs. The kill criteria are `verdict`'s docstring and the
pre-registration `docs/research/vol-sizing-plan-2026-09-27.md`. Nothing
here trades or changes the executor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.agents.trading.desk import paper, point_in_time, policy_v4, simulate
from backend.cli import market_pit_scorecard as scorecard
from backend.cli.market_pit_scorecard import WINDOWS, Curve, _on, _since, window_stats
from backend.market import candidate_stats
from backend.market.vol_forecast import Aligned, sigma

CONTROL = "ew"
FORECAST = "forecast"
TRAILING = "trailing"
SOURCES = (FORECAST, TRAILING)
INV_VOL = "inv-vol"
VOL_TARGET = "vol-target"
HYBRID = "hybrid"
SCHEMES = (INV_VOL, VOL_TARGET, HYBRID)
PLAIN = "plain"
LIVE = "live"
OPTION_SETS = (PLAIN, LIVE)
HAC_LAG = 20
VERDICT_COST_BPS = 25.0
CHOOSING = "2016-2023"
REPORTED = "2024-2026"
# The floors, fixed before the run: CAGR points over the control on the
# choosing window at 25 bp under live options, the paired Newey-West t
# against the control, and the points a forecast variant must earn over
# its trailing twin for the finding to be "the forecast" rather than
# "inverse vol".
ADOPT_POINTS = 1.0
ADOPT_T = 2.0
TWIN_POINTS = 0.5
ADOPT = "ADOPT (registered)"
RECORD = "RECORD"
INVERSE_VOL = "RECORD (inverse vol, not the forecast)"
# The weight cap every sized book keeps: the operator's hold limit.
CAP = policy_v4.HOLD_CAP
# Tolerance on the cap in the water-filling.
EPS = 1e-12


@dataclass(frozen=True)
class Variant:
    """One named sizing rule: the scheme, the sigma source, and its trailing twin."""

    name: str
    scheme: str | None = None
    source: str | None = None
    twin: str | None = None
    note: str = ""


# Fixed before the run and named in the payload: the control, each scheme
# fed the forecast and fed the trailing baseline. Six trials and the control.
VARIANTS: tuple[Variant, ...] = (
    Variant(CONTROL, note="control: policy_v4 as it is, equal weight capped at HOLD_CAP"),
    Variant(
        "inv-vol-forecast",
        INV_VOL,
        FORECAST,
        twin="inv-vol-trailing",
        note="held names weighted 1 / sigma from the CNN forecast, same total invested, cap 0.20",
    ),
    Variant(
        "inv-vol-trailing",
        INV_VOL,
        TRAILING,
        note="the same with the trailing-20-session realized volatility",
    ),
    Variant(
        "vol-target-forecast",
        VOL_TARGET,
        FORECAST,
        twin="vol-target-trailing",
        note="equal weights, exposure scaled to the volatility target from the CNN forecast, no leverage",
    ),
    Variant(
        "vol-target-trailing",
        VOL_TARGET,
        TRAILING,
        note="the same with the trailing baseline",
    ),
    Variant(
        "hybrid-forecast",
        HYBRID,
        FORECAST,
        twin="hybrid-trailing",
        note="inverse-volatility weights then the volatility target, both from the CNN forecast",
    ),
    Variant(
        "hybrid-trailing",
        HYBRID,
        TRAILING,
        note="the same with the trailing baseline",
    ),
)


# The variant by name, or KeyError.
def variant(name: str) -> Variant:
    """Return the registered variant called `name`."""
    for v in VARIANTS:
        if v.name == name:
            return v
    raise KeyError(name)


# The plain option set: no exit overlay, the live reset cadence, next-open fills.
def plain_options() -> dict[str, Any]:
    """Return the `simulate.run` keyword options for plain next-open fills."""
    return dict(use_exits=False, rebalance=paper.REBALANCE_EVERY)


# The option set by name on a panel: plain, or the live execution policy
# exactly as the scorecard prices the account.
def options_for(option_set: str, panel) -> dict[str, Any]:
    """Return the `simulate.run` keyword options of `option_set`."""
    if option_set == PLAIN:
        return plain_options()
    if option_set == LIVE:
        return scorecard._live_options(panel)
    raise ValueError(f"unknown option set {option_set!r}; expected one of {OPTION_SETS}")


# Distribute `total` over the names in proportion to `raw` (>= 0) with no
# name above `cap`: names that would exceed the cap are fixed at it and
# the remainder is shared among the rest in proportion, repeatedly. When
# every name is at the cap the sum falls short of `total` and the rest is
# cash. Names with raw 0 get 0.
def cap_and_renormalise(raw: np.ndarray, total: float, cap: float) -> np.ndarray:
    """Return weights proportional to `raw` summing to min(total, cap * count), none above cap."""
    raw = np.asarray(raw, dtype=float)
    out = np.zeros(len(raw))
    if not (np.isfinite(total) and total > 0):
        return out
    free = np.isfinite(raw) & (raw > 0)
    remaining = float(total)
    while free.any() and remaining > EPS:
        share = raw[free] / raw[free].sum() * remaining
        over = share > cap + EPS
        if not over.any():
            out[free] = share
            break
        idx = np.flatnonzero(free)
        out[idx[over]] = cap
        remaining -= cap * int(over.sum())
        free[idx[over]] = False
    return out


# The book's predicted volatility under weights `w` and per-name sigma: the
# exposure-weighted sum over the names with both (a full-correlation proxy).
def book_vol(weights: np.ndarray, sig: np.ndarray) -> float:
    """Return sum(w_i * sigma_i) over the names with a finite positive sigma."""
    w = np.asarray(weights, dtype=float)
    s = np.asarray(sig, dtype=float)
    have = (w > 0) & np.isfinite(s) & (s > 0)
    return float((w[have] * s[have]).sum()) if have.any() else math.nan


# One session's sized weights from the control's weights and the names'
# sigma. Names the control holds without a sigma keep the control's weight
# (the fallback) and are left out of the sizing; the others are rescaled by
# the scheme: inverse volatility renormalised to their share of the
# control's total under `cap`; the volatility target scaling their weights
# by min(1, target / book_vol); hybrid both in that order. Returns the
# weights, the count of held names and the count that fell back.
def size_weights(
    scheme: str, control: np.ndarray, sig: np.ndarray, target: float, cap: float = CAP
) -> tuple[np.ndarray, int, int]:
    """Return (weights, positions, fallbacks) for one session."""
    if scheme not in SCHEMES:
        raise ValueError(f"unknown scheme {scheme!r}; expected one of {SCHEMES}")
    control = np.asarray(control, dtype=float)
    sig = np.asarray(sig, dtype=float)
    held = control > 0
    have = held & np.isfinite(sig) & (sig > 0)
    positions = int(held.sum())
    fallbacks = int(positions - have.sum())
    out = control.copy()
    if not have.any():
        return out, positions, fallbacks
    if scheme in (INV_VOL, HYBRID):
        raw = np.zeros(len(control))
        raw[have] = 1.0 / sig[have]
        sized = cap_and_renormalise(raw, float(control[have].sum()), cap)
        out[have] = sized[have]
    if scheme in (VOL_TARGET, HYBRID):
        if not (np.isfinite(target) and target > 0):
            raise ValueError("the volatility target must be a finite positive number")
        predicted = book_vol(np.where(have, out, 0.0), sig)
        if np.isfinite(predicted) and predicted > 0:
            out[have] *= min(1.0, target / predicted)
    return out, positions, fallbacks


# The control's target weights on every session of the restricted report:
# (T, N), the policy read at each session's close.
def control_weights(restricted, mask: np.ndarray) -> np.ndarray:
    """Return policy_v4's (T, N) target weights over the panel."""
    panel = restricted.panel
    allocate = policy_v4.allocator(mask)
    weights = np.zeros((len(panel.dates), len(panel.tickers)))
    for t in range(len(panel.dates)):
        weights[t] = allocate(restricted, panel, None, t)
    return weights


# The volatility target, measured once before the run from the control
# itself: the median over the choosing window's sessions of the control
# book's exposure-weighted realized next-session volatility (`realized`
# from the forecast file; the trailing baseline when the file carries no
# realized column), over sessions on which every held name has a value.
# Returns the number and how it was made; the target is NaN when no session
# qualifies, and the volatility-target variants are then refused.
def measure_vol_target(
    weights: np.ndarray,
    aligned: Aligned,
    window: str = CHOOSING,
) -> dict[str, Any]:
    """Return {target, source, window, sessions, sessions_in_window}."""
    source = "realized" if aligned.realized is not None else "baseline"
    values = aligned.realized if aligned.realized is not None else aligned.baseline
    sig = sigma(values)
    start, end = WINDOWS[window]
    keep = point_in_time.window(aligned.dates, start, end)
    held = weights > 0
    complete = held.any(axis=1) & ~(held & ~np.isfinite(sig)).any(axis=1) & keep
    proxy = np.array([book_vol(weights[t], sig[t]) for t in np.flatnonzero(complete)])
    proxy = proxy[np.isfinite(proxy)]
    return {
        "target": float(np.median(proxy)) if len(proxy) else math.nan,
        "source": source,
        "window": window,
        "sessions": int(len(proxy)),
        "sessions_in_window": int(keep.sum()),
        "definition": (
            "median over the choosing window of sum_i w_i * sigma_i on the control's "
            "own target weights, sigma_i = exp(log realized variance of the next "
            "session / 2), sessions where every held name has a value"
        ),
    }


class Sizer:
    """A variant's allocator around `policy_v4.allocator(mask)`, with its fallback record."""

    # Bind the variant, the mask, the aligned forecasts and the target.
    def __init__(
        self, variant_: Variant, mask: np.ndarray, aligned: Aligned, vol_target: float
    ) -> None:
        self.variant = variant_
        self.base = policy_v4.allocator(mask)
        self.aligned = aligned
        self.vol_target = float(vol_target)
        rows = len(aligned.dates)
        # Per decision session: the control's held count, how many of them
        # fell back, and the sized book's total exposure; NaN off rebalances.
        self.positions = np.full(rows, np.nan)
        self.fallbacks = np.full(rows, np.nan)
        self.exposure = np.full(rows, np.nan)
        if variant_.scheme is not None and variant_.source not in SOURCES:
            raise ValueError(f"unknown sigma source {variant_.source!r}")
        if variant_.scheme in (VOL_TARGET, HYBRID) and not (
            np.isfinite(self.vol_target) and self.vol_target > 0
        ):
            raise ValueError(
                f"{variant_.name} needs a finite positive volatility target"
            )

    # The sigma row the variant reads at session t.
    def _sigma(self, t: int) -> np.ndarray:
        source = (
            self.aligned.forecast
            if self.variant.source == FORECAST
            else self.aligned.baseline
        )
        return sigma(source[t])

    # The allocator: the control's weights, rescaled by the variant's
    # scheme. The control variant returns the control's weights untouched.
    def allocate(self, report, panel, config, t: int) -> np.ndarray:
        """Return the sized target weights for session t."""
        control = np.asarray(self.base(report, panel, config, t), dtype=float)
        if self.variant.scheme is None:
            self.positions[t] = int((control > 0).sum())
            self.fallbacks[t] = 0
            self.exposure[t] = float(control.sum())
            return control
        out, positions, fallbacks = size_weights(
            self.variant.scheme, control, self._sigma(t), self.vol_target
        )
        self.positions[t] = positions
        self.fallbacks[t] = fallbacks
        self.exposure[t] = float(out.sum())
        return out


@dataclass
class Priced:
    """One variant under one option set from one offset at one cost."""

    curve: Curve
    option_set: str
    positions: np.ndarray  # per session, NaN off rebalances
    fallbacks: np.ndarray
    exposure: np.ndarray


# Price one variant under one option set from one offset at one cost.
def price(
    restricted,
    mask: np.ndarray,
    variant_: Variant,
    option_set: str,
    since,
    cost_bps: float,
    aligned: Aligned,
    vol_target: float,
) -> Priced:
    """Return the variant's Priced result from `since` at `cost_bps`."""
    panel = restricted.panel
    sizer = Sizer(variant_, mask, aligned, vol_target)
    result = simulate.run(
        restricted,
        since=since,
        cost_bps=cost_bps,
        allocator=sizer.allocate,
        **options_for(option_set, panel),
    )
    return Priced(
        Curve(variant_.name, result.dates, result.returns),
        option_set,
        sizer.positions,
        sizer.fallbacks,
        sizer.exposure,
    )


# The key a priced run is stored under.
def key(name: str, option_set: str) -> str:
    """Return "<variant>@<option set>"."""
    return f"{name}@{option_set}"


# Median over finite entries, NaN when there are none.
def _nanmedian(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.nanmedian(x)) if np.isfinite(x).any() else math.nan


# Minimum over finite entries, NaN when there are none.
def _nanmin(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.nanmin(x)) if np.isfinite(x).any() else math.nan


# Maximum over finite entries, NaN when there are none.
def _nanmax(x) -> float:
    x = np.asarray(x, dtype=float)
    return float(np.nanmax(x)) if np.isfinite(x).any() else math.nan


# CAGR over the absolute drawdown, NaN when either is missing or the
# drawdown is zero.
def ratio(cagr: float, drawdown: float) -> float:
    """Return cagr / |drawdown|."""
    if not (np.isfinite(cagr) and np.isfinite(drawdown)) or drawdown == 0:
        return math.nan
    return float(cagr / abs(drawdown))


# The reference calendar of one offset: the plain control's sessions, else
# the first run that exists.
def _calendar(offset: dict[str, Priced], panel_dates: np.ndarray) -> np.ndarray:
    control = offset.get(key(CONTROL, PLAIN)) or next(iter(offset.values()), None)
    return control.curve.dates if control is not None else panel_dates


# One row per (variant, option set, window) at one cost: medians, worsts,
# the ratio, the count of offsets above the control under the same
# options, the fallback share and the median exposure on the window's
# rebalance sessions.
def summarise(
    priced: list[dict[str, Priced]], cost_bps: float, panel_dates: np.ndarray
) -> list[dict[str, Any]]:
    """Return the per-window rows across the offsets at `cost_bps`."""
    rows: list[dict[str, Any]] = []
    panel_dates = np.asarray(panel_dates).astype("datetime64[D]")
    for option_set in OPTION_SETS:
        names = [
            v.name
            for v in VARIANTS
            if all(key(v.name, option_set) in offset for offset in priced)
        ]
        for window, (start, end) in WINDOWS.items():
            stats: dict[str, list[dict[str, float]]] = {n: [] for n in names}
            fallback: dict[str, list[float]] = {n: [] for n in names}
            exposure: dict[str, list[float]] = {n: [] for n in names}
            keep_panel = point_in_time.window(panel_dates, start, end)
            for offset in priced:
                base = _calendar(offset, panel_dates)
                keep = point_in_time.window(base, start, end)
                for name in names:
                    run = offset[key(name, option_set)]
                    stats[name].append(window_stats(_on(base, run.curve)[keep]))
                    decided = keep_panel & np.isfinite(run.positions)
                    held = float(np.nansum(run.positions[decided]))
                    fell = float(np.nansum(run.fallbacks[decided]))
                    fallback[name].append(fell / held if held > 0 else math.nan)
                    exposure[name].append(_nanmedian(run.exposure[decided]))
            control_cagr = np.array(
                [s["cagr"] for s in stats.get(CONTROL, [])], dtype=float
            )
            for name in names:
                cagrs = np.array([s["cagr"] for s in stats[name]], dtype=float)
                above = (
                    int(np.nansum(cagrs > control_cagr))
                    if len(control_cagr) == len(cagrs) and name != CONTROL
                    else 0
                )
                median_cagr = _nanmedian(cagrs)
                median_dd = _nanmedian([s["drawdown"] for s in stats[name]])
                rows.append(
                    {
                        "line": name,
                        "options": option_set,
                        "cost_bps": cost_bps,
                        "window": window,
                        "offsets": len(priced),
                        "median_cagr": median_cagr,
                        "worst_cagr": _nanmin(cagrs),
                        "best_cagr": _nanmax(cagrs),
                        "median_drawdown": median_dd,
                        "median_sharpe": _nanmedian([s["sharpe"] for s in stats[name]]),
                        "ratio": ratio(median_cagr, median_dd),
                        "offsets_above_control": above,
                        "fallback_share": _nanmedian(fallback[name]),
                        "median_exposure": _nanmedian(exposure[name]),
                        "sessions": int(
                            np.nanmedian([s["sessions"] for s in stats[name]])
                        ),
                    }
                )
    return rows


# The paired daily difference of one curve against another on a window.
def _pair_row(
    base: np.ndarray, a: Priced, b: Priced, keep: np.ndarray, extra: dict[str, Any]
) -> dict[str, Any]:
    diff = _on(base, a.curve)[keep] - _on(base, b.curve)[keep]
    diff = diff[np.isfinite(diff)]
    mom = candidate_stats.moments(diff) if len(diff) > 2 else None
    return {
        **extra,
        "sessions": int(len(diff)),
        "mean_daily_bp": float(diff.mean() * 1e4) if len(diff) else math.nan,
        "hac_t": candidate_stats.hac_t(diff, HAC_LAG) if len(diff) > 2 else math.nan,
        "psr": (
            candidate_stats.probabilistic_sharpe(
                mom.sharpe, mom.length, mom.skew, mom.kurtosis
            )
            if mom is not None
            else math.nan
        ),
    }


# The paired daily differences at the median offset, per option set and
# window: every variant against the control, and every forecast variant
# against its trailing twin. Field names are the scorecard's.
def paired(
    priced: list[dict[str, Priced]], cost_bps: float, panel_dates: np.ndarray
) -> list[dict[str, Any]]:
    """Return the paired rows at the median offset for `cost_bps`."""
    out: list[dict[str, Any]] = []
    offset = priced[len(priced) // 2]
    base = _calendar(offset, panel_dates)
    for option_set in OPTION_SETS:
        control = offset.get(key(CONTROL, option_set))
        for window, (start, end) in WINDOWS.items():
            keep = point_in_time.window(base, start, end)
            for v in VARIANTS:
                run = offset.get(key(v.name, option_set))
                if run is None:
                    continue
                extra = {
                    "cost_bps": cost_bps,
                    "options": option_set,
                    "window": window,
                    "line": v.name,
                }
                if v.name != CONTROL and control is not None:
                    out.append(_pair_row(base, run, control, keep, {**extra, "against": CONTROL}))
                twin = offset.get(key(v.twin, option_set)) if v.twin else None
                if twin is not None:
                    out.append(_pair_row(base, run, twin, keep, {**extra, "against": v.twin}))
    return out


# Run every variant under both option sets at every offset and cost and
# assemble the payload. `store` is accepted for the scorecard's call shape
# and not read. The volatility target is measured once here, before any
# run, from the control's own weights. A run `simulate.run` or the sizer
# refuses is recorded under `refused` and left out of the rows.
def run_variants(
    report,
    restricted,
    mask: np.ndarray,
    store,
    offsets: int,
    costs: tuple[float, ...],
    aligned: Aligned,
) -> dict[str, Any]:
    """Return the volatility-sizing payload for the policy on the restricted report."""
    panel = restricted.panel
    weights = control_weights(restricted, mask)
    target_info = measure_vol_target(weights, aligned)
    vol_target = float(target_info["target"])
    refused: dict[str, str] = {}
    held = weights > 0
    payload: dict[str, Any] = {
        "study": "vol_sizing",
        "policy": policy_v4.POLICY_VERSION,
        "asof": str(panel.dates[-1]),
        "offsets": int(offsets),
        "costs_bps": [float(c) for c in costs],
        "option_sets": list(OPTION_SETS),
        "windows": {
            k: [str(s) if s else None, str(e) if e else None]
            for k, (s, e) in WINDOWS.items()
        },
        "trials": len(VARIANTS) - 1,
        "variants": [
            {
                "name": v.name,
                "scheme": v.scheme,
                "source": v.source,
                "twin": v.twin,
                "note": v.note,
            }
            for v in VARIANTS
        ],
        "cap": CAP,
        "vol_target": target_info,
        "forecast_coverage": {
            "cells": float(aligned.coverage()),
            "held_cells": float(np.isfinite(aligned.forecast[held]).mean())
            if held.any()
            else math.nan,
            "first_session_with_forecast": (
                str(aligned.dates[np.flatnonzero(np.isfinite(aligned.forecast).any(axis=1))[0]])
                if np.isfinite(aligned.forecast).any()
                else None
            ),
        },
        "hac_lag": HAC_LAG,
        "rows": [],
        "paired": [],
        "refused": refused,
        "note": (
            "Every non-control variant is one registered trial, fixed in VARIANTS "
            "before the run. Each wraps policy_v4's allocator and rescales its "
            "weights; a held name with no sigma keeps the control's weight and is "
            "counted in fallback_share. Priced under plain next-open fills and "
            "under the live execution policy on identical sessions from each of the "
            "first `offsets` sessions; medians and worsts are across offsets; paired "
            "statistics at the median offset against the control under the same "
            "options and against the trailing twin. The verdict reads live at 25 bp."
        ),
    }
    for cost in costs:
        priced: list[dict[str, Priced]] = []
        for k in range(int(offsets)):
            since = _since(panel, k)
            offset: dict[str, Priced] = {}
            for option_set in OPTION_SETS:
                for v in VARIANTS:
                    k_ = key(v.name, option_set)
                    if k_ in refused:
                        continue
                    try:
                        offset[k_] = price(
                            restricted, mask, v, option_set, since, float(cost), aligned, vol_target
                        )
                    except ValueError as exc:
                        refused[k_] = f"refused: {exc}"
            priced.append(offset)
        for offset in priced:
            for k_ in list(offset):
                if k_ in refused:
                    del offset[k_]
        payload["rows"].extend(summarise(priced, float(cost), panel.dates))
        payload["paired"].extend(paired(priced, float(cost), panel.dates))
    payload["ran"] = [
        key(v.name, o) for o in OPTION_SETS for v in VARIANTS if key(v.name, o) not in refused
    ]
    return payload


# The row for a line under an option set on a window at a cost, or None.
def _row(
    payload: dict[str, Any], line: str, option_set: str, window: str, cost: float
) -> dict | None:
    for r in payload["rows"]:
        if (
            r["line"] == line
            and r["options"] == option_set
            and r["window"] == window
            and float(r["cost_bps"]) == cost
        ):
            return r
    return None


# The paired entry for a line against another under an option set on a
# window at a cost, or None.
def _pair(
    payload: dict[str, Any],
    line: str,
    against: str,
    option_set: str,
    window: str,
    cost: float,
) -> dict | None:
    for p in payload["paired"]:
        if (
            p["line"] == line
            and p["against"] == against
            and p["options"] == option_set
            and p["window"] == window
            and float(p["cost_bps"]) == cost
        ):
            return p
    return None


# A payload value that may be None (after json_ready) or NaN, as a float.
def _f(value) -> float:
    return math.nan if value is None else float(value)


# A signed number to `digits` decimals, "n/a" for NaN.
def _signed(x: float, digits: int = 2) -> str:
    return "n/a" if not np.isfinite(x) else f"{x:+.{digits}f}"


# The floors read for one variant against the control under one option
# set at one cost: points, t, drawdown, the reported window, the twin.
def _assess(
    payload: dict[str, Any], v: Variant, option_set: str, cost: float
) -> dict[str, Any]:
    row = _row(payload, v.name, option_set, CHOOSING, cost) or {}
    control = _row(payload, CONTROL, option_set, CHOOSING, cost) or {}
    later = _row(payload, v.name, option_set, REPORTED, cost) or {}
    control_later = _row(payload, CONTROL, option_set, REPORTED, cost) or {}
    pair = _pair(payload, v.name, CONTROL, option_set, CHOOSING, cost) or {}
    later_pair = _pair(payload, v.name, CONTROL, option_set, REPORTED, cost) or {}
    cagr = _f(row.get("median_cagr"))
    points = (cagr - _f(control.get("median_cagr"))) * 100.0
    t = _f(pair.get("hac_t"))
    drawdown = _f(row.get("median_drawdown"))
    control_drawdown = _f(control.get("median_drawdown"))
    later_bp = _f(later_pair.get("mean_daily_bp"))
    twin_row = (
        _row(payload, v.twin, option_set, CHOOSING, cost) or {} if v.twin else {}
    )
    twin_points = (cagr - _f(twin_row.get("median_cagr"))) * 100.0 if v.twin else math.nan
    measured = bool(np.isfinite(points))
    return {
        "measured": measured,
        "cagr": cagr,
        "choosing_points": points,
        "choosing_bp_vs_control": _f(pair.get("mean_daily_bp")),
        "choosing_t_vs_control": t,
        "drawdown": drawdown,
        "control_drawdown": control_drawdown,
        "ratio": _f(row.get("ratio")),
        "control_ratio": _f(control.get("ratio")),
        "reported_points": (
            _f(later.get("median_cagr")) - _f(control_later.get("median_cagr"))
        )
        * 100.0,
        "reported_bp_vs_control": later_bp,
        "fallback_share": _f(row.get("fallback_share")),
        "median_exposure": _f(row.get("median_exposure")),
        "twin": v.twin,
        "twin_points": twin_points,
        "passes_points": bool(measured and points >= ADOPT_POINTS),
        "passes_t": bool(np.isfinite(t) and t >= ADOPT_T),
        "drawdown_not_worse": bool(
            np.isfinite(drawdown)
            and np.isfinite(control_drawdown)
            and drawdown >= control_drawdown
        ),
        "not_worse_reported": bool(np.isfinite(later_bp) and later_bp >= 0.0),
        "beats_twin": bool(np.isfinite(twin_points) and twin_points >= TWIN_POINTS),
    }


# The verdict, fixed before the run. A forecast variant is ADOPT
# (registered) only if, on 2016-2023 at 25 bp under the live options, its
# median CAGR is at least ADOPT_POINTS above the control with the paired
# Newey-West t against the control at least ADOPT_T, its median worst
# drawdown is not worse than the control's, it is not worse than the
# control on 2024-2026 by paired bp a day, AND it beats its trailing twin
# by at least TWIN_POINTS. A variant that clears everything but the twin
# is RECORD labelled "inverse vol, not the forecast". Everything else is
# RECORD. Trailing variants are controls and are assessed but never
# adopted. The plain-options numbers are carried beside the live ones.
def verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the verdict block for the payload."""
    costs = [float(c) for c in payload.get("costs_bps", [])]
    cost = (
        VERDICT_COST_BPS
        if VERDICT_COST_BPS in costs
        else (max(costs) if costs else math.nan)
    )
    control = _row(payload, CONTROL, LIVE, CHOOSING, cost) or {}
    control_cagr = _f(control.get("median_cagr"))
    variants: dict[str, dict[str, Any]] = {}
    adopt: list[str] = []
    inverse: list[str] = []
    for v in VARIANTS:
        if v.scheme is None:
            continue
        live = _assess(payload, v, LIVE, cost)
        plain = _assess(payload, v, PLAIN, cost)
        floors = (
            live["passes_points"]
            and live["passes_t"]
            and live["drawdown_not_worse"]
            and live["not_worse_reported"]
        )
        if v.source == FORECAST:
            if floors and live["beats_twin"]:
                decision = ADOPT
            elif floors:
                decision = INVERSE_VOL
            else:
                decision = RECORD
        else:
            decision = RECORD
        variants[v.name] = {
            "scheme": v.scheme,
            "source": v.source,
            "refused": payload.get("refused", {}).get(key(v.name, LIVE)),
            "live": live,
            "plain": plain,
            "passes_floors_live": bool(floors),
            "decision": decision,
        }
        if decision == ADOPT:
            adopt.append(v.name)
        elif decision == INVERSE_VOL:
            inverse.append(v.name)
    if not np.isfinite(control_cagr):
        text = (
            f"not measured: the control has no {CHOOSING} CAGR at {cost:g} bp under "
            f"live options (refused: {sorted(payload.get('refused', {})) or 'none'})"
        )
    else:
        parts = [
            f"{name} {_signed(info['live']['choosing_points'], 1)} pt "
            f"(t {_signed(info['live']['choosing_t_vs_control'])}, maxDD "
            f"{info['live']['drawdown'] * 100:.1f}% vs {info['live']['control_drawdown'] * 100:.1f}%"
            + (
                f", vs twin {_signed(info['live']['twin_points'], 1)} pt"
                if info['source'] == FORECAST
                else ""
            )
            + f", fallback {info['live']['fallback_share'] * 100:.0f}%) {info['decision']}"
            for name, info in variants.items()
        ]
        target = _f((payload.get("vol_target") or {}).get("target"))
        text = (
            f"{CHOOSING} at {cost:g} bp under live options: control {control_cagr * 100:.1f}% "
            f"(maxDD {_f(control.get('median_drawdown')) * 100:.1f}%, ratio "
            f"{_f(control.get('ratio')):.2f}); volatility target {target:.4f} per session. "
            + "; ".join(parts)
            + ". "
            + (
                f"{ADOPT}: {', '.join(adopt)}."
                if adopt
                else (
                    f"No forecast variant clears {ADOPT_POINTS:g} pt with t >= {ADOPT_T:g}, "
                    f"drawdown not worse, not worse on {REPORTED}, and {TWIN_POINTS:g} pt "
                    f"over its trailing twin"
                    + (
                        f"; {', '.join(inverse)} clear the floors but not the twin - the "
                        "finding is inverse vol, not the forecast."
                        if inverse
                        else "; every variant is RECORD."
                    )
                )
            )
        )
    return {
        "cost_bps": cost,
        "options": LIVE,
        "choosing_window": CHOOSING,
        "reported_window": REPORTED,
        "floors": {
            "points": ADOPT_POINTS,
            "hac_t": ADOPT_T,
            "twin_points": TWIN_POINTS,
            "drawdown_not_worse": True,
            "reported_not_worse": True,
        },
        "control_cagr": control_cagr,
        "control_drawdown": _f(control.get("median_drawdown")),
        "control_ratio": _f(control.get("ratio")),
        "vol_target": _f((payload.get("vol_target") or {}).get("target")),
        "variants": variants,
        "adopt": adopt,
        "inverse_vol": inverse,
        "text": text,
    }
