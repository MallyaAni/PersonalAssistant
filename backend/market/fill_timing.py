"""Fill timing inside the session: the `/4` policy's orders, seven fill conventions.

The pre-registration is `docs/research/execution-timing-plan-2026-09-27.md`;
this module is that plan's engine and computes nothing the plan did not fix
in advance. The question is only *when within the next session* the orders
`graded-equal-weight/4` generates should fill, and whether a price condition
should gate them. Nothing here changes what is held or when it is decided.

What is priced
--------------
The orders are exactly the plain simulator's: `simulate.run(restricted,
since=..., allocator=policy_v4.allocator(mask), cost_bps=10, use_exits=False,
rebalance=paper.REBALANCE_EVERY)`. That run decides on session t's close
(the allocator's targets sized by `planner.plan` at the adjusted close, on
`_Book.plan`) and fills the whole order at t + 1's adjusted open; between
decisions nothing trades. `target_path` re-derives that schedule and those
targets from `policy_v4.allocator(mask)` rather than reading the journal
observer, because the plain arm has no between-decision trades (with
`use_exits=False` and no exit evidence `_Book.between` returns the held
weights, which `planner.plan` leaves alone) and no overlay; the re-derivation
is therefore exactly the observer's `desired_weights` on the decision
sessions and nothing on the others. `test_fill_timing.py` pins this by
asserting that `next_open` priced here reproduces the simulator's returns to
1e-10 on a synthetic report and store.

`price_book` then holds those share orders in the simulator's own ledger
(`simulate._Book`: the same cash budget, the same one-way cost on turnover,
the same "missing price keeps the holding") and fills every order at the
convention's price on the fill session. Fill prices come from the SIP
session cube (26 regular bars plus the closing auction, raw basis) and are
moved onto the panel's adjusted basis by the same factor `adjusted_open`
uses (`adj_close / close` on the fill session), so a split never sits
between a fill and a mark. Marks are the panel's adjusted daily close - the
official close, what the cube's `auction_open` holds where present - on the
fill session and on every session after it, for every convention alike.
A name with no complete cube session on its fill day fills at the panel's
adjusted open (the simulator's price) and is counted as a fallback.

The seven conventions (`CONVENTIONS`), each one registered trial:

  next_open        bar 0's open of the fill session - the control
  first_hour_vwap  volume-weighted mean of the bar closes over slots 0-3
  session_vwap     the same over all 26 slots
  next_close       the closing auction's print, else the last bar's close
  dip_or_close     a buy fills at the first bar close at or below
                   open * (1 - DIP), else at the official close; a sell at
                   the first bar close at or above open * (1 + DIP), else
                   the official close. "The close" is the same print
                   `next_close` fills at, so the dip is isolated from the
                   last quarter hour's noise.
  late_day         VWAP over LATE_SLOTS (15:00-15:45)
  breakout_gate    the executor's band gate, isolated: a buy fills at the
                   next open when the name's daily is not rejecting its
                   upper band on the decision date (`exit.evidence(panel)
                   .signalled()`, the very function `market_daily._band_blocked`
                   and `simulate.run(block_overbought=True)` read); a
                   rejecting name is deferred one session and re-tested, up
                   to MAX_DEFERRALS times, after which it fills at the open
                   regardless. Sells never wait. Deferrals are counted.

The VWAPs are a proxy from bar closes weighted by bar volume (the store has
no per-bar VWAP), as the plan states.

Statistics (`study`)
--------------------
Per convention and per start offset (the first `offsets` sessions, the
scorecard's phases of the 20-session clock), a daily return series aligned
to the panel. Per window (`market_pit_scorecard.WINDOWS`): the median CAGR
across offsets, the count of offsets whose CAGR beats `next_open`, and at
the median offset the paired daily difference against `next_open` in basis
points with a Newey-West t at lag HAC_LAG, plus the deferral and fallback
counts. The best convention's excess is deflated against TRIALS = 7 trials
(`candidate_stats.deflated_sharpe`). `verdict` applies the plan's kill
criteria unchanged: ADOPTED only when a convention beats `next_open` by at
least ADOPT_BP a session with t >= ADOPT_T on the choosing window and is not
worse on the reported window; anything else is RECORDED, NOT ACTED ON. The
`breakout_gate` line against `next_open` is stated separately because the
plan already names what follows from it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from backend.agents.trading.desk import exit as exit_analyst
from backend.agents.trading.desk import paper, policy_v4, simulate
from backend.market import candidate_stats, session_anatomy
from backend.market.sip_cube import FULL_SESSION_SLOTS, SessionCube

CONVENTIONS = (
    "next_open",
    "first_hour_vwap",
    "session_vwap",
    "next_close",
    "dip_or_close",
    "late_day",
    "breakout_gate",
)
CONTROL = "next_open"
# The dip a `dip_or_close` order waits for, as a fraction of the open.
DIP = 0.01
# 15:00-15:45: the four bars where the index-level intraday momentum lives.
LATE_SLOTS = (22, 23, 24, 25)
# The first hour: slots 0-3, the anatomy study's definition.
FIRST_HOUR_SLOTS = session_anatomy.FIRST_HOUR_SLOTS
# The one cost the trial is scored at, one way on every fill.
COST_BPS = (10.0,)
# The plan's kill floors: bp a session over the control and its HAC t.
ADOPT_BP = 5.0
ADOPT_T = 2.5
# A gated buy waits at most this many sessions, then fills at the open.
MAX_DEFERRALS = 5
# Newey-West lag on the paired daily differences, the scorecard's.
HAC_LAG = 20
# Seven conventions were scored, so the best is deflated against seven.
TRIALS = len(CONVENTIONS)
WINDOWS: dict[str, tuple[date | None, date | None]] = {
    "2016-2023": (date(2016, 1, 1), date(2024, 1, 1)),
    "2024-2026": (date(2024, 1, 1), None),
    "all": (None, None),
}
CHOOSING = "2016-2023"
REPORTED = "2024-2026"
ADOPTED = "ADOPTED"
RECORDED = "RECORDED, NOT ACTED ON"
BP = 1e4

assert FIRST_HOUR_SLOTS == 4
assert all(0 <= s < FULL_SESSION_SLOTS for s in LATE_SLOTS)


@dataclass(frozen=True)
class TargetPath:
    """The policy's desired weights on the simulator's decision sessions."""

    start: int  # the first session of the run (the `since` row)
    decisions: tuple[int, ...]  # sessions the policy decides on
    weights: np.ndarray  # (T, N): the targets on decision rows, NaN elsewhere


@dataclass(frozen=True)
class FillPrices:
    """One convention's raw-basis fill prices aligned to the panel, per side."""

    convention: str
    buy: np.ndarray  # (T, N) raw price, NaN where the cube has no session
    sell: np.ndarray  # (T, N)
    available: np.ndarray  # (T, N) True where the cube has the session


