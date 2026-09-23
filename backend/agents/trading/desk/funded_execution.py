"""Shared daily funded allocation decision and its one order plan.

`allocation.decide` is the reviewed pure decision: it says what the desk
*wants* to hold. This module turns one decision day into the order basket
both the paper account and the simulator execute on the optional policy path,
so the two cannot drift apart again the way they did before `planner.plan`.

`plan_funded` is the one order planner. It sizes buys from the cash actually
on hand at the decision - never from the proceeds of sells filling the same
day - so a plan that says "sell X and buy Y" waits until the next daily plan
before Y's money is spent. It never sells more than is held. One min-trade
threshold applies to buys and sells alike, so the book is not left under
target by trims too small to matter; it never suppresses a full exit or a
genuine risk cut (`is_risk_cut`: a constraint binds *and* the held exposure
exceeds the decision's ceiling), which the decision requires however small.
The paper account asks for whole shares and re-checks the
cash, fee and name-cap bounds after rounding; the simulator asks for
continuous shares and fills through the funded `_Book`. Whole shares round to
the nearest share inside a half-share no-trade band on both sides
(`whole_share_gap`): a sell is never rounded up past its target, because the
share it oversold was bought back the next session and sold again the one
after, indefinitely, against a constant target.

`daily_decision` builds one day's `AllocationDecision` for the simulator from
the desk's own panel plus the dated SPY/QQQ benchmark context passed in
separately. The stable stock composition is *supplied* by the caller and
refreshed only on the caller's scheduled rebalance clock; `daily_decision`
never recomputes it, so a risk cut or a missing score on an ordinary day can
neither lose nor resurrect a name. SPY is only ever a risk benchmark and
residual asset, QQQ only a risk benchmark, and the dated context is validated
against the panel calendar rather than guessed. The incumbent default path
never calls this module, so its outputs are unchanged.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, replace

import numpy as np

from backend.agents.trading.desk import allocation, planner
from backend.agents.trading.desk.allocation import AllocationDecision
from backend.agents.trading.desk.paper import ENTRY_NAME_CAP


# The version the optional execution path reports for each policy.
def _version(policy: str) -> str:
    """Return the funded-execution version identifier for `policy`."""
    return f"funded-allocation/{policy}/1"


# Recover the policy name from the allocation decision's own version string.
def _policy_of(decision: AllocationDecision) -> str:
    """Return "vol" or "vol_trend" from a decision's version."""
    for name in allocation.POLICIES:
        if f"/{name}/" in decision.version:
            return name
    return allocation.POLICY_VOL_TREND


@dataclass(frozen=True)
class FundedPlan:
    """The shared order basket for one decision day, and why it is that.

    `executable` and `cash` are *projected* fractions of the post-fee NAV the
    returned order basket would produce at the reference prices: executable is
    each final holding's value over that NAV, and cash is the projected cash
    balance over the same NAV. Both are fractions of the same denominator, so
    they sum with the fee cost and any unfilled notional, and neither is
    presented as an actual ledger balance. When a held name cannot be valued
    both are `None`/empty with the explicit block reason.
    """

    policy: str
    index_eligible: bool
    version: str
    as_of: str
    available: bool
    desired: dict[str, float]
    executable: dict[str, float]
    cash: float | None
    orders: tuple[planner.Order, ...]
    reason: str
    missing: tuple[str, ...]
    blocked: tuple[str, ...]
    binding: str
    # The projected dollar cash balance and post-fee NAV of the returned order
    # basket at the reference prices, `None` when a held name blocks sizing.
    projected_cash_amount: float | None = None
    projected_equity: float | None = None
    # Whether the decision genuinely cut the held exposure below its ceiling
    # (see `is_risk_cut`), as opposed to merely reporting a binding constraint.
    risk_cut: bool = False


@dataclass(frozen=True)
class DailyDecision:
    """One decision day's allocation input and its blocking reasons."""

    policy: str
    index_eligible: bool
    as_of: str
    decision: AllocationDecision | None
    blocked: tuple[str, ...]
    reason: str


# Whether a price is usable as decision or valuation evidence.
def _price_ok(value) -> bool:
    """Return True when `value` is a finite positive price."""
    return value is not None and np.isfinite(value) and value > 0


