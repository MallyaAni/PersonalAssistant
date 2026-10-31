"""The installed policy run as the paper account runs it, session by session.

One simulator serves the backtest, the strategy charts and the live parity
check, so the three cannot disagree. Every night it reads only that close:
the desk's grades (the nightly's fundamentals mode), the band analyst's buy
block and the trailing closes. It plans what the nightly plans: the leader
sizing (`grade_led_leader_policy.leader_weights`) over the names graded B or
better with a full window, the band block on buys, and in the FOMC guidance
regime the event cycle in place of the ordinary plan (`event_execution`).
Orders fill as the account's do: market-on-open at the next session's open,
sells first, buys sized from the cash on hand before the day's sells (the
funded planner never spends same-day sale proceeds), whole shares, a cost on
every fill, and an FOMC restoration planned on the eve at the decision
session's close.

Variants of the rule are parameters (`Rule`), so a candidate is tested on
exactly the engine that would run it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from backend.agents.trading.desk import event_risk
from backend.market import grade_led_leader_policy as leader
from backend.market.calendar import fomc_decisions
from backend.market.labels import ExecutionTiming, TradeAction

INDICES = ("SPY", "QQQ")


@dataclass(frozen=True)
class Rule:
    """The policy's free choices; the defaults are the installed rule."""

    entry_grade: int = leader.ENTRY_GRADE
    # The least grade a held name keeps its place at (None: the entry grade).
    hold_grade: int | None = leader.HOLD_GRADE
    # Sessions a held name may stay below the hold grade before it is sold.
    exit_grace: int = 0
    # A resize smaller than this share of equity is not traded (never an exit).
    min_trade: float = leader.MIN_TRADE
    band_block: bool = True
    fomc: bool = True
    cost_bps: float = 10.0
    floor: float = leader.EXPOSURE_FLOOR
    target: float = leader.TARGET
    # Research only: defer an entry while the name's trailing 63-session
    # return exceeds this fraction. None is the installed rule.
    chase: float | None = None
    # Research placebo: defer the guard's count of entering names at random,
    # seeded. Requires `chase`.
    chase_random: int | None = None
    # Research only: cap the target weight in `sector_cap_sectors` at this
    # fraction of equity after protected holdings are kept. None is the
    # installed rule.
    sector_cap: float | None = None
    sector_cap_sectors: tuple[str, ...] = (
        "Information Technology",
        "Communication Services",
    )
    # Research placebo: remove the cap's weight from a random subset instead of
    # the sector group, seeded. Requires `sector_cap`.
    sector_random: int | None = None
    # Research only: trim a flagged held name's target to this fraction while
    # it is inside its predicted pre-release window. None is the installed rule.
    earnings_trim: float | None = None
    # Research only: block an entry into a flagged unheld name.
    earnings_blackout: bool = False
    # Research placebo: remove the overlay's weight from a random subset instead
    # of the flagged names, seeded. Requires the overlay.
    earnings_random: int | None = None


@dataclass
class Book:
    dates: list[str]
    tickers: list[str]
    equity: np.ndarray
    weights: np.ndarray  # (T, N) weight held at each close
    trades: list[dict] = field(default_factory=list)
    costs: float = 0.0
    # Tonight's plan after the last close: the weights the rule wants next.
    planned: np.ndarray | None = None
    # Cash at each close, and the cash on hand before each session's fills.
    cash: np.ndarray | None = None
    cash_before: np.ndarray | None = None


class _Shim:
    def __init__(self, dates, tickers, adj_close, benchmark):
        self.dates = np.asarray(dates, dtype="datetime64[D]")
        self.tickers = tuple(tickers)
        self.adj_close = adj_close
        self.benchmark = benchmark

    def index(self, ticker):
        return self.tickers.index(ticker)


# (T, N) True where the name can be sized at that close: on the desk, not an
# index or the benchmark, with WINDOW + 1 finite positive closes.
def sizable(
    adj_close: np.ndarray, tickers, benchmark, window: int = leader.WINDOW
) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        priced = (np.isfinite(adj_close) & (adj_close > 0)).astype(np.int64)
    run = np.cumsum(priced, axis=0)
    span = window + 1
    lagged = np.vstack(
        [np.zeros((span, adj_close.shape[1]), dtype=np.int64), run[:-span]]
    )
    mask = (run - lagged[: len(run)]) == span
    for j, ticker in enumerate(tickers):
        if ticker in (*INDICES, benchmark):
            mask[:, j] = False
    return mask


