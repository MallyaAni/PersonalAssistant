"""Price the /4 candidate under the live execution policy in the simulator, beside plain."""
import json, math
from datetime import date
from pathlib import Path
import numpy as np
from backend.agents.trading.desk import desk, point_in_time, policy_v4, simulate, event_risk
from backend.agents.trading.desk import paper
from backend.market.store import MarketStore
from backend.cli import market_pit_scorecard as sc

store = MarketStore(Path("/home/animallya96/deploy/anios/data/market"))
report = desk.run(store, None, inputs=(desk.EXPECTATIONS_GAP,))
restricted, mask = point_in_time.point_in_time(report)
panel = report.panel
live = sc._live_options(panel)
plain = dict(use_exits=False, rebalance=paper.REBALANCE_EVERY)
WINDOWS = {"2016-2023": (date(2016,1,1), date(2024,1,1)), "2024-2026": (date(2024,1,1), None)}

def cagr(sim, start, end):
    d = np.asarray(sim.dates, dtype="datetime64[D]"); r = np.asarray(sim.returns, dtype=float)
    w = np.ones(len(d), bool)
    if start: w &= d >= np.datetime64(start)
    if end: w &= d < np.datetime64(end)
    r = r[w]
    if len(r) < 50: return float("nan")
    g = float(np.prod(1 + r)); return g ** (252 / len(r)) - 1

rows = []
for cost in (10.0, 25.0):
    for k in (0, 5, 10, 15):
        since = sc._since(panel, k)
        runs = {
            "rule /3 live": simulate.run(restricted, since=since, cost_bps=cost, **live),
            "/4 plain": simulate.run(restricted, since=since, cost_bps=cost, allocator=policy_v4.allocator(mask), **plain),
        }
        try:
            runs["/4 live policy"] = simulate.run(restricted, since=since, cost_bps=cost, allocator=policy_v4.allocator(mask), **live)
        except Exception as exc:
            runs["/4 live policy"] = exc
        for name, sim in runs.items():
            if isinstance(sim, Exception):
                rows.append((cost, k, name, "REFUSED: " + str(sim)[:120])); continue
            rows.append((cost, k, name, {w: cagr(sim, *b) for w, b in WINDOWS.items()}))
for r in rows: print(r)
print("--- medians over offsets")
for cost in (10.0, 25.0):
    for name in ("rule /3 live", "/4 plain", "/4 live policy"):
        vals = [r[3] for r in rows if r[0]==cost and r[2]==name and isinstance(r[3], dict)]
        if vals:
            print(cost, name, {w: round(float(np.median([v[w] for v in vals]))*100,1) for w in WINDOWS})