# Verify the benchmark context's own calendar is exactly the panel's. Equal
# length is not alignment: prices aligned to the wrong session would shift
# every risk read, so a missing or malformed dates array is a caller error.
def _validate_benchmark_dates(panel, benchmark_prices) -> np.ndarray:
    """Return the validated benchmark dates equal to the panel calendar."""
    dates = benchmark_prices.get("dates")
    if dates is None:
        raise ValueError("benchmark context must carry its own dates")
    dates = np.asarray(dates)
    if dates.ndim != 1 or dates.dtype.kind != "M":
        raise ValueError("benchmark dates must be one-dimensional datetime64")
    if np.isnat(dates).any():
        raise ValueError("benchmark dates must not contain NaT")
    if len(dates) != len(panel.dates):
        raise ValueError(
            "benchmark dates must match the panel calendar exactly; "
            "equal length is not alignment"
        )
    if not np.array_equal(dates, panel.dates):
        raise ValueError("benchmark dates must equal the panel calendar exactly")
    return dates


# Validate the dated benchmark context the decision needs. Price gaps are *not*
# rejected here: a gap in the past reaches allocation.decide's missing-evidence
# and known-cap fallback, and a gap in the future must not reject an earlier
# decision. A panel that already carries QQQ is legitimate (its frozen scores
# and grades are untouched) - the benchmark QQQ column is used for risk and the
# panel column is never appended twice.
def validate_benchmarks(panel, benchmark_prices) -> dict[str, np.ndarray]:
    """Return the validated SPY/QQQ histories on the panel calendar."""
    if benchmark_prices is None:
        raise ValueError("funded allocation requires dated SPY/QQQ benchmark context")
    _validate_benchmark_dates(panel, benchmark_prices)
    required = (allocation.SPY, allocation.QQQ)
    rows = len(panel.dates)
    out: dict[str, np.ndarray] = {}
    for name in required:
        arr = benchmark_prices.get(name)
        if arr is None:
            raise ValueError(f"funded allocation requires a {name} benchmark history")
        arr = np.asarray(arr, dtype=float)
        if arr.ndim != 1 or arr.shape[0] != rows:
            raise ValueError(
                f"{name} must be a one-dimensional history aligned to the panel "
                "calendar; gaps are not filled"
            )
        out[name] = arr
    if allocation.SPY not in panel.tickers:
        raise ValueError(
            "the panel must carry tradable SPY prices for the context check"
        )
    return out


# Build the temporary input matrix allocation.decide reads: the stock columns
# plus SPY/QQQ, the frozen panel never being extended. SPY and QQQ are excluded
# from the stock set even when the panel already carries one of them, so the
# appended benchmark columns are never duplicated.
def _decision_inputs(
    panel, benchmarks: dict[str, np.ndarray]
) -> tuple[list[str], np.ndarray]:
    """Return (tickers, prices) for allocation.decide over the whole panel."""
    index_columns = (panel.benchmark, allocation.SPY, allocation.QQQ)
    tickers = [t for t in panel.tickers if t not in index_columns]
    tickers.append(allocation.SPY)
    tickers.append(allocation.QQQ)
    cols: list[np.ndarray] = []
    for ticker in panel.tickers:
        if ticker in index_columns:
            continue
        cols.append(panel.adj_close[:, panel.index(ticker)])
    cols.append(benchmarks[allocation.SPY])
    cols.append(benchmarks[allocation.QQQ])
    return tickers, np.column_stack(cols)


# The stable stock composition: what the desk wants to hold with full equity,
# preserving tightening, grades and the existing sizing limits. SPY and QQQ are
# never part of it - SPY is a residual index asset and QQQ a risk benchmark -
# even when the panel already carries one of them. The frozen scores and grades
# are copied, never mutated.
def stable_composition(report, panel, config, t: int) -> dict[str, float]:
    """Return the exposure-1 stock target dict, SPY/QQQ excluded."""
    window = replace(
        panel,
        dates=panel.dates[: t + 1],
        open=panel.open[: t + 1],
        high=panel.high[: t + 1],
        low=panel.low[: t + 1],
        close=panel.close[: t + 1],
        adj_close=panel.adj_close[: t + 1],
        volume=panel.volume[: t + 1],
    )
    graded = np.asarray(report.graded.grades[t], dtype=int).copy()
    excluded = (panel.benchmark, allocation.SPY, allocation.QQQ)
    for col, ticker in enumerate(panel.tickers):
        if ticker in excluded:
            graded[col] = 0
    regime = replace(report.regime.states[t], exposure=1.0)
    _positions, targets = _desk_targets(
        report.scores[t], graded, window, regime, config
    )
    return {
        ticker: float(targets[j])
        for j, ticker in enumerate(panel.tickers)
        if float(targets[j]) > 1e-9 and ticker not in excluded
    }