def simulate(
    dates,
    tickers,
    benchmark: str,
    open_: np.ndarray,
    close: np.ndarray,
    adj_close: np.ndarray,
    grades: np.ndarray,
    band: np.ndarray,
    rule: Rule = Rule(),
    capital: float = 100_000.0,
    start: int = 0,
    tilt: np.ndarray | None = None,
    eligible: np.ndarray | None = None,
    sector: np.ndarray | None = None,
    earnings: np.ndarray | None = None,
) -> Book:
    dates = [str(d)[:10] for d in dates]
    tickers = list(tickers)
    T, N = adj_close.shape
    if rule.sector_random is not None and rule.sector_cap is None:
        raise ValueError("sector_random requires sector_cap")
    if rule.sector_cap is not None:
        if not 0 <= rule.sector_cap <= 1:
            raise ValueError("sector_cap must be within unit capital")
        if sector is None:
            raise ValueError("sector_cap requires one sector label per ticker")
        sector = np.asarray(sector, dtype=str)
        if sector.shape != (N,):
            raise ValueError("One sector label per ticker required")
    overlay = rule.earnings_trim is not None or rule.earnings_blackout
    if rule.earnings_trim is not None and not 0 <= rule.earnings_trim <= 1:
        raise ValueError("earnings_trim must be within [0, 1]")
    if rule.earnings_random is not None and not overlay:
        raise ValueError("earnings_random requires the earnings overlay")
    if overlay and earnings is None:
        raise ValueError("the earnings overlay requires one flag per session and name")
    if earnings is not None:
        earnings = np.asarray(earnings, dtype=bool)
        if earnings.shape != (T, N):
            raise ValueError("One earnings flag per session and name required")
    with np.errstate(invalid="ignore", divide="ignore"):
        opens = open_ * adj_close / close
    mask = sizable(adj_close, tickers, benchmark)
    # The names the trailing window can price: a held name outside it
    # freezes the night, as live; a name merely outside a research
    # universe is sold, not frozen.
    priceable = mask.copy()
    if eligible is not None:
        # A research universe narrower than the desk (an index's dated
        # membership): a name outside it on a session is not sized there.
        mask &= np.asarray(eligible, dtype=bool)
    factor = (
        event_risk.live_path(_Shim(dates, tickers, adj_close, benchmark))
        if rule.fomc
        else np.ones(T)
    )
    meetings = fomc_decisions()
    days = [date.fromisoformat(d) for d in dates]
    cost = rule.cost_bps / 1e4
    if rule.chase_random is not None and rule.chase is None:
        raise ValueError("chase_random requires chase")
    rng = (
        np.random.default_rng(rule.chase_random)
        if rule.chase_random is not None
        else None
    )
    sector_rng = (
        np.random.default_rng(rule.sector_random)
        if rule.sector_random is not None
        else None
    )
    earnings_rng = (
        np.random.default_rng(rule.earnings_random)
        if rule.earnings_random is not None
        else None
    )
    window = leader.WINDOW
    shares = np.zeros(N)
    cash = capital
    below = np.zeros(N, dtype=int)
    equity = np.full(T, np.nan)
    weights = np.zeros((T, N))
    trades: list[dict] = []
    costs_paid = 0.0
    cycle = None
    pending = None  # last night's plan: (decided, sells, buys, reason, timing)
    planned = None
    cash_close = np.full(T, np.nan)
    cash_open = np.full(T, np.nan)

    def mark(t):
        px = np.where(np.isfinite(adj_close[t]), adj_close[t], 0.0)
        return float(cash + (shares * px).sum()), px

    def fill(t, j, qty, price, decided, reason, timing, before_w, value_equity):
        nonlocal cash, costs_paid
        notional = qty * price
        fee = abs(notional) * cost
        cash -= notional + fee
        costs_paid += fee
        shares[j] += qty
        trades.append(
            {
                "ticker": tickers[j],
                "decided": decided,
                "date": dates[t],
                "action": TradeAction.BUY if qty > 0 else TradeAction.SELL,
                "shares": int(abs(qty)),
                "price": float(price),
                "size": float(abs(notional) / value_equity),
                "before": float(before_w),
                "target": float(shares[j] * price / value_equity),
                **({"reason": reason} if reason else {}),
                **({"timing": timing} if timing else {}),
            }
        )

    for t in range(start, T):
        # 1. Fill last night's orders at this open (a decision-close restoration at this close).
        cash_open[t] = cash
        if pending is not None:
            decided, sells, buys, reason, timing = pending
            pending = None
            at_close = timing == ExecutionTiming.DECISION_CLOSE
            prices = adj_close[t] if at_close else opens[t]
            value, px = mark(t - 1)
            before = shares * px / value if value > 0 else np.zeros(N)
            budget = cash  # cash on hand before today's sells
            for j, qty in sells.items():
                if np.isfinite(prices[j]) and prices[j] > 0 and qty > 0:
                    fill(
                        t,
                        j,
                        -min(qty, shares[j]),
                        prices[j],
                        decided,
                        reason,
                        timing,
                        before[j],
                        value,
                    )
            want = {
                j: q
                for j, q in buys.items()
                if q > 0 and np.isfinite(prices[j]) and prices[j] > 0
            }
            if at_close:
                budget = cash  # the cut's proceeds have settled by the decision close
            for j, qty in funded(want, prices, budget, cost).items():
                if qty > 0:
                    fill(
                        t, j, qty, prices[j], decided, reason, timing, before[j], value
                    )
        value, px = mark(t)
        equity[t] = value
        cash_close[t] = cash
        weights[t] = shares * px / value if value > 0 else 0.0
        held = weights[t]
        g = grades[t]
        hold = rule.entry_grade if rule.hold_grade is None else rule.hold_grade
        below = np.where((shares > 0) & (g < hold), below + 1, 0)
        if t + 1 >= T:
            # Tonight's plan has no next session here to fill on: report the
            # weights it wants (a cycle in progress holds what it holds).
            planned = held.copy() if cycle is not None or t < window else None
            if planned is None:
                tilt_t = None if tilt is None else tilt[t]
                if rule.sector_cap is not None:
                    planned, _ = plan_target(
                        rule, mask[t], g, below, shares, band[t], adj_close, t,
                        held, tilt_t, rng, sector, sector_rng,
                        None if earnings is None else earnings[t], earnings_rng,
                    )
                else:
                    planned = _ordinary(
                        rule, mask[t], g, below, shares, band[t], adj_close, t,
                        held, tilt_t, rng,
                    )
                    if overlay:
                        planned = trim_earnings_target(
                            rule, planned, earnings[t], shares,
                            (shares > 0) & (g < 0), earnings_rng,
                        )
            break
        # 2. Tonight's plan, from this close only.
        day = days[t]
        eve = days[t + 1] == cycle["decision"] if cycle else False
        if cycle is None and factor[t] == event_risk.REDUCED and t > start:
            upcoming = next((m for m in meetings if m >= day), None)
            if upcoming is not None:
                cycle = {
                    "decision": upcoming,
                    "baseline": shares.copy(),
                    "cut": False,
                    "restored": False,
                }
                eve = days[t + 1] == upcoming
        if cycle is not None:
            base = cycle["baseline"]
            if day < cycle["decision"]:
                if eve and cycle["cut"]:
                    buys = cycle_restore(base, shares)
                    pending = (
                        dates[t],
                        {},
                        buys,
                        "fomc_restoration_decision_close",
                        ExecutionTiming.DECISION_CLOSE,
                    )
                    cycle["restored"] = True
                elif not cycle["cut"]:
                    sells = cycle_cut(base)
                    pending = (dates[t], sells, {}, "fomc_reduction", None)
                    cycle["cut"] = True
                continue
            restored = cycle["restored"]
            cycle = None
            if not restored:
                buys = cycle_restore(base, shares)
                pending = (dates[t], {}, buys, "fomc_restoration", None)
                continue
        if t < window:
            continue
        # A held name the trailing window cannot price freezes the whole
        # decision, as the live sizing refuses to resize a book it cannot value.
        if ((shares > 0) & ~priceable[t] & (g >= 0)).any():
            continue
        target, protected = plan_target(
            rule, mask[t], g, below, shares, band[t], adj_close, t, held,
            None if tilt is None else tilt[t], rng, sector, sector_rng,
            None if earnings is None else earnings[t], earnings_rng,
        )
        sells, buys = plan_orders(rule, target, shares, adj_close[t], value, protected)
        if sells or buys:
            pending = (dates[t], sells, buys, None, None)
    return Book(dates, tickers, equity, weights, trades, costs_paid, planned, cash_close, cash_open)


