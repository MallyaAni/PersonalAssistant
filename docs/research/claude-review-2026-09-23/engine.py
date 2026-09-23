"""Independent next-open backtester for reviewing the AniOS desk sizing layer.

Decisions at close t use data through t only; fills at the adjusted open of t+1.
Costs are charged per side on traded notional. Fractional shares.
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))  # repo root
from backend.agents.trading.desk import allocation as alloc  # GPT's policy code

# Yahoo adjusted daily bars 2015-01-02..2026-09-21 for the book, SPY, QQQ, SMH,
# ^TNX and ^IRX, fetched 2026-09-23 (open/close reconstructed from 1bp log returns).
P = np.load(HERE / "px.npz")
DATES = P["dates"].astype("datetime64[D]")
TICK = [str(t) for t in P["tickers"]]
OPEN = P["open"]
CLOSE = P["close"]
IDX = {t: i for i, t in enumerate(TICK)}
NON_STOCK = {"SPY", "QQQ", "SMH", "^TNX", "^IRX"}
STOCKS = [t for t in TICK if t not in NON_STOCK]

RET = np.vstack([np.full((1, CLOSE.shape[1]), np.nan), CLOSE[1:] / CLOSE[:-1] - 1])


def cagr(nav, days):
    return nav[-1] ** (252 / days) - 1


def stats(nav, name, exposure=None, turnover=None):
    nav = np.asarray(nav)
    r = nav[1:] / nav[:-1] - 1
    dd = 1 - nav / np.maximum.accumulate(nav)
    out = {
        "name": name,
        "CAGR": cagr(nav, len(r)),
        "vol": r.std() * np.sqrt(252),
        "sharpe": r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0,
        "maxDD": dd.max(),
        "total": nav[-1] - 1,
    }
    if exposure is not None:
        out["avg_exp"] = float(np.mean(exposure))
    if turnover is not None:
        out["turn/yr"] = float(turnover) * 252 / len(r)
    return out


def run(target_fn, start, end=None, cost_bps=10.0, min_trade=0.0, recycle=True,
        cash_yield=None, name="", sell_threshold=None):
    """target_fn(t, held_weights) -> dict ticker->weight (decided at close t).

    Executed at OPEN[t+1]. NAV marked at CLOSE. Returns (nav array, info).
    """
    s = int(np.searchsorted(DATES, np.datetime64(start)))
    e = len(DATES) - 1 if end is None else int(np.searchsorted(DATES, np.datetime64(end)))
    shares = np.zeros(len(TICK))
    cash = 1.0
    navs = [1.0]
    exps = []
    turnover = 0.0
    c = cost_bps / 1e4
    for t in range(s, e):
        px_c = np.nan_to_num(CLOSE[t])
        nav_c = cash + shares @ px_c
        held = {TICK[i]: shares[i] * px_c[i] / nav_c for i in np.nonzero(shares)[0]}
        target = target_fn(t, held)
        if target is None:  # hold: no orders this session
            px_c1 = np.where(np.isfinite(CLOSE[t + 1]), CLOSE[t + 1], np.nan_to_num(CLOSE[t]))
            if cash_yield is not None and cash > 0:
                cash *= 1 + max(cash_yield[t + 1], 0) / 252
            nav1 = cash + shares @ np.nan_to_num(px_c1)
            navs.append(nav1)
            exps.append(1 - cash / nav1)
            continue
        # execute at open t+1
        po = OPEN[t + 1].copy()
        # a missing open: carry close (no trade possible in that name)
        po = np.where(np.isfinite(po), po, np.nan_to_num(CLOSE[t]))
        nav_o = cash + shares @ po
        tw = np.zeros(len(TICK))
        for k, w in target.items():
            tw[IDX[k]] = w
        cur = shares * po / nav_o
        diff = tw - cur
        trade_ok = np.isfinite(OPEN[t + 1])
        sell_th = min_trade if sell_threshold is None else sell_threshold
        sells = (diff < -sell_th) & trade_ok & (shares > 0)
        buys = (diff > min_trade) & trade_ok
        # full exits always allowed
        sells |= (tw == 0) & (shares > 0) & trade_ok
        sell_val = -diff[sells] * nav_o
        dq = np.zeros(len(TICK))
        dq[sells] = diff[sells] * nav_o / po[sells]
        proceeds = sell_val.sum() * (1 - c)
        avail = cash + (proceeds if recycle else 0.0)
        buy_val = diff[buys] * nav_o
        need = buy_val.sum() * (1 + c)
        scale = 1.0 if need <= avail + 1e-12 else max(0.0, avail / need)
        dq[buys] = buy_val * scale / po[buys]
        cash = cash + proceeds - buy_val.sum() * scale * (1 + c)
        shares = np.maximum(shares + dq, 0)
        turnover += (sell_val.sum() + buy_val.sum() * scale) / nav_o
        if cash_yield is not None:
            cash *= 1 + max(cash_yield[t + 1], 0) / 252 if cash > 0 else 1
        px_c1 = np.where(np.isfinite(CLOSE[t + 1]), CLOSE[t + 1], po)
        nav1 = cash + shares @ np.nan_to_num(px_c1)
        navs.append(nav1)
        exps.append(1 - cash / nav1)
    nav = np.array(navs)
    return nav, stats(nav, name, exps, turnover)


def buy_hold(ticker, start, end=None, cost_bps=10.0):
    return run(lambda t, h: {ticker: 1.0}, start, end, cost_bps=cost_bps, name=f"{ticker} buy&hold")


# ---------- price-only proxy of the desk's selection + incumbent sizing ----------

def trailing_vol(t, cols, n=60):
    r = RET[t - n + 1: t + 1][:, cols]
    return np.nanstd(r, axis=0) * np.sqrt(252)


def momentum_scores(t):
    """Price-only proxy for the technical analyst: 120d momentum (skip 5),
    above 200d mean, and 60d range position. Rank-averaged. NaN when history < 252."""
    cols = [IDX[s] for s in STOCKS]
    c = CLOSE[: t + 1][:, cols]
    ok = np.isfinite(c[-252:]).all(axis=0)
    mom = c[-6] / c[-126] - 1
    above = (c[-1] > np.nanmean(c[-200:], axis=0)).astype(float)
    hi = np.nanmax(c[-60:], axis=0)
    lo = np.nanmin(c[-60:], axis=0)
    rng = (c[-1] - lo) / np.maximum(hi - lo, 1e-9)

    def rk(x):
        x = np.where(ok, x, np.nan)
        order = np.argsort(np.argsort(np.where(np.isfinite(x), x, -np.inf)))
        return np.where(ok, order / max(ok.sum() - 1, 1), np.nan)

    score = (rk(mom) + rk(rng)) / 2 + 0.5 * above
    return dict(zip(STOCKS, np.where(ok, score, np.nan)))


def incumbent_weights(t, top_frac=0.10, name_cap=0.15, vol_target=0.30, min_names=5):
    """Mirrors risk.desk_targets: top decile, inverse-vol (10% floor), 15% cap,
    scale book to 30% trailing vol, gross <= 1."""
    sc = momentum_scores(t)
    live = {k: v for k, v in sc.items() if np.isfinite(v)}
    if not live:
        return {}
    k = max(min_names, int(round(len(live) * top_frac)))
    pick = sorted(live, key=lambda n: -live[n])[:k]
    cols = [IDX[n] for n in pick]
    v = np.maximum(trailing_vol(t, cols), 0.10)
    w = (1 / v) / (1 / v).sum()
    for _ in range(10):
        w = np.minimum(w, name_cap)
        w = w / w.sum() if w.sum() > 1 else w
    joint = RET[t - 59: t + 1][:, cols] @ w
    pv = np.nanstd(joint) * np.sqrt(252)
    scale = min(1.0, vol_target / pv) if pv > 0 else 1.0
    w = np.minimum(w * scale, name_cap)
    return dict(zip(pick, w))


class Hold20:
    """Refresh the composition every `every` sessions; hold weights otherwise
    (let winners run) — the incumbent cadence."""

    def __init__(self, every=20, fn=incumbent_weights):
        self.every, self.fn, self.last, self.n = every, fn, None, 0

    def __call__(self, t, held):
        if self.last is None or self.n % self.every == 0:
            self.last = self.fn(t)
            self.n += 1
            return self.last
        self.n += 1
        return None


def policy_wrapper(policy, every=20, index_eligible=False, fn=incumbent_weights, daily=True):
    """GPT's funded path: composition refreshed every `every` sessions, then
    allocation.decide() applied every session and traded daily."""
    state = {"comp": None, "n": 0}
    dates = DATES
    prices = np.where(np.isfinite(CLOSE), CLOSE, np.nan)

    def f(t, held):
        if state["comp"] is None or state["n"] % every == 0:
            state["comp"] = fn(t)
        state["n"] += 1
        desired = {k: v for k, v in state["comp"].items() if v > 0}
        h = {k: v for k, v in held.items() if k in IDX and v > 0}
        tot = sum(h.values())
        if tot > 1:
            h = {k: v / tot for k, v in h.items()}
        d = alloc.decide(dates[: t + 1], prices[: t + 1], TICK, t, desired, h,
                         regime_cap=1.0, event_cap=1.0, policy=policy,
                         index_eligible=index_eligible)
        return d.desired_weights
    return f


def fixed_daily_reset(every=20, fn=incumbent_weights):
    """Composition refreshed every `every` sessions, weights reset daily, no vol budget."""
    state = {"comp": None, "n": 0}

    def f(t, held):
        if state["comp"] is None or state["n"] % every == 0:
            state["comp"] = fn(t)
        state["n"] += 1
        return state["comp"]
    return f


def ann_vol(series, t):
    s = series[t - 59: t + 1]
    s20 = series[t - 19: t + 1]
    return max(np.nanstd(s), np.nanstd(s20)) * np.sqrt(252)


class Book:
    """Hold-20 book with optional overlays.

    deferred: on sessions after a trade, deploy idle cash into under-target names
              (buys only) — fixes the cash that sells-at-close leaves idle.
    overlay:  None | 'trend_hyst' | 'vol_qqq'  — exposure scalar; trades only when
              the scalar moves by > 10% of book (hysteresis), never daily nudges.
    """

    def __init__(self, every=20, fn=incumbent_weights, deferred=False, overlay=None):
        self.every, self.fn, self.deferred, self.overlay = every, fn, deferred, overlay
        self.comp, self.n, self.scale, self.pending = None, 0, 1.0, False
        self.risk_off = False

    def _scalar(self, t):
        if self.overlay is None:
            return 1.0
        if self.overlay == "trend_hyst":
            q = CLOSE[: t + 1, IDX["QQQ"]]
            ma = np.mean(q[-200:])
            if self.risk_off and q[-1] > ma * 1.02:
                self.risk_off = False
            elif not self.risk_off and q[-1] < ma * 0.97:
                self.risk_off = True
            return 0.5 if self.risk_off else 1.0
        if self.overlay == "vol_qqq":
            cols = [IDX[k] for k in self.comp]
            w = np.array(list(self.comp.values()))
            if not len(w):
                return 1.0
            pv = ann_vol(RET[:, cols] @ w, t)
            qv = ann_vol(RET[:, IDX["QQQ"]], t)
            return min(1.0, 1.25 * qv / pv) if pv > 0 else 1.0
        raise ValueError(self.overlay)

    def __call__(self, t, held):
        rebalance = self.comp is None or self.n % self.every == 0
        self.n += 1
        if rebalance:
            self.comp = self.fn(t)
        s = self._scalar(t)
        moved = abs(s - self.scale) > 0.10 or (s == 1.0 and self.scale < 1.0 and abs(s - self.scale) > 1e-9)
        if rebalance or moved:
            self.scale = s
            self.pending = True
            return {k: v * s for k, v in self.comp.items()}
        if self.deferred and self.pending:
            self.pending = False
            tgt = {k: v * self.scale for k, v in self.comp.items()}
            # buys only: never trim what is held
            return {k: max(tgt.get(k, 0.0), held.get(k, 0.0)) for k in set(tgt) | set(held)}
        return None