@dataclass(frozen=True)
class Priced:
    """One convention's daily returns from one start offset."""

    convention: str
    start: int
    returns: np.ndarray  # (T,) aligned to the panel; NaN before start + 1
    fills: int  # orders filled
    deferrals: int  # sessions gated buys waited, summed over orders
    fallbacks: int  # fills priced at the panel's open for want of a cube session


# The simulator's decision schedule on the plain arm and the policy's
# targets on it: `start` is the `since` row, decisions come every
# `rebalance` sessions from it while a next session exists, exactly as
# `simulate.run`'s `next_rebalance` clock walks. Between decisions the plain
# arm trades nothing, so the observer's desired weights on the other
# sessions are the held weights and are left NaN here.
def target_path(
    report, mask: np.ndarray, since: date | None, rebalance: int = paper.REBALANCE_EVERY
) -> TargetPath:
    """Return the (T, N) target weights on the decision sessions from `since`."""
    panel = report.panel
    rows, names = panel.adj_close.shape
    start = int(np.searchsorted(panel.dates, np.datetime64(since))) if since else 0
    allocate = policy_v4.allocator(mask)
    weights = np.full((rows, names), np.nan)
    decisions: list[int] = []
    next_rebalance = start
    for t in range(start, rows - 1):
        if t >= next_rebalance:
            next_rebalance = t + rebalance
            weights[t] = allocate(report, panel, None, t)
            decisions.append(t)
    return TargetPath(start, tuple(decisions), weights)