# The one desk sizing call, kept here so the composition and the simulator
# cannot call it in different orders.
def _desk_targets(scores, graded, window, regime, config):
    """Return (positions, targets) from risk.desk_targets with the given regime."""
    from backend.agents.trading.desk import risk

    return risk.desk_targets(scores, graded, window, regime, config)


# Whether the separately-passed SPY context agrees with the panel's own
# tradable SPY prices through the decision session. A conflict would feed two
# different SPY series to one decision, so it is a caller error, reported here
# rather than trusted. Future sessions are never read for this check.
def _check_spy_context(panel, benchmarks: dict[str, np.ndarray], t: int) -> None:
    """Raise ValueError where finite SPY context contradicts panel SPY through t."""
    column = panel.index(allocation.SPY)
    tradable = np.asarray(panel.adj_close[:, column], dtype=float)
    context = np.asarray(benchmarks[allocation.SPY], dtype=float)
    through = slice(0, t + 1)
    both = np.isfinite(tradable[through]) & np.isfinite(context[through])
    if not both.any():
        return
    agree = np.isclose(
        tradable[through][both], context[through][both], rtol=1e-6, atol=1e-9
    )
    if not bool(agree.all()):
        row = int(np.flatnonzero(~agree)[0])
        raise ValueError(
            "SPY benchmark context disagrees with the panel's tradable SPY "
            f"prices on {panel.dates[row]}"
        )


# The one explicit way a company-exit caller removes a name from the stable
# composition, preventing resurrection. A missing score is not an exit and must
# never reach here; only a genuine delisting/removal signal calls this.
def exclude_names(
    composition: dict[str, float], removed: Iterable[str]
) -> dict[str, float]:
    """Return `composition` without the named companies."""
    dropped = set(removed)
    return {
        name: float(weight)
        for name, weight in composition.items()
        if name not in dropped
    }


# One decision day for the simulator: build the allocation input from the real
# panel and ledger and run the pure decision.
def daily_decision(
    report,
    panel,
    config,
    t: int,
    *,
    policy: str,
    index_eligible: bool,
    benchmark_prices,
    desired: dict[str, float],
    held: dict[str, float],
    prices: dict[str, float],
    equity: float,
    regime_cap: float,
    event_cap: float,
    excluded_symbols: Iterable[str] = (),
) -> DailyDecision:
    """Return the DailyDecision for session `t` from the supplied composition.

    `desired` is the caller's stable unscaled stock composition - refreshed only
    on the caller's scheduled rebalance, never recomputed here - so a risk-only
    cut or a missing score on an ordinary day cannot lose the names to re-enter.
    """
    benchmarks = validate_benchmarks(panel, benchmark_prices)
    _check_spy_context(panel, benchmarks, t)
    if policy not in allocation.POLICIES:
        raise ValueError(f"policy must be one of {allocation.POLICIES}")
    blocked: list[str] = []
    for symbol, qty in held.items():
        if qty > 0 and not _price_ok(prices.get(symbol)):
            blocked.append(f"held valuation unavailable for {symbol}")
    if blocked:
        return DailyDecision(
            policy=policy,
            index_eligible=index_eligible,
            as_of=str(panel.dates[t]),
            decision=None,
            blocked=tuple(blocked),
            reason="blocked: a held position cannot be valued; sizing deferred",
        )
    held_weights = {
        symbol: float(qty) * float(prices[symbol]) / equity
        for symbol, qty in held.items()
        if qty > 0 and equity > 0
    }
    tickers, matrix = _decision_inputs(panel, benchmarks)
    decision = allocation.decide(
        panel.dates,
        matrix,
        tickers,
        t,
        desired=desired,
        # Explicit exits must not be resurrected by the retain-held fallback.
        held=exclude_names(held_weights, excluded_symbols),
        regime_cap=regime_cap,
        event_cap=event_cap,
        policy=policy,
        index_eligible=index_eligible,
    )
    return DailyDecision(
        policy=policy,
        index_eligible=index_eligible,
        as_of=str(panel.dates[t]),
        decision=decision,
        blocked=(),
        reason=decision.reasons[0]
        if decision.reasons
        else "no risk reduction required",
    )


