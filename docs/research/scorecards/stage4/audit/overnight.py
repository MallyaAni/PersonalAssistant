# Descriptive diagnostic for the operator's question "has most of the move
# already happened by the first 15 minutes?" (not a trial; nothing is chosen
# from it). On the live executor's own orders (stage 4's, offset 10 of 20),
# where does each order's price move happen: overnight (the decision close
# to the next open), in the first 15-minute bar, by the board's fill, and
# over the next four sessions. Signed so that a positive number is a move
# against the order (a buy's price rising, a sell's falling), in bp.
import json
import math
import sys
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.cli import market_stage4_decisions as cli
from backend.cli.market_pit_scorecard import _since
from backend.market import stage3_export
from backend.market import stage4_decisions as sd
from backend.market import stage4_labels as lab
from backend.market import stage4_orders as so
from backend.market.store import MarketStore

ROOT = Path.home() / "deploy/anios/data/market"
report, cubes, records = cli.load_inputs(MarketStore(ROOT), 8, print)
restricted, mask = point_in_time.point_in_time(report, cli.universe.MEMBERSHIP_HISTORY_PATH)
panel = restricted.panel
dates = np.asarray(panel.dates, dtype="datetime64[D]")
fills, _, _, _ = sd.fill_grids(panel, cubes)
earn = stage3_export.earnings_days(panel, records)
BASIS = sys.argv[2] if len(sys.argv) > 2 else so.EXECUTED
run = so.run_control(restricted, mask, _since(panel, 10), basis=BASIS)
print("basis", BASIS)
orders = run.orders
T, N = len(dates), len(panel.tickers)

# Per name: cube rows, the session scale, the first bar's open and close.
first_open = np.full((T, N), np.nan)
first_close = np.full((T, N), np.nan)
for j, ticker in enumerate(panel.tickers):
    cube = cubes.get(ticker)
    if cube is None or not len(cube):
        continue
    series = lab.name_series(dates, panel.close[:, j], panel.adj_close[:, j], panel.high[:, j], panel.low[:, j])
    rows = lab.cube_rows(dates, cube)
    scale = lab.cube_scale(series, cube)
    ok = rows >= 0
    first_open[ok, j] = cube.open[rows[ok], 0] * scale[ok]
    first_close[ok, j] = cube.close[rows[ok], 0] * scale[ok]
closes = np.asarray(panel.adj_close, dtype=float)

out = {}
for window, (lo, hi) in {"2018-2023": ("2018-01-01", "2024-01-01"), "2024-2026": ("2024-01-01", None)}.items():
    inside = (dates[orders.session] >= np.datetime64(lo)) & ((dates[orders.session] < np.datetime64(hi)) if hi else True)
    for side in ("buy", "sell"):
        k = np.flatnonzero(inside & (orders.side == side))
        t, j = orders.session[k], orders.column[k]
        ok = (t + 5 < T)
        k, t, j = k[ok], t[ok], j[ok]
        s = 1.0 if side == "buy" else -1.0
        c0 = closes[t, j]
        o1 = first_open[t + 1, j]
        b1 = first_close[t + 1, j]
        ctrl = fills.price[(lab.CONTROL, side)][t, j]
        c1 = closes[t + 1, j]
        c5 = closes[t + 5, j]
        good = np.isfinite(c0) & np.isfinite(o1) & np.isfinite(b1) & np.isfinite(ctrl) & np.isfinite(c5)
        w = orders.weight[k][good]
        with np.errstate(all="ignore"):
            parts = {
                "overnight (close t -> open t+1)": s * 1e4 * np.log(o1 / c0)[good],
                "first 15 minutes (open -> 09:45 close)": s * 1e4 * np.log(b1 / o1)[good],
                "decision close -> board's fill": s * 1e4 * np.log(ctrl / c0)[good],
                "board's fill -> close t+5": s * 1e4 * np.log(c5 / ctrl)[good],
                "decision close -> close t+5": s * 1e4 * np.log(c5 / c0)[good],
            }
        # Earnings released between the decision close and the next open.
        after = earn[np.minimum(t + 1, T - 1), j][good]
        detail = orders.detail[k][good]
        rec = {"orders": int(good.sum())}
        for name, v in parts.items():
            se = v.std(ddof=1) / math.sqrt(len(v)) if len(v) > 1 else float("nan")
            rec[name] = {
                "mean_bp": float(v.mean()),
                "t_naive": float(v.mean() / se) if se > 0 else float("nan"),
                "median_bp": float(np.median(v)),
                "weighted_mean_bp": float((w * v).sum() / w.sum()),
                "share_against": float((v > 0).mean()),
            }
        by = {}
        for label in sorted(set(detail.tolist())):
            m = detail == label
            by[label] = {
                "orders": int(m.sum()),
                "overnight_mean_bp": float(parts["overnight (close t -> open t+1)"][m].mean()),
                "close_to_fill_mean_bp": float(parts["decision close -> board's fill"][m].mean()),
                "fill_to_t5_mean_bp": float(parts["board's fill -> close t+5"][m].mean()),
            }
        rec["by_detail"] = by
        rec["earnings_after_close"] = {
            "orders": int(after.sum()),
            "overnight_mean_bp": float(parts["overnight (close t -> open t+1)"][after].mean()) if after.any() else None,
            "overnight_mean_bp_without": float(parts["overnight (close t -> open t+1)"][~after].mean()),
        }
        out[f"{window} {side}"] = rec

json.dump(out, open(sys.argv[1], "w"), indent=1)
for key, rec in out.items():
    print(f"== {key}: {rec['orders']} orders")
    for name, r in rec.items():
        if isinstance(r, dict) and "mean_bp" in r:
            print(f"  {name:<42} mean {r['mean_bp']:+7.1f} bp (naive t {r['t_naive']:+.2f}), median {r['median_bp']:+7.1f}, weighted {r['weighted_mean_bp']:+7.1f}, against the order {100 * r['share_against']:.0f}%")
    for label, r in rec["by_detail"].items():
        print(f"  {label:<16} n{r['orders']:<5} overnight {r['overnight_mean_bp']:+7.1f}  close->fill {r['close_to_fill_mean_bp']:+7.1f}  fill->t+5 {r['fill_to_t5_mean_bp']:+7.1f}")
    e = rec["earnings_after_close"]
    print(f"  earnings between the close and the open: {e['orders']} orders, overnight {e['overnight_mean_bp']}; others {e['overnight_mean_bp_without']:+.1f}")
