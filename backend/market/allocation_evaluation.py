"""Reproducible fixed-candidate funded evaluation and its scorecard.

This is the evaluation role's runner: given the trusted cached inputs (the
corrected desk report pickle and the separately aligned SPY/QQQ adjusted-price
npz, both read only through explicit local paths), it reproduces the fixed
funded comparison declared in `PARALLEL_CONTRACT.md` and the acceptance file.
No fetch, no model recomputation, no training, and no parameter search happen
here; every convention is fixed up front.

Fixed conventions (the ones the acceptance predeclares):

* common window 2016-01-04 .. 2026-09-18 (session index 252 of the cached
  2015-01-02 .. 2026-09-18 calendar),
* starting NAV 1 on the first session, first fill at the first next open,
* 10 bps one-way cost on the funded ledger's convention, zero cash interest,
* dividend-inclusive SPY and QQQ, compared separately,
* no window or fitting tuning.

Every number is retrospective, survivor-biased and reused history; passing
this diagnostic is not fresh-holdout proof, and no strategy is promoted for a
better aggregate alone.

The `common-window-reference` NPZ is the authoritative independent control for
the common dates (its incumbent and benchmark series were produced elsewhere
and are checked against their own JSON below); the candidate scorecard in
`scripts/allocation-scorecard.py` is the independently checked reference for
the metric arithmetic, and this module reproduces its numbers rather than
duplicating its code.

The funded candidate runner (`run_funded_candidate`) runs the shared integrated
execution path: `simulate.run` with `funded_allocation=True` builds the stable
exposure-1 stock composition from the desk's sizing engine, applies the
reviewed pure decision (`backend.agents.trading.desk.allocation.decide`)
against the current absolute regime and event ceilings with the aligned
SPY/QQQ context, and sizes the orders from cash on hand through the shared
`funded_execution.plan_funded` and the simulator's funded `_Book`. That
simulator dependency is the root-integration snapshot and is not accepted for
final performance until root review; final candidate numbers are produced only
after that review (the CLI gates them behind `--final`). Until then the runner
is validated on synthetic and frozen baseline cases only.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import allocation, event_risk, paper, simulate
from backend.market.allocation_controls import constant_exposure

# The fixed evaluation window and conventions.
COMMON_START = np.datetime64("2016-01-04")
COMMON_END = np.datetime64("2026-09-18")
ANNUAL = 252
START_EQUITY = 1.0
COST_BPS = 10.0
CASH_INCOME = 0.0
RISK_CUT_POINTS = 0.10  # a risk cut drops target equity at least 10 points
RISK_CUT_RECOVER = 0.90  # the target that ends a merged cut episode
CANDIDATES = ("incumbent", "vol", "vol_trend")

# The names the loader accepts inside the aligned npz histories.
SPY = "SPY"
QQQ = "QQQ"


@dataclass(frozen=True)
class BenchmarkInputs:
    """The aligned SPY/QQQ adjusted-price histories and their calendar."""

    dates: np.ndarray  # (T,) full cached calendar (2015-01-02 .. 2026-09-18)
    spy: np.ndarray  # (T,) dividend-inclusive adjusted closes
    qqq: np.ndarray  # (T,) dividend-inclusive adjusted closes
    common_start: int  # the index of COMMON_START inside `dates`


@dataclass(frozen=True)
class ReferenceControls:
    """The authoritative independent controls for the common window."""

    dates: np.ndarray  # (T,) common dates
    incumbent_daily: np.ndarray  # (T,) includes the leading NAV NaN slot
    incumbent_equity: np.ndarray  # (T,) NAV, first value 1
    invested: np.ndarray  # (T,) fraction of equity in the market
    spy_daily: np.ndarray
    spy_equity: np.ndarray
    qqq_daily: np.ndarray
    qqq_equity: np.ndarray

    # The evaluated (leading slot removed) daily returns of each series.
    def evaluated(self) -> dict[str, np.ndarray]:
        """Return {name: evaluated daily returns} for incumbent, SPY and QQQ."""
        return {
            "incumbent": self.incumbent_daily[1:],
            SPY: self.spy_daily[1:],
            QQQ: self.qqq_daily[1:],
        }


@dataclass
class CandidateResult:
    """One candidate's aligned series, exposure and (when run) full trace."""

    name: str
    dates: np.ndarray  # (T,) common dates
    daily: np.ndarray  # (T,) includes the leading NAV NaN slot
    equity: np.ndarray  # (T,) NAV
    exposure: np.ndarray | None  # (T,) fraction of equity in the market
    trace: list[dict] | None  # one entry per decision session, or None
    method: str  # how the series was produced
    cost_bps: float = COST_BPS


# --------------------------------------------------------------------------- #
# Cache loaders: trusted local files only, strictly validated.
# --------------------------------------------------------------------------- #


# Validate a session calendar before any evaluation uses it.
def _validate_calendar(dates: np.ndarray) -> np.ndarray:
    """Return the validated sorted-unique datetime64[D] calendar (raises on bad)."""
    dates = np.asarray(dates)
    if dates.dtype.kind != "M":
        raise ValueError("the session calendar must be datetime64")
    if dates.ndim != 1:
        raise ValueError("the session calendar must be one-dimensional")
    if len(dates) < 2:
        raise ValueError("the session calendar needs at least two sessions")
    if np.isnat(dates).any():
        raise ValueError("the session calendar must not contain NaT")
    if len(np.unique(dates)) != len(dates):
        raise ValueError("the session calendar must contain unique dates")
    if not np.all(dates[1:] > dates[:-1]):
        raise ValueError("the session calendar must be strictly ascending")
    return dates