# A held quantity that is not a finite nonnegative number is a caller error,
# not a row to drop from the ledger silently - the positive filter used
# downstream would let +inf through and hide a NaN or a negative.
def _validate_held(held: dict[str, float]) -> None:
    """Raise ValueError if any held quantity is nonfinite or negative."""
    for symbol, qty in held.items():
        value = float(qty)
        if not math.isfinite(value) or value < 0:
            raise ValueError(
                "Held quantity for "
                f"{symbol} must be finite and nonnegative, got {qty!r}"
            )


# A desired weight that is not a finite nonnegative number is a caller error,
# never an order to size: a NaN weight would otherwise slip past the `<= 0`
# filter and become a NaN-quantity buy that poisons the whole cash projection,
# and an inf weight would silently collapse the buy basket it sits in.
def _validate_desired(desired: dict[str, float]) -> None:
    """Raise ValueError if any desired weight is nonfinite or negative."""
    for symbol, weight in desired.items():
        value = float(weight)
        if not math.isfinite(value) or value < 0:
            raise ValueError(
                "Desired weight for "
                f"{symbol} must be finite and nonnegative, got {weight!r}"
            )


# Whether the decision is a genuine risk cut: a constraint binds *and* the
# exposure actually held exceeds the decision's total equity ceiling by more
# than the minimum trade. A binding constraint's name alone is not a cut - the
# volatility budget binds every day it scales the composition, including the
# days the book already sits at the scaled level and only drifts - and a
# ceiling the holdings are already under reduces nothing. Whole-share rounding
# leaves the book within fractions of a share of its ceiling, so an excess
# smaller than the minimum trade is rounding and drift, never a cut.
def is_risk_cut(decision, held, priced, equity, min_trade) -> bool:
    """Return True when `decision` cuts the held exposure below its ceiling."""
    binding = decision.binding
    if not binding or binding == allocation.BINDING_NONE:
        return False
    held_exposure = (
        sum(qty * priced[s] for s, qty in held.items() if s in priced) / equity
    )
    ceiling = sum(w for w in decision.desired_weights.values() if w > 0.0)
    return held_exposure - ceiling > min_trade