# True where an unheld name has already run more than `threshold` over the
# trailing `window` sessions. The caller intersects this with the names it is
# about to enter; a held name is never deferred.
def chase_defer(adj_close, shares, t, window=leader.WINDOW, threshold=0.25):
    """Return the (N,) mask of unheld names whose trailing return is hot."""
    defer = np.zeros(len(shares), dtype=bool)
    if threshold is None or t < window:
        return defer
    then = adj_close[t - window]
    now = adj_close[t]
    with np.errstate(invalid="ignore", divide="ignore"):
        hot = (
            np.isfinite(then)
            & np.isfinite(now)
            & (then > 0)
            & (now / then - 1.0 > threshold)
        )
    return hot & (shares == 0)


# The ordinary nightly plan at close t: the leader weights over the names the
# grades admit (or keep, while held at the hold grade), the band block on buys.
def _ordinary(
    rule, mask_t, g, below, shares, band_t, adj_close, t, held, tilt_t=None, rng=None
):
    window = leader.WINDOW
    keep = (shares > 0) & (below <= rule.exit_grace) & (g >= 0)
    sized = mask_t & ((g >= rule.entry_grade) | keep)
    blocked = band_t if rule.band_block else np.zeros(len(g), dtype=bool)
    sized &= ~blocked | (shares > 0)
    target, _ = leader.leader_weights(
        adj_close[t - window : t + 1],
        sized,
        floor=rule.floor,
        target=rule.target,
        extra=tilt_t,
    )
    target = np.where(blocked, np.minimum(target, held), target)
    if rule.chase is not None:
        entering = (shares == 0) & (target > 0)
        defer = chase_defer(adj_close, shares, t, threshold=rule.chase) & entering
        if rule.chase_random is not None and defer.any():
            count = int(defer.sum())
            candidates = np.flatnonzero(entering)
            pick = rng.choice(candidates, size=count, replace=False)
            defer = np.zeros(len(target), dtype=bool)
            defer[pick] = True
        target = np.where(defer, 0.0, target)
    return target