# Validate the aligned benchmark price history array.
def _validate_price_array(name: str, values, dates: np.ndarray) -> np.ndarray:
    """Return the finite positive price array aligned to `dates`, or raise."""
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1 or arr.shape[0] != len(dates):
        raise ValueError(
            f"{name} must be one-dimensional with one price per cached session; "
            "gaps are never filled"
        )
    if not np.isfinite(arr).all() or not (arr > 0).all():
        raise ValueError(
            f"{name} must carry complete finite positive prices; "
            "a missing interior price is rejected, never filled"
        )
    return arr


# Load and strictly validate the aligned SPY/QQQ price history npz.
def load_benchmark_prices(path: str | Path) -> BenchmarkInputs:
    """Return validated aligned SPY/QQQ histories from `path`, or raise.

    `path` is an explicit local path (the trusted cache); no default, no
    network. The npz must hold `dates`, `SPY` and `QQQ`, the calendar must
    cover the whole fixed window starting at or before COMMON_START, and the
    SPY/QQQ arrays must be complete positive finite prices over the whole
    calendar. The common-window slice is validated to start exactly on
    COMMON_START; an interior NaN is a hard failure, never a zero return.
    """
    with np.load(path, allow_pickle=False) as data:
        for required in ("dates", SPY, QQQ):
            if required not in data.files:
                raise ValueError(f"{path} must hold '{required}'")
        dates = _validate_calendar(data["dates"])
        spy = _validate_price_array(SPY, data[SPY], dates)
        qqq = _validate_price_array(QQQ, data[QQQ], dates)
    if dates[0] > COMMON_START:
        raise ValueError(
            f"benchmark calendar starts {dates[0]} after the common window "
            f"{COMMON_START}"
        )
    common = np.where(dates == COMMON_START)[0]
    if len(common) != 1:
        raise ValueError(f"benchmark calendar must contain exactly one {COMMON_START}")
    common_start = int(common[0])
    if dates[common_start] != COMMON_START or dates[-1] != COMMON_END:
        raise ValueError(
            f"benchmark calendar must cover {COMMON_START}..{COMMON_END} exactly"
        )
    return BenchmarkInputs(dates=dates, spy=spy, qqq=qqq, common_start=common_start)


# Validate the reference arrays' shape, initial NAV slot and completeness.
def _validate_reference_arrays(
    arrays: dict[str, np.ndarray], dates: np.ndarray
) -> None:
    """Raise ValueError if any reference array is misaligned or incomplete."""
    for name, arr in arrays.items():
        if arr.ndim != 1 or arr.shape[0] != len(dates):
            raise ValueError(f"reference '{name}' must align to the common dates")
    for name in ("incumbent_daily", "spy_daily", "qqq_daily"):
        if not np.isnan(arrays[name][0]):
            raise ValueError(
                f"reference '{name}' must lead with the initial NAV NaN slot"
            )
        if not np.isfinite(arrays[name][1:]).all():
            raise ValueError(
                f"reference '{name}' has a missing evaluated return; "
                "an interior gap is rejected, never filled"
            )
    for name in ("incumbent_equity", "spy_equity", "qqq_equity"):
        if arrays[name][0] != 1.0:
            raise ValueError(f"reference '{name}' must start at NAV 1")
        if not np.isfinite(arrays[name]).all() or not (arrays[name] > 0).all():
            raise ValueError(f"reference '{name}' must be finite positive")


# Load and strictly validate the authoritative common-window reference NPZ.
def load_common_window_reference(path: str | Path) -> ReferenceControls:
    """Return the authoritative independent common-window controls, or raise.

    The npz must carry `dates`, `incumbent_daily`, `incumbent_equity`,
    `invested`, `spy_daily`, `spy_equity`, `qqq_daily`, `qqq_equity` all
    aligned to the exact common dates (2016-01-04 .. 2026-09-18). The first
    daily slot is the intentional initial NAV (NaN, equity 1) and is the only
    missing return allowed; anything else non-finite rejects the whole file.
    """
    with np.load(path, allow_pickle=False) as data:
        required = (
            "dates",
            "incumbent_daily",
            "incumbent_equity",
            "invested",
            "spy_daily",
            "spy_equity",
            "qqq_daily",
            "qqq_equity",
        )
        for name in required:
            if name not in data.files:
                raise ValueError(f"{path} must hold '{name}'")
        dates = _validate_calendar(data["dates"])
        if dates[0] != COMMON_START or dates[-1] != COMMON_END:
            raise ValueError(
                f"reference dates must be exactly {COMMON_START}..{COMMON_END}"
            )
        arrays = {
            name: np.asarray(data[name], dtype=float)
            for name in required
            if name != "dates"
        }
        _validate_reference_arrays(arrays, dates)
    return ReferenceControls(
        dates=dates,
        incumbent_daily=arrays["incumbent_daily"],
        incumbent_equity=arrays["incumbent_equity"],
        invested=arrays["invested"],
        spy_daily=arrays["spy_daily"],
        spy_equity=arrays["spy_equity"],
        qqq_daily=arrays["qqq_daily"],
        qqq_equity=arrays["qqq_equity"],
    )