# Classify each name's share gap into sells and buys, noting the legs a
# min-trade threshold suppresses. The threshold is the same on both sides:
# a sell below it would leave the book under target and turning over for
# nothing, exactly as a buy below it would. Two sells always go whatever their
# size - a full exit (the name's target is zero) and a genuine risk cut (the
# decision reduced the held exposure below its ceiling) - because either is
# something the decision requires, not a drift the threshold exists to ignore.
def _plan_side_orders(
    held, want, priced, equity, min_trade, missing, risk_cut: bool
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return (sells, buys) from the gap between held and wanted shares."""
    sells: list[tuple[str, float]] = []
    buys: list[tuple[str, float]] = []
    for symbol in sorted(set(held) | set(want)):
        price = priced.get(symbol)
        if price is None:
            continue
        delta = want.get(symbol, 0.0) - held.get(symbol, 0.0)
        if abs(delta) < 1e-9:
            continue
        if delta < 0:
            qty = min(-delta, held.get(symbol, 0.0))
            exit_all = want.get(symbol, 0.0) <= 1e-9
            if not (exit_all or risk_cut) and qty * price < min_trade * equity:
                missing.append(f"{symbol}: sell below min trade")
                continue
            sells.append((symbol, qty))
        else:
            if delta * price < min_trade * equity:
                missing.append(f"{symbol}: buy below min trade")
                continue
            buys.append((symbol, delta))
    return sells, buys


# The continuous share target of every priced name the decision wants. A
# prebuilt decision may carry SPY from an index-eligible composition, but
# execution still respects the current index eligibility: it is a ceiling on
# SPY, never a mandate to exit, so an existing SPY holding is preserved up to
# the requested quantity and only an increase is blocked.
def _wanted_shares(
    decision, held, priced, equity, missing, index_eligible: bool
) -> dict[str, float]:
    """Return {symbol: continuous shares wanted} for the decision's names."""
    want: dict[str, float] = {}
    for symbol, weight in decision.desired_weights.items():
        if weight <= 0.0:
            continue
        price = priced.get(symbol)
        if price is None:
            missing.append(f"{symbol}: no decision price")
            continue
        wanted = weight * equity / price
        if symbol == allocation.SPY and not index_eligible:
            # Eligibility blocks only the increase: an existing holding is
            # preserved up to the requested quantity (a partial cut or a full
            # exit still happens), and a desired buy that would exceed the
            # holding is suppressed rather than honored or liquidated.
            held_qty = held.get(symbol, 0.0)
            if wanted > held_qty:
                missing.append(
                    f"{symbol}: buy suppressed, index not eligible at execution"
                )
            wanted = min(wanted, held_qty)
        want[symbol] = wanted
    return want


# The continuous buy and sell quantities toward the wanted shares, buys scaled
# to the cash actually on hand after fees.
def _continuous_orders(
    decision,
    want,
    held,
    priced,
    equity,
    cash,
    cost,
    min_trade,
    missing,
    risk_cut: bool,
) -> list[planner.Order]:
    """Return the shared continuous orders for one decision day."""
    sells, buys = _plan_side_orders(
        held, want, priced, equity, min_trade, missing, risk_cut
    )
    buy_notional = sum(qty * priced[symbol] for symbol, qty in buys)
    spend = buy_notional * (1.0 + cost)
    scale = min(1.0, max(0.0, cash) / spend) if spend > 0 else 0.0
    orders: list[planner.Order] = []
    for symbol, qty in sells:
        orders.append(
            planner.Order(
                symbol,
                "sell",
                qty,
                priced[symbol],
                _sell_reason(decision, symbol, want, risk_cut),
            )
        )
    for symbol, qty in buys:
        scaled = qty * scale
        if scaled <= 1e-9:
            continue
        orders.append(
            planner.Order(
                symbol,
                "buy",
                scaled,
                priced[symbol],
                "funded allocation toward target",
            )
        )
    return orders


# The plain-language reason a name is being sold, which is also the label
# execution reads: only a sell that genuinely reduces the held exposure below
# the decision's ceiling is a "risk reduction" - the paper path turns that
# label into `priority`, which exempts the order from the green-open skip and
# the closing-auction policy. A name the composition no longer wants at all
# is a rotation out of it, and a sell toward a positive target on a day with
# no genuine cut is a rebalance of drift; neither is a risk cut, whatever
# constraint the decision happens to name that day.
def _sell_reason(decision, symbol: str, want, risk_cut: bool) -> str:
    """Return the reason a sell of `symbol` was planned this day."""
    if want.get(symbol, 0.0) <= 1e-9:
        return "rotation out of the composition"
    if risk_cut:
        return f"risk reduction ({decision.binding})"
    return "rebalance toward desired weight"


# The no-trade band around a whole-share target: a gap of half a share or
# less rounds to nothing, so a whole-share book sits within one rounding of
# its fractional target and is never pushed through it. The hundredth of a
# share of hysteresis absorbs what one fill's own fee drags the target by, so
# a name that has just been rounded onto the band's edge is not rounded back
# across it the next session by the fee alone.
SHARE_BAND = 0.5
_BAND_TOL = 1e-2


# The whole shares a continuous gap of `gap` shares trades: nothing inside the
# half-share band, otherwise the nearest whole share. Rounding to nearest on
# both sides is what stops the ping-pong a rounded-up sell produced: it left
# the name under target by more than the rounding, so the next session bought
# the share back, and the one after sold it again.
def whole_share_gap(gap: float) -> int:
    """Return the nearest whole-share quantity for `gap`, zero inside the band."""
    gap = abs(float(gap))
    if gap <= SHARE_BAND + _BAND_TOL:
        return 0
    return int(math.floor(gap + 0.5))


# The whole shares one sell order submits. Rounding a sell past the whole
# shares actually held would create a short, so the rounded sell is capped at
# the whole shares held. A full exit sells every whole share and reports the
# fractional remainder whole shares cannot sell as blocked, never silently
# left behind. A partial sell rounds to the nearest whole share and is no
# trade inside the band: the position then sits within one rounding of its
# target, which is where a whole-share book belongs, and is not a blocked leg.
def _whole_share_sell(order, held_qty: float, exit_all: bool, blocked, missing) -> int:
    """Return the whole shares to sell for `order`, zero when nothing can go."""
    max_sell = int(math.floor(held_qty + 1e-10))
    rounded = whole_share_gap(order.qty)
    qty = min(rounded, max_sell)
    if qty <= 0:
        if rounded > 0 or exit_all:
            blocked.append(
                f"whole-share rounding leaves no sellable quantity for {order.symbol}"
            )
        else:
            missing.append(f"{order.symbol}: sell inside the whole-share band")
        return 0
    unexecutable = order.qty - qty
    if (exit_all and unexecutable > 1e-9) or unexecutable > SHARE_BAND + _BAND_TOL:
        blocked.append(
            f"whole-share eligibility leaves an unexecutable "
            f"fractional residual in {order.symbol}"
        )
    return qty


# Round a continuous basket to whole shares and re-check the bounds a broker
# actually faces: the cash after fees and the name cap for stocks. `want` is
# the continuous share target each order moved toward, so a full exit (target
# zero) can be told from a gap that merely sits inside the band.
def _whole_share_bound(
    orders,
    held,
    priced,
    equity,
    cash,
    cost,
    index_eligible,
    entry_cap,
    blocked,
    missing,
    want,
) -> list[planner.Order]:
    """Return `orders` rounded to whole shares, bounds re-checked after."""
    buys: list[tuple[planner.Order, int]] = []
    sells: list[tuple[planner.Order, int]] = []
    for o in orders:
        if o.side == "sell":
            qty = _whole_share_sell(
                o,
                held.get(o.symbol, 0.0),
                want.get(o.symbol, 0.0) <= 1e-9,
                blocked,
                missing,
            )
            if qty > 0:
                sells.append((o, qty))
        else:
            qty = whole_share_gap(o.qty)
            if qty <= 0:
                missing.append(f"{o.symbol}: buy rounds to zero shares")
                continue
            buys.append((o, qty))
    buy_spend = sum(qty * priced[o.symbol] for o, qty in buys)
    scale = (
        min(1.0, max(0.0, cash) / (buy_spend * (1.0 + cost))) if buy_spend > 0 else 0.0
    )
    result = dict(held)
    out: list[planner.Order] = []
    for o, qty in sells:
        result[o.symbol] = result.get(o.symbol, 0.0) - qty
        out.append(replace(o, qty=qty))
    for o, qty in buys:
        q = qty
        if o.symbol != allocation.SPY or not index_eligible:
            cap_shares = entry_cap * equity / priced[o.symbol]
            room = cap_shares - result.get(o.symbol, 0.0)
            q = min(q, max(0, int(math.floor(room + 1e-10))))
        q = max(0, int(q * scale + 1e-10))
        if q <= 0:
            missing.append(f"{o.symbol}: buy rounds to zero shares under bounds")
            continue
        result[o.symbol] = result.get(o.symbol, 0.0) + q
        out.append(replace(o, qty=q))
    return out


# The shared order plan both the paper account and the simulator use.
def plan_funded(
    decision: AllocationDecision,
    held: dict[str, float],
    prices: dict[str, float],
    equity: float,
    cash: float,
    *,
    cost_bps: float = 10.0,
    whole_shares: bool = False,
    index_eligible: bool = False,
    entry_cap: float = ENTRY_NAME_CAP,
    min_trade: float = planner.MIN_TRADE,
) -> FundedPlan:
    """Return the FundedPlan that moves `held` toward `decision` within cash.

    Buys are sized from `cash` actually on hand after fees, never from the
    proceeds of the same day's sells; sells never exceed what is held; and the
    one `min_trade` threshold applies to both sides but never suppresses a
    full exit or a genuine risk cut. `whole_shares` rounds for
    the paper account and re-checks the fee, cash and name-cap bounds after
    rounding. The returned `executable` weights and `cash` fraction are
    projected against the post-fee NAV of the order basket at the reference
    prices, and `projected_cash_amount`/`projected_equity` carry the dollar
    balances behind them. A held name with no usable price blocks sizing
    explicitly (both projections are `None`), and `index_eligible` is
    respected at execution too: a prebuilt decision may carry SPY, but
    eligibility is a ceiling on SPY, not a mandate to exit - an existing
    holding is preserved up to the requested quantity (a partial cut or a
    full exit still happens) and only an increase is blocked.
    """
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError("A finite positive account equity is required")
    if not math.isfinite(cash) or cash < 0:
        raise ValueError("A finite nonnegative cash balance is required")
    if not math.isfinite(cost_bps) or cost_bps < 0:
        raise ValueError("A finite nonnegative cost is required")
    cost = cost_bps / 1e4
    _validate_held(held)
    _validate_desired(decision.desired_weights)
    held = {s: float(q) for s, q in held.items() if q > 0}
    priced = {s: float(p) for s, p in prices.items() if _price_ok(p)}
    blocked: list[str] = []
    missing: list[str] = []
    for symbol in sorted(held):
        if symbol not in priced:
            blocked.append(f"held valuation unavailable for {symbol}")
    if blocked:
        return FundedPlan(
            policy=_policy_of(decision),
            index_eligible=index_eligible,
            version=decision.version,
            as_of=decision.as_of,
            available=decision.available,
            desired=dict(decision.desired_weights),
            executable={},
            cash=None,
            orders=(),
            reason="blocked: a held position cannot be valued; sizing deferred",
            missing=tuple(sorted(set(decision.missing) | set(missing))),
            blocked=tuple(blocked),
            binding=decision.binding,
        )
    want = _wanted_shares(decision, held, priced, equity, missing, index_eligible)
    risk_cut = is_risk_cut(decision, held, priced, equity, min_trade)
    orders = _continuous_orders(
        decision,
        want,
        held,
        priced,
        equity,
        cash,
        cost,
        min_trade,
        missing,
        risk_cut,
    )
    if whole_shares:
        orders = _whole_share_bound(
            orders,
            held,
            priced,
            equity,
            cash,
            cost,
            index_eligible,
            entry_cap,
            blocked,
            missing,
            want,
        )
    result = dict(held)
    for o in orders:
        result[o.symbol] = result.get(o.symbol, 0.0) + (
            o.qty if o.side == "buy" else -o.qty
        )
    # The actual projected balances of the returned order basket at the
    # reference prices: cash is the pre-trade cash moved by the net sale
    # proceeds and the gross buy spend including fees, and the post-fee NAV is
    # that cash plus the final holdings at the same prices. Both fractions -
    # executable and cash - use this NAV as their denominator, so the fee-free
    # complement of the executable weights is never presented as the projected
    # cash.
    buy_notional = sum(o.qty * priced[o.symbol] for o in orders if o.side == "buy")
    sell_notional = sum(o.qty * priced[o.symbol] for o in orders if o.side == "sell")
    # Buys are scaled to the cash on hand, so the projected cash can only land
    # below zero through float rounding of that scale; report the nonnegative
    # balance the basket actually leaves, the same guard the paper path's own
    # projection applies, so the reported cash is never a negative number.
    projected_cash = max(
        0.0, cash + sell_notional * (1.0 - cost) - buy_notional * (1.0 + cost)
    )
    final_value = sum(
        result[s] * priced[s] for s in result if s in priced and result[s] > 1e-9
    )
    projected_equity = projected_cash + final_value
    executable = (
        {
            s: result[s] * priced[s] / projected_equity
            for s in sorted(result)
            if result[s] > 1e-9 and s in priced
        }
        if projected_equity > 0
        else {}
    )
    reason = decision.reasons[0] if decision.reasons else "no risk reduction required"
    return FundedPlan(
        policy=_policy_of(decision),
        index_eligible=index_eligible,
        version=decision.version,
        as_of=decision.as_of,
        available=decision.available,
        desired=dict(decision.desired_weights),
        executable=executable,
        cash=projected_cash / projected_equity if projected_equity > 0 else 0.0,
        orders=tuple(orders),
        reason=reason,
        missing=tuple(sorted(set(decision.missing) | set(missing))),
        blocked=tuple(blocked),
        binding=decision.binding,
        projected_cash_amount=projected_cash,
        projected_equity=projected_equity,
        risk_cut=risk_cut,
    )