# Whether each name is rejecting its upper band on each session: the exit
# analyst's signal, the one function the live executor (`market_daily.
# _band_blocked`) and the simulator's `block_overbought` gate both read.
def band_rejecting(panel) -> np.ndarray:
    """Return the (T, N) band-rejection flags the executor's gate reads."""
    return exit_analyst.evidence(panel).signalled()


# The official close of every cube session: the closing auction's first
# print where the partition has one, else the last regular bar's close.
def _official_close(cube: SessionCube) -> np.ndarray:
    """Return (N,) the auction print with the last bar's close as fallback."""
    last = cube.close[:, FULL_SESSION_SLOTS - 1]
    auction = np.asarray(cube.auction_open, dtype=float)
    return np.where(np.isfinite(auction), auction, last)


# The first bar close at or past the dip threshold per session, else the
# official close. Buys wait for a fall below open * (1 - DIP); sells for a
# rise above open * (1 + DIP). Every order fills.
def _dip_or_close(cube: SessionCube, side: str) -> np.ndarray:
    """Return (N,) the dip-or-close fill price for `side`."""
    open0 = cube.open[:, 0][:, None]
    if side == "buy":
        hit = cube.close <= open0 * (1.0 - DIP)
    else:
        hit = cube.close >= open0 * (1.0 + DIP)
    any_hit = hit.any(axis=1)
    first = np.argmax(hit, axis=1)
    picked = cube.close[np.arange(len(cube)), first]
    return np.where(any_hit, picked, _official_close(cube))


# One convention's fill price for every session of a cube, on the raw
# basis, for one side. The single place each convention's arithmetic lives.
def session_prices(cube: SessionCube, convention: str, side: str) -> np.ndarray:
    """Return (N,) raw-basis fill prices for `convention` and `side`."""
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be buy or sell, not {side!r}")
    if len(cube) == 0:
        return np.zeros(0)
    if convention in ("next_open", "breakout_gate"):
        return np.asarray(cube.open[:, 0], dtype=float)
    if convention == "first_hour_vwap":
        return session_anatomy._vwap(
            cube.close[:, :FIRST_HOUR_SLOTS], cube.volume[:, :FIRST_HOUR_SLOTS]
        )
    if convention == "session_vwap":
        return session_anatomy._vwap(cube.close, cube.volume)
    if convention == "next_close":
        return _official_close(cube)
    if convention == "dip_or_close":
        return _dip_or_close(cube, side)
    if convention == "late_day":
        slots = list(LATE_SLOTS)
        return session_anatomy._vwap(cube.close[:, slots], cube.volume[:, slots])
    raise ValueError(f"unknown convention {convention!r}")


# The price one order fills at on one session, from that session's bars:
# `row` holds the session's `open`, `high`, `low`, `close`, `volume` (26,)
# and `auction_open` (a float, NaN when absent). For `breakout_gate`,
# `blocked` says whether the daily was rejecting its band on the decision
# date: a blocked buy is deferred and the price is NaN.
def fill_price(
    row: dict[str, Any], convention: str, side: str, blocked: bool = False
) -> float:
    """Return the fill price for one session, NaN when the order is deferred."""
    if convention == "breakout_gate" and side == "buy" and blocked:
        return math.nan
    cube = SessionCube(
        ticker="row",
        dates=np.array(["2000-01-03"], dtype="datetime64[D]"),
        open=np.asarray(row["open"], dtype=float)[None, :],
        high=np.asarray(row["high"], dtype=float)[None, :],
        low=np.asarray(row["low"], dtype=float)[None, :],
        close=np.asarray(row["close"], dtype=float)[None, :],
        volume=np.asarray(row["volume"], dtype=float)[None, :],
        prior_close=np.array([math.nan]),
        excluded={},
        auction_open=np.array([float(row.get("auction_open", math.nan))]),
        auction_volume=np.array([math.nan]),
    )
    return float(session_prices(cube, convention, side)[0])