# Load the trusted corrected desk report from an explicit local pickle path.
def load_cached_report(path: str | Path) -> tuple[object, int]:
    """Return (report, common_start index) from the trusted pickle, or raise.

    The pickle is loaded from the explicit local `path` only, and the report
    must expose a `panel` whose calendar covers the fixed window and contains
    exactly one COMMON_START session. No fetch, no recomputation.
    """
    with open(path, "rb") as handle:
        report = pickle.load(handle)
    panel = getattr(report, "panel", None)
    if panel is None:
        raise ValueError(f"{path} does not hold a desk report with a panel")
    dates = np.asarray(panel.dates)
    if dates.dtype.kind != "M":
        raise ValueError("the report panel calendar must be datetime64")
    common = np.where(dates == COMMON_START)[0]
    if len(common) != 1:
        raise ValueError(f"the report panel must contain exactly one {COMMON_START}")
    common_start = int(common[0])
    if dates[common_start] != COMMON_START or dates[-1] != COMMON_END:
        raise ValueError(f"the report panel must cover {COMMON_START}..{COMMON_END}")
    return report, common_start


# Load the independently checked benchmark reference JSON for cross-checking.
def load_independent_reference(path: str | Path) -> dict:
    """Return the independent benchmark reference payload as a dict."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Candidate validation and the scorecard arithmetic.
# --------------------------------------------------------------------------- #


# Validate one candidate's series integrity (shape, NAV slot, completeness).
def validate_series_integrity(
    name: str, dates: np.ndarray, daily: np.ndarray, equity: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return (daily, equity) after integrity checks, or raise ValueError.

    The first daily slot is the intentional initial NAV (NaN, equity 1) and is
    the only missing return allowed; a missing interior or trailing return, a
    non-positive equity value, or a daily/equity disagreement rejects the
    whole candidate rather than becoming a shorter, favorable window. The
    calendar must be valid but is not required to be the fixed common window,
    so a narrowed validation run can use the same checks.
    """
    dates = _validate_calendar(dates)
    daily = np.asarray(daily, dtype=float)
    equity = np.asarray(equity, dtype=float)
    if daily.ndim != 1 or daily.shape[0] != len(dates):
        raise ValueError(
            f"{name}: daily returns must align to the session calendar "
            f"({len(dates)} sessions)"
        )
    if equity.ndim != 1 or equity.shape[0] != len(dates):
        raise ValueError(
            f"{name}: equity must align to the session calendar ({len(dates)} sessions)"
        )
    if not np.isnan(daily[0]):
        raise ValueError(f"{name}: the first daily slot must be the initial NAV NaN")
    if not np.isfinite(daily[1:]).all():
        raise ValueError(
            f"{name}: a missing interior or trailing return is rejected, never filled"
        )
    if equity[0] != START_EQUITY:
        raise ValueError(f"{name}: equity must start at NAV {START_EQUITY}")
    if not np.isfinite(equity).all() or not (equity > 0).all():
        raise ValueError(f"{name}: equity must be finite and strictly positive")
    if not np.allclose(
        daily[1:], equity[1:] / equity[:-1] - 1.0, rtol=1e-9, atol=1e-10
    ):
        raise ValueError(
            f"{name}: daily returns must be the equity curve's own returns; "
            "the series disagree"
        )
    return daily, equity


