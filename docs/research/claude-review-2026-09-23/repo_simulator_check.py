"""Run the repo's own simulator (live policy) on real Yahoo bars with proxy analyst
scores, to verify the deferred buy leg and the trend brake in the actual code."""
import sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))  # repo root
import numpy as np
from backend.market.panel import Panel
from backend.market.universe import build_universe, book_sides, theme_map
from backend.agents.trading.desk import desk, regime, technical, simulate, event_risk, paper
from backend.agents.trading.desk.opinions import Opinion

P = np.load(HERE / "px.npz")
dates = P["dates"].astype("datetime64[D]"); tick=[str(t) for t in P["tickers"]]
O, C = P["open"], P["close"]
u = build_universe(); sides_all = book_sides(u); themes = theme_map(u)
book = [t for t in tick if t in sides_all] + ["SPY"]
cols = [tick.index(t) for t in book]
start = int(np.searchsorted(dates, np.datetime64("2015-01-02")))
o, c = O[start:, cols], C[start:, cols]
hi, lo = np.maximum(o, c), np.minimum(o, c)
vol = np.where(np.isfinite(c), 1e6, np.nan)
panel = Panel(dates[start:], tuple(book), o, hi, lo, c, c, vol, {t: tuple(themes.get(t, ())) for t in book}, "SPY")
sides = {t: sides_all[t] for t in book if t in sides_all}
view = regime.opine(panel, sides, regime.tightening_from(None))
# proxy scores: 6-month momentum (skip 1 month) as "fundamental", 1-month as "sentiment"
def mom(n, skip):
    out = np.full(c.shape, np.nan)
    out[n:] = c[n-skip:len(c)-skip] / c[:len(c)-n] - 1 if skip else c[n:] / c[:-n] - 1
    return out
ops = {"fundamental": Opinion("fundamental", mom(126, 21)), "technical": technical.opine(panel, view.ai_trend),
       "sentiment": Opinion("sentiment", mom(21, 0)), "value": Opinion("value", np.full(c.shape, np.nan))}
rep = desk.assemble(panel, sides, ops, view)
g = rep.graded.grades
print("grade share A+/A/B/C over sample:", [round(float((g == k).mean()), 3) for k in range(4)])
qqq = C[start:, tick.index("QQQ")]; spy = C[start:, tick.index("SPY")]
bench = {"dates": panel.dates, "SPY": spy, "QQQ": qqq}
since = np.datetime64("2016-01-04")
def show(label, sim):
    eq = sim.equity; r = np.diff(eq) / eq[:-1]
    n = len(r); cagr = eq[-1] ** (252 / n) - 1
    dd = (1 - eq / np.maximum.accumulate(eq)).max()
    print(f"{label:55s} CAGR {cagr:6.1%}  maxDD {dd:5.1%}  sharpe {r.mean()/r.std()*np.sqrt(252):4.2f}  avg_inv {np.nanmean(sim.invested):.2f}")
common = dict(use_exits=False, rebalance=paper.REBALANCE_EVERY, event_exposure=event_risk.live_path(panel), event_lifecycle=True, since=since)
lp = dict(simulate.LIVE_POLICY)
t0 = time.time()
show("live policy, deferred_buys OFF (old live)", simulate.run(rep, **common, **{**lp, "deferred_buys": False}))
show("live policy, deferred_buys ON (branch)", simulate.run(rep, **common, **lp))
show("live policy + trend brake (branch)", simulate.run(rep, **common, **lp, trend_brake=True, benchmark_prices=bench))
print("elapsed", round(time.time() - t0))
