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
) -> Book:
    dates = [str(d)[:10] for d in dates]
    tickers = list(tickers)
    T, N = adj_close.shape
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
            need = sum(q * prices[j] for j, q in want.items()) * (1 + cost)
            scale = min(1.0, max(0.0, budget) / need) if need > 0 else 0.0
            for j, q in sorted(want.items()):
                qty = math.floor(q * scale)
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
                planned = _ordinary(
                    rule, mask[t], g, below, shares, band[t], adj_close, t, held,
                    None if tilt is None else tilt[t],
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
                    buys = {
                        j: base[j] - shares[j] for j in range(N) if base[j] > shares[j]
                    }
                    pending = (
                        dates[t],
                        {},
                        buys,
                        "fomc_restoration_decision_close",
                        ExecutionTiming.DECISION_CLOSE,
                    )
                    cycle["restored"] = True
                elif not cycle["cut"]:
                    sells = {
                        j: math.floor(base[j] * event_risk.REDUCED)
                        for j in range(N)
                        if base[j] > 0
                    }
                    pending = (dates[t], sells, {}, "fomc_reduction", None)
                    cycle["cut"] = True
                continue
            restored = cycle["restored"]
            cycle = None
            if not restored:
                buys = {j: base[j] - shares[j] for j in range(N) if base[j] > shares[j]}
                pending = (dates[t], {}, buys, "fomc_restoration", None)
                continue
        if t < window:
            continue
        # A held name the trailing window cannot price freezes the whole
        # decision, as the live sizing refuses to resize a book it cannot value.
        if ((shares > 0) & ~priceable[t] & (g >= 0)).any():
            continue
        target = _ordinary(
            rule, mask[t], g, below, shares, band[t], adj_close, t, held,
            None if tilt is None else tilt[t],
        )
        # A held name without a grade keeps its shares (a protected holding);
        # the rest of the book is sized on the remaining capital.
        protected = (shares > 0) & (g < 0)
        if protected.any():
            target = np.where(protected, held, target * (1.0 - held[protected].sum()))
        sells, buys = {}, {}
        for j in range(N):
            price = adj_close[t, j]
            if not (np.isfinite(price) and price > 0) or protected[j]:
                continue
            # The funded planner's arithmetic: the continuous share gap, tested
            # against the minimum trade (never an exit), rounded to the nearest
            # whole share with nothing inside half a share; a held name the
            # grade keeps never rounds to nothing.
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
        if sells or buys:
            pending = (dates[t], sells, buys, None, None)
    return Book(dates, tickers, equity, weights, trades, costs_paid, planned, cash_close, cash_open)


# The ordinary nightly plan at close t: the leader weights over the names the
# grades admit (or keep, while held at the hold grade), the band block on buys.
def _ordinary(rule, mask_t, g, below, shares, band_t, adj_close, t, held, tilt_t=None):
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
    return np.where(blocked, np.minimum(target, held), target)


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