# Validate one candidate's aligned series against the common calendar.
def validate_candidate_series(
    name: str, dates: np.ndarray, daily: np.ndarray, equity: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return (daily, equity) after strict validation, or raise ValueError.

    `daily` and `equity` must align to the exact common dates; the integrity
    checks of `validate_series_integrity` then apply. A calendar mismatch is
    rejected rather than silently re-aligned by array offset.
    """
    dates = _validate_calendar(dates)
    if dates[0] != COMMON_START or dates[-1] != COMMON_END:
        raise ValueError(f"{name}: dates must be exactly {COMMON_START}..{COMMON_END}")
    return validate_series_integrity(name, dates, daily, equity)


# The full metric set over one evaluated return series, reference-convention.
def metrics(daily: np.ndarray) -> dict[str, float | None]:
    """Return the scorecard metrics for one evaluated return series.

    Follows the independently checked `allocation-scorecard` arithmetic: net
    compounded return, annualised return over 252-session years, realised
    volatility, maximum drawdown (positive loss), Sharpe, worst single session,
    worst five consecutive sessions, longest underwater interval and the
    recovery time (sessions from the trough back to the prior peak) of the
    longest episode. A non-finite evaluated return rejects the measurement.
    """
    values = np.asarray(daily, dtype=float)
    if not len(values) or not np.isfinite(values).all() or (values <= -1).any():
        raise ValueError("every evaluated return must be finite and above -100%")
    nav = np.r_[1.0, np.cumprod(1 + values)]
    dd = 1.0 - nav / np.maximum.accumulate(nav)
    longest = 0
    run = 0
    for underwater in dd > 0:
        run = run + 1 if underwater else 0
        longest = max(longest, run)
    vol = float(np.std(values) * np.sqrt(ANNUAL))
    recovery, unrecovered = _recovery_metrics(nav)
    return {
        "total": float(nav[-1] - 1.0),
        "annual": float(nav[-1] ** (ANNUAL / len(values)) - 1.0),
        "volatility": float(vol),
        "drawdown": float(dd.max()),
        "sharpe": float(np.mean(values) * ANNUAL / vol) if vol > 0 else None,
        "worst_day": float(values.min()),
        "worst_five_sessions": (
            float((nav[5:] / nav[:-5] - 1.0).min()) if len(values) >= 5 else None
        ),
        "longest_underwater_sessions": int(longest),
        "recovery_sessions": recovery,
        "unrecovered_episodes": int(unrecovered),
    }


# The recovery statistics over the NAV curve's underwater episodes.
def _recovery_metrics(nav: np.ndarray) -> tuple[int | None, int]:
    """Return (max sessions from trough back to prior peak, unrecovered count)."""
    dd = 1.0 - nav / np.maximum.accumulate(nav)
    underwater = dd > 0
    recoveries: list[int] = []
    unrecovered = 0
    start = None
    trough = None
    for i in range(1, len(nav)):
        if underwater[i] and not underwater[i - 1]:
            start = i - 1
            trough = i
        elif underwater[i]:
            trough = i if dd[i] >= dd[trough] else trough
        elif underwater[i - 1] and start is not None:
            recoveries.append(i - trough)
            start = None
            trough = None
    if start is not None and trough is not None:
        unrecovered = 1
    return (max(recoveries) if recoveries else None), unrecovered


# The two benchmark controls evaluated over the common window.
def controls_from_reference(reference: ReferenceControls) -> dict[str, np.ndarray]:
    """Return {SPY: evaluated daily, QQQ: evaluated daily} controls."""
    return {SPY: reference.spy_daily[1:], QQQ: reference.qqq_daily[1:]}


# The per-benchmark comparison and the two-benchmark objective for one candidate.
def compare_candidate(
    daily: np.ndarray, controls: dict[str, np.ndarray]
) -> dict[str, object]:
    """Return the metrics and per-benchmark comparisons for `daily`.

    The objective is met against a benchmark when the candidate's net
    compounded return is higher AND its maximum drawdown is no greater, on the
    common dates; `both_objectives_met` requires it against EACH of SPY and
    QQQ. Up/down capture is the arithmetic mean of the candidate's returns on
    the benchmark's positive/negative sessions divided by the benchmark's own
    mean on those sessions. No ranking or promotion is derived here.
    """
    candidate = np.asarray(daily, dtype=float)
    own = metrics(candidate)
    vs: dict[str, dict[str, float | bool | None]] = {}
    for symbol, control in controls.items():
        benchmark = np.asarray(control, dtype=float)
        if len(benchmark) != len(candidate):
            raise ValueError(
                f"{symbol} control must share the candidate's evaluated sessions"
            )
        benchmark_metrics = metrics(benchmark)
        up = benchmark > 0
        down = benchmark < 0
        vs[symbol] = {
            "return_advantage": float(own["total"] - benchmark_metrics["total"]),
            "drawdown_advantage": float(
                benchmark_metrics["drawdown"] - own["drawdown"]
            ),
            "objective_met": bool(
                own["total"] > benchmark_metrics["total"]
                and own["drawdown"] <= benchmark_metrics["drawdown"]
            ),
            "up_capture": (
                float(candidate[up].mean() / benchmark[up].mean())
                if bool(up.any())
                else None
            ),
            "down_capture": (
                float(candidate[down].mean() / benchmark[down].mean())
                if bool(down.any())
                else None
            ),
        }
    return {
        "metrics": own,
        "vs": vs,
        "both_objectives_met": bool(all(v["objective_met"] for v in vs.values())),
    }


# --------------------------------------------------------------------------- #
# Periods, subwindows and rolling comparisons.
# --------------------------------------------------------------------------- #


# The period masks over the evaluated sessions, labelled partial where short.
def year_and_subwindow_masks(dates: np.ndarray) -> dict[str, tuple[np.ndarray, bool]]:
    """Return {label: (mask over evaluated sessions, is_partial)}.

    Every calendar year 2016..2026 (2016 and 2026 labelled partial because
    they do not cover a full year inside the window) plus the
    `2023-through-end` subwindow from 2023-01-01 to the end. The same
    2020/2022/2023-through-end subwindows the acceptance calls out are the
    calendar 2020, calendar 2022 and the 2023-through-end block.
    """
    evaluated = dates[1:]
    periods: dict[str, tuple[np.ndarray, bool]] = {}
    for year in range(2016, 2027):
        mask = evaluated.astype("datetime64[Y]") == np.datetime64(f"{year}", "Y")
        if not mask.any():
            continue
        partial = bool(
            year == 2016
            and evaluated[0].astype("datetime64[Y]") == np.datetime64(f"{year}", "Y")
        )
        if year == 2026:
            partial = True
        periods[f"{year}"] = (mask, partial)
    after_2023 = evaluated >= np.datetime64("2023-01-01")
    periods["2023-through-end"] = (after_2023, True)
    return periods


# The trailing-252-session comparison on identical dates for one candidate.
def rolling_252(
    daily: np.ndarray, controls: dict[str, np.ndarray]
) -> dict[str, object]:
    """Return the trailing-252 window comparisons against each benchmark.

    Every complete trailing 252 evaluated sessions shares data with its
    neighbours, so `overlapping` is True and the fractions are of overlapping
    windows - never independent evidence. A window is won against a benchmark
    when net return is higher and drawdown no greater on those identical dates.
    """
    values = np.asarray(daily, dtype=float)
    if len(values) < ANNUAL:
        return {
            "windows": 0,
            "overlapping": True,
            "fraction_objective_met": {s: None for s in controls},
            "fraction_both_met": None,
        }
    won: dict[str, list[bool]] = {s: [] for s in controls}
    both: list[bool] = []
    for i in range(ANNUAL, len(values) + 1):
        window = metrics(values[i - ANNUAL : i])
        row_both = True
        for symbol, control in controls.items():
            bench = metrics(np.asarray(control)[i - ANNUAL : i])
            met = bool(
                window["total"] > bench["total"]
                and window["drawdown"] <= bench["drawdown"]
            )
            won[symbol].append(met)
            row_both = row_both and met
        both.append(row_both)
    return {
        "windows": len(both),
        "overlapping": True,
        "fraction_objective_met": {
            s: float(sum(flags) / len(flags)) if flags else None
            for s, flags in won.items()
        },
        "fraction_both_met": float(sum(both) / len(both)) if both else None,
    }


# --------------------------------------------------------------------------- #
# Exposure-matched hindsight diagnostics and the funded constant-equity ledger.
# --------------------------------------------------------------------------- #


# One funded constant-equity account: shares and cash, rebalanced daily.
def constant_equity_account(
    prices: np.ndarray,
    fraction: float,
    cost_bps: float = COST_BPS,
    *,
    opens: np.ndarray,
) -> np.ndarray:
    """Return a previous-close decision / next-open fill benchmark NAV."""
    return constant_exposure(prices, opens, fraction, cost_bps)


# The hindsight exposure-matched diagnostic for one candidate.
def exposure_matched_diagnostic(
    candidate: CandidateResult,
    common_prices: dict[str, np.ndarray],
    controls: dict[str, np.ndarray],
    common_opens: dict[str, np.ndarray],
) -> dict[str, object]:
    """Return the constant-equity benchmark accounts at the candidate's mean
    exposure, plus the return difference including timing and stock selection.

    `common_prices` are the common-window adjusted closes (SPY/QQQ) used to
    run the funded constant-equity ledgers; `controls` are the authoritative
    benchmark series used for the mean-exposure comparison. The result is
    explicitly a hindsight exposure diagnostic, not an isolated timing effect;
    it is never an executable strategy and never promotes a
    candidate.
    """
    if candidate.exposure is None:
        return {
            "unavailable": "candidate carries no exposure series",
            "accounts": {},
        }
    mean_exposure = float(np.nanmean(np.abs(candidate.exposure[1:])))
    accounts: dict[str, dict[str, object]] = {}
    for symbol, prices in common_prices.items():
        if symbol not in controls:
            continue
        equity = constant_equity_account(
            prices, mean_exposure, candidate.cost_bps, opens=common_opens[symbol]
        )
        daily = equity[1:] / equity[:-1] - 1.0
        accounted = metrics(daily)
        candidate_metrics = metrics(candidate.daily[1:])
        accounts[symbol] = {
            "constant_equity": mean_exposure,
            "metrics": accounted,
            "total_return_difference": float(
                candidate_metrics["total"] - accounted["total"]
            ),
        }
    return {
        "mean_observed_equity_exposure": float(mean_exposure),
        "accounts": accounts,
        "note": (
            "Hindsight exposure-matched diagnostic: each account holds the "
            "benchmark at the candidate's mean observed equity exposure with "
            "previous-close decisions and next-open fills at the candidate's "
            "cost, rebalanced daily. Differences include stock selection and "
            "timing, not isolated timing alpha. It is not an "
            "executable strategy selected ex ante."
        ),
    }


# --------------------------------------------------------------------------- #
# Trace diagnostics: turnover, fees, ledger invariants and false exits.
# --------------------------------------------------------------------------- #


# The ledger invariants the acceptance requires the trace to satisfy.
def trace_checks(  # noqa: C901 - independent chronological and ledger invariants
    trace: list[dict], cost_bps: float = COST_BPS
) -> dict[str, object]:
    """Return the result of the fixed trace sanity checks.

    Asserts, over a funded runner's trace: no negative cash or shares, no
    fill before the session after the decision, no fee on an unfilled amount,
    and that a missing-price day changed nothing. Each violation is reported
    as a count and the first offending entry.
    """
    violations: list[str] = []
    for entry in trace:
        stamp = entry.get("decision_date")
        if np.datetime64(entry["fill_date"]) <= np.datetime64(stamp):
            violations.append(f"noncausal fill at {stamp}")
        if (
            entry.get("cash_before", 0.0) < -1e-9
            or entry.get("cash_after", 0.0) < -1e-9
        ):
            violations.append(f"negative cash at {entry.get('decision_date')}")
        for symbol, qty in (entry.get("shares_after") or {}).items():
            if qty < -1e-9:
                violations.append(
                    f"negative shares {symbol} at {entry.get('decision_date')}"
                )
        before = entry.get("shares_before") or {}
        after = entry.get("shares_after") or {}
        fills = entry.get("fills") or {}
        deltas = entry.get("deltas") or {}
        buy = sell = 0.0
        for symbol in set(before) | set(after) | set(fills) | set(deltas):
            change = after.get(symbol, 0.0) - before.get(symbol, 0.0)
            fill = fills.get(symbol)
            filled = 0.0
            if fill is not None:
                qty, price = float(fill["qty"]), float(fill["fill_price"])
                if not (
                    np.isfinite(qty) and qty > 0 and np.isfinite(price) and price > 0
                ):
                    violations.append(f"invalid fill for {symbol} at {stamp}")
                    continue
                notional = qty * price
                if not np.isclose(notional, fill["notional"], rtol=1e-9, atol=1e-10):
                    violations.append(
                        f"fill notional disagrees for {symbol} at {stamp}"
                    )
                if fill["side"] == "buy":
                    buy += notional
                    filled = qty
                elif fill["side"] == "sell":
                    sell += notional
                    filled = -qty
                else:
                    violations.append(f"invalid fill side at {stamp}")
            if not np.isclose(change, filled, rtol=1e-9, atol=1e-10):
                violations.append(f"shares disagree with fills for {symbol} at {stamp}")
            if not np.isclose(change, deltas.get(symbol, 0.0), rtol=1e-9, atol=1e-10):
                violations.append(
                    f"shares disagree with deltas for {symbol} at {stamp}"
                )
        fees = (buy + sell) * cost_bps / 1e4
        expected_cash = entry["cash_before"] + sell - buy - fees
        for label, actual, expected in (
            ("cash conservation", entry["cash_after"], expected_cash),
            ("fees", entry.get("fees"), fees),
            ("traded notional", entry.get("notional_traded"), buy + sell),
        ):
            if actual is None or not np.isclose(
                actual, expected, rtol=1e-9, atol=1e-10
            ):
                violations.append(f"{label} disagrees at {stamp}")
        if buy * (1 + cost_bps / 1e4) > entry["cash_before"] + 1e-9:
            violations.append(f"buys spent same-session sale proceeds at {stamp}")
    return {
        "checked": bool(trace),
        "violations": violations,
        "clean": not violations,
    }


# Turnover and fee accounting from one trace.
def turnover_and_fees(trace: list[dict], terminal_equity: float) -> dict[str, float]:
    """Return traded notional, fees and turnover ratios from a trace.

    The integrated simulator trace reports each day's actual traded notional in
    `notional_traded` and its fees in `fees`; a legacy-style trace that split
    buys and sells into `notional_buy`/`notional_sell` is still summed the same
    way. Fees are charged only on executed notional, never on an unfilled or
    missing-price amount.
    """
    notional = 0.0
    fees = 0.0
    relative_notional = relative_fees = 0.0
    nav_complete = bool(trace)
    for entry in trace:
        traded = entry.get("notional_traded")
        if traded is not None:
            notional += float(traded)
        else:
            notional += float(entry.get("notional_buy", 0.0)) + float(
                entry.get("notional_sell", 0.0)
            )
        fees += float(entry.get("fees", 0.0))
        nav = entry.get("nav_before")
        if nav is None or not np.isfinite(nav) or nav <= 0:
            nav_complete = False
        else:
            relative_notional += float(traded or 0.0) / nav
            relative_fees += float(entry.get("fees", 0.0)) / nav
    return {
        "traded_notional": float(notional),
        "fees": float(fees),
        "sum_traded_notional_over_decision_nav": relative_notional
        if nav_complete
        else None,
        "annualized_two_way_turnover": (
            relative_notional * ANNUAL / len(trace) if nav_complete else None
        ),
        "sum_fees_over_decision_nav": relative_fees if nav_complete else None,
        "fees_to_terminal_nav": (
            float(fees / terminal_equity) if terminal_equity else None
        ),
        "traded_notional_to_terminal_nav": (
            float(notional / terminal_equity) if terminal_equity else None
        ),
    }


# Identify merged risk-cut episodes in a target-equity series.
def _risk_cut_episodes(
    target: np.ndarray,
) -> list[dict[str, int | float | None]]:
    """Return merged risk-cut episodes from the per-session target series.

    A cut episode starts at the first session whose target equity is at least
    `RISK_CUT_POINTS` below the preceding target, and merges successive cuts
    until the target recovers `RISK_CUT_RECOVER` of the pre-cut level.
    """
    n = len(target)
    episodes: list[dict[str, int | float | None]] = []
    i = 1
    while i < n:
        if target[i] <= target[i - 1] - RISK_CUT_POINTS:
            start = i
            pre_cut = float(target[i - 1])
            floor = pre_cut * RISK_CUT_RECOVER
            low = float(target[i])
            j = i
            while j + 1 < n and target[j + 1] < floor:
                j += 1
                low = min(low, float(target[j]))
            episodes.append(
                {
                    "start": start,
                    "end": j,
                    "pre_cut_target": pre_cut,
                    "cut_target": low,
                    "cut_depth_points": float(pre_cut - low),
                }
            )
            i = j + 1
        else:
            i += 1
    return episodes


# The forward-return and re-entry diagnostics for each risk-cut episode.
def false_exit_diagnostics(
    trace: list[dict], controls: dict[str, np.ndarray]
) -> dict[str, object]:
    """Return the false-exit diagnostics over `trace` against each benchmark.

    For each merged risk-cut episode, report the decision date, the pre-cut
    and cut target equity, the actual exposure after the decision, the delay
    (sessions) to regain 90% of the pre-cut actual exposure, and each
    benchmark's forward 5- and 20-session returns after that decision. An
    exit is labelled costly against a benchmark when the 20-session window
    rises. Episodes lacking a full 20-session horizon are censored, never
    labelled, and future returns only judge the decision afterwards - they
    never create a signal.
    """
    if not trace:
        return {"episodes": [], "controls": sorted(controls)}
    target = np.array([float(e.get("desired_equity", 0.0)) for e in trace])
    actual = np.array([float(e.get("exposure", np.nan)) for e in trace])
    evaluated_len = min(len(trace), min(len(np.asarray(c)) for c in controls.values()))
    episodes: list[dict[str, object]] = []
    for episode in _risk_cut_episodes(target):
        start = int(episode["start"])
        if start >= evaluated_len:
            continue
        fill_date = trace[start].get("fill_date") or trace[start].get("decision_date")
        pre_cut_actual = actual[start - 1] if start - 1 >= 0 else np.nan
        regain_target = pre_cut_actual * RISK_CUT_RECOVER
        delay: int | None = None
        for k in range(start, evaluated_len):
            if (
                np.isfinite(actual[k])
                and np.isfinite(pre_cut_actual)
                and actual[k] >= regain_target
            ):
                delay = k - start
                break
        horizon = evaluated_len - start
        forward: dict[str, dict[str, float | None]] = {}
        for symbol, control in controls.items():
            series = np.asarray(control)
            f5 = (
                float(np.prod(1.0 + series[start : start + 5]) - 1.0)
                if start + 5 <= evaluated_len
                else None
            )
            f20 = (
                float(np.prod(1.0 + series[start : start + 20]) - 1.0)
                if start + 20 <= evaluated_len
                else None
            )
            forward[symbol] = {
                "forward_5": f5,
                "forward_20": f20,
                "costly_exit": bool(f20 > 0) if f20 is not None else None,
            }
        episodes.append(
            {
                "decision_date": str(trace[start].get("decision_date")),
                "fill_date": str(fill_date),
                "pre_cut_target": float(episode["pre_cut_target"]),
                "cut_target": float(episode["cut_target"]),
                "cut_depth_points": float(episode["cut_depth_points"]),
                "actual_exposure_after_fill": float(actual[start]),
                "pre_cut_actual_exposure": float(pre_cut_actual),
                "reentry_delay_sessions": delay,
                "full_20_session_horizon": bool(horizon >= 20),
                "forward": forward,
            }
        )
    return {
        "episodes": episodes,
        "controls": sorted(controls),
        "note": (
            "Future returns judge each exit afterwards only; they never "
            "create a signal. A 20-session exit is costly against a benchmark "
            "when that benchmark rises over the interval. Terminal episodes "
            "lacking a full horizon are censored."
        ),
    }


# --------------------------------------------------------------------------- #
# The fixed-candidate runners.
# --------------------------------------------------------------------------- #


# The incumbent candidate, read from the authoritative reference NPZ.
def run_incumbent(reference: ReferenceControls) -> CandidateResult:
    """Return the incumbent candidate series from the reference controls."""
    dates = reference.dates
    daily = reference.incumbent_daily
    equity = reference.incumbent_equity
    validate_candidate_series("incumbent", dates, daily, equity)
    return CandidateResult(
        name="incumbent",
        dates=dates,
        daily=daily,
        equity=equity,
        exposure=np.asarray(reference.invested, dtype=float),
        trace=None,
        method="authoritative common-window reference (incumbent_daily)",
    )


# Run one fixed funded policy over the common window through the integrated
# simulator's shared funded execution path.
def run_funded_candidate(
    report,
    benchmark_prices: BenchmarkInputs,
    policy: str,
    *,
    index_eligible: bool = False,
    cost_bps: float = COST_BPS,
    start: np.datetime64 | None = None,
    end: np.datetime64 | None = None,
) -> CandidateResult:
    """Return the funded candidate series and full trace for `policy`.

    Runs the real integrated path - `simulate.run` with `funded_allocation=True`
    and the reviewed pure decision (`allocation.decide`) - over the fixed
    common window (NAV 1, next-open fills, `cost_bps` one-way, zero cash
    interest), narrowed to `start`/`end` when given. The aligned SPY/QQQ
    benchmark histories are passed as the dated context on the panel calendar;
    the FOMC live event exposure is applied as the absolute event ceiling, and
    the desk's scheduled rebalance clock drives the stable composition refresh.
    No incompatible live-policy option is passed. The result serializes the
    simulator's actual returns, equity, invested and per-session trace; the
    trace is enriched with the decision's desired-equity and the actual
    post-fill exposure so the scorecard's false-exit diagnostics read the
    integrated ledger. The simulator dependency is the root-integration
    snapshot and is not accepted for final performance until root review.
    """
    if policy not in allocation.POLICIES:
        raise ValueError(f"policy must be one of {allocation.POLICIES}")
    panel = report.panel
    if not np.array_equal(benchmark_prices.dates, panel.dates):
        raise ValueError("benchmark calendar must match the panel calendar exactly")
    start = COMMON_START if start is None else np.datetime64(start, "D")
    end = COMMON_END if end is None else np.datetime64(end, "D")
    t_start = int(np.where(panel.dates == start)[0][0])
    t_end = int(np.where(panel.dates == end)[0][0])
    result = simulate.run(
        report,
        since=start,
        rebalance=paper.REBALANCE_EVERY,
        cost_bps=cost_bps,
        use_exits=False,
        event_exposure=event_risk.live_path(report.panel),
        funded_allocation=True,
        allocation_policy=policy,
        index_eligible=index_eligible,
        benchmark_prices={
            "dates": benchmark_prices.dates,
            SPY: benchmark_prices.spy,
            QQQ: benchmark_prices.qqq,
        },
    )
    count = t_end - t_start + 1
    dates = result.dates[:count]
    daily = result.returns[:count]
    equity = result.equity[:count]
    exposure = result.invested[:count]
    trace = result.trace[: count - 1] if result.trace is not None else None
    if trace is not None:
        # Keep the desired target, but measure exposure from the settled account
        # at the following close; projected weights cannot represent actual fills.
        trace = [
            {
                **entry,
                "desired_equity": float(sum((entry.get("desired") or {}).values())),
                "exposure": float(exposure[i + 1]),
                "nav_before": float(equity[i]),
                "nav_after": float(equity[i + 1]),
                "actual_weights": {
                    symbol: float(
                        qty
                        * panel.adj_close[t_start + i + 1, panel.index(symbol)]
                        / equity[i + 1]
                    )
                    for symbol, qty in entry["shares_after"].items()
                },
            }
            for i, entry in enumerate(trace)
        ]
    validate_series_integrity(policy, dates, daily, equity)
    checks = trace_checks(trace or [], cost_bps)
    if not checks["checked"] or not checks["clean"]:
        raise ValueError(f"Invalid funded execution trace: {checks['violations'][:3]}")
    return CandidateResult(
        name=policy,
        dates=dates,
        daily=daily,
        equity=equity,
        exposure=exposure,
        trace=trace,
        cost_bps=cost_bps,
        method=(
            f"integrated simulator funded path "
            f"({simulate.FUNDING_MODEL}), policy {policy}, "
            f"research SPY eligibility={index_eligible}"
        ),
    )


# --------------------------------------------------------------------------- #
# The aggregate payload one candidate contributes to the scorecard.
# --------------------------------------------------------------------------- #


# The full scorecard payload for one candidate.
def evaluate_candidate(
    candidate: CandidateResult,
    controls: dict[str, np.ndarray],
    common_prices: dict[str, np.ndarray] | None = None,
    common_opens: dict[str, np.ndarray] | None = None,
) -> dict[str, object]:
    """Return the complete JSON-able scorecard payload for `candidate`.

    Combines the metrics, per-benchmark comparisons and two-benchmark
    objective, every calendar-year and subwindow comparison, the trailing-252
    windows, the exposure-matched hindsight diagnostic (when the candidate has
    an exposure series), the trace checks and false-exit diagnostics (when a
    trace is present), and the fixed-convention metadata. No ranking or
    promotion is produced.
    """
    daily = candidate.daily
    dates = candidate.dates
    evaluated = daily[1:]
    payload: dict[str, object] = {
        "candidate": candidate.name,
        "method": candidate.method,
        "from": str(dates[0]),
        "to": str(dates[-1]),
        "evaluated_sessions": int(len(evaluated)),
        "cost_bps": candidate.cost_bps,
        "cash_income": CASH_INCOME,
        "status": (
            "Retrospective reused survivor-biased data; not independent "
            "holdout evidence"
        ),
    }
    comparison = compare_candidate(evaluated, controls)
    payload.update(comparison)
    periods: dict[str, dict[str, object]] = {}
    for label, (mask, partial) in year_and_subwindow_masks(dates).items():
        periods[label] = {
            "partial": partial,
            "evaluated_sessions": int(mask.sum()),
            **compare_candidate(
                evaluated[mask], {s: c[mask] for s, c in controls.items()}
            ),
        }
    payload["periods"] = periods
    payload["rolling_252"] = rolling_252(evaluated, controls)
    if candidate.exposure is not None and common_prices is not None:
        if common_opens is None:
            raise ValueError("adjusted next-open prices are required for diagnostics")
        payload["exposure_matched"] = exposure_matched_diagnostic(
            candidate, common_prices, controls, common_opens
        )
    if candidate.trace is not None:
        payload["trace_checks"] = trace_checks(candidate.trace, candidate.cost_bps)
        payload["turnover_fees"] = turnover_and_fees(
            candidate.trace, float(candidate.equity[-1])
        )
        payload["false_exit"] = false_exit_diagnostics(candidate.trace, controls)
        weights = [entry.get("actual_weights", {}) for entry in candidate.trace]
        if weights and all("actual_weights" in entry for entry in candidate.trace):
            stocks = [
                sum(w for s, w in row.items() if s not in (SPY, QQQ)) for row in weights
            ]
            indexes = [sum(row.get(s, 0.0) for s in (SPY, QQQ)) for row in weights]
            payload["allocation_observed"] = {
                "mean_stock_weight": float(np.mean(stocks)),
                "mean_index_weight": float(np.mean(indexes)),
                "mean_cash_weight": float(1.0 - np.mean(np.array(stocks) + indexes)),
                "max_company_weight": max(
                    (
                        w
                        for row in weights
                        for s, w in row.items()
                        if s not in (SPY, QQQ)
                    ),
                    default=0.0,
                ),
                "note": "Closing weights; gaps and drift may exceed decision caps.",
            }
    return payload