# Cap the unprotected target weight in the rule's sectors at `sector_cap` of
# equity, after protected holdings are kept at their weight. The freed weight
# stays cash. With `rng`, the placebo removes the same weight from a random
# subset of unprotected names instead of the sector group.
def cap_sector_target(rule, target, sector_t, protected, rng=None):
    """Return the target with its sector weight capped, or the placebo draw."""
    labels = np.asarray(sector_t)
    if labels.shape != target.shape:
        raise ValueError("One sector label per name required")
    group = np.array([label in rule.sector_cap_sectors for label in labels])
    unprotected = group & ~protected
    group_weight = float(target[unprotected].sum())
    removed = max(0.0, float(target[group].sum()) - rule.sector_cap)
    if removed <= 0:
        return target
    out = target.copy()
    if rng is None:
        if group_weight <= removed:
            out[unprotected] = 0.0
        else:
            out[unprotected] *= (group_weight - removed) / group_weight
        return out
    candidates = np.flatnonzero((out > 0) & ~protected)
    if len(candidates) == 0:
        return out
    picked = []
    picked_weight = 0.0
    for j in rng.permutation(candidates):
        picked.append(j)
        picked_weight += out[j]
        if picked_weight >= removed:
            break
    if picked_weight <= 0:
        return out
    if picked_weight <= removed:
        out[picked] = 0.0
    else:
        out[picked] *= (picked_weight - removed) / picked_weight
    return out


# Trim or block the names flagged inside their predicted pre-release window.
# A flagged unheld name is not entered (blackout); a flagged held name is
# scaled by the trim fraction; a protected holding is never touched. The freed
# weight stays cash. With `rng`, the placebo removes the overlay's total
# removed weight from a random subset of unprotected names instead.
def trim_earnings_target(rule, target, earnings_t, shares, protected, rng=None):
    """Return the target with flagged pre-release names trimmed or blocked."""
    flagged = np.asarray(earnings_t, dtype=bool)
    if flagged.shape != target.shape:
        raise ValueError("One earnings flag per name required")
    flagged = flagged & ~protected
    if not flagged.any():
        return target
    if rng is None:
        out = target.copy()
        if rule.earnings_blackout:
            out[flagged & (shares == 0)] = 0.0
        if rule.earnings_trim is not None:
            out[flagged & (shares > 0)] *= rule.earnings_trim
        return out
    removed = 0.0
    if rule.earnings_blackout:
        removed += float(target[flagged & (shares == 0)].sum())
    if rule.earnings_trim is not None:
        removed += float(target[flagged & (shares > 0)].sum()) * (
            1.0 - rule.earnings_trim
        )
    if removed <= 0:
        return target
    out = target.copy()
    candidates = np.flatnonzero((out > 0) & ~protected)
    if len(candidates) == 0:
        return out
    picked = []
    picked_weight = 0.0
    for j in rng.permutation(candidates):
        picked.append(j)
        picked_weight += out[j]
        if picked_weight >= removed:
            break
    if picked_weight <= 0:
        return out
    if picked_weight <= removed:
        out[picked] = 0.0
    else:
        out[picked] *= (picked_weight - removed) / picked_weight
    return out


