# The T-S1 book gate for the A1 text-surprise candidates, paired against a
# control run on the same tree and store. Reuses the paired-difference and
# offset helpers of research/vol-target (backend.market.vol_target; run with
# PYTHONPATH=~/scratch/wt-vt). Read-only; prints one block per arm.
# Gate (text-surprise-plan-2026-10-01.md): +2 bp of equity a session at 25 bp,
# NW t >= 2 (lag 20) on the model window 2016-2023, not negative after
# (2024-2026 mean >= 0), above the control at >= 15 of 20 offsets, deflated
# Sharpe at the cumulative 471 >= 0.95 (trial variance: across the candidates'
# paired Sharpes on the model window).
import json
import math
import sys
from pathlib import Path

import numpy as np

from backend.market import candidate_stats, vol_target as vt

control = json.loads(Path(sys.argv[1]).read_text())
cands = {Path(p).stem: json.loads(Path(p).read_text()) for p in sys.argv[2:]}
TRIALS = 471
pairs = {k: {w: vt.paired(c, control, w) for w in vt.WINDOWS} for k, c in cands.items()}
sh = [p[vt.DECIDING]["sharpe"] for p in pairs.values() if math.isfinite(p[vt.DECIDING]["sharpe"])]
var = float(np.var(sh, ddof=1)) if len(sh) >= 2 else math.nan
print(f"T-S1 gate, A1 candidates against {control.get('arm')} as of {control.get('asof')}, 25 bp, trials {TRIALS}, trial variance {var:.3g}")
for k, c in cands.items():
    d, r = pairs[k][vt.DECIDING], pairs[k][vt.RECENT]
    above, n = vt.offsets_above(c, control, vt.DECIDING)
    dsr = math.nan
    if math.isfinite(var) and var > 0:
        dsr = candidate_stats.deflated_sharpe(d["sharpe"], d["length"], d["skew"], d["kurtosis"], TRIALS, var)
    tests = {
        "+2 bp at t>=2 (2016-2023)": d["mean_daily_bp"] >= 2.0 and d["hac_t"] >= 2.0,
        "not negative 2024-2026": r["mean_daily_bp"] >= 0.0,
        ">= 15 of 20 offsets": above >= 15,
        "DSR >= 0.95": math.isfinite(dsr) and dsr >= 0.95,
    }
    print(f"{k} ({c.get('arm')}): paired 2016-2023 {d['mean_daily_bp']:+.2f} bp/session (t {d['hac_t']:+.2f}, {d['sessions']} sessions); "
          f"2024-2026 {r['mean_daily_bp']:+.2f} (t {r['hac_t']:+.2f}, {r['sessions']}); above the control at {above} of {n}; DSR {dsr:.2f} at {TRIALS}")
    for w in vt.WINDOWS:
        v = vt.window_reading(c, control, w)
        print(f"  {w}: CAGR {v['cagr']*100:+.1f}% vs {v['cagr_control']*100:+.1f}%; worst drawdown {v['drawdown']*100:+.1f}% vs {v['drawdown_control']*100:+.1f}%; Sharpe {v['sharpe']:.2f} vs {v['sharpe_control']:.2f}")
    failed = [t for t, ok in tests.items() if not ok]
    print("  GATE HOLDS (proposed as the tone replacement; operator decides)" if not failed else f"  GATE FAILS ({'; '.join(failed)}) -> RECORD")