# Every name's fill prices for one convention on the panel's calendar, raw
# basis, NaN where the name has no complete cube session that day.
def cube_prices(cubes: dict[str, SessionCube], panel, convention: str) -> FillPrices:
    """Return the FillPrices of `convention` aligned to `panel.dates`."""
    dates = np.asarray(panel.dates, dtype="datetime64[D]")
    rows, names = panel.adj_close.shape
    buy = np.full((rows, names), np.nan)
    sell = np.full((rows, names), np.nan)
    available = np.zeros((rows, names), dtype=bool)
    for j, ticker in enumerate(panel.tickers):
        cube = cubes.get(ticker)
        if cube is None or len(cube) == 0:
            continue
        pos = np.searchsorted(dates, cube.dates)
        ok = (pos < rows) & (dates[np.minimum(pos, rows - 1)] == cube.dates)
        buy[pos[ok], j] = session_prices(cube, convention, "buy")[ok]
        sell[pos[ok], j] = session_prices(cube, convention, "sell")[ok]
        available[pos[ok], j] = True
    return FillPrices(convention, buy, sell, available)


# The session a gated buy decided on `t` fills on: the first session after
# `t` whose previous close was not rejecting the band, at most
# MAX_DEFERRALS sessions late. Returns (fill session, deferrals).
def _gated_fill_session(blocked: np.ndarray, t: int, j: int) -> tuple[int, int]:
    """Return (session, deferrals) for a band-gated buy decided on `t`."""
    deferrals = 0
    rows = blocked.shape[0]
    while (
        deferrals < MAX_DEFERRALS
        and t + deferrals < rows
        and bool(blocked[t + deferrals, j])
    ):
        deferrals += 1
    return t + 1 + deferrals, deferrals


# Hold the policy's targets in the simulator's ledger, filling every share
# order at the convention's price on its fill session and marking at the
# panel's adjusted close. Returns daily returns aligned to the panel.
def price_book(  # noqa: C901 - one ledger walk: queue, fill, mark, decide
    targets: TargetPath,
    report,
    prices: FillPrices,
    convention: str,
    cost_bps: float,
    blocked: np.ndarray | None = None,
) -> Priced:
    """Return the Priced series of `convention` for the targets."""
    if convention not in CONVENTIONS:
        raise ValueError(f"unknown convention {convention!r}")
    if convention == "breakout_gate" and blocked is None:
        raise ValueError("breakout_gate needs the band-rejection flags")
    panel = report.panel
    rows, names = panel.adj_close.shape
    closes = panel.adj_close
    opens = simulate.adjusted_open(panel)
    with np.errstate(all="ignore"):
        factor = np.where(panel.close > 0, panel.adj_close / panel.close, np.nan)
    stamps = [str(d) for d in panel.dates]
    book = simulate._Book(names, simulate.START_EQUITY, cost_bps, panel, report, stamps)
    returns = np.full(rows, np.nan)
    equity = np.full(rows, np.nan)
    start = targets.start
    decisions = set(targets.decisions)
    # Orders waiting to fill: session -> list of (column, share delta).
    pending: dict[int, list[tuple[int, float]]] = {}
    fills = deferrals = fallbacks = 0
    equity[start] = book.equity(closes[start])

    # Queue the share moves a decision on `t` asks for, each on its fill session.
    def decide(t: int) -> None:
        nonlocal deferrals
        order = book.plan(targets.weights[t], closes[t])
        delta = order - book.shares
        # A new decision supersedes anything still waiting, as a rebalance
        # supersedes the simulator's deferred leg.
        pending.clear()
        for j in np.flatnonzero(np.abs(delta) > 1e-12):
            session = t + 1
            if convention == "breakout_gate" and delta[j] > 0:
                session, late = _gated_fill_session(blocked, t, j)
                deferrals += late
            if session < rows:
                pending.setdefault(session, []).append((int(j), float(delta[j])))

    # Fill what is due on `s` at the convention's adjusted price, one ledger call.
    def fill(s: int) -> None:
        nonlocal fills, fallbacks
        due = pending.pop(s, None)
        if not due:
            return
        order = np.array(book.shares, dtype=float)
        price = np.full(names, np.nan)
        for j, delta in due:
            order[j] = max(book.shares[j] + delta, 0.0)
            raw = prices.buy[s, j] if delta > 0 else prices.sell[s, j]
            if prices.available[s, j] and np.isfinite(raw) and raw > 0:
                price[j] = raw * factor[s, j]
            else:
                price[j] = opens[s, j]
                fallbacks += 1
            fills += 1
        book.settle(order, price, s, convention)

    if start in decisions:
        decide(start)
    for s in range(start + 1, rows):
        fill(s)
        equity[s] = book.equity(closes[s])
        returns[s] = equity[s] / equity[s - 1] - 1.0 if equity[s - 1] > 0 else np.nan
        if s in decisions:
            decide(s)
    return Priced(convention, start, returns, fills, deferrals, fallbacks)