# Tonight's ordinary target at close t on the book's own holdings: the leader
# plan, with a held name the grades cannot read (a protected holding) kept at
# its weight and the rest of the book sized on the remaining capital. Returns
# the (N,) target weights and the (N,) protected mask. The simulator and the
# nightly plan check (`plan_parity`) both plan through this.
def plan_target(
    rule,
    mask_t,
    g,
    below,
    shares,
    band_t,
    adj_close,
    t,
    held,
    tilt_t=None,
    rng=None,
    sector_t=None,
    sector_rng=None,
    earnings_t=None,
    earnings_rng=None,
):
    target = _ordinary(
        rule, mask_t, g, below, shares, band_t, adj_close, t, held, tilt_t, rng
    )
    protected = (shares > 0) & (g < 0)
    if protected.any():
        target = np.where(protected, held, target * (1.0 - held[protected].sum()))
    if rule.sector_cap is not None:
        target = cap_sector_target(rule, target, sector_t, protected, sector_rng)
    if rule.earnings_trim is not None or rule.earnings_blackout:
        target = trim_earnings_target(
            rule, target, earnings_t, shares, protected, earnings_rng
        )
    return target, protected


# Tonight's whole-share orders toward `target` at `prices`, on `value` of
# equity: the funded planner's arithmetic. The continuous share gap is tested
# against the minimum trade (never an exit) and rounded to the nearest whole
# share with nothing inside half a share; a held name the grade keeps never
# rounds to nothing; an exit sells every share. Returns ({j: shares to sell},
# {j: shares to buy}) before the cash limit (`funded`).
def plan_orders(rule, target, shares, prices, value, protected):
    sells, buys = {}, {}
    for j in range(len(target)):
        price = prices[j]
        if not (np.isfinite(price) and price > 0) or protected[j]:
            continue
        exit_all = target[j] <= 0
        gap = (target[j] * value / price if not exit_all else 0.0) - shares[j]
        if not exit_all and abs(gap) * price < rule.min_trade * value:
            continue
        qty = 0 if abs(gap) <= 0.5 + 1e-9 else int(math.floor(abs(gap) + 0.5))
        if exit_all:
            qty = int(shares[j])
        if gap < 0 and not exit_all:
            qty = min(qty, int(shares[j]) - 1) if shares[j] >= 1 else 0
        if qty <= 0:
            continue
        if gap < 0:
            sells[j] = qty
        else:
            buys[j] = qty
    return sells, buys


# The buys `want` ({j: shares}) funded from `budget` of cash at `prices`, a
# `cost` fraction charged on each: every buy scaled by one factor so the
# basket fits the cash, then rounded down to whole shares, in name order.
def funded(want, prices, budget, cost):
    need = sum(q * prices[j] for j, q in want.items()) * (1 + cost)
    scale = min(1.0, max(0.0, budget) / need) if need > 0 else 0.0
    return {j: math.floor(q * scale) for j, q in sorted(want.items())}


# The FOMC cycle's arithmetic on its snapshot of shares `base`: the cut sells
# the reduced share of every snapshot name, the restoration buys each name back
# up to its snapshot.
def cycle_cut(base):
    return {
        j: math.floor(base[j] * event_risk.REDUCED)
        for j in range(len(base))
        if base[j] > 0
    }


def cycle_restore(base, shares):
    return {j: base[j] - shares[j] for j in range(len(base)) if base[j] > shares[j]}


# Compounded results of a simulated book over [lo, hi).
def metrics(book: Book, lo: int = 0, hi: int | None = None) -> dict:
    e = book.equity[lo:hi]
    e = e[np.isfinite(e)]
    if len(e) < 2:
        return {}
    r = e[1:] / e[:-1] - 1
    years = len(r) / 252.0
    peak = np.maximum.accumulate(e)
    return {
        "cagr": float((e[-1] / e[0]) ** (1 / years) - 1),
        "max_drawdown": float((e / peak - 1).min()),
        "sharpe": float(r.mean() / r.std(ddof=1) * math.sqrt(252))
        if r.std() > 0
        else 0.0,
        "total": float(e[-1] / e[0] - 1),
    }