# The k-th panel session as a date, the scorecard's `_since`.
def since_offset(panel, k: int) -> date:
    """Return panel session `k` as a date."""
    return panel.dates[k].astype("datetime64[D]").astype(object)


# Sessions inside [start, end) as a mask over the panel's dates.
def _window(dates: np.ndarray, start: date | None, end: date | None) -> np.ndarray:
    days = np.asarray(dates, dtype="datetime64[D]")
    keep = np.ones(len(days), dtype=bool)
    if start is not None:
        keep &= days >= np.datetime64(start, "D")
    if end is not None:
        keep &= days < np.datetime64(end, "D")
    return keep


# Annualised return of the finite entries of a daily series, NaN under two.
def _cagr(daily: np.ndarray) -> float:
    r = daily[np.isfinite(daily)]
    if len(r) < 2:
        return math.nan
    return float(np.prod(1.0 + r) ** (252.0 / len(r)) - 1.0)


# Median over finite entries, NaN when there are none.
def _nanmedian(x: np.ndarray) -> float:
    return float(np.nanmedian(x)) if np.isfinite(x).any() else math.nan


# The paired daily difference of two aligned series over a window.
def _excess(a: np.ndarray, b: np.ndarray, keep: np.ndarray) -> np.ndarray:
    diff = (a - b)[keep]
    return diff[np.isfinite(diff)]


# How far this engine's `next_open` sits from the simulator it stands in
# for, at one offset: the simulator's own returns against the control's,
# in basis points a day. Zero on a store whose bar-0 opens are the panel's
# opens; on the real store the SIP first print and the daily open differ.
def simulator_gap(report, mask: np.ndarray, control: Priced, cost_bps: float) -> dict:
    """Return the mean and largest absolute daily gap to `simulate.run`."""
    panel = report.panel
    sim = simulate.run(
        report,
        since=since_offset(panel, control.start),
        allocator=policy_v4.allocator(mask),
        cost_bps=cost_bps,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
    )
    ours = control.returns[control.start :]
    diff = ours - sim.returns
    finite = diff[np.isfinite(diff)]
    return {
        "offset": int(control.start),
        "sessions": int(len(finite)),
        "mean_abs_bp": float(np.abs(finite).mean() * BP) if len(finite) else math.nan,
        "max_abs_bp": float(np.abs(finite).max() * BP) if len(finite) else math.nan,
        "mean_bp": float(finite.mean() * BP) if len(finite) else math.nan,
        "nan_mismatch": int((np.isfinite(ours) != np.isfinite(sim.returns)).sum()),
    }


# Price every convention from every offset, then score them per window.
def study(
    report,
    cubes: dict[str, SessionCube],
    mask: np.ndarray,
    offsets: int = 20,
    cost: float = COST_BPS[0],
) -> dict[str, Any]:
    """Return the trial payload: rows per (convention, window), best, verdict."""
    if offsets < 1:
        raise ValueError("offsets must be at least 1")
    panel = report.panel
    blocked = band_rejecting(panel)
    prices = {c: cube_prices(cubes, panel, c) for c in CONVENTIONS}
    priced: dict[str, list[Priced]] = {c: [] for c in CONVENTIONS}
    for k in range(offsets):
        targets = target_path(report, mask, since_offset(panel, k))
        for c in CONVENTIONS:
            priced[c].append(price_book(targets, report, prices[c], c, cost, blocked))
    median = offsets // 2
    rows: list[dict[str, Any]] = []
    best: dict[str, dict[str, Any]] = {}
    for window, (lo, hi) in WINDOWS.items():
        keep = _window(panel.dates, lo, hi)
        cagrs = {
            c: np.array([_cagr(p.returns[keep]) for p in priced[c]])
            for c in CONVENTIONS
        }
        control = priced[CONTROL][median].returns
        moments: dict[str, candidate_stats.Moments] = {}
        for c in CONVENTIONS:
            at_median = priced[c][median]
            diff = _excess(at_median.returns, control, keep)
            moments[c] = candidate_stats.moments(diff)
            rows.append(
                {
                    "convention": c,
                    "window": window,
                    "cost_bps": cost,
                    "offsets": offsets,
                    "median_cagr": _nanmedian(cagrs[c]),
                    "worst_cagr": float(np.nanmin(cagrs[c]))
                    if np.isfinite(cagrs[c]).any()
                    else math.nan,
                    "best_cagr": float(np.nanmax(cagrs[c]))
                    if np.isfinite(cagrs[c]).any()
                    else math.nan,
                    "median_cagr_vs_open": _nanmedian(cagrs[c] - cagrs[CONTROL]),
                    "offsets_above_open": int(np.nansum(cagrs[c] > cagrs[CONTROL])),
                    "sessions": int(len(diff)),
                    "mean_daily_bp_vs_open": float(diff.mean() * BP)
                    if len(diff)
                    else math.nan,
                    "hac_t_vs_open": candidate_stats.hac_t(diff, HAC_LAG)
                    if len(diff) > 2
                    else math.nan,
                    "fills": int(at_median.fills),
                    "deferrals": int(at_median.deferrals),
                    "fallbacks": int(at_median.fallbacks),
                }
            )
        best[window] = _best(rows, window, moments)
    payload: dict[str, Any] = {
        "policy": policy_v4.POLICY_VERSION,
        "conventions": list(CONVENTIONS),
        "control": CONTROL,
        "cost_bps": cost,
        "offsets": offsets,
        "median_offset": median,
        "windows": {
            k: [str(s) if s else None, str(e) if e else None]
            for k, (s, e) in WINDOWS.items()
        },
        "constants": {
            "DIP": DIP,
            "LATE_SLOTS": list(LATE_SLOTS),
            "FIRST_HOUR_SLOTS": FIRST_HOUR_SLOTS,
            "MAX_DEFERRALS": MAX_DEFERRALS,
            "HAC_LAG": HAC_LAG,
            "TRIALS": TRIALS,
            "ADOPT_BP": ADOPT_BP,
            "ADOPT_T": ADOPT_T,
        },
        "rows": rows,
        "best": best,
        "simulator_gap": simulator_gap(report, mask, priced[CONTROL][median], cost),
        "cube_coverage": {
            "names_with_cube": int(
                sum(1 for t in panel.tickers if t in cubes and len(cubes[t]))
            ),
            "names_in_panel": int(len(panel.tickers)),
        },
        "note": (
            "Orders are the plain simulator's on the point-in-time report; fills "
            "at the convention's SIP price scaled to the panel's adjusted basis; "
            "marks at the panel's adjusted daily close for every convention. VWAPs "
            "are bar closes weighted by bar volume, a proxy. A name without a "
            "complete cube session on its fill day fills at the panel's open and "
            "is counted as a fallback. Costs are one way on every fill."
        ),
    }
    payload.update(verdict(payload))
    return payload


# The convention whose excess over the control is largest on the window,
# with its deflated Sharpe against TRIALS trials from the excess series'
# own moments. The trial variance is the spread of the per-period excess
# Sharpes across the conventions scored; the control's own excess is
# identically zero and has no Sharpe, so it drops out of the spread.
def _best(
    rows: list[dict], window: str, moments: dict[str, candidate_stats.Moments]
) -> dict[str, Any]:
    """Return the window's best convention against the control, deflated."""
    candidates = [
        r
        for r in rows
        if r["window"] == window
        and r["convention"] != CONTROL
        and np.isfinite(r["mean_daily_bp_vs_open"])
    ]
    if not candidates:
        return {"convention": None, "deflated_sharpe": math.nan, "trials": TRIALS}
    top = max(candidates, key=lambda r: r["mean_daily_bp_vs_open"])
    sharpes = np.array([m.sharpe for m in moments.values() if np.isfinite(m.sharpe)])
    variance = float(sharpes.var(ddof=1)) if len(sharpes) > 1 else 0.0
    mom = moments[top["convention"]]
    return {
        "convention": top["convention"],
        "mean_daily_bp_vs_open": top["mean_daily_bp_vs_open"],
        "hac_t_vs_open": top["hac_t_vs_open"],
        "excess_sharpe": mom.sharpe,
        "trial_variance": variance,
        "trials": TRIALS,
        "deflated_sharpe": candidate_stats.deflated_sharpe(
            mom.sharpe, mom.length, mom.skew, mom.kurtosis, TRIALS, variance
        ),
    }


# The plan's kill criteria on the payload's rows, and the separate
# statement about the band gate. Returns the fields `study` merges in.
def verdict(payload: dict[str, Any]) -> dict[str, Any]:
    """Return {"verdict", "adopted", "criteria", "breakout_gate"} for the payload."""
    rows = payload["rows"]

    def row(convention: str, window: str) -> dict | None:
        for r in rows:
            if r["convention"] == convention and r["window"] == window:
                return r
        return None

    adopted: list[str] = []
    criteria: dict[str, dict[str, Any]] = {}
    for c in payload["conventions"]:
        if c == payload.get("control", CONTROL):
            continue
        choose = row(c, CHOOSING) or {}
        report = row(c, REPORTED) or {}
        bp = choose.get("mean_daily_bp_vs_open", math.nan)
        t = choose.get("hac_t_vs_open", math.nan)
        later = report.get("mean_daily_bp_vs_open", math.nan)
        passes_choosing = bool(
            np.isfinite(bp) and np.isfinite(t) and bp >= ADOPT_BP and t >= ADOPT_T
        )
        not_worse = bool(np.isfinite(later) and later >= 0.0)
        criteria[c] = {
            "choosing_bp": bp,
            "choosing_t": t,
            "reported_bp": later,
            "passes_choosing": passes_choosing,
            "not_worse_reported": not_worse,
        }
        if passes_choosing and not_worse:
            adopted.append(c)
    gate = row("breakout_gate", CHOOSING) or {}
    gate_bp = gate.get("mean_daily_bp_vs_open", math.nan)
    gate_t = gate.get("hac_t_vs_open", math.nan)
    if not np.isfinite(gate_bp):
        gate_line = (
            "breakout_gate vs next_open: not measured on the choosing window"
        )
    elif gate_bp < 0:
        gate_line = (
            f"breakout_gate loses to next_open on {CHOOSING} ({gate_bp:+.2f} "
            f"bp/session, t {gate_t:.2f}): the prior holds and the band gate is "
            f"removed from the /4 executor path as a separate, already-measured change"
        )
    else:
        gate_line = (
            f"breakout_gate does not lose to next_open on {CHOOSING} ({gate_bp:+.2f} "
            f"bp/session, t {gate_t:.2f}): the band gate stays until re-tested on "
            f"{REPORTED}"
        )
    if adopted:
        text = (
            f"{ADOPTED}: {', '.join(adopted)} beat next_open by at least "
            f"{ADOPT_BP:g} bp a session with t >= {ADOPT_T:g} on {CHOOSING} and are "
            f"not worse on {REPORTED}"
        )
    else:
        text = (
            f"{RECORDED}: no convention beats next_open by {ADOPT_BP:g} bp a session "
            f"with t >= {ADOPT_T:g} on {CHOOSING} while not worse on {REPORTED}"
        )
    return {
        "verdict": text,
        "adopted": adopted,
        "criteria": criteria,
        "breakout_gate": gate_line,
    }
